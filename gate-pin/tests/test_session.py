from addon import session
from gate_pin.clock import now

SECRET = b"x" * 48


def test_roundtrip():
    c = session.issue(SECRET, "abc123", now() + 60)
    assert session.read(SECRET, c) == "abc123"


def test_tampering_is_rejected():
    c = session.issue(SECRET, "abc123", now() + 60)
    payload, sig = c.split(".")
    assert session.read(SECRET, f"{payload}x.{sig}") is None
    assert session.read(SECRET, f"{payload}.{sig[:-2]}aa") is None


def test_a_different_secret_invalidates_every_session():
    c = session.issue(SECRET, "abc123", now() + 60)
    assert session.read(b"y" * 48, c) is None


def test_expired_cookie_is_rejected():
    assert session.read(SECRET, session.issue(SECRET, "abc123", now() - 1)) is None


def test_garbage_is_rejected_without_raising():
    for junk in ("", "nodot", "a.b", "....", "x" * 500):
        assert session.read(SECRET, junk) is None
