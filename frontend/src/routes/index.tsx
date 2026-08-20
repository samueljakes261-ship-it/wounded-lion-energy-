import { useEffect, useState } from "react"
import { createFileRoute } from "@tanstack/react-router"
import { resolveApiConfig } from "@/lib/api-config"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  RefreshCw,
  TrendingUp,
  Activity,
  ChevronDown,
  AlertTriangle,
  CircleDot,
} from "lucide-react"

export const Route = createFileRoute("/")({
  component: Dashboard,
})

type Leg = {
  bookmaker: string
  odds: number
  stake: number
  // Exchange semantics (Orbit, etc). Absent/null for an ordinary
  // fixed-odds bookmaker (OnWin, BetKanyon) -- only ever "BACK" here
  // in practice, since the engine excludes LAY prices from this
  // 3-way selection (see engine/best_odds_selector.py).
  side?: string | null
  market?: string
  // ISO timestamp of when this specific bookmaker's odds were last
  // collected -- lets the UI (and anyone inspecting the API response)
  // verify how fresh a displayed price actually is, independent of
  // "when did the engine compute this opportunity".
  collectedAt?: string | null
}

type Opportunity = {
  competition: string
  homeTeam: string
  awayTeam: string
  profitPercentage: number
  roi: number
  guaranteedProfit: number
  guaranteedReturn: number
  totalStake: number
  generatedAt?: string | null
  home: Leg
  draw: Leg
  away: Leg
}

// One collector's health, independent of opportunity count -- see
// collector.py's CollectorStatus / /status endpoint. A collector can
// (and very often will) report RUNNING with zero current
// opportunities; that is normal, healthy behavior, not a fault.
type CollectorHealth = {
  name: string
        collectorStatus: "RUNNING" | "STARTING" | "RECOVERING" | "DEGRADED" | "STOPPED" | "ERROR"
  lastSuccessfulCollection: string | null
  lastCollectionAttempt: string | null
  ageSeconds: number | null
  eventsCollected: number
  error: string | null
}

type CollectorStatusResponse = {
  generatedAt: string | null
  matchedEvents: number
  opportunityCount: number
  collectors: Record<string, CollectorHealth>
}

// The backend base URL is ALWAYS read from VITE_API_URL -- never
// hardcoded here. See frontend/.env.example for the variable this
// build expects.
//
// - Local dev: frontend/.env.local sets VITE_API_URL (gitignored,
//   e.g. http://localhost:8000).
// - Production (Vercel): VITE_API_URL must be set as a Vercel project
//   environment variable pointing at a backend that is ACTUALLY
//   publicly reachable (a VPS/Render/Railway/etc. deployment, or --
//   only as an explicit, intentional temporary bridge -- a currently
//   running ngrok tunnel). Vite inlines VITE_* vars at build time, so
//   changing this in Vercel requires a new deployment to take effect.
//
// See lib/api-config.ts for the (unit-tested) resolution logic. The
// local-dev fallback there is a convenience only -- it deliberately
// does NOT fall back to any production/tunnel URL: a stale hardcoded
// URL here previously left the deployed frontend silently depending
// on a personal ngrok tunnel that could go offline at any time.
const { apiUrl: API_URL, statusUrl: STATUS_URL, usedLocalDevFallback } = resolveApiConfig({
  VITE_API_URL: import.meta.env.VITE_API_URL,
})

if (import.meta.env.PROD && usedLocalDevFallback) {
  // Loud, dev-console-only warning (no secrets) -- surfaces
  // misconfiguration immediately instead of quietly showing "no
  // opportunities" with no explanation.
  console.error(
    "[ArbScanner] VITE_API_URL is not set in this production build. " +
      `Falling back to ${API_URL}, which will not work for real visitors. ` +
      "Set VITE_API_URL in the Vercel project settings to a publicly " +
      "reachable backend URL and redeploy."
  )
}

// Opt-in, zero-cost-by-default trace of exactly what odds value this
// component rendered for each leg -- the final "FRONTEND DISPLAY"
// stage of the RAW -> PARSED -> ENGINE -> API -> FRONTEND trace (see
// debug/odds_trace.py for the backend stages). Never sends anything
// anywhere; just a local console log for manual comparison against
// the API response / bookmaker site.
const ODDS_TRACE = import.meta.env.VITE_ODDS_TRACE === "1"

function traceDisplayedOdds(opportunity: Opportunity) {
  if (!ODDS_TRACE) return
  for (const [label, leg] of [
    ["home", opportunity.home],
    ["draw", opportunity.draw],
    ["away", opportunity.away],
  ] as const) {
    console.debug(
      `[ODDS-TRACE] stage=FRONTEND ${leg.bookmaker} | ` +
        `${opportunity.homeTeam} vs ${opportunity.awayTeam} (${label}) | ` +
        `odds=${leg.odds} collectedAt=${leg.collectedAt ?? "n/a"}`
    )
  }
}

