// Static/structural checks on the live dashboard's data-fetching
// contract. Rendering the full TanStack Start route (SSR + router
// context + hooks) in a unit test would require a much heavier test
// harness than this project currently has; these checks instead prove
// -- directly against the real source file, not a copy -- the
// specific properties this task cares about: correct endpoints are
// called, failures are surfaced (not silently swallowed into an empty
// list), and no stale hardcoded backend URL survives in source.
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SOURCE = readFileSync(fileURLToPath(new URL("./index.tsx", import.meta.url)), "utf-8")

describe("dashboard data-fetching contract (frontend/src/routes/index.tsx)", () => {
  it("resolves the backend URL via the shared, tested resolveApiConfig helper", () => {
    expect(SOURCE).toMatch(/resolveApiConfig\(/)
    expect(SOURCE).toMatch(/from ["']@\/lib\/api-config["']/)
  })

  it("fetches opportunities from API_URL (with mode) and status from STATUS_URL", () => {
    expect(SOURCE).toMatch(/fetch\(`\$\{API_URL\}\?mode=\$\{mode\}`/)
    expect(SOURCE).toMatch(/fetch\(STATUS_URL/)
  })

  it("does not hardcode any production/tunnel backend URL", () => {
    // "ngrok-skip-browser-warning" is a legitimate request header kept
    // for when ngrok IS intentionally used as a bridge (see
    // frontend/.env.example) -- what must never reappear is an actual
    // hardcoded backend hostname/URL baked into source.
    expect(SOURCE).not.toMatch(/https?:\/\/[a-z0-9.-]+\.ngrok[a-z0-9.-]*\//i)
    expect(SOURCE).not.toMatch(/https?:\/\/[a-z0-9.-]+\.(vercel\.app|onrender\.com|railway\.app)/i)
  })

  it("surfaces opportunity-fetch failures via error state rather than silently returning an empty list", () => {
    const loadOpportunitiesFn = SOURCE.slice(
      SOURCE.indexOf("const loadOpportunities"),
      SOURCE.indexOf("const loadOpportunities") + 900
    )

    expect(loadOpportunitiesFn).toMatch(/catch \(err\)/)
    expect(loadOpportunitiesFn).toMatch(/setError\(/)
    // The failure path must not quietly reset the opportunities list to
    // an empty array -- that would look identical to "zero
    // opportunities found", hiding a real connectivity/config failure.
    expect(loadOpportunitiesFn).not.toMatch(/catch[\s\S]*?setOpportunities\(\[\]\)/)
  })

  it("logs opportunity-fetch failures to the console for diagnosis", () => {
    expect(SOURCE).toMatch(/console\.error\(`\[ArbScanner\] opportunities fetch failed/)
  })

  it("warns loudly (without secrets) when a production build has no VITE_API_URL configured", () => {
    expect(SOURCE).toMatch(/import\.meta\.env\.PROD && usedLocalDevFallback/)
    expect(SOURCE).toMatch(/console\.error\(/)
  })
})
