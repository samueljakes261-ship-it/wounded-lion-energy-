"""
Configuration/constants for the isolated Kenyan Bookmakers module.

Deliberately self-contained: does NOT import or override anything from
collector.py / run_engine.py's own constants (MAX_ODDS_AGE_SECONDS,
ENGINE_TICK_SECONDS, etc). The existing Turkish/client-facing engine's
timing is untouched.
"""
import os

# ------------------------------------------------------------------
# Polling.
#
# Every one of the four Kenyan bookmakers is polled every 5 seconds,
# per the explicit product requirement. This is intentionally a
# separate constant from the existing engine's timings so a future
# change to either one can never accidentally affect the other.
# ------------------------------------------------------------------
KENYAN_POLL_INTERVAL_SECONDS = float(os.getenv("KENYAN_POLL_INTERVAL_SECONDS", "5"))

# How long a worker's last-good snapshot is still trusted after its
# most recent successful acquisition, before being treated as stale
# and dropped from the arbitrage calculation. Several multiples of the
# 5s poll interval so a single missed cycle (or two) doesn't instantly
# blank out otherwise-valid odds, while a feed that has genuinely gone
# quiet for a long time still gets excluded.
KENYAN_STALE_AFTER_SECONDS = float(os.getenv("KENYAN_STALE_AFTER_SECONDS", "45"))

# Consecutive-failure / consecutive-success hysteresis for flipping a
# worker's reported health, mirroring the spirit of
# engine/collector_health.py's approach for the existing workers but
# kept as an independent copy (see kenyan/health.py) so nothing here
# can ever change the existing feeds' behavior.
KENYAN_DEGRADE_AFTER_CONSECUTIVE_FAILURES = int(
    os.getenv("KENYAN_DEGRADE_AFTER_CONSECUTIVE_FAILURES", "3")
)
KENYAN_RECOVER_AFTER_CONSECUTIVE_SUCCESSES = int(
    os.getenv("KENYAN_RECOVER_AFTER_CONSECUTIVE_SUCCESSES", "2")
)

# HTTP request timeout for a single acquisition call.
KENYAN_HTTP_TIMEOUT_SECONDS = float(os.getenv("KENYAN_HTTP_TIMEOUT_SECONDS", "10"))

# Default bankroll used for Kenyan stake-plan calculations. Independent
# of main.py's BANKROLL constant.
KENYAN_BANKROLL = float(os.getenv("KENYAN_BANKROLL", "1000"))

# A plain browser-like User-Agent. Several Kenyan bookmaker endpoints
# reject requests with no/blank User-Agent outright, independent of
# any anti-bot challenge.
KENYAN_USER_AGENT = os.getenv(
    "KENYAN_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

# East Africa Time (Kenya) offset. Used only for "is this event today"
# filtering on prematch feeds -- a match at 2026-08-31 01:00 EAT is
# "tomorrow" locally even though it may still be "today" in UTC.
KENYA_UTC_OFFSET_HOURS = 3

# Bookmaker identifiers -- used consistently across models, workers,
# diagnostics and the frontend so nothing free-types a bookmaker name.
SPORTPESA = "SportPesa"
BETIKA = "Betika"
ONEXBET = "1xBet"
BET22 = "22Bet"

ALL_KENYAN_BOOKMAKERS = (SPORTPESA, BETIKA, ONEXBET, BET22)

LIVE = "LIVE"
PREMATCH = "PREMATCH"
