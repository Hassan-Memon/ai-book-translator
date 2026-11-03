"""Prompt loader, JSON parsing, and the per-chunk graph with the fake provider."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.chunk_graph import build_chunk_graph, glossary_report, run_chunk
from app.agents.schemas import VerificationOutput
from app.core.config import settings
from app.llm.prompts import PromptError, format_glossary, load_prompt
from app.llm.provider import CallContext, FakeProvider, LLMError, LLMOutputError, LLMProvider


def test_prompts_load_with_versions_and_render() -> None:
    for name in ("translation", "verification", "terminology"):
        prompt = load_prompt(name, settings.prompts_dir)
        assert prompt.version >= 1
        assert prompt.placeholders, name
        values = dict.fromkeys(prompt.placeholders, "x")
        rendered = prompt.render(**values)
        assert "{" not in rendered.replace("{{", "")


def test_prompt_render_reports_missing_placeholders() -> None:
    prompt = load_prompt("terminology", settings.prompts_dir)
    with pytest.raises(PromptError):
        prompt.render(glossary="g")


def test_format_glossary_marks_bracket_entries() -> None:
    text = format_glossary(
        [{"original_term": "صلاة", "translation": "نماز", "with_original_in_brackets": True}]
    )
    assert "صلاة → نماز (with_original_in_brackets)" in text
    assert format_glossary([]) == "(no glossary entries yet)"


class _Out(BaseModel):
    a: int


def test_parse_json_strips_fences_and_prose() -> None:
    assert LLMProvider._parse_json('```json\n{"a": 1}\n```', _Out).a == 1
    assert LLMProvider._parse_json('Sure! Here it is: {"a": 2} hope it helps', _Out).a == 2
    with pytest.raises(LLMOutputError):
        LLMProvider._parse_json("not json at all", _Out)


def test_glossary_report_only_counts_terms_present_in_source() -> None:
    glossary = [
        {"original_term": "salah", "translation": "صلاة"},
        {"original_term": "zakat", "translation": "زكاة"},
    ]
    report = glossary_report("about salah", "عن الصلاة", glossary)
    assert report["expected"] == ["salah"]
    assert report["missing"] == []
    assert report["adherence"] == 1.0
    report = glossary_report("about salah", "wrong", glossary)
    assert report["missing"] == ["salah"]
    assert report["adherence"] == 0.0


def _state(source: str) -> dict:
    return {
        "book_id": "00000000-0000-0000-0000-000000000001",
        "chunk_index": 3,
        "source_text": source,
        "content_type": "prose",
        "source_language": "ur",
        "target_language": "ar",
        "context_before": "before",
        "context_after": "after",
        "glossary": [],
    }


async def test_chunk_graph_happy_path_calls_three_nodes() -> None:
    provider = FakeProvider(cfg=settings)
    graph = build_chunk_graph(provider, settings)
    result = await run_chunk(graph, _state("Hello «salah» world"))
    assert result["translation"].startswith("[fake-")
    assert "Hello «salah» world" in result["translation"]
    assert result["verification"]["score"] >= 0.9
    assert [f["term"] for f in result["flags"]] == ["salah"]
    assert [kind for kind, _ in provider.calls] == [
        "TranslationOutput",
        "VerificationOutput",
        "TerminologyOutput",
    ]
    assert result["attempts"] == 1


async def test_chunk_graph_retries_once_when_verification_fails() -> None:
    cfg = settings.model_copy(update={"max_translation_retries": 1, "verification_threshold": 0.8})
    provider = FakeProvider(cfg=cfg)
    graph = build_chunk_graph(provider, cfg)
    # The fake verifier scores 0.3 whenever the translation contains FAIL; the
    # fake translator echoes the source, so this always fails verification.
    result = await run_chunk(graph, _state("this will FAIL"))
    kinds = [kind for kind, _ in provider.calls]
    assert kinds == [
        "TranslationOutput",
        "VerificationOutput",
        "TranslationOutput",
        "VerificationOutput",
        "TerminologyOutput",
    ]
    assert result["attempts"] == 2
    # Retry prompt carried the reviewer's feedback.
    assert "Reviewer feedback" in provider.calls[2][1]
    assert result["verification"]["suggestions"][0]["severity"] == "high"


async def test_chunk_graph_passes_quranic_verses_through() -> None:
    provider = FakeProvider(cfg=settings)
    graph = build_chunk_graph(provider, settings)
    state = _state("﴿verse﴾")
    state["content_type"] = "quranic_verse"
    result = await run_chunk(graph, state)
    assert result["translation"] == "﴿verse﴾"
    assert provider.calls == []
    assert result["verification"]["summary"] == "passthrough"


async def test_chunk_graph_propagates_translation_errors() -> None:
    provider = FakeProvider(cfg=settings)
    provider.fail_next = 1
    graph = build_chunk_graph(provider, settings)
    with pytest.raises(LLMError):
        await run_chunk(graph, _state("x"))


async def test_fake_provider_records_calls(fake_provider: FakeProvider) -> None:
    out = await fake_provider.ainvoke_structured(
        "## Translation under review\nfine", VerificationOutput, CallContext(node="verify")
    )
    assert out.score >= 0.9
