"""The small-model scaffolding, end to end through the real graph.

``ScriptedSmallModel`` impersonates a 4B model (tier "small") and replays
scripted answers, so the tests exercise exactly what a laptop model gets:
sentence alignment, tagged output, the deterministic gate, retries fed with
the gate's findings, and the polish pass guarded by the gate.
"""

from __future__ import annotations

from typing import Any

from app.agents.chunk_graph import build_chunk_graph, run_chunk
from app.agents.schemas import TerminologyOutput, VerificationOutput
from app.core.config import settings
from app.llm.provider import CallContext, LLMProvider

SOURCE = "The sun rose over the hills. The birds sang in the trees. We walked home together."
FULL = "[1] أشرقت الشمس فوق التلال. [2] غنّت الطيور في الأشجار. [3] عدنا إلى البيت معًا."


class ScriptedSmallModel(LLMProvider):
    name = "scripted"
    is_local = False  # keeps candidates at 1 so every call is predictable

    def __init__(self, translations: list[str], polish: str | None = None):
        super().__init__("qwen3:4b", cfg=settings)
        self.translations = list(translations)
        self.polish_answer = polish
        self.calls: list[tuple[str, str]] = []

    def _build_chat_model(self, model: str | None = None, **overrides: Any) -> Any:
        raise NotImplementedError

    def supports_vision(self) -> bool:
        return False

    async def ainvoke_tagged(
        self, prompt: str, tags: list[str], ctx: CallContext
    ) -> dict[str, str]:
        self.calls.append((ctx.node, prompt))
        answer = self.translations.pop(0) if len(self.translations) > 1 else self.translations[0]
        return {"translation": answer}

    async def ainvoke_structured(self, prompt: str, schema: type, ctx: CallContext):
        self.calls.append((ctx.node, prompt))
        if schema is VerificationOutput:
            return VerificationOutput(score=0.95, summary="ok", suggestions=[])
        if schema is TerminologyOutput:
            return TerminologyOutput(flags=[])
        raise AssertionError(f"unexpected schema {schema}")

    async def ainvoke_text(self, prompt: str, ctx: CallContext) -> str:
        self.calls.append((ctx.node, prompt))
        if ctx.node == "polish" and self.polish_answer is not None:
            return self.polish_answer
        return "unexpected"

    def nodes(self) -> list[str]:
        return [node for node, _ in self.calls]


def _state(**over: Any) -> dict[str, Any]:
    state = {
        "book_id": "00000000-0000-0000-0000-00000000abcd",
        "chunk_index": 0,
        "source_text": SOURCE,
        "content_type": "prose",
        "source_language": "en",
        "target_language": "ar",
        "glossary": [],
        "domain": "children's books",
        "instructions": "Simple words.",
    }
    state.update(over)
    return state


async def test_small_model_gets_aligned_prompt_and_retries_a_skipped_sentence() -> None:
    skipped = "[1] أشرقت الشمس فوق التلال. [3] عدنا إلى البيت معًا."
    provider = ScriptedSmallModel(
        [skipped, FULL], polish=FULL.replace("[1] ", "").replace("[2] ", "").replace("[3] ", "")
    )
    graph = build_chunk_graph(provider, settings)
    result = await run_chunk(graph, _state())

    assert result["strategy"]["tier"] == "small"
    assert result["strategy"]["sentence_alignment"] and result["strategy"]["tagged_output"]
    first_prompt = provider.calls[0][1]
    assert "[1] The sun rose over the hills." in first_prompt
    assert "[3] We walked home together." in first_prompt
    assert "Domain of this book: children's books" in first_prompt
    assert "Simple words." in first_prompt

    translate_calls = [p for n, p in provider.calls if n == "translate"]
    assert len(translate_calls) == 2, provider.nodes()
    assert "Translate sentences [2]" in translate_calls[1]
    assert result["missing_sentences"] == []
    assert "غنّت الطيور" in result["translation"]
    assert "[" not in result["translation"], "markers are stripped from the final text"
    assert result["gate_report"]["passed"]


