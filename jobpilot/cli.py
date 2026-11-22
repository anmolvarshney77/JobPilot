from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

import typer

app = typer.Typer(
    name="jobpilot",
    help="Job application automation for software engineers targeting international markets.",
    no_args_is_help=True,
)

DryRun = Annotated[bool, typer.Option("--dry-run", help="Preview actions without making changes.")]


def _load_configs() -> tuple:
    from jobpilot.config import load_app_config, load_profile

    profile = load_profile("profile.yaml")
    cfg = load_app_config("config.yaml")
    return profile, cfg


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@app.command()
def fetch(dry_run: DryRun = False) -> None:
    """Scrape job listings from configured sources."""
    import os

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from jobpilot.db import Company, Job
    from jobpilot.sources import RawJob
    from jobpilot.sources import adzuna, arbeitnow, remotive
    from jobpilot.sources import greenhouse, lever, ashby, smartrecruiters, personio, recruitee, workable
    from jobpilot.sources.company_loader import discover_ats, seed_companies
    from jobpilot.sources.http_client import make_client
    from jobpilot.sources.normalizer import (
        build_dedupe_key,
        is_title_excluded,
        is_title_match,
        normalize_company_name,
        normalize_title,
        parse_location,
        parse_salary,
    )
    from jobpilot.sources.ratelimit import HostRateLimiter

    profile, cfg = _load_configs()

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    _ATS_FETCHERS = {
        "greenhouse": greenhouse.fetch,
        "lever": lever.fetch,
        "ashby": ashby.fetch,
        "smartrecruiters": smartrecruiters.fetch,
        "personio": personio.fetch,
        "recruitee": recruitee.fetch,
        "workable": workable.fetch,
    }

    with Session() as session:
        newly_seeded = seed_companies(session, "companies.yaml")
        session.commit()
        if newly_seeded:
            typer.echo(f"Seeded {newly_seeded} new companies from companies.yaml")

    run_start = _now()
    stats: dict[str, dict[str, int]] = {}  # source -> {new, updated}
    total_duplicates = 0
    total_closed = 0
    discovery_count = 0

    client = make_client()
    limiter = HostRateLimiter()

    all_raw_jobs: list[tuple[RawJob, str | None]] = []  # (job, company_normalized_name)

    if dry_run:
        typer.echo("dry run — no changes made")
        return

    with Session() as session:
        # Fetch ATS companies
        verified_companies = session.execute(
            __import__("sqlalchemy").select(Company).where(
                Company.verified == True, Company.ats_type != None
            )
        ).scalars().all()

        for company in verified_companies:
            fetcher = _ATS_FETCHERS.get(company.ats_type or "")
            if fetcher is None or company.ats_slug is None:
                continue
            jobs = fetcher(company.ats_slug, client, limiter)
            for job in jobs:
                all_raw_jobs.append((job, company.normalized_name))
            if jobs:
                company.last_fetch_ok = _now()
                company.consecutive_failures = 0
            else:
                company.consecutive_failures += 1
        session.commit()

    # Aggregators
    aggregator_jobs = arbeitnow.fetch(client, limiter)
    for j in aggregator_jobs:
        all_raw_jobs.append((j, None))

    aggregator_jobs = remotive.fetch(profile.target_countries, client, limiter)
    for j in aggregator_jobs:
        all_raw_jobs.append((j, None))

    aggregator_jobs = adzuna.fetch_all(
        profile.target_countries, profile.core_skills[:3], client, limiter
    )
    for j in aggregator_jobs:
        all_raw_jobs.append((j, None))

    with Session() as session:
        for raw_job, known_company_norm in all_raw_jobs:
            source = raw_job.source
            if source not in stats:
                stats[source] = {"new": 0, "updated": 0}

            # Title filtering
            if is_title_excluded(raw_job.title):
                continue
            if not is_title_match(raw_job.title, profile.target_titles + profile.target_titles_local):
                continue

            # Location filtering
            countries, remote_type = parse_location(raw_job.location_raw)
            if remote_type != "remote" and not any(c in profile.target_countries for c in countries):
                continue

            # Resolve or create company
            company_norm = known_company_norm or normalize_company_name(raw_job.company_name)
            company = session.execute(
                __import__("sqlalchemy").select(Company).where(Company.normalized_name == company_norm)
            ).scalar_one_or_none()

            if company is None:
                # Discover ATS (capped at 20 per run)
                ats_info = None
                if discovery_count < 20:
                    ats_info = discover_ats(raw_job.company_name, client, limiter)
                    discovery_count += 1
                company = Company(
                    name=raw_job.company_name,
                    normalized_name=company_norm,
                    ats_type=ats_info[0] if ats_info else None,
                    ats_slug=ats_info[1] if ats_info else None,
                    verified=bool(ats_info),
                    source_discovered_from=source,
                )
                session.add(company)
                session.flush()

            # Deduplicate
            title_norm = normalize_title(raw_job.title)
            primary_country = countries[0] if countries else None
            dedupe_key = build_dedupe_key(company_norm, title_norm, primary_country)

            existing = session.execute(
                __import__("sqlalchemy").select(Job).where(Job.dedupe_key == dedupe_key)
            ).scalar_one_or_none()

            if existing is not None:
                # Prefer ATS source over aggregator
                if existing.source not in ("greenhouse", "lever", "ashby", "smartrecruiters", "personio", "recruitee", "workable") and source in ("greenhouse", "lever", "ashby", "smartrecruiters", "personio", "recruitee", "workable"):
                    existing.source = source
                    existing.url = raw_job.url
                    existing.apply_url = raw_job.apply_url
                existing.last_seen_at = run_start
                existing.is_live = True
                total_duplicates += 1
                stats[source]["updated"] += 1
            else:
                sal_min, sal_max, sal_cur = parse_salary(None)  # already parsed in RawJob
                new_job = Job(
                    source=source,
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
                )
                session.add(new_job)
                stats[source]["new"] += 1

        # Mark stale jobs closed
        from sqlalchemy import update
        stale_result = session.execute(
            __import__("sqlalchemy").select(Job).where(
                Job.is_live == True,
                Job.last_seen_at < run_start,
            )
        ).scalars().all()
        for stale_job in stale_result:
            stale_job.is_live = False
            stale_job.status = "closed"
            total_closed += 1

        session.commit()

    # Print summary
    typer.echo("\n=== Fetch Summary ===")
    for source, counts in stats.items():
        typer.echo(f"  {source:<20}: {counts['new']:>4} new, {counts['updated']:>4} updated")
    typer.echo(f"\n  Duplicates merged : {total_duplicates}")
    typer.echo(f"  Jobs closed       : {total_closed}")


