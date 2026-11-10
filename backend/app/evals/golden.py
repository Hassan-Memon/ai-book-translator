"""Golden-set loading and validation (contract: docs/evals/golden/SCHEMA.md)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.languages import get_language, normalize_text
from app.models.base import ContentType


class GoldenTerm(BaseModel):
    source: str
    target: str
    variants: list[str] = Field(default_factory=list)
    must_match: bool = True


class GoldenItem(BaseModel):
    id: str
    source_lang: str
    target_lang: str
    content_type: ContentType
    source: str
    reference: str
    alt_references: list[str] = Field(default_factory=list)
    context_before: str | None = None
    context_after: str | None = None
    terms: list[GoldenTerm] = Field(default_factory=list)
    structure: dict[str, object] = Field(default_factory=dict)
    split: Literal["dev", "test"]
    page: int | None = None
    notes: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    adversarial: bool = False
    # Who checked the reference. ``None`` = draft reference, not yet reviewed
    # by a fluent translator; results on such items are labelled as such.
    reviewed_by: str | None = None
    domain: str | None = None

    @property
    def references(self) -> list[str]:
        return [self.reference, *self.alt_references]

    @property
    def pair(self) -> str:
        return f"{self.source_lang}→{self.target_lang}"


class GoldenError(ValueError):
    pass


def load_golden(path: Path) -> list[GoldenItem]:
    """Parse a JSON Lines golden file. Raises GoldenError naming the line."""
    items: list[GoldenItem] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            items.append(GoldenItem.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise GoldenError(f"{path.name}:{lineno}: {exc}") from exc
    return items


def validate_golden(items: list[GoldenItem], *, release: bool = False) -> list[str]:
    """Return a list of problems (empty = valid).

    ``release=True`` adds the size rules a v1 set must meet before its numbers
    go in the README: ≥15 test items and ≥5 items per content type used.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for item in items:
        where = item.id
        if item.id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(item.id)
        for code in (item.source_lang, item.target_lang):
            if get_language(code) is None:
                problems.append(f"{where}: unknown language code {code!r}")
        if item.source_lang == item.target_lang:
            problems.append(f"{where}: source and target language are the same")
        if not item.source.strip():
            problems.append(f"{where}: empty source")
        if not item.reference.strip():
            problems.append(f"{where}: empty reference")
        src = normalize_text(item.source)
        for term in item.terms:
            forms = [term.source, *term.variants]
            if not any(normalize_text(f) in src for f in forms):
                problems.append(f"{where}: term {term.source!r} (or a variant) not in source")
            if not term.target.strip():
                problems.append(f"{where}: term {term.source!r} has an empty target")
        if item.content_type == ContentType.quranic_verse and item.reference != item.source:
            problems.append(f"{where}: quranic_verse reference must equal the source (passthrough)")
    if release:
        tests = sum(1 for i in items if i.split == "test")
        if tests < 15:
            problems.append(f"release set needs ≥15 test items, has {tests}")
        for ctype, n in Counter(i.content_type.value for i in items).items():
            if n < 5:
                problems.append(f"release set needs ≥5 {ctype} items, has {n}")
    return problems
