from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.dependencies import TenantContext
from app.core.exceptions import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.main import create_app
from app.modules.assistant.models import AssistantRun
from app.modules.assistant.schemas import ActionRequest, ConfirmRequest, Draft
from app.modules.assistant.service import (
    AssistantService,
    campaign_snapshot,
    draft_document,
    require_future,
)
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.editor.service import EditorService


def service(role="owner"):
    tenant = TenantContext(uuid4(), SimpleNamespace(id=uuid4()), role)
    db = Mock(scalar=AsyncMock(), scalars=AsyncMock(), flush=AsyncMock())
    return AssistantService(db, tenant)


def campaign(svc, status="draft"):
    return Campaign(
        id=uuid4(),
        workspace_id=svc.workspace_id,
        product_id=uuid4(),
        sequence_id=uuid4(),
        name="Campaign",
        sender_email="from@example.com",
        sender_name="Tester",
        schedule_start=datetime.now(UTC) + timedelta(days=1),
        status=status,
        updated_at=datetime.now(UTC),
    )


def test_draft_compiles_variables_and_hidden_cta():
    draft = Draft(
        name="Письмо",
        subject="Для {{company}}",
        paragraphs=["Здравствуйте, {{full_name}}!", "<script>alert(1)</script>"],
        cta_label="Обсудить",
        cta_url="https://example.com/meeting",
    )
    doc = draft_document(draft)
    html, text, variables, _, _ = EditorService().compile(doc)
    assert "<script>" not in html and 'href="https://example.com/meeting"' in html
    assert "Обсудить" in html and "full_name" in variables
    assert doc["content"][-1]["type"] == "unsubscribeBlock"


@pytest.mark.parametrize("bad", ["{{config}}", "{% for x in range(2) %}", "{{7*7}}", "{# note #}"])
def test_draft_rejects_unapproved_template_syntax(bad):
    with pytest.raises(ValueError):
        draft_document(
            Draft(name="Test", subject="Test", paragraphs=[bad], cta_url=None, cta_label=None)
        )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:password@example.com",
        "https://example.com/{{bad}}",
    ],
)
def test_draft_rejects_unsafe_cta(url):
    with pytest.raises(ValueError):
        draft_document(
            Draft(name="Test", subject="Test", paragraphs=["Hello"], cta_url=url, cta_label="Link")
        )


def test_confirm_requires_true_and_dates_require_timezone():
    with pytest.raises(ValidationError):
        ConfirmRequest(confirmed=False)
    with pytest.raises(ValidationError):
        ActionRequest(action="reschedule", send_at="2028-01-01T10:00:00")
    with pytest.raises(AppError):
        require_future(datetime.now(UTC))


@pytest.mark.asyncio
async def test_viewer_cannot_prepare_or_confirm():
    svc = service("viewer")
    with pytest.raises(PermissionDeniedError):
        await svc.prepare_action(uuid4(), ActionRequest(action="pause"))
    with pytest.raises(PermissionDeniedError):
        await svc.confirm(uuid4())
    svc.db.scalar.assert_not_called()


@pytest.mark.asyncio
async def test_tenant_and_author_scopes_are_in_queries():
    svc = service()
    svc.db.scalar.return_value = None
    with pytest.raises(NotFoundError):
        await svc.get_run(uuid4())
    sql = str(svc.db.scalar.call_args.args[0])
    assert "assistant_runs.workspace_id" in sql and "assistant_runs.user_id" in sql
    with pytest.raises(NotFoundError):
        await svc.campaign(uuid4())
    assert "campaigns.workspace_id" in str(svc.db.scalar.call_args.args[0])


@pytest.mark.asyncio
async def test_reschedule_preparation_never_changes_campaign():
    svc = service()
    item = campaign(svc)
    old = item.schedule_start
    svc.campaign = AsyncMock(return_value=item)
    svc.recipients = AsyncMock(
        return_value=[CampaignContact(current_step_index=0, status="active")]
    )
    run = await svc.prepare_action(
        item.id, ActionRequest(action="reschedule", send_at=old + timedelta(days=1))
    )
    assert item.schedule_start == old and item.status == "draft"
    assert run.result["action"]["kind"] == "reschedule"
    assert run.action_snapshot == campaign_snapshot(item)


@pytest.mark.asyncio
async def test_reschedule_rejected_after_first_enqueue():
    svc = service()
    item = campaign(svc, "paused")
    svc.recipients = AsyncMock(return_value=[CampaignContact(current_step_index=1)])
    with pytest.raises(AppError):
        await svc.action_details(
            item, ActionRequest(action="reschedule", send_at=item.schedule_start)
        )


@pytest.mark.asyncio
async def test_confirm_reschedules_rows_and_is_idempotent(monkeypatch):
    svc = service()
    item = campaign(svc)
    target = item.schedule_start + timedelta(days=1)
    recipient = CampaignContact(
        current_step_index=0, status="active", next_send_at=item.schedule_start
    )
    run = AssistantRun(
        id=uuid4(),
        status="complete",
        created_at=datetime.now(UTC),
        action_snapshot=campaign_snapshot(item),
        result={"action": {"kind": "reschedule", "send_at": target.isoformat()}},
    )
    svc.get_run = AsyncMock(return_value=run)
    svc.campaign = AsyncMock(return_value=item)
    svc.recipients = AsyncMock(return_value=[recipient])
    log = AsyncMock()
    monkeypatch.setattr("app.modules.assistant.service.AuditService.log", log)
    assert await svc.confirm(run.id) is run
    assert recipient.next_send_at == target and item.schedule_start == target
    assert item.status == "draft" and run.applied_at is not None
    await svc.confirm(run.id)
    log.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_confirmation_rejects_stale_state_or_expired_proposal(expired):
    svc = service()
    item = campaign(svc)
    run = AssistantRun(
        id=uuid4(),
        status="complete",
        created_at=datetime.now(UTC) - timedelta(minutes=16 if expired else 0),
        action_snapshot=campaign_snapshot(item),
        result={"action": {"kind": "start"}},
    )
    if not expired:
        item.name = "Changed elsewhere"
    svc.get_run = AsyncMock(return_value=run)
    svc.campaign = AsyncMock(return_value=item)
    with pytest.raises(ConflictError):
        await svc.confirm(run.id)
    assert item.status == "draft" and run.applied_at is None


@pytest.mark.parametrize("path", ["/assistant/context", "/assistant/runs", "/assistant/contacts"])
def test_assistant_requires_authentication(path):
    with TestClient(create_app()) as client:
        response = client.get("/api/v1" + path)
    assert response.status_code == 401
