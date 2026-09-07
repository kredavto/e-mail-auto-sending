from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class ContactsImportedEvent(DomainEvent):
    count: int = 0
