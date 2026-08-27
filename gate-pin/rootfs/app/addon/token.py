"""Supervisor token access.

Kept in exactly one module so it is greppable, and so the guest request path
provably never touches it. gate_pin.ha takes a provider, not a token.

The token grants the FULL Home Assistant API and cannot be scoped --
homeassistant_api is all-or-nothing. That is the largest accepted risk in the
design, and the reason this is an add-on rather than an integration: at least
the token is a boundary, rather than the code already running inside Home
Assistant.
"""

from __future__ import annotations

import os


def supervisor_token() -> str:
    return os.environ.get("SUPERVISOR_TOKEN", "")


def has_token() -> bool:
    return bool(supervisor_token())
