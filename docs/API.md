# API contract (v1)

Backend listens on **http://localhost:8010** (port 8000 is taken by another project on this
machine). All JSON. Base path `/api/v1`. The built frontend is served by FastAPI at `/`; in dev,
Vite on 5173 proxies `/api` and `/health` to 8010.

Enums (strings):
- `book.status`: `uploaded | extracting | extracted | translating | review | done | failed`
- `chunk.status`: `pending | extracted | translated | verified | terminology_reviewed | approved | failed`
- `chunk.content_type`: `prose | heading | poetry | quranic_verse | hadith | footnote | numbered_list | margin_note`
- `job.kind`: `extraction | translation | export | reapply_glossary` · `job.status`: `queued | running | succeeded | failed`
- `flag.human_decision`: `pending | accepted | rejected | edited`

## Shapes

```ts
type Book = { id: string; title: string; author: string | null; source_language: string; target_language: string;
  status: BookStatus; total_chunks: number; completed_chunks: number; page_count: number; is_scanned: boolean;
  error: string | null; created_at: string; updated_at: string }

type BookDetail = Book & {
  chunk_counts: Record<ChunkStatus, number>;      // every status key present, 0 if none
  percent_translated: number;                      // 0..100, chunks with a translation
  percent_approved: number;                        // 0..100
  active_job: Job | null;                          // queued/running job if any
  latest_export: { job_id: string; file_name: string; created_at: string } | null }

type Job = { id: string; book_id: string; kind: JobKind; status: JobStatus; progress: number; // 0..1
  message: string | null; error: string | null; attempts: number; created_at: string;
  started_at: string | null; finished_at: string | null }

type Suggestion = { issue: string; original_span: string; suggested: string; severity: "low"|"medium"|"high";
  status: "pending" | "accepted" | "rejected" }

type Verification = { score: number; summary: string | null; suggestions: Suggestion[]; attempt: number } | null

type Flag = { id: string; chunk_id: string; chunk_index: number; term: string; suggested_translation: string;
  category: string; show_in_brackets: boolean; rationale: string | null; human_decision: HumanDecision;
  final_value: string | null; applied_to_book: boolean; created_at: string }

type Chunk = { id: string; book_id: string; index: number; raw_text: string; translated_text: string | null;
  format_map: Array<Record<string, unknown>>; content_type: ContentType; status: ChunkStatus;
  page_start: number; page_end: number; quality_score: number | null; retry_count: number;
  human_edited: boolean; error: string | null; verification: Verification; flags: Flag[];
  pending_flags: number; created_at: string; updated_at: string }

type GlossaryTerm = { id: string; book_id: string | null; original_term: string; translation: string;
  category: string; with_original_in_brackets: boolean; human_approved: boolean; scope: "book"|"global";
  usage_count: number; notes: string | null; created_at: string }

type Stats = { llm_calls: number; input_tokens: number; output_tokens: number; cost_usd: number;
  by_model: Array<{ model: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number }>;
  avg_latency_ms: number | null }

type AppSettings = { llm_provider: string; model: string; worker_inline: boolean; version: string;
  provider_configured: boolean; provider_label: string; model_tier: "small"|"medium"|"large";
  supports_vision: boolean; is_local: boolean; source: "env"|"ui" }

// Book also carries: domain, instructions, settings (per-book strategy overrides), ocr_summary
// Chunk also carries: ocr_quality (0..1 | null), ocr_engine, source_clean (OCR-repaired source)

type LlmSettings = { provider; provider_label; model; base_url; vision_model; temperature; max_output_tokens;
  api_key_hint: string | null /* masked, never the key */; has_api_key; needs_key; is_local; model_tier;
  supports_vision; source; configured; error; catalog?: {providers, local_recommendations}; strategy?: Strategy }

type Strategy = { profile; tier; sentence_alignment; tagged_output; gate; verify; max_retries; polish;
  candidates; memory_examples; terminology; chunk_target_chars; ocr_cleanup; ocr_cleanup_threshold;
  verification_threshold }
```

## Endpoints

