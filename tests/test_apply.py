from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
APPLY_FIXTURE_DIR = FIXTURE_DIR / "apply"
PROFILE_FIXTURE = FIXTURE_DIR / "profile_fixture.yaml"
RESUME_FIXTURE = FIXTURE_DIR / "tailoring" / "master_resume_fixture.md"


def _load_profile():
    from jobpilot.config import load_profile
    return load_profile(PROFILE_FIXTURE)


# ──────────────────────────────────────────────────────────────
# Unit tests — no Playwright, no network
# ──────────────────────────────────────────────────────────────

def test_classify_us_work_auth():
    from jobpilot.apply.field_classifier import classify_field
    key, _ = classify_field("Are you authorized to work in the United States?")
    assert key == "authorized_to_work_US"


def test_classify_sponsorship():
    from jobpilot.apply.field_classifier import classify_field
    key, _ = classify_field("Will you require visa sponsorship?")
    assert key == "require_sponsorship_now_or_future"


def test_classify_gender():
    from jobpilot.apply.field_classifier import classify_field
    key, _ = classify_field("Gender")
    assert key == "gender"


def test_classify_veteran():
    from jobpilot.apply.field_classifier import classify_field
    key, _ = classify_field("Are you a protected veteran?")
    assert key == "veteran_status"


def test_classify_no_match():
    from jobpilot.apply.field_classifier import classify_field
    key, val = classify_field("What is your preferred programming language?")
    assert key is None
    assert val is None


def test_classify_relocation():
    from jobpilot.apply.field_classifier import classify_field
    key, _ = classify_field("Are you willing to relocate?")
    assert key == "willing_to_relocate"


def test_get_fixed_answer_us_auth():
    from jobpilot.apply.field_classifier import get_fixed_answer
    profile = _load_profile()
    answer = get_fixed_answer("Are you authorized to work in the United States?", "", profile.fixed_answers)
    assert answer == "No"


def test_get_fixed_answer_sponsorship():
    from jobpilot.apply.field_classifier import get_fixed_answer
    profile = _load_profile()
    answer = get_fixed_answer("Will you now or in the future require visa sponsorship?", "", profile.fixed_answers)
    assert answer == "Yes"


def test_detect_ats_greenhouse_url():
    from jobpilot.apply.ats_detector import detect_ats_from_url
    assert detect_ats_from_url("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"


def test_detect_ats_lever_url():
    from jobpilot.apply.ats_detector import detect_ats_from_url
    assert detect_ats_from_url("https://jobs.lever.co/acme/abc-123/apply") == "lever"


def test_detect_ats_workday_url():
    from jobpilot.apply.ats_detector import detect_ats_from_url
    assert detect_ats_from_url("https://acme.wd3.myworkdayjobs.com/jobs") == "workday"


def test_detect_ats_unknown():
    from jobpilot.apply.ats_detector import detect_ats_from_url
    assert detect_ats_from_url("https://jobs.example.com/apply") is None


# ──────────────────────────────────────────────────────────────
# Playwright tests — local file:// fixtures, no external network
# ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def profile():
    return _load_profile()


@pytest.fixture(scope="module")
def resume_path():
    # Just needs to exist; we won't actually upload in tests
    return RESUME_FIXTURE


def _gh_fixture_url() -> str:
    return (APPLY_FIXTURE_DIR / "greenhouse_form.html").as_uri()


def _lv_fixture_url() -> str:
    return (APPLY_FIXTURE_DIR / "lever_form.html").as_uri()


@pytest.mark.asyncio
async def test_greenhouse_fills_standard_fields(profile, resume_path):
    from playwright.async_api import async_playwright
    from jobpilot.apply.fillers.greenhouse import fill_form

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_gh_fixture_url())

        result = await fill_form(page, profile, resume_path, None, None, None)

        first_name_val = await page.input_value("#first_name")
        email_val = await page.input_value("#email")
        phone_val = await page.input_value("#phone")

        await browser.close()

    expected_first = profile.name.split()[0]
    assert expected_first in first_name_val
    assert email_val == profile.email
    assert profile.phone.number in phone_val


@pytest.mark.asyncio
async def test_greenhouse_fixed_answer_us_auth(profile, resume_path):
    from playwright.async_api import async_playwright
    from jobpilot.apply.fillers.greenhouse import fill_form

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_gh_fixture_url())

        await fill_form(page, profile, resume_path, None, None, None)

        # Check the US work auth select was set to "No" from fixed_answers
        selected = await page.evaluate("document.querySelector('#q_us_auth').value")
        await browser.close()

    assert selected == "No"


@pytest.mark.asyncio
async def test_greenhouse_fixed_answer_sponsorship(profile, resume_path):
    from playwright.async_api import async_playwright
    from jobpilot.apply.fillers.greenhouse import fill_form

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_gh_fixture_url())

        await fill_form(page, profile, resume_path, None, None, None)

        selected = await page.evaluate("document.querySelector('#q_sponsor').value")
        await browser.close()

    assert selected == "Yes"


@pytest.mark.asyncio
async def test_greenhouse_submit_not_clicked(profile, resume_path):
    from playwright.async_api import async_playwright
    from jobpilot.apply.fillers.greenhouse import fill_form
    from jobpilot.apply.form_filler import find_submit_button

    submitted = False

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        # Track form submissions via JS
        await page.evaluate("""
            window._submitted = false;
            document.addEventListener('submit', e => { e.preventDefault(); window._submitted = true; });
        """)
        await page.goto(_gh_fixture_url())
        # Re-attach after navigation
        await page.evaluate("""
            window._submitted = false;
            document.addEventListener('submit', e => { e.preventDefault(); window._submitted = true; });
        """)

        await fill_form(page, profile, resume_path, None, None, None)
        btn = await find_submit_button(page)
        was_submitted = await page.evaluate("window._submitted")

        await browser.close()

    assert btn is not None, "Submit button should exist in DOM"
    assert not was_submitted, "Form must NOT have been submitted"


@pytest.mark.asyncio
async def test_lever_fills_standard_fields(profile, resume_path):
    from playwright.async_api import async_playwright
    from jobpilot.apply.fillers.lever import fill_form

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_lv_fixture_url())

        await fill_form(page, profile, resume_path, None, None, None)

        name_val = await page.input_value("input[name=name]")
        email_val = await page.input_value("input[name=email]")

        await browser.close()

    assert profile.name in name_val
    assert email_val == profile.email


@pytest.mark.asyncio
async def test_lever_fixed_answer_us_auth(profile, resume_path):
    """Fixed-answer questions must be answered from fixed_answers — LLM never called."""
    from unittest.mock import MagicMock
    from playwright.async_api import async_playwright
    from jobpilot.apply.fillers.lever import fill_form

    mock_llm = MagicMock()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(_lv_fixture_url())

        # fill_form does NOT accept llm_client — the classifier is deterministic
        await fill_form(page, profile, resume_path, None, None, None)

        auth_val = await page.evaluate("document.querySelector('[name=\"eeo[authorized]\"]').value")
        sponsor_val = await page.evaluate("document.querySelector('[name=\"eeo[sponsorship]\"]').value")

        await browser.close()

    # LLM must never have been called for these fields
    mock_llm.call.assert_not_called()
    # Fixed answers: authorized=No → "no", require sponsorship=Yes → "yes"
    assert auth_val.lower() == "no"
    assert sponsor_val.lower() == "yes"
