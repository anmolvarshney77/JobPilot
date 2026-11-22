"""Dashboard tests: 17 cases covering all 7 pages + HTMX actions."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_session_factory():
    """Create an in-memory SQLite engine and return a sessionmaker.

    StaticPool ensures all sessions share one connection, so the test-seeded
    data remains visible to routes that open new sessions.
    """
    from sqlalchemy.pool import StaticPool

    from jobpilot.db import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    return Session


def _seed(session) -> dict:
    """Seed minimal data and return IDs."""
    from jobpilot.db import Application, Company, Job, LLMUsage, Outreach, RunLog

    now = _now()

    c = Company(
        name="TestCorp", normalized_name="testcorp",
        ats_type="greenhouse", ats_slug="testcorp",
        verified=True, consecutive_failures=0,
        source_discovered_from="test",
        added_at=now,
    )
    session.add(c)
    session.flush()

    j1 = Job(
        source="greenhouse", external_id="tc-001", company_id=c.id,
        title="Senior Backend Engineer", location_raw="Berlin, Germany",
        countries=["DE"], remote_type="hybrid",
        url="https://example.com/job/1",
        description="We need a senior engineer.",
        posted_at=now - timedelta(days=2),
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now, is_live=True,
        sponsorship_signal="yes",
        match_score=92.0,
        match_details={
            "matched_skills": ["Python", "PostgreSQL"],
            "missing_must_haves": [],
            "missing_nice_to_haves": ["Kafka"],
            "red_flags": [],
            "sponsorship_assessment": "yes",
            "prompt_injection_detected": False,
        },
        status="shortlisted",
        required_languages=["English"],
        required_years=None,
        remote_allowed_countries=[],
        salary_min=90000, salary_max=130000, salary_currency="EUR",
        apply_url=None,
    )
    j2 = Job(
        source="lever", external_id="tc-002", company_id=c.id,
        title="Junior Developer", location_raw="Berlin, Germany",
        countries=["DE"], remote_type="onsite",
        url="https://example.com/job/2",
        description="We need a junior dev.",
        posted_at=now - timedelta(days=10),
        first_seen_at=now - timedelta(days=9),
        last_seen_at=now, is_live=True,
        sponsorship_signal="no",
        match_score=55.0,
        match_details={"sponsorship_assessment": "no", "prompt_injection_detected": False},
        status="filtered_out",
        filter_reason="sponsorship_refused",
        required_languages=[], required_years=None,
        remote_allowed_countries=[],
        salary_min=None, salary_max=None, salary_currency=None,
        apply_url=None,
    )
    j3 = Job(
        source="greenhouse", external_id="tc-003", company_id=c.id,
        title="Applied Engineer", location_raw="Amsterdam, NL",
        countries=["NL"], remote_type="remote",
        url="https://example.com/job/3",
        description="Applied role description.",
        posted_at=now - timedelta(days=40),
        first_seen_at=now - timedelta(days=39),
        last_seen_at=now, is_live=True,
        sponsorship_signal="yes",
        match_score=89.0,
        match_details={"matched_skills": ["Go"], "missing_must_haves": [], "sponsorship_assessment": "yes", "prompt_injection_detected": False},
        status="applied",
        required_languages=[], required_years=None,
        remote_allowed_countries=[],
        salary_min=None, salary_max=None, salary_currency=None,
        apply_url=None,
    )
    session.add_all([j1, j2, j3])
    session.flush()

    app1 = Application(
        job_id=j3.id,
        submitted_at=now - timedelta(days=35),
        outcome="interview",
        outcome_date=now - timedelta(days=28),
        answers={"why_company": "Great mission."},
    )
    session.add(app1)
    session.flush()

    o1 = Outreach(
        job_id=j1.id,
        contact_name="Jane Recruiter",
        contact_role="recruiter",
        contact_url="https://linkedin.com/in/jane",
        message_draft='{"linkedin_note": "Hi Jane!", "email_body": ""}',
        sent_at=None, reply_status=None,
    )
    session.add(o1)
    session.flush()

    llm = LLMUsage(
        model="claude-haiku-5-5", purpose="scoring",
        input_tokens=1000, output_tokens=200, cost_usd=0.0010,
        called_at=now,
    )
    session.add(llm)
    rl = RunLog(
        command="fetch", status="ok",
        started_at=now - timedelta(hours=1),
        finished_at=now,
        summary={"jobs_found": 3},
        error=None,
    )
    session.add(rl)
    session.commit()

    return {
        "company_id": c.id,
        "job1_id": j1.id,
        "job2_id": j2.id,
        "job3_id": j3.id,
        "app1_id": app1.id,
        "outreach1_id": o1.id,
    }


@pytest.fixture()
def client():
    """TestClient with in-memory DB injected via _session_factory_override."""
    import jobpilot.dashboard as dashboard_module
    from fastapi.testclient import TestClient

    Session = _make_session_factory()
    with Session() as session:
        ids = _seed(session)

    dashboard_module._session_factory_override = Session
    tc = TestClient(dashboard_module.dashboard_app, raise_server_exceptions=True)
    tc.ids = ids
    yield tc
    dashboard_module._session_factory_override = None


# ---------------------------------------------------------------------------
# Page 1: Jobs list
# ---------------------------------------------------------------------------

def test_jobs_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Senior Backend Engineer" in resp.text


def test_jobs_filter_by_status(client):
    resp = client.get("/?status=filtered_out")
    assert resp.status_code == 200
    assert "Junior Developer" in resp.text
    assert "Senior Backend Engineer" not in resp.text


def test_jobs_filter_by_min_score(client):
    resp = client.get("/?min_score=90")
    assert resp.status_code == 200
    assert "Senior Backend Engineer" in resp.text
    assert "Junior Developer" not in resp.text


def test_jobs_fresh_badge(client):
    # job1 was first seen 1 day ago — should show NEW badge
    resp = client.get("/")
    assert resp.status_code == 200
    assert "NEW" in resp.text


# ---------------------------------------------------------------------------
# Page 2: Filtered-out
# ---------------------------------------------------------------------------

def test_filtered_out_page_renders(client):
    resp = client.get("/filtered-out")
    assert resp.status_code == 200
    assert "Junior Developer" in resp.text
    assert "sponsorship" in resp.text.lower()


def test_restore_job_htmx(client):
    job2_id = client.ids["job2_id"]
    resp = client.post(f"/jobs/{job2_id}/restore")
    assert resp.status_code == 200
    assert "Restored" in resp.text


# ---------------------------------------------------------------------------
# Page 3: Job detail
# ---------------------------------------------------------------------------

def test_job_detail_renders(client):
    job1_id = client.ids["job1_id"]
    resp = client.get(f"/jobs/{job1_id}")
    assert resp.status_code == 200
    assert "Senior Backend Engineer" in resp.text
    assert "TestCorp" in resp.text


def test_job_detail_no_pii(client):
    job1_id = client.ids["job1_id"]
    resp = client.get(f"/jobs/{job1_id}")
    assert resp.status_code == 200
    text = resp.text
    # Should never expose email or phone patterns
    import re
    # Require letter-only TLD to avoid false-positives from CDN version strings like htmx.org@1.9.12
    assert not re.search(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b", text), "Email found in job detail HTML"


def test_job_detail_outreach_shown(client):
    job1_id = client.ids["job1_id"]
    resp = client.get(f"/jobs/{job1_id}")
    assert resp.status_code == 200
    assert "Jane Recruiter" in resp.text


def test_update_job_status_htmx(client):
    job1_id = client.ids["job1_id"]
    resp = client.post(f"/jobs/{job1_id}/status", data={"new_status": "applied"})
    assert resp.status_code == 200
    assert "applied" in resp.text


# ---------------------------------------------------------------------------
# Page 4: Applications
# ---------------------------------------------------------------------------

def test_applications_page_renders(client):
    resp = client.get("/applications")
    assert resp.status_code == 200
    assert "Applied Engineer" in resp.text


def test_applications_outcome_shown(client):
    resp = client.get("/applications")
    assert resp.status_code == 200
    assert "interview" in resp.text


def test_application_detail_htmx(client):
    app1_id = client.ids["app1_id"]
    resp = client.get(f"/applications/{app1_id}/detail")
    assert resp.status_code == 200
    assert "Great mission" in resp.text


# ---------------------------------------------------------------------------
# Page 5: Companies
# ---------------------------------------------------------------------------

def test_companies_page_renders(client):
    resp = client.get("/companies")
    assert resp.status_code == 200
    assert "TestCorp" in resp.text
    assert "greenhouse" in resp.text


# ---------------------------------------------------------------------------
# Page 6: Insights (not ready — fewer than 20 outcomes)
# ---------------------------------------------------------------------------

def test_insights_not_ready(client):
    resp = client.get("/insights")
    assert resp.status_code == 200
    assert "Not enough data" in resp.text or "not enough" in resp.text.lower()


# ---------------------------------------------------------------------------
# Page 7: Stats / Costs
# ---------------------------------------------------------------------------

def test_stats_page_renders(client):
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert "fetch" in resp.text
    assert "claude-haiku" in resp.text


def test_stats_budget_bar(client):
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert "bar-fill" in resp.text
    assert "budget" in resp.text.lower() or "Monthly" in resp.text
