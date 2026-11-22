from __future__ import annotations

import logging

import httpx

from jobpilot.db import Company, Job
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)

_ATS_TYPES = {"greenhouse", "lever", "ashby", "smartrecruiters", "personio", "recruitee", "workable"}


def check_liveness(
    job: Job,
    company: Company,
    client: httpx.Client,
    limiter: HostRateLimiter,
) -> bool:
    ats_type = company.ats_type
    if not ats_type or ats_type not in _ATS_TYPES or not company.ats_slug:
        return True  # can't check; assume live

    try:
        if ats_type == "greenhouse":
            from jobpilot.sources.greenhouse import fetch
        elif ats_type == "lever":
            from jobpilot.sources.lever import fetch
        elif ats_type == "ashby":
            from jobpilot.sources.ashby import fetch
        elif ats_type == "smartrecruiters":
            from jobpilot.sources.smartrecruiters import fetch
        elif ats_type == "personio":
            from jobpilot.sources.personio import fetch
        elif ats_type == "recruitee":
            from jobpilot.sources.recruitee import fetch
        elif ats_type == "workable":
            from jobpilot.sources.workable import fetch
        else:
            return True

        raw_jobs = fetch(company.ats_slug, client, limiter)
        for rj in raw_jobs:
            if rj.external_id == job.external_id:
                return True
        return False

    except Exception as exc:
        logger.warning(
            "liveness check failed for job_id=%s company=%s: %s",
            job.id,
            company.normalized_name,
            exc,
        )
        return True  # network failure → assume live
