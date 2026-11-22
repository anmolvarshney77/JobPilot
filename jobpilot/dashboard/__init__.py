from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

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

_STATUSES = ["new", "shortlisted", "prepared", "applied", "filtered_out", "closed"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_session():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///./jobpilot.db")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session


@dashboard_app.get("/", response_class=HTMLResponse)
async def jobs_list(request: Request, status: str = ""):
    Session = _get_session()
    with Session() as session:
        q = select(Job, Company).join(Company, Job.company_id == Company.id)
        if status:
            q = q.where(Job.status == status)
        q = q.order_by(Job.match_score.desc().nullslast())
        rows = session.execute(q).all()

        total = session.execute(select(func.count()).select_from(Job)).scalar() or 0

    job_rows = []
    for job, company in rows:
        details = job.match_details or {}
        job_rows.append({
            "job_id": job.id,
            "title": job.title,
            "company": company.name,
            "countries": ", ".join(job.countries[:3]) if job.countries else "—",
            "status": job.status,
            "sponsorship": details.get("sponsorship_assessment", job.sponsorship_signal),
            "score": int(job.match_score) if job.match_score else "—",
            "posted_at": job.posted_at.strftime("%Y-%m-%d") if job.posted_at else "—",
        })

    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "jobs": job_rows,
        "total": total,
        "statuses": _STATUSES,
        "current_status": status,
    })


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
        outreach_records = session.execute(
            select(Outreach).where(Outreach.job_id == job_id)
        ).scalars().all()

    details = job.match_details or {}
    injection_warning = details.get("prompt_injection_detected") or details.get("prompt_injection")

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job,
        "company_name": company.name if company else "Unknown",
        "outreach_records": outreach_records,
        "injection_warning": injection_warning,
        "match_summary": details.get("one_line_summary", ""),
        "matched_skills": details.get("matched_skills", []),
        "missing_must_haves": details.get("missing_must_haves", []),
    })


@dashboard_app.post("/outreach/{outreach_id}/mark-sent", response_class=HTMLResponse)
async def mark_sent(request: Request, outreach_id: int):
    Session = _get_session()
    with Session() as session:
        rec = session.execute(
            select(Outreach).where(Outreach.id == outreach_id)
        ).scalar_one_or_none()
        if rec:
            rec.sent_at = _now()
            session.commit()

    return HTMLResponse(
        f'<div id="outreach-{outreach_id}" style="border:1px solid #e5e7eb;border-radius:6px;padding:12px;">'
        f'<strong>{rec.contact_name if rec else "Contact"}</strong>'
        f'<span style="margin-left:12px;font-size:12px;color:#059669;">✓ Sent {_now().strftime("%Y-%m-%d")}</span>'
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
        f'<span id="outreach-reply-{outreach_id}" style="font-size:12px;color:#059669;">'
        f'{"✓ " + label if label else ""}</span>'
    )


@dashboard_app.get("/follow-ups", response_class=HTMLResponse)
async def follow_ups(request: Request):
    Session = _get_session()
    with Session() as session:
        pairs = get_follow_up_candidates(session)

    candidates = []
    for job, outreach in pairs:
        Session2 = _get_session()
        with Session2() as s:
            app_row = s.execute(
                select(Application).where(Application.job_id == job.id)
            ).scalar_one_or_none()

        applied_days_ago = 0
        if app_row and app_row.submitted_at:
            applied_days_ago = (_now() - app_row.submitted_at).days

        Session3 = _get_session()
        with Session3() as s:
            company = s.execute(
                select(Company).where(Company.id == job.company_id)
            ).scalar_one_or_none()

        candidates.append({
            "job_id": job.id,
            "title": job.title,
            "company": company.name if company else "Unknown",
            "contact_name": outreach.contact_name,
            "sent_at": outreach.sent_at.strftime("%Y-%m-%d") if outreach.sent_at else "—",
            "applied_days_ago": applied_days_ago,
            "follow_up_draft": None,
        })

    return templates.TemplateResponse("follow_ups.html", {
        "request": request,
        "candidates": candidates,
    })


@dashboard_app.get("/stats", response_class=HTMLResponse)
async def stats(request: Request):
    Session = _get_session()
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

        job_counts_rows = session.execute(
            select(Job.status, func.count().label("count")).group_by(Job.status)
        ).fetchall()

    total_cost = sum(r.cost or 0.0 for r in llm_rows)
    job_counts = [{"status": r.status, "count": r.count} for r in job_counts_rows]

    return templates.TemplateResponse("stats.html", {
        "request": request,
        "run_rows": run_rows,
        "llm_rows": llm_rows,
        "total_cost": total_cost,
        "job_counts": job_counts,
    })
