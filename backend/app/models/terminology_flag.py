from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    HUMAN_DECISION,
    TERM_CATEGORY,
    Base,
    HumanDecision,
    TermCategory,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class TerminologyFlag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A term surfaced for human decision (README section 6).

    Flags do not block the pipeline: translation continues while these sit in
    ``pending``. Resolving one with ``applied_to_book`` re-queues every already
    translated chunk containing the term so the decision propagates backwards.
    """

    __tablename__ = "terminology_flag"
    __table_args__ = (Index("ix_terminology_flag_chunk_decision", "chunk_id", "human_decision"),)

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunk.id", ondelete="CASCADE"), nullable=False
    )

    term: Mapped[str] = mapped_column(String(300), nullable=False)
    suggested_translation: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[TermCategory] = mapped_column(
        TERM_CATEGORY, nullable=False, default=TermCategory.other
    )
    show_in_brackets: Mapped[bool] = mapped_column(nullable=False, default=False)
    rationale: Mapped[str | None] = mapped_column(Text)

    human_decision: Mapped[HumanDecision] = mapped_column(
        HUMAN_DECISION, nullable=False, default=HumanDecision.pending
    )
    # What was actually used after the human decided.
    final_value: Mapped[str | None] = mapped_column(String(300))
    applied_to_book: Mapped[bool] = mapped_column(nullable=False, default=False)

    chunk: Mapped[Chunk] = relationship(back_populates="terminology_flags")
