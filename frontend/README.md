# TranslateBook AI · frontend

React 19 + TypeScript + Vite 8, Tailwind CSS v4, React Router 7, TanStack Query 5. It talks to the FastAPI backend described in [`../docs/API.md`](../docs/API.md).

## Run in development

```bash
npm install
npm run dev          # http://localhost:5173, proxies /api and /health to http://localhost:8010
```

The backend must be running on port 8010 (`make api` in the repo root).

## Build for production

```bash
npm run build        # tsc -b && vite build → dist/
npm run preview      # serve dist/ locally
npm run lint         # oxlint
```

FastAPI serves `dist/` at `/`, so the API and UI share one origin.

## Screens

| Route | Page | What is on it |
|---|---|---|
| `/` | `BooksPage` | Library stats, book cards, an empty-state hero, and the upload wizard (PDF sniff, language pickers grouped by script, domain presets, instructions) |
| `/books/:id` | `BookOverviewPage` | Progress, OCR report, live jobs over SSE, actions, agent strategy, cost ledger, book settings, glossary |
| `/books/:id/review` | `ReviewPage` | Chunk list with filters, side-by-side source and translation in the script's font, OCR quality, suggestions, terminology decisions. Keys: `j`/`k`, `a`, `e` |
| `/settings` | `SettingsPage` | **Model**: provider cards, key entry, test connection, live model list, recommended local models, strategy preview. **OCR**: engines and language packs. **About** |

## Design system

- **Tokens** in `src/index.css` (`--bg`, `--surface`, `--fg`, `--brand`, …) are mapped into Tailwind with `@theme inline`, so utilities such as `bg-surface`, `text-fg-muted` and `border-border` follow the theme.
- **Dark mode** is the `data-theme="dark"` attribute on `<html>`, set before first paint by an inline script in `index.html` and managed by `src/lib/theme.ts`. It follows the OS until the user chooses.
- **Components** in `src/components/ui.tsx`: `Button` (with variants, sizes and a loading state), `Card`, `Field`, `Segmented`, `Pill`, `StatusBadge`, `QualityPill`, `ProgressBar`, `Stat`, `Callout`, `Modal`, `Skeleton`, `Empty` and `Icon` (inline SVG).
- **Script fonts**: `src/lib/lang.ts` reads the language registry from `GET /api/v1/languages`, and `langStyle(code)` returns the font family, direction, size scale and line height. `src/lib/fonts.ts` injects the Google Fonts stylesheet for a family the first time it is needed, so an Urdu book loads Noto Nastaliq Urdu and nothing else.

## SEO and metadata

`index.html` carries the description, keywords, Open Graph and Twitter cards (`public/og.png`, 1200×630), JSON-LD `SoftwareApplication` data, a canonical URL, theme colours and the manifest. `public/` also holds `robots.txt` (which disallows `/api/`), `sitemap.xml`, `manifest.webmanifest` and the icons. `src/lib/useTitle.ts` sets a title and description per page.
