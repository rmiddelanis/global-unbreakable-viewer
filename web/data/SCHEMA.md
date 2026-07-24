# `web/data/` — the process → serve JSON contract

These files are produced by `process.py` (from `simulation_output/`) and consumed by
`web/src/app.jsx`. They are committed so the site runs without the model or Python. All fetches are
relative to `web/index.html`, so `web/data/` must sit beside it.

Risk metrics and resilience are stored **×100** (i.e. already in % / % of GDP); `recovery` is in years.

---

## `explorer_data.json`
Top level:

| key | type | notes |
|-----|------|-------|
| `generatedFrom` | string | provenance (`simulation_output/0_baseline`) |
| `framework` | string | model name |
| `incomeOrder` | string[] | income-group codes in display order (`LICs`…`HICs`) |
| `incomeLabels` | object | code → full label |
| `regionLabels` | object | code → full label |
| `countries` | object[] | one per simulated country (see below) |
| `meta` | object | `nCountries`, `hazards[]`, `returnPeriods[]`, `notes{}` |

Each `countries[]` entry:

| key | type | notes |
|-----|------|-------|
| `iso` | string | ISO-A3 (join key to the globe polygons and to `policies/<ISO>.json`) |
| `name`, `region`, `regionLabel`, `incomeGroup`, `incomeLabel` | string | labels |
| `pop`, `gdppc`, `gnipc`, `gini` | number \| null | context |
| `riskAssets`, `riskConsumption`, `riskWellbeing` | number | % of GDP (×100) |
| `resilience` | number | % (×100) |
| `recovery` | number \| null | 95% recovery duration, years |
| `imputedInputs`, `totalInputs` | int | data-quality counts |
| `quint` | object[] | 5 rows (poorest→richest), each `{q:1..5, incomeShare:%, riskWellbeing:%GDP, riskAssets:%GDP}` — decomposes exactly to the national totals |

## `policies/<ISO>.json`
One file per country. Single-policy scenarios (one lever moved at a time):

```jsonc
{
  "iso": "AGO",
  "baseline": { "riskAssets": .., "riskConsumption": .., "riskWellbeing": .., "resilience": .., "recovery": .. },
  "series": {
    "exposure_all": {
      "param":          [1.0, 0.99, 0.98, …],   // index 0 = identity (== baseline); ascending policy intensity
      "display":        "reduction",             // "reduction" → label (1-p)*100% ; "share" → p*100%
      "riskAssets":     [.., .., …],             // one array per output metric, aligned with `param`
      "riskConsumption":[…], "riskWellbeing":[…], "resilience":[…], "recovery":[…]
    },
    "…": { … }
  }
}
```

- Array index 0 is the **baseline identity** endpoint (not simulated — copied from `baseline`).
- Values beyond a country's feasible range are `null` (e.g. deep poorest-quintile steps the model can't
  solve); the frontend clamps each country's slider to the last non-null index.
- A series only appears if `process.py` found raw runs for it. The frontend shows a lever card only when
  the backing series is present (`manifest.levers` × per-country `series`).

## `policies/manifest.json`
Describes the lever cards and the metrics, independent of any one country:

| key | type | notes |
|-----|------|-------|
| `method` | string | `"table"` (frontend does a lookup; seam for a future per-country `"emulator"`) |
| `outputs` | string[] | metric keys present in each series (`riskAssets`…`recovery`) |
| `levers` | object[] | frontend lever grouping: `key`, `label`, `kind`, and either `series{scope→id}`+`scopes[]` (scale levers) or `variants{}`+`variantLabels{}` (PDS) |
| `note` | string | human note |
