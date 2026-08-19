"""Convert the vendored World Bank GAD shapefiles into the JSON assets served by web/.

Inputs (vendored copies from the paper repo's data/WB_shapes/simplified):
    data/WB_shapes/simplified/WB_GAD_ADM0_complete.shp   country + disputed-region polygons
    data/WB_shapes/simplified/WB_GAD_Lines.shp           international boundary lines (Style attribute)
    data/WB_shapes/simplified/WB_GAD_ocean_mask.shp      ocean polygon (land = bbox - ocean)

Outputs (all consumed by web/src/app.jsx):
    web/data/wb_adm0.json     GeoJSON FeatureCollection, props {iso3, name}; special/disputed
                              regions keep iso3=null and are matched by name (see
                              get_special_map_colors in the paper repo's plotting.py)
    web/data/wb_borders.json  {"borders": [...], "coast": [...]} polylines as [[lng,lat],...];
                              borders are the WB_GAD_Lines with dashed/dotted styles pre-baked
                              into short segments (globe.gl paths cannot render per-path dash
                              patterns), coast is the outline of the land mask (negative of the
                              ocean mask) drawn steelblue like the paper maps

Requires geopandas/shapely, which are NOT in this repo's env (they are heavy and only
needed for this one-off conversion). Run either with the paper repo's env or via
    uv run --with geopandas python prepare_shapes.py
"""

import json
import os

import geopandas as gpd
import shapely
from shapely.geometry import box
from shapely.ops import substring

ROOT = os.path.dirname(os.path.abspath(__file__))
SHAPE_DIR = os.path.join(ROOT, "data/WB_shapes/simplified")
OUT_DIR = os.path.join(ROOT, "web/data")

# dash patterns of the paper maps (BORDER_LINESTYLES in plotting.py, matplotlib
# (on, off) units), scaled to degrees so the dashing stays readable on the globe
DASH_SCALE = 0.15  # degrees per matplotlib dash unit
BORDER_LINESTYLES = {
    "Dashed": (4, 2),
    "Dotted": (1, 2),
    "Tightly Dashed": (0.5, 0.5),
    # 'solid' handled separately (no baking)
}

PRECISION = 3  # coordinate decimals (~110 m, well below the shapes' simplification)
GRID = 10 ** -PRECISION  # snap grid for set_precision
MAX_SEG = 0.5  # densify edges to this max segment length (deg) before export


def _clean(geoms):
    """Segmentize + grid-snap geometries (arrays or scalars).

    globe.gl tessellates every polygon cap independently, so two countries sharing a long
    straight border segment would curve it slightly differently, rendering as paired hairline
    overlaps/gaps along the border. Densifying edges to MAX_SEG makes both sides share
    identical vertices (residual chord sag ~1 km, invisible on the globe), and set_precision
    snaps everything to one global grid so shared vertices stay bit-identical after export."""
    return shapely.set_precision(shapely.segmentize(geoms, MAX_SEG), GRID)


def _round_coords(coords):
    """Round and drop consecutive duplicates created by the rounding."""
    out = []
    for x, y in coords:
        pt = [round(float(x), PRECISION), round(float(y), PRECISION)]
        if not out or out[-1] != pt:
            out.append(pt)
    return out


def _ring_ok(pts):
    """Reject degenerate rings: hairline slivers (dissolve/rounding artifacts) make
    globe.gl's spherical triangulation blow up into a cap covering the whole sphere."""
    if len(pts) < 4:
        return False
    area = perim = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        area += x1 * y2 - x2 * y1
        perim += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    area = abs(area) / 2
    return area >= 1e-5 and perim > 0 and area / perim ** 2 >= 1e-4


def _geom_to_multipolygon_coords(geom):
    if geom.geom_type == "GeometryCollection":  # set_precision can demote collapsed parts
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        polys = [q for g in polys for q in (g.geoms if g.geom_type == "MultiPolygon" else [g])]
    else:
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    out = []
    for p in polys:
        exterior = _round_coords(p.exterior.coords)
        if not _ring_ok(exterior):
            continue
        rings = [exterior]
        for interior in p.interiors:
            r = _round_coords(interior.coords)
            if _ring_ok(r):
                rings.append(r)
        out.append(rings)
    return out


