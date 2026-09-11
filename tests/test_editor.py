import pytest
from jinja2 import UndefinedError

from app.modules.editor.service import EditorService


def document() -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Здравствуйте, "},
                    {"type": "variable", "attrs": {"name": "first_name"}},
                ],
            },
            {"type": "ctaButton", "attrs": {"label": "Встреча", "url": "https://example.com"}},
            {
                "type": "unsubscribeBlock",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "unsubscribe"}]}
                ],
            },
        ],
    }


def test_compile_tiptap_to_safe_email() -> None:
    html, text, variables, score, warnings = EditorService().compile(document())
    assert 'width="640"' in html
    assert "{{first_name}}" in html
    assert variables == ["first_name"]
    assert "Здравствуйте" in text
    assert score == 100
    assert warnings == []


def test_preview_uses_strict_variables() -> None:
    assert "Анна" in EditorService().preview(document(), {"first_name": "Анна"})
    with pytest.raises(UndefinedError):
        EditorService().preview(document(), {})


def test_compiler_strips_scripts() -> None:
    state = {
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "<script>alert(1)</script>"}],
            }
        ]
    }
    html, *_ = EditorService().compile(state)
    assert "<script>" not in html


def test_multiple_cta_preserve_independent_links_and_document_order() -> None:
    state = {
        "type": "doc",
        "content": [
            {
                "type": "ctaButton",
                "attrs": {"label": "Каталог", "url": "https://example.com/catalog?a=1&b=2"},
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "Между кнопками"}]},
            {
                "type": "ctaButton",
                "attrs": {"label": "Встреча", "url": "https://example.com/meeting"},
            },
        ],
    }
    compiled, text, *_ = EditorService().compile(state)
    assert 'href="https://example.com/catalog?a=1&amp;b=2"' in compiled
    assert 'href="https://example.com/meeting"' in compiled
    assert compiled.index("Каталог") < compiled.index("Между кнопками") < compiled.index("Встреча")
    assert "Каталог: https://example.com/catalog?a=1&b=2" in text
    assert "Встреча: https://example.com/meeting" in text
    assert "data-drag-handle" not in compiled
    state["content"].reverse()
    preview = EditorService().preview(state, {})
    assert preview.index("Встреча") < preview.index("Между кнопками") < preview.index("Каталог")
