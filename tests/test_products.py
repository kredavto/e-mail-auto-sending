from uuid import uuid4

from app.modules.contacts.models import Contact
from app.modules.products.models import Product
from app.modules.products.service import ProductService


def test_product_match_score_exact() -> None:
    product = Product(
        workspace_id=uuid4(),
        name="Premium sites",
        slug="premium-sites",
        category="digital",
        target_audience={
            "industries": ["IT"],
            "company_sizes": ["500+"],
            "annual_revenue": ["300M+"],
        },
    )
    contact = Contact(
        workspace_id=product.workspace_id,
        email="a@example.com",
        full_name="A",
        industry="IT",
        company_size="500+",
        annual_revenue_tier="300M+",
    )
    assert ProductService.score_contact(product, contact) == (
        1.0,
        ["industry", "company_size", "annual_revenue"],
    )


def test_product_match_score_partial() -> None:
    product = Product(
        workspace_id=uuid4(),
        name="Sites",
        slug="sites",
        category="digital",
        target_audience={"industries": ["IT"], "company_sizes": [], "annual_revenue": []},
    )
    contact = Contact(workspace_id=product.workspace_id, email="a@example.com", industry="IT")
    assert ProductService.score_contact(product, contact)[0] == 0.4
