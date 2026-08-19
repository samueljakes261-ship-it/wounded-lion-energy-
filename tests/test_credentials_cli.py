"""
Tests for credentials/cli.py management commands (init/add/list/
enable/disable/remove/health/reset-state), exercised via main()
against an isolated store. No real credentials, no network.
"""
import pytest

import credentials.cli as cli
from credentials.crypto import generate_master_key
from credentials.store import CredentialStore


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_CREDENTIAL_KEY", generate_master_key())

    # store.py's DEFAULT_STORE_PATH/DEFAULT_STATE_PATH are read from
    # the environment once at import time, so CredentialStore()
    # (constructed with no explicit path, as cli.py does) needs these
    # module-level constants patched directly for test isolation.
    monkeypatch.setattr(
        "credentials.store.DEFAULT_STORE_PATH", str(tmp_path / "credentials.json")
    )
    monkeypatch.setattr(
        "credentials.store.DEFAULT_STATE_PATH",
        str(tmp_path / "runtime" / "credentials_state.json"),
    )

    # health/reset-state go through the process-wide manager singleton
    # (credentials.manager._managers) -- reset it so a manager cached
    # by an earlier test (pointing at a different store path) can
    # never leak into this test.
    monkeypatch.setattr("credentials.manager._managers", {})

    yield tmp_path


def test_init_creates_store(tmp_path, capsys):
    assert cli.main(["init"]) == 0

    captured = capsys.readouterr()
    assert "Credential store ready" in captured.out

    store = CredentialStore()
    assert store.load_credentials() == []


def test_add_and_list_credential(capsys):
    cli.main(["init"])
    capsys.readouterr()

    rc = cli.main([
        "add", "--provider", "zenrows",
        "--secret", "wss://browser.zenrows.com?apikey=abc123",
        "--id", "zenrows-01",
        "--label", "primary",
    ])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Added credential 'zenrows-01'" in out
    assert "abc123" not in out

    rc = cli.main(["list"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "zenrows-01" in out
    assert "abc123" not in out


def test_add_duplicate_id_fails(capsys):
    cli.main(["init"])
    capsys.readouterr()

    cli.main([
        "add", "--provider", "zenrows", "--secret", "s1", "--id", "zenrows-01",
    ])
    capsys.readouterr()

    rc = cli.main([
        "add", "--provider", "zenrows", "--secret", "s2", "--id", "zenrows-01",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "already exists" in err


def test_disable_and_enable_credential(capsys):
    cli.main(["init"])
    cli.main([
        "add", "--provider", "zenrows", "--secret", "s1", "--id", "zenrows-01",
    ])
    capsys.readouterr()

    assert cli.main(["disable", "zenrows-01"]) == 0
    out = capsys.readouterr().out
    assert "disabled" in out

    store = CredentialStore()
    credentials = store.load_credentials()
    assert credentials[0].enabled is False

    assert cli.main(["enable", "zenrows-01"]) == 0
    credentials = CredentialStore().load_credentials()
    assert credentials[0].enabled is True


def test_disable_unknown_credential_fails(capsys):
    cli.main(["init"])
    capsys.readouterr()

    rc = cli.main(["disable", "does-not-exist"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_remove_credential(capsys):
    cli.main(["init"])
    cli.main([
        "add", "--provider", "zenrows", "--secret", "s1", "--id", "zenrows-01",
    ])
    capsys.readouterr()

    assert cli.main(["remove", "zenrows-01"]) == 0

    store = CredentialStore()
    assert store.load_credentials() == []


def test_health_reports_configured_status(capsys):
    cli.main(["init"])
    cli.main([
        "add", "--provider", "zenrows", "--secret", "s1", "--id", "zenrows-01",
    ])
    capsys.readouterr()

    rc = cli.main(["health", "--provider", "zenrows"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "configured: True" in out
    assert "decryptable: True" in out
    assert "s1" not in out


def test_reset_state_clears_health_but_keeps_credentials(capsys):
    cli.main(["init"])
    cli.main([
        "add", "--provider", "zenrows", "--secret", "s1", "--id", "zenrows-01",
    ])
    capsys.readouterr()

    assert cli.main(["reset-state", "--provider", "zenrows"]) == 0

    store = CredentialStore()
    assert len(store.load_credentials()) == 1
