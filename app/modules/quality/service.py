from __future__ import annotations

import re

from app.modules.quality.schemas import QualityReport


class QualityChecker:
    SPAM_WORDS_RU = ("бесплатно", "срочно", "гарантия", "100%", "акция", "скидка")
    SPAM_WORDS_EN = ("free", "urgent", "guarantee", "act now", "click here")
    CTA_RE = re.compile(
        r"(звонк|встреч|ссылк|подробн|расскаж|обсуд|ответ|созвон|"
        r"book|call|meeting|reply|learn more)",
        re.IGNORECASE,
    )
    VARIABLE_RE = re.compile(r"{{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*}}")

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None

    def check(self, html: str, text: str, subject: str = "") -> QualityReport:
        issues: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []
        combined = f"{subject}\n{text}"
        for word in self.SPAM_WORDS_RU + self.SPAM_WORDS_EN:
            if self._contains(combined, word):
                warnings.append(f"Спам-слово: «{word}»")
        letters = [char for char in combined if char.isalpha()]
        caps_ratio = sum(char.isupper() for char in letters) / len(letters) if letters else 0
        if caps_ratio > 0.3 and len(letters) >= 10:
            warnings.append("Слишком много заглавных букв")
        if combined.count("!") > 3:
            warnings.append("Больше 3 восклицательных знаков")
        if not self.VARIABLE_RE.search(f"{html} {subject}"):
            issues.append("Нет переменных — письмо не персонализировано")
        words_count = len(re.findall(r"\b[\w'-]+\b", text, re.UNICODE))
        if words_count < 50:
            warnings.append("Письмо слишком короткое — целевой диапазон 50–400 слов")
        elif words_count > 400:
            warnings.append("Письмо слишком длинное — целевой диапазон 50–400 слов")
        if not self.CTA_RE.search(text):
            warnings.append("Нет явного призыва к действию")
        image_count = len(re.findall(r"<img\b", html, re.IGNORECASE))
        if image_count > 0 and words_count / image_count < 40:
            warnings.append("Слишком много изображений относительно объёма текста")
        if "unsubscribe" not in html.casefold() and "отпис" not in html.casefold():
            issues.append("Нет ссылки отписки")
        if not subject.strip():
            warnings.append("Не задана тема письма")
        elif len(subject) > 60:
            suggestions.append("Сократите тему до 60 символов, чтобы она не обрезалась")
        if words_count > 0 and not re.search(r"https?://|mailto:", html, re.IGNORECASE):
            suggestions.append("Добавьте одну релевантную ссылку, если CTA требует перехода")
        score = max(0, 100 - len(issues) * 20 - len(warnings) * 5)
        return QualityReport(
            score=score,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions,
            words_count=words_count,
            caps_ratio=round(caps_ratio, 4),
            image_count=image_count,
        )
