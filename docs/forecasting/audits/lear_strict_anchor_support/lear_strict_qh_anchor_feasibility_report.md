# LEAR_STRICT QH Anchor Feasibility Audit

Date: 2026-05-10  
Scope: focused feasibility audit only (no QH_MODEL_3 implementation, no scenario generation)

## Executive conclusion

- The earlier warning is **real but solvable**: **(b)**.
- `LEAR_STRICT` does **not** currently overlap the observed-QH evaluation grid used by the canonical observed pipeline.
- This is not a hard methodological blocker; it is a data/coverage and rerun-export sequencing issue.
- Recommended next action: **B** (first generate compatible LEAR_STRICT hourly anchors on the observed-QH grid, then implement QH_MODEL_3).

---

## 1) Exact forecast-origin / target / lead-day grid in observed-QH evaluation

Source used:
- `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/targets_by_origin.csv`

Observed-QH canonical grid:
- rows: `103,680`
- unique `forecast_origin_utc`: `216`
- `lead_day` values: `0,1,2,3,4`
- min `forecast_origin_utc`: `2025-09-26 06:00:00+00:00`
- max `forecast_origin_utc`: `2026-04-29 06:00:00+00:00`
- min `target_timestamp_utc`: `2025-09-26 22:00:00+00:00`
- max `target_timestamp_utc`: `2026-05-04 21:45:00+00:00`

Validation+test subset of this same observed-QH grid:
- min target: `2026-02-02 23:00:00+00:00`
- max target: `2026-05-04 21:45:00+00:00`

---

## 2) Current two QH model IDs and prediction storage

Model IDs (from phase2.7 parity suite):
- `qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted`
- `qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate`

Evidence:
- `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_phase2_7_hourly_parity/20260506_091021_qh_fs1_phase2_7_hourly_parity/suite_models.json`

Predictions stored at:
- `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_phase2_7_hourly_parity/20260506_091021_qh_fs1_phase2_7_hourly_parity/predictions_long.csv`

---

## 3) Where their hourly anchors come from

Upstream source run metadata (phase07 realistic track A):
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/20260505_134716_phase07_realistic_track_a/run_summary.json`

Selected hourly anchor candidates in that run:
- deterministic winner: `xgboost_fs3_combo_pruned_candidate` (hourly run `20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark`)
- hour-ranking winner: `lear_fs3_combo_promoted` (hourly run `20260425_124242_lear_fs3_combo_promoted_benchmark`)

---

## 4) Do those anchor artifacts cover observed post-transition QH window?

Yes, for the parity models’ own evaluated slice (validation+test), they have high overlap.

From `qh_anchor_coverage_by_model.csv`:
- each current QH model has:
  - `40,660 / 41,740` matched rows on observed validation+test QH targets (`97.41%`)
  - matched origins `87/87`
  - lead days `0..4` present

On full observed-QH grid (including train), parity bundle coverage is partial (`54.49%`) because the parity artifact itself only contains validation/test splits.

---

## 5) What are these anchors structurally?

They are **true hourly forecast anchors** produced by the hourly forecast pipeline and then expanded to quarter-hours in the QH pipeline; not simple static repeated constants.

Concrete mechanics:
- observed deterministic path fits hourly backbone forecasts per forecast origin (`_run_hourly_backbone_extension` in `observed_deterministic.py`)
- quarter-hour predictions are reconstructed as:
  - repeated-hourly benchmark (flat intra-hour),
  - plus learned quarter-hour deviation models (`mean_shape_deviation`, `xgboost_deviation`) with zero-mean correction.

So the anchor is a rolling-origin hourly forecast series, then QH shape/deviation is applied.

---

## 6) Exact LEAR_STRICT artifacts that exist

Primary LEAR_STRICT run:
- `data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/20260508_122730_lago_lear_six_year_benchmark/`

Key files:
- `predictions/predictions_long.csv`
- `predictions/predictions_long.parquet`
- `run_summary.json`
- `run_progress_dplus4.json`
- `metrics_by_lead_day.csv`
- `metrics_by_reporting_level.csv`
- `metrics_overall.csv`

Model column value:
- `lear_lago_direct_dplus4_strict_no_future_1092`

Dataset split counts in this artifact:
- validation: `24,218`
- test: `48,111`

---

## 7) Do existing LEAR_STRICT artifacts already cover the observed-QH grid?

No.

From `qh_anchor_coverage_by_model.csv`:
- LEAR_STRICT vs observed-QH hourly-anchor grid (full): `0 / 25,920` matched rows (`0%`)
- LEAR_STRICT vs observed-QH hourly-anchor grid (validation+test): `0 / 10,435` matched rows (`0%`)
- matched origins: `0`
- matched lead days: none

Therefore, current LEAR_STRICT artifacts cannot be used directly as hourly anchors for observed-QH comparison.

---

## 8) If not, can LEAR_STRICT be exported/rerun on same grid with existing code?

Yes, with existing code paths (no new modeling method required), by rerunning/exporting LEAR_STRICT on the needed observed-QH origin horizon window.

Relevant existing runner and core:
- runner: `scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_six_year_benchmark.py`
- model core: `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/lago_lear_model.py`
- feature builder: `.../hourly_da/core/lago_multiday_features.py`

The runner already supports:
- `--run-dplus4`
- date window flags (`--start-local-date`, `--end-exclusive-local-date`)
- `--max-origins`
- checkpointing (`--checkpoint-predictions`, chunk controls)

---

## 9) Full rolling retraining required, or only export?

- **Only export from existing LEAR_STRICT files is not sufficient** (zero overlap).
- Minimum viable path requires **new rolling fit/predict generation** for the required origin window using existing LEAR_STRICT logic.
- So this is not a pure reformat/reindex export task.

---

## 10) Runtime and memory risk estimate (minimum viable anchor generation)

Reference runtime from existing LEAR_STRICT run:
- `run_progress_dplus4.json` reports:
  - `72,329` eval rows
  - `654` origins
  - `19,626` seconds elapsed (~`5.45` hours)
  - ~`30` sec/origin average

Observed-QH origin count:
- `216` origins total on canonical observed grid

Back-of-envelope estimate:
- `216 * 30 sec ≈ 6,480 sec` (~`1.8` hours)
- With overhead / less warm cache / potential feature availability effects: practical band ~`2–4` hours

Memory risk:
- low-to-moderate if checkpoint mode is kept on (already supported in LEAR_STRICT pipeline).
- avoid holding all intermediate fit audits in memory without checkpointing.

---

## 11) Final classification

Earlier warning status:
- **(b) real but solvable issue**

Reason:
- direct overlap is currently zero,
- but existing pipeline components can generate compatible LEAR_STRICT anchors with bounded additional runtime.

---

## Recommended next action

**B. First create/export/rerun LEAR_STRICT hourly anchors for the observed-QH grid, then implement QH_MODEL_3.**

