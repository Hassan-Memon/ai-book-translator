# Evaluation

**Status: built (v0.4).** The harness runs the product's own chunk graph over a hand-checked golden set and scores the output four ways. It is what turns "I built a translator" into "I know how good it is, where it fails, and what each change did." Run it after every change to prompts, strategy or models.

```bash
cd backend
uv run translatebook eval validate                        # check the golden set
uv run translatebook eval run --provider ollama --model qwen3:8b \
    --judge-provider ollama --judge-model llama3.1:8b --split all
uv run translatebook eval calibrate --judge-provider openai --judge-model gpt-4.1-mini
```

Results land in [`evals/results/`](evals/results/README.md): one JSON per run, plus one row in the results table. The design decisions are in [ADR-0014](adr/0014-evaluation-harness-in-the-app.md).

## 1. What is measured

A literary or scholarly translation can fail in four different ways, and a single score hides which one happened, so each is measured separately:

| Failure | Metric | How | Cost |
|---|---|---|---|
| Wrong meaning or poor wording | **chrF++** against the human reference(s), 0–100, best over `alt_references` | Deterministic. Character n-grams 1–6 plus word n-grams 1–2, β = 2, matching `sacrebleu.CHRF(word_order=2)` exactly. Character n-grams are fair to Arabic, Urdu and Hindi morphology | free |
| | Judge **adequacy** and **fluency**, 1–5 | LLM judge, reference-based | cheap or free |
| Terminology drift | **Term adherence** = decided terms rendered as decided ÷ decided terms present (micro-averaged) | Deterministic, with `variants` counted | free |
| Omissions and additions | Judge **omissions** and **additions**, 1–5, plus the **length ratio** | Judge and heuristic | cheap |
| Structure lost | **Structure kept**: paragraph count, list items, footnote markers (any digit system), verse brackets, headings on one line | Deterministic | free |

Each run also records the gate pass rate, the in-product reviewer score, LLM calls, tokens, cost, **$ per 100 pages** (at 1,800 source characters per page) and **p50 seconds per item**. Every result file carries the git commit, all prompt versions, the model, and the full resolved strategy.

## 2. The golden sets (`docs/evals/golden/`)

| File | Items | Pairs | Status |
|---|---|---|---|
| `starter-v1.jsonl` | 15 (10 dev, 5 test) | en→ar, en→ur, en→hi, ur→ar | **References are drafts** (`reviewed_by: null`). Public-domain sources (Aesop, Marcus Aurelius) and short Islamic-studies lines. Includes adversarial items: a Quranic verse that must pass through, and an Arabic quotation inside Urdu that must stay verbatim |
| `example.jsonl` | 3 | ur→ar | Shape examples only |

The contract is in [`golden/SCHEMA.md`](evals/golden/SCHEMA.md), and `translatebook eval validate` enforces it. `--release` adds the size rules a set must meet before its numbers go in the README (≥ 15 test items, ≥ 5 per content type).

**Next:** `ur-ar-v1.jsonl`, about 60 items from the sample book, with references written and signed off (`reviewed_by`) by a trained scholar. That file, not the starter set, is the asset that makes the numbers trustworthy. Once a set has results, it is never edited; corrections go into a v2.

## 3. The judge (`app/evals/judge.py`, `prompts/judge.md`)

- It scores five axes from 1 to 5, each with a one-sentence rationale: adequacy, fluency, omissions, additions and terminology. Scoring is absolute and reference-based; the judge sees the source, the reference, the candidate and the decided terms.
- **The judge must come from a different model family than the translator** (ADR-0007). The run records a warning when it does not, for example `aya-expanse` judged by `command-r`.
- **Calibrate before trusting it.** `eval calibrate` judges each reference against a degraded copy, with a sentence dropped or a decided term swapped. The degraded copy must lose on that axis or overall. Agreement must reach ≥ 0.8, or the rubric or the judge model has to change.
- Spot-check 10 verdicts by hand per milestone and record the agreement next to the run.

## 4. The runner (`app/evals/runner.py`)

