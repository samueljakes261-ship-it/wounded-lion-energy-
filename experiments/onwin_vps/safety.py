"""Safety checks for the dedicated Onwin VPS Chrome.

Kolay90 already owns port 9222 and its own profile. This module refuses
to start or attach Onwin on that port or profile.
"""

from __future__ import annotations

import argparse
from pathlib import Path

KOLAY_PORT = 9222


class OnwinVpsGuardError(RuntimeError):
    pass


def validate_target(port: int, profile: Path) -> None:
    if int(port) == KOLAY_PORT:
        raise OnwinVpsGuardError(
            "refusing port 9222; that debugging port belongs to the Kolay90 Chrome"
        )
    text = str(profile).replace("\\", "/").lower()
    if "kolay90" in text or "kolay91" in text:
        raise OnwinVpsGuardError(
            "refusing a Kolay90 profile; Onwin must use experiments/onwin_vps/chrome_profile"
        )
    if int(port) < 1 or int(port) > 65535:
        raise OnwinVpsGuardError(f"refusing port {port}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an Onwin VPS Chrome target")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validate_target(args.port, args.profile)
    except OnwinVpsGuardError as exc:
        print(f"[ONWIN VPS] {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
