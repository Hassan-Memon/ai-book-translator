from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class VerificationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Output of the verification agent — suggestions only, never a rewrite.

    ``suggestions`` holds a list of
    ``{issue, original_span, suggested, severity}`` objects so the review UI can
    render them as inline diffs the human accepts or rejects individually.
    """

    __tablename__ = "verification_result"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunk.id", ondelete="CASCADE"), nullable=False, index=True
    )

    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    summary: Mapped[str | None] = mapped_column(Text)

    # Which translation attempt this verification belongs to.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    accepted: Mapped[bool] = mapped_column(nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chunk: Mapped[Chunk] = relationship(back_populates="verification_results")
