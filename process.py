#!/usr/bin/env python3
"""
process.py — PROCESSING stage: distil the raw model outputs under ``simulation_output/`` into the
compact JSON the static ``web/`` explorer fetches. Pure pandas — it never runs the model.

Two parts, run in order:

  1. BASELINE  ``simulation_output/0_baseline``  ->  ``web/data/explorer_data.json``
     Country-level headline numbers are taken verbatim from ``results.csv``. Per-quintile values are
     derived from ``iah.csv`` by replicating the model's own aggregation pipeline
     (agg_to_event_level -> average_over_rp with FLOPROS protection -> sum over hazards ->
     calc_risk_and_resilience_from_k_w). ``average_over_rp`` is copied verbatim from the model repo so
     the annualisation matches the published results. A self-validation recomputes the country
     risk/resilience from iah+macro and checks it against results.csv (max rel err ≈ 1e-13) — this also
     guards against scenarios.default_settings drifting from the model baseline.

  2. POLICIES  ``simulation_output/<series>/<scope>/<param>``  ->  ``web/data/policies/<ISO>.json``
     + ``manifest.json``. Each series' index-0 (identity/baseline) endpoint is the baseline just
     computed above, so there is no cross-file build-order dependency.

    uv run python process.py
"""
from __future__ import annotations

import argparse
import json
import os
from itertools import product

import numpy as np
import pandas as pd

from scenarios import LEVERS, OUTPUTS, RESULT_COLS, SCALE_100, SERIES

ROOT = os.path.dirname(os.path.abspath(__file__))
SIM_OUT = os.path.join(ROOT, "simulation_output")
BASE = os.path.join(SIM_OUT, "0_baseline")
WEB_DATA = os.path.join(ROOT, "web", "data")
OUT_FILE = os.path.join(WEB_DATA, "explorer_data.json")
POLICIES_DIR = os.path.join(WEB_DATA, "policies")

ZERO_RP = 2  # natural protection level (settings.yml -> hazard_params.zero_rp)
EVENT_LEVEL = ["iso3", "hazard", "rp"]

INCOME_LABELS = {
    "LICs": "Low income",
    "LMICs": "Lower-middle income",
    "UMICs": "Upper-middle income",
    "HICs": "High income",
}
INCOME_ORDER = ["LICs", "LMICs", "UMICs", "HICs"]
REGION_LABELS = {
    "EAP": "East Asia & Pacific",
    "ECA": "Europe & Central Asia",
    "LAC": "Latin America & Caribbean",
    "MNA": "Middle East & North Africa",
    "NMA": "North America",
    "SAR": "South Asia",
    "SSA": "Sub-Saharan Africa",
}
INCOME_CAT_TO_Q = {0.2: 1, 0.4: 2, 0.6: 3, 0.8: 4, 1.0: 5}


