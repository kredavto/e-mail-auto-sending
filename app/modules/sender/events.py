from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class EmailSentEvent(DomainEvent):
    message_id: str = ""
