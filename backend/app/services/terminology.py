"""Terminology flags: the human-in-the-loop decision point."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import HumanDecision
from app.models.chunk import Chunk
from app.models.glossary_term import GlossaryTerm
from app.models.terminology_flag import TerminologyFlag
from app.services import glossary as glossary_service
from app.services.books import NotFound


async def list_flags(
    session: AsyncSession, book_id: uuid.UUID, *, pending_only: bool = True, limit: int = 500
) -> list[tuple[TerminologyFlag, int]]:
    stmt = (
        select(TerminologyFlag, Chunk.index)
        .join(Chunk, TerminologyFlag.chunk_id == Chunk.id)
        .where(Chunk.book_id == book_id)
        .order_by(Chunk.index.asc(), TerminologyFlag.created_at.asc())
        .limit(limit)
    )
    if pending_only:
        stmt = stmt.where(TerminologyFlag.human_decision == HumanDecision.pending)
    return [(flag, idx) for flag, idx in (await session.execute(stmt)).all()]


async def decide(
    session: AsyncSession,
    book_id: uuid.UUID,
    flag_id: uuid.UUID,
    *,
    decision: str,
    final_value: str | None,
    apply_to_book: bool,
) -> tuple[TerminologyFlag, int, GlossaryTerm | None]:
    stmt = (
        select(TerminologyFlag, Chunk.index)
        .join(Chunk, TerminologyFlag.chunk_id == Chunk.id)
        .where(TerminologyFlag.id == flag_id, Chunk.book_id == book_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFound("Flag not found")
    flag, chunk_index = row
    try:
        flag.human_decision = HumanDecision(decision)
    except ValueError as exc:
        raise ValueError("decision must be accepted, rejected or edited") from exc
    if flag.human_decision == HumanDecision.pending:
        raise ValueError("decision must be accepted, rejected or edited")

    term: GlossaryTerm | None = None
    if flag.human_decision == HumanDecision.rejected:
        flag.final_value = None
        flag.applied_to_book = False
    else:
        value = (final_value or flag.suggested_translation).strip()
        if not value:
            raise ValueError("final_value is required")
        flag.final_value = value
        if apply_to_book:
            term = await glossary_service.upsert_term(
                session,
                book_id,
                original_term=flag.term,
                translation=value,
                category=flag.category.value,
                with_original_in_brackets=flag.show_in_brackets,
                notes=flag.rationale,
            )
            flag.applied_to_book = True
            # The same term flagged elsewhere in the book is now decided too.
            siblings = (
                select(TerminologyFlag)
                .join(Chunk, TerminologyFlag.chunk_id == Chunk.id)
                .where(
                    Chunk.book_id == book_id,
                    TerminologyFlag.term == flag.term,
                    TerminologyFlag.human_decision == HumanDecision.pending,
                )
            )
            for sibling in (await session.execute(siblings)).scalars().all():
                sibling.human_decision = flag.human_decision
                sibling.final_value = value
                sibling.applied_to_book = True
    await session.commit()
    return flag, chunk_index, term
