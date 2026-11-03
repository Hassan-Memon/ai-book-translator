# TranslateBook AI — frontend

React 19 + TypeScript + Vite 8, Tailwind CSS v4, React Router, TanStack Query.
Talks to the FastAPI backend described in `../docs/API.md`.

## Run in development

```bash
npm install
npm run dev          # http://localhost:5173 — proxies /api and /health to http://localhost:8010
```

The backend must be running on port 8010 (`make api` in the repo root, or `uv run uvicorn app.main:app --port 8010 --loop app.core.eventloop:new_event_loop` from `backend/`).

## Build for production

```bash
npm run build        # tsc -b && vite build → dist/
npm run preview      # serve dist/ locally
npm run lint         # oxlint
```

`dist/` is served by FastAPI at `/` in production, so the API and UI share one origin.

## Screens

- `/` Books: list + upload modal (PDF, title, language pair).
- `/books/:id` Overview: chunk progress, jobs (live polling), translate/export/delete, LLM cost, glossary.
- `/books/:id/review` Review: chunk list with filters, side-by-side source/translation (RTL-aware), verification suggestions, terminology flags. Shortcuts: `j`/`k` next/prev, `a` approve, `e` edit.
