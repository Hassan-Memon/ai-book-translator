from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
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
    """A long-running unit of work and the row the worker queue is built on.

    The ``job`` table *is* the queue (ADR-0002): workers claim a queued row
    with ``SELECT ... FOR UPDATE SKIP LOCKED``, heartbeat ``locked_at`` while
    running, and either succeed or get re-queued with a later ``run_after``
    until ``max_attempts`` is exhausted. It doubles as the activity log.
    """

    __tablename__ = "job"

    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("book.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[JobKind] = mapped_column(JOB_KIND, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        JOB_STATUS, nullable=False, default=JobStatus.queued, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    book: Mapped[Book] = relationship(back_populates="jobs")

    @property
    def is_active(self) -> bool:
        return self.status in (JobStatus.queued, JobStatus.running)
