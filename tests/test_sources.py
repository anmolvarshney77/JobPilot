from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sources"


# ---------------------------------------------------------------------------
# ATS parser tests (pure, no network)
# ---------------------------------------------------------------------------


def test_greenhouse_parse():
    from jobpilot.sources.greenhouse import parse_jobs

    with open(FIXTURE_DIR / "greenhouse_response.json") as f:
        data = json.load(f)

    jobs = parse_jobs("testco", data)
    assert len(jobs) == 2
    assert jobs[0].external_id == "12345"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].source == "greenhouse"
    assert jobs[0].location_raw == "Berlin, Germany"
    # First job mentions visa + sponsor → should detect sponsorship
    assert jobs[0].sponsorship_signal == "yes"
    # Second job says "do not sponsor" variant
    assert jobs[1].sponsorship_signal == "no"


def test_lever_parse():
    from jobpilot.sources.lever import parse_jobs

    with open(FIXTURE_DIR / "lever_response.json") as f:
        data = json.load(f)

    jobs = parse_jobs("testco", data)
    assert len(jobs) == 2
    assert jobs[0].external_id == "abc-lever-1"
    assert jobs[0].title == "Python Developer"
    assert jobs[0].source == "lever"
    assert jobs[0].location_raw == "Amsterdam, Netherlands"
    assert jobs[0].posted_at is not None


def test_ashby_parse():
    from jobpilot.sources.ashby import parse_jobs

    with open(FIXTURE_DIR / "ashby_response.json") as f:
        data = json.load(f)

    jobs = parse_jobs("testco", data)
    assert len(jobs) == 2
    assert jobs[0].external_id == "ashby-job-1"
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].source == "ashby"
    assert jobs[0].salary_min == 60000.0
    assert jobs[0].salary_max == 80000.0
    assert jobs[0].salary_currency == "EUR"
    assert jobs[0].posted_at is not None


def test_smartrecruiters_parse():
    from jobpilot.sources.smartrecruiters import parse_jobs

    with open(FIXTURE_DIR / "smartrecruiters_response.json") as f:
        data = json.load(f)

    # Pass pre-populated descriptions dict to avoid HTTP calls
    descriptions = {
        "sr-job-1": "Backend developer description",
        "sr-job-2": "Node.js engineer description",
    }
    jobs = parse_jobs("testco", data, descriptions)
    assert len(jobs) == 2
    assert jobs[0].external_id == "sr-job-1"
    assert jobs[0].title == "Backend Developer"
    assert jobs[0].location_raw == "Stockholm, Sweden"
    assert jobs[0].description == "Backend developer description"


def test_personio_parse():
    from jobpilot.sources.personio import parse_jobs

    with open(FIXTURE_DIR / "personio_response.xml") as f:
        xml_text = f.read()

    jobs = parse_jobs("testco", xml_text)
    assert len(jobs) == 2
    assert jobs[0].external_id == "personio-1"
    # Title keeps gender marker; normalizer handles it separately
    assert "Software Engineer" in jobs[0].title
    assert jobs[0].location_raw == "Munich"
    assert jobs[0].source == "personio"
    assert jobs[0].description is not None
    assert "Python" in jobs[0].description


def test_recruitee_parse():
    from jobpilot.sources.recruitee import parse_jobs

    with open(FIXTURE_DIR / "recruitee_response.json") as f:
        data = json.load(f)

    jobs = parse_jobs("testco", data)
    assert len(jobs) == 2
    assert jobs[0].external_id == "1001"
    assert jobs[0].title == "Python Backend Engineer"
    assert jobs[0].url == "https://testco.recruitee.com/o/python-backend-engineer"


def test_workable_parse():
    from jobpilot.sources.workable import parse_jobs

    with open(FIXTURE_DIR / "workable_response.json") as f:
        data = json.load(f)

    jobs = parse_jobs("testco", data)
    assert len(jobs) == 2
    assert jobs[0].external_id == "workable-1"
    assert jobs[0].title == "Software Engineer"
    assert jobs[1].location_raw == "Remote"


def test_arbeitnow_visa_signal():
    from jobpilot.sources.arbeitnow import parse_jobs

    with open(FIXTURE_DIR / "arbeitnow_response.json") as f:
        data = json.load(f)

    jobs = parse_jobs(data)
    assert len(jobs) == 2
    # First job has visa_sponsorship=true
    visa_job = next(j for j in jobs if j.external_id == "backend-engineer-at-acme")
    assert visa_job.sponsorship_signal == "yes"
    # Second job has visa_sponsorship=false
    no_visa_job = next(j for j in jobs if j.external_id == "frontend-dev-at-globaltech")
    assert no_visa_job.sponsorship_signal == "unknown"


