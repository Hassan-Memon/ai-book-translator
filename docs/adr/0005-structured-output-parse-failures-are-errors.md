# ADR-0005: Typed LLM output; a parse failure is an error, never an empty result
Date: 2026-11-02 · Status: accepted (implemented in `backend/app/agents/schemas.py`, `backend/app/llm/provider.py`; extended for small models in v0.3)

## Context
The reviewer and terminology steps return structured data: a score, span-level suggestions and flags. The common anti-pattern is `json.loads` inside a `try` that returns `[]` on failure. That turns "the model produced garbage" into "no issues found", which is the most dangerous possible outcome for a verifier.

## Decision
Every structured node asks for a Pydantic model (`TranslationOutput`, `VerificationOutput`, `TerminologyOutput`). The provider tries native structured output first, then JSON mode with the schema in the prompt, then a repair pass (fences, `<think>` blocks, a sentence before the object, smart quotes, trailing commas, Python literals, raw newlines). If the result still does not validate, `LLMOutputError` is raised and the ledger row is marked `parse_error`. Since v0.3 the free-text translation itself uses `<translation>` tags for small models (ADR-0013), because JSON around long right-to-left text is where small models break most.

## Alternatives considered
- **Lenient parsing that defaults to empty**: hides failures and approves bad translations.
- **Regex extraction of fields**: brittle and still silent on failure.
- **Retrying until it parses**: the retry policy belongs to the graph, not the parser. Transient errors are retried by tenacity; parse errors surface.

## Consequences
- Easier: a chunk is never marked verified because its review could not be read. Failures are visible in the ledger by node and model.
- Harder: weak models raise more errors. The terminology node therefore treats its own failure as advisory (it records the error and keeps the translation), while the reviewer's failure fails the chunk.
