from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from jobpilot.db import Application, Company, Job, LLMUsage, Outreach, RunLog
from jobpilot.outreach.follow_up import get_follow_up_candidates

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

dashboard_app = FastAPI(title="JobPilot Dashboard")

_STATUSES = ["new", "shortlisted", "prepared", "applied", "filtered_out", "closed", "skipped"]

# Allow tests to inject an in-memory session factory
_session_factory_override = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_session():
    if _session_factory_override is not None:
        return _session_factory_override
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine, expire_on_commit=False)


def _safe_dir_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name


def _get_budget() -> float:
    try:
        from jobpilot.config import load_app_config
        cfg = load_app_config("config.yaml")
        return cfg.llm.monthly_budget_usd
    except Exception:
        return 15.0


def _is_fresh(first_seen_at: datetime | None) -> bool:
    if first_seen_at is None:
        return False
    return (_now() - first_seen_at).days < 3


def _score_class(score: float | None) -> str:
    if score is None:
        return "score-none"
    if score >= 90:
        return "score-green"
    if score >= 80:
        return "score-blue"
    if score >= 70:
        return "score-amber"
    return "score-grey"


def _score_band(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 90:
        return "90-100"
    if score >= 80:
        return "80-89"
    if score >= 70:
        return "70-79"
    return "<70"


def _interview_rate(interviews: int, total: int) -> float:
    return round(interviews / total * 100, 1) if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Page 1: Jobs
# ---------------------------------------------------------------------------

@dashboard_app.get("/", response_class=HTMLResponse)
async def jobs_list(
    request: Request,
    status: str = "",
    country: str = "",
    source: str = "",
    sponsorship: str = "",
    remote_type: str = "",
    min_score: str = "",
    sort: str = "score_desc",
):
    Session = _get_session()
    with Session() as session:
        q = select(Job, Company).join(Company, Job.company_id == Company.id)
        if status:
            q = q.where(Job.status == status)
        if source:
            q = q.where(Job.source == source)
        if remote_type:
            q = q.where(Job.remote_type == remote_type)
        if min_score:
            try:
                q = q.where(Job.match_score >= float(min_score))
            except ValueError:
                pass

        sort_map = {
            "score_desc": Job.match_score.desc().nullslast(),
            "score_asc": Job.match_score.asc().nullsfirst(),
            "posted_desc": Job.posted_at.desc().nullslast(),
            "first_seen_desc": Job.first_seen_at.desc(),
        }
        q = q.order_by(sort_map.get(sort, Job.match_score.desc().nullslast()))
        rows = session.execute(q).all()

        total = session.execute(select(func.count()).select_from(Job)).scalar() or 0

        # Distinct filter values
        all_sources = [r[0] for r in session.execute(
            select(Job.source).distinct().order_by(Job.source)
        ).all()]
        all_remote = [r[0] for r in session.execute(
            select(Job.remote_type).distinct().where(Job.remote_type.is_not(None)).order_by(Job.remote_type)
        ).all()]

    now = _now()
    job_rows = []
    for job, company in rows:
        details = job.match_details or {}
        spons = details.get("sponsorship_assessment", job.sponsorship_signal)

        # Country filter (JSON array)
        job_countries = job.countries if isinstance(job.countries, list) else []
        if country and country not in job_countries:
            continue

        # Sponsorship filter
        if sponsorship and spons != sponsorship:
            continue

        injection = bool(details.get("prompt_injection_detected") or details.get("prompt_injection"))
        fresh = _is_fresh(job.first_seen_at)

        job_rows.append({
            "job_id": job.id,
            "title": job.title,
            "company": company.name,
            "countries": ", ".join(job_countries[:3]) if job_countries else "—",
            "status": job.status,
            "sponsorship": spons,
            "score": int(job.match_score) if job.match_score is not None else None,
            "score_class": _score_class(job.match_score),
            "posted_at": job.posted_at.strftime("%Y-%m-%d") if job.posted_at else "—",
            "remote_type": job.remote_type or "—",
            "source": job.source,
            "fresh": fresh,
            "injection": injection,
        })

    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": job_rows,
        "total": total,
        "filtered_count": len(job_rows),
        "statuses": _STATUSES,
        "current_status": status,
        "current_country": country,
        "current_source": source,
        "current_sponsorship": sponsorship,
        "current_remote_type": remote_type,
        "current_min_score": min_score,
        "current_sort": sort,
        "all_sources": all_sources,
        "all_remote_types": all_remote,
    })


