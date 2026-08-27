"""Import the real application object.

The rest of the suite builds its own FastAPI app from the routers, which is
fast and isolated -- but it meant addon/main.py was never imported, and a route
there with an unannotated Request parameter (so FastAPI would have treated it
as a query parameter) went unnoticed until a container smoke test. This closes
that gap.
"""

from addon.main import app


def route_map():
    out = {}
    for r in app.routes:
        path = getattr(r, "path", None)
        if path:
            out.setdefault(path, set()).update(
                m for m in getattr(r, "methods", set()) if m not in ("HEAD", "OPTIONS")
            )
    return out


def test_the_real_app_imports_and_registers_both_routers():
    paths = route_map()
    assert "/api/guest/redeem" in paths
    assert "/api/guest/act" in paths
    assert "/api/admin/mint" in paths
    assert "/api/guest/logo" in paths


def test_no_guest_route_accepts_a_get_that_could_act():
    """A GET must never be able to act. Messengers fetch URLs to build link
    previews, so a GET that opened the gate would open it when you sent the
    link."""
    acting = {
        p for p, methods in route_map().items()
        if p.startswith("/api/guest") and "GET" in methods
    }
    assert acting <= {"/api/guest/state", "/api/guest/branding", "/api/guest/logo"}


def test_every_route_parameter_is_resolvable():
    """A parameter FastAPI cannot classify becomes a silent query parameter.
    Building the OpenAPI schema forces it to resolve every one of them."""
    app.openapi_schema = None
    schema = app.openapi()
    logo = schema["paths"]["/api/guest/logo"]["get"]
    assert not logo.get("parameters"), (
        "unannotated handler arguments leak into the API as query parameters: "
        f"{logo.get('parameters')}"
    )


def test_docs_endpoints_are_disabled():
    paths = route_map()
    assert "/docs" not in paths and "/openapi.json" not in paths
