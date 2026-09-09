import re
from typing import Any

CONTACT_FIELDS = (
    "first_name",
    "full_name",
    "last_name",
    "patronymic",
    "company",
    "position",
    "email",
    "phone",
    "industry",
    "current_site_url",
    "company_size",
    "annual_revenue_tier",
)


def contact_variables(contact: Any, product_name: str) -> dict[str, str]:
    """One context for email and other sequence channels; built-ins cannot be overridden."""
    fields = getattr(contact, "custom_fields", None) or {}
    context = {
        key: str(value if value is not None else "")
        for key, value in fields.items()
        if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", key)
    }
    context.update({key: str(getattr(contact, key, None) or "") for key in CONTACT_FIELDS})
    context["product_name"] = product_name
    return context
