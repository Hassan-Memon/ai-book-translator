"""Typed LLM outputs. Every node asks the provider for one of these models;
a response that cannot be parsed into them is an error, never an empty
"no issues" (ADR-0005)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TranslationOutput(BaseModel):
    translation: str = Field(description="Translation of the target chunk only.")
    notes: list[str] = Field(default_factory=list, description="Uncertain terms or ambiguities.")


class Suggestion(BaseModel):
    issue: str = Field(description="What is wrong, in one sentence.")
    original_span: str = Field(description="Exact text copied from the translation.")
    suggested: str = Field(description="Replacement text for the span.")
    severity: Literal["low", "medium", "high"] = "medium"


class VerificationOutput(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="Overall faithfulness confidence.")
    summary: str = Field(default="", description="One-line overall verdict.")
    suggestions: list[Suggestion] = Field(default_factory=list)


class TermFlag(BaseModel):
    term: str
    suggested_translation: str
    category: Literal["religious", "technical", "scholarly", "name", "other"] = "other"
    show_in_brackets: bool = False
    rationale: str = ""


class TerminologyOutput(BaseModel):
    flags: list[TermFlag] = Field(default_factory=list)
