"""Structured Kenyan diagnostics. Never logs credentials, cookies, or tokens."""

import logging
import os

logger = logging.getLogger("kenyan")

_MAX_MATCHER_LOGS = int(os.getenv("KENYAN_MAX_MATCHER_LOGS", "20"))
_matcher_logs = 0


def reset_matcher_log_budget():
    global _matcher_logs
    _matcher_logs = 0


def log_parse(
    bookmaker,
    *,
    event="",
    status="parsed",
    market="",
    selection="",
    event_id="",
    cluster_id="",
    market_id="",
    reason="",
):
    parts = [f"{bookmaker.upper()}:", f"event={event}", f"status={status}"]
    if market:
        parts.append(f"market={market}")
    if selection:
        parts.append(f"selection={selection}")
    if event_id:
        parts.append(f"event_id={event_id}")
    if cluster_id:
        parts.append(f"cluster_id={cluster_id}")
    if market_id:
        parts.append(f"market_id={market_id}")
    if reason:
        parts.append(f"reason={reason}")
    logger.info(" ".join(parts))


def log_matcher(candidate_a, candidate_b, decision, reason):
    global _matcher_logs
    if _matcher_logs >= _MAX_MATCHER_LOGS:
        return
    _matcher_logs += 1
    logger.info(
        "MATCHER: candidate_event=%s candidate_event=%s decision=%s reason=%s",
        candidate_a,
        candidate_b,
        decision,
        reason,
    )


def log_arb(*, event="", market="", line=None, decision="", reason="", **selections):
    parts = [f"ARB: event={event}", f"market={market}"]
    if line is not None:
        parts.append(f"line={line}")
    for key, value in selections.items():
        parts.append(f"{key}={value}")
    parts.append(f"decision={decision}")
    if reason:
        parts.append(f"reason={reason}")
    logger.info(" ".join(parts))


def event_label(match) -> str:
    home = getattr(match, "home_team", "") or ""
    away = getattr(match, "away_team", "") or ""
    book = getattr(match, "bookmaker", "") or ""
    return f"{book}:{home} vs {away}"
