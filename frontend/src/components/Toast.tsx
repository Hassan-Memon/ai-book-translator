import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

type ToastKind = 'error' | 'success' | 'info'
interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface ToastApi {
  push: (message: string, kind?: ToastKind) => void
  error: (err: unknown) => void
  success: (message: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = nextId++
    setToasts((t) => [...t, { id, kind, message }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 6000 : 3500)
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      push,
      error: (err) => push(err instanceof Error ? err.message : String(err), 'error'),
      success: (m) => push(m, 'success'),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 w-80 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={
              'pointer-events-auto rounded-md border px-3 py-2 text-sm shadow-md ' +
              (t.kind === 'error'
                ? 'bg-red-50 border-red-300 text-red-800'
                : t.kind === 'success'
                  ? 'bg-green-50 border-green-300 text-green-800'
                  : 'bg-white border-gray-300 text-gray-800')
            }
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
