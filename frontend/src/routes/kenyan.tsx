import { useCallback, useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertTriangle, Eye, EyeOff, Lock, RefreshCw, TrendingUp } from "lucide-react";
import {
  clearStoredKenyanSession,
  getStoredKenyanSession,
  resolveKenyanApiBase,
  storeKenyanSession,
} from "@/lib/kenyan-api-config";

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
  sport: string;
  competition: string;
  homeTeam: string;
  awayTeam: string;
  profitPercentage: number;
  roi: number;
  guaranteedProfit: number;
  guaranteedReturn: number;
  totalStake: number;
  home: KenyanLeg;
  draw: KenyanLeg;
  away: KenyanLeg;
};

type KenyanMode = "live" | "prematch";

// ------------------------------------------------------------
// Access gate
// ------------------------------------------------------------

function AccessGate({ onUnlocked }: { onUnlocked: () => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    // A leading/trailing space from copy-paste or autofill is a common,
    // purely-accidental source of "the code isn't working" -- trimming
    // client-side does not weaken the gate (the required code itself
    // has no surrounding whitespace) and avoids that specific footgun.
    const candidate = code.trim();

    try {
      const response = await fetch(`${KENYAN_API_BASE}/auth`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: candidate }),
      });

      if (!response.ok) {
        // Deliberately generic -- the backend never explains *why* a
        // code was rejected, so there is nothing more specific to show.
        setError("Incorrect access code.");
        return;
      }

      const data = await response.json();
      storeKenyanSession(data.token, data.expires_at);
      setCode("");
      onUnlocked();
    } catch {
      setError("Could not reach the Kenyan bookmakers service. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <Card className="bg-slate-900 border-slate-800 w-full max-w-sm">
        <CardHeader className="text-center space-y-2">
          <Lock className="w-8 h-8 mx-auto text-cyan-400" />
          <CardTitle>Kenyan Bookmakers</CardTitle>
          <p className="text-sm text-slate-400">Enter the access code to continue.</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="relative">
              <Input
                // `type="text"` + `WebkitTextSecurity` (rather than
                // `type="password"`) avoids triggering the browser's
                // saved-password autofill/heuristics entirely -- a
                // real password manager silently substituting an
                // unrelated saved credential for "localhost" into a
                // `type="password"` field is a known, confusing
                // failure mode for a short access code like this one.
                type="text"
                inputMode="text"
                autoFocus
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                name="kenyan-access-code"
                data-lpignore="true"
                data-1p-ignore="true"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="Access code"
                className="bg-slate-800 border-slate-700 text-center pr-10"
                style={
                  revealed ? undefined : ({ WebkitTextSecurity: "disc" } as React.CSSProperties)
                }
              />
              <button
                type="button"
                onClick={() => setRevealed((value) => !value)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                aria-label={revealed ? "Hide access code" : "Show access code"}
                tabIndex={-1}
              >
                {revealed ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {error ? <div className="text-sm text-rose-400 text-center">{error}</div> : null}
            <Button type="submit" className="w-full" disabled={submitting || !code.trim()}>
              {submitting ? "Checking..." : "Unlock"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------
// Dashboard
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
  return (
    <Card className="bg-slate-900 border-slate-800">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-lg">
              {opportunity.homeTeam} vs {opportunity.awayTeam}
            </CardTitle>
            <div className="text-slate-400 text-sm mt-1 truncate">{opportunity.competition}</div>
          </div>
          <Badge className="bg-emerald-500 text-black shrink-0">
            +{opportunity.profitPercentage.toFixed(2)}%
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <OpportunityRow label="HOME" teamName={opportunity.homeTeam} leg={opportunity.home} />
        <OpportunityRow label="DRAW" leg={opportunity.draw} />
        <OpportunityRow label="AWAY" teamName={opportunity.awayTeam} leg={opportunity.away} />
        <div className="mt-3 pt-3 border-t border-slate-800 flex items-center justify-between text-sm">
          <span className="text-slate-400">ROI</span>
          <span className="font-bold text-cyan-400">{opportunity.roi.toFixed(2)}%</span>
        </div>
      </CardContent>
    </Card>
  );
}

function KenyanDashboard({ token, onLocked }: { token: string; onLocked: () => void }) {
  const [mode, setMode] = useState<KenyanMode>("live");
  const [opportunities, setOpportunities] = useState<KenyanOpportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${KENYAN_API_BASE}/opportunities?mode=${mode}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.status === 401) {
        clearStoredKenyanSession();
        onLocked();
        return;
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      setOpportunities(await response.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load opportunities");
    } finally {
      setLoading(false);
    }
  }, [mode, token, onLocked]);

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
              <OpportunityCard key={index} opportunity={opportunity} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------
// Page: gate first, dashboard once unlocked
// ------------------------------------------------------------

function KenyanPage() {
  const [token, setToken] = useState<string | null>(null);
  const [checkedStorage, setCheckedStorage] = useState(false);

  useEffect(() => {
    const session = getStoredKenyanSession();
    setToken(session?.token ?? null);
    setCheckedStorage(true);
  }, []);

  if (!checkedStorage) {
    return <div className="min-h-screen bg-slate-950" />;
  }

  if (!token) {
    return <AccessGate onUnlocked={() => setToken(getStoredKenyanSession()?.token ?? null)} />;
  }

  return <KenyanDashboard token={token} onLocked={() => setToken(null)} />;
}