@app.command(name="validate-companies")
def validate_companies(dry_run: DryRun = False) -> None:
    """Check each company slug against its ATS endpoint and mark verified."""
    import os

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from jobpilot.db import Company
    from jobpilot.sources import greenhouse, lever, ashby, smartrecruiters, personio, recruitee, workable
    from jobpilot.sources.company_loader import seed_companies
    from jobpilot.sources.http_client import make_client
    from jobpilot.sources.ratelimit import HostRateLimiter

    _ATS_FETCHERS = {
        "greenhouse": greenhouse.fetch,
        "lever": lever.fetch,
        "ashby": ashby.fetch,
        "smartrecruiters": smartrecruiters.fetch,
        "personio": personio.fetch,
        "recruitee": recruitee.fetch,
        "workable": workable.fetch,
    }

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        newly_seeded = seed_companies(session, "companies.yaml")
        session.commit()
        if newly_seeded:
            typer.echo(f"Seeded {newly_seeded} new companies")

    if dry_run:
        with Session() as session:
            companies = session.execute(
                select(Company).where(Company.verified == False, Company.ats_slug != None)
            ).scalars().all()
        typer.echo(f"dry run — would check {len(companies)} unverified companies")
        return

    client = make_client()
    limiter = HostRateLimiter()
    verified_count = error_count = unverified_count = 0

    with Session() as session:
        companies = session.execute(
            select(Company).where(Company.ats_slug != None)
        ).scalars().all()

        for company in companies:
            fetcher = _ATS_FETCHERS.get(company.ats_type or "")
            if fetcher is None:
                unverified_count += 1
                continue
            try:
                jobs = fetcher(company.ats_slug, client, limiter)
                if jobs:
                    company.verified = True
                    company.last_fetch_ok = _now()
                    company.consecutive_failures = 0
                    verified_count += 1
                else:
                    company.verified = False
                    company.consecutive_failures += 1
                    unverified_count += 1
            except Exception as exc:
                company.verified = False
                company.consecutive_failures += 1
                error_count += 1
                typer.echo(f"  ERROR {company.name}: {exc}")

        session.commit()

    typer.echo(f"\nVerified: {verified_count} | Unverified: {unverified_count} | Errors: {error_count}")


