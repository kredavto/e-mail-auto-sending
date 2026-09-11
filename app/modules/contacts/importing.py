import re

from app.core.exceptions import AppError
from app.modules.contacts.schemas import MAX_IMPORT_CONTACTS, ContactCreate


def prepare_import_rows(rows: list[dict[str, object]]) -> tuple[list[ContactCreate], list[str]]:
    """Expand email lists before validation; one bad address must not discard its siblings."""
    allowed = set(ContactCreate.model_fields)
    contacts: list[ContactCreate] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        emails = [
            email.lower()
            for email in re.split(r"[,;\s]+", str(row.get("email") or "").strip())
            if email
        ]
        if not emails:
            errors.append(f"Строка {index}: отсутствует email.")
            continue
        for email in emails:
            try:
                contact = ContactCreate.model_validate(
                    {**{key: value for key, value in row.items() if key in allowed}, "email": email}
                )
            except ValueError:
                errors.append(
                    f"Строка {index}: некорректный email или данные контакта «{email}». "
                    "Корректные адреса строки обрабатываются отдельно."
                )
                continue
            if len(contacts) >= MAX_IMPORT_CONTACTS:
                raise AppError(
                    f"После разделения email получилось больше {MAX_IMPORT_CONTACTS} контактов. "
                    "Разделите файл; контакты не были сохранены."
                )
            contacts.append(contact)
    return contacts, errors
