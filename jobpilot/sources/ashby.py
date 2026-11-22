from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import parse_salary, strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://api.ashbyhq.com/posting-api/job-board"


def parse_jobs(slug: str, data: dict) -> list[RawJob]:
    jobs = []
    for posting in data.get("jobPostings", []):
        description_html = posting.get("descriptionHtml") or ""
        description = strip_html(description_html)

        published_raw = posting.get("publishedAt")
        posted_at: datetime | None = None
        if published_raw:
            try:
                posted_at = datetime.fromisoformat(
                    str(published_raw).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass

        comp = posting.get("compensation") or {}
        salary_raw = comp.get("summaryShort") or comp.get("summary")
        sal_min, sal_max, sal_cur = parse_salary(salary_raw)

        pid = posting.get("id", "")
        jobs.append(
            RawJob(
                source="ashby",
                external_id=pid,
                company_name=slug,
                title=posting.get("title", ""),
                location_raw=posting.get("locationName"),
                url=f"https://jobs.ashbyhq.com/{slug}/{pid}",
                apply_url=f"https://jobs.ashbyhq.com/{slug}/{pid}",
                description=description[:50000] if description else None,
                posted_at=posted_at,
                salary_min=sal_min,
                salary_max=sal_max,
                salary_currency=sal_cur,
                sponsorship_signal="unknown",
                required_languages=[],
                extra={},
            )
        )
    return jobs


def fetch(slug: str, client: httpx.Client, limiter: HostRateLimiter) -> list[RawJob]:
    url = f"{_BASE}/{slug}?includeCompensation=true"
    try:
        data = get_json(client, url, limiter)
        return parse_jobs(slug, data)
    except Exception as exc:
        logger.error("ashby fetch failed for slug=%s: %s", slug, exc)
        return []