async def test_wrong_language_answer_is_caught_and_retried_with_instruction() -> None:
    english = "[1] The sun rose. [2] The birds sang. [3] We walked home."
    provider = ScriptedSmallModel([english, FULL])
    graph = build_chunk_graph(provider, settings)
    result = await run_chunk(graph, _state())
    translate_calls = [p for n, p in provider.calls if n == "translate"]
    assert len(translate_calls) == 2
    assert "Arabic (Arabic script) only" in translate_calls[1]
    assert result["gate_report"]["passed"]
    assert "أشرقت" in result["translation"]


async def test_polish_is_kept_only_when_the_gate_does_not_get_worse() -> None:
    good = "أشرقت الشمس فوق التلال، وغنّت الطيور في الأشجار، ثم عدنا إلى البيت معًا."
    provider = ScriptedSmallModel([FULL], polish=good)
    result = await run_chunk(build_chunk_graph(provider, settings), _state())
    assert "polish" in provider.nodes()
    assert result["polished"] is True and result["translation"] == good

    provider = ScriptedSmallModel([FULL], polish="Here is a nicer English version of the text.")
    result = await run_chunk(build_chunk_graph(provider, settings), _state(chunk_index=1))
    assert result["polished"] is False
    assert "أشرقت" in result["translation"], "a polish in the wrong language is rejected"


async def test_book_settings_override_profile_to_fast() -> None:
    provider = ScriptedSmallModel([FULL])
    graph = build_chunk_graph(provider, settings, book_settings={"quality_profile": "fast"})
    result = await run_chunk(graph, _state())
    assert result["strategy"]["profile"] == "fast"
    assert provider.nodes() == ["translate"], "fast: no review, no polish, no terminology"
    assert result["verification"] is None


async def test_ocr_repair_runs_only_for_low_quality_chunks() -> None:
    class Repairing(ScriptedSmallModel):
        async def ainvoke_text(self, prompt: str, ctx: CallContext) -> str:
            self.calls.append((ctx.node, prompt))
            if ctx.node == "ocr_cleanup":
                return SOURCE
            return FULL

    noisy = "The sun r0se over the hi1ls. The b1rds sang in the trees. We wa1ked home together."
    provider = Repairing([FULL])
    result = await run_chunk(
        build_chunk_graph(provider, settings, book_settings={"quality_profile": "balanced"}),
        _state(source_text=noisy, ocr_quality=0.5),
    )
    assert provider.nodes()[0] == "ocr_cleanup"
    assert result["source_cleaned"] is True and result["source_work"] == SOURCE
    assert "The sun rose over the hills." in [p for n, p in provider.calls if n == "translate"][0]

    provider = Repairing([FULL])
    await run_chunk(
        build_chunk_graph(provider, settings, book_settings={"quality_profile": "balanced"}),
        _state(chunk_index=2, ocr_quality=0.97),
    )
    assert "ocr_cleanup" not in provider.nodes()


def test_failed_gate_caps_the_score_and_warns_the_reviewer() -> None:
    from app.services.translation import combined_score

    failed = {
        "score": 0.3,
        "passed": False,
        "problems": [
            {"name": "sentences", "severity": "high", "detail": "sentences not translated: [3]"},
            {"name": "paragraphs", "severity": "low", "detail": "2 vs 1 paragraphs"},
        ],
    }
    score, warning = combined_score({"score": 0.95}, failed)
    assert score == 0.3, "a lenient reviewer cannot hide a failed gate"
    assert "sentences not translated: [3]" in warning and "paragraphs" not in warning
    assert combined_score({"score": 0.9}, {"score": 1.0, "passed": True, "problems": []}) == (
        0.9,
        None,
    )
    assert combined_score({}, {"score": 0.85, "passed": True}) == (0.85, None)
    assert combined_score({}, {}) == (None, None)
