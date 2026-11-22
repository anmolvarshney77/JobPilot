"""Generic form filler for Ashby, SmartRecruiters, Workable, Recruitee, Personio."""
from __future__ import annotations

import logging
from pathlib import Path

from jobpilot.apply.field_classifier import get_fixed_answer
from jobpilot.apply.form_filler import (
    FieldResult,
    FormFillResult,
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

    # Name
    for sel in ["input[autocomplete=name]", "input[name*=name][type=text]", "input[placeholder*=name]"]:
        el = await page.query_selector(sel)
        if el:
            await fill_text_field(page, sel, profile.name)
            result.filled.append(FieldResult(label="Name", value=profile.name, source="profile"))
            break

    # Email
    el = await page.query_selector("input[type=email]")
    if el:
        await fill_text_field(page, "input[type=email]", profile.email)
        result.filled.append(FieldResult(label="Email", value=profile.email, source="profile"))

    # Phone
    el = await page.query_selector("input[type=tel]")
    if el:
        await fill_text_field(page, "input[type=tel]", profile.phone.number)
        result.filled.append(FieldResult(label="Phone", value=profile.phone.number, source="profile"))

    # Resume
    el = await page.query_selector("input[type=file]")
    if el and resume_path.exists():
        await handle_file_upload(page, "input[type=file]", resume_path)
        result.filled.append(FieldResult(label="Resume", value=str(resume_path), source="upload"))

    # Scan labels for fixed answers
    labels = await page.query_selector_all("label")
    for label_el in labels:
        label_text = (await label_el.inner_text()).strip()
        for_attr = await label_el.get_attribute("for") or ""
        input_el = None
        if for_attr:
            input_el = await page.query_selector(f"#{for_attr}")
        if input_el is None:
            # Sibling input
            parent = await label_el.evaluate_handle("el => el.parentElement")
            input_el = await parent.query_selector("input, select, textarea")

        if input_el is None:
            continue

        input_name = await input_el.get_attribute("name") or ""
        fixed_val = get_fixed_answer(label_text, input_name, fa)
        if fixed_val:
            tag = (await input_el.evaluate("el => el.tagName")).lower()
            sel = f"[name='{input_name}']" if input_name else f"#{for_attr}" if for_attr else None
            if sel:
                from jobpilot.apply.form_filler import fill_select_field
                if tag == "select":
                    await fill_select_field(page, sel, fixed_val)
                else:
                    await fill_text_field(page, sel, fixed_val)
                result.filled.append(FieldResult(label=label_text, value=fixed_val, source="fixed"))

    btn = await find_submit_button(page)
    result.submit_button_found = btn is not None
    return result
