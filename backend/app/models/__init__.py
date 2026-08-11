"""SQLAlchemy models. Importing this package registers every table on Base."""

from app.models.base import (
    Base,
    BookStatus,
    ChunkStatus,
    ContentType,
    GlossaryScope,
    HumanDecision,
    JobKind,
    JobStatus,
    TermCategory,
)
from app.models.book import Book
from app.models.chunk import Chunk
from app.models.glossary_term import GlossaryTerm
from app.models.job import Job
from app.models.terminology_flag import TerminologyFlag
from app.models.verification_result import VerificationResult

__all__ = [
    "Base",
    "Book",
    "BookStatus",
    "Chunk",
    "ChunkStatus",
    "ContentType",
    "GlossaryScope",
    "GlossaryTerm",
    "HumanDecision",
    "Job",
    "JobKind",
    "JobStatus",
    "TermCategory",
    "TerminologyFlag",
    "VerificationResult",
]
