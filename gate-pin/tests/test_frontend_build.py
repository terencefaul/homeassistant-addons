"""The public origin must never ship a service worker.

Unlike an ordinary bug this cannot be fixed forward: a service worker that
ships once keeps running on every device that registered it, including devices
that never come back to pick up a fix. So it is asserted twice -- once against
the source config, which always runs, and once against the built output.
"""

import json
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
