# Testing

## Latest results

Run on 2026-11-10 on Windows 11 with Python 3.13, PostgreSQL 17 + pgvector in Docker and Tesseract 5.5 installed:

```
$ make test           # = uv run pytest -q --cov=app
68 passed in 61.51s
TOTAL   4680 statements   802 missed   83% coverage
```

Ruff (lint and format), oxlint and the production frontend build are clean. CI runs the same checks on every push.

| Area | Module | Coverage |
|---|---|---|
| Agent | `agents/strategy.py` | 95% |
| | `agents/quality.py` (gate) | 89% |
| | `agents/chunk_graph.py` | 87% |
| | `agents/segmenter.py` | 80% |
| OCR | `pipeline/ocr/quality.py` | 92% |
| | `pipeline/ocr/layout.py` | 86% |
| | `pipeline/ocr/tessdata.py` | 77% |
| | `pipeline/ocr/ladder.py` | 75% |
| | `pipeline/ocr/engines.py` | 58% |
| Languages and models | `core/languages.py` | 94% |
| | `llm/catalog.py` | 91% |
| | `llm/provider.py` | 82% |
| API and services | `services/translation.py` | 90% |
| | `services/review.py`, `services/glossary.py`, `services/extraction.py` | 89% |
| | `api/routes_settings.py` | 88% |
| | `api/routes.py` | 85% |
| | `services/settings.py` | 66% |
| Jobs | `jobs/handlers.py` | 88% |
| | `jobs/queue.py` | 86% |

**What is not covered, and why:**
- `worker.py` (25%) runs in a separate process during the kill test, so its lines are exercised but not measured.
- `cli.py` (0%) wraps the same services the tests call directly.
- In `ocr/engines.py`, the EasyOCR and vision-model branches need a 2.5 GB install or a running vision model.
- In `services/settings.py`, live model listing and runtime detection need Ollama or LM Studio running.

These paths were checked by hand (see below).

## What the 68 tests prove

| File | Tests | What it proves |
|---|---:|---|
| `test_kill_resume.py` | 1 | A real worker process is **hard-killed** in the middle of a chunk's review step. A new worker resumes at exactly that node, every chunk is translated exactly once, and the log shows `resuming at ('verify',)` |
| `test_checkpoint_resume.py` | 5 | Resume at the failed node with the memory and Postgres checkpointers. A stale checkpoint is ignored when the source text changed. Checkpoints are cleaned up after success |
| `test_jobs_and_services.py` | 3 | The queue claim is exclusive (`SKIP LOCKED`), with retries and backoff. Upload → extract → translate → review → export through the services, and through the worker handlers |
| `test_review_http.py` | 1 | **The whole review workflow over HTTP**, as the UI drives it: upload, page-range validation, list and filter chunks, edit, accept a suggestion, decide a term for the whole book, glossary CRUD with CSV/JSON import and export, approve and unapprove, one active job per book (409), DOCX export with right-to-left paragraphs, download, stats, jobs, delete |
| `test_api_events.py` | 2 | The SSE stream sends progress, then `idle`, then closes. Unknown books return 404 |
| `test_agent_scaffolding.py` | 6 | **The small-model path through the real graph**: a 4B model gets numbered sentences and tagged output, a skipped sentence triggers a retry whose prompt says "Translate sentences [2]", a wrong-language answer triggers a retry with a script instruction, polish is kept only when the gate holds, the *fast* profile runs one call, OCR repair runs only below the threshold, and a failed gate caps the score and warns the reviewer |
| `test_llm_layer.py` | 10 | Prompt loading and versions, missing placeholders, glossary formatting, JSON parsing, glossary adherence, and the graph's happy path, retry, verse passthrough and errors with the demo provider |
| `test_provider_runtime.py` | 9 | The provider layer against a stand-in chat model: `<think>` stripping, cost ledger, tagged parsing and its fallback, JSON repair of small-model output, retry on 429 but not on 401, vision messages, test-connection ping. Factories for every provider kind with clear missing-key errors, base-URL normalisation, and language-pack copy, download and offline fallback |
| `test_settings_api.py` | 4 | Keys are encrypted at rest and masked. Settings persist; an omitted key keeps the old one and an empty key clears it. Settings endpoints and catalog. Catalog-only provider keys are read from `.env` |
| `test_books_api_v03.py` | 3 | Unknown language codes are rejected. Domain, author and instructions are stored. PATCH per-book settings. The PDF sniff detects the text layer and language. **A scanned page is OCRed**: correct reading order, page number dropped, quality > 0.6, language detected |
| `test_ocr_ladder.py` | 8 | Line grouping and wide-gap splitting (scanned spreads), two-column detection with right-to-left order, headings that span both columns, page numbers and running heads, Latin de-hyphenation, quality score (clean vs. garbage vs. no confidences), Otsu binarisation, and an end-to-end synthetic page |
| `test_languages_and_strategy.py` | 12 | The 51-language registry, fonts, direction and OCR packs, language guessing (Urdu vs. Arabic vs. Persian, Hindi), script ratio, model tiers and vision detection, strategy by model size and per-book override, the sentence splitter (Urdu terminators, "Dr.", "vol. 2."), numbered round trips, gate checks (wrong script, copy, empty, glossary, alignment), output cleaning, JSON repair |
| `test_pipeline_foundation.py` | 4 | Format mapper (RTL, headings, verses), chunker metadata and no duplicated text, text-layer extraction |

