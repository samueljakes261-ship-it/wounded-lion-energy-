// Isolated Kenyan-section counterpart to lib/api-config.ts.
//
// Reuses the SAME VITE_API_URL as the Turkish/client-facing dashboard
// (the Kenyan routes are mounted on the same FastAPI backend, under
// `/kenyan/*` -- see kenyan/api_router.py), but never imports from or
// modifies lib/api-config.ts, keeping this section's frontend code
// fully separate. Does NOT import LOCAL_DEV_FALLBACK_API_URL from
// that module -- see the relative-path fallback below instead.
//
// IMPORTANT -- local/dev-tunnel behavior:
// When VITE_API_URL is NOT set, this deliberately returns a RELATIVE
// path ("/kenyan") rather than an absolute "http://localhost:8000"
// URL. An absolute localhost URL baked into the browser bundle only
// ever resolves correctly when the browser and the backend are on the
// SAME machine -- it breaks the moment the frontend dev server is
// reached through any kind of forwarded/proxied/tunneled URL (a
// different machine's "localhost" is not this one's), which is
// exactly the "Could not reach the Kenyan bookmakers service" failure
// this caused in practice. A relative path always resolves against
// whatever origin actually served the page, and vite.config.ts's dev
// server proxy (see `server.proxy["/kenyan"]`) forwards it to the
// real backend on this same machine -- so it works identically
// whether the page was reached directly or through a tunnel.
//
// In production (VITE_API_URL set, frontend and backend on different
// real domains), the absolute URL is still used exactly as before --
// there is no dev proxy in a production build.
export function resolveKenyanApiBase(env: { VITE_API_URL?: string }): string {
  if (!env.VITE_API_URL) {
    return "/kenyan";
  }

  const rawBase = env.VITE_API_URL.replace(/\/+$/, "");
  return `${rawBase}/kenyan`;
}

// NOTE: this module previously also exported sessionStorage helpers
// (getStoredKenyanSession/storeKenyanSession/clearStoredKenyanSession)
// for the access-code gate's short-lived session token. That gate was
// removed at explicit user request -- see kenyan/api_router.py and
// frontend/src/routes/kenyan.tsx's own notes -- so those helpers are
// no longer used and were removed. kenyan/access.py's server-side
// code/session-token machinery is untouched if this needs to be
// re-attached later.
