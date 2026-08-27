"""Facts about this add-on that only Supervisor knows.

Supervisor-specific by nature, so it lives here rather than in gate_pin/.
"""

from __future__ import annotations

import socket
from typing import Optional

import httpx

from .token import supervisor_token

SELF_INFO_URL = "http://supervisor/addons/self/info"


async def hostname(timeout: float = 5.0) -> tuple[str, str]:
    """This container's hostname on the add-on network, and where it came from.

    That hostname is what a tunnel must target, and it cannot be worked out from
    outside -- Supervisor assigns it, and it differs between a repository
    install and a local one. Asking for it beats asking the operator to guess.

    Supervisor is authoritative. It sets the container hostname too, so
    socket.gethostname() is a good fallback when the API is unavailable (a local
    test run, a permissions change, a Supervisor version that moves the route).
    """
    token = supervisor_token()
    if token:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    SELF_INFO_URL, headers={"Authorization": f"Bearer {token}"}
                )
                r.raise_for_status()
                name = (r.json().get("data") or {}).get("hostname")
                if name:
                    return name, "supervisor"
        except Exception:
            pass

    name = socket.gethostname()
    return name, "container hostname"


async def tunnel_origin(port: int = 8888) -> dict[str, Optional[str]]:
    """The URL to give a Cloudflare Tunnel as this add-on's service."""
    name, source = await hostname()
    return {
        "hostname": name,
        "source": source,
        "url": f"http://{name}:{port}",
    }
