// Forward a request to the TranslateBook API running on your machine, reached
// through a Cloudflare Tunnel (BACKEND_URL). Adds the shared secret the API
// checks (API_SHARED_SECRET on the backend = BACKEND_SECRET here) and drops the
// site password so it never reaches the backend. Responses stream through, so
// uploads, downloads and the live progress stream (SSE) work unchanged.

export async function proxy({ request, env }) {
  if (!env.BACKEND_URL) {
    return Response.json(
      {
        detail:
          'The translation server is not connected. On the machine that runs it, start the ' +
          'app and run `python deploy/cloudflare/connect.py` from the repository root ' +
          '(docs/CLOUDFLARE.md).',
      },
      { status: 503 },
    )
  }
  const incoming = new URL(request.url)
  const target = new URL(incoming.pathname + incoming.search, env.BACKEND_URL)
  const upstream = new Request(target.toString(), request)
  upstream.headers.delete('Authorization')
  upstream.headers.delete('Cookie')
  upstream.headers.set('X-Forwarded-Host', incoming.host)
  if (env.BACKEND_SECRET) upstream.headers.set('X-TranslateBook-Key', env.BACKEND_SECRET)
  try {
    return await fetch(upstream, { redirect: 'manual' })
  } catch (err) {
    return Response.json(
      { detail: `The translation server did not answer (${err}). Is the tunnel running?` },
      { status: 502 },
    )
  }
}
