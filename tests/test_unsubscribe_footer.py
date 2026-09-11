from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import AppError
from app.main import create_app
from app.modules.contacts.models import Contact
from app.modules.editor.service import EditorService
from app.modules.scheduler.service import SchedulerService
from app.modules.sender.schemas import SendEmailRequest
from app.modules.sender.service import SenderService
from app.modules.tracking.service import TrackingService
from app.shared.email_footer import with_unsubscribe_footer


@pytest.mark.parametrize("kind", ["personalized", "general"])
def test_compiler_adds_one_footer_at_end_and_ignores_legacy_blocks(kind):
    state = {
        "type": "doc",
        "attrs": {"letterType": kind},
        "content": [
            {"type": "unsubscribeBlock"},
            {"type": "paragraph", "content": [{"type": "text", "text": "Предложение"}]},
            {"type": "unsubscribeBlock"},
        ],
    }
    html, text, variables, _, warnings = EditorService().compile(state)
    assert html.count('data-unsubscribe-footer="true"') == 1
    assert "font-size:12px" in html and 'href="' in html
    assert html.index("Предложение") < html.index("Отписаться от рассылки")
    assert "/unsubscribe/preview" in html and "/unsubscribe/preview" in text
    assert not variables and "Нет блока отписки" not in warnings
    assert "никто не отписан" in TestClient(create_app()).get("/api/v1/unsubscribe/preview").text


def test_sender_personalizes_footer_for_each_message_without_click_tracking():
    sender = SenderService.__new__(SenderService)
    sender.settings = Mock(public_base_url="https://mailer.example")
    for body in ["<html><body><p>Legacy</p></body></html>", EditorService().compile({})[0]]:
        request = SendEmailRequest(
            to="lead@example.com",
            subject="Тема",
            html=body,
            text="Текст",
            sender_email="sender@example.com",
            sender_name="Компания",
        )
        ids = [uuid4(), uuid4()]
        for message_id in ids:
            message = sender.build_mime(request, message_id)
            html = message.get_body(preferencelist=("html",)).get_content()
            text = message.get_body(preferencelist=("plain",)).get_content()
            url = f"https://mailer.example/api/v1/unsubscribe/{message_id}"
            assert f'href="{url}"' in html and url in text
            assert message["List-Unsubscribe"] == f"<{url}>"
            assert html.count('data-unsubscribe-footer="true"') == 1
            assert "/unsubscribe/preview" not in html and "/track/click/" not in html
            if "</body>" in html:
                assert html.index("Отписаться") < html.index("</body>")


def test_duplicate_system_footer_collapses_and_cta_still_tracks():
    preview = "https://mailer.example/api/v1/unsubscribe/preview"
    first = with_unsubscribe_footer("<p>Текст</p>", preview)
    result = with_unsubscribe_footer(
        first + first, "https://mailer.example/api/v1/unsubscribe/real"
    )
    assert result.count('data-unsubscribe-footer="true"') == 1
    sender = SenderService.__new__(SenderService)
    sender.settings = Mock(public_base_url="https://mailer.example")
    tracked = sender._track_links(
        f'<a href="{preview}">Отписка</a><a href="https://example.com">CTA</a>', uuid4()
    )
    assert f'href="{preview}"' in tracked and tracked.count("/track/click/") == 1


@pytest.mark.parametrize("explicit_contact", [True, False])
async def test_unsubscribed_contact_blocked_before_billing_or_smtp(explicit_contact):
    workspace = uuid4()
    contact = Contact(
        id=uuid4(), workspace_id=workspace, email="lead@example.com", is_unsubscribed=True
    )
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = workspace
    sender.repo = Mock(db=Mock(scalar=AsyncMock(return_value=contact)))
    sender.billing = Mock(check_limits=AsyncMock())
    request = SendEmailRequest(
        to=contact.email,
        contact_id=contact.id if explicit_contact else None,
        subject="Тема",
        html="Текст",
        text="Текст",
        sender_email="sender@example.com",
        sender_name="Компания",
    )
    with pytest.raises(AppError, match="отписался"):
        await sender.send(request)
    sender.billing.check_limits.assert_not_awaited()
    assert SchedulerService.should_stop(contact, {"unsubscribed": False})


async def test_unsubscribe_is_idempotent_and_rejects_cross_workspace_links():
    workspace = uuid4()
    contact = Contact(
        id=uuid4(), workspace_id=workspace, email="lead@example.com", is_unsubscribed=False
    )
    message = Mock(contact_id=contact.id, workspace_id=workspace)
    db = Mock(get=AsyncMock(side_effect=[message, contact, message, contact, message, contact]))
    service = TrackingService(db)
    assert await service.unsubscribe(uuid4())
    assert await service.unsubscribe(uuid4())
    assert contact.is_unsubscribed and contact.status == "unsubscribed"
    contact.workspace_id = uuid4()
    assert not await service.unsubscribe(uuid4())


def test_preview_is_public_and_never_unsubscribes():
    response = TestClient(create_app()).get("/api/v1/unsubscribe/preview")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert "никто не отписан" in response.text
