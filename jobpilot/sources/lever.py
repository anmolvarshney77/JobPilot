from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://api.lever.co/v0/postings"


def parse_jobs(slug: str, data: list) -> list[RawJob]:
    jobs = []
    for posting in data:
        categories = posting.get("categories", {})
        location_raw = categories.get("location") if isinstance(categories, dict) else None
        created_ms = posting.get("createdAt")
        posted_at = datetime.fromtimestamp(created_ms / 1000) if created_ms else None
        description_html = posting.get("description", "") or ""
        description_plain = posting.get("descriptionPlain", "") or ""
        description = strip_html(description_html) or description_plain
        jobs.append(
            RawJob(
                source="lever",
                external_id=posting["id"],
                company_name=slug,
                title=posting.get("text", ""),
                location_raw=location_raw,
                url=posting.get("hostedUrl", ""),
                apply_url=posting.get("applyUrl"),
                description=description[:50000] if description else None,
                posted_at=posted_at,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                sponsorship_signal="unknown",
                required_languages=[],
                extra={},
            )
        )
    return jobs


def fetch(slug: str, client: httpx.Client, limiter: HostRateLimiter) -> list[RawJob]:
    url = f"{_BASE}/{slug}?mode=json"
    try:
        data = get_json(client, url, limiter)
        if isinstance(data, dict):
            data = data.get("data", [])
        return parse_jobs(slug, data)
    except Exception as exc:
        logger.error("lever fetch failed for slug=%s: %s", slug, exc)
        return []
