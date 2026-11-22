from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://remotive.com/api/remote-jobs"


def parse_jobs(data: dict, target_countries: list[str]) -> list[RawJob]:
    jobs = []
    for job in data.get("jobs", []):
        candidate_location = job.get("candidate_required_location", "") or ""

        # Keep worldwide/empty, broad regions, or any target country substring match
        loc_lower = candidate_location.lower().strip()
        _OPEN_REGIONS = {"worldwide", "anywhere", "global", "europe", "emea", "eu",
                         "apac", "asia", "latam", "americas"}
        keep = not loc_lower or loc_lower in _OPEN_REGIONS
        if not keep:
            # check if any open region keyword appears in a longer string
            if any(r in loc_lower for r in _OPEN_REGIONS):
                keep = True
        if not keep:
            for country in target_countries:
                if country.lower() in loc_lower:
                    keep = True
                    break
        if not keep:
            continue

        pub_raw = job.get("publication_date")
        posted_at: datetime | None = None
        if pub_raw:
            try:
                posted_at = datetime.fromisoformat(
                    str(pub_raw).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        description = strip_html(job.get("description", ""))
        jobs.append(
            RawJob(
                source="remotive",
                external_id=str(job.get("id", "")),
                company_name=job.get("company_name", ""),
                title=job.get("title", ""),
                location_raw=candidate_location or "Remote",
                url=job.get("url", ""),
                apply_url=job.get("url"),
                description=description[:50000] if description else None,
                posted_at=posted_at,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                sponsorship_signal="unknown",
                required_languages=[],
                extra={"job_type": job.get("job_type", "")},
            )
        )
    return jobs


def fetch(target_countries: list[str], client: httpx.Client, limiter: HostRateLimiter) -> list[RawJob]:
    try:
        data = get_json(client, _BASE, limiter)
        return parse_jobs(data, target_countries)
    except Exception as exc:
        logger.error("remotive fetch failed: %s", exc)
        return []
