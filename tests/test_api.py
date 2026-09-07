from fastapi.testclient import TestClient

from app.main import create_app


def test_health() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_contains_product_modules() -> None:
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/auth/register",
        "/api/v1/products",
        "/api/v1/editor/compile",
        "/api/v1/campaigns",
        "/api/v1/scheduler/status",
        "/api/v1/queue/stats",
        "/api/v1/ses/webhook",
        "/api/v1/bitrix/sync-contacts",
        "/api/v1/hunter/find-email",
        "/api/v1/linkedin/import-csv",
        "/api/v1/tenchat/outreach",
        "/api/v1/omnichannel/orchestrate",
    ):
        assert path in paths
