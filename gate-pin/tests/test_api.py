"""API-level tests.

These cover the failure paths, not the happy path. The happy path passing is
not evidence that this system is safe.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from addon import routes_admin, routes_guest
from addon.deps import Deps
from addon.options import Options
from gate_pin import grants as g
from gate_pin.clock import now
from gate_pin.ratelimit import RateLimiter
from gate_pin.store import Store, load_or_create_secret


class FakeHA:
    """Stands in for Home Assistant. `fail` makes every call fail the way a
    dead gate would."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.fail = False

    async def states(self):
        return [
            {"entity_id": "cover.driveway", "state": "closed", "attributes": {"friendly_name": "Driveway"}},
            {"entity_id": "light.porch", "state": "off", "attributes": {"friendly_name": "Porch"}},
            {"entity_id": "camera.gate", "state": "idle", "attributes": {"friendly_name": "Gate cam"}},
        ]

    async def state(self, entity_id):
        return {"entity_id": entity_id, "state": "closed", "attributes": {}}

    async def call_intent(self, entity_id, intent):
        from gate_pin.ha import HAError
        from gate_pin import policy

        policy.resolve_service(entity_id, intent)
        if self.fail:
            raise HAError("gate did not answer")
        self.calls.append((entity_id, intent))

    async def camera_snapshot(self, entity_id):
        return b"\xff\xd8\xff", "image/jpeg"

    async def notify(self, *a, **k):
        return None

    async def persistent_notification(self, *a, **k):
        return None

    async def aclose(self):
        return None


@pytest.fixture()
def ctx(tmp_path):
    secret = load_or_create_secret(tmp_path / "secret.key")
    store = Store(tmp_path / "t.db", secret)
    ha = FakeHA()
    opts = Options(external_base_url="https://gate.example", require_cf_header=True)
    app = FastAPI()
    app.include_router(routes_guest.router)
    app.include_router(routes_admin.router)
    app.state.deps = Deps(
        store=store, secret=secret, ha=ha,
        limiter=RateLimiter(global_budget=50), options=opts, bot_status={},
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client, store, ha
    store.close()


def mint(store, entities=("cover.driveway",), kinds=("pin", "token"), **kw):
    return g.mint(
        store, label="t", entities=list(entities),
        valid_from=kw.get("valid_from", now() - 1),
        valid_until=kw.get("valid_until", now() + 3600),
        kinds=kinds,
    )


CF = {"CF-Connecting-IP": "203.0.113.9"}
INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/abc"}


# ---- the guest page GET must be inert ------------------------------------

def test_no_get_endpoint_can_act(ctx):
    """Messengers fetch URLs to build link previews. If a GET could open the
    gate, sending someone the link would open it."""
    client, store, ha = ctx
    r = mint(store)
    for path in (f"/g/{r.token}", "/", f"/?p={r.pin}"):
        client.get(path, headers={**CF, "User-Agent": "TelegramBot (like TwitterBot)"})
    assert ha.calls == []
    # And the credential is still usable afterwards -- nothing was consumed.
    assert client.post("/api/guest/redeem", json={"credential": r.token}, headers=CF).status_code == 200


def test_only_post_routes_exist_under_guest_api(ctx):
    client, _, _ = ctx
    routes = {
        (r.path, tuple(sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS"))))
        for r in client.app.routes if getattr(r, "path", "").startswith("/api/guest")
    }
    acting = {p for p, methods in routes if "GET" in methods}
    assert acting <= {"/api/guest/state", "/api/guest/branding"}, "a GET route must never act"


# ---- request validation ---------------------------------------------------

def test_extra_body_fields_are_rejected_at_the_boundary(ctx):
    """Pydantic extra='forbid' is why FastAPI was chosen: this is a type-level
    guarantee, not a rule someone has to remember."""
    client, store, ha = ctx
    r = mint(store)
    client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF)
    for payload in (
        {"entity_id": "cover.driveway", "intent": "open", "service": "homeassistant.restart"},
        {"entity_id": "cover.driveway", "intent": "open", "service_data": {"x": 1}},
        {"entity_id": ["cover.driveway"], "intent": "open"},
        {"entity_id": "cover.driveway", "intent": "lock"},
        {"entity_id": "cover.driveway", "intent": "open", "extra": True},
    ):
        resp = client.post("/api/guest/act", json=payload, headers=CF)
        assert resp.status_code == 422, payload
    assert ha.calls == []


def test_lock_entity_cannot_be_locked(ctx):
    client, store, ha = ctx
    r = mint(store, entities=("lock.front",))
    client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF)
    assert client.post("/api/guest/act", json={"entity_id": "lock.front", "intent": "lock"}, headers=CF).status_code == 422
    assert client.post("/api/guest/act", json={"entity_id": "lock.front", "intent": "open"}, headers=CF).status_code == 200
    assert ha.calls == [("lock.front", "open")]


# ---- authorisation --------------------------------------------------------

def test_a_session_cannot_reach_another_grants_entity(ctx):
    """The 0.1.33 bug class. Permanent regression test."""
    client, store, ha = ctx
    a = mint(store, entities=("cover.driveway",))
    mint(store, entities=("light.porch",))
    client.post("/api/guest/redeem", json={"credential": a.pin}, headers=CF)
    resp = client.post("/api/guest/act", json={"entity_id": "light.porch", "intent": "on"}, headers=CF)
    assert resp.status_code == 403
    assert ha.calls == []
    assert any(e["event"] == "denied" for e in store.audit())


def test_camera_is_never_actionable_or_visible_to_a_guest(ctx):
    client, store, ha = ctx
    r = mint(store, entities=("cover.driveway", "camera.gate"))
    body = client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF).json()
    assert [e["entity_id"] for e in body["entities"]] == ["cover.driveway"]
    # The camera IS attached to this grant, and "open" is a valid intent in the
    # global vocabulary, so the request shape is legal. It is refused at the
    # authorisation layer instead: cameras are never actuated by a guest.
    assert client.post("/api/guest/act", json={"entity_id": "camera.gate", "intent": "open"}, headers=CF).status_code == 403
    assert ha.calls == []


