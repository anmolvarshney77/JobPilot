from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ContactSuggestion:
    name: str | None
    role: str | None        # "recruiter" | "hiring_manager" | "engineer"
    source: str             # "posting" | "search_query"
    contact_url: str | None
    search_query: str | None


_CONTACT_PATTERNS = [
    (re.compile(r"contact\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.I), "recruiter"),
    (re.compile(r"reach\s+out\s+to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.I), "hiring_manager"),
    (re.compile(r"recruiter:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.I), "recruiter"),
    (re.compile(r"hiring\s+manager:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.I), "hiring_manager"),
    (re.compile(r"questions\??\s+(?:email|contact)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.I), "recruiter"),
    (re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+\((?:engineering\s+manager|recruiter|hiring\s+manager|talent|hr)\)", re.I), "hiring_manager"),
]

_LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/([\w-]+)")

_TEAM_KEYWORDS = {
    "backend": ["backend", "server", "api", "infrastructure", "platform", "data"],
    "frontend": ["frontend", "ui", "react", "angular", "vue", "web"],
    "fullstack": ["fullstack", "full-stack", "full stack"],
    "ml": ["machine learning", "ml", "ai", "data science", "nlp"],
    "mobile": ["mobile", "ios", "android", "react native"],
    "devops": ["devops", "sre", "cloud", "kubernetes", "infrastructure"],
}


def _extract_team_keyword(job_title: str) -> str:
    lower = job_title.lower()
    for keyword, signals in _TEAM_KEYWORDS.items():
        if any(s in lower for s in signals):
            return keyword
    return "engineering"


def extract_contacts_from_posting(
    description: str, company_name: str, job_title: str
) -> list[ContactSuggestion]:
    contacts: list[ContactSuggestion] = []

    # 1. Try to find named contacts in description
    for pattern, role in _CONTACT_PATTERNS:
        for m in pattern.finditer(description):
            name = m.group(1).strip()
            words = name.split()
            # Reject if any word isn't capitalized — filters false positives from re.I
            if not (1 <= len(words) <= 4 and all(w[0].isupper() for w in words)):
                continue
            if len(name.split()) <= 4:  # sanity check: not too many words
                contacts.append(ContactSuggestion(
                    name=name,
                    role=role,
                    source="posting",
                    contact_url=None,
                    search_query=None,
                ))

    # 2. Find LinkedIn URLs in the description and try to associate with names
    for m in _LINKEDIN_RE.finditer(description):
        url = m.group(0)
        # Check if any existing contact is nearby (within 100 chars)
        pos = m.start()
        matched = False
        for contact in contacts:
            if contact.source == "posting" and contact.contact_url is None:
                contact.contact_url = url
                matched = True
                break
        if not matched:
            contacts.append(ContactSuggestion(
                name=None,
                role="recruiter",
                source="posting",
                contact_url=url,
                search_query=None,
            ))

    if contacts:
        # Deduplicate by name
        seen_names: set[str] = set()
        deduped: list[ContactSuggestion] = []
        for c in contacts:
            key = c.name or c.contact_url or ""
            if key not in seen_names:
                seen_names.add(key)
                deduped.append(c)
        return deduped

    # 3. No contacts found — generate search queries
    team_keyword = _extract_team_keyword(job_title)
    queries = [
        f'"{company_name}" engineering manager {team_keyword} site:linkedin.com',
        f'"{company_name}" recruiter software engineer site:linkedin.com',
        f'"{company_name}" {job_title} team lead site:linkedin.com',
    ]
    return [
        ContactSuggestion(
            name=None,
            role="hiring_manager",
            source="search_query",
            contact_url=None,
            search_query=q,
        )
        for q in queries
    ]
