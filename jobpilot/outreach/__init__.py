from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from jobpilot.config import AppConfig, ProfileConfig
from jobpilot.db import Company, Job, Outreach
from jobpilot.outreach.contact_extractor import ContactSuggestion, extract_contacts_from_posting
from jobpilot.outreach.message_drafter import (
    MessageDraft,
    draft_hiring_manager_message,
    draft_referral_message,
    enforce_length_limits,
)
from jobpilot.tailoring.resume_parser import ResumeData

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_dir_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name


@dataclass
class OutreachResult:
    job_id: int
    company: str
    title: str
    contact_suggestions: list[ContactSuggestion]
    outreach_records: list[int]
    output_paths: list[Path]
    skipped_reason: str | None = None


def run_outreach(
    jobs: list[Job],
    companies: dict[int, Company],
    profile: ProfileConfig,
    app_config: AppConfig,
    session: object,
    llm_client: object,
    resume: ResumeData,
    output_root: Path = Path("output"),
    dry_run: bool = False,
) -> list[OutreachResult]:
    results: list[OutreachResult] = []
    first_name = profile.name.split()[0]

    for job in jobs:
        company = companies.get(job.company_id)
        company_name = company.name if company else "Unknown Company"

        # Score filter
        if (job.match_score or 0) < 80:
            results.append(OutreachResult(
                job_id=job.id,
                company=company_name,
                title=job.title,
                contact_suggestions=[],
                outreach_records=[],
                output_paths=[],
                skipped_reason="score_too_low",
            ))
            continue

        # Status filter
        if job.status not in ("applied", "prepared"):
            results.append(OutreachResult(
                job_id=job.id,
                company=company_name,
                title=job.title,
                contact_suggestions=[],
                outreach_records=[],
                output_paths=[],
                skipped_reason="wrong_status",
            ))
            continue

        # Already has outreach?
        existing = session.execute(  # type: ignore[union-attr]
            select(Outreach).where(Outreach.job_id == job.id)
        ).scalars().first()
        if existing is not None:
            results.append(OutreachResult(
                job_id=job.id,
                company=company_name,
                title=job.title,
                contact_suggestions=[],
                outreach_records=[existing.id],
                output_paths=[],
                skipped_reason="already_has_outreach",
            ))
            continue

        # Extract contacts
        contacts = extract_contacts_from_posting(
            description=job.description or "",
            company_name=company_name,
            job_title=job.title,
        )

        outreach_ids: list[int] = []
        output_paths: list[Path] = []

        # Set up output dir
        company_dir = _safe_dir_name(company_name)
        title_dir = _safe_dir_name(job.title)
        job_output_dir = output_root / f"{company_dir}_{title_dir}_{job.id}"

        if not dry_run:
            job_output_dir.mkdir(parents=True, exist_ok=True)

        if contacts[0].source == "search_query":
            # No named contact — save search queries + a generic draft
            search_lines = "\n".join(
                f"- {c.search_query}" for c in contacts if c.search_query
            )
            message_text = (
                f"LinkedIn search queries to find contacts:\n{search_lines}\n\n"
                f"[Draft a personalised message once you find a contact]"
            )
            if not dry_run:
                record = Outreach(
                    job_id=job.id,
                    contact_name="[search: linkedin queries]",
                    contact_role="unknown",
                    contact_url=None,
                    message_draft=message_text,
                    sent_at=None,
                )
                session.add(record)  # type: ignore[union-attr]
                session.flush()  # type: ignore[union-attr]
                outreach_ids.append(record.id)

                out_path = job_output_dir / "outreach_queries.txt"
                out_path.write_text(message_text)
                output_paths.append(out_path)
        else:
            for n, contact in enumerate(contacts[:2]):
                try:
                    if contact.role in ("hiring_manager", "recruiter"):
                        draft = draft_hiring_manager_message(
                            job, company_name, contact, resume, first_name, app_config, llm_client
                        )
                    else:
                        draft = draft_referral_message(
                            job, company_name, contact, resume, first_name, app_config, llm_client
                        )
                    draft, warnings = enforce_length_limits(draft)
                    for w in warnings:
                        logger.warning("outreach length limit: %s (job_id=%s)", w, job.id)

                    message_json = json.dumps({
                        "linkedin_note": draft.linkedin_note,
                        "email_subject": draft.email_subject,
                        "email_body": draft.email_body,
                    }, indent=2)

                    if not dry_run:
                        record = Outreach(
                            job_id=job.id,
                            contact_name=contact.name or "[unknown]",
                            contact_role=contact.role,
                            contact_url=contact.contact_url,
                            message_draft=message_json,
                            sent_at=None,
                        )
                        session.add(record)  # type: ignore[union-attr]
                        session.flush()  # type: ignore[union-attr]
                        outreach_ids.append(record.id)

                        out_path = job_output_dir / f"outreach_{n + 1}.txt"
                        out_path.write_text(
                            f"To: {contact.name or '[find contact]'} ({contact.role})\n"
                            f"LinkedIn: {contact.contact_url or 'N/A'}\n\n"
                            f"=== LinkedIn Note (≤300 chars) ===\n{draft.linkedin_note}\n\n"
                            f"=== Email Subject ===\n{draft.email_subject}\n\n"
                            f"=== Email Body (≤120 words) ===\n{draft.email_body}\n"
                        )
                        output_paths.append(out_path)
                except Exception as exc:
                    logger.error("Failed to draft outreach for job_id=%s contact=%s: %s", job.id, contact.name, exc)

        if not dry_run:
            session.commit()  # type: ignore[union-attr]

        results.append(OutreachResult(
            job_id=job.id,
            company=company_name,
            title=job.title,
            contact_suggestions=contacts,
            outreach_records=outreach_ids,
            output_paths=output_paths,
        ))

    return results
