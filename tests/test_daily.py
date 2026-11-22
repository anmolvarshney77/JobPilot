"""Tests for daily.py orchestration, lock, and digest utilities."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jobpilot.daily import should_catch_up, should_run_validate_companies
from jobpilot.daily_lock import DailyAlreadyRunningError, DailyLock
from jobpilot.notify.digest import DigestData, build_digest_text, collect_digest_data


# ─────────────────────────────────────────── helpers ─────────────────────────

def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_run_log(command="daily", status="ok", hours_ago=1):
    return SimpleNamespace(
        command=command,
        status=status,
        started_at=_now() - timedelta(hours=hours_ago),
    )


# ─────────────────────────────────────────── should_catch_up ─────────────────

class TestShouldCatchUp:
    def test_no_prior_run_returns_true(self):
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None
        assert should_catch_up(session) is True

    def test_recent_run_returns_false(self):
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = _make_run_log(hours_ago=1)
        assert should_catch_up(session) is False

    def test_stale_run_returns_true(self):
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = _make_run_log(hours_ago=25)
        assert should_catch_up(session) is True

    def test_19h_still_false(self):
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = _make_run_log(hours_ago=19)
        assert should_catch_up(session) is False


# ─────────────────────────────────────────── should_run_validate_companies ───

class TestShouldRunValidateCompanies:
    def test_never_run_returns_true(self):
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None
        assert should_run_validate_companies(session) is True

    def test_ran_6_days_ago_returns_false(self):
        session = MagicMock()
        r = _make_run_log(command="validate-companies", hours_ago=6 * 24)
        session.execute.return_value.scalar_one_or_none.return_value = r
        assert should_run_validate_companies(session) is False

    def test_ran_8_days_ago_returns_true(self):
        session = MagicMock()
        r = _make_run_log(command="validate-companies", hours_ago=8 * 24)
        session.execute.return_value.scalar_one_or_none.return_value = r
        assert should_run_validate_companies(session) is True


# ─────────────────────────────────────────── DailyLock ───────────────────────

class TestDailyLock:
    def test_acquires_and_releases(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        with DailyLock(lock_path=lock_path):
            assert lock_path.exists()
        # Lock file cleaned up
        assert not lock_path.exists()

    def test_second_acquire_raises(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        with DailyLock(lock_path=lock_path):
            with pytest.raises(DailyAlreadyRunningError):
                DailyLock(lock_path=lock_path).__enter__()

    def test_release_on_exception(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        try:
            with DailyLock(lock_path=lock_path):
                raise ValueError("boom")
        except ValueError:
            pass
        assert not lock_path.exists()


# ─────────────────────────────────────────── build_digest_text ───────────────

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "daily" / "digest_data.json"


@pytest.fixture
def digest_fixture() -> DigestData:
    raw = json.loads(FIXTURE_PATH.read_text())
    return DigestData(**raw)


class TestBuildDigestText:
    def test_contains_date(self, digest_fixture):
        text = build_digest_text(digest_fixture)
        assert "JobPilot Daily Digest" in text

    def test_top_matches_listed(self, digest_fixture):
        text = build_digest_text(digest_fixture)
        assert "Acme Corp" in text
        assert "Beta GmbH" in text

    def test_closing_job_listed(self, digest_fixture):
        text = build_digest_text(digest_fixture)
        assert "Gamma Ltd" in text
        assert "CLOSED" in text

    def test_follow_up_listed(self, digest_fixture):
        text = build_digest_text(digest_fixture)
        assert "Alex P" in text

    def test_llm_spend_shown(self, digest_fixture):
        text = build_digest_text(digest_fixture)
        assert "$3.42" in text

    def test_no_errors_shown(self, digest_fixture):
        text = build_digest_text(digest_fixture)
        assert "None." in text

    def test_dry_run_flag(self, digest_fixture):
        digest_fixture.dry_run = True
        text = build_digest_text(digest_fixture)
        assert "DRY RUN" in text

    def test_budget_warning_at_80pct(self, digest_fixture):
        digest_fixture.llm_spend_usd = 13.0
        digest_fixture.llm_budget_usd = 15.0
        text = build_digest_text(digest_fixture)
        assert "Warning" in text

    def test_no_budget_warning_below_80pct(self, digest_fixture):
        digest_fixture.llm_spend_usd = 3.0
        digest_fixture.llm_budget_usd = 15.0
        text = build_digest_text(digest_fixture)
        assert "Warning" not in text

    def test_no_matches_message(self):
        d = DigestData()
        text = build_digest_text(d)
        assert "No new matches" in text


# ─────────────────────────────────────────── collect_digest_data ─────────────

class TestCollectDigestData:
    def _make_session(self, top_rows=None, closing_rows=None, spend=0.0):
        """Build a mock session that returns pre-canned query results."""
        from jobpilot.db import Job, Company, Outreach

        session = MagicMock()
        execute = MagicMock()

        def side_effect(query):
            result = MagicMock()
            q_str = str(query)
            # top matches query
            if "first_seen_at" in q_str:
                result.all.return_value = top_rows or []
            # closing query
            elif "is_live" in q_str and "prepared" in q_str:
                result.all.return_value = closing_rows or []
            # llm spend query
            else:
                result.scalar.return_value = spend
            return result

        session.execute.side_effect = side_effect
        return session

    def test_empty_db_returns_empty_digest(self):
        from jobpilot.outreach.follow_up import get_follow_up_candidates

        session = MagicMock()

        def execute_side(q):
            r = MagicMock()
            r.all.return_value = []
            r.scalar.return_value = 0.0
            return r

        session.execute.side_effect = execute_side
        cfg = MagicMock()
        cfg.llm.monthly_budget_usd = 15.0

        with patch("jobpilot.outreach.follow_up.get_follow_up_candidates", return_value=[]):
            data = collect_digest_data(session, cfg, [], _now(), False)

        assert data.top_matches == []
        assert data.closing_or_closed == []
        assert data.follow_ups_due == []
        assert data.llm_spend_usd == 0.0

    def test_errors_passed_through(self):
        session = MagicMock()

        def execute_side(q):
            r = MagicMock()
            r.all.return_value = []
            r.scalar.return_value = 0.0
            return r

        session.execute.side_effect = execute_side
        cfg = MagicMock()
        cfg.llm.monthly_budget_usd = 15.0

        with patch("jobpilot.outreach.follow_up.get_follow_up_candidates", return_value=[]):
            data = collect_digest_data(session, cfg, ["something broke"], _now(), False)

        assert data.errors == ["something broke"]

    def test_dry_run_flag_propagated(self):
        session = MagicMock()

        def execute_side(q):
            r = MagicMock()
            r.all.return_value = []
            r.scalar.return_value = 0.0
            return r

        session.execute.side_effect = execute_side
        cfg = MagicMock()
        cfg.llm.monthly_budget_usd = 15.0

        with patch("jobpilot.outreach.follow_up.get_follow_up_candidates", return_value=[]):
            data = collect_digest_data(session, cfg, [], _now(), True)

        assert data.dry_run is True
