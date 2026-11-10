# Deployment

TranslateBook AI is self-hosted. Choose one of three setups.

## 1. Single machine (laptop or desktop)

The README quickstart: `make setup` once, then `make start`. The API runs the worker inline (`WORKER_INLINE=true`), Postgres runs in Docker on port 5433, and the UI is served at http://127.0.0.1:8010. Pair it with Ollama for a fully offline install.

## 2. Docker Compose (server)

```bash
cp .env.example .env          # set SECRET_KEY to a long random string
docker compose --profile full up --build -d
```

This starts three containers:

| Service | Role |
|---|---|
| `db` | `pgvector/pgvector:pg17`, with data in the `pgdata` volume |
| `api` | Runs migrations, then serves the API and UI on port 8010 (`WORKER_INLINE=false`) |
| `worker` | `python -m app.worker`. Scale with `docker compose up --scale worker=3` |

The image includes Tesseract. Language packs, uploads and exports persist in the `appdata` volume (`/app/backend/data`).

To reach Ollama running on the host from inside Docker, set the server URL in Settings to `http://host.docker.internal:11434` (Docker Desktop) or to the host's LAN address (Linux).

## 3. Your own infrastructure

- **Database:** any PostgreSQL 15+ with the `vector` and `pg_trgm` extensions. Run `uv run alembic upgrade head` on each release.
- **API:** `uvicorn app.main:app --host 0.0.0.0 --port 8010` behind a reverse proxy. Disable buffering on `/api/v1/books/*/events` so Server-Sent Events stream (`X-Accel-Buffering: no` is already sent).
- **Workers:** any number of `python -m app.worker` processes. They coordinate through the job table; no broker is needed.
- **Storage:** `UPLOAD_DIR`, `EXPORT_DIR` and `TESSDATA_DIR` must be shared between the API and the workers (a volume or network disk).

## Production checklist

- [ ] Set `SECRET_KEY`. API keys saved in Settings are encrypted with it, and changing it means re-entering them.
- [ ] Put the app behind HTTPS with authentication (a reverse proxy with SSO or basic auth). The app has **no user accounts yet**; anyone who can reach it can change settings and read books.
- [ ] Restrict `CORS_ORIGINS` to your domain.
- [ ] Back up the database and the upload volume.
- [ ] Raise `LLM_TIMEOUT_SECONDS` if workers use slow local models.
- [ ] Set `OCR_DOWNLOAD_PACKS=false` on air-gapped servers and pre-install the packs into `TESSDATA_DIR`.
- [ ] Monitor `GET /health`, which returns 503 when the database is unreachable.

## Upgrading

```bash
git pull
make install build-frontend   # or rebuild the image
make migrate                  # alembic upgrade head
```

Each release's migrations are listed in [CHANGELOG.md](../CHANGELOG.md).
