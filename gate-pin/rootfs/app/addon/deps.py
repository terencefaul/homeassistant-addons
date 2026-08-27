"""Shared runtime objects and the client-IP rule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

from gate_pin.ha import HomeAssistant
from gate_pin.ratelimit import RateLimiter
from gate_pin.store import Store

from .options import Options

CF_HEADER = "cf-connecting-ip"


@dataclass
class Deps:
    store: Store
    secret: bytes
    ha: HomeAssistant
    limiter: RateLimiter
    options: Options
    bot_status: dict


def deps(request: Request) -> Deps:
    return request.app.state.deps


def client_ip(request: Request) -> str:
    """The visitor's real address.

    Behind Cloudflare Tunnel, REMOTE_ADDR is the tunnel -- identical for every
    visitor. Cloudflare sets CF-Connecting-IP at the edge and overwrites
    whatever the client sent, so unlike X-Forwarded-For a client cannot forge
    it.

    That is true ONLY while port 8888 is unreachable except through
    cloudflared. Expose 8888 on the LAN and forging this header becomes
    trivial, and every limiter silently stops working while still appearing to
    work under test. `require_cf_header` turns that misconfiguration from
    silent into loud: under the intended topology there is no legitimate
    request without this header.
    """
    d = deps(request)
    header = request.headers.get(CF_HEADER)
    if header:
        return header.split(",")[0].strip()
    if d.options.require_cf_header:
        raise HTTPException(
            status_code=421,
            detail="This endpoint is only reachable through the configured tunnel.",
        )
    return request.client.host if request.client else "unknown"


def require_ingress(request: Request) -> None:
    """Defence in depth for admin routes.

    The real control is that nginx on the public port proxies /api/guest/ and
    no other prefix, so /api/admin/ is unreachable from outside regardless.
    This is a second line, not the first.
    """
    if request.headers.get("x-ingress-path") is not None:
        return
    if request.headers.get(CF_HEADER) is not None:
        raise HTTPException(status_code=404, detail="Not found")
