# Evaluation strategy

Status: **planned, not built yet.** This is the next milestone. It is what turns "I built a
translator" into "I know how good it is, where it fails, and what each change did." Once built, it
runs after every meaningful change.

## 1. What we are measuring

Literary/scholarly translation has four distinct failure modes. A single score hides them, so we
measure each:

| Failure | Metric | Type | Cost |
|---------|--------|------|------|
| Wrong meaning / poor wording | **chrF++** vs the human reference; judge *adequacy* and *fluency* (1–5) | automatic + judge | free / cheap |
| Terminology inconsistency | **Glossary adherence** = tagged terms rendered as decided ÷ tagged terms present | deterministic | free |
| Omissions and additions | Judge *omission* / *addition* (1–5) + **length ratio** guard (hyp chars ÷ src chars within band per content type) | judge + heuristic | cheap |
| Structure lost | **Structure preserved**: heading markers, list numbering, footnote markers, verse brackets survive | deterministic | free |

Plus operational metrics from the `llm_call` table: tokens, cost, latency, retries per item.

## 2. The golden set (`evals/golden/`)

- Format: JSON Lines, schema in `evals/golden/SCHEMA.md`, example in `example.jsonl`.
- **v1 target: 60 items** Urdu→Arabic from the sample book. Later: 40 Arabic→Urdu from a public-domain
  Arabic text. Keep ≤ 100 per direction; quality over quantity.
- Stratify by `content_type`: prose 50%, headings 15%, hadith/quotation 15%, footnotes 10%, lists 10%.
- Each item carries `terms`: the source terms whose rendering has been *decided* (this seeds the
  glossary for the run so adherence is measurable).
- References are written by hand by a trained scholar (the author), not generated; this is the
  asset. `notes` / `alt_references` record where more than one rendering is acceptable.
- Add 10 **adversarial** items: a chunk with a Quranic verse (must be passed through, not
  translated), a chunk with a mixed Arabic quotation inside Urdu prose, a very short heading, a
  footnote with a book citation. These catch the failures that matter to real users.
- Version the file (`urdu-ar-v1.jsonl`). Never edit v1 after results exist; create v2.

## 3. The judge (`evals/judge.py`, `prompts/judge.md`)

- Absolute scoring with a rubric, 1–5 on: adequacy, fluency/register, omissions, additions,
  terminology. Each score must come with a one-sentence rationale (structured output).
- Judge sees: source, reference, candidate, the term list. Reference-based judging is far more
  reliable than reference-free.
- **Judge model ≠ translating model family** (ADR-0007) to reduce self-preference bias.
- Calibrate once: judge the reference vs. a deliberately degraded copy (drop a sentence, swap a
  term). Degraded must lose on the right axis. Record the calibration in `evals/results/README.md`.
- Periodically spot-check 10 judge verdicts by hand and record agreement. If agreement < 80%, fix
  the rubric before trusting the numbers.

## 4. The runner (`evals/run_eval.py`)

```
uv run python evals/run_eval.py \
  --golden evals/golden/urdu-ar-v1.jsonl \
  --model github:openai/gpt-4.1 \
  --prompt-version 2 \
  --concurrency 3 --limit 60
```

- Imports and runs **the same compiled chunk graph** the worker uses (with an in-memory glossary
  seeded from `terms`), so the eval measures the product, not a copy of it.
- Writes `evals/results/<YYYY-MM-DD>_<model>_<pv>.json` (per-item scores + aggregates) and appends a
  row to `evals/results/README.md`.
- Deterministic where possible: `temperature=0`, fixed seed when the provider supports it.
- Caches by `(item_id, model, prompt_version)` so re-runs only pay for changes.

## 5. The results table (what goes in the README)

| Date | Model | Prompt v | chrF++ | Adherence | Omission (judge) | Structure | $/100 pages | p50 s/chunk |
|------|-------|----------|--------|-----------|------------------|-----------|-------------|-------------|
| 2026-12-0x | gpt-4.1 (GitHub) | 1 | … | … | … | … | … | … |
| 2026-12-0x | claude (current) | 1 | … | … | … | … | … | … |
| 2026-12-0x | qwen2.5:7b (local) | 1 | … | … | … | … | 0 | … |
| 2026-12-0x | best of above | 2 | … | … | … | … | … | … |

Every row has a one-line note: what changed, what moved, what did not. Negative results stay.

## 6. Rules that keep the numbers honest

1. Never tune a prompt on the golden set *and* report on it alone. Hold out 15 items as a test
   split (`split: "test"`) you only run at milestone ends.
2. Report confidence: with 60 items, differences under ~2 chrF points are noise. Say so.
3. The judge score is not ground truth. Pair it with a human spot-check rate.
4. Log the exact commit hash, prompt version, and model id in every result file.
5. When a model refuses or truncates, that is a scored failure, not an excluded item.
