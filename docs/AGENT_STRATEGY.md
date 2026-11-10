# The translation agent

One LangGraph runs per chunk ([`agents/chunk_graph.py`](../backend/app/agents/chunk_graph.py)). The graph is the same for every model. What changes with the model is how much scaffolding it gets ([`agents/strategy.py`](../backend/app/agents/strategy.py), [ADR-0013](adr/0013-agent-strategy-by-model-size.md)).

```
prepare ─► clean_source? ─► translate ─► gate ─┬─ fail, retries left ─► retry ─┐
                                ▲              └─ pass ─► verify ─┬─ low ───────┤
                                │                                 └─ ok ─► polish? ─► terminology ─► END
                                └──────────────────────────────────────────────────┘
```

Every node is checkpointed in Postgres. A worker that dies during `verify` resumes at `verify` and never pays for `translate` again ([ADR-0006](adr/README.md), proven by `tests/test_kill_resume.py`).

## Why scaffolding, not a bigger prompt

Small models translate individual sentences well. Their failures are about following instructions over a long input:

| Failure | How often in small models | Countermeasure |
|---|---|---|
| A sentence is silently skipped | Common | Sentence alignment + gate |
| Answer in the wrong language or script, or the source copied back | Occasional, catastrophic | Gate: script ratio, copy check |
| "Here is the translation:" or `<think>` wrapped around the answer | Common | Output cleaning + gate |
| Broken JSON around long RTL text | Common | Tagged output, JSON repair |
| A glossary term ignored | Common | Gate: glossary check, then retry with the exact terms |
| Literal, stiff phrasing | Common | Polish pass, accepted only if the gate holds |
| A term rendered differently across the book | Very common | Glossary + translation memory |
| OCR garbage translated literally | On scans | OCR repair node |

Each countermeasure is cheap. Most are deterministic and cost no LLM call at all.

## The nodes

### `prepare`
This node sets the working state. Content types in `PASSTHROUGH_CONTENT_TYPES` (default `quranic_verse`) are copied through untouched and never machine-translated.

### `clean_source` (OCR repair)
It runs only for chunks whose OCR quality is below the threshold. The text model fixes recognition errors with [`prompts/ocr_cleanup.md`](../prompts/ocr_cleanup.md). The result is rejected if its length changes by more than ±40% or its script changes. The raw text stays on the chunk, so a reviewer can always see what the page said.

### `translate`
- **Sentence alignment** (small and medium models): the source is split by the script-aware segmenter ([`agents/segmenter.py`](../backend/app/agents/segmenter.py)). The splitter knows `۔ ؟ । 。`, abbreviations like "Dr." and "vol.", and splits overlong runs on clause punctuation. The model receives `[1] … [n]` and must return the same numbers. `parse_numbered` turns "did it skip something?" into a set difference. A missing sentence is filled with its source text so nothing disappears silently, and the gate flags it as high severity.
- **Tagged output** (small and medium): the translation comes back inside `<translation>…</translation>`, optionally followed by `<notes>`. This survives small models far better than JSON does. Large models use native structured output.
- **Context**: up to 1,500 characters before and after the chunk, the decided glossary, the book's domain and the editor's instructions, plus up to three **approved chunks of the same book**. Those are found by trigram similarity and shown as examples, which is translation memory.
- **Candidates**: with `TRANSLATION_CANDIDATES > 1`, or automatically for small local models, several samples run in parallel and the gate picks the best one.

### `gate` (deterministic quality checks)
[`agents/quality.py`](../backend/app/agents/quality.py) runs these checks:

| Check | Severity | Rule |
|---|---|---|
| empty | high | No translation |
| target_script | high | Under 60% of the letters are in the target script |
| source_leak | high | Over 35% of the letters are still in the source script (different-script pairs only) |
| copied | high | The translation is identical to the source |
| sentences | high | Numbered sentences missing (alignment mode) |
| length_ratio | medium or high | Target/source length outside a band tuned per script pair (Urdu → Arabic 0.55–1.4, CJK ↔ alphabetic, …) |
| list_items | medium | Numbered or bulleted items lost |
| glossary | medium | A decided term is present in the source but its rendering is absent from the translation |
| preamble | medium | Starts with "Here is the translation" and similar phrases |
| paragraphs | low | Paragraph count differs a lot |
| footnote_markers | low | Footnote markers lost |

