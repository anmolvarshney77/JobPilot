from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

FIXTURE_DIR = Path(__file__).parent / "fixtures"
OUTREACH_FIXTURE_DIR = FIXTURE_DIR / "outreach"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _in_memory_session():
    from jobpilot.db import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def factory():
        with Session() as s:
            yield s

    return Session, factory


def _load_profile():
    from jobpilot.config import load_profile
    return load_profile(FIXTURE_DIR / "profile_fixture.yaml")


def _load_app_config():
    from jobpilot.config import load_app_config
    return load_app_config(FIXTURE_DIR / "config_fixture.yaml")


def _make_job(**kwargs) -> MagicMock:
    job = MagicMock()
    job.id = kwargs.get("id", 1)
    job.title = kwargs.get("title", "Backend Engineer")
    job.location_raw = kwargs.get("location_raw", "Berlin, Germany")
    job.url = kwargs.get("url", "https://jobs.example.com/1")
    job.apply_url = kwargs.get("apply_url", None)
    job.description = kwargs.get("description", "We build great software.")
    job.sponsorship_signal = kwargs.get("sponsorship_signal", "unknown")
    job.match_score = kwargs.get("match_score", 85.0)
    job.status = kwargs.get("status", "prepared")
    job.company_id = kwargs.get("company_id", 1)
    job.countries = kwargs.get("countries", ["DE"])
    job.source = kwargs.get("source", "greenhouse")
    return job


def _make_company(**kwargs) -> MagicMock:
    c = MagicMock()
    c.id = kwargs.get("id", 1)
    c.name = kwargs.get("name", "Acme Corp")
    c.normalized_name = kwargs.get("normalized_name", "acme corp")
    return c


# ---------------------------------------------------------------------------
# Contact extractor tests
# ---------------------------------------------------------------------------

def test_extract_contact_from_posting():
    from jobpilot.outreach.contact_extractor import extract_contacts_from_posting

    text = (OUTREACH_FIXTURE_DIR / "posting_with_contact.txt").read_text()
    contacts = extract_contacts_from_posting(text, "Acme Corp", "Backend Engineer")

    assert len(contacts) >= 1
    named = [c for c in contacts if c.name is not None]
    assert len(named) >= 1
    names = [c.name for c in named]
    assert any("Sarah Johnson" in (n or "") for n in names)


def test_extract_contact_linkedin_url():
    from jobpilot.outreach.contact_extractor import extract_contacts_from_posting

    text = (OUTREACH_FIXTURE_DIR / "posting_with_contact.txt").read_text()
    contacts = extract_contacts_from_posting(text, "Acme Corp", "Backend Engineer")

    urls = [c.contact_url for c in contacts if c.contact_url]
    assert any("linkedin.com/in/sarahjohnson" in (u or "") for u in urls)


def test_extract_no_contact_generates_queries():
    from jobpilot.outreach.contact_extractor import extract_contacts_from_posting

    text = (OUTREACH_FIXTURE_DIR / "posting_no_contact.txt").read_text()
    contacts = extract_contacts_from_posting(text, "Acme Corp", "Backend Engineer")

    assert len(contacts) >= 2
    assert all(c.source == "search_query" for c in contacts)
    assert all(c.search_query is not None for c in contacts)
    assert all("site:linkedin.com" in (c.search_query or "") for c in contacts)


# ---------------------------------------------------------------------------
# Message drafter — length enforcement
# ---------------------------------------------------------------------------

def test_enforce_linkedin_note_limit():
    from jobpilot.outreach.message_drafter import MessageDraft, enforce_length_limits

    long_note = "x" * 320
    draft = MessageDraft(
        linkedin_note=long_note,
        email_subject="Subject",
        email_body="Short body.",
    )
    result, warnings = enforce_length_limits(draft)
    assert len(result.linkedin_note) <= 300
    assert any("linkedin_note" in w for w in warnings)


def test_enforce_email_body_limit():
    from jobpilot.outreach.message_drafter import MessageDraft, enforce_length_limits

    long_body = " ".join(["word"] * 150)
    draft = MessageDraft(
        linkedin_note="Short note.",
        email_subject="Subject",
        email_body=long_body,
    )
    result, warnings = enforce_length_limits(draft)
    word_count = len(result.email_body.split())
    assert word_count <= 120
    assert any("email_body" in w for w in warnings)