# ---------------------------------------------------------------------------
# Page 2: Filtered-out audit
# ---------------------------------------------------------------------------

@dashboard_app.get("/filtered-out", response_class=HTMLResponse)
async def filtered_out(request: Request):
    Session = _get_session()
    with Session() as session:
        rows = session.execute(
            select(Job, Company)
            .join(Company, Job.company_id == Company.id)
            .where(Job.status == "filtered_out")
            .order_by(Job.filter_reason, Job.match_score.desc().nullslast())
        ).all()

    grouped: dict[str, list[dict]] = defaultdict(list)
    for job, company in rows:
        reason = job.filter_reason or "unknown"
        grouped[reason].append({
            "job_id": job.id,
            "title": job.title,
            "company": company.name,
            "countries": ", ".join(job.countries[:2]) if job.countries else "—",
            "score": int(job.match_score) if job.match_score is not None else "—",
            "score_class": _score_class(job.match_score),
        })

    return templates.TemplateResponse(request, "filtered_out.html", {
        "grouped": dict(grouped),
        "total": sum(len(v) for v in grouped.values()),
    })


@dashboard_app.post("/jobs/{job_id}/restore", response_class=HTMLResponse)
async def restore_job(request: Request, job_id: int):
    Session = _get_session()
    with Session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if job:
            job.status = "new"
            job.filter_reason = None
            session.commit()
    return HTMLResponse(
        f'<tr id="job-row-{job_id}" style="opacity:0.4;">'
        f'<td colspan="5" style="text-align:center;font-size:12px;color:#059669;">✓ Restored to new — will be rescored</td>'
        f'</tr>'
    )


# ---------------------------------------------------------------------------
# Page 3: Job detail
# ---------------------------------------------------------------------------

@dashboard_app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    Session = _get_session()
    with Session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if job is None:
            return HTMLResponse("<p>Job not found.</p>", status_code=404)

        company = session.execute(
            select(Company).where(Company.id == job.company_id)
        ).scalar_one_or_none()
        outreach_records = list(session.execute(
            select(Outreach).where(Outreach.job_id == job_id)
        ).scalars().all())

    details = job.match_details or {}
    injection_warning = bool(details.get("prompt_injection_detected") or details.get("prompt_injection"))
    fresh = _is_fresh(job.first_seen_at)

    # Tailored output dir
    company_name = company.name if company else "unknown"
    norm_company = _safe_dir_name(company_name)
    norm_title = _safe_dir_name(job.title)
    output_dir = Path("output") / f"{norm_company}_{norm_title}_{job_id}"
    output_exists = output_dir.exists()

    pdf_path = None
    review_html_path = None
    cover_letter_text = None
    draft_answers: dict = {}

    if output_exists:
        pdfs = list(output_dir.glob("*.pdf"))
        pdf_path = str(pdfs[0]) if pdfs else None
        review_path = output_dir / "review.html"
        review_html_path = str(review_path) if review_path.exists() else None
        cl_path = output_dir / "cover_letter.txt"
        if cl_path.exists():
            cover_letter_text = cl_path.read_text()
        da_path = output_dir / "draft_answers.json"
        if da_path.exists():
            try:
                draft_answers = json.loads(da_path.read_text())
            except Exception:
                pass

    # Parse outreach message_drafts
    outreach_data = []
    for rec in outreach_records:
        md: dict = {}
        if rec.message_draft:
            try:
                md = json.loads(rec.message_draft)
            except Exception:
                md = {"raw": rec.message_draft}
        outreach_data.append({
            "id": rec.id,
            "contact_name": rec.contact_name,
            "contact_role": rec.contact_role,
            "contact_url": rec.contact_url,
            "linkedin_note": md.get("linkedin_note", ""),
            "email_body": md.get("email_body", ""),
            "sent_at": rec.sent_at.strftime("%Y-%m-%d") if rec.sent_at else None,
            "reply_status": rec.reply_status,
        })

    required_langs = job.required_languages if isinstance(job.required_languages, list) else []

    return templates.TemplateResponse(request, "job_detail.html", {
        "job": job,
        "job_id": job_id,
        "company_name": company_name,
        "injection_warning": injection_warning,
        "fresh": fresh,
        "details": details,
        "matched_skills": details.get("matched_skills", []),
        "missing_must_haves": details.get("missing_must_haves", []),
        "missing_nice_to_haves": details.get("missing_nice_to_haves", []),
        "required_languages": required_langs,
        "red_flags": details.get("red_flags", []),
        "outreach_data": outreach_data,
        "output_exists": output_exists,
        "pdf_path": pdf_path,
        "review_html_path": review_html_path,
        "cover_letter_text": cover_letter_text,
        "draft_answers": draft_answers,
        "score_class": _score_class(job.match_score),
    })


