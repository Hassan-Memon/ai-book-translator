import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  deleteBook,
  deleteGlossaryTerm,
  exportDownloadUrl,
  getBook,
  getSettings,
  getStats,
  getStrategy,
  glossaryExportUrl,
  importGlossary,
  listGlossary,
  listJobs,
  startExport,
  startTranslation,
  updateBook,
  upsertGlossaryTerm,
} from '../api/client'
import { useBookEvents } from '../api/events'
import { CHUNK_STATUSES, type BookDetail, type Job } from '../api/types'
import { useToast } from '../components/Toast'
import {
  Button,
  Callout,
  Card,
  Empty,
  ErrorBox,
  Field,
  Icon,
  Pill,
  ProgressBar,
  QualityPill,
  Segmented,
  Spinner,
  Stat,
  StatusBadge,
} from '../components/ui'
import { duration, formatDate, humanize, num, plural, pct, usd } from '../lib/format'
import { DOMAIN_PRESETS, langLabel, langName, langStyle } from '../lib/lang'
import { CHUNK_DOT_COLORS } from '../lib/statuses'
import { useTitle } from '../lib/useTitle'

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
  useTitle(book.data?.title ?? 'Book')

  if (book.isLoading) return <Spinner />
  if (book.isError) return <ErrorBox error={book.error} />
  if (!book.data) return null
  const b = book.data

  return (
    <div className="space-y-4">
      <Header book={b} />
      {b.status === 'failed' && b.error && (
        <Callout tone="danger" title="This book needs attention">
          {b.error}
        </Callout>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <ChunkBreakdown book={b} />
          {b.is_scanned && <OcrPanel book={b} />}
          <JobsPanel book={b} live={live} />
          <BookSettingsPanel key={`${b.id}:${b.updated_at}`} book={b} />
        </div>
        <div className="space-y-4">
          <ActionsPanel book={b} />
          <StrategyPanel />
          <StatsPanel bookId={b.id} />
        </div>
      </div>
      <GlossaryPanel book={b} />
    </div>
  )
}

function Header({ book }: { book: BookDetail }) {
  const titleStyle = langStyle(book.source_language, 1)
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-xs text-fg-muted">
          <Link to="/" className="hover:underline">
            Books
          </Link>{' '}
          / Overview
        </div>
        <h1 className="text-2xl font-semibold tracking-tight script-text" style={{ fontFamily: titleStyle.fontFamily, fontSize: '1.5rem', lineHeight: 1.5, textAlign: 'start' }} dir="auto">
          {book.title}
        </h1>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-fg-muted">
          {book.author && <span>{book.author} ·</span>}
          <span>
            {langLabel(book.source_language)} → {langLabel(book.target_language)}
          </span>
          <span>· {plural(book.page_count, 'page')}</span>
          <span>· {plural(book.total_chunks, 'chunk')}</span>
          {book.is_scanned && (
            <Pill tone="info">
              <Icon name="scan" size={11} /> scanned
            </Pill>
          )}
          <QualityPill value={book.ocr_summary?.mean_quality} />
          {book.domain && <Pill>{book.domain}</Pill>}
          <span className="text-fg-faint">· uploaded {formatDate(book.created_at)}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge status={book.status} />
        <Link to={`/books/${book.id}/review`}>
          <Button variant="primary">
            <Icon name="edit" /> Open review
          </Button>
        </Link>
      </div>
    </div>
  )
}

