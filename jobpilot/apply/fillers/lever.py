from __future__ import annotations

import logging
from pathlib import Path

from jobpilot.apply.field_classifier import classify_field, get_fixed_answer
from jobpilot.apply.form_filler import (
    FieldResult,
    FormFillResult,
    fill_select_field,
    fill_text_field,
    find_submit_button,
    handle_file_upload,
)
from jobpilot.config import ProfileConfig
from jobpilot.tailoring.draft_answers import DraftAnswers

logger = logging.getLogger(__name__)


async def fill_form(
    page,
    profile: ProfileConfig,
    resume_path: Path,
    cover_letter_path: Path | None,
    draft_answers: DraftAnswers | None,
    salary_for_country: int | None,
) -> FormFillResult:
    result = FormFillResult()
    fa = profile.fixed_answers

    async def _fill(selector: str, value: str, label: str, source: str) -> None:
        el = await page.query_selector(selector)
        if el is None:
            return
        await fill_text_field(page, selector, value)
        result.filled.append(FieldResult(label=label, value=value, source=source))

    # Standard fields
    await _fill("input[name=name]", profile.name, "Full Name", "profile")
    await _fill("input[name=email]", profile.email, "Email", "profile")
    await _fill("input[name=phone]", profile.phone.number, "Phone", "profile")

    # LinkedIn / GitHub / Portfolio links
    for name_attr, label, val in [
        ("urls[LinkedIn]", "LinkedIn", profile.linkedin),
        ("urls[GitHub]", "GitHub", profile.github),
        ("urls[Portfolio]", "Portfolio", profile.portfolio),
    ]:
        for name_pat in [name_attr, name_attr.lower()]:
            el = await page.query_selector(f"input[name='{name_pat}']")
            if el:
                await fill_text_field(page, f"input[name='{name_pat}']", val)
                result.filled.append(FieldResult(label=label, value=val, source="profile"))
                break

    # Also try generic linkedin/github inputs
    for sel, label, val in [
        ("input[name*=linkedin]", "LinkedIn", profile.linkedin),
        ("input[name*=github]", "GitHub", profile.github),
        ("input[name*=portfolio]", "Portfolio", profile.portfolio),
    ]:
        el = await page.query_selector(sel)
        if el and not any(f.label == label for f in result.filled):
            await fill_text_field(page, sel, val)
            result.filled.append(FieldResult(label=label, value=val, source="profile"))

    # Resume upload
    for sel in ["input[type=file]"]:
        el = await page.query_selector(sel)
        if el and resume_path.exists():
            await handle_file_upload(page, sel, resume_path)
            result.filled.append(FieldResult(label="Resume", value=str(resume_path), source="upload"))
            break

    # Custom questions
    questions = await page.query_selector_all(".application-question")
    for question in questions:
        label_el = await question.query_selector("label")
        input_el = await question.query_selector("input, select, textarea")
        if label_el is None or input_el is None:
            continue

        label_text = (await label_el.inner_text()).strip()
        input_name = await input_el.get_attribute("name") or ""
        tag = (await input_el.evaluate("el => el.tagName")).lower()

        # Skip already-filled standard fields
        if input_name in ("name", "email", "phone"):
            continue

        fixed_val = get_fixed_answer(label_text, input_name, fa)
        if fixed_val is not None:
            if tag == "select":
                await fill_select_field(page, f"[name='{input_name}']", fixed_val)
            else:
                await fill_text_field(page, f"[name='{input_name}']", fixed_val)
            result.filled.append(FieldResult(label=label_text, value=fixed_val, source="fixed"))
            continue

        draft_val = _match_draft(label_text, draft_answers)
        if draft_val:
            await fill_text_field(page, f"[name='{input_name}']", draft_val)
            fr = FieldResult(label=label_text, value=draft_val, source="draft", highlight="yellow")
            result.filled.append(fr)
            result.yellow_fields.append(fr)
            continue

        fr = FieldResult(label=label_text, value="", source="unfilled", highlight="yellow")
        result.yellow_fields.append(fr)

    btn = await find_submit_button(page)
    result.submit_button_found = btn is not None
    return result


def _match_draft(label: str, draft_answers: DraftAnswers | None) -> str | None:
    if draft_answers is None:
        return None
    lower = label.lower()
    if "why" in lower and "company" in lower:
        return draft_answers.why_company
    if "why" in lower and ("role" in lower or "position" in lower or "job" in lower):
        return draft_answers.why_role
    if "proud" in lower or "project" in lower:
        return draft_answers.proud_project
    return None
