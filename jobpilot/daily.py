from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from jobpilot.daily_lock import DailyAlreadyRunningError, DailyLock
from jobpilot.db import Company, Job, RunLog
from jobpilot.notify.digest import DigestData, build_digest_text, collect_digest_data

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_session_factory():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine, expire_on_commit=False)


# ─────────────────────────────────────────── scheduling helpers ──────────────

def should_catch_up(session) -> bool:
    """True if the last successful daily run was >20 hours ago (or never)."""
    row = session.execute(
        select(RunLog)
        .where(RunLog.command == "daily", RunLog.status == "ok")
        .order_by(RunLog.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return True
    return (_now() - row.started_at) > timedelta(hours=20)


def should_run_validate_companies(session) -> bool:
    """True if validate-companies hasn't run successfully in the last 7 days."""
    row = session.execute(
        select(RunLog)
        .where(RunLog.command == "validate-companies", RunLog.status == "ok")
        .order_by(RunLog.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return True
    return (_now() - row.started_at) > timedelta(days=7)


# ─────────────────────────────────────────── step helpers ────────────────────

def _run_validate_companies(session, dry_run: bool) -> list[str]:
    errors: list[str] = []
    try:
        from jobpilot.sources import ashby, greenhouse, lever, personio, recruitee, smartrecruiters, workable
        from jobpilot.sources.company_loader import seed_companies
        from jobpilot.sources.http_client import make_client
        from jobpilot.sources.ratelimit import HostRateLimiter

        _ATS = {
            "greenhouse": greenhouse.fetch,
            "lever": lever.fetch,
            "ashby": ashby.fetch,
            "smartrecruiters": smartrecruiters.fetch,
            "personio": personio.fetch,
            "recruitee": recruitee.fetch,
            "workable": workable.fetch,
        }

        seed_companies(session, "companies.yaml")
        session.commit()

        if dry_run:
            return []

        client = make_client()
        limiter = HostRateLimiter()

        companies = session.execute(
            select(Company).where(Company.ats_slug.isnot(None))
        ).scalars().all()

        for company in companies:
            fetcher = _ATS.get(company.ats_type or "")
            if fetcher is None:
                continue
            try:
                jobs = fetcher(company.ats_slug, client, limiter)
                if jobs:
                    company.verified = True
                    company.last_fetch_ok = _now()
                    company.consecutive_failures = 0
                else:
                    company.verified = False
                    company.consecutive_failures += 1
            except Exception as exc:
                company.verified = False
                company.consecutive_failures += 1
                errors.append(f"validate {company.name}: {exc}")

        session.commit()
        _log_run(session, "validate-companies", "ok")
    except Exception as exc:
        errors.append(f"validate-companies failed: {exc}")
        logger.error("validate-companies error: %s", exc)
    return errors


def _run_fetch(profile, cfg, session, dry_run: bool) -> list[str]:
    errors: list[str] = []
    if dry_run:
        return []
    try:
        from jobpilot.sources import adzuna, arbeitnow, greenhouse, lever, ashby, smartrecruiters, personio, recruitee, remotive, workable
        from jobpilot.sources.company_loader import discover_ats, seed_companies
        from jobpilot.sources.http_client import make_client
        from jobpilot.sources.normalizer import (
            build_dedupe_key, is_title_excluded, is_title_match,
            normalize_company_name, normalize_title, parse_location, parse_salary,
        )
        from jobpilot.sources.ratelimit import HostRateLimiter

        _ATS = {
            "greenhouse": greenhouse.fetch,
            "lever": lever.fetch,
            "ashby": ashby.fetch,
            "smartrecruiters": smartrecruiters.fetch,
            "personio": personio.fetch,
            "recruitee": recruitee.fetch,
            "workable": workable.fetch,
        }

        seed_companies(session, "companies.yaml")
        session.commit()

        client = make_client()
        limiter = HostRateLimiter()
        run_start = _now()
        discovery_count = 0
        all_raw = []

        verified = session.execute(
            select(Company).where(Company.verified == True, Company.ats_type.isnot(None))
        ).scalars().all()

        for company in verified:
            fetcher = _ATS.get(company.ats_type or "")
            if fetcher is None or not company.ats_slug:
                continue
            try:
                jobs = fetcher(company.ats_slug, client, limiter)
                for j in jobs:
                    all_raw.append((j, company.normalized_name))
                if jobs:
                    company.last_fetch_ok = _now()
                    company.consecutive_failures = 0
                else:
                    company.consecutive_failures += 1
                if company.consecutive_failures >= 3:
                    errors.append(f"{company.name}: {company.consecutive_failures} consecutive fetch failures")
            except Exception as exc:
                company.consecutive_failures += 1
                errors.append(f"fetch {company.name}: {exc}")
        session.commit()

        for j in arbeitnow.fetch(client, limiter):
            all_raw.append((j, None))
        for j in remotive.fetch(profile.target_countries, client, limiter):
            all_raw.append((j, None))
        for j in adzuna.fetch_all(profile.target_countries, profile.core_skills[:3], client, limiter):
            all_raw.append((j, None))

        for raw_job, known_norm in all_raw:
            if is_title_excluded(raw_job.title):
                continue
            if not is_title_match(raw_job.title, profile.target_titles + profile.target_titles_local):
                continue
            countries, remote_type = parse_location(raw_job.location_raw)
            if remote_type != "remote" and not any(c in profile.target_countries for c in countries):
                continue

            company_norm = known_norm or normalize_company_name(raw_job.company_name)
            company = session.execute(
                select(Company).where(Company.normalized_name == company_norm)
            ).scalar_one_or_none()

            if company is None:
                ats_info = None
                if discovery_count < 20:
                    try:
                        ats_info = discover_ats(raw_job.company_name, client, limiter)
                    except Exception:
                        pass
                    discovery_count += 1
                company = Company(
                    name=raw_job.company_name,
                    normalized_name=company_norm,
                    ats_type=ats_info[0] if ats_info else None,
                    ats_slug=ats_info[1] if ats_info else None,
                    verified=bool(ats_info),
                    source_discovered_from=raw_job.source,
                )
                session.add(company)
                session.flush()

            title_norm = normalize_title(raw_job.title)
            primary_country = countries[0] if countries else None
            dedupe_key = build_dedupe_key(company_norm, title_norm, primary_country)

            existing = session.execute(
                select(Job).where(Job.dedupe_key == dedupe_key)
            ).scalar_one_or_none()

            if existing is not None:
                existing.last_seen_at = run_start
                existing.is_live = True
            else:
                session.add(Job(
                    source=raw_job.source,
                    external_id=raw_job.external_id,
                    company_id=company.id,
                    title=raw_job.title,
                    normalized_title=title_norm,
                    location_raw=raw_job.location_raw,
                    countries=countries,
                    remote_type=remote_type,
                    remote_allowed_countries=[],
                    url=raw_job.url,
                    apply_url=raw_job.apply_url,
                    description=raw_job.description,
                    posted_at=raw_job.posted_at,
                    first_seen_at=run_start,
                    last_seen_at=run_start,
                    salary_min=raw_job.salary_min,
                    salary_max=raw_job.salary_max,
                    salary_currency=raw_job.salary_currency,
                    sponsorship_signal=raw_job.sponsorship_signal,
                    required_languages=raw_job.required_languages,
                    status="new",
                    dedupe_key=dedupe_key,
                ))

        # Mark stale
        for stale in session.execute(
            select(Job).where(Job.is_live == True, Job.last_seen_at < run_start)
        ).scalars().all():
            stale.is_live = False
            stale.status = "closed"

        session.commit()
    except Exception as exc:
        errors.append(f"fetch failed: {exc}")
        logger.error("fetch error: %s", exc)
    return errors


def _run_score(profile, cfg, session, Session, dry_run: bool) -> list[str]:
    errors: list[str] = []
    if dry_run:
        return []
    try:
        from jobpilot.llm import LLMClient
        from jobpilot.matching import run_pipeline

        jobs = session.execute(select(Job).where(Job.status == "new")).scalars().all()
        if not jobs:
            return []

        llm_client = LLMClient(cfg, Session)
        run_pipeline(
            jobs=list(jobs),
            profile=profile,
            app_config=cfg,
            session=session,
            llm_client=llm_client,
            dry_run=False,
        )
        session.commit()
    except Exception as exc:
        errors.append(f"score failed: {exc}")
        logger.error("score error: %s", exc)
    return errors


def _run_prepare(profile, cfg, session, Session, max_prepare: int, min_score: float, dry_run: bool) -> list[str]:
    errors: list[str] = []
    if dry_run:
        return []
    try:
        from jobpilot.llm import LLMClient
        from jobpilot.tailoring import run_tailoring
        from jobpilot.tailoring.resume_parser import parse_master_resume

        jobs = session.execute(
            select(Job)
            .where(Job.status == "shortlisted", Job.match_score >= min_score)
            .order_by(Job.match_score.desc())
            .limit(max_prepare)
        ).scalars().all()

        if not jobs:
            return []

        company_ids = {j.company_id for j in jobs}
        companies = {
            c.id: c
            for c in session.execute(select(Company).where(Company.id.in_(company_ids))).scalars().all()
        }

        resume = parse_master_resume(profile.resume_master_path)
        llm_client = LLMClient(cfg, Session)

        run_tailoring(
            jobs=list(jobs),
            companies=companies,
            profile=profile,
            app_config=cfg,
            session=session,
            llm_client=llm_client,
            output_root=Path("output"),
            dry_run=False,
        )
        session.commit()
    except Exception as exc:
        errors.append(f"prepare failed: {exc}")
        logger.error("prepare error: %s", exc)
    return errors


def recheck_liveness_for_prepared(session, profile, app_config) -> list[str]:
    """Re-fetch prepared jobs and mark closed ones. Returns list of closed descriptions."""
    closed: list[str] = []
    try:
        import httpx
        from jobpilot.sources.ratelimit import HostRateLimiter
        from jobpilot.tailoring.liveness import check_liveness

        prepared_jobs = session.execute(
            select(Job).where(Job.status == "prepared", Job.is_live == True)
        ).scalars().all()

        if not prepared_jobs:
            return []

        company_ids = {j.company_id for j in prepared_jobs}
        companies = {
            c.id: c
            for c in session.execute(select(Company).where(Company.id.in_(company_ids))).scalars().all()
        }

        client = httpx.Client(timeout=15, follow_redirects=True)
        limiter = HostRateLimiter()

        try:
            for job in prepared_jobs:
                company = companies.get(job.company_id)
                if company is None:
                    continue
                live = check_liveness(job, company, client, limiter)
                if not live:
                    job.is_live = False
                    job.status = "closed"
                    closed.append(f"{job.title} @ {company.name}")
        finally:
            client.close()

        session.commit()
    except Exception as exc:
        logger.error("liveness recheck error: %s", exc)
    return closed


def _log_run(session, command: str, status: str, error: str | None = None) -> RunLog:
    entry = RunLog(command=command, started_at=_now(), status=status, error=error)
    session.add(entry)
    session.commit()
    return entry


# ─────────────────────────────────────────── main orchestrator ───────────────

def run_daily(
    dry_run: bool = False,
    max_prepare: int = 10,
    prepare_min_score: float = 80.0,
) -> tuple[bool, DigestData]:
    run_start = _now()
    errors: list[str] = []

    with DailyLock():
        Session = _make_session_factory()

        with Session() as session:
            run_entry = RunLog(command="daily", started_at=run_start, status="running")
            session.add(run_entry)
            session.commit()
            run_id = run_entry.id

        try:
            from jobpilot.config import Settings, load_app_config, load_profile
            profile = load_profile("profile.yaml")
            cfg = load_app_config("config.yaml")
            settings = Settings()

            with Session() as session:
                if should_run_validate_companies(session):
                    errors.extend(_run_validate_companies(session, dry_run))

            with Session() as session:
                errors.extend(_run_fetch(profile, cfg, session, dry_run))

            with Session() as session:
                errors.extend(_run_score(profile, cfg, session, Session, dry_run))

            with Session() as session:
                errors.extend(_run_prepare(profile, cfg, session, Session, max_prepare, prepare_min_score, dry_run))

            with Session() as session:
                recheck_liveness_for_prepared(session, profile, cfg)

            with Session() as session:
                digest_data = collect_digest_data(session, cfg, errors, run_start, dry_run)

            digest_text = build_digest_text(digest_data)

            if dry_run:
                print(digest_text)
            else:
                from jobpilot.notify import send_digest
                send_digest(digest_text, settings)

            with Session() as session:
                entry = session.execute(select(RunLog).where(RunLog.id == run_id)).scalar_one_or_none()
                if entry:
                    entry.status = "ok" if not errors else "ok_with_errors"
                    entry.finished_at = _now()
                    entry.summary = {
                        "top_matches": len(digest_data.top_matches),
                        "errors": len(errors),
                        "llm_spend_usd": digest_data.llm_spend_usd,
                    }
                session.commit()

            return True, digest_data

        except Exception as exc:
            logger.error("daily run failed: %s", exc)
            with Session() as session:
                entry = session.execute(select(RunLog).where(RunLog.id == run_id)).scalar_one_or_none()
                if entry:
                    entry.status = "error"
                    entry.finished_at = _now()
                    entry.error = str(exc)
                session.commit()
            errors.append(f"daily run exception: {exc}")
            dummy = DigestData(errors=errors, dry_run=dry_run)
            return False, dummy
