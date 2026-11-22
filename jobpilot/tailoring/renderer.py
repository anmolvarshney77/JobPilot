from __future__ import annotations

import asyncio
import html as html_module
from pathlib import Path

from pypdf import PdfReader

from jobpilot.tailoring.bullet_selector import BulletSelection, SectionSelection
from jobpilot.tailoring.resume_parser import ResumeData

RESUME_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  /* ATS-friendly: no tables, no columns, no icons, no images */
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Arial, sans-serif; font-size: 10.5pt; line-height: 1.4;
         margin: 0.6in 0.65in; color: #000; }}
  h1 {{ font-size: 16pt; font-weight: bold; margin-bottom: 2px; }}
  .contact {{ font-size: 9.5pt; margin-bottom: 8px; }}
  h2 {{ font-size: 11pt; font-weight: bold; border-bottom: 1px solid #000;
       margin-top: 10px; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  h3 {{ font-size: 10.5pt; font-weight: bold; margin-top: 6px; }}
  .meta {{ font-size: 9.5pt; color: #333; margin-bottom: 2px; }}
  ul {{ margin-left: 16px; margin-bottom: 4px; }}
  li {{ margin-bottom: 2px; }}
  .skills-block {{ margin-top: 2px; }}
  .education-block {{ margin-top: 2px; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


def _e(text: str) -> str:
    return html_module.escape(text)


def _get_bullet_text(
    bullet_id: str,
    sec: SectionSelection,
    resume: ResumeData,
) -> str:
    rephrased = sec.rephrasings.get(bullet_id)
    if rephrased:
        return rephrased
    bullet = resume.bullets.get(bullet_id)
    return bullet.text if bullet else ""


def render_html(
    resume: ResumeData,
    selection: BulletSelection,
    profile_name: str,
    contact_block: str,
) -> str:
    parts: list[str] = []

    # Name and contact
    parts.append(f"<h1>{_e(profile_name)}</h1>")
    contact_html = _e(contact_block).replace("\n", "<br>")
    parts.append(f'<div class="contact">{contact_html}</div>')

    # Summary
    summary_bullet = resume.bullets.get(selection.summary_id)
    if summary_bullet:
        parts.append("<h2>Summary</h2>")
        parts.append(f"<p>{_e(summary_bullet.text)}</p>")

    # Group sections
    exp_sections = [s for s in selection.sections if s.section == "experience"]
    proj_sections = [s for s in selection.sections if s.section == "projects"]
    honor_sections = [s for s in selection.sections if s.section == "honors"]

    # Experience
    if exp_sections:
        parts.append("<h2>Experience</h2>")
        for sec in exp_sections:
            employer = sec.employer or ""
            # Find employer meta
            meta = ""
            for emp_heading, emp_meta in resume.employers:
                if emp_heading == employer:
                    meta = emp_meta
                    break
            if employer:
                parts.append(f"<h3>{_e(employer)}</h3>")
            if meta:
                parts.append(f'<div class="meta">{_e(meta)}</div>')
            if sec.bullet_ids:
                parts.append("<ul>")
                for bid in sec.bullet_ids:
                    text = _get_bullet_text(bid, sec, resume)
                    if text:
                        parts.append(f"<li>{_e(text)}</li>")
                parts.append("</ul>")

    # Projects
    if proj_sections:
        parts.append("<h2>Projects</h2>")
        for sec in proj_sections:
            employer = sec.employer or ""
            if employer:
                parts.append(f"<h3>{_e(employer)}</h3>")
            if sec.bullet_ids:
                parts.append("<ul>")
                for bid in sec.bullet_ids:
                    text = _get_bullet_text(bid, sec, resume)
                    if text:
                        parts.append(f"<li>{_e(text)}</li>")
                parts.append("</ul>")

    # Honors
    if honor_sections:
        parts.append("<h2>Honors &amp; Achievements</h2>")
        parts.append("<ul>")
        for sec in honor_sections:
            for bid in sec.bullet_ids:
                text = _get_bullet_text(bid, sec, resume)
                if text:
                    parts.append(f"<li>{_e(text)}</li>")
        parts.append("</ul>")

    # Skills
    if resume.skills_raw:
        parts.append("<h2>Skills</h2>")
        parts.append(f'<div class="skills-block">{_e(resume.skills_raw)}</div>')

    # Education
    if resume.education_raw or any(
        b.section == "education" for b in resume.bullets.values()
    ):
        parts.append("<h2>Education</h2>")
        if resume.education_raw:
            for line in resume.education_raw.splitlines():
                if line.strip():
                    parts.append(f'<div class="education-block">{_e(line)}</div>')
        edu_bullets = [b for b in resume.bullets.values() if b.section == "education"]
        if edu_bullets:
            parts.append("<ul>")
            for b in edu_bullets:
                parts.append(f"<li>{_e(b.text)}</li>")
            parts.append("</ul>")

    body_html = "\n".join(parts)
    return RESUME_TEMPLATE.format(body_html=body_html)


async def html_to_pdf(html_content: str, output_path: Path) -> int:
    from playwright.async_api import async_playwright

    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html_content, wait_until="networkidle")
        await page.pdf(
            path=str(output_path),
            format="A4",
            print_background=False,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        await browser.close()

    # Count pages with pypdf
    reader = PdfReader(str(output_path))
    return len(reader.pages)


async def render_resume(
    resume: ResumeData,
    selection: BulletSelection,
    profile_name: str,
    output_dir: Path,
    company_name: str,
    max_iterations: int = 3,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    first_name, last_name = _split_name(profile_name)
    pdf_name = f"{first_name}_{last_name}_Resume_{_safe_name(company_name)}.pdf"
    pdf_path = output_dir / pdf_name

    contact_block = resume.contact
    current_selection = selection.model_copy(deep=True)

    for iteration in range(max_iterations):
        html_content = render_html(resume, current_selection, profile_name, contact_block)
        page_count = await html_to_pdf(html_content, pdf_path)

        if page_count <= 1:
            return pdf_path

        if iteration < max_iterations - 1:
            # Drop last bullet from each section to trim
            for sec in current_selection.sections:
                if len(sec.bullet_ids) > 1:
                    sec.bullet_ids = sec.bullet_ids[:-1]
                    # Remove any rephrasings for dropped bullets
                    sec.rephrasings = {
                        k: v for k, v in sec.rephrasings.items()
                        if k in sec.bullet_ids
                    }

    raise ValueError(
        f"Resume still >1 page after {max_iterations} iterations for {company_name}"
    )


def verify_pdf_text(pdf_path: Path, expected_name: str, bullet_texts: list[str]) -> list[str]:
    try:
        reader = PdfReader(str(pdf_path))
        full_text = " ".join(
            (page.extract_text() or "") for page in reader.pages
        )
    except Exception:
        full_text = ""

    missing: list[str] = []
    if expected_name not in full_text:
        missing.append("name missing")
    for bt in bullet_texts:
        needle = bt[:30]
        if needle not in full_text:
            missing.append(f"bullet missing: {needle}")
    return missing


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return parts[0], ""


def _safe_name(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "_", name).strip("_")
