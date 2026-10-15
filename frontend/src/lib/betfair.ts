export type BetfairRef = {
  bookmaker: string
  value?: number | null
}

export type BetfairOpportunity = {
  opportunityType: "BETFAIR"
  source: string
  sourceLabel?: string
  clusterId?: string
  matchClusterId?: string
  homeTeam: string
  awayTeam: string
  startTime?: string | null
  sport?: string
  league?: string
  competition?: string
  marketLabel?: string
  market?: string
  category?: string | null
  categoryLabel?: string | null
  direction?: string
  iddaaOdd?: number | null
  refOdd?: number | null
  refBookmaker?: string
  bestBackBookmaker?: string
  backStake?: number | null
  layStake?: number | null
  layLiability?: number | null
  commissionRate?: number | null
  profitIfBackWins?: number | null
  profitIfBackLoses?: number | null
  guaranteedProfit?: number | null
  eventOrientation?: string | null
  layAvailableSize?: number | null
  executionGrade?: string | null
  refs?: BetfairRef[]
  valuePct?: number | null
  profitPercentage?: number | null
  status?: string
  eventMatchScore?: number | null
  period?: string | null
  line?: number | null
  outcome?: string
  isLive: boolean | null
  liveClassification?: "LIVE" | "PREMATCH" | "UNKNOWN" | string
  liveClock?: string | null
  detectedAt?: string | null
  firstSeenAt?: string | null
  lastUpdatedAt?: string | null
  isProfitable?: boolean
}

export function isBetfairOpportunity(
  opportunity: { opportunityType?: string } | null | undefined
): opportunity is BetfairOpportunity {
  return opportunity?.opportunityType === "BETFAIR"
}

export function betfairMatchesMode(
  opportunity: BetfairOpportunity,
  mode: "live" | "prematch"
): boolean {
  if (mode === "live") {
    return opportunity.isLive === true
  }
  return opportunity.isLive === false
}

export function filterBetfairOpportunities(
  opportunities: BetfairOpportunity[],
  options: {
    mode: "live" | "prematch"
    minArb?: number | null
    maxArb?: number | null
    positiveValueOnly?: boolean
  }
): BetfairOpportunity[] {
  return opportunities.filter((opportunity) => {
    if (!betfairMatchesMode(opportunity, options.mode)) {
      return false
    }
    if (options.positiveValueOnly && opportunity.isProfitable !== true) {
      return false
    }
    const value =
      typeof opportunity.valuePct === "number"
        ? opportunity.valuePct
        : typeof opportunity.profitPercentage === "number"
          ? opportunity.profitPercentage
          : null
    if (options.minArb != null && (value == null || value < options.minArb)) {
      return false
    }
    if (options.maxArb != null && (value == null || value > options.maxArb)) {
      return false
    }
    return true
  })
}

export function formatUtcTimestamp(value: string | null | undefined): string {
  if (!value) {
    return ""
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString()
}