def test_revocation_takes_effect_in_an_already_open_session(ctx):
    client, store, ha = ctx
    r = mint(store)
    client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF)
    assert client.post("/api/guest/act", json={"entity_id": "cover.driveway", "intent": "open"}, headers=CF).status_code == 200
    store.revoke_grant(r.grant.id)
    # The cookie is still valid on its own terms; the grant is re-read anyway.
    assert client.post("/api/guest/act", json={"entity_id": "cover.driveway", "intent": "open"}, headers=CF).status_code == 401
    assert client.get("/api/guest/state", headers=CF).status_code == 401


def test_expiry_is_enforced_server_side(ctx):
    client, store, ha = ctx
    r = mint(store)
    client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF)
    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, r.grant.id))
    assert client.post("/api/guest/act", json={"entity_id": "cover.driveway", "intent": "open"}, headers=CF).status_code == 401


def test_acting_without_a_session_is_refused(ctx):
    client, store, ha = ctx
    mint(store)
    assert client.post("/api/guest/act", json={"entity_id": "cover.driveway", "intent": "open"}, headers=CF).status_code == 401
    assert ha.calls == []


# ---- distinct failure messages -------------------------------------------

def test_every_redemption_failure_has_its_own_message(ctx):
    client, store, _ = ctx
    seen = {}

    seen["unknown"] = client.post("/api/guest/redeem", json={"credential": "000000"}, headers=CF).json()["detail"]

    later = mint(store, valid_from=now() + 600, valid_until=now() + 1200)
    seen["scheduled"] = client.post("/api/guest/redeem", json={"credential": later.pin}, headers=CF).json()["detail"]

    gone = mint(store)
    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, gone.grant.id))
    seen["expired"] = client.post("/api/guest/redeem", json={"credential": gone.pin}, headers=CF).json()["detail"]

    killed = mint(store)
    store.revoke_grant(killed.grant.id)
    seen["revoked"] = client.post("/api/guest/redeem", json={"credential": killed.pin}, headers=CF).json()["detail"]

    assert len(set(seen.values())) == 4, f"messages collapsed: {seen}"


def test_a_not_yet_active_credential_comes_back_with_its_window(ctx):
    """The holder has proved possession -- the only thing missing is the time.
    Without the window the page can only say no, and a link-only guest has no
    code to type into the box it would otherwise be shown."""
    client, store, _ = ctx
    later = mint(store, valid_from=now() + 600, valid_until=now() + 1200)
    r = client.post("/api/guest/redeem", json={"credential": later.pin}, headers=CF)
    assert r.status_code == 401
    body = r.json()

    # detail stays a plain string: it is what the visitor reads.
    assert isinstance(body["detail"], str)
    st = body["status"]
    assert st["outcome"] == "scheduled"
    assert st["starts_at"] == later.grant.valid_from
    assert st["expires_at"] == later.grant.valid_until
    # The countdown is anchored to the server, not the visitor's phone clock.
    assert abs(st["now"] - now()) <= 5
    assert st["now"] < st["starts_at"]


