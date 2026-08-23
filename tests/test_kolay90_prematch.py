"""Isolated Kolay90 prematch parser/feed tests. No network."""

from __future__ import annotations

from datetime import datetime, timezone

from parsers.kolay90_prematch.feed import Kolay90PrematchFeed
from parsers.kolay90_prematch.parser import (
    count_oranlar,
    extract_1x2,
    is_unauthenticated,
    parse_event,
    parse_payload,
    start_time_from_event,
    unwrap_events,
    validate_against_raw,
)

BOCHOLT = {
    "_id": "evt-bocholt",
    "ev_sahibi": "Bocholt",
    "deplasman": "Rodinghausen",
    "lig_id": 245759,
    "code": 598,
    "mbs": 1,
    "zaman": {"sec": 1787400000},
    "oranlar": {"1": "2.38", "0": "3.45", "2": "2.50"},
    "type": 1,
    "zs": "Cmt 15:00",
}


def test_one_x_two_mapping_not_first_numeric_keys():
    parsed = parse_event(BOCHOLT)
    assert parsed is not None
    assert parsed.home_odds == 2.38
    assert parsed.draw_odds == 3.45
    assert parsed.away_odds == 2.50
    assert parsed.raw_home == "2.38"
    assert parsed.raw_draw == "3.45"
    assert parsed.raw_away == "2.50"
    assert parsed.match.feed_type == "prematch"
    assert parsed.match.bookmaker == "kolay90"
    assert parsed.event_id == "evt-bocholt"
    assert parsed.bookmaker_code == "598"
    assert parsed.match.tournament_id == "245759"
    assert validate_against_raw(BOCHOLT, parsed) == []


def test_missing_odds_only_draw_key_rejected():
    item = {**BOCHOLT, "oranlar": {"0": "8.75"}}
    assert extract_1x2(item) is None
    assert parse_event(item) is None


def test_malformed_event_ignored():
    assert parse_event("not-an-object") is None
    assert parse_payload(["x", None, 3]) == []


def test_missing_oranlar():
    item = {k: v for k, v in BOCHOLT.items() if k != "oranlar"}
    assert parse_event(item) is None


def test_missing_event_id():
    item = {**BOCHOLT, "_id": ""}
    assert parse_event(item) is None
    item.pop("_id")
    assert parse_event(item) is None


def test_invalid_decimal_odds():
    item = {**BOCHOLT, "oranlar": {"1": "abc", "0": "3.45", "2": "2.50"}}
    assert parse_event(item) is None


def test_unauthenticated_response():
    payload = {"hata": True, "mesaj": "Lütfen Tekrar Giriş Yapınız.. Yada Sisteme Bağlı Olduğunuzu Kontrol Ediniz."}
    assert is_unauthenticated(payload) is True
    assert unwrap_events(payload) == []
    assert parse_payload(payload) == []


def test_valid_authenticated_list():
    parsed = parse_payload([BOCHOLT])
    assert len(parsed) == 1
    assert parsed[0].home_team == "Bocholt"


def test_timestamp_conversion():
    start = start_time_from_event(BOCHOLT)
    assert start == datetime.fromtimestamp(1787400000, tz=timezone.utc)
    parsed = parse_event(BOCHOLT)
    assert parsed is not None
    assert parsed.match.start_time == start


def test_duplicate_events_last_wins():
    first = {**BOCHOLT, "oranlar": {"1": "2.00", "0": "3.00", "2": "4.00"}}
    second = {**BOCHOLT, "oranlar": {"1": "2.10", "0": "3.10", "2": "4.10"}}
    parsed = parse_payload([first, second])
    assert len(parsed) == 1
    assert parsed[0].home_odds == 2.10


def test_non_football_rejected_when_sport_present():
    item = {**BOCHOLT, "spor": "Basketbol", "_id": "hoops"}
    assert parse_event(item) is None


