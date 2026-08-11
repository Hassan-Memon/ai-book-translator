"""Glossary memory helpers — load and persist per-book terminology decisions."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.glossary_term import GlossaryTerm

logger = logging.getLogger(__name__)


async def load_book_glossary(book_id: uuid.UUID | str, session: AsyncSession) -> dict[str, str]:
    """Return {original_term: translation} for every approved term in this book.

    The dictionary is injected into every translation prompt so the LLM
    uses consistent terminology across the entire book.
    """
    stmt = select(GlossaryTerm).where(GlossaryTerm.book_id == book_id)
    result = await session.execute(stmt)
    terms = result.scalars().all()
    glossary = {t.original_term: t.translation for t in terms}
    logger.debug(f"Loaded {len(glossary)} glossary entries for book {book_id}")
    return glossary


async def upsert_glossary_term(
    book_id: uuid.UUID | str,
    original_term: str,
    translation: str,
    human_approved: bool = False,
    session: AsyncSession = None,
) -> GlossaryTerm:
    """Add a new glossary term or update the translation if the term already exists."""
    stmt = select(GlossaryTerm).where(
        GlossaryTerm.book_id == book_id,
        GlossaryTerm.original_term == original_term,
    )
    result = await session.execute(stmt)
    term = result.scalars().first()

    if term:
        term.translation = translation
        term.human_approved = human_approved
    else:
        term = GlossaryTerm(
            book_id=book_id,
            original_term=original_term,
            translation=translation,
            human_approved=human_approved,
        )
        session.add(term)

    return term