def test_an_expired_credential_says_so_and_when_it_ran_out(ctx):
    """Same reasoning as the wait: a link-only guest has nothing to type, so
    the code box is the question restated rather than an answer."""
    client, store, _ = ctx
    gone = mint(store)
    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, gone.grant.id))
    st = client.post(
        "/api/guest/redeem", json={"credential": gone.pin}, headers=CF
    ).json()["status"]
    assert st["outcome"] == "expired"
    assert st["expires_at"] == now() - 1


def test_a_revoked_credential_is_not_given_a_window_to_come_back_for(ctx):
    """valid_until on a revoked grant is the window it WOULD have had. Showing
    it would send someone back at a time the code is still dead."""
    client, store, _ = ctx
    killed = mint(store)
    store.revoke_grant(killed.grant.id)
    st = client.post(
        "/api/guest/redeem", json={"credential": killed.pin}, headers=CF
    ).json()["status"]
    assert st["outcome"] == "revoked"
    assert "expires_at" not in st and "starts_at" not in st


def test_a_credential_that_resolves_to_nothing_reveals_nothing(ctx):
    """A wrong code must not answer questions about grants that exist."""
    client, _, _ = ctx
    body = client.post("/api/guest/redeem", json={"credential": "000000"}, headers=CF).json()
    assert "status" not in body
    assert isinstance(body["detail"], str)


def test_a_dead_gate_is_reported_differently_from_a_wrong_code(ctx):
    """Without this the visitor is told 'wrong code' when the gate is simply
    unreachable, and you spend the evening re-minting credentials."""
    client, store, ha = ctx
    r = mint(store)
    client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF)
    ha.fail = True
    resp = client.post("/api/guest/act", json={"entity_id": "cover.driveway", "intent": "open"}, headers=CF)
    assert resp.status_code == 502
    assert "still valid" in resp.json()["detail"]
    assert any(e["event"] == "act_failed" for e in store.audit())


# ---- real IP / topology ---------------------------------------------------

def test_requests_without_the_cloudflare_header_are_refused(ctx):
    """Under the intended topology there is no legitimate request without it.
    This turns 'someone exposed 8888 on the LAN' from silent into loud."""
    client, store, _ = ctx
    r = mint(store)
    assert client.post("/api/guest/redeem", json={"credential": r.pin}).status_code == 421


def test_client_ip_recorded_is_the_cloudflare_one(ctx):
    client, store, _ = ctx
    r = mint(store)
    client.post("/api/guest/redeem", json={"credential": r.pin},
                headers={**CF, "X-Forwarded-For": "10.0.0.1"})
    assert store.audit(event="redeem_ok")[0]["client_ip"] == "203.0.113.9"


# ---- admin ----------------------------------------------------------------

def test_admin_routes_are_hidden_from_a_public_caller(ctx):
    client, store, _ = ctx
    assert client.get("/api/admin/grants", headers=CF).status_code == 404
    assert client.get("/api/admin/grants", headers=INGRESS).status_code == 200


def test_mint_returns_credentials_once_and_never_again(ctx):
    client, store, _ = ctx
    body = client.post("/api/admin/mint", headers=INGRESS, json={
        "label": "plumber", "entities": ["cover.driveway"], "duration_s": 3600,
    }).json()
    assert body["pin"] and body["link"].startswith("https://gate.example/g/")
    listed = client.get("/api/admin/grants", headers=INGRESS).json()["grants"]
    assert "pin" not in str(listed) or body["pin"] not in str(listed)


def test_extend_refuses_an_expired_grant(ctx):
    client, store, _ = ctx
    r = mint(store)
    assert client.post(f"/api/admin/grants/{r.grant.id}/extend", headers=INGRESS,
                       json={"additional_s": 3600}).status_code == 200
    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, r.grant.id))
    resp = client.post(f"/api/admin/grants/{r.grant.id}/extend", headers=INGRESS, json={"additional_s": 3600})
    assert resp.status_code == 409
    assert "Mint a new one" in resp.json()["detail"]


