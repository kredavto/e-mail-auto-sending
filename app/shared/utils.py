import re

from email_validator import EmailNotValidError, validate_email


def parse_full_name(full_name: str) -> tuple[str, str, str | None]:
    parts = [part for part in re.split(r"\s+", full_name.strip()) if part]
    if not parts:
        return "", "", None
    if len(parts) == 1:
        return "", parts[0], None
    surname, first_name, *rest = parts
    return surname, first_name, " ".join(rest) or None


def is_valid_email(value: str) -> bool:
    try:
        validate_email(value, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def normalize_email(value: str) -> str:
    return value.strip().casefold()
