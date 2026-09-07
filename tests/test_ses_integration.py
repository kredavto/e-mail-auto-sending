import json
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.config import Settings
from app.integrations.resilience import IntegrationError
from app.modules.contacts.models import Contact
from app.modules.sender.models import EmailMessage
from app.modules.ses.client import SESClient
from app.modules.ses.service import SESWebhookHandler
from app.modules.ses.sns import SNSSignatureVerifier, SNSVerificationError


@pytest.mark.asyncio
async def test_ses_client_sends_raw_mime() -> None:
    sdk = Mock()
    sdk.send_raw_email.return_value = {"MessageId": "ses-123"}
    settings = Settings(_env_file=None, aws_region="eu-central-1")
    client = SESClient(settings, sdk)
    from email.message import EmailMessage as MIMEMessage

    mime = MIMEMessage()
    mime["From"] = "sender@example.com"
    mime["To"] = "lead@example.com"
    mime.set_content("Hello")
    assert await client.send_raw_email(mime) == "ses-123"
    sdk.send_raw_email.assert_called_once()


@pytest.mark.asyncio
async def test_permanent_bounce_unsubscribes_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    contact_id = uuid4()
    message = EmailMessage(
        id=uuid4(),
        workspace_id=uuid4(),
        contact_id=contact_id,
        recipient_email="lead@example.com",
        subject="Hello",
        provider_message_id="ses-123",
    )
    contact = Contact(id=contact_id, workspace_id=message.workspace_id, email="lead@example.com")
    db = Mock()
    db.scalar = AsyncMock(return_value=message)
    db.get = AsyncMock(return_value=contact)
    topic = "arn:aws:sns:eu-central-1:1:ses"
    monkeypatch.setattr(SNSSignatureVerifier, "verify", AsyncMock())
    notification = {
        "notificationType": "Bounce",
        "mail": {"messageId": "ses-123"},
        "bounce": {"bounceType": "Permanent", "timestamp": "2026-09-07T08:00:00Z"},
    }
    event = await SESWebhookHandler(db, Settings(_env_file=None, ses_sns_topic_arn=topic)).handle(
        {"Type": "Notification", "TopicArn": topic, "Message": json.dumps(notification)}
    )
    assert event == "bounce"
    assert message.bounced is True
    assert contact.is_unsubscribed is True
    assert contact.status == "unsubscribed"


@pytest.mark.asyncio
async def test_complaint_unsubscribes_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    contact_id = uuid4()
    message = EmailMessage(
        id=uuid4(),
        workspace_id=uuid4(),
        contact_id=contact_id,
        recipient_email="lead@example.com",
        subject="Hello",
        provider_message_id="ses-complaint",
    )
    contact = Contact(id=contact_id, workspace_id=message.workspace_id, email="lead@example.com")
    db = Mock(scalar=AsyncMock(return_value=message), get=AsyncMock(return_value=contact))
    topic = "arn:aws:sns:eu-central-1:1:ses"
    monkeypatch.setattr(SNSSignatureVerifier, "verify", AsyncMock())
    notification = {
        "notificationType": "Complaint",
        "mail": {"messageId": "ses-complaint"},
        "complaint": {"timestamp": "2026-09-07T08:00:00Z"},
    }
    await SESWebhookHandler(db, Settings(_env_file=None, ses_sns_topic_arn=topic)).handle(
        {"Type": "Notification", "TopicArn": topic, "Message": json.dumps(notification)}
    )
    assert message.status == "complained"
    assert contact.is_unsubscribed is True


@pytest.mark.asyncio
async def test_sns_rejects_untrusted_certificate_url_without_network() -> None:
    with pytest.raises(SNSVerificationError):
        await SNSSignatureVerifier().verify(
            {
                "Type": "Notification",
                "Message": "{}",
                "MessageId": "id",
                "Timestamp": "2026-09-07T08:00:00Z",
                "TopicArn": "arn:aws:sns:eu-central-1:1:ses",
                "SignatureVersion": "2",
                "Signature": "invalid",
                "SigningCertURL": "https://attacker.example/cert.pem",
            }
        )


@pytest.mark.asyncio
async def test_ses_handler_rejects_unsigned_and_foreign_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = SESWebhookHandler(
        Mock(), Settings(_env_file=None, ses_sns_topic_arn="arn:aws:sns:eu-central-1:1:expected")
    )
    with pytest.raises(IntegrationError, match="signed SNS"):
        await handler.handle({"notificationType": "Bounce"})
    monkeypatch.setattr(SNSSignatureVerifier, "verify", AsyncMock())
    with pytest.raises(IntegrationError, match="Unexpected SNS topic"):
        await handler.handle(
            {
                "Type": "Notification",
                "TopicArn": "arn:aws:sns:eu-central-1:1:attacker",
                "Message": json.dumps({"notificationType": "Bounce"}),
            }
        )
