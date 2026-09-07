import hashlib
import json

import httpx
import pytest

from app.config import Settings
from app.modules.bitrix24.client import Bitrix24Client
from app.modules.hunter.client import HunterClient
from app.modules.linkedin.client import LinkedInClient
from app.modules.tenchat.client import TenchatClient


@pytest.mark.asyncio
async def test_bitrix_client_uses_webhook_rest_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/crm.lead.add.json")
        assert json.loads(request.content) == {"fields": {"TITLE": "Lead"}}
        return httpx.Response(200, json={"result": 42})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Bitrix24Client(
            "https://example.bitrix24.ru/rest/1/token",
            settings=Settings(_env_file=None),
            http=http,
        )
        assert await client.create_lead({"TITLE": "Lead"}) == 42


@pytest.mark.asyncio
async def test_hunter_client_normalizes_finder_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "secret"
        assert request.url.params["domain"] == "acme.example"
        return httpx.Response(
            200,
            json={"data": {"email": "Anna@Acme.Example", "score": 91, "position": "CEO"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HunterClient("secret", settings=Settings(_env_file=None), http=http)
        assert await client.find_email("acme.example", "Anna", "Ivanova") == {
            "email": "anna@acme.example",
            "confidence": 91,
            "position": "CEO",
        }


@pytest.mark.asyncio
async def test_linkedin_matched_audience_hashes_emails() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/dmpSegments"):
            return httpx.Response(200, json={"id": "segment-1"})
        return httpx.Response(200, json={})

    settings = Settings(
        _env_file=None,
        linkedin_api_base_url="https://api.linkedin.example/rest",
        linkedin_api_version="202601",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LinkedInClient("token", settings=settings, http=http)
        assert await client.create_matched_audience("Retarget", ["Lead@Example.com"]) == "segment-1"
    upload = json.loads(requests[1].content)
    expected = hashlib.sha256(b"lead@example.com").hexdigest()
    assert upload == {"elements": [{"userIds": [expected]}]}
    assert requests[0].headers["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_tenchat_client_sends_authenticated_message() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert json.loads(request.content) == {"recipient_id": "tc-1", "text": "Здравствуйте"}
        return httpx.Response(200, json={"id": "message-1"})

    settings = Settings(_env_file=None, tenchat_api_base_url="https://tenchat.example/v1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TenchatClient("token", settings=settings, http=http).send_message(
            "tc-1", "Здравствуйте"
        )
    assert result["id"] == "message-1"
