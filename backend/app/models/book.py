from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    BOOK_STATUS,
    Base,
    BookStatus,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.glossary_term import GlossaryTerm
    from app.models.job import Job


class Book(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "book"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(500))

    source_language: Mapped[str] = mapped_column(String(8), nullable=False, default="ur")
    target_language: Mapped[str] = mapped_column(String(8), nullable=False, default="ar")

    status: Mapped[BookStatus] = mapped_column(
        BOOK_STATUS, nullable=False, default=BookStatus.uploaded
    )

    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source_path: Mapped[str | None] = mapped_column(Text)
    # sha256 of the uploaded bytes; lets the same file be re-uploaded without
    # storing a second 100MB copy.
    source_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True when at least one page needed OCR.
    is_scanned: Mapped[bool] = mapped_column(nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)

    # What the book is about ("Islamic jurisprudence", "19th-century novel",
    # "medical textbook"); steers register and terminology in every prompt.
    domain: Mapped[str | None] = mapped_column(String(100))
    # Free-text style guide from the user, injected verbatim into prompts.
    instructions: Mapped[str | None] = mapped_column(Text)
    # Per-book overrides: quality_profile, sentence_alignment, ... (see
    # app/agents/strategy.py). Empty dict means "use the app settings".
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Engines used, mean OCR quality, escalated pages (from extraction).
    ocr_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="Chunk.index",
    )
    glossary_terms: Mapped[list[GlossaryTerm]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="book", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Book {self.title!r} {self.source_language}->{self.target_language}>"
