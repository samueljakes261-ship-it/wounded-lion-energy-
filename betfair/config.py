"""
Isolated configuration for the Betfair valuebets opportunity feed.

Kept independent of Kenyan and Turkish bookmaker timing constants so a
change here cannot alter those workers.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load repo-root `.env` even when systemd's WorkingDirectory is not the
# project directory. Do not override variables already in the process
# (systemd EnvironmentFile wins).
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

VALUEBETS_URL = os.getenv(
    "BETFAIR_VALUEBETS_URL",
    "https://verigood.top/valuebets",
)

LOGIN_URL = os.getenv(
    "BETFAIR_VALUEBETS_LOGIN_URL",
    "https://verigood.top/api/auth/login",
)

# Product requirement: poll this endpoint every 3 seconds.
POLL_INTERVAL_SECONDS = float(os.getenv("BETFAIR_POLL_INTERVAL_SECONDS", "3"))

HTTP_TIMEOUT_SECONDS = float(os.getenv("BETFAIR_HTTP_TIMEOUT_SECONDS", "8"))

# Several missed 3s cycles before a previously-good snapshot is dropped.
STALE_AFTER_SECONDS = float(os.getenv("BETFAIR_STALE_AFTER_SECONDS", "15"))

DEGRADE_AFTER_CONSECUTIVE_FAILURES = int(
    os.getenv("BETFAIR_DEGRADE_AFTER_CONSECUTIVE_FAILURES", "3")
)
RECOVER_AFTER_CONSECUTIVE_SUCCESSES = int(
    os.getenv("BETFAIR_RECOVER_AFTER_CONSECUTIVE_SUCCESSES", "2")
)

# Login retry backoff after a failed POST /api/auth/login.
AUTH_RETRY_INITIAL_SECONDS = float(
    os.getenv("BETFAIR_AUTH_RETRY_INITIAL_SECONDS", "5")
)
AUTH_RETRY_MAX_SECONDS = float(os.getenv("BETFAIR_AUTH_RETRY_MAX_SECONDS", "60"))

CACHE_FILE = Path(
    os.getenv("BETFAIR_CACHE_FILE", "cached_betfair_opportunities.json")
)

SOURCE_ID = "betfair"
SOURCE_LABEL = "Betfair"

USER_AGENT = os.getenv(
    "BETFAIR_USER_AGENT",
    "WoundedLionEnergy/2.0 (Betfair valuebets feed)",
)
