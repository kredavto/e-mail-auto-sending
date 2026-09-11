import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import TenantContext
from app.core.exceptions import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.modules.assistant.agent import run_agent
from app.modules.assistant.models import AssistantRun
from app.modules.assistant.schemas import (
    ActionRequest,
    AskRequest,
    CampaignDraftRequest,
    Draft,
)
from app.modules.audit.service import AuditService
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.contacts.personalization import contact_variables
from app.modules.products.models import Product
from app.modules.sequences.models import Sequence, SequenceStep
from app.modules.templates.models import Template
from app.modules.users.models import Workspace

ALLOWED_VARIABLES = {"first_name", "full_name", "company", "product_name"}
VARIABLE = re.compile(r"{{\s*(first_name|full_name|company|product_name)\s*}}")


def draft_document(draft: Draft) -> dict:
    """Only a small, deterministic TipTap subset; never trust model-supplied HTML."""
    if sum(map(len, draft.paragraphs)) > 12000:
        raise ValueError("Draft too large")
    for value in [draft.subject, draft.cta_label or "", *draft.paragraphs]:
        remainder = VARIABLE.sub("", value)
        if any(marker in remainder for marker in ("{{", "}}", "{%", "%}", "{#", "#}")):
            raise ValueError("Unsupported template syntax")
    content = []
    for paragraph in draft.paragraphs:
        nodes = []
        offset = 0
        for match in VARIABLE.finditer(paragraph):
            if match.start() > offset:
                nodes.append({"type": "text", "text": paragraph[offset : match.start()]})
            nodes.append({"type": "variable", "attrs": {"name": match.group(1)}})
            offset = match.end()
        if offset < len(paragraph):
            nodes.append({"type": "text", "text": paragraph[offset:]})
        content.append({"type": "paragraph", "content": nodes})
    if draft.cta_url:
        url = urlsplit(draft.cta_url)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError("Unsafe CTA URL")
        if any(c in draft.cta_url for c in "\r\n{}"):
            raise ValueError("Unsafe CTA URL")
        content.append(
            {
                "type": "ctaButton",
                "attrs": {
                    "label": (draft.cta_label or "Подробнее")[:200],
                    "url": draft.cta_url,
                },
            }
        )
    content.append({"type": "unsubscribeBlock"})
    return {"type": "doc", "content": content}


def campaign_snapshot(campaign: Campaign) -> dict:
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "status": campaign.status,
        "schedule_start": campaign.schedule_start.isoformat(),
        "updated_at": campaign.updated_at.isoformat(),
        "sender_email": campaign.sender_email,
        "sender_name": campaign.sender_name,
        "sequence_id": str(campaign.sequence_id),
    }


def require_future(value: datetime) -> None:
    if value.tzinfo is None or value <= datetime.now(UTC) + timedelta(minutes=1):
        raise AppError("Укажите время с часовым поясом минимум на минуту позже текущего.")


