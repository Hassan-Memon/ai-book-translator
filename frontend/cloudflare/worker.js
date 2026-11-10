// Cloudflare Worker for TranslateBook AI (docs/CLOUDFLARE.md).
//
// Serves the built React app from static assets and, in front of everything:
//   1. a password for the whole site (SITE_PASSWORD, HTTP Basic, any user name);
//   2. a proxy that forwards /api/* and /health to the app on your machine
//      (BACKEND_URL, reached through a Cloudflare Tunnel), adding the shared
//      secret the API checks (BACKEND_SECRET = API_SHARED_SECRET).
// wrangler.toml sets run_worker_first so even static files pass the gate.

import { proxy } from './proxy.js'

// Files that link previews and crawlers need stay public.
const PUBLIC = new Set([
  '/robots.txt',
  '/sitemap.xml',
  '/og.png',
  '/favicon.svg',
  '/icons.svg',
  '/icon-192.png',
  '/icon-512.png',
  '/manifest.webmanifest',
])

export function sameSecret(a, b) {
  // Constant-time comparison of two strings.
  const enc = new TextEncoder()
  const x = enc.encode(a)
  const y = enc.encode(b)
  let diff = x.length ^ y.length
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0)
  return diff === 0
}

export function passwordFrom(request) {
  const header = request.headers.get('Authorization') || ''
  if (!header.startsWith('Basic ')) return null
  try {
    const decoded = atob(header.slice(6))
    const colon = decoded.indexOf(':')
    return colon >= 0 ? decoded.slice(colon + 1) : null
  } catch {
    return null
  }
}

function gate(request, env) {
  const password = env.SITE_PASSWORD
  if (!password) {
    if (env.ALLOW_PUBLIC === 'true') return null
    return new Response(
      'This TranslateBook AI site has no SITE_PASSWORD set, so it is closed. ' +
        'Run: python deploy/cloudflare/connect.py setup (see docs/CLOUDFLARE.md).',
      { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } },
    )
  }
  const given = passwordFrom(request)
  if (given !== null && sameSecret(given, password)) return null
  return new Response('Password required', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="TranslateBook AI", charset="UTF-8"',
      'Content-Type': 'text/plain; charset=utf-8',
    },
  })
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url)
    if (PUBLIC.has(pathname)) return env.ASSETS.fetch(request)
    const denied = gate(request, env)
    if (denied) return denied
    if (pathname.startsWith('/api/') || pathname === '/health') return proxy({ request, env })
    return env.ASSETS.fetch(request)
  },
}
