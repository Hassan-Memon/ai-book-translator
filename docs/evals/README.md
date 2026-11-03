# evals/

Evaluation assets for TranslateBook AI. Strategy is in `docs/06-evaluation-strategy.md`.
The runnable harness (`run_eval.py`, `metrics.py`, `judge.py`) is built in Milestone 2 and lives
at the repo root `evals/` next to `backend/`; this folder under `docs/` holds the golden-set
contract and the results narrative so they are reviewed like documentation.

```
docs/evals/
├── README.md            this file
├── golden/
│   ├── SCHEMA.md        field-by-field contract for golden items
│   └── example.jsonl    three example items showing the shape (not real references yet)
└── results/             created in Milestone 2: one JSON per run + README.md with the table
```

## Writing golden items

1. Open the sample book PDF. Pick passages that are self-contained (a paragraph, a heading plus its
   first sentence, one footnote, one list). Note the page.
2. Copy the source text exactly as a correct extraction would produce it (fix OCR errors by hand;
   the golden set tests translation, not OCR).
3. Write the reference translation by hand, in the register a scholarly publisher would accept.
4. Tag `terms`: every religious/technical term in the source and the decided rendering. These
   seed the glossary during the eval and are what "glossary adherence" measures.
5. Set `content_type`, `split` (`dev` for 45 items, `test` for 15), and `notes` for anything a
   judge should know (e.g. "alternative rendering X also acceptable").
6. Run `python evals/validate_golden.py docs/evals/golden/urdu-ar-v1.jsonl` (Milestone 2.1 builds it).

Budget ~5–8 minutes per prose item. 60 items ≈ 6 hours across a week of evenings. Do not rush
them; everything downstream is only as honest as this file.
