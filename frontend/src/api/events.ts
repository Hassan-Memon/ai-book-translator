import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

/**
 * Live progress over Server-Sent Events (GET /books/{id}/events).
 *
 * While `active` (the book has a queued/running job) we keep an EventSource
 * open. Every `progress` event means something changed on the server, so we
 * invalidate the book's queries and React Query refetches what is on screen.
 * The server sends `idle` and closes once no job is active; we close too, and
 * the effect re-subscribes when a new job makes `active` true again.
 *
 * `onLive(true)` lets callers switch their polling fallback off while the
 * stream is healthy; it flips back to false on error or idle.
 */
export function useBookEvents(bookId: string, active: boolean, onLive: (live: boolean) => void) {
  const qc = useQueryClient()

  useEffect(() => {
    if (!bookId || !active || typeof EventSource === 'undefined') return
    const es = new EventSource(`/api/v1/books/${bookId}/events`)
    const refresh = () => {
      for (const key of ['book', 'jobs', 'chunks', 'chunk', 'flags', 'stats']) {
        qc.invalidateQueries({ queryKey: [key, bookId] })
      }
      qc.invalidateQueries({ queryKey: ['books'] })
    }
    es.addEventListener('progress', () => {
      onLive(true)
      refresh()
    })
    es.addEventListener('idle', () => {
      es.close()
      onLive(false)
      refresh()
    })
    es.onerror = () => onLive(false) // browser retries on its own; polling covers the gap
    return () => {
      es.close()
      onLive(false)
    }
  }, [bookId, active, qc, onLive])
}