@dashboard_app.post("/jobs/{job_id}/status", response_class=HTMLResponse)
async def update_job_status(request: Request, job_id: int, new_status: str = Form(...)):
    Session = _get_session()
    with Session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if job:
            job.status = new_status
            session.commit()
    badge_classes = {
        "new": "badge-new", "shortlisted": "badge-shortlisted", "prepared": "badge-prepared",
        "applied": "badge-applied", "filtered_out": "badge-filtered_out",
        "closed": "badge-closed", "skipped": "badge-closed",
    }
    cls = badge_classes.get(new_status, "badge-new")
    return HTMLResponse(
        f'<span id="status-badge-{job_id}" class="badge {cls}">{new_status}</span>'
    )


@dashboard_app.post("/jobs/{job_id}/save-answers", response_class=HTMLResponse)
async def save_draft_answers(
    request: Request,
    job_id: int,
    why_company: str = Form(""),
    why_role: str = Form(""),
    proud_project: str = Form(""),
):
    answers = {"why_company": why_company, "why_role": why_role, "proud_project": proud_project}
    Session = _get_session()
    with Session() as session:
        app_row = session.execute(
            select(Application).where(Application.job_id == job_id)
        ).scalar_one_or_none()
        if app_row:
            existing = dict(app_row.answers or {})
            existing.update(answers)
            app_row.answers = existing
            session.commit()
    return HTMLResponse('<span style="font-size:12px;color:#059669;">✓ Saved</span>')


# ---------------------------------------------------------------------------
# Keep existing outreach HTMX routes
# ---------------------------------------------------------------------------

@dashboard_app.post("/outreach/{outreach_id}/mark-sent", response_class=HTMLResponse)
async def mark_sent(request: Request, outreach_id: int):
    Session = _get_session()
    contact_name = "Contact"
    with Session() as session:
        rec = session.execute(
            select(Outreach).where(Outreach.id == outreach_id)
        ).scalar_one_or_none()
        if rec:
            rec.sent_at = _now()
            contact_name = rec.contact_name
            session.commit()

    return HTMLResponse(
        f'<div id="outreach-{outreach_id}" style="border:1px solid var(--border);border-radius:6px;padding:12px;">'
        f'<strong>{contact_name}</strong>'
        f'<span style="margin-left:12px;font-size:12px;color:var(--success);">✓ Sent {_now().strftime("%Y-%m-%d")}</span>'
        f'</div>'
    )


@dashboard_app.post("/outreach/{outreach_id}/reply", response_class=HTMLResponse)
async def update_reply(request: Request, outreach_id: int, reply_status: str = Form("")):
    Session = _get_session()
    with Session() as session:
        rec = session.execute(
            select(Outreach).where(Outreach.id == outreach_id)
        ).scalar_one_or_none()
        if rec:
            rec.reply_status = reply_status or None
            session.commit()
    label = reply_status.replace("_", " ").title() if reply_status else ""
    return HTMLResponse(
        f'<span id="outreach-reply-{outreach_id}" style="font-size:12px;color:var(--success);">'
        f'{"✓ " + label if label else ""}</span>'
    )


# ---------------------------------------------------------------------------
# Follow-ups (existing, kept)
# ---------------------------------------------------------------------------

