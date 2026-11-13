"""Small, dependency-free helpers."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def slugify(value: str) -> str:
    """Convert free text into a lowercase ASCII slug (``"São Paulo"`` -> ``"sao-paulo"``)."""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "unknown"


def content_hash(data: dict[str, Any]) -> str:
    """Stable SHA-256 of a JSON-serializable mapping, used to detect changed records."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Location:
    """A named geographic point."""

    name: str
    latitude: float
    longitude: float


def parse_csv(raw: str) -> list[str]:
    """Split a comma-separated string, trimming blanks and dropping empty items."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_locations(raw: str) -> list[Location]:
    """Parse ``"Name:lat:lon,Name:lat:lon"`` into locations.

    Raises:
        ValueError: if an entry is malformed or coordinates are out of range.
    """
    locations: list[Location] = []
    for entry in parse_csv(raw):
        parts = entry.rsplit(":", 2)
        if len(parts) != 3 or not parts[0].strip():
            raise ValueError(f"Invalid location '{entry}': expected 'Name:latitude:longitude'")
        name, lat_raw, lon_raw = parts[0].strip(), parts[1], parts[2]
        try:
            latitude, longitude = float(lat_raw), float(lon_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid coordinates in location '{entry}'") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(f"Coordinates out of range in location '{entry}'")
        locations.append(Location(name=name, latitude=latitude, longitude=longitude))
    if not locations:
        raise ValueError("At least one location is required")
    return locations


def parse_repositories(raw: str) -> list[str]:
    """Parse ``"owner/repo,owner/repo"`` and validate each entry."""
    repositories = parse_csv(raw)
    for repository in repositories:
        if not _REPO_PATTERN.match(repository):
            raise ValueError(f"Invalid repository '{repository}': expected 'owner/repo'")
    if not repositories:
        raise ValueError("At least one repository is required")
    return repositories


def parse_currencies(raw: str) -> list[str]:
    """Parse ``"BRL,EUR"`` into upper-case ISO 4217-style codes."""
    currencies = [item.upper() for item in parse_csv(raw)]
    for currency in currencies:
        if not _CURRENCY_PATTERN.match(currency):
            raise ValueError(f"Invalid currency code '{currency}': expected 3 letters")
    if not currencies:
        raise ValueError("At least one currency is required")
    return currencies
