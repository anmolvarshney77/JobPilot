"""Seed an in-memory SQLite DB with test data for MCP server tests."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jobpilot.db import Application, Base, Company, Job, LLMUsage


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed(db_url: str = "sqlite:///:memory:"):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        c1 = Company(name="Zalando", normalized_name="zalando", ats_type="greenhouse", ats_slug="zalando")
        c2 = Company(name="Revolut", normalized_name="revolut", ats_type="lever", ats_slug="revolut")
        session.add_all([c1, c2])
        session.flush()

        j1 = Job(
            source="greenhouse",
            external_id="zal-001",
            company_id=c1.id,
            title="Senior Software Engineer",
            countries=["DE"],
            status="shortlisted",
            match_score=82.0,
            sponsorship_signal="yes",
            remote_type="hybrid",
            url="https://jobs.example.com/zal-001",
            apply_url="https://apply.example.com/zal-001",
            description="Build scalable systems.",
            first_seen_at=_now(),
            last_seen_at=_now(),
            dedupe_key="zal-001-de",
        )
        j2 = Job(
            source="adzuna",
            external_id="rev-002",
            company_id=c2.id,
            title="Backend Engineer",
            countries=["GB"],
            status="new",
            match_score=55.0,
            sponsorship_signal="unknown",
            remote_type="remote",
            url="https://jobs.example.com/rev-002",
            apply_url="https://apply.example.com/rev-002",
            description="Scale financial infrastructure.",
            first_seen_at=_now(),
            last_seen_at=_now(),
            dedupe_key="rev-002-gb",
        )
        j3 = Job(
            source="greenhouse",
            external_id="zal-003",
            company_id=c1.id,
            title="Director of Engineering",
            countries=["DE"],
            status="filtered_out",
            match_score=20.0,
            sponsorship_signal="no",
            remote_type="onsite",
            url="https://jobs.example.com/zal-003",
            first_seen_at=_now(),
            last_seen_at=_now(),
            filter_reason="title_excluded",
            dedupe_key="zal-003-de",
        )
        session.add_all([j1, j2, j3])
        session.flush()

        app1 = Application(
            job_id=j1.id,
            submitted_at=_now(),
            outcome="interview",
            outcome_date=_now(),
        )
        app2 = Application(
            job_id=j2.id,
            outcome="none",
        )
        session.add_all([app1, app2])

        llm = LLMUsage(
            model="claude-haiku-5-5",
            purpose="scoring",
            input_tokens=500,
            output_tokens=100,
            cost_usd=0.0012,
            job_id=j1.id,
        )
        session.add(llm)
        session.commit()

        return {
            "engine": engine,
            "Session": Session,
            "c1": c1,
            "c2": c2,
            "j1": j1,
            "j2": j2,
            "j3": j3,
            "app1": app1,
            "app2": app2,
        }