- It calls `build_chunk_graph()`, the same function the worker uses, with no checkpointer, and seeds the glossary from each item's `terms`. It needs no database: an in-memory recorder captures every provider call.
- `--profile fast|balanced|thorough|auto` sets the agent strategy, so profiles can be compared on equal terms.
- **Failures are scored, never dropped.** A provider error, refusal or empty answer scores 0 everywhere.
- **Cache**: translations are cached in `results/.cache/`, keyed by item, model, profile and the pipeline prompt versions. Re-running after a judge change costs nothing, and a prompt change re-translates exactly what it affects. Use `--no-cache` to force a fresh run.
- `--only-cached` re-scores cached translations without ever calling the translator. Use it to add a judge afterwards, to recover an interrupted run (skipped items are listed in the run's warnings), or to re-score after a metric change.
- Use `--split dev` while iterating and `--split test` only at milestone ends. `--pair en->ur` and `--limit N` narrow a run.

## 5. Reading the results

The [results table](evals/results/README.md) has one row per run:

- **chrF++ (95% CI)**: the mean over items, with a seeded bootstrap interval. With 15 items the interval is wide, and differences smaller than it are noise. Say so.
- **Term adherence**: 1.00 means every decided term was used. This is what a reviewer cares about most in scholarly text.
- **Structure kept**: the share of items where every applicable structural check passed.
- **Judge**: the mean of the five axes, with the judge model named.
- **$/100 pages**: shown as 0 for local models. **p50 s/item**: wall-clock per item, including retries.

### First results (2026-11-10, CPU-only laptop)

See the [results table](evals/results/README.md) for the run itself; the summary is below.

**`aya-expanse:8b`, fast profile (one translation call, no retries), CPU only.** The run was stopped for low memory after 13 of the 15 items. It was scored from the cache with `--only-cached`. The judge was not run, and `ur-ar-0003` is missing.

| Pair | Items | chrF++ | Structure kept |
|---|---:|---:|---:|
| en→ar | 4 | 39.9 | 0.50 |
| en→hi | 3 | 40.9 | 0.67 |
| en→ur | 4 | 21.7 | 0.75 |
| ur→ar | 3 | 55.1 | 0.67 |
| **All** | **14** | **38.2** (95% CI 25–52) | **0.64** |

Term adherence was 0.80 (12 of 15 decided terms), the gate passed 92% of items, and the median time was 137 s per item.

**What the numbers say**

- **Prose is usable; headings are not.** Prose scored between 24 and 58 chrF++. On **all four headings**, the model translated the heading and then *invented a paragraph under it* (chrF++ 4–14).
- **The gate passed those invented paragraphs**, because its length check skipped sources under 80 characters. That was a real product bug, found by this harness and **fixed in 0.4.0**. A new check flags a short source whose translation runs on, with the instruction *"translate only that line"*. Re-gating the same 13 outputs now fails all four, and no good translation is newly rejected. A test pins it with the model's actual output.
- **Urdu is the weakest target** (21.7). The output is garbled, and two decided terms were missed: "fox" → لومڑی and "evil" → برائی. Hindi and Arabic prose read well. The 2026-11-10 "fox → mouse" Hindi error did not recur on this item.
- **The numbered list collapsed into one line** and English leaked into it. The gate caught this, but the fast profile does not retry.
- The Quranic verse passed through untouched, scoring 100.

**Next runs:** the same model with the `balanced` profile (retries on), to measure the fix; `qwen3:8b` for comparison; a calibrated judge from another family; and the scholar-reviewed `ur-ar-v1` set. On this laptop, a 15-item balanced run takes about an hour, and memory is the limit: run the translator and the judge in separate passes, which the cache makes possible.

## 6. Rules that keep the numbers honest

1. Never tune a prompt on the golden set *and* report on it alone. Iterate on `dev` and report on `test`.
2. Report the confidence interval. With 15 to 60 items, small differences are noise.
3. The judge score is not ground truth. Pair it with a calibration and a human spot check.
4. Every result file logs the commit, the prompt versions and the model ID; that is automatic.
5. A refusal or truncation is a scored failure, never an excluded item.
6. Draft references (`reviewed_by: null`) make chrF++ indicative only, and the run warns about it.
7. Never edit a row in the results table. Negative results stay.
