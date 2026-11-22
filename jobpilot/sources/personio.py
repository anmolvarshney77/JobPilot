from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from jobpilot.sources import RawJob
from jobpilot.sources.http_client import get_text
from jobpilot.sources.normalizer import strip_html
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)


def parse_jobs(slug: str, xml_text: str) -> list[RawJob]:
    jobs = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("personio XML parse error for slug=%s: %s", slug, exc)
        return []

    for position in root.findall(".//position"):
        pid = position.findtext("id") or ""
        name = position.findtext("name") or ""
        office = position.findtext("office") or ""

        desc_parts: list[str] = []
        for jd in position.findall(".//jobDescription"):
            value_el = jd.find("value")
            if value_el is not None and value_el.text:
                desc_parts.append(strip_html(value_el.text))
        description = " ".join(desc_parts)

        jobs.append(
            RawJob(
                source="personio",
                external_id=pid,
                company_name=slug,
                title=name,
                location_raw=office or None,
                url=f"https://{slug}.jobs.personio.de/job/{pid}",
                apply_url=f"https://{slug}.jobs.personio.de/job/{pid}",
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
    url = f"https://{slug}.jobs.personio.de/xml"
    try:
        xml_text = get_text(client, url, limiter)
        return parse_jobs(slug, xml_text)
    except Exception as exc:
        logger.error("personio fetch failed for slug=%s: %s", slug, exc)
        return []
