from __future__ import annotations

import re

from jobpilot.config import FixedAnswers

FIXED_ANSWER_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Work authorisation — most specific first
    (re.compile(r"authoris?ed.*work.*us\b|authorized.*united states|work.*legally.*us\b|legally.*work.*us\b|us.*work.*authori|right to work.*us\b", re.I), "authorized_to_work_US"),
    (re.compile(r"authoris?ed.*work.*(?:eu\b|europe|european union)", re.I), "authorized_to_work_EU"),
    (re.compile(r"authoris?ed.*work.*(?:uk\b|united kingdom|britain)", re.I), "authorized_to_work_UK"),
    # Sponsorship
    (re.compile(r"(?:require|need|visa).*sponsor|sponsor.*visa|work.*permit.*sponsor|employer.*sponsor|sponsorship.*work", re.I), "require_sponsorship_now_or_future"),
    # Relocation
    (re.compile(r"willing.*reloc|open.*reloc|relocate", re.I), "willing_to_relocate"),
    # Previous employment
    (re.compile(r"previous(?:ly)?.*employ|former(?:ly)?.*work.*here|work(?:ed)?.*(?:this|our) company before", re.I), "previously_employed_here"),
    # Criminal
    (re.compile(r"criminal|felony|convicted|background check.*criminal|arrest record", re.I), "criminal_conviction"),
    # Age
    (re.compile(r"18.*over|over.*18|age.*18|at least 18", re.I), "age_18_or_over"),
    # Gender
    (re.compile(r"\bgender\b", re.I), "gender"),
    # Race / ethnicity
    (re.compile(r"\brace\b|ethnic(?:ity)?", re.I), "race_ethnicity"),
    # Veteran
    (re.compile(r"veteran|military service|protected veteran", re.I), "veteran_status"),
    # Disability
    (re.compile(r"disabilit|disabled|accommodation request", re.I), "disability_status"),
    # Pronouns
    (re.compile(r"\bpronoun", re.I), "pronouns"),
    # How did you hear
    (re.compile(r"how did you hear|how did you find|source of application|referral source", re.I), "how_did_you_hear"),
]


def classify_field(label: str, field_name: str = "") -> tuple[str | None, str | None]:
    """Return (fixed_answer_key, None) if confident match, else (None, None)."""
    for pattern, key in FIXED_ANSWER_PATTERNS:
        if pattern.search(label) or (field_name and pattern.search(field_name)):
            return key, None
    return None, None


def get_fixed_answer(label: str, field_name: str, fixed_answers: FixedAnswers) -> str | None:
    """Return fixed answer string for this field, or None if no match."""
    key, _ = classify_field(label, field_name)
    if key is None:
        return None
    return getattr(fixed_answers, key, None)
