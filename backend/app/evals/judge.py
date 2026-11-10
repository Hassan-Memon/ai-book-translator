"""LLM-as-judge for the evaluation harness (ADR-0007, ADR-0014).

Reference-based, absolute 1–5 scoring on five axes, each with a one-sentence
rationale. The judge should come from a different model family than the
translator to limit self-preference; :func:`same_family` warns when it does
not. :func:`calibrate` checks the judge can tell a reference from a
deliberately degraded copy before its numbers are trusted.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings, settings
from app.llm.prompts import language_name, load_prompt
from app.llm.provider import CallContext, LLMProvider

AXES = ("adequacy", "fluency", "omissions", "additions", "terminology")


class JudgeOutput(BaseModel):
    adequacy: int = Field(ge=1, le=5)
    adequacy_why: str = ""
    fluency: int = Field(ge=1, le=5)
    fluency_why: str = ""
    omissions: int = Field(ge=1, le=5)
    omissions_why: str = ""
    additions: int = Field(ge=1, le=5)
    additions_why: str = ""
    terminology: int = Field(ge=1, le=5)
    terminology_why: str = ""

    @property
    def mean(self) -> float:
        return round(sum(getattr(self, a) for a in AXES) / len(AXES), 3)


_FAMILIES = (
    ("openai", r"\bgpt|\bo[134]\b|o[134]-|openai/"),
    ("anthropic", r"claude"),
    ("google", r"gemini|gemma"),
    ("qwen", r"qwen|qwq"),
    ("meta", r"llama"),
    ("mistral", r"mistral|mixtral|ministral|codestral"),
    ("cohere", r"aya|command"),
    ("microsoft", r"\bphi"),
    ("deepseek", r"deepseek"),
)


def model_family(model: str) -> str:
    name = (model or "").lower()
    for family, pattern in _FAMILIES:
        if re.search(pattern, name):
            return family
    return name.split(":")[0].split("/")[-1] or "unknown"


def same_family(a: str, b: str) -> bool:
    return model_family(a) == model_family(b)


def _terms_block(terms: list[dict[str, Any]]) -> str:
    rows = [f"- {t['source']} → {t['target']}" for t in terms if t.get("must_match", True)]
    return "\n".join(rows) or "(none)"


async def judge(
    provider: LLMProvider,
    *,
    source: str,
    reference: str,
    candidate: str,
    source_lang: str,
    target_lang: str,
    terms: list[dict[str, Any]] | None = None,
    item_id: str | None = None,
    cfg: Settings | None = None,
) -> JudgeOutput:
    cfg = cfg or settings
    prompt_def = load_prompt("judge", cfg.prompts_dir)
    prompt = prompt_def.render(
        source_language_name=language_name(source_lang),
        target_language_name=language_name(target_lang),
        terms=_terms_block(terms or []),
        source=source,
        reference=reference,
        candidate=candidate or "(empty)",
    )
    ctx = CallContext(
        node="judge",
        book_id=f"eval:{item_id}" if item_id else None,
        prompt_name=prompt_def.name,
        prompt_version=prompt_def.version,
    )
    return await provider.ainvoke_structured(prompt, JudgeOutput, ctx)


def degrade(reference: str, terms: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """A deliberately worse copy of the reference and the axis it should lose
    on: drop the last sentence when there are several (omissions), otherwise
    swap a decided term for a wrong word (terminology), otherwise truncate."""
    parts = [p for p in re.split(r"(?<=[.!?؟۔।])\s+", reference.strip()) if p]
    if len(parts) >= 2:
        return " ".join(parts[:-1]), "omissions"
    for term in terms or []:
        target = term.get("target", "")
        if target and target in reference:
            return reference.replace(target, "X" * max(2, len(target) // 2)), "terminology"
    half = max(1, len(reference) // 2)
    return reference[:half], "omissions"


async def calibrate(
    provider: LLMProvider, items: list[Any], cfg: Settings | None = None
) -> dict[str, Any]:
    """Judge each item's reference against a degraded copy. The judge passes
    an item when the degraded copy scores lower on the expected axis (or
    lower overall). Returns the agreement rate and per-item detail."""
    rows: list[dict[str, Any]] = []
    for item in items:
        terms = [t.model_dump() for t in item.terms]
        bad, axis = degrade(item.reference, terms)
        common = {
            "source": item.source,
            "reference": item.reference,
            "source_lang": item.source_lang,
            "target_lang": item.target_lang,
            "terms": terms,
            "item_id": item.id,
            "cfg": cfg,
        }
        good_score = await judge(provider, candidate=item.reference, **common)
        bad_score = await judge(provider, candidate=bad, **common)
        ok = (
            getattr(bad_score, axis) < getattr(good_score, axis) or bad_score.mean < good_score.mean
        )
        rows.append(
            {
                "id": item.id,
                "axis": axis,
                "reference": good_score.model_dump(),
                "degraded": bad_score.model_dump(),
                "agrees": ok,
            }
        )
    agreement = round(sum(r["agrees"] for r in rows) / len(rows), 3) if rows else None
    return {"agreement": agreement, "items": rows}
