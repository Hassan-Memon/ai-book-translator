import { useEffect } from 'react'

const SUFFIX = 'TranslateBook AI'

/** Document title per page (search engines and browser tabs read it). */
export function useTitle(title?: string | null, description?: string) {
  useEffect(() => {
    document.title = title ? `${title} · ${SUFFIX}` : `${SUFFIX} · Translate whole books with any LLM, cloud or local`
    if (description) {
      let meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
      if (!meta) {
        meta = document.createElement('meta')
        meta.name = 'description'
        document.head.appendChild(meta)
      }
      meta.content = description
    }
  }, [title, description])
}