| Method | Path | Body / query | Returns |
|--------|------|--------------|---------|
| GET | `/health` | | `{status:"ok", version, db:"ok"|"error"}` |
| GET | `/api/v1/settings` | | `AppSettings` (effective provider summary) |
| GET | `/api/v1/settings/llm` | | `LlmSettings` + provider catalog + strategy |
| PUT | `/api/v1/settings/llm` | `{provider, model?, api_key?, base_url?, vision_model?, temperature?, max_output_tokens?}` (`api_key` omitted = keep, `""` = clear) | `LlmSettings` |
| DELETE | `/api/v1/settings/llm` | | 204 (back to `.env` defaults) |
| POST | `/api/v1/settings/llm/test` | same body as PUT (not saved) | `{ok, reply?, latency_ms?, model_tier?, supports_vision?, is_local?, stage?, error?}` |
| GET | `/api/v1/settings/llm/models` | `provider`, `base_url?` | `{source: "live"\|"catalog", running, models: [{id, tier, vision, size_gb?}]}` |
| GET | `/api/v1/settings/local-runtimes` | | `{runtimes: [{provider, url, models}]}` (Ollama / LM Studio answering now) |
| GET | `/api/v1/settings/ocr` | | OCR engines, installed packs, thresholds |
| GET | `/api/v1/languages` | | `{languages: Language[]}` (the registry) |
| GET | `/api/v1/strategy` | `model?` | `{model, strategy: Strategy}` |
| POST | `/api/v1/books/sniff` | multipart `file` (pdf) | `{page_count, has_text_layer, language_guess, sample, script?, ocr_quality?, ocr_engine?}` (nothing stored) |
| POST | `/api/v1/books` | multipart: `file` (pdf), `title`, `author?`, `source_language`="ur", `target_language`="ar", `domain?`, `instructions?` | 201 `Book` (status `uploaded`; extraction job queued). 400 on unknown language codes |
| PATCH | `/api/v1/books/{id}` | `{title?, author?, domain?, instructions?, settings?}` | `BookDetail` |
| GET | `/api/v1/books` | | `{books: Book[], count}` |
| GET | `/api/v1/books/{id}` | | `BookDetail` |
| DELETE | `/api/v1/books/{id}` | | 204 |
| POST | `/api/v1/books/{id}/translate` | `{page_range?: "10-13", only_failed?: boolean}` | 202 `{job: Job}` (400 if a job is already active or no chunks) |
| POST | `/api/v1/books/{id}/export` | `{format: "docx"}` | 202 `{job: Job}` |
| GET | `/api/v1/books/{id}/export/download` | | DOCX file (404 if none) |
| GET | `/api/v1/books/{id}/jobs` | | `{jobs: Job[]}` newest first |
| GET | `/api/v1/jobs/{job_id}` | | `Job` |
| GET | `/api/v1/books/{id}/events` | | SSE stream: `progress` (snapshot: status, chunk_counts, percents, active_job) on every change, then `idle` and close when no job is active |
| GET | `/api/v1/books/{id}/stats` | | `Stats` |
| GET | `/api/v1/books/{id}/chunks` | `offset`=0, `limit`=50 (max 200), `status?`, `has_pending_flags?` | `{chunks: Chunk[], total}` |
| GET | `/api/v1/books/{id}/chunks/{index}` | | `Chunk` |
| PATCH | `/api/v1/books/{id}/chunks/{index}` | `{translated_text}` | `Chunk` (sets `human_edited`) |
| POST | `/api/v1/books/{id}/chunks/{index}/approve` | | `Chunk` (idempotent) |
| POST | `/api/v1/books/{id}/chunks/{index}/unapprove` | | `Chunk` |
| POST | `/api/v1/books/{id}/chunks/{index}/retranslate` | | 202 `{job: Job}` |
| POST | `/api/v1/books/{id}/chunks/{index}/suggestions/{n}` | `{action: "accept"|"reject"}` | `Chunk` (accept replaces `original_span` with `suggested` in the translation) |
| GET | `/api/v1/books/{id}/terminology` | `pending_only`=true | `{flags: Flag[], count}` |
| POST | `/api/v1/books/{id}/terminology/{flag_id}/decide` | `{decision: "accepted"|"rejected"|"edited", final_value?: string, apply_to_book?: boolean}` | `{flag: Flag, glossary_term: GlossaryTerm | null}` |
| GET | `/api/v1/books/{id}/glossary` | | `{terms: GlossaryTerm[], count}` |
| POST | `/api/v1/books/{id}/glossary` | `{original_term, translation, category?, notes?, with_original_in_brackets?}` | `GlossaryTerm` (upsert on `original_term`) |
| DELETE | `/api/v1/books/{id}/glossary/{term_id}` | | 204 |
| GET | `/api/v1/books/{id}/glossary/export` | | JSON file `[{original_term, translation, category, notes}]` |
| POST | `/api/v1/books/{id}/glossary/import` | multipart `file` (.json array or .csv with header `original_term,translation`) | `{imported: number}` |

Errors: `{detail: string}` with 400/404/409/500. Validation errors: FastAPI 422 shape.

Polling guidance for the UI: while `BookDetail.active_job` is non-null, refetch book detail every
2 s; chunk list every 4 s on the review screen.
