# Changelog

## 0.3.1 · 2026-11-10

### Fixed
- The retry prompt now carries each gate finding together with its fix instruction, not only the finding.
- A chunk whose deterministic checks still fail after the last retry no longer shows the reviewer's (possibly lenient) score. Its score is capped at the gate score, and the chunk carries a visible warning.
- Keys for catalog-only providers (Gemini, OpenRouter, Groq, …) set only in `.env` are now read.

### Added
- 19 new tests (68 in total, 83% coverage): small-model scaffolding through the real graph, the full review workflow over HTTP, the provider runtime and language packs, and the v0.3 book endpoints. Coverage now traces greenlets. See docs/TESTING.md.
- Docs: USER_GUIDE, ARCHITECTURE, DEPLOYMENT, TESTING, a docs index, ADR-0003 to ADR-0010, CONTRIBUTING and SECURITY.
- README banner, animated tour and script showcase, built from real output.
- UI: the review editor grows with its text, page and chunk counts are pluralised, and latency shows in seconds or minutes.

## 0.3.0 · 2026-11-09 · "Any language, any model"

### Added
- **Free OCR ladder** (`pipeline/ocr/`). Tesseract CLI → Tesseract in PyMuPDF → EasyOCR → vision model only for pages that score below the threshold. It rebuilds layout (columns, two-page spreads, RTL order, margin furniture), scores quality without a reference, and downloads language packs on demand. Chunks store `ocr_quality` and `ocr_engine`.
- **OCR repair** node: the text model fixes OCR noise in low-quality chunks before translating. Reviewers can toggle between the repaired and raw source.
- **Language registry** with 51 languages: script, direction, Tesseract packs, fonts, terminators and sibling markers. `GET /api/v1/languages`.
- **Language detection** at upload (`POST /api/v1/books/sniff`), with no model.
- **Bring your own key**: a Settings screen for 13 providers (Ollama, LM Studio, any OpenAI-compatible server, OpenAI, Anthropic, Gemini, OpenRouter, Groq, DeepSeek, Mistral, Together, NVIDIA, GitHub Models). Keys are stored encrypted, and the screen offers test connection, live model lists, local-runtime detection and recommended laptop models.
- **Agent strategy by model size**: sentence-aligned translation, tagged output, a deterministic quality gate, candidates, a polish pass, translation memory from approved chunks, and smaller chunks for small models. Fast, balanced and thorough profiles, overridable per book.
- **Per-book domain and translator instructions**, injected into every prompt.
- Robust parsing: `<think>` stripping, JSON repair, a fallback for hosts without structured output, and Ollama JSON mode.
- New prompts: `ocr_cleanup.md`, `polish.md`. Generalised `translation.md` (v3), `verification.md` (v3) and `terminology.md` (v4) for any domain.
- **UI redesign**: design tokens, dark mode, per-script fonts loaded on demand, an upload wizard, a settings page, OCR panels, agent strategy and cost panels, skeleton loaders.
- **SEO**: meta, Open Graph and Twitter cards, JSON-LD, `robots.txt`, `sitemap.xml`, a web manifest and icons, per-page titles.
- Docs: `LOCAL_MODELS.md`, `OCR.md`, `AGENT_STRATEGY.md`, `LANGUAGES.md`, `CONFIGURATION.md`, ADR-0011 to ADR-0013. Screenshots in `docs/images/`.
- Tesseract added to the Docker image and CI.
- 24 new tests (49 in total).

### Changed
- `get_provider()` is async and re-reads UI settings every 5 s, so a key saved in the UI reaches separate worker processes without a restart.
- The DOCX exporter picks font and direction from the registry.
- `langchain-anthropic` and `langchain-ollama` are core dependencies. The `ocr-local` extra is renamed `ocr-neural`.
- The default `.env` provider is `ollama` with `qwen3:8b`.

### Migration
- `alembic upgrade head` applies `002_settings_ocr_quality`, which adds `app_setting`, `book.domain`/`instructions`/`settings`/`ocr_summary` and `chunk.ocr_quality`/`ocr_engine`/`source_clean`.

## 0.2.0 · 2026-11-04
- Postgres job queue, a checkpointed per-chunk LangGraph, a review UI, SSE progress, DOCX export, and a kill-resume test in CI.