def test_feed_keeps_last_good_on_auth_expiry():
    feed = Kolay90PrematchFeed()
    good = feed._apply_fetch(
        {
            "status": 200,
            "content_type": "application/json",
            "bytes": 100,
            "json": True,
            "payload": [BOCHOLT],
            "looks_html": False,
            "unauthenticated": False,
            "error": None,
            "cloudflare": False,
        }
    )
    assert good["ok"] is True
    assert len(feed.last_good()) == 1
    expired = feed._apply_fetch(
        {
            "status": 200,
            "content_type": "application/json",
            "bytes": 80,
            "json": True,
            "payload": {"hata": True, "mesaj": "Lütfen Tekrar Giriş Yapınız.."},
            "looks_html": False,
            "unauthenticated": True,
            "error": None,
            "cloudflare": False,
        }
    )
    assert expired["ok"] is False
    assert expired["kept_last_good"] is True
    assert expired["failure"] == "login_expired"
    assert len(expired["matches"]) == 1
    assert expired["matches"][0].home_team == "Bocholt"


def test_feed_keeps_last_good_on_cloudflare_html():
    feed = Kolay90PrematchFeed()
    feed._apply_fetch(
        {
            "status": 200,
            "content_type": "application/json",
            "bytes": 100,
            "json": True,
            "payload": [BOCHOLT],
            "looks_html": False,
            "unauthenticated": False,
            "error": None,
            "cloudflare": False,
        }
    )
    blocked = feed._apply_fetch(
        {
            "status": 403,
            "content_type": "text/html",
            "bytes": 5000,
            "json": False,
            "payload": None,
            "looks_html": True,
            "unauthenticated": False,
            "error": None,
            "cloudflare": True,
        }
    )
    assert blocked["kept_last_good"] is True
    assert blocked["failure"] == "cloudflare_html"
    assert len(feed.last_good()) == 1


def test_kolay90_browser_uses_env_ws_not_credential_failover(monkeypatch):
    from parsers.kolay90_prematch.browser import Kolay90PrematchBrowser

    failover_calls = []

    def fake_failover(*_args, **_kwargs):
        failover_calls.append(True)
        raise AssertionError("Kolay90 must not use connect_with_failover")

    class FakeBrowser:
        contexts = []

        def new_context(self):
            return object()

        def close(self):
            pass

    class FakePlaywright:
        class chromium:
            @staticmethod
            def connect_over_cdp(_url):
                return FakeBrowser()

        def start(self):
            return self

        def stop(self):
            pass

    monkeypatch.setattr(
        "parsers.kolay90_prematch.browser.sync_playwright",
        lambda: FakePlaywright(),
    )
    monkeypatch.setattr(
        "credentials.zenrows_provider.connect_with_failover",
        fake_failover,
    )
    monkeypatch.setenv("ZENROWS_BROWSER_WS", "wss://browser.zenrows.com?apikey=testkey1234")
    browser = Kolay90PrematchBrowser()
    browser.connect()
    assert failover_calls == []
    assert browser.credential_id == "kolay90-env-zenrows"
    assert browser.browser is not None
    browser.close()


def test_count_oranlar_partial_and_complete():
    events = [
        BOCHOLT,
        {**BOCHOLT, "_id": "draw-only", "oranlar": {"0": "8.75"}},
        {**BOCHOLT, "_id": "none", "oranlar": {}},
    ]
    counts = count_oranlar(events)
    assert counts["with_any_1x2"] == 2
    assert counts["with_all_1x2"] == 1


def test_repeated_apply_fetch_stays_authenticated():
    feed = Kolay90PrematchFeed()
    payload = {
        "status": 200,
        "content_type": "application/json",
        "bytes": 100,
        "json": True,
        "payload": [BOCHOLT],
        "looks_html": False,
        "unauthenticated": False,
        "error": None,
        "cloudflare": False,
    }
    rows = [feed._apply_fetch(payload) for _ in range(3)]
    assert all(row["authenticated"] for row in rows)
    assert all(row["one_x_two"] == 1 for row in rows)