@app.command()
def score(dry_run: DryRun = False) -> None:
    """Score and filter fetched jobs against your profile."""
    import os

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from jobpilot.db import Company, Job
    from jobpilot.llm import LLMClient
    from jobpilot.matching import PipelineResult, run_pipeline

    profile, cfg = _load_configs()

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        jobs = session.execute(
            select(Job).where(Job.status == "new")
        ).scalars().all()

        if not jobs:
            typer.echo("No new jobs to score.")
            return

        llm_client = LLMClient(cfg, Session)
        result = run_pipeline(
            jobs=list(jobs),
            profile=profile,
            app_config=cfg,
            session=session,
            llm_client=llm_client,
            dry_run=dry_run,
        )

    typer.echo(f"\nProcessed: {result.total_processed} jobs")

    if result.hard_filtered:
        typer.echo("\nHard filters:")
        for reason, count in sorted(result.hard_filtered.items()):
            typer.echo(f"  {reason}: {count}")

    typer.echo(f"\nKeyword filtered: {result.keyword_filtered}")
    typer.echo(f"LLM scored: {result.llm_scored}  (cost: ${result.llm_cost_usd:.4f})")

    if result.post_filtered:
        typer.echo("\nPost-LLM filtered:")
        for reason, count in sorted(result.post_filtered.items()):
            typer.echo(f"  {reason}: {count}")

    typer.echo(f"\nShortlisted: {result.shortlisted}")

    if result.injection_flagged:
        typer.echo(f"\n⚠ Prompt injection flagged in {result.injection_flagged} job(s) — review in dashboard.")

    if dry_run:
        typer.echo("\n(dry run — no changes committed)")
        return

    # Show top 20 shortlisted
    with Session() as session:
        from sqlalchemy import desc

        top_jobs = session.execute(
            select(Job, Company)
            .join(Company, Job.company_id == Company.id)
            .where(Job.status == "shortlisted")
            .order_by(desc(Job.match_score))
            .limit(20)
        ).all()

    if top_jobs:
        typer.echo("\n--- Top 20 Shortlisted ---")
        typer.echo(
            f"{'#':>3}  {'Score':>5}  {'Title':<35}  {'Company':<20}  {'Country':<8}  {'Sponsor':<12}  Languages"
        )
        typer.echo("-" * 110)
        for rank, (job, company) in enumerate(top_jobs, 1):
            countries = ",".join(job.countries[:2]) if job.countries else "?"
            details = job.match_details or {}
            sponsor = details.get("sponsorship_assessment", job.sponsorship_signal)[:12]
            langs = ", ".join(
                f"{r.get('language','?')}({r.get('level','?')})"
                for r in (details.get("required_languages") or [])[:2]
            ) or "—"
            score_val = int(job.match_score) if job.match_score else 0
            typer.echo(
                f"{rank:>3}  {score_val:>5}  {job.title[:35]:<35}  {company.name[:20]:<20}  {countries:<8}  {sponsor:<12}  {langs}"
            )


@app.command()
def prepare(dry_run: DryRun = False) -> None:
    """Tailor resume and draft cover letter for shortlisted jobs."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("prepare: not yet implemented")


@app.command()
def apply(dry_run: DryRun = False) -> None:
    """Submit applications via browser automation."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("apply: not yet implemented")


@app.command()
def outreach(dry_run: DryRun = False) -> None:
    """Draft recruiter/referral outreach messages."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("outreach: not yet implemented")


@app.command()
def dashboard(dry_run: DryRun = False) -> None:
    """Start the local web dashboard."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("dashboard: not yet implemented (will start uvicorn on http://localhost:8000)")


@app.command()
def daily(dry_run: DryRun = False) -> None:
    """Run fetch → score → prepare in sequence."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return
    typer.echo("daily: running fetch → score → prepare (not yet implemented)")


@app.command()
def stats(dry_run: DryRun = False) -> None:
    """Show run history and LLM usage/cost summary."""
    if dry_run:
        typer.echo("dry run — no changes made")
        return

    import os

    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from jobpilot.db import LLMUsage, RunLog

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    eng = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=eng)

    with Session() as session:
        run_rows = session.execute(
            select(RunLog.command, RunLog.status, RunLog.started_at)
            .order_by(RunLog.started_at.desc())
            .limit(10)
        ).fetchall()

        llm_rows = session.execute(
            select(
                LLMUsage.model,
                func.count().label("calls"),
                func.sum(LLMUsage.input_tokens).label("in_tok"),
                func.sum(LLMUsage.output_tokens).label("out_tok"),
                func.sum(LLMUsage.cost_usd).label("cost"),
            ).group_by(LLMUsage.model)
        ).fetchall()

    typer.echo("\n=== Recent Runs ===")
    if run_rows:
        for r in run_rows:
            typer.echo(f"  {r.started_at}  {r.command:<12}  {r.status}")
    else:
        typer.echo("  (no runs yet)")

    typer.echo("\n=== LLM Usage (this database) ===")
    if llm_rows:
        typer.echo(
            f"  {'Model':<25} {'Calls':>6} {'In tok':>10} {'Out tok':>10} {'Cost USD':>10}"
        )
        total_cost = 0.0
        for r in llm_rows:
            typer.echo(
                f"  {r.model:<25} {r.calls:>6} {r.in_tok:>10} {r.out_tok:>10} {r.cost:>10.4f}"
            )
            total_cost += r.cost
        typer.echo(f"\n  Total cost: ${total_cost:.4f}")
    else:
        typer.echo("  (no LLM usage yet)")
