"""Request/response schemas for books, chunks, and terminology."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field


class BookCreate(BaseModel):
    title: str
    source_language: str = "ur"
    target_language: str = "ar"


class BookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    author: str | None = None
    source_language: str
    target_language: str
    status: str
    total_chunks: int
    completed_chunks: int
    page_count: int
    is_scanned: bool
    created_at: datetime
    updated_at: datetime


class BookStatusResponse(BookResponse):
    error: str | None = None

    @computed_field
    @property
    def progress_percent(self) -> float:
        if self.total_chunks == 0:
            return 0.0
        return round((self.completed_chunks / self.total_chunks) * 100, 1)


class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    book_id: UUID
    index: int
    raw_text: str
    translated_text: str | None = None
    format_map: list[dict[str, Any]] = []
    content_type: str
    status: str
    page_start: int
    page_end: int
    quality_score: float | None = None
    retry_count: int
    human_edited: bool
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class TerminologyFlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chunk_id: UUID
    term: str
    suggested_translation: str
    category: str
    show_in_brackets: bool
    rationale: str | None = None
    human_decision: str
    final_value: str | None = None
    applied_to_book: bool
    created_at: datetime
