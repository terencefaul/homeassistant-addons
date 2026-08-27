#!/usr/bin/env bash
# Cut a new add-on version, so Home Assistant offers it as an update.
#
#   ./scripts/release.sh patch "Fix the porch light state"
#   ./scripts/release.sh minor "Add a QR code to the mint screen"
#   ./scripts/release.sh 0.3.0 "Something specific"
#
# Home Assistant compares the version in config.yaml against the installed one,
# so bumping it is the entire update mechanism. Nothing else is needed.
set -uo pipefail

BUMP="${1:-patch}"
NOTE="${2:-}"

cd "$(dirname "$0")/.."
CURRENT=$(grep -E '^version:' config.yaml | head -1 | tr -d '"' | awk '{print $2}')

if [ -z "${NOTE}" ]; then
  echo "usage: $0 <patch|minor|major|X.Y.Z> \"what changed\""
  echo "current version: ${CURRENT}"
  exit 1
fi

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

if [ -n "$(git status --porcelain -- . ../repository.json)" ]; then
  echo "Working tree has uncommitted changes. Commit them first:"
  git status --short -- . ../repository.json | sed 's/^/  /'
  exit 1
fi

echo "Releasing ${CURRENT} -> ${NEXT}"

sed -i '' -E "s/^version: \".*\"/version: \"${NEXT}\"/" config.yaml 2>/dev/null \
  || sed -i -E "s/^version: \".*\"/version: \"${NEXT}\"/" config.yaml

DATE=$(date +%Y-%m-%d)
python3 - "${NEXT}" "${DATE}" "${NOTE}" <<'PY'
import sys, pathlib
version, date, note = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path("CHANGELOG.md")
s = p.read_text()
entry = f"## [{version}] - {date}\n- {note}\n\n"
marker = "# Changelog\n\n"
s = s.replace(marker, marker + entry, 1) if marker in s else entry + s
p.write_text(s)
print(f"  CHANGELOG.md updated")
PY

git add config.yaml CHANGELOG.md
git commit -q -m "Release ${NEXT}

${NOTE}"
git push -q origin HEAD && echo "  pushed"

cat <<TXT

Released ${NEXT}.

Home Assistant checks its add-on repositories periodically. To see it now:
  Settings > Add-ons > Add-on store > ... > Check for updates

Then the Gate PIN card shows an Update button. Installing it rebuilds the
image on your machine, which takes a couple of minutes.
TXT
