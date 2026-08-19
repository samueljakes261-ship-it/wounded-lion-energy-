"""
Shared failure-classification + hysteresis policy for the three
persistent bookmaker workers (OnWin, BetKanyon, Orbit) and for
collector.py's collector-health classifier.

Kept dependency-free (no imports from collector.py or any worker
module) so every worker module can import it without risking a
circular import with collector.py, which itself imports all three
worker modules.

WHY THIS MODULE EXISTS
-----------------------
Before this module existed, every worker treated ANY exception the
same way: tear down the entire session/browser/socket and start a
full reconnect from scratch, and the collector-health classifier
treated "currently reconnecting" as unconditionally DEGRADED. That
meant a single transient hiccup (one timeout, one malformed message)
looked identical to a genuinely dead bookmaker feed, and because a
full reconnect (especially OnWin/BetKanyon's ZenRows browser
re-navigation) is comparatively slow, it also reliably burned enough
wall-clock time to push the feed's data past MAX_ODDS_AGE_SECONDS --
turning a brief blip into real, visible opportunity loss.

This module gives every worker a shared, consistent policy for:

  1. Deciding whether a caught exception means the underlying
     transport is actually dead (`is_connection_dead_error`) -- in
     which case only a full reconnect can help -- or whether it is
     worth retrying the SAME still-alive session first.
  2. How many consecutive failures/successes it takes to actually
     flip a collector's REPORTED health (see collector.py's
     `_classify_collector_status`), so a single blip does not read as
     "the bookmaker is down" and a single lucky retry does not read
     as "fully recovered".
"""

# ------------------------------------------------------------------
# Hysteresis thresholds.
#
# Chosen relative to each worker's own natural cycle time (BetKanyon
# ~3s poll via BETKANYON_POLL_INTERVAL, Orbit/OnWin push-driven with
# near-continuous frames) and collector.py's MAX_ODDS_AGE_SECONDS
# (30s default): DEGRADE_AFTER_CONSECUTIVE_FAILURES failures in a row,
# even paired with MAX_INPLACE_RETRIES's short in-place retry pause
# below, still resolves in well under 30s for all three feeds -- so
# genuinely fresh last-known-good data is never reported DEGRADED just
# because a retry is in flight, while a feed that is ACTUALLY down for
# several cycles in a row still gets flagged before its data would
# silently go stale. RECOVER_AFTER_CONSECUTIVE_SUCCESSES intentionally
# requires more than one clean cycle before fully trusting a worker
# again, so a single lucky retry sandwiched between failures doesn't
# flap the reported status back and forth.
# ------------------------------------------------------------------
DEGRADE_AFTER_CONSECUTIVE_FAILURES = 3
RECOVER_AFTER_CONSECUTIVE_SUCCESSES = 2

# How many consecutive failures on the SAME session/browser/socket a
# worker retries "in place" (no teardown) before giving up and forcing
# a full reconnect anyway, even for an exception not recognized as an
# explicit dead-connection signal. This is a bounded safety net: an
# unrecognized error that keeps recurring is treated as effectively
# equivalent to a dead connection after this many tries, so a worker
# can never retry forever against a session that is, in practice,
# never going to succeed again.
MAX_INPLACE_RETRIES = DEGRADE_AFTER_CONSECUTIVE_FAILURES

# Short pause between in-place retries. The underlying session is
# presumed still alive here, so this is intentionally much shorter
# than the exponential reconnect backoff used once a real reconnect is
# needed (see each worker's own INITIAL_BACKOFF_SECONDS/
# MAX_BACKOFF_SECONDS).
INPLACE_RETRY_PAUSE_SECONDS = 1.0


# Substrings (already-lowercased) that reliably indicate the
# underlying transport (browser page/context, websocket, TCP socket)
# is actually gone and cannot be retried in place -- only these (or a
# matching type name below) force an IMMEDIATE full reconnect
# regardless of consecutive-failure count. Deliberately conservative:
# an unrecognized exception is assumed to be POSSIBLY transient (and
# thus retried in place, bounded by MAX_INPLACE_RETRIES above) rather
# than assumed fatal, so a new/unclassified error type never gets
# stuck endlessly retrying a truly dead session AND never gets treated
# as more serious than it has actually demonstrated itself to be.
_CONNECTION_DEAD_MESSAGE_MARKERS = (
    "target page",
    "browser has been closed",
    "context has been closed",
    "connection closed",
    "socket hang up",
    "websocket",
    "econnreset",
    "econnrefused",
    "connection reset",
    "connection refused",
    "network is unreachable",
    "server disconnected",
    "timed out",
    "timeout",
)

_CONNECTION_DEAD_TYPE_NAME_MARKERS = (
    "targetclosederror",
    "connectionclosederror",
    "connectionerror",
    "connectionreseterror",
    "connectionrefusederror",
    "brokenpipeerror",
    "timeouterror",
)


def is_connection_dead_error(exc: BaseException) -> bool:
    """
    Best-effort classification: True if `exc` looks like the
    underlying transport itself died or is definitely unresponsive (so
    retrying the SAME browser/page/socket cannot usefully succeed and
    a full reconnect is the appropriate response), False if it looks
    like a locally recoverable/transient issue (a single malformed
    message, a one-off parse error) where retrying the existing,
    presumed-still-alive session is worth trying first.

    Deliberately string/type-name based rather than a fixed allowlist
    of exception classes: Playwright/websockets raise plain `Error`/
    generic exception types whose class name alone doesn't distinguish
    "page closed" from "evaluate() threw", so message text is the only
    reliable signal here -- same reasoning as
    credentials/failures.py's classify_zenrows_error, though these
    worker-level exceptions never embed a credential/URL the way a
    ZenRows connection error can, so there is no matching secrecy
    constraint on inspecting the message here.
    """

    name = type(exc).__name__.lower()

    if any(marker in name for marker in _CONNECTION_DEAD_TYPE_NAME_MARKERS):
        return True

    message = str(exc).lower()

    return any(marker in message for marker in _CONNECTION_DEAD_MESSAGE_MARKERS)
