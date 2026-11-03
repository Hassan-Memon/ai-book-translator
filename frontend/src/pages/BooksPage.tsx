import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type DragEvent, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { listBooks, uploadBook } from '../api/client'
import type { Book } from '../api/types'
import { useToast } from '../components/Toast'
import { Button, Empty, ErrorBox, Modal, ProgressBar, Spinner, StatusBadge } from '../components/ui'
import { inputCls } from '../lib/styles'
import { formatDate } from '../lib/format'
import { LANGUAGE_OPTIONS, langLabel } from '../lib/lang'

export function BooksPage() {
  const [open, setOpen] = useState(false)
  const books = useQuery({
    queryKey: ['books'],
    queryFn: listBooks,
    refetchInterval: 5000,
  })

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Books</h1>
        <Button variant="primary" onClick={() => setOpen(true)}>
          + Upload book
        </Button>
      </div>

      {books.isLoading && <Spinner />}
      {books.isError && <ErrorBox error={books.error} />}
      {books.data && books.data.books.length === 0 && (
        <Empty>No books yet. Upload a PDF to start.</Empty>
      )}
      {books.data && books.data.books.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {books.data.books.map((b) => (
            <BookCard key={b.id} book={b} />
          ))}
        </div>
      )}

      <UploadModal open={open} onClose={() => setOpen(false)} />
    </div>
  )
}

function BookCard({ book }: { book: Book }) {
  // The list endpoint returns Book (no percent fields); approved % is derived from
  // completed_chunks / total_chunks. "Translated" is inferred from status.
  const approved = book.total_chunks ? (book.completed_chunks / book.total_chunks) * 100 : 0
  const translated =
    book.status === 'review' || book.status === 'done' ? 100 : book.status === 'translating' ? approved : 0
  return (
    <Link
      to={`/books/${book.id}`}
      className="block rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition hover:border-indigo-300 hover:shadow"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h2 className="font-semibold text-gray-900 line-clamp-2">{book.title}</h2>
        <StatusBadge status={book.status} />
      </div>
      <div className="mb-3 text-xs text-gray-600">
        {langLabel(book.source_language)} → {langLabel(book.target_language)}
      </div>
      <div className="space-y-2">
        <ProgressBar label="Translated" value={translated} />
        <ProgressBar label="Approved" value={approved} color="bg-green-500" />
      </div>
      <div className="mt-3 flex justify-between text-xs text-gray-500">
        <span>
          {book.page_count} pages · {book.total_chunks} chunks{book.is_scanned ? ' · scanned' : ''}
        </span>
        <span>{formatDate(book.created_at)}</span>
      </div>
      {book.error && <div className="mt-2 truncate text-xs text-red-600">{book.error}</div>}
    </Link>
  )
}

function UploadModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [source, setSource] = useState('ur')
  const [target, setTarget] = useState('ar')
  const [dragging, setDragging] = useState(false)

  const upload = useMutation({
    mutationFn: uploadBook,
    onSuccess: (book) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      toast.success('Book uploaded; extraction queued')
      reset()
      onClose()
      nav(`/books/${book.id}`)
    },
    onError: (e) => toast.error(e),
  })

  function reset() {
    setFile(null)
    setTitle('')
  }

  function pick(f: File | undefined | null) {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Only PDF files are supported')
      return
    }
    setFile(f)
    if (!title) setTitle(f.name.replace(/\.pdf$/i, ''))
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files?.[0])
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!file) {
      toast.error('Choose a PDF first')
      return
    }
    if (!title.trim()) {
      toast.error('Title is required')
      return
    }
    if (source === target) {
      toast.error('Source and target language must differ')
      return
    }
    upload.mutate({ file, title: title.trim(), source_language: source, target_language: target })
  }

  return (
    <Modal open={open} onClose={onClose} title="Upload a book (PDF)">
      <form onSubmit={submit} className="space-y-4">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center rounded-md border-2 border-dashed p-6 text-sm ${
            dragging ? 'border-indigo-400 bg-indigo-50' : 'border-gray-300'
          }`}
        >
          {file ? (
            <div className="text-gray-800">
              <span className="font-medium">{file.name}</span>{' '}
              <span className="text-gray-500">({(file.size / 1024 / 1024).toFixed(1)} MB)</span>
            </div>
          ) : (
            <div className="text-gray-500">Drag a PDF here, or</div>
          )}
          <label className="mt-2 cursor-pointer text-indigo-700 hover:underline">
            choose a file
            <input
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </label>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-gray-700">Title</label>
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">Source language</label>
            <select className={inputCls} value={source} onChange={(e) => setSource(e.target.value)}>
              {LANGUAGE_OPTIONS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700">Target language</label>
            <select className={inputCls} value={target} onChange={(e) => setTarget(e.target.value)}>
              {LANGUAGE_OPTIONS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={upload.isPending}>
            {upload.isPending ? 'Uploading…' : 'Upload'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
