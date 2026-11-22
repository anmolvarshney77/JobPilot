from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawJob:
    source: str
    external_id: str
    company_name: str
    title: str
    location_raw: str | None
    url: str
    apply_url: str | None
    description: str | None
    posted_at: datetime | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    sponsorship_signal: str  # "yes" / "no" / "unknown"
    required_languages: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    source: str
    jobs: list[RawJob]
    error: str | None = None
