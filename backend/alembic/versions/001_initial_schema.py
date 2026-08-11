"""Initial schema migration — create all tables.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-06 13:45:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial schema."""
    # Enable extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # --- Create Postgres ENUM types (must exist before columns reference them) ---
    book_status = postgresql.ENUM(
        "uploaded", "extracting", "extracted", "translating", "review", "done", "failed",
        name="book_status",
    )
    chunk_status = postgresql.ENUM(
        "pending", "extracted", "translated", "verified", "terminology_reviewed",
        "approved", "failed",
        name="chunk_status",
    )
    content_type = postgresql.ENUM(
        "prose", "heading", "poetry", "quranic_verse", "hadith", "footnote",
        "numbered_list", "margin_note",
        name="content_type",
    )
    glossary_scope = postgresql.ENUM(
        "book", "global",
        name="glossary_scope",
    )
    human_decision = postgresql.ENUM(
        "pending", "accepted", "rejected", "edited",
        name="human_decision",
    )
    job_kind = postgresql.ENUM(
        "extraction", "translation", "export", "reapply_glossary",
        name="job_kind",
    )
    job_status = postgresql.ENUM(
        "queued", "running", "succeeded", "failed",
        name="job_status",
    )

    bind = op.get_bind()
    book_status.create(bind, checkfirst=True)
    chunk_status.create(bind, checkfirst=True)
    content_type.create(bind, checkfirst=True)
    glossary_scope.create(bind, checkfirst=True)
    human_decision.create(bind, checkfirst=True)
    job_kind.create(bind, checkfirst=True)
    job_status.create(bind, checkfirst=True)

    # Create book table
    op.create_table(
        "book",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("author", sa.String(500), nullable=True),
        sa.Column("source_language", sa.String(8), nullable=False, server_default="ur"),
        sa.Column("target_language", sa.String(8), nullable=False, server_default="ar"),
        sa.Column("status", postgresql.ENUM(name="book_status", create_type=False), nullable=False, server_default="uploaded"),
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_scanned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create chunk table
    op.create_table(
        "chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("format_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("content_type", postgresql.ENUM(name="content_type", create_type=False), nullable=False, server_default="prose"),
        sa.Column("status", postgresql.ENUM(name="chunk_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("page_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("human_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "index", name="uq_chunk_book_id_index"),
    )

    # Create glossary_term table
    op.create_table(
        "glossary_term",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_term", sa.String(500), nullable=False),
        sa.Column("translation", sa.String(500), nullable=False),
        sa.Column("with_original_in_brackets", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("human_approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("scope", postgresql.ENUM(name="glossary_scope", create_type=False), nullable=False, server_default="book"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create verification_result table
    op.create_table(
        "verification_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create terminology_flag table
    op.create_table(
        "terminology_flag",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("term", sa.String(500), nullable=False),
        sa.Column("suggested_translation", sa.String(500), nullable=True),
        sa.Column("show_in_brackets", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("human_decision", postgresql.ENUM(name="human_decision", create_type=False), nullable=True),
        sa.Column("final_value", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create job table for background task tracking
    op.create_table(
        "job",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", postgresql.ENUM(name="job_kind", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM(name="job_status", create_type=False), nullable=False, server_default="queued"),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["book_id"], ["book.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index("ix_chunk_book_id_status", "chunk", ["book_id", "status"])
    op.create_index("ix_glossary_term_book_id", "glossary_term", ["book_id"])
    op.create_index("ix_verification_result_chunk_id", "verification_result", ["chunk_id"])
    op.create_index("ix_terminology_flag_chunk_id", "terminology_flag", ["chunk_id"])
    op.create_index("ix_job_book_id", "job", ["book_id"])


def downgrade() -> None:
    """Drop all tables and enum types."""
    op.drop_index("ix_job_book_id")
    op.drop_index("ix_terminology_flag_chunk_id")
    op.drop_index("ix_verification_result_chunk_id")
    op.drop_index("ix_glossary_term_book_id")
    op.drop_index("ix_chunk_book_id_status")

    op.drop_table("job")
    op.drop_table("terminology_flag")
    op.drop_table("verification_result")
    op.drop_table("glossary_term")
    op.drop_table("chunk")
    op.drop_table("book")

    bind = op.get_bind()
    postgresql.ENUM(name="job_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="job_kind").drop(bind, checkfirst=True)
    postgresql.ENUM(name="human_decision").drop(bind, checkfirst=True)
    postgresql.ENUM(name="glossary_scope").drop(bind, checkfirst=True)
    postgresql.ENUM(name="content_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="chunk_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="book_status").drop(bind, checkfirst=True)