# --------------------------------------------------------------------------------------
# average_over_rp — copied verbatim from unbreakable/misc/helpers.py (model repo) so the
# return-period annualisation exactly matches the published results.
# --------------------------------------------------------------------------------------
def average_over_rp(d_in, protection_=None, zero_rp=2):
    """Aggregate outputs over return periods, weighted by probabilities."""
    if isinstance(d_in, pd.Series):
        df_in = d_in.to_frame()
    else:
        df_in = d_in.copy()

    if 'rp' not in df_in.index.names:
        raise ValueError("Need index level 'rp' to average over return periods.")

    if zero_rp is not None:
        if zero_rp <= 0:
            raise ValueError("zero_rp should be > 0")
        elif zero_rp not in df_in.index.get_level_values('rp'):
            new_index = df_in.index.droplevel("rp").unique()
            new_index = pd.MultiIndex.from_arrays(
                [new_index.get_level_values(l) for l in range(new_index.nlevels)] + [[zero_rp] * len(new_index)],
                names=list(new_index.names) + ['rp']
            )
            new_rows = pd.DataFrame(0, index=new_index, columns=df_in.columns).reorder_levels(df_in.index.names)
            df_in = pd.concat([df_in, new_rows]).sort_index().copy()
        else:
            print(f"Warning: zero_rp={zero_rp} was provided for return period averaging, but return period is "
                  f"already in df_in. Ignoring zero_rp.")

    group_levels = [idxn for idxn in df_in.index.names if idxn != 'rp']

    if protection_ is not None:
        if isinstance(protection_, pd.DataFrame):
            protection = protection_.protection.copy().round(3)
        else:
            protection = protection_.copy().round(3)
        protection = protection[protection > zero_rp]

        common_index = protection.index.intersection(df_in.droplevel(list(np.setdiff1d(df_in.index.names, protection.index.names))).index.unique())
        protection = protection.loc[common_index]

        protected_index = protection.rename('rp').to_frame().set_index('rp', append=True).index
        missing_levels = list(set(df_in.index.names) - set(protected_index.names))
        for missing_level in missing_levels:
            protected_index = pd.MultiIndex.from_tuples(
                [(*t, m) for t, m in product(list(protected_index.to_flat_index()), list(df_in.index.get_level_values(missing_level).unique()))],
                names=list(protected_index.names) + [missing_level]
            )
        protected_index.reorder_levels(df_in.index.names)
        protected_levels = pd.DataFrame(np.nan, index=protected_index.difference(df_in.index), columns=df_in.columns)

        df_in = pd.concat([df_in, protected_levels]).sort_index()
        if group_levels:
            idx_order = df_in.index.names
            df_in = df_in.reset_index('rp').groupby(group_levels).apply(
                lambda g: g.reset_index().drop(columns=group_levels).set_index('rp').interpolate(method='index')
            ).reorder_levels(idx_order).sort_index()
        else:
            df_in = df_in.sort_index().interpolate(method='index')

        df_in = df_in[((df_in.reset_index('rp').rp - protection).fillna(0) >= 0).values]

    def calculate_rp_average(g):
        g_ = g.sort_index().copy()
        g_.loc[np.inf] = g_.iloc[-1]
        rp_weights = pd.Series(1 / g_.index, index=g_.index).diff(-1).loc[g.sort_index().index]
        return pd.DataFrame((g_.values[:-1] + g_.values[1:]) / 2, index=g.sort_index().index, columns=g_.columns).mul(rp_weights, axis=0).sum()

    res = df_in.groupby(group_levels, group_keys=False).apply(lambda g: calculate_rp_average(g.droplevel(group_levels)))
    res.loc[d_in.droplevel('rp').index.unique().difference(res.index)] = 0

    if isinstance(d_in, pd.Series):
        res.name = d_in.name
        res = res.squeeze()
    return res


# --------------------------------------------------------------------------------------
# calculate_average_recovery_duration — copied verbatim from unbreakable/misc/helpers.py, used only as a
# FALLBACK when results.csv predates the country-level `t_reco_95` column (unbreakable-core < 0.1.2).
# --------------------------------------------------------------------------------------
def calculate_average_recovery_duration(df, aggregation_level, hazard_protection_=None, agg_rp=None):
    df = df[['n', 't_reco_95']].xs('a', level='affected_cat').copy()

    if agg_rp is not None:
        if hazard_protection_ is not None:
            df['rp'] = df.reset_index().rp.values
            df = pd.merge(df, hazard_protection_, left_index=True, right_index=True, how='left')
            df.loc[df[df.rp <= df.protection].index, 'n'] = 0
            df = df.drop(columns=['protection', 'rp'])
        return df.xs(agg_rp, level='rp').groupby(aggregation_level).apply(
            lambda x: np.average(x.t_reco_95, weights=x.n) if np.sum(x.n) > 0 else 0).squeeze().rename('t_reco_avg')

    if type(aggregation_level) is str:
        aggregation_level = [aggregation_level]

    df_ = (df.t_reco_95 * df.n).groupby(aggregation_level + ['rp']).sum() / df.n.groupby(aggregation_level + ['rp']).sum()
    df_[df.n.groupby(aggregation_level + ['rp']).sum() == 0] = 0
    df = df_.rename('t_reco_avg')
    if 1 not in df.index.get_level_values('rp'):
        rp_1 = df.xs(df.index.get_level_values('rp').min(), level='rp').copy().to_frame()
        rp_1['rp'] = 1
        rp_1 = rp_1.set_index('rp', append=True).reorder_levels(df.index.names).squeeze()
        df = pd.concat([df, rp_1]).sort_index()

    return_periods = df.index.get_level_values('rp').unique()
    rp_probabilities = pd.Series(1 / return_periods - np.append(1 / return_periods, 0)[1:], index=return_periods)
    probabilities = pd.Series(data=df.reset_index('rp').rp.replace(rp_probabilities).values, index=df.index,
                              name='probability').to_frame()

    if hazard_protection_ is not None:
        probabilities['rp'] = probabilities.reset_index().rp.values
        probabilities = pd.merge(probabilities, hazard_protection_, left_index=True, right_index=True, how='left')
        probabilities.loc[probabilities[probabilities.rp <= probabilities.protection].index, 'probability'] = 0
        probabilities = probabilities.drop(columns=['protection', 'rp'])

    res = pd.merge(df, probabilities, left_index=True, right_index=True, how='left')
    res = ((res.t_reco_avg * res.probability).groupby(aggregation_level).sum()
           / res.probability.groupby(aggregation_level).sum()).rename('t_reco_avg')
    if type(df) is pd.Series:
        res.name = df.name
    return res


