/** Display-only filters. Does not change opportunity generation. */

export type FilterableOpportunity = Record<string, unknown>

export type OpportunityFilters = {
  minArb?: number | null
  maxArb?: number | null
  minOdds?: number | null
  maxOdds?: number | null
  bookmakers?: string[] | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function profitPercentage(opportunity: FilterableOpportunity): number | null {
  const value = opportunity.profitPercentage
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function displayedOdds(opportunity: FilterableOpportunity): number[] {
  const odds: number[] = []
  for (const key of ["home", "draw", "away", "back", "lay"] as const) {
    const leg = opportunity[key]
    if (isRecord(leg) && typeof leg.odds === "number" && Number.isFinite(leg.odds)) {
      odds.push(leg.odds)
    }
  }
  return odds
}

function displayedBookmakers(opportunity: FilterableOpportunity): string[] {
  const names: string[] = []
  for (const key of ["home", "draw", "away", "back", "lay"] as const) {
    const leg = opportunity[key]
    if (isRecord(leg) && typeof leg.bookmaker === "string" && leg.bookmaker.trim()) {
      names.push(leg.bookmaker)
    }
  }
  return names
}

export function parseOptionalNumber(raw: string): number | null {
  const trimmed = raw.trim()
  if (!trimmed) {
    return null
  }
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

export function bookmakersFromOpportunities(
  opportunities: FilterableOpportunity[]
): string[] {
  const seen = new Set<string>()
  for (const opportunity of opportunities) {
    for (const name of displayedBookmakers(opportunity)) {
      seen.add(name)
    }
  }
  return [...seen].sort((left, right) => left.localeCompare(right))
}

export function bookmakersFromStatus(
  collectors: Record<string, { name?: string }> | undefined,
  mode: "live" | "prematch"
): string[] {
  if (!collectors) {
    return []
  }
  const keys =
    mode === "prematch"
      ? Object.keys(collectors).filter((key) => key.endsWith("_prematch"))
      : Object.keys(collectors).filter((key) => !key.endsWith("_prematch"))
  const names = keys
    .map((key) => collectors[key]?.name || "")
    .map((name) => name.replace(/\s+Prematch$/i, "").trim())
    .filter(Boolean)
  return [...new Set(names)].sort((left, right) => left.localeCompare(right))
}

export function opportunityPassesFilters(
  opportunity: FilterableOpportunity,
  filters: OpportunityFilters
): boolean {
  const arb = profitPercentage(opportunity)
  if (filters.minArb != null && (arb == null || arb < filters.minArb)) {
    return false
  }
  if (filters.maxArb != null && (arb == null || arb > filters.maxArb)) {
    return false
  }

  const odds = displayedOdds(opportunity)
  if (filters.minOdds != null && (odds.length === 0 || odds.some((value) => value < filters.minOdds!))) {
    return false
  }
  if (filters.maxOdds != null && (odds.length === 0 || odds.some((value) => value > filters.maxOdds!))) {
    return false
  }

  const selected = filters.bookmakers
  if (selected && selected.length > 0) {
    const allowed = new Set(selected.map((name) => name.toLowerCase()))
    const names = displayedBookmakers(opportunity)
    if (names.length === 0 || names.some((name) => !allowed.has(name.toLowerCase()))) {
      return false
    }
  }
  return true
}

export function filterOpportunities<T extends FilterableOpportunity>(
  opportunities: T[],
  filters: OpportunityFilters
): T[] {
  return opportunities.filter((opportunity) =>
    opportunityPassesFilters(opportunity, filters)
  )
}

export function keepLastGoodSnapshot<T>(
  incoming: T[] | null | undefined,
  previous: T[]
): T[] {
  if (!Array.isArray(incoming)) {
    return previous
  }
  if (incoming.length === 0 && previous.length > 0) {
    return previous
  }
  return incoming
}
