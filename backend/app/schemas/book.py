"""Request/response schemas (see docs/API.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    error: str | None = None
    domain: str | None = None
    instructions: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    ocr_summary: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    percent_translated: float = 0.0
    percent_approved: float = 0.0


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    book_id: UUID
    kind: str
    status: str
    progress: float
    message: str | None = None
    error: str | None = None
    attempts: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LatestExport(BaseModel):
    job_id: str
    file_name: str
    created_at: datetime | None = None


class BookDetailResponse(BookResponse):
    chunk_counts: dict[str, int]
    active_job: JobResponse | None = None
    latest_export: LatestExport | None = None


class SuggestionResponse(BaseModel):
    issue: str = ""
    original_span: str = ""
    suggested: str = ""
    severity: str = "medium"
    status: str = "pending"


class VerificationResponse(BaseModel):
    score: float
    summary: str | None = None
    suggestions: list[SuggestionResponse] = Field(default_factory=list)
    attempt: int = 1


class FlagResponse(BaseModel):
    id: UUID
    chunk_id: UUID
    chunk_index: int
    term: str
    suggested_translation: str
    category: str
    show_in_brackets: bool
    rationale: str | None = None
    human_decision: str
    final_value: str | None = None
    applied_to_book: bool
    created_at: datetime


class ChunkResponse(BaseModel):
    id: UUID
    book_id: UUID
    index: int
    raw_text: str
    translated_text: str | None = None
    format_map: list[dict[str, Any]] = Field(default_factory=list)
    content_type: str
    status: str
    page_start: int
    page_end: int
    quality_score: float | None = None
    retry_count: int
    human_edited: bool
    error: str | None = None
    ocr_quality: float | None = None
    ocr_engine: str | None = None
    source_clean: str | None = None
    verification: VerificationResponse | None = None
    flags: list[FlagResponse] = Field(default_factory=list)
    pending_flags: int = 0
    created_at: datetime
    updated_at: datetime


class GlossaryTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    book_id: UUID | None = None
    original_term: str
    translation: str
    category: str
    with_original_in_brackets: bool
    human_approved: bool
    scope: str
    usage_count: int
    notes: str | None = None
    created_at: datetime


# --- request bodies ---------------------------------------------------------


class TranslateRequest(BaseModel):
    page_range: str | None = None
    only_failed: bool = False


class BookUpdateRequest(BaseModel):
    title: str | None = None
    author: str | None = None
    domain: str | None = None
    instructions: str | None = None
    settings: dict[str, Any] | None = None


class ExportRequest(BaseModel):
    format: str = "docx"


class EditChunkRequest(BaseModel):
    translated_text: str


class SuggestionActionRequest(BaseModel):
    action: str  # accept | reject


class DecideFlagRequest(BaseModel):
    decision: str  # accepted | rejected | edited
    final_value: str | None = None
    apply_to_book: bool = False


class GlossaryUpsertRequest(BaseModel):
    original_term: str
    translation: str
    category: str | None = None
    notes: str | None = None
    with_original_in_brackets: bool | None = None


class AppSettingsResponse(BaseModel):
    llm_provider: str
    model: str
    worker_inline: bool
    version: str
    provider_configured: bool
    provider_label: str = ""
    model_tier: str = "unknown"
    supports_vision: bool = False
    is_local: bool = False
    source: str = "env"  # env | ui


class LlmSettingsRequest(BaseModel):
    """Body of PUT /settings/llm. ``api_key`` omitted/None keeps the stored key;
    empty string clears it."""

    provider: str
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    vision_model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


class LlmTestRequest(LlmSettingsRequest):
    pass
