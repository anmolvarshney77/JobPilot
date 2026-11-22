"""Initial schema: companies, jobs, applications, outreach, llm_usage, run_log

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("normalized_name", sa.String, nullable=False, unique=True),
        sa.Column("ats_type", sa.String, nullable=True),
        sa.Column("ats_slug", sa.String, nullable=True),
        sa.Column("verified", sa.Boolean, default=False, nullable=False),
        sa.Column("last_fetch_ok", sa.DateTime, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, default=0, nullable=False),
        sa.Column("source_discovered_from", sa.String, nullable=True),
        sa.Column("added_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("external_id", sa.String, nullable=False),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("normalized_title", sa.String, nullable=True),
        sa.Column("location_raw", sa.String, nullable=True),
        sa.Column("countries", sa.JSON, nullable=False),
        sa.Column("remote_type", sa.String, nullable=True),
        sa.Column("remote_allowed_countries", sa.JSON, nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("apply_url", sa.String, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime, nullable=False),
        sa.Column("is_live", sa.Boolean, default=True, nullable=False),
        sa.Column("salary_min", sa.Float, nullable=True),
        sa.Column("salary_max", sa.Float, nullable=True),
        sa.Column("salary_currency", sa.String, nullable=True),
        sa.Column("sponsorship_signal", sa.String, default="unknown", nullable=False),
        sa.Column("required_languages", sa.JSON, nullable=False),
        sa.Column("required_years", sa.Integer, nullable=True),
        sa.Column("match_score", sa.Float, nullable=True),
        sa.Column("match_details", sa.JSON, nullable=True),
        sa.Column("status", sa.String, default="new", nullable=False),
        sa.Column("filter_reason", sa.String, nullable=True),
        sa.Column("dedupe_key", sa.String, nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
        sa.Column("resume_path", sa.String, nullable=True),
        sa.Column("cover_letter_path", sa.String, nullable=True),
        sa.Column("answers", sa.JSON, nullable=False),
        sa.Column("screenshot_path", sa.String, nullable=True),
        sa.Column("outcome", sa.String, default="none", nullable=False),
        sa.Column("outcome_date", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "outreach",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("contact_name", sa.String, nullable=False),
        sa.Column("contact_role", sa.String, nullable=True),
        sa.Column("contact_url", sa.String, nullable=True),
        sa.Column("message_draft", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("reply_status", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("called_at", sa.DateTime, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("purpose", sa.String, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=True),
    )

    op.create_table(
        "run_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("command", sa.String, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("summary", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("run_log")
    op.drop_table("llm_usage")
    op.drop_table("outreach")
    op.drop_table("applications")
    op.drop_table("jobs")
    op.drop_table("companies")
