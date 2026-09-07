from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class EmailOpenedEvent(DomainEvent):
    message_id: str = ""


@dataclass(frozen=True)
class EmailClickedEvent(DomainEvent):
    message_id: str = ""
    url: str = ""


@dataclass(frozen=True)
class EmailBouncedEvent(DomainEvent):
    message_id: str = ""
    reason: str = ""
