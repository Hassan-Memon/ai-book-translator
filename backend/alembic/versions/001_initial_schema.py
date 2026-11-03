"""Initial schema — matches app/models exactly.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-11-02

Written against a fresh database (translatebook_v2). The previous 001 drifted
from the models (different job/verification/terminology columns), so this file
was regenerated from the ORM metadata instead of patched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

ENUMS = {
    "book_status": ["uploaded", "extracting", "extracted", "translating", "review", "done", "failed"],
    "chunk_status": [
        "pending", "extracted", "translated", "verified", "terminology_reviewed",
        "approved", "failed",
    ],
    "content_type": [
        "prose", "heading", "poetry", "quranic_verse", "hadith", "footnote",
        "numbered_list", "margin_note",
    ],
    "glossary_scope": ["book", "global"],
    "term_category": ["religious", "technical", "scholarly", "name", "other"],
    "human_decision": ["pending", "accepted", "rejected", "edited"],
    "job_kind": ["extraction", "translation", "export", "reapply_glossary"],
    "job_status": ["queued", "running", "succeeded", "failed"],
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    ts = sa.DateTime(timezone=True)
    uuid = postgresql.UUID(as_uuid=True)

    op.create_table(
        "book",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("author", sa.String(500)),
        sa.Column("source_language", sa.String(8), nullable=False, server_default="ur"),
        sa.Column("target_language", sa.String(8), nullable=False, server_default="ar"),
        sa.Column("status", _enum("book_status"), nullable=False, server_default="uploaded"),
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_path", sa.Text()),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_scanned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_book_source_sha256", "book", ["source_sha256"])

    op.create_table(
        "chunk",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("book_id", uuid, sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text()),
        sa.Column("format_map", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("content_type", _enum("content_type"), nullable=False, server_default="prose"),
        sa.Column("status", _enum("chunk_status"), nullable=False, server_default="pending"),
        sa.Column("page_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_score", sa.Float()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("human_edited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("book_id", "index", name="uq_chunk_book_id_index"),
    )
    op.create_index("ix_chunk_book_id_status", "chunk", ["book_id", "status"])

    op.create_table(
        "glossary_term",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("book_id", uuid, sa.ForeignKey("book.id", ondelete="CASCADE")),
        sa.Column("original_term", sa.String(300), nullable=False),
        sa.Column("translation", sa.String(300), nullable=False),
        sa.Column("category", _enum("term_category"), nullable=False, server_default="other"),
        sa.Column(
            "with_original_in_brackets", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("human_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope", _enum("glossary_scope"), nullable=False, server_default="book"),
        sa.Column("embedding", Vector(1536)),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "book_id", "original_term", name="uq_glossary_term_book_id_original_term"
        ),
    )
    op.create_index("ix_glossary_term_book_id", "glossary_term", ["book_id"])
    op.create_index(
        "ix_glossary_term_original_trgm",
        "glossary_term",
        ["original_term"],
        postgresql_using="gin",
        postgresql_ops={"original_term": "gin_trgm_ops"},
    )

    op.create_table(
        "verification_result",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("chunk_id", uuid, sa.ForeignKey("chunk.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggestions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text()),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied_at", ts),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_verification_result_chunk_id", "verification_result", ["chunk_id"])

    op.create_table(
        "terminology_flag",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("chunk_id", uuid, sa.ForeignKey("chunk.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term", sa.String(300), nullable=False),
        sa.Column("suggested_translation", sa.String(300), nullable=False),
        sa.Column("category", _enum("term_category"), nullable=False, server_default="other"),
        sa.Column("show_in_brackets", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rationale", sa.Text()),
        sa.Column(
            "human_decision", _enum("human_decision"), nullable=False, server_default="pending"
        ),
        sa.Column("final_value", sa.String(300)),
        sa.Column("applied_to_book", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_terminology_flag_chunk_decision", "terminology_flag", ["chunk_id", "human_decision"]
    )

    op.create_table(
        "job",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("book_id", uuid, sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", _enum("job_kind"), nullable=False),
        sa.Column("status", _enum("job_status"), nullable=False, server_default="queued"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("run_after", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("locked_by", sa.String(100)),
        sa.Column("locked_at", ts),
        sa.Column("started_at", ts),
        sa.Column("finished_at", ts),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_book_id", "job", ["book_id"])
    op.create_index("ix_job_status", "job", ["status"])

    op.create_table(
        "llm_call",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("book_id", uuid, sa.ForeignKey("book.id", ondelete="CASCADE")),
        sa.Column("chunk_index", sa.Integer()),
        sa.Column("node", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_name", sa.String(60)),
        sa.Column("prompt_version", sa.Integer()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_llm_call_book_id", "llm_call", ["book_id"])


def downgrade() -> None:
    for table in (
        "llm_call", "job", "terminology_flag", "verification_result", "glossary_term",
        "chunk", "book",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
