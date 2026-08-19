"""
Lightweight, request-free health checks for credential-backed
providers.

These check configuration / decryptability / recorded state; they
deliberately do NOT make a live provider request unless probe=True is
explicitly passed, since ZenRows browser sessions are a billed
resource and health checks should not spend it.
"""
import socket

from credentials.errors import CredentialError
from credentials.manager import get_manager

_REACHABILITY_TARGETS = {
    "zenrows": ("browser.zenrows.com", 443),
}


def check_provider(provider: str, probe: bool = False) -> dict:
    """
    Returns a dict describing:
      - configured: whether any credentials exist for this provider
      - decryptable: whether the active credential could be decrypted
      - active_credential_id / active_credential_status
      - available_count / total_count
      - reachable: None unless probe=True (cheap TCP-only check, no
        billed request)
      - error: a short, non-sensitive description if something failed
    """
    manager = get_manager(provider)

    result = {
        "provider": provider,
        "configured": False,
        "decryptable": False,
        "active_credential_id": None,
        "active_credential_status": None,
        "available_count": 0,
        "total_count": 0,
        "reachable": None,
        "error": None,
    }

    try:
        descriptions = manager.describe_all()
    except CredentialError as exc:
        result["error"] = str(exc)
        return result

    result["configured"] = len(descriptions) > 0
    result["total_count"] = len(descriptions)
    result["available_count"] = sum(1 for d in descriptions if d["available"])

    if not descriptions:
        return result

    secret = None

    try:
        credential_id, secret = manager.get_active_secret()
        result["decryptable"] = True
        result["active_credential_id"] = credential_id

        active = next(
            (d for d in descriptions if d["credential_id"] == credential_id),
            None,
        )
        if active:
            result["active_credential_status"] = active["status"]

    except CredentialError as exc:
        result["error"] = str(exc)

    if probe and secret:
        result["reachable"] = _probe_reachable(provider)

    return result


def _probe_reachable(provider: str, timeout: float = 5.0) -> bool:
    """
    Cheap TCP-level reachability probe (no billed request): opens a
    TCP connection to the provider's host without completing any
    HTTP/WebSocket handshake or spending quota.
    """
    target = _REACHABILITY_TARGETS.get(provider)

    if target is None:
        return False

    host, port = target

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
