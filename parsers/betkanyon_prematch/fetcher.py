"""Persistent BetKanyon prematch fetcher.

Opens one ZenRows/Playwright session (reusing BetkanyonBrowser, not
modifying it) and keeps it open while polling tournament payloads.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from parsers.betkanyon.browser import BetkanyonBrowser


SPORT_HOST = "https://sport.bksp3.com/0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"
PREMATCH_PAGE = "https://betkanyon1617.com/tr/sport/prematchevents/4520"
STAKE_TYPES = [1, 702, 37, 3, 2533, 313639, 2, 2532, 313638]
PATHS = (
    "/common/getmixedsportandeventslistwithoutright",
    "/prematch/getmixedsportsandeventswithoutright",
)
FETCH_BATCH_SIZE = 8

_BATCH_JS = """
async (urls) => {
    return Promise.all(urls.map(async (url) => {
        try {
            const response = await fetch(url, { credentials: "include" });
            const json = await response.json();
            return json.payload || json.Payload || null;
        } catch (e) {
            return null;
        }
    }));
}
"""


def _date_window():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=14)
    return (
        start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        end.strftime("%Y-%m-%dT23:59:59.000Z"),
    )


def build_prematch_url(tournament_id, path=PATHS[0]):
    start_date, end_date = _date_window()
    params = [
        ("startDate", start_date),
        ("endDate", end_date),
        ("period", "0"),
        ("tournamentId", str(tournament_id)),
    ]
    for stake in STAKE_TYPES:
        params.append(("stakeTypes", str(stake)))
    params.extend(
        [
            ("isTournament", "false"),
            ("eventFilterType", "false"),
            ("includeLiveEvents", "false"),
            ("langId", "4"),
            ("partnerId", "107"),
            ("countryCode", "KE"),
        ]
    )
    return SPORT_HOST + path + "?" + urlencode(params)


def _is_browser_dead(exc):
    message = str(exc).lower()
    return (
        "target page" in message
        or "browser has been closed" in message
        or "context has been closed" in message
        or "socket hang up" in message
        or "websocket" in message
        or "connection closed" in message
        or "epipe" in message
    )


class BetkanyonPrematchFetcher:
    def __init__(self):
        self.browser = None
        self.page = None
        self.initialized = False
        self._working_path = PATHS[0]

    def _connect(self):
        print("[BETKANYON PREMATCH] browser started")
        self.browser = BetkanyonBrowser()
        self.browser.open()
        self.page = self.browser.page
        self.browser.goto(PREMATCH_PAGE)
        self.browser.wait(5000)
        self.initialized = True

    def _reset_browser(self):
        print("[BETKANYON PREMATCH] browser died; reconnecting")
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.page = None
        self.initialized = False
        self._connect()

    def _evaluate_urls(self, urls):
        if not self.initialized:
            self._connect()
        return self.page.evaluate(_BATCH_JS, urls)

    def fetch_tournament(self, tournament_id):
        payloads = self.fetch_all([tournament_id])
        return payloads.get(str(tournament_id))

    def fetch_all(self, tournament_ids):
        """Fetch encrypted payloads for many tournaments on one open page."""
        if not self.initialized:
            self._connect()

        ids = [str(tid) for tid in tournament_ids]
        results = {}
        total = len(ids)
        paths_to_try = (
            self._working_path,
            *[p for p in PATHS if p != self._working_path],
        )

        for offset in range(0, total, FETCH_BATCH_SIZE):
            chunk = ids[offset : offset + FETCH_BATCH_SIZE]
            payloads = None
            last_error = None
            for path in paths_to_try:
                urls = [build_prematch_url(tid, path=path) for tid in chunk]
                try:
                    payloads = self._evaluate_urls(urls)
                    if any(payloads):
                        self._working_path = path
                        break
                except Exception as exc:
                    last_error = exc
                    if _is_browser_dead(exc):
                        self._reset_browser()
                        try:
                            payloads = self._evaluate_urls(urls)
                            if any(payloads or []):
                                self._working_path = path
                                break
                        except Exception as retry_exc:
                            last_error = retry_exc
            if last_error and payloads is None:
                raise last_error
            for tid, payload in zip(chunk, payloads or []):
                if payload:
                    results[tid] = payload
            done = min(offset + FETCH_BATCH_SIZE, total)
            if done == total or done % 40 == 0 or offset == 0:
                print(
                    f"[BETKANYON PREMATCH] fetch progress: {done}/{total} "
                    f"(payloads={len(results)})"
                )

        return results

    def close(self):
        if self.browser:
            self.browser.close()
        self.browser = None
        self.page = None
        self.initialized = False
