from __future__ import annotations

import hashlib
import math
import random
from statistics import NormalDist
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import IntegrationEvent, publish_enterprise_event
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.modules.ab_testing.models import ABTest, ABTestAssignment, ABTestVariant
from app.modules.ab_testing.schemas import ABTestCreate
from app.modules.campaigns.models import Campaign, CampaignContact
from app.modules.contacts.models import Contact
from app.modules.sender.models import EmailMessage
from app.modules.sequences.models import SequenceStep


class ABTestingService:
    METRIC_COUNTS = {
        "open_rate": "opened_count",
        "reply_rate": "replied_count",
        "click_rate": "clicked_count",
        "meeting_rate": "meeting_count",
    }

    def __init__(self, db: AsyncSession | None = None, workspace_id: UUID | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id

    @staticmethod
    def assign_variant(test_id: UUID, contact_id: UUID, split_ratio: float = 0.5) -> str:
        digest = hashlib.md5(f"{test_id}:{contact_id}".encode(), usedforsecurity=False).hexdigest()
        bucket = int(digest[:8], 16) % 1000
        return "A" if bucket < int(split_ratio * 1000) else "B"

    @staticmethod
    def _normal_cdf(value: float) -> float:
        return NormalDist().cdf(value)

    def frequentist_analysis(self, variant_a: Any, variant_b: Any, metric: str) -> dict[str, Any]:
        if metric not in self.METRIC_COUNTS:
            raise ValueError(f"Unsupported metric: {metric}")
        n_a, n_b = int(variant_a.sent_count), int(variant_b.sent_count)
        if n_a == 0 or n_b == 0:
            return {
                "p_value": 1.0,
                "is_significant": False,
                "confidence": 0.0,
                "winner": None,
                "lift": 0.0,
            }
        p_a, p_b = float(getattr(variant_a, metric)), float(getattr(variant_b, metric))
        p_pool = (p_a * n_a + p_b * n_b) / (n_a + n_b)
        se = math.sqrt(max(0.0, p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b)))
        z_score = (p_b - p_a) / se if se else 0.0
        p_value = max(0.0, min(1.0, 2 * (1 - self._normal_cdf(abs(z_score)))))
        return {
            "p_value": p_value,
            "is_significant": p_value < 0.05,
            "confidence": 1 - p_value,
            "winner": "B" if p_b > p_a else ("A" if p_a > p_b else None),
            "lift": (p_b - p_a) / p_a if p_a > 0 else (float("inf") if p_b else 0.0),
        }

    def bayesian_analysis(
        self, variant_a: Any, variant_b: Any, metric: str = "reply_rate", simulations: int = 10_000
    ) -> dict[str, Any]:
        count_field = self.METRIC_COUNTS.get(metric)
        if not count_field:
            raise ValueError(f"Unsupported metric: {metric}")
        success_a, success_b = (
            int(getattr(variant_a, count_field)),
            int(getattr(variant_b, count_field)),
        )
        sent_a, sent_b = int(variant_a.sent_count), int(variant_b.sent_count)
        seed = f"{metric}:{sent_a}:{success_a}:{sent_b}:{success_b}:{simulations}"
        rng = random.Random(seed)
        better = sum(
            rng.betavariate(1 + success_b, 1 + max(0, sent_b - success_b))
            > rng.betavariate(1 + success_a, 1 + max(0, sent_a - success_a))
            for _ in range(simulations)
        )
        probability = better / simulations
        return {
            "probability_b_better": probability,
            "probability_a_better": 1 - probability,
            "recommended": "B" if probability > 0.95 else ("A" if probability < 0.05 else None),
        }

    @staticmethod
    def calculate_required_sample_size(
        baseline: float, mde: float, confidence: float = 0.95, power: float = 0.8
    ) -> int:
        if not 0 < baseline < 1 or mde <= 0 or not 0 < confidence < 1 or not 0 < power < 1:
            raise ValueError("Invalid sample size parameters")
        p1, p2 = baseline, min(baseline * (1 + mde), 1 - 1e-9)
        if math.isclose(p1, p2):
            raise ValueError("MDE does not produce a measurable difference")
        z_alpha = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
        z_beta = NormalDist().inv_cdf(power)
        numerator = (
            z_alpha * math.sqrt(2 * p1 * (1 - p1))
            + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
        ) ** 2
        return math.ceil(numerator / ((p2 - p1) ** 2))

    def _require_db(self) -> AsyncSession:
        if self.db is None or self.workspace_id is None:
            raise RuntimeError("Database context is required")
        return self.db

    async def get(self, test_id: UUID) -> ABTest:
        db = self._require_db()
        item = await db.scalar(
            select(ABTest).where(ABTest.id == test_id, ABTest.workspace_id == self.workspace_id)
        )
        if not item:
            raise NotFoundError("A/B-тест не найден")
        return item

    async def variants(self, test_id: UUID) -> list[ABTestVariant]:
        db = self._require_db()
        return list(
            (
                await db.scalars(
                    select(ABTestVariant)
                    .where(ABTestVariant.test_id == test_id)
                    .order_by(ABTestVariant.variant_key)
                )
            ).all()
        )

    async def create(self, data: ABTestCreate) -> ABTest:
        db = self._require_db()
        campaign = await db.get(Campaign, data.campaign_id)
        if not campaign or campaign.workspace_id != self.workspace_id:
            raise NotFoundError("Кампания не найдена")
        item = ABTest(workspace_id=self.workspace_id, **data.model_dump(exclude={"variants"}))
        db.add(item)
        await db.flush()
        db.add_all([ABTestVariant(test_id=item.id, **row.model_dump()) for row in data.variants])
        return item

    async def start(self, test_id: UUID) -> ABTest:
        db, item = self._require_db(), await self.get(test_id)
        if item.status != "draft":
            raise ConflictError("Запустить можно только draft-тест")
        contact_ids = list(
            (
                await db.scalars(
                    select(CampaignContact.contact_id).where(
                        CampaignContact.campaign_id == item.campaign_id
                    )
                )
            ).all()
        )
        for contact_id in contact_ids:
            db.add(
                ABTestAssignment(
                    test_id=item.id,
                    contact_id=contact_id,
                    variant_key=self.assign_variant(item.id, contact_id, item.split_ratio),
                )
            )
        item.status = "running"
        return item

    async def stop(self, test_id: UUID) -> ABTest:
        item = await self.get(test_id)
        if item.status != "running":
            raise ConflictError("Остановить можно только запущенный тест")
        item.status = "completed"
        await self._publish_completed(item)
        return item

    async def _publish_completed(self, item: ABTest) -> None:
        db = self._require_db()
        assert self.workspace_id is not None
        await publish_enterprise_event(
            db,
            IntegrationEvent(
                workspace_id=self.workspace_id,
                resource_type="ab_test",
                resource_id=item.id,
                data={
                    "campaign_id": str(item.campaign_id),
                    "winner_variant": item.winner_variant,
                },
                kind="ab_test.completed",
            ),
        )

    async def assignment(self, test_id: UUID, contact_id: UUID) -> ABTestAssignment:
        db, item = self._require_db(), await self.get(test_id)
        contact = await db.get(Contact, contact_id)
        if not contact or contact.workspace_id != self.workspace_id:
            raise NotFoundError("Контакт не найден")
        existing = await db.scalar(
            select(ABTestAssignment).where(
                ABTestAssignment.test_id == test_id, ABTestAssignment.contact_id == contact_id
            )
        )
        if existing:
            return existing
        row = ABTestAssignment(
            test_id=test_id,
            contact_id=contact_id,
            variant_key=self.assign_variant(test_id, contact_id, item.split_ratio),
        )
        db.add(row)
        await db.flush()
        return row

    async def update_metrics(self, test_id: UUID) -> dict[str, Any]:
        db, item = self._require_db(), await self.get(test_id)
        variants = await self.variants(test_id)
        assignments = list(
            (
                await db.scalars(
                    select(ABTestAssignment).where(ABTestAssignment.test_id == test_id)
                )
            ).all()
        )
        by_key = {
            key: {a.contact_id for a in assignments if a.variant_key == key} for key in ("A", "B")
        }
        messages = list(
            (
                await db.scalars(
                    select(EmailMessage).where(EmailMessage.campaign_id == item.campaign_id)
                )
            ).all()
        )
        contacts = (
            {
                c.id: c
                for c in (
                    await db.scalars(
                        select(Contact).where(Contact.id.in_({a.contact_id for a in assignments}))
                    )
                ).all()
            }
            if assignments
            else {}
        )
        for variant in variants:
            rows = [m for m in messages if m.contact_id in by_key[variant.variant_key]]
            variant.sent_count = sum(
                m.sent_at is not None or m.status in {"sent", "delivered", "open", "click"}
                for m in rows
            )
            variant.opened_count = sum(m.opened_at is not None for m in rows)
            variant.clicked_count = sum(m.clicked_at is not None for m in rows)
            variant.replied_count = sum(
                bool(contacts.get(cid) and contacts[cid].has_replied)
                for cid in by_key[variant.variant_key]
            )
            variant.meeting_count = sum(
                bool(contacts.get(cid) and contacts[cid].status == "meeting_booked")
                for cid in by_key[variant.variant_key]
            )
            denominator = max(variant.sent_count, 1)
            variant.open_rate = variant.opened_count / denominator
            variant.reply_rate = variant.replied_count / denominator
            variant.click_rate = variant.clicked_count / denominator
            variant.meeting_rate = variant.meeting_count / denominator
        analysis = self.analyze_variants(variants, item.primary_metric, item.confidence_level)
        for variant in variants:
            variant.p_value = float(analysis["frequentist"]["p_value"])
        recommended = analysis["automatic_winner"]
        enough = (
            sum(v.sent_count for v in variants) >= item.sample_size if item.sample_size else True
        )
        if item.status == "running" and enough and recommended:
            item.winner_variant, item.status = recommended, "completed"
            await self._publish_completed(item)
        return analysis

    def analyze_variants(
        self, variants: list[ABTestVariant], metric: str, confidence_level: float = 0.95
    ) -> dict[str, Any]:
        if len(variants) != 2:
            raise AppError("A/B-тест должен содержать ровно два варианта")
        ordered = sorted(variants, key=lambda row: row.variant_key)
        frequentist = self.frequentist_analysis(ordered[0], ordered[1], metric)
        bayesian = self.bayesian_analysis(ordered[0], ordered[1], metric)
        frequentist["is_significant"] = frequentist["p_value"] < 1 - confidence_level
        probability = float(bayesian["probability_b_better"])
        bayesian["recommended"] = (
            "B"
            if probability > confidence_level
            else ("A" if probability < 1 - confidence_level else None)
        )
        auto = frequentist["winner"] if frequentist["is_significant"] else bayesian["recommended"]
        return {
            "metric": metric,
            "frequentist": frequentist,
            "bayesian": bayesian,
            "automatic_winner": auto,
        }

    async def results(self, test_id: UUID) -> dict[str, Any]:
        item = await self.get(test_id)
        variants = await self.variants(test_id)
        analysis = self.analyze_variants(variants, item.primary_metric, item.confidence_level)
        return {
            "test_id": str(item.id),
            "status": item.status,
            "winner_variant": item.winner_variant,
            "variants": variants,
            **analysis,
        }

    async def select_winner(self, test_id: UUID, variant_key: str | None = None) -> ABTest:
        item, variants = await self.get(test_id), await self.variants(test_id)
        chosen = (
            variant_key
            or self.analyze_variants(variants, item.primary_metric, item.confidence_level)[
                "automatic_winner"
            ]
        )
        if chosen not in {"A", "B"}:
            raise ConflictError("Статистически уверенный победитель ещё не определён")
        item.winner_variant, item.status = chosen, "completed"
        await self._publish_completed(item)
        return item

    async def apply_winner(self, test_id: UUID) -> ABTest:
        db, item = self._require_db(), await self.get(test_id)
        if not item.winner_variant:
            raise ConflictError("Сначала выберите победителя")
        winner = next(
            v for v in await self.variants(test_id) if v.variant_key == item.winner_variant
        )
        campaign = await db.get(Campaign, item.campaign_id)
        if campaign and item.test_type == "sender_name" and winner.sender_name:
            campaign.sender_name = winner.sender_name
        if campaign:
            steps = list(
                (
                    await db.scalars(
                        select(SequenceStep).where(
                            SequenceStep.sequence_id == campaign.sequence_id,
                            SequenceStep.step_type == "email",
                        )
                    )
                ).all()
            )
            for step in steps:
                if winner.template_id:
                    step.template_id = winner.template_id
                if winner.subject:
                    step.config = {**(step.config or {}), "subject_override": winner.subject}
        return item
