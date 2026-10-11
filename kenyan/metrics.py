"""
One-line Kenyan pipeline cycle summaries.

Never logs payloads, cookies, tokens, or proxy credentials.
"""
from datetime import datetime, timezone

from kenyan.log import logger


def log_cycle(*, bookmaker="", mode="", sport="", **counts):
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    parts = [f"CYCLE ts={stamp}"]
    if bookmaker:
        parts.append(f"bookmaker={bookmaker}")
    if mode:
        parts.append(f"mode={mode}")
    if sport:
        parts.append(f"sport={sport}")
    for key, value in counts.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    logger.info(" ".join(parts))
