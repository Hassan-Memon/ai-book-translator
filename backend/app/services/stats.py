"""Cost/latency aggregates from the llm_call ledger."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_call import LlmCall


async def book_stats(session: AsyncSession, book_id: uuid.UUID) -> dict[str, Any]:
    totals = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LlmCall.input_tokens), 0),
                func.coalesce(func.sum(LlmCall.output_tokens), 0),
                func.coalesce(func.sum(LlmCall.cost_usd), 0.0),
                func.avg(LlmCall.latency_ms),
            ).where(LlmCall.book_id == book_id)
        )
    ).one()
    by_model = (
        await session.execute(
            select(
                LlmCall.model,
                func.count(),
                func.coalesce(func.sum(LlmCall.input_tokens), 0),
                func.coalesce(func.sum(LlmCall.output_tokens), 0),
                func.coalesce(func.sum(LlmCall.cost_usd), 0.0),
            )
            .where(LlmCall.book_id == book_id)
            .group_by(LlmCall.model)
            .order_by(func.count().desc())
        )
    ).all()
    return {
        "llm_calls": int(totals[0]),
        "input_tokens": int(totals[1]),
        "output_tokens": int(totals[2]),
        "cost_usd": round(float(totals[3]), 4),
        "avg_latency_ms": round(float(totals[4]), 1) if totals[4] is not None else None,
        "by_model": [
            {
                "model": m,
                "calls": int(c),
                "input_tokens": int(i),
                "output_tokens": int(o),
                "cost_usd": round(float(cost), 4),
            }
            for m, c, i, o, cost in by_model
        ],
    }
