"""Record Onwin responses without using the debugger inside an event.

Playwright and CDP callbacks run on the connection that has to deliver
the next response. Reading a body there stops that connection. Live odds
then arrive for a short while and the dashboard goes back to error.
Callbacks only remember ids. The collector loop reads the bodies.

A quiet open page is asked again with the same request it already made.
That uses the document that cleared Cloudflare. It does not navigate.
"""

from __future__ import annotations

import threading

from parsers.onwin.local_collector import feed_kind

# The live page on a private screen stops polling once Chrome reports it
# hidden. Ask again only after a real gap, and not on every pass.
REPLAY_QUIET_SECONDS = 6.0
REPLAY_GAP_SECONDS = 4.0
SNAPSHOT_REPLAY_GAP_SECONDS = 8.0
KEEP_AWAKE_SECONDS = 15.0

_REPLAY_HEADER_NAMES = {
    "accept",
    "accept-language",
    "content-type",
    "x-message-metadata",
    "x-token",
}

# Runs in the open page. Makes the sportsbook see a visible, focused
# document so its own poll keeps running. Does not navigate.
KEEP_AWAKE_SOURCE = """
() => {
  const define = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, {
        configurable: true,
        get: () => value,
        set: () => {},
      });
    } catch (e) {}
  };
  define(Document.prototype, "hidden", false);
  define(Document.prototype, "visibilityState", "visible");
  define(Document.prototype, "webkitHidden", false);
  define(Document.prototype, "webkitVisibilityState", "visible");
  define(document, "hidden", false);
  define(document, "visibilityState", "visible");
  try { document.hasFocus = () => true; } catch (e) {}
  try { document.dispatchEvent(new Event("visibilitychange")); } catch (e) {}
  return document.visibilityState || "";
}
"""

# Fired from the open page. The body is drained so the debugger can see
# the finished response. The collector reads that capture afterwards.
REPLAY_SOURCE = """
async ({url, method, headers, body}) => {
  const response = await fetch(url, {
    method: method || "GET",
    headers: headers || {},
    body: body == null ? undefined : body,
    credentials: "include",
    cache: "no-store",
  });
  await response.arrayBuffer();
  return response.status;
}
"""


def replay_headers(headers: dict) -> dict:
    """Headers the page may set on a follow-up fetch.

    Cookie is left to the document. The names that carry the session
    stay in memory for that fetch and are not returned anywhere else.
    """
    kept = {}
    for key, value in (headers or {}).items():
        name = str(key).lower()
        if name not in _REPLAY_HEADER_NAMES or value is None:
            continue
        kept[name] = str(value)
    if "accept" not in kept:
        kept["accept"] = "application/json"
    if "content-type" not in kept:
        kept["content-type"] = "application/json"
    return kept


def should_replay_feed(
    *,
    seconds_since_traffic: float,
    seconds_since_replay: float,
    challenge: bool,
    have_request: bool,
    minimum_quiet: float = REPLAY_QUIET_SECONDS,
    minimum_gap: float = REPLAY_GAP_SECONDS,
) -> bool:
    """Ask the open page for odds only after it has gone quiet.

    A Cloudflare check is left alone. A page that is already sending is
    left alone too.
    """
    if challenge or not have_request:
        return False
    if seconds_since_traffic < minimum_quiet:
        return False
    return seconds_since_replay >= minimum_gap


def should_queue_response(url: str) -> bool:
    """True for a sportsbook response, including one from an inner frame.

    The casino shell is the top document. The odds calls come from the
    sportsbook frame. A listener on the top document alone never sees them.
    """
    lowered = (url or "").lower()
    if "kolay" in lowered:
        return False
    if feed_kind(url):
        return True
    return "erisgaming" in lowered or "4297.lol" in lowered


def should_keep_awake(*, challenge: bool, seconds_since_awake: float, minimum: float = KEEP_AWAKE_SECONDS) -> bool:
    """Refresh the visible-document signal on a slow cadence."""
    if challenge:
        return False
    return seconds_since_awake >= minimum