@dashboard_app.get("/follow-ups", response_class=HTMLResponse)
async def follow_ups(request: Request):
    Session = _get_session()
    with Session() as session:
        pairs = get_follow_up_candidates(session)
        candidates = []
        for job, outreach in pairs:
            app_row = session.execute(
                select(Application).where(Application.job_id == job.id)
            ).scalar_one_or_none()
            company = session.execute(
                select(Company).where(Company.id == job.company_id)
            ).scalar_one_or_none()
            applied_days_ago = 0
            if app_row and app_row.submitted_at:
                applied_days_ago = (_now() - app_row.submitted_at).days
            candidates.append({
                "job_id": job.id,
                "title": job.title,
                "company": company.name if company else "Unknown",
                "contact_name": outreach.contact_name,
                "sent_at": outreach.sent_at.strftime("%Y-%m-%d") if outreach.sent_at else "—",
                "applied_days_ago": applied_days_ago,
                "follow_up_draft": None,
            })

    return templates.TemplateResponse(request, "follow_ups.html", {"candidates": candidates})


# ---------------------------------------------------------------------------
# Page 4: Applications
# ---------------------------------------------------------------------------

@dashboard_app.get("/applications", response_class=HTMLResponse)
async def applications_list(request: Request):
    Session = _get_session()
    with Session() as session:
        # Auto-ghost stale applications
        cutoff = _now() - timedelta(days=30)
        stale = session.execute(
            select(Application).where(
                Application.outcome == "none",
                Application.submitted_at.is_not(None),
                Application.submitted_at < cutoff,
            )
        ).scalars().all()
        for app_row in stale:
            app_row.outcome = "ghosted"
            app_row.outcome_date = _now()
        if stale:
            session.commit()

        rows = session.execute(
            select(Application, Job, Company)
            .join(Job, Application.job_id == Job.id)
            .join(Company, Job.company_id == Company.id)
            .order_by(Application.submitted_at.desc().nullslast())
        ).all()

    app_rows = []
    for app, job, company in rows:
        days_since = None
        if app.submitted_at:
            days_since = (_now() - app.submitted_at).days
        app_rows.append({
            "app_id": app.id,
            "job_id": job.id,
            "title": job.title,
            "company": company.name,
            "countries": ", ".join(job.countries[:2]) if job.countries else "—",
            "score": int(job.match_score) if job.match_score is not None else "—",
            "submitted_at": app.submitted_at.strftime("%Y-%m-%d") if app.submitted_at else "—",
            "outcome": app.outcome,
            "days_since": days_since,
        })

    return templates.TemplateResponse(request, "applications.html", {"apps": app_rows})


@dashboard_app.get("/applications/{app_id}/detail", response_class=HTMLResponse)
async def application_detail(request: Request, app_id: int):
    Session = _get_session()
    with Session() as session:
        app_row = session.execute(
            select(Application).where(Application.id == app_id)
        ).scalar_one_or_none()
        if not app_row:
            return HTMLResponse("<p>Not found.</p>", status_code=404)
        job = session.execute(select(Job).where(Job.id == app_row.job_id)).scalar_one_or_none()

    answers = app_row.answers or {}
    answers_html = ""
    for k, v in answers.items():
        answers_html += f"<p><strong>{k}:</strong> {v}</p>"

    screenshot_html = ""
    if app_row.screenshot_path and Path(app_row.screenshot_path).exists():
        screenshot_html = f'<img src="/static/{app_row.screenshot_path}" style="max-width:100%;border:1px solid var(--border);border-radius:4px;">'

    outcome_options = ["none", "interview", "rejected", "offer", "ghosted"]
    opts = "".join(
        f'<option value="{o}" {"selected" if app_row.outcome == o else ""}>{o}</option>'
        for o in outcome_options
    )
    outcome_date_val = app_row.outcome_date.strftime("%Y-%m-%d") if app_row.outcome_date else ""

    html = f"""
<div style="padding:16px;background:var(--surface);border-radius:6px;margin-top:8px;">
  {screenshot_html}
  <div style="margin-top:12px;">{answers_html or "<p style='color:var(--text-muted)'>No answers recorded.</p>"}</div>
  <form hx-post="/applications/{app_id}/outcome" hx-target="#app-row-{app_id}" hx-swap="outerHTML"
        style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
    <label style="font-size:13px;">Outcome:</label>
    <select name="outcome">{opts}</select>
    <input type="date" name="outcome_date" value="{outcome_date_val}" style="padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:13px;">
    <button type="submit" class="btn btn-primary btn-sm">Save</button>
  </form>
</div>
"""
    return HTMLResponse(html)


