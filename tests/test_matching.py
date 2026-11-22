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
MATCHING_DIR = FIXTURE_DIR / "matching"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_profile():
    from jobpilot.config import load_profile
    return load_profile(FIXTURE_DIR / "profile_fixture.yaml")


def _load_config():
    from jobpilot.config import load_app_config
    return load_app_config(FIXTURE_DIR / "config_fixture.yaml")


def _make_in_memory_session():
    from jobpilot.db import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session


def _make_job_from_fixture(name: str, session, company_id: int = 1):
    """Load a job fixture and create a Job ORM object (not persisted unless session.add called)."""
    from jobpilot.db import Job
    data = json.loads((MATCHING_DIR / name).read_text())
    # Build a Job with the fixture data, forcing company_id
    kwargs = {k: v for k, v in data.items() if hasattr(Job, k) and k != "id"}
    kwargs["company_id"] = company_id
    if "posted_at" in kwargs and kwargs["posted_at"]:
        kwargs["posted_at"] = datetime.fromisoformat(kwargs["posted_at"])
    return Job(**kwargs)


def _seed_db(session):
    """Insert a minimal company into the in-memory DB."""
    from jobpilot.db import Company
    company = Company(
        id=1,
        name="Example Corp",
        normalized_name="example corp",
        ats_type="greenhouse",
        ats_slug="example",
        verified=True,
    )
    session.add(company)
    session.commit()
    return company


# ---------------------------------------------------------------------------
# Hard filter tests
# ---------------------------------------------------------------------------

def test_hard_filter_exclude_company():
    from jobpilot.matching.hard_filters import filter_job

    Session = _make_in_memory_session()
    with Session() as session:
        _seed_db(session)
        job = _make_job_from_fixture("job_valid.json", session, company_id=1)
        session.add(job)
        session.flush()

        profile = _load_profile()
        # Monkey-patch exclude list
        object.__setattr__(profile, "exclude_companies", ["Example Corp"])

        reason = filter_job(job, profile, session, _now())
        assert reason == "exclude_company"


def test_hard_filter_sponsorship_refusal():
    from jobpilot.matching.hard_filters import filter_job

    Session = _make_in_memory_session()
    with Session() as session:
        _seed_db(session)
        job = _make_job_from_fixture("job_sponsorship_refusal.json", session, company_id=1)
        session.add(job)
        session.flush()

        profile = _load_profile()
        assert profile.needs_visa_sponsorship is True

        reason = filter_job(job, profile, session, _now())
        assert reason == "sponsorship_refused"


def test_hard_filter_negation_not_refusal():
    """'we do not offer relocation support' must NOT trigger sponsorship_refused."""
    from jobpilot.matching.hard_filters import detect_sponsorship_refusal

    text = "We do not offer relocation support, but international applications are welcome."
    assert detect_sponsorship_refusal(text) is False


def test_hard_filter_negation_visa_is_refusal():
    """'does not offer visa sponsorship' IS a refusal (negation is part of the pattern)."""
    from jobpilot.matching.hard_filters import detect_sponsorship_refusal

    text = "The company does not offer visa sponsorship to applicants."
    assert detect_sponsorship_refusal(text) is True


def test_hard_filter_no_sponsorship_phrase():
    """Plain 'no visa sponsorship' is a refusal."""
    from jobpilot.matching.hard_filters import detect_sponsorship_refusal

    text = "We are excited to hire. Note: no visa sponsorship available."
    assert detect_sponsorship_refusal(text) is True


def test_hard_filter_old_job():
    from jobpilot.matching.hard_filters import filter_job

    Session = _make_in_memory_session()
    with Session() as session:
        _seed_db(session)
        job = _make_job_from_fixture("job_old.json", session, company_id=1)
        session.add(job)
        session.flush()

        profile = _load_profile()
        now = _now()
        reason = filter_job(job, profile, session, now)
        assert reason == "too_old"


# ---------------------------------------------------------------------------
# Keyword filter tests
# ---------------------------------------------------------------------------

