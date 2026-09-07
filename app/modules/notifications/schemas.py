from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from app.shared.dto import ORMModel


class NotificationResponse(ORMModel):
    id: UUID
    user_id: UUID
    workspace_id: UUID
    type: str
    title: str
    message: str
    data: dict[str, object]
    channel: str
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int


class PreferenceUpdate(BaseModel):
    email_notifications: dict[str, bool] = Field(default_factory=dict)
    webpush_notifications: dict[str, bool] = Field(default_factory=dict)
    telegram_notifications: dict[str, bool] = Field(default_factory=dict)
    telegram_chat_id: str | None = Field(default=None, max_length=100)


class PreferenceResponse(PreferenceUpdate, ORMModel):
    id: UUID


class WebPushSubscriptionCreate(BaseModel):
    endpoint: HttpUrl
    p256dh: str = Field(min_length=1, max_length=500)
    auth: str = Field(min_length=1, max_length=500)


class UnreadCount(BaseModel):
    count: int
