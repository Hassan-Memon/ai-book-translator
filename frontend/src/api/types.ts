// Types mirror docs/API.md (v1).

export type BookStatus =
  | 'uploaded'
  | 'extracting'
  | 'extracted'
  | 'translating'
  | 'review'
  | 'done'
  | 'failed'

export type ChunkStatus =
  | 'pending'
  | 'extracted'
  | 'translated'
  | 'verified'
  | 'terminology_reviewed'
  | 'approved'
  | 'failed'

export const CHUNK_STATUSES: ChunkStatus[] = [
  'pending',
  'extracted',
  'translated',
  'verified',
  'terminology_reviewed',
  'approved',
  'failed',
]

export type ContentType =
  | 'prose'
  | 'heading'
  | 'poetry'
  | 'quranic_verse'
  | 'hadith'
  | 'footnote'
  | 'numbered_list'
  | 'margin_note'

export type JobKind = 'extraction' | 'translation' | 'export' | 'reapply_glossary'
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type HumanDecision = 'pending' | 'accepted' | 'rejected' | 'edited'

export interface OcrSummary {
  pages_ocr: number
  escalated: number
  engines: Record<string, number>
  mean_quality: number | null
}

export interface BookSettings {
  quality_profile?: 'auto' | 'fast' | 'balanced' | 'thorough' | string
  sentence_alignment?: 'auto' | 'on' | 'off' | string
  polish_pass?: 'auto' | 'on' | 'off' | string
  translation_candidates?: number
  verification_threshold?: number
  [key: string]: unknown
}

export interface Book {
  id: string
  title: string
  author: string | null
  source_language: string
  target_language: string
  status: BookStatus
  total_chunks: number
  completed_chunks: number
  page_count: number
  is_scanned: boolean
  error: string | null
  domain: string | null
  instructions: string | null
  settings: BookSettings
  ocr_summary: OcrSummary | null
  created_at: string
  updated_at: string
  percent_translated?: number
  percent_approved?: number
}

export interface Job {
  id: string
  book_id: string
  kind: JobKind
  status: JobStatus
  progress: number
  message: string | null
  error: string | null
  attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface BookDetail extends Book {
  chunk_counts: Record<ChunkStatus, number>
  percent_translated: number
  percent_approved: number
  active_job: Job | null
  latest_export: { job_id: string; file_name: string; created_at: string } | null
}

export interface Suggestion {
  issue: string
  original_span: string
  suggested: string
  severity: 'low' | 'medium' | 'high'
  status: 'pending' | 'accepted' | 'rejected'
}

export interface Verification {
  score: number
  summary: string | null
  suggestions: Suggestion[]
  attempt: number
}

export interface Flag {
  id: string
  chunk_id: string
  chunk_index: number
  term: string
  suggested_translation: string
  category: string
  show_in_brackets: boolean
  rationale: string | null
  human_decision: HumanDecision
  final_value: string | null
  applied_to_book: boolean
  created_at: string
}

export interface Chunk {
  id: string
  book_id: string
  index: number
  raw_text: string
  translated_text: string | null
  format_map: Array<Record<string, unknown>>
  content_type: ContentType
  status: ChunkStatus
  page_start: number
  page_end: number
  quality_score: number | null
  retry_count: number
  human_edited: boolean
  error: string | null
  ocr_quality: number | null
  ocr_engine: string | null
  source_clean: string | null
  verification: Verification | null
  flags: Flag[]
  pending_flags: number
  created_at: string
  updated_at: string
}

export interface GlossaryTerm {
  id: string
  book_id: string | null
  original_term: string
  translation: string
  category: string
  with_original_in_brackets: boolean
  human_approved: boolean
  scope: 'book' | 'global'
  usage_count: number
  notes: string | null
  created_at: string
}

export interface Stats {
  llm_calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  by_model: Array<{
    model: string
    calls: number
    input_tokens: number
    output_tokens: number
    cost_usd: number
  }>
  avg_latency_ms: number | null
}

export interface AppSettings {
  llm_provider: string
  model: string
  worker_inline: boolean
  version: string
  provider_configured: boolean
  provider_label: string
  model_tier: 'small' | 'medium' | 'large' | string
  supports_vision: boolean
  is_local: boolean
  source: 'env' | 'ui' | string
}

export interface Health {
  status: string
  version: string
  db: 'ok' | 'error'
}

// ---- languages ------------------------------------------------------------

export interface LanguageInfo {
  code: string
  name: string
  native: string
  script: string
  rtl: boolean
  tesseract: string[]
  font: string
  font_scale: number
  line_height: number
  terminators: string[]
  markers: string
  spaced: boolean
}

// ---- settings / catalog -----------------------------------------------------

export interface ProviderSpec {
  id: string
  label: string
  kind: 'openai' | 'anthropic' | 'ollama' | 'fake' | string
  base_url: string | null
  needs_key: boolean
  local: boolean
  default_model: string
  models: string[]
  docs_url: string
  key_url: string
  note: string
  custom_base_url: boolean
}

export interface LocalModelRec {
  name: string
  params_b: number
  ram_gb: number
  vision: boolean
  languages: string
  best_for: string
  tags: string[]
}

export interface Strategy {
  profile: string
  tier: string
  sentence_alignment: boolean
  tagged_output: boolean
  gate: boolean
  verify: boolean
  max_retries: number
  polish: boolean
  candidates: number
  memory_examples: number
  terminology: boolean
  chunk_target_chars: number
  ocr_cleanup: string
  ocr_cleanup_threshold: number
  verification_threshold: number
}

export interface LlmSettings {
  provider: string
  provider_label: string
  model: string
  base_url: string | null
  vision_model: string | null
  temperature: number | null
  max_output_tokens: number | null
  api_key_hint: string | null
  has_api_key: boolean
  needs_key: boolean
  is_local: boolean
  model_tier: string
  supports_vision: boolean
  source: string
  configured: boolean
  error: string | null
  catalog?: { providers: ProviderSpec[]; local_recommendations: LocalModelRec[] }
  strategy?: Strategy
}

export interface LlmSettingsBody {
  provider: string
  model?: string | null
  api_key?: string | null
  base_url?: string | null
  vision_model?: string | null
  temperature?: number | null
  max_output_tokens?: number | null
}

export interface LlmTestResult {
  ok: boolean
  stage?: string
  error?: string
  reply?: string
  latency_ms?: number
  model?: string
  supports_vision?: boolean
  model_tier?: string
  is_local?: boolean
}

export interface ModelListing {
  source: 'live' | 'catalog'
  running: boolean | null
  error?: string
  models: Array<{ id: string; tier?: string; vision?: boolean; size_gb?: number; params?: string; family?: string }>
}

export interface OcrStatus {
  engine_setting: string
  engines: Array<{ name: string; label: string; available: boolean; confidence: boolean; hint: string }>
  tessdata_dir: string
  system_tessdata_dirs: string[]
  installed_packs: string[]
  download_packs: boolean
  pack_repo: string
  dpi: number
  escalation_threshold: number
  vision_policy: string
}

export interface SniffResult {
  page_count: number
  has_text_layer: boolean
  language_guess: string | null
  sample: string
  script?: string | null
  ocr_quality?: { score: number } | null
  ocr_engine?: string | null
}
