# Configuration

There are two layers:

1. **`.env`** sets the defaults for a fresh install. [`.env.example`](../.env.example) documents every variable.
2. **The Settings screen** sets the model provider, model, API key, server URL and vision model. Values saved there are stored in the database and **override `.env`**. **Reset to .env** removes them.

Per-book settings (domain, instructions, quality profile, sentence alignment) live on the book and override both layers for that book.

## API keys

Keys pasted in Settings are encrypted with Fernet before they are stored. The encryption key comes from `SECRET_KEY` in `.env`. When `SECRET_KEY` is empty, a random key is generated once into `backend/data/.secret_key`, which is gitignored. Keys are never returned to the browser, only a masked hint such as `sk-a••••xyz`. If you change `SECRET_KEY`, you only need to re-enter your keys. Set `SECRET_KEY` explicitly for any shared or production deployment. Details: [ADR-0012](adr/0012-bring-your-own-key.md).

A worker running in a separate process picks up a change made in Settings within five seconds, with no restart.

## Providers

| `LLM_PROVIDER` | Key variable | Default model |
|---|---|---|
| `ollama` | none | `qwen3:8b` |
| `lmstudio` | none | (the model loaded in LM Studio) |
| `openai_compatible` | `OPENAI_COMPATIBLE_API_KEY` (optional) | (set `OPENAI_COMPATIBLE_MODEL`) |
| `github` | `GITHUB_TOKEN` | `openai/gpt-4.1` |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| `openrouter` | `OPENROUTER_API_KEY` | `google/gemini-2.5-flash` |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `mistral` | `MISTRAL_API_KEY` | `mistral-large-latest` |
| `together` | `TOGETHER_API_KEY` | `Qwen/Qwen2.5-72B-Instruct-Turbo` |
| `nvidia` | `NVIDIA_API_KEY` | `meta/llama-3.3-70b-instruct` |
| `fake` | none | Deterministic placeholders (demo mode and tests) |

For providers without a dedicated model variable, set `<PROVIDER>_MODEL`, for example `GEMINI_MODEL=gemini-2.5-pro`. If the configured provider has no key, the app logs a warning and runs in demo mode.

`VISION_MODEL` optionally names a separate multimodal model used only for OCR of poor scanned pages.

## Agent strategy

| Variable | Default | Meaning |
|---|---|---|
| `QUALITY_PROFILE` | `auto` | `auto`, `fast`, `balanced` or `thorough`. `auto` means thorough for small models and balanced otherwise |
| `SENTENCE_ALIGNMENT` | `auto` | `auto` (small and medium models), `on` or `off` |
| `TRANSLATION_CANDIDATES` | `1` | Samples per chunk; the gate keeps the best |
| `TRANSLATION_MEMORY_EXAMPLES` | `3` | Approved chunks used as examples |
| `POLISH_PASS` | `auto` | `auto`, `on` or `off` |
| `VERIFICATION_THRESHOLD` | `0.8` | A reviewer score below this triggers a retry |
| `MAX_TRANSLATION_RETRIES` | `1` | Retries in the balanced profile |
| `CHUNK_TARGET_CHARS` | `1200` | Soft chunk size; smaller models get less automatically |
| `TRANSLATION_CONCURRENCY` | `3` | Chunks in flight; use 1 for local models |
| `PASSTHROUGH_CONTENT_TYPES` | `quranic_verse` | Content copied untouched |

See [AGENT_STRATEGY.md](AGENT_STRATEGY.md).

## OCR

See [OCR.md](OCR.md#settings).

## LLM call limits

| Variable | Default |
|---|---|
| `LLM_TEMPERATURE` | `0.2` |
| `LLM_TIMEOUT_SECONDS` | `120` (raise it to 600 for slow CPU inference) |
| `LLM_MAX_RETRIES` | `3` (on 429, 5xx and timeouts) |
| `LLM_MAX_OUTPUT_TOKENS` | `4000` |

## Infrastructure

| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://translatebook:translatebook@localhost:5433/translatebook_v2` |
| `API_HOST`, `API_PORT` | `127.0.0.1`, `8010` |
| `WORKER_INLINE` | `true` (the API process also runs the worker) |
| `CHECKPOINTER` | `postgres` (`memory` or `none`) |
| `JOB_STALE_SECONDS` | `600` |
| `UPLOAD_DIR`, `EXPORT_DIR`, `TESSDATA_DIR` | `./data/uploads`, `./data/exports`, `./data/tessdata` |
| `SECRET_KEY` | auto-generated |
| `API_SHARED_SECRET` | empty. When set, `/api` calls that arrive through Cloudflare or from another machine must send it in `X-TranslateBook-Key`. Direct calls on the machine itself are exempt. Set by `deploy/cloudflare/connect.py setup` ([CLOUDFLARE.md](CLOUDFLARE.md)) |
| `CLOUDFLARE_SITE_PASSWORD` | written by `connect.py setup`, for your reference. The live value is a Pages secret |
| `LOG_LEVEL` | `INFO` |