def test_enforce_no_truncation_needed():
    from jobpilot.outreach.message_drafter import MessageDraft, enforce_length_limits

    draft = MessageDraft(
        linkedin_note="Short note.",
        email_subject="Subject",
        email_body="This body is under 120 words.",
    )
    result, warnings = enforce_length_limits(draft)
    assert warnings == []
    assert result.linkedin_note == "Short note."


# ---------------------------------------------------------------------------
# Message drafter — PII and sponsorship tests
# ---------------------------------------------------------------------------

def _mock_llm_capture():
    captured = {}

    class MockLLM:
        def call(self, **kwargs):
            captured["kwargs"] = kwargs
            from jobpilot.outreach.message_drafter import MessageDraft
            return MessageDraft(
                linkedin_note="Hi there!",
                email_subject="Role",
                email_body="I am interested in this role.",
            )

    return MockLLM(), captured


def test_draft_hiring_manager_no_pii():
    from jobpilot.outreach.contact_extractor import ContactSuggestion
    from jobpilot.outreach.message_drafter import draft_hiring_manager_message
    from jobpilot.tailoring.resume_parser import ResumeData

    profile = _load_profile()
    cfg = _load_app_config()
    job = _make_job()
    contact = ContactSuggestion(name="Jane Doe", role="hiring_manager", source="posting",
                                contact_url=None, search_query=None)
    resume = ResumeData(contact="", bullets={}, skills_raw="", education_raw="", employers=[])
    mock_llm, captured = _mock_llm_capture()

    draft_hiring_manager_message(job, "Acme Corp", contact, resume, "Test", cfg, mock_llm)

    user_message = captured["kwargs"]["user_message"]
    assert profile.email not in user_message
    assert profile.phone.number not in user_message


def test_draft_message_sponsorship_silent():
    from jobpilot.outreach.contact_extractor import ContactSuggestion
    from jobpilot.outreach.message_drafter import _build_hiring_manager_prompt
    from jobpilot.tailoring.resume_parser import ResumeData

    job = _make_job(sponsorship_signal="unknown")
    contact = ContactSuggestion(name="Jane", role="hiring_manager", source="posting",
                                contact_url=None, search_query=None)
    resume = ResumeData(contact="", bullets={}, skills_raw="", education_raw="", employers=[])

    prompt = _build_hiring_manager_prompt(job, "Acme", contact, resume, "Test")
    assert "neutral sponsorship" in prompt.lower() or "not refused" in prompt.lower() or "silent on sponsorship" in prompt.lower()


def test_draft_message_sponsorship_refused():
    from jobpilot.outreach.contact_extractor import ContactSuggestion
    from jobpilot.outreach.message_drafter import _build_hiring_manager_prompt
    from jobpilot.tailoring.resume_parser import ResumeData

    job = _make_job(sponsorship_signal="no")
    contact = ContactSuggestion(name="Jane", role="hiring_manager", source="posting",
                                contact_url=None, search_query=None)
    resume = ResumeData(contact="", bullets={}, skills_raw="", education_raw="", employers=[])

    prompt = _build_hiring_manager_prompt(job, "Acme", contact, resume, "Test")
    assert "do NOT mention sponsorship" in prompt or "refused" in prompt.lower()


# ---------------------------------------------------------------------------
# Pipeline — skip conditions
# ---------------------------------------------------------------------------

def test_run_outreach_skips_low_score():
    from jobpilot.outreach import run_outreach
    from jobpilot.tailoring.resume_parser import ResumeData

    profile = _load_profile()
    cfg = _load_app_config()
    job = _make_job(match_score=60.0, status="prepared")
    company = _make_company()

    Session, factory = _in_memory_session()
    resume = ResumeData(contact="", bullets={}, skills_raw="", education_raw="", employers=[])
    mock_llm = MagicMock()

    with Session() as session:
        results = run_outreach(
            jobs=[job],
            companies={1: company},
            profile=profile,
            app_config=cfg,
            session=session,
            llm_client=mock_llm,
            resume=resume,
            dry_run=True,
        )

    assert len(results) == 1
    assert results[0].skipped_reason == "score_too_low"


