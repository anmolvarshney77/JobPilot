from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from jobpilot.apply.ats_detector import ATS_UNSUPPORTED, resolve_apply_url
from jobpilot.apply.fillers.unsupported import check_unsupported, handle_unsupported
from jobpilot.apply.form_filler import FormFillResult, find_submit_button
from jobpilot.config import AppConfig, ProfileConfig
from jobpilot.db import Application, Company, Job
from jobpilot.sources.ratelimit import HostRateLimiter
from jobpilot.tailoring.draft_answers import DraftAnswers
from jobpilot.tailoring.liveness import check_liveness

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class ApplyResult:
    job_id: int
    company: str
    title: str
    ats_type: str | None
    fill_result: FormFillResult | None
    skipped_reason: str | None = None
    application_id: int | None = None


def _get_filler(ats_type: str | None):
    if ats_type == "greenhouse":
        from jobpilot.apply.fillers import greenhouse
        return greenhouse.fill_form
    if ats_type == "lever":
        from jobpilot.apply.fillers import lever
        return lever.fill_form
    if ats_type == "ashby":
        from jobpilot.apply.fillers import ashby
        return ashby.fill_form
    if ats_type == "smartrecruiters":
        from jobpilot.apply.fillers import smartrecruiters
        return smartrecruiters.fill_form
    if ats_type == "workable":
        from jobpilot.apply.fillers import workable
        return workable.fill_form
    if ats_type == "recruitee":
        from jobpilot.apply.fillers import recruitee
        return recruitee.fill_form
    if ats_type == "personio":
        from jobpilot.apply.fillers import personio
        return personio.fill_form
    # Default generic
    from jobpilot.apply.fillers import generic
    return generic.fill_form


def _find_output_dir(output_root: Path, company_name: str, job: Job) -> Path | None:
    import re
    norm = lambda s: re.sub(r"[^\w]", "_", s.lower()).strip("_")
    company_safe = norm(company_name)
    title_safe = norm(job.title)
    expected = output_root / f"{company_safe}_{title_safe}_{job.id}"
    if expected.exists():
        return expected
    # Fallback: scan for matching job_id
    if output_root.exists():
        for d in output_root.iterdir():
            if d.is_dir() and d.name.endswith(f"_{job.id}"):
                return d
    return None


def _load_draft_answers(output_dir: Path) -> DraftAnswers | None:
    da_path = output_dir / "draft_answers.json"
    if not da_path.exists():
        return None
    try:
        data = json.loads(da_path.read_text())
        return DraftAnswers(**data)
    except Exception:
        return None


def _find_pdf(output_dir: Path) -> Path | None:
    for f in output_dir.glob("*.pdf"):
        return f
    return None


def _find_cover_letter(output_dir: Path) -> Path | None:
    for f in output_dir.glob("cover_letter*.txt"):
        return f
    return None


def _get_salary_for_job(job: Job, profile: ProfileConfig) -> int | None:
    countries = job.countries
    if isinstance(countries, list) and countries:
        country = countries[0]
        band = profile.expected_salary.get(country) or profile.expected_salary.get("default")
    else:
        band = profile.expected_salary.get("default")
    return band.min if band else None


def _check_cooldown(session, company: Company, cooldown_days: int) -> bool:
    """Return True if still in cooldown (applied recently)."""
    from sqlalchemy import select
    from jobpilot.db import Job as JobModel, Application as AppModel
    cutoff = _now()
    from datetime import timedelta
    cutoff_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=cooldown_days)

    recent_apps = session.execute(
        select(AppModel)
        .join(JobModel, AppModel.job_id == JobModel.id)
        .where(
            JobModel.company_id == company.id,
            AppModel.submitted_at >= cutoff_dt,
        )
    ).scalars().all()
    return len(recent_apps) > 0


def _print_summary(fill_result: FormFillResult) -> None:
    print("\n--- Form Fill Summary ---")
    print(f"Filled ({len(fill_result.filled)}):")
    for f in fill_result.filled:
        src_tag = f"[{f.source}]"
        print(f"  {src_tag:<10} {f.label}")
    if fill_result.red_fields:
        print(f"\nRED — Must Fix ({len(fill_result.red_fields)}):")
        for f in fill_result.red_fields:
            print(f"  !! {f.label}")
    if fill_result.yellow_fields:
        print(f"\nYELLOW — Review ({len(fill_result.yellow_fields)}):")
        for f in fill_result.yellow_fields:
            print(f"  ?? {f.label}")
    print(f"\nSubmit button found: {fill_result.submit_button_found}")
    print("NOTE: Submit button was NOT clicked.")


