#!/usr/bin/env bash
# Run the add-on locally against a stubbed Supervisor, and leave it running so
# you can use it in a browser. This is the closest thing to the real add-on
# without a Home Assistant instance: same container, same nginx, same port
# split, same API.
#
#   ./scripts/dev-run.sh          build and start
#   ./scripts/dev-run.sh stop     tear down
set -uo pipefail

IMAGE=gate-pin:dev
NET=gate-pin-dev-net
DATA_DIR="${GATE_PIN_DEV_DATA:-/tmp/gate-pin-dev-data}"
PLATFORM="${PLATFORM:-linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}"
case "${PLATFORM}" in
  linux/amd64) BASE=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 ;;
  *)           BASE=ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20 ;;
esac

cd "$(dirname "$0")/.."

if [ "${1:-}" = "stop" ]; then
  docker rm -f gate-pin-dev gate-pin-dev-supervisor >/dev/null 2>&1
  docker network rm "${NET}" >/dev/null 2>&1
  echo "stopped (data kept in ${DATA_DIR})"
  exit 0
fi

echo "Building ${IMAGE} for ${PLATFORM}..."
docker build --platform "${PLATFORM}" --build-arg BUILD_FROM="${BASE}" -t "${IMAGE}" . >/dev/null || {
  echo "build failed"; exit 1; }

mkdir -p "${DATA_DIR}"
[ -f "${DATA_DIR}/options.json" ] || cat > "${DATA_DIR}/options.json" <<JSON
{"external_base_url":"http://127.0.0.1:8888","telegram_bot_token":"","telegram_chat_ids":[],
 "notify_service":"","pin_length":6,"max_live_pin_grants":20,
 "trusted_proxy_cidr":"172.30.32.0/23","audit_retention_days":90,
 "require_cf_header":false}
JSON

docker rm -f gate-pin-dev gate-pin-dev-supervisor >/dev/null 2>&1
docker network create "${NET}" >/dev/null 2>&1

# Named `supervisor` so the add-on's hardcoded http://supervisor/core/api/ resolves.
docker run -d --name gate-pin-dev-supervisor --network "${NET}" --network-alias supervisor \
  --platform "${PLATFORM}" -v "${PWD}/scripts/stub-supervisor.py:/stub.py:ro" \
  python:3.12-alpine python3 /stub.py >/dev/null

docker run -d --name gate-pin-dev --network "${NET}" --platform "${PLATFORM}" \
  -e SUPERVISOR_TOKEN=dev-token -v "${DATA_DIR}:/data" \
  -p 8888:8888 -p 8099:8099 "${IMAGE}" >/dev/null

printf 'Starting'
for _ in $(seq 1 60); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Ingress-Path: /x' http://127.0.0.1:8099/api/admin/health)" = "200" ]; then
    break
  fi
  printf '.'; sleep 1
done
echo

cat <<TXT

  Admin panel   http://127.0.0.1:8099/
  Guest page    http://127.0.0.1:8888/

Mint a credential in the admin panel, then open the guest page and use it.
The entities are stubs (a driveway gate, a porch light, a front door lock, a
camera) and they really do change state when you operate them.

Two things differ from a real install:
  - require_cf_header is off, because there is no Cloudflare in front of you.
    On the real add-on it stays ON.
  - The admin panel is reachable directly on 8099. On a real install it is
    published nowhere and only Home Assistant ingress can reach it.

  Logs   docker logs -f gate-pin-dev
  Stop   ./scripts/dev-run.sh stop
TXT
