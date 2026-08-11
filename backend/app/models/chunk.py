from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    CHUNK_STATUS,
    CONTENT_TYPE,
    Base,
    ChunkStatus,
    ContentType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.terminology_flag import TerminologyFlag
    from app.models.verification_result import VerificationResult


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One semantic unit of the book: the translation pipeline's work item.

    Neighbouring chunks (n-2..n+2) are *not* duplicated here — they are looked
    up by ``index`` at translation time, so there is a single copy of the text.
    """

    __tablename__ = "chunk"
    __table_args__ = (
        UniqueConstraint("book_id", "index", name="uq_chunk_book_id_index"),
        Index("ix_chunk_book_id_status", "book_id", "status"),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("book.id", ondelete="CASCADE"), nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text)

    # List of per-line format descriptors, exactly the shape documented in
    # README section 2 (line_id/type/font_size/bold/alignment/rtl/page/...).
    format_map: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    content_type: Mapped[ContentType] = mapped_column(
        CONTENT_TYPE, nullable=False, default=ContentType.prose
    )
    status: Mapped[ChunkStatus] = mapped_column(
        CHUNK_STATUS, nullable=False, default=ChunkStatus.pending
    )

    page_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    quality_score: Mapped[float | None] = mapped_column(Float)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_edited: Mapped[bool] = mapped_column(nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)

    book: Mapped[Book] = relationship(back_populates="chunks")
    verification_results: Mapped[list[VerificationResult]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        order_by="VerificationResult.created_at",
    )
    terminology_flags: Mapped[list[TerminologyFlag]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Chunk {self.index} {self.content_type.value} {self.status.value}>"
