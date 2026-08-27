import pytest

from gate_pin import policy


def test_lock_cannot_be_locked_only_unlocked():
    """A guest who can lock a door can lock someone out."""
    assert policy.resolve_service("lock.front", "open") == ("lock", "unlock")
    with pytest.raises(policy.PolicyError):
        policy.resolve_service("lock.front", "lock")
    assert "lock" not in policy.POLICY["lock"]


def test_camera_is_never_actuated_and_never_guest_visible():
    with pytest.raises(policy.PolicyError):
        policy.resolve_service("camera.driveway", "open")
    assert policy.is_selectable("camera.driveway")      # admin may attach it
    assert not policy.is_guest_visible("camera.driveway")  # guest never sees it


def test_unknown_domain_and_intent_are_refused():
    with pytest.raises(policy.PolicyError):
        policy.resolve_service("climate.lounge", "on")
    with pytest.raises(policy.PolicyError):
        policy.resolve_service("cover.gate", "explode")


def test_cover_intents():
    assert policy.resolve_service("cover.gate", "open") == ("cover", "open_cover")
    assert policy.resolve_service("cover.gate", "close") == ("cover", "close_cover")
    assert policy.intents_for("cover.gate") == ["close", "open", "stop"]
