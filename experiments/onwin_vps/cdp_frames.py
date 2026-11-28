"""Read Onwin odds from every Chrome target, including the sportsbook frame.

Playwright's page session does not see an out-of-process frame. Chrome
will attach those targets on the browser socket when auto-attach is on.
Silence on that socket is normal. Only a closed socket means it died.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
from urllib.parse import urlparse

from parsers.onwin.local_collector import feed_kind


def lane_for_target(url: str) -> str:
    lowered = (url or "").lower()
    if "sportsbook/prelive" in lowered or "sportsbook/prematch" in lowered:
        return "prematch"
    if "sportsbook/live" in lowered:
        return "live"
    return ""


def read_available(sock) -> bytes | None:
    """Return new bytes. b'' means nothing is waiting. None means the socket closed."""
    try:
        chunk = sock.recv(1 << 16)
    except (TimeoutError, BlockingIOError, InterruptedError, socket.timeout):
        return b""
    if chunk == b"":
        return None
    return chunk


def encode_client_frame(payload: bytes, mask: bytes, opcode: int = 0x1) -> bytes:
    raw = payload
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(raw)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
    return bytes(header) + masked


def take_frames(buf: bytearray) -> list[tuple[bool, int, bytes]]:
    """Pop complete websocket frames. An unfinished frame stays in buf."""
    frames = []
    while True:
        if len(buf) < 2:
            return frames
        first, second = buf[0], buf[1]
        opcode = first & 0x0F
        masked = second & 0x80
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                return frames
            length = struct.unpack("!H", buf[2:4])[0]
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                return frames
            length = struct.unpack("!Q", buf[2:10])[0]
            offset = 10
        mask = b""
        if masked:
            if len(buf) < offset + 4:
                return frames
            mask = bytes(buf[offset : offset + 4])
            offset += 4
        if len(buf) < offset + length:
            return frames
        payload = bytes(buf[offset : offset + length])
        del buf[: offset + length]
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        frames.append((bool(first & 0x80), opcode, payload))


class CdpFrameFeed:
    """Browser-level CDP client. One socket, one thread: the collector loop."""

    def __init__(self):
        self.sock = None
        self.alive = False
        self.buf = bytearray()
        self.commands: list[dict] = []
        self.captures: list[dict] = []
        self.noticed: list[str] = []
        self.targets_seen = 0
        self.last_target_url = ""
        self._next_id = 0
        self._session_lane: dict[str, str] = {}
        self._pending: dict[tuple[str, str], dict] = {}
        self._bodies: dict[int, dict] = {}
        self._fragments: list[bytes] = []
        self._fragment_opcode = 1

    def connect(self, ws_url: str) -> None:
        parsed = urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        sock.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                sock.close()
                raise ConnectionError("cdp socket closed during handshake")
            data += chunk
            if len(data) > 65536:
                sock.close()
                raise ConnectionError("cdp handshake too large")
        status = data.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            sock.close()
            raise ConnectionError(status.decode("ascii", "replace"))
        self.sock = sock
        self.buf = bytearray(data.split(b"\r\n\r\n", 1)[1])
        self.alive = True
        sock.settimeout(0)
        self._command("Target.setDiscoverTargets", {"discover": True})
        self._command(
            "Target.setAutoAttach",
            {
                "autoAttach": True,
                "waitForDebuggerOnStart": True,
                "flatten": True,
            },
        )

    def close(self) -> None:
        self.alive = False
        sock = self.sock
        self.sock = None
        if sock is None:
            return
        try:
            sock.close()
        except Exception:
            pass

    def pump(self) -> None:
        if not self.alive or self.sock is None:
            return
        while True:
            chunk = read_available(self.sock)
            if chunk is None:
                self.alive = False
                return
            if chunk == b"":
                break
            self.buf.extend(chunk)
        self._consume()

    def pump_for(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self.alive and time.monotonic() < end:
            self.pump()
            time.sleep(0.02)

    def take(self) -> list[dict]:
        found = self.captures
        self.captures = []
        return found

    def take_noticed(self) -> list[str]:
        found = self.noticed
        self.noticed = []
        return found

    def handle_message(self, msg: dict) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            self._finish_command(msg)
            return
        method = msg.get("method")
        params = msg.get("params") or {}
        parent = msg.get("sessionId")
        if method == "Target.attachedToTarget":
            self._attach(params, parent if isinstance(parent, str) else "")
        elif method == "Network.responseReceived":
            self._response(params, parent if isinstance(parent, str) else "")
        elif method == "Network.loadingFinished":
            self._finished(params, parent if isinstance(parent, str) else "")
        elif method == "Fetch.requestPaused":
            self._paused(params, parent if isinstance(parent, str) else "")

    def _attach(self, params: dict, parent: str) -> None:
        child = str(params.get("sessionId") or "")
        if not child:
            return
        info = params.get("targetInfo") or {}
        url = str(info.get("url") or "")
        lane = lane_for_target(url) or self._session_lane.get(parent, "")
        self._session_lane[child] = lane
        self.targets_seen += 1
        if url:
            self.last_target_url = url
        self._command(
            "Network.enable",
            {
                "maxTotalBufferSize": 100 * 1024 * 1024,
                "maxResourceBufferSize": 50 * 1024 * 1024,
            },
            child,
        )
        self._command(
            "Fetch.enable",
            {"patterns": [{"urlPattern": pattern, "requestStage": "Response"} for pattern in _FEED_PATTERNS]},
            child,
        )
        self._command(
            "Target.setAutoAttach",
            {
                "autoAttach": True,
                "waitForDebuggerOnStart": True,
                "flatten": True,
            },
            child,
        )
        if params.get("waitingForDebugger"):
            self._command("Runtime.runIfWaitingForDebugger", {}, child)

    def _response(self, params: dict, session_id: str) -> None:
        response = params.get("response") or {}
        url = str(response.get("url") or "")
        request_id = str(params.get("requestId") or "")
        if not request_id or not url:
            return
        if looks_like_feed_url(url):
            self.noticed.append(url)
        kind = feed_kind(url)
        if kind is None or int(response.get("status") or 0) >= 400:
            return
        lane = self._session_lane.get(session_id) or lane_for_target(url)
        self._pending[(session_id, request_id)] = {
            "url": url,
            "lane": lane,
            "kind": kind,
        }

    def _paused(self, params: dict, session_id: str) -> None:
        """Take the odds body while Chrome is still holding the response."""
        request_id = str(params.get("requestId") or "")
        request = params.get("request") or {}
        url = str(request.get("url") or "")
        if not request_id:
            return
        if url and looks_like_feed_url(url):
            self.noticed.append(url)
        kind = feed_kind(url)
        status = int(params.get("responseStatusCode") or 0)
        if kind is not None and status < 400:
            lane = self._session_lane.get(session_id) or lane_for_target(url)
            command_id = self._command(
                "Fetch.getResponseBody",
                {"requestId": request_id},
                session_id or None,
            )
            self._bodies[command_id] = {"url": url, "lane": lane, "kind": kind}
        self._command(
            "Fetch.continueResponse",
            {"requestId": request_id},
            session_id or None,
        )

    def _finished(self, params: dict, session_id: str) -> None:
        request_id = str(params.get("requestId") or "")
        meta = self._pending.pop((session_id, request_id), None)
        if meta is None:
            return
        command_id = self._command(
            "Network.getResponseBody",
            {"requestId": request_id},
            session_id or None,
        )
        self._bodies[command_id] = meta

    def _finish_command(self, msg: dict) -> None:
        meta = self._bodies.pop(msg.get("id"), None)
        if meta is None or "result" not in msg:
            return
        result = msg.get("result") or {}
        body = result.get("body") or ""
        if result.get("base64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", "replace")
            except Exception:
                return
        if not body:
            return
        try:
            raw = json.loads(body)
        except Exception:
            return
        self.captures.append({"url": meta["url"], "lane": meta["lane"], "raw": raw})

    def _consume(self) -> None:
        for fin, opcode, payload in take_frames(self.buf):
            if opcode == 0x8:
                self.alive = False
                return
            if opcode == 0x9:
                self._send_text_opcode(payload, 0xA)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                self._fragments = [payload]
            elif opcode == 0x0:
                self._fragments.append(payload)
            else:
                continue
            if fin:
                whole = b"".join(self._fragments)
                self._fragments = []
                if whole:
                    self._accept_text(whole)

    def _accept_text(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload.decode("utf-8", "replace"))
        except Exception:
            return
        if isinstance(msg, dict):
            self.handle_message(msg)

    def _command(self, method: str, params: dict, session_id: str | None = None) -> int:
        self._next_id += 1
        msg = {"id": self._next_id, "method": method, "params": params}
        if session_id:
            msg["sessionId"] = session_id
        self.commands.append(msg)
        if self.sock is not None and self.alive:
            self._send_text_opcode(json.dumps(msg).encode("utf-8"), 0x1)
        return self._next_id

    def _send_text_opcode(self, payload: bytes, opcode: int) -> None:
        self._send_frame(encode_client_frame(payload, os.urandom(4), opcode))

    def _send_frame(self, frame: bytes) -> None:
        sock = self.sock
        if sock is None:
            return
        previous = sock.gettimeout()
        try:
            sock.settimeout(2)
            sock.sendall(frame)
        except Exception:
            self.alive = False
        finally:
            try:
                sock.settimeout(previous)
            except Exception:
                pass


_FEED_PATTERNS = (
    "*get_main_line.erisgaming*",
    "*get_main_line_compact.erisgaming*",
    "*get_main_line_gap.erisgaming*",
    "*find_event_snapshots.erisgaming*",
)


def looks_like_feed_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(token in lowered for token in ("erisgaming", "4297.lol", "538.lol", "api-onwin"))
