#!/usr/bin/env bash
# Force Home Assistant to re-read its add-on repositories, then report what it
# thinks is installed and what is available.
#
#   export HA_URL=http://homeassistant.local:8123
#   export HA_TOKEN=...        # Profile > Security > Long-lived access tokens
#   ./scripts/ha-status.sh
#
# Supervisor caches the git clone of each add-on repository and only refreshes
# it periodically, so a push can take a while to show up as an Update button.
# This asks it to look now.
set -uo pipefail

if [ -z "${HA_URL:-}" ] || [ -z "${HA_TOKEN:-}" ]; then
  echo "Set HA_URL and HA_TOKEN first:"
  echo "  export HA_URL=http://homeassistant.local:8123"
  echo "  export HA_TOKEN=...   # Profile > Security > Long-lived access tokens"
  exit 1
fi

api() { curl -s -H "Authorization: Bearer ${HA_TOKEN}" "$@"; }

echo "Reloading the add-on store..."
CODE=$(curl -s -o /tmp/ha-reload.log -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${HA_TOKEN}" "${HA_URL%/}/api/hassio/store/reload")
if [ "${CODE}" = "200" ]; then
  echo "  done"
else
  echo "  store/reload returned ${CODE}; trying refresh_updates"
  curl -s -o /dev/null -X POST -H "Authorization: Bearer ${HA_TOKEN}" \
    "${HA_URL%/}/api/hassio/refresh_updates"
fi

echo
ADDONS_JSON=$(api "${HA_URL%/}/api/hassio/addons")
echo "${ADDONS_JSON}" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)["data"]["addons"]
except Exception:
    print("  Could not read the add-on list. Is HA_TOKEN a long-lived access token?")
    sys.exit(1)

rows = [a for a in data if "gate" in a["slug"] or "gate" in a["name"].lower()]
if not rows:
    print("  No Gate PIN add-on is installed.")
    sys.exit(0)

for a in rows:
    slug = a["slug"]
    # A repository add-on gets a hash prefix; a folder dropped in /addons gets
    # "local_". They are DIFFERENT add-ons to Supervisor, and only the
    # repository one can ever show an Update button.
    kind = "local folder (/addons)" if slug.startswith("local_") else "add-on repository"
    installed = a.get("version")
    latest = a.get("version_latest")
    print(f"  {a[\"name\"]}")
    print(f"    slug        {slug}   <- {kind}")
    print(f"    installed   {installed}")
    print(f"    available   {latest}")
    print(f"    state       {a.get(\"state\")}")
    if latest and installed != latest:
        print(f"    -> update to {latest} is available; the card should show it now")
    elif kind.startswith("local"):
        print("    -> local add-ons never show updates. Rebuild it, or install the")
        print("       repository copy instead and remove this one.")
    else:
        print("    -> up to date as far as Supervisor can see")
    print()
    print("  Point your tunnel at this add-on with:")
    print(f"    http://{slug.replace('_', '-')}:8888")
    print("    (confirm against the Hostname shown below, which comes from Supervisor)")
'

# The hostname Supervisor actually assigns is what cloudflared must target, and
# it is the one thing that cannot be worked out from the outside. Ask for it.
SLUG=$(echo "${ADDONS_JSON}" | python3 -c '
import json, sys
try:
    for a in json.load(sys.stdin)["data"]["addons"]:
        if "gate_pin" in a["slug"]:
            print(a["slug"]); break
except Exception:
    pass
')

if [ -n "${SLUG}" ]; then
  echo
  echo "Supervisor's own view of the add-on:"
  api "${HA_URL%/}/api/hassio/addons/${SLUG}/info" | python3 -c '
import json, sys
d = json.load(sys.stdin)["data"]
host = d.get("hostname")
print(f"  hostname     {host}")
print(f"  ingress      {d.get("ingress_url")}")
ports = d.get("network") or {}
print(f"  ports        {ports if ports else "none published (correct for a tunnel)"}")
print()
print("  Cloudflare Tunnel -> Public hostname -> Service URL:")
print(f"    http://{host}:8888")
print()
print("  Do NOT route 8099. That is the admin panel and Home Assistant already")
print("  protects it through ingress.")
'
fi
