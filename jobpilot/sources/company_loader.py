from __future__ import annotations

import logging
from pathlib import Path

import httpx
import yaml

from jobpilot.sources.normalizer import normalize_company_name
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)


def load_companies_yaml(path: str | Path = "companies.yaml") -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"companies.yaml not found at {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("companies", [])


def seed_companies(session, companies_yaml_path: str | Path = "companies.yaml") -> int:
    from jobpilot.db import Company

    companies = load_companies_yaml(companies_yaml_path)
    inserted = 0
    for entry in companies:
        name = entry.get("name", "")
        normalized = normalize_company_name(name)
        existing = session.execute(
            __import__("sqlalchemy").select(Company).where(Company.normalized_name == normalized)
        ).scalar_one_or_none()
        if existing is None:
            company = Company(
                name=name,
                normalized_name=normalized,
                ats_type=entry.get("ats_type"),
                ats_slug=entry.get("ats_slug"),
                verified=entry.get("verified", False),
                source_discovered_from="companies.yaml",
            )
            session.add(company)
            inserted += 1
        else:
            # Update slug/type if companies.yaml has them and DB doesn't
            if existing.ats_slug is None and entry.get("ats_slug"):
                existing.ats_slug = entry["ats_slug"]
            if existing.ats_type is None and entry.get("ats_type"):
                existing.ats_type = entry["ats_type"]
    session.flush()
    return inserted


def discover_ats(
    company_name: str,
    client: httpx.Client,
    limiter: HostRateLimiter,
) -> tuple[str, str] | None:
    """Probe Greenhouse, Lever, Ashby with candidate slugs. Returns (ats_type, slug) or None."""
    from jobpilot.sources import greenhouse, lever, ashby

    base = company_name.lower().strip()
    slug_candidates = [
        base.replace(" ", "-"),
        base.replace(" ", ""),
        base,
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    slugs: list[str] = []
    for s in slug_candidates:
        if s not in seen:
            seen.add(s)
            slugs.append(s)

    for slug in slugs:
        # Greenhouse
        try:
            jobs = greenhouse.fetch(slug, client, limiter)
            if jobs:
                logger.info("discover_ats: found greenhouse slug=%s for %s", slug, company_name)
                return ("greenhouse", slug)
        except Exception:
            pass

        # Lever
        try:
            jobs = lever.fetch(slug, client, limiter)
            if jobs:
                logger.info("discover_ats: found lever slug=%s for %s", slug, company_name)
                return ("lever", slug)
        except Exception:
            pass

        # Ashby
        try:
            jobs = ashby.fetch(slug, client, limiter)
            if jobs:
                logger.info("discover_ats: found ashby slug=%s for %s", slug, company_name)
                return ("ashby", slug)
        except Exception:
            pass

    return None
