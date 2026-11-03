import type { ReactNode } from 'react'
import type { BookStatus, ChunkStatus, JobStatus } from '../api/types'
import { humanize } from '../lib/format'

const STATUS_COLORS: Record<string, string> = {
  // book
  uploaded: 'bg-gray-100 text-gray-700 border-gray-300',
  extracting: 'bg-blue-50 text-blue-700 border-blue-300',
  extracted: 'bg-sky-50 text-sky-700 border-sky-300',
  translating: 'bg-indigo-50 text-indigo-700 border-indigo-300',
  review: 'bg-amber-50 text-amber-800 border-amber-300',
  done: 'bg-green-50 text-green-700 border-green-300',
  failed: 'bg-red-50 text-red-700 border-red-300',
  // chunk
  pending: 'bg-gray-100 text-gray-700 border-gray-300',
  translated: 'bg-indigo-50 text-indigo-700 border-indigo-300',
  verified: 'bg-violet-50 text-violet-700 border-violet-300',
  terminology_reviewed: 'bg-amber-50 text-amber-800 border-amber-300',
  approved: 'bg-green-50 text-green-700 border-green-300',
  // job
  queued: 'bg-gray-100 text-gray-700 border-gray-300',
  running: 'bg-blue-50 text-blue-700 border-blue-300',
  succeeded: 'bg-green-50 text-green-700 border-green-300',
}


export function StatusBadge({ status }: { status: BookStatus | ChunkStatus | JobStatus | string }) {
  const cls = STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-700 border-gray-300'
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${cls}`}>
      {humanize(status)}
    </span>
  )
}

export function ProgressBar({
  value,
  color = 'bg-indigo-500',
  label,
}: {
  value: number // 0..100
  color?: string
  label?: string
}) {
  const v = Math.max(0, Math.min(100, value || 0))
  return (
    <div>
      {label && (
        <div className="flex justify-between text-xs text-gray-600 mb-1">
          <span>{label}</span>
          <span>{v.toFixed(0)}%</span>
        </div>
      )}
      <div className="h-2 w-full rounded bg-gray-200 overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${v}%` }} />
      </div>
    </div>
  )
}

export function Button({
  children,
  variant = 'secondary',
  className = '',
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
}) {
  const base =
    'inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed'
  const styles = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700',
    secondary: 'bg-white border border-gray-300 text-gray-800 hover:bg-gray-50',
    danger: 'bg-white border border-red-300 text-red-700 hover:bg-red-50',
    ghost: 'text-gray-700 hover:bg-gray-100',
  }[variant]
  return (
    <button className={`${base} ${styles} ${className}`} {...rest}>
      {children}
    </button>
  )
}

export function Card({
  title,
  children,
  actions,
  className = '',
}: {
  title?: ReactNode
  children: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-lg border border-gray-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-gray-100 px-4 py-2">
          <h2 className="text-sm font-semibold text-gray-800">{title}</h2>
          <div className="flex gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-gray-500 p-4">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-600" />
      {label}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">{children}</div>
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error)
  return <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">{msg}</div>
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <h3 className="font-semibold">{title}</h3>
          <button className="text-gray-500 hover:text-gray-800" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

