import { useEffect, useState } from "react"
import { createFileRoute } from "@tanstack/react-router"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RefreshCw, TrendingUp, DollarSign, Activity } from "lucide-react"

export const Route = createFileRoute("/")({
  component: Dashboard,
})

type Opportunity = {
  competition: string
  homeTeam: string
  awayTeam: string
  profitPercentage: number
  roi: number
  guaranteedProfit: number
  guaranteedReturn: number
  home: {
  bookmaker: string
  odds: number
  stake: number
}

draw: {
  bookmaker: string
  odds: number
  stake: number
}

away: {
  bookmaker: string
  odds: number
  stake: number
}
}

const API_URL = "http://127.0.0.1:8000/opportunities"

function Dashboard() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const loadOpportunities = async () => {
    try {
      setLoading(true)

      const response = await fetch(API_URL)

      if (!response.ok) {
        throw new Error("Failed to fetch opportunities")
      }

      const data = await response.json()

      setOpportunities(data)
      setLastUpdated(new Date())
    } catch (error) {
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOpportunities()

    const interval = setInterval(loadOpportunities, 5000)

    return () => clearInterval(interval)
  }, [])

  const totalProfit = opportunities.reduce(
    (sum, opportunity) => sum + opportunity.guaranteedProfit,
    0
  )

  const bestRoi = opportunities.length
    ? Math.max(...opportunities.map((opportunity) => opportunity.roi))
    : 0

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

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="bg-slate-900 border-slate-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-slate-400">
                Active Arbitrages
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{opportunities.length}</div>
            </CardContent>
          </Card>

          <Card className="bg-slate-900 border-slate-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-slate-400">
                Total Guaranteed Profit
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-emerald-400">
                ${totalProfit.toFixed(2)}
              </div>
            </CardContent>
          </Card>

          <Card className="bg-slate-900 border-slate-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-slate-400">
                Best ROI
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-cyan-400">
                {bestRoi.toFixed(2)}%
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="text-sm text-slate-500">
          {lastUpdated
            ? `Last updated: ${lastUpdated.toLocaleTimeString()}`
            : "Waiting for first scan..."}
        </div>

        {loading && opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <RefreshCw className="w-8 h-8 mx-auto mb-4 animate-spin text-cyan-400" />
              <div className="text-lg font-semibold">Scanning bookmakers...</div>
              <div className="text-slate-400 mt-2">
                Orbit • Betfair • Kolay90 • Novel34 • BetKanyon • OnWin
              </div>
            </CardContent>
          </Card>
        ) : opportunities.length === 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="py-12 text-center">
              <TrendingUp className="w-10 h-10 mx-auto mb-4 text-slate-500" />
              <div className="text-xl font-semibold">No arbitrage opportunities</div>
              <div className="text-slate-400 mt-2">
                The scanner is running and checking all connected bookmakers.
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {opportunities.map((opportunity, index) => (
              <Card
                key={index}
                className="bg-slate-900 border-slate-800 hover:border-cyan-500/50 transition-all duration-300"
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-xl">
                        {opportunity.homeTeam} vs {opportunity.awayTeam}
                      </CardTitle>
                      <div className="text-slate-400 mt-1">{opportunity.competition}</div>
                    </div>

                    <Badge className="bg-emerald-500 text-black text-lg px-3 py-1">
                      +{opportunity.roi.toFixed(2)}%
                    </Badge>
                  </div>
                </CardHeader>

                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-slate-400 text-sm">Guaranteed Profit</div>
                      <div className="text-2xl font-bold text-emerald-400">
                        ${opportunity.guaranteedProfit.toFixed(2)}
                      </div>
                    </div>

                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-slate-400 text-sm">Guaranteed Return</div>
                      <div className="text-2xl font-bold">
                        ${opportunity.guaranteedReturn.toFixed(2)}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="font-semibold text-emerald-400">HOME</div>
                        <Badge variant="outline">{opportunity.home.bookmaker}</Badge>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <div className="text-slate-400">Odds</div>
                          <div className="font-bold text-lg">{opportunity.home.odds}</div>
                        </div>
                        <div>
                          <div className="text-slate-400">Stake</div>
                          <div className="font-bold text-lg">${opportunity.home.stake}</div>
                        </div>
                      </div>
                    </div>

                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="font-semibold text-amber-400">DRAW</div>
                        <Badge variant="outline">{opportunity.draw.bookmaker}</Badge>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <div className="text-slate-400">Odds</div>
                          <div className="font-bold text-lg">{opportunity.draw.odds}</div>
                        </div>
                        <div>
                          <div className="text-slate-400">Stake</div>
                          <div className="font-bold text-lg">${opportunity.draw.stake}</div>
                        </div>
                      </div>
                    </div>

                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="font-semibold text-cyan-400">AWAY</div>
                        <Badge variant="outline">{opportunity.away.bookmaker}</Badge>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <div className="text-slate-400">Odds</div>
                          <div className="font-bold text-lg">{opportunity.away.odds}</div>
                        </div>
                        <div>
                          <div className="text-slate-400">Stake</div>
                          <div className="font-bold text-lg">${opportunity.away.stake}</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <Button className="w-full bg-emerald-500 hover:bg-emerald-600 text-black font-semibold">
                    <DollarSign className="w-4 h-4 mr-2" />
                    View Opportunity
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}