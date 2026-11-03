import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { getSettings } from '../api/client'

export function Layout() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 60_000, retry: 1 })

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-2">
          <div className="flex items-center gap-6">
            <Link to="/" className="text-lg font-semibold text-indigo-700">
              TranslateBook AI
            </Link>
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `text-sm ${isActive ? 'text-indigo-700 font-medium' : 'text-gray-600 hover:text-gray-900'}`
              }
            >
              Books
            </NavLink>
          </div>
          <div className="text-xs text-gray-500">
            {settings.data ? (
              <>
                <span className="font-medium text-gray-700">{settings.data.llm_provider}</span> ·{' '}
                {settings.data.model}
                {settings.data.worker_inline ? ' · inline worker' : ''} · v{settings.data.version}
              </>
            ) : settings.isError ? (
              <span className="text-red-600">backend unreachable</span>
            ) : null}
          </div>
        </div>
      </nav>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
