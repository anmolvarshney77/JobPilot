from __future__ import annotations

import logging

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://apply.workable.com/api/v3/accounts"


def parse_jobs(slug: str, data: dict) -> list[RawJob]:
    jobs = []
    for result in data.get("results", []):
        location = result.get("location", {})
        if isinstance(location, dict):
            city = location.get("city", "")
            country = location.get("country", "")
            is_remote = location.get("remote", False)
        else:
            city = country = ""
            is_remote = False

        location_parts = [p for p in [city, country] if p]
        location_raw = ", ".join(location_parts) or None
        if is_remote:
            location_raw = f"Remote, {location_raw}" if location_raw else "Remote"

        desc_obj = result.get("description", {})
        if isinstance(desc_obj, dict):
            description = strip_html(desc_obj.get("html") or "")
        elif desc_obj:
            description = strip_html(str(desc_obj))
        else:
            description = ""

        shortcode = result.get("shortcode", "")
        jobs.append(
            RawJob(
                source="workable",
                external_id=result.get("id") or shortcode,
                company_name=slug,
                title=result.get("title", ""),
                location_raw=location_raw,
                url=result.get("url", f"https://apply.workable.com/{slug}/j/{shortcode}"),
                apply_url=result.get("url"),
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
    url = f"{_BASE}/{slug}/jobs?details=true"
    try:
        data = get_json(client, url, limiter)
        return parse_jobs(slug, data)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            logger.info("workable: no public endpoint for slug=%s (HTTP %s)", slug, exc.response.status_code)
            return []
        logger.error("workable fetch failed for slug=%s: %s", slug, exc)
        return []
    except Exception as exc:
        logger.error("workable fetch failed for slug=%s: %s", slug, exc)
        return []
