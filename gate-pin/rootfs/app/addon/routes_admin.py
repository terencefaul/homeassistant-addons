"""Admin API.

Reached only through Home Assistant ingress, which authenticates the caller
before the request arrives -- so there is no login to build here. This is the
one thing the reference add-on got badly wrong: it served its admin panel on a
published port with no authentication at all.

Unreachable from the public port because nginx there proxies /api/guest/ and no
other prefix. require_ingress is a second line, not the first.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from gate_pin import grants as g
from gate_pin import policy
from gate_pin.clock import now
from gate_pin.credentials import generate_id
from gate_pin.ha import HAError
from gate_pin.store import Grant

from . import supervisor
from .deps import deps, require_ingress
from .schemas import (
    BrandingRequest,
    ControlConfigRequest,
    ExtendRequest,
    MintRequest,
    OwnerActRequest,
    PresetRequest,
    ReissueRequest,
    ReorderRequest,
)

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_ingress)]
)

MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}


def _grant_json(grant: Grant) -> dict:
    return {
        "id": grant.id,
        "label": grant.label,
        "created_at": grant.created_at,
        "valid_from": grant.valid_from,
        "valid_until": grant.valid_until,
        "theme": grant.theme,
        "revoked_at": grant.revoked_at,
        "entities": list(grant.entities),
        "kinds": list(grant.kinds),
        "status": grant.status(),
    }


@router.get("/entities")
async def entities(request: Request):
    d = deps(request)
    try:
        raw = await d.ha.states()
    except HAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Convenience filter only. policy.is_selectable is still the security
    # boundary; narrowing this option does not narrow what a grant may reach.
    allowed = set(d.options.picker_domains or [])
    out = []
    for s in raw:
        eid = s.get("entity_id", "")
        if not policy.is_selectable(eid):
            continue
        if allowed and policy.domain_of(eid) not in allowed:
            continue
        out.append(
            {
                "entity_id": eid,
                "domain": policy.domain_of(eid),
                "name": (s.get("attributes") or {}).get("friendly_name") or eid,
                "state": s.get("state"),
                "actionable": policy.is_actionable(eid),
                "admin_only": policy.domain_of(eid) in policy.ADMIN_ONLY_DOMAINS,
            }
        )
    out.sort(key=lambda e: (e["domain"], e["name"].lower()))
    return {"entities": out}


async def _mint(request: Request, *, label, entities_, duration_s, starts_in_s, theme, kinds):
    d = deps(request)
    if theme is None:
        # The same lookup the Telegram bot already does. Without this the
        # Branding form's theme setting had no effect on panel mints, and the
        # two paths disagreed.
        theme = await asyncio.to_thread(d.store.get_setting, "default_theme", "dark")
    start = now() + starts_in_s
    try:
        result = await asyncio.to_thread(
            g.mint,
            d.store,
            label=label,
            entities=entities_,
            valid_from=start,
            valid_until=start + duration_s,
            theme=theme,
            kinds=kinds,
            pin_length=d.options.pin_length,
            max_live_pin_grants=d.options.max_live_pin_grants,
        )
    except g.MintError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "grant": _grant_json(result.grant),
        # Shown exactly once. Nothing persists these and no endpoint can
        # return them again -- there is deliberately no "show the code again".
        "pin": result.pin,
        "link": result.link(d.options.external_base_url),
        "live_pin_grants": await asyncio.to_thread(d.store.live_pin_grant_count),
        "pin_cap": d.options.max_live_pin_grants,
    }


@router.post("/mint")
async def mint(body: MintRequest, request: Request):
    return await _mint(
        request,
        label=body.label,
        entities_=body.entities,
        duration_s=body.duration_s,
        starts_in_s=body.starts_in_s,
        theme=body.theme,
        kinds=body.kinds,
    )


@router.get("/grants")
async def list_grants(request: Request):
    d = deps(request)
    grants = await asyncio.to_thread(d.store.list_grants)
    return {
        "grants": [_grant_json(x) for x in grants],
        "live_pin_grants": await asyncio.to_thread(d.store.live_pin_grant_count),
        "pin_cap": d.options.max_live_pin_grants,
        "now": now(),
    }


@router.post("/grants/order")
async def order_grants(body: ReorderRequest, request: Request):
    d = deps(request)
    await asyncio.to_thread(d.store.reorder_grants, body.ids)
    return await list_grants(request)


@router.post("/grants/{grant_id}/revoke")
async def revoke(grant_id: str, request: Request):
    d = deps(request)
    ok = await asyncio.to_thread(d.store.revoke_grant, grant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="No such live grant")
    await asyncio.to_thread(d.store.log, "revoke", grant_id=grant_id)
    return {"ok": True}


@router.post("/grants/{grant_id}/extend")
async def extend(grant_id: str, body: ExtendRequest, request: Request):
    d = deps(request)
    grant = await asyncio.to_thread(d.store.get_grant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="No such grant")
    # Only a live grant. Reviving an expired one would mean a code still
    # sitting in someone's messages silently starts working again.
    if grant.status() != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Only a live grant can be extended (this one is {grant.status()}). Mint a new one.",
        )
    new_until = grant.valid_until + body.additional_s
    ok = await asyncio.to_thread(d.store.extend_grant, grant_id, new_until)
    if not ok:
        raise HTTPException(status_code=409, detail="Could not extend that grant")
    await asyncio.to_thread(
        d.store.log, "extend", grant_id=grant_id, detail=f"+{body.additional_s}s"
    )
    return {"ok": True, "valid_until": new_until}


@router.post("/grants/{grant_id}/reissue")
async def reissue(grant_id: str, body: ReissueRequest, request: Request):
    """Issue a fresh credential for an existing grant.

    A credential cannot be shown twice -- only its keyed hash is stored -- so
    re-sending means issuing another key to the same lock. The grant keeps its
    window, entities and single revocation.
    """
    d = deps(request)
    try:
        result = await asyncio.to_thread(
            g.reissue,
            d.store,
            grant_id,
            kinds=body.kinds,
            pin_length=d.options.pin_length,
            max_live_pin_grants=d.options.max_live_pin_grants,
        )
    except g.MintError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "grant": _grant_json(result.grant),
        "pin": result.pin,
        "link": result.link(d.options.external_base_url),
        "live_pin_grants": await asyncio.to_thread(d.store.live_pin_grant_count),
        "pin_cap": d.options.max_live_pin_grants,
    }


@router.get("/presets")
async def get_presets(request: Request):
    d = deps(request)
    return {"presets": await asyncio.to_thread(d.store.list_presets)}


@router.post("/presets")
async def save_preset(body: PresetRequest, request: Request):
    d = deps(request)
    for e in body.entities:
        if not policy.is_selectable(e):
            raise HTTPException(status_code=400, detail=f"{e} cannot be exposed")
    theme = body.theme or await asyncio.to_thread(
        d.store.get_setting, "default_theme", "dark"
    )
    await asyncio.to_thread(
        d.store.upsert_preset,
        preset_id=body.id or generate_id(),
        name=body.name,
        entities=body.entities,
        duration_s=body.duration_s,
        theme=theme,
        kinds=body.kinds,
    )
    return {"presets": await asyncio.to_thread(d.store.list_presets)}


@router.post("/presets/order")
async def order_presets(body: ReorderRequest, request: Request):
    d = deps(request)
    await asyncio.to_thread(d.store.reorder_presets, body.ids)
    return {"presets": await asyncio.to_thread(d.store.list_presets)}


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: str, request: Request):
    d = deps(request)
    if not await asyncio.to_thread(d.store.delete_preset, preset_id):
        raise HTTPException(status_code=404, detail="No such preset")
    return {"ok": True}


@router.get("/audit")
async def audit(request: Request, limit: int = 200, grant_id: str | None = None, event: str | None = None):
    d = deps(request)
    return {
        "entries": await asyncio.to_thread(
            d.store.audit, limit=limit, grant_id=grant_id, event=event
        )
    }


@router.get("/camera/{entity_id}/snapshot")
async def camera_snapshot(entity_id: str, request: Request):
    """Live camera view, admin only.

    Deliberately under /api/admin/ so nginx never serves it on the public port.
    A camera on the guest origin is out of scope by design, not by omission.
    """
    d = deps(request)
    if policy.domain_of(entity_id) != "camera":
        raise HTTPException(status_code=400, detail="Not a camera entity")
    try:
        content, ctype = await d.ha.camera_snapshot(entity_id)
    except HAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=ctype,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ---- the owner's own control page ----------------------------------------

CONTROL_KEY = "control_page"


def _control_config(raw: str) -> list[dict]:
    """Read the stored page config as an ordered list of blocks.

    Two older shapes are lifted forward rather than discarded -- a dropped
    setting is indistinguishable from one that never saved, so it would be
    reported as "it forgot my cameras" rather than as an upgrade bug:

      {"camera": "camera.x", "entities": [...]}   the first shape
      {"cameras": [...], "entities": [...]}       cameras-then-controls
    """
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    items = []
    for it in data.get("items") or []:
        if (
            isinstance(it, dict)
            and it.get("type") in ("camera", "control")
            and isinstance(it.get("entity_id"), str)
        ):
            items.append({"type": it["type"], "entity_id": it["entity_id"]})
    if items:
        return items

    cameras = [c for c in (data.get("cameras") or []) if isinstance(c, str)]
    if not cameras and isinstance(data.get("camera"), str) and data["camera"]:
        cameras = [data["camera"]]
    return (
        [{"type": "camera", "entity_id": c} for c in cameras]
        + [
            {"type": "control", "entity_id": e}
            for e in (data.get("entities") or [])
            if isinstance(e, str)
        ]
    )


@router.get("/control")
async def get_control(request: Request):
    """The owner's control page: a camera and an ordered list of entities.

    Behind ingress like everything else here, which is what keeps a live camera
    feed off the public guest origin.
    """
    d = deps(request)
    cfg = _control_config(await asyncio.to_thread(d.store.get_setting, CONTROL_KEY, ""))

    states: dict[str, dict] = {}
    try:
        for raw in await d.ha.states():
            states[raw.get("entity_id", "")] = raw
    except HAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    items = []
    for it in cfg:
        eid = it["entity_id"]
        raw = states.get(eid)
        block = {
            "type": it["type"],
            "entity_id": eid,
            "name": ((raw or {}).get("attributes") or {}).get("friendly_name") or eid,
            # Flagged rather than hidden: silently dropping it would look like
            # the page forgot the setting.
            "missing": raw is None,
        }
        if it["type"] == "control":
            block.update({
                "domain": policy.domain_of(eid),
                "state": (raw or {}).get("state"),
                "intents": policy.intents_for(eid),
                "actionable": policy.is_actionable(eid),
            })
        items.append(block)

    return {"items": items}


@router.post("/control")
async def set_control(body: ControlConfigRequest, request: Request):
    d = deps(request)
    for it in body.items:
        if it.type == "camera":
            if policy.domain_of(it.entity_id) != "camera":
                raise HTTPException(
                    status_code=400, detail=f"{it.entity_id} is not a camera entity"
                )
        elif not policy.is_selectable(it.entity_id):
            raise HTTPException(
                status_code=400, detail=f"{it.entity_id} cannot be exposed"
            )
    await asyncio.to_thread(
        d.store.set_setting,
        CONTROL_KEY,
        # Order is the list order. No sort key to drift out of sync.
        json.dumps({"items": [it.model_dump() for it in body.items]}),
    )
    return {"ok": True}


@router.post("/act")
async def owner_act(body: OwnerActRequest, request: Request):
    """Operate an entity as the owner.

    A second path to calling a Home Assistant service, so it goes through the
    same policy.resolve_service as the guest path -- it must not be the looser
    one. It is audited as its own event so owner actions stay distinguishable
    from a guest's in the log.
    """
    d = deps(request)
    try:
        domain, service = policy.resolve_service(body.entity_id, body.intent)
    except policy.PolicyError as exc:
        await asyncio.to_thread(
            d.store.log, "denied", entity_id=body.entity_id, detail=f"owner: {exc}"
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        await d.ha.call_intent(body.entity_id, body.intent)
    except HAError as exc:
        await asyncio.to_thread(
            d.store.log,
            "owner_act_failed",
            entity_id=body.entity_id,
            service=f"{domain}.{service}",
            detail=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="That didn't respond.") from exc

    await asyncio.to_thread(
        d.store.log, "owner_act", entity_id=body.entity_id, service=f"{domain}.{service}"
    )
    return {"ok": True, "entity_id": body.entity_id, "intent": body.intent}


@router.get("/branding")
async def get_branding(request: Request):
    d = deps(request)
    return {
        "accent": await asyncio.to_thread(d.store.get_setting, "accent", "#22c55e"),
        "default_theme": await asyncio.to_thread(d.store.get_setting, "default_theme", "dark"),
        "logo": await asyncio.to_thread(d.store.get_setting, "logo", ""),
        "property_name": await asyncio.to_thread(d.store.get_setting, "property_name", ""),
        "max_logo_kb": MAX_LOGO_BYTES // 1024,
    }


@router.post("/branding")
async def set_branding(body: BrandingRequest, request: Request):
    d = deps(request)
    await asyncio.to_thread(d.store.set_setting, "accent", body.accent)
    await asyncio.to_thread(d.store.set_setting, "default_theme", body.default_theme)
    await asyncio.to_thread(d.store.set_setting, "property_name", body.property_name.strip())
    return {"ok": True}


@router.post("/branding/logo")
async def upload_logo(request: Request, file: UploadFile = File(...)):
    d = deps(request)
    if file.content_type not in LOGO_TYPES:
        raise HTTPException(status_code=400, detail="Use a PNG, JPEG, SVG or WebP image")
    data = await file.read()
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"That image is {len(data) // 1024} KB. The limit is "
                   f"{MAX_LOGO_BYTES // 1024} KB — scale it down and try again.",
        )
    ext = LOGO_TYPES[file.content_type]
    target = Path(d.options.branding_dir) / f"logo{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    for old in Path(d.options.branding_dir).glob("logo.*"):
        old.unlink(missing_ok=True)
    target.write_bytes(data)
    # Served from the add-on itself. Never hotlinked: a third-party asset on
    # the guest page would carry the link token out in the Referer header.
    await asyncio.to_thread(d.store.set_setting, "logo", target.name)
    return {"ok": True, "logo": target.name}


@router.delete("/branding/logo")
async def delete_logo(request: Request):
    d = deps(request)
    for old in Path(d.options.branding_dir).glob("logo.*"):
        old.unlink(missing_ok=True)
    await asyncio.to_thread(d.store.set_setting, "logo", "")
    return {"ok": True}


@router.get("/health")
async def health(request: Request):
    d = deps(request)
    ha_ok = True
    ha_detail = ""
    try:
        await d.ha.state("sun.sun")
    except HAError as exc:
        ha_ok = False
        ha_detail = str(exc)[:200]
    return {
        "home_assistant": {"ok": ha_ok, "detail": ha_detail},
        # What a tunnel must point at. Supervisor assigns this and it differs
        # between a repository install and a local one, so it is shown here
        # rather than left for the operator to guess.
        "tunnel_origin": await supervisor.tunnel_origin(),
        # A silently dead bot is discovered when someone is standing at the
        # gate, so it has to be visible here.
        "telegram": d.bot_status,
        "rate_limiter": d.limiter.snapshot(),
        "options": {
            "external_base_url": d.options.external_base_url,
            "pin_length": d.options.pin_length,
            "max_live_pin_grants": d.options.max_live_pin_grants,
            "require_cf_header": d.options.require_cf_header,
            "notify_service": d.options.notify_service or None,
        },
    }
