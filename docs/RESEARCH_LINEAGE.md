# Research Lineage

## Purpose

This document records the red line of the thesis repository so future work can distinguish:

- the canonical current implementation path;
- important historical branches that still matter methodologically;
- generated artifacts that should not be confused with source-level thesis progress.

It is based on the existing repository docs and the phase3/phase4 lineage and retention analysis. It is not a substitute for direct inspection of every run folder, notebook output, or large artifact.

## Canonical Current Path

The current canonical path through the repository is:

1. data cleaning;
2. standard hourly day-ahead forecasting;
3. quarter-hour extension with explicit observed-vs-counterfactual separation;
4. scenario generation and scenario diagnostics;
5. hydrogen selected-week optimisation through the command centre.

In practical terms, the current best-supported optimisation path is:

- hourly;
- `D_only`;
- `DA_only`;
- hydrogen test case;
- selected regimes / selected weeks;
- risk-neutral command-centre execution.

The main current blocker is upstream scenario support mismatch, not missing MILP infrastructure.

## Stage 1: Data Cleaning And Feature Preparation

The earliest stable implementation layer is the cleaning pipeline:

- `scripts/Data/01_cleaning/day_ahead_prices_pipeline.py`
- `scripts/Data/01_cleaning/entsoe_system_features_pipeline.py`

This layer prepares the cleaned DA price tables and ENTSO-E feature families that feed the forecasting stack. The effective baseline input store is still `data/01_cleaned/`, even though its long-term tracking policy is not yet frozen.

This stage matters because later forecasting and optimisation logic inherit:

- UTC-internal timestamp handling;
- local-market timing semantics;
- known-at / availability logic;
- the separation between observed truth and forecastable inputs.

## Stage 2: Hourly Day-Ahead Forecasting

The standardised hourly forecasting stack lives under:

- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/`

The core forecasting progression is an FS ladder:

- `FS0`: naive baselines;
- `FS1`: endogenous LEAR / XGBoost foundation;
- `FS2`: richer benchmark and shortlist layer;
- `FS3`: exogenous feature-family expansion and ordered comparison.

This progression matters because the thesis did not jump directly to the final model comparison. It added complexity stepwise and used intermediate stages to decide:

- which model families remained competitive;
- which feature strategies were worth carrying forward;
- which branches were dropped or demoted.

The active hourly interpretation layer appears to culminate in:

- `23_fs3_decision_relevant_forecast_evaluation.ipynb`
- `24_final_conclusion_and_best_model.ipynb`

Those notebooks should be treated as interpretation layers on top of the code-first hourly package, not as the canonical implementation by themselves.

## Hourly D-only DA model selection and scenario-count sensitivity, June 2026

The hourly `D_only` day-ahead forecasting stage was frozen in June 2026 for downstream optimisation reuse. The final selected model is:

- `LEAR Strict D-only 1092 repaired anchor`

The frozen main scenario setting is:

- `30` scenarios per model-origin-day
- common observed support from `2024-10-01` to `2025-09-25`
- `307` complete delivery days

The key evidence locations are:

- three-model model-selection bundle:
  `data/02_Forecasting/01_DA_prices/hourly_da/model_selection_evidence/model_selection_3model_common_observed_20260611_150137/`
- governed economic comparison run:
  `scripts/Data/03_Hydrogen_Test_Case/runs/20260611_135643_common_observed_3model_30scen_dam_only/`
- LEAR Strict `30`-vs-`75` scenario-count sensitivity:
  `data/03_Hydrogen_Test_Case/dam_only_sensitivity/lear_strict_scenario_count_sensitivity_20260611_172625/`

The compact handoff record is:

- `docs/forecasting/hourly_donly_da_model_selection_handoff_v1.md`

Final caveat:

- `30` scenarios remain the main tractability setting for thesis workflow continuity.
- `75` scenarios improve scenario coverage and realised economics for LEAR Strict on the same support, but they are materially heavier computationally and do not reopen the three-model ranking.

This freeze closes the hourly `D_only` model-selection stage as the upstream input choice for the next research stage: steel-plant MILP model development.

## Why FS0 / FS1 / FS2 / FS3 Still Matter

The FS ladder is not only historical naming. It explains why many files still exist:

- `FS0` preserves the official naive reference and the basis for relative metrics such as `rMAE`.
- `FS1` establishes the endogenous benchmark foundation.
- `FS2` is where shortlisting starts to matter in a more serious way.
- `FS3` carries the exogenous feature-family logic, pruning, and decision-relevant comparison work that feeds later scenario and optimisation thinking.

Future cleanup should not flatten these stages into "old notebooks" or "obsolete scripts" without preserving the methodology they represent.

## Stage 3: LEAR Strict, Lago, And Extended Forecast Comparison Work

A later forecasting branch adds work that is not the canonical default path, but remains methodologically important:

- LEAR Strict;
- Lago-style six-year benchmark work;
- D-only versus `D_plus_4` applicability and support analysis;
- additional decision-relevant forecast metrics;
- quarter-hour anchor and support diagnostics.

This branch appears mostly in:

- `scripts/Data/02_Forecasting/01_DA_prices/one_off/2026-05_campaign/`
- `docs/forecasting/lago_lear_six_year_benchmark.md`
- compact root-level LEAR Strict / backbone-routing summaries.

These files matter because they explain:

- why LEAR Strict became relevant even outside the main hourly stack;
- why support/routing issues appeared in quarter-hour extension work;
- why some bounded scripts were intentionally moved out of the canonical runner surface rather than simply deleted.

## Stage 4: Quarter-Hour Extension

The quarter-hour branch is not just a minor forecasting variant. It became a structured extension with two distinct tracks:

1. observed-market quarter-hour forecasting;
2. counterfactual full-year quarter-hour support for downstream experiments.

This distinction is central.

Observed-market quarter-hour work is tied to the observed Dutch 15-minute market period and must be treated as observed-target forecasting work.

Counterfactual quarter-hour work uses a frozen synthetic actual-path layer for downstream comparison and optimisation support. It must remain labelled counterfactual or synthetic, not observed truth.

The earlier phase workflow still matters because it explains how the repository reached this separation:

- phase01 through phase07 quarter-hour workflow;
- 15-minute extension notebooks;
- later canonical observed and counterfactual runners.

Future cleanup must preserve this observed-vs-counterfactual distinction.

## Stage 5: Scenario Generation

Scenario generation is implemented for both hourly and quarter-hour work, but it remains methodologically caveated.

The current doc layer indicates:

- scenario generation is implemented and reproducible at code level;
- a validation-selected hourly `D_only` scenario configuration exists;
- scenario quality is still not thesis-final, especially for coverage and tails.

This matters for later optimisation interpretation:

- scenario generation is in scope;
- scenario probabilities are required;
- scenario undercoverage is a known methodological warning;
- exploratory optimisation can proceed with caveats;
- final robust risk claims should not ignore these caveats.

## Stage 6: Hydrogen Optimisation

The active frontier of the repository is now the hydrogen optimisation workstream.

The current code/governance surface is built around:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/`
- `scripts/Data/03_Hydrogen_Test_Case/configs/`
- `docs/optimisation/`
- hydrogen-specific audit and methodology docs.

