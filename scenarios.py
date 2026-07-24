"""
scenarios.py — shared definitions for the produce → process stages of the viewer.

This is the single source of truth for *what scenarios exist* and *how they map to the viewer's
JSON*. It is imported by both:

  * simulate.py  (production)  — reads SERIES + default_settings to know which model runs to execute.
  * process.py   (processing)  — reads SERIES/LEVERS/OUTPUTS to distil results.csv into web/data JSON.

`default_settings()` is a faithful transcription of the model's
`ub_global_socioeconomic_resilience.reproduce_results.default_settings()` (all policy levers neutral).
It is transcribed rather than imported because importing `reproduce_results` executes its module-level
reproduction loops as a side effect (that module has no `__main__` guard). The scientifically
load-bearing baseline parameters below (income_elasticity_eta, discount_rate_rho, hazard_protection,
transfers_regression_params, exclude_countries, …) MUST stay in sync with the model's baseline, or the
viewer's numbers stop matching the published results. process.py's self-validation (recomputing
country risk/resilience from iah+macro and comparing against results.csv) catches any divergence.
"""

# Population-share scopes a policy lever can target.
ALL_SCOPE = [[0, 0.2], [0.2, 0.4], [0.4, 0.6], [0.6, 0.8], [0.8, 1]]
Q1_SCOPE = [[0, 0.2]]

# The five metrics the viewer shows, and their results.csv source columns. Risk fractions and
# resilience are ×100 (matching the baseline processing); recovery (t_reco_95) is years as-is.
OUTPUTS = ["riskAssets", "riskConsumption", "riskWellbeing", "resilience", "recovery"]
RESULT_COLS = {
    "riskAssets": "risk_to_assets",
    "riskConsumption": "risk_to_consumption",
    "riskWellbeing": "risk_to_wellbeing",
    "resilience": "resilience",
    "recovery": "t_reco_95",
}
SCALE_100 = {"riskAssets", "riskConsumption", "riskWellbeing", "resilience"}  # recovery stays in years

# results.csv restricted to what we read; iah/macro trimmed to one real column each (run_model always
# writes all three — an empty list would NOT restrict, so list >= 1 column). Applied to POLICY runs
# only; the baseline run omits `observables` so it emits full iah/macro (process.py needs them for the
# quintile + recovery derivations).
OBSERVABLES = {
    "results": list(RESULT_COLS.values()),
    "iah": ["n"],
    "macro": ["dk_ctry"],
}


def _round_grid(lo, hi, step):
    """Inclusive grid of nicely rounded values from lo to hi (ascending)."""
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 4) for i in range(n + 1)]


# Each series sweeps ONE lever. `params` are the swept, non-identity model runs (ascending policy
# intensity); `identity` is the baseline-equal endpoint taken from the baseline run (not simulated).
# `display`: how the slider labels a param ('reduction' -> (1-p)*100%, 'share' -> p*100%).
SERIES = {
    "exposure_all": {"kind": "scale", "measure": "scale_exposure", "scope": "all",
                     "scale_total": True, "identity": 1.0, "display": "reduction",
                     "params": _round_grid(0.75, 0.99, 0.01)[::-1]},
    "exposure_q1": {"kind": "scale", "measure": "scale_exposure", "scope": "q1",
                    "scale_total": True, "identity": 1.0, "display": "reduction",
                    "params": _round_grid(0.75, 0.99, 0.01)[::-1]},
    "vulnerability_all": {"kind": "scale", "measure": "scale_vulnerability", "scope": "all",
                          "scale_total": True, "identity": 1.0, "display": "reduction",
                          "params": _round_grid(0.75, 0.99, 0.01)[::-1]},
    "vulnerability_q1": {"kind": "scale", "measure": "scale_vulnerability", "scope": "q1",
                         "scale_total": True, "identity": 1.0, "display": "reduction",
                         "params": _round_grid(0.75, 0.99, 0.01)[::-1]},
    "self_employment": {"kind": "scale", "measure": "scale_self_employment", "scope": "all",
                        "identity": 1.0, "display": "reduction",
                        "params": _round_grid(0.50, 0.98, 0.02)[::-1]},
    "non_diversified_income": {"kind": "scale", "measure": "scale_non_diversified_income",
                               "scope": "all", "identity": 1.0, "display": "reduction",
                               "params": _round_grid(0.50, 0.98, 0.02)[::-1]},
    "gini": {"kind": "scale", "measure": "scale_gini_index", "scope": None,
             "identity": 1.0, "display": "reduction", "params": _round_grid(0.50, 0.98, 0.02)[::-1]},
    "pds_uniform": {"kind": "pds", "variant": "uniform:0.2", "identity": 0.0, "display": "share",
                    "params": _round_grid(0.05, 0.75, 0.05)},
    "pds_proportional": {"kind": "pds", "variant": "proportional", "identity": 0.0, "display": "share",
                         "params": _round_grid(0.05, 0.75, 0.05)},
}

# Frontend-facing lever grouping (6 cards; scope/variant toggles pick among the 9 series).
LEVERS = [
    {"key": "vulnerability", "label": "Reduce total vulnerability", "kind": "scale",
     "series": {"all": "vulnerability_all", "q1": "vulnerability_q1"}, "scopes": ["all", "q1"]},
    {"key": "exposure", "label": "Reduce total exposure", "kind": "scale",
     "series": {"all": "exposure_all", "q1": "exposure_q1"}, "scopes": ["all", "q1"]},
    {"key": "self_employment", "label": "Reduce self-employment", "kind": "scale",
     "series": {"all": "self_employment"}, "scopes": ["all"]},
    {"key": "non_diversified_income", "label": "Diversify income", "kind": "scale",
     "series": {"all": "non_diversified_income"}, "scopes": ["all"]},
    {"key": "gini", "label": "Reduce income inequality", "kind": "scale",
     "series": {"all": "gini"}, "scopes": ["all"]},
    {"key": "pds", "label": "Disaster aid", "kind": "pds",
     "variants": {"uniform": "pds_uniform", "proportional": "pds_proportional"},
     "variantLabels": {"uniform": "Post-disaster support", "proportional": "Insurance"}},
]


def default_settings(num_cores):
    """Baseline model settings — faithfully transcribed from the model's
    ``reproduce_results.default_settings()`` (all policy levers neutral). See the module docstring for
    why this is transcribed rather than imported, and why these values are load-bearing."""
    full_scope = [[0, 0.2], [0.2, 0.4], [0.4, 0.6], [0.6, 0.8], [0.8, 1]]
    return {
        "model_params": {
            "outpath": "",
            "zero_rp": 2,
            "optimization_params": {"num_cores": num_cores, "min_lambda": 0.05,
                                    "max_lambda": 100, "tolerance": 0.01},
            "run_params": {"verbose": False},
            "pds_params": {
                "pds_variant": "no", "pds_targeting": "perfect", "pds_borrowing_ability": "unlimited",
                "covered_loss_share": 0.0, "pds_lending_rate": 0.05, "pds_scope": full_scope,
            },
        },
        "scenario_params": {
            "run_params": {
                "recompute": False, "recompute_hazard_protection": False, "recompute_wb_data": False,
                "download": False, "verbose": False, "countries": "all", "hazards": "all",
                "exclude_countries": ["THA", "LUX"], "resolution": 0.2, "pip_reference_year": 2021,
                "include_poverty_data": False, "poverty_line": 3.0,
            },
            "macro_params": {
                "income_elasticity_eta": 1.5, "discount_rate_rho": 0.06, "axfin_impact": 0.1,
                "reduction_vul": 0.2, "reconstruction_capital": "self_hous", "early_warning_file": None,
            },
            "hazard_params": {"hazard_protection": "FLOPROS", "no_exposure_bias": False,
                              "fa_threshold": 0.99},
            "data_params": {"transfers_regression_params": {
                "type": "LassoCV",
                "features": ["GDP_{pc}", "REM", "SOC", "UNE", "income_group", "region", "FSY"]}},
            "policy_params": {
                "scale_self_employment": {"parameter": 1, "scope": full_scope},
                "scale_non_diversified_income": {"parameter": 1, "scope": full_scope},
                "min_diversified_share": {"parameter": 0, "scope": full_scope},
                "scale_income": {"parameter": 1, "scope": full_scope},
                "scale_liquidity": {"parameter": 1, "scope": full_scope},
                "scale_exposure": {"parameter": 1, "scope": full_scope, "scale_total": False},
                "scale_vulnerability": {"parameter": 1, "scope": full_scope, "scale_total": False},
            },
        },
    }