def test_keyword_score_core_skills():
    from jobpilot.matching.keyword_filter import keyword_score

    desc = "We need a Python developer with FastAPI experience to build REST APIs."
    score = keyword_score(desc, ["Python", "FastAPI"], [])
    assert score > 0


def test_keyword_score_synonyms():
    from jobpilot.matching.keyword_filter import keyword_score

    desc = "We use Postgres for our main database and Redis for caching."
    # "Postgres" should match "PostgreSQL" via synonyms
    score = keyword_score(desc, ["PostgreSQL"], [])
    assert score > 0


def test_keyword_score_golang():
    from jobpilot.matching.keyword_filter import keyword_score

    desc = "Looking for a Golang developer to build microservices."
    score = keyword_score(desc, ["Go"], [])
    assert score > 0


def test_keyword_score_empty_description():
    from jobpilot.matching.keyword_filter import keyword_score

    score = keyword_score("", ["Python", "FastAPI"], ["Docker"])
    assert score == 0.0


def test_keyword_score_no_match():
    from jobpilot.matching.keyword_filter import keyword_score

    desc = "We need a Java developer with Spring Boot experience."
    score = keyword_score(desc, ["Python", "FastAPI", "React"], ["Docker"])
    assert score == 0.0


# ---------------------------------------------------------------------------
# Post-processor tests
# ---------------------------------------------------------------------------

def _make_llm_response(**overrides) -> object:
    from jobpilot.matching.llm_scorer import ScoringResponse
    base = json.loads((MATCHING_DIR / "llm_score_response.json").read_text())
    base.update(overrides)
    return ScoringResponse.model_validate(base)


def test_post_processor_mandatory_language_drop():
    from jobpilot.matching.post_processor import should_drop_post_llm

    profile = _load_profile()
    # Profile languages: English C1 — German not present (defaults to "none")
    resp = _make_llm_response(
        required_languages=[
            {"language": "German", "level": "B2", "mandatory": True}
        ]
    )
    reason = should_drop_post_llm(resp, profile)
    assert reason is not None
    assert "German" in reason


def test_post_processor_non_mandatory_language_ok():
    from jobpilot.matching.post_processor import should_drop_post_llm

    profile = _load_profile()
    resp = _make_llm_response(
        required_languages=[
            {"language": "German", "level": "B2", "mandatory": False}
        ]
    )
    reason = should_drop_post_llm(resp, profile)
    assert reason is None


def test_post_processor_eligible_location_false_drop():
    from jobpilot.matching.post_processor import should_drop_post_llm

    profile = _load_profile()
    resp = _make_llm_response(candidate_location_eligible=False)
    reason = should_drop_post_llm(resp, profile)
    assert reason == "location_not_eligible"


def test_post_processor_too_many_years():
    from jobpilot.matching.post_processor import should_drop_post_llm

    profile = _load_profile()
    # seniority_years_range.max = 5; require > 5 + 1 = 6 → drop
    resp = _make_llm_response(required_years=8, seniority_fit="over")
    reason = should_drop_post_llm(resp, profile)
    assert reason == "overqualified_years"


def test_post_processor_years_max_plus_one_ok():
    """required_years == max + 1 is allowed (not strictly greater)."""
    from jobpilot.matching.post_processor import should_drop_post_llm

    profile = _load_profile()
    # max = 5; required = 6 → 6 > 5+1=6 is False → not dropped
    resp = _make_llm_response(required_years=6, seniority_fit="over")
    reason = should_drop_post_llm(resp, profile)
    assert reason is None


# ---------------------------------------------------------------------------
# compute_final_score tests
# ---------------------------------------------------------------------------

def test_compute_final_score_explicit_yes():
    from jobpilot.matching.post_processor import compute_final_score

    profile = _load_profile()
    score = compute_final_score(
        llm_score=70,
        sponsorship_assessment="explicit_yes",
        posted_at=None,
        job_countries=["DE"],
        profile=profile,
        salary_meets_expectation=None,
        now=_now(),
    )
    assert score == 80


