import { useEffect, useState } from "react"
import { createFileRoute } from "@tanstack/react-router"
import { resolveApiConfig } from "@/lib/api-config"
import { t, type FeedMode, type Lang } from "@/lib/i18n"
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
  opportunityType?: "BACK_BACK" | string
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

type BackLayPrice = {
  bookmaker: string
  side: string
  odds: number
}

type BackLayOpportunity = {
  opportunityType: "BACK_LAY"
  homeTeam: string
  awayTeam: string
  outcome: string
  arbitrageTeam: string
  back: BackLayPrice
  lay: BackLayPrice
}

type ApiOpportunity = Opportunity | BackLayOpportunity

function isBackLayOpportunity(
  opportunity: ApiOpportunity
): opportunity is BackLayOpportunity {
  return opportunity.opportunityType === "BACK_LAY"
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
  engineMode?: "live" | "prematch"
  prematchMatchedEvents?: number
  prematchOpportunityCount?: number
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
  const name =
    leg.bookmaker.toLowerCase() === "orbit" ? "Orbit" : leg.bookmaker
  if (leg.bookmaker.toLowerCase() === "orbit" && leg.side) {
    return `${name} — ${leg.side}`
  }
  if (leg.bookmaker.toLowerCase() === "orbit") {
    return "Orbit Exchange"
  }
  return name
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
  mode,
  lang,
}: {
  status: CollectorStatusResponse | null
  mode: FeedMode
  lang: Lang
}) {
  if (!status) {
    return null
  }

  const order =
    mode === "prematch"
      ? ["orbit_prematch", "betkanyon_prematch"]
      : ["orbit", "betkanyon", "onwin"]
  const collectors = order
    .map((key) => status.collectors[key])
    .filter((c): c is CollectorHealth => Boolean(c))
  const matched =
    mode === "prematch"
      ? (status as CollectorStatusResponse & { prematchMatchedEvents?: number })
          .prematchMatchedEvents ?? status.matchedEvents
      : status.matchedEvents
  const opps =
    mode === "prematch"
      ? (status as CollectorStatusResponse & { prematchOpportunityCount?: number })
          .prematchOpportunityCount ?? status.opportunityCount
      : status.opportunityCount

  return (
    <Card className="bg-slate-900 border-slate-800">
      <CardContent className="py-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="text-xs font-semibold text-slate-500 tracking-wide">
            {t(lang, "collectors")}
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
            {t(lang, "matchedEvents")}: {matched} &middot; {t(lang, "opportunities")}:{" "}
            {opps}
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

function formatOdds(odds: number): string {
  return odds.toFixed(2)
}

function BackLayCard({
  opportunity,
  lang,
}: {
  opportunity: BackLayOpportunity
  lang: Lang
}) {
  const teamName =
    opportunity.outcome === "DRAW"
      ? t(lang, "draw")
      : opportunity.arbitrageTeam || opportunity.homeTeam

  return (
    <Card
      data-testid="back-lay-card"
      className="bg-slate-900 border-slate-800 hover:border-cyan-500/50 transition-colors duration-300"
    >
      <CardHeader className="pb-3">
        <div className="text-xs font-semibold text-slate-500 tracking-wide">
          {t(lang, "matchLabel")}
        </div>
        <CardTitle className="text-lg">
          {opportunity.homeTeam} vs {opportunity.awayTeam}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        <div>
          <div className="text-xs font-semibold text-slate-500 tracking-wide">
            {t(lang, "arbitrageLabel")}
          </div>
          <div className="text-base text-slate-100 mt-0.5">{teamName}</div>
        </div>
        <div className="text-sm text-slate-200 space-y-1">
          <div>
            {opportunity.back.bookmaker} — {opportunity.back.side} @{" "}
            {formatOdds(opportunity.back.odds)}
          </div>
          <div>
            {opportunity.lay.bookmaker} — {opportunity.lay.side} @{" "}
            {formatOdds(opportunity.lay.odds)}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function OpportunityCard({
  opportunity,
  lang,
}: {
  opportunity: Opportunity
  lang: Lang
}) {
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
                label={t(lang, "home")}
                teamName={opportunity.homeTeam}
                leg={opportunity.home}
              />
              <OutcomeRow label={t(lang, "draw")} leg={opportunity.draw} />
              <OutcomeRow
                label={t(lang, "away")}
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
                {t(lang, "stakePlan")}
              </div>

              <StakeRow label={t(lang, "home")} value={opportunity.home.stake} />
              <StakeRow label={t(lang, "draw")} value={opportunity.draw.stake} />
              <StakeRow label={t(lang, "away")} value={opportunity.away.stake} />

              <div className="!my-3 border-t border-slate-700" />

              <StakeRow label={t(lang, "totalStake")} value={opportunity.totalStake} />
              <StakeRow
                label={t(lang, "expectedReturn")}
                value={opportunity.guaranteedReturn}
              />
              <StakeRow
                label={t(lang, "guaranteedProfit")}
                value={opportunity.guaranteedProfit}
                emphasize
              />

              <div className="flex items-center justify-between text-sm pt-1">
                <span className="text-slate-400">{t(lang, "roi")}</span>
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
  const [opportunities, setOpportunities] = useState<ApiOpportunity[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [collectorStatus, setCollectorStatus] =
    useState<CollectorStatusResponse | null>(null)
  const [lang, setLang] = useState<Lang>("tr")
  const [mode, setMode] = useState<FeedMode>("live")
  const [backBackOpen, setBackBackOpen] = useState(false)

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

      const response = await fetch(`${API_URL}?mode=${mode}`, {
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
  }, [mode])

  useEffect(() => {
    if (collectorStatus?.engineMode === "prematch" && mode !== "prematch") {
      setMode("prematch")
    }
  }, [collectorStatus?.engineMode])

  const backLayOpportunities = opportunities.filter(isBackLayOpportunity)
  const backBackOpportunities = opportunities.filter(
    (opportunity): opportunity is Opportunity => !isBackLayOpportunity(opportunity)
  )

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold">{t(lang, "title")}</h1>
            <p className="text-slate-400">
              {mode === "live" ? t(lang, "subtitleLive") : t(lang, "subtitlePrematch")}
            </p>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex rounded-md overflow-hidden border border-slate-700">
              <button
                type="button"
                className={`px-3 py-1 text-sm font-semibold ${
                  lang === "tr" ? "bg-cyan-500 text-black" : "bg-slate-900 text-slate-300"
                }`}
                onClick={() => setLang("tr")}
              >
                TR
              </button>
              <button
                type="button"
                className={`px-3 py-1 text-sm font-semibold ${
                  lang === "en" ? "bg-cyan-500 text-black" : "bg-slate-900 text-slate-300"
                }`}
                onClick={() => setLang("en")}
              >
                EN
              </button>
            </div>

            <div className="flex rounded-md overflow-hidden border border-slate-700">
              <button
                type="button"
                className={`px-3 py-1 text-sm font-semibold ${
                  mode === "live"
                    ? "bg-emerald-500 text-black"
                    : "bg-slate-900 text-slate-300"
                }`}
                onClick={() => setMode("live")}
              >
                {t(lang, "live")}
              </button>
              <button
                type="button"
                className={`px-3 py-1 text-sm font-semibold ${
                  mode === "prematch"
                    ? "bg-emerald-500 text-black"
                    : "bg-slate-900 text-slate-300"
                }`}
                onClick={() => setMode("prematch")}
              >
                {t(lang, "prematch")}
              </button>
            </div>

            <Button
              variant="outline"
              onClick={loadOpportunities}
              disabled={loading}
            >
              <RefreshCw
                className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`}
              />
              {t(lang, "scanAgain")}
            </Button>
          </div>
        </div>

        <div className="text-sm text-slate-500">
          {lastUpdated
            ? `${t(lang, "lastUpdated")}: ${lastUpdated.toLocaleTimeString()}`
            : t(lang, "waiting")}
        </div>

        {collectorStatus?.engineMode === "prematch" ? (
          <div className="text-sm text-amber-300 border border-amber-500/40 bg-amber-500/10 rounded-md px-3 py-2">
            {lang === "tr"
              ? "Maç öncesi hata ayıklama: canlı işçiler donduruldu. Sadece /opportunities?mode=prematch gösteriliyor."
              : "Prematch debug: live workers are frozen. Showing /opportunities?mode=prematch only."}
          </div>
        ) : null}

        <CollectorStatusPanel status={collectorStatus} mode={mode} lang={lang} />

        {loading && opportunities.length === 0 && !error ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <RefreshCw className="w-8 h-8 mx-auto mb-4 animate-spin text-cyan-400" />
              <div className="text-lg font-semibold">{t(lang, "scanning")}</div>
              <div className="text-slate-400 mt-2">
                {t(lang, "scanningHint")}
              </div>
            </CardContent>
          </Card>
        ) : error && opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <AlertTriangle className="w-10 h-10 mx-auto mb-4 text-amber-500" />
              <div className="text-xl font-semibold">
                {t(lang, "backendError")}
              </div>
              <div className="text-slate-400 mt-2">{error}</div>
            </CardContent>
          </Card>
        ) : opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <TrendingUp className="w-10 h-10 mx-auto mb-4 text-slate-500" />
              <div className="text-xl font-semibold">
                {t(lang, "noOpps")}
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-6">
            <section className="space-y-3">
              <h2 className="text-sm font-semibold tracking-wide text-slate-400">
                {t(lang, "backVsLay")}
              </h2>
              {backLayOpportunities.length === 0 ? (
                <div className="text-sm text-slate-500">{t(lang, "noBackLay")}</div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {backLayOpportunities.map((opportunity, index) => (
                    <BackLayCard
                      key={`back-lay-${index}`}
                      opportunity={opportunity}
                      lang={lang}
                    />
                  ))}
                </div>
              )}
            </section>

            {backBackOpportunities.length > 0 ? (
              <Collapsible
                open={backBackOpen}
                onOpenChange={setBackBackOpen}
                defaultOpen={false}
              >
                <CollapsibleTrigger asChild>
                  <button
                    type="button"
                    data-testid="back-back-toggle"
                    className="flex items-center gap-2 text-sm font-semibold tracking-wide text-slate-400 hover:text-slate-200"
                  >
                    <ChevronDown
                      className={`w-4 h-4 transition-transform duration-200 ${
                        backBackOpen ? "rotate-180" : ""
                      }`}
                    />
                    {t(lang, "backVsBackOpportunities")}
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-3">
                    {backBackOpportunities.map((opportunity, index) => (
                      <OpportunityCard
                        key={`back-back-${index}`}
                        opportunity={opportunity}
                        lang={lang}
                      />
                    ))}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
