import pytest

from gate_pin.duration import DurationError, humanise, parse


def test_units():
    assert parse("30m") == 1800
    assert parse("2h") == 7200
    assert parse("1d") == 86400
    assert parse("90") == 5400  # bare number is minutes


def test_bounds():
    with pytest.raises(DurationError):
        parse("10s")
    with pytest.raises(DurationError):
        parse("60d")
    with pytest.raises(DurationError):
        parse("soon")


def test_humanise():
    assert humanise(3600) == "1h"
    assert humanise(5400) == "1h 30m"
    assert humanise(0) == "expired"