class AssistantService:
    def __init__(self, db: AsyncSession, tenant: TenantContext):
        self.db, self.tenant = db, tenant
        self.workspace_id = tenant.workspace_id

    def require_manager(self) -> None:
        if self.tenant.role not in {"owner", "admin", "manager"}:
            raise PermissionDeniedError(
                "Управлять рассылками может владелец, администратор или менеджер."
            )

    async def campaign(self, campaign_id: UUID, lock: bool = False) -> Campaign:
        query = select(Campaign).where(
            Campaign.id == campaign_id, Campaign.workspace_id == self.workspace_id
        )
        if lock:
            query = query.with_for_update()
        row = await self.db.scalar(query.execution_options(populate_existing=True))
        if not row:
            raise NotFoundError("Кампания не найдена в текущем рабочем пространстве.")
        return row

    async def get_run(self, run_id: UUID, lock: bool = False) -> AssistantRun:
        query = select(AssistantRun).where(
            AssistantRun.id == run_id,
            AssistantRun.workspace_id == self.workspace_id,
            AssistantRun.user_id == self.tenant.user.id,
        )
        row = await self.db.scalar(query.with_for_update() if lock else query)
        if not row:
            raise NotFoundError("Запрос ИИ не найден.")
        return row

    async def context(self, request: AskRequest | None = None) -> dict:
        counts = {}
        for name, model in (
            ("contacts", Contact),
            ("templates", Template),
            ("campaigns", Campaign),
        ):
            counts[name] = await self.db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.workspace_id == self.workspace_id)
            )
        settings = get_settings()
        context = {
            "counts": counts,
            "now_utc": datetime.now(UTC).isoformat(),
            "timezone": "Europe/Moscow",
            "delivery_mode": (
                "test"
                if settings.email_provider == "smtp"
                and ("mailpit" in settings.smtp_host or not settings.smtp_host)
                else settings.email_provider
            ),
            "ai_configured": bool(settings.openai_api_key.get_secret_value()),
            "can_manage": self.tenant.role in {"owner", "admin", "manager"},
            "daily_limit": settings.assistant_daily_limit,
        }
        if request and request.campaign_id:
            context["campaign"] = campaign_snapshot(await self.campaign(request.campaign_id))
        if request and request.template_id:
            template = await self.db.scalar(
                select(Template).where(
                    Template.id == request.template_id, Template.workspace_id == self.workspace_id
                )
            )
            if not template:
                raise NotFoundError("Шаблон не найден.")
            context["selected_template"] = {
                "name": template.name,
                "subject": template.subject_template,
                "text": template.text_body[:12000],
                "category": template.category,
            }
        return context

    async def ask(self, request: AskRequest) -> AssistantRun:
        settings = get_settings()
        if not settings.openai_api_key.get_secret_value():
            raise AppError("OpenAI ещё не подключён на сервере.")
        context = await self.context(request)
        # Serialize admissions per workspace to enforce the daily spend guardrail.
        await self.db.scalar(
            select(Workspace).where(Workspace.id == self.workspace_id).with_for_update()
        )
        count = await self.db.scalar(
            select(func.count())
            .select_from(AssistantRun)
            .where(
                AssistantRun.workspace_id == self.workspace_id,
                AssistantRun.model != "manual",
                AssistantRun.created_at
                >= datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        if (count or 0) >= settings.assistant_daily_limit:
            raise AppError(
                "Дневной лимит запросов ИИ исчерпан. Попробуйте завтра (сброс в 00:00 UTC)."
            )
        row = AssistantRun(
            id=uuid4(),
            workspace_id=self.workspace_id,
            user_id=self.tenant.user.id,
            prompt=request.prompt,
            model=settings.openai_model,
        )
        self.db.add(row)
        await self.db.commit()
        try:
            answer, input_tokens, output_tokens = await run_agent(request, context)
            row.input_tokens, row.output_tokens = input_tokens, output_tokens
            result = answer.model_dump()
            # Standard short-context pricing verified on 2026-09-11. No cache discount assumed.
            result["estimated_cost_usd"] = (
                round((input_tokens * 0.20 + output_tokens * 1.20) / 1_000_000, 8)
                if settings.openai_model == "gpt-5.6-luna"
                else None
            )
            if request.mode != "draft":
                result["draft"] = None
            if result["draft"]:
                result["draft"]["editor_state"] = draft_document(answer.draft)
                result["draft"]["category"] = request.stage
            row.action_snapshot = {}
            result["action"] = None
            if request.mode == "schedule" and request.campaign_id and answer.action != "none":
                self.require_manager()
                campaign = await self.campaign(request.campaign_id)
                action = ActionRequest(action=answer.action, send_at=answer.send_at)
                result["action"] = await self.action_details(campaign, action)
                row.action_snapshot = campaign_snapshot(campaign)
            row.result, row.status = result, "complete"
        except RateLimitError:
            row.result, row.status = {
                "message": "OpenAI ограничил запросы или исчерпан баланс API. "
                "Проверьте биллинг OpenAI."
            }, "error"
        except (TimeoutError, APIConnectionError, APITimeoutError):
            row.result, row.status = {
                "message": "ИИ не ответил вовремя. Попробуйте позже; рассылки не изменены."
            }, "error"
        except APIStatusError:
            row.result, row.status = {
                "message": "OpenAI отклонил запрос. "
                "Администратору нужно проверить ключ и доступ к модели."
            }, "error"
        except AppError as exc:
            row.result, row.status = {"message": exc.message}, "error"
        except Exception:
            # Provider errors and untrusted output must never expose credentials or internal traces.
            row.result, row.status = {
                "message": "Не удалось подготовить безопасный результат. "
                "Уточните запрос; рассылки не изменены."
            }, "error"
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def recipients(self, campaign: Campaign, lock: bool = False) -> list[CampaignContact]:
        query = select(CampaignContact).where(CampaignContact.campaign_id == campaign.id)
        return list((await self.db.scalars(query.with_for_update() if lock else query)).all())

    async def action_details(self, campaign: Campaign, action: ActionRequest) -> dict:
        rows = await self.recipients(campaign)
        if action.action == "pause":
            if campaign.status not in {"running", "scheduled"}:
                raise AppError("Приостановить можно только запущенную кампанию.")
        elif action.action == "reschedule":
            if campaign.status not in {"draft", "paused"} or any(
                r.current_step_index for r in rows
            ):
                raise AppError(
                    "Перенос доступен только в черновике/на паузе "
                    "до постановки первого письма в очередь."
                )
            if action.send_at is None:
                raise AppError("Укажите новую дату и время.")
            require_future(action.send_at)
        else:
            if campaign.status not in {"draft", "paused", "scheduled"}:
                raise AppError("Кампания уже запущена или завершена.")
            if not rows or not any(r.status == "active" for r in rows):
                raise AppError("В кампании нет активных получателей.")
            if not any(r.current_step_index for r in rows):
                require_future(campaign.schedule_start)
            await self.validate_campaign(campaign, rows)
        return {
            "kind": action.action,
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "send_at": (
                action.send_at.isoformat()
                if action.send_at
                else campaign.schedule_start.isoformat()
            ),
            "recipients": len(rows),
            "sender_email": campaign.sender_email,
            "warning": "Пауза не отзывает уже переданные в очередь/SMTP письма. "
            "Возобновление может отправить просроченные шаги сразу.",
        }

    async def validate_campaign(self, campaign: Campaign, rows: list[CampaignContact]) -> None:
        sequence = await self.db.scalar(
            select(Sequence).where(
                Sequence.id == campaign.sequence_id, Sequence.workspace_id == self.workspace_id
            )
        )
        product = await self.db.scalar(
            select(Product).where(
                Product.id == campaign.product_id, Product.workspace_id == self.workspace_id
            )
        )
        if not sequence or not product or not sequence.is_active:
            raise AppError("Проверьте продукт и цепочку кампании.")
        if not all(
            sequence.stop_conditions.get(key) for key in ("replied", "unsubscribed", "bounced")
        ):
            raise AppError("Включите остановку цепочки при ответе, отписке и возврате письма.")
        window = sequence.send_window
        days, hours = window.get("days", []), window.get("hours", [])
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(str(window.get("timezone", "Europe/Moscow")).replace("MSK", "Europe/Moscow"))
            if not days or not set(days) <= {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
                raise ValueError()
            if (
                len(hours) != 2
                or not all(type(x) is int for x in hours)
                or not 0 <= hours[0] < hours[1] <= 24
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise AppError("Некорректное окно отправки в цепочке.") from None
        steps = list(
            (
                await self.db.scalars(
                    select(SequenceStep)
                    .where(SequenceStep.sequence_id == sequence.id)
                    .order_by(SequenceStep.position)
                )
            ).all()
        )
        if not steps or [s.position for s in steps] != list(range(len(steps))):
            raise AppError("В цепочке нет шагов или нарушен порядок.")
        required = set()
        for step in steps:
            if step.step_type != "email":
                raise AppError("ИИ-планировщик поддерживает только email-цепочки.")
            template = await self.db.scalar(
                select(Template).where(
                    Template.id == step.template_id, Template.workspace_id == self.workspace_id
                )
            )
            if not template:
                raise AppError("Один из шаблонов удалён или недоступен.")
            required.update(template.variables)
        ids = [r.contact_id for r in rows if r.status == "active"]
        contacts = list(
            (
                await self.db.scalars(
                    select(Contact).where(
                        Contact.workspace_id == self.workspace_id, Contact.id.in_(ids)
                    )
                )
            ).all()
        )
        if len(contacts) != len(ids):
            raise AppError("В кампании есть недоступные контакты.")
        eligible = 0
        for contact in contacts:
            if (
                contact.is_unsubscribed
                or contact.has_replied
                or contact.status in {"bounced", "meeting_booked"}
            ):
                continue
            eligible += 1
            values = contact_variables(contact, product.name)
            missing = [v for v in required if not values.get(v)]
            if missing:
                raise AppError(
                    "У получателей не заполнены поля шаблона: " + ", ".join(sorted(missing))
                )
        if not eligible:
            raise AppError("Нет доступных получателей: проверьте отписки, ответы и возвраты.")

    async def prepare_action(self, campaign_id: UUID, action: ActionRequest) -> AssistantRun:
        self.require_manager()
        campaign = await self.campaign(campaign_id)
        details = await self.action_details(campaign, action)
        row = AssistantRun(
            id=uuid4(),
            workspace_id=self.workspace_id,
            user_id=self.tenant.user.id,
            model="manual",
            prompt="Управление расписанием",
            status="complete",
            result={"message": "Проверьте параметры и подтвердите действие.", "action": details},
            action_snapshot=campaign_snapshot(campaign),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def confirm(self, run_id: UUID) -> AssistantRun:
        self.require_manager()
        row = await self.get_run(run_id, lock=True)
        if row.applied_at:
            return row  # Replaying a confirmation never repeats a side effect.
        if row.status != "complete" or not row.action_snapshot or not row.result.get("action"):
            raise AppError("В этом ответе нет действия для подтверждения.")
        if row.created_at < datetime.now(UTC) - timedelta(minutes=15):
            raise ConflictError("Предложение устарело. Запросите новое подтверждение.")
        campaign = await self.campaign(UUID(row.action_snapshot["id"]), lock=True)
        if campaign_snapshot(campaign) != row.action_snapshot:
            raise ConflictError("Кампания изменилась. Обновите предложение перед подтверждением.")
        rows = await self.recipients(campaign, lock=True)
        details = row.result["action"]
        action = ActionRequest(action=details["kind"], send_at=details["send_at"])
        await self.action_details(campaign, action)
        if action.action == "reschedule":
            campaign.schedule_start = action.send_at
            for recipient in rows:
                if recipient.status == "active":
                    recipient.next_send_at = action.send_at
        else:
            campaign.status = "paused" if action.action == "pause" else "running"
        row.applied_at = datetime.now(UTC)
        await AuditService(self.db, self.workspace_id).log(
            "assistant." + action.action,
            "campaign",
            user_id=self.tenant.user.id,
            resource_id=campaign.id,
            old_values=row.action_snapshot,
            new_values={
                "status": campaign.status,
                "schedule_start": campaign.schedule_start,
                "approved_run_id": str(row.id),
            },
        )
        await self.db.flush()
        return row

    async def create_campaign(self, data: CampaignDraftRequest) -> Campaign:
        self.require_manager()
        require_future(data.schedule_start)
        ids = set(data.contact_ids)
        contacts = list(
            (
                await self.db.scalars(
                    select(Contact).where(
                        Contact.workspace_id == self.workspace_id, Contact.id.in_(ids)
                    )
                )
            ).all()
        )
        if len(contacts) != len(ids):
            raise AppError("Выбраны недоступные контакты.")
        if any(
            c.is_unsubscribed or c.has_replied or c.status in {"bounced", "meeting_booked"}
            for c in contacts
        ):
            raise AppError("Уберите из получателей отписавшихся, ответивших и адреса с возвратами.")
        templates = list(
            (
                await self.db.scalars(
                    select(Template).where(
                        Template.workspace_id == self.workspace_id,
                        Template.id.in_(data.template_ids),
                    )
                )
            ).all()
        )
        if len(templates) != len(set(data.template_ids)):
            raise AppError("Выбранный шаблон недоступен.")
        product = Product(
            workspace_id=self.workspace_id,
            name=data.product_name,
            slug="studio-" + uuid4().hex,
            category="studio",
        )
        self.db.add(product)
        await self.db.flush()
        sequence = Sequence(
            workspace_id=self.workspace_id,
            product_id=product.id,
            name=data.name,
            send_window={
                "days": ["mon", "tue", "wed", "thu", "fri"],
                "hours": [9, 18],
                "timezone": "Europe/Moscow",
            },
            stop_conditions={
                "replied": True,
                "unsubscribed": True,
                "bounced": True,
                "meeting_booked": True,
            },
        )
        self.db.add(sequence)
        await self.db.flush()
        for position, template_id in enumerate(data.template_ids):
            self.db.add(
                SequenceStep(
                    sequence_id=sequence.id,
                    position=position,
                    step_type="email",
                    template_id=template_id,
                    delay_days=0 if position == 0 else data.delay_days,
                )
            )
        campaign = Campaign(
            workspace_id=self.workspace_id,
            product_id=product.id,
            sequence_id=sequence.id,
            name=data.name,
            sender_email=str(data.sender_email),
            sender_name=data.sender_name,
            schedule_start=data.schedule_start,
            status="draft",
        )
        self.db.add(campaign)
        await self.db.flush()
        self.db.add_all(
            [
                CampaignContact(
                    campaign_id=campaign.id, contact_id=i, next_send_at=data.schedule_start
                )
                for i in ids
            ]
        )
        await self.db.flush()
        await AuditService(self.db, self.workspace_id).log(
            "assistant.campaign_draft_created",
            "campaign",
            user_id=self.tenant.user.id,
            resource_id=campaign.id,
            new_values={"name": campaign.name, "recipients": len(ids), "consent_confirmed": True},
        )
        return campaign
