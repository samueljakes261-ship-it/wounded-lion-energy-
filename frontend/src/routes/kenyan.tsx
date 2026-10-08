import { useCallback, useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { StakePlanPanel } from "@/components/stake-plan";
import { t } from "@/lib/i18n";
import { AlertTriangle, ChevronDown, RefreshCw, TrendingUp } from "lucide-react";
import { resolveKenyanApiBase } from "@/lib/kenyan-api-config";

export const Route = createFileRoute("/kenyan")({
  component: KenyanPage,
});

const KENYAN_API_BASE = resolveKenyanApiBase({ VITE_API_URL: import.meta.env.VITE_API_URL });

type KenyanLeg = {
  bookmaker: string;
  odds: number;
  stake: number;
};

type KenyanOpportunity = {
  opportunityId?: string;
  opportunityType?: string;
  isLive?: boolean;
  sport: string;
  competition: string;
  market?: string;
  marketLabel?: string;
  line?: number | null;
  period?: string | null;
  outcomeCount?: number;
  homeLabel?: string;
  awayLabel?: string;
  homeTeam: string;
  awayTeam: string;
  profitPercentage: number;
  roi: number;
  guaranteedProfit: number;
  guaranteedReturn: number;
  totalStake: number;
  home: KenyanLeg;
  draw: KenyanLeg | null;
  away: KenyanLeg;
};

type KenyanMode = "live" | "prematch";

// ------------------------------------------------------------
// Dashboard
//
// NOTE: this section previously required an access code before
// showing opportunities (see git history for the removed AccessGate
// component and kenyan/access.py's server-side code/session-token
// machinery, which is untouched and could be re-attached later). That
// gate was removed at explicit user request -- the "KENYAN
// BOOKMAKERS" nav link now goes straight to this view.
// ------------------------------------------------------------

function OpportunityRow({
  label,
  teamName,
  leg,
}: {
  label: string;
  teamName?: string;
  leg: KenyanLeg;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-slate-800 last:border-b-0">
      <div className="min-w-0">
        <div className="text-xs font-semibold text-slate-500 tracking-wide">{label}</div>
        {teamName ? <div className="text-sm text-slate-200 truncate">{teamName}</div> : null}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="font-bold text-lg">{leg.odds}</span>
        <Badge variant="outline">{leg.bookmaker}</Badge>
      </div>
    </div>
  );
}

function OpportunityCard({ opportunity }: { opportunity: KenyanOpportunity }) {
  const [open, setOpen] = useState(false);
  const twoWay = opportunity.outcomeCount === 2 || opportunity.draw == null;
  const homeLabel = opportunity.homeLabel || "HOME";
  const awayLabel = opportunity.awayLabel || "AWAY";
  const marketText = opportunity.marketLabel || opportunity.market || "Match Winner";

  return (
    <Card
      data-testid="kenyan-opportunity-card"
      className="bg-slate-900 border-slate-800 hover:border-cyan-500/50 transition-colors duration-300 overflow-hidden"
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button type="button" className="w-full text-left cursor-pointer">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle className="text-lg">
                    {opportunity.homeTeam} vs {opportunity.awayTeam}
                  </CardTitle>
                  <div className="text-slate-400 text-sm mt-1 truncate">{opportunity.competition}</div>
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    <Badge variant="outline" className="text-[10px] tracking-wide">
                      {opportunity.isLive ? "LIVE" : "PREMATCH"}
                    </Badge>
                    <Badge
                      data-testid="kenyan-market-label"
                      variant="outline"
                      className="text-[10px] tracking-wide text-cyan-300 border-cyan-700/60"
                    >
                      MARKET {marketText}
                    </Badge>
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
              <OpportunityRow label={homeLabel} teamName={opportunity.homeTeam} leg={opportunity.home} />
              {twoWay || !opportunity.draw ? null : (
                <OpportunityRow label="DRAW" leg={opportunity.draw} />
              )}
              <OpportunityRow label={awayLabel} teamName={opportunity.awayTeam} leg={opportunity.away} />
            </CardContent>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="pt-0 pb-6">
            <StakePlanPanel
              labels={{
                title: t("en", "stakePlan"),
                home: twoWay ? homeLabel : t("en", "home"),
                draw: twoWay ? "" : t("en", "draw"),
                away: twoWay ? awayLabel : t("en", "away"),
                totalStake: t("en", "totalStake"),
                expectedReturn: t("en", "expectedReturn"),
                guaranteedProfit: t("en", "guaranteedProfit"),
                roi: t("en", "roi"),
              }}
              values={{
                homeStake: opportunity.home.stake,
                drawStake: opportunity.draw?.stake ?? 0,
                awayStake: opportunity.away.stake,
                totalStake: opportunity.totalStake,
                guaranteedReturn: opportunity.guaranteedReturn,
                guaranteedProfit: opportunity.guaranteedProfit,
                roi: opportunity.roi,
              }}
            />
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

function KenyanDashboard() {
  const [mode, setMode] = useState<KenyanMode>("prematch");
  const [opportunities, setOpportunities] = useState<KenyanOpportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${KENYAN_API_BASE}/opportunities?mode=${mode}`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      if (Array.isArray(data)) {
        setOpportunities(data);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load opportunities");
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold">Kenyan Bookmakers</h1>
            <p className="text-slate-400 text-sm">
              SportPesa &middot; Betika &middot; 1xBet &middot; 22Bet -- BACK vs BACK only
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={mode === "live" ? "default" : "outline"}
              onClick={() => setMode("live")}
            >
              LIVE
            </Button>
            <Button
              size="sm"
              variant={mode === "prematch" ? "default" : "outline"}
              onClick={() => setMode("prematch")}
            >
              PREMATCH
            </Button>
            <Button size="sm" variant="outline" onClick={load} disabled={loading}>
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {error ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-8 text-center">
              <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-amber-500" />
              <div className="text-slate-300">{error}</div>
            </CardContent>
          </Card>
        ) : opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <TrendingUp className="w-8 h-8 mx-auto mb-3 text-slate-500" />
              <div className="text-slate-300">
                No {mode === "live" ? "live" : "prematch"} Kenyan arbitrage opportunities right now.
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {opportunities.map((opportunity, index) => (
              <OpportunityCard
                key={opportunity.opportunityId || `${opportunity.homeTeam}-${opportunity.awayTeam}-${index}`}
                opportunity={opportunity}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function KenyanPage() {
  return <KenyanDashboard />;
}
