# DA Price Scenario Generation Audit (2026-05-12)

## Current Implementation Summary

### 1) Where scenario generation is implemented
- **Hourly core logic**: `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/scenario_generation.py`
  - Main generation function: `generate_scenario_bundle(...)`
  - Driver script: `scripts/Data/02_Forecasting/01_DA_prices/run_hourly_scenario_generation_with_lear_strict.py`
  - Notebook entrypoint (generated): `notebooks/Data/03_Scenario's/01_da_price_scenario_generation_hourly.ipynb`
- **Quarter-hour core logic**: `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/scenario_generation_qh.py`
  - Main generation function: `run_qh_scenario_generation(...)` / `_generate_scenarios(...)`
  - Driver script: `scripts/Data/02_Forecasting/01_DA_prices/run_15min_qh_scenario_generation.py`
- **Legacy counterfactual path generator (not canonical observed-market probabilistic DA scenarios)**:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase05.py` (`run_phase05_counterfactual_generation`)

### 2) Inputs and outputs
- **Hourly input artifacts**:
  - discovered benchmark prediction runs + external LEAR strict anchor export
  - selected run (latest): `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260511_212611/`
- **Quarter-hour input artifacts**:
  - phase2.7 parity predictions (`phase27_run_dir`) + model3 LEAR strict predictions (`model3_run_dir`)
  - selected run: `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/`
- **Hourly outputs**:
  - `scenario_prices_long.csv`, `scenario_metadata.csv`, `residual_period_table.csv`, `residual_daily_profiles.csv`, `scenario_generation_config.json`, `scenario_generation_run_summary.json`, `scenario_period_quantiles.csv`, `scenario_validation_summary.csv`, `scenario_bank_logs.csv`, `scenario_reduction_summary.csv`
- **Quarter-hour outputs**:
  - `scenario_prices_long.csv(.parquet)`, `scenario_metadata.csv`, `scenario_period_quantiles.csv`, `scenario_validation_summary.csv`, `scenario_generation_config.json`, `scenario_generation_run_summary.json`, `provenance_manifest.json`, support tables
- **Schema (key fields)**:
  - hourly scenario long: `candidate_key, scenario_variant, scenario_id, delivery_day, period_timestamp, scenario_price, central_forecast_price, actual_price, probability, source_residual_day, scenario_type`
  - qh scenario long: `model_id, forecast_origin_utc, target_timestamp_utc, lead_day, scenario_id, scenario_price, point_forecast, y_true, dataset_split, scenario_probability`

## Strategy B Match Assessment

### Verdict
- **Partially matches Strategy B**.
- Both pipelines are **forecast-centered residual add-on generators**, but there are material methodological gaps versus the intended thesis-grade Strategy B.

### What matches
- Scenarios are generated as:
  - hourly: `scenario_price = central_forecast (+ optional bias-corrected forecast) + residual`
  - quarter-hour: `scenario_price = y_pred + residual_sampled`
- Residual definition is correct (`actual - forecast`).
- Scenarios are generated **per model/candidate** (not pooled across models).
- Per-period probabilities are present and normalized in current artifacts (sum ~1 per origin/day group).

### What does not fully match
- **Hourly selection/tuning uses test split** for candidate and scenario-variant decisions (test-preferred slice).
- **Hourly generator is D-only in practice** (lead day 0 selection path), not full D..D+4 coherent path generation.
- **Quarter-hour calibration uses train+validation residuals by default**, not validation-only.
- **Cross-day D..D+4 path coherence is not preserved**:
  - quarter-hour samples each lead-day day-block independently; same `scenario_id` across leads usually comes from different source days.
- **Quarter-hour has no explicit stress/tail scenario layer** (hourly has optional stress variant B).

## Detailed Findings by Audit Topic

### Central forecast logic
- Both hourly and quarter-hour are forecast-centered residual-based generators.
- No evidence of generating scenarios directly from raw historical price paths without central forecast anchoring.

### Residual calibration and leakage
- **Hourly**:
  - calibration split in run `20260511_212611` is `validation`.
  - residuals are from scored rows (`y_true` and `y_pred` non-null).
  - no explicit `source_day_end < forecast_origin` filter in hourly generator; relies on split separation.
- **Quarter-hour**:
  - residual library filters to observed rows and enforces `source_day_end_utc < forecast_origin_utc` (good leakage guard).
  - calibration splits are `("train", "validation")` in current run.
  - no evidence of using test residuals for calibration in current run.

### Temporal coherence
- **Within-day coherence**:
  - hourly preserves full daily residual profile (24h target day shape; DST day lengths handled, occasionally interpolated when lengths differ).
  - quarter-hour preserves full daily residual profile (typically 96 quarters).
- **Cross-day coherence (D..D+4)**:
  - not explicitly enforced; lead days are sampled independently.
  - in qh run, same `scenario_id` across lead days is usually not a single consistent multi-day source trajectory.

### Tail behavior / CVaR suitability
- Hourly has optional tail enrichment + protected stress scenarios (option A/B variants).
- Quarter-hour method is plain daily residual bootstrap + mean-based reduction, no dedicated stress insertion.
- Latest distribution diagnostics (`scenario_evaluation/20260512_111340`) show broad undercoverage and tail imbalance issues across models, with MILP-readiness flags mostly fail/warning.

### Probabilities and scenario reduction
- Probabilities are normalized and present in both pipelines.
- **Hourly reduction** reassigns probability mass when representative reduction is applied.
- **Quarter-hour reduction** selects scenarios by sorted mean spread of raw scenarios and then sets equal probabilities (does not preserve empirical cluster mass structure).

### Reproducibility and provenance
- Seeds are configured (default 42), but qh uses Python `hash(...)` in per-group seed derivation; process-level hash randomization can break strict reproducibility across runs/environments.
- Quarter-hour provenance is stronger (`provenance_manifest.json` with source run paths, method id, settings).
- Hourly has run/config summaries and selected source run ids but weaker per-scenario provenance detail than qh.

## Key Methodological Risks (Priority Order)

1. **P0: Test-set peeking in hourly scenario pipeline**
   - Candidate selection and scenario-variant selection are based on test-preferred slice.
2. **P1: Missing explicit origin-time leakage guard in hourly generator**
   - No direct `source_day_end < forecast_origin` check in sampling stage.
3. **P1: Quarter-hour calibration policy ambiguity**
   - Uses train+validation residuals by default; not strictly validation-only calibration.
4. **P1: Reproducibility risk in qh seed derivation**
   - Per-group random seed uses Python salted hash.
5. **P2: No coherent multi-day scenario identity across D..D+4**
   - Lead-day blocks sampled independently; weak horizon path coherence for stochastic optimization.
6. **P2: Quarter-hour tail/stress underrepresentation**
   - No explicit stress scenario channel; evaluation indicates tail miss issues.
7. **P2: Simplistic qh scenario reduction**
   - Mean-based selection + equal weights can lose distributional structure relevant for CVaR.

## Recommended Fixes (Ordered)

1. **Lock hourly selection/tuning to validation only**; keep test for final holdout reporting.
2. **Add hourly causal source filter**: enforce `source_residual_day_end_utc < forecast_origin_utc` in bank sampling.
3. **Make qh calibration policy explicit**:
   - default to validation-only for strict Strategy B; optionally allow train+validation with explicit flag and rationale.
4. **Replace salted hash seed logic** in qh with deterministic stable hashing (or explicit integer mapping).
5. **Introduce multi-day path sampler** for D..D+4:
   - sample 5-day residual blocks (or copula/block bootstrap) with scenario IDs coherent across lead days.
6. **Add qh tail/stress layer** analogous to hourly option B (or EVT/tail-conditional residual enrichment).
7. **Upgrade qh reduction** to probability-aware clustering (e.g., k-medoids/Wasserstein proxy) and retain cluster-mass weights.
8. **Strengthen provenance metadata**:
   - include calibration source split/date per scenario in hourly outputs, plus explicit residual-source manifest.

## Diagnostic Notebook Status

- A diagnostic notebook already exists and was recently executed:
  - `notebooks/Data/02_Forecasting/01_DA_prices/29_scenario_distribution_evaluation_all_models.ipynb`
  - latest artifact run: `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260512_111340/`
- It already covers requested diagnostics:
  - p05/p50/p95-style coverage checks, outside-spread frequency, spread diagnostics by period/lead, temporal exceedance clusters, and representative path plots including worst undercoverage/tail-miss days.
