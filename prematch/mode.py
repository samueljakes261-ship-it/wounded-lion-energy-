"""Reversible engine mode for the prematch forensic session.

ENGINE_MODE=prematch  -> do not start live BetKanyon/Orbit/OnWin
ENGINE_MODE=live      -> default, both pipelines (unchanged)

Never deletes live worker code. Flip the env var and restart.
"""

import os


def is_prematch_only() -> bool:
    value = os.getenv("ENGINE_MODE", "live").strip().lower()
    return value in {"prematch", "prematch-only", "prematch_only"}


def engine_mode_label() -> str:
    return "prematch" if is_prematch_only() else "live"
