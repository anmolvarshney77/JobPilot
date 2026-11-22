"""Seed the database with realistic test data for dashboard development."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed_test_data(session) -> None:
    """Idempotent: safe to call multiple times; skips if data already present."""
    from jobpilot.db import Application, Company, Job, LLMUsage, Outreach, RunLog

    if session.execute(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(Company)).scalar() > 0:
        return

    now = _now()

    # ---- Companies ----
    companies_data = [
        {"name": "Zalando", "normalized_name": "zalando", "ats_type": "greenhouse", "ats_slug": "zalando", "verified": True, "consecutive_failures": 0, "last_fetch_ok": now - timedelta(hours=2), "source_discovered_from": "companies.yaml"},
        {"name": "Klarna", "normalized_name": "klarna", "ats_type": "lever", "ats_slug": "klarna", "verified": True, "consecutive_failures": 0, "last_fetch_ok": now - timedelta(hours=3), "source_discovered_from": "companies.yaml"},
        {"name": "Revolut", "normalized_name": "revolut", "ats_type": "greenhouse", "ats_slug": "revolut", "verified": True, "consecutive_failures": 1, "last_fetch_ok": now - timedelta(days=1), "source_discovered_from": "companies.yaml"},
        {"name": "Wise", "normalized_name": "wise", "ats_type": "greenhouse", "ats_slug": "wise", "verified": False, "consecutive_failures": 3, "last_fetch_ok": None, "source_discovered_from": "companies.yaml"},
        {"name": "Delivery Hero", "normalized_name": "delivery hero", "ats_type": "workday", "ats_slug": "deliveryhero", "verified": True, "consecutive_failures": 0, "last_fetch_ok": now - timedelta(hours=1), "source_discovered_from": "companies.yaml"},
    ]
    companies = []
    for cd in companies_data:
        c = Company(**cd, added_at=now - timedelta(days=10))
        session.add(c)
        companies.append(c)
    session.flush()

    # ---- Jobs ----
    jobs_data = [
        {
            "source": "greenhouse", "external_id": "gh-001", "company_idx": 0,
            "title": "Senior Backend Engineer", "location_raw": "Berlin, Germany",
            "countries": ["DE"], "remote_type": "hybrid",
            "url": "https://jobs.zalando.com/en/jobs/1",
            "description": "We are looking for a Senior Backend Engineer to join our team.",
            "posted_at": now - timedelta(days=2), "first_seen_at": now - timedelta(days=1),
            "sponsorship_signal": "yes", "match_score": 92.0,
            "match_details": {
                "match_summary": "Strong match across Go, distributed systems, and PostgreSQL.",
                "matched_skills": ["Go", "PostgreSQL", "Kubernetes", "gRPC"],
                "missing_must_haves": [],
                "missing_nice_to_haves": ["Kafka"],
                "red_flags": [],
                "sponsorship_assessment": "yes",
                "prompt_injection_detected": False,
            },
            "status": "shortlisted", "filter_reason": None,
            "salary_min": 90000, "salary_max": 130000, "salary_currency": "EUR",
            "required_languages": ["English"],
        },
        {
            "source": "lever", "external_id": "lv-001", "company_idx": 1,
            "title": "Staff Engineer, Payments", "location_raw": "Stockholm, Sweden",
            "countries": ["SE"], "remote_type": "remote",
            "url": "https://jobs.lever.co/klarna/1",
            "description": "Build the future of payments infrastructure at scale.",
            "posted_at": now - timedelta(days=5), "first_seen_at": now - timedelta(days=4),
            "sponsorship_signal": "unknown",
            "match_score": 85.0,
            "match_details": {
                "match_summary": "Good fit for payments background, missing Kotlin experience.",
                "matched_skills": ["Java", "Microservices", "SQL"],
                "missing_must_haves": ["Kotlin"],
                "missing_nice_to_haves": ["Spring Boot"],
                "red_flags": [],
                "sponsorship_assessment": "unknown",
                "prompt_injection_detected": False,
            },
            "status": "prepared",
            "salary_min": 100000, "salary_max": 150000, "salary_currency": "SEK",
            "required_languages": ["English"],
        },
        {
            "source": "greenhouse", "external_id": "gh-002", "company_idx": 2,
            "title": "Principal Engineer", "location_raw": "London, UK",
            "countries": ["GB"], "remote_type": "onsite",
            "url": "https://www.revolut.com/careers/job/1",
            "description": "Lead architecture decisions at Revolut.",
            "posted_at": now - timedelta(days=10), "first_seen_at": now - timedelta(days=9),
            "sponsorship_signal": "no",
            "match_score": 74.0,
            "match_details": {
                "match_summary": "Title match but sponsorship refused explicitly.",
                "matched_skills": ["Python", "Django", "Redis"],
                "missing_must_haves": [],
                "missing_nice_to_haves": ["Kotlin"],
                "red_flags": ["sponsorship_refused_explicitly"],
                "sponsorship_assessment": "no",
                "prompt_injection_detected": False,
            },
            "status": "filtered_out",
            "filter_reason": "sponsorship_refused",
        },
        {
            "source": "greenhouse", "external_id": "gh-003", "company_idx": 0,
            "title": "Engineering Manager", "location_raw": "Berlin, Germany",
            "countries": ["DE"], "remote_type": "hybrid",
            "url": "https://jobs.zalando.com/en/jobs/2",
            "description": "Lead a team of 8 engineers.",
            "posted_at": now - timedelta(days=1), "first_seen_at": now - timedelta(hours=6),
            "sponsorship_signal": "yes",
            "match_score": 88.0,
            "match_details": {
                "match_summary": "Strong management experience, slight overfit on IC role.",
                "matched_skills": ["Team leadership", "Python", "Agile"],
                "missing_must_haves": [],
                "missing_nice_to_haves": [],
                "red_flags": [],
                "sponsorship_assessment": "yes",
                "prompt_injection_detected": False,
            },
            "status": "new",
        },
        {
            "source": "workday", "external_id": "wd-001", "company_idx": 4,
            "title": "Backend Engineer, Platform", "location_raw": "Berlin, Germany",
            "countries": ["DE"], "remote_type": "hybrid",
            "url": "https://careers.deliveryhero.com/job/1",
            "description": "Platform engineering at scale.",
            "posted_at": now - timedelta(days=7), "first_seen_at": now - timedelta(days=6),
            "sponsorship_signal": "yes",
            "match_score": 56.0,
            "match_details": {
                "match_summary": "Title matches but low keyword overlap.",
                "matched_skills": ["Python"],
                "missing_must_haves": ["Go", "C++"],
                "missing_nice_to_haves": [],
                "red_flags": [],
                "sponsorship_assessment": "yes",
                "prompt_injection_detected": False,
            },
            "status": "filtered_out",
            "filter_reason": "low_keyword_score",
        },
        {
            "source": "greenhouse", "external_id": "gh-004", "company_idx": 2,
            "title": "Senior Software Engineer", "location_raw": "London, UK",
            "countries": ["GB"], "remote_type": "hybrid",
            "url": "https://www.revolut.com/careers/job/2",
            "description": "Great opportunity at Revolut.",
            "posted_at": now - timedelta(days=30), "first_seen_at": now - timedelta(days=29),
            "sponsorship_signal": "yes",
            "match_score": 91.0,
            "match_details": {
                "match_summary": "Excellent match.",
                "matched_skills": ["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
                "missing_must_haves": [],
                "missing_nice_to_haves": [],
                "red_flags": [],
                "sponsorship_assessment": "yes",
                "prompt_injection_detected": False,
            },
            "status": "applied",
        },
        {
            "source": "lever", "external_id": "lv-002", "company_idx": 1,
            "title": "Data Engineer", "location_raw": "Stockholm, Sweden",
            "countries": ["SE"], "remote_type": "remote",
            "url": "https://jobs.lever.co/klarna/2",
            "description": "Data pipeline engineering.",
            "posted_at": now - timedelta(days=15), "first_seen_at": now - timedelta(days=14),
            "sponsorship_signal": "yes",
            "match_score": 82.0,
            "match_details": {
                "match_summary": "Good match for data infra.",
                "matched_skills": ["Python", "Spark", "dbt"],
                "missing_must_haves": [],
                "missing_nice_to_haves": ["Flink"],
                "red_flags": [],
                "sponsorship_assessment": "yes",
                "prompt_injection_detected": False,
            },
            "status": "applied",
        },
        {
            "source": "greenhouse", "external_id": "gh-005", "company_idx": 0,
            "title": "Platform Engineer", "location_raw": "Berlin, Germany",
            "countries": ["DE"], "remote_type": "hybrid",
            "url": "https://jobs.zalando.com/en/jobs/3",
            "description": "Platform infra.",
            "posted_at": now - timedelta(days=45), "first_seen_at": now - timedelta(days=44),
            "sponsorship_signal": "yes",
            "match_score": 89.0,
            "match_details": {
                "match_summary": "Great platform match.",
                "matched_skills": ["Kubernetes", "Terraform", "Go"],
                "missing_must_haves": [],
                "missing_nice_to_haves": [],
                "red_flags": [],
                "sponsorship_assessment": "yes",
                "prompt_injection_detected": False,
            },
            "status": "applied",
        },
    ]

    jobs = []
    for jd in jobs_data:
        company_idx = jd.pop("company_idx")
        jd.setdefault("salary_min", None)
        jd.setdefault("salary_max", None)
        jd.setdefault("salary_currency", None)
        jd.setdefault("required_languages", [])
        jd.setdefault("filter_reason", None)
        j = Job(
            company_id=companies[company_idx].id,
            last_seen_at=now,
            is_live=True,
            required_years=None,
            remote_allowed_countries=[],
            apply_url=None,
            **jd,
        )
        session.add(j)
        jobs.append(j)
    session.flush()

    # ---- Applications ----
    app_configs = [
        # job idx 5: applied, interview outcome
        {"job_idx": 5, "submitted_at": now - timedelta(days=25), "outcome": "interview",
         "outcome_date": now - timedelta(days=18), "answers": {"why_company": "Love their product.", "why_role": "Aligns with my backend expertise."}},
        # job idx 6: applied, rejected
        {"job_idx": 6, "submitted_at": now - timedelta(days=12), "outcome": "rejected",
         "outcome_date": now - timedelta(days=5), "answers": {}},
        # job idx 7: applied, ghosted (submitted 44 days ago — auto-ghosted)
        {"job_idx": 7, "submitted_at": now - timedelta(days=44), "outcome": "none",
         "outcome_date": None, "answers": {}},
        # job idx 1: prepared
        {"job_idx": 1, "submitted_at": None, "outcome": "none", "outcome_date": None,
         "answers": {"why_company": "Klarna is leading fintech.", "why_role": "Payments infra interests me."}},
    ]
    apps = []
    for ac in app_configs:
        job_idx = ac.pop("job_idx")
        a = Application(job_id=jobs[job_idx].id, **ac)
        session.add(a)
        apps.append(a)
    session.flush()

    # ---- Outreach ----
    outreach_data = [
        {"job_idx": 5, "contact_name": "Sarah Johnson", "contact_role": "hiring_manager",
         "contact_url": "https://linkedin.com/in/sarahjohnson",
         "message_draft": json.dumps({"linkedin_note": "Hi Sarah, I applied for the Senior SWE role at Revolut and wanted to connect.", "email_body": "Dear Sarah,\n\nI recently applied for the Senior SWE role at Revolut..."}),
         "sent_at": now - timedelta(days=24), "reply_status": "interested"},
        {"job_idx": 0, "contact_name": "Max Müller", "contact_role": "hiring_manager",
         "contact_url": None,
         "message_draft": json.dumps({"linkedin_note": "Hi Max, I'm very interested in the Senior Backend role at Zalando.", "email_body": ""}),
         "sent_at": None, "reply_status": None},
        {"job_idx": 6, "contact_name": "Anna Lindqvist", "contact_role": "recruiter",
         "contact_url": "https://linkedin.com/in/annalindqvist",
         "message_draft": json.dumps({"linkedin_note": "Hi Anna!", "email_body": ""}),
         "sent_at": now - timedelta(days=10), "reply_status": "no_reply"},
    ]
    for od in outreach_data:
        job_idx = od.pop("job_idx")
        o = Outreach(job_id=jobs[job_idx].id, **od)
        session.add(o)
    session.flush()

    # ---- LLM Usage ----
    llm_records = [
        {"model": "claude-haiku-5-5", "purpose": "scoring", "input_tokens": 1200, "output_tokens": 300, "cost_usd": 0.0012, "called_at": now - timedelta(hours=4)},
        {"model": "claude-haiku-5-5", "purpose": "scoring", "input_tokens": 980, "output_tokens": 240, "cost_usd": 0.0009, "called_at": now - timedelta(hours=4)},
        {"model": "claude-sonnet-5-5", "purpose": "tailoring", "input_tokens": 3200, "output_tokens": 800, "cost_usd": 0.0180, "called_at": now - timedelta(hours=3)},
        {"model": "claude-sonnet-5-5", "purpose": "cover_letter", "input_tokens": 2800, "output_tokens": 600, "cost_usd": 0.0150, "called_at": now - timedelta(hours=2)},
        {"model": "claude-haiku-5-5", "purpose": "outreach", "input_tokens": 1500, "output_tokens": 400, "cost_usd": 0.0015, "called_at": now - timedelta(hours=1)},
    ]
    for lr in llm_records:
        u = LLMUsage(job_id=None, **lr)
        session.add(u)

    # ---- Run logs ----
    run_logs = [
        {"command": "fetch", "status": "ok", "started_at": now - timedelta(hours=5), "finished_at": now - timedelta(hours=4, minutes=55), "summary": {"jobs_found": 42}},
        {"command": "score", "status": "ok", "started_at": now - timedelta(hours=4), "finished_at": now - timedelta(hours=3, minutes=50), "summary": {"scored": 38}},
        {"command": "prepare", "status": "ok", "started_at": now - timedelta(hours=3), "finished_at": now - timedelta(hours=2, minutes=58), "summary": {"prepared": 2}},
        {"command": "outreach", "status": "ok", "started_at": now - timedelta(hours=1), "finished_at": now - timedelta(minutes=55), "summary": {"drafted": 3}},
    ]
    for rl_data in run_logs:
        rl = RunLog(error=None, **rl_data)
        session.add(rl)

    session.commit()