@dashboard_app.post("/applications/{app_id}/outcome", response_class=HTMLResponse)
async def update_outcome(
    request: Request,
    app_id: int,
    outcome: str = Form("none"),
    outcome_date: str = Form(""),
):
    Session = _get_session()
    with Session() as session:
        app_row = session.execute(
            select(Application).where(Application.id == app_id)
        ).scalar_one_or_none()
        if app_row:
            app_row.outcome = outcome
            if outcome_date:
                try:
                    app_row.outcome_date = datetime.strptime(outcome_date, "%Y-%m-%d")
                except ValueError:
                    pass
            session.commit()

    outcome_colors = {
        "interview": "color:#059669;", "offer": "color:#059669;font-weight:700;",
        "rejected": "color:#dc2626;", "ghosted": "color:#6b7280;", "none": "",
    }
    style = outcome_colors.get(outcome, "")
    return HTMLResponse(
        f'<tr id="app-row-{app_id}"><td colspan="7"><span style="{style}">{outcome}</span> — updated</td></tr>'
    )


# ---------------------------------------------------------------------------
# Page 5: Companies
# ---------------------------------------------------------------------------

@dashboard_app.get("/companies", response_class=HTMLResponse)
async def companies_list(request: Request):
    Session = _get_session()
    with Session() as session:
        companies = session.execute(
            select(Company).order_by(Company.consecutive_failures.desc(), Company.name)
        ).scalars().all()

        jobs_by_company: dict[int, int] = {}
        for company in companies:
            count = session.execute(
                select(func.count()).select_from(Job).where(Job.company_id == company.id)
            ).scalar() or 0
            jobs_by_company[company.id] = count

    rows = []
    for c in companies:
        rows.append({
            "id": c.id,
            "name": c.name,
            "ats_type": c.ats_type or "—",
            "ats_slug": c.ats_slug or "—",
            "verified": c.verified,
            "consecutive_failures": c.consecutive_failures,
            "jobs_found": jobs_by_company.get(c.id, 0),
            "last_fetch_ok": c.last_fetch_ok.strftime("%Y-%m-%d") if c.last_fetch_ok else "—",
            "source_discovered_from": c.source_discovered_from or "—",
        })

    return templates.TemplateResponse(request, "companies.html", {"companies": rows})


# ---------------------------------------------------------------------------
# Page 6: Insights
# ---------------------------------------------------------------------------

