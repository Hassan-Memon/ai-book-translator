# Cloudflare (free tier)

Put TranslateBook AI on the internet without paying for a server. A **Cloudflare Worker** serves the web app at `https://translatebook-ai.<your-subdomain>.workers.dev`; the live instance is https://translatebook-ai.hassan-memon.workers.dev. The API, job worker, database and OCR keep running on **your own machine**, reached through a free **Cloudflare Tunnel**.

```
 browser ──https──► translatebook-ai.hassan-memon.workers.dev   (Cloudflare Worker, free)
                     frontend/cloudflare/worker.js
                     ├─ password for the whole site (runs before any file is served)
                     ├─ static React app (frontend/dist, SPA fallback)
                     └─ /api/*, /health ─► proxy.js ─┐  + X-TranslateBook-Key
                                                     │
                     Cloudflare quick tunnel (free) ◄┘
                                │
                     your machine: API :8010 + job worker + Postgres + Tesseract + Ollama
```

## Why this split

The backend needs four things the free tier does not offer:
- Python with PyMuPDF and Tesseract;
- PostgreSQL with pgvector;
- long-running jobs;
- for local models, your GPU or CPU.

The free tier runs JavaScript Workers and static assets. So the free tier hosts what it can, the web app, the password gate and the proxy, and the heavy work stays where the models are. Your books and keys never leave your machine except to the model provider you chose. See [ADR-0015](adr/0015-cloudflare-worker-plus-tunnel.md).

## Security model

1. **Site password.** Every page, script and API call needs `SITE_PASSWORD` (HTTP Basic auth, any user name). `run_worker_first` makes the Worker check it before any static file is served. Only `robots.txt`, `sitemap.xml`, the icons, the manifest and `og.png` are public, so link previews work. With no password set, the site refuses to serve, unless `ALLOW_PUBLIC=true` is set on purpose.
2. **Shared secret.** The proxy adds `X-TranslateBook-Key: BACKEND_SECRET` to each forwarded call. The API rejects any `/api` call that arrives through Cloudflare or from another machine without `API_SHARED_SECRET`. Knowing the tunnel address is therefore not enough to use your machine. Requests made directly on the machine, such as your browser at `http://127.0.0.1:8010`, still work.
3. The site password and cookies are removed before a request is forwarded.

The app still has no user accounts. Everyone with the password is an administrator, so share it only with people you trust.

## One-time setup

Requirements: Node.js, a free Cloudflare account with a workers.dev subdomain, and `cloudflared`:

```bash
winget install Cloudflare.cloudflared          # Windows
brew install cloudflared                       # macOS
cd deploy/cloudflare && npm install && npx wrangler login   # once, opens the browser
```

Then, from the repository root:

```bash
python deploy/cloudflare/connect.py setup      # or: make cf-setup
```

This command:
1. generates `API_SHARED_SECRET` and a site password, and saves both in `.env` (never committed);
2. builds the web app;
3. deploys the Worker `translatebook-ai`;
4. stores `BACKEND_SECRET` and `SITE_PASSWORD` as encrypted Worker secrets;
5. writes the site address to `.env` as `CLOUDFLARE_SITE_URL`.

Use `--password "…"` to choose your own password, and set `CF_WORKER_NAME` for another Worker name, and so another address.

**Restart the server once afterwards** so it reads `API_SHARED_SECRET`.

After a UI change, run `python deploy/cloudflare/connect.py deploy` to rebuild and redeploy.

## Every session

```bash
make start                                     # the app on :8010, as usual
python deploy/cloudflare/connect.py            # or: make cf-connect
```

The script runs three steps:
1. checks that the server answers on `:8010`;
2. starts a quick tunnel, which gets a fresh `*.trycloudflare.com` address each time;
3. saves that address as the Worker's `BACKEND_URL` secret, which takes effect immediately.

Keep the window open; the site is online while it runs. **Ctrl+C** takes it offline, and the site then answers *"The translation server is not connected"*.

## A stable backend address (optional)

Quick tunnels change address on every start, have no uptime guarantee, and do not carry Server-Sent Events. The UI falls back to polling every 2 seconds. With a domain on your Cloudflare account, use a **named tunnel**:

```bash
cloudflared tunnel login
cloudflared tunnel create translatebook
cloudflared tunnel route dns translatebook api.example.com
cloudflared tunnel run --url http://127.0.0.1:8010 translatebook   # or install it as a service
python deploy/cloudflare/connect.py set-backend https://api.example.com   # once
```

A custom domain for the site itself: Workers → `translatebook-ai` → **Domains & Routes**.

## Free-tier limits that matter

| Limit | Free tier | Effect here |
|---|---|---|
| Worker requests | 100,000 per day | Every page load, script and API call counts. A busy session uses a few thousand |
| CPU time | 10 ms per request | The Worker only checks a password and forwards bytes, so it stays far below |
| Request body | 100 MB | The largest PDF you can upload through the site |
| Quick tunnel | No SLA, about 200 concurrent requests, no SSE | Fine for a personal or demo instance |

## Troubleshooting

| Symptom | Fix |
|---|---|
| The browser keeps asking for the password | Use `CLOUDFLARE_SITE_PASSWORD` from `.env`. Any user name works |
| `The translation server is not connected` | Run `connect.py`. If it is running, check that the server answers on `:8010` |
| `missing or wrong API key` | Restart the server after `setup` so it reads `API_SHARED_SECRET` |
| No tunnel address within 60 s | Run `connect.py --verbose`. A firewall may block outbound QUIC or port 7844 |
| Deploy fails with an authentication error | `npx wrangler login` again, from `deploy/cloudflare` |

## Files

| File | Role |
|---|---|
| `deploy/cloudflare/connect.py` | `setup`, `deploy`, the tunnel, `set-backend`. Standard library only |
| `deploy/cloudflare/package.json` | Pins the Cloudflare CLI (wrangler 4.60.0) |
| `frontend/wrangler.toml` | Worker name, static assets, SPA fallback, `run_worker_first` |
| `frontend/cloudflare/worker.js` | Password gate and routing |
| `frontend/cloudflare/proxy.js` | Forwarding to the backend |
| `backend/app/main.py` (`require_shared_secret`) | The API side of the shared secret |
