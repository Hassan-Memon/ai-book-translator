# Documentation

## Using TranslateBook AI

| Guide | For |
|---|---|
| [USER_GUIDE.md](USER_GUIDE.md) | Translating a book end to end: connect a model, upload, review, export. Includes an FAQ |
| [LOCAL_MODELS.md](LOCAL_MODELS.md) | Running free on your laptop: which small model, hardware sizing, Ollama and LM Studio |
| [OCR.md](OCR.md) | How scanned pages are read without a model, the quality score, when to add a vision model |
| [LANGUAGES.md](LANGUAGES.md) | The 51 languages, their fonts, detection, and adding one |
| [CONFIGURATION.md](CONFIGURATION.md) | Every setting, from `.env` and from the Settings screen |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Laptop, Docker Compose, your own servers or Cloudflare, plus a production checklist |
| [CLOUDFLARE.md](CLOUDFLARE.md) | Online for free: the web app on a Cloudflare Worker (`*.workers.dev`) behind a password, the backend on your machine through a tunnel |

## How it works

| Document | For |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, request and job flow, data model, module map |
| [AGENT_STRATEGY.md](AGENT_STRATEGY.md) | The per-chunk agent: every node, the quality gate, and why small models get more scaffolding |
| [API.md](API.md) | REST contract (`/api/v1`) |
| [adr/](adr/README.md) | 15 architecture decision records |
| [../prompts/](../prompts/) | The versioned prompts, each with its changelog |

## Quality

| Document | For |
|---|---|
| [TESTING.md](TESTING.md) | What the 90 tests cover, the latest results and coverage, and how to run them |
| [EVALUATION.md](EVALUATION.md) | How translation quality is measured: chrF++, term adherence, structure, LLM judge |
| [evals/](evals/README.md) | Golden sets, their schema, and how to write items |
| [evals/results/](evals/results/README.md) | Every evaluation run so far, one row each |

## Project

[README](../README.md) · [CHANGELOG](../CHANGELOG.md) · [CONTRIBUTING](../CONTRIBUTING.md) · [SECURITY](../SECURITY.md) · [LICENSE](../LICENSE)
