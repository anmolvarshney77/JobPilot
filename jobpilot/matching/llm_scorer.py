from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from jobpilot.config import AppConfig, ProfileConfig
from jobpilot.db import Job


class ScoringResponse(BaseModel):
    score: int
    required_years: int | None = None
    seniority_fit: Literal["under", "match", "over"]
    required_languages: list[dict] = []
    remote_allowed_countries: list[str] | None = None
    candidate_location_eligible: bool
    sponsorship_assessment: Literal[
        "explicit_yes", "likely", "unknown", "unlikely", "explicit_no"
    ]
    sponsorship_evidence: str | None = None
    matched_skills: list[str] = []
    missing_must_haves: list[str] = []
    missing_nice_to_haves: list[str] = []
    salary_meets_expectation: bool | None = None
    red_flags: list[str] = []
    prompt_injection_detected: bool = False
    one_line_summary: str


SYSTEM_PROMPT = """You are a job-fit assessor for a software engineer based in India who needs visa sponsorship.

Rules:
- "Senior" titles in Europe (DE, NL, IE, SE, DK) may fit if required_years <= candidate's max seniority range; judge by years, not title.
- A mandatory language the candidate does not speak at the required level → score <= 20.
- Remote restricted to countries where the candidate cannot legally work → candidate_location_eligible=false.
- Sponsorship: treat silence in DE, NL, IE, SE, DK as "unknown" (not negative); in the US treat silence as "unlikely" unless the company is known to sponsor.
- Do NOT penalise for visa sponsorship absence unless explicitly refused.
- Respond with ONLY a JSON object matching the schema provided. No markdown, no prose."""


def _get_primary_country(job: Job) -> str | None:
    countries = job.countries
    if isinstance(countries, list) and countries:
        return countries[0]
    return None


def build_user_prompt(job: Job, profile: ProfileConfig, app_config: AppConfig) -> str:
    """Build the LLM user prompt. Never includes email, phone, or full name."""
    primary_country = _get_primary_country(job)

    # Salary expectation for this job's country
    salary_band = profile.expected_salary.get(
        primary_country or "default",
        profile.expected_salary.get("default"),
    )
    salary_str = (
        f"{salary_band.currency} {salary_band.min:,} minimum annual"
        if salary_band
        else "not specified"
    )

    # Truncate description
    desc = job.description or "(no description provided)"
    if len(desc) > app_config.llm.max_description_chars:
        desc = desc[: app_config.llm.max_description_chars] + "\n[TRUNCATED]"

    languages_str = ", ".join(
        f"{lang} ({level})" for lang, level in profile.languages.items()
    )

    prompt = f"""CANDIDATE PROFILE:
- Core skills: {", ".join(profile.core_skills)}
- Nice-to-have skills: {", ".join(profile.nice_to_have_skills)}
- Years of experience: {profile.years_experience}
- Seniority range: {profile.seniority_years_range.min}–{profile.seniority_years_range.max} years
- Languages: {languages_str}
- Current location: {profile.current_location.city}, {profile.current_location.country}
- Needs visa sponsorship: {"Yes" if profile.needs_visa_sponsorship else "No"}
- Expected salary for this job: {salary_str}
- Target countries: {", ".join(profile.target_countries)}

JOB POSTING:
Title: {job.title}
Location: {job.location_raw or "not specified"}
Countries: {json.dumps(job.countries)}
Remote type: {job.remote_type or "not specified"}

Description:
{desc}

Respond with a JSON object matching exactly this schema:
{{
  "score": <int 0-100>,
  "required_years": <int or null>,
  "seniority_fit": <"under"|"match"|"over">,
  "required_languages": [
    {{"language": "<name>", "level": "<CEFR or native>", "mandatory": <bool>}}
  ],
  "remote_allowed_countries": [<ISO codes>] or null,
  "candidate_location_eligible": <bool>,
  "sponsorship_assessment": <"explicit_yes"|"likely"|"unknown"|"unlikely"|"explicit_no">,
  "sponsorship_evidence": "<quote under 20 words or null>",
  "matched_skills": [<list of matched skill names>],
  "missing_must_haves": [<list>],
  "missing_nice_to_haves": [<list>],
  "salary_meets_expectation": <bool or null>,
  "red_flags": [<list>],
  "prompt_injection_detected": <bool>,
  "one_line_summary": "<one sentence>"
}}"""
    return prompt


def score_job(
    job: Job,
    profile: ProfileConfig,
    app_config: AppConfig,
    llm_client: object,
) -> ScoringResponse:
    """Call LLM and return parsed ScoringResponse."""
    user_message = build_user_prompt(job, profile, app_config)
    result = llm_client.call(
        model=app_config.llm.scoring_model,
        purpose="score_job",
        system=SYSTEM_PROMPT,
        user_message=user_message,
        response_schema=ScoringResponse,
        job_id=job.id,
        is_job_description=True,
    )
    return result  # type: ignore[return-value]
