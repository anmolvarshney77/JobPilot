from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from jobpilot.config import AppConfig
from jobpilot.db import Job
from jobpilot.tailoring.resume_parser import ResumeData

logger = logging.getLogger(__name__)


class SectionSelection(BaseModel):
    section: str
    employer: str | None = None
    bullet_ids: list[str]
    rephrasings: dict[str, str] = {}


class BulletSelection(BaseModel):
    summary_id: str
    sections: list[SectionSelection]
    cover_letter_needed: bool = False


SYSTEM_PROMPT = """You are a resume tailoring assistant.
Given a job description and the candidate's master resume, select and optionally rephrase bullets to maximise fit for this specific role.

RULES (you must follow all of them):
1. Only use bullet ids that exist in the master resume. NEVER invent experience, employers, job titles, dates, metrics, tools, or degrees.
2. Rephrasing may change wording and order to mirror the job's terminology, but every number, tool, and factual claim must already exist in the original bullet text.
3. Do NOT keyword-stuff: each technology or skill should appear naturally at most twice across the whole resume.
4. Aim for a one-page resume. Prefer fewer, stronger bullets over many weak ones.
5. Include a cover_letter_needed: true field if the posting explicitly requests one or has a cover letter field.
6. Respond with ONLY a JSON object matching the schema. No markdown, no prose."""


def _build_resume_summary(resume: ResumeData) -> str:
    lines = ["MASTER RESUME BULLETS:"]
    for bullet_id, bullet in resume.bullets.items():
        employer_info = f" [{bullet.employer}]" if bullet.employer else ""
        lines.append(f"  {bullet_id} ({bullet.section}{employer_info}): {bullet.text}")
    return "\n".join(lines)


def select_bullets(
    job: Job,
    resume: ResumeData,
    app_config: AppConfig,
    llm_client: object,
) -> BulletSelection:
    desc = job.description or "(no description)"
    if len(desc) > app_config.llm.max_description_chars:
        desc = desc[: app_config.llm.max_description_chars] + "\n[TRUNCATED]"

    resume_summary = _build_resume_summary(resume)
    schema = BulletSelection.model_json_schema()

    user_message = f"""JOB TITLE: {job.title}
LOCATION: {job.location_raw or "not specified"}

JOB DESCRIPTION:
{desc}

{resume_summary}

Respond with a JSON object matching this schema exactly:
{json.dumps(schema, indent=2)}"""

    result = llm_client.call(  # type: ignore[attr-defined]
        model=app_config.llm.tailoring_model,
        purpose="select_bullets",
        system=SYSTEM_PROMPT,
        user_message=user_message,
        response_schema=BulletSelection,
        job_id=job.id,
        is_job_description=True,
    )
    return result  # type: ignore[return-value]