def recovery_by_country(results, iah, protection):
    """Country-level 95% recovery duration (years), indexed by iso3. Prefer the `t_reco_95` column
    (unbreakable-core >= 0.1.2); else derive it from iah (ln(1/0.05)/lambda_h, pop-weighted)."""
    ref = results.set_index("iso3")
    if "t_reco_95" in ref.columns:
        return ref["t_reco_95"]
    idx = ["iso3", "hazard", "rp", "income_cat", "affected_cat", "helped_cat"]
    cat = iah.set_index(idx).copy()
    cat["t_reco_95"] = np.log(1 / 0.05) / cat["lambda_h"]
    return calculate_average_recovery_duration(cat, "iso3", protection, None)


# --------------------------------------------------------------------------------------
def load_inputs():
    results = pd.read_csv(os.path.join(BASE, "simulation_outputs", "results.csv"))
    iah = pd.read_csv(os.path.join(BASE, "simulation_outputs", "iah.csv"))
    macro = pd.read_csv(os.path.join(BASE, "simulation_outputs", "macro.csv"))
    haz_prot = pd.read_csv(os.path.join(BASE, "model_inputs", "scenario__hazard_protection.csv"))
    coverage = pd.read_csv(os.path.join(BASE, "model_inputs", "data_coverage.csv"))
    return results, iah, macro, haz_prot, coverage


def protection_frame(haz_prot):
    return haz_prot.set_index(["iso3", "hazard"])[["protection"]]


def annualise(event_df, protection):
    """average_over_rp then sum over hazard -> one row per remaining group key."""
    avg = average_over_rp(event_df, protection, zero_rp=ZERO_RP)
    keep = [n for n in avg.index.names if n != "hazard"]
    return avg.groupby(level=keep).sum()


def calc_risk(df, gdp_pc, eta):
    """Replicates calc_risk_and_resilience_from_k_w for the columns we surface."""
    w_prime = gdp_pc ** (-eta)
    out = pd.DataFrame(index=df.index)
    out["risk_to_wellbeing"] = (df["dw"] / w_prime) / gdp_pc
    out["risk_to_consumption"] = df["dc"] / gdp_pc
    out["resilience"] = (w_prime * df["dk"]) / df["dw"]
    out["risk_to_assets"] = out["resilience"] * out["risk_to_wellbeing"]
    return out


def country_meta(results):
    """gdp_pc_pp and income_elasticity_eta per country, indexed by iso3."""
    m = results.set_index("iso3")
    return m["gdp_pc_pp"], m["income_elasticity_eta"]


def validate_country_level(results, iah, macro, protection):
    """Recompute country risk/resilience from iah+macro; compare with results.csv."""
    gdp_pc, eta = country_meta(results)

    iah_idx = iah.set_index(EVENT_LEVEL)
    dw = (iah_idx["dw"] * iah_idx["n"]).groupby(level=EVENT_LEVEL).sum()
    dc = (iah_idx["dc"] * iah_idx["n"]).groupby(level=EVENT_LEVEL).sum()
    dk = macro.set_index(EVENT_LEVEL)["dk_ctry"]

    out = pd.concat({"dk": dk, "dw": dw, "dc": dc}, axis=1)
    out = annualise(out, protection)

    risk = calc_risk(out, gdp_pc.reindex(out.index), eta.reindex(out.index))
    ref = results.set_index("iso3")

    diffs = {}
    for col in ["risk_to_assets", "risk_to_wellbeing", "resilience"]:
        a = risk[col].reindex(ref.index)
        b = ref[col]
        rel = ((a - b).abs() / b.abs().clip(lower=1e-12))
        diffs[col] = float(rel.max())
    return diffs


def build_quintiles(iah, results, protection):
    """Per-quintile annualised risk/resilience + income share, indexed (iso3, income_cat)."""
    gdp_pc, eta = country_meta(results)

    level_q = ["iso3", "hazard", "rp", "income_cat"]
    iah_idx = iah.set_index(level_q)
    weighted = iah_idx[["dk", "dw", "dc"]].mul(iah_idx["n"], axis=0)
    event_q = weighted.groupby(level=level_q).sum()

    annual = annualise(event_q, protection)  # -> (iso3, income_cat)

    iso = annual.index.get_level_values("iso3")
    gdp = gdp_pc.reindex(iso).to_numpy()
    et = eta.reindex(iso).to_numpy()
    gdp = pd.Series(gdp, index=annual.index)
    et = pd.Series(et, index=annual.index)

    risk_q = calc_risk(annual, gdp, et)

    # income share is constant per (iso3, income_cat)
    share = iah.groupby(["iso3", "income_cat"])["income_share"].first()
    risk_q["income_share"] = share.reindex(risk_q.index)
    return risk_q


