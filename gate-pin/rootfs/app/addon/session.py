"""Guest session cookie.

Its only job is to save re-typing the credential for every tap. It grants
nothing the credential does not still grant: every action re-reads the grant
and re-checks the window and revocation, so revoking is immediate even for a
tab that is already open.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Optional

from gate_pin.clock import now

COOKIE_NAME = "gp_session"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue(secret: bytes, grant_id: str, expires_at: int) -> str:
    payload = json.dumps(
        {"g": grant_id, "e": int(expires_at)}, separators=(",", ":")
    ).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def read(secret: bytes, cookie: Optional[str]) -> Optional[str]:
    """Return the grant id if the cookie is intact and unexpired, else None."""
    if not cookie or "." not in cookie:
        return None
    try:
        raw, sig = cookie.split(".", 1)
        payload = _unb64(raw)
        expected = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig)):
            return None
        data = json.loads(payload)
    except Exception:
        return None
    if int(data.get("e", 0)) <= now():
        return None
    gid = data.get("g")
    return gid if isinstance(gid, str) and gid else None
