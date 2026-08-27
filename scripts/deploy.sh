#!/usr/bin/env bash
# Copy this add-on onto a Home Assistant machine's /addons folder.
#
#   ./scripts/deploy.sh gate-pin /Volumes/addons              # mounted Samba share
#   ./scripts/deploy.sh gate-pin root@homeassistant.local     # SSH add-on
#   ./scripts/deploy.sh gate-pin root@192.168.1.50:/addons    # SSH, explicit path
#
# Add --rebuild to make it a one-command update: the add-on is rebuilt and
# restarted through the Home Assistant API, so there is nothing to click.
# Needs two environment variables, best put in a .env you do not commit:
#
#   export HA_URL=http://homeassistant.local:8123
#   export HA_TOKEN=...   # Profile > Security > Long-lived access tokens
#
# Excludes node_modules and dist: the container builds the frontend itself, and
# copying them would bloat the transfer and can poison the build with host-built
# artefacts.
set -uo pipefail

REBUILD=0
ADDON=""
TARGET=""
for arg in "$@"; do
  case "${arg}" in
    --rebuild) REBUILD=1 ;;
    *) if [ -z "${ADDON}" ]; then ADDON="${arg}"; else TARGET="${arg}"; fi ;;
  esac
done

cd "$(dirname "$0")/.."
ROOT="$PWD"

if [ -z "${ADDON}" ] || [ -z "${TARGET}" ]; then
  echo "usage: $0 <add-on> <mounted-path | [user@]host[:/addons]> [--rebuild]"
  echo "add-ons in this repository:"
  for d in */config.yaml; do [ -f "$d" ] && echo "  $(dirname "$d")"; done
  exit 1
fi

if [ ! -f "${ADDON}/config.yaml" ]; then
  echo "No add-on called '${ADDON}' (expected ${ADDON}/config.yaml)"
  exit 1
fi

SRC="${ROOT}/${ADDON}"
NAME="${ADDON}"
VERSION="$(grep -E '^version:' "${SRC}/config.yaml" | head -1 | tr -d '\"' | awk '{print $2}')"

EXCLUDES=(
  --exclude 'frontend/node_modules'
  --exclude 'frontend/dist'
  --exclude '__pycache__'
  --exclude '.pytest_cache'
  --exclude '*.pyc'
)

echo "Deploying ${NAME} ${VERSION}"

if [ -d "${TARGET}" ]; then
  # A mounted share.
  DEST="${TARGET%/}/${NAME}"
  if command -v rsync >/dev/null; then
    rsync -a --delete "${EXCLUDES[@]}" "${SRC}/" "${DEST}/" || exit 1
  else
    rm -rf "${DEST}" && mkdir -p "${DEST}"
    tar -cf - --exclude node_modules --exclude dist --exclude __pycache__ -C "${SRC}" . \
      | tar -xf - -C "${DEST}" || exit 1
  fi
  echo "  -> ${DEST}"
else
  # An SSH target, with or without an explicit path.
  case "${TARGET}" in
    *:*) HOST="${TARGET%%:*}"; PATH_ON_HOST="${TARGET#*:}" ;;
    *)   HOST="${TARGET}";     PATH_ON_HOST="/addons" ;;
  esac
  if command -v rsync >/dev/null; then
    rsync -a --delete "${EXCLUDES[@]}" "${SRC}/" "${HOST}:${PATH_ON_HOST%/}/${NAME}/" || exit 1
  else
    ssh "${HOST}" "rm -rf ${PATH_ON_HOST%/}/${NAME} && mkdir -p ${PATH_ON_HOST%/}/${NAME}" || exit 1
    tar -cf - --exclude node_modules --exclude dist --exclude __pycache__ -C "${SRC}" . \
      | ssh "${HOST}" "tar -xf - -C ${PATH_ON_HOST%/}/${NAME}" || exit 1
  fi
  echo "  -> ${HOST}:${PATH_ON_HOST%/}/${NAME}"
fi

SLUG="local_$(grep -E '^slug:' "${SRC}/config.yaml" | awk '{print $2}')"

if [ "${REBUILD}" = "1" ]; then
  if [ -z "${HA_URL:-}" ] || [ -z "${HA_TOKEN:-}" ]; then
    echo
    echo "--rebuild needs HA_URL and HA_TOKEN:"
    echo "  export HA_URL=http://homeassistant.local:8123"
    echo "  export HA_TOKEN=...   # Profile > Security > Long-lived access tokens"
    exit 1
  fi
  echo
  echo "Rebuilding ${SLUG} via the Home Assistant API..."
  # Home Assistant proxies the Supervisor API at /api/hassio for admins, so this
  # works from anywhere that can reach Home Assistant -- no SSH, no clicking.
  CODE=$(curl -s -o /tmp/gate-pin-rebuild.log -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    "${HA_URL%/}/api/hassio/addons/${SLUG}/rebuild")
  if [ "${CODE}" = "200" ]; then
    echo "  rebuilt and restarted."
  else
    echo "  rebuild failed (HTTP ${CODE}):"
    sed 's/^/    /' /tmp/gate-pin-rebuild.log
    echo
    echo "  If this is the first deploy, install the add-on once by hand:"
    echo "    Settings > Add-ons > Add-on store > ... > Check for updates"
    exit 1
  fi
else
  cat <<TXT

In Home Assistant:
  first install   Settings > Add-ons > Add-on store > ... > Check for updates
                  then open "Gate PIN" under Local add-ons and Install
  after a change  open the add-on and click Rebuild
                  (or re-run this with --rebuild and skip the clicking)

A rebuild takes a few minutes on first run and is mostly cached after that.
TXT
fi
