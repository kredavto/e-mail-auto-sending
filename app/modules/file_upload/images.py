"""Email-only image storage. Contact imports remain private."""

import io
import re
from asyncio import to_thread
from uuid import UUID, uuid4

import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings
from app.core.exceptions import AppError, NotFoundError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_NAME = re.compile(r"[a-f0-9]{32}\.png")


def normalize_image(body: bytes) -> tuple[bytes, int, int]:
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise AppError("Выберите изображение размером до 5 МБ.")
    try:
        with Image.open(io.BytesIO(body)) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"}:
                raise AppError("Поддерживаются только JPEG, PNG и WebP.")
            if original.width * original.height > MAX_IMAGE_PIXELS:
                raise AppError("Изображение слишком большое: максимум 20 мегапикселей.")
            if getattr(original, "is_animated", False):
                raise AppError("Выберите статичное изображение, без анимации.")
            original.load()
            normalized = ImageOps.exif_transpose(original).convert("RGBA")
            normalized.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            # A fresh image strips EXIF, GPS, comments and other uploaded metadata.
            clean = Image.new("RGBA", normalized.size)
            clean.paste(normalized)
            output = io.BytesIO()
            clean.save(output, format="PNG")
            return output.getvalue(), clean.width, clean.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AppError("Файл повреждён или не является поддерживаемым изображением.") from exc


class EmailImageService:
    def __init__(self) -> None:
        settings = get_settings()
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        self.bucket = settings.s3_bucket
        self.public_base = settings.public_base_url.rstrip("/")

    async def upload(self, body: bytes, workspace_id: UUID) -> dict[str, object]:
        content, width, height = await to_thread(normalize_image, body)
        filename = f"{uuid4().hex}.png"
        await to_thread(
            self.s3.put_object,
            Bucket=self.bucket,
            Key=f"email-images/{filename}",
            Body=content,
            ContentType="image/png",
            Metadata={"workspace-id": str(workspace_id)},
        )
        return {
            "url": f"{self.public_base}/api/v1/files/images/{filename}",
            "width": width,
            "height": height,
        }

    def download(self, filename: str) -> bytes:
        if not IMAGE_NAME.fullmatch(filename):
            raise NotFoundError("Изображение не найдено")
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=f"email-images/{filename}")
            stream = response["Body"]
            try:
                return stream.read()
            finally:
                stream.close()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                raise NotFoundError("Изображение не найдено") from exc
            raise
