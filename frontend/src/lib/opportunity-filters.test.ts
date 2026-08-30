import { describe, expect, it } from "vitest"

import {
  bookmakersFromOpportunities,
  filterOpportunities,
  keepLastGoodSnapshot,
  parseOptionalNumber,
} from "./opportunity-filters"

const backBack = {
  opportunityType: "BACK_BACK",
  profitPercentage: 2.5,
  home: { bookmaker: "Betkanyon", odds: 2.2 },
  draw: { bookmaker: "Orbit", odds: 3.6 },
  away: { bookmaker: "Betkanyon", odds: 3.4 },
}

const withOnWin = {
  opportunityType: "BACK_BACK",
  profitPercentage: 8,
  home: { bookmaker: "OnWin", odds: 1.9 },
  draw: { bookmaker: "Orbit", odds: 3.2 },
  away: { bookmaker: "kolay90", odds: 4.8 },
}

const backLay = {
  opportunityType: "BACK_LAY",
  profitPercentage: 1.1,
  back: { bookmaker: "Orbit", odds: 2.0 },
  lay: { bookmaker: "Orbit", odds: 2.1 },
}

describe("opportunity display filters", () => {
  it("applies a minimum arb percentage", () => {
    expect(filterOpportunities([backBack, backLay], { minArb: 2 })).toEqual([backBack])
  })

  it("applies a maximum arb percentage", () => {
    expect(filterOpportunities([backBack, withOnWin], { maxArb: 5 })).toEqual([backBack])
  })

  it("applies a minimum odds bound to all displayed odds", () => {
    expect(filterOpportunities([backBack, withOnWin], { minOdds: 2 })).toEqual([backBack])
  })

  it("applies a maximum odds bound to all displayed odds", () => {
    expect(filterOpportunities([backBack, withOnWin], { maxOdds: 4 })).toEqual([backBack])
  })

  it("combines all filters", () => {
    const kept = filterOpportunities([backBack, withOnWin, backLay], {
      minArb: 2,
      maxArb: 10,
      minOdds: 1.5,
      maxOdds: 5,
      bookmakers: ["Betkanyon", "Orbit"],
    })
    expect(kept).toEqual([backBack])
  })

  it("treats empty/unset filters as unrestricted", () => {
    expect(filterOpportunities([backBack, backLay], {})).toEqual([backBack, backLay])
    expect(parseOptionalNumber("")).toBeNull()
    expect(parseOptionalNumber("  ")).toBeNull()
  })

  it("restricts to selected bookmakers", () => {
    expect(
      filterOpportunities([backBack, withOnWin], { bookmakers: ["Betkanyon", "Orbit"] })
    ).toEqual([backBack])
  })

  it("treats ALL bookmakers as no restriction", () => {
    expect(filterOpportunities([backBack, withOnWin], { bookmakers: null })).toEqual([
      backBack,
      withOnWin,
    ])
    expect(filterOpportunities([backBack, withOnWin], { bookmakers: [] })).toEqual([
      backBack,
      withOnWin,
    ])
  })

  it("allows multiple bookmaker selection", () => {
    const kept = filterOpportunities([backBack, backLay], {
      bookmakers: ["Betkanyon", "Orbit"],
    })
    expect(kept).toEqual([backBack, backLay])
  })

  it("hides opportunities that include an unselected bookmaker", () => {
    expect(
      filterOpportunities([withOnWin], { bookmakers: ["Betkanyon", "Orbit"] })
    ).toEqual([])
  })

  it("derives bookmaker names from existing opportunity legs", () => {
    expect(bookmakersFromOpportunities([backBack, withOnWin])).toEqual([
      "Betkanyon",
      "kolay90",
      "OnWin",
      "Orbit",
    ])
  })
})

describe("last-good opportunity snapshot", () => {
  it("keeps the previous snapshot when the incoming list is empty", () => {
    expect(keepLastGoodSnapshot([], [backBack])).toEqual([backBack])
  })

  it("replaces the previous snapshot with a valid incoming list", () => {
    expect(keepLastGoodSnapshot([backLay], [backBack])).toEqual([backLay])
  })
})
