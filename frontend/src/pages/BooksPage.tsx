import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type DragEvent, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getSettings, listBooks, sniffPdf, uploadBook } from '../api/client'
import type { Book, LanguageInfo, SniffResult } from '../api/types'
import { useToast } from '../components/Toast'
import {
  Button,
  Callout,
  ErrorBox,
  Field,
  Icon,
  Modal,
  Pill,
  ProgressBar,
  QualityPill,
  Skeleton,
  Stat,
  StatusBadge,
} from '../components/ui'
import { formatDate, num, plural } from '../lib/format'
import { DOMAIN_PRESETS, groupLanguages, langLabel, langName, langStyle, useLanguages } from '../lib/lang'
import { useTitle } from '../lib/useTitle'

export function BooksPage() {
  useTitle(
    'Books',
    'Your library: upload a PDF (text or scanned), pick the languages, and TranslateBook AI extracts, translates, verifies and lets you review.',
  )
  const [open, setOpen] = useState(false)
  const books = useQuery({ queryKey: ['books'], queryFn: listBooks, refetchInterval: 5000 })
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 15_000, retry: 1 })

  const totals = useMemo(() => {
    const list = books.data?.books ?? []
    return {
      books: list.length,
      pages: list.reduce((a, b) => a + (b.page_count || 0), 0),
      chunks: list.reduce((a, b) => a + (b.total_chunks || 0), 0),
      approved: list.reduce((a, b) => a + (b.completed_chunks || 0), 0),
      scanned: list.filter((b) => b.is_scanned).length,
    }
  }, [books.data])

  const empty = books.data && books.data.books.length === 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Books</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Upload a PDF, choose the languages, review the result chunk by chunk, export a DOCX.
          </p>
        </div>
        <Button variant="primary" size="lg" onClick={() => setOpen(true)}>
          <Icon name="upload" /> Upload book
        </Button>
      </div>

      {settings.data && !settings.data.provider_configured && (
        <Callout tone="warn" title="Demo mode: no translation model is configured">
          Translations will be placeholders until you add a model. Open{' '}
          <Link to="/settings" className="font-medium">
            Settings
          </Link>{' '}
          to paste an API key or connect a model running on this machine (Ollama, LM Studio). OCR of scanned pages works
          without any model.
        </Callout>
      )}

      {books.isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card space-y-3 p-4">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-2 w-full" />
              <Skeleton className="h-2 w-full" />
            </div>
          ))}
        </div>
      )}
      {books.isError && <ErrorBox error={books.error} />}

      {empty && <Hero onUpload={() => setOpen(true)} />}

      {books.data && books.data.books.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Stat label="Books" value={num(totals.books)} />
            <Stat label="Pages" value={num(totals.pages)} hint={`${totals.scanned} scanned`} />
            <Stat label="Chunks" value={num(totals.chunks)} />
            <Stat label="Approved" value={num(totals.approved)} hint={totals.chunks ? `${Math.round((100 * totals.approved) / totals.chunks)}% of chunks` : undefined} />
            <Stat
              label="Model"
              value={settings.data ? (settings.data.provider_configured ? settings.data.model : 'none') : '…'}
              hint={settings.data?.is_local ? 'local, free' : settings.data?.provider_label}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {books.data.books.map((b) => (
              <BookCard key={b.id} book={b} />
            ))}
          </div>
        </>
      )}

      <UploadWizard open={open} onClose={() => setOpen(false)} />
    </div>
  )
}

