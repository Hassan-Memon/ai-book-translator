import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import {
  approveChunk,
  decideFlag,
  decideSuggestion,
  getBook,
  getChunk,
  listChunks,
  listFlags,
  retranslateChunk,
  unapproveChunk,
  updateChunk,
} from '../api/client'
import { useBookEvents } from '../api/events'
import { CHUNK_STATUSES, type BookDetail, type Chunk, type ChunkStatus, type Flag, type Suggestion } from '../api/types'
import { useToast } from '../components/Toast'
import { Button, Empty, ErrorBox, Icon, Pill, QualityPill, Segmented, Spinner, StatusBadge } from '../components/ui'
import { humanize } from '../lib/format'
import { langName, langStyle } from '../lib/lang'
import { CHUNK_DOT_COLORS } from '../lib/statuses'
import { useTitle } from '../lib/useTitle'

const PAGE = 200

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

export function ReviewPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const qc = useQueryClient()

  const [status, setStatus] = useState<ChunkStatus | ''>('')
  const [onlyFlags, setOnlyFlags] = useState(false)
  const [pages, setPages] = useState(1)
  const selectedIndex = params.get('chunk') ? Number(params.get('chunk')) : null

  const [live, setLive] = useState(false)
  const book = useQuery({
    queryKey: ['book', id],
    queryFn: () => getBook(id),
    refetchInterval: (q) => (q.state.data?.active_job && !live ? 2000 : false),
  })
  useBookEvents(id, !!book.data?.active_job, setLive)
  const active = !!book.data?.active_job && !live
  useTitle(book.data ? `Review · ${book.data.title}` : 'Review')

  const listQueries = useQuery({
    queryKey: ['chunks', id, status, onlyFlags, pages],
    queryFn: async () => {
      const results = await Promise.all(
        Array.from({ length: pages }, (_, i) =>
          listChunks(id, { offset: i * PAGE, limit: PAGE, status, has_pending_flags: onlyFlags }),
        ),
      )
      return { chunks: results.flatMap((r) => r.chunks), total: results[0]?.total ?? 0 }
    },
    refetchInterval: active ? 4000 : false,
    placeholderData: (prev) => prev,
  })

  const chunksData = listQueries.data?.chunks
  const chunks = useMemo(() => chunksData ?? [], [chunksData])
  const total = listQueries.data?.total ?? 0

  const selectIndex = useCallback(
    (idx: number | null) => {
      const next = new URLSearchParams(params)
      if (idx === null) next.delete('chunk')
      else next.set('chunk', String(idx))
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  useEffect(() => {
    if (selectedIndex === null && chunks.length > 0) selectIndex(chunks[0].index)
  }, [selectedIndex, chunks, selectIndex])

  const chunk = useQuery({
    queryKey: ['chunk', id, selectedIndex],
    queryFn: () => getChunk(id, selectedIndex as number),
    enabled: selectedIndex !== null,
    refetchInterval: active ? 4000 : false,
  })

  const invalidateChunk = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['chunk', id, selectedIndex] })
    qc.invalidateQueries({ queryKey: ['chunks', id] })
    qc.invalidateQueries({ queryKey: ['flags', id] })
    qc.invalidateQueries({ queryKey: ['book', id] })
  }, [qc, id, selectedIndex])

  const approve = useMutation({
    mutationFn: (idx: number) => approveChunk(id, idx),
    onSuccess: () => {
      toast.success('Approved')
      invalidateChunk()
    },
    onError: (e) => toast.error(e),
  })

  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return
      if (selectedIndex === null || chunks.length === 0) return
      const pos = chunks.findIndex((c) => c.index === selectedIndex)
      if (e.key === 'j') {
        const next = chunks[Math.min(chunks.length - 1, pos + 1)]
        if (next) selectIndex(next.index)
      } else if (e.key === 'k') {
        const prev = chunks[Math.max(0, pos - 1)]
        if (prev) selectIndex(prev.index)
      } else if (e.key === 'a') {
        approve.mutate(selectedIndex)
      } else if (e.key === 'e') {
        e.preventDefault()
        textareaRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [chunks, selectedIndex, selectIndex, approve])

  if (book.isLoading) return <Spinner />
  if (book.isError) return <ErrorBox error={book.error} />
  if (!book.data) return null

  return (
    <div className="flex h-[calc(100vh-8.5rem)] flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs text-fg-muted">
            <Link to="/" className="hover:underline">
              Books
            </Link>{' '}
            /{' '}
            <Link to={`/books/${id}`} className="hover:underline">
              {book.data.title}
            </Link>{' '}
            / Review
          </div>
          <h1 className="text-lg font-semibold">
            Review <span className="text-fg-muted">· {langName(book.data.source_language)} → {langName(book.data.target_language)}</span>
          </h1>
        </div>
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <StatusBadge status={book.data.status} />
          {active && <span className="text-info">job running: {humanize(book.data.active_job!.kind)}</span>}
          <span className="hidden sm:inline">
            <kbd>j</kbd>/<kbd>k</kbd> next/prev · <kbd>a</kbd> approve · <kbd>e</kbd> edit
          </span>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[16rem_1fr_20rem]">
        {/* Sidebar */}
        <aside className="card flex min-h-0 flex-col">
          <div className="space-y-2 border-b border-border p-2">
            <select
              className="input"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as ChunkStatus | '')
                setPages(1)
              }}
            >
              <option value="">All statuses</option>
              {CHUNK_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-xs text-fg-muted">
              <input
                type="checkbox"
                checked={onlyFlags}
                onChange={(e) => {
                  setOnlyFlags(e.target.checked)
                  setPages(1)
                }}
              />
              Only with pending flags
            </label>
            <div className="text-xs text-fg-faint">
              {chunks.length} of {total}
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {listQueries.isLoading && <Spinner />}
            {listQueries.isError && (
              <div className="p-2">
                <ErrorBox error={listQueries.error} />
              </div>
            )}
            {!listQueries.isLoading && chunks.length === 0 && (
              <div className="p-2">
                <Empty>No chunks match.</Empty>
              </div>
            )}
            <ul>
              {chunks.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => selectIndex(c.index)}
                    className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs transition hover:bg-surface-2 ${
                      c.index === selectedIndex ? 'bg-brand-soft' : ''
                    }`}
                  >
                    <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${CHUNK_DOT_COLORS[c.status]}`} />
                    <span className="w-10 shrink-0 font-mono text-fg">#{c.index}</span>
                    <span className="min-w-0 flex-1 truncate text-fg-muted">{humanize(c.content_type)}</span>
                    {c.ocr_quality != null && c.ocr_quality < 0.7 && (
                      <span className="shrink-0 text-warn" title={`OCR quality ${Math.round(c.ocr_quality * 100)}%`}>
                        <Icon name="alert" size={12} />
                      </span>
                    )}
                    {c.pending_flags > 0 && (
                      <span className="shrink-0 rounded-full bg-warn-soft px-1.5 text-[10px] font-medium text-warn">{c.pending_flags}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
            {chunks.length < total && (
              <div className="p-2">
                <Button className="w-full" onClick={() => setPages((p) => p + 1)}>
                  Load more
                </Button>
              </div>
            )}
          </div>
        </aside>

        {/* Main pane */}
        <section className="card min-h-0 overflow-y-auto p-4">
          {selectedIndex === null && <Empty>Select a chunk.</Empty>}
          {selectedIndex !== null && chunk.isLoading && <Spinner />}
          {chunk.isError && <ErrorBox error={chunk.error} />}
          {chunk.data && (
            <ChunkEditor
              key={chunk.data.id}
              book={book.data}
              chunk={chunk.data}
              textareaRef={textareaRef}
              onChanged={invalidateChunk}
              onApprove={() => approve.mutate(chunk.data.index)}
              approving={approve.isPending}
            />
          )}
        </section>

        {/* Terminology panel */}
        <aside className="card min-h-0 overflow-y-auto p-3">
          <TerminologyPanel book={book.data} chunk={chunk.data ?? null} onChanged={invalidateChunk} />
        </aside>
      </div>
    </div>
  )
}

