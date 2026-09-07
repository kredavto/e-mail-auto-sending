from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class RefreshTokenReuseDetectedEvent(DomainEvent):
    family_id: str = ""
