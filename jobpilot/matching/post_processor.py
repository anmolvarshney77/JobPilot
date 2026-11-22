from __future__ import annotations

from datetime import datetime, timedelta

from jobpilot.config import ProfileConfig
from jobpilot.matching.llm_scorer import ScoringResponse

_CEFR_LEVELS: dict[str, int] = {
    "none": 0,
    "a1": 1, "a2": 2,
    "b1": 3, "b2": 4,
    "c1": 5, "c2": 6,
    "native": 7,
}

# Map preferred cities to ISO country codes
_CITY_TO_COUNTRY: dict[str, str] = {
    "berlin": "DE", "munich": "DE", "münchen": "DE", "hamburg": "DE",
    "frankfurt": "DE", "cologne": "DE",
    "amsterdam": "NL", "rotterdam": "NL", "utrecht": "NL",
    "dublin": "IE", "cork": "IE",
    "london": "GB", "manchester": "GB", "edinburgh": "GB",
    "stockholm": "SE", "gothenburg": "SE",
    "copenhagen": "DK",
    "warsaw": "PL", "kraków": "PL",
    "madrid": "ES", "barcelona": "ES",
    "lisbon": "PT", "porto": "PT",
    "dubai": "AE",
    "singapore": "SG",
    "new york": "US", "san francisco": "US", "austin": "US",
}


def _preferred_countries(profile: ProfileConfig) -> set[str]:
    result: set[str] = set()
    for city in profile.preferred_cities:
        iso = _CITY_TO_COUNTRY.get(city.lower())
        if iso:
            result.add(iso)
    return result


def compute_final_score(
    llm_score: int,
    sponsorship_assessment: str,
    posted_at: datetime | None,
    job_countries: list[str],
    profile: ProfileConfig,
    salary_meets_expectation: bool | None,
    now: datetime,
) -> int:
    """Apply deterministic adjustments to the LLM score. Clamped to [0, 100]."""
    score = llm_score

    if sponsorship_assessment == "explicit_yes":
        score += 10
    elif sponsorship_assessment == "likely":
        score += 5
    elif sponsorship_assessment == "unlikely":
        score -= 10

    if posted_at is not None and (now - posted_at).days <= 3:
        score += 5

    pref_countries = _preferred_countries(profile)
    if pref_countries and any(c in pref_countries for c in job_countries):
        score += 5

    if salary_meets_expectation is False:
        score -= 10

    return max(0, min(100, score))


def _cefr_level(level_str: str) -> int:
    return _CEFR_LEVELS.get(level_str.lower(), 0)


def should_drop_post_llm(
    llm_response: ScoringResponse,
    profile: ProfileConfig,
) -> str | None:
    """Return filter_reason if job should be dropped after LLM scoring, else None."""

    # 1. Mandatory language not met
    for lang_req in llm_response.required_languages:
        if not lang_req.get("mandatory", False):
            continue
        lang_name = lang_req.get("language", "")
        required_level = lang_req.get("level", "A1")
        # Check candidate's level (case-insensitive key lookup)
        candidate_level = "none"
        for k, v in profile.languages.items():
            if k.lower() == lang_name.lower():
                candidate_level = v
                break
        if _cefr_level(candidate_level) < _cefr_level(required_level):
            return f"mandatory_language_unmet:{lang_name}"

    # 2. Location not eligible
    if not llm_response.candidate_location_eligible:
        return "location_not_eligible"

    # 3. Explicit sponsorship refusal
    if llm_response.sponsorship_assessment == "explicit_no" and profile.needs_visa_sponsorship:
        return "sponsorship_explicit_no"

    # 4. Too many required years
    if llm_response.required_years is not None:
        if llm_response.required_years > profile.seniority_years_range.max + 1:
            return "overqualified_years"

    return None
