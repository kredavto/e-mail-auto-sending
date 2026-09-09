"""Regenerate the tiny, synthetic workbook used in browser import tests."""

from pathlib import Path

from openpyxl import Workbook

book = Workbook()
book.active.title = "Описание"
book.active.append(["Это тестовый файл"])
book.active.append(["Выберите лист Контакты"])
sheet = book.create_sheet("Контакты")
sheet.append(["Email", "Ф.И.О.", "Компания", "ИНН"])
sheet.append(["ivan@example.com", "Иванов Иван", "Тест", "001234"])
target = Path(__file__).resolve().parents[1] / "frontend/e2e/fixtures/contacts.xlsx"
target.parent.mkdir(parents=True, exist_ok=True)
book.save(target)
