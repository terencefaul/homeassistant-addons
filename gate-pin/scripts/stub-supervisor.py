#!/usr/bin/env python3
"""A stand-in for the Home Assistant Supervisor API.

Lets the whole guest flow be exercised locally -- including actually operating
an "entity" -- without a Home Assistant instance. Runs as a container named
`supervisor` on the same Docker network, so the add-on's hardcoded
http://supervisor/core/api/ resolves to it with nothing changed.

Beyond the normal endpoints it exposes two control routes the smoke test uses:
  GET  /_calls  -- every service call received, for assertions
  POST /_fail   -- make every call fail, to exercise the "the gate didn't
                   respond" path, which must be distinguishable from a wrong code
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

STATES = {
    "cover.driveway": {"state": "closed", "attributes": {"friendly_name": "Driveway gate"}},
    "light.porch": {"state": "off", "attributes": {"friendly_name": "Porch light"}},
    "lock.front": {"state": "locked", "attributes": {"friendly_name": "Front door"}},
    "camera.gate": {"state": "idle", "attributes": {"friendly_name": "Gate camera"}},
    "sensor.temperature": {"state": "21.4", "attributes": {"friendly_name": "Outside"}},
    "climate.lounge": {"state": "heat", "attributes": {"friendly_name": "Lounge"}},
    "sun.sun": {"state": "above_horizon", "attributes": {}},
}

CALLS: list[dict] = []
FAIL = {"on": False}

# A generated placeholder frame, so the camera proxy returns a real image.
def _placeholder_png(w=320, h=180):
    import struct, zlib
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            band = (y // 12) % 2 == 0
            row += bytes((40, 40, 46) if band else (58, 58, 66))
        rows.append(bytes(row))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
        + chunk(b"IEND", b"")
    )


FRAME = _placeholder_png()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        p = self.path
        if p == "/_calls":
            return self._json(200, CALLS)
        if p == "/core/api/states":
            return self._json(200, [{"entity_id": k, **v} for k, v in STATES.items()])
        if p.startswith("/core/api/states/"):
            eid = p.rsplit("/", 1)[-1]
            if eid not in STATES:
                return self._json(404, {"message": "not found"})
            return self._json(200, {"entity_id": eid, **STATES[eid]})
        if p.startswith("/core/api/camera_proxy/"):
            return self._send(200, FRAME, "image/png")
        return self._json(404, {"message": "no"})

    def do_POST(self):
        p = self.path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if p == "/_fail":
            FAIL["on"] = not FAIL["on"]
            return self._json(200, {"failing": FAIL["on"]})
        if p.startswith("/core/api/services/"):
            domain, service = p[len("/core/api/services/"):].split("/", 1)
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
            if domain in ("notify", "persistent_notification"):
                CALLS.append({"domain": domain, "service": service, "data": body})
                return self._json(200, [])
            if FAIL["on"]:
                return self._json(500, {"message": "simulated failure"})
            CALLS.append({"domain": domain, "service": service, "data": body})
            eid = body.get("entity_id")
            if eid in STATES:
                # Reflect the change so live state on the guest page is real.
                STATES[eid]["state"] = {
                    "open_cover": "open", "close_cover": "closed",
                    "turn_on": "on", "turn_off": "off", "unlock": "unlocked",
                }.get(service, STATES[eid]["state"])
            return self._json(200, [])
        return self._json(404, {"message": "no"})


if __name__ == "__main__":
    print("stub supervisor listening on :80", flush=True)
    HTTPServer(("0.0.0.0", 80), Handler).serve_forever()
