from unittest.mock import Mock
from uuid import uuid4

from app.modules.sender.schemas import SendEmailRequest
from app.modules.sender.service import SenderService


def test_mime_has_alternative_tracking_and_unsubscribe() -> None:
    service = SenderService.__new__(SenderService)
    service.settings = Mock(public_base_url="https://mailer.example")
    payload = SendEmailRequest(
        to="lead@example.com",
        subject="Hello",
        html="<p>Hello</p>",
        text="Hello",
        sender_email="sender@example.com",
        sender_name="Sender",
    )
    message = service.build_mime(payload, uuid4())
    assert message.is_multipart()
    assert message["List-Unsubscribe"]
    assert "/track/open/" in message.get_body(preferencelist=("html",)).get_content()
