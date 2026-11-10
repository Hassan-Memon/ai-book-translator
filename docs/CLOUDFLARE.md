# Cloudflare (free tier)

Put TranslateBook AI on the internet without paying for a server. The web app is served by **Cloudflare Pages**. The API, worker, database and OCR keep running on **your own machine**, reached through a free **Cloudflare Tunnel**.

```
 browser ──https──► translatebook-ai.pages.dev  (Cloudflare Pages, free)
                     ├─ static React app
                     ├─ functions/_middleware.js   password for the whole site
                     └─ functions/api/[[path]].js  forwards /api ─┐
                                                                 │ X-TranslateBook-Key
                     Cloudflare quick tunnel (free) ◄────────────┘
                                │
                     your machine: API :8010 + worker + Postgres + Tesseract + Ollama
```

## Why this split

The backend needs Python with PyMuPDF and Tesseract, PostgreSQL with pgvector, long-running jobs and, for local models, your GPU or CPU. Cloudflare's free tier runs JavaScript Workers and static sites, with no Python packages that need native code, no Postgres and no long jobs. So the free tier hosts what it can (the web app, the password gate and the proxy), and the heavy work stays where the models are. Your books and keys never leave your machine except to the model provider you chose. See [ADR-0015](adr/0015-cloudflare-pages-plus-tunnel.md).

## Security model

1. **Site password.** Every page and API call needs `SITE_PASSWORD` (HTTP Basic auth, with any user name). Only `robots.txt`, `sitemap.xml`, the icons, the manifest and `og.png` are public, so link previews still work. With no password set, the site refuses to serve, unless `ALLOW_PUBLIC=true` is set on purpose.
2. **Shared secret.** The proxy adds `X-TranslateBook-Key: BACKEND_SECRET` to each forwarded call. The API rejects any `/api` call that arrives through Cloudflare or from another machine without `API_SHARED_SECRET`. Knowing the tunnel address is therefore not enough to use your machine. Requests made directly on the machine itself, such as your browser at `http://127.0.0.1:8010`, still work without the key.
3. The site password is removed before the request is forwarded. Cookies are not forwarded either.

The app still has no user accounts. Everyone with the password is an administrator, so share it only with people you trust.

## One-time setup

Requirements: Node.js, a free Cloudflare account and `cloudflared`:

```bash
winget install Cloudflare.cloudflared          # Windows
brew install cloudflared                       # macOS
npx wrangler login                             # once, opens the browser
```

Then, from the repository root:

```bash
python deploy/cloudflare/connect.py setup      # or: make cf-setup
```

This command does five things:

- generates `API_SHARED_SECRET` and a site password, and saves both in `.env` (which is never committed);
- creates the Pages project `translatebook-ai`;
- stores `BACKEND_SECRET` and `SITE_PASSWORD` as encrypted Pages secrets;
- builds the web app and deploys it;
- prints the address and the password.

Use `--password "…"` to choose your own password. Set `CF_PAGES_PROJECT` to use another project name.

**Restart the server once afterwards** so it reads `API_SHARED_SECRET`.

## Every session

```bash
make start                                     # the app on :8010, as usual
python deploy/cloudflare/connect.py            # or: make cf-connect
```

The script runs four steps:

1. It checks that the server answers on `:8010`.
2. It starts a quick tunnel, which gets a fresh `*.trycloudflare.com` address each time.
3. It saves that address as the `BACKEND_URL` secret.
4. It redeploys, which takes about 20 seconds.

Keep the window open; the site is online while it runs. **Ctrl+C** takes it offline, and the site then answers *"The translation server is not connected"*.

## A stable address (optional)

Quick tunnels change address on every start, which is why the script redeploys each time. They also have no uptime guarantee and do not carry Server-Sent Events. The UI falls back to polling every 2 seconds, so progress still updates.

With a domain on your Cloudflare account, you can use a **named tunnel** instead:

```bash
cloudflared tunnel login
cloudflared tunnel create translatebook
cloudflared tunnel route dns translatebook api.example.com
cloudflared tunnel run --url http://127.0.0.1:8010 translatebook   # or install it as a service
python deploy/cloudflare/connect.py set-backend https://api.example.com   # once
```

You can also give Pages your own domain: Pages project → **Custom domains**.

## Free-tier limits that matter

| Limit | Free tier | Effect here |
|---|---|---|
| Pages builds and deploys | 500 per month | One per tunnel start. Plenty |
| Pages Functions requests | 100,000 per day | Each API call counts once. A busy review session makes a few thousand |
| Request body | 100 MB | The largest PDF you can upload through the site |
| Quick tunnel | No SLA, about 200 concurrent requests, no SSE | Fine for a personal or demo instance |

## Troubleshooting

| Symptom | Fix |
|---|---|
| The browser keeps asking for the password | Use the password from `CLOUDFLARE_SITE_PASSWORD` in `.env`. Any user name works |
| `The translation server is not connected` | Run `connect.py`. If it is running, check that the server answers on `:8010` |
| `missing or wrong API key` | Restart the server after `setup` so it reads `API_SHARED_SECRET`. If you changed the secret, run `setup` again |
| `connect.py` says the tunnel did not report an address | Run it with `--verbose` to see the `cloudflared` log. A firewall or proxy may be blocking outbound QUIC or port 7844 |
| Deploy fails with an authentication error | `npx wrangler login` again |

## Files

| File | Role |
|---|---|
| `deploy/cloudflare/connect.py` | `setup`, the tunnel, `set-backend`. Standard library only |
| `deploy/cloudflare/package.json` | Pins the Cloudflare CLI (wrangler), installed on first use |
| `frontend/wrangler.toml` | Pages project name and build output folder |
| `frontend/functions/_middleware.js` | Password gate |
| `frontend/functions/api/[[path]].js`, `frontend/functions/health.js` | Routes forwarded to the backend |
| `frontend/cloudflare/proxy.js` | The forwarding logic |
| `backend/app/main.py` (`require_shared_secret`) | The API side of the shared secret |
