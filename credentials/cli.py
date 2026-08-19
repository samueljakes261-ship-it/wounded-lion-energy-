"""
Credential store management CLI.

Usage:
    python -m credentials.cli init
    python -m credentials.cli add --provider zenrows --secret "wss://browser.zenrows.com?apikey=..." --label "primary"
    python -m credentials.cli list [--provider zenrows]
    python -m credentials.cli enable <credential_id>
    python -m credentials.cli disable <credential_id>
    python -m credentials.cli remove <credential_id>
    python -m credentials.cli health --provider zenrows [--probe]
    python -m credentials.cli reset-state [--provider zenrows]

This tool never prints a decrypted secret or the master key.
"""
import argparse
import sys
import uuid

import credentials  # noqa: F401 -- ensures .env is loaded
from credentials.crypto import MASTER_KEY_ENV_VAR, generate_master_key
from credentials.health import check_provider
from credentials.manager import get_manager
from credentials.models import StoredCredential
from credentials.store import CredentialStore

import os


def cmd_init(args):
    store = CredentialStore()

    if not os.getenv(MASTER_KEY_ENV_VAR):
        new_key = generate_master_key()
        print("No MASTER_CREDENTIAL_KEY found in the environment.\n")
        print("Generated a new one. Add this line to your .env file:\n")
        print(f"{MASTER_KEY_ENV_VAR}={new_key}\n")
        print(
            "Keep this secret -- anyone with this key can decrypt every "
            "credential in the store. Never commit it to Git."
        )
    else:
        print(f"{MASTER_KEY_ENV_VAR} is already set in the environment.")

    store.ensure_store_exists()
    print(f"\nCredential store ready at: {store.store_path}")
    return 0


def cmd_add(args):
    if not os.getenv(MASTER_KEY_ENV_VAR):
        print(f"ERROR: {MASTER_KEY_ENV_VAR} is not set. Run 'init' first.", file=sys.stderr)
        return 1

    store = CredentialStore()
    store.ensure_store_exists()
    credentials_list = store.load_credentials()

    credential_id = args.id or f"{args.provider}-{uuid.uuid4().hex[:8]}"

    if any(c.credential_id == credential_id for c in credentials_list):
        print(f"ERROR: credential_id '{credential_id}' already exists.", file=sys.stderr)
        return 1

    encrypted = CredentialStore.encrypt(args.secret)

    credentials_list.append(
        StoredCredential(
            credential_id=credential_id,
            provider=args.provider,
            encrypted_secret=encrypted,
            enabled=True,
            label=args.label or "",
        )
    )

    store.save_credentials(credentials_list)

    print(f"Added credential '{credential_id}' for provider '{args.provider}'.")
    return 0


def cmd_list(args):
    store = CredentialStore()
    store.ensure_store_exists()
    credentials_list = store.load_credentials()

    if args.provider:
        credentials_list = [c for c in credentials_list if c.provider == args.provider]

    if not credentials_list:
        print("No credentials configured.")
        return 0

    state = store.load_state()

    header = f"{'CREDENTIAL_ID':<26}{'PROVIDER':<12}{'ENABLED':<9}{'STATUS':<14}{'LABEL'}"
    print(header)
    print("-" * len(header))

    for c in credentials_list:
        s = state.get(c.credential_id)
        status = s.status if s else "unknown"
        print(f"{c.credential_id:<26}{c.provider:<12}{str(c.enabled):<9}{status:<14}{c.label}")

    return 0


def _set_enabled(credential_id, enabled):
    store = CredentialStore()
    credentials_list = store.load_credentials()

    found = False
    for c in credentials_list:
        if c.credential_id == credential_id:
            c.enabled = enabled
            found = True

    if not found:
        print(f"ERROR: credential_id '{credential_id}' not found.", file=sys.stderr)
        return 1

    store.save_credentials(credentials_list)
    print(f"Credential '{credential_id}' {'enabled' if enabled else 'disabled'}.")
    return 0


def cmd_enable(args):
    return _set_enabled(args.credential_id, True)


def cmd_disable(args):
    return _set_enabled(args.credential_id, False)


def cmd_remove(args):
    store = CredentialStore()
    credentials_list = store.load_credentials()

    remaining = [c for c in credentials_list if c.credential_id != args.credential_id]

    if len(remaining) == len(credentials_list):
        print(f"ERROR: credential_id '{args.credential_id}' not found.", file=sys.stderr)
        return 1

    store.save_credentials(remaining)

    state = store.load_state()
    state.pop(args.credential_id, None)
    store.save_state(state)

    print(f"Removed credential '{args.credential_id}'.")
    return 0


def cmd_health(args):
    result = check_provider(args.provider, probe=args.probe)

    for key, value in result.items():
        print(f"{key}: {value}")

    return 0 if not result.get("error") else 1


def cmd_reset_state(args):
    if args.provider:
        manager = get_manager(args.provider)
        manager.reset_runtime_state()
        print(f"Runtime state reset for provider '{args.provider}'.")
    else:
        store = CredentialStore()
        store.reset_state()
        print("Runtime state reset for all providers.")

    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m credentials.cli",
        description="Manage the encrypted credential store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create the credential store / master key.")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="Add a new credential.")
    p_add.add_argument("--provider", required=True)
    p_add.add_argument("--secret", required=True, help="Plaintext secret (never logged).")
    p_add.add_argument("--id", dest="id", default=None)
    p_add.add_argument("--label", default=None)
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List configured credentials (no secrets shown).")
    p_list.add_argument("--provider", default=None)
    p_list.set_defaults(func=cmd_list)

    p_enable = sub.add_parser("enable", help="Enable a credential.")
    p_enable.add_argument("credential_id")
    p_enable.set_defaults(func=cmd_enable)

    p_disable = sub.add_parser("disable", help="Disable a credential.")
    p_disable.add_argument("credential_id")
    p_disable.set_defaults(func=cmd_disable)

    p_remove = sub.add_parser("remove", help="Remove a credential permanently.")
    p_remove.add_argument("credential_id")
    p_remove.set_defaults(func=cmd_remove)

    p_health = sub.add_parser("health", help="Run health checks for a provider.")
    p_health.add_argument("--provider", required=True)
    p_health.add_argument(
        "--probe", action="store_true",
        help="Also do a request-free TCP reachability check.",
    )
    p_health.set_defaults(func=cmd_health)

    p_reset = sub.add_parser(
        "reset-state", help="Clear runtime health state (never the secrets).",
    )
    p_reset.add_argument("--provider", default=None)
    p_reset.set_defaults(func=cmd_reset_state)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
