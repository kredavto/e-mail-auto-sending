from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.analytics.models import AnalyticsReport, DailyMetric
from app.modules.analytics.schemas import GenerateReportRequest
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.products.models import Product
from app.modules.sender.models import EmailMessage


class AnalyticsService:
    PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}

    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db, self.workspace_id = db, workspace_id

    @classmethod
    def since(cls, period: str) -> date:
        return date.today() - timedelta(days=cls.PERIOD_DAYS.get(period, 30) - 1)

    @staticmethod
    def _number(value: object) -> float:
        return float(value) if isinstance(value, (int, float, str)) else 0.0

    @staticmethod
    def _rates(values: dict[str, object]) -> dict[str, object]:
        sent = AnalyticsService._number(values.get("sent", 0))
        values["delivery_rate"] = (
            AnalyticsService._number(values.get("delivered", 0)) / sent if sent else 0
        )
        values["open_rate"] = (
            AnalyticsService._number(values.get("opened", 0)) / sent if sent else 0
        )
        values["click_rate"] = (
            AnalyticsService._number(values.get("clicked", 0)) / sent if sent else 0
        )
        values["reply_rate"] = (
            AnalyticsService._number(values.get("replied", 0)) / sent if sent else 0
        )
        values["bounce_rate"] = (
            AnalyticsService._number(values.get("bounced", 0)) / sent if sent else 0
        )
        return values

    async def _metrics(
        self,
        *,
        product_id: UUID | None = None,
        campaign_id: UUID | None = None,
        period: str = "30d",
    ) -> list[DailyMetric]:
        query = select(DailyMetric).where(
            DailyMetric.workspace_id == self.workspace_id, DailyMetric.date >= self.since(period)
        )
        if product_id:
            query = query.where(DailyMetric.product_id == product_id)
        if campaign_id:
            query = query.where(DailyMetric.campaign_id == campaign_id)
        return list((await self.db.scalars(query.order_by(DailyMetric.date))).all())

    @staticmethod
    def _sum(rows: list[DailyMetric]) -> dict[str, object]:
        result: dict[str, object] = {
            key: sum(getattr(row, f"{key}_count") for row in rows)
            for key in ("sent", "delivered", "opened", "clicked", "replied", "bounced", "meeting")
        }
        result["meetings"] = result.pop("meeting")
        return AnalyticsService._rates(result)

    async def get_product_stats(self, product_id: UUID, period: str = "30d") -> dict[str, object]:
        product = await self.db.get(Product, product_id)
        if not product or product.workspace_id != self.workspace_id:
            raise NotFoundError("Направление не найдено")
        rows = await self._metrics(product_id=product_id, period=period)
        if rows:
            stats = self._sum(rows)
        else:
            campaigns = list(
                (
                    await self.db.scalars(
                        select(Campaign).where(
                            Campaign.workspace_id == self.workspace_id,
                            Campaign.product_id == product_id,
                        )
                    )
                ).all()
            )
            sent = sum(row.sent_count for row in campaigns)
            stats = self._rates(
                {
                    "sent": sent,
                    "delivered": max(0, sent - sum(row.bounced_count for row in campaigns)),
                    "opened": sum(row.opened_count for row in campaigns),
                    "clicked": sum(row.clicked_count for row in campaigns),
                    "replied": sum(row.replied_count for row in campaigns),
                    "bounced": sum(row.bounced_count for row in campaigns),
                    "meetings": sum(row.meeting_count for row in campaigns),
                }
            )
        meetings = self._number(stats["meetings"])
        conversion = 0.1
        stats.update(
            {
                "product_id": str(product.id),
                "product_name": product.name,
                "estimated_revenue": meetings
                * conversion
                * (product.average_check + product.monthly_fee * 12),
            }
        )
        return stats

    async def get_campaign_stats(self, campaign_id: UUID, period: str = "30d") -> dict[str, object]:
        campaign = await self.db.get(Campaign, campaign_id)
        if not campaign or campaign.workspace_id != self.workspace_id:
            raise NotFoundError("Кампания не найдена")
        rows = await self._metrics(campaign_id=campaign_id, period=period)
        stats = (
            self._sum(rows)
            if rows
            else self._rates(
                {
                    "sent": campaign.sent_count,
                    "delivered": max(0, campaign.sent_count - campaign.bounced_count),
                    "opened": campaign.opened_count,
                    "clicked": campaign.clicked_count,
                    "replied": campaign.replied_count,
                    "bounced": campaign.bounced_count,
                    "meetings": campaign.meeting_count,
                }
            )
        )
        stats.update({"campaign_id": str(campaign.id), "campaign_name": campaign.name})
        return stats

    async def dashboard(self, period: str = "30d") -> dict[str, object]:
        products = list(
            (
                await self.db.scalars(
                    select(Product).where(
                        Product.workspace_id == self.workspace_id, Product.is_active.is_(True)
                    )
                )
            ).all()
        )
        product_stats = [await self.get_product_stats(product.id, period) for product in products]
        totals = self._sum(await self._metrics(period=period))
        estimated_revenue = 0.0
        for row in product_stats:
            estimated_revenue += self._number(row.get("estimated_revenue"))
        totals["estimated_revenue"] = estimated_revenue
        return {"period": period, "totals": totals, "products": product_stats}

    async def contact_stats(self, contact_id: UUID) -> dict[str, object]:
        contact = await self.db.get(Contact, contact_id)
        if not contact or contact.workspace_id != self.workspace_id:
            raise NotFoundError("Контакт не найден")
        messages = list(
            (
                await self.db.scalars(
                    select(EmailMessage).where(
                        EmailMessage.workspace_id == self.workspace_id,
                        EmailMessage.contact_id == contact_id,
                    )
                )
            ).all()
        )
        return {
            "contact_id": str(contact.id),
            "email": contact.email,
            "status": contact.status,
            "sent": sum(row.sent_at is not None for row in messages),
            "opened": sum(row.opened_at is not None for row in messages),
            "clicked": sum(row.clicked_at is not None for row in messages),
            "replied": contact.has_replied,
            "unsubscribed": contact.is_unsubscribed,
        }

    async def trends(
        self, period: str = "30d", product_id: UUID | None = None
    ) -> list[dict[str, object]]:
        rows = await self._metrics(product_id=product_id, period=period)
        by_date: dict[date, list[DailyMetric]] = {}
        for row in rows:
            by_date.setdefault(row.date, []).append(row)
        return [
            {"date": day.isoformat(), **self._sum(group)} for day, group in sorted(by_date.items())
        ]

    async def generate_report(self, data: GenerateReportRequest) -> AnalyticsReport:
        payload: object
        if data.report_type == "dashboard":
            payload = await self.dashboard(data.period)
        elif data.report_type == "products" and data.product_id:
            payload = await self.get_product_stats(data.product_id, data.period)
        elif data.report_type == "campaigns" and data.campaign_id:
            payload = await self.get_campaign_stats(data.campaign_id, data.period)
        else:
            payload = await self.trends(data.period, data.product_id)
        if data.format == "json":
            content = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            rows = payload if isinstance(payload, list) else [payload]
            flattened = [self._flatten(row) for row in rows if isinstance(row, dict)]
            buffer = io.StringIO()
            fields = sorted({key for row in flattened for key in row})
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(flattened)
            content = buffer.getvalue()
        row = AnalyticsReport(
            workspace_id=self.workspace_id,
            report_type=data.report_type,
            format=data.format,
            parameters=data.model_dump(mode="json"),
            content=content,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    @staticmethod
    def _flatten(row: dict[str, object]) -> dict[str, object]:
        return {
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        }

    async def get_report(self, report_id: UUID) -> AnalyticsReport:
        row = await self.db.scalar(
            select(AnalyticsReport).where(
                AnalyticsReport.id == report_id, AnalyticsReport.workspace_id == self.workspace_id
            )
        )
        if not row:
            raise NotFoundError("Отчёт не найден")
        return row

    async def aggregate_daily(self, day: date | None = None) -> int:
        target = day or datetime.now(UTC).date()
        start = datetime.combine(target, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        campaigns = list(
            (
                await self.db.scalars(
                    select(Campaign).where(Campaign.workspace_id == self.workspace_id)
                )
            ).all()
        )
        updated = 0
        for campaign in campaigns:
            messages = list(
                (
                    await self.db.scalars(
                        select(EmailMessage).where(
                            EmailMessage.campaign_id == campaign.id,
                            EmailMessage.created_at >= start,
                            EmailMessage.created_at < end,
                        )
                    )
                ).all()
            )
            if not messages:
                continue
            metric = await self.db.scalar(
                select(DailyMetric).where(
                    DailyMetric.campaign_id == campaign.id, DailyMetric.date == target
                )
            )
            if not metric:
                metric = DailyMetric(
                    workspace_id=self.workspace_id,
                    campaign_id=campaign.id,
                    product_id=campaign.product_id,
                    date=target,
                )
                self.db.add(metric)
            metric.sent_count = sum(row.sent_at is not None for row in messages)
            metric.delivered_count = sum(row.delivered_at is not None for row in messages)
            metric.opened_count = sum(row.opened_at is not None for row in messages)
            metric.clicked_count = sum(row.clicked_at is not None for row in messages)
            metric.bounced_count = sum(
                row.bounced or row.bounced_at is not None for row in messages
            )
            contact_ids = {row.contact_id for row in messages if row.contact_id}
            changed_contacts = (
                list(
                    (
                        await self.db.scalars(
                            select(Contact).where(
                                Contact.id.in_(contact_ids),
                                Contact.updated_at >= start,
                                Contact.updated_at < end,
                            )
                        )
                    ).all()
                )
                if contact_ids
                else []
            )
            metric.replied_count = sum(row.has_replied for row in changed_contacts)
            metric.meeting_count = sum(row.status == "meeting_booked" for row in changed_contacts)
            updated += 1
        await self.db.flush()
        return updated
