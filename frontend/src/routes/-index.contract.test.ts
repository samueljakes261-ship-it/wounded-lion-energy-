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

describe("BACK vs LAY UI contract (frontend/src/routes/index.tsx)", () => {
  const backLayCard = SOURCE.slice(
    SOURCE.indexOf("function BackLayCard"),
    SOURCE.indexOf("function OpportunityCard")
  )
  const backBackSection = SOURCE.slice(
    SOURCE.indexOf("backBackOpportunities.length > 0"),
    SOURCE.indexOf("backBackOpportunities.map")
  )

  it("renders a dedicated BackLayCard with match, team, BACK/LAY prices, and percentage", () => {
    expect(SOURCE).toMatch(/function BackLayCard/)
    expect(backLayCard).toMatch(/matchLabel/)
    expect(backLayCard).toMatch(/arbitrageLabel/)
    expect(backLayCard).toMatch(/opportunity\.back\.bookmaker/)
    expect(backLayCard).toMatch(/opportunity\.back\.side/)
    expect(backLayCard).toMatch(/opportunity\.lay\.bookmaker/)
    expect(backLayCard).toMatch(/opportunity\.lay\.side/)
    expect(backLayCard).toMatch(/profitPercentage/)
    expect(backLayCard).not.toMatch(/stake/i)
    expect(backLayCard).not.toMatch(/guaranteedProfit/)
    expect(backLayCard).not.toMatch(/\broi\b/i)
    expect(backLayCard).not.toMatch(/liability/i)
    expect(backLayCard).not.toMatch(/implied/i)
    expect(backLayCard).not.toMatch(/generatedAt/)
    expect(backLayCard).not.toMatch(/collectedAt/)
    expect(backLayCard).not.toMatch(/eventId|marketId|feedId/i)
  })

  it("keeps the BACK vs BACK section collapsed by default", () => {
    expect(SOURCE).toMatch(/const \[backBackOpen, setBackBackOpen\] = useState\(false\)/)
    expect(backBackSection).toMatch(/defaultOpen=\{false\}/)
    expect(backBackSection).toMatch(/open=\{backBackOpen\}/)
  })

  it("reveals BACK vs BACK cards when the dropdown is clicked", () => {
    expect(SOURCE).toMatch(/data-testid="back-back-toggle"/)
    expect(backBackSection).toMatch(/CollapsibleTrigger/)
    expect(backBackSection).toMatch(/onOpenChange=\{setBackBackOpen\}/)
    expect(SOURCE).toMatch(/backBackOpportunities\.map/)
    expect(SOURCE).toMatch(/<OpportunityCard/)
  })

  it("shows BACK vs LAY opportunities first", () => {
    const layIndex = SOURCE.indexOf("backLayOpportunities.map")
    const backIndex = SOURCE.indexOf("backBackOpportunities.map")
    expect(layIndex).toBeGreaterThan(0)
    expect(backIndex).toBeGreaterThan(layIndex)
  })

  it("uses the shared i18n helper for new BACK vs LAY / BACK vs BACK labels", () => {
    expect(SOURCE).toMatch(/t\(lang, "backVsLay"\)/)
    expect(SOURCE).toMatch(/t\(lang, "backVsBackOpportunities"\)/)
    expect(SOURCE).toMatch(/t\(lang, "matchLabel"\)/)
    expect(SOURCE).toMatch(/t\(lang, "arbitrageLabel"\)/)
  })

  it("keeps existing BACK vs BACK and BACK vs LAY cards after adding filters", () => {
    expect(SOURCE).toMatch(/function BackLayCard/)
    expect(SOURCE).toMatch(/function OpportunityCard/)
    expect(SOURCE).toMatch(/filterOpportunities\(/)
    expect(SOURCE).toMatch(/keepLastGoodSnapshot\(/)
    expect(SOURCE).not.toMatch(/Restarting/)
  })

  it("defines Turkish and English strings for the new labels", () => {
    const i18n = readFileSync(fileURLToPath(new URL("../lib/i18n.ts", import.meta.url)), "utf-8")
    expect(i18n).toMatch(/backVsLay: "BACK vs LAY"/)
    expect(i18n).toMatch(/matchLabel: "Maç"/)
    expect(i18n).toMatch(/matchLabel: "Match"/)
    expect(i18n).toMatch(/arbitrageLabel: "Arbitraj"/)
    expect(i18n).toMatch(/arbitrageLabel: "Arbitrage"/)
    expect(i18n).toMatch(/backVsBackOpportunities: "BACK vs BACK FIRSATLARI"/)
    expect(i18n).toMatch(/backVsBackOpportunities: "BACK vs BACK OPPORTUNITIES"/)
  })
})
