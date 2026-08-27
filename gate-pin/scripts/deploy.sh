#!/usr/bin/env bash
# Copy this add-on onto a Home Assistant machine's /addons folder.
#
#   ./scripts/deploy.sh /Volumes/addons              # Samba add-on, mounted on a Mac
#   ./scripts/deploy.sh root@homeassistant.local     # SSH add-on
#   ./scripts/deploy.sh root@192.168.1.50:/addons    # SSH, explicit path
#
# Excludes node_modules and dist: the container builds the frontend itself, and
# copying them would bloat the transfer and can poison the build with host-built
# artefacts.
set -uo pipefail

TARGET="${1:-}"
if [ -z "${TARGET}" ]; then
  echo "usage: $0 <mounted-path | [user@]host[:/addons]>"
  exit 1
fi

cd "$(dirname "$0")/.."
SRC="$PWD"
NAME="$(basename "${SRC}")"
VERSION="$(grep -E '^version:' config.yaml | head -1 | tr -d '\"' | awk '{print $2}')"

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

cat <<TXT

In Home Assistant:
  first install   Settings > Add-ons > Add-on store > ... > Check for updates
                  then open "Gate PIN" under Local add-ons and Install
  after a change  open the add-on and click Rebuild

A rebuild takes a few minutes on first run and is mostly cached after that.
TXT
