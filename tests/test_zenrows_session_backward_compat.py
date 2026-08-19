"""
Regression tests: the existing ZenRowsSession classes used by OnWin
(utils/zenrows_persistent.py) and BetKanyon/legacy code
(browser/sessions/zenrows.py) must keep their existing public
interface (connect(), page()/get_page(), close(), and connect()
returning the browser) after being refactored to obtain credentials
via CredentialManager -- callers should not need any changes.

No real Playwright/browser/network/credentials are used.
"""
import sys
import types

import pytest


class FakeContext:
    def new_page(self):
        return FakePage()


class FakePage:
    def is_closed(self):
        return False

    def on(self, *args, **kwargs):
        pass

    def close(self):
        pass


class FakeBrowser:
    def __init__(self):
        self.contexts = []

    def new_context(self):
        return FakeContext()

    def close(self):
        pass


class FakePlaywrightInstance:
    def __init__(self):
        self.chromium = types.SimpleNamespace()
        self.stopped = False

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_sync_playwright(monkeypatch):
    """
    Patches sync_playwright() (as imported inside the modules under
    test) to return a fake instance whose .start() is a no-op, and
    patches connect_with_failover() to return a fake browser without
    touching any real credential/network machinery.
    """
    instance = FakePlaywrightInstance()

    def fake_start():
        return instance

    def fake_sync_playwright_factory():
        return types.SimpleNamespace(start=fake_start)

    def fake_connect_with_failover(playwright):
        assert playwright is instance
        return FakeBrowser(), "zenrows-01"

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", fake_sync_playwright_factory,
    )
    monkeypatch.setattr(
        "credentials.zenrows_provider.connect_with_failover",
        fake_connect_with_failover,
    )

    return instance


def _reload(module_name):
    if module_name in sys.modules:
        del sys.modules[module_name]
    __import__(module_name)
    return sys.modules[module_name]


def test_utils_zenrows_persistent_session_interface(fake_sync_playwright):
    module = _reload("utils.zenrows_persistent")
    session = module.ZenRowsSession()

    session.connect()

    assert session.browser is not None
    assert session.credential_id == "zenrows-01"

    page = session.page()
    assert page is not None

    # Calling page() again must reuse the same page, not recreate it.
    assert session.page() is page

    # Backwards-compatible alias.
    assert session.get_page() is page

    session.close()
    assert session.browser is None
    assert session.credential_id is None


def test_browser_sessions_zenrows_session_interface(fake_sync_playwright):
    module = _reload("browser.sessions.zenrows")
    session = module.ZenRowsSession()

    browser = session.connect()

    assert browser is not None
    assert session.credential_id == "zenrows-01"

    session.close()
    assert session.browser is None
    assert session.credential_id is None


def test_browser_sessions_zenrows_stops_playwright_on_connect_failure(
    fake_sync_playwright, monkeypatch,
):
    """
    A failed connect_with_failover (e.g. all credentials cooling down)
    must stop the Playwright Sync dispatcher on this thread. Otherwise
    the next BetKanyon retry hits 'Sync API inside the asyncio loop'.
    """
    from credentials.errors import AllCredentialsUnavailableError

    def failing_connect(_playwright):
        raise AllCredentialsUnavailableError("unavailable")

    monkeypatch.setattr(
        "credentials.zenrows_provider.connect_with_failover",
        failing_connect,
    )

    module = _reload("browser.sessions.zenrows")
    session = module.ZenRowsSession()

    with pytest.raises(AllCredentialsUnavailableError):
        session.connect()

    assert fake_sync_playwright.stopped is True
    assert session.playwright is None
    assert session.browser is None
    assert session.credential_id is None


def test_connect_is_idempotent_when_already_connected(fake_sync_playwright):
    module = _reload("utils.zenrows_persistent")
    session = module.ZenRowsSession()

    session.connect()
    first_browser = session.browser

    # A second connect() call must be a no-op (no second
    # connect_with_failover call) while already connected.
    session.connect()

    assert session.browser is first_browser
