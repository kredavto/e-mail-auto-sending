from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass(frozen=True)
class ProductMatchedEvent(DomainEvent):
    product_id: str = ""
    contact_id: str = ""
    score: float = 0.0
