"""BetKanyon prematch HTTP Cloudflare detection and Chrome CDP failover."""

from __future__ import annotations

from parsers.betkanyon_prematch.cdp import find_sport_page
from parsers.betkanyon_prematch.fetcher import (
    PREMATCH_PAGE,
    SPORT_HOST,
    SPORT_PAGE,
    BetkanyonPrematchFetcher,
    BetkanyonPrematchHttpFetcher,
    build_prematch_url,
    looks_like_cloudflare,
)


CF_HTML = (
    "<!DOCTYPE html><html lang=\"en-US\"><head><title>Just a moment...</title>"
    "<meta name=\"robots\" content=\"noindex,nofollow\">"
    "cdn-cgi/challenge-platform</head></html>"
)


def test_sport_page_is_same_origin_request_helper():
    assert SPORT_PAGE.startswith(SPORT_HOST)
    assert "Tools/RequestHelper" in SPORT_PAGE
    assert "betkanyon1617.com" not in SPORT_PAGE
    assert PREMATCH_PAGE == SPORT_PAGE
    url = build_prematch_url("4520")
    assert url.startswith(SPORT_HOST)
    assert "betkanyon1617.com" not in url


def test_looks_like_cloudflare_challenge_html():
    assert looks_like_cloudflare(403, CF_HTML, "text/html; charset=UTF-8") is True
    assert looks_like_cloudflare(200, '{"payload":"%s"}' % ("A" * 40), "application/json") is False
    assert looks_like_cloudflare(404, "<html>404</html>", "text/html") is False


def test_http_cloudflare_stops_sweep_and_flags_block():
    fetcher = BetkanyonPrematchHttpFetcher()
    calls = []

    class FakeResponse:
        status_code = 403
        text = CF_HTML
        headers = {"Content-Type": "text/html; charset=UTF-8"}

        def json(self):
            raise ValueError("not json")

    def fake_get(url, timeout=None):
        calls.append(url)
        return FakeResponse()

    fetcher.session.get = fake_get
    payloads = fetcher.fetch_all(["1", "2", "3", "4", "5", "6", "7", "8", "9"])
    assert payloads == {}
    assert fetcher.cloudflare_blocked is True
    # First chunk only (8), not the leftover tournament.
    assert len(calls) <= 16
    assert len(calls) < 9 * 2


def test_http_404_still_does_not_abort_batch():
    class FakeResponse:
        def __init__(self, status, payload=None, html=False):
            self.status_code = status
            self._payload = payload
            self.text = "<html>404</html>" if html else '{"payload":"%s"}' % (payload or "")
            self.headers = {
                "Content-Type": "text/html" if html else "application/json"
            }

        def json(self):
            if self.status_code >= 400:
                raise ValueError("not json")
            return {"payload": self._payload}

    fetcher = BetkanyonPrematchHttpFetcher()

    def fake_get(url, timeout=None):
        if "tournamentId=1" in url:
            return FakeResponse(404, html=True)
        return FakeResponse(200, payload="B" * 40)

    fetcher.session.get = fake_get
    payloads = fetcher.fetch_all(["1", "4520"])
    assert "1" not in payloads
    assert payloads["4520"] == "B" * 40
    assert fetcher.cloudflare_blocked is False


def test_auto_failover_uses_cdp_when_http_is_cloudflare(monkeypatch):
    from parsers.betkanyon_prematch import fetcher as fetcher_mod

    class FakeHttp(BetkanyonPrematchHttpFetcher):
        def fetch_all(self, tournament_ids):
            self.cloudflare_blocked = True
            return {}

        def close(self):
            self.initialized = False

    class FakeCdp:
        def __init__(self):
            self.ids = None

        def fetch_all(self, tournament_ids):
            self.ids = list(tournament_ids)
            return {"4520": "C" * 40}

        def close(self):
            pass

    fake_cdp = FakeCdp()
    monkeypatch.setenv("BETKANYON_PREMATCH_FETCH", "auto")
    monkeypatch.setattr(fetcher_mod, "BetkanyonPrematchHttpFetcher", FakeHttp)

    def fake_cdp_ctor(*_args, **_kwargs):
        return fake_cdp

    monkeypatch.setattr(
        "parsers.betkanyon_prematch.fetcher_cdp.BetkanyonPrematchCdpFetcher",
        fake_cdp_ctor,
        raising=False,
    )
    # Import happens inside fetch_all; patch the module attribute once loaded.
    import parsers.betkanyon_prematch.fetcher_cdp as cdp_fetch

    monkeypatch.setattr(cdp_fetch, "BetkanyonPrematchCdpFetcher", fake_cdp_ctor)

    wrapped = BetkanyonPrematchFetcher()
    payloads = wrapped.fetch_all(["4520", "4486"])
    assert payloads == {"4520": "C" * 40}
    assert fake_cdp.ids == ["4520", "4486"]


def test_find_sport_page_prefers_bksp3():
    rows = [
        {"url": "https://kolay90.com/", "title": "Kolay90", "page": object()},
        {
            "url": "https://sport.bksp3.com/0587cccf-5a4f-430c-a2b4-b1b98af7e3ad/Tools/RequestHelper",
            "title": "",
            "page": object(),
        },
    ]
    found = find_sport_page(rows)
    assert found is not None
    assert "sport.bksp3.com" in found["url"]


def test_cdp_attach_does_not_launch_chrome(monkeypatch):
    from parsers.betkanyon_prematch import cdp

    launches = []

    def fake_connect(url=None):
        launches.append(url)
        raise RuntimeError("no chrome")

    monkeypatch.setattr(cdp, "connect_existing_chrome", fake_connect)
    try:
        cdp.attach_sport_page("http://127.0.0.1:9222")
    except RuntimeError as exc:
        assert "no chrome" in str(exc)
    assert launches == ["http://127.0.0.1:9222"]


def test_http_only_mode_does_not_failover(monkeypatch):
    monkeypatch.setenv("BETKANYON_PREMATCH_FETCH", "http")
    wrapped = BetkanyonPrematchFetcher()
    wrapped._impl.cloudflare_blocked = True
    assert wrapped._should_failover_to_cdp({}) is False
