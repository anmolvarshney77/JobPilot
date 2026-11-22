from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class DigestData:
    top_matches: list[dict] = field(default_factory=list)
    closing_or_closed: list[dict] = field(default_factory=list)
    follow_ups_due: list[dict] = field(default_factory=list)
    llm_spend_usd: float = 0.0
    llm_budget_usd: float = 15.0
    errors: list[str] = field(default_factory=list)
    run_duration_seconds: float = 0.0
    dry_run: bool = False


def build_digest_text(data: DigestData) -> str:
    now = _now()
    lines: list[str] = []

    lines.append(f"*JobPilot Daily Digest* — {now.strftime('%Y-%m-%d')}")
    if data.dry_run:
        lines.append("⚠ DRY RUN — no changes were made")
    lines.append("")

    # Top matches
    lines.append("*Top New Matches*")
    if data.top_matches:
        for i, m in enumerate(data.top_matches[:10], 1):
            country = m.get("country", "?")
            score = m.get("score", "?")
            sponsor = m.get("sponsorship", "unknown")
            age = m.get("posted_age_days")
            age_str = f"{age}d old" if age is not None else "age unknown"
            url = m.get("url", "")
            title = m.get("title", "?")
            company = m.get("company", "?")
            lines.append(f"{i}. {title} @ {company} ({country}) — Score {score} | {sponsor} | {age_str}")
            if url:
                lines.append(f"   🔗 {url}")
    else:
        lines.append("No new matches.")
    lines.append("")

    # Liveness changes
    lines.append("*Prepared Jobs: Liveness Changes*")
    if data.closing_or_closed:
        for item in data.closing_or_closed:
            lines.append(f"- CLOSED: {item.get('title', '?')} @ {item.get('company', '?')}")
    else:
        lines.append("No changes.")
    lines.append("")

    # Follow-ups
    lines.append("*Follow-ups Due*")
    if data.follow_ups_due:
        for fu in data.follow_ups_due:
            contact = fu.get("contact", "?")
            days = fu.get("days_since_sent", "?")
            lines.append(f"- {fu.get('title', '?')} @ {fu.get('company', '?')} → contact: {contact} (sent {days}d ago)")
    else:
        lines.append("None.")
    lines.append("")

    # LLM Spend
    pct = (data.llm_spend_usd / data.llm_budget_usd * 100) if data.llm_budget_usd > 0 else 0
    lines.append(f"*LLM Spend*: ${data.llm_spend_usd:.2f} / ${data.llm_budget_usd:.2f} ({pct:.0f}%)")
    if pct >= 80:
        lines.append(f"⚠ Warning: {pct:.0f}% of monthly budget used.")
    lines.append("")

    # Errors
    lines.append("*Errors*")
    if data.errors:
        for err in data.errors:
            lines.append(f"- {err}")
    else:
        lines.append("None.")
    lines.append("")

    lines.append(f"Run completed in {data.run_duration_seconds:.1f}s.")
    return "\n".join(lines)


def collect_digest_data(
    session: object,
    app_config: object,
    errors: list[str],
    run_start: datetime,
    dry_run: bool,
) -> DigestData:
    from sqlalchemy import func, select

    from jobpilot.db import Company, Job, LLMUsage, Outreach
    from jobpilot.outreach.follow_up import get_follow_up_candidates

    now = _now()
    yesterday = now - timedelta(days=1)
    two_days_ago = now - timedelta(hours=48)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Top 10 new matches (scored, seen within 48h)
    top_rows = session.execute(  # type: ignore[union-attr]
        select(Job, Company)
        .join(Company, Job.company_id == Company.id)
        .where(
            Job.status.in_(["shortlisted", "new"]),
            Job.match_score.isnot(None),
            Job.first_seen_at >= two_days_ago,
        )
        .order_by(Job.match_score.desc())
        .limit(10)
    ).all()

    top_matches: list[dict] = []
    for job, company in top_rows:
        age_days = None
        if job.posted_at:
            age_days = (now - job.posted_at).days
        details = job.match_details or {}
        countries = job.countries or []
        top_matches.append({
            "title": job.title,
            "company": company.name,
            "country": countries[0] if countries else "?",
            "score": int(job.match_score) if job.match_score else 0,
            "sponsorship": details.get("sponsorship_assessment", job.sponsorship_signal),
            "posted_age_days": age_days,
            "url": job.url,
        })

    # Closing/closed prepared jobs
    closing_rows = session.execute(  # type: ignore[union-attr]
        select(Job, Company)
        .join(Company, Job.company_id == Company.id)
        .where(
            Job.status == "prepared",
            Job.is_live == False,
            Job.last_seen_at >= yesterday,
        )
    ).all()

    closing_or_closed: list[dict] = []
    for job, company in closing_rows:
        closing_or_closed.append({
            "title": job.title,
            "company": company.name,
            "closed_at": job.last_seen_at.strftime("%Y-%m-%d") if job.last_seen_at else "?",
        })

    # Follow-ups due
    follow_up_pairs = get_follow_up_candidates(session)
    follow_ups_due: list[dict] = []
    for job, outreach in follow_up_pairs:
        days_since = (now - outreach.sent_at).days if outreach.sent_at else 0
        follow_ups_due.append({
            "title": job.title,
            "company": "?",
            "contact": outreach.contact_name,
            "days_since_sent": days_since,
        })

    # LLM spend this month
    spend_result = session.execute(  # type: ignore[union-attr]
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
            LLMUsage.called_at >= month_start
        )
    )
    llm_spend = float(spend_result.scalar() or 0.0)

    duration = (now - run_start).total_seconds()
    budget = getattr(getattr(app_config, "llm", None), "monthly_budget_usd", 15.0)

    return DigestData(
        top_matches=top_matches,
        closing_or_closed=closing_or_closed,
        follow_ups_due=follow_ups_due,
        llm_spend_usd=llm_spend,
        llm_budget_usd=budget,
        errors=errors,
        run_duration_seconds=duration,
        dry_run=dry_run,
    )
