from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tailoring"


# ---------------------------------------------------------------------------
# Resume parser tests
# ---------------------------------------------------------------------------

def test_parse_master_resume_bullets():
    from jobpilot.tailoring.resume_parser import parse_master_resume

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")
    assert "e1" in resume.bullets
    assert resume.bullets["e1"].text.startswith("Built REST APIs")


def test_parse_master_resume_bullet_count():
    from jobpilot.tailoring.resume_parser import parse_master_resume

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")
    # s1, e1, e2, p1 — edu1 is in education bullets too = 5
    assert len(resume.bullets) == 5


def test_parse_master_resume_sections():
    from jobpilot.tailoring.resume_parser import parse_master_resume

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")
    assert resume.bullets["e1"].section == "experience"
    assert resume.bullets["p1"].section == "projects"
    assert resume.bullets["s1"].section == "summary"


def test_parse_master_resume_employer():
    from jobpilot.tailoring.resume_parser import parse_master_resume

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")
    assert resume.bullets["e1"].employer == "Acme Corp"


# ---------------------------------------------------------------------------
# Verifier tests
# ---------------------------------------------------------------------------

def test_verify_rephrasing_valid():
    from jobpilot.tailoring.verifier import verify_rephrasing

    original = "Built REST APIs serving 10,000 requests/day using FastAPI."
    rephrased = "Built high-performance REST APIs serving 10,000 requests/day using FastAPI."
    valid, reason = verify_rephrasing(original, rephrased)
    assert valid is True
    assert reason == ""


def test_verify_rephrasing_invented_number():
    from jobpilot.tailoring.verifier import verify_rephrasing

    original = "Built REST APIs serving 10,000 requests/day using FastAPI."
    rephrased = "Built REST APIs serving 50,000 requests/day using FastAPI."
    valid, reason = verify_rephrasing(original, rephrased)
    assert valid is False
    assert "number" in reason


def test_verify_rephrasing_invented_tech():
    from jobpilot.tailoring.verifier import verify_rephrasing

    original = "Built REST APIs serving 10,000 requests/day using FastAPI."
    rephrased = "Built REST APIs serving 10,000 requests/day using FastAPI and Kubernetes."
    valid, reason = verify_rephrasing(original, rephrased)
    assert valid is False
    assert "tech" in reason


def test_apply_verifications_reverts_bad():
    from jobpilot.tailoring.bullet_selector import BulletSelection, SectionSelection
    from jobpilot.tailoring.resume_parser import parse_master_resume
    from jobpilot.tailoring.verifier import apply_verifications

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")

    # e1 has an invented metric
    selection = BulletSelection(
        summary_id="s1",
        sections=[
            SectionSelection(
                section="experience",
                employer="Acme Corp",
                bullet_ids=["e1"],
                rephrasings={"e1": "Built REST APIs serving 50,000 requests/day using FastAPI."},
            )
        ],
    )
    cleaned, rejections = apply_verifications(selection, resume)
    assert len(rejections) == 1
    assert "e1" in rejections[0]
    assert "e1" not in cleaned.sections[0].rephrasings


def test_apply_verifications_keeps_valid():
    from jobpilot.tailoring.bullet_selector import BulletSelection, SectionSelection
    from jobpilot.tailoring.resume_parser import parse_master_resume
    from jobpilot.tailoring.verifier import apply_verifications

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")

    valid_rephrasing = "Built scalable REST APIs serving 10,000 requests/day using FastAPI."
    selection = BulletSelection(
        summary_id="s1",
        sections=[
            SectionSelection(
                section="experience",
                employer="Acme Corp",
                bullet_ids=["e1"],
                rephrasings={"e1": valid_rephrasing},
            )
        ],
    )
    cleaned, rejections = apply_verifications(selection, resume)
    assert len(rejections) == 0
    assert cleaned.sections[0].rephrasings.get("e1") == valid_rephrasing


# ---------------------------------------------------------------------------
# HTML renderer tests
# ---------------------------------------------------------------------------

def test_render_html_contains_name():
    from jobpilot.tailoring.bullet_selector import BulletSelection, SectionSelection
    from jobpilot.tailoring.renderer import render_html
    from jobpilot.tailoring.resume_parser import parse_master_resume

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")
    selection = BulletSelection(
        summary_id="s1",
        sections=[
            SectionSelection(
                section="experience",
                employer="Acme Corp",
                bullet_ids=["e1"],
            )
        ],
    )
    html = render_html(resume, selection, "Test User", "test@example.com")
    assert "Test User" in html


def test_render_html_contains_bullet():
    from jobpilot.tailoring.bullet_selector import BulletSelection, SectionSelection
    from jobpilot.tailoring.renderer import render_html
    from jobpilot.tailoring.resume_parser import parse_master_resume

    resume = parse_master_resume(FIXTURE_DIR / "master_resume_fixture.md")
    selection = BulletSelection(
        summary_id="s1",
        sections=[
            SectionSelection(
                section="experience",
                employer="Acme Corp",
                bullet_ids=["e1"],
            )
        ],
    )
    html = render_html(resume, selection, "Test User", "test@example.com")
    assert "Built REST APIs serving 10,000 requests/day" in html


# ---------------------------------------------------------------------------
# PDF text extraction test (mocked pypdf)
# ---------------------------------------------------------------------------

def test_pdf_text_extraction_missing():
    from unittest.mock import MagicMock, patch
    from jobpilot.tailoring.renderer import verify_pdf_text

    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""

    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("jobpilot.tailoring.renderer.PdfReader", return_value=mock_reader):
        warnings = verify_pdf_text(
            Path("fake.pdf"),
            "Test User",
            ["Built REST APIs serving 10,000"],
        )

    assert any("name missing" in w for w in warnings)
    assert any("bullet missing" in w for w in warnings)


def test_pdf_text_extraction_present():
    from unittest.mock import MagicMock, patch
    from jobpilot.tailoring.renderer import verify_pdf_text

    text = "Test User | test@example.com\nBuilt REST APIs serving 10,000 requests/day using FastAPI."
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text

    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("jobpilot.tailoring.renderer.PdfReader", return_value=mock_reader):
        warnings = verify_pdf_text(
            Path("fake.pdf"),
            "Test User",
            ["Built REST APIs serving 10,000"],
        )

    assert warnings == []
