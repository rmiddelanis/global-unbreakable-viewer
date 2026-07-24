#!/usr/bin/env python3
"""
simulate.py — PRODUCTION stage: run the disaster-resilience model to produce the raw outputs the
viewer needs.

This is the viewer-tailored analogue of the model's ``reproduce_results.py``. Every run — the baseline
AND each single-policy sweep step — is the same kind of job: write a model ``settings.yml`` and drive
the model's two entry points (``run_prepare`` → ``unbreakable.model.run_model``) as subprocesses. The
baseline is simply the scenario with NO lever applied (and full observables); it flows through the
exact same ``build_settings`` + ``run_scenario`` path as the policies. It is authored from scratch
rather than importing ``reproduce_results`` (that module runs its whole pipeline on import). Scenario
definitions and baseline settings live in ``scenarios.py``.

The model itself is a separate uv project (the ``UB-global-socioeconomic-resilience`` repo, with
``unbreakable-core`` installed and its own ``data/processed``). We invoke it via
``uv run --directory <model repo> python -m …`` so it runs in ITS OWN environment, resolved from:
  (1) the git submodule ``external/UB-global-socioeconomic-resilience``,
  (2) ``$UB_PAPER_REPO``,
  (3) the sibling checkout ``../UB-global-socioeconomic-resilience``.

Outputs land under ``simulation_output/`` (gitignored): ``0_baseline/`` and
``<series>/<scope>/<param>/``. The next stage, ``process.py``, distils these into ``web/data/``.

    uv run python simulate.py                      # baseline + all policy sweeps (long!)
    uv run python simulate.py --baseline           # baseline only (minutes)
    uv run python simulate.py --series exposure_all --limit 1   # smoke test one step
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess

import pandas as pd

from scenarios import ALL_SCOPE, OBSERVABLES, Q1_SCOPE, SERIES, default_settings

ROOT = os.path.dirname(os.path.abspath(__file__))
SIM_OUT = os.path.join(ROOT, "simulation_output")
BASELINE_DIR = os.path.join(SIM_OUT, "0_baseline")

RUN_PREPARE = "ub_global_socioeconomic_resilience.run_prepare"
RUN_MODEL = "unbreakable.model.run_model"


# --------------------------------------------------------------------------------------
def resolve_paper_repo() -> str:
    """Locate the model repo (with a populated data/processed) as a submodule, via $UB_PAPER_REPO,
    or as a sibling checkout."""
    candidates = [
        os.path.join(ROOT, "external", "UB-global-socioeconomic-resilience"),
        os.environ.get("UB_PAPER_REPO"),
        os.path.join(ROOT, "..", "UB-global-socioeconomic-resilience"),
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.join(os.path.abspath(c), "src",
                                            "ub_global_socioeconomic_resilience")) \
                and os.path.isdir(os.path.join(os.path.abspath(c), "data", "processed")):
            return os.path.abspath(c)
    raise RuntimeError(
        "Could not locate the model repo (UB-global-socioeconomic-resilience) with a populated "
        "data/processed. Add the submodule external/UB-global-socioeconomic-resilience, set "
        "$UB_PAPER_REPO, or place it as a sibling checkout.")


def run_model_step(paper_root: str, module: str, settings_file: str) -> None:
    """Run one model entry point in the model repo's OWN uv environment.

    ``uv run --directory`` executes with the model repo as the project (so its .venv / unbreakable-core
    are used and its relative ``data/processed`` resolves). Settings paths are absolute, so cwd does not
    matter for outputs."""
    env = dict(os.environ)
    # Don't let an active outer venv (e.g. this project's .venv) shadow the model's own project env —
    # `uv run --directory` should resolve the model repo's environment cleanly.
    env.pop("VIRTUAL_ENV", None)
    r = subprocess.run(["uv", "run", "--directory", paper_root, "python", "-m", module, settings_file],
                       env=env)
    if r.returncode != 0:
        raise RuntimeError(f"{module} failed (exit {r.returncode}) for {settings_file}")


# --------------------------------------------------------------------------------------
def _write_settings(settings: dict, outdir: str) -> str:
    import yaml
    os.makedirs(outdir, exist_ok=True)
    settings_file = os.path.join(outdir, "settings.yml")
    with open(settings_file, "w") as f:
        yaml.dump(settings, f)
    return settings_file


def build_settings(outdir: str, num_cores: int, series: dict | None = None, param=None,
                   observables: dict | None = None) -> dict:
    """Settings for ONE scenario. `series=None` → the baseline (all levers neutral). One lever is moved
    off-neutral otherwise. `observables` trims the written CSV columns for policy runs; the baseline
    passes `observables=None` so it emits the FULL iah/macro that process.py needs for quintiles +
    recovery. Mirrors reproduce_results.py by ASSIGNING a fresh policy dict (required for
    scale_gini_index, which is not one of default_settings' neutral keys)."""
    s = default_settings(num_cores)
    s["scenario_params"]["run_params"]["countries"] = "all"
    s["model_params"]["outpath"] = outdir
    s["model_params"]["input_path"] = os.path.join(outdir, "model_inputs")
    if observables is not None:
        s["model_params"]["observables"] = observables

    if series is None:
        return s  # baseline: no lever applied

    if series["kind"] == "scale":
        pp = {"parameter": param}
        if series["scope"] is not None:
            pp["scope"] = Q1_SCOPE if series["scope"] == "q1" else ALL_SCOPE
        if series.get("scale_total"):
            pp["scale_total"] = True
        s["scenario_params"]["policy_params"][series["measure"]] = pp
    else:  # pds
        s["model_params"]["pds_params"] = {
            "pds_variant": series["variant"], "pds_targeting": "perfect",
            "pds_borrowing_ability": "unlimited", "pds_lending_rate": 0.05,
            "pds_scope": ALL_SCOPE, "covered_loss_share": param,
        }
    return s


def drop_isos_from_inputs(outdir: str, isos: set) -> None:
    """Remove ISOs from the prepared model_inputs so run_model skips them (-> null in the JSON)."""
    inputs = os.path.join(outdir, "model_inputs")
    for fname in ("scenario__hazard_ratios.csv", "scenario__macro.csv", "scenario__cat_info.csv",
                  "scenario__hazard_protection.csv", "data_coverage.csv"):
        p = os.path.join(inputs, fname)
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        if "iso3" in df.columns:
            df[~df["iso3"].isin(isos)].to_csv(p, index=False)


def resolve_q1_feasibility(outdir: str) -> set:
    """Per-HAZARD feasibility handling for q1 scale_total runs.

    Scaling total exposure/vulnerability by moving only the poorest quintile drives a hazard's q1 fa/v
    negative once the requested cut exceeds that quintile's share of the hazard. Handle it per hazard,
    not per country:
      * a hazard is INFEASIBLE for a country if any poorest-quintile row would go < 0;
      * if EVERY hazard of a country is infeasible -> DROP the country (null; the frontend clamps the
        slider width there — the policy can no longer do anything);
      * otherwise KEEP it and CLAMP the infeasible rows' fa/v (and v_ew) to their physical floor of 0,
        so the feasible hazard(s) still scale with the slider while saturated ones sit at 0.
    Rewrites the prepared inputs in place; returns the dropped ISOs."""
    hr_path = os.path.join(outdir, "model_inputs", "scenario__hazard_ratios.csv")
    hr = pd.read_csv(hr_path)
    neg = (hr["fa"] < 0) | (hr["v"] < 0)
    if not neg.any():
        return set()
    bad_haz = hr.loc[neg].groupby("iso3")["hazard"].agg(set)   # hazards with >=1 infeasible q1 row
    all_haz = hr.groupby("iso3")["hazard"].agg(set)
    dropped = {iso for iso, bh in bad_haz.items() if bh == all_haz[iso]}   # every hazard infeasible
    keep = ~hr["iso3"].isin(dropped)
    clamped = sorted(hr.loc[neg & keep, "iso3"].unique())
    cols = [c for c in ("fa", "v", "v_ew") if c in hr.columns]
    hr.loc[keep, cols] = hr.loc[keep, cols].clip(lower=0)   # clamp infeasible rows to the 0 floor
    hr.to_csv(hr_path, index=False)
    if clamped:
        print(f"         clamped q1 to feasible floor for {len(clamped)} countries "
              f"{clamped[:8]}{'…' if len(clamped) > 8 else ''}", flush=True)
    if dropped:
        drop_isos_from_inputs(outdir, dropped)
    return dropped


def run_scenario(paper_root: str, settings: dict, outdir: str, is_q1: bool = False) -> set:
    """Run one scenario (baseline or a policy step) over all countries. Returns dropped ISOs (only for
    q1-scope runs, where every hazard is infeasible)."""
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    settings_file = _write_settings(settings, outdir)
    run_model_step(paper_root, RUN_PREPARE, settings_file)
    dropped = set()
    if is_q1:
        dropped = resolve_q1_feasibility(outdir)
    run_model_step(paper_root, RUN_MODEL, settings_file)
    return dropped


# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", action="store_true",
                    help="Run the baseline. (With no flags at all, baseline AND all series run.)")
    ap.add_argument("--series", nargs="+", choices=list(SERIES),
                    help="Policy series to run. Default (no selection flags): all 9.")
    ap.add_argument("--num-cores", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap steps per series (0 = all). Use e.g. --limit 1 for a quick smoke test.")
    ap.add_argument("--force", action="store_true", help="Re-run even if a run's results.csv exists.")
    args = ap.parse_args()

    # Selection: no flags -> everything; --baseline only -> baseline; --series only -> those series.
    do_baseline = args.baseline or (not args.baseline and not args.series)
    series_to_run = args.series if args.series else ([] if args.baseline else list(SERIES))

    paper_root = resolve_paper_repo()
    chk = subprocess.run(["uv", "run", "--directory", paper_root, "python", "-c", "import unbreakable"],
                         capture_output=True)
    if chk.returncode != 0:
        raise SystemExit(
            f"The model env at {paper_root} cannot import 'unbreakable' (unbreakable-core).\n"
            f"Bootstrap it with:  uv sync --directory {paper_root}")
    print(f"Model repo: {paper_root}\nRunning via: uv run --directory {paper_root}")
    os.makedirs(SIM_OUT, exist_ok=True)

    # One unified job list. The baseline is just the first scenario (no lever, full observables); every
    # policy step is a scenario with one lever off-neutral and trimmed observables.
    jobs = []  # (label, outdir, settings, is_q1)
    if do_baseline:
        jobs.append(("baseline", BASELINE_DIR,
                     build_settings(BASELINE_DIR, args.num_cores), False))
    for sid in series_to_run:
        series = SERIES[sid]
        is_q1 = series.get("scope") == "q1"
        scope_folder = "q1" if is_q1 else ("all" if series["kind"] == "scale" else "share")
        params = series["params"][:args.limit] if args.limit else series["params"]
        for param in params:
            outdir = os.path.join(SIM_OUT, sid, scope_folder, str(param))
            jobs.append((f"{sid} {param}", outdir,
                         build_settings(outdir, args.num_cores, series, param, OBSERVABLES), is_q1))

    for label, outdir, settings, is_q1 in jobs:
        res_csv = os.path.join(outdir, "simulation_outputs", "results.csv")
        if os.path.exists(res_csv) and not args.force:
            print(f"  [cached] {label}")
            continue
        print(f"  [run] {label} cores={args.num_cores}", flush=True)
        try:
            dropped = run_scenario(paper_root, settings, outdir, is_q1)
        except Exception as e:  # keep a long unattended batch going; a failed step retries next run
            print(f"  [FAIL] {label}: {e}", flush=True)
            continue
        if dropped:
            print(f"         dropped {len(dropped)} infeasible q1 countries: "
                  f"{sorted(dropped)[:8]}{'…' if len(dropped) > 8 else ''}")

    print("Done. Raw outputs under simulation_output/. Next: uv run python process.py")


if __name__ == "__main__":
    main()