async def _run_apply_job(
    job: Job,
    company: Company,
    profile: ProfileConfig,
    app_config: AppConfig,
    session,
    output_root: Path,
    client: httpx.Client,
    limiter: HostRateLimiter,
) -> ApplyResult:
    company_name = company.name

    # 1. Liveness check
    if not check_liveness(job, company, client, limiter):
        job.status = "closed"
        job.is_live = False
        return ApplyResult(
            job_id=job.id, company=company_name, title=job.title,
            ats_type=None, fill_result=None, skipped_reason="closed"
        )

    # 2. Cooldown check
    if _check_cooldown(session, company, profile.company_cooldown_days):
        return ApplyResult(
            job_id=job.id, company=company_name, title=job.title,
            ats_type=None, fill_result=None, skipped_reason="cooldown"
        )

    # 3. Find prepared output
    output_dir = _find_output_dir(output_root, company_name, job)
    if output_dir is None:
        return ApplyResult(
            job_id=job.id, company=company_name, title=job.title,
            ats_type=None, fill_result=None, skipped_reason="no_prepared_output"
        )

    resume_path = _find_pdf(output_dir) or Path("master_resume.md")
    cover_letter_path = _find_cover_letter(output_dir)
    draft_answers = _load_draft_answers(output_dir)
    salary = _get_salary_for_job(job, profile)

    # 4–9. Browser automation
    from playwright.async_api import async_playwright
    apply_url = job.apply_url or job.url
    ats_type = None
    fill_result = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            "./browser_profile",
            headless=False,
        )
        page = await browser.new_page()

        try:
            resolved_url, ats_type = await resolve_apply_url(page, apply_url)

            # Check unsupported
            unsupported_reason = None
            if ats_type in ATS_UNSUPPORTED:
                unsupported_reason = ats_type
            else:
                unsupported_reason = await check_unsupported(page)

            if unsupported_reason:
                fill_result = await handle_unsupported(page, unsupported_reason)
                _print_summary(fill_result)
                print(f"\nUnsupported ATS / barrier: {unsupported_reason}")
                print("Please apply manually.")
                await browser.close()
                return ApplyResult(
                    job_id=job.id, company=company_name, title=job.title,
                    ats_type=ats_type, fill_result=fill_result, skipped_reason="unsupported"
                )

            # 8. Fill form
            filler = _get_filler(ats_type)
            fill_result = await filler(page, profile, resume_path, cover_letter_path, draft_answers, salary)

            # 10. Screenshot
            screenshot_path = output_dir / "pre_submit_screenshot.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)

            # 11. Print summary
            _print_summary(fill_result)

            # 12. Interactive prompt
            application_id = None
            while True:
                choice = input("\n[s] I submitted it  [k] skip  [r] refill  [o] open notes > ").strip().lower()
                if choice == "s":
                    # Save to DB
                    answers_dict = {f.label: f.value for f in fill_result.filled}
                    app = Application(
                        job_id=job.id,
                        submitted_at=_now(),
                        resume_path=str(resume_path),
                        cover_letter_path=str(cover_letter_path) if cover_letter_path else None,
                        answers=answers_dict,
                        screenshot_path=str(screenshot_path),
                    )
                    session.add(app)
                    job.status = "applied"
                    session.flush()
                    application_id = app.id
                    print("Waiting for confirmation page... press Enter when ready.")
                    input()
                    confirmed_path = output_dir / "confirmed_screenshot.png"
                    await page.screenshot(path=str(confirmed_path), full_page=True)
                    print(f"Confirmation screenshot saved: {confirmed_path}")
                    break
                elif choice == "k":
                    break
                elif choice == "r":
                    fill_result = await filler(page, profile, resume_path, cover_letter_path, draft_answers, salary)
                    _print_summary(fill_result)
                elif choice == "o":
                    notes = input("Notes: ").strip()
                    # Stored when application is saved
                    break
                else:
                    print("Invalid choice. Enter s/k/r/o.")

        finally:
            await browser.close()

    return ApplyResult(
        job_id=job.id, company=company_name, title=job.title,
        ats_type=ats_type, fill_result=fill_result, application_id=application_id
    )


def apply_job(
    job: Job,
    company: Company,
    profile: ProfileConfig,
    app_config: AppConfig,
    session,
    output_root: Path = Path("output"),
) -> ApplyResult:
    client = httpx.Client(timeout=15, follow_redirects=True)
    limiter = HostRateLimiter()
    return asyncio.run(
        _run_apply_job(job, company, profile, app_config, session, output_root, client, limiter)
    )
