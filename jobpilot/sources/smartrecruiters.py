from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://api.smartrecruiters.com/v1/companies"


def _get_description(
    slug: str, job_id: str, client: httpx.Client, limiter: HostRateLimiter
) -> str:
    url = f"{_BASE}/{slug}/postings/{job_id}"
    try:
        data = get_json(client, url, limiter)
        sections = data.get("jobAd", {}).get("sections", {})
        parts = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            sec = sections.get(key, {})
            text = sec.get("text") if isinstance(sec, dict) else None
            if text:
                parts.append(strip_html(text))
        return " ".join(parts)
    except Exception as exc:
        logger.warning("smartrecruiters description fetch failed %s/%s: %s", slug, job_id, exc)
        return ""


def parse_jobs(
    slug: str, data: dict, descriptions: dict[str, str] | None = None
) -> list[RawJob]:
    descriptions = descriptions or {}
    jobs = []
    for posting in data.get("content", []):
        job_id = posting.get("id", "")
        location = posting.get("location", {})
        city = location.get("city", "") if isinstance(location, dict) else ""
        country = location.get("country", "") if isinstance(location, dict) else ""
        location_parts = [p for p in [city, country] if p]
        location_raw = ", ".join(location_parts) or None

        released_raw = posting.get("releasedDate")
        posted_at: datetime | None = None
        if released_raw:
            try:
                posted_at = datetime.fromisoformat(
                    str(released_raw).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass

        description = descriptions.get(job_id, "")
        jobs.append(
            RawJob(
                source="smartrecruiters",
                external_id=job_id,
                company_name=slug,
                title=posting.get("name", ""),
                location_raw=location_raw,
                url=posting.get("ref", f"https://jobs.smartrecruiters.com/{slug}/{job_id}"),
                apply_url=posting.get("ref"),
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
    url = f"{_BASE}/{slug}/postings"
    try:
        data = get_json(client, url, limiter)
        descriptions: dict[str, str] = {}
        for posting in data.get("content", []):
            job_id = posting.get("id", "")
            if job_id:
                descriptions[job_id] = _get_description(slug, job_id, client, limiter)
        return parse_jobs(slug, data, descriptions)
    except Exception as exc:
        logger.error("smartrecruiters fetch failed for slug=%s: %s", slug, exc)
        return []
