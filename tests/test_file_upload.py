from app.modules.file_upload.service import FileService


def test_parse_semicolon_cp1251_csv() -> None:
    content = "email;full_name;company\nlead@example.com;Иванов Иван;Альфа\n".encode("cp1251")
    columns, rows = FileService.parse_content("contacts.csv", content)
    assert columns == ["email", "full_name", "company"]
    assert rows[0]["full_name"] == "Иванов Иван"


def test_parse_csv_falls_back_to_comma() -> None:
    columns, rows = FileService.parse_content("contacts.csv", b"email\nlead@example.com\n")
    assert columns == ["email"]
    assert rows == [{"email": "lead@example.com"}]
