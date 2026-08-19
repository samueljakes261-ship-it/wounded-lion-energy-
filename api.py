from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from collector import get_cached_opportunities, get_collector_status


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
def opportunities():

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