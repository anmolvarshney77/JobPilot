from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from jobpilot.config import AppConfig, ProfileConfig
from jobpilot.db import Company, Job
from jobpilot.tailoring.bullet_selector import BulletSelection, select_bullets
from jobpilot.tailoring.cover_letter import generate_cover_letter
from jobpilot.tailoring.draft_answers import generate_draft_answers
from jobpilot.tailoring.liveness import check_liveness
from jobpilot.tailoring.renderer import render_resume, verify_pdf_text
from jobpilot.tailoring.resume_parser import ResumeData
from jobpilot.tailoring.review import generate_review_html
from jobpilot.tailoring.verifier import apply_verifications
from jobpilot.sources.ratelimit import HostRateLimiter

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_dir_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name


@dataclass
class TailoringResult:
    job_id: int
    company: str
    title: str
    output_dir: Path
    pdf_path: Path | None
    cover_letter_path: Path | None
    review_html_path: Path
    skipped_reason: str | None
    rejected_rephrasings: list[str] = field(default_factory=list)
    pdf_verification_warnings: list[str] = field(default_factory=list)


async def tailor_job(
    job: Job,
    company: Company,
    profile: ProfileConfig,
    app_config: AppConfig,
    llm_client: object,
    resume: ResumeData,
    output_root: Path,
    client: httpx.Client,
    limiter: HostRateLimiter,
    dry_run: bool = False,
    session: object = None,
) -> TailoringResult:
    from jobpilot.llm import BudgetExceededError

    company_dir = _safe_dir_name(company.name)
    title_dir = _safe_dir_name(job.title)
    output_dir = output_root / f"{company_dir}_{title_dir}_{job.id}"

    # Liveness check
    is_live = check_liveness(job, company, client, limiter)
    if not is_live:
        if not dry_run and session is not None:
            job.status = "closed"
            job.is_live = False
        return TailoringResult(
            job_id=job.id,
            company=company.name,
            title=job.title,
            output_dir=output_dir,
            pdf_path=None,
            cover_letter_path=None,
            review_html_path=output_dir / "review.html",
            skipped_reason="closed",
        )

    # LLM: bullet selection
    try:
        selection: BulletSelection = select_bullets(job, resume, app_config, llm_client)
    except BudgetExceededError:
        return TailoringResult(
            job_id=job.id,
            company=company.name,
            title=job.title,
            output_dir=output_dir,
            pdf_path=None,
            cover_letter_path=None,
            review_html_path=output_dir / "review.html",
            skipped_reason="budget_exceeded",
        )

    # Verification
    selection, rejections = apply_verifications(selection, resume)

    # Render PDF
    pdf_path: Path | None = None
    pdf_warnings: list[str] = []
    try:
        pdf_path = await render_resume(
            resume=resume,
            selection=selection,
            profile_name=profile.name,
            output_dir=output_dir,
            company_name=company.name,
        )
        # Collect expected bullet texts for verification
        bullet_texts: list[str] = []
        for sec in selection.sections:
            for bid in sec.bullet_ids:
                rephrased = sec.rephrasings.get(bid)
                bullet = resume.bullets.get(bid)
                text = rephrased or (bullet.text if bullet else "")
                if text:
                    bullet_texts.append(text)
        pdf_warnings = verify_pdf_text(pdf_path, profile.name, bullet_texts)
        if pdf_warnings:
            logger.warning(
                "PDF verification warnings for job_id=%s: %s", job.id, pdf_warnings
            )
    except Exception as exc:
        logger.error("PDF render failed for job_id=%s: %s", job.id, exc)
        pdf_warnings.append(f"PDF render error: {exc}")

    # Cover letter
    cover_letter_path: Path | None = None
    cover_letter_text = generate_cover_letter(
        job=job,
        profile_name=profile.name,
        resume=resume,
        selection=selection,
        app_config=app_config,
        llm_client=llm_client,
    )
    if cover_letter_text and not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        cover_letter_path = output_dir / "cover_letter.txt"
        cover_letter_path.write_text(cover_letter_text, encoding="utf-8")

    # Draft answers
    try:
        draft_answers = generate_draft_answers(
            job=job,
            profile_name=profile.name,
            resume=resume,
            app_config=app_config,
            llm_client=llm_client,
        )
        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            answers_path = output_dir / "draft_answers.json"
            answers_path.write_text(
                json.dumps(draft_answers.model_dump(), indent=2), encoding="utf-8"
            )
    except Exception as exc:
        logger.warning("Draft answers failed for job_id=%s: %s", job.id, exc)

    # Review HTML
    review_html_path = generate_review_html(
        resume=resume,
        selection=selection,
        rejected_rephrasings=rejections,
        output_dir=output_dir,
        job_title=job.title,
        company_name=company.name,
    )

    # Update job status
    if not dry_run and session is not None:
        job.status = "prepared"

    return TailoringResult(
        job_id=job.id,
        company=company.name,
        title=job.title,
        output_dir=output_dir,
        pdf_path=pdf_path,
        cover_letter_path=cover_letter_path,
        review_html_path=review_html_path,
        skipped_reason=None,
        rejected_rephrasings=rejections,
        pdf_verification_warnings=pdf_warnings,
    )


def run_tailoring(
    jobs: list[Job],
    companies: dict[int, Company],
    profile: ProfileConfig,
    app_config: AppConfig,
    session: object,
    llm_client: object,
    output_root: Path = Path("output"),
    dry_run: bool = False,
) -> list[TailoringResult]:
    from jobpilot.sources.http_client import make_client

    client = make_client()
    limiter = HostRateLimiter()

    async def _run_all() -> list[TailoringResult]:
        results = []
        for job in jobs:
            company = companies.get(job.company_id)
            if company is None:
                logger.warning("company not found for job_id=%s", job.id)
                continue
            result = await tailor_job(
                job=job,
                company=company,
                profile=profile,
                app_config=app_config,
                llm_client=llm_client,
                resume=_get_resume(profile),
                output_root=output_root,
                client=client,
                limiter=limiter,
                dry_run=dry_run,
                session=session,
            )
            results.append(result)
        return results

    return asyncio.run(_run_all())


def _get_resume(profile: ProfileConfig) -> ResumeData:
    from jobpilot.tailoring.resume_parser import parse_master_resume
    return parse_master_resume(profile.resume_master_path)
