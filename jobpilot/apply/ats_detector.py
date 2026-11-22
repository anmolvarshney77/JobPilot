from __future__ import annotations

import re
from urllib.parse import urlparse

ATS_UNSUPPORTED = {"workday", "taleo", "icims", "successfactors", "brassring", "smarterp"}

_URL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"boards(?:-api)?\.greenhouse\.io", re.I), "greenhouse"),
    (re.compile(r"jobs\.lever\.co", re.I), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com", re.I), "ashby"),
    (re.compile(r"(?:careers|jobs)\.smartrecruiters\.com", re.I), "smartrecruiters"),
    (re.compile(r"apply\.workable\.com", re.I), "workable"),
    (re.compile(r"\.recruitee\.com", re.I), "recruitee"),
    (re.compile(r"(?:\.jobs\.personio\.de|personio\.de)", re.I), "personio"),
    (re.compile(r"myworkdayjobs\.com|wd\d+\.myworkday\.com", re.I), "workday"),
    (re.compile(r"taleo\.net", re.I), "taleo"),
    (re.compile(r"\.icims\.com", re.I), "icims"),
    (re.compile(r"successfactors\.com|sapsf\.com", re.I), "successfactors"),
]

_DOM_ATS_MARKERS = {
    "greenhouse": [
        'form[action*="greenhouse.io"]',
        '[data-greenhouse-id]',
        'iframe[src*="greenhouse.io"]',
    ],
    "lever": [
        'form[action*="lever.co"]',
        '[data-lever]',
        'iframe[src*="lever.co"]',
    ],
    "ashby": [
        'form[action*="ashbyhq.com"]',
        'iframe[src*="ashbyhq.com"]',
    ],
    "workday": [
        'iframe[src*="myworkdayjobs.com"]',
        'iframe[src*="myworkday.com"]',
    ],
}


def detect_ats_from_url(url: str) -> str | None:
    for pattern, ats in _URL_PATTERNS:
        if pattern.search(url):
            return ats
    return None


async def detect_ats_from_dom(page) -> str | None:
    for ats, selectors in _DOM_ATS_MARKERS.items():
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    return ats
            except Exception:
                pass
    return None


async def resolve_apply_url(page, job_url: str) -> tuple[str, str | None]:
    """Navigate to job_url, detect ATS, switch into iframe if needed."""
    await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
    current_url = page.url

    ats = detect_ats_from_url(current_url) or detect_ats_from_url(job_url)
    if ats:
        return current_url, ats

    # Check for embedded iframe
    try:
        frames = page.frames
        for frame in frames:
            frame_url = frame.url
            if frame_url and frame_url != current_url:
                iframe_ats = detect_ats_from_url(frame_url)
                if iframe_ats:
                    return frame_url, iframe_ats
    except Exception:
        pass

    # DOM fallback
    ats = await detect_ats_from_dom(page)
    return current_url, ats
