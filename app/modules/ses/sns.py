from __future__ import annotations

import base64
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.integrations.resilience import IntegrationError


class SNSVerificationError(IntegrationError):
    status_code = 403
    code = "sns_signature_invalid"


class SNSSignatureVerifier:
    """Verifies the AWS SNS envelope before feedback mutates suppression state."""

    FIELD_ORDER = {
        "Notification": ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"),
        "SubscriptionConfirmation": (
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ),
        "UnsubscribeConfirmation": (
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ),
    }

    async def verify(self, payload: dict[str, object]) -> None:
        message_type = str(payload.get("Type", ""))
        fields = self.FIELD_ORDER.get(message_type)
        if not fields:
            raise SNSVerificationError("Unsupported SNS message type")
        cert_url = str(payload.get("SigningCertURL", ""))
        parsed = urlparse(cert_url)
        hostname = (parsed.hostname or "").casefold()
        if (
            parsed.scheme != "https"
            or not hostname.startswith("sns.")
            or not hostname.endswith(".amazonaws.com")
        ):
            raise SNSVerificationError("Untrusted SNS signing certificate URL")
        signature_version = str(payload.get("SignatureVersion", ""))
        if signature_version not in {"1", "2"}:
            raise SNSVerificationError("Unsupported SNS signature version")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(cert_url)
                response.raise_for_status()
            certificate = x509.load_pem_x509_certificate(response.content)
            canonical = "".join(
                f"{field}\n{payload[field]}\n" for field in fields if field in payload
            ).encode()
            algorithm = hashes.SHA256() if signature_version == "2" else hashes.SHA1()
            public_key = certificate.public_key()
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise SNSVerificationError("SNS certificate does not contain an RSA public key")
            public_key.verify(
                base64.b64decode(str(payload.get("Signature", ""))),
                canonical,
                padding.PKCS1v15(),
                algorithm,
            )
        except SNSVerificationError:
            raise
        except Exception as exc:
            raise SNSVerificationError("Invalid SNS signature") from exc
