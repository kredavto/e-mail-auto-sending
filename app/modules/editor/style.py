import re
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import AppError

FONTS = {
    "sans": "Arial,Helvetica,sans-serif",
    "serif": "Georgia,'Times New Roman',serif",
    "modern": "Verdana,Geneva,sans-serif",
}


def readable_text(color: str) -> str:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return "#000000" if r * 0.2126 + g * 0.7152 + b * 0.0722 > 0.179 else "#ffffff"


@dataclass(frozen=True)
class EmailStyle:
    background: str = "#ffffff"
    button_background: str = "#d6f04a"
    font: str = "sans"
    font_size: int = 16
    radius: int = 6

    @property
    def text(self) -> str:
        return readable_text(self.background)

    @property
    def button_text(self) -> str:
        return readable_text(self.button_background)

    @property
    def family(self) -> str:
        return FONTS[self.font]


def parse_style(state: dict[str, Any]) -> EmailStyle:
    attrs = state.get("attrs") or {}
    if not isinstance(attrs, dict):
        raise AppError("Некорректное оформление письма")
    raw = attrs.get("emailStyle")
    if raw is None:
        return EmailStyle()
    if not isinstance(raw, dict):
        raise AppError("Некорректное оформление письма")
    bg, button = raw.get("background", "#ffffff"), raw.get("buttonBackground", "#d6f04a")
    if any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in (bg, button)):
        raise AppError("Цвета оформления должны быть в формате #RRGGBB")
    font, size, radius = raw.get("font", "sans"), raw.get("fontSize", 16), raw.get("radius", 6)
    if not isinstance(font, str) or font not in FONTS:
        raise AppError("Выберите шрифт из списка")
    if type(size) is not int or size not in (14, 16, 18, 20):
        raise AppError("Выберите размер текста из списка")
    if type(radius) is not int or radius not in (0, 6, 12, 24):
        raise AppError("Выберите скругление кнопок из списка")
    return EmailStyle(bg.lower(), button.lower(), font, size, radius)
