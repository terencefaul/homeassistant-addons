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


def test_mint_from_preset(ctx):
    client, store, _ = ctx
    store.upsert_preset(preset_id="p1", name="plumber", entities=["cover.driveway"],
                        duration_s=7200, theme="dark", kinds=["token"])
    body = client.post("/api/admin/mint-preset", headers=INGRESS, json={"preset_id": "p1"}).json()
    assert body["pin"] is None and body["link"]
    assert body["grant"]["label"] == "plumber"
