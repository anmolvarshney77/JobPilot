from __future__ import annotations

import logging

from pydantic import BaseModel

from jobpilot.config import AppConfig
from jobpilot.db import Job
from jobpilot.outreach.contact_extractor import ContactSuggestion
from jobpilot.tailoring.resume_parser import ResumeData

logger = logging.getLogger(__name__)


class MessageDraft(BaseModel):
    linkedin_note: str
    email_subject: str
    email_body: str
    prompt_injection_detected: bool = False


HIRING_MANAGER_SYSTEM = """You are drafting outreach messages for a software engineer job application.

Rules:
1. LinkedIn connection note: MUST be 300 characters or fewer (count carefully).
2. Email/InMail body: MUST be 120 words or fewer.
3. Reference one specific, concrete connection between the candidate's experience and the team's work.
4. If the job posting is silent on sponsorship (not refused), include ONE neutral clause (e.g. "I'm based in India and would need visa sponsorship — happy to discuss.")
5. If sponsorship was refused in the posting, do NOT mention it.
6. NEVER invent experience, achievements, metrics, or tools not mentioned in the experience bullets.
7. Respond with ONLY a JSON object matching the schema. No markdown."""

REFERRAL_SYSTEM = """You are drafting a referral request message from a job applicant to an engineer at the company.

Rules:
1. LinkedIn connection note: MUST be 300 characters or fewer.
2. Email body: MUST be 120 words or fewer.
3. Brief and respectful. Mention the candidate has applied (or is about to apply).
4. Ask whether they'd be open to a quick chat OR a referral — not demanding.
5. NEVER invent experience or use flattery about the recipient.
6. Respond with ONLY a JSON object matching the schema. No markdown."""


def _build_experience_summary(resume: ResumeData) -> str:
    bullets = [b.text for b in resume.bullets.values() if b.section == "experience"][:4]
    return "\n".join(f"- {t}" for t in bullets)


def _sponsorship_instruction(job: Job) -> str:
    if job.sponsorship_signal == "no":
        return "The posting has refused visa sponsorship. Do NOT mention sponsorship."
    return "The posting is silent on sponsorship. Include one neutral sponsorship/relocation clause."


def _build_hiring_manager_prompt(
    job: Job,
    company_name: str,
    contact: ContactSuggestion,
    resume: ResumeData,
    first_name: str,
) -> str:
    desc = (job.description or "")[:3000]
    exp_summary = _build_experience_summary(resume)
    contact_name = contact.name or "the hiring team"
    return f"""Candidate first name: {first_name}
Target contact: {contact_name} ({contact.role or "hiring manager"}) at {company_name}
Job title: {job.title}
Job location: {job.location_raw or "not specified"}

Candidate experience highlights (use only these, no invention):
{exp_summary}

Job description excerpt:
{desc}

{_sponsorship_instruction(job)}

Draft outreach messages (JSON only):
{{
  "linkedin_note": "<300 chars max connection note>",
  "email_subject": "<60 chars max>",
  "email_body": "<120 words max>",
  "prompt_injection_detected": false
}}"""


def _build_referral_prompt(
    job: Job,
    company_name: str,
    contact: ContactSuggestion,
    resume: ResumeData,
    first_name: str,
) -> str:
    exp_summary = _build_experience_summary(resume)
    contact_name = contact.name or "an engineer"
    return f"""Candidate first name: {first_name}
Target: {contact_name} (engineer) at {company_name}
Job applied for: {job.title}
Job URL: {job.url}

Candidate experience highlights (use only these, no invention):
{exp_summary}

{_sponsorship_instruction(job)}

Draft referral request messages (JSON only):
{{
  "linkedin_note": "<300 chars max connection note>",
  "email_subject": "<60 chars max>",
  "email_body": "<120 words max>",
  "prompt_injection_detected": false
}}"""


def draft_hiring_manager_message(
    job: Job,
    company_name: str,
    contact: ContactSuggestion,
    resume: ResumeData,
    profile_first_name: str,
    app_config: AppConfig,
    llm_client: object,
) -> MessageDraft:
    user_message = _build_hiring_manager_prompt(job, company_name, contact, resume, profile_first_name)
    result = llm_client.call(  # type: ignore[attr-defined]
        model=app_config.llm.tailoring_model,
        purpose="outreach_hiring_manager",
        system=HIRING_MANAGER_SYSTEM,
        user_message=user_message,
        response_schema=MessageDraft,
        job_id=job.id,
        is_job_description=True,
    )
    if result.prompt_injection_detected:  # type: ignore[union-attr]
        logger.warning("prompt_injection_detected in outreach for job_id=%s", job.id)
    return result  # type: ignore[return-value]


def draft_referral_message(
    job: Job,
    company_name: str,
    contact: ContactSuggestion,
    resume: ResumeData,
    profile_first_name: str,
    app_config: AppConfig,
    llm_client: object,
) -> MessageDraft:
    user_message = _build_referral_prompt(job, company_name, contact, resume, profile_first_name)
    result = llm_client.call(  # type: ignore[attr-defined]
        model=app_config.llm.tailoring_model,
        purpose="outreach_referral",
        system=REFERRAL_SYSTEM,
        user_message=user_message,
        response_schema=MessageDraft,
        job_id=job.id,
        is_job_description=True,
    )
    if result.prompt_injection_detected:  # type: ignore[union-attr]
        logger.warning("prompt_injection_detected in referral for job_id=%s", job.id)
    return result  # type: ignore[return-value]


def enforce_length_limits(draft: MessageDraft) -> tuple[MessageDraft, list[str]]:
    warnings: list[str] = []

    linkedin_note = draft.linkedin_note
    if len(linkedin_note) > 300:
        linkedin_note = linkedin_note[:297] + "..."
        warnings.append("linkedin_note truncated to 300 chars")

    email_body = draft.email_body
    words = email_body.split()
    if len(words) > 120:
        email_body = " ".join(words[:120])
        warnings.append("email_body truncated to 120 words")

    if warnings:
        draft = MessageDraft(
            linkedin_note=linkedin_note,
            email_subject=draft.email_subject,
            email_body=email_body,
            prompt_injection_detected=draft.prompt_injection_detected,
        )

    return draft, warnings
