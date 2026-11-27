"""Listen on every Chrome target, including the sportsbook frame.

The top document is the casino shell. A network listener on that document
does not see the frame that calls the odds feed. This client attaches to
each frame on its own debugger socket. Callbacks only remember ids. The
collector loop reads the bodies.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from urllib.parse import urlsplit
from urllib.request import urlopen

from parsers.onwin.local_collector import feed_kind

_MAX_MESSAGE = 20 * 1024 * 1024
_INTERESTING = ("erisgaming", "4297.lol", "538.lol", "frontserver", "get_main_line")


def public_page(url: str) -> str:
    """Page address without a query. The query can carry a clearance token."""
    parts = urlsplit(url or "")
    if not parts.scheme or not parts.netloc:
        return (url or "").split("?", 1)[0].split("#", 1)[0]
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def lane_for(url: str) -> str:
    lowered = (url or "").lower()
    if "prelive" in lowered or "prematch" in lowered:
        return "prematch"
    return "live"


def interesting_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(part in lowered for part in _INTERESTING)


def encode_client_text(text: str) -> bytes:
    return encode_client_frame(0x1, text.encode("utf-8"))


def encode_client_frame(opcode: int, payload: bytes) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | (opcode & 0x0F)])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + mask + masked


def take_server_frames(buf: bytes) -> tuple[list[tuple[bool, int, bytes]], bytes]:
    """Split complete server frames off a buffer. The rest stays buffered."""
    frames: list[tuple[bool, int, bytes]] = []
    while True:
        if len(buf) < 2:
            break
        first, second = buf[0], buf[1]
        finished = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                break
            length = struct.unpack("!H", buf[2:4])[0]
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                break
            length = struct.unpack("!Q", buf[2:10])[0]
            offset = 10
        if length > _MAX_MESSAGE:
            raise ValueError("debugger frame is too large")
        if masked:
            if len(buf) < offset + 4:
                break
            mask = buf[offset:offset + 4]
            offset += 4
        else:
            mask = b""
        if len(buf) < offset + length:
            break
        data = buf[offset:offset + length]
        if mask:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        buf = buf[offset + length:]
        frames.append((finished, opcode, data))
    return frames, buf


class _Conn:
    def __init__(self, sock: socket.socket, key: str, url: str):
        self.sock = sock
        self.key = key
        self.url = url
        self.lock = threading.Lock()
        self.buf = b""
        self.partial = b""
        self.dead = False


class FeedTargets:
    """Debugger sockets for the open tabs and the frames inside them.

    The browser-level socket is the one Playwright waits on. HTTP
    /json/version keeps answering while that handshake never finishes.
    Each open tab has its own socket, and that one accepts.
    """

    def __init__(self):
        self.attached = 0
        self._lock = threading.Lock()
        self._wait: dict[int, tuple[threading.Event, dict]] = {}
        self._next = 1
        self._partial = b""
        self._partial_opcode = 0
        self._closed = False
        self._conns: list[_Conn] = []
        self._socket_of: dict[str, _Conn] = {}
        self._sessions: dict[str, str] = {}
        self._frames: list[str] = []
        self._pending: dict[tuple[str, str], dict] = {}
        self._ready: list[dict] = []
        self._seen: list[str] = []
        self.dropped = 0

    def open_pages(self, cdp: str) -> list[dict]:
        pages = list_pages(cdp)
        if not pages:
            raise RuntimeError("Chrome has no tab")
        self._closed = False
        for page in pages:
            try:
                self._add_page(page)
            except Exception:
                continue
        if not self._conns:
            raise RuntimeError("page socket was not accepted")
        self.attached = len(self._socket_of)
        return pages

    def _lane(self, session_id: str, url: str) -> str:
        """Use the tab address when the frame address does not say which book it is."""
        owner = self._socket_of.get(session_id)
        page_url = owner.url if owner is not None else ""
        target = self._sessions.get(session_id, "")
        for candidate in (page_url, target, url):
            lowered = (candidate or "").lower()
            if "prelive" in lowered or "prematch" in lowered:
                return "prematch"
            if "sportsbook/live" in lowered:
                return "live"
        return lane_for(page_url or target or url)

    def page_urls(self) -> list[tuple[str, str]]:
        return [(conn.key, conn.url) for conn in self._conns if not conn.dead]

    def note_urls(self, pages: list[dict]) -> None:
        by_id = {str(page.get("id") or ""): public_page(str(page.get("url") or "")) for page in pages}
        for conn in self._conns:
            if conn.key in by_id and by_id[conn.key]:
                conn.url = by_id[conn.key]

    def alive(self) -> bool:
        return any(not conn.dead for conn in self._conns)

    def evaluate(self, key: str, source: str):
        conn = self._socket_of.get(key)
        if conn is None or conn.dead:
            raise RuntimeError("tab is gone")
        chrome_session = None if conn.key == key else key
        result = self._call(
            "Runtime.evaluate",
            {"expression": source, "returnByValue": True},
            conn=conn,
            chrome_session=chrome_session,
            timeout=2,
        )
        return (result.get("result") or {}).get("value")

    def bring_to_front(self, key: str) -> None:
        conn = self._socket_of.get(key)
        if conn is None:
            return
        self._call("Page.bringToFront", {}, conn=conn, timeout=2)

    def focus_page(self, key: str) -> None:
        self.bring_to_front(key)

    def open_blank(self, key: str, url: str) -> None:
        """Open a sportsbook address only on a tab that has no document."""
        conn = self._socket_of.get(key)
        if conn is None or not url:
            return
        self._call("Page.navigate", {"url": url}, conn=conn, timeout=3)

    def _add_page(self, page: dict) -> None:
        sock = _connect_websocket(str(page.get("webSocketDebuggerUrl") or ""), timeout=3)
        conn = _Conn(sock, str(page.get("id") or ""), public_page(str(page.get("url") or "")))
        self._conns.append(conn)
        self._socket_of[conn.key] = conn
        self._remember(conn.key, "page", conn.url)
        threading.Thread(target=self._read_loop, args=(conn,), name="onwin-page", daemon=True).start()
        try:
            self._call(
                "Network.enable",
                {
                    "maxTotalBufferSize": 100 * 1024 * 1024,
                    "maxResourceBufferSize": 50 * 1024 * 1024,
                },
                conn=conn,
                timeout=3,
            )
        except Exception:
            pass
        # No type filter. The odds frame is not always reported as an iframe,
        # and a filter that misses it leaves the live tab at 0.
        try:
            self._call(
                "Target.setAutoAttach",
                {
                    "autoAttach": True,
                    "waitForDebuggerOnStart": False,
                    "flatten": True,
                },
                conn=conn,
                timeout=3,
            )
        except Exception:
            pass
        self.collect_frames()
        try:
            self._call("Page.enable", {}, conn=conn, timeout=2)
        except Exception:
            pass

    def close(self) -> None:
        self._closed = True
        for conn in self._conns:
            conn.dead = True
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.sock.close()
            except Exception:
                pass

    def collect_frames(self) -> None:
        """Record every document URL, including the sportsbook frame."""
        for conn in list(self._conns):
            if conn.dead:
                continue
            try:
                result = self._call("Page.getFrameTree", {}, conn=conn, timeout=2)
            except Exception:
                continue
            self._walk_frame(result.get("frameTree") or {})

    def _walk_frame(self, node: dict) -> None:
        frame = node.get("frame") or {}
        url = public_page(str(frame.get("url") or ""))
        if url and not url.lower().startswith("about:"):
            self._add_frame(f"frame {url}")
        for child in node.get("childFrames") or []:
            if isinstance(child, dict):
                self._walk_frame(child)

    def _add_frame(self, label: str) -> None:
        label = (label or "")[:180]
        if not label:
            return
        with self._lock:
            if label not in self._frames:
                self._frames.append(label)
                del self._frames[:-12]

    def wake_all(self, source: str) -> None:
        """Tell every sportsbook document it is visible, including a child frame."""
        for key, conn in list(self._socket_of.items()):
            if conn.dead:
                continue
            target = (self._sessions.get(key) or conn.url or "").lower()
            if "analytics." in target or "fstrg" in target:
                continue
            try:
                self.evaluate(key, source)
            except Exception:
                continue

    def frame_labels(self) -> list[str]:
        with self._lock:
            return list(self._frames)

    def take_seen(self) -> list[str]:
        with self._lock:
            seen = self._seen
            self._seen = []
            return seen

    def take_ready(self) -> list[dict]:
        with self._lock:
            ready = self._ready
            self._ready = []
            return ready

    def read_body(self, session_id: str, request_id: str) -> str | None:
        if not session_id or not request_id:
            return None
        conn = self._socket_of.get(session_id)
        if conn is None or conn.dead:
            return None
        chrome_session = None if conn.key == session_id else session_id
        try:
            result = self._call(
                "Network.getResponseBody",
                {"requestId": request_id},
                conn=conn,
                chrome_session=chrome_session,
                timeout=8,
            )
        except Exception:
            return None
        body = (result or {}).get("body")
        if not isinstance(body, str) or not body:
            return None
        if (result or {}).get("base64Encoded"):
            import base64

            try:
                return base64.b64decode(body).decode("utf-8", "replace")
            except Exception:
                return None
        return body

    def accept(self, message: dict, origin: _Conn | None = None) -> None:
        """Handle one debugger message. Tests call this without a socket."""
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if message.get("id") is not None and "method" not in message:
            self._fulfill(int(message["id"]), message.get("result") or {}, message.get("error"))
            return
        if method == "Target.attachedToTarget":
            child = str(params.get("sessionId") or "")
            if child and origin is not None:
                self._socket_of[child] = origin
            self._attached(params)
            return
        if method == "Target.detachedFromTarget":
            session_id = str(params.get("sessionId") or "")
            with self._lock:
                self._sessions.pop(session_id, None)
                self.attached = len(self._sessions)
            return
        session_id = str(message.get("sessionId") or "")
        if method == "Target.targetInfoChanged":
            info = params.get("targetInfo") or {}
            url = public_page(str(info.get("url") or ""))
            if url:
                self._add_frame(f"{info.get('type') or 'target'} {url}")
            return
        if method == "Network.webSocketCreated":
            url = str(params.get("url") or "")
            self._note_url(url)
            if url:
                self._add_frame(f"socket {public_page(url)}")
            return
        if method == "Network.requestWillBeSent":
            request = params.get("request") or {}
            self._note_url(str(request.get("url") or ""))
            return
        if method == "Network.responseReceived":
            response = params.get("response") or {}
            url = str(response.get("url") or "")
            request_id = str(params.get("requestId") or "")
            self._note_url(url)
            if not request_id or feed_kind(url) is None:
                return
            item = {
                "kind": "http",
                "session_id": session_id,
                "request_id": request_id,
                "url": url,
                "status": int(response.get("status") or 0),
                "lane": self._lane(session_id, url),
            }
            with self._lock:
                self._pending[(session_id, request_id)] = item
            return
        if method == "Network.loadingFinished":
            request_id = str(params.get("requestId") or "")
            with self._lock:
                item = self._pending.pop((session_id, request_id), None)
                if item is None:
                    return
                self._ready.append(item)
                overflow = len(self._ready) - 40
                if overflow > 0:
                    del self._ready[:overflow]
                    self.dropped += overflow
            return
        if method == "Network.webSocketFrameReceived":
            response = params.get("response") or {}
            payload = response.get("payloadData")
            if not isinstance(payload, str):
                return
            text = payload
            if int(response.get("opcode") or 1) == 2 or (text[:1] not in "{["):
                import base64

                try:
                    decoded = base64.b64decode(payload).decode("utf-8", "replace").lstrip()
                except Exception:
                    decoded = ""
                if decoded[:1] in "{[":
                    text = decoded
            text = text.lstrip()
            if not text or text[0] not in "{[":
                return
            lowered = text.lower()
            if "sports" not in lowered and "erisgaming" not in lowered:
                return
            with self._lock:
                self._ready.append(
                    {
                        "kind": "socket",
                        "session_id": session_id,
                        "url": "wss://frame",
                        "lane": self._lane(session_id, ""),
                        "payload": text[:2_000_000],
                    }
                )

    def _attached(self, params: dict) -> None:
        session_id = str(params.get("sessionId") or "")
        info = params.get("targetInfo") or {}
        url = public_page(str(info.get("url") or ""))
        kind = str(info.get("type") or "")
        if not session_id:
            return
        label = f"{kind} {url}".strip()
        self._remember(session_id, kind, url)
        self._enable(session_id)

    def _note_url(self, url: str) -> None:
        if feed_kind(url) or not interesting_url(url):
            return
        path = public_page(url)[-160:]
        with self._lock:
            self._seen.append(path)
            del self._seen[:-20]

    def _remember(self, session_id: str, kind: str, url: str) -> None:
        label = f"{kind} {url}".strip()
        with self._lock:
            if url:
                self._sessions[session_id] = url
            self.attached = max(len(self._socket_of), len(self._sessions))
            if url and label not in self._frames:
                self._frames.append(label[:180])
                del self._frames[:-12]

    def _enable(self, session_id: str) -> None:
        conn = self._socket_of.get(session_id)
        if conn is None:
            return
        chrome_session = None if conn.key == session_id else session_id
        try:
            self._send(
                "Network.enable",
                {
                    "maxTotalBufferSize": 100 * 1024 * 1024,
                    "maxResourceBufferSize": 50 * 1024 * 1024,
                },
                conn=conn,
                chrome_session=chrome_session,
            )
        except Exception:
            return

    def _call(
        self,
        method: str,
        params: dict | None = None,
        conn: _Conn | None = None,
        chrome_session: str | None = None,
        timeout: float = 8,
    ):
        event = threading.Event()
        box: dict = {}
        with self._lock:
            message_id = self._next
            self._next += 1
            self._wait[message_id] = (event, box)
        self._send(method, params or {}, conn=conn, chrome_session=chrome_session, message_id=message_id)
        if not event.wait(timeout):
            with self._lock:
                self._wait.pop(message_id, None)
            raise TimeoutError(method)
        if box.get("error"):
            raise RuntimeError(str(box["error"])[:160])
        return box.get("result") or {}

    def _send(
        self,
        method: str,
        params: dict,
        conn: _Conn | None = None,
        chrome_session: str | None = None,
        message_id: int | None = None,
    ):
        if message_id is None:
            with self._lock:
                message_id = self._next
                self._next += 1
        if conn is None:
            return
        message = {"id": message_id, "method": method, "params": params}
        if chrome_session:
            message["sessionId"] = chrome_session
        data = encode_client_text(json.dumps(message))
        with conn.lock:
            conn.sock.sendall(data)

    def _fulfill(self, message_id: int, result: dict, error) -> None:
        with self._lock:
            waiting = self._wait.pop(message_id, None)
        if waiting is None:
            return
        event, box = waiting
        box["result"] = result
        box["error"] = error
        event.set()

    def _read_loop(self, conn: _Conn) -> None:
        try:
            while not self._closed and not conn.dead:
                try:
                    chunk = conn.sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                conn.buf += chunk
                frames, conn.buf = take_server_frames(conn.buf)
                for finished, opcode, data in frames:
                    self._take_opcode(conn, finished, opcode, data)
        except Exception:
            pass
        conn.dead = True

    def _take_opcode(self, conn: _Conn | None, finished: bool, opcode: int, data: bytes) -> None:
        partial = conn.partial if conn is not None else self._partial
        if opcode in {0, 1}:
            if opcode == 1:
                partial = data
            else:
                partial += data
            if conn is not None:
                conn.partial = b"" if finished else partial
            else:
                self._partial = b"" if finished else partial
            if not finished:
                return
            self._dispatch_text(partial, conn)
            return
        if opcode == 9 and conn is not None:
            try:
                with conn.lock:
                    conn.sock.sendall(encode_client_frame(0xA, data))
            except Exception:
                return
            return
        if opcode == 8 and conn is not None:
            conn.dead = True

    def _dispatch_text(self, data: bytes, origin: _Conn | None = None) -> None:
        try:
            message = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(message, dict):
            return
        if origin is not None and message.get("method") and not message.get("sessionId"):
            if message.get("method") != "Target.attachedToTarget":
                message["sessionId"] = origin.key
        self.accept(message, origin)


def list_pages(cdp: str) -> list[dict]:
    """Open tabs from /json/list. The browser websocket is not used."""
    parts = urlsplit(cdp if "://" in cdp else f"http://{cdp}")
    host = parts.hostname or ""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("debugger host is not local")
    port = parts.port or 9223
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
        rows = json.loads(response.read().decode("utf-8"))
    return select_pages(rows if isinstance(rows, list) else [])


def select_pages(rows: list) -> list[dict]:
    pages = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "page":
            continue
        ws_url = str(row.get("webSocketDebuggerUrl") or "")
        ws_parts = urlsplit(ws_url)
        if ws_parts.hostname not in {"127.0.0.1", "localhost"}:
            continue
        url = str(row.get("url") or "")
        if url.startswith(("chrome:", "devtools:", "chrome-extension:")):
            continue
        pages.append(
            {
                "id": str(row.get("id") or ""),
                "url": url,
                "title": str(row.get("title") or ""),
                "webSocketDebuggerUrl": ws_url,
            }
        )
    return pages


def _browser_websocket(cdp: str) -> str:
    parts = urlsplit(cdp if "://" in cdp else f"http://{cdp}")
    host = parts.hostname or ""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("debugger host is not local")
    port = parts.port or 9223
    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
        version = json.loads(response.read().decode("utf-8"))
    ws_url = str(version.get("webSocketDebuggerUrl") or "")
    ws_parts = urlsplit(ws_url)
    if ws_parts.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("debugger socket is not local")
    return ws_url


def _connect_websocket(ws_url: str, timeout: float = 3) -> socket.socket:
    parts = urlsplit(ws_url)
    if parts.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("debugger socket is not local")
    port = parts.port or 80
    sock = socket.create_connection((parts.hostname, port), timeout=timeout)
    sock.settimeout(2)
    key = os.urandom(16)
    import base64

    nonce = base64.b64encode(key).decode("ascii")
    path = parts.path or "/"
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {parts.hostname}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {nonce}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sock.recv(4096)
        if not chunk:
            break
        header += chunk
        if len(header) > 8192:
            break
    status = header.split(b"\r\n", 1)[0]
    if b" 101 " not in status:
        sock.close()
        raise RuntimeError("debugger did not accept the socket")
    # A quiet tab is not a dead socket. The handshake timeout must not
    # stay on the read loop, or two seconds of silence closes the tab.
    sock.settimeout(None)
    return sock