The implementation appears to have progressed in phases:

1. deterministic physical schedule logic;
2. baseline audit of the hydrogen model;
3. schedule-to-bid bridge;
4. bidding and clearing primitives;
5. redispatch after clearing;
6. real-scenario integration dry runs;
7. selected-week support and reporting governance;
8. command-centre hardening.

This is why the repository now contains both:

- optimisation code and tests;
- a substantial governance/reporting layer around selected weeks, run contracts, and command-centre options.

## Hydrogen mFRR/DAM sandbox freeze, June 2026

The hydrogen `mFRR` / DAM integration work is now frozen as a sandbox handoff rather than extended toward a full activation model before the steel process model exists.

The compact handoff record is:

- `docs/optimisation/mfrr_dam_integration_handoff_v1.md`

The compact forecasting/proxy evidence registry for the Dutch incident-reserve capacity layer is:

- `docs/forecasting/mfrr_capacity_metric_registry_v1.md`

This freeze preserves:

- the accepted/rejected capacity-result interface;
- `EUR/MW/ISP` plus `contract_isp_count` handling;
- ISP-to-hourly reserve-obligation mapping;
- the DAM reserve-obligation hook in the stochastic hourly bidding model;
- the boundary that future steel work should reuse the market interfaces and validation logic, but not the hydrogen-specific production or activation physics.

## Stage 7: CVaR And Risk-Aversion Work

CVaR is not missing from the repository. It exists as an implemented branch with:

- runners;
- source modules;
- tests;
- supporting methodology notes.

However, it is not yet the command-centre-hardened default path. The current hardened default remains the risk-neutral selected-week hydrogen backend.

This distinction is important:

- CVaR work is methodologically relevant and should be preserved;
- future cleanup should not treat it as a failed side branch;
- at the same time, users should not assume the command centre currently exposes CVaR as the default production path.

## Important Historical Attempts To Preserve

The following are not the canonical current path, but they remain part of the research lineage:

- pre-standardisation forecasting scaffolds and notebook archives;
- the May 2026 forecasting campaign bundle;
- the Lago / LEAR Strict branch;
- quarter-hour phase workflow;
- scenario calibration and undercoverage audit work;
- hydrogen support/readiness diagnostics;
- CVaR validation and anomaly work;
- legacy mixed selected-week governance files.

These attempts should be summarised before any cleanup that might hide why they existed.

## What This Means For Cleanup

Cleanup in this repository is not only about removing output volume. It must preserve:

- the canonical current path;
- the methodological reasoning behind noncanonical branches;
- the distinction between source-level thesis progress and generated artifacts.

In practice:

- compact code, configs, tests, and stable docs belong in Git;
- large run folders, exports, solver logs, and generated tables should stay outside Git;
- important historical attempts should be summarised before their scattered artifacts are ignored or archived;
- `data/01_cleaned/` requires a separate tracked-data policy rather than bulk cleanup.
