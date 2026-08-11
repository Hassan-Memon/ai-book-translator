"""Terminology agent — flag domain-specific terms for human review."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TerminologyAgent:
    """Detect and flag terminology requiring human review."""

    def __init__(self, llm_provider: Any):
        self.llm = llm_provider

    async def flag_terminology(
        self,
        chunk_text: str,
        translated_text: str,
        glossary: dict[str, str],
    ) -> dict[str, Any]:
        """Flag terminology that needs human review."""

        glossary_text = "\n".join(
            [f"- {src}: {tgt}" for src, tgt in glossary.items()]
        )

        prompt = f"""You are an expert in Islamic terminology.

Scan this chunk and flag terms requiring human review for consistency.

Original:
{chunk_text}

Translation:
{translated_text}

Already Decided (glossary):
{glossary_text}

Respond with JSON array of flagged terms:
[
  {{
    "term": "original term",
    "category": "islamic_terminology|classical_name|technical_term|ambiguous",
    "suggested_translation": "...",
    "reasoning": "why this needs review"
  }}
]

If no significant terminology flags, return empty array []."""

        try:
            response = await self.llm.ainvoke(prompt)
            result = json.loads(response.content)
            return {"flags": result if isinstance(result, list) else []}
        except Exception as e:
            logger.error(f"Terminology detection failed: {e}")
            return {"flags": []}
