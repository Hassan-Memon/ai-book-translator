"""The per-chunk LangGraph workflow (ADR-0006).

    prepare ─► translate ─► verify ─┬─ score ≥ threshold ─► terminology ─► END
                   ▲               │
                   └── retry ◄─────┘ score < threshold and retries left

One graph invocation = one chunk. The worker loops over chunks and runs this
with ``thread_id = f"{book_id}:{chunk_index}"``; with a checkpointer (1.6,
app/agents/checkpoint.py) a chunk that failed mid-graph resumes at the failed
node on its next attempt. Persistence to the ``chunk`` row happens in the service
layer after the graph returns, which keeps the graph pure and unit-testable
with the FakeProvider.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.schemas import (
    Suggestion,
    TerminologyOutput,
    TranslationOutput,
    VerificationOutput,
)
from app.core.config import Settings, settings
from app.llm.prompts import format_glossary, language_name, load_prompt
from app.llm.provider import CallContext, LLMProvider

logger = logging.getLogger(__name__)


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
    # working state
    translation: str
    notes: list[str]
    verification: dict[str, Any] | None  # VerificationOutput.model_dump()
    attempts: int
    retry_hints: str
    passthrough: bool
    # outputs
    flags: list[dict[str, Any]]
    glossary_report: dict[str, Any]
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


def build_chunk_graph(
    provider: LLMProvider, cfg: Settings | None = None, checkpointer: Any | None = None
) -> Any:
    """Compile the per-chunk graph bound to a provider. Compile once per job."""
    cfg = cfg or settings
    translation_prompt = load_prompt("translation", cfg.prompts_dir)
    verification_prompt = load_prompt("verification", cfg.prompts_dir)
    terminology_prompt = load_prompt("terminology", cfg.prompts_dir)

    async def prepare(state: ChunkState) -> dict[str, Any]:
        passthrough = state.get("content_type") in set(cfg.passthrough_content_types)
        return {
            "attempts": 0,
            "retry_hints": "",
            "errors": [],
            "flags": [],
            "notes": [],
            "verification": None,
            "passthrough": passthrough,
            "translation": state["source_text"] if passthrough else "",
        }

    async def translate(state: ChunkState) -> dict[str, Any]:
        if state.get("passthrough"):
            return {}
        prompt = translation_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            glossary=format_glossary(state.get("glossary", [])),
            retry_hints=state.get("retry_hints", ""),
            context_before=state.get("context_before") or "(start of book)",
            target_chunk=state["source_text"],
            context_after=state.get("context_after") or "(end of book)",
        )
        out: TranslationOutput = await provider.ainvoke_structured(
            prompt, TranslationOutput, _ctx(state, "translate", translation_prompt)
        )
        translation = out.translation.strip()
        if not translation:
            raise ValueError("empty translation returned")
        return {
            "translation": translation,
            "notes": list(state.get("notes", [])) + out.notes,
            "attempts": state.get("attempts", 0) + 1,
        }

    async def verify(state: ChunkState) -> dict[str, Any]:
        if state.get("passthrough"):
            return {"verification": {"score": 1.0, "summary": "passthrough", "suggestions": []}}
        prompt = verification_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            glossary=format_glossary(state.get("glossary", [])),
            context_before=state.get("context_before") or "(start of book)",
            target_chunk=state["source_text"],
            context_after=state.get("context_after") or "(end of book)",
            translation=state["translation"],
        )
        out: VerificationOutput = await provider.ainvoke_structured(
            prompt, VerificationOutput, _ctx(state, "verify", verification_prompt)
        )
        return {"verification": out.model_dump()}

    def route_after_verify(state: ChunkState) -> Literal["retry", "terminology"]:
        ver = state.get("verification") or {}
        score = float(ver.get("score", 1.0))
        if (
            score < cfg.verification_threshold
            and state.get("attempts", 0) <= cfg.max_translation_retries
        ):
            return "retry"
        return "terminology"

    async def retry(state: ChunkState) -> dict[str, Any]:
        ver = state.get("verification") or {}
        suggestions = [Suggestion.model_validate(s) for s in ver.get("suggestions", [])]
        lines = ["## Reviewer feedback on your previous attempt (fix every point)"]
        for s in suggestions:
            lines.append(
                f"- [{s.severity}] {s.issue}: replace «{s.original_span}» with «{s.suggested}»"
            )
        if ver.get("summary"):
            lines.append(f"- Overall: {ver['summary']}")
        logger.info(
            "chunk %s: verification score %.2f < %.2f, retrying",
            state.get("chunk_index"),
            float(ver.get("score", 0)),
            cfg.verification_threshold,
        )
        return {"retry_hints": "\n".join(lines)}

    async def terminology(state: ChunkState) -> dict[str, Any]:
        report = glossary_report(
            state["source_text"], state["translation"], state.get("glossary", [])
        )
        if state.get("passthrough"):
            return {"flags": [], "glossary_report": report}
        prompt = terminology_prompt.render(
            source_language_name=language_name(state["source_language"]),
            target_language_name=language_name(state["target_language"]),
            glossary=format_glossary(state.get("glossary", [])),
            target_chunk=state["source_text"],
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
        flags = [f.model_dump() for f in out.flags if f.term and f.term not in decided]
        return {"flags": flags, "glossary_report": report}

    graph: StateGraph = StateGraph(ChunkState)
    graph.add_node("prepare", prepare)
    graph.add_node("translate", translate)
    graph.add_node("verify", verify)
    graph.add_node("retry", retry)
    graph.add_node("terminology", terminology)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "translate")
    graph.add_edge("translate", "verify")
    graph.add_conditional_edges(
        "verify", route_after_verify, {"retry": "retry", "terminology": "terminology"}
    )
    graph.add_edge("retry", "translate")
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
            if previous.get("verification") is not None:
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
