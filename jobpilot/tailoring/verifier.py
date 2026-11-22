from __future__ import annotations

import re

from jobpilot.tailoring.bullet_selector import BulletSelection
from jobpilot.tailoring.resume_parser import ResumeData

KNOWN_TECH_TERMS: set[str] = {
    "fastapi", "postgresql", "postgres", "react", "nextjs", "next.js",
    "langchain", "openai", "anthropic", "kubernetes", "k8s", "docker",
    "aws", "gcp", "azure", "kafka", "redis", "mongodb", "graphql",
    "typescript", "javascript", "python", "java", "golang", "go",
    "springboot", "spring", "node", "nodejs", "flask", "django",
    "pytorch", "tensorflow", "scikit", "pandas", "numpy",
    "elasticsearch", "mysql", "sqlite", "cassandra", "dynamodb",
    "terraform", "ansible", "jenkins", "github", "gitlab", "jira",
    "langraph", "langgraph", "vectordb", "pinecone", "weaviate", "qdrant",
    "n8n", "playwright", "selenium", "celery", "rabbitmq", "grpc",
}

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _extract_tech_terms(text: str) -> set[str]:
    lower = text.lower()
    found = set()
    for term in KNOWN_TECH_TERMS:
        # word-boundary-ish check
        pattern = re.escape(term)
        if re.search(r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])", lower):
            found.add(term)
    return found


def _extract_proper_nouns(text: str, original: str) -> set[str]:
    # Capitalised tokens that aren't the first word after a sentence boundary
    # and don't appear in the original text
    words = text.split()
    orig_tokens = set(original.split())
    # Sentence-starting positions: index 0, or after ". " or "! " or "? "
    sentence_starts: set[int] = {0}
    for i, w in enumerate(words):
        if w.endswith((".", "!", "?")):
            if i + 1 < len(words):
                sentence_starts.add(i + 1)

    proper: set[str] = set()
    for i, word in enumerate(words):
        # Strip punctuation for comparison
        clean = re.sub(r"[^A-Za-z0-9]", "", word)
        if not clean:
            continue
        if clean[0].isupper() and i not in sentence_starts:
            if word not in orig_tokens and clean not in orig_tokens:
                proper.add(clean)
    return proper


def verify_rephrasing(original: str, rephrased: str) -> tuple[bool, str]:
    orig_numbers = _extract_numbers(original)
    new_numbers = _extract_numbers(rephrased)
    invented_numbers = new_numbers - orig_numbers
    if invented_numbers:
        return False, f"invented number(s): {invented_numbers}"

    orig_tech = _extract_tech_terms(original)
    new_tech = _extract_tech_terms(rephrased)
    invented_tech = new_tech - orig_tech
    if invented_tech:
        return False, f"invented tech term(s): {invented_tech}"

    invented_nouns = _extract_proper_nouns(rephrased, original)
    if invented_nouns:
        return False, f"invented proper noun(s): {invented_nouns}"

    return True, ""


def apply_verifications(
    selection: BulletSelection,
    resume: ResumeData,
) -> tuple[BulletSelection, list[str]]:
    rejections: list[str] = []

    for sec in selection.sections:
        cleaned: dict[str, str] = {}
        for bullet_id, rephrased in sec.rephrasings.items():
            original_bullet = resume.bullets.get(bullet_id)
            if original_bullet is None:
                rejections.append(f"{bullet_id}: bullet id not found in master resume")
                continue
            valid, reason = verify_rephrasing(original_bullet.text, rephrased)
            if valid:
                cleaned[bullet_id] = rephrased
            else:
                rejections.append(f"{bullet_id}: {reason} — reverted to original")
        sec.rephrasings = cleaned

    return selection, rejections
