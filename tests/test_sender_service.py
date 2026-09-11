from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.sender.models import EmailMessage
from app.modules.sender.schemas import SendEmailRequest
from app.modules.sender.service import SenderService


def payload() -> SendEmailRequest:
    return SendEmailRequest(
        to="lead@example.com",
        subject="Предложение",
        html='<p><a href="https://example.com/offer">Открыть</a></p>',
        text="Открыть",
        sender_email="sender@example.com",
        sender_name="Sender",
    )


def test_link_rewrite_is_urlsafe() -> None:
    sender = SenderService.__new__(SenderService)
    sender.settings = Mock(public_base_url="https://mailer.example")
    result = sender._track_links(payload().html, uuid4())
    assert "/track/click/" in result
    assert "https://example.com/offer" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("port,tls", [(465, True), (587, True), (1025, False)])
async def test_send_success(monkeypatch: pytest.MonkeyPatch, port: int, tls: bool) -> None:
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = uuid4()
    sender.settings = Mock(
        public_base_url="https://mailer.example",
        smtp_host="smtp.example.com",
        smtp_port=port,
        smtp_username="user",
        smtp_password="pass",
        smtp_use_tls=tls,
    )
    row = EmailMessage(id=uuid4(), workspace_id=sender.workspace_id)
    sender.repo = Mock(add=AsyncMock(return_value=row), db=AsyncMock())
    sender._check_domain_rate = AsyncMock()  # type: ignore[method-assign]
    smtp_send = AsyncMock(return_value=({}, "id"))
    monkeypatch.setattr("app.modules.sender.service.aiosmtplib.send", smtp_send)
    result = await sender.send(payload())
    assert result.status == "sent"
    assert result.sent_at is not None
    options = smtp_send.await_args.kwargs
    assert options["use_tls"] is (tls and port == 465)
    assert options["start_tls"] is (tls and port != 465)


@pytest.mark.asyncio
async def test_send_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = uuid4()
    sender.settings = Mock(
        public_base_url="https://mailer.example",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="",
        smtp_password="",
        smtp_use_tls=True,
    )
    row = EmailMessage(id=uuid4(), workspace_id=sender.workspace_id)
    sender.repo = Mock(add=AsyncMock(return_value=row), db=AsyncMock())
    sender._check_domain_rate = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.modules.sender.service.aiosmtplib.send", AsyncMock(side_effect=TimeoutError("slow"))
    )
    with pytest.raises(TimeoutError):
        await sender.send(payload())
    assert row.status == "failed"
    assert row.error == "slow"


@pytest.mark.asyncio
async def test_send_uses_ses_when_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = uuid4()
    sender.settings = Mock(
        public_base_url="https://mailer.example",
        email_provider="ses",
        bitrix24_webhook_url="",
    )
    row = EmailMessage(id=uuid4(), workspace_id=sender.workspace_id)
    sender.repo = Mock(add=AsyncMock(return_value=row), db=AsyncMock())
    sender._check_domain_rate = AsyncMock()  # type: ignore[method-assign]
    ses_client = Mock(send_raw_email=AsyncMock(return_value="ses-message-id"))
    monkeypatch.setattr("app.modules.ses.client.SESClient", Mock(return_value=ses_client))
    result = await sender.send(payload())
    assert result.status == "sent"
    assert result.provider_message_id == "ses-message-id"
    ses_client.send_raw_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_campaign_contact_is_synced_to_bitrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.campaigns.models import Campaign
    from app.modules.contacts.models import Contact
    from app.modules.products.models import Product

    workspace_id, campaign_id, contact_id, product_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    contact = Contact(id=contact_id, workspace_id=workspace_id, email="lead@example.com")
    campaign = Campaign(
        id=campaign_id,
        workspace_id=workspace_id,
        product_id=product_id,
        sequence_id=uuid4(),
        sender_email="sender@example.com",
        sender_name="Sender",
    )
    product = Product(id=product_id, workspace_id=workspace_id, name="Sites", slug="sites")
    db = Mock()
    db.get = AsyncMock(
        side_effect=lambda model, item_id: {
            (Contact, contact_id): contact,
            (Campaign, campaign_id): campaign,
            (Product, product_id): product,
        }.get((model, item_id))
    )
    sync = AsyncMock()
    bitrix_service = Mock(sync_contact_to_lead=sync)
    monkeypatch.setattr(
        "app.modules.bitrix24.service.Bitrix24SyncService", Mock(return_value=bitrix_service)
    )
    sender = SenderService.__new__(SenderService)
    sender.workspace_id = workspace_id
    sender.settings = Mock(bitrix24_webhook_url="https://bitrix.example/rest/1/token")
    sender.repo = Mock(db=db)
    request = payload().model_copy(update={"campaign_id": campaign_id, "contact_id": contact_id})
    await sender._ensure_bitrix_lead(request)
    sync.assert_awaited_once_with(contact, product, campaign_id)
