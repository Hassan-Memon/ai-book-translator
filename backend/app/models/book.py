from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, Text
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
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True when at least one page needed OCR.
    is_scanned: Mapped[bool] = mapped_column(nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="Chunk.index",
    )
    glossary_terms: Mapped[list[GlossaryTerm]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Book {self.title!r} {self.source_language}->{self.target_language}>"
