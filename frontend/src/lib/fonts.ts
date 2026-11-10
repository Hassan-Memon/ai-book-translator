/**
 * Load script fonts on demand from Google Fonts.
 *
 * A book in Urdu needs Noto Nastaliq Urdu; a Hindi book needs Noto Sans
 * Devanagari. Loading every family up front would cost megabytes, so the
 * language registry names the family and this module injects one <link> per
 * family the first time it is needed.
 */

const loaded = new Set<string>()
const WEIGHTS = '400;500;700'

export function ensureFont(family: string | undefined | null): void {
  if (!family || loaded.has(family) || typeof document === 'undefined') return
  // System / generic families never need a download.
  if (/^(system-ui|serif|sans-serif|monospace|inter)$/i.test(family)) {
    loaded.add(family)
    return
  }
  loaded.add(family)
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family).replace(/%20/g, '+')}:wght@${WEIGHTS}&display=swap`
  link.setAttribute('data-font', family)
  document.head.appendChild(link)
}
