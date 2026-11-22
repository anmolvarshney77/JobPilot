from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FieldResult:
    label: str
    value: str
    source: str        # "fixed" | "profile" | "upload" | "draft" | "llm" | "unfilled"
    highlight: str | None = None  # "red" | "yellow" | None


@dataclass
class FormFillResult:
    filled: list[FieldResult] = field(default_factory=list)
    red_fields: list[FieldResult] = field(default_factory=list)
    yellow_fields: list[FieldResult] = field(default_factory=list)
    submit_button_found: bool = False


async def type_with_delay(page, selector: str, text: str) -> None:
    """Type into selector with small random delays per character."""
    el = await page.query_selector(selector)
    if el is None:
        return
    await el.click()
    await el.fill("")
    for char in text:
        await el.type(char, delay=random.randint(10, 30))


async def fill_text_field(page, selector: str, value: str) -> None:
    el = await page.query_selector(selector)
    if el is None:
        return
    await el.fill(value)


async def fill_select_field(page, selector: str, value: str) -> None:
    """Try native select first, then custom dropdown."""
    el = await page.query_selector(selector)
    if el is None:
        return
    tag = (await el.evaluate("el => el.tagName")).lower()
    if tag == "select":
        # Try exact match first, then case-insensitive
        options = await page.evaluate(
            """({sel}) => {
                const el = document.querySelector(sel);
                if (!el) return [];
                return Array.from(el.options).map(o => ({value: o.value, text: o.text}));
            }""",
            {"sel": selector},
        )
        for opt in options:
            if opt["text"].strip().lower() == value.lower() or opt["value"].lower() == value.lower():
                await page.select_option(selector, value=opt["value"])
                return
        # Partial match
        for opt in options:
            if value.lower() in opt["text"].lower():
                await page.select_option(selector, value=opt["value"])
                return
    else:
        # Custom dropdown
        await el.click()
        await asyncio.sleep(0.3)
        items = await page.query_selector_all('[role=listbox] [role=option], ul li')
        for item in items:
            text = (await item.inner_text()).strip()
            if text.lower() == value.lower() or value.lower() in text.lower():
                await item.click()
                return


async def fill_autocomplete(page, selector: str, value: str) -> None:
    """Type value and select best autocomplete suggestion."""
    el = await page.query_selector(selector)
    if el is None:
        return
    await el.fill(value)
    try:
        await page.wait_for_selector(
            '[role=listbox], [role=option], ul[class*=suggest] li',
            timeout=2000
        )
        items = await page.query_selector_all('[role=option], [role=listbox] li, ul[class*=suggest] li')
        if items:
            # Pick best match
            for item in items:
                text = (await item.inner_text()).strip()
                if value.lower() in text.lower():
                    await item.click()
                    return
            await items[0].click()
    except Exception:
        pass  # no suggestions; keep typed value


async def fill_phone(
    page,
    country_code_selector: str | None,
    number_selector: str,
    country_code: str,
    number: str,
) -> None:
    if country_code_selector:
        await fill_select_field(page, country_code_selector, country_code)
    await fill_text_field(page, number_selector, number)


async def handle_file_upload(page, selector: str, file_path: Path) -> None:
    el = await page.query_selector(selector)
    if el is None:
        return
    await el.set_input_files(str(file_path))


async def find_submit_button(page) -> object | None:
    """Find but do NOT click the submit button."""
    for sel in [
        'input[type=submit]',
        'button[type=submit]',
        'button:text("Submit")',
        'button:text("Submit Application")',
        'button:text("Apply")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el:
                return el
        except Exception:
            pass
    return None
