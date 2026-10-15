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
# Prematch stays on the 5s catalogue cadence. LIVE workers are
# independent threads, so they no longer need a 15s gap to avoid
# starving prematch. 2s is the floor between LIVE polls: a slow
# bookmaker still cannot overlap itself, and a fast one is not
# hammered every 200ms.
# ------------------------------------------------------------------
KENYAN_POLL_INTERVAL_SECONDS = float(os.getenv("KENYAN_POLL_INTERVAL_SECONDS", "5"))
KENYAN_PREMATCH_POLL_INTERVAL_SECONDS = float(
    os.getenv("KENYAN_PREMATCH_POLL_INTERVAL_SECONDS", str(KENYAN_POLL_INTERVAL_SECONDS))
)
KENYAN_LIVE_POLL_INTERVAL_SECONDS = float(
    os.getenv("KENYAN_LIVE_POLL_INTERVAL_SECONDS", "2")
)

# LIVE matching wakes immediately when a worker publishes. This idle
# timeout only covers the case where no bookmaker has published, so
# stale cards can still expire.
KENYAN_LIVE_COMPUTE_IDLE_SECONDS = float(
    os.getenv("KENYAN_LIVE_COMPUTE_IDLE_SECONDS", "1")
)

# How long a worker's last-good snapshot is still trusted after its
# most recent successful acquisition. Uncapped prematch walks many
# VZip/Betika pages and routinely takes longer than 45s, so the window
# must outlast one full prematch cycle or the snapshot is born expired
# and /kenyan/opportunities?mode=prematch stays empty.
KENYAN_STALE_AFTER_SECONDS = float(os.getenv("KENYAN_STALE_AFTER_SECONDS", "180"))

# LIVE confirmation must land inside this window or the price is
# unusable. Quiet markets may keep the same odds; confirmation, not
# last price change, is the expiry clock. PREMATCH keeps the
# catalogue-walk window above. KENYAN_STALE_AFTER_SECONDS remains the
# shared/prematch default so existing env files keep working.
KENYAN_LIVE_STALE_AFTER_SECONDS = float(
    os.getenv("KENYAN_LIVE_STALE_AFTER_SECONDS", "45")
)
KENYAN_PREMATCH_STALE_AFTER_SECONDS = float(
    os.getenv(
        "KENYAN_PREMATCH_STALE_AFTER_SECONDS",
        str(KENYAN_STALE_AFTER_SECONDS),
    )
)

# How long a computed Kenyan opportunity is retained after a poll no
# longer returns it. LIVE uses the live stale window so cards do not
# stay actionable after the odds are outdated. PREMATCH keeps the
# longer catalogue-walk grace.
KENYAN_OPPORTUNITY_RETENTION_SECONDS = float(
    os.getenv("KENYAN_OPPORTUNITY_RETENTION_SECONDS", str(KENYAN_STALE_AFTER_SECONDS))
)
KENYAN_LIVE_OPPORTUNITY_RETENTION_SECONDS = float(
    os.getenv(
        "KENYAN_LIVE_OPPORTUNITY_RETENTION_SECONDS",
        str(KENYAN_LIVE_STALE_AFTER_SECONDS),
    )
)
KENYAN_PREMATCH_OPPORTUNITY_RETENTION_SECONDS = float(
    os.getenv(
        "KENYAN_PREMATCH_OPPORTUNITY_RETENTION_SECONDS",
        str(KENYAN_PREMATCH_STALE_AFTER_SECONDS),
    )
)

# LIVE pagination ceilings. LIVE catalogues are small; these bound a
# hung or repeating cursor without waiting on a full prematch walk.
# Hitting one is recorded as page_cap_hit / snapshot_complete=False.
KENYAN_VZIP_MAX_PAGES = int(os.getenv("KENYAN_VZIP_MAX_PAGES", "80"))
KENYAN_BETIKA_MAX_PAGES = int(os.getenv("KENYAN_BETIKA_MAX_PAGES", "80"))
KENYAN_SPORTPESA_LIVE_DISCOVERY_LIMIT = int(
    os.getenv("KENYAN_SPORTPESA_LIVE_DISCOVERY_LIMIT", "50")
)
KENYAN_SPORTPESA_LIVE_MAX_PAGES = int(
    os.getenv("KENYAN_SPORTPESA_LIVE_MAX_PAGES", "40")
)

# PREMATCH has no catalogue-size page ceiling. Workers stop on a short
# or empty page, a reported total, or a repeated cursor. This runaway
# figure is only infinite-loop protection; hitting it is incomplete,
# never treated as the end of the bookmaker catalogue.
KENYAN_PREMATCH_RUNAWAY_PAGES = int(
    os.getenv("KENYAN_PREMATCH_RUNAWAY_PAGES", "10000")
)
# Kept so existing env files still parse. PREMATCH acquisition no
# longer uses it as a stop; LIVE SportPesa discovery uses
# KENYAN_SPORTPESA_LIVE_MAX_PAGES.
KENYAN_SPORTPESA_PREMATCH_MAX_PAGES = int(
    os.getenv(
        "KENYAN_SPORTPESA_PREMATCH_MAX_PAGES",
        str(KENYAN_PREMATCH_RUNAWAY_PAGES),
    )
)

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

SPORTS = {
    "football": {"1xbet_id": 1, "bet22_id": 1, "betika_id": 14, "betika_name": "soccer"},
    "tennis": {"1xbet_id": 4, "bet22_id": 4, "betika_id": 28, "betika_name": "tennis"},
    "basketball": {"1xbet_id": 3, "bet22_id": 3, "betika_id": 30, "betika_name": "basketball"},
    "volleyball": {"1xbet_id": 6, "bet22_id": 6, "betika_id": 35, "betika_name": "volleyball"},
}
