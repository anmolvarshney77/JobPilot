from __future__ import annotations

import logging

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://boards-api.greenhouse.io/v1/boards"


def _detect_sponsorship(description: str) -> str:
    desc = description.lower()
    no_patterns = ["no sponsorship", "not sponsor", "unable to sponsor", "cannot sponsor",
                   "do not sponsor", "doesn't sponsor", "does not sponsor"]
    if any(p in desc for p in no_patterns):
        return "no"
    if "visa" in desc and "sponsor" in desc:
        return "yes"
    return "unknown"


def parse_jobs(slug: str, data: dict) -> list[RawJob]:
    jobs = []
    for job in data.get("jobs", []):
        description = strip_html(job.get("content") or "")
        location = job.get("location", {})
        location_raw = location.get("name") if isinstance(location, dict) else None
        jobs.append(
            RawJob(
                source="greenhouse",
                external_id=str(job["id"]),
                company_name=slug,
                title=job.get("title", ""),
                location_raw=location_raw,
                url=job.get("absolute_url", f"https://boards.greenhouse.io/{slug}/jobs/{job['id']}"),
                apply_url=job.get("absolute_url"),
                description=description[:50000] if description else None,
                posted_at=None,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                sponsorship_signal=_detect_sponsorship(description),
                required_languages=[],
                extra={},
            )
        )
    return jobs


def fetch(slug: str, client: httpx.Client, limiter: HostRateLimiter) -> list[RawJob]:
    url = f"{_BASE}/{slug}/jobs?content=true"
    try:
        data = get_json(client, url, limiter)
        return parse_jobs(slug, data)
    except Exception as exc:
        logger.error("greenhouse fetch failed for slug=%s: %s", slug, exc)
        return []
