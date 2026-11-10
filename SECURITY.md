# Security

## What the app protects

- **API keys** saved in Settings are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256). The key derives from `SECRET_KEY`, or from a random secret generated once into `backend/data/.secret_key` (gitignored). Keys are never returned by the API; only a masked hint such as `sk-a••••xyz` is.
- **Books and glossaries** stay in your database and upload folder. They are sent only to the model provider you configure. With Ollama or LM Studio, nothing leaves the machine.
- **Uploads** must be PDFs, are stored under a content-hash name, and are served back only as exports.
- **The SPA file server** resolves paths inside `frontend/dist` only.
- **Online through Cloudflare** ([docs/CLOUDFLARE.md](docs/CLOUDFLARE.md)), the whole site requires a password, checked in constant time at Cloudflare's edge. The API accepts calls from outside the machine only with `API_SHARED_SECRET`, which the edge proxy adds. The site password and cookies are not forwarded to your machine.

## What it does not do yet

- **There are no user accounts.** Anyone who can reach the server can read books and change settings, including keys. Bind to `127.0.0.1` (the default), or put it behind an authenticating reverse proxy (or the Cloudflare setup, which adds one password for everyone) before exposing it on a network. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#production-checklist).
- **No rate limiting** on the API.
- **PDF parsing** uses PyMuPDF. Keep it updated (`uv lock --upgrade-package pymupdf`), and treat PDFs from untrusted sources accordingly.

## Reporting a vulnerability

Email hassan.ghaddai@live.com with the details and a way to reproduce. Please do not open a public issue for security problems. You will get an acknowledgement within a few days.
