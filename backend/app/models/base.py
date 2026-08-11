"""Declarative base, shared column types and enums."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit naming convention keeps Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BookStatus(StrEnum):
    uploaded = "uploaded"
    extracting = "extracting"
    extracted = "extracted"
    translating = "translating"
    review = "review"
    done = "done"
    failed = "failed"


class ChunkStatus(StrEnum):
    """Lifecycle from README section 8.

    ``extracted`` is the queue state the translation runner picks up, which is
    what makes resumability a plain query rather than extra machinery.
    """

    pending = "pending"
    extracted = "extracted"
    translated = "translated"
    verified = "verified"
    terminology_reviewed = "terminology_reviewed"
    approved = "approved"
    failed = "failed"


class ContentType(StrEnum):
    prose = "prose"
    heading = "heading"
    poetry = "poetry"
    quranic_verse = "quranic_verse"
    hadith = "hadith"
    footnote = "footnote"
    numbered_list = "numbered_list"
    margin_note = "margin_note"


class GlossaryScope(StrEnum):
    book = "book"
    global_ = "global"


class TermCategory(StrEnum):
    religious = "religious"
    technical = "technical"
    scholarly = "scholarly"
    name = "name"
    other = "other"


class HumanDecision(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    edited = "edited"


class JobKind(StrEnum):
    extraction = "extraction"
    translation = "translation"
    export = "export"
    reapply_glossary = "reapply_glossary"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


# Bind each SQL enum type to the shared metadata once. TermCategory in
# particular is referenced by two tables, and declaring Enum() inline in both
# would emit CREATE TYPE twice; sharing the instance emits it exactly once.
BOOK_STATUS = Enum(BookStatus, name="book_status", metadata=Base.metadata)
CHUNK_STATUS = Enum(ChunkStatus, name="chunk_status", metadata=Base.metadata)
CONTENT_TYPE = Enum(ContentType, name="content_type", metadata=Base.metadata)
GLOSSARY_SCOPE = Enum(
    GlossaryScope,
    name="glossary_scope",
    metadata=Base.metadata,
    # GlossaryScope.global_ would otherwise be stored as "global_".
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)
TERM_CATEGORY = Enum(TermCategory, name="term_category", metadata=Base.metadata)
HUMAN_DECISION = Enum(HumanDecision, name="human_decision", metadata=Base.metadata)
JOB_KIND = Enum(JobKind, name="job_kind", metadata=Base.metadata)
JOB_STATUS = Enum(JobStatus, name="job_status", metadata=Base.metadata)
