from __future__ import annotations

import re

SYNONYMS: dict[str, list[str]] = {
    "kubernetes": ["k8s"],
    "postgresql": ["postgres", "psql"],
    "go": ["golang"],
    "javascript": ["js"],
    "typescript": ["ts"],
    "elasticsearch": ["elastic"],
    "mongodb": ["mongo"],
    "redis": ["valkey"],
    "machine learning": ["ml"],
    "natural language processing": ["nlp"],
    "large language model": ["llm", "llms"],
    "retrieval augmented generation": ["rag"],
    "continuous integration": ["ci/cd", "cicd"],
    "amazon web services": ["aws"],
    "google cloud platform": ["gcp", "google cloud"],
    "microsoft azure": ["azure"],
}

# Build reverse lookup: synonym → canonical term
_REVERSE: dict[str, str] = {}
for _canonical, _syns in SYNONYMS.items():
    for _s in _syns:
        _REVERSE[_s] = _canonical


def _expand(term: str) -> set[str]:
    """Return term plus all its synonyms (and reverse-lookup to canonical)."""
    term_lower = term.lower()
    result: set[str] = {term_lower}
    # direct synonyms
    if term_lower in SYNONYMS:
        result.update(SYNONYMS[term_lower])
    # reverse: if term is a synonym, add the canonical
    if term_lower in _REVERSE:
        canonical = _REVERSE[term_lower]
        result.add(canonical)
        result.update(SYNONYMS.get(canonical, []))
    return result


def _term_in_text(term: str, text_lower: str) -> bool:
    """Case-insensitive word-boundary match for a term (which may be multi-word)."""
    # For multi-word terms like "google cloud", a simple 'in' check with boundary is fine
    escaped = re.escape(term)
    return bool(re.search(r"(?<!\w)" + escaped + r"(?!\w)", text_lower))


def keyword_score(
    description: str,
    core_skills: list[str],
    nice_to_have: list[str],
) -> float:
    """
    Weighted overlap: core_skills weight 2, nice_to_have weight 1.
    Returns [0.0, 1.0] normalised by max possible weighted score.
    Returns 0.0 if description is empty or no skills provided.
    """
    if not description or not (core_skills or nice_to_have):
        return 0.0

    text_lower = description.lower()
    max_weight = len(core_skills) * 2 + len(nice_to_have) * 1
    if max_weight == 0:
        return 0.0

    earned = 0.0
    for skill in core_skills:
        for variant in _expand(skill):
            if _term_in_text(variant, text_lower):
                earned += 2
                break

    for skill in nice_to_have:
        for variant in _expand(skill):
            if _term_in_text(variant, text_lower):
                earned += 1
                break

    return min(earned / max_weight, 1.0)
