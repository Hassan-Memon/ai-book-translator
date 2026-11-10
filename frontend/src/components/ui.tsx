import type { CSSProperties, ReactNode } from 'react'
import type { BookStatus, ChunkStatus, JobStatus } from '../api/types'
import { humanize } from '../lib/format'

// ---------------------------------------------------------------------------
// Status badges
// ---------------------------------------------------------------------------

const STATUS_TONE: Record<string, string> = {
  // book
  uploaded: 'bg-surface-2 text-fg-muted border-border',
  extracting: 'bg-info-soft text-info border-info/30',
  extracted: 'bg-info-soft text-info border-info/30',
  translating: 'bg-brand-soft text-brand border-brand/30',
  review: 'bg-warn-soft text-warn border-warn/30',
  done: 'bg-success-soft text-success border-success/30',
  failed: 'bg-danger-soft text-danger border-danger/30',
  // chunk
  pending: 'bg-surface-2 text-fg-muted border-border',
  translated: 'bg-brand-soft text-brand border-brand/30',
  verified: 'bg-brand-soft text-brand border-brand/30',
  terminology_reviewed: 'bg-warn-soft text-warn border-warn/30',
  approved: 'bg-success-soft text-success border-success/30',
  // job
  queued: 'bg-surface-2 text-fg-muted border-border',
  running: 'bg-info-soft text-info border-info/30',
  succeeded: 'bg-success-soft text-success border-success/30',
}

export function StatusBadge({ status }: { status: BookStatus | ChunkStatus | JobStatus | string }) {
  const cls = STATUS_TONE[status] ?? 'bg-surface-2 text-fg-muted border-border'
  const live = status === 'running' || status === 'translating' || status === 'extracting'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${cls}`}
    >
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {humanize(status)}
    </span>
  )
}

export function Pill({
  children,
  tone = 'neutral',
  title,
  className = '',
}: {
  children: ReactNode
  tone?: 'neutral' | 'brand' | 'success' | 'warn' | 'danger' | 'info'
  title?: string
  className?: string
}) {
  const tones = {
    neutral: 'bg-surface-2 text-fg-muted border-border',
    brand: 'bg-brand-soft text-brand border-brand/30',
    success: 'bg-success-soft text-success border-success/30',
    warn: 'bg-warn-soft text-warn border-warn/30',
    danger: 'bg-danger-soft text-danger border-danger/30',
    info: 'bg-info-soft text-info border-info/30',
  }[tone]
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${tones} ${className}`}
    >
      {children}
    </span>
  )
}

