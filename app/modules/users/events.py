from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class WorkspaceMemberInvitedEvent(DomainEvent):
    email: str = ""
    role: str = "viewer"