function ChunkBreakdown({ book }: { book: BookDetail }) {
  const total = Math.max(1, book.total_chunks)
  return (
    <Card title="Progress" subtitle="Where every chunk of the book is in the pipeline.">
      <div className="mb-3 flex h-3 w-full overflow-hidden rounded-full bg-surface-3">
        {CHUNK_STATUSES.map((s) => {
          const n = book.chunk_counts?.[s] ?? 0
          if (!n) return null
          return <div key={s} className={`${CHUNK_DOT_COLORS[s]} transition-all`} style={{ width: `${(n / total) * 100}%` }} title={`${humanize(s)}: ${n}`} />
        })}
      </div>
      <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
        {CHUNK_STATUSES.map((s) => (
          <span key={s} className="inline-flex items-center gap-1">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${CHUNK_DOT_COLORS[s]}`} />
            {humanize(s)}: <strong className="text-fg">{book.chunk_counts?.[s] ?? 0}</strong>
          </span>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <ProgressBar label="Translated" value={book.percent_translated} />
        <ProgressBar label="Approved" value={book.percent_approved} color="bg-success" />
      </div>
    </Card>
  )
}

function OcrPanel({ book }: { book: BookDetail }) {
  const s = book.ocr_summary
  if (!s) return null
  const engines = Object.entries(s.engines ?? {})
  return (
    <Card
      title="OCR"
      subtitle="Scanned pages were read by the free OCR ladder. Quality is estimated without a reference text; poor chunks are marked in review."
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Pages OCRed" value={num(s.pages_ocr)} />
        <Stat label="Mean quality" value={s.mean_quality == null ? '—' : `${Math.round(s.mean_quality * 100)}%`} />
        <Stat label="Vision escalations" value={num(s.escalated)} hint="pages re-read by a vision model" />
        <Stat label="Engines" value={engines.map(([e, n]) => `${e} ×${n}`).join(', ') || '—'} />
      </div>
      {s.mean_quality != null && s.mean_quality < 0.7 && (
        <Callout tone="warn" className="mt-3">
          Quality is low on this scan (Nastaliq Urdu and faint prints are hard for Tesseract). Two fixes: configure a
          vision-capable model in <Link to="/settings">Settings</Link> (for example <code>qwen2.5vl:7b</code> on Ollama)
          and re-upload so poor pages escalate, or keep <em>OCR repair</em> on so the text model fixes noise before
          translating.
        </Callout>
      )}
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
          {job.attempts > 1 && <span className="text-xs text-fg-muted">attempt {job.attempts}</span>}
        </div>
        <div className="truncate text-xs text-fg-muted">
          {job.message ?? ''}
          {job.error && <span className="text-danger"> {job.error}</span>}
        </div>
      </div>
      <div className="whitespace-nowrap text-right text-xs text-fg-muted">
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
    <Card title="Jobs" subtitle={live ? 'Live updates over SSE' : undefined}>
      {active && (
        <div className="mb-3 rounded-lg border border-info/30 bg-info-soft p-3">
          <div className="mb-1 flex items-center justify-between text-sm">
            <span className="font-medium capitalize">
              {humanize(active.kind)} · {humanize(active.status)}
            </span>
            <span className="text-xs text-fg-muted">{pct(active.progress * 100)}</span>
          </div>
          <ProgressBar value={active.progress * 100} color="bg-info" />
          {active.message && <div className="mt-1 text-xs text-fg-muted">{active.message}</div>}
        </div>
      )}
      {jobs.isLoading && <Spinner />}
      {jobs.isError && <ErrorBox error={jobs.error} />}
      {jobs.data && jobs.data.jobs.length === 0 && <Empty>No jobs yet.</Empty>}
      {jobs.data && jobs.data.jobs.length > 0 && (
        <div className="divide-y divide-border">
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
      startTranslation(book.id, { page_range: pageRange.trim() || undefined, only_failed: onlyFailed || undefined }),
    onSuccess: () => {
      toast.success('Translation started')
      invalidate()
    },
    onError: (e) => toast.error(e),
  })
  const exp = useMutation({
    mutationFn: () => startExport(book.id, 'docx'),
    onSuccess: () => {
      toast.success('Export started')
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
          <div className="mb-2 text-xs font-medium text-fg-muted">Translate</div>
          <input className="input mb-2" placeholder="Page range, e.g. 10-13 (optional)" value={pageRange} onChange={(e) => setPageRange(e.target.value)} />
          <label className="mb-2 flex items-center gap-2 text-xs text-fg-muted">
            <input type="checkbox" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} />
            Only failed chunks
          </label>
          <Button variant="primary" className="w-full" disabled={!canTranslate} loading={translate.isPending} onClick={() => translate.mutate()} title={busy ? 'A job is already running' : undefined}>
            <Icon name="play" /> Start translation
          </Button>
        </div>
        <div>
          <div className="mb-2 text-xs font-medium text-fg-muted">Export</div>
          <Button className="w-full" disabled={busy || book.total_chunks === 0} loading={exp.isPending} onClick={() => exp.mutate()}>
            <Icon name="file" /> Export DOCX
          </Button>
          {book.latest_export && (
            <a href={exportDownloadUrl(book.id)} className="mt-2 flex items-center justify-center gap-1 text-sm text-brand hover:underline" download>
              <Icon name="download" size={14} /> {book.latest_export.file_name}
            </a>
          )}
        </div>
        <div className="border-t border-border pt-3">
          <Button
            variant="danger"
            className="w-full"
            loading={del.isPending}
            onClick={() => {
              if (window.confirm(`Delete "${book.title}" and all its chunks? This cannot be undone.`)) del.mutate()
            }}
          >
            <Icon name="trash" /> Delete book
          </Button>
        </div>
      </div>
    </Card>
  )
}

function StrategyPanel() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 15_000 })
  const strat = useQuery({ queryKey: ['strategy'], queryFn: () => getStrategy(), staleTime: 15_000 })
  const s = strat.data?.strategy
  return (
    <Card title="Agent strategy" subtitle="Chosen from the model's size. Smaller models get more scaffolding.">
      {!s && <Spinner />}
      {s && (
        <div className="space-y-2 text-xs">
          <div className="flex flex-wrap gap-1.5">
            <Pill tone="brand">{settings.data?.model ?? strat.data?.model}</Pill>
            <Pill>{s.tier} model</Pill>
            <Pill tone="info">{s.profile}</Pill>
          </div>
          <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-fg-muted">
            <Li on={s.sentence_alignment}>sentence alignment</Li>
            <Li on={s.gate}>deterministic gate</Li>
            <Li on={s.verify}>LLM review</Li>
            <Li on={s.polish}>polish pass</Li>
            <Li on={s.candidates > 1}>{s.candidates} candidates</Li>
            <Li on={s.memory_examples > 0}>{s.memory_examples} memory examples</Li>
            <Li on={s.terminology}>terminology flags</Li>
            <Li on={s.ocr_cleanup !== 'off'}>OCR repair ({s.ocr_cleanup})</Li>
          </ul>
          <div className="text-fg-faint">
            retries ≤ {s.max_retries} · chunk ≈ {s.chunk_target_chars} chars · verify ≥ {s.verification_threshold}
          </div>
        </div>
      )}
    </Card>
  )
}

function Li({ on, children }: { on: boolean; children: React.ReactNode }) {
  return (
    <li className={`flex items-center gap-1 ${on ? 'text-fg' : 'line-through opacity-60'}`}>
      <Icon name={on ? 'check' : 'x'} size={12} className={on ? 'text-success' : 'text-fg-faint'} />
      {children}
    </li>
  )
}

function StatsPanel({ bookId }: { bookId: string }) {
  const stats = useQuery({ queryKey: ['stats', bookId], queryFn: () => getStats(bookId), refetchInterval: 10_000 })
  return (
    <Card title="LLM usage & cost" subtitle="Every call is on the ledger. Local models cost $0.">
      {stats.isLoading && <Spinner />}
      {stats.isError && <ErrorBox error={stats.error} />}
      {stats.data && (
        <div className="text-sm">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Calls" value={num(stats.data.llm_calls)} />
            <Stat label="Cost" value={usd(stats.data.cost_usd)} />
            <Stat label="Input tokens" value={num(stats.data.input_tokens)} />
            <Stat label="Output tokens" value={num(stats.data.output_tokens)} />
          </div>
          <div className="mt-2 text-xs text-fg-muted">
            avg latency {duration(stats.data.avg_latency_ms)} per call
          </div>
          {stats.data.by_model.length > 0 && (
            <table className="mt-3 w-full text-xs">
              <thead className="text-fg-faint">
                <tr>
                  <th className="text-left font-medium">Model</th>
                  <th className="text-right font-medium">Calls</th>
                  <th className="text-right font-medium">Tokens</th>
                  <th className="text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {stats.data.by_model.map((m) => (
                  <tr key={m.model} className="border-t border-border">
                    <td className="max-w-[10rem] truncate py-1" title={m.model}>
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

function BookSettingsPanel({ book }: { book: BookDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [domain, setDomain] = useState(book.domain ?? '')
  const [instructions, setInstructions] = useState(book.instructions ?? '')
  const [profile, setProfile] = useState<string>((book.settings?.quality_profile as string) || 'auto')
  const [alignment, setAlignment] = useState<string>((book.settings?.sentence_alignment as string) || 'auto')

  const dirty =
    domain !== (book.domain ?? '') ||
    instructions !== (book.instructions ?? '') ||
    profile !== ((book.settings?.quality_profile as string) || 'auto') ||
    alignment !== ((book.settings?.sentence_alignment as string) || 'auto')

  const save = useMutation({
    mutationFn: () =>
      updateBook(book.id, {
        domain,
        instructions,
        settings: { ...book.settings, quality_profile: profile, sentence_alignment: alignment },
      }),
    onSuccess: () => {
      toast.success('Book settings saved; they apply to the next translation run')
      qc.invalidateQueries({ queryKey: ['book', book.id] })
    },
    onError: (e) => toast.error(e),
  })

  return (
    <Card
      title="Book settings"
      subtitle="Domain and instructions go into every prompt. Profile and alignment override the app defaults for this book."
      actions={
        <Button variant="primary" size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
      }
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="Domain">
          <input className="input" list="domain-presets-overview" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="general literature and non-fiction" />
          <datalist id="domain-presets-overview">
            {DOMAIN_PRESETS.map((d) => (
              <option key={d} value={d} />
            ))}
          </datalist>
        </Field>
        <div className="grid grid-cols-1 gap-3">
          <Field label="Quality profile" hint="auto = thorough for small models, balanced otherwise">
            <Segmented
              value={profile}
              onChange={setProfile}
              size="sm"
              options={[
                { value: 'auto', label: 'auto' },
                { value: 'fast', label: 'fast', title: 'translate only' },
                { value: 'balanced', label: 'balanced', title: 'translate + checks + review' },
                { value: 'thorough', label: 'thorough', title: '+ retries, polish, candidates' },
              ]}
            />
          </Field>
          <Field label="Sentence alignment" hint="numbered sentences in and out; catches omissions">
            <Segmented
              value={alignment}
              onChange={setAlignment}
              size="sm"
              options={[
                { value: 'auto', label: 'auto' },
                { value: 'on', label: 'on' },
                { value: 'off', label: 'off' },
              ]}
            />
          </Field>
        </div>
        <Field label="Instructions for the translator" className="md:col-span-2">
          <textarea className="input min-h-20 resize-y" value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Formal register. Keep Quranic verses in Arabic. Render names of scholars in standard transliteration…" />
        </Field>
      </div>
    </Card>
  )
}

function GlossaryPanel({ book }: { book: BookDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [orig, setOrig] = useState('')
  const [trans, setTrans] = useState('')
  const src = langStyle(book.source_language, 0.95)
  const tgt = langStyle(book.target_language, 0.95)

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
    if (!orig.trim() || !trans.trim()) return toast.error('Both term and translation are required')
    add.mutate()
  }

  return (
    <Card
      title={`Glossary (${glossary.data?.count ?? 0})`}
      subtitle="Decided once, applied in every prompt. Decide terminology flags in review or add terms here."
      actions={
        <>
          <label className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-border-strong bg-surface px-3 py-1.5 text-xs font-medium text-fg hover:bg-surface-2">
            <Icon name="upload" size={14} /> {imp.isPending ? 'Importing…' : 'Import'}
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
            <Button type="button" size="sm">
              <Icon name="download" size={14} /> Export
            </Button>
          </a>
        </>
      }
    >
      <form onSubmit={submit} className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <input className="input script-text" style={src} dir={src.dir} placeholder={`Term (${langName(book.source_language)})`} value={orig} onChange={(e) => setOrig(e.target.value)} />
        <input className="input script-text" style={tgt} dir={tgt.dir} placeholder={`Translation (${langName(book.target_language)})`} value={trans} onChange={(e) => setTrans(e.target.value)} />
        <Button type="submit" variant="primary" loading={add.isPending}>
          Add
        </Button>
      </form>

      {glossary.isLoading && <Spinner />}
      {glossary.isError && <ErrorBox error={glossary.error} />}
      {glossary.data && glossary.data.terms.length === 0 && <Empty>No glossary terms yet.</Empty>}
      {glossary.data && glossary.data.terms.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-fg-faint">
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
                <tr key={t.id} className="border-t border-border">
                  <td className="py-1 pe-3 script-text" style={src} dir={src.dir}>
                    {t.original_term}
                  </td>
                  <td className="py-1 pe-3 script-text" style={tgt} dir={tgt.dir}>
                    {t.translation}
                    {t.with_original_in_brackets && <span className="text-xs text-fg-faint"> (+orig)</span>}
                  </td>
                  <td className="py-1 text-xs text-fg-muted">{t.category}</td>
                  <td className="py-1 text-xs">{t.human_approved ? <Icon name="check" size={14} className="text-success" /> : '—'}</td>
                  <td className="py-1 text-right text-xs text-fg-muted">{t.usage_count}</td>
                  <td className="py-1 text-right">
                    <button className="text-xs text-danger hover:underline" onClick={() => remove.mutate(t.id)} disabled={remove.isPending}>
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
