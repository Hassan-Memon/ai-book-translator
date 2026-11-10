export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function pct(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${n.toFixed(digits)}%`
}

export function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `$${n.toFixed(4)}`
}

export function num(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString()
}

export function humanize(s: string): string {
  return s.replace(/_/g, ' ')
}

/** "1 page", "3 pages" */
export function plural(n: number, word: string, many?: string): string {
  return `${n.toLocaleString()} ${n === 1 ? word : (many ?? `${word}s`)}`
}

/** 850 → "850 ms", 4200 → "4.2 s", 276634 → "4.6 min" */
export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${(ms / 60_000).toFixed(1)} min`
}
