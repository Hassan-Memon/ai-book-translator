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