def test_run_logs_mask_password(monkeypatch, capsys):
    from parsers.kolay90_prematch.run import log, mask_ws_source

    monkeypatch.setenv("KOLAY90_PASSWORD", "secret-pass-xyz")
    monkeypatch.setenv("ZENROWS_BROWSER_WS", "wss://browser.zenrows.com?apikey=abcd1234efgh")
    log(mask_ws_source())
    out = capsys.readouterr().out
    assert "secret-pass-xyz" not in out
    assert "abcd1234efgh" not in out
    assert "********efgh" in out
    assert "ZENROWS_BROWSER_WS" in out


def test_cloudflare_title_includes_localized_moment():
    class FakePage:
        def title(self):
            return "Un momento?"

        @property
        def url(self):
            return "https://kolay90.com/"

    from parsers.kolay90_prematch.login import _looks_like_challenge

    assert _looks_like_challenge(FakePage()) is True


def test_agreement_page_and_accept_button():
    from parsers.kolay90_prematch.agreement import (
        classify_agreement_buttons,
        is_agreement_page,
    )

    assert is_agreement_page("https://kolay90.com/sozlesme.html", "User Agreement", "") is True
    assert is_agreement_page(
        "https://kolay90.com/",
        "Sözleşme",
        "bu sitedeki tüm içerikler bilgilendirme ve eğlence amaçlı olduğunu kabul ediyormusunuz",
    ) is True
    assert is_agreement_page("https://kolay90.com/", "Just a moment...", "Cloudflare Privacy") is False
    classified = classify_agreement_buttons(
        [
            {"index": 0, "text": "Reddet"},
            {"index": 1, "text": "Kabul Et"},
        ]
    )
    assert classified["chosen"]["index"] == 1
    assert classified["chosen"]["role"] == "accept"
    ambiguous = classify_agreement_buttons(
        [{"index": 0, "text": "Cloudflare"}, {"index": 1, "text": "Privacy"}]
    )
    assert ambiguous["chosen"] is None


def test_accept_agreement_page_does_not_click_reject():
    from parsers.kolay90_prematch.agreement import accept_agreement_page

    class FakePage:
        def evaluate(self, _js):
            return [{"index": 0, "text": "Reddet"}]

        def get_by_text(self, *_args, **_kwargs):
            raise AssertionError("must not click reject")

    result = accept_agreement_page(FakePage())
    assert result["found"] is False
    assert result["clicked"] is False
    assert result["reject_candidates"] == ["Reddet"]


def test_session_probe_log_ascii_safe(capsys):
    from parsers.kolay90_prematch.session_probe import log

    log("giriş yap")
    out = capsys.readouterr().out
    assert "KOLAY90 SESSION PROBE" in out
    assert "\u015f" not in out


def test_session_probe_redacts_query_and_detects_challenge():
    from parsers.kolay90_prematch.session_probe import (
        app_reached,
        marker_flags,
        safe_url,
    )

    assert safe_url("https://kolay90.com/?__cf_chl_rt_tk=secret") == "https://kolay90.com/"
    flags = marker_flags("Just a moment... Cloudflare Privacy")
    assert flags["just a moment"] is True
    assert flags["cloudflare"] is True
    blocked = {
        "cloudflare": True,
        "login_form": False,
        "application": False,
        "markers": flags,
    }
    assert app_reached(blocked) is False
    ready = {
        "cloudflare": False,
        "login_form": True,
        "application": True,
        "markers": marker_flags("Giriş Yap"),
    }
    assert app_reached(ready) is True


def test_diagnose_redacts_apikey_and_cf_token():
    from parsers.kolay90_prematch.diagnose_zenrows import redact_error

    text = redact_error(
        "connect failed wss://browser.zenrows.com/?apikey=supersecretkey "
        "https://kolay90.com/?__cf_chl_rt_tk=tokensecret"
    )
    assert "supersecretkey" not in text
    assert "tokensecret" not in text
    assert "wss://***" in text

