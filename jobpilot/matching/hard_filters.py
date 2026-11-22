from __future__ import annotations

import re
from datetime import datetime

from jobpilot.config import ProfileConfig
from jobpilot.db import Application, Company, Job
from jobpilot.sources.normalizer import normalize_company_name

SPONSORSHIP_REFUSE_PATTERNS: list[str] = [
    r"no\s+(?:visa\s+)?sponsorship",
    r"(?:unable|not\s+able)\s+to\s+sponsor",
    r"will\s+not\s+sponsor",
    r"(?:do|does)\s+not\s+(?:offer|provide)\s+(?:visa\s+)?sponsorship",
    r"(?:us|u\.s\.)\s+citizens?\s+only",
    r"security\s+clearance\s+required",
    r"must\s+(?:currently\s+)?(?:be|have)\s+(?:legally\s+)?authorized\s+to\s+work\s+\S+\s+without\s+sponsorship",
]

NEGATION_WORDS: set[str] = {
    "not", "no", "never", "without", "don't", "doesn't",
    "won't", "cannot", "can't", "neither", "nor",
}

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in SPONSORSHIP_REFUSE_PATTERNS]


def _has_negation_within(text: str, match_start: int, window_words: int = 5) -> bool:
    """True if any NEGATION_WORD appears within window_words words before match_start."""
    snippet = text[:match_start]
    words = snippet.split()
    return bool({w.strip(".,;:!?") for w in words[-window_words:]} & NEGATION_WORDS)


def detect_sponsorship_refusal(text: str) -> bool:
    """
    Return True only if the text contains an unambiguous sponsorship refusal.
    A match preceded by a negation within 5 words does NOT count (double-negation guard).
    """
    lower = text.lower()
    for pat in _COMPILED_PATTERNS:
        for m in pat.finditer(lower):
            if not _has_negation_within(lower, m.start()):
                return True
    return False


def filter_job(
    job: Job,
    profile: ProfileConfig,
    session: object,
    now: datetime,
) -> str | None:
    """
    Return filter_reason string if job should be dropped, else None.
    Checks in order:
    1. Company in exclude_companies
    2. Applied to same company within cooldown period
    3. Sponsorship refusal detected (when needs_visa_sponsorship)
    4. Posted more than 30 days ago
    """
    from sqlalchemy import select

    # 1. Exclude company
    if profile.exclude_companies:
        company = session.get(Company, job.company_id)
        if company:
            norm = normalize_company_name(company.name)
            excluded_norms = {normalize_company_name(e) for e in profile.exclude_companies}
            if norm in excluded_norms:
                return "exclude_company"

    # 2. Company cooldown
    company = session.get(Company, job.company_id)
    if company and profile.company_cooldown_days > 0:
        cutoff = now.replace(
            day=now.day,
            hour=0, minute=0, second=0, microsecond=0,
        )
        from datetime import timedelta
        cooldown_start = now - timedelta(days=profile.company_cooldown_days)
        recent_app = session.execute(
            select(Application)
            .join(Job, Application.job_id == Job.id)
            .where(
                Job.company_id == job.company_id,
                Application.submitted_at >= cooldown_start,
            )
        ).scalar_one_or_none()
        if recent_app:
            return "cooldown"

    # 3. Sponsorship refusal
    if profile.needs_visa_sponsorship and job.description:
        if detect_sponsorship_refusal(job.description):
            return "sponsorship_refused"

    # 4. Too old
    if job.posted_at is not None:
        from datetime import timedelta
        if (now - job.posted_at).days > 30:
            return "too_old"

    return None
