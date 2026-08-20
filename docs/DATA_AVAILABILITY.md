# Data availability — Explorer vs. baseline model outputs

This note records which data the explorer needs, what the baseline model run provides, and what is
missing. The explorer (`web/index.html`) consumes only the JSON under `web/data/`, produced by
`process.py` from the raw outputs under `simulation_output/` (see the top-level `README.md` for the
produce → process → serve pipeline). `process.py` **validates** itself by recomputing the country-level
risk/resilience from `iah.csv` + `macro.csv` and comparing against `results.csv`
(max relative error ≈ 1e-13 — an exact reproduction of the published pipeline). This validation also
guards against `scenarios.default_settings` drifting from the model's canonical baseline.

## Coverage on the globe

- **132 countries** are simulated (`simulation_output/0_baseline/simulation_outputs/results.csv`).
  `THA` and `LUX` are explicitly excluded in the baseline settings (`exclude_countries`); every other
  country in the world is simply not modelled.
- All **132 simulated countries are shown coloured** on the globe. Countries not covered by the
  simulation render **grey** and are non-interactive (tooltip: *"Not covered by the simulation"*).
- The globe uses the **World Bank GAD** country polygons (the same source as the paper's maps),
  vendored as raw zips in `data/WB_shapes/raw/`, topologically simplified by `simplify_shapes.sh`
  (mapshaper, shared-arc topology + `keep-shapes` so no polygon vanishes) and converted to
  `web/data/wb_adm0.json` / `wb_borders.json` by `prepare_shapes.py`; all 132 simulated
  countries have a polygon. Country
  matching is by the `iso3` property (WB `ISO_A3`). Disputed regions without an ISO code are
  coloured following the paper's `get_special_map_colors` (claimant colors, 50/50 blends), and
  boundary lines carry the WB `Style` linestyles (solid / dashed / dotted), pre-baked into the
  border polylines.

## Present and wired up

| Variable (UI)             | Source field (`results.csv`) | Notes |
|---------------------------|------------------------------|-------|
| Risk to assets            | `risk_to_assets`             | fraction → shown ×100 as % GDP |
| Risk to consumption       | `risk_to_consumption`        | fraction → % GDP |
| Risk to well-being        | `risk_to_wellbeing`          | fraction → % GDP |
| Socio-economic resilience | `resilience`                 | = `risk_to_assets / risk_to_wellbeing`; ×100 as % |
| Recovery duration         | `t_reco_95`                  | years (fallback: derived from `iah.csv` `lambda_h`) |
| Context (income/region/pop/GDPpc/Gini) | `income_group`,`region`,`pop`,`gdp_pc_pp`,`gini_index` | region/income codes mapped to full labels |

**Per-quintile breakdown** (Q1 poorest … Q5 richest) is derived from
`simulation_output/0_baseline/simulation_outputs/iah.csv` by replicating the model's own aggregation
(`agg_to_event_level` → `average_over_rp` with FLOPROS protection → sum over hazards →
`calc_risk_and_resilience_from_k_w`). The surfaced quintile metrics — **income share**, **risk to
well-being**, **risk to assets** — each decompose *exactly* to the national total.

**Data-quality flags** come from `model_inputs/data_coverage.csv` (count of `imputed` vs. `available`
inputs per country), shown in the country panel footer.

## Policy simulations

Single-policy scenarios (one lever at a time) are produced by `simulate.py` (full model runs over all
countries, ~15–25 rounded steps per lever) into `simulation_output/<series>/<scope>/<param>/`, and
assembled by `process.py` into `web/data/policies/<ISO>.json` + `manifest.json`. The frontend does a
table lookup (no live model) and shows one editable policy at a time. Deep poorest-quintile steps the
model cannot solve for a country are stored as `null` and the slider clamps to each country's feasible
range. See `web/data/SCHEMA.md` for the exact shape.

Nine response series back six lever cards: exposure & vulnerability (whole-population / poorest-20%
scope), self-employment, income diversification, income equalization (gini), and PDS (post-disaster
support / insurance).

> **Note — `gini` series.** The `gini` (income-equalization) sweep currently has **no raw outputs**
> under `simulation_output/gini/` (only empty step directories), so `process.py` omits it and the
> "Reduce income inequality" lever does not appear. To restore it, run
> `uv run python simulate.py --series gini` (model required), then `uv run python process.py`.

## Regenerating the data

```sh
# 1) wire the model (once) and bootstrap its env — see README for the submodule command
uv sync --directory external/UB-global-socioeconomic-resilience
uv sync

# 2) produce raw outputs, then distil to web/data/
uv run python simulate.py          # baseline + all policy sweeps → simulation_output/  (hours)
uv run python process.py           # → web/data/explorer_data.json + policies/*.json

# 3) build + serve the site
npm --prefix web ci && npm --prefix web run build
python3 -m http.server -d web 8000   # open http://localhost:8000/
```
