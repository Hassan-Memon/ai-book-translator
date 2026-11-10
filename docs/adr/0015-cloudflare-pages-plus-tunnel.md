# ADR-0015: Cloudflare Pages for the web app, a tunnel to the machine for everything else

**Status:** accepted · 2026-11-10

## Context

Hassan wants the product reachable on the internet using Cloudflare's free tier. The backend needs four things the free tier cannot provide:
- CPython with native packages (PyMuPDF, Tesseract, asyncpg);
- PostgreSQL with pgvector;
- jobs that run for minutes or hours;
- for local models, the machine's own CPU or GPU.

Workers' Python runtime runs on Pyodide without those native packages. Containers and Hyperdrive are paid, or still lack Postgres extensions.

## Decision

- **Cloudflare Pages** (free) serves the built React app. Two Pages Functions sit in front of it:
  - a password gate for the whole site;
  - a proxy that forwards `/api/*` and `/health`.
- The backend keeps running where it already runs and is reached through **Cloudflare Tunnel**. The account has no domain, so this is a quick tunnel; a named tunnel can replace it later.
- The proxy authenticates to the API with a shared secret (`X-TranslateBook-Key`). The API enforces the secret for any request that arrives through Cloudflare or from another host. Requests made directly from the machine itself are exempt, so the local UI keeps working.
- `deploy/cloudflare/connect.py` automates everything. A quick tunnel changes address on each start, so the script stores the new address as a Pages secret and redeploys, which takes about 20 seconds.

## Consequences

- Zero hosting cost. Data stays on the owner's machine, and only the chosen LLM provider sees text.
- The site is online only while the machine and the tunnel run. That is acceptable for a personal or demo instance, but not for a multi-user service.
- Quick tunnels do not carry Server-Sent Events, so the UI's existing polling fallback takes over (2-second refresh).
- A password protects the whole site, so pages are not indexed. A public marketing page would be a separate, static Pages project.
- When the product gains user accounts, the site password becomes optional. The shared secret stays: it is what keeps the tunnel from being an open door.
