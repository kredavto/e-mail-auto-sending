import csv
from io import StringIO
from urllib.parse import urlparse

from app.integrations.resilience import IntegrationError


class SalesNavigatorParser:
    REQUIRED_COLUMNS = {"First Name", "Last Name", "LinkedIn URL", "Company Name"}

    def parse(self, csv_content: str) -> list[dict[str, str]]:
        reader = csv.DictReader(StringIO(csv_content.lstrip("\ufeff")))
        columns = set(reader.fieldnames or [])
        missing = self.REQUIRED_COLUMNS - columns
        if missing:
            raise IntegrationError(
                f"Sales Navigator CSV missing columns: {', '.join(sorted(missing))}"
            )
        profiles: list[dict[str, str]] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            linkedin_url = row.get("LinkedIn URL", "").strip()
            linkedin_id = self._extract_id_from_url(linkedin_url)
            if not linkedin_id:
                raise IntegrationError(f"Invalid LinkedIn URL at row {row_number}")
            if linkedin_id in seen:
                continue
            seen.add(linkedin_id)
            profiles.append(
                {
                    "linkedin_id": linkedin_id,
                    "first_name": row.get("First Name", "").strip(),
                    "last_name": row.get("Last Name", "").strip(),
                    "headline": row.get("Title", "").strip(),
                    "company_name": row.get("Company Name", "").strip(),
                    "company_domain": self._domain(
                        row.get("Company Website", "") or row.get("Company Domain", "")
                    ),
                    "industry": row.get("Industry", "").strip(),
                    "location": row.get("Location", "").strip(),
                    "profile_url": linkedin_url,
                }
            )
        return profiles

    @staticmethod
    def _extract_id_from_url(url: str) -> str:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        if parsed.netloc.casefold() not in {"linkedin.com", "www.linkedin.com"}:
            return ""
        parts = [part for part in parsed.path.split("/") if part]
        return parts[1].casefold() if len(parts) >= 2 and parts[0] == "in" else ""

    @staticmethod
    def _domain(value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value if "://" in value else f"https://{value}")
        return (parsed.hostname or "").removeprefix("www.").casefold()