def test_run_outreach_skips_existing():
    from jobpilot.db import Base, Company as CompanyDB, Job as JobDB, Outreach as OutreachDB
    from jobpilot.outreach import run_outreach
    from jobpilot.tailoring.resume_parser import ResumeData

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        # Insert real DB objects
        company_db = CompanyDB(name="Acme Corp", normalized_name="acme corp")
        session.add(company_db)
        session.flush()

        job_db = JobDB(
            source="greenhouse",
            external_id="123",
            company_id=company_db.id,
            title="Backend Engineer",
            url="https://example.com/job/1",
            match_score=90.0,
            status="prepared",
        )
        session.add(job_db)
        session.flush()

        # Existing outreach
        outreach_db = OutreachDB(
            job_id=job_db.id,
            contact_name="Existing Contact",
        )
        session.add(outreach_db)
        session.commit()

        profile = _load_profile()
        cfg = _load_app_config()
        resume = ResumeData(contact="", bullets={}, skills_raw="", education_raw="", employers=[])
        mock_llm = MagicMock()

        results = run_outreach(
            jobs=[job_db],
            companies={company_db.id: company_db},
            profile=profile,
            app_config=cfg,
            session=session,
            llm_client=mock_llm,
            resume=resume,
            dry_run=True,
        )

    assert len(results) == 1
    assert results[0].skipped_reason == "already_has_outreach"


# ---------------------------------------------------------------------------
# Follow-up candidates
# ---------------------------------------------------------------------------

def test_follow_up_candidates():
    from jobpilot.db import Application, Base, Company as CompanyDB, Job as JobDB, Outreach as OutreachDB
    from jobpilot.outreach.follow_up import get_follow_up_candidates

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        company_db = CompanyDB(name="Follow Corp", normalized_name="follow corp")
        session.add(company_db)
        session.flush()

        job_db = JobDB(
            source="greenhouse",
            external_id="456",
            company_id=company_db.id,
            title="Backend Engineer",
            url="https://example.com/job/2",
            status="applied",
        )
        session.add(job_db)
        session.flush()

        # Application with no outcome
        app_db = Application(
            job_id=job_db.id,
            outcome="none",
        )
        session.add(app_db)
        session.flush()

        # Outreach sent 15 days ago with no reply
        sent_15_days_ago = _now() - timedelta(days=15)
        outreach_db = OutreachDB(
            job_id=job_db.id,
            contact_name="Some Recruiter",
            sent_at=sent_15_days_ago,
            reply_status=None,
        )
        session.add(outreach_db)
        session.commit()

        result = get_follow_up_candidates(session, days=10)

    assert len(result) == 1
    found_job, found_outreach = result[0]
    assert found_job.title == "Backend Engineer"
    assert found_outreach.contact_name == "Some Recruiter"


# ---------------------------------------------------------------------------
# Dashboard smoke tests
# ---------------------------------------------------------------------------

def test_dashboard_root_ok():
    from fastapi.testclient import TestClient
    from jobpilot.dashboard import dashboard_app

    client = TestClient(dashboard_app, raise_server_exceptions=False)
    resp = client.get("/")
    assert resp.status_code == 200


def test_dashboard_jobs_ok():
    from fastapi.testclient import TestClient
    from jobpilot.dashboard import dashboard_app

    client = TestClient(dashboard_app, raise_server_exceptions=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Jobs" in resp.content or b"table" in resp.content.lower()


def test_dashboard_follow_ups_ok():
    from fastapi.testclient import TestClient
    from jobpilot.dashboard import dashboard_app

    client = TestClient(dashboard_app, raise_server_exceptions=False)
    resp = client.get("/follow-ups")
    assert resp.status_code == 200


def test_dashboard_stats_ok():
    from fastapi.testclient import TestClient
    from jobpilot.dashboard import dashboard_app

    client = TestClient(dashboard_app, raise_server_exceptions=False)
    resp = client.get("/stats")
    assert resp.status_code == 200
