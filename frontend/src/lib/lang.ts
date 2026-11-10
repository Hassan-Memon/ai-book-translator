import { useQuery } from '@tanstack/react-query'
import { useEffect, type CSSProperties } from 'react'
import { getLanguages } from '../api/client'
import type { LanguageInfo } from '../api/types'
import { ensureFont } from './fonts'

/**
 * Language helpers backed by the server's registry (GET /api/v1/languages).
 * A small static fallback keeps the UI usable before the first fetch.
 */

const FALLBACK: LanguageInfo[] = [
  { code: 'ur', name: 'Urdu', native: 'اردو', script: 'Arabic', rtl: true, font: 'Noto Nastaliq Urdu', font_scale: 1.1, line_height: 2.4, tesseract: ['urd'], terminators: [], markers: '', spaced: true },
  { code: 'ar', name: 'Arabic', native: 'العربية', script: 'Arabic', rtl: true, font: 'Noto Naskh Arabic', font_scale: 1.15, line_height: 2.0, tesseract: ['ara'], terminators: [], markers: '', spaced: true },
  { code: 'fa', name: 'Persian', native: 'فارسی', script: 'Arabic', rtl: true, font: 'Noto Naskh Arabic', font_scale: 1.15, line_height: 2.0, tesseract: ['fas'], terminators: [], markers: '', spaced: true },
  { code: 'en', name: 'English', native: 'English', script: 'Latin', rtl: false, font: 'Noto Serif', font_scale: 1, line_height: 1.7, tesseract: ['eng'], terminators: [], markers: '', spaced: true },
  { code: 'hi', name: 'Hindi', native: 'हिन्दी', script: 'Devanagari', rtl: false, font: 'Noto Sans Devanagari', font_scale: 1.05, line_height: 1.9, tesseract: ['hin'], terminators: [], markers: '', spaced: true },
  { code: 'tr', name: 'Turkish', native: 'Türkçe', script: 'Latin', rtl: false, font: 'Noto Serif', font_scale: 1, line_height: 1.7, tesseract: ['tur'], terminators: [], markers: '', spaced: true },
  { code: 'fr', name: 'French', native: 'Français', script: 'Latin', rtl: false, font: 'Noto Serif', font_scale: 1, line_height: 1.7, tesseract: ['fra'], terminators: [], markers: '', spaced: true },
  { code: 'de', name: 'German', native: 'Deutsch', script: 'Latin', rtl: false, font: 'Noto Serif', font_scale: 1, line_height: 1.7, tesseract: ['deu'], terminators: [], markers: '', spaced: true },
  { code: 'es', name: 'Spanish', native: 'Español', script: 'Latin', rtl: false, font: 'Noto Serif', font_scale: 1, line_height: 1.7, tesseract: ['spa'], terminators: [], markers: '', spaced: true },
]

let registry: LanguageInfo[] = FALLBACK

export function useLanguages(): LanguageInfo[] {
  const q = useQuery({ queryKey: ['languages'], queryFn: getLanguages, staleTime: Infinity, retry: 1 })
  const list = q.data?.languages
  useEffect(() => {
    if (list && list.length) registry = list
  }, [list])
  return list && list.length ? list : registry
}

export function findLanguage(code: string): LanguageInfo | undefined {
  const key = code.toLowerCase()
  return registry.find((l) => l.code.toLowerCase() === key) ?? registry.find((l) => l.code.toLowerCase() === key.split('-')[0])
}

export function isRtl(lang: string): boolean {
  return findLanguage(lang)?.rtl ?? false
}

export function langLabel(code: string): string {
  const l = findLanguage(code)
  return l ? (l.native && l.native !== l.name ? `${l.name} (${l.native})` : l.name) : code
}

export function langName(code: string): string {
  return findLanguage(code)?.name ?? code
}

/** Inline style for text in a language: font, direction, size, leading. */
export function langStyle(code: string, base = 1): CSSProperties & { dir: 'rtl' | 'ltr' } {
  const l = findLanguage(code)
  const family = l?.font ?? 'Noto Serif'
  ensureFont(family)
  return {
    fontFamily: `"${family}", "Noto Sans", serif`,
    direction: l?.rtl ? 'rtl' : 'ltr',
    textAlign: l?.rtl ? 'right' : 'left',
    fontSize: `${(l?.font_scale ?? 1) * base}rem`,
    lineHeight: l?.line_height ?? 1.7,
    dir: l?.rtl ? 'rtl' : 'ltr',
  }
}

/** Legacy helper kept for the review page: class + dir. */
export function langClass(lang: string): { className: string; dir: 'rtl' | 'ltr'; style: CSSProperties } {
  const s = langStyle(lang)
  const { dir, ...style } = s
  return { className: 'script-text', dir, style }
}

/** Groups for the language picker: by script family, source language first. */
export function groupLanguages(list: LanguageInfo[]): Array<{ label: string; items: LanguageInfo[] }> {
  const groups = new Map<string, LanguageInfo[]>()
  for (const l of list) {
    const key = l.script === 'Arabic' ? 'Arabic script' : l.rtl ? 'Right-to-left' : l.script === 'Latin' ? 'Latin script' : l.script === 'Cyrillic' || l.script === 'Greek' ? 'Cyrillic & Greek' : ['Devanagari', 'Bengali', 'Gurmukhi', 'Gujarati', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Sinhala'].includes(l.script) ? 'South Asian' : ['Han', 'Japanese', 'Hangul', 'Thai', 'Myanmar', 'Khmer'].includes(l.script) ? 'East & Southeast Asian' : 'Other'
    groups.set(key, [...(groups.get(key) ?? []), l])
  }
  const order = ['Arabic script', 'Right-to-left', 'Latin script', 'Cyrillic & Greek', 'South Asian', 'East & Southeast Asian', 'Other']
  return order.filter((k) => groups.has(k)).map((k) => ({ label: k, items: groups.get(k)! }))
}

export const DOMAIN_PRESETS: string[] = [
  'general literature and non-fiction',
  'Islamic scholarship (fiqh, hadith, tafsir)',
  'classical poetry',
  'novel / fiction',
  'history and biography',
  'philosophy and theology',
  'law and contracts',
  'medicine and health',
  'science and engineering',
  'business and economics',
  'children’s books',
  'academic paper / textbook',
]
