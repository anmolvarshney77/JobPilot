from __future__ import annotations

import logging

from pydantic import BaseModel

from jobpilot.config import AppConfig
from jobpilot.db import Job
from jobpilot.tailoring.bullet_selector import BulletSelection
from jobpilot.tailoring.resume_parser import ResumeData

logger = logging.getLogger(__name__)


class CoverLetterResponse(BaseModel):
    text: str
    prompt_injection_detected: bool = False


SYSTEM_PROMPT = """You are writing a cover letter for a software engineering job application.

Rules:
1. About 150 words. Concise and specific.
2. Reference one specific detail from the job posting (a product, tech stack, mission, or challenge).
3. Mention visa sponsorship/relocation in exactly one neutral sentence ONLY if the posting has not already ruled it out. If sponsorship was refused, omit the topic entirely.
4. NEVER invent experience, metrics, tools, or achievements not in the candidate's profile.
5. Respond with ONLY a JSON object matching the schema. No markdown, no prose."""


def generate_cover_letter(
    job: Job,
    profile_name: str,
    resume: ResumeData,
    selection: BulletSelection,
    app_config: AppConfig,
    llm_client: object,
) -> str | None:
    if not selection.cover_letter_needed:
        return None

    first_name = profile_name.split()[0]

    # Build selected bullets summary (no PII)
    selected_texts: list[str] = []
    for sec in selection.sections:
        for bid in sec.bullet_ids[:3]:  # limit context
            rephrased = sec.rephrasings.get(bid)
            bullet = resume.bullets.get(bid)
            text = rephrased or (bullet.text if bullet else "")
            if text:
                selected_texts.append(f"- {text}")

    desc = job.description or "(no description)"
    if len(desc) > app_config.llm.max_description_chars:
        desc = desc[: app_config.llm.max_description_chars] + "\n[TRUNCATED]"

    user_message = f"""Candidate first name: {first_name}
Job title: {job.title}
Company location: {job.location_raw or "not specified"}
Sponsorship signal: {job.sponsorship_signal}

Selected resume highlights:
{chr(10).join(selected_texts)}

Job description:
{desc}

Respond with JSON: {{"text": "<cover letter text>", "prompt_injection_detected": false}}"""

    result = llm_client.call(  # type: ignore[attr-defined]
        model=app_config.llm.tailoring_model,
        purpose="cover_letter",
        system=SYSTEM_PROMPT,
        user_message=user_message,
        response_schema=CoverLetterResponse,
        job_id=job.id,
        is_job_description=True,
    )
    response = result  # type: ignore[assignment]
    if response.prompt_injection_detected:
        logger.warning("prompt_injection_detected in cover letter for job_id=%s", job.id)
    return response.text