def write_adm0():
    adm0 = gpd.read_file(os.path.join(SHAPE_DIR, "WB_GAD_ADM0_complete.shp"))
    adm0["geometry"] = adm0["geometry"].make_valid()
    adm0["NAM_0"] = adm0["NAM_0"].str.strip()  # e.g. 'Kauirik\r\n'

    # like load_country_shapes() in the paper repo: dissolve by ISO, but keep the
    # ISO-less special/disputed regions as individual features (matched by name)
    na = adm0[adm0.ISO_A3.isna()].copy()
    iso = adm0[adm0.ISO_A3.notna()].dissolve(by="ISO_A3", as_index=False)
    iso["geometry"] = _clean(iso["geometry"].values)
    na["geometry"] = _clean(na["geometry"].values)

    features = []
    for _, row in iso.iterrows():
        features.append({
            "type": "Feature",
            "properties": {"iso3": row.ISO_A3, "name": row.NAM_0},
            "geometry": {"type": "MultiPolygon",
                         "coordinates": _geom_to_multipolygon_coords(row.geometry)},
        })
    for _, row in na.iterrows():
        features.append({
            "type": "Feature",
            "properties": {"iso3": None, "name": row.NAM_0},
            "geometry": {"type": "MultiPolygon",
                         "coordinates": _geom_to_multipolygon_coords(row.geometry)},
        })

    path = os.path.join(OUT_DIR, "wb_adm0.json")
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
    print(f"wb_adm0.json: {len(features)} features, {os.path.getsize(path)/1e6:.2f} MB")


MIN_COAST_RING = 1.0   # skip islets below this ring length (deg) to bound the object count
FRAME = 180 - 1e-6     # |lng| at/beyond this is the antimeridian cut, not a real coastline


def coast_paths():
    """Coastline polylines: rings of the land mask (negative of the ocean mask), split where
    they run along the antimeridian cut so no artificial meridian is drawn on the globe."""
    ocean = gpd.read_file(os.path.join(SHAPE_DIR, "WB_GAD_ocean_mask.shp"))
    ocean["geometry"] = ocean["geometry"].make_valid()
    land = box(*ocean.total_bounds)
    for g in ocean.geometry:
        land = land.difference(g)
    land = _clean(land)
    polys = land.geoms if land.geom_type == "MultiPolygon" else [land]
    paths = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            if ring.length < MIN_COAST_RING:
                continue
            # split the ring into runs of points off the antimeridian frame
            run = []
            for x, y in ring.coords:
                if abs(x) >= FRAME:
                    if len(run) >= 2:
                        paths.append(run)
                    run = []
                else:
                    run.append((x, y))
            if len(run) >= 2:
                paths.append(run)
    return [pts for pts in (_round_coords(r) for r in paths) if len(pts) >= 2]


def write_borders():
    lines = gpd.read_file(os.path.join(SHAPE_DIR, "WB_GAD_Lines.shp"))
    lines["geometry"] = _clean(lines["geometry"].make_valid().values)
    lines["Style"] = lines["Style"].fillna("solid")

    paths = []
    for _, row in lines.explode(index_parts=False).iterrows():
        geom = row.geometry
        if geom.geom_type != "LineString" or geom.is_empty:
            continue
        pattern = BORDER_LINESTYLES.get(row.Style)
        if pattern is None:  # solid
            pts = _round_coords(geom.coords)
            if len(pts) >= 2:
                paths.append(pts)
            continue
        on, off = (p * DASH_SCALE for p in pattern)
        d, length = 0.0, geom.length
        while d < length:
            dash = substring(geom, d, min(d + on, length))
            if dash.geom_type == "LineString" and not dash.is_empty:
                pts = _round_coords(dash.coords)
                if len(pts) >= 2:
                    paths.append(pts)
            d += on + off

    coast = coast_paths()
    path = os.path.join(OUT_DIR, "wb_borders.json")
    with open(path, "w") as f:
        json.dump({"borders": paths, "coast": coast}, f, separators=(",", ":"))
    print(f"wb_borders.json: {len(paths)} border + {len(coast)} coast polylines, "
          f"{os.path.getsize(path)/1e6:.2f} MB")


if __name__ == "__main__":
    write_adm0()
    write_borders()
