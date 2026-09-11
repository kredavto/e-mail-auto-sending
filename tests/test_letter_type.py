from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AppError
from app.modules.editor.service import EditorService
from app.modules.templates.schemas import TemplateCreate, TemplateUpdate
from app.modules.templates.service import TemplateService


def general_document(text="Предложение {{product_name}}"):
    return {
        "type": "doc",
        "attrs": {"letterType": "general"},
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": text}]},
            {"type": "ctaButton", "attrs": {"label": "Подробнее", "url": "https://example.com"}},
        ],
    }


def test_general_renders_identically_without_recipient_name():
    editor = EditorService()
    state = general_document()
    html, text, variables, _, _ = editor.compile(state)
    assert variables == ["product_name"]
    assert "Здравствуйте" not in html
    assert "Здравствуйте" not in text
    assert 'href="https://example.com"' in html
    assert editor.preview(state, {"product_name": "Услуга"}) == editor.preview(
        state, {"product_name": "Услуга", "first_name": "Анна", "company": "Компания"}
    )


@pytest.mark.parametrize(
    "value",
    [
        "{{first_name}}",
        "{{full_name}}",
        "{{company}}",
        "{{custom_city}}",
        "{{ first_name | default('') }}",
        "{% if email %}x{% endif %}",
        "{{cycler}}",
    ],
)
def test_general_rejects_recipient_data_and_expressions_in_body_and_subject(value):
    editor = EditorService()
    with pytest.raises(AppError, match="Общее письмо"):
        editor.compile(general_document(value))
    with pytest.raises(AppError, match="Общее письмо"):
        TemplateService(MagicMock(), uuid4())._compiled(general_document(), value)


def test_general_rejects_nested_variable_nodes_and_cta_personalization():
    for node in [
        {
            "type": "signatureBlock",
            "content": [{"type": "variable", "attrs": {"name": "full_name"}}],
        },
        {"type": "ctaButton", "attrs": {"label": "{{first_name}}", "url": "https://example.com"}},
    ]:
        state = general_document()
        state["content"].append(node)
        with pytest.raises(AppError, match="Общее письмо"):
            EditorService().compile(state)


def test_legacy_templates_keep_personalization_and_unknown_type_is_rejected():
    state = general_document("{{first_name}}")
    del state["attrs"]
    assert EditorService().letter_type(state) == "personalized"
    assert "Анна" in EditorService().preview(state, {"first_name": "Анна"})
    state["attrs"] = {"letterType": "unknown"}
    with pytest.raises(AppError, match="тип письма"):
        EditorService().compile(state)


async def test_type_survives_create_update_snapshot_and_rollback():
    service = TemplateService(MagicMock(), uuid4())
    service.repo = AsyncMock()
    data = TemplateCreate(
        name="Общая рассылка",
        category="first_contact",
        subject_template="Предложение",
        editor_state=general_document(),
    )
    item = await service.create(data)
    item.id, item.version = uuid4(), 1
    snapshot = service.repo.add_version.call_args.args[0]
    assert snapshot.editor_state["attrs"]["letterType"] == "general"
    assert item.variables == ["product_name"]
    service.repo.get.return_value = item
    personal = deepcopy(item.editor_state)
    personal["attrs"]["letterType"] = "personalized"
    await service.update(item.id, TemplateUpdate(editor_state=personal))
    assert item.editor_state["attrs"]["letterType"] == "personalized"
    service.repo.version.return_value = snapshot
    await service.rollback(item.id, 1)
    assert item.editor_state["attrs"]["letterType"] == "general"
    assert item.version == 3
