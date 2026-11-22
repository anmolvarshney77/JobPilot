from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://www.arbeitnow.com/api/job-board-api"


def parse_jobs(data: dict) -> list[RawJob]:
    jobs = []
    for item in data.get("data", []):
        description = strip_html(item.get("description", ""))
        visa_sponsorship = item.get("visa_sponsorship", False)

        created_raw = item.get("created_at")
        posted_at: datetime | None = None
        if created_raw:
            try:
                posted_at = datetime.fromisoformat(
                    str(created_raw).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        jobs.append(
            RawJob(
                source="arbeitnow",
                external_id=item.get("slug", ""),
                company_name=item.get("company_name", ""),
                title=item.get("title", ""),
                location_raw=item.get("location"),
                url=item.get("url", ""),
                apply_url=item.get("url"),
                description=description[:50000] if description else None,
                posted_at=posted_at,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                sponsorship_signal="yes" if visa_sponsorship else "unknown",
                required_languages=[],
                extra={"tags": item.get("tags", [])},
            )
        )
    return jobs


def fetch(client: httpx.Client, limiter: HostRateLimiter) -> list[RawJob]:
    all_jobs: list[RawJob] = []
    url: str | None = _BASE
    page = 0
    max_pages = 5
    while url and page < max_pages:
        try:
            data = get_json(client, url, limiter)
            all_jobs.extend(parse_jobs(data))
            links = data.get("links", {})
            url = links.get("next") if isinstance(links, dict) else None
            page += 1
        except Exception as exc:
            logger.error("arbeitnow fetch failed at page=%d: %s", page, exc)
            break
    return all_jobs
