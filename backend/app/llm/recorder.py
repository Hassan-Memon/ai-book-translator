"""Writes one ``llm_call`` row per provider invocation, in its own short
session so bookkeeping never shares a transaction with pipeline work."""

from __future__ import annotations

import logging
import uuid

from app.core.database import session_scope
from app.llm.provider import CallRecord
from app.models.llm_call import LlmCall

logger = logging.getLogger(__name__)


async def record_llm_call(record: CallRecord) -> None:
    book_id = record.book_id
    if isinstance(book_id, str):
        try:
            book_id = uuid.UUID(book_id)
        except ValueError:
            book_id = None
    async with session_scope() as session:
        session.add(
            LlmCall(
                book_id=book_id,
                chunk_index=record.chunk_index,
                node=record.node,
                provider=record.provider,
                model=record.model,
                prompt_name=record.prompt_name,
                prompt_version=record.prompt_version,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cost_usd=record.cost_usd,
                latency_ms=record.latency_ms,
                attempts=record.attempts,
                status=record.status,
                error=record.error,
            )
        )
        await session.commit()
