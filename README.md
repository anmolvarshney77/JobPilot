# JobPilot

A personal job application automation tool for finding, scoring, and preparing applications to software engineering jobs in the US, Europe, and other foreign markets.

> **⚠️ PRIVACY WARNING**
>
> This tool stores personal data — including your resume, contact details, and application history — locally in `jobpilot.db`.
> **Never commit `jobpilot.db` or `.env` to version control.** Both are in `.gitignore` by default. Verify this before every push.

---

## Overview

JobPilot automates the job search pipeline:
1. **Fetch** — scrapes job listings from configured sources
2. **Score** — uses Claude to match jobs to your profile
3. **Prepare** — tailors your resume and drafts cover letters
4. **Apply** — fills and submits applications via Playwright
5. **Outreach** — drafts personalised recruiter/referral messages
6. **Dashboard** — local web UI to track everything

---

## Setup

```bash
# 1. Create and activate a virtualenv
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install the package and dev dependencies
pip install -e ".[dev]"

# 3. Copy and fill in secrets
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY

# 4. Create the database
alembic upgrade head

# 5. Install Playwright browser
playwright install chromium
```

---

## CLI Usage

All commands accept `--dry-run` to preview actions without making changes.

| Command | Description |
|---------|-------------|
| `jobpilot fetch` | Scrape job listings from configured sources |
| `jobpilot score` | Score and filter fetched jobs against your profile |
| `jobpilot prepare` | Tailor resume and draft cover letter for shortlisted jobs |
| `jobpilot apply` | Submit applications via browser automation |
| `jobpilot outreach` | Draft recruiter/referral outreach messages |
| `jobpilot dashboard` | Start the local web dashboard (http://localhost:8000) |
| `jobpilot daily` | Run fetch → score → prepare in sequence |
| `jobpilot stats` | Show run history and LLM usage/cost summary |

---

## Configuration

- `profile.yaml` — your personal profile, skills, salary bands, and fixed application answers
- `config.yaml` — LLM models, budget, scoring thresholds, rate limits
- `.env` — secrets (API keys, database URL)

---

## Security Notes

- PII (phone, email, resume text) is never written to logs.
- Job descriptions are wrapped in `<untrusted_job_posting>` tags before being sent to the LLM to prevent prompt injection.
- The LLM enforces a monthly budget cap to prevent runaway API costs.
