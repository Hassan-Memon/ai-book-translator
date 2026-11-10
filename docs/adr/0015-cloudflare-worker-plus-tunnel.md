# ADR-0015: A Cloudflare Worker for the web app, a tunnel to the machine for everything else

**Status:** accepted · 2026-11-10, revised 2026-11-11 (Pages → Workers)

## Context

Hassan wants the product online on Cloudflare's free tier, at an address in the same style as his other projects (`<name>.hassan-memon.workers.dev`). The backend needs:
- CPython with native packages (PyMuPDF, Tesseract, asyncpg);
- PostgreSQL with pgvector;
- jobs that run for minutes to hours;
- for local models, the machine's own CPU or GPU.

The free tier provides none of these. Workers run JavaScript, and their Python runs on Pyodide without those native packages.

## Decision

- A **Cloudflare Worker with static assets** (free) serves the built React app.
  - `run_worker_first = true` makes the Worker check a site password before any file is served.
  - It forwards `/api/*` and `/health` to the backend.
  - Unknown paths fall back to `index.html` (`not_found_handling = "single-page-application"`).
- The backend stays on the owner's machine and is reached through **Cloudflare Tunnel**. The account has no domain, so this is a quick tunnel; a named tunnel can replace it later.
- The Worker authenticates to the API with a shared secret (`X-TranslateBook-Key`). The API enforces it for any request arriving through Cloudflare or from another host. Requests made directly on the machine are exempt.
- `deploy/cloudflare/connect.py` automates setup and tunnels.

## Why Workers rather than Pages

The first version (2026-11-10) used Pages with Pages Functions. Workers won on three counts:
- **The address.** `*.workers.dev` matches the owner's other projects.
- **No redeploys.** A Worker secret change applies immediately. On Pages, every tunnel start (a new quick-tunnel address) needed a redeploy.
- **Simpler code.** One file (`worker.js`) does the gating and routing, instead of a middleware plus route files.

## Consequences

- Zero hosting cost. Data stays on the owner's machine, and only the chosen LLM provider sees text.
- The site is online only while the machine and the tunnel run. That suits a personal or demo instance, not a multi-user service.
- Quick tunnels do not carry Server-Sent Events, so the UI's polling fallback (2 seconds) takes over.
- A password protects the whole site, so its pages are not indexed. A public marketing page would be a separate static deployment.
- When the product gains user accounts, the site password becomes optional. The shared secret stays: it is what keeps the tunnel from being an open door.
