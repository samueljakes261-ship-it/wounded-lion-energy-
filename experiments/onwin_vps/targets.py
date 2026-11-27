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


class FeedTargets:
    """One debugger connection that follows pages and their frames."""

    def __init__(self):
        self.attached = 0
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._wait: dict[int, tuple[threading.Event, dict]] = {}
        self._next = 1
        self._send_lock = threading.Lock()
        self._buf = b""
        self._partial = b""
        self._partial_opcode = 0
        self._closed = False
        self._sessions: dict[str, str] = {}
        self._frames: list[str] = []
        self._pending: dict[tuple[str, str], dict] = {}
        self._ready: list[dict] = []
        self._seen: list[str] = []
        self.dropped = 0

    def open(self, cdp: str) -> None:
        ws_url = _browser_websocket(cdp)
        self._sock = _connect_websocket(ws_url)
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop, name="onwin-frames", daemon=True)
        self._reader.start()
        self._call("Target.setDiscoverTargets", {"discover": True})
        try:
            self._call(
                "Target.setAutoAttach",
                {
                    "autoAttach": True,
                    "waitForDebuggerOnStart": False,
                    "flatten": True,
                    "filter": [
                        {"type": "page"},
                        {"type": "iframe"},
                        {"type": "worker"},
                        {"type": "service_worker"},
                    ],
                },
            )
        except Exception:
            self._call(
                "Target.setAutoAttach",
                {
                    "autoAttach": True,
                    "waitForDebuggerOnStart": False,
                    "flatten": True,
                },
            )

    def close(self) -> None:
        self._closed = True
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

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
        try:
            result = self._call(
                "Network.getResponseBody",
                {"requestId": request_id},
                session_id=session_id,
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

    def accept(self, message: dict) -> None:
        """Handle one debugger message. Tests call this without a socket."""
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if message.get("id") is not None and "method" not in message:
            self._fulfill(int(message["id"]), message.get("result") or {}, message.get("error"))
            return
        if method == "Target.attachedToTarget":
            self._attached(params)
            return
        if method == "Target.detachedFromTarget":
            session_id = str(params.get("sessionId") or "")
            with self._lock:
                self._sessions.pop(session_id, None)
                self.attached = len(self._sessions)
            return
        session_id = str(message.get("sessionId") or "")
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
            target = self._sessions.get(session_id, "")
            item = {
                "kind": "http",
                "session_id": session_id,
                "request_id": request_id,
                "url": url,
                "status": int(response.get("status") or 0),
                "lane": lane_for(target or url),
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
            payload = (params.get("response") or {}).get("payloadData")
            if not isinstance(payload, str):
                return
            text = payload.lstrip()
            if not text or text[0] not in "{[":
                return
            lowered = text.lower()
            if "sports" not in lowered and "erisgaming" not in lowered:
                return
            target = self._sessions.get(session_id, "")
            with self._lock:
                self._ready.append(
                    {
                        "kind": "socket",
                        "session_id": session_id,
                        "url": "wss://frame",
                        "lane": lane_for(target),
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
        with self._lock:
            self._sessions[session_id] = url
            self.attached = len(self._sessions)
            if url and label not in self._frames:
                self._frames.append(label[:180])
                del self._frames[:-8]
        self._enable(session_id)

    def _note_url(self, url: str) -> None:
        if feed_kind(url) or not interesting_url(url):
            return
        path = public_page(url)[-160:]
        with self._lock:
            self._seen.append(path)
            del self._seen[:-20]

    def _enable(self, session_id: str) -> None:
        if self._sock is None:
            return
        try:
            self._send(
                "Network.enable",
                {
                    "maxTotalBufferSize": 100 * 1024 * 1024,
                    "maxResourceBufferSize": 50 * 1024 * 1024,
                },
                session_id=session_id,
                wait=False,
            )
        except Exception:
            return

    def _call(self, method: str, params: dict | None = None, session_id: str | None = None, timeout: float = 8):
        event = threading.Event()
        box: dict = {}
        with self._lock:
            message_id = self._next
            self._next += 1
            self._wait[message_id] = (event, box)
        self._send(method, params or {}, session_id=session_id, message_id=message_id)
        if not event.wait(timeout):
            with self._lock:
                self._wait.pop(message_id, None)
            raise TimeoutError(method)
        if box.get("error"):
            raise RuntimeError(str(box["error"])[:160])
        return box.get("result") or {}

    def _send(self, method: str, params: dict, session_id: str | None = None, message_id: int | None = None, wait: bool = True):
        del wait
        if message_id is None:
            with self._lock:
                message_id = self._next
                self._next += 1
        message = {"id": message_id, "method": method, "params": params}
        if session_id:
            message["sessionId"] = session_id
        sock = self._sock
        if sock is None:
            return
        data = encode_client_text(json.dumps(message))
        with self._send_lock:
            sock.sendall(data)

    def _fulfill(self, message_id: int, result: dict, error) -> None:
        with self._lock:
            waiting = self._wait.pop(message_id, None)
        if waiting is None:
            return
        event, box = waiting
        box["result"] = result
        box["error"] = error
        event.set()

    def _read_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            while not self._closed:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                self._buf += chunk
                frames, self._buf = take_server_frames(self._buf)
                for finished, opcode, data in frames:
                    self._take_opcode(sock, finished, opcode, data)
        except Exception:
            return

    def _take_opcode(self, sock: socket.socket, finished: bool, opcode: int, data: bytes) -> None:
        if opcode in {0, 1}:
            if opcode == 1:
                self._partial = data
                self._partial_opcode = 1
            else:
                self._partial += data
            if not finished:
                return
            payload = self._partial
            self._partial = b""
            self._dispatch_text(payload)
            return
        if opcode == 9:
            try:
                with self._send_lock:
                    sock.sendall(encode_client_frame(0xA, data))
            except Exception:
                return
            return
        if opcode == 8:
            self._closed = True

    def _dispatch_text(self, data: bytes) -> None:
        try:
            message = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if isinstance(message, dict):
            self.accept(message)


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


def _connect_websocket(ws_url: str) -> socket.socket:
    parts = urlsplit(ws_url)
    port = parts.port or 80
    sock = socket.create_connection((parts.hostname, port), timeout=5)
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
    return sock