A high-severity problem fails the gate. Each check carries an instruction ("Translate sentences [4, 7]; every [n] must appear once"), and the retry prompt receives exactly those instructions.

### `verify` (LLM reviewer)
[`prompts/verification.md`](../prompts/verification.md) is the reviewer prompt. The reviewer sees the source, the context, the glossary and the gate's findings, which it is told to confirm or dismiss. It returns a score from 0 to 1 and span-level suggestions (`original_span` → `suggested`) that the reviewer in the UI can accept with one click. A score below `VERIFICATION_THRESHOLD` (0.8) triggers a retry while retries remain.

### `retry`
This node builds a feedback block and loops back to `translate`. Each gate problem appears with its fix ("sentences not translated: [2]. Fix: Translate sentences [2]; every [n] must appear once."), followed by the reviewer's span-level suggestions.

### When the checks still fail
If the gate still fails after the last retry, the chunk is saved anyway, but it is never presented as good. Its score becomes the lower of the reviewer's score and the gate's score, and the chunk carries a warning ("Automatic checks still failing after retries (…). Review closely.") that the review screen shows above the editor. A lenient small reviewer cannot hide a missing sentence this way. A dropped sentence stays visible in the source language rather than disappearing.

### `polish` (thorough profile)
A fluency edit with [`prompts/polish.md`](../prompts/polish.md). The polished text is kept only if it still passes the gate with a score no lower than before. A polish that drops a sentence is thrown away.

### `terminology`
This node flags at most eight terms per chunk that a human should decide once: technical, legal, religious or scientific terms, and names. In the UI, **Apply to whole book** writes the decision to the glossary that every later prompt uses. A deterministic glossary report measures adherence.

## Profiles

| | fast | balanced | thorough |
|---|---|---|---|
| Gate | ✓ | ✓ | ✓ |
| LLM review | | ✓ | ✓ |
| Retries | 0 | `MAX_TRANSLATION_RETRIES` | ≥ 2 |
| Polish | | | ✓ (small and medium models) |
| Terminology flags | | ✓ | ✓ |

The `auto` setting picks thorough for small models and balanced for everything else. You can set it per book in **Book settings**, or globally with `QUALITY_PROFILE`.

## Model tiers

The tier comes from the model name ([`llm/catalog.py`](../backend/app/llm/catalog.py)). A parameter count in the name decides it: ≤ 4.5B is small, ≤ 14.5B is medium, and anything bigger is large. Without a count, the family decides it: `gpt-4.1`, `claude`, `gemini-2.5-pro` and `llama-3.3-70b` are large, and "mini", "flash" and "haiku" variants are medium. Unknown names default to medium, which keeps the alignment safeguards on.

## Robust output parsing

[`llm/provider.py`](../backend/app/llm/provider.py) handles the output:

- `<think>…</think>` blocks are stripped from every answer.
- Tagged answers tolerate a missing closing tag and upper-case tags. With no tags at all, the whole answer is used and marked `untagged` in the ledger.
- JSON answers are repaired: fences, a sentence before the object, smart quotes, trailing commas, Python literals and raw newlines inside strings. A response that still does not validate raises `LLMOutputError`. A parse failure is an error, never a silent "no issues".
- Hosts that reject `response_format` or tools fall back to JSON mode, and Ollama uses its native `format=json`.

## What this does and does not buy you

The scaffolding catches the failures above and makes a small model's output **reviewable**. It does not give an 8B model the knowledge or fluency of a frontier model, and an 8B reviewer is lenient about output from its own model family. That limit is why:

- the gate exists, because deterministic checks do not grade on a curve;
- every chunk goes through human review before export;
- the [evaluation harness](EVALUATION.md) is the next milestone, so the gap between models can be measured instead of claimed.
