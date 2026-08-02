# Research Lineage

## Purpose

This document records the red line of the thesis repository so future work can distinguish:

- the canonical current implementation path;
- important historical branches that still matter methodologically;
- generated artifacts that should not be confused with source-level thesis progress.

It is based on the existing repository docs and the phase3/phase4 lineage and retention analysis. It is not a substitute for direct inspection of every run folder, notebook output, or large artifact.

## Canonical Current Path

The active thesis implementation frontier is now the C0/C1 steel physical
model. The canonical high-level sequence is:

1. preserve the existing data-cleaning and forecasting lineage;
2. complete deterministic, price-free steel production feasibility;
3. close material, carrier-WAG, represented steam/utility and residual
   reporting boundaries;
4. validate configuration-matched annual-equivalent outputs against the
   canonical anchor register;
5. add deterministic energy costs only after the physical gate;
6. return to DA, scenarios, CVaR and later mFRR only after deterministic steel
   cost optimisation is stable.

The active steel task-start document is
`docs/optimisation/steel/S4/C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md`.
The active feasibility config is
`scripts/Data/04_Steel_Test_Case/configs/steel_quota_driven_physical_feasibility.yaml`.

Hydrogen, hourly/quarter-hour forecasting and scenario work remain important
methodological lineage. They are not the current implementation priority and
must not redirect a steel task to the hydrogen command centre or an old fixed
C0 schedule.

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

The canonical observed-support Strict LEAR D--D+4 finalisation is now the run
`20260729_strict_lear_dplus4_full_a03`. It couples the unchanged hourly Strict
LEAR anchor to the causal QH mean-shape model and exports probability-weighted,
nested 30- and 10-scenario sets on 116 common evaluation origins from 18 March
through 19 July 2026. All hard artifact, timing, probability, nesting, DST, and
hourly/QH parity contracts pass. Evaluation p05--p95 coverage remains below
85%, so the artifacts are optimization-ready but not evidence of calibrated
risk coverage. The compact method and results record is
`docs/forecasting/strict_lear_hourly_qh_dplus4_finalisation.md`.

The accepted family-audit evidence
`20260731_donly_family_audit_s10_s30_v3` records runner hash
`07e97dbf7b464ff4f9dcbcf6f36863b2d324af42ff09088ce62f7c2d48b8c644`
and config hash
`ae9cd3974673c4af669fb6b1ee469522ec94cc2ed05ac46f199e3b0bb698f9a2`.
The later accepted v11 preparation embeds the family-run summary hash, but the
exact historical runner and resolved-config snapshots for those two hashes are
not present in the current workspace. The audit remains accepted generated
evidence; exact source/config replay of that historical invocation is limited.

## Stage 6: Hydrogen Optimisation — Historical Methodological Reference

Hydrogen was the earlier optimisation frontier and remains a reusable
methodological reference. It is not the active thesis implementation path.

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

## Strict LEAR 2026 Hydrogen Horizon/Granularity Evaluation

The 2026 hydrogen comparison is a new thesis-candidate generated-evaluation
lineage. It reuses the frozen Strict LEAR model selection and canonical coupled
hourly/QH D--D+4 artifacts. A causal 2026 D-only support export is classified
as an extension of the selected model, not a new selection run.

Canonical code, config, tests, and the compact method record belong in Git.
The D-only forecast/scenario exports, input-slice caches, rolling optimizer
runs, solver outputs, dispatch tables, and broad comparison tables are
generated local output under governed run roots and remain ignored. The old
307-day runs in the sibling repository are read-only historical evidence and
must never be overwritten or merged into the new common-support results.

Accepted generated-evaluation run:
`20260729_strict_lear_horizon_granularity_full_a01`. Its compact governance
record reports `complete` with all solver, oracle, carryover, quota, and
settlement gates passing. The archived 300-second QH/30 convergence attempt is
diagnostic evidence; the accepted primary QH/30 policy is the uniform
900-second rerun with unchanged model/data inputs and MIP gap. Broad result
tables, figures, dispatch, solver metrics, and forecasts remain generated
local artifacts. Their headline interpretation is maintained in
`docs/optimisation/STRICT_LEAR_HYDROGEN_HORIZON_GRANULARITY_COMPARISON.md`.

The H2 mechanism run `20260731_h2_mechanism_s10_v3` preserves its generated
outputs and forecast-input hashes. Its input manifest records config hash
`8428faeb481446f5435d5a6b15e39c4bea421ac898420ed75437732106f0ab72`,
whereas the current config hashes to
`a37e2f410b2980dbdc6ae4f38887801dd4a74ed28d33c8e9c6d6e617996ebbe8`;
no resolved config or source snapshot with the historical hash was found.
Consequently, the run remains accepted mechanism evidence, but exact config
replay from the present source tree is limited.

## Non-canonical performance evidence -- 2026-07-30

The following artifacts are diagnostic performance evidence and do not replace
the accepted Strict LEAR hydrogen comparison or deterministic steel baseline:

- `data/03_Hydrogen_Test_Case/performance_benchmarks/20260730_optimized_equivalent_a01/`
  -- three consecutive origins, runtime median/p95, 96/96 realised-ledger
  parity; QH speed targets not met.
- `data/03_Hydrogen_Test_Case/performance_benchmarks/20260730_optimized_equivalent_objective_parity_a02/`
  -- one-origin solver-objective/status gate; 40/40 checks pass, including
  eight zero-difference objective comparisons.
- `data/03_Optimisation/performance_benchmarks/20260730_optimized_equivalent_a02/`
  -- active deterministic steel two-replan fixture; 56/56 physical-ledger
  checks pass exactly and both configurations remain within the 10% runtime
  non-regression boundary.

All three use `output_policy = audit`, `run_class = diagnostic_performance` and
`lineage_role = non-canonical performance evidence`. Golden baselines dated
2026-07-20 and 2026-07-29 remain read-only and authoritative for research
results.

## Phase 6B hourly stochastic steel engineering validation -- 2026-07-30

Canonical source consists of the Phase-6B runner, shared steel market module,
frozen YAML config, targeted tests and
`docs/optimisation/steel/S4/C6_PHASE6B_HOURLY_STOCHASTIC_DA_BID_CLEAR_REDISPATCH_GATE.md`.
These wrap the frozen Phase-5K boundary and the read-only Strict LEAR D--D+4
point/S10 artifacts; they do not create or retune forecasting evidence.

Accepted generated evidence is
`steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730`, classified as
`diagnostic_validation` and `thesis-candidate implementation validation, not
economic evaluation`. The governed run and compact comparison bundle remain
ignored local outputs. All 256 checks and 156 solves pass. A03 is numerically
identical to a02 and supersedes it only because a03 includes `fixture_id` in
every consolidated market/result key. Earlier v1/a02 attempts are non-canonical
implementation diagnostics and must not be cited as final evidence.

The lineage validates only an hourly one-day and seven-day engineering chain:
forecast/scenarios, scenario-independent bid curve, realised D clearing, exact
physical redispatch, settlement and complete inventory/production/route state
handoff. It is not a long-run economic evaluation, historical QH backtest,
annual simulation or authorization for QH, CVaR, mFRR, export, ETS or product
revenue. Phase 6A remains read-only historical quantity-only bridge evidence.