def test_compute_final_score_unlikely():
    from jobpilot.matching.post_processor import compute_final_score

    profile = _load_profile()
    score = compute_final_score(
        llm_score=70,
        sponsorship_assessment="unlikely",
        posted_at=None,
        job_countries=["DE"],
        profile=profile,
        salary_meets_expectation=None,
        now=_now(),
    )
    assert score == 60


def test_compute_final_score_recent_posting():
    from jobpilot.matching.post_processor import compute_final_score

    profile = _load_profile()
    now = _now()
    score = compute_final_score(
        llm_score=70,
        sponsorship_assessment="unknown",
        posted_at=now - timedelta(days=1),
        job_countries=["DE"],
        profile=profile,
        salary_meets_expectation=None,
        now=now,
    )
    assert score == 75  # +5 for recent


def test_compute_final_score_capped_at_100():
    from jobpilot.matching.post_processor import compute_final_score

    profile = _load_profile()
    now = _now()
    score = compute_final_score(
        llm_score=98,
        sponsorship_assessment="explicit_yes",
        posted_at=now - timedelta(days=1),
        job_countries=["DE"],
        profile=profile,
        salary_meets_expectation=True,
        now=now,
    )
    assert score == 100


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------

def _make_session_factory_with_zero_spend():
    @contextmanager
    def factory():
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0.0
        mock_session.execute.return_value = mock_result
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.get = MagicMock(return_value=None)
        mock_session.flush = MagicMock()
        yield mock_session
    return factory


def test_pipeline_dry_run_no_db_changes():
    """dry_run=True: session.commit() must NOT be called."""
    from jobpilot.db import Job
    from jobpilot.matching import run_pipeline

    profile = _load_profile()
    cfg = _load_config()

    Session = _make_in_memory_session()
    with Session() as session:
        _seed_db(session)
        job = Job(
            source="greenhouse",
            external_id="dry1",
            company_id=1,
            title="Software Engineer",
            url="https://example.com/job/dry1",
            status="new",
            countries=["DE"],
            sponsorship_signal="unknown",
            required_languages=[],
        )
        session.add(job)
        session.commit()

        # Mock LLM client to avoid real calls
        mock_llm = MagicMock()
        from jobpilot.matching.llm_scorer import ScoringResponse
        llm_resp = ScoringResponse.model_validate(
            json.loads((MATCHING_DIR / "llm_score_response.json").read_text())
        )
        mock_llm.call.return_value = llm_resp

        # Patch score_job to use mock
        with patch("jobpilot.matching.score_job", return_value=llm_resp):
            result = run_pipeline(
                jobs=[job],
                profile=profile,
                app_config=cfg,
                session=session,
                llm_client=mock_llm,
                dry_run=True,
            )

        # In dry_run mode, job status should NOT be persisted
        session.refresh(job)
        assert job.status == "new"


def test_pipeline_caches_scored_job():
    """A job with matching description_hash and match_score skips LLM."""
    import hashlib
    from jobpilot.db import Job
    from jobpilot.matching import run_pipeline
    from jobpilot.matching.llm_scorer import ScoringResponse

    profile = _load_profile()
    cfg = _load_config()

    description = "Python and FastAPI job in Berlin."
    desc_hash = hashlib.md5(description.encode()).hexdigest()

    Session = _make_in_memory_session()
    with Session() as session:
        _seed_db(session)
        job = Job(
            source="greenhouse",
            external_id="cached1",
            company_id=1,
            title="Software Engineer",
            url="https://example.com/job/cached1",
            status="new",
            countries=["DE"],
            sponsorship_signal="unknown",
            required_languages=[],
            description=description,
            description_hash=desc_hash,
            match_score=80.0,  # already scored
            match_details={"sponsorship_assessment": "likely", "required_languages": []},
        )
        session.add(job)
        session.commit()

        mock_llm = MagicMock()

        with patch("jobpilot.matching.score_job") as mock_score:
            run_pipeline(
                jobs=[job],
                profile=profile,
                app_config=cfg,
                session=session,
                llm_client=mock_llm,
                dry_run=False,
            )
            # score_job must NOT have been called
            mock_score.assert_not_called()
