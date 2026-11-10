import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'
const KEY = 'tb-theme'

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    /* private mode */
  }
  return systemTheme()
}

function apply(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
}

/** Light/dark theme with persistence; follows the OS until the user picks. */
export function useTheme(): { theme: Theme; toggle: () => void; set: (t: Theme) => void } {
  const [theme, setTheme] = useState<Theme>(() => readTheme())

  useEffect(() => {
    apply(theme)
  }, [theme])

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = () => {
      try {
        if (!localStorage.getItem(KEY)) setTheme(systemTheme())
      } catch {
        setTheme(systemTheme())
      }
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const set = useCallback((t: Theme) => {
    setTheme(t)
    try {
      localStorage.setItem(KEY, t)
    } catch {
      /* ignore */
    }
  }, [])

  const toggle = useCallback(() => set(theme === 'dark' ? 'light' : 'dark'), [theme, set])
  return { theme, toggle, set }
}
