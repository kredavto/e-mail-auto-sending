from unittest.mock import AsyncMock, Mock

import pytest

from app.integrations.resilience import IntegrationError
from app.modules.hunter.service import HunterService
from app.modules.linkedin.parser import SalesNavigatorParser


def test_sales_navigator_csv_parser() -> None:
    csv_content = (
        "First Name,Last Name,LinkedIn URL,Company Name,Company Website,Title\n"
        "Anna,Ivanova,https://www.linkedin.com/in/anna-ivanova/,Acme,https://acme.example,CEO\n"
    )
    profile = SalesNavigatorParser().parse(csv_content)[0]
    assert profile["linkedin_id"] == "anna-ivanova"
    assert profile["company_domain"] == "acme.example"
    assert profile["headline"] == "CEO"


def test_sales_navigator_requires_columns() -> None:
    with pytest.raises(IntegrationError):
        SalesNavigatorParser().parse("First Name,Last Name\nAnna,Ivanova\n")


@pytest.mark.asyncio
async def test_hunter_only_accepts_confidence_70_or_more() -> None:
    client = Mock(find_email=AsyncMock(return_value={"email": "a@acme.io", "confidence": 69}))
    service = HunterService(client)
    assert await service.find_confident_email("acme.io", "A", "B") is None
    client.find_email.return_value = {"email": "a@acme.io", "confidence": 70}
    assert await service.find_confident_email("acme.io", "A", "B") == {
        "email": "a@acme.io",
        "confidence": 70,
    }
