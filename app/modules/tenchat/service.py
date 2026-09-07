from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import AppError
from app.modules.campaigns.models import CampaignContact
from app.modules.contacts.models import Contact
from app.modules.tenchat.client import TenchatClient
from app.modules.tenchat.models import TenchatMessage, TenchatProfile


class TenchatService:
    def __init__(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        *,
        client: TenchatClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.client = client or TenchatClient()
        self.settings = settings or get_settings()

    async def sync_profiles(self, user_ids: list[str]) -> int:
        synced = 0
        for user_id in dict.fromkeys(user_ids):
            data = await self.client.enrich_profile(user_id)
            profile = await self.db.scalar(
                select(TenchatProfile).where(
                    TenchatProfile.workspace_id == self.workspace_id,
                    TenchatProfile.tenchat_user_id == user_id,
                )
            )
            values = self._profile_values(user_id, data)
            if profile:
                for key, value in values.items():
                    setattr(profile, key, value)
            else:
                profile = TenchatProfile(workspace_id=self.workspace_id, **values)
                self.db.add(profile)
            contact = await self._match_contact(values)
            if contact:
                await self.db.flush()
                profile.contact_id = contact.id
                contact.tenchat_user_id = user_id
            synced += 1
        return synced

    async def send_outreach(self, profile: TenchatProfile, text: str) -> TenchatMessage:
        if not text.strip():
            raise AppError("Сообщение Tenchat не может быть пустым")
        await self._check_daily_limit()
        result = await self.client.send_message(profile.tenchat_user_id, text)
        row = TenchatMessage(
            workspace_id=self.workspace_id,
            profile_id=profile.id,
            contact_id=profile.contact_id,
            external_message_id=str(result.get("id") or result.get("message_id") or "") or None,
            conversation_id=str(result.get("conversation_id") or "") or None,
            direction="O",
            text=text,
            status="sent",
        )
        self.db.add(row)
        return row

    async def check_replies(self) -> int:
        payload = await self.client.get_conversations()
        conversations = payload.get("items") or payload.get("elements") or []
        if not isinstance(conversations, list):
            return 0
        created = 0
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            conversation_id = str(
                conversation.get("id") or conversation.get("conversation_id") or ""
            )
            user_id = str(conversation.get("user_id") or conversation.get("participant_id") or "")
            if not conversation_id:
                continue
            profile = await self.db.scalar(
                select(TenchatProfile).where(
                    TenchatProfile.workspace_id == self.workspace_id,
                    TenchatProfile.tenchat_user_id == user_id,
                )
            )
            if not profile:
                continue
            messages_payload = await self.client.get_messages(conversation_id)
            messages = messages_payload.get("items") or messages_payload.get("elements") or []
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                direction = str(message.get("direction") or "").casefold()
                if direction not in {"i", "in", "incoming"}:
                    continue
                external_id = str(message.get("id") or message.get("message_id") or "")
                if external_id and await self.db.scalar(
                    select(TenchatMessage.id).where(
                        TenchatMessage.workspace_id == self.workspace_id,
                        TenchatMessage.external_message_id == external_id,
                    )
                ):
                    continue
                self.db.add(
                    TenchatMessage(
                        workspace_id=self.workspace_id,
                        profile_id=profile.id,
                        contact_id=profile.contact_id,
                        external_message_id=external_id or None,
                        conversation_id=conversation_id,
                        direction="I",
                        text=str(message.get("text") or ""),
                        status="received",
                        is_reply=True,
                    )
                )
                if profile.contact_id:
                    contact = await self.db.get(Contact, profile.contact_id)
                    if contact:
                        was_replied = contact.has_replied
                        contact.has_replied = True
                        contact.status = "replied"
                        if not was_replied:
                            await publish_enterprise_event(
                                self.db,
                                IntegrationEvent(
                                    workspace_id=self.workspace_id,
                                    resource_type="contact",
                                    resource_id=contact.id,
                                    data={"email": contact.email, "channel": "tenchat"},
                                    kind="contact.replied",
                                ),
                            )
                    await self.db.execute(
                        update(CampaignContact)
                        .where(
                            CampaignContact.contact_id == profile.contact_id,
                            CampaignContact.status == "active",
                        )
                        .values(status="stopped", next_send_at=None)
                    )
                created += 1
        return created

    async def get_profile_for_contact(self, contact_id: UUID) -> TenchatProfile | None:
        return cast(
            TenchatProfile | None,
            await self.db.scalar(
                select(TenchatProfile).where(
                    TenchatProfile.workspace_id == self.workspace_id,
                    TenchatProfile.contact_id == contact_id,
                )
            ),
        )

    async def has_replies(self, contact_id: UUID) -> bool:
        return bool(
            await self.db.scalar(
                select(TenchatMessage.id).where(
                    TenchatMessage.workspace_id == self.workspace_id,
                    TenchatMessage.contact_id == contact_id,
                    TenchatMessage.is_reply.is_(True),
                )
            )
        )

    async def _check_daily_limit(self) -> None:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(TenchatMessage)
                .where(
                    TenchatMessage.workspace_id == self.workspace_id,
                    TenchatMessage.direction == "O",
                    TenchatMessage.created_at >= start,
                )
            )
            or 0
        )
        limit = 500 if self.settings.tenchat_account_tier.casefold() == "business" else 50
        if count >= limit:
            raise AppError(f"Дневной лимит Tenchat ({limit}) исчерпан")

    async def _match_contact(self, values: dict[str, object]) -> Contact | None:
        email = values.get("email")
        if email:
            return cast(
                Contact | None,
                await self.db.scalar(
                    select(Contact).where(
                        Contact.workspace_id == self.workspace_id, Contact.email == email
                    )
                ),
            )
        return None

    @staticmethod
    def _profile_values(user_id: str, data: dict[str, object]) -> dict[str, object]:
        return {
            "tenchat_user_id": user_id,
            "username": str(data.get("username") or ""),
            "display_name": str(data.get("display_name") or data.get("name") or ""),
            "bio": str(data.get("bio") or ""),
            "company_name": str(data.get("company_name") or data.get("company") or ""),
            "position": str(data.get("position") or ""),
            "industry": str(data.get("industry") or ""),
            "city": str(data.get("city") or ""),
            "email": str(data["email"]).casefold() if data.get("email") else None,
            "phone": str(data["phone"]) if data.get("phone") else None,
            "raw_data": data,
        }
