"""Public guest API.

Reachable from the internet. Everything here assumes an unauthenticated,
possibly hostile caller.

Note what is NOT here: any GET that serves the page. `/` and `/g/<token>` are
served as static files by nginx and never reach application code at all, which
is the strongest available form of "a GET must never act". Telegram, WhatsApp
and every other messenger fetches URLs to build link previews; if a GET could
open the gate, sending someone the link would open it.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from gate_pin import grants as g
from gate_pin import policy
from gate_pin.clock import now
from gate_pin.ha import HAError

from . import session
from .deps import client_ip, deps
from .schemas import ActRequest, RedeemRequest

router = APIRouter(prefix="/api/guest", tags=["guest"])

# Every outcome gets its own message. If these collapse into one, an expired
# code, a scheduled code, a revoked code and a genuinely wrong code all look
# identical to the visitor -- and to you when they phone to say it did not work.
MESSAGES = {
    g.OUTCOME_UNKNOWN: "That code isn't recognised.",
    g.OUTCOME_SCHEDULED: "This code isn't active yet.",
    g.OUTCOME_EXPIRED: "This code has expired.",
    g.OUTCOME_REVOKED: "This code has been cancelled.",
}



def _looks_like(credential: str) -> str:
    return "pin" if credential.isdigit() and 6 <= len(credential) <= 10 else "token"


def _cookie(response: Response, value: str, max_age: int) -> None:
    response.set_cookie(
        session.COOKIE_NAME,
        value,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


async def _entity_view(d, grant) -> list[dict]:
    out = []
    for eid in grant.entities:
        if not policy.is_guest_visible(eid):
            continue  # cameras are admin-only and never rendered publicly
        state = None
        try:
            raw = await d.ha.state(eid)
            if raw:
                state = {
                    "state": raw.get("state"),
                    "name": (raw.get("attributes") or {}).get("friendly_name") or eid,
                }
        except HAError:
            state = None
        out.append(
            {
                "entity_id": eid,
                "domain": policy.domain_of(eid),
                "name": (state or {}).get("name") or eid,
                "state": (state or {}).get("state"),
                "intents": policy.intents_for(eid),
                "actionable": policy.is_actionable(eid),
            }
        )
    return out


@router.post("/redeem")
async def redeem(body: RedeemRequest, request: Request, response: Response):
    d = deps(request)
    ip = client_ip(request)

    probe = await asyncio.to_thread(d.store.resolve_credential, body.credential)
    # An unknown credential is charged to the budget it LOOKS like. Charging
    # every unknown to the PIN budget would let someone grind random tokens to
    # lock out PIN entry for real visitors -- a denial of service against the
    # channel that has no alternative.
    kind = probe[1] if probe else _looks_like(body.credential)

    decision = d.limiter.check(ip, kind)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again shortly.",
            headers={"Retry-After": str(max(1, decision.retry_after))},
        )

    result = await asyncio.to_thread(g.redeem, d.store, body.credential)

    if not result.ok:
        after = d.limiter.record_failure(ip, kind)
        await asyncio.to_thread(
            d.store.log,
            "redeem_fail",
            grant_id=result.grant.id if result.grant else None,
            kind=result.kind,
            client_ip=ip,
            detail=result.outcome,
        )
        if after.lockout:
            await asyncio.to_thread(d.store.log, "lockout", client_ip=ip, detail="pin budget exhausted")
            asyncio.create_task(_alert_lockout(d, ip))

        # `detail` stays a plain string for every outcome -- it is the one
        # thing the visitor reads, and several checks compare the four
        # messages for distinctness.
        payload: dict = {"detail": MESSAGES[result.outcome]}
        if result.outcome == g.OUTCOME_SCHEDULED and result.grant is not None:
            # The holder of a scheduled credential has proved possession; the
            # only thing they are missing is the time. Telling them when turns
            # a dead end into a wait, and saves the phone call asking why the
            # link does not work.
            payload["schedule"] = {
                "label": result.grant.label,
                "theme": result.grant.theme,
                "starts_at": result.grant.valid_from,
                "expires_at": result.grant.valid_until,
                # The device clock is not trustworthy and this is a countdown.
                "now": now(),
            }
        return JSONResponse(status_code=401, content=payload)

    d.limiter.record_success(ip, kind)
    grant = result.grant
    assert grant is not None
    await asyncio.to_thread(
        d.store.log, "redeem_ok", grant_id=grant.id, kind=result.kind, client_ip=ip
    )

    _cookie(
        response,
        session.issue(d.secret, grant.id, grant.valid_until),
        max_age=max(1, grant.valid_until - now()),
    )
    return {
        "label": grant.label,
        "theme": grant.theme,
        "expires_at": grant.valid_until,
        "now": now(),
        "entities": await _entity_view(d, grant),
    }


async def _alert_lockout(d, ip: str) -> None:
    msg = (
        f"Repeated wrong PINs from {ip}. PIN entry is locked for a cooldown. "
        "Link credentials still work."
    )
    if d.options.notify_service:
        await d.ha.notify(d.options.notify_service, "Gate PIN: lockout", msg)
    else:
        await d.ha.persistent_notification("Gate PIN: lockout", msg)


def _session_grant(request: Request):
    d = deps(request)
    gid = session.read(d.secret, request.cookies.get(session.COOKIE_NAME))
    if not gid:
        raise HTTPException(status_code=401, detail="Enter your code again.")
    return d, gid


@router.get("/state")
async def state(request: Request):
    d, gid = _session_grant(request)
    grant = await asyncio.to_thread(d.store.get_grant, gid)
    # Re-checked on every request rather than trusting the cookie, so a
    # revocation takes effect in a tab that is already open.
    if grant is None or not grant.is_live:
        raise HTTPException(status_code=401, detail="This code is no longer valid.")
    return {
        "expires_at": grant.valid_until,
        "now": now(),
        "entities": await _entity_view(d, grant),
    }


@router.post("/act")
async def act(body: ActRequest, request: Request):
    d, gid = _session_grant(request)
    ip = client_ip(request)
    grant = await asyncio.to_thread(d.store.get_grant, gid)
    if grant is None or not grant.is_live:
        raise HTTPException(status_code=401, detail="This code is no longer valid.")

    # Scoped to THIS grant, not merely "some grant". The reference add-on
    # shipped a bug of exactly this shape (CHANGELOG 0.1.33).
    allowed = await asyncio.to_thread(d.store.grant_allows, grant.id, body.entity_id)
    if not allowed or not policy.is_guest_visible(body.entity_id):
        await asyncio.to_thread(
            d.store.log,
            "denied",
            grant_id=grant.id,
            entity_id=body.entity_id,
            client_ip=ip,
            detail="entity not on this grant",
        )
        raise HTTPException(status_code=403, detail="Not permitted.")

    try:
        domain, service = policy.resolve_service(body.entity_id, body.intent)
    except policy.PolicyError as exc:
        await asyncio.to_thread(
            d.store.log,
            "denied",
            grant_id=grant.id,
            entity_id=body.entity_id,
            client_ip=ip,
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail="Not permitted.") from exc

    try:
        await d.ha.call_intent(body.entity_id, body.intent)
    except HAError as exc:
        await asyncio.to_thread(
            d.store.log,
            "act_failed",
            grant_id=grant.id,
            entity_id=body.entity_id,
            service=f"{domain}.{service}",
            client_ip=ip,
            detail=str(exc)[:300],
        )
        # 502, and a message that is unmistakably not "wrong code". The
        # difference between "your code is wrong" and "the gate did not answer"
        # is a correctness requirement, not a nicety.
        raise HTTPException(
            status_code=502, detail="The gate didn't respond. Your code is still valid."
        ) from exc

    await asyncio.to_thread(
        d.store.log,
        "act",
        grant_id=grant.id,
        entity_id=body.entity_id,
        service=f"{domain}.{service}",
        client_ip=ip,
    )
    return {"ok": True, "entity_id": body.entity_id, "intent": body.intent}


@router.get("/branding")
async def branding(request: Request):
    d = deps(request)
    return {
        "accent": await asyncio.to_thread(d.store.get_setting, "accent", "#22c55e"),
        "has_logo": await asyncio.to_thread(d.store.get_setting, "logo", "") != "",
        "property_name": await asyncio.to_thread(d.store.get_setting, "property_name", ""),
    }
