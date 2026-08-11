"""Verification agent — constrained review suggestions."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class VerificationAgent:
    """Review translations and suggest improvements."""

    def __init__(self, llm_provider: Any):
        self.llm = llm_provider

    async def verify_translation(
        self,
        chunk_text: str,
        translated_text: str,
        context_before: str,
        context_after: str,
        glossary: dict[str, str],
    ) -> dict[str, Any]:
        """Verify translation and suggest improvements."""

        glossary_text = "\n".join(
            [f"- {src}: {tgt}" for src, tgt in glossary.items()]
        )

        prompt = f"""You are an expert reviewer of translations.

Review the translation for issues (but DO NOT retranslate):

Original:
{chunk_text}

Current Translation:
{translated_text}

Context Before:
{context_before}

Context After:
{context_after}

Glossary:
{glossary_text}

Respond with JSON:
{{
  "has_issues": boolean,
  "issues": [
    {{"phrase": "...", "suggestion": "...", "reason": "..."}}
  ]
}}"""

        try:
            response = await self.llm.ainvoke(prompt)
            # Extract JSON from response
            result = json.loads(response.content)
            return result
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return {"has_issues": False, "issues": []}
