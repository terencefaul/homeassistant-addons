#!/usr/bin/env bash
# Cut a new add-on version, so Home Assistant offers it as an update.
#
#   ./scripts/release.sh gate-pin patch "Fix the porch light state"
#   ./scripts/release.sh gate-pin minor "Add a QR code to the mint screen"
#   ./scripts/release.sh gate-pin 0.3.0 "Something specific"
#
# Home Assistant compares the version in config.yaml against the installed one,
# so bumping it is the entire update mechanism. Nothing else is needed.
set -uo pipefail

ADDON="${1:-}"
BUMP="${2:-patch}"
NOTE="${3:-}"

cd "$(dirname "$0")/.."

if [ -z "${ADDON}" ] || [ -z "${NOTE}" ] || [ ! -f "${ADDON}/config.yaml" ]; then
  echo "usage: $0 <add-on> <patch|minor|major|X.Y.Z> \"what changed\""
  echo "add-ons in this repository:"
  for d in */config.yaml; do
    [ -f "$d" ] || continue
    a=$(dirname "$d")
    v=$(grep -E '^version:' "$d" | head -1 | tr -d '"' | awk '{print $2}')
    echo "  ${a}  (${v})"
  done
  exit 1
fi

CURRENT=$(grep -E '^version:' "${ADDON}/config.yaml" | head -1 | tr -d '"' | awk '{print $2}')

case "${BUMP}" in
  patch|minor|major)
    IFS=. read -r MA MI PA <<< "${CURRENT}"
    case "${BUMP}" in
      major) NEXT="$((MA+1)).0.0" ;;
      minor) NEXT="${MA}.$((MI+1)).0" ;;
      patch) NEXT="${MA}.${MI}.$((PA+1))" ;;
    esac ;;
  *) NEXT="${BUMP}" ;;
esac

if ! echo "${NEXT}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "not a version: ${NEXT}"; exit 1
fi

if [ -n "$(git status --porcelain -- "${ADDON}" repository.json)" ]; then
  echo "Working tree has uncommitted changes. Commit them first:"
  git status --short -- "${ADDON}" repository.json | sed 's/^/  /'
  exit 1
fi

echo "Releasing ${ADDON} ${CURRENT} -> ${NEXT}"

sed -i '' -E "s/^version: \".*\"/version: \"${NEXT}\"/" "${ADDON}/config.yaml" 2>/dev/null \
  || sed -i -E "s/^version: \".*\"/version: \"${NEXT}\"/" "${ADDON}/config.yaml"

DATE=$(date +%Y-%m-%d)
python3 - "${ADDON}" "${NEXT}" "${DATE}" "${NOTE}" <<'PY'
import sys, pathlib
addon, version, date, note = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path(addon) / "CHANGELOG.md"
s = p.read_text()
entry = f"## [{version}] - {date}\n- {note}\n\n"
marker = "# Changelog\n\n"
s = s.replace(marker, marker + entry, 1) if marker in s else entry + s
p.write_text(s)
print(f"  CHANGELOG.md updated")
PY

git add "${ADDON}/config.yaml" "${ADDON}/CHANGELOG.md"
git commit -q -m "Release ${ADDON} ${NEXT}

${NOTE}"
git push -q origin HEAD && echo "  pushed"

cat <<TXT

Released ${ADDON} ${NEXT}.

Home Assistant checks its add-on repositories periodically. To see it now:
  Settings > Add-ons > Add-on store > ... > Check for updates

Then the add-on card shows an Update button. Installing it rebuilds the
image on your machine, which takes a couple of minutes.
TXT
