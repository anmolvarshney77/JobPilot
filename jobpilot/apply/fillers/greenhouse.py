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
    name_parts = profile.name.split(None, 1)
    first = name_parts[0]
    last = name_parts[1] if len(name_parts) > 1 else ""

    async def _fill(selector: str, value: str, label: str, source: str) -> None:
        el = await page.query_selector(selector)
        if el is None:
            return
        await fill_text_field(page, selector, value)
        result.filled.append(FieldResult(label=label, value=value, source=source))

    # Standard fields
    await _fill("#first_name", first, "First Name", "profile")
    await _fill("#last_name", last, "Last Name", "profile")
    await _fill("#email", profile.email, "Email", "profile")
    await _fill("#phone", profile.phone.number, "Phone", "profile")

    # LinkedIn / GitHub / Portfolio
    for sel_pattern, label, val in [
        ("input[id*=linkedin], input[name*=linkedin]", "LinkedIn", profile.linkedin),
        ("input[id*=github], input[name*=github]", "GitHub", profile.github),
        ("input[id*=website], input[id*=portfolio]", "Website", profile.portfolio),
    ]:
        for sel in sel_pattern.split(", "):
            el = await page.query_selector(sel)
            if el:
                await fill_text_field(page, sel, val)
                result.filled.append(FieldResult(label=label, value=val, source="profile"))
                break

    # Resume upload
    for sel in ["input[type=file][id*=resume]", "input[type=file][name*=resume]", "input[type=file]"]:
        el = await page.query_selector(sel)
        if el and resume_path.exists():
            await handle_file_upload(page, sel, resume_path)
            result.filled.append(FieldResult(label="Resume", value=str(resume_path), source="upload"))
            break

    # Cover letter upload
    if cover_letter_path and cover_letter_path.exists():
        for sel in ["input[type=file][id*=cover]", "input[type=file][name*=cover]"]:
            el = await page.query_selector(sel)
            if el:
                await handle_file_upload(page, sel, cover_letter_path)
                result.filled.append(FieldResult(label="Cover Letter", value=str(cover_letter_path), source="upload"))
                break

    # Custom question fields
    fields = await page.query_selector_all("div.field")
    for field_div in fields:
        label_el = await field_div.query_selector("label")
        input_el = await field_div.query_selector("input, select, textarea")
        if label_el is None or input_el is None:
            continue

        label_text = (await label_el.inner_text()).strip()
        input_id = await input_el.get_attribute("id") or ""
        input_name = await input_el.get_attribute("name") or ""
        tag = (await input_el.evaluate("el => el.tagName")).lower()

        # Skip already-filled standard fields
        if input_id in ("first_name", "last_name", "email", "phone"):
            continue

        # Fixed answer check
        fixed_val = get_fixed_answer(label_text, input_name, fa)
        if fixed_val is not None:
            if tag == "select":
                await fill_select_field(page, f"#{input_id}" if input_id else f"[name='{input_name}']", fixed_val)
            else:
                sel = f"#{input_id}" if input_id else f"[name='{input_name}']"
                await fill_text_field(page, sel, fixed_val)
            result.filled.append(FieldResult(label=label_text, value=fixed_val, source="fixed"))
            continue

        # Draft answers
        draft_val = _match_draft(label_text, draft_answers)
        if draft_val:
            sel = f"#{input_id}" if input_id else f"[name='{input_name}']"
            await fill_text_field(page, sel, draft_val)
            fr = FieldResult(label=label_text, value=draft_val, source="draft", highlight="yellow")
            result.filled.append(fr)
            result.yellow_fields.append(fr)
            continue

        # Unfilled
        fr = FieldResult(label=label_text, value="", source="unfilled", highlight="yellow")
        result.yellow_fields.append(fr)

    # Find submit button (but don't click)
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
