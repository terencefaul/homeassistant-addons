"""The public origin must never ship a service worker.

Unlike an ordinary bug this cannot be fixed forward: a service worker that
ships once keeps running on every device that registered it, including devices
that never come back to pick up a fix. So it is asserted twice -- once against
the source config, which always runs, and once against the built output.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"

SW_MARKERS = ("sw.js", "workbox", "serviceworker", "service-worker", "registerSW")


def test_guest_vite_config_does_not_reference_the_pwa_plugin():
    """The structural guard. A single shared config with a flag is how a
    service worker eventually reaches the public origin by accident."""
    text = (FRONTEND / "vite.guest.config.js").read_text().lower()
    code = "\n".join(l for l in text.splitlines() if not l.strip().startswith(("//", "*", "/*")))
    assert "vite-plugin-pwa" not in code
    assert "vitepwa" not in code


def test_admin_vite_config_does_have_the_pwa_plugin():
    """The asymmetry is deliberate, so assert the other half too -- otherwise
    deleting both plugins would leave this suite green."""
    text = (FRONTEND / "vite.admin.config.js").read_text()
    assert "vite-plugin-pwa" in text and "VitePWA" in text


@pytest.mark.skipif(not (DIST / "guest").exists(), reason="frontend not built")
def test_built_guest_bundle_contains_no_service_worker():
    files = [p.name.lower() for p in (DIST / "guest").rglob("*") if p.is_file()]
    assert not [f for f in files if any(m in f for m in SW_MARKERS)], files
    index = (DIST / "guest" / "index.html").read_text().lower()
    assert "serviceworker" not in index and "registersw" not in index


@pytest.mark.skipif(not (DIST / "guest").exists(), reason="frontend not built")
def test_built_guest_bundle_references_no_outside_host():
    """A request to any third-party host would carry a link token out in the
    Referer header. Everything is self-hosted, including fonts."""
    offenders = []
    for p in (DIST / "guest").rglob("*"):
        if p.is_file() and p.suffix in (".html", ".js", ".css"):
            text = p.read_text(errors="ignore")
            for marker in ("https://fonts.", "http://fonts.", "cdn.", "unpkg.com", "jsdelivr"):
                if marker in text:
                    offenders.append(f"{p.name}: {marker}")
    assert not offenders, offenders


@pytest.mark.skipif(not (DIST / "admin").exists(), reason="frontend not built")
def test_built_admin_bundle_does_have_a_service_worker():
    files = [p.name for p in (DIST / "admin").rglob("*") if p.is_file()]
    assert "sw.js" in files
    manifest = json.loads((DIST / "admin" / "manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone"


@pytest.mark.skipif(not (DIST / "admin").exists(), reason="frontend not built")
def test_the_qr_library_stays_out_of_the_public_bundle():
    """The QR code is an admin-only feature. Every kilobyte on the guest bundle
    is paid for on one bar of signal at a gate, and every dependency there is
    one more thing running on the public origin."""
    admin = " ".join(p.read_text(errors="ignore") for p in (DIST / "admin").rglob("*.js"))
    guest = " ".join(p.read_text(errors="ignore") for p in (DIST / "guest").rglob("*.js"))
    assert "getModuleCount" in admin, "the QR library should be in the admin bundle"
    assert "getModuleCount" not in guest
    assert "isDark" not in guest


@pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").exists(),
    reason="node or node_modules unavailable",
)
def test_the_generated_qr_decodes_back_to_the_link():
    """Runs the real generator and points a real decoder at the rendered
    symbol. A QR that renders but does not scan looks perfectly fine on screen
    and fails only when somebody is standing at the gate holding up a phone."""
    result = subprocess.run(
        ["node", "scripts/verify-qr.mjs"],
        cwd=FRONTEND, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "a real decoder reads it back verbatim" in result.stdout


@pytest.mark.skipif(not (DIST / "guest").exists(), reason="frontend not built")
def test_guest_asset_paths_are_absolute():
    """The guest page is served from the domain root but is ALSO reached at
    /g/<token>. A relative base makes the browser request /g/assets/... , which
    does not exist -- the page loads, renders nothing, and the only symptom is a
    blank screen or a 404 on an asset. Shipped once; caught by hand, not here."""
    html = (DIST / "guest" / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert refs, "no asset references found at all"
    relative = [r for r in refs if r.startswith("./") or (not r.startswith(("/", "http", "data:")))]
    assert not relative, (
        f"guest assets must be absolute so they resolve from /g/<token>: {relative}"
    )


@pytest.mark.skipif(not (DIST / "admin").exists(), reason="frontend not built")
def test_admin_asset_paths_are_relative():
    """The mirror image, and the reason the two configs are separate: Home
    Assistant ingress serves the admin panel under /api/hassio_ingress/<token>/,
    a prefix that changes. Absolute paths there would leave the ingress path and
    hit Home Assistant itself."""
    html = (DIST / "admin" / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    absolute = [r for r in refs if r.startswith("/")]
    assert not absolute, (
        f"admin assets must be relative to survive the ingress prefix: {absolute}"
    )


# ---- Tailwind sees frontend/shared/ ---------------------------------------
#
# The Vite root is each app's own folder, so Tailwind v4's automatic source
# detection never reaches ../shared -- and silently purged every class used
# only there. The guest page shipped with a full-size logo and buttons with no
# height or gaps, and nothing failed. Both halves are asserted: the @source
# directive that fixes it, and the built CSS that proves it worked.

SHARED_ONLY = {
    # BrandHeader's logo. Without it the logo renders at its natural size.
    "h-14": r".h-14",
    # EntityControl's action button. Without it the buttons collapse into a run.
    "min-h-[3.5rem]": r".min-h-\[3\.5rem\]",
}


@pytest.mark.parametrize("app", ["guest", "admin"])
def test_stylesheet_declares_the_shared_component_folder_as_a_source(app):
    css = (FRONTEND / app / "src" / "styles.css").read_text()
    assert "@source" in css and "shared" in css


@pytest.mark.parametrize("app", ["guest", "admin"])
def test_built_css_kept_the_classes_only_shared_components_use(app):
    if not (DIST / app).exists():
        pytest.skip("frontend not built")
    sheets = list((DIST / app / "assets").glob("*.css"))
    assert sheets, f"no stylesheet in dist/{app}"
    text = "\n".join(p.read_text() for p in sheets)
    missing = [name for name, selector in SHARED_ONLY.items() if selector not in text]
    assert not missing, f"purged from the {app} bundle: {missing}"
