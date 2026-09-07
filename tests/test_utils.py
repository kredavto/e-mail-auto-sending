from app.shared.utils import is_valid_email, normalize_email, parse_full_name


def test_parse_russian_full_name() -> None:
    assert parse_full_name("Иванов Иван Иванович") == ("Иванов", "Иван", "Иванович")


def test_parse_single_name() -> None:
    assert parse_full_name("Иван") == ("", "Иван", None)


def test_normalize_and_validate_email() -> None:
    assert normalize_email("  USER@Example.COM ") == "user@example.com"
    assert is_valid_email("user@example.com")
    assert not is_valid_email("not-an-email")
