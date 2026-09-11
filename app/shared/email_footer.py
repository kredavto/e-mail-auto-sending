import html
import re

FOOTER_RE = re.compile(r'<p\s+data-unsubscribe-footer="true"[^>]*>.*?</p>', re.I | re.S)
LABEL = "Отписаться от рассылки"


def unsubscribe_footer(url: str, color: str = "#69736b") -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#69736b"
    return (
        f'<p data-unsubscribe-footer="true" data-footer-color="{color}" style="margin:24px 0 0;'
        f'font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;color:{color}">'
        f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'style="font-size:12px;color:{color};text-decoration:underline">{LABEL}</a></p>'
    )


def with_unsubscribe_footer(body: str, url: str) -> str:
    existing = FOOTER_RE.search(body)
    color = (
        re.search(r'data-footer-color="(#[0-9a-fA-F]{6})"', existing.group()) if existing else None
    )
    footer = unsubscribe_footer(url, color.group(1) if color else "#69736b")
    if FOOTER_RE.search(body):
        # Keep the compiler's footer inside the email card; collapse duplicate system footers.
        first = True

        def replace(_match: re.Match[str]) -> str:
            nonlocal first
            value = footer if first else ""
            first = False
            return value

        return FOOTER_RE.sub(replace, body)
    if re.search(r"</body\s*>", body, re.I):
        return re.sub(r"</body\s*>", lambda m: footer + m.group(), body, count=1, flags=re.I)
    return body + footer


def with_unsubscribe_text(text: str, url: str) -> str:
    text = re.sub(r"(?:\r?\n)*Отписаться от рассылки: https?://[^\s]+", "", text)
    return text.rstrip() + f"\n\n{LABEL}: {url}"