No test calls a real LLM. They use a deterministic `FakeProvider` or a scripted stand-in model, so the suite is free, offline and repeatable.

## What was checked by hand

| Check | Result |
|---|---|
| Free OCR, clean printed Arabic (synthetic, 300 dpi) | Quality 0.96, mean word confidence 92 |
| Free OCR, scanned Urdu/Arabic spread (*Ghair Soodi Bankari*, pp. 11–14) | Mean quality 0.70 (0.47–0.87 per chunk). Arabic quotations read well; Nastaliq Urdu is poor. See [OCR.md](OCR.md) |
| English → Urdu, `aya-expanse:8b`, CPU only, balanced profile | First attempt failed the gate (missing sentence, length, paragraphs). The retry with fix instructions passed, reviewer 0.90. All sentences present, but the Urdu is rough: garbled words and one leaked Hindi word |
| English → Hindi, `aya-expanse:8b`, CPU only | Fluent Hindi. Two sentences still untranslated after the retry, so the chunk shows **score 0.60 and a "review closely" warning** instead of the reviewer's 0.95. One meaning error no check caught: "fox" → "चूहा" (mouse) |
| Kill and resume on a real model | The server was stopped during the Hindi job. On restart the stale job was reclaimed and resumed at `terminology` without repeating the paid calls |
| UI | All pages rendered in headless Chromium at 1440×900 in light and dark themes with no console errors. The screenshots in `docs/images/` come from that run |

These runs are the reason two behaviours changed in 0.3.1. The retry now carries the gate's fix instructions, and a failed gate caps the displayed score. They are also why the README does not claim that small models match large ones.

## Running the tests

```bash
make test                                   # starts Postgres, runs everything with coverage
cd backend
uv run pytest -q tests/test_ocr_ladder.py   # one file
uv run pytest -q -k gate                    # by name
uv run pytest -q --cov=app --cov-report=html && start htmlcov/index.html
```

Requirements: Docker running (the `translatebook_test` database), and optionally Tesseract with the `eng` pack. OCR tests that need an engine are skipped without one.

Notes:
- The schema is built with Alembic (downgrade to base, then upgrade to head) once per session, which also tests the migrations. Tables are truncated after each test.
- The kill test starts real worker subprocesses with a 600 ms simulated LLM delay. It is timing-sensitive, so do not run it while the machine is busy with local inference.
- Coverage traces greenlets (`[tool.coverage.run] concurrency`), because SQLAlchemy's async engine runs ORM code inside them.

## Writing tests

- Use the `fake_provider` fixture for graph and service tests, or subclass `LLMProvider` like `ScriptedSmallModel` in `test_agent_scaffolding.py` to replay exact model answers.
- HTTP tests use `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()))`, with no server needed.
- Use the `sample_pdf` fixture (two text pages, one «flagged» term) and `tmp_storage` (isolated upload and export folders).
- Never assert on text your own input put there. Assert on what the system produced.

Translation **quality** is measured separately, by the evaluation harness planned in [EVALUATION.md](EVALUATION.md). These tests prove behaviour, not translation quality.