def test_camera_snapshot_is_admin_only(ctx):
    client, _, _ = ctx
    assert client.get("/api/admin/camera/camera.gate/snapshot", headers=INGRESS).status_code == 200
    assert client.get("/api/admin/camera/camera.gate/snapshot", headers=CF).status_code == 404
    assert client.get("/api/admin/camera/cover.driveway/snapshot", headers=INGRESS).status_code == 400


def test_health_reports_where_a_tunnel_should_point(ctx):
    """The hostname Supervisor assigns cannot be worked out from outside and
    differs between a repository install and a local one. Guessing it is the
    single most likely setup mistake, so the panel states it."""
    client, _, _ = ctx
    origin = client.get("/api/admin/health", headers=INGRESS).json()["tunnel_origin"]
    assert origin["url"].startswith("http://")
    assert origin["url"].endswith(":8888")
    assert origin["hostname"]
    assert origin["source"] in ("supervisor", "container hostname")


def test_reissue_gives_a_new_credential_and_kills_the_old_one(ctx):
    """"Send it again" cannot mean "show it again" -- only the keyed hash is
    stored. It means issuing another key to the same lock."""
    client, store, _ = ctx
    r = mint(store, kinds=("pin", "token"))
    old_pin, old_token, gid = r.pin, r.token, r.grant.id

    body = client.post(f"/api/admin/grants/{gid}/reissue", headers=INGRESS,
                       json={"kinds": ["token"]}).json()
    assert body["link"] and body["grant"]["id"] == gid

    new_token = body["link"].rsplit("/", 1)[-1]
    assert new_token != old_token
    # Same grant: same window, same entities, one revocation.
    assert body["grant"]["entities"] == list(r.grant.entities)
    assert body["grant"]["valid_until"] == r.grant.valid_until

    assert client.post("/api/guest/redeem", json={"credential": new_token}, headers=CF).status_code == 200
    assert client.post("/api/guest/redeem", json={"credential": old_token}, headers=CF).status_code == 401
    # The PIN was not re-issued, so it must be untouched.
    assert client.post("/api/guest/redeem", json={"credential": old_pin}, headers=CF).status_code == 200


def test_reissue_refuses_a_grant_that_is_no_longer_live(ctx):
    client, store, _ = ctx
    r = mint(store)
    store.revoke_grant(r.grant.id)
    resp = client.post(f"/api/admin/grants/{r.grant.id}/reissue", headers=INGRESS,
                       json={"kinds": ["token"]})
    assert resp.status_code == 409
    assert "mint a new one" in resp.json()["detail"]


def test_reissue_revocation_still_kills_every_credential(ctx):
    client, store, _ = ctx
    r = mint(store)
    body = client.post(f"/api/admin/grants/{r.grant.id}/reissue", headers=INGRESS,
                       json={"kinds": ["pin", "token"]}).json()
    store.revoke_grant(r.grant.id)
    assert client.post("/api/guest/redeem", json={"credential": body["pin"]}, headers=CF).status_code == 401


def test_a_preset_keeps_the_credentials_and_theme_it_was_saved_with(ctx):
    """The panel offers link-only presets, so the round trip has to preserve
    kinds -- a preset silently widened back to pin+token hands out a PIN the
    owner did not mean to create."""
    client, store, _ = ctx
    payload = {"name": "plumber", "entities": ["cover.driveway"], "duration_s": 7200,
               "theme": "warm", "kinds": ["token"]}
    assert client.post("/api/admin/presets", headers=INGRESS, json=payload).status_code == 200
    preset = client.get("/api/admin/presets", headers=INGRESS).json()["presets"][0]
    assert preset["kinds"] == ["token"] and preset["theme"] == "warm"

    # And minting from it produces a link and no PIN.
    r = g.mint(store, label=preset["name"], entities=preset["entities"],
               valid_from=now(), valid_until=now() + preset["duration_s"],
               theme=preset["theme"], kinds=preset["kinds"])
    assert r.pin is None and r.token


def test_a_preset_saved_without_a_theme_takes_the_branding_default(ctx):
    """presets.theme is NOT NULL. Passing the model's None straight through
    was a 500 waiting for the first client that omitted the field."""
    client, store, _ = ctx
    store.set_setting("default_theme", "contrast")
    payload = {"name": "plumber", "entities": ["cover.driveway"], "duration_s": 7200}
    assert client.post("/api/admin/presets", headers=INGRESS, json=payload).status_code == 200
    assert client.get("/api/admin/presets", headers=INGRESS).json()["presets"][0]["theme"] == "contrast"


