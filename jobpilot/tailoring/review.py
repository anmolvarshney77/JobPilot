from __future__ import annotations

import difflib
import html as html_module
from pathlib import Path

from jobpilot.tailoring.bullet_selector import BulletSelection
from jobpilot.tailoring.resume_parser import ResumeData


def _e(text: str) -> str:
    return html_module.escape(text)


def _highlight_diff(original: str, rephrased: str) -> str:
    orig_words = original.split()
    new_words = rephrased.split()
    matcher = difflib.SequenceMatcher(None, orig_words, new_words)
    result_parts: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            result_parts.extend(_e(w) for w in new_words[j1:j2])
        elif op in ("replace", "insert"):
            for w in new_words[j1:j2]:
                result_parts.append(f'<mark style="background:#ff9">{_e(w)}</mark>')
    return " ".join(result_parts)


def generate_review_html(
    resume: ResumeData,
    selection: BulletSelection,
    rejected_rephrasings: list[str],
    output_dir: Path,
    job_title: str,
    company_name: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_path = output_dir / "review.html"

    rejected_ids: set[str] = set()
    for msg in rejected_rephrasings:
        bullet_id = msg.split(":")[0].strip()
        rejected_ids.add(bullet_id)

    rows: list[str] = []

    # Summary
    summary_bullet = resume.bullets.get(selection.summary_id)
    if summary_bullet:
        rows.append(_make_row(
            bullet_id=selection.summary_id,
            original=summary_bullet.text,
            rephrased=None,
            rejected=False,
        ))

    for sec in selection.sections:
        for bid in sec.bullet_ids:
            bullet = resume.bullets.get(bid)
            if not bullet:
                continue
            original = bullet.text
            rephrased_raw = sec.rephrasings.get(bid)
            is_rejected = bid in rejected_ids
            rows.append(_make_row(
                bullet_id=bid,
                original=original,
                rephrased=rephrased_raw,
                rejected=is_rejected,
            ))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Review: {_e(job_title)} @ {_e(company_name)}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 10pt; padding: 20px; color: #111; }}
  h1 {{ font-size: 14pt; margin-bottom: 4px; }}
  .subtitle {{ color: #555; margin-bottom: 20px; }}
  .row {{ display: flex; gap: 16px; margin-bottom: 12px; border-bottom: 1px solid #ddd; padding-bottom: 10px; }}
  .col {{ flex: 1; }}
  .col-label {{ font-size: 8pt; font-weight: bold; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
  .original {{ background: #f5f5f5; padding: 6px 8px; border-radius: 3px; }}
  .rephrased {{ padding: 6px 8px; }}
  .rejected-label {{ color: red; font-size: 8pt; font-weight: bold; }}
  .bullet-id {{ font-size: 8pt; color: #999; margin-bottom: 2px; }}
</style>
</head>
<body>
<h1>Resume Review</h1>
<div class="subtitle">{_e(job_title)} @ {_e(company_name)}</div>
{"".join(rows)}
</body>
</html>"""

    review_path.write_text(html, encoding="utf-8")
    return review_path


def _make_row(
    bullet_id: str,
    original: str,
    rephrased: str | None,
    rejected: bool,
) -> str:
    right_content: str
    if rephrased and not rejected:
        right_content = _highlight_diff(original, rephrased)
        right_label = "Rephrased"
    elif rejected:
        right_content = f'<span class="rejected-label">REJECTED — original used</span> {_e(original)}'
        right_label = "Rephrased (rejected)"
    else:
        right_content = "(original used)"
        right_label = "Tailored"

    return f"""<div class="row">
  <div class="col">
    <div class="bullet-id">{_e(bullet_id)}</div>
    <div class="col-label">Original</div>
    <div class="original">{_e(original)}</div>
  </div>
  <div class="col">
    <div class="col-label">{right_label}</div>
    <div class="rephrased">{right_content}</div>
  </div>
</div>"""
