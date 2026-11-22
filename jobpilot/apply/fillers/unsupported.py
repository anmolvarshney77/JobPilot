from __future__ import annotations

from jobpilot.apply.form_filler import FieldResult, FormFillResult

UNSUPPORTED_SIGNALS = [
    "workday", "taleo", "icims", "successfactors",
    "login", "sign in", "create account", "register",
    "captcha", "recaptcha", "hcaptcha",
]


async def check_unsupported(page) -> str | None:
    """Return a reason string if the page requires login, account creation, or CAPTCHA."""
    try:
        content = (await page.content()).lower()
    except Exception:
        return None

    for signal in UNSUPPORTED_SIGNALS:
        if signal in content:
            return signal

    # Check URL
    url = page.url.lower()
    for signal in ["workday", "taleo", "icims", "successfactors"]:
        if signal in url:
            return signal

    return None


async def handle_unsupported(page, reason: str) -> FormFillResult:
    """Fill nothing; return a yellow-flagged result explaining why."""
    result = FormFillResult()
    fr = FieldResult(
        label=f"Unsupported ATS / barrier: {reason}",
        value="",
        source="unfilled",
        highlight="yellow",
    )
    result.yellow_fields.append(fr)
    result.submit_button_found = False
    return result