/** OCR quality 0..1 as a coloured pill. */
export function QualityPill({ value, label = 'OCR' }: { value: number | null | undefined; label?: string }) {
  if (value == null) return null
  const tone = value >= 0.85 ? 'success' : value >= 0.7 ? 'warn' : 'danger'
  const word = value >= 0.85 ? 'good' : value >= 0.7 ? 'fair' : 'poor'
  return (
    <Pill tone={tone} title={`${label} quality ${value.toFixed(2)} (${word})`}>
      {label} {Math.round(value * 100)}%
    </Pill>
  )
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

export function ProgressBar({
  value,
  color = 'bg-brand',
  label,
  size = 'md',
}: {
  value: number // 0..100
  color?: string
  label?: string
  size?: 'sm' | 'md'
}) {
  const v = Math.max(0, Math.min(100, value || 0))
  return (
    <div>
      {label && (
        <div className="mb-1 flex justify-between text-xs text-fg-muted">
          <span>{label}</span>
          <span className="tabular-nums">{v.toFixed(0)}%</span>
        </div>
      )}
      <div className={`w-full overflow-hidden rounded-full bg-surface-3 ${size === 'sm' ? 'h-1.5' : 'h-2'}`}>
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${v}%` }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

export function Button({
  children,
  variant = 'secondary',
  size = 'md',
  className = '',
  loading = false,
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'soft'
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}) {
  const base =
    'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100'
  const sizes = { sm: 'px-2.5 py-1 text-xs', md: 'px-3.5 py-2 text-sm', lg: 'px-5 py-2.5 text-sm' }[size]
  const styles = {
    primary: 'bg-brand text-brand-fg shadow-sm hover:bg-brand-strong',
    secondary: 'border border-border-strong bg-surface text-fg hover:bg-surface-2',
    soft: 'bg-brand-soft text-brand hover:bg-brand/20',
    danger: 'border border-danger/40 bg-surface text-danger hover:bg-danger-soft',
    ghost: 'text-fg-muted hover:bg-surface-2 hover:text-fg',
  }[variant]
  return (
    <button className={`${base} ${sizes} ${styles} ${className}`} disabled={disabled || loading} {...rest}>
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------

export function Card({
  title,
  subtitle,
  children,
  actions,
  className = '',
  padded = true,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  actions?: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-fg-muted">{subtitle}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={padded ? 'p-4' : ''}>{children}</div>
    </section>
  )
}

export function Field({
  label,
  hint,
  children,
  className = '',
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium text-fg-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-fg-faint">{hint}</span>}
    </label>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = 'md',
}: {
  value: T
  options: Array<{ value: T; label: ReactNode; title?: string }>
  onChange: (v: T) => void
  size?: 'sm' | 'md'
}) {
  return (
    <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          onClick={() => onChange(o.value)}
          className={`rounded-md font-medium transition ${size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'} ${
            o.value === value ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-4 text-sm text-fg-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-border-strong border-t-brand" />
      {label}
    </div>
  )
}

export function Skeleton({ className = 'h-4 w-full' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}

export function Empty({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border-strong p-8 text-center text-sm text-fg-muted">
      {icon && <div className="text-fg-faint">{icon}</div>}
      <div>{children}</div>
    </div>
  )
}

export function ErrorBox({ error, className = '' }: { error: unknown; className?: string }) {
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div className={`rounded-lg border border-danger/40 bg-danger-soft p-3 text-sm text-danger ${className}`}>{msg}</div>
  )
}

export function Callout({
  tone = 'info',
  title,
  children,
  className = '',
}: {
  tone?: 'info' | 'warn' | 'success' | 'danger' | 'brand'
  title?: ReactNode
  children: ReactNode
  className?: string
}) {
  const tones = {
    info: 'border-info/30 bg-info-soft text-info',
    warn: 'border-warn/30 bg-warn-soft text-warn',
    success: 'border-success/30 bg-success-soft text-success',
    danger: 'border-danger/30 bg-danger-soft text-danger',
    brand: 'border-brand/30 bg-brand-soft text-brand',
  }[tone]
  return (
    <div className={`rounded-lg border p-3 text-sm ${tones} ${className}`}>
      {title && <div className="mb-0.5 font-semibold">{title}</div>}
      <div className="text-fg/90 [&_a]:underline">{children}</div>
    </div>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = 'max-w-lg',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  width?: string
}) {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-[8vh] backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className={`fade-up w-full ${width} card`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h3 className="font-semibold">{title}</h3>
          <button className="rounded-md p-1 text-fg-muted hover:bg-surface-2 hover:text-fg" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

export function Stat({ label, value, hint, style }: { label: string; value: ReactNode; hint?: string; style?: CSSProperties }) {
  return (
    <div className="rounded-lg bg-surface-2 p-3" style={style}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-fg-faint">{label}</div>
      <div className="mt-0.5 text-base font-semibold tabular-nums text-fg">{value}</div>
      {hint && <div className="text-[11px] text-fg-muted">{hint}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Icons (inline SVG, stroke icons, 16px default)
// ---------------------------------------------------------------------------

const PATHS: Record<string, string> = {
  x: 'M18 6 6 18M6 6l12 12',
  upload: 'M12 16V4m0 0 4 4m-4-4-4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3',
  book: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15Z',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1l2-1.6-2-3.4-2.4 1a7 7 0 0 0-1.7-1l-.4-2.6H9.2L8.8 6a7 7 0 0 0-1.7 1l-2.4-1-2 3.4L4.7 11a7.4 7.4 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.4 2.6h4.6l.4-2.6a7 7 0 0 0 1.7-1l2.4 1 2-3.4-2-1.6c.1-.3.1-.7.1-1Z',
  sun: 'M12 3v2m0 14v2M5.6 5.6l1.4 1.4m9.9 9.9 1.4 1.4M3 12h2m14 0h2M5.6 18.4 7 17m9.9-9.9 1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z',
  check: 'M20 6 9 17l-5-5',
  alert: 'M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  cpu: 'M9 2v2m6-2v2M9 20v2m6-2v2M2 9h2m-2 6h2m16-6h2m-2 6h2M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm3 5h6v6H9V9Z',
  cloud: 'M17.5 19a4.5 4.5 0 0 0 .4-9A7 7 0 0 0 4.3 12 4 4 0 0 0 6 19h11.5Z',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  eyeOff: 'M17.9 17.9A10 10 0 0 1 12 19c-6.5 0-10-7-10-7a18 18 0 0 1 5.1-6M9.9 4.2A9 9 0 0 1 12 4c6.5 0 10 7 10 7a18 18 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2M2 2l20 20',
  scan: 'M3 7V5a2 2 0 0 1 2-2h2m10 0h2a2 2 0 0 1 2 2v2m0 10v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10',
  sparkles: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Zm7 11 .9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14ZM5 15l.7 1.6L7.3 17l-1.6.7L5 19.3l-.7-1.6L2.7 17l1.6-.7L5 15Z',
  download: 'M12 4v12m0 0 4-4m-4 4-4-4M4 20h16',
  play: 'M6 4l14 8-14 8V4Z',
  trash: 'M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m-9 0 1 14h10l1-14',
  external: 'M14 4h6v6m0-6L10 14M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5',
  github: 'M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.2-3.4-1.2-.4-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.6 2.4 1.1 3 .9.1-.7.4-1.1.6-1.4-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.2-.4-1.2.1-2.6 0 0 .8-.3 2.8 1a9.5 9.5 0 0 1 5 0c1.9-1.3 2.8-1 2.8-1 .5 1.4.2 2.4.1 2.6.6.7 1 1.6 1 2.7 0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5A10 10 0 0 0 12 2Z',
  globe: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Zm0 0c2.8 0 5-4.5 5-10S14.8 2 12 2 7 6.5 7 12s2.2 10 5 10ZM2 12h20',
  zap: 'M13 2 3 14h9l-1 8 10-12h-9l1-8Z',
  layers: 'm12 2 10 5-10 5L2 7l10-5Zm-10 10 10 5 10-5M2 17l10 5 10-5',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z',
  refresh: 'M21 12a9 9 0 1 1-3-6.7M21 3v6h-6',
  chevronRight: 'm9 18 6-6-6-6',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Zm0-6v-4m0-4h.01',
  key: 'm21 2-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8Zm0 0L15 8m0 0 3 3m-3-3 4-4',
  file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Zm0 0v6h6',
  edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5Z',
  languages: 'm5 8 6 6m-7 0 6-6 2-3M2 5h12M7 2h1m14 20-5-10-5 10m2-4h6',
}

export function Icon({ name, size = 16, className = '' }: { name: keyof typeof PATHS | string; size?: number; className?: string }) {
  const d = PATHS[name] ?? PATHS.info
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`inline-block shrink-0 ${className}`}
      aria-hidden="true"
    >
      <path d={d} />
    </svg>
  )
}
