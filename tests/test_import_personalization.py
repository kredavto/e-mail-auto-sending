from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.modules.contacts.personalization import contact_variables
from app.modules.contacts.schemas import ContactCreate
from app.modules.editor.service import EditorService
from tests.test_contacts_service import service


@pytest.mark.asyncio
async def test_explicit_name_parts_survive_import() -> None:
    contacts, _ = service()
    contact = await contacts.create(
        ContactCreate(
            email="person@example.com",
            full_name="Иван Петров",
            first_name="Иван",
            last_name="Петров",
            custom_fields={"city": "Москва", "inn": "001234"},
        )
    )
    assert contact.first_name == "Иван"
    assert contact.last_name == "Петров"
    context = contact_variables(contact, "Сайт")
    assert context["inn"] == "001234"
    assert context["city"] == "Москва"
    assert context["product_name"] == "Сайт"


def test_builtin_fields_cannot_be_overridden() -> None:
    contact = SimpleNamespace(
        email="right@example.com",
        full_name="Иванов Иван",
        custom_fields={
            "email": "wrong@example.com",
            "product_name": "wrong",
            "city": "Москва",
        },
    )
    result = contact_variables(contact, "Верный продукт")
    assert result["email"] == "right@example.com"
    assert result["product_name"] == "Верный продукт"
    assert result["city"] == "Москва"


def test_cta_html_hides_address_and_text_retains_fallback() -> None:
    state = {
        "content": [
            {
                "type": "ctaButton",
                "attrs": {
                    "label": "Обсудить задачу",
                    "url": "https://example.com/meeting?a=1&b=2",
                },
            }
        ]
    }
    html, text, *_ = EditorService().compile(state)
    assert 'href="https://example.com/meeting?a=1&amp;b=2"' in html
    assert 'target="_blank"' in html
    assert ">Обсудить задачу</a>" in html
    assert "Обсудить задачу: https://example.com/meeting?a=1&b=2" in text


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,x", "//example.com", "https://"]
)
def test_invalid_cta_is_rejected(url: str) -> None:
    with pytest.raises(AppError, match="CTA"):
        EditorService().compile({"content": [{"type": "ctaButton", "attrs": {"url": url}}]})


def test_personalized_preview_escapes_imported_markup() -> None:
    state = {
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "variable", "attrs": {"name": "city"}},
                ],
            }
        ]
    }
    html = EditorService().preview(state, {"city": '<img src=x onerror="alert(1)">'})
    assert "<img" not in html
    assert "&lt;img" in html