@dashboard_app.get("/insights", response_class=HTMLResponse)
async def insights(request: Request):
    Session = _get_session()
    with Session() as session:
        outcome_rows = session.execute(
            select(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .where(Application.outcome.in_(["interview", "rejected", "offer", "ghosted"]))
        ).all()

        total_with_outcomes = len(outcome_rows)

        if total_with_outcomes < 20:
            return templates.TemplateResponse(request, "insights.html", {
                "ready": False,
                "total_with_outcomes": total_with_outcomes,
                "needed": 20,
            })

        # Build jobs_with_sent_outreach set
        jobs_with_outreach = set(
            r[0] for r in session.execute(
                select(Outreach.job_id).where(Outreach.sent_at.is_not(None)).distinct()
            ).all()
        )

    def is_interview(outcome: str) -> bool:
        return outcome in ("interview", "offer")

    # --- Score bands ---
    band_data: dict[str, dict[str, int]] = {
        "70-79": {"total": 0, "interviews": 0},
        "80-89": {"total": 0, "interviews": 0},
        "90-100": {"total": 0, "interviews": 0},
        "<70": {"total": 0, "interviews": 0},
    }
    country_data: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "interviews": 0})
    source_data: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "interviews": 0})
    spons_data: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "interviews": 0})
    days_data: dict[str, dict[str, int]] = {
        "<7 days": {"total": 0, "interviews": 0},
        "7-30 days": {"total": 0, "interviews": 0},
        ">30 days": {"total": 0, "interviews": 0},
        "unknown": {"total": 0, "interviews": 0},
    }
    outreach_data: dict[str, dict[str, int]] = {
        "with_outreach": {"total": 0, "interviews": 0},
        "without_outreach": {"total": 0, "interviews": 0},
    }

    for app, job in outcome_rows:
        interview = is_interview(app.outcome)
        band = _score_band(job.match_score)
        if band and band in band_data:
            band_data[band]["total"] += 1
            if interview:
                band_data[band]["interviews"] += 1

        for country in (job.countries or [])[:1]:
            country_data[country]["total"] += 1
            if interview:
                country_data[country]["interviews"] += 1

        source_data[job.source]["total"] += 1
        if interview:
            source_data[job.source]["interviews"] += 1

        md = job.match_details or {}
        spons = md.get("sponsorship_assessment", job.sponsorship_signal or "unknown")
        spons_data[spons]["total"] += 1
        if interview:
            spons_data[spons]["interviews"] += 1

        if app.submitted_at and job.posted_at:
            d = (app.submitted_at - job.posted_at).days
            if d < 7:
                dk = "<7 days"
            elif d <= 30:
                dk = "7-30 days"
            else:
                dk = ">30 days"
        else:
            dk = "unknown"
        days_data[dk]["total"] += 1
        if interview:
            days_data[dk]["interviews"] += 1

        ok = "with_outreach" if job.id in jobs_with_outreach else "without_outreach"
        outreach_data[ok]["total"] += 1
        if interview:
            outreach_data[ok]["interviews"] += 1

    # Build table dicts
    def _table(raw: dict) -> list[dict]:
        return [
            {
                "band": k,
                "total": v["total"],
                "interviews": v["interviews"],
                "rate": _interview_rate(v["interviews"], v["total"]),
            }
            for k, v in raw.items() if v["total"] > 0
        ]

    score_table = _table(band_data)
    country_table = sorted(_table(country_data), key=lambda r: r["total"], reverse=True)[:5]
    source_table = _table(source_data)
    spons_table = _table(spons_data)
    days_table = [r for r in _table(days_data) if r["band"] != "unknown"]
    outreach_table = _table(outreach_data)

    # Suggestions
    suggestions = []

    for row in score_table:
        if row["interviews"] == 0 and row["total"] >= 5:
            suggestions.append(
                f"Jobs scored {row['band']} produced 0 interviews out of {row['total']}. "
                f"Consider raising the minimum score threshold."
            )

    with_o = outreach_data["with_outreach"]
    without_o = outreach_data["without_outreach"]
    if with_o["total"] >= 5 and without_o["total"] >= 5:
        rate_with = _interview_rate(with_o["interviews"], with_o["total"])
        rate_without = _interview_rate(without_o["interviews"], without_o["total"])
        if rate_with - rate_without >= 10:
            suggestions.append(
                f"Applications with outreach sent had a {rate_with}% interview rate vs "
                f"{rate_without}% without. Keep sending messages."
            )

    for row in country_table:
        if row["interviews"] == 0 and row["total"] >= 5:
            suggestions.append(
                f"No interviews from {row['band']} yet ({row['total']} applications). "
                f"Consider deprioritising this market."
            )

    return templates.TemplateResponse(request, "insights.html", {
        "ready": True,
        "total_with_outcomes": total_with_outcomes,
        "score_table": score_table,
        "country_table": country_table,
        "source_table": source_table,
        "spons_table": spons_table,
        "days_table": days_table,
        "outreach_table": outreach_table,
        "suggestions": suggestions,
    })


# ---------------------------------------------------------------------------
# Page 7: Stats / Costs
# ---------------------------------------------------------------------------

@dashboard_app.get("/stats", response_class=HTMLResponse)
async def stats(request: Request):
    budget = _get_budget()
    Session = _get_session()
    with Session() as session:
        now = _now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_spend = session.execute(
            select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
                LLMUsage.called_at >= month_start
            )
        ).scalar() or 0.0

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

        job_counts_rows = session.execute(
            select(Job.status, func.count().label("count")).group_by(Job.status)
        ).fetchall()

    total_cost = sum(r.cost or 0.0 for r in llm_rows)
    pct = round(monthly_spend / budget * 100, 1) if budget > 0 else 0.0
    pct_clamped = min(pct, 100)
    job_counts = [{"status": r.status, "count": r.count} for r in job_counts_rows]

    return templates.TemplateResponse(request, "stats.html", {
        "run_rows": run_rows,
        "llm_rows": llm_rows,
        "total_cost": total_cost,
        "job_counts": job_counts,
        "monthly_spend": round(monthly_spend, 4),
        "budget": budget,
        "budget_pct": pct,
        "budget_pct_clamped": pct_clamped,
    })
