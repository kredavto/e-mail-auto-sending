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
