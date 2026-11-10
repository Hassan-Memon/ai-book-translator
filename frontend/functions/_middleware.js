// Cloudflare Pages middleware: one password in front of the whole site.
//
// The app has no user accounts (it is self-hosted), and behind this site sits
// your own machine with your API keys. So every page and API call asks for
// SITE_PASSWORD (HTTP Basic auth; any user name). Files that link previews and
// crawlers need stay public. See docs/CLOUDFLARE.md.

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

function sameSecret(a, b) {
  // Constant-time comparison of two strings.
  const enc = new TextEncoder()
  const x = enc.encode(a)
  const y = enc.encode(b)
  let diff = x.length ^ y.length
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0)
  return diff === 0
}

function passwordFrom(request) {
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

export async function onRequest(context) {
  const { request, env, next } = context
  const url = new URL(request.url)
  if (PUBLIC.has(url.pathname)) return next()

  const password = env.SITE_PASSWORD
  if (!password) {
    if (env.ALLOW_PUBLIC === 'true') return next()
    return new Response(
      'This TranslateBook AI site has no SITE_PASSWORD set, so it is closed. ' +
        'Set one with: npx wrangler pages secret put SITE_PASSWORD (see docs/CLOUDFLARE.md).',
      { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } },
    )
  }
  const given = passwordFrom(request)
  if (given !== null && sameSecret(given, password)) return next()
  return new Response('Password required', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="TranslateBook AI", charset="UTF-8"',
      'Content-Type': 'text/plain; charset=utf-8',
    },
  })
}
