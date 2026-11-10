# Evaluation results

One row per run of `translatebook eval run`, appended automatically. Each row links the
full JSON (every item, its translation, every score). How to read the columns is in
[`docs/EVALUATION.md`](../../EVALUATION.md#5-reading-the-results). Rows are never edited
or deleted; negative results stay.

| Date | Model | Profile | Golden set (split, items) | chrF++ (95% CI) | Term adherence | Structure kept | Judge (1–5) | Errors | $/100 pages | p50 s/item | Run |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | `aya-expanse:8b` | fast | starter-v1.jsonl (all, 14) | 38.2 (25–52) | 0.80 | 0.64 | – | 0 | 0 (local) | 137 | [2026-11-10_aya-expanse-8b_fast_all.json](2026-11-10_aya-expanse-8b_fast_all.json) |
