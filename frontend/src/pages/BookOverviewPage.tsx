import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  deleteBook,
  deleteGlossaryTerm,
  exportDownloadUrl,
  getBook,
  getStats,
  glossaryExportUrl,
  importGlossary,
  listGlossary,
  listJobs,
  startExport,
  startTranslation,
  upsertGlossaryTerm,
} from '../api/client'
import { useBookEvents } from '../api/events'
import { CHUNK_STATUSES, type BookDetail, type Job } from '../api/types'
import { useToast } from '../components/Toast'
import {
  Button,
  Card,
  Empty,
  ErrorBox,
  ProgressBar,
  Spinner,
  StatusBadge,
} from '../components/ui'
import { inputCls } from '../lib/styles'
import { formatDate, humanize, num, pct, usd } from '../lib/format'
import { CHUNK_DOT_COLORS } from '../lib/statuses'
import { langClass, langLabel } from '../lib/lang'

export function BookOverviewPage() {
  const { id = '' } = useParams()
  const [live, setLive] = useState(false)
  const book = useQuery({
    queryKey: ['book', id],
    queryFn: () => getBook(id),
    // SSE drives refreshes while a job runs; polling is the fallback.
    refetchInterval: (q) => (q.state.data?.active_job ? (live ? false : 2000) : 10_000),
  })
  useBookEvents(id, !!book.data?.active_job, setLive)

  if (book.isLoading) return <Spinner />
  if (book.isError) return <ErrorBox error={book.error} />
  if (!book.data) return null
  const b = book.data

  return (
    <div className="space-y-4">
      <Header book={b} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <ChunkBreakdown book={b} />
          <JobsPanel book={b} live={live} />
        </div>
        <div className="space-y-4">
          <ActionsPanel book={b} />
          <StatsPanel bookId={b.id} />
        </div>
      </div>
      <GlossaryPanel book={b} />
    </div>
  )
}

function Header({ book }: { book: BookDetail }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="text-xs text-gray-500">
          <Link to="/" className="hover:underline">
            Books
          </Link>{' '}
          / Overview
        </div>
        <h1 className="text-xl font-semibold">{book.title}</h1>
        <div className="mt-1 text-sm text-gray-600">
          {langLabel(book.source_language)} → {langLabel(book.target_language)} · {book.page_count} pages ·{' '}
          {book.total_chunks} chunks{book.is_scanned ? ' · scanned (OCR)' : ''} · uploaded{' '}
          {formatDate(book.created_at)}
        </div>
        {book.error && <div className="mt-1 text-sm text-red-700">{book.error}</div>}
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge status={book.status} />
        <Link to={`/books/${book.id}/review`}>
          <Button variant="primary">Open review</Button>
        </Link>
      </div>
    </div>
  )
}

