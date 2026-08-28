#!/usr/bin/env bash
# End-to-end smoke test against a real container, with a stubbed Supervisor API.
#
# Covers what unit tests cannot: the nginx port split, the security headers,
# startup ordering, and a full mint-then-redeem-then-act flow through both
# ports. Everything it asserts is a failure path someone would otherwise only
# discover in production.
#
#   ./scripts/smoke.sh            build and run
#   ./scripts/smoke.sh --no-build use the existing image
set -uo pipefail

IMAGE=gate-pin:smoke
NET=gate-pin-smoke-net
PLATFORM="${PLATFORM:-linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}"
case "${PLATFORM}" in
  linux/amd64) BASE=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 ;;
  *)           BASE=ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20 ;;
esac

cd "$(dirname "$0")/.."
PASS=0; FAIL=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then printf '  \033[32mok\033[0m   %-46s %s\n' "$1" "$3"; PASS=$((PASS+1))
  else printf '  \033[31mFAIL\033[0m %-46s got %s, want %s\n' "$1" "$3" "$2"; FAIL=$((FAIL+1)); fi
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

cleanup() {
  docker rm -f gate-pin-app gate-pin-supervisor >/dev/null 2>&1
  docker network rm "${NET}" >/dev/null 2>&1
  rm -rf "${DATA:-}" 2>/dev/null
}
trap cleanup EXIT

if [ "${1:-}" != "--no-build" ]; then
  echo "Building $IMAGE for ${PLATFORM}..."
  docker build --platform "${PLATFORM}" --build-arg BUILD_FROM="$BASE" -t "${IMAGE}" . >/dev/null || {
    echo "build failed"; exit 1; }
fi

DATA=$(mktemp -d)
cat > "$DATA/options.json" <<JSON
{"external_base_url":"https://gate.example","telegram_bot_token":"","telegram_chat_ids":[],
 "notify_service":"","pin_length":6,"max_live_pin_grants":20,
 "trusted_proxy_cidr":"172.30.32.0/23","audit_retention_days":90,"require_cf_header":true}
JSON

docker network create "${NET}" >/dev/null 2>&1
# Named `supervisor` so the add-on's hardcoded http://supervisor/core/api/ resolves.
docker run -d --name gate-pin-supervisor --network "${NET}" --network-alias supervisor \
  --platform "${PLATFORM}" -v "$PWD/scripts/stub-supervisor.py:/stub.py:ro" \
  -p 18081:80 python:3.12-alpine python3 /stub.py >/dev/null
docker run -d --name gate-pin-app --network "${NET}" --platform "${PLATFORM}" \
  -e SUPERVISOR_TOKEN=stub-token -v "$DATA:/data" \
  -p 18888:8888 -p 18099:8099 "${IMAGE}" >/dev/null

printf 'Waiting for the add-on...'
for _ in $(seq 1 60); do
  [ "$(code http://127.0.0.1:18099/api/admin/health -H 'X-Ingress-Path: /x')" = "200" ] && break
  printf '.'; sleep 1
done
echo

G=http://127.0.0.1:18888
A=http://127.0.0.1:18099
CF=(-H 'CF-Connecting-IP: 203.0.113.9')
IN=(-H 'X-Ingress-Path: /api/hassio_ingress/x')
J=(-H 'Content-Type: application/json')

echo
echo "Startup ordering - the first request must not be a 502"
check "guest page serves"                200 "$(code ${G}/)"
check "link path serves the same page"   200 "$(code ${G}/g/aaaaaaaaaaaaaaaaaaaaaaaa)"
check "API answers immediately"          401 "$(code -X POST "${J[@]}" "${CF[@]}" -d '{"credential":"999999"}' ${G}/api/guest/redeem)"

echo
echo "The link route must serve a page whose assets actually load"
# Asserting 200 on /g/<token> was not enough: the page returned 200 while its
# assets 404'd, so a visitor got a blank screen. Follow the references.
PAGE=$(curl -s ${G}/g/aaaaaaaaaaaaaaaaaaaaaaaa)
ASSETS=$(echo "${PAGE}" | grep -oE '(src|href)="[^"]+"' | sed 's/.*="//; s/"//' | grep -E '\.(js|css)$')
if [ -z "${ASSETS}" ]; then
  printf '  \033[31mFAIL\033[0m no asset references found on the link page\n'; FAIL=$((FAIL+1))
