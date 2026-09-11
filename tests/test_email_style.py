import pytest

from app.core.exceptions import AppError
from app.modules.editor.service import EditorService
from app.modules.editor.style import parse_style, readable_text
from app.shared.email_footer import with_unsubscribe_footer


def document(background="#1746a2"):
    return {
        "type": "doc",
        "attrs": {
            "emailStyle": {
                "background": background,
                "buttonBackground": "#ffffff",
                "font": "serif",
                "fontSize": 18,
                "radius": 12,
            }
        },
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Пример письма"}]},
            {
                "type": "caseStudyBlock",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Пример кейса"}]}
                ],
            },
            {"type": "ctaButton", "attrs": {"label": "Открыть", "url": "https://example.com"}},
        ],
    }


@pytest.mark.parametrize("background", ["#000000", "#1746a2", "#a71930", "#145c40", "#54278a"])
def test_dark_style_compile_preview_and_sender_footer(background):
    compiled, text, *_ = EditorService().compile(document(background))
    assert f'bgcolor="{background}"' in compiled
    assert f"background:{background}" in compiled
    assert "color:#ffffff" in compiled
    assert "font-size:18px" in compiled
    assert "font-family:Georgia," in compiled
    assert "border-radius:12px" in compiled
    assert "Пример письма" in text
    assert "color:#000000" in compiled  # White CTA has black text.
    final = with_unsubscribe_footer(compiled, "https://example.com/unsubscribe/id")
    assert 'data-footer-color="#ffffff"' in final
    assert "https://example.com/unsubscribe/id" in final
    assert "color:#ffffff;text-decoration:underline" in final
    assert EditorService().preview(document(background), {}) == compiled


@pytest.mark.parametrize(
    "patch",
    [
        {"background": '";background:url(https://evil.test)'},
        {"background": "{{secret}}"},
        {"buttonBackground": "red"},
        {"font": "serif;display:none"},
        {"font": []},
        {"fontSize": True},
        {"fontSize": 999},
        {"radius": -1},
    ],
)
def test_invalid_style_is_rejected(patch):
    state = document()
    state["attrs"]["emailStyle"].update(patch)
    with pytest.raises(AppError):
        EditorService().compile(state)


def test_legacy_and_malformed_style():
    assert parse_style({}).background == "#ffffff"
    assert readable_text("#ffffff") == "#000000"
    with pytest.raises(AppError):
        parse_style({"attrs": {"emailStyle": "red"}})