class LaneTap:
    """One tab's feed calls and the response ids waiting to be read."""

    def __init__(self, limit: int = 40):
        self.limit = limit
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._order: list[str] = []
        self._ready: list[dict] = []
        self._sockets: list[str] = []
        self._calls: dict[str, dict] = {}
        self._need_body: list[str] = []
        self.last_snapshot: dict | None = None
        self.last_update: dict | None = None
        self.dropped = 0

    def note_request(self, request_id: str, url: str, method: str, headers: dict, post_data) -> None:
        kind = feed_kind(url)
        if not request_id or kind is None:
            return
        verb = (method or "GET").upper()
        body = post_data if isinstance(post_data, str) else None
        call = {
            "url": url,
            "method": verb,
            "headers": replay_headers(headers or {}),
            "body": body,
            "kind": kind,
            "needs_body": body is None and verb != "GET",
        }
        with self._lock:
            self._calls[request_id] = call
            if call["needs_body"]:
                self._need_body.append(request_id)
            else:
                self._publish_call(call)

    def set_post_data(self, request_id: str, post_data) -> None:
        with self._lock:
            call = self._calls.get(request_id)
            if call is None:
                return
            call["body"] = post_data if isinstance(post_data, str) else None
            call["needs_body"] = False
            self._need_body = [item for item in self._need_body if item != request_id]
            self._publish_call(call)

    def bodies_needed(self) -> list[str]:
        with self._lock:
            needed = list(self._need_body)
            self._need_body = []
            return needed

    def restore_body_request(self, request_id: str) -> None:
        """Try once more to read a missing POST body. Do not retry forever."""
        with self._lock:
            call = self._calls.get(request_id)
            if call is None or not call.get("needs_body"):
                return
            tries = int(call.get("body_tries") or 0) + 1
            call["body_tries"] = tries
            if tries > 2:
                return
            if request_id not in self._need_body:
                self._need_body.append(request_id)

    def note_response(self, request_id: str, url: str, status: int) -> None:
        if not request_id or feed_kind(url) is None:
            return
        item = {"kind": "http", "id": request_id, "url": url, "status": int(status or 0)}
        with self._lock:
            self._pending[request_id] = item
            self._order.append(request_id)
            while len(self._order) > self.limit:
                old = self._order.pop(0)
                if self._pending.pop(old, None) is not None:
                    self.dropped += 1

    def note_finished(self, request_id: str) -> None:
        if not request_id:
            return
        with self._lock:
            item = self._pending.pop(request_id, None)
            if item is None:
                return
            try:
                self._order.remove(request_id)
            except ValueError:
                pass
            self._ready.append(item)
            overflow = len(self._ready) - self.limit
            if overflow > 0:
                del self._ready[:overflow]
                self.dropped += overflow

    def note_socket(self, payload: str) -> None:
        text = (payload or "").lstrip()
        if not text or text[0] not in "{[":
            return
        lowered = text.lower()
        if "sports" not in lowered and "erisgaming" not in lowered:
            return
        with self._lock:
            self._sockets.append(text[:2_000_000])
            overflow = len(self._sockets) - 20
            if overflow > 0:
                del self._sockets[:overflow]
                self.dropped += overflow

    def take_ready(self) -> list[dict]:
        with self._lock:
            items = self._ready
            sockets = self._sockets
            self._ready = []
            self._sockets = []
        for text in sockets:
            items.append({"kind": "socket", "payload": text, "url": "wss://live", "status": 200})
        return items

    def replay_choice(self, prefer_snapshot: bool) -> dict | None:
        with self._lock:
            if prefer_snapshot:
                choices = (self.last_snapshot, self.last_update)
            else:
                choices = (self.last_update, self.last_snapshot)
            for call in choices:
                if call and not call.get("needs_body"):
                    return {
                        "url": call["url"],
                        "method": call["method"],
                        "headers": dict(call["headers"]),
                        "body": call["body"],
                        "kind": call["kind"],
                    }
        return None

    def _publish_call(self, call: dict) -> None:
        stored = {
            "url": call["url"],
            "method": call["method"],
            "headers": dict(call["headers"]),
            "body": call["body"],
            "kind": call["kind"],
            "needs_body": False,
        }
        if call["kind"] == "snapshot":
            self.last_snapshot = stored
        else:
            self.last_update = stored
