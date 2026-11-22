from __future__ import annotations

import logging

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)


def parse_jobs(slug: str, data: dict) -> list[RawJob]:
    jobs = []
    for offer in data.get("offers", []):
        posting_slug = offer.get("slug") or str(offer.get("id", ""))
        description_html = offer.get("description") or ""
        description = strip_html(description_html)
        jobs.append(
            RawJob(
                source="recruitee",
                external_id=str(offer.get("id", "")),
                company_name=slug,
                title=offer.get("title", ""),
                location_raw=offer.get("location"),
                url=f"https://{slug}.recruitee.com/o/{posting_slug}",
                apply_url=f"https://{slug}.recruitee.com/o/{posting_slug}",
                description=description[:50000] if description else None,
                posted_at=None,
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
    url = f"https://{slug}.recruitee.com/api/offers/"
    try:
        data = get_json(client, url, limiter)
        return parse_jobs(slug, data)
    except Exception as exc:
        logger.error("recruitee fetch failed for slug=%s: %s", slug, exc)
        return []
