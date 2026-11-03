"""Glossary use-cases: the per-book terminology memory."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import TermCategory
from app.models.glossary_term import GlossaryTerm


async def list_terms(session: AsyncSession, book_id: uuid.UUID) -> list[GlossaryTerm]:
    stmt = (
        select(GlossaryTerm)
        .where(GlossaryTerm.book_id == book_id)
        .order_by(GlossaryTerm.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def load_for_prompt(session: AsyncSession, book_id: uuid.UUID) -> list[dict[str, Any]]:
    """Glossary snapshot injected into every chunk run."""
    return [
        {
            "original_term": t.original_term,
            "translation": t.translation,
            "with_original_in_brackets": t.with_original_in_brackets,
        }
        for t in await list_terms(session, book_id)
    ]


async def upsert_term(
    session: AsyncSession,
    book_id: uuid.UUID,
    *,
    original_term: str,
    translation: str,
    category: str | None = None,
    notes: str | None = None,
    with_original_in_brackets: bool | None = None,
    human_approved: bool = True,
) -> GlossaryTerm:
    original_term = original_term.strip()
    translation = translation.strip()
    if not original_term or not translation:
        raise ValueError("original_term and translation are required")
    stmt = select(GlossaryTerm).where(
        GlossaryTerm.book_id == book_id, GlossaryTerm.original_term == original_term
    )
    term = (await session.execute(stmt)).scalars().first()
    if term is None:
        term = GlossaryTerm(book_id=book_id, original_term=original_term, translation=translation)
        session.add(term)
    term.translation = translation
    term.human_approved = human_approved
    if category:
        try:
            term.category = TermCategory(category)
        except ValueError:
            term.category = TermCategory.other
    if notes is not None:
        term.notes = notes
    if with_original_in_brackets is not None:
        term.with_original_in_brackets = with_original_in_brackets
    await session.flush()
    return term


async def delete_term(session: AsyncSession, book_id: uuid.UUID, term_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(GlossaryTerm).where(GlossaryTerm.id == term_id, GlossaryTerm.book_id == book_id)
    )
    await session.commit()
    return bool(result.rowcount)


async def find_similar(
    session: AsyncSession, book_id: uuid.UUID, term: str, k: int = 5
) -> list[GlossaryTerm]:
    """Trigram similarity lookup (pg_trgm). Embedding search can replace this
    later without changing callers (ADR-0009)."""
    sim = func.similarity(GlossaryTerm.original_term, term)
    stmt = (
        select(GlossaryTerm)
        .where(GlossaryTerm.book_id == book_id, sim > 0.3)
        .order_by(sim.desc())
        .limit(k)
    )
    return list((await session.execute(stmt)).scalars().all())


def export_terms(terms: list[GlossaryTerm]) -> list[dict[str, Any]]:
    return [
        {
            "original_term": t.original_term,
            "translation": t.translation,
            "category": t.category.value,
            "with_original_in_brackets": t.with_original_in_brackets,
            "notes": t.notes,
        }
        for t in terms
    ]


def parse_import(filename: str, data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        items = json.loads(text)
        if not isinstance(items, list):
            raise ValueError("JSON import must be a list of objects")
        return [dict(i) for i in items]
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


async def import_terms(
    session: AsyncSession, book_id: uuid.UUID, items: list[dict[str, Any]]
) -> int:
    n = 0
    for item in items:
        src = str(item.get("original_term") or "").strip()
        tgt = str(item.get("translation") or "").strip()
        if not src or not tgt:
            continue
        raw_flag = item.get("with_original_in_brackets")
        flag = None
        if raw_flag is not None:
            flag = str(raw_flag).strip().lower() in ("1", "true", "yes")
        await upsert_term(
            session,
            book_id,
            original_term=src,
            translation=tgt,
            category=item.get("category"),
            notes=item.get("notes"),
            with_original_in_brackets=flag,
        )
        n += 1
    await session.commit()
    return n
