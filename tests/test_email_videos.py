import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.core.dependencies import get_tenant_context
from app.core.exceptions import AppError, NotFoundError, install_exception_handlers
from app.modules.editor.service import EditorService
from app.modules.file_upload.router import router
from app.modules.file_upload.videos import (
    MAX_VIDEO_BYTES,
    EmailVideoService,
    byte_range,
    normalize_video,
)

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 30


@pytest.fixture
def media(monkeypatch):
    info = {
        "format": {"duration": "12"},
        "streams": [{"codec_type": "video", "width": 1280, "height": 720}],
    }
    image = io.BytesIO()
    Image.new("RGB", (480, 270), "green").save(image, format="PNG")

    def run(args, timeout=10):
        assert timeout <= 40
        if args[0] == "ffprobe":
            assert "file" in args and "-enable_drefs" in args
            return json.dumps(info).encode()
        if args[-1] == "pipe:1":
            return image.getvalue()
        assert "libx264" in args and "+faststart" in args
        Path(args[-1]).write_bytes(M4P_RESULT)
        return b""

    monkeypatch.setattr("app.modules.file_upload.videos.run_media", run)
    return info


M4P_RESULT = MP4 + b"encoded"


def test_video_processing(media):
    content, poster, duration = normalize_video(MP4)
    assert content == M4P_RESULT and duration == 12
    assert Image.open(io.BytesIO(poster)).size == (480, 270)


@pytest.mark.parametrize(
    "data",
    [b"", b"not-mp4", b"x" * (MAX_VIDEO_BYTES + 1)],
    ids=["empty", "wrong-format", "oversize"],
)
def test_invalid_video(data):
    with pytest.raises(AppError):
        normalize_video(data)


@pytest.mark.parametrize("duration", ["61", "0", "nan", "oops"])
def test_invalid_duration(media, duration):
    media["format"]["duration"] = duration
    with pytest.raises(AppError):
        normalize_video(MP4)


def test_audio_only_rejected(media):
    media["streams"] = [{"codec_type": "audio"}]
    with pytest.raises(AppError):
        normalize_video(MP4)


def test_oversized_dimensions(media):
    media["streams"][0]["width"] = 9000
    with pytest.raises(AppError):
        normalize_video(MP4)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("bytes=0-1", (0, 1)),
        ("bytes=5-", (5, 9)),
        ("bytes=-3", (7, 9)),
        ("bytes=1-90", (1, 9)),
    ],
)
def test_valid_ranges(value, expected):
    assert byte_range(value, 10) == expected


@pytest.mark.parametrize(
    "value",
    ["bytes=-", "bytes=-0", "bytes=20-", "bytes=9-2", "bytes=1-2,4-5", "bytes=" + "9" * 200 + "-"],
)
def test_invalid_ranges(value):
    with pytest.raises(HTTPException) as error:
        byte_range(value, 10)
    assert error.value.status_code == 416


def test_upload_public_playback_and_compilation(monkeypatch, media):
    objects = {}
    s3 = Mock()
    s3.put_object.side_effect = lambda **kw: objects.update({kw["Key"]: kw["Body"]})
    s3.head_object.side_effect = lambda **kw: {"ContentLength": len(objects[kw["Key"]])}

    def get(**kw):
        data = objects[kw["Key"]]
        if "Range" in kw:
            start, end = byte_range(kw["Range"], len(data))
            data = data[start : end + 1]
        return {"Body": io.BytesIO(data)}

    s3.get_object.side_effect = get
    monkeypatch.setattr("app.modules.file_upload.images.boto3.client", lambda *a, **kw: s3)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    install_exception_handlers(app)
    with TestClient(app) as client:
        assert (
            client.post("/api/v1/files/videos", files={"file": ("test.mp4", MP4)}).status_code
            == 401
        )
        app.dependency_overrides[get_tenant_context] = lambda: SimpleNamespace(workspace_id=uuid4())
        result = client.post("/api/v1/files/videos", files={"file": ("test.mp4", MP4)})
        assert result.status_code == 201
        video = result.json()
        app.dependency_overrides.clear()
        path = video["url"].removeprefix(get_settings().public_base_url.rstrip("/"))
        response = client.get(path, headers={"Range": "bytes=0-1"})
        assert response.status_code == 206 and response.content == M4P_RESULT[:2]
        assert response.headers["content-type"] == "video/mp4"
        assert response.headers["content-range"].startswith("bytes 0-1/")
        assert client.get(path).content == M4P_RESULT
        assert client.head(path).content == b""
        assert client.get(path, headers={"Range": "bytes=99999-"}).status_code == 416
        state = {
            "content": [
                {
                    "type": "emailVideo",
                    "attrs": {
                        "src": video["url"],
                        "poster": video["poster_url"],
                        "alt": "Обзор {{7*7}} <script>",
                    },
                }
            ]
        }
        html, text, *_ = EditorService().compile(state)
        assert video["url"] in html and video["url"] in text
        assert video["poster_url"] in html and "width:25%" in html
        assert "<video" not in html and 'target="_blank"' in html
        assert "{{7*7}}" not in EditorService().preview(state, {})
        state["content"][0]["attrs"]["poster"] = "https://evil.example/poster.png"
        with pytest.raises(AppError):
            EditorService().compile(state)
        with pytest.raises(NotFoundError):
            EmailVideoService().response("private.csv", None)


@pytest.mark.parametrize(
    "src", ["javascript:alert(1)", "https://example.com/video.mp4", "data:video/mp4,test"]
)
def test_arbitrary_video_url_rejected(src):
    with pytest.raises(AppError):
        EditorService().compile({"content": [{"type": "emailVideo", "attrs": {"src": src}}]})