# ---- branding, control page, owner actions --------------------------------


def test_minting_without_a_theme_uses_the_branding_default(ctx):
    """The Branding form wrote default_theme and this path never read it, so
    every panel-minted grant came out 'dark' regardless. The bot honoured it,
    which made the two paths disagree."""
    client, store, _ = ctx
    client.post("/api/admin/branding", headers=INGRESS,
                json={"accent": "#2563eb", "default_theme": "warm", "property_name": "Terica"})
    body = client.post("/api/admin/mint", headers=INGRESS, json={
        "label": "x", "entities": ["cover.driveway"], "duration_s": 3600,
    }).json()
    assert body["grant"]["theme"] == "warm"

    # An explicit theme still wins.
    body = client.post("/api/admin/mint", headers=INGRESS, json={
        "label": "x", "entities": ["cover.driveway"], "duration_s": 3600, "theme": "light",
    }).json()
    assert body["grant"]["theme"] == "light"


def test_guest_branding_carries_the_property_name(ctx):
    """It is rendered in the guest page header, so it has to reach the public
    endpoint -- unlike anything else on the branding record."""
    client, _, _ = ctx
    client.post("/api/admin/branding", headers=INGRESS,
                json={"accent": "#2563eb", "default_theme": "dark", "property_name": "Terica"})
    body = client.get("/api/guest/branding", headers=CF).json()
    assert body["property_name"] == "Terica"
    assert set(body) == {"accent", "has_logo", "property_name"}, "no admin data may leak here"


def test_the_control_page_is_admin_only(ctx):
    """It carries a camera, which is exactly what must never reach the public
    origin."""
    client, _, _ = ctx
    assert client.get("/api/admin/control", headers=CF).status_code == 404
    assert client.post("/api/admin/act", headers=CF,
                       json={"entity_id": "cover.driveway", "intent": "open"}).status_code == 404
    assert client.get("/api/admin/control", headers=INGRESS).status_code == 200


def test_the_page_is_one_ordered_list_of_blocks(ctx):
    """Cameras and controls interleave, so a camera can sit directly above the
    gate it looks at. Order is the list order and must survive verbatim."""
    client, _, _ = ctx
    layout = [
        {"type": "camera", "entity_id": "camera.gate"},
        {"type": "control", "entity_id": "cover.driveway"},
        {"type": "camera", "entity_id": "camera.drive"},
        {"type": "control", "entity_id": "light.porch"},
    ]
    client.post("/api/admin/control", headers=INGRESS, json={"items": layout})
    items = client.get("/api/admin/control", headers=INGRESS).json()["items"]
    assert [(i["type"], i["entity_id"]) for i in items] == [
        (i["type"], i["entity_id"]) for i in layout
    ]
    # Controls carry what it takes to render a control; cameras do not.
    control = items[1]
    assert control["intents"] == ["close", "open", "stop"] and control["actionable"]
    assert control["name"] == "Driveway"
    assert "intents" not in items[0] and items[0]["name"] == "Gate cam"


def test_the_same_camera_can_appear_more_than_once(ctx):
    """A camera above each of two gates it overlooks is a reasonable layout, so
    nothing should deduplicate it."""
    client, _, _ = ctx
    layout = [
        {"type": "camera", "entity_id": "camera.gate"},
        {"type": "control", "entity_id": "cover.driveway"},
        {"type": "camera", "entity_id": "camera.gate"},
        {"type": "control", "entity_id": "light.porch"},
    ]
    client.post("/api/admin/control", headers=INGRESS, json={"items": layout})
    items = client.get("/api/admin/control", headers=INGRESS).json()["items"]
    assert len(items) == 4


def test_both_older_config_shapes_are_lifted_forward(ctx):
    """A dropped setting is indistinguishable from one that never saved, so it
    would be reported as 'it forgot my cameras' rather than as an upgrade bug."""
    client, store, _ = ctx

    # The first shape: a single camera key.
    store.set_setting("control_page",
                      '{"camera": "camera.gate", "entities": ["cover.driveway"]}')
    items = client.get("/api/admin/control", headers=INGRESS).json()["items"]
    assert [(i["type"], i["entity_id"]) for i in items] == [
        ("camera", "camera.gate"), ("control", "cover.driveway"),
    ]

    # The second: cameras-then-controls.
    store.set_setting("control_page",
                      '{"cameras": ["camera.gate"], "entities": ["cover.driveway", "light.porch"]}')
    items = client.get("/api/admin/control", headers=INGRESS).json()["items"]
    assert [(i["type"], i["entity_id"]) for i in items] == [
        ("camera", "camera.gate"),
        ("control", "cover.driveway"),
        ("control", "light.porch"),
    ]


