import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SOURCE = readFileSync(fileURLToPath(new URL("./kenyan.tsx", import.meta.url)), "utf-8")
const INDEX = readFileSync(fileURLToPath(new URL("./index.tsx", import.meta.url)), "utf-8")
const STAKE = readFileSync(
  fileURLToPath(new URL("../components/stake-plan.tsx", import.meta.url)),
  "utf-8"
)

describe("Kenyan opportunity click opens the shared BACK vs BACK stake plan", () => {
  it("reuses StakePlanPanel instead of a second calculator", () => {
    expect(SOURCE).toMatch(/import \{ StakePlanPanel \} from ["']@\/components\/stake-plan["']/)
    expect(INDEX).toMatch(/import \{ StakePlanPanel \} from ["']@\/components\/stake-plan["']/)
    expect(STAKE).toMatch(/export function StakePlanPanel/)
    expect(STAKE).toMatch(/homeStake/)
    expect(STAKE).toMatch(/drawStake/)
    expect(STAKE).toMatch(/awayStake/)
    expect(STAKE).not.toMatch(/liability/i)
    expect(STAKE).not.toMatch(/layStake/)
  })

  it("opens the stake plan with the same Collapsible click pattern as Turkish BACK vs BACK", () => {
    expect(SOURCE).toMatch(/CollapsibleTrigger/)
    expect(SOURCE).toMatch(/CollapsibleContent/)
    expect(SOURCE).toMatch(/<StakePlanPanel/)
    expect(SOURCE).toMatch(/data-testid="kenyan-opportunity-card"/)
    expect(INDEX).toMatch(/CollapsibleTrigger/)
    expect(INDEX).toMatch(/<StakePlanPanel/)
  })

  it("keys Kenyan cards by opportunityId so a poll does not remount an open calculator", () => {
    expect(SOURCE).toMatch(/key=\{opportunity\.opportunityId/)
  })

  it("shows the exact market on each Kenyan card", () => {
    expect(SOURCE).toMatch(/data-testid="kenyan-market-label"/)
    expect(SOURCE).toMatch(/opportunity\.marketLabel/)
  })

  it("does not independently retain an empty backend list", () => {
    expect(SOURCE).not.toMatch(/keepLastGoodSnapshot/)
  })

  it("shows a freshness indicator without remounting cards on odds updates", () => {
    expect(SOURCE).toMatch(/data-testid="kenyan-freshness"/)
    expect(SOURCE).toMatch(/key=\{opportunity\.opportunityId/)
    expect(SOURCE).toMatch(/Keep the last successful list/)
  })

  it("opens on PREMATCH because those markets are more stable to execute", () => {
    expect(SOURCE).toMatch(/useState<KenyanMode>\("prematch"\)/)
  })

  it("refreshes LIVE independently and faster than PREMATCH", () => {
    expect(SOURCE).toMatch(/mode === "live" \? 1000 : 5000/)
    expect(SOURCE).toMatch(/sameOpportunityPayload/)
    expect(SOURCE).toMatch(/requestSeq/)
    expect(SOURCE).toMatch(/confirmedAgeSeconds/)
    expect(SOURCE).toMatch(/cache: "no-store"/)
  })
})