function ChunkEditor({
  book,
  chunk,
  textareaRef,
  onChanged,
  onApprove,
  approving,
}: {
  book: BookDetail
  chunk: Chunk
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  onChanged: () => void
  onApprove: () => void
  approving: boolean
}) {
  const toast = useToast()
  const src = langStyle(book.source_language, 1.05)
  const tgt = langStyle(book.target_language, 1.05)
  const [text, setText] = useState(chunk.translated_text ?? '')
  const [sourceView, setSourceView] = useState<'raw' | 'clean'>(chunk.source_clean ? 'clean' : 'raw')
  const dirty = text !== (chunk.translated_text ?? '')

  useEffect(() => {
    if (!dirty) setText(chunk.translated_text ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chunk.translated_text])

  const save = useMutation({
    mutationFn: () => updateChunk(book.id, chunk.index, text),
    onSuccess: () => {
      toast.success('Saved')
      onChanged()
    },
    onError: (e) => toast.error(e),
  })
  const unapprove = useMutation({
    mutationFn: () => unapproveChunk(book.id, chunk.index),
    onSuccess: onChanged,
    onError: (e) => toast.error(e),
  })
  const retranslate = useMutation({
    mutationFn: () => retranslateChunk(book.id, chunk.index),
    onSuccess: () => {
      toast.success('Retranslation queued')
      onChanged()
    },
    onError: (e) => toast.error(e),
  })
  const suggestion = useMutation({
    mutationFn: ({ n, action }: { n: number; action: 'accept' | 'reject' }) => decideSuggestion(book.id, chunk.index, n, action),
    onSuccess: onChanged,
    onError: (e) => toast.error(e),
  })

  const isApproved = chunk.status === 'approved'
  const v = chunk.verification
  const sourceText = sourceView === 'clean' && chunk.source_clean ? chunk.source_clean : chunk.raw_text

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
          <span className="font-mono text-sm text-fg">#{chunk.index}</span>
          <StatusBadge status={chunk.status} />
          <Pill>{humanize(chunk.content_type)}</Pill>
          <span>
            pages {chunk.page_start + 1}
            {chunk.page_end !== chunk.page_start ? `–${chunk.page_end + 1}` : ''}
          </span>
          {chunk.quality_score != null && (
            <Pill tone={chunk.quality_score >= 0.8 ? 'success' : chunk.quality_score >= 0.6 ? 'warn' : 'danger'} title="Reviewer score">
              score {chunk.quality_score.toFixed(2)}
            </Pill>
          )}
          <QualityPill value={chunk.ocr_quality} />
          {chunk.ocr_engine && <span className="text-fg-faint">via {chunk.ocr_engine}</span>}
          {chunk.retry_count > 0 && <span>retries {chunk.retry_count}</span>}
          {chunk.human_edited && <span className="text-brand">human edited</span>}
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => retranslate.mutate()} loading={retranslate.isPending} disabled={!!book.active_job}>
            <Icon name="refresh" size={14} /> Retranslate
          </Button>
          {isApproved ? (
            <Button size="sm" onClick={() => unapprove.mutate()} loading={unapprove.isPending}>
              Unapprove
            </Button>
          ) : (
            <Button size="sm" variant="primary" onClick={onApprove} loading={approving} disabled={!chunk.translated_text}>
              <Icon name="check" size={14} /> Approve
            </Button>
          )}
        </div>
      </div>
      {chunk.error && <div className="rounded-lg border border-danger/30 bg-danger-soft p-2 text-xs text-danger">{chunk.error}</div>}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 flex items-center justify-between text-xs font-medium text-fg-muted">
            <span>Source · {langName(book.source_language)}</span>
            {chunk.source_clean && (
              <Segmented
                size="sm"
                value={sourceView}
                onChange={setSourceView}
                options={[
                  { value: 'clean', label: 'OCR-repaired', title: 'What the translator actually read' },
                  { value: 'raw', label: 'as scanned', title: 'Raw OCR output' },
                ]}
              />
            )}
          </div>
          <div className="min-h-40 whitespace-pre-wrap rounded-lg border border-border bg-surface-2 p-3 script-text" style={src} dir={src.dir}>
            {sourceText}
          </div>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-xs font-medium text-fg-muted">
            <span>Translation · {langName(book.target_language)}</span>
            <span className={dirty ? 'text-warn' : ''}>{dirty ? 'unsaved changes' : ''}</span>
          </div>
          <textarea
            ref={textareaRef}
            className="input min-h-40 w-full resize-y script-text"
            style={tgt}
            dir={tgt.dir}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={chunk.translated_text ? '' : 'Not translated yet'}
          />
          <div className="mt-2 flex justify-end gap-2">
            <Button size="sm" onClick={() => setText(chunk.translated_text ?? '')} disabled={!dirty}>
              Reset
            </Button>
            <Button size="sm" variant="primary" onClick={() => save.mutate()} disabled={!dirty} loading={save.isPending}>
              Save
            </Button>
          </div>
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-fg">Verification</h3>
        {!v && <div className="text-xs text-fg-muted">No verification result yet.</div>}
        {v && (
          <div className="space-y-2">
            <div className="text-xs text-fg-muted">
              score <strong className="text-fg">{v.score.toFixed(2)}</strong> · attempt {v.attempt}
              {v.summary && <span> · {v.summary}</span>}
            </div>
            {v.suggestions.length === 0 && <div className="text-xs text-fg-faint">No suggestions.</div>}
            {v.suggestions.map((s, n) => (
              <SuggestionRow key={n} s={s} tgt={tgt} busy={suggestion.isPending} onDecide={(action) => suggestion.mutate({ n, action })} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SuggestionRow({
  s,
  tgt,
  busy,
  onDecide,
}: {
  s: Suggestion
  tgt: ReturnType<typeof langStyle>
  busy: boolean
  onDecide: (action: 'accept' | 'reject') => void
}) {
  const tone = { low: 'neutral', medium: 'warn', high: 'danger' }[s.severity] as 'neutral' | 'warn' | 'danger'
  return (
    <div className="rounded-lg border border-border p-2 text-sm">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Pill tone={tone}>{s.severity}</Pill>
          <span className="text-xs text-fg-muted">{s.issue}</span>
        </div>
        {s.status === 'pending' ? (
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDecide('accept')}>
              Accept
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDecide('reject')}>
              Reject
            </Button>
          </div>
        ) : (
          <span className={`text-xs ${s.status === 'accepted' ? 'text-success' : 'text-fg-faint'}`}>{s.status}</span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <div className="rounded bg-danger-soft p-1.5 line-through decoration-danger/60 script-text" style={{ ...tgt, fontSize: '0.95rem' }} dir={tgt.dir}>
          {s.original_span}
        </div>
        <div className="rounded bg-success-soft p-1.5 script-text" style={{ ...tgt, fontSize: '0.95rem' }} dir={tgt.dir}>
          {s.suggested}
        </div>
      </div>
    </div>
  )
}

function TerminologyPanel({ book, chunk, onChanged }: { book: BookDetail; chunk: Chunk | null; onChanged: () => void }) {
  const bookFlags = useQuery({
    queryKey: ['flags', book.id],
    queryFn: () => listFlags(book.id, true),
    refetchInterval: book.active_job ? 8000 : false,
  })
  const flagsData = chunk?.flags
  const chunkFlags = useMemo(() => flagsData ?? [], [flagsData])
  const chunkFlagIds = useMemo(() => new Set(chunkFlags.map((f) => f.id)), [chunkFlags])
  const otherPending = (bookFlags.data?.flags ?? []).filter((f) => !chunkFlagIds.has(f.id))

  return (
    <div className="space-y-4">
      <div>
        <h3 className="mb-2 text-sm font-semibold text-fg">
          Terminology · this chunk {chunkFlags.length > 0 && <span className="text-xs text-fg-muted">({chunkFlags.length})</span>}
        </h3>
        {!chunk && <div className="text-xs text-fg-muted">Select a chunk.</div>}
        {chunk && chunkFlags.length === 0 && <div className="text-xs text-fg-faint">No terminology flags.</div>}
        <div className="space-y-2">
          {chunkFlags.map((f) => (
            <FlagCard key={f.id} book={book} flag={f} onChanged={onChanged} />
          ))}
        </div>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold text-fg">
          Book-wide pending {bookFlags.data && <span className="text-xs text-fg-muted">({bookFlags.data.count})</span>}
        </h3>
        {bookFlags.isLoading && <Spinner />}
        {bookFlags.isError && <ErrorBox error={bookFlags.error} />}
        {bookFlags.data && otherPending.length === 0 && <div className="text-xs text-fg-faint">Nothing else pending.</div>}
        <div className="space-y-2">
          {otherPending.slice(0, 50).map((f) => (
            <FlagCard key={f.id} book={book} flag={f} onChanged={onChanged} showChunk />
          ))}
          {otherPending.length > 50 && <div className="text-xs text-fg-faint">…and {otherPending.length - 50} more</div>}
        </div>
      </div>
    </div>
  )
}

function FlagCard({ book, flag, onChanged, showChunk = false }: { book: BookDetail; flag: Flag; onChanged: () => void; showChunk?: boolean }) {
  const toast = useToast()
  const src = langStyle(book.source_language, 0.95)
  const tgt = langStyle(book.target_language, 0.95)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(flag.final_value ?? flag.suggested_translation)
  const [applyAll, setApplyAll] = useState(true)

  const decide = useMutation({
    mutationFn: (body: { decision: 'accepted' | 'rejected' | 'edited'; final_value?: string }) =>
      decideFlag(book.id, flag.id, { ...body, apply_to_book: applyAll }),
    onSuccess: (r) => {
      toast.success(r.glossary_term ? `Saved to glossary: ${r.glossary_term.translation}` : 'Decision recorded')
      setEditing(false)
      onChanged()
    },
    onError: (e) => toast.error(e),
  })

  const decided = flag.human_decision !== 'pending'

  return (
    <div className={`rounded-lg border p-2 text-sm ${decided ? 'border-border bg-surface-2' : 'border-warn/40 bg-warn-soft/40'}`}>
      <div className="mb-1 flex items-center justify-between gap-2 text-[10px] uppercase text-fg-faint">
        <span>{flag.category}</span>
        <span>
          {showChunk && (
            <Link to={`/books/${book.id}/review?chunk=${flag.chunk_index}`} className="text-brand hover:underline">
              #{flag.chunk_index}
            </Link>
          )}
          {decided && <span className="ms-2 normal-case text-fg-muted">{flag.human_decision}</span>}
        </span>
      </div>
      <div className="script-text" style={src} dir={src.dir}>
        {flag.term}
      </div>
      <div className="text-fg script-text" style={tgt} dir={tgt.dir}>
        → {flag.final_value ?? flag.suggested_translation}
        {flag.show_in_brackets && <span className="text-xs text-fg-faint"> (+orig)</span>}
      </div>
      {flag.rationale && <div className="mt-1 text-xs text-fg-muted">{flag.rationale}</div>}

      {!decided && (
        <div className="mt-2 space-y-2">
          {editing && <input className="input script-text" style={tgt} dir={tgt.dir} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />}
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            <input type="checkbox" checked={applyAll} onChange={(e) => setApplyAll(e.target.checked)} />
            Apply to whole book
          </label>
          <div className="flex flex-wrap gap-1">
            {editing ? (
              <>
                <Button variant="primary" size="sm" disabled={!value.trim()} loading={decide.isPending} onClick={() => decide.mutate({ decision: 'edited', final_value: value.trim() })}>
                  Save edit
                </Button>
                <Button size="sm" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button variant="primary" size="sm" loading={decide.isPending} onClick={() => decide.mutate({ decision: 'accepted' })}>
                  Accept
                </Button>
                <Button size="sm" disabled={decide.isPending} onClick={() => setEditing(true)}>
                  Edit
                </Button>
                <Button variant="danger" size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ decision: 'rejected' })}>
                  Reject
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
