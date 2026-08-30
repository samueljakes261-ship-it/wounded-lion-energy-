// Isolated Kenyan-section counterpart to lib/api-config.ts.
//
// Reuses the SAME VITE_API_URL as the Turkish/client-facing dashboard
// (the Kenyan routes are mounted on the same FastAPI backend, under
// `/kenyan/*` -- see kenyan/api_router.py), but never imports from or
// modifies lib/api-config.ts, keeping this section's frontend code
// fully separate.
import { LOCAL_DEV_FALLBACK_API_URL } from "@/lib/api-config";

export function resolveKenyanApiBase(env: { VITE_API_URL?: string }): string {
  const rawBase = (env.VITE_API_URL ?? LOCAL_DEV_FALLBACK_API_URL).replace(/\/+$/, "");
  return `${rawBase}/kenyan`;
}

const KENYAN_TOKEN_STORAGE_KEY = "kenyan_session_token";
const KENYAN_TOKEN_EXPIRES_STORAGE_KEY = "kenyan_session_expires_at";

// sessionStorage ONLY -- never localStorage, and never the plaintext
// access code either way (the token is not the code; see
// kenyan/access.py). Clearing/closing the browser tab/session ends
// access, matching "maintain access for the CURRENT SESSION".
export function getStoredKenyanSession(): { token: string; expiresAt: number } | null {
  if (typeof window === "undefined") return null;

  const token = window.sessionStorage.getItem(KENYAN_TOKEN_STORAGE_KEY);
  const expiresAtRaw = window.sessionStorage.getItem(KENYAN_TOKEN_EXPIRES_STORAGE_KEY);

  if (!token || !expiresAtRaw) return null;

  const expiresAt = Number(expiresAtRaw);
  if (!Number.isFinite(expiresAt) || Date.now() / 1000 >= expiresAt) {
    clearStoredKenyanSession();
    return null;
  }

  return { token, expiresAt };
}

export function storeKenyanSession(token: string, expiresAt: number): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(KENYAN_TOKEN_STORAGE_KEY, token);
  window.sessionStorage.setItem(KENYAN_TOKEN_EXPIRES_STORAGE_KEY, String(expiresAt));
}

export function clearStoredKenyanSession(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(KENYAN_TOKEN_STORAGE_KEY);
  window.sessionStorage.removeItem(KENYAN_TOKEN_EXPIRES_STORAGE_KEY);
}
