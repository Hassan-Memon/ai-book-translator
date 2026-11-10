"""The per-chunk LangGraph workflow (ADR-0006; strategy: ADR-0013).

    prepare ─► clean_source? ─► translate ─► gate ─┬─ fail, retries left ─► retry ─┐
                                      ▲            └─ pass ─► verify ─┬─ low ──────┘
                                      │                               └─ ok ─► polish?
                                      └── retry ◄─────────────────────┘   └─► terminology ─► END

One graph invocation = one chunk. The worker loops over chunks and runs this
with ``thread_id = f"{book_id}:{chunk_index}"``; with a checkpointer
(app/agents/checkpoint.py) a chunk that failed mid-graph resumes at the
failed node on its next attempt.

What makes a 4B local model usable here is not the prompt, it is the
scaffolding chosen by :mod:`app.agents.strategy`:

* ``clean_source``: repair OCR noise before translating (text models only);
* sentence alignment: numbered sentences in, numbered sentences out, so a
  dropped sentence is a set difference, not a judgement;
* ``gate``: deterministic checks (script, length, structure, glossary,
  alignment) that cost nothing and feed precise instructions to the retry;
* candidates: sample N translations, keep the one the gate likes best;
* ``verify``: the LLM reviewer, told what the gate already found;
* ``polish``: a fluency pass accepted only if the gate does not get worse;
* translation memory: approved chunks of the same book as examples.

Persistence to the ``chunk`` row happens in the service layer after the graph
returns, which keeps the graph pure and unit-testable with the FakeProvider.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.agents import strategy as strategy_mod
from app.agents.quality import GateResult, clean_model_output, gate
from app.agents.schemas import (
    Suggestion,
    TerminologyOutput,
    TranslationOutput,
    VerificationOutput,
)
from app.agents.segmenter import join_numbered, number_sentences, parse_numbered, split_sentences
from app.core.config import Settings, settings
from app.core.languages import script_ratio
from app.llm.prompts import format_glossary, language_name, load_prompt
from app.llm.provider import CallContext, LLMProvider

logger = logging.getLogger(__name__)

DEFAULT_DOMAIN = "general literature and non-fiction"


class ChunkState(TypedDict, total=False):
    # inputs
    book_id: str
    chunk_index: int
    source_text: str
    content_type: str
    source_language: str
    target_language: str
    context_before: str
    context_after: str
    glossary: list[dict[str, Any]]  # [{original_term, translation, with_original_in_brackets}]
    domain: str
    instructions: str
    examples: list[dict[str, str]]  # [{source, translation}] approved chunks of this book
    ocr_quality: float | None
    # working state
    source_work: str  # text actually translated (raw or OCR-repaired)
    source_cleaned: bool
    sentences: list[str]  # when sentence alignment is on
    translation: str
    notes: list[str]
    gate_report: dict[str, Any] | None
    missing_sentences: list[int]
    verification: dict[str, Any] | None  # VerificationOutput.model_dump()
    attempts: int
    retry_hints: str
    passthrough: bool
    polished: bool
    # outputs
    flags: list[dict[str, Any]]
    glossary_report: dict[str, Any]
    strategy: dict[str, Any]
    errors: list[str]


def _ctx(state: ChunkState, node: str, prompt: Any) -> CallContext:
    return CallContext(
        node=node,
        book_id=state.get("book_id"),
        chunk_index=state.get("chunk_index"),
        prompt_name=prompt.name,
        prompt_version=prompt.version,
    )


def glossary_report(
    source: str, translation: str, glossary: list[dict[str, Any]]
) -> dict[str, Any]:
    """Deterministic terminology check: for every glossary term that occurs in
    the *source*, is its decided rendering present in the translation?"""
    expected: list[str] = []
    missing: list[str] = []
    for entry in glossary:
        src = str(entry.get("original_term", "")).strip()
        tgt = str(entry.get("translation", "")).strip()
        if not src or not tgt or src not in source:
            continue
        expected.append(src)
        if tgt not in translation:
            missing.append(src)
    adherence = 1.0 if not expected else round(1 - len(missing) / len(expected), 3)
    return {"expected": expected, "missing": missing, "adherence": adherence}


def _instructions_block(state: ChunkState) -> str:
    text = (state.get("instructions") or "").strip()
    return f"## Instructions from the editor (follow them)\n{text}\n" if text else ""


def _examples_block(state: ChunkState, limit: int) -> str:
    examples = (state.get("examples") or [])[:limit]
    if not examples:
        return ""
    lines = ["## Approved translations from this book (match their style and terminology exactly)"]
    for i, ex in enumerate(examples, 1):
        src = str(ex.get("source", "")).strip()[:700]
        tgt = str(ex.get("translation", "")).strip()[:700]
        if not src or not tgt:
            continue
        lines.append(f"### Example {i}\nSource:\n{src}\nTranslation:\n{tgt}")
    return "\n".join(lines) + "\n" if len(lines) > 1 else ""


def _ocr_guidance(state: ChunkState) -> str:
    q = state.get("ocr_quality")
    if q is None or q >= 0.9:
        return ""
    return (
        "7. The source comes from OCR of a scanned page and may contain misread letters, "
        "merged or split words and stray symbols. Translate the text the author evidently "
        "wrote; do not reproduce OCR noise and do not comment on it."
    )


def _gate(state: ChunkState, translation: str) -> GateResult:
    return gate(
        state.get("source_work") or state["source_text"],
        translation,
        source_language=state["source_language"],
        target_language=state["target_language"],
        glossary=state.get("glossary", []),
        missing_sentences=state.get("missing_sentences") or None,
    )


def build_chunk_graph(
    provider: LLMProvider,
    cfg: Settings | None = None,
    checkpointer: Any | None = None,
    book_settings: dict[str, Any] | None = None,
) -> Any:
    """Compile the per-chunk graph bound to a provider. Compile once per job."""
    cfg = cfg or settings
    strat = strategy_mod.resolve(
        provider.model,
        cfg=cfg,
        book_settings=book_settings,
        is_local=getattr(provider, "is_local", False),
        fake=provider.name == "fake",
    )
    logger.info("agent strategy for %s: %s", provider.model, strat.as_dict())
    translation_prompt = load_prompt("translation", cfg.prompts_dir)
    verification_prompt = load_prompt("verification", cfg.prompts_dir)
    terminology_prompt = load_prompt("terminology", cfg.prompts_dir)
    cleanup_prompt = load_prompt("ocr_cleanup", cfg.prompts_dir)
    polish_prompt = load_prompt("polish", cfg.prompts_dir)

    # ------------------------------------------------------------------ nodes

    async def prepare(state: ChunkState) -> dict[str, Any]:
        passthrough = state.get("content_type") in set(cfg.passthrough_content_types)
        return {
            "attempts": 0,
            "retry_hints": "",
            "errors": [],
            "flags": [],
            "notes": [],
            "verification": None,
            "gate_report": None,
            "missing_sentences": [],
            "sentences": [],
            "passthrough": passthrough,
            "polished": False,
            "source_work": state["source_text"],
            "source_cleaned": False,
            "translation": state["source_text"] if passthrough else "",
            "strategy": strat.as_dict(),
        }

    def needs_cleanup(state: ChunkState) -> bool:
        if state.get("passthrough"):
            return False
        policy = strat.ocr_cleanup
        q = state.get("ocr_quality")
        if policy == "off" or q is None:
            return False
        if policy == "always":
            return True
        return float(q) < strat.ocr_cleanup_threshold

    async def clean_source(state: ChunkState) -> dict[str, Any]:
        if not needs_cleanup(state):
            return {}
        prompt = cleanup_prompt.render(
            source_language_name=language_name(state["source_language"]),
            source_text=state["source_text"],
        )
        try:
            repaired = clean_model_output(
                await provider.ainvoke_text(prompt, _ctx(state, "ocr_cleanup", cleanup_prompt))
            )
        except Exception as exc:
            logger.warning("chunk %s: OCR cleanup failed: %s", state.get("chunk_index"), exc)
            return {"errors": list(state.get("errors", [])) + [f"ocr_cleanup: {exc}"]}
        src = state["source_text"]
        ratio = len(repaired) / max(1, len(src))
        same_script = script_ratio(repaired, state["source_language"]) >= 0.6
        if repaired and 0.6 <= ratio <= 1.4 and same_script:
            return {"source_work": repaired, "source_cleaned": True}
        logger.info("chunk %s: OCR cleanup rejected (ratio %.2f)", state.get("chunk_index"), ratio)
        return {}

    def _render_translation_prompt(state: ChunkState) -> tuple[str, list[str]]:
        source = state.get("source_work") or state["source_text"]
        sentences: list[str] = []
        alignment_rules = ""
        target = source
        if strat.sentence_alignment:
            sentences = split_sentences(source, state["source_language"])
            if len(sentences) >= 2:
                target = number_sentences(sentences)
                alignment_rules = (
                    "8. The target chunk is given as numbered sentences [1] … "
                    f"[{len(sentences)}]. Return the translation as the same numbered list: "
                    "every number exactly once, in order, each followed by the translation of "
                    "that sentence only. Never merge, drop or renumber sentences."
                )
            else:
                sentences = []
        prompt = translation_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            domain=state.get("domain") or DEFAULT_DOMAIN,
            instructions=_instructions_block(state),
            ocr_guidance=_ocr_guidance(state),
            alignment_rules=alignment_rules,
            glossary=format_glossary(state.get("glossary", [])),
            examples=_examples_block(state, strat.memory_examples),
            retry_hints=state.get("retry_hints", ""),
            context_before=state.get("context_before") or "(start of book)",
            target_chunk=target,
            context_after=state.get("context_after") or "(end of book)",
        )
        return prompt, sentences

    async def _one_translation(
        state: ChunkState, prompt: str, sentences: list[str]
    ) -> tuple[str, list[str], list[int], GateResult]:
        ctx = _ctx(state, "translate", translation_prompt)
        notes: list[str] = []
        if strat.tagged_output:
            found = await provider.ainvoke_tagged(prompt, ["translation", "notes"], ctx)
            raw = found.get("translation", "")
            if found.get("notes"):
                notes = [n.strip("-• ").strip() for n in found["notes"].splitlines() if n.strip()]
        else:
            out: TranslationOutput = await provider.ainvoke_structured(
                prompt, TranslationOutput, ctx
            )
            raw, notes = out.translation, list(out.notes)
        translation = clean_model_output(raw)
        missing: list[int] = []
        if sentences:
            by_number, problems = parse_numbered(translation, len(sentences))
            if by_number:
                missing = [n for n in range(1, len(sentences) + 1) if not by_number.get(n)]
                translation = join_numbered(by_number, len(sentences), sentences)
            else:
                # No markers at all: keep the text, let the gate judge it.
                logger.info("chunk %s: %s", state.get("chunk_index"), "; ".join(problems))
        if not translation.strip():
            raise ValueError("empty translation returned")
        probe = dict(state)
        probe["missing_sentences"] = missing
        report = _gate(probe, translation)  # type: ignore[arg-type]
        return translation, notes, missing, report

    async def translate(state: ChunkState) -> dict[str, Any]:
        if state.get("passthrough"):
            return {}
        prompt, sentences = _render_translation_prompt(state)
        n = max(1, strat.candidates if strat.gate else 1)
        if n == 1:
            translation, notes, missing, report = await _one_translation(state, prompt, sentences)
        else:
            results = await asyncio.gather(
                *(_one_translation(state, prompt, sentences) for _ in range(n)),
                return_exceptions=True,
            )
            ok = [r for r in results if not isinstance(r, BaseException)]
            if not ok:
                raise results[0]  # type: ignore[misc]
            translation, notes, missing, report = max(ok, key=lambda r: r[3].score)
            logger.info(
                "chunk %s: picked best of %d candidates (gate %.2f)",
                state.get("chunk_index"),
                len(ok),
                report.score,
            )
        return {
            "translation": translation,
            "notes": list(state.get("notes", [])) + notes,
            "sentences": sentences,
            "missing_sentences": missing,
            "gate_report": report.as_dict() if strat.gate else None,
            "attempts": state.get("attempts", 0) + 1,
        }

    async def gate_node(state: ChunkState) -> dict[str, Any]:
        if state.get("passthrough") or not strat.gate:
            return {"gate_report": None}
        report = _gate(state, state["translation"])
        return {"gate_report": report.as_dict()}

    def route_after_gate(state: ChunkState) -> Literal["retry", "verify", "polish", "terminology"]:
        if state.get("passthrough"):
            return "verify"  # records the passthrough verification without an LLM call
        report = state.get("gate_report") or {}
        if (
            strat.gate
            and report
            and not report.get("passed", True)
            and state.get("attempts", 0) <= strat.max_retries
        ):
            return "retry"
        if strat.verify:
            return "verify"
        return "polish" if strat.polish else "terminology"

    async def verify(state: ChunkState) -> dict[str, Any]:
        if state.get("passthrough"):
            return {"verification": {"score": 1.0, "summary": "passthrough", "suggestions": []}}
        report = state.get("gate_report") or {}
        problems = report.get("problems") or []
        findings = (
            "; ".join(f"{p['name']} ({p['severity']}): {p['detail']}" for p in problems)
            if problems
            else "none"
        )
        prompt = verification_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            domain=state.get("domain") or DEFAULT_DOMAIN,
            instructions=_instructions_block(state),
            automatic_findings=findings,
            glossary=format_glossary(state.get("glossary", [])),
            context_before=state.get("context_before") or "(start of book)",
            target_chunk=state.get("source_work") or state["source_text"],
            context_after=state.get("context_after") or "(end of book)",
            translation=state["translation"],
        )
        out: VerificationOutput = await provider.ainvoke_structured(
            prompt, VerificationOutput, _ctx(state, "verify", verification_prompt)
        )
        return {"verification": out.model_dump()}

    def route_after_verify(state: ChunkState) -> Literal["retry", "polish", "terminology"]:
        ver = state.get("verification") or {}
        score = float(ver.get("score", 1.0))
        if (
            score < strat.verification_threshold
            and state.get("attempts", 0) <= strat.max_retries
            and not state.get("passthrough")
        ):
            return "retry"
        return "polish" if strat.polish and not state.get("passthrough") else "terminology"

    async def retry(state: ChunkState) -> dict[str, Any]:
        lines = ["## Reviewer feedback on your previous attempt (fix every point)"]
        report = state.get("gate_report") or {}
        for p in report.get("problems") or []:
            lines.append(f"- [{p['severity']}] {p['detail']}")
        ver = state.get("verification") or {}
        for s in (Suggestion.model_validate(x) for x in ver.get("suggestions", [])):
            lines.append(
                f"- [{s.severity}] {s.issue}: replace «{s.original_span}» with «{s.suggested}»"
            )
        if ver.get("summary"):
            lines.append(f"- Overall: {ver['summary']}")
        logger.info(
            "chunk %s: retrying (gate %.2f, verifier %.2f)",
            state.get("chunk_index"),
            float(report.get("score", 1.0) if report else 1.0),
            float(ver.get("score", 1.0) if ver else 1.0),
        )
        return {"retry_hints": "\n".join(lines), "verification": None}

    async def polish(state: ChunkState) -> dict[str, Any]:
        if state.get("passthrough") or not strat.polish:
            return {}
        prompt = polish_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            domain=state.get("domain") or DEFAULT_DOMAIN,
            instructions=_instructions_block(state),
            glossary=format_glossary(state.get("glossary", [])),
            target_chunk=state.get("source_work") or state["source_text"],
            translation=state["translation"],
        )
        try:
            polished = clean_model_output(
                await provider.ainvoke_text(prompt, _ctx(state, "polish", polish_prompt))
            )
        except Exception as exc:
            logger.warning("chunk %s: polish failed: %s", state.get("chunk_index"), exc)
            return {"errors": list(state.get("errors", [])) + [f"polish: {exc}"]}
        if not polished:
            return {}
        before = float((state.get("gate_report") or {}).get("score", 1.0))
        after = _gate(state, polished)
        if after.passed and after.score >= before - 1e-9:
            return {"translation": polished, "polished": True, "gate_report": after.as_dict()}
        logger.info("chunk %s: polish rejected by gate", state.get("chunk_index"))
        return {}

    async def terminology(state: ChunkState) -> dict[str, Any]:
        source = state.get("source_work") or state["source_text"]
        report = glossary_report(source, state["translation"], state.get("glossary", []))
        if state.get("passthrough") or not strat.terminology:
            return {"flags": [], "glossary_report": report}
        prompt = terminology_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            domain=state.get("domain") or DEFAULT_DOMAIN,
            instructions=_instructions_block(state),
            glossary=format_glossary(state.get("glossary", [])),
            target_chunk=source,
            translation=state["translation"],
        )
        try:
            out: TerminologyOutput = await provider.ainvoke_structured(
                prompt, TerminologyOutput, _ctx(state, "terminology", terminology_prompt)
            )
        except Exception as exc:
            # Terminology flags are advisory; a failure here must not lose the translation.
            logger.warning("chunk %s: terminology node failed: %s", state.get("chunk_index"), exc)
            return {
                "flags": [],
                "glossary_report": report,
                "errors": list(state.get("errors", [])) + [f"terminology: {exc}"],
            }
        decided = {e.get("original_term") for e in state.get("glossary", [])}
        flags = [f.model_dump() for f in out.flags if f.term and f.term not in decided][:8]
        return {"flags": flags, "glossary_report": report}

    # ------------------------------------------------------------------ graph

    graph: StateGraph = StateGraph(ChunkState)
    graph.add_node("prepare", prepare)
    graph.add_node("clean_source", clean_source)
    graph.add_node("translate", translate)
    graph.add_node("gate", gate_node)
    graph.add_node("verify", verify)
    graph.add_node("retry", retry)
    graph.add_node("polish", polish)
    graph.add_node("terminology", terminology)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "clean_source")
    graph.add_edge("clean_source", "translate")
    graph.add_edge("translate", "gate")
    graph.add_conditional_edges(
        "gate",
        route_after_gate,
        {"retry": "retry", "verify": "verify", "polish": "polish", "terminology": "terminology"},
    )
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        {"retry": "retry", "polish": "polish", "terminology": "terminology"},
    )
    graph.add_edge("retry", "translate")
    graph.add_edge("polish", "terminology")
    graph.add_edge("terminology", END)
    return graph.compile(checkpointer=checkpointer)


def thread_id(state: ChunkState) -> str:
    return f"{state.get('book_id')}:{state.get('chunk_index')}"


async def run_chunk(graph: Any, state: ChunkState) -> ChunkState:
    """Invoke the compiled graph for one chunk with a stable thread id.

    With a checkpointer, an existing checkpoint for the *same source text* is
    reused: unfinished → resume from the failed node (input ``None``);
    finished but never persisted → return its result without new LLM calls.
    A checkpoint for different text (book re-extracted) is ignored and
    overwritten by a fresh run.
    """
    config = {"configurable": {"thread_id": thread_id(state)}}
    if graph.checkpointer is not None:
        snapshot = await graph.aget_state(config)
        previous = snapshot.values or {}
        if previous and previous.get("source_text") == state.get("source_text"):
            if snapshot.next:
                logger.info("chunk %s: resuming at %s", state.get("chunk_index"), snapshot.next)
                return await graph.ainvoke(None, config=config)
            if previous.get("verification") is not None or previous.get("glossary_report"):
                logger.info("chunk %s: reusing finished checkpoint", state.get("chunk_index"))
                return previous  # type: ignore[return-value]
    return await graph.ainvoke(state, config=config)


async def forget_chunk(graph: Any, state: ChunkState) -> None:
    """Drop a chunk's checkpoints once its result is safely in the chunk row."""
    if graph.checkpointer is None:
        return
    try:
        await graph.checkpointer.adelete_thread(thread_id(state))
    except Exception as exc:  # cleanup only; never fail the chunk for this
        logger.warning("could not delete checkpoint %s: %s", thread_id(state), exc)
