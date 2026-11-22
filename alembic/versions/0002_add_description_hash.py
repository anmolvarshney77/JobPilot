"""add description_hash to jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("description_hash", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "description_hash")
