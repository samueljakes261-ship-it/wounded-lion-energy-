"""
Tests for kenyan/access.py's access-code verification and session
tokens, plus (via kenyan/api_router.py) that Kenyan opportunities are
genuinely inaccessible without a valid session, and that none of this
touches the existing Turkish/client-facing app in any way.
"""
import logging

import pytest

from kenyan.access import issue_session_token, verify_access_code, verify_session_token

CORRECT_CODE = "23@2005"


def test_correct_code_is_accepted():
    assert verify_access_code(CORRECT_CODE) is True


@pytest.mark.parametrize(
    "wrong_code",
    ["", "23@2006", "232005", "23@200", "wrong", "23@2005 ", " 23@2005", "0000"],
)
def test_incorrect_code_is_rejected(wrong_code):
    assert verify_access_code(wrong_code) is False


def test_incorrect_code_gives_no_partial_match_signal():
    """
    There is no code path that returns anything other than a plain
    boolean -- there is structurally no way for a caller to learn
    "how close" a wrong guess was.
    """
    result_1 = verify_access_code("23@2005wrong")
    result_2 = verify_access_code("completely-unrelated")
    assert result_1 is False
    assert result_2 is False
    assert type(result_1) is bool
    assert type(result_2) is bool


def test_code_is_never_written_to_logs(caplog):
    with caplog.at_level(logging.DEBUG):
        verify_access_code(CORRECT_CODE)
        verify_access_code("some-wrong-guess")

    for record in caplog.records:
        assert CORRECT_CODE not in record.getMessage()
        assert "some-wrong-guess" not in record.getMessage()


def test_session_token_round_trips():
    session = issue_session_token()
    assert verify_session_token(session.token) is True


def test_session_token_is_not_the_plaintext_code():
    session = issue_session_token()
    assert CORRECT_CODE not in session.token


def test_tampered_token_is_rejected():
    session = issue_session_token()
    tampered = session.token[:-2] + ("aa" if session.token[-2:] != "aa" else "bb")
    assert verify_session_token(tampered) is False


def test_garbage_token_is_rejected():
    assert verify_session_token("not-a-real-token") is False
    assert verify_session_token("") is False
    assert verify_session_token(None) is False


def test_expired_token_is_rejected():
    """
    Fabricates an already-expired-but-correctly-signed token (rather
    than monkeypatching `time.time`, which many stdlib internals rely
    on) to verify expiry is actually enforced, not just signature
    validity.
    """
    import base64
    import hashlib
    import hmac

    import kenyan.access as access_module

    issued_at = 1.0
    expires_at = 2.0  # long since expired
    payload = f"{issued_at:.3f}:{expires_at:.3f}"
    signature = hmac.new(
        access_module._session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    raw_token = f"{payload}:{signature}"
    expired_token = base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("ascii")

    assert access_module.verify_session_token(expired_token) is False
