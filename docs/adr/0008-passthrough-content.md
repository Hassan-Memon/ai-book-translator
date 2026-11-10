# ADR-0008: Some content is passed through, never machine-translated
Date: 2026-11-02 · Status: accepted (implemented in `chunk_graph.prepare`, `PASSTHROUGH_CONTENT_TYPES`)

## Context
Books quote texts whose wording is fixed. Scripture is the clearest case: a Quranic verse inside an Urdu book must stay in its original Arabic, and a machine "translation" of it is an error that a reader in this domain will not forgive. The same holds for verse quoted in its original language, legal citations and formulas.

## Decision
Chunks whose content type is listed in `PASSTHROUGH_CONTENT_TYPES` (default `quranic_verse`) are copied unchanged: no translate, gate, review or polish calls, and a verification of 1.0 with the summary `passthrough`. The format mapper tags verse-like lines (﴿…﴾ brackets, ۝ markers, `n:n` references). The translation prompt separately tells the model to keep quotations in a third language in their original wording when they appear inside prose.

## Alternatives considered
- **Prompt-only protection**: models still "helpfully" translate quoted verses some of the time.
- **Translating, then letting a human revert**: puts the burden on the reviewer for something that is never wanted.

## Consequences
- Easier: zero risk for the most sensitive content, and no tokens spent on it.
- Harder: detection is heuristic. A misdetected verse inside a prose chunk is protected only by the prompt rule. The list is configurable for other domains.
