import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { getSettings } from '../api/client'
import { useTheme } from '../lib/theme'
import { Icon, Pill } from './ui'

const GITHUB = 'https://github.com/Hassan-Memon/ai-book-translator'

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="TranslateBook AI home">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-brand-fg shadow-sm">
        <Icon name="languages" size={18} />
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-tight text-fg">TranslateBook AI</span>
        <span className="hidden text-[10px] font-medium uppercase tracking-[0.14em] text-fg-faint sm:block">
          whole books · any language · any model
        </span>
      </span>
    </Link>
  )
}

function ProviderPill() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 15_000, retry: 1 })
  if (settings.isError) {
    return (
      <Pill tone="danger" title="The API is not reachable">
        <Icon name="alert" size={12} /> backend unreachable
      </Pill>
    )
  }
  const s = settings.data
  if (!s) return <span className="skeleton h-5 w-36" />
  const tone = !s.provider_configured ? 'warn' : s.is_local ? 'success' : 'brand'
  const label = !s.provider_configured ? 'demo mode · no model' : `${s.provider_label} · ${s.model}`
  return (
    <NavLink to="/settings" className="group" title="Model settings">
      <Pill tone={tone} className="max-w-[16rem] truncate group-hover:ring-2 group-hover:ring-[var(--ring)]">
        <Icon name={s.is_local ? 'cpu' : 'cloud'} size={12} />
        <span className="truncate">{label}</span>
        {s.provider_configured && <span className="opacity-70">· {s.model_tier}</span>}
      </Pill>
    </NavLink>
  )
}

export function Layout() {
  const { theme, toggle } = useTheme()
  const navCls = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-2.5 py-1.5 text-sm font-medium transition ${
      isActive ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg'
    }`

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-border bg-surface/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-2.5">
          <div className="flex items-center gap-6">
            <Logo />
            <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
              <NavLink to="/" end className={navCls}>
                Books
              </NavLink>
              <NavLink to="/settings" className={navCls}>
                Settings
              </NavLink>
              <a
                href={`${GITHUB}#readme`}
                target="_blank"
                rel="noreferrer"
                className="rounded-md px-2.5 py-1.5 text-sm font-medium text-fg-muted transition hover:bg-surface-2 hover:text-fg"
              >
                Docs
              </a>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <ProviderPill />
            <button
              onClick={toggle}
              className="rounded-md p-2 text-fg-muted transition hover:bg-surface-2 hover:text-fg"
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
            </button>
            <a
              href={GITHUB}
              target="_blank"
              rel="noreferrer"
              className="hidden rounded-md p-2 text-fg-muted transition hover:bg-surface-2 hover:text-fg sm:block"
              aria-label="GitHub repository"
              title="GitHub"
            >
              <Icon name="github" />
            </a>
          </div>
        </div>
        <nav className="flex gap-1 border-t border-border px-3 py-1.5 md:hidden" aria-label="Main mobile">
          <NavLink to="/" end className={navCls}>
            Books
          </NavLink>
          <NavLink to="/settings" className={navCls}>
            Settings
          </NavLink>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-border py-4 text-center text-xs text-fg-faint">
        TranslateBook AI · open source (MIT) · your books and keys stay on your machine ·{' '}
        <a href={GITHUB} className="hover:text-fg" target="_blank" rel="noreferrer">
          GitHub
        </a>
      </footer>
    </div>
  )
}
