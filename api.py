from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from collector import get_cached_opportunities


app = FastAPI(
    title="ArbScanner API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://wounded-lion-energy.vercel.app",
        "http://localhost:8080",
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