def test_remotive_parse():
    from jobpilot.sources.remotive import parse_jobs

    with open(FIXTURE_DIR / "remotive_response.json") as f:
        data = json.load(f)

    # Both jobs should be kept: one is "Worldwide", one is "Europe" which we match broadly
    jobs = parse_jobs(data, ["DE", "NL", "IE", "GB"])
    assert len(jobs) == 2
    assert all(j.source == "remotive" for j in jobs)
    # Worldwide job should be kept
    worldwide_job = next(j for j in jobs if j.external_id == "90001")
    assert worldwide_job.company_name == "RemoteCo"


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------


def test_normalize_title():
    from jobpilot.sources.normalizer import normalize_title

    assert normalize_title("Software Engineer (m/w/d)") == "software engineer"
    assert normalize_title("Backend Developer (f/m/x)") == "backend developer"
    assert normalize_title("Senior Python Developer II") == "senior python developer"
    assert normalize_title("SDE 2") == "sde"
    assert normalize_title("  ML Engineer  ") == "ml engineer"


def test_title_excluded():
    from jobpilot.sources.normalizer import is_title_excluded

    assert is_title_excluded("Staff Engineer") is True
    assert is_title_excluded("Principal Software Engineer") is True
    assert is_title_excluded("Engineering Manager") is True
    assert is_title_excluded("Head of Engineering") is True
    assert is_title_excluded("Software Engineering Intern") is True
    assert is_title_excluded("Werkstudent Backend") is True

    # These must NOT be excluded
    assert is_title_excluded("Senior Software Engineer") is False
    assert is_title_excluded("Lead Backend Developer") is False
    assert is_title_excluded("Software Engineer") is False
    assert is_title_excluded("Backend Developer") is False


def test_parse_location_remote():
    from jobpilot.sources.normalizer import parse_location

    countries, remote_type = parse_location("Remote (Europe)")
    assert remote_type == "remote"


def test_parse_location_city():
    from jobpilot.sources.normalizer import parse_location

    countries, remote_type = parse_location("Berlin, Germany")
    assert "DE" in countries


def test_parse_location_hybrid():
    from jobpilot.sources.normalizer import parse_location

    countries, remote_type = parse_location("Hybrid - Amsterdam")
    assert remote_type == "hybrid"
    assert "NL" in countries


def test_parse_salary():
    from jobpilot.sources.normalizer import parse_salary

    # Using en-dash / hyphen
    sal_min, sal_max, cur = parse_salary("$120k - $150k")
    assert sal_min == 120000.0
    assert sal_max == 150000.0
    assert cur == "USD"

    sal_min, sal_max, cur = parse_salary("€60,000 - €80,000")
    assert sal_min == 60000.0
    assert sal_max == 80000.0
    assert cur == "EUR"


def test_dedupe_key():
    from jobpilot.sources.normalizer import build_dedupe_key

    key = build_dedupe_key("delivery hero", "backend engineer", "DE")
    assert key == "delivery hero::backend engineer::DE"

    key_no_country = build_dedupe_key("remote co", "software engineer", None)
    assert key_no_country == "remote co::software engineer::any"


def test_normalize_company_name():
    from jobpilot.sources.normalizer import normalize_company_name

    assert normalize_company_name("Delivery Hero GmbH") == "delivery hero"
    assert normalize_company_name("Acme Corp.") == "acme"
    assert normalize_company_name("Test Company Ltd") == "test company"
    assert normalize_company_name("N26 AG") == "n26"


def test_is_title_match_positive():
    from jobpilot.sources.normalizer import is_title_match

    # "Backend Engineer" shares "engineer" with "Software Engineer"
    # and "backend" with "Backend Developer"
    assert is_title_match("Backend Engineer", ["Backend Developer", "Software Engineer"]) is True
    assert is_title_match("Python Developer", ["Python Developer", "Software Engineer"]) is True
    assert is_title_match("Senior Software Engineer", ["Software Engineer", "Backend Engineer"]) is True


def test_is_title_match_negative():
    from jobpilot.sources.normalizer import is_title_match

    # "Head of Engineering" — no word overlap with common titles
    # Note: "Head of Engineering" is also excluded, but test the match logic
    assert is_title_match("Marketing Manager", ["Software Engineer", "Backend Developer"]) is False
    assert is_title_match("Data Analyst", ["Software Engineer", "Python Developer"]) is False
