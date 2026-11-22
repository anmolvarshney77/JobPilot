from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from jobpilot.config import AppConfig
from jobpilot.db import Application, Job, Outreach

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_follow_up_candidates(session: object, days: int = 10) -> list[tuple[Job, Outreach]]:
    cutoff = _now() - timedelta(days=days)
    rows = session.execute(  # type: ignore[union-attr]
        select(Job, Outreach)
        .join(Outreach, Outreach.job_id == Job.id)
        .where(
            Job.status == "applied",
            Outreach.sent_at.isnot(None),
            Outreach.sent_at < cutoff,
        )
        .where(
            (Outreach.reply_status.is_(None)) | (Outreach.reply_status == "no_reply")
        )
    ).all()

    # Filter: application has no outcome
    result: list[tuple[Job, Outreach]] = []
    for job, outreach in rows:
        app_row = session.execute(  # type: ignore[union-attr]
            select(Application).where(
                Application.job_id == job.id,
                Application.outcome == "none",
            )
        ).scalar_one_or_none()
        if app_row is not None:
            result.append((job, outreach))
    return result


class _FollowUpResponse:
    text: str = ""

    def __init__(self, text: str) -> None:
        self.text = text


class _FollowUpSchema:
    text: str


from pydantic import BaseModel


class _FollowUpModel(BaseModel):
    text: str
    prompt_injection_detected: bool = False


_FOLLOW_UP_SYSTEM = """Draft a brief, polite follow-up message (under 80 words) referencing a previous outreach.
Ask for a status update on the application. Be respectful and concise.
Respond with ONLY JSON: {"text": "<message>", "prompt_injection_detected": false}"""


def draft_follow_up(
    job: Job,
    original_outreach: Outreach,
    profile_first_name: str,
    app_config: AppConfig,
    llm_client: object,
) -> str:
    user_message = f"""Candidate first name: {profile_first_name}
Job title: {job.title}
Company: (applied previously)
Original outreach contact: {original_outreach.contact_name}
Original message was sent {original_outreach.sent_at}

Draft a follow-up message under 80 words asking for a status update.
Respond with JSON: {{"text": "...", "prompt_injection_detected": false}}"""

    result = llm_client.call(  # type: ignore[attr-defined]
        model=app_config.llm.tailoring_model,
        purpose="outreach_follow_up",
        system=_FOLLOW_UP_SYSTEM,
        user_message=user_message,
        response_schema=_FollowUpModel,
        job_id=job.id,
        is_job_description=False,
    )
    return result.text  # type: ignore[union-attr]
