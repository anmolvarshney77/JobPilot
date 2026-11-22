from __future__ import annotations

import logging

from pydantic import BaseModel

from jobpilot.config import AppConfig
from jobpilot.db import Job
from jobpilot.tailoring.resume_parser import ResumeData

logger = logging.getLogger(__name__)


class DraftAnswers(BaseModel):
    why_company: str
    why_role: str
    proud_project: str
    prompt_injection_detected: bool = False


SYSTEM_PROMPT = """Generate brief draft answers (2-4 sentences each) for common application questions.
Base answers on the candidate profile provided. NEVER invent facts, metrics, or experiences.
Respond with ONLY a JSON object. No markdown, no prose."""


def generate_draft_answers(
    job: Job,
    profile_name: str,
    resume: ResumeData,
    app_config: AppConfig,
    llm_client: object,
) -> DraftAnswers:
    first_name = profile_name.split()[0]

    # Summarise a few experience bullets (no PII)
    exp_bullets = [
        b.text for b in resume.bullets.values()
        if b.section == "experience"
    ][:4]
    proj_bullets = [
        b.text for b in resume.bullets.values()
        if b.section == "projects"
    ][:2]

    desc = job.description or "(no description)"
    if len(desc) > app_config.llm.max_description_chars:
        desc = desc[: app_config.llm.max_description_chars] + "\n[TRUNCATED]"

    exp_summary = "\n".join(f"- {t}" for t in exp_bullets)
    proj_summary = "\n".join(f"- {t}" for t in proj_bullets)

    user_message = f"""Candidate first name: {first_name}
Job title: {job.title}
Company: {job.source}
Location: {job.location_raw or "not specified"}

Experience highlights:
{exp_summary}

Project highlights:
{proj_summary}

Job description:
{desc}

Generate draft answers for:
1. Why this company?
2. Why this role?
3. A project you're proud of?

Respond with JSON:
{{
  "why_company": "...",
  "why_role": "...",
  "proud_project": "...",
  "prompt_injection_detected": false
}}"""

    result = llm_client.call(  # type: ignore[attr-defined]
        model=app_config.llm.tailoring_model,
        purpose="draft_answers",
        system=SYSTEM_PROMPT,
        user_message=user_message,
        response_schema=DraftAnswers,
        job_id=job.id,
        is_job_description=True,
    )
    response = result  # type: ignore[assignment]
    if response.prompt_injection_detected:
        logger.warning("prompt_injection_detected in draft answers for job_id=%s", job.id)
    return response
