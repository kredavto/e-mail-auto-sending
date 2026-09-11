import html
import re

FOOTER_RE = re.compile(r'<p\s+data-unsubscribe-footer="true"[^>]*>.*?</p>', re.I | re.S)
LABEL = "Отписаться от рассылки"


def unsubscribe_footer(url: str) -> str:
    return (
        '<p data-unsubscribe-footer="true" style="margin:24px 0 0;'
        'font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;color:#69736b">'
        f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'style="font-size:12px;color:#69736b;text-decoration:underline">{LABEL}</a></p>'
    )


def with_unsubscribe_footer(body: str, url: str) -> str:
    footer = unsubscribe_footer(url)
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