fi
for a in ${ASSETS}; do
  case "${a}" in
    /*) URL="${G}${a}" ;;
    *)  URL="${G}/g/${a#./}" ;;   # what a browser would actually resolve
  esac
  CT=$(curl -s -o /dev/null -w '%{content_type}' "${URL}")
  ST=$(curl -s -o /dev/null -w '%{http_code}' "${URL}")
  case "${a}" in
    *.js)  WANT=javascript ;;
    *.css) WANT=css ;;
  esac
  if [ "${ST}" = "200" ] && echo "${CT}" | grep -q "${WANT}"; then
    printf '  \033[32mok\033[0m   asset loads from /g/<token>%-19s %s\n' "" "${a}"; PASS=$((PASS+1))
  else
    printf '  \033[31mFAIL\033[0m asset %s -> %s %s (want 200 and %s)\n' "${a}" "${ST}" "${CT}" "${WANT}"; FAIL=$((FAIL+1))
  fi
done

echo
echo "Port split - the admin API must be unreachable from the public port"
for p in /api/admin/grants /api/admin/health /api/admin/audit /api/admin/control /api/; do
  check "public :8888 $p" 404 "$(code $G$p)"
done
# The owner control page carries a camera, and owner actions are a second path
# to calling a service. Both must be as unreachable here as everything else.
check "public :8888 POST /api/admin/act" 404 \
  "$(code -X POST "${J[@]}" "${CF[@]}" -d '{"entity_id":"cover.driveway","intent":"open"}' ${G}/api/admin/act)"
check "ingress :8099 /api/admin/grants"  200 "$(code "${IN[@]}" ${A}/api/admin/grants)"
check "ingress :8099 /api/admin/control" 200 "$(code "${IN[@]}" ${A}/api/admin/control)"

echo
echo "Security headers on the public origin"
H=$(curl -sI ${G}/)
for h in "Referrer-Policy: no-referrer" "X-Frame-Options: DENY" "X-Content-Type-Options: nosniff"; do
  echo "$H" | grep -qi "$h" && { printf '  \033[32mok\033[0m   %s\n' "$h"; PASS=$((PASS+1)); } \
                            || { printf '  \033[31mFAIL\033[0m missing %s\n' "$h"; FAIL=$((FAIL+1)); }
done

echo
echo "Real-IP requirement - a request that did not come through the tunnel"
check "no CF-Connecting-IP header"       421 "$(code -X POST "${J[@]}" -d '{"credential":"123456"}' ${G}/api/guest/redeem)"

echo
echo "Request validation - nothing from a body may reach Home Assistant"
for payload in '{"credential":"1","service":"homeassistant.restart"}' \
               '{"credential":"1","service_data":{"x":1}}' \
               '{"credential":["1"]}'; do
  check "rejected: ${payload:0:36}" 422 "$(code -X POST "${J[@]}" "${CF[@]}" -d "$payload" ${G}/api/guest/redeem)"
done

echo
echo "Mint through ingress, then use it on the public port"
MINT=$(curl -s -X POST "${J[@]}" "${IN[@]}" -d \
  '{"label":"smoke","entities":["cover.driveway","light.porch"],"duration_s":3600,"kinds":["pin","token"]}' \
  ${A}/api/admin/mint)
PIN=$(echo "$MINT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["pin"])' 2>/dev/null)
LINK=$(echo "$MINT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["link"])' 2>/dev/null)
TOKEN="${LINK##*/}"
check "mint returned a PIN"              6 "${#PIN}"
check "mint returned a link token"       32 "${#TOKEN}"

JAR=$(mktemp)
check "redeem the PIN"                   200 "$(code -c "$JAR" -X POST "${J[@]}" "${CF[@]}" -d "{\"credential\":\"$PIN\"}" ${G}/api/guest/redeem)"
check "open the gate"                    200 "$(code -b "$JAR" -X POST "${J[@]}" "${CF[@]}" -d '{"entity_id":"cover.driveway","intent":"open"}' ${G}/api/guest/act)"
check "the service call reached HA"      1 "$(curl -s http://127.0.0.1:18081/_calls | python3 -c 'import json,sys;print(sum(1 for c in json.load(sys.stdin) if c["service"]=="open_cover"))')"
check "an entity NOT on this grant"      403 "$(code -b "$JAR" -X POST "${J[@]}" "${CF[@]}" -d '{"entity_id":"lock.front","intent":"open"}' ${G}/api/guest/act)"
check "redeem the link token too"        200 "$(code -X POST "${J[@]}" "${CF[@]}" -d "{\"credential\":\"$TOKEN\"}" ${G}/api/guest/redeem)"

