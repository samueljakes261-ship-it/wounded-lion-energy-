"""Browser-socket capture of Onwin sportsbook frames. No Chrome required."""

from experiments.onwin_vps.cdp_frames import (
    CdpFrameFeed,
    encode_client_frame,
    read_available,
    take_frames,
)


class _Silent:
    def recv(self, _n):
        raise BlockingIOError

    def gettimeout(self):
        return 0

    def settimeout(self, _timeout):
        return None


class _Closed:
    def recv(self, _n):
        return b""


def test_silence_on_the_browser_socket_is_not_death():
    feed = CdpFrameFeed()
    feed.alive = True
    feed.sock = _Silent()
    feed.pump()
    assert feed.alive is True
    assert read_available(_Silent()) == b""
    assert read_available(_Closed()) is None


def test_partial_websocket_frame_stays_buffered():
    buf = bytearray(bytes([0x81, 5]) + b"hel")
    assert take_frames(buf) == []
    assert bytes(buf) == bytes([0x81, 5]) + b"hel"
    buf.extend(b"lo")
    frames = take_frames(buf)
    assert frames == [(True, 1, b"hello")]
    assert buf == bytearray()


def test_client_frame_round_trip():
    mask = b"\x01\x02\x03\x04"
    frame = encode_client_frame(b"{}", mask)
    frames = take_frames(bytearray(frame))
    assert frames == [(True, 1, b"{}")]


def test_attached_sportsbook_frame_gets_network_enabled_on_its_session():
    feed = CdpFrameFeed()
    feed.handle_message(
        {
            "method": "Target.attachedToTarget",
            "params": {
                "sessionId": "child",
                "waitingForDebugger": True,
                "targetInfo": {
                    "type": "iframe",
                    "url": "https://onwin4921.com/sportsbook/live/main-line/soccer",
                },
            },
        }
    )
    methods = [(item["method"], item.get("sessionId")) for item in feed.commands]
    assert ("Network.enable", "child") in methods
    assert ("Runtime.runIfWaitingForDebugger", "child") in methods
    assert feed._session_lane["child"] == "live"
    assert feed.targets_seen == 1


def test_paused_live_odds_response_is_taken_and_released():
    feed = CdpFrameFeed()
    feed._session_lane["live-page"] = "live"
    url = (
        "https://api-onwin-tr--prd--sb.4298.lol/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.get_main_line_compact.erisgaming"
    )
    feed.handle_message(
        {
            "method": "Fetch.requestPaused",
            "sessionId": "live-page",
            "params": {
                "requestId": "paused-1",
                "responseStatusCode": 200,
                "request": {"url": url},
            },
        }
    )
    methods = [(item["method"], item.get("sessionId")) for item in feed.commands]
    assert ("Fetch.getResponseBody", "live-page") in methods
    assert ("Fetch.continueResponse", "live-page") in methods
    body_call = [item for item in feed.commands if item["method"] == "Fetch.getResponseBody"][-1]
    feed.handle_message(
        {
            "id": body_call["id"],
            "sessionId": "live-page",
            "result": {"body": '{"sports":{"1":{"categories":{}}}}', "base64Encoded": False},
        }
    )
    captured = feed.take()
    assert captured[0]["lane"] == "live"
    assert captured[0]["url"] == url


def test_blank_iframe_keeps_its_parent_lane_and_a_body_is_captured():
    feed = CdpFrameFeed()
    feed._session_lane["parent"] = "prematch"
    feed.handle_message(
        {
            "method": "Target.attachedToTarget",
            "sessionId": "parent",
            "params": {
                "sessionId": "iframe",
                "targetInfo": {"type": "iframe", "url": "about:blank"},
            },
        }
    )
    assert feed._session_lane["iframe"] == "prematch"
    url = (
        "https://api-onwin-tr--prd--sb.538.lol/rpc/"
        "sumstats.frontserver.command.get_main_line.erisgaming"
    )
    feed.handle_message(
        {
            "method": "Network.responseReceived",
            "sessionId": "iframe",
            "params": {"requestId": "9", "response": {"url": url, "status": 200}},
        }
    )
    feed.handle_message(
        {
            "method": "Network.loadingFinished",
            "sessionId": "iframe",
            "params": {"requestId": "9"},
        }
    )
    body_call = [item for item in feed.commands if item["method"] == "Network.getResponseBody"]
    assert body_call and body_call[-1]["sessionId"] == "iframe"
    feed.handle_message(
        {
            "id": body_call[-1]["id"],
            "sessionId": "iframe",
            "result": {"body": '{"sports":{"1":{}}}', "base64Encoded": False},
        }
    )
    captured = feed.take()
    assert captured[0]["lane"] == "prematch"
    assert captured[0]["raw"] == {"sports": {"1": {}}}
    assert url in feed.take_noticed()
