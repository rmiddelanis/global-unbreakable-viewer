#!/usr/bin/env bash
# Build the frontend bundle: transpile + minify the JSX source (src/app.jsx)
# into app.js, which index.html loads as a plain <script>. This removes the
# in-browser Babel transform so there are no third-party runtime dependencies.
#
# Requires esbuild. Easiest: `npx esbuild` (Node), or a standalone esbuild binary
# on PATH (https://esbuild.github.io/getting-started/#download-a-build).
set -euo pipefail
cd "$(dirname "$0")"

ESBUILD="${ESBUILD:-esbuild}"
command -v "$ESBUILD" >/dev/null 2>&1 || ESBUILD="npx --yes esbuild"

$ESBUILD src/app.jsx \
  --jsx=transform --jsx-factory=React.createElement --jsx-fragment=React.Fragment \
  --minify --target=es2018 \
  --banner:js='/* Generated from src/app.jsx by build.sh — edit the .jsx source, not this file. */' \
  --outfile=app.js

echo "Built app.js ($(wc -c < app.js) bytes)"
