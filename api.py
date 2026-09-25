from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from collector import (
    get_cached_opportunities,
    get_cached_prematch_opportunities,
    get_collector_status,
)
from kenyan.api_router import include_kenyan_routes
from kenyan.runner import get_runner


app = FastAPI(
    title="ArbScanner API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://woundedlionenergy.vercel.app",
        "https://wounded-lion-energy.vercel.app",
        "http://localhost:8080",
        # Local frontend dev server (vite dev), for local end-to-end
        # verification -- see frontend/.env.local (VITE_API_URL).
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():

    return {
        "application": "ArbScanner",
        "status": "running"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy"
    }


@app.get("/opportunities")
def opportunities(mode: str = "live"):
    """
    Live opportunities by default so existing consumers are unchanged.
    Pass mode=prematch for the separate prematch cache.
    """
    normalized = (mode or "live").strip().lower()
    if normalized in ("prematch", "pre-match", "mac-oncesi", "maç öncesi"):
        return get_cached_prematch_opportunities()
    return get_cached_opportunities()


@app.get("/status")
def status():
    """
    Collector/engine health -- independent of opportunity count.

    A collector reporting collectorStatus="RUNNING" with
    opportunityCount=0 is completely healthy: DATA COLLECTION and
    ARBITRAGE OPPORTUNITY EXISTING are two different things (see
    collector.py's CollectorStatus docstring). This is a pure read of
    a file the engine process publishes every tick -- it never starts
    or touches any collector itself, so polling this endpoint has no
    side effects.
    """

    return get_collector_status()


# ------------------------------------------------------------------
# Kenyan Bookmakers section -- fully isolated addition.
#
# Adds /kenyan/auth, /kenyan/opportunities, /kenyan/status. Does not
# alter any of the routes above, their behavior, or their CORS
# configuration (the Kenyan routes share the same CORS middleware,
# which is the one deliberately-shared piece of existing config -- see
# kenyan/api_router.py for the routes themselves and kenyan/access.py
# for the access-code/session gate they sit behind).
# ------------------------------------------------------------------
include_kenyan_routes(app)


@app.on_event("startup")
def _start_kenyan_workers():
    """
    Starts the 8 persistent Kenyan workers (SportPesa/Betika/1xBet/
    22Bet x LIVE/PREMATCH) once, when this API process boots.

    Unlike the Turkish/client-facing collectors (which are started
    exclusively by run_engine.py and read here only from a file
    cache -- see get_cached_opportunities()/get_collector_status()
    above), the Kenyan workers have no separate always-running engine
    process assumption in this deployment, so /kenyan/opportunities
    and /kenyan/status would otherwise never have any real data to
    serve. This call is idempotent (KenyanEngineRunner.start() no-ops
    if already started) and touches nothing outside kenyan/*.
    """
    get_runner().start()