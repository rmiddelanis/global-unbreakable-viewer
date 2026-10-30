#!/usr/bin/env bash
# Assemble the hand-off package for hosting the explorer on an external web server.
#
# Builds web/app.js from web/src/app.jsx, copies the runtime files of web/ into
# dist/global-resilience-explorer/site/ (dropping build tooling, sources and dev notes),
# adds docs/HOSTING.md, docs/THIRD_PARTY_LICENSES.md and a VERSION.txt stamp, and zips it
# as dist/global-resilience-explorer-<commit>.zip. Whoever hosts it uploads the
# contents of site/; see docs/HOSTING.md.
#
# Usage: ./package.sh
# Requires node (see .nvmrc); runs `npm ci` in web/ first if node_modules is missing.

set -euo pipefail
cd "$(dirname "$0")"

NAME=global-resilience-explorer
OUT=dist/$NAME

COMMIT=$(git rev-parse --short HEAD)
if [ -n "$(git status --porcelain)" ]; then
  COMMIT="$COMMIT-dirty"
  echo "warning: uncommitted changes — the package won't match any commit" >&2
fi

[ -d web/node_modules ] || npm --prefix web ci
npm --prefix web run build

rm -rf "$OUT" "dist/$NAME-$COMMIT.zip"
mkdir -p "$OUT/site"
rsync -a \
  --exclude node_modules --exclude src --exclude 'package*.json' \
  --exclude .nojekyll --exclude SCHEMA.md --exclude .DS_Store \
  web/ "$OUT/site/"
cp docs/HOSTING.md docs/THIRD_PARTY_LICENSES.md "$OUT/"
printf 'commit:   %s\npackaged: %s\nsource:   https://github.com/rmiddelanis/global-unbreakable-viewer\n' \
  "$COMMIT" "$(date -u +%Y-%m-%dT%H:%MZ)" > "$OUT/VERSION.txt"

(cd dist && zip -qr -X "$NAME-$COMMIT.zip" "$NAME")
echo "wrote dist/$NAME-$COMMIT.zip ($(find "$OUT/site" -type f | wc -l | tr -d ' ') site files, $(du -sh "$OUT/site" | cut -f1))"
