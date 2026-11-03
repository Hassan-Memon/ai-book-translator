from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class LlmCall(UUIDPrimaryKeyMixin, Base):
    """One row per LLM invocation: the raw material for the cost table and
    for comparing prompt versions in the eval harness."""

    __tablename__ = "llm_call"

    book_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("book.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_name: Mapped[str | None] = mapped_column(String(60))
    prompt_version: Mapped[int | None] = mapped_column(Integer)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
