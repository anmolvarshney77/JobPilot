from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Bullet:
    id: str
    tags: list[str]
    text: str
    section: str          # "summary" | "experience" | "projects" | "honors"
    employer: str | None
    employer_meta: str | None


@dataclass
class ResumeData:
    contact: str
    bullets: dict[str, Bullet]
    skills_raw: str
    education_raw: str
    employers: list[tuple[str, str]]  # [(employer_heading, meta)] in order


_BULLET_RE = re.compile(
    r"^-\s+id:\s*(\S+)\s*\|(?:\s*tags:\s*([^|]*)\|)?\s*text:\s*(.+)$"
)


def parse_master_resume(path: str | Path) -> ResumeData:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    contact_lines: list[str] = []
    bullets: dict[str, Bullet] = {}
    skills_lines: list[str] = []
    education_lines: list[str] = []
    employers: list[tuple[str, str]] = []

    current_section: str | None = None
    current_employer: str | None = None
    current_employer_meta: str | None = None
    in_contact = False

    for line in lines:
        stripped = line.strip()

        # Section headers
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            in_contact = False
            if "contact" in heading:
                current_section = "contact"
                in_contact = True
                current_employer = None
            elif "summary" in heading:
                current_section = "summary"
                current_employer = None
            elif "experience" in heading:
                current_section = "experience"
                current_employer = None
            elif "project" in heading:
                current_section = "projects"
                current_employer = None
            elif "honor" in heading or "achievement" in heading:
                current_section = "honors"
                current_employer = None
            elif "skill" in heading:
                current_section = "skills"
                current_employer = None
            elif "education" in heading:
                current_section = "education"
                current_employer = None
            else:
                current_section = "other"
            continue

        # Sub-section employer header (###)
        if stripped.startswith("### "):
            parts = stripped[4:].split("|", 1)
            heading = parts[0].strip()
            meta = parts[1].strip() if len(parts) > 1 else ""
            current_employer = heading
            current_employer_meta = meta
            employers.append((heading, meta))
            continue

        # Contact block
        if current_section == "contact" and stripped and not stripped.startswith("-"):
            contact_lines.append(stripped)
            continue

        # Skills section
        if current_section == "skills":
            if stripped:
                skills_lines.append(stripped)
            continue

        # Education section — may have bullets or plain text
        if current_section == "education":
            m = _BULLET_RE.match(stripped)
            if m:
                bullet_id = m.group(1)
                tags_raw = m.group(2) or ""
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                bullet_text = m.group(3).strip()
                bullets[bullet_id] = Bullet(
                    id=bullet_id,
                    tags=tags,
                    text=bullet_text,
                    section="education",
                    employer=None,
                    employer_meta=None,
                )
            elif stripped:
                education_lines.append(stripped)
            continue

        # Bullet lines
        if current_section in ("summary", "experience", "projects", "honors"):
            m = _BULLET_RE.match(stripped)
            if m:
                bullet_id = m.group(1)
                tags_raw = m.group(2) or ""
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                bullet_text = m.group(3).strip()
                bullets[bullet_id] = Bullet(
                    id=bullet_id,
                    tags=tags,
                    text=bullet_text,
                    section=current_section,
                    employer=current_employer,
                    employer_meta=current_employer_meta,
                )

    return ResumeData(
        contact="\n".join(contact_lines),
        bullets=bullets,
        skills_raw="\n".join(skills_lines),
        education_raw="\n".join(education_lines),
        employers=employers,
    )