function Hero({ onUpload }: { onUpload: () => void }) {
  const features = [
    { icon: 'scan', title: 'Free OCR for scans', text: 'Tesseract-based ladder with layout, column and reading-order reconstruction in 50+ languages. No model needed.' },
    { icon: 'cpu', title: 'Your model, your key', text: 'Paste an OpenAI, Anthropic, Gemini or OpenRouter key, or run Qwen / Gemma on your own laptop with Ollama.' },
    { icon: 'sparkles', title: 'Agent that checks itself', text: 'Sentence alignment, deterministic quality gate, LLM review with span-level fixes, retry, polish, glossary.' },
    { icon: 'shield', title: 'A human stays in charge', text: 'Side-by-side review, accept fixes, decide terminology once for the whole book, export DOCX.' },
  ]
  return (
    <div className="card fade-up overflow-hidden">
      <div className="grid gap-8 p-8 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <Pill tone="brand">Open source · runs on your machine</Pill>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">
            Translate a whole book, <span className="text-brand">not a paragraph.</span>
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-6 text-fg-muted">
            Scanned PDF in Urdu, Arabic, Persian, Hindi, Chinese or any of 50+ languages → structured chunks → a
            translation agent that verifies and retries its own work → a review screen built for the script → DOCX.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="primary" size="lg" onClick={onUpload}>
              <Icon name="upload" /> Upload your first PDF
            </Button>
            <Link to="/settings">
              <Button size="lg">
                <Icon name="settings" /> Connect a model
              </Button>
            </Link>
          </div>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2">
          {features.map((f) => (
            <li key={f.title} className="rounded-xl border border-border bg-surface-2 p-4">
              <div className="mb-2 grid h-8 w-8 place-items-center rounded-lg bg-brand-soft text-brand">
                <Icon name={f.icon} />
              </div>
              <div className="text-sm font-semibold">{f.title}</div>
              <div className="mt-1 text-xs leading-5 text-fg-muted">{f.text}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function BookCard({ book }: { book: Book }) {
  const approved = book.total_chunks ? (book.completed_chunks / book.total_chunks) * 100 : 0
  const translated =
    book.percent_translated ?? (book.status === 'review' || book.status === 'done' ? 100 : book.status === 'translating' ? approved : 0)
  const titleStyle = langStyle(book.source_language, 1.0)
  return (
    <Link to={`/books/${book.id}`} className="card fade-up block p-4 transition hover:-translate-y-0.5 hover:border-brand/50">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h2 className="line-clamp-2 font-semibold leading-snug text-fg script-text" style={{ fontFamily: titleStyle.fontFamily, fontSize: '1.05rem', lineHeight: 1.6, textAlign: 'start' }} dir="auto">
          {book.title}
        </h2>
        <StatusBadge status={book.status} />
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
        <span>
          {langName(book.source_language)} → {langName(book.target_language)}
        </span>
        {book.is_scanned && (
          <Pill tone="info">
            <Icon name="scan" size={11} /> scanned
          </Pill>
        )}
        <QualityPill value={book.ocr_summary?.mean_quality} />
        {book.domain && <Pill>{book.domain}</Pill>}
      </div>
      <div className="space-y-2">
        <ProgressBar label="Translated" value={translated} size="sm" />
        <ProgressBar label="Approved" value={approved} color="bg-success" size="sm" />
      </div>
      <div className="mt-3 flex justify-between text-xs text-fg-faint">
        <span>
          {plural(book.page_count, 'page')} · {plural(book.total_chunks, 'chunk')}
        </span>
        <span>{formatDate(book.created_at)}</span>
      </div>
      {book.error && <div className="mt-2 truncate text-xs text-danger">{book.error}</div>}
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Upload wizard
// ---------------------------------------------------------------------------

function LanguageSelect({
  value,
  onChange,
  languages,
  exclude,
}: {
  value: string
  onChange: (v: string) => void
  languages: LanguageInfo[]
  exclude?: string
}) {
  const groups = groupLanguages(languages)
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {groups.map((g) => (
        <optgroup key={g.label} label={g.label}>
          {g.items.map((l) => (
            <option key={l.code} value={l.code} disabled={l.code === exclude}>
              {l.name} · {l.native}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

function UploadWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const toast = useToast()
  const languages = useLanguages()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [source, setSource] = useState('ur')
  const [target, setTarget] = useState('ar')
  const [domain, setDomain] = useState('')
  const [instructions, setInstructions] = useState('')
  const [dragging, setDragging] = useState(false)
  const [sniff, setSniff] = useState<SniffResult | null>(null)

  const sniffing = useMutation({
    mutationFn: sniffPdf,
    onSuccess: (r) => {
      setSniff(r)
      if (r.language_guess && r.language_guess !== target) setSource(r.language_guess)
    },
    onError: () => setSniff(null),
  })

  const upload = useMutation({
    mutationFn: uploadBook,
    onSuccess: (book) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      toast.success('Book uploaded; extraction started')
      reset()
      onClose()
      nav(`/books/${book.id}`)
    },
    onError: (e) => toast.error(e),
  })

  function reset() {
    setFile(null)
    setTitle('')
    setAuthor('')
    setDomain('')
    setInstructions('')
    setSniff(null)
  }

  useEffect(() => {
    if (!open) reset()
  }, [open])

  function pick(f: File | undefined | null) {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Only PDF files are supported')
      return
    }
    setFile(f)
    if (!title) setTitle(f.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' '))
    setSniff(null)
    sniffing.mutate(f)
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files?.[0])
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!file) return toast.error('Choose a PDF first')
    if (!title.trim()) return toast.error('Title is required')
    if (source === target) return toast.error('Source and target language must differ')
    upload.mutate({
      file,
      title: title.trim(),
      author: author.trim() || undefined,
      source_language: source,
      target_language: target,
      domain: domain.trim() || undefined,
      instructions: instructions.trim() || undefined,
    })
  }

  const sample = sniff?.sample?.trim()
  const sampleStyle = langStyle(sniff?.language_guess ?? source, 0.95)

  return (
    <Modal open={open} onClose={onClose} title="Upload a book" width="max-w-2xl">
      <form onSubmit={submit} className="space-y-5">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-sm transition ${
            dragging ? 'border-brand bg-brand-soft' : 'border-border-strong bg-surface-2'
          }`}
        >
          <div className="mb-2 grid h-10 w-10 place-items-center rounded-full bg-surface text-brand shadow-sm">
            <Icon name={file ? 'file' : 'upload'} size={20} />
          </div>
          {file ? (
            <div className="text-center">
              <div className="font-medium text-fg">{file.name}</div>
              <div className="text-xs text-fg-muted">{(file.size / 1024 / 1024).toFixed(1)} MB</div>
            </div>
          ) : (
            <div className="text-fg-muted">Drag a PDF here (text or scanned), or</div>
          )}
          <label className="mt-2 cursor-pointer text-sm font-medium text-brand hover:underline">
            {file ? 'choose another file' : 'choose a file'}
            <input type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
          </label>
        </div>

        {file && (
          <div className="rounded-lg border border-border bg-surface-2 p-3 text-xs">
            {sniffing.isPending && (
              <div className="flex items-center gap-2 text-fg-muted">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border-strong border-t-brand" />
                Looking at the first pages (page count, scan or text, language)…
              </div>
            )}
            {sniff && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Pill>{plural(sniff.page_count, 'page')}</Pill>
                  {sniff.has_text_layer ? (
                    <Pill tone="success">text layer · no OCR needed</Pill>
                  ) : (
                    <Pill tone="info">
                      <Icon name="scan" size={11} /> scanned · OCR {sniff.ocr_engine ? `via ${sniff.ocr_engine}` : ''}
                    </Pill>
                  )}
                  {sniff.ocr_quality && <QualityPill value={sniff.ocr_quality.score} />}
                  {sniff.language_guess ? (
                    <Pill tone="brand">looks like {langLabel(sniff.language_guess)}</Pill>
                  ) : (
                    <Pill tone="warn">language not detected</Pill>
                  )}
                </div>
                {sample && (
                  <div
                    className="line-clamp-3 rounded-md bg-surface p-2 text-fg-muted script-text"
                    style={{ ...sampleStyle, fontSize: '0.9rem', lineHeight: 1.8 }}
                    dir={sampleStyle.dir}
                  >
                    {sample}
                  </div>
                )}
              </div>
            )}
            {sniffing.isError && <div className="text-fg-muted">Could not inspect the file; you can still upload it.</div>}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Title">
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Author (optional)">
            <input className="input" value={author} onChange={(e) => setAuthor(e.target.value)} />
          </Field>
          <Field label="Source language" hint={sniff?.language_guess ? 'Detected from the first pages; change it if wrong.' : undefined}>
            <LanguageSelect value={source} onChange={setSource} languages={languages} exclude={target} />
          </Field>
          <Field label="Target language">
            <LanguageSelect value={target} onChange={setTarget} languages={languages} exclude={source} />
          </Field>
        </div>

        <Field label="What is this book about?" hint="Steers register and terminology in every prompt. Pick a preset or type your own.">
          <input className="input" list="domain-presets" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="e.g. Islamic jurisprudence, 19th-century novel, medical textbook" />
          <datalist id="domain-presets">
            {DOMAIN_PRESETS.map((d) => (
              <option key={d} value={d} />
            ))}
          </datalist>
        </Field>
        <div className="flex flex-wrap gap-1.5">
          {DOMAIN_PRESETS.slice(0, 6).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDomain(d)}
              className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
                domain === d ? 'border-brand bg-brand-soft text-brand' : 'border-border text-fg-muted hover:border-border-strong hover:text-fg'
              }`}
            >
              {d}
            </button>
          ))}
        </div>

        <Field label="Instructions for the translator (optional)" hint="Style guide in plain words: formality, how to render names, what to keep untranslated, footnote conventions…">
          <textarea
            className="input min-h-20 resize-y"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="e.g. Keep Quranic verses in Arabic. Render scholars' names in standard transliteration. Formal register, no colloquialisms."
          />
        </Field>

        <div className="flex items-center justify-between gap-2 border-t border-border pt-4">
          <div className="text-xs text-fg-faint">
            {languages.length} languages available · fonts load automatically
          </div>
          <div className="flex gap-2">
            <Button type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={upload.isPending} disabled={!file}>
              <Icon name="play" /> Upload & extract
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  )
}

