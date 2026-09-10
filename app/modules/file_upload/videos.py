"""Bounded MP4 processing and public capability URLs for email recipients."""

import io
import json
import math
import re
import subprocess
import tempfile
from asyncio import Semaphore, to_thread
from pathlib import Path
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from fastapi import HTTPException
from PIL import Image, ImageDraw
from starlette.responses import Response, StreamingResponse

from app.core.exceptions import AppError, NotFoundError
from app.modules.file_upload.images import EmailImageService

MAX_VIDEO_BYTES = 20 * 1024 * 1024
MAX_VIDEO_SECONDS = 60
VIDEO_NAME = re.compile(r"[a-f0-9]{32}\.mp4")
processing_slots = Semaphore(2)


def run_media(args: list[str], timeout: int = 10) -> bytes:
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout
    except FileNotFoundError as exc:
        raise AppError("Обработка видео временно недоступна: на сервере требуется FFmpeg.") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AppError(
            "Не удалось обработать MP4. Проверьте файл или загрузите видео меньшего размера."
        ) from exc


def normalize_video(body: bytes) -> tuple[bytes, bytes, float]:
    if not body or len(body) > MAX_VIDEO_BYTES:
        raise AppError("Максимальный размер MP4 — 20 МБ.")
    if (
        len(body) < 16
        or body[4:8] != b"ftyp"
        or body[8:12]
        not in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"iso5", b"iso6", b"M4V "}
    ):
        raise AppError("Выберите настоящий видеофайл MP4.")
    with tempfile.TemporaryDirectory(prefix="mailer-video-") as folder:
        source, output = Path(folder) / "input.mp4", Path(folder) / "output.mp4"
        source.write_bytes(body)
        # The MOV demuxer cannot follow external references or network protocols.
        input_args = [
            "-protocol_whitelist",
            "file",
            "-f",
            "mov",
            "-enable_drefs",
            "0",
            "-use_absolute_path",
            "0",
        ]
        raw = run_media(
            [
                "ffprobe",
                "-v",
                "error",
                *input_args,
                "-show_entries",
                "format=duration:stream=codec_type,width,height,duration",
                "-of",
                "json",
                str(source),
            ]
        )
        try:
            metadata = json.loads(raw)
            duration = float(metadata["format"]["duration"])
            videos = [s for s in metadata["streams"] if s["codec_type"] == "video"]
            if not videos or not math.isfinite(duration) or duration <= 0:
                raise ValueError("No valid video track")
            if duration > MAX_VIDEO_SECONDS or any(
                float(s.get("duration", duration)) > MAX_VIDEO_SECONDS for s in videos
            ):
                raise AppError("Видео должно быть не длиннее 60 секунд.")
            if any(
                not 2 <= s["width"] <= 4096
                or not 2 <= s["height"] <= 4096
                or s["width"] * s["height"] > 8_847_360
                for s in videos
            ):
                raise AppError("Максимальное разрешение видео — 4K.")
        except (ValueError, KeyError, TypeError) as exc:
            raise AppError("Не удалось определить длительность и параметры MP4.") from exc
        run_media(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-threads",
                "2",
                *input_args,
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-vf",
                "scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "26",
                "-threads",
                "2",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-t",
                "60",
                "-movflags",
                "+faststart",
                str(output),
            ],
            timeout=40,
        )
        if output.stat().st_size > MAX_VIDEO_BYTES:
            raise AppError("После обработки видео превышает 20 МБ. Загрузите более короткий ролик.")
        frame = run_media(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ]
        )
        with Image.open(io.BytesIO(frame)) as image:
            poster = image.convert("RGB")
            draw = ImageDraw.Draw(poster)
            x, y, r = poster.width / 2, poster.height / 2, min(poster.size) * 0.18
            draw.ellipse((x - r, y - r, x + r, y + r), fill="#142019", outline="white", width=2)
            draw.polygon(
                [(x - r * 0.3, y - r * 0.5), (x - r * 0.3, y + r * 0.5), (x + r * 0.5, y)],
                fill="white",
            )
            buffer = io.BytesIO()
            poster.save(buffer, format="PNG")
        return output.read_bytes(), buffer.getvalue(), duration


def byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip()) if len(value) <= 128 else None
    if not match or not any(match.groups()):
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    start = int(first) if first else max(0, size - int(last))
    end = min(int(last), size - 1) if first and last else size - 1
    if start >= size or start > end:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    return start, end


class EmailVideoService(EmailImageService):
    async def upload(self, body: bytes, workspace_id: UUID) -> dict[str, object]:
        if processing_slots.locked():
            raise AppError("Сервер обрабатывает другие видео. Повторите загрузку немного позже.")
        async with processing_slots:
            content, poster, duration = await to_thread(normalize_video, body)
        token = uuid4().hex
        video_key, poster_key = f"email-videos/{token}.mp4", f"email-images/{token}.png"
        try:
            for key, data, mime in [
                (video_key, content, "video/mp4"),
                (poster_key, poster, "image/png"),
            ]:
                await to_thread(
                    self.s3.put_object,
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType=mime,
                    Metadata={"workspace-id": str(workspace_id)},
                )
        except Exception:
            # Roll back only the two new keys belonging to this upload.
            for key in (video_key, poster_key):
                await to_thread(self.s3.delete_object, Bucket=self.bucket, Key=key)
            raise
        return {
            "url": f"{self.public_base}/api/v1/files/videos/{token}.mp4",
            "poster_url": f"{self.public_base}/api/v1/files/images/{token}.png",
            "duration": duration,
        }

    def response(self, filename: str, range_header: str | None, head: bool = False) -> Response:
        if not VIDEO_NAME.fullmatch(filename):
            raise NotFoundError("Видео не найдено")
        key = f"email-videos/{filename}"
        try:
            size = self.s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
            selection = byte_range(range_header, size)
            headers = {
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=31536000, immutable",
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
                "Content-Length": str(size),
            }
            options = {}
            if selection:
                start, end = selection
                headers.update(
                    {
                        "Content-Range": f"bytes {start}-{end}/{size}",
                        "Content-Length": str(end - start + 1),
                    }
                )
                options["Range"] = f"bytes={start}-{end}"
            status = 206 if selection else 200
            if head:
                return Response(media_type="video/mp4", status_code=status, headers=headers)
            stream = self.s3.get_object(Bucket=self.bucket, Key=key, **options)["Body"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404", "NotFound"}:
                raise NotFoundError("Видео не найдено") from exc
            raise

        def chunks():
            try:
                while chunk := stream.read(64 * 1024):
                    yield chunk
            finally:
                stream.close()

        return StreamingResponse(
            chunks(), media_type="video/mp4", status_code=status, headers=headers
        )
