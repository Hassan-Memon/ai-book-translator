# ADR-0012: Bring your own key, stored encrypted in the database
Date: 2026-11-09 · Status: accepted (implemented in `core/secrets.py`, `services/settings.py`, `api/routes_settings.py`, migration `002`)

## Context
The product is self-hosted and sold to people who either have their own API key or want to run a model on their own machine. Asking them to edit `.env` and restart is a support burden. The worker may run in a separate process from the API, so a key entered in the UI has to reach the worker without a restart. Keys are secrets and must never be echoed back to a browser.

## Decision
Store the LLM configuration (provider, model, base URL, vision model, temperature, key) as one JSON row in an `app_setting` table, layered over `.env` defaults. Encrypt the key with Fernet. The Fernet key derives from `SECRET_KEY`, or from a random secret generated once into `data/.secret_key`. The API returns only a masked hint. `get_provider()` re-reads the row at most every five seconds and rebuilds the provider when its fingerprint changes. A single catalog (`llm/catalog.py`) describes 13 providers: OpenAI-compatible hosts differ only by base URL, while Anthropic and Ollama have their own clients.

## Alternatives considered
- **`.env` only**: no UI, needs a restart, and cannot reach other workers.
- **OS keychain**: not available in Docker, and not shared between the API and worker containers.
- **Plaintext in the database**: simpler, but a database dump would leak every customer key.
- **Browser-side keys sent with each request**: background jobs run while the browser is closed.

## Consequences
- Easier: paste a key, test it, save it, with no restart. Local runtimes are detected and listed live.
- Harder: losing `SECRET_KEY` means re-entering keys. A multi-user deployment would need per-user settings and auth, which is out of scope today and recorded in the README's "Not yet" column.
