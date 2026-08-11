from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import (
    GLOSSARY_SCOPE,
    TERM_CATEGORY,
    Base,
    GlossaryScope,
    TermCategory,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.book import Book


class GlossaryTerm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A terminology decision. Once recorded, it is injected into every
    subsequent translation prompt so the same term never diverges across the
    book (README section 7).

    ``book_id`` NULL means the term is global and reusable across books.
    """

    __tablename__ = "glossary_term"
    __table_args__ = (
        UniqueConstraint(
            "book_id", "original_term", name="uq_glossary_term_book_id_original_term"
        ),
        # Trigram index backs the non-vector fallback path in glossary_service.
        Index(
            "ix_glossary_term_original_trgm",
            "original_term",
            postgresql_using="gin",
            postgresql_ops={"original_term": "gin_trgm_ops"},
        ),
    )

    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("book.id", ondelete="CASCADE")
    )

    original_term: Mapped[str] = mapped_column(String(300), nullable=False)
    translation: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[TermCategory] = mapped_column(
        TERM_CATEGORY, nullable=False, default=TermCategory.other
    )

    # When true the term renders as "نماز (صلاة)" in the output.
    with_original_in_brackets: Mapped[bool] = mapped_column(nullable=False, default=False)
    human_approved: Mapped[bool] = mapped_column(nullable=False, default=False)
    scope: Mapped[GlossaryScope] = mapped_column(
        GLOSSARY_SCOPE, nullable=False, default=GlossaryScope.book
    )

    # Nullable: providers without an embedding endpoint (ollama, fake) still
    # work, they just fall back to trigram matching.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimensions)
    )
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    book: Mapped[Book | None] = relationship(back_populates="glossary_terms")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<GlossaryTerm {self.original_term!r} -> {self.translation!r}>"
