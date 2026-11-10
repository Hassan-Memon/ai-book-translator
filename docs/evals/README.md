# docs/evals/

Evaluation assets for TranslateBook AI. The method is described in [`docs/EVALUATION.md`](../EVALUATION.md). The harness itself is the `backend/app/evals/` package, run as `translatebook eval …` (see [ADR-0014](../adr/0014-evaluation-harness-in-the-app.md)). This folder holds the data and the results so they are reviewed like documentation.

```
docs/evals/
├── README.md               this file
├── golden/
│   ├── SCHEMA.md           field-by-field contract for golden items
│   ├── starter-v1.jsonl    15 items, en→ar/ur/hi and ur→ar, draft references
│   └── example.jsonl       three items showing the shape
└── results/
    ├── README.md           one row per run, appended automatically
    ├── <date>_<model>_<profile>_<split>.json   every item, translation and score
    └── .cache/             cached translations (gitignored)
```

## Running

```bash
cd backend
uv run translatebook eval validate ../docs/evals/golden/starter-v1.jsonl
uv run translatebook eval run --provider ollama --model qwen3:8b --split dev
uv run translatebook eval run --provider openai --model gpt-4.1-mini \
    --judge-provider ollama --judge-model llama3.1:8b --split all --note "baseline"
```

`--golden` defaults to `starter-v1.jsonl` and `--out` to this folder's `results/`.

## Writing golden items

1. Open the source book. Pick passages that are self-contained: a paragraph, a heading, one footnote or one list. Note the page.
2. Copy the source text exactly as a correct extraction would produce it, fixing OCR errors by hand. The golden set tests translation, not OCR.
3. Write the reference translation by hand, in the register a scholarly publisher would accept. Add `alt_references` where another rendering is equally right.
4. Tag `terms`: every religious or technical term in the source, with its decided rendering. They seed the glossary during the run and are what "term adherence" measures.
5. Set `content_type`, `split` (about 75% `dev`, 25% `test`), `reviewed_by` (your name, once you have checked it), and `notes` for anything a judge should know.
6. Run `translatebook eval validate <file>` (add `--release` before publishing numbers).

Budget 5–8 minutes per prose item; 60 items take about 6 hours across a week of evenings. Do not rush them: everything downstream is only as honest as this file.
