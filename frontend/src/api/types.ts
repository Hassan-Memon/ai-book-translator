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
  created_at: string
  updated_at: string
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
}

export interface Health {
  status: string
  version: string
  db: 'ok' | 'error'
}
