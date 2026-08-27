"""Credential generation.

A PIN and a link token are the same kind of thing -- a bearer credential,
looked up server-side, revocable, time-bounded -- but they sit at opposite ends
of the entropy/delivery trade-off.

A PIN is typed by someone standing at a gate, which caps it at ~6 digits, about
20 bits. It survives only because of rate limiting. A token is never typed, so
it can carry 192 bits, at which point guessing stops being a threat model.

Modelling them as one object would have given the link the token's silent leak
surface (history, referrers, preview fetchers) AND the PIN's tiny keyspace.
"""

from __future__ import annotations

import secrets

TOKEN_BYTES = 24  # 192 bits, url-safe base64 -> 32 characters


def generate_pin(length: int) -> str:
    if not 6 <= length <= 10:
        raise ValueError("pin length must be between 6 and 10")
    return "".join(secrets.choice("0123456789") for _ in range(length))


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def generate_id() -> str:
    """Short opaque identifier for logs and the admin UI.

    Not a credential and never used as one -- contrast the reference add-on,
    whose link id was mb_substr(md5(time()), 0, 6): time-seeded, and the only
    thing standing between a stranger and the gate.
    """
    return secrets.token_hex(4)
