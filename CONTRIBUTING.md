# Contributing

Thanks for helping. The bar is simple: every change is tested, linted and explained.

## Set up

```bash
make setup        # .env, Postgres in Docker, dependencies, UI build, migrations
make test         # backend tests on a real Postgres
make lint         # ruff + oxlint
make dev          # Vite dev server on :5173, proxying /api to :8010 (run `make api` too)
```

## Ground rules

- **Tests with the change.** Backend tests live in `backend/tests/` and run against the `translatebook_test` database, never a real LLM: use the `fake_provider` fixture. See [docs/TESTING.md](docs/TESTING.md).
- **Lint clean.** Run `make fmt` before committing. CI runs `ruff check`, `ruff format --check`, `oxlint` and a production build.
- **Prompts are versioned.** When you change a file in `prompts/`, bump `version` and add a changelog line (ADR-0003).
- **Decisions get an ADR.** If someone could reasonably have chosen differently, add `docs/adr/00NN-title.md` (the next number is 0014) and list it in `docs/adr/README.md`.
- **Schema changes need a migration** in `backend/alembic/versions/`.
- **New languages** are one line in `backend/app/core/languages.py`. See [docs/LANGUAGES.md](docs/LANGUAGES.md).
- **New providers** are one `ProviderSpec` in `backend/app/llm/catalog.py` if they speak the OpenAI API.

## Pull requests

Describe what changed and why, how you tested it, and any migration. Keep each PR focused on one concern. Screenshots are welcome for UI changes.

## Reporting bugs

Open an issue with the steps to reproduce, what you expected, what happened, the relevant lines from the server log and, if possible, a small PDF that shows the problem. For security issues, see [SECURITY.md](SECURITY.md).
