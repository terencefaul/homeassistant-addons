"""Human duration parsing, shared by the bot and the API."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"^\s*(\d+)\s*([smhd])?\s*$", re.I)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class DurationError(ValueError):
    pass


def parse(text: str) -> int:
    """'30m' -> 1800. A bare number is minutes."""
    m = _PATTERN.match(text or "")
    if not m:
        raise DurationError(f"'{text}' is not a duration. Try 30m, 2h or 1d.")
    value = int(m.group(1))
    unit = (m.group(2) or "m").lower()
    seconds = value * _UNITS[unit]
    if seconds < 60:
        raise DurationError("Minimum is 1 minute.")
    if seconds > 30 * 86400:
        raise DurationError("Maximum is 30 days.")
    return seconds


def humanise(seconds: int) -> str:
    if seconds <= 0:
        return "expired"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")
    return " ".join(parts) or "<1m"
