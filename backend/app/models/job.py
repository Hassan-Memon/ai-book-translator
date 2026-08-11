from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    JOB_KIND,
    JOB_STATUS,
    Base,
    JobKind,
    JobStatus,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.book import Book


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A long-running background unit of work.

    Doubles as the activity log behind README section 12 — every extraction,
    translation run and export leaves a row here with its progress.
    """

    __tablename__ = "job"

    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("book.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[JobKind] = mapped_column(JOB_KIND, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        JOB_STATUS, nullable=False, default=JobStatus.queued
    )

    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    book: Mapped[Book] = relationship(back_populates="jobs")
