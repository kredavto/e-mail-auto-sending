from typing import Any

# Keep indexed/short database columns compatible; retain complete spreadsheet values in JSONB.
CONTACT_TEXT_LIMITS = {
    "full_name": 255,
    "first_name": 100,
    "last_name": 100,
    "patronymic": 100,
    "company": 255,
    "position": 100,
    "industry": 100,
    "phone": 50,
    "current_site_url": 255,
    "company_size": 50,
    "annual_revenue_tier": 50,
    "source": 50,
    "linkedin_url": 500,
    "tenchat_user_id": 100,
}


def normalize_contact_text(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    custom = dict(data.get("custom_fields") or {})
    for field, limit in CONTACT_TEXT_LIMITS.items():
        value = result.get(field)
        if value is None:
            if field in result and field in {"full_name", "company", "position", "source"}:
                result[field] = ""
            continue
        value = str(value)
        if len(value) > limit:
            base = f"import_original_{field}"
            key, suffix = base, 2
            while key in custom and custom[key] != value:
                key = f"{base}_{suffix}"
                suffix += 1
            custom[key] = value
            value = value[:limit]
        result[field] = value
    result["custom_fields"] = custom
    if result.get("tags") is None:
        result.pop("tags", None)
    return result
