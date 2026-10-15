import { describe, expect, it } from "vitest"

import {
  betfairMatchesMode,
  filterBetfairOpportunities,
  isBetfairOpportunity,
  type BetfairOpportunity,
} from "./betfair"

function sample(overrides: Partial<BetfairOpportunity> = {}): BetfairOpportunity {
  return {
    opportunityType: "BETFAIR",
    source: "betfair",
    homeTeam: "Wales",
    awayTeam: "Norway",
    isLive: false,
    valuePct: -2.083,
    isProfitable: false,
    status: "MATCHED_NO_VALUE",
    ...overrides,
  }
}

describe("Betfair opportunity filtering", () => {
  it("identifies BETFAIR records and never treats them as Kenyan/Turkish types", () => {
    expect(isBetfairOpportunity(sample())).toBe(true)
    expect(isBetfairOpportunity({ opportunityType: "BACK_LAY" })).toBe(false)
    expect(isBetfairOpportunity({ opportunityType: "BACK_BACK" })).toBe(false)
  })

  it("keeps LIVE and PREMATCH strictly separated via isLive", () => {
    const live = sample({ homeTeam: "Live FC", isLive: true })
    const prematch = sample({ isLive: false })
    const unknown = sample({ isLive: null })

    expect(betfairMatchesMode(live, "live")).toBe(true)
    expect(betfairMatchesMode(live, "prematch")).toBe(false)
    expect(betfairMatchesMode(prematch, "prematch")).toBe(true)
    expect(betfairMatchesMode(prematch, "live")).toBe(false)
    expect(betfairMatchesMode(unknown, "live")).toBe(false)
    expect(betfairMatchesMode(unknown, "prematch")).toBe(false)

    expect(filterBetfairOpportunities([live, prematch, unknown], { mode: "live" })).toEqual([
      live,
    ])
    expect(
      filterBetfairOpportunities([live, prematch, unknown], { mode: "prematch" })
    ).toEqual([prematch])
  })

  it("does not label MATCHED_NO_VALUE records as profitable when positive-only is on", () => {
    const profitable = sample({
      valuePct: 3.2,
      isProfitable: true,
      status: "VALUE",
    })
    const none = sample()
    expect(
      filterBetfairOpportunities([profitable, none], {
        mode: "prematch",
        positiveValueOnly: true,
      })
    ).toEqual([profitable])
  })
})
