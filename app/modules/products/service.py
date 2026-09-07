import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit import audited
from app.modules.contacts.models import Contact
from app.modules.products.models import Product
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import ProductCreate, ProductMatch, ProductResponse, ProductUpdate


class ProductService:
    def __init__(self, db: AsyncSession, workspace_id: UUID) -> None:
        self.db = db
        self.repo = ProductRepository(db, workspace_id)
        self.workspace_id = workspace_id

    async def create(self, data: ProductCreate) -> Product:
        if await self.repo.by_slug(data.slug):
            raise ConflictError("Направление с таким slug уже существует")
        return await self.repo.add(Product(workspace_id=self.workspace_id, **data.model_dump()))

    @audited("product.updated", "product")
    async def update(self, product_id: UUID, data: ProductUpdate) -> Product:
        product = await self.repo.get(product_id)
        if not product:
            raise NotFoundError("Направление не найдено")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(product, field, value)
        return product

    @staticmethod
    def score_contact(product: Product, contact: Contact) -> tuple[float, list[str]]:
        target = product.target_audience or {}
        score = 0.0
        reasons: list[str] = []
        industries = target.get("industries", [])
        sizes = target.get("company_sizes", [])
        revenues = target.get("annual_revenue", [])
        if contact.industry and (contact.industry in industries or "Любые" in industries):
            score += 0.4
            reasons.append("industry")
        if contact.company_size and (contact.company_size in sizes or "Любые" in sizes):
            score += 0.3
            reasons.append("company_size")
        if contact.annual_revenue_tier and (
            contact.annual_revenue_tier in revenues or "Любая" in revenues
        ):
            score += 0.3
            reasons.append("annual_revenue")
        return round(score, 2), reasons

    async def match(self, contact: Contact) -> list[ProductMatch]:
        matches = []
        for product in await self.repo.list_all(active_only=True):
            score, reasons = self.score_contact(product, contact)
            matches.append(
                ProductMatch(
                    product=ProductResponse.model_validate(product), score=score, reasons=reasons
                )
            )
        return sorted(matches, key=lambda item: item.score, reverse=True)

    async def load_defaults(self) -> int:
        path = Path(__file__).parents[3] / "seed" / "products_default.json"
        rows: list[dict[str, object]] = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for row in rows:
            if not await self.repo.by_slug(str(row["slug"])):
                await self.create(ProductCreate.model_validate(row))
                count += 1
        return count
