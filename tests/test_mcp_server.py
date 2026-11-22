"""Tests for the JobPilot MCP server (all 10 tools, no live calls)."""
from __future__ import annotations

import json
import os

import pytest
from sqlalchemy.orm import sessionmaker

from tests.fixtures.mcp.seed_jobs import seed

# Patch _get_session before importing mcp_server so tools use our in-memory DB.
# We override via monkeypatching inside each test using the fixture.


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/test.db"
    data = seed(db_url)
    monkeypatch.setenv("DATABASE_URL", db_url)
    # Re-import mcp_server with fresh env so _get_session picks up the URL.
    import importlib

    import jobpilot.mcp_server as mod
    importlib.reload(mod)
    return data, mod


# ── Helpers ────────────────────────────────────────────────────────────────

async def _call(mod, name: str, args: dict) -> dict:
    result = await mod.mcp.call_tool(name, args)
    text = result.content[0].text
    return json.loads(text)


# ── Tool listing ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tools_returns_all_ten(db):
    _, mod = db
    tools = await mod.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "search_jobs", "get_job", "list_shortlist", "list_filtered_out",
        "get_insights", "score_jobs", "prepare_application", "draft_outreach",
        "update_status", "log_outcome",
    }
    assert expected == names


# ── search_jobs ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_jobs_no_filter_returns_all(db):
    data, mod = db
    r = await _call(mod, "search_jobs", {})
    assert r["count"] == 3


@pytest.mark.asyncio
async def test_search_jobs_filter_by_status(db):
    data, mod = db
    r = await _call(mod, "search_jobs", {"status": "shortlisted"})
    assert r["count"] == 1
    assert r["jobs"][0]["status"] == "shortlisted"


@pytest.mark.asyncio
async def test_search_jobs_no_description_in_summary(db):
    data, mod = db
    r = await _call(mod, "search_jobs", {})
    for job in r["jobs"]:
        assert "description" not in job


@pytest.mark.asyncio
async def test_search_jobs_no_pii_fields(db):
    data, mod = db
    r = await _call(mod, "search_jobs", {})
    for job in r["jobs"]:
        for key in job:
            assert "email" not in key.lower()
            assert "phone" not in key.lower()


# ── get_job ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_job_exists(db):
    data, mod = db
    j1 = data["j1"]
    r = await _call(mod, "get_job", {"job_id": j1.id})
    assert r["id"] == j1.id
    assert r["title"] == j1.title


@pytest.mark.asyncio
async def test_get_job_description_wrapped_in_untrusted_tags(db):
    data, mod = db
    j1 = data["j1"]
    r = await _call(mod, "get_job", {"job_id": j1.id})
    assert "<untrusted_job_posting>" in r["description"]
    assert "</untrusted_job_posting>" in r["description"]
    assert "third-party data" in r["description"]


@pytest.mark.asyncio
async def test_get_job_not_found(db):
    _, mod = db
    r = await _call(mod, "get_job", {"job_id": 99999})
    assert "error" in r


# ── list_shortlist ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_shortlist_returns_shortlisted_only(db):
    data, mod = db
    r = await _call(mod, "list_shortlist", {})
    assert r["count"] == 1
    assert r["jobs"][0]["status"] == "shortlisted"


# ── list_filtered_out ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_filtered_out_groups_by_reason(db):
    data, mod = db
    r = await _call(mod, "list_filtered_out", {})
    assert r["total"] == 1
    assert "title_excluded" in r["by_reason"]


@pytest.mark.asyncio
async def test_list_filtered_out_filter_by_reason(db):
    data, mod = db
    r = await _call(mod, "list_filtered_out", {"reason": "title_excluded"})
    assert r["total"] == 1
    r2 = await _call(mod, "list_filtered_out", {"reason": "no_such_reason"})
    assert r2["total"] == 0


# ── get_insights ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_insights_has_expected_keys(db):
    data, mod = db
    r = await _call(mod, "get_insights", {})
    assert "total_jobs_by_status" in r
    assert "sponsorship_breakdown" in r
    assert "llm_this_month_usd" in r
    assert "message" in r


@pytest.mark.asyncio
async def test_get_insights_not_enough_data_message(db):
    data, mod = db
    r = await _call(mod, "get_insights", {})
    # only 1 outcome in seed — below the 20 threshold
    assert "Not enough data" in r["message"]


# ── update_status ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_status_applied_is_blocked(db):
    data, mod = db
    j2 = data["j2"]
    r = await _call(mod, "update_status", {"job_id": j2.id, "status": "applied"})
    assert "error" in r
    assert "interactive" in r["error"].lower() or "applied" in r["error"]


@pytest.mark.asyncio
async def test_update_status_valid_transition(db):
    data, mod = db
    j2 = data["j2"]
    r = await _call(mod, "update_status", {"job_id": j2.id, "status": "shortlisted"})
    assert r["new_status"] == "shortlisted"
    assert r["old_status"] == "new"


@pytest.mark.asyncio
async def test_update_status_invalid_status(db):
    data, mod = db
    j2 = data["j2"]
    r = await _call(mod, "update_status", {"job_id": j2.id, "status": "banana"})
    assert "error" in r


# ── log_outcome ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_outcome_success(db):
    data, mod = db
    app2 = data["app2"]
    r = await _call(mod, "log_outcome", {"application_id": app2.id, "outcome": "rejected"})
    assert r["new_outcome"] == "rejected"


@pytest.mark.asyncio
async def test_log_outcome_invalid_outcome(db):
    data, mod = db
    app2 = data["app2"]
    r = await _call(mod, "log_outcome", {"application_id": app2.id, "outcome": "promoted"})
    assert "error" in r


@pytest.mark.asyncio
async def test_log_outcome_bad_date(db):
    data, mod = db
    app2 = data["app2"]
    r = await _call(mod, "log_outcome", {
        "application_id": app2.id,
        "outcome": "ghosted",
        "date": "not-a-date",
    })
    assert "error" in r


@pytest.mark.asyncio
async def test_log_outcome_not_found(db):
    _, mod = db
    r = await _call(mod, "log_outcome", {"application_id": 99999, "outcome": "rejected"})
    assert "error" in r
