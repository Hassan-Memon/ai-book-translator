"""Runtime settings (BYOK), per-book domain/instructions, OCR quality.

Revision ID: 002_settings_ocr_quality
Revises: 001_initial_schema
Create Date: 2026-11-09

- app_setting: key/value store for settings edited in the UI (provider, model,
  encrypted API keys). See ADR-0012.
- book.domain / book.instructions / book.settings / book.ocr_summary: what the
  book is about, the user's style guide, per-book overrides, OCR report.
- chunk.ocr_quality / chunk.ocr_engine / chunk.source_clean: OCR score shown to
  the reviewer, which engine read it, and the LLM-repaired source text.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_settings_ocr_quality"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.add_column("book", sa.Column("domain", sa.String(100)))
    op.add_column("book", sa.Column("instructions", sa.Text()))
    op.add_column(
        "book", sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}")
    )
    op.add_column("book", sa.Column("ocr_summary", postgresql.JSONB()))
    op.add_column("chunk", sa.Column("ocr_quality", sa.Float()))
    op.add_column("chunk", sa.Column("ocr_engine", sa.String(32)))
    op.add_column("chunk", sa.Column("source_clean", sa.Text()))


def downgrade() -> None:
    op.drop_column("chunk", "source_clean")
    op.drop_column("chunk", "ocr_engine")
    op.drop_column("chunk", "ocr_quality")
    op.drop_column("book", "ocr_summary")
    op.drop_column("book", "settings")
    op.drop_column("book", "instructions")
    op.drop_column("book", "domain")
    op.drop_table("app_setting")
