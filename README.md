# Global Resilience Explorer

An interactive globe visualising country-level outputs of the **Global Unbreakable** disaster-resilience
model. The site itself is a dependency-free static page (vendored React + globe.gl, self-hosted fonts);
all computation happens offline in Python.

The repo is organised as three stages — **produce → process → serve**:

| Stage | What it does | Entry point → output | Toolchain |
|-------|--------------|----------------------|-----------|
| **simulate** | run the model (baseline + policy sweeps) | `simulate.py` → `simulation_output/` | uv (drives the model submodule in its own env) |
| **process** | distil raw outputs into compact data JSON | `process.py` → `web/data/` | uv (numpy / pandas) |
| **serve** | the static globe frontend | `web/` → built `web/app.js`, deployed to Pages | Node (nvm) + esbuild |

`scenarios.py` holds the scenario/lever definitions shared by `simulate.py` and `process.py`.
Two boundaries make the stages independent:

- **`simulation_output/`** — raw model outputs (large, **gitignored**): the produce→process boundary.
- **`web/data/*.json`** — the compact JSON (**committed**): the process→serve contract, so the site
  runs from a clone with no model and no Python.

## Layout

```
├── simulate.py             produce: run the model  → simulation_output/
├── process.py              process: simulation_output/ → web/data/
├── scenarios.py            shared scenario/lever definitions
├── pyproject.toml, uv.lock uv project for simulate + process
├── .nvmrc                  Node version for the web build
├── external/               model submodule (gitignored)         ← you wire this once
├── simulation_output/      raw model outputs (gitignored, large)
├── web/                    serve: the static site
│   ├── index.html  src/app.jsx  vendor/  fonts/  .nojekyll
│   ├── package.json        esbuild + `build` script
│   ├── app.js              built bundle (gitignored)
│   └── data/               committed JSON contract  (+ SCHEMA.md)
├── docs/                   DATA_AVAILABILITY.md, THIRD_PARTY_LICENSES.md
└── .github/workflows/deploy.yml
```

## Quickstart

### Serve the site (no data regeneration)
The committed `web/data/*.json` is everything the site needs. You only build the JS bundle:

```sh
nvm use                        # Node per .nvmrc  (install nvm first if needed)
npm --prefix web ci            # install esbuild (writes web/package-lock.json on first `npm install`)
npm --prefix web run build     # web/src/app.jsx → web/app.js
python3 -m http.server -d web 8000    # open http://localhost:8000/  (file:// blocks the fetches)
```

Editing the UI: edit **`web/src/app.jsx`** and re-run the build. `web/app.js` is generated, not committed.

### Regenerate the data (only when the model changes)
Needs the model. Wire it as a submodule (or point at a sibling checkout / `$UB_PAPER_REPO`):

```sh
# one-time: model as a submodule (it's gitignored, so -f), then bootstrap its own env
git submodule add -f https://github.com/rmiddelanis/UB-global-socioeconomic-resilience.git \
    external/UB-global-socioeconomic-resilience
uv sync --directory external/UB-global-socioeconomic-resilience
uv sync                                        # this project's env (numpy/pandas/pyyaml)

uv run python simulate.py                      # baseline + all policy sweeps → simulation_output/  (hours)
uv run python process.py                       # simulation_output/ → web/data/*.json
```

Selective / quick runs:

```sh
uv run python simulate.py --baseline                     # baseline only (minutes)
uv run python simulate.py --series exposure_all --limit 1  # smoke-test one step
uv run python process.py --skip-policies                 # rebuild explorer_data.json only
```

`process.py` re-runs anytime (fast) and self-validates the baseline against `results.csv`
(max relative error ≈ 1e-13). It only emits policy series it can reproduce from raw outputs.

## Deployment
`.github/workflows/deploy.yml` builds `web/` and publishes it to GitHub Pages on push to the deploy
branch (default `main`). One-time: repo **Settings → Pages → Source = GitHub Actions**. Because
`web/data/` is committed, CI needs only Node — no Python/uv.

## More
- [`docs/DATA_AVAILABILITY.md`](docs/DATA_AVAILABILITY.md) — coverage and what is / isn't surfaced.
- [`web/data/SCHEMA.md`](web/data/SCHEMA.md) — the JSON contract the frontend consumes.
- [`docs/THIRD_PARTY_LICENSES.md`](docs/THIRD_PARTY_LICENSES.md) — vendored components.