// Orbit is an exchange, not an ordinary bookmaker -- label it as such
// wherever a leg's bookmaker name is displayed, per the requirement
// that an Orbit price must never appear without its BACK/LAY side.
function bookmakerLabel(leg: Leg): string {
  if (leg.bookmaker.toLowerCase() === "orbit") {
    return "Orbit Exchange"
  }
  return leg.bookmaker
}

function LegBadges({ leg }: { leg: Leg }) {
  return (
    <div className="flex items-center gap-1.5">
      <Badge variant="outline">{bookmakerLabel(leg)}</Badge>
      {leg.side ? (
        <Badge
          className={
            leg.side === "LAY"
              ? "bg-rose-500/20 text-rose-300 border-rose-500/40"
              : "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
          }
        >
          {leg.side}
        </Badge>
      ) : null}
    </div>
  )
}

// One outcome row (HOME/DRAW/AWAY) in the collapsed card. Draw has no
// team name of its own, so `teamName` is optional.
function OutcomeRow({
  label,
  teamName,
  leg,
}: {
  label: string
  teamName?: string
  leg: Leg
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-slate-800 last:border-b-0">
      <div className="min-w-0">
        <div className="text-xs font-semibold text-slate-500 tracking-wide">
          {label}
        </div>
        {teamName ? (
          <div className="text-sm text-slate-200 truncate">{teamName}</div>
        ) : null}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="font-bold text-lg">{leg.odds}</span>
        <LegBadges leg={leg} />
      </div>
    </div>
  )
}

const COLLECTOR_STATUS_STYLES: Record<CollectorHealth["collectorStatus"], string> = {
  RUNNING: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  STARTING: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  RECOVERING: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
  DEGRADED: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  STOPPED: "bg-slate-600/30 text-slate-300 border-slate-500/40",
  ERROR: "bg-rose-500/20 text-rose-300 border-rose-500/40",
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "n/a"
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  return `${Math.round(seconds / 60)}m ago`
}

