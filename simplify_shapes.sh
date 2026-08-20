#!/usr/bin/env bash
# Simplify the vendored raw World Bank GAD shapefiles into data/WB_shapes/simplified/,
# the input of prepare_shapes.py.
#
# Reads the raw zips vendored in data/WB_shapes/raw/ (WB Official Boundaries,
# https://datacatalog.worldbank.org/search/dataset/0038272), builds ONE shared
# topology across the three layers (combine-files), and simplifies the shared
# arcs. Because ADM0 polygons, boundary Lines and the ocean mask reference the
# same arcs, neighbouring countries and the styled border lines stay perfectly
# aligned at any simplification level, and keep-shapes guarantees no polygon
# (e.g. the Vatican) vanishes entirely.
#
# Usage: ./simplify_shapes.sh [retention]   e.g. ./simplify_shapes.sh 1%
# Requires node (see web/.nvmrc); mapshaper is fetched via npx.

set -euo pipefail
cd "$(dirname "$0")"

RETAIN="${1:-1%}"
RAW=data/WB_shapes/raw
OUT=data/WB_shapes/simplified

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
for z in WB_GAD_ADM0_complete WB_GAD_Lines WB_GAD_ocean_mask; do
  unzip -q -o "$RAW/$z.zip" -x '__MACOSX/*' -d "$TMP"
done

mkdir -p "$OUT"
npx --yes mapshaper \
  -i "$TMP"/WB_GAD_ADM0_complete.shp "$TMP"/WB_GAD_Lines.shp "$TMP"/WB_GAD_ocean_mask.shp \
     combine-files snap \
  -simplify "$RETAIN" keep-shapes \
  -o "$OUT" target='*' format=shapefile force

echo "wrote $OUT (retention $RETAIN)"