echo
echo "A dead gate must not look like a wrong code"
curl -s -X POST http://127.0.0.1:18081/_fail >/dev/null
check "act while HA is failing"          502 "$(code -b "$JAR" -X POST "${J[@]}" "${CF[@]}" -d '{"entity_id":"cover.driveway","intent":"open"}' ${G}/api/guest/act)"
MSG=$(curl -s -b "$JAR" -X POST "${J[@]}" "${CF[@]}" -d '{"entity_id":"cover.driveway","intent":"open"}' ${G}/api/guest/act | python3 -c 'import json,sys;print(json.load(sys.stdin)["detail"])')
echo "$MSG" | grep -qi "still valid" && { printf '  \033[32mok\033[0m   message says the code is still valid\n'; PASS=$((PASS+1)); } \
                                     || { printf '  \033[31mFAIL\033[0m message was: %s\n' "$MSG"; FAIL=$((FAIL+1)); }
curl -s -X POST http://127.0.0.1:18081/_fail >/dev/null

echo
echo "Revocation takes effect in a session that is already open"
GID=$(echo "$MINT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["grant"]["id"])')
curl -s -X POST "${IN[@]}" ${A}/api/admin/grants/${GID}/revoke >/dev/null
check "act after revoke"                 401 "$(code -b "$JAR" -X POST "${J[@]}" "${CF[@]}" -d '{"entity_id":"cover.driveway","intent":"open"}' ${G}/api/guest/act)"
check "the PIN no longer redeems"        401 "$(code -X POST "${J[@]}" "${CF[@]}" -d "{\"credential\":\"$PIN\"}" ${G}/api/guest/redeem)"
check "the link no longer redeems"       401 "$(code -X POST "${J[@]}" "${CF[@]}" -d "{\"credential\":\"$TOKEN\"}" ${G}/api/guest/redeem)"

echo
echo "Cameras are admin-only"
check "camera on the ingress port"       200 "$(code "${IN[@]}" ${A}/api/admin/camera/camera.gate/snapshot)"
check "camera on the public port"        404 "$(code ${G}/api/admin/camera/camera.gate/snapshot)"

echo
echo "Distinct messages for every redemption outcome"
python3 - "$A" <<'PYEOF'
import json, subprocess, sys, time
A = sys.argv[1]
IN = ["-H", "X-Ingress-Path: /x", "-H", "Content-Type: application/json"]
G = "http://127.0.0.1:18888/api/guest/redeem"
CF = ["-H", "CF-Connecting-IP: 198.51.100.7", "-H", "Content-Type: application/json"]

def post(url, data, extra):
    out = subprocess.run(["curl", "-s", "-X", "POST", *extra, "-d", json.dumps(data), url],
                         capture_output=True, text=True).stdout
    try: return json.loads(out)
    except Exception: return {}

msgs = {}
msgs["unknown"] = post(G, {"credential": "000000"}, CF).get("detail")
later = post(A + "/api/admin/mint", {"label": "later", "entities": ["cover.driveway"],
             "duration_s": 3600, "starts_in_s": 3600, "kinds": ["pin"]}, IN)
msgs["scheduled"] = post(G, {"credential": later["pin"]}, CF).get("detail")
short = post(A + "/api/admin/mint", {"label": "short", "entities": ["cover.driveway"],
             "duration_s": 60, "kinds": ["pin"]}, IN)
subprocess.run(["curl", "-s", "-X", "POST", *IN[:2],
                A + f"/api/admin/grants/{short['grant']['id']}/revoke"], capture_output=True)
msgs["revoked"] = post(G, {"credential": short["pin"]}, CF).get("detail")

distinct = len({m for m in msgs.values() if m})
if distinct == len(msgs):
    print(f"  \033[32mok\033[0m   {len(msgs)} outcomes, {distinct} distinct messages")
    for k, v in msgs.items(): print(f"         {k:<10} {v}")
else:
    print(f"  \033[31mFAIL\033[0m messages collapsed: {msgs}")
    sys.exit(1)
PYEOF
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo
echo "Rate limiting backs off"
for i in $(seq 1 6); do
  curl -s -o /dev/null -X POST "${J[@]}" -H 'CF-Connecting-IP: 198.51.100.66' -d '{"credential":"111111"}' ${G}/api/guest/redeem
done
check "after repeated wrong PINs"        429 "$(code -X POST "${J[@]}" -H 'CF-Connecting-IP: 198.51.100.66' -d '{"credential":"111111"}' ${G}/api/guest/redeem)"
check "a link credential is unaffected"  401 "$(code -X POST "${J[@]}" -H 'CF-Connecting-IP: 198.51.100.66' -d '{"credential":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}' ${G}/api/guest/redeem)"

echo
printf '\033[1m%d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