function ChunkBreakdown({ book }: { book: BookDetail }) {
  const total = Math.max(1, book.total_chunks)
  return (
    <Card title="Chunk progress">
      <div className="mb-3 flex h-3 w-full overflow-hidden rounded bg-gray-200">
        {CHUNK_STATUSES.map((s) => {
          const n = book.chunk_counts?.[s] ?? 0
          if (!n) return null
          return (
            <div
              key={s}
              className={CHUNK_DOT_COLORS[s]}
              style={{ width: `${(n / total) * 100}%` }}
              title={`${humanize(s)}: ${n}`}
            />
          )
        })}
      </div>
      <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-700">
        {CHUNK_STATUSES.map((s) => (
          <span key={s} className="inline-flex items-center gap-1">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${CHUNK_DOT_COLORS[s]}`} />
            {humanize(s)}: <strong>{book.chunk_counts?.[s] ?? 0}</strong>
          </span>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ProgressBar label="Translated" value={book.percent_translated} />
        <ProgressBar label="Approved" value={book.percent_approved} color="bg-green-500" />
      </div>
    </Card>
  )
}

function JobRow({ job }: { job: Job }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 text-sm">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium capitalize">{humanize(job.kind)}</span>
          <StatusBadge status={job.status} />
          {job.attempts > 1 && <span className="text-xs text-gray-500">attempt {job.attempts}</span>}
        </div>
        <div className="truncate text-xs text-gray-500">
          {job.message ?? ''}
          {job.error && <span className="text-red-600"> {job.error}</span>}
        </div>
      </div>
      <div className="text-right text-xs text-gray-500 whitespace-nowrap">
        <div>{pct(job.progress * 100)}</div>
        <div>{formatDate(job.finished_at ?? job.started_at ?? job.created_at)}</div>
      </div>
    </div>
  )
}

function JobsPanel({ book, live }: { book: BookDetail; live: boolean }) {
  const jobs = useQuery({
    queryKey: ['jobs', book.id],
    queryFn: () => listJobs(book.id),
    refetchInterval: book.active_job && !live ? 2000 : 15_000,
  })
  const active = book.active_job
  return (
    <Card title="Jobs">
      {active && (
        <div className="mb-3 rounded-md border border-blue-200 bg-blue-50 p-3">
          <div className="mb-1 flex items-center justify-between text-sm">
            <span className="font-medium capitalize">
              {humanize(active.kind)} · {humanize(active.status)}
            </span>
            <span className="text-xs text-gray-600">{pct(active.progress * 100)}</span>
          </div>
          <ProgressBar value={active.progress * 100} color="bg-blue-500" />
          {active.message && <div className="mt-1 text-xs text-gray-600">{active.message}</div>}
        </div>
      )}
      {jobs.isLoading && <Spinner />}
      {jobs.isError && <ErrorBox error={jobs.error} />}
      {jobs.data && jobs.data.jobs.length === 0 && <Empty>No jobs yet.</Empty>}
      {jobs.data && jobs.data.jobs.length > 0 && (
        <div className="divide-y divide-gray-100">
          {jobs.data.jobs.map((j) => (
            <JobRow key={j.id} job={j} />
          ))}
        </div>
      )}
    </Card>
  )
}

function ActionsPanel({ book }: { book: BookDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const nav = useNavigate()
  const [pageRange, setPageRange] = useState('')
  const [onlyFailed, setOnlyFailed] = useState(false)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['book', book.id] })
    qc.invalidateQueries({ queryKey: ['jobs', book.id] })
  }

  const translate = useMutation({
    mutationFn: () =>
      startTranslation(book.id, {
        page_range: pageRange.trim() || undefined,
        only_failed: onlyFailed || undefined,
      }),
    onSuccess: () => {
      toast.success('Translation job queued')
      invalidate()
    },
    onError: (e) => toast.error(e),
  })

  const exp = useMutation({
    mutationFn: () => startExport(book.id, 'docx'),
    onSuccess: () => {
      toast.success('Export job queued')
      invalidate()
    },
    onError: (e) => toast.error(e),
  })

  const del = useMutation({
    mutationFn: () => deleteBook(book.id),
    onSuccess: () => {
      toast.success('Book deleted')
      qc.invalidateQueries({ queryKey: ['books'] })
      nav('/')
    },
    onError: (e) => toast.error(e),
  })

  const busy = !!book.active_job
  const canTranslate = book.total_chunks > 0 && !busy

  return (
    <Card title="Actions">
      <div className="space-y-4">
        <div>
          <div className="mb-2 text-xs font-medium text-gray-700">Translation</div>
          <div className="mb-2 flex gap-2">
            <input
              className={inputCls}
              placeholder="Page range, e.g. 10-13 (optional)"
              value={pageRange}
              onChange={(e) => setPageRange(e.target.value)}
            />
          </div>
          <label className="mb-2 flex items-center gap-2 text-xs text-gray-700">
            <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} />
            Only failed chunks
          </label>
          <Button
            variant="primary"
            className="w-full justify-center"
            disabled={!canTranslate || translate.isPending}
            onClick={() => translate.mutate()}
            title={busy ? 'A job is already running' : undefined}
          >
            Start translation
          </Button>
        </div>

        <div>
          <div className="mb-2 text-xs font-medium text-gray-700">Export</div>
          <Button
            className="w-full justify-center"
            disabled={busy || exp.isPending || book.total_chunks === 0}
            onClick={() => exp.mutate()}
          >
            Export DOCX
          </Button>
          {book.latest_export && (
            <a
              href={exportDownloadUrl(book.id)}
              className="mt-2 block text-center text-sm text-indigo-700 hover:underline"
              download
            >
              Download {book.latest_export.file_name}
            </a>
          )}
        </div>

        <div className="border-t border-gray-100 pt-3">
          <Button
            variant="danger"
            className="w-full justify-center"
            disabled={del.isPending}
            onClick={() => {
              if (window.confirm(`Delete "${book.title}" and all its chunks? This cannot be undone.`)) {
                del.mutate()
              }
            }}
          >
            Delete book
          </Button>
        </div>
      </div>
    </Card>
  )
}

function StatsPanel({ bookId }: { bookId: string }) {
  const stats = useQuery({ queryKey: ['stats', bookId], queryFn: () => getStats(bookId), refetchInterval: 10_000 })
  return (
    <Card title="LLM usage & cost">
      {stats.isLoading && <Spinner />}
      {stats.isError && <ErrorBox error={stats.error} />}
      {stats.data && (
        <div className="text-sm">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Stat label="Calls" value={num(stats.data.llm_calls)} />
            <Stat label="Cost" value={usd(stats.data.cost_usd)} />
            <Stat label="Input tokens" value={num(stats.data.input_tokens)} />
            <Stat label="Output tokens" value={num(stats.data.output_tokens)} />
            <Stat
              label="Avg latency"
              value={stats.data.avg_latency_ms == null ? '—' : `${Math.round(stats.data.avg_latency_ms)} ms`}
            />
          </div>
          {stats.data.by_model.length > 0 && (
            <table className="mt-3 w-full text-xs">
              <thead className="text-gray-500">
                <tr>
                  <th className="text-left font-medium">Model</th>
                  <th className="text-right font-medium">Calls</th>
                  <th className="text-right font-medium">Tokens</th>
                  <th className="text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {stats.data.by_model.map((m) => (
                  <tr key={m.model} className="border-t border-gray-100">
                    <td className="py-1 truncate max-w-[10rem]" title={m.model}>
                      {m.model}
                    </td>
                    <td className="py-1 text-right">{num(m.calls)}</td>
                    <td className="py-1 text-right">{num(m.input_tokens + m.output_tokens)}</td>
                    <td className="py-1 text-right">{usd(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-gray-50 p-2">
      <div className="text-gray-500">{label}</div>
      <div className="font-medium text-gray-900">{value}</div>
    </div>
  )
}

function GlossaryPanel({ book }: { book: BookDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [orig, setOrig] = useState('')
  const [trans, setTrans] = useState('')
  const src = langClass(book.source_language)
  const tgt = langClass(book.target_language)

  const glossary = useQuery({ queryKey: ['glossary', book.id], queryFn: () => listGlossary(book.id) })
  const invalidate = () => qc.invalidateQueries({ queryKey: ['glossary', book.id] })

  const add = useMutation({
    mutationFn: () => upsertGlossaryTerm(book.id, { original_term: orig.trim(), translation: trans.trim() }),
    onSuccess: () => {
      setOrig('')
      setTrans('')
      toast.success('Term saved')
      invalidate()
    },
    onError: (e) => toast.error(e),
  })
  const remove = useMutation({
    mutationFn: (termId: string) => deleteGlossaryTerm(book.id, termId),
    onSuccess: invalidate,
    onError: (e) => toast.error(e),
  })
  const imp = useMutation({
    mutationFn: (file: File) => importGlossary(book.id, file),
    onSuccess: (r) => {
      toast.success(`Imported ${r.imported} term(s)`)
      invalidate()
    },
    onError: (e) => toast.error(e),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!orig.trim() || !trans.trim()) {
      toast.error('Both term and translation are required')
      return
    }
    add.mutate()
  }

  return (
    <Card
      title={`Glossary (${glossary.data?.count ?? 0})`}
      actions={
        <>
          <label className="inline-flex cursor-pointer items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-800 hover:bg-gray-50">
            {imp.isPending ? 'Importing…' : 'Import'}
            <input
              type="file"
              accept=".json,.csv,application/json,text/csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) imp.mutate(f)
                e.currentTarget.value = ''
              }}
            />
          </label>
          <a href={glossaryExportUrl(book.id)} download>
            <Button type="button">Export</Button>
          </a>
        </>
      }
    >
      <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <input
          className={`${inputCls} ${src.className}`}
          dir={src.dir}
          placeholder={`Term (${book.source_language})`}
          value={orig}
          onChange={(e) => setOrig(e.target.value)}
        />
        <input
          className={`${inputCls} ${tgt.className}`}
          dir={tgt.dir}
          placeholder={`Translation (${book.target_language})`}
          value={trans}
          onChange={(e) => setTrans(e.target.value)}
        />
        <Button type="submit" variant="primary" disabled={add.isPending}>
          Add
        </Button>
      </form>

      {glossary.isLoading && <Spinner />}
      {glossary.isError && <ErrorBox error={glossary.error} />}
      {glossary.data && glossary.data.terms.length === 0 && (
        <Empty>No glossary terms yet. Decide terminology flags in review, or add terms here.</Empty>
      )}
      {glossary.data && glossary.data.terms.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th className="py-1 text-left font-medium">Term</th>
                <th className="py-1 text-left font-medium">Translation</th>
                <th className="py-1 text-left font-medium">Category</th>
                <th className="py-1 text-left font-medium">Approved</th>
                <th className="py-1 text-right font-medium">Uses</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {glossary.data.terms.map((t) => (
                <tr key={t.id} className="border-t border-gray-100">
                  <td className={`py-1 pe-3 ${src.className}`} dir={src.dir}>
                    {t.original_term}
                  </td>
                  <td className={`py-1 pe-3 ${tgt.className}`} dir={tgt.dir}>
                    {t.translation}
                    {t.with_original_in_brackets && <span className="text-xs text-gray-500"> (+orig)</span>}
                  </td>
                  <td className="py-1 text-xs text-gray-600">{t.category}</td>
                  <td className="py-1 text-xs">{t.human_approved ? '✓' : '—'}</td>
                  <td className="py-1 text-right text-xs text-gray-600">{t.usage_count}</td>
                  <td className="py-1 text-right">
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={() => remove.mutate(t.id)}
                      disabled={remove.isPending}
                    >
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
