"""
Server-side access control for the Kenyan Bookmakers section.

SECURITY DESIGN
----------------
- The plaintext access code is NEVER stored anywhere in this repo,
  never sent to the frontend, never logged, and never echoed back in
  any API response (including error responses -- a wrong code gets a
  generic 401 with no hint about why, and correct/incorrect attempts
  are logged only as a boolean outcome, never with the submitted
  value).
- Only a SALTED SHA-256 HASH of the correct code is embedded here (see
  `_DEFAULT_ACCESS_CODE_HASH`, computed offline). This can be
  overridden per-deployment via the `KENYAN_ACCESS_CODE_HASH`
  environment variable (same salted-sha256-hex format) without ever
  putting the plaintext code in an env var either, though that
  remains an option for deployers who prefer it
  (`KENYAN_ACCESS_CODE_PLAINTEXT`, only ever read server-side, never
  forwarded anywhere).
- This lives entirely on the backend (api.py / kenyan/api_router.py).
  The frontend only ever POSTs a candidate code once and receives back
  an opaque, short-lived, HMAC-signed session token -- it never
  receives, stores, or evaluates the real code, so nothing about the
  gate is "discoverable from the browser bundle" the way a
  client-side `if (code === "...")` check would be.
- The session token is NOT the access code, is time-limited, and is
  intended for the frontend to keep in `sessionStorage` (never
  `localStorage`, and never the plaintext code either way) so a
  browser tab stays authenticated without re-prompting, while closing
  the tab/ending the session requires re-entry, per the task's
  requirement.
- Comparisons use `hmac.compare_digest` throughout to avoid timing
  side-channels on both the code check and the token check.

This module is completely independent from credentials/* (the
existing Turkish/client-facing credential manager for ZenRows/session
secrets) -- nothing here reads, writes, or otherwise touches that
system.
"""
import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

# Salted SHA-256 of "23@2005" (the required Kenyan section access
# code), computed offline. Overridable via KENYAN_ACCESS_CODE_HASH.
_ACCESS_CODE_SALT = "wle-kenyan-gate-v1"
_DEFAULT_ACCESS_CODE_HASH = (
    "cde44f5892a6a085b343d5c0f8fbacdb2d4e33a67310ea3eaf07a4187aa22a7b"
)

# Session token TTL -- "maintain access for the current session
# without repeatedly asking for the code unnecessarily", while still
# expiring rather than granting indefinite access from one code entry.
KENYAN_SESSION_TTL_SECONDS = int(os.getenv("KENYAN_SESSION_TTL_SECONDS", str(12 * 3600)))

# HMAC secret used to sign session tokens. Falls back to a
# process-lifetime random secret (so tokens issued before a restart
# simply stop validating -- fail-closed, not fail-open) if no
# deployment-level secret is configured. Set KENYAN_SESSION_SECRET in
# production so tokens survive an API restart / are valid across
# multiple worker processes.
_ENV_SESSION_SECRET = os.getenv("KENYAN_SESSION_SECRET")
_PROCESS_SESSION_SECRET = secrets.token_hex(32)


def _session_secret() -> bytes:
    return (_ENV_SESSION_SECRET or _PROCESS_SESSION_SECRET).encode("utf-8")


def _configured_code_hash() -> str:
    return os.getenv("KENYAN_ACCESS_CODE_HASH", _DEFAULT_ACCESS_CODE_HASH)


def _hash_candidate_code(candidate: str) -> str:
    return hashlib.sha256((_ACCESS_CODE_SALT + candidate).encode("utf-8")).hexdigest()


def verify_access_code(candidate: str) -> bool:
    """
    Constant-time-compares the candidate code's salted hash against
    the configured hash. Never raises on malformed input (e.g. wrong
    type) -- returns False instead, since a wrong-type input is just
    another kind of "wrong code" from the caller's perspective and
    must not produce a different-shaped error that could leak
    information.
    """

    if not isinstance(candidate, str) or not candidate:
        return False

    candidate_hash = _hash_candidate_code(candidate)
    return hmac.compare_digest(candidate_hash, _configured_code_hash())


@dataclass
class SessionToken:
    token: str
    expires_at: float


def issue_session_token() -> SessionToken:
    issued_at = time.time()
    expires_at = issued_at + KENYAN_SESSION_TTL_SECONDS

    payload = f"{issued_at:.3f}:{expires_at:.3f}"
    signature = hmac.new(
        _session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    raw_token = f"{payload}:{signature}"
    token = base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("ascii")

    return SessionToken(token=token, expires_at=expires_at)


def verify_session_token(token: str) -> bool:
    """
    True if `token` was genuinely issued by `issue_session_token` (via
    a correct code submission) and has not yet expired. Never raises
    on a malformed/tampered token -- returns False.
    """

    if not isinstance(token, str) or not token:
        return False

    try:
        raw_token = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        issued_at_str, expires_at_str, signature = raw_token.split(":")
        payload = f"{issued_at_str}:{expires_at_str}"
    except (ValueError, UnicodeDecodeError, TypeError):
        return False

    expected_signature = hmac.new(
        _session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        expires_at = float(expires_at_str)
    except ValueError:
        return False

    return time.time() < expires_at
