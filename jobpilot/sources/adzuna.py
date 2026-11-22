from __future__ import annotations

import logging
import os

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_json
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

# Country codes supported by Adzuna API (as of 2024)
_SUPPORTED_COUNTRIES = {"gb", "us", "de", "nl", "pl", "sg", "ae"}
# Countries in typical target list that Adzuna does NOT support
_UNSUPPORTED_COUNTRIES = {"IE", "SE", "DK", "ES", "PT"}


def parse_jobs(data: dict, country: str) -> list[RawJob]:
    jobs = []
    for result in data.get("results", []):
        location_obj = result.get("location", {})
        location_raw = (
            location_obj.get("display_name") if isinstance(location_obj, dict) else None
        )
        company_obj = result.get("company", {})
        company_name = (
            company_obj.get("display_name", "") if isinstance(company_obj, dict) else ""
        )
        description = strip_html(result.get("description", ""))
        jobs.append(
            RawJob(
                source="adzuna",
                external_id=str(result.get("id", "")),
                company_name=company_name,
                title=result.get("title", ""),
                location_raw=location_raw,
                url=result.get("redirect_url", ""),
                apply_url=result.get("redirect_url"),
                description=description[:50000] if description else None,
                posted_at=None,
                salary_min=float(result["salary_min"]) if result.get("salary_min") is not None else None,
                salary_max=float(result["salary_max"]) if result.get("salary_max") is not None else None,
                salary_currency=None,
                sponsorship_signal="unknown",
                required_languages=[],
                extra={"country": country},
            )
        )
    return jobs


def fetch_all(
    target_countries: list[str],
    core_titles: list[str],
    client: httpx.Client,
    limiter: HostRateLimiter,
) -> list[RawJob]:
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        logger.info("adzuna: ADZUNA_APP_ID/ADZUNA_APP_KEY not set, skipping")
        return []

    supported = [c for c in target_countries if c.lower() in _SUPPORTED_COUNTRIES]
    unsupported = [c for c in target_countries if c.upper() in _UNSUPPORTED_COUNTRIES]
    if unsupported:
        logger.info("adzuna: unsupported countries skipped: %s", unsupported)

    all_jobs: list[RawJob] = []
    for country in supported:
        for title in core_titles[:3]:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/{country.lower()}/search/1"
                f"?app_id={app_id}&app_key={app_key}&what={title}&results_per_page=50"
            )
            try:
                data = get_json(client, url, limiter)
                all_jobs.extend(parse_jobs(data, country))
            except Exception as exc:
                logger.error("adzuna failed country=%s title=%s: %s", country, title, exc)
    return all_jobs
