import html
import re
from typing import Any
from urllib.parse import urlsplit

import bleach
from bleach.css_sanitizer import CSSSanitizer
from jinja2 import Environment, StrictUndefined, select_autoescape

from app.config import get_settings
from app.core.exceptions import AppError
from app.modules.editor.style import EmailStyle, parse_style
from app.shared.email_footer import unsubscribe_footer, with_unsubscribe_text

VARIABLE_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "u",
    "a",
    "ul",
    "ol",
    "li",
    "blockquote",
    "span",
    "div",
    "table",
    "tbody",
    "tr",
    "td",
    "img",
]
ALLOWED_ATTRS = {
    "a": ["href", "style", "target", "rel"],
    "span": ["style", "data-variable"],
    "div": ["style"],
    "table": ["style", "role", "width", "cellpadding", "cellspacing"],
    "td": ["style", "align"],
    "img": ["src", "alt", "width", "height", "style"],
}
CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "background",
        "background-color",
        "border",
        "border-left",
        "border-radius",
        "color",
        "display",
        "font-family",
        "font-size",
        "font-weight",
        "height",
        "line-height",
        "margin",
        "margin-top",
        "max-width",
        "padding",
        "padding-left",
        "text-align",
        "text-decoration",
        "width",
    ]
)


class EditorService:
    def letter_type(self, state: dict[str, object]) -> str:
        attrs = state.get("attrs") or {}
        if not isinstance(attrs, dict):
            raise AppError("Некорректный тип письма")
        kind = attrs.get("letterType", "personalized")
        if kind not in ("personalized", "general"):
            raise AppError("Выберите тип письма: «Персонализированное» или «Общее»")
        return str(kind)

    def validate_general(self, state: dict[str, object], *values: str) -> None:
        if self.letter_type(state) != "general":
            return
        remaining = re.sub(r"{{\s*product_name\s*}}", "", "\n".join(values))
        if any(marker in remaining for marker in ("{{", "{%", "{#")):
            names = sorted(set(VARIABLE_RE.findall(remaining)))
            detail = ", ".join("{{" + name + "}}" for name in names) or "переменные и выражения"
            raise AppError(
                f"Общее письмо: замените {detail} обычным текстом в теме и письме "
                "или выберите «Персонализированное». Доступна только общая "
                "переменная {{product_name}}; ФИО получателя не требуется."
            )

    def compile(self, state: dict[str, object]) -> tuple[str, str, list[str], int, list[str]]:
        theme = parse_style(state)
        content = state.get("content", [])
        nodes = content if isinstance(content, list) else []
        body = "".join(self._node(node, theme) for node in nodes if isinstance(node, dict))
        clean = bleach.clean(
            body,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=["http", "https", "mailto"],
            css_sanitizer=CSS_SANITIZER,
            strip=True,
        )
        preview_url = get_settings().public_base_url.rstrip("/") + "/api/v1/unsubscribe/preview"
        clean += unsubscribe_footer(preview_url, theme.text)
        wrapped = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="background:#f4f2ed;width:100%">'
            '<tr><td align="center" style="padding:24px 12px">'
            '<!--[if mso]><table role="presentation" width="640" cellpadding="0" '
            'cellspacing="0"><tr><td><![endif]-->'
            '<table role="presentation" width="640" cellpadding="0" cellspacing="0" '
            f'bgcolor="{theme.background}" style="width:100%;max-width:640px;'
            f'background:{theme.background}">'
            f'<tr><td bgcolor="{theme.background}" style="padding:32px;'
            f'background:{theme.background};font-family:{theme.family};'
            f'font-size:{theme.font_size}px;line-height:1.55;color:{theme.text}">{clean}</td></tr>'
            "</table><!--[if mso]></td></tr></table><![endif]--></td></tr></table>"
        )
        text = self._text(nodes).strip()
        self.validate_general(state, body, text)
        variables = sorted(set(VARIABLE_RE.findall(f"{body} {text}")))
        warnings: list[str] = []
        score = 100
        if not text:
            warnings.append("Пустое письмо")
            score -= 60
        if len(text) > 1500:
            warnings.append("Письмо длиннее 1500 символов")
            score -= 15
        if not any(node.get("type") == "ctaButton" for node in nodes if isinstance(node, dict)):
            warnings.append("Нет CTA-кнопки")
            score -= 10
        return wrapped, with_unsubscribe_text(text, preview_url), variables, max(0, score), warnings

    def preview(self, state: dict[str, object], variables: dict[str, str]) -> str:
        compiled, _, _, _, _ = self.compile(state)
        environment = Environment(
            autoescape=select_autoescape(default=True), undefined=StrictUndefined
        )
        return environment.from_string(compiled).render(**variables)

    def _node(self, node: dict[str, Any], theme: EmailStyle = EmailStyle()) -> str:
        node_type = node.get("type", "")
        attrs = node.get("attrs") or {}
        children = node.get("content") or []
        inner = "".join(self._node(child, theme) for child in children if isinstance(child, dict))
        if node_type == "text":
            value = html.escape(str(node.get("text", "")))
            for mark in node.get("marks") or []:
                mark_type = str(mark.get("type", "")) if isinstance(mark, dict) else ""
                value = {
                    "bold": f"<strong>{value}</strong>",
                    "italic": f"<em>{value}</em>",
                    "underline": f"<u>{value}</u>",
                }.get(mark_type, value)
            return value
        if node_type == "paragraph":
            return f'<p style="margin:0 0 16px">{inner or "&nbsp;"}</p>'
        if node_type == "heading":
            return (
                '<p style="margin:0 0 18px;font-size:24px;line-height:1.25;'
                f'font-weight:bold">{inner}</p>'
            )
        if node_type == "bulletList":
            return f'<ul style="margin:0 0 16px;padding-left:24px">{inner}</ul>'
        if node_type == "orderedList":
            return f'<ol style="margin:0 0 16px;padding-left:24px">{inner}</ol>'
        if node_type == "listItem":
            return f"<li>{inner}</li>"
        if node_type == "variable":
            name = str(attrs.get("name", ""))
            return f'<span data-variable="{html.escape(name)}">{{{{{html.escape(name)}}}}}</span>'
        if node_type == "ctaButton":
            raw_url = str(attrs.get("url", "")).strip()
            try:
                parsed = urlsplit(raw_url)
                valid_url = (
                    parsed.scheme in {"http", "https"}
                    and bool(parsed.netloc)
                    and not parsed.username
                    and not parsed.password
                )
            except ValueError:
                valid_url = False
            if not valid_url:
                raise AppError("CTA: укажите полный адрес с https:// или http://")
            label, url = (
                html.escape(str(attrs.get("label", "Подробнее"))),
                html.escape(raw_url, quote=True),
            )
            return (
                '<table role="presentation" cellpadding="0" cellspacing="0" '
                f'style="margin:24px 0"><tr><td style="background:{theme.button_background};'
                f'border-radius:{theme.radius}px">'
                f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                'style="display:inline-block;padding:13px 22px;'
                f'background:{theme.button_background};border-radius:{theme.radius}px;'
                f'color:{theme.button_text};'
                f'text-decoration:none;font-weight:bold">{label}</a></td></tr></table>'
            )
        if node_type == "emailVideo":
            source, poster = str(attrs.get("src", "")), str(attrs.get("poster", ""))
            base = get_settings().public_base_url.rstrip("/") + "/api/v1/files/"
            if not source.startswith(base + "videos/") or not re.fullmatch(
                r"[a-f0-9]{32}\.mp4", source[len(base + "videos/") :]
            ):
                raise AppError("Загрузите MP4 через кнопку «+ Фото / видео».")
            token = source.rsplit("/", 1)[-1].removesuffix(".mp4")
            if poster != f"{base}images/{token}.png":
                raise AppError("Некорректное превью видео. Загрузите MP4 повторно.")
            label = html.escape(str(attrs.get("alt") or "Смотреть видео")[:300], quote=True)
            label = label.replace("{", "&#123;").replace("}", "&#125;")
            return (
                f'<a href="{html.escape(source, quote=True)}" target="_blank" '
                'rel="noopener noreferrer" style="display:block;width:25%;max-width:144px;'
                f'margin:16px 0;color:{theme.text};text-decoration:underline">'
                f'<img src="{html.escape(poster, quote=True)}" alt="{label}" width="144" '
                'style="display:block;width:100%;max-width:144px;height:auto">'
                f'<span style="font-size:12px">▶ {label}</span></a>'
            )
        if node_type == "emailImage":
            source = str(attrs.get("src", ""))
            prefix = get_settings().public_base_url.rstrip("/") + "/api/v1/files/images/"
            if not source.startswith(prefix) or not re.fullmatch(
                r"[a-f0-9]{32}\.png", source[len(prefix) :]
            ):
                raise AppError("Загрузите изображение через кнопку «+ Изображение».")
            alt = html.escape(str(attrs.get("alt", ""))[:300], quote=True)
            alt = alt.replace("{", "&#123;").replace("}", "&#125;")
            return (
                f'<img src="{html.escape(source, quote=True)}" alt="{alt}" width="144" '
                'style="display:block;width:25%;max-width:144px;height:auto;margin:16px 0">'
            )
        if node_type == "signatureBlock":
            return (
                '<div style="margin-top:24px;border-top:1px solid #ddd;'
                f'padding-top:16px">{inner}</div>'
            )
        if node_type == "caseStudyBlock":
            return (
                '<div style="margin:20px 0;padding:16px;'
                f'border-left:4px solid {theme.button_background};'
                f'background:{theme.background};color:{theme.text}">{inner}</div>'
            )
        if node_type == "unsubscribeBlock":
            return ""  # Replaced with one mandatory footer after all content.
        if node_type == "hardBreak":
            return "<br>"
        return inner

    def _text(self, nodes: list[object]) -> str:
        chunks: list[str] = []
        for item in nodes:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "unsubscribeBlock":
                continue
            if item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            elif item.get("type") == "variable":
                chunks.append("{{" + str((item.get("attrs") or {}).get("name", "")) + "}}")
            elif item.get("type") == "ctaButton":
                attrs = item.get("attrs") or {}
                chunks.append(f'{attrs.get("label", "Подробнее")}: {attrs.get("url", "")}')
            elif item.get("type") == "emailImage":
                chunks.append("[Изображение]\n")
            elif item.get("type") == "emailVideo":
                chunks.append(f'Смотреть видео: {(item.get("attrs") or {}).get("src", "")}\n')
            children = item.get("content")
            if isinstance(children, list):
                chunks.append(self._text(children))
            if item.get("type") in {"paragraph", "heading", "listItem", "ctaButton"}:
                chunks.append("\n")
        return "".join(chunks)
