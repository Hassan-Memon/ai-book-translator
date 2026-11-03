import type {
  AppSettings,
  Book,
  BookDetail,
  Chunk,
  ChunkStatus,
  Flag,
  GlossaryTerm,
  Health,
  HumanDecision,
  Job,
  Stats,
} from './types'

const BASE = '/api/v1'

async function parseError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      // FastAPI 422 validation shape
      return body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join('.')}: ${d.msg ?? ''}`)
        .join('; ')
    }
    return JSON.stringify(body)
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) throw new Error(await parseError(res))
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function json(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

// ---- health / settings ----------------------------------------------------

export const getHealth = () => request<Health>('/health')
export const getSettings = () => request<AppSettings>(`${BASE}/settings`)

// ---- books ----------------------------------------------------------------

export const listBooks = () => request<{ books: Book[]; count: number }>(`${BASE}/books`)

export const getBook = (id: string) => request<BookDetail>(`${BASE}/books/${id}`)

export function uploadBook(args: {
  file: File
  title: string
  source_language: string
  target_language: string
}): Promise<Book> {
  const fd = new FormData()
  fd.append('file', args.file)
  fd.append('title', args.title)
  fd.append('source_language', args.source_language)
  fd.append('target_language', args.target_language)
  return request<Book>(`${BASE}/books`, { method: 'POST', body: fd })
}

export const deleteBook = (id: string) => request<void>(`${BASE}/books/${id}`, { method: 'DELETE' })

export const startTranslation = (id: string, body: { page_range?: string; only_failed?: boolean }) =>
  request<{ job: Job }>(`${BASE}/books/${id}/translate`, json('POST', body))

export const startExport = (id: string, format: 'docx' = 'docx') =>
  request<{ job: Job }>(`${BASE}/books/${id}/export`, json('POST', { format }))

export const exportDownloadUrl = (id: string) => `${BASE}/books/${id}/export/download`

export const listJobs = (id: string) => request<{ jobs: Job[] }>(`${BASE}/books/${id}/jobs`)
export const getJob = (jobId: string) => request<Job>(`${BASE}/jobs/${jobId}`)
export const getStats = (id: string) => request<Stats>(`${BASE}/books/${id}/stats`)

// ---- chunks ---------------------------------------------------------------

export function listChunks(
  id: string,
  params: { offset?: number; limit?: number; status?: ChunkStatus | ''; has_pending_flags?: boolean } = {},
) {
  const q = new URLSearchParams()
  q.set('offset', String(params.offset ?? 0))
  q.set('limit', String(params.limit ?? 50))
  if (params.status) q.set('status', params.status)
  if (params.has_pending_flags) q.set('has_pending_flags', 'true')
  return request<{ chunks: Chunk[]; total: number }>(`${BASE}/books/${id}/chunks?${q.toString()}`)
}

export const getChunk = (id: string, index: number) =>
  request<Chunk>(`${BASE}/books/${id}/chunks/${index}`)

export const updateChunk = (id: string, index: number, translated_text: string) =>
  request<Chunk>(`${BASE}/books/${id}/chunks/${index}`, json('PATCH', { translated_text }))

export const approveChunk = (id: string, index: number) =>
  request<Chunk>(`${BASE}/books/${id}/chunks/${index}/approve`, { method: 'POST' })

export const unapproveChunk = (id: string, index: number) =>
  request<Chunk>(`${BASE}/books/${id}/chunks/${index}/unapprove`, { method: 'POST' })

export const retranslateChunk = (id: string, index: number) =>
  request<{ job: Job }>(`${BASE}/books/${id}/chunks/${index}/retranslate`, { method: 'POST' })

export const decideSuggestion = (id: string, index: number, n: number, action: 'accept' | 'reject') =>
  request<Chunk>(`${BASE}/books/${id}/chunks/${index}/suggestions/${n}`, json('POST', { action }))

// ---- terminology ----------------------------------------------------------

export const listFlags = (id: string, pendingOnly = true) =>
  request<{ flags: Flag[]; count: number }>(
    `${BASE}/books/${id}/terminology?pending_only=${pendingOnly ? 'true' : 'false'}`,
  )

export const decideFlag = (
  id: string,
  flagId: string,
  body: { decision: Exclude<HumanDecision, 'pending'>; final_value?: string; apply_to_book?: boolean },
) =>
  request<{ flag: Flag; glossary_term: GlossaryTerm | null }>(
    `${BASE}/books/${id}/terminology/${flagId}/decide`,
    json('POST', body),
  )

// ---- glossary -------------------------------------------------------------

export const listGlossary = (id: string) =>
  request<{ terms: GlossaryTerm[]; count: number }>(`${BASE}/books/${id}/glossary`)

export const upsertGlossaryTerm = (
  id: string,
  body: {
    original_term: string
    translation: string
    category?: string
    notes?: string
    with_original_in_brackets?: boolean
  },
) => request<GlossaryTerm>(`${BASE}/books/${id}/glossary`, json('POST', body))

export const deleteGlossaryTerm = (id: string, termId: string) =>
  request<void>(`${BASE}/books/${id}/glossary/${termId}`, { method: 'DELETE' })

export const glossaryExportUrl = (id: string) => `${BASE}/books/${id}/glossary/export`

export function importGlossary(id: string, file: File) {
  const fd = new FormData()
  fd.append('file', file)
  return request<{ imported: number }>(`${BASE}/books/${id}/glossary/import`, {
    method: 'POST',
    body: fd,
  })
}
