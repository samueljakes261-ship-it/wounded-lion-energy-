"""ZenRows/Playwright BetKanyon prematch fetcher (FALLBACK ONLY).

Kept so the previous acquisition path can be restored without rewriting
it. The default prematch path is direct HTTP in fetcher.py.

Do not import this module unless BETKANYON_PREMATCH_FETCH=zenrows.
Live parsers.betkanyon.browser is not modified.
"""

from parsers.betkanyon.browser import BetkanyonBrowser
from parsers.betkanyon_prematch.fetcher import (
    FETCH_BATCH_SIZE,
    PATHS,
    SPORT_PAGE,
    build_prematch_url,
)


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


class BetkanyonPrematchZenrowsFetcher:
    """Previous persistent ZenRows browser fetcher. Unused by default."""

    def __init__(self):
        self.browser = None
        self.page = None
        self.initialized = False
        self._working_path = PATHS[0]

    def _connect(self):
        print("[BETKANYON PREMATCH] browser started (ZenRows fallback)")
        self.browser = BetkanyonBrowser()
        self.browser.open()
        self.page = self.browser.page
        # Same-origin RequestHelper. The rotating frontend host is unused.
        self.browser.goto(SPORT_PAGE)
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
