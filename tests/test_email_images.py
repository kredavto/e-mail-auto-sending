import io
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.config import get_settings
from app.core.dependencies import get_tenant_context
from app.core.exceptions import AppError, NotFoundError, install_exception_handlers
from app.modules.editor.service import EditorService
from app.modules.file_upload.images import MAX_IMAGE_BYTES, EmailImageService, normalize_image
from app.modules.file_upload.router import router


def picture(format="PNG", size=(480, 320)):
    output = io.BytesIO()
    image = Image.new("RGB", size, "#254b39")
    image.save(output, format=format)
    return output.getvalue()


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_images_normalized_and_resized(format):
    content, width, height = normalize_image(picture(format, (2400, 1600)))
    assert (width, height) == (1200, 800)
    with Image.open(io.BytesIO(content)) as result:
        assert result.format == "PNG"
        assert not result.getexif()


@pytest.mark.parametrize(
    "body",
    [b"", b"<svg></svg>", b"broken", b"x" * (MAX_IMAGE_BYTES + 1)],
    ids=["empty", "svg", "corrupt", "oversize"],
)
def test_invalid_files_rejected(body):
    with pytest.raises(AppError):
        normalize_image(body)


def test_pixel_limit(monkeypatch):
    monkeypatch.setattr("app.modules.file_upload.images.MAX_IMAGE_PIXELS", 100)
    with pytest.raises(AppError, match="мегапикселей"):
        normalize_image(picture())


def test_animation_rejected():
    output = io.BytesIO()
    first = Image.new("RGB", (10, 10), "red")
    first.save(
        output, format="PNG", save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")]
    )
    with pytest.raises(AppError, match="анимации"):
        normalize_image(output.getvalue())


@pytest.fixture
def storage(monkeypatch):
    objects = {}
    s3 = Mock()
    s3.put_object.side_effect = lambda **kwargs: objects.update({kwargs["Key"]: kwargs["Body"]})
    s3.get_object.side_effect = lambda **kwargs: {"Body": io.BytesIO(objects[kwargs["Key"]])}
    monkeypatch.setattr("app.modules.file_upload.images.boto3.client", lambda *a, **kw: s3)
    return objects, s3


def test_authenticated_upload_and_public_retrieval(storage):
    objects, s3 = storage
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    install_exception_handlers(app)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/files/images", files={"file": ("photo.png", picture(), "image/png")}
        )
        assert response.status_code == 401
        assert not objects
        workspace = uuid4()
        app.dependency_overrides[get_tenant_context] = lambda: SimpleNamespace(
            workspace_id=workspace
        )
        response = client.post(
            "/api/v1/files/images", files={"file": ("photo.png", picture(), "image/png")}
        )
        assert response.status_code == 201
        uploaded = response.json()
        assert uploaded["width"] == 480
        assert s3.put_object.call_args.kwargs["Metadata"]["workspace-id"] == str(workspace)
        app.dependency_overrides.clear()
        path = uploaded["url"].removeprefix(get_settings().public_base_url.rstrip("/"))
        public = client.get(path)
        assert public.status_code == 200
        assert public.headers["content-type"] == "image/png"
        assert "immutable" in public.headers["cache-control"]
        assert public.content.startswith(b"\x89PNG")
        state = {
            "content": [
                {
                    "type": "emailImage",
                    "attrs": {"src": uploaded["url"], "alt": 'Фото "продукта" {{7*7}} <script>'},
                }
            ]
        }
        html = EditorService().preview(state, {})
        assert 'width="144"' in html and "width:25%" in html and "height:auto" in html
        assert uploaded["url"] in html
        assert "<script>" not in html and "{{7*7}}" not in html


@pytest.mark.parametrize("name", ["private.csv", "../../contacts.xlsx", "a" * 32 + ".svg"])
def test_public_route_cannot_access_private_files(storage, name):
    with pytest.raises(NotFoundError):
        EmailImageService().download(name)
    storage[1].get_object.assert_not_called()


@pytest.mark.parametrize(
    "source",
    [
        "javascript:alert(1)",
        "data:image/png;base64,abc",
        "https://example.com/a.png",
        "http://localhost:8000/api/v1/files/images/../../contacts.csv",
    ],
)
def test_compiler_rejects_non_uploaded_images(source):
    with pytest.raises(AppError, match="Изображение"):
        EditorService().compile({"content": [{"type": "emailImage", "attrs": {"src": source}}]})