def coverage_counts(coverage):
    cols = [c for c in coverage.columns if c not in ("iso3", "name", "region", "income_group")]
    sub = coverage.set_index("iso3")[cols]
    n_imputed = (sub == "imputed").sum(axis=1)
    n_avail = (sub == "available").sum(axis=1)
    n_total = n_imputed + n_avail
    return n_imputed, n_total


def build_baseline():
    """Process simulation_output/0_baseline -> web/data/explorer_data.json.
    Returns (baseline_metrics {iso: {OUTPUT: value}}, iso_order) for the policy identity endpoints."""
    if not os.path.isdir(BASE):
        raise SystemExit(f"Missing {BASE}. Run: uv run python simulate.py --baseline")
    results, iah, macro, haz_prot, coverage = load_inputs()
    protection = protection_frame(haz_prot)

    print(f"Loaded {len(results)} countries from {os.path.relpath(BASE, ROOT)}/simulation_outputs/results.csv")

    diffs = validate_country_level(results, iah, macro, protection)
    print("Validation (max relative error vs results.csv):")
    for k, v in diffs.items():
        flag = "OK" if v < 0.01 else "WARN"
        print(f"  {k:20s} {v:.3e}  [{flag}]")

    quint = build_quintiles(iah, results, protection)
    recovery = recovery_by_country(results, iah, protection)
    n_imputed, n_total = coverage_counts(coverage)
    if "t_reco_95" in results.columns:
        print("Recovery duration: read t_reco_95 column from results.csv")
    else:
        print("Recovery duration: t_reco_95 absent from results.csv; derived from iah.csv (fallback)")

    countries = []
    for _, row in results.iterrows():
        iso = row["iso3"]
        qrows = []
        if iso in quint.index.get_level_values("iso3"):
            sub = quint.xs(iso, level="iso3")
            for income_cat, q in sorted(INCOME_CAT_TO_Q.items()):
                if income_cat in sub.index:
                    r = sub.loc[income_cat]
                    qrows.append({
                        "q": q,
                        "incomeShare": float(r["income_share"]) * 100.0,
                        "riskWellbeing": float(r["risk_to_wellbeing"]) * 100.0,
                        "riskAssets": float(r["risk_to_assets"]) * 100.0,
                    })
        countries.append({
            "iso": iso,
            "name": row["name"],
            "region": row["region"],
            "regionLabel": REGION_LABELS.get(row["region"], row["region"]),
            "incomeGroup": row["income_group"],
            "incomeLabel": INCOME_LABELS.get(row["income_group"], row["income_group"]),
            "pop": None if pd.isna(row["pop"]) else float(row["pop"]),
            "gdppc": None if pd.isna(row["gdp_pc_pp"]) else float(row["gdp_pc_pp"]),
            "gnipc": None if pd.isna(row["gni_pc_pp"]) else float(row["gni_pc_pp"]),
            "gini": None if pd.isna(row["gini_index"]) else float(row["gini_index"]),
            "riskAssets": float(row["risk_to_assets"]) * 100.0,
            "riskConsumption": float(row["risk_to_consumption"]) * 100.0,
            "riskWellbeing": float(row["risk_to_wellbeing"]) * 100.0,
            "resilience": float(row["resilience"]) * 100.0,
            "recovery": (None if iso not in recovery.index or pd.isna(recovery.loc[iso])
                         else float(recovery.loc[iso])),
            "imputedInputs": int(n_imputed.get(iso, 0)),
            "totalInputs": int(n_total.get(iso, 0)),
            "quint": qrows,
        })

    payload = {
        "generatedFrom": "simulation_output/0_baseline",
        "framework": "Global Unbreakable model",
        "incomeOrder": INCOME_ORDER,
        "incomeLabels": INCOME_LABELS,
        "regionLabels": REGION_LABELS,
        "countries": countries,
        "meta": {
            "nCountries": len(countries),
            "hazards": sorted(macro["hazard"].unique().tolist()),
            "returnPeriods": sorted(macro["rp"].unique().tolist()),
            "notes": {
                "recovery": "95% recovery duration (years), population-weighted over affected households.",
                "policies": "Single-policy scenarios are produced by simulate.py into simulation_output/ "
                            "and assembled here into web/data/policies/.",
            },
        },
    }

    os.makedirs(WEB_DATA, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    n_q = sum(1 for c in countries if c["quint"])
    print(f"Wrote {os.path.relpath(OUT_FILE, ROOT)}: {len(countries)} countries "
          f"({n_q} with quintile breakdown), {os.path.getsize(OUT_FILE) / 1024:.0f} KiB")

    baseline = {c["iso"]: {m: c.get(m) for m in OUTPUTS} for c in countries}
    iso_order = [c["iso"] for c in countries]
    return baseline, iso_order


# --------------------------------------------------------------------------------------
def extract_metrics(res):
    """results.csv DataFrame -> {iso: {metric: value}} in viewer units (risk/resilience ×100)."""
    out = {}
    for iso, row in res.iterrows():
        vals = {}
        ok = True
        for m in OUTPUTS:
            col = RESULT_COLS[m]
            v = row.get(col, np.nan)
            if pd.isna(v) or np.isinf(v):
                ok = False
                vals[m] = None
            else:
                vals[m] = float(v) * (100.0 if m in SCALE_100 else 1.0)
        out[iso] = vals if ok else {m: None for m in OUTPUTS}
    return out


def collect_policy_metrics():
    """Read every simulation_output/<series>/<scope>/<param>/…/results.csv that exists.
    Returns metrics_by_series[sid][param] = {iso: {metric: value|None}}. Missing params are simply
    absent (assembled as null)."""
    metrics = {sid: {} for sid in SERIES}
    for sid, series in SERIES.items():
        is_q1 = series.get("scope") == "q1"
        scope_folder = "q1" if is_q1 else ("all" if series["kind"] == "scale" else "share")
        for param in series["params"]:
            res_csv = os.path.join(SIM_OUT, sid, scope_folder, str(param), "simulation_outputs", "results.csv")
            if not os.path.exists(res_csv):
                continue
            res = pd.read_csv(res_csv, index_col=0)
            metrics[sid][param] = extract_metrics(res)
        n = len(metrics[sid])
        if n:
            print(f"  policies: {sid}: {n}/{len(series['params'])} steps found")
    return metrics


def assemble(baseline, iso_order, metrics_by_series):
    """Write web/data/policies/<ISO>.json. A series is included only if at least one step was found;
    within an included series, missing steps are stored as null and the frontend clamps."""
    os.makedirs(POLICIES_DIR, exist_ok=True)
    n_series_written = 0
    for iso in iso_order:
        doc = {"iso": iso, "series": {}, "baseline": baseline[iso]}
        for sid, series in SERIES.items():
            if not metrics_by_series[sid]:
                continue
            params = [series["identity"]] + list(series["params"])
            col = {m: [baseline[iso][m]] for m in OUTPUTS}  # index 0 = identity/baseline
            for param in series["params"]:
                vals = metrics_by_series[sid].get(param, {}).get(iso, {m: None for m in OUTPUTS})
                for m in OUTPUTS:
                    col[m].append(vals[m])
            entry = {"param": params, "display": series["display"]}
            entry.update({m: col[m] for m in OUTPUTS})
            doc["series"][sid] = entry
        with open(os.path.join(POLICIES_DIR, f"{iso}.json"), "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        n_series_written = max(n_series_written, len(doc["series"]))
    print(f"Wrote {len(iso_order)} country files to {os.path.relpath(POLICIES_DIR, ROOT)} "
          f"(up to {n_series_written} series each)")


def write_manifest():
    manifest = {
        "method": "table",
        "outputs": OUTPUTS,
        "levers": LEVERS,
        "note": "Pre-computed single-policy scenarios (one lever at a time) from full model runs; "
                "the frontend does a table lookup. Extensible to per-country emulators (method).",
    }
    with open(os.path.join(POLICIES_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"Wrote {os.path.relpath(os.path.join(POLICIES_DIR, 'manifest.json'), ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-policies", action="store_true",
                    help="Only (re)build explorer_data.json from the baseline; skip policy assembly.")
    args = ap.parse_args()

    baseline, iso_order = build_baseline()
    if args.skip_policies:
        return
    metrics = collect_policy_metrics()
    if any(metrics[sid] for sid in SERIES):
        assemble(baseline, iso_order, metrics)
        write_manifest()
    else:
        print("No policy runs found under simulation_output/ — skipping policies. "
              "Run: uv run python simulate.py")


if __name__ == "__main__":
    main()