// Surfaces each collector's OWN health (RUNNING/STARTING/DEGRADED/
// STOPPED/ERROR), deliberately separate from opportunityCount --
// a collector showing RUNNING with 0 opportunities is healthy: data
// collection continuing and an arbitrage opportunity existing are two
// different things (see collector.py's CollectorStatus docstring).
function CollectorStatusPanel({
  status,
}: {
  status: CollectorStatusResponse | null
}) {
  if (!status) {
    return null
  }

  const order = ["orbit", "betkanyon", "onwin"]
  const collectors = order
    .map((key) => status.collectors[key])
    .filter((c): c is CollectorHealth => Boolean(c))

  return (
    <Card className="bg-slate-900 border-slate-800">
      <CardContent className="py-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="text-xs font-semibold text-slate-500 tracking-wide">
            COLLECTORS
          </div>
          {collectors.map((collector) => (
            <div key={collector.name} className="flex items-center gap-1.5">
              <CircleDot className="w-3 h-3 text-slate-500" />
              <span className="text-sm text-slate-300">{collector.name}</span>
              <Badge className={COLLECTOR_STATUS_STYLES[collector.collectorStatus]}>
                {collector.collectorStatus}
              </Badge>
              <span className="text-xs text-slate-500">
                {formatAge(collector.ageSeconds)}
              </span>
            </div>
          ))}
          <div className="text-xs text-slate-500 ml-auto">
            Matched events: {status.matchedEvents} &middot; Opportunities:{" "}
            {status.opportunityCount}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// One line in the expanded "Stake Plan" -- values already come
// straight from the backend's StakeCalculator/ArbitrageOpportunity
// output (see cached_opportunities.json / api.py), never recomputed
// here.
function StakeRow({
  label,
  value,
  emphasize,
}: {
  label: string
  value: number
  emphasize?: boolean
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-400">{label}</span>
      <span
        className={
          emphasize
            ? "font-bold text-emerald-400"
            : "font-medium text-slate-100"
        }
      >
        ${value.toFixed(2)}
      </span>
    </div>
  )
}

function OpportunityCard({ opportunity }: { opportunity: Opportunity }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    traceDisplayedOdds(opportunity)
  }, [opportunity])

  return (
    <Card className="bg-slate-900 border-slate-800 hover:border-cyan-500/50 transition-colors duration-300 overflow-hidden">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button type="button" className="w-full text-left cursor-pointer">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle className="text-lg">
                    {opportunity.homeTeam} vs {opportunity.awayTeam}
                  </CardTitle>
                  <div className="text-slate-400 text-sm mt-1 truncate">
                    {opportunity.competition}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Badge className="bg-emerald-500 text-black">
                    +{opportunity.profitPercentage.toFixed(2)}%
                  </Badge>
                  <ChevronDown
                    className={`w-4 h-4 text-slate-500 transition-transform duration-200 ${
                      open ? "rotate-180" : ""
                    }`}
                  />
                </div>
              </div>
            </CardHeader>

            <CardContent className="pt-0">
              <OutcomeRow
                label="HOME"
                teamName={opportunity.homeTeam}
                leg={opportunity.home}
              />
              <OutcomeRow label="DRAW" leg={opportunity.draw} />
              <OutcomeRow
                label="AWAY"
                teamName={opportunity.awayTeam}
                leg={opportunity.away}
              />
            </CardContent>
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0 pb-6">
            <div className="bg-slate-800 rounded-lg p-4 space-y-2">
              <div className="text-sm font-semibold text-slate-300 mb-1">
                Stake Plan
              </div>

              <StakeRow label="Home" value={opportunity.home.stake} />
              <StakeRow label="Draw" value={opportunity.draw.stake} />
              <StakeRow label="Away" value={opportunity.away.stake} />

              <div className="!my-3 border-t border-slate-700" />

              <StakeRow label="Total Stake" value={opportunity.totalStake} />
              <StakeRow
                label="Expected Return"
                value={opportunity.guaranteedReturn}
              />
              <StakeRow
                label="Guaranteed Profit"
                value={opportunity.guaranteedProfit}
                emphasize
              />

              <div className="flex items-center justify-between text-sm pt-1">
                <span className="text-slate-400">ROI</span>
                <span className="font-bold text-cyan-400">
                  {opportunity.roi.toFixed(2)}%
                </span>
              </div>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

function Dashboard() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [collectorStatus, setCollectorStatus] =
    useState<CollectorStatusResponse | null>(null)

  const loadCollectorStatus = async () => {
    try {
      const response = await fetch(STATUS_URL, {
        headers: { "ngrok-skip-browser-warning": "true" },
      })
      if (!response.ok) {
        // Supplementary UI -- never blocks/clears opportunities -- but
        // still worth a console trace (no secrets) so a misconfigured
        // backend URL isn't a silent mystery.
        console.warn(
          `[ArbScanner] /status request to ${STATUS_URL} returned ${response.status}`
        )
        return
      }
      setCollectorStatus(await response.json())
    } catch (err) {
      console.warn(
        `[ArbScanner] /status request to ${STATUS_URL} failed:`,
        err instanceof Error ? err.message : err
      )
    }
  }

  const loadOpportunities = async () => {
    try {
      setLoading(true)

      const response = await fetch(API_URL, {
       headers: {
        "ngrok-skip-browser-warning": "true",
       },
    })

      if (!response.ok) {
        throw new Error(
          `Failed to fetch opportunities (HTTP ${response.status} from ${API_URL})`
        )
      }

      const data = await response.json()

      setOpportunities(data)
      setLastUpdated(new Date())
      setError(null)
    } catch (err) {
      // Logged in full (URL + status, never secrets -- VITE_API_URL
      // never carries credentials) so production failures are
      // diagnosable from the browser console rather than silently
      // showing an empty opportunities list.
      console.error(`[ArbScanner] opportunities fetch failed:`, err)
      setError(
        err instanceof Error ? err.message : "Failed to fetch opportunities"
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOpportunities()
    loadCollectorStatus()

    const interval = setInterval(() => {
      loadOpportunities()
      loadCollectorStatus()
    }, 5000)

    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">ArbScanner</h1>
            <p className="text-slate-400">
              Live arbitrage opportunities from 6 bookmakers
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Badge className="bg-emerald-500 text-black">
              <Activity className="w-3 h-3 mr-1" />
              LIVE
            </Badge>

            <Button
              variant="outline"
              onClick={loadOpportunities}
              disabled={loading}
            >
              <RefreshCw
                className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`}
              />
              Scan Again
            </Button>
          </div>
        </div>

        <div className="text-sm text-slate-500">
          {lastUpdated
            ? `Last updated: ${lastUpdated.toLocaleTimeString()}`
            : "Waiting for first scan..."}
        </div>

        <CollectorStatusPanel status={collectorStatus} />

        {loading && opportunities.length === 0 && !error ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <RefreshCw className="w-8 h-8 mx-auto mb-4 animate-spin text-cyan-400" />
              <div className="text-lg font-semibold">Scanning bookmakers...</div>
              <div className="text-slate-400 mt-2">
                Orbit • Betfair • Kolay90 • Novel34 • BetKanyon • OnWin
              </div>
            </CardContent>
          </Card>
        ) : error && opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <AlertTriangle className="w-10 h-10 mx-auto mb-4 text-amber-500" />
              <div className="text-xl font-semibold">
                Unable to reach the scanner backend
              </div>
              <div className="text-slate-400 mt-2">{error}</div>
            </CardContent>
          </Card>
        ) : opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <TrendingUp className="w-10 h-10 mx-auto mb-4 text-slate-500" />
              <div className="text-xl font-semibold">
                No arbitrage opportunities detected.
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {opportunities.map((opportunity, index) => (
              <OpportunityCard key={index} opportunity={opportunity} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