def test_control_config_rejects_a_non_camera_and_an_unexposable_entity(ctx):
    client, _, _ = ctx
    assert client.post("/api/admin/control", headers=INGRESS, json={
        "items": [{"type": "camera", "entity_id": "cover.driveway"}]
    }).status_code == 400
    assert client.post("/api/admin/control", headers=INGRESS, json={
        "items": [{"type": "control", "entity_id": "climate.lounge"}]
    }).status_code == 400
    assert client.post("/api/admin/control", headers=INGRESS, json={
        "items": [{"type": "wallpaper", "entity_id": "cover.driveway"}]
    }).status_code == 422


def test_an_entity_no_longer_in_home_assistant_is_flagged_not_hidden(ctx):
    """Silently dropping it would look like the page forgot the setting."""
    client, _, _ = ctx
    client.post("/api/admin/control", headers=INGRESS, json={"items": [
        {"type": "control", "entity_id": "cover.driveway"},
        {"type": "control", "entity_id": "switch.gone"},
    ]})
    body = client.get("/api/admin/control", headers=INGRESS).json()
    missing = {e["entity_id"]: e["missing"] for e in body["items"]}
    assert missing == {"cover.driveway": False, "switch.gone": True}


def test_owner_act_goes_through_the_same_policy_as_a_guest(ctx):
    """A second path to calling a service must not be the looser one."""
    client, store, ha = ctx
    assert client.post("/api/admin/act", headers=INGRESS,
                       json={"entity_id": "cover.driveway", "intent": "open"}).status_code == 200
    assert ha.calls == [("cover.driveway", "open")]

    # Locking a lock is refused for the owner exactly as it is for a guest.
    assert client.post("/api/admin/act", headers=INGRESS,
                       json={"entity_id": "lock.front", "intent": "lock"}).status_code == 422
    # A camera is never actuated.
    assert client.post("/api/admin/act", headers=INGRESS,
                       json={"entity_id": "camera.gate", "intent": "open"}).status_code == 403
    # And nothing extra in the body reaches Home Assistant.
    assert client.post("/api/admin/act", headers=INGRESS,
                       json={"entity_id": "cover.driveway", "intent": "open",
                             "service": "homeassistant.restart"}).status_code == 422
    assert ha.calls == [("cover.driveway", "open")]


def test_owner_actions_are_distinguishable_in_the_audit_log(ctx):
    client, store, ha = ctx
    client.post("/api/admin/act", headers=INGRESS,
                json={"entity_id": "cover.driveway", "intent": "open"})
    events = {e["event"] for e in store.audit()}
    assert "owner_act" in events and "act" not in events


def test_a_dead_gate_reports_differently_for_the_owner_too(ctx):
    client, store, ha = ctx
    ha.fail = True
    resp = client.post("/api/admin/act", headers=INGRESS,
                       json={"entity_id": "cover.driveway", "intent": "open"})
    assert resp.status_code == 502
    assert any(e["event"] == "owner_act_failed" for e in store.audit())


def test_the_entity_picker_filter_does_not_narrow_what_a_grant_can_reach(ctx):
    """picker_domains is a convenience. policy.py is the security boundary, and
    a grant already holding a filtered-out entity must keep working."""
    client, store, _ = ctx
    d = client.app.state.deps
    d.options.picker_domains = ["cover"]

    listed = {e["entity_id"] for e in client.get("/api/admin/entities", headers=INGRESS).json()["entities"]}
    assert "cover.driveway" in listed
    assert "light.porch" not in listed and "camera.gate" not in listed

    r = mint(store, entities=("light.porch",))
    client.post("/api/guest/redeem", json={"credential": r.pin}, headers=CF)
    assert client.post("/api/guest/act", headers=CF,
                       json={"entity_id": "light.porch", "intent": "on"}).status_code == 200


def test_the_logo_size_limit_says_the_actual_size(ctx):
    """The old message named a limit that did not match the code path and gave
    no clue how far over you were."""
    client, _, _ = ctx
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (3 * 1024 * 1024)
    resp = client.post("/api/admin/branding/logo", headers=INGRESS,
                       files={"file": ("logo.png", big, "image/png")})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "3072 KB" in detail and "2048 KB" in detail
