const RTL_LANGS = new Set(['ur', 'ar', 'fa', 'ps', 'sd'])

export function isRtl(lang: string): boolean {
  return RTL_LANGS.has(lang.toLowerCase())
}

/** Font class + text direction for a language code. */
export function langClass(lang: string): { className: string; dir: 'rtl' | 'ltr' } {
  const code = lang.toLowerCase()
  if (code === 'ur') return { className: 'font-urdu', dir: 'rtl' }
  if (isRtl(code)) return { className: 'font-arabic', dir: 'rtl' }
  return { className: 'font-latin', dir: 'ltr' }
}

export const LANGUAGE_OPTIONS: Array<{ code: string; label: string }> = [
  { code: 'ur', label: 'Urdu (اردو)' },
  { code: 'ar', label: 'Arabic (العربية)' },
  { code: 'en', label: 'English' },
]

export function langLabel(code: string): string {
  return LANGUAGE_OPTIONS.find((l) => l.code === code)?.label ?? code
}
