"""Translation agent — context-aware chunk translation."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


class TranslationAgentState:
    """State passed through the translation agent graph."""

    def __init__(self):
        self.chunk_text: str = ""
        self.chunk_index: int = 0
        self.context_before: str = ""
        self.context_after: str = ""
        self.glossary: dict[str, str] = {}
        self.source_language: str = "ur"
        self.target_language: str = "ar"
        self.translation: str = ""
        self.errors: list[str] = []


class TranslationAgent:
    """LangGraph-based translation agent for context-aware translation."""

    def __init__(self, llm_provider: Any):
        self.llm = llm_provider
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the translation workflow graph."""
        graph = StateGraph(dict)

        # Define nodes
        graph.add_node("load_context", self._load_context)
        graph.add_node("translate", self._translate)
        graph.add_node("verify_glossary", self._verify_glossary)
        graph.add_node("finalize", self._finalize)

        # Define edges
        graph.add_edge("load_context", "translate")
        graph.add_edge("translate", "verify_glossary")
        graph.add_edge("verify_glossary", "finalize")
        graph.add_edge("finalize", END)

        graph.set_entry_point("load_context")
        return graph

    async def translate_chunk(
        self,
        chunk_text: str,
        chunk_index: int,
        neighbors: dict[str, str],
        glossary: dict[str, str],
        source_language: str,
        target_language: str,
    ) -> dict[str, Any]:
        """Translate a single chunk."""
        state = {
            "chunk_text": chunk_text,
            "chunk_index": chunk_index,
            "context_before": neighbors.get("n_minus_1", ""),
            "context_after": neighbors.get("n_plus_1", ""),
            "glossary": glossary,
            "source_language": source_language,
            "target_language": target_language,
            "translation": "",
            "errors": [],
        }

        # Execute graph
        compiled = self.graph.compile()
        final_state = await compiled.ainvoke(state)

        return {
            "translation": final_state.get("translation", ""),
            "errors": final_state.get("errors", []),
        }

    async def _load_context(self, state: dict) -> dict:
        """Load and prepare context for translation."""
        logger.info(f"Loading context for chunk {state['chunk_index']}")
        return state

    async def _translate(self, state: dict) -> dict:
        """Translate chunk using LLM."""
        chunk_text = state["chunk_text"]
        glossary = state["glossary"]
        source_lang = state["source_language"]
        target_lang = state["target_language"]

        # Format glossary for prompt
        glossary_text = ""
        if glossary:
            glossary_text = "\n".join(
                [f"- {src}: {tgt}" for src, tgt in glossary.items()]
            )
        else:
            glossary_text = "(No glossary entries yet)"

        prompt = f"""You are a scholarly translator specializing in Islamic literature.

Translate ONLY the target chunk from {source_lang} to {target_lang}.
The surrounding chunks are context only — do not translate them.

Glossary (use these translations consistently):
{glossary_text}

Context Before:
{state['context_before'][:200] if state['context_before'] else "(No context)"}

TARGET CHUNK — TRANSLATE ONLY THIS:
{chunk_text}

Context After:
{state['context_after'][:200] if state['context_after'] else "(No context)"}

Translate the target chunk preserving meaning, tone, and scholarly register. Return ONLY the translation."""

        try:
            # Call LLM via provider
            logger.info(f"Translating chunk {state['chunk_index']}...")
            response = await self.llm.ainvoke(prompt)
            state["translation"] = (
                response.content if hasattr(response, "content") else str(response)
            )
            logger.info(
                f"Chunk {state['chunk_index']} translated "
                f"({len(state['translation'])} chars)"
            )
        except Exception as e:
            logger.error(f"Translation failed for chunk {state['chunk_index']}: {e}")
            state["errors"].append(str(e))
            state["translation"] = f"[Translation error: {str(e)}]"

        return state

    async def _verify_glossary(self, state: dict) -> dict:
        """Verify that glossary terms are used in translation."""
        translation = state["translation"]
        glossary = state["glossary"]

        for _src_term, tgt_term in glossary.items():
            if tgt_term not in translation:
                logger.warning(
                    f"Glossary term '{tgt_term}' not found in translation"
                )
                state["errors"].append(
                    f"Glossary term '{tgt_term}' may not be used consistently"
                )

        return state

    async def _finalize(self, state: dict) -> dict:
        """Finalize translation."""
        logger.info(f"Chunk {state['chunk_index']} translation complete")
        return state
