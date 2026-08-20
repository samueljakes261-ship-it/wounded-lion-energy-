// Resolves the backend base URL this frontend build should call.
//
// Pulled out of routes/index.tsx into a pure, dependency-free function
// so the resolution logic itself can be unit tested (see
// api-config.test.ts) without needing to render the whole dashboard.
//
// RULE: the backend URL comes exclusively from VITE_API_URL. There is
// NO production/tunnel URL hardcoded here -- a stale hardcoded ngrok
// URL previously left the deployed frontend silently depending on a
// personal tunnel that could go offline at any time (see
// frontend/.env.example for the required Vercel configuration).
export const LOCAL_DEV_FALLBACK_API_URL = "http://localhost:8000"

export interface ApiConfigEnv {
  /** import.meta.env.VITE_API_URL */
  VITE_API_URL?: string
}

export interface ApiConfig {
  /** Full URL to GET arbitrage opportunities from. */
  apiUrl: string
  /** Full URL to GET collector/engine health from. */
  statusUrl: string
  /**
   * True when VITE_API_URL was not provided and the local-dev-only
   * fallback was used instead. In a production build this indicates a
   * missing Vercel environment variable, not a valid deployment state.
   */
  usedLocalDevFallback: boolean
}

export function resolveApiConfig(env: ApiConfigEnv): ApiConfig {
  const usedLocalDevFallback = !env.VITE_API_URL
  const rawBase = (env.VITE_API_URL ?? LOCAL_DEV_FALLBACK_API_URL).replace(/\/+$/, "")
  const apiUrl = rawBase.endsWith("/opportunities") ? rawBase : `${rawBase}/opportunities`
  const statusUrl = apiUrl.replace(/\/opportunities\/?$/, "") + "/status"

  return { apiUrl, statusUrl, usedLocalDevFallback }
}
