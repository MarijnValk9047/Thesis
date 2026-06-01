# Optimisation Data Support Map

This is an audit-only support map. No optimisation runs were performed, no scenarios were regenerated, and no MILP code was changed.

## Tracks

- `Hourly D-only thesis track`: intended final comparison period is `2024-10-01` to `2025-09-30`.
- `Hourly D+4 track`: forecast support exists, but scenario support was not found.
- `Quarter-hour observed-market track`: separate observed 15-minute evaluation window in late `2025/2026` data.
- `Quarter-hour counterfactual track`: frozen synthetic within-hour paths for `2024-10-01` to `2025-09-30`, which must stay labelled counterfactual.

## Hourly Support Summary

| Model | Artifact status | Delivery support | Thesis-grade | Notes |
| --- | --- | --- | --- | --- |
| LEAR Strict | thesis-grade scenario file exists | 2026-02-05 to 2026-04-30 | yes | later observed-quarter-hour bridge window, not the intended hourly test year |
| LEAR FS3 | thesis-grade scenario file exists | 2023-10-05 to 2025-09-26 | yes | overlaps the hourly test year for 361 days only |
| XGBoost FS3 | thesis-grade scenario file exists | 2023-10-05 to 2025-09-26 | yes | overlaps the hourly test year for 361 days only |
| LEAR FS3 legacy integration candidate | single-variant export exists | 2024-10-01 to 2025-09-26 | no | reconstructed forecast origins; diagnostic/integration use only |
| XGBoost FS3 legacy integration candidate | single-variant export exists | 2024-10-01 to 2025-09-26 | no | reconstructed forecast origins; diagnostic/integration use only |

Three-model common support inside the intended hourly test period: `none`.

Two-model LEAR FS3 / XGBoost support inside the intended hourly test period: `2024-10-01` to `2025-09-26` (`361` days).

Likely reason for the LEAR FS3 / XGBoost stop at `2025-09-26`: the upstream benchmark and scenario generation were capped on a shared `D..D+4` rolling-origin window, so the last forecast origin is `2025-09-25`. That gives `D+4` support through `2025-09-30`, but only `D` support through `2025-09-26`.

## Quarter-Hour Support Summary

### Observed-market quarter-hour track

- Observed target store: `2025-09-27` to `2026-04-30` on observed targets only.
- Deterministic LEAR Strict quarter-hour extension: `2025-09-27` to `2026-04-30` with observed-target-only scoring.
- Three-model quarter-hour scenario common support: `2026-01-03` to `2026-04-30` (`111` days).
- Three-model held-out test support for quarter-hour scenarios: `2026-03-18` to `2026-04-30` (`38` days).

### Counterfactual quarter-hour track

- Frozen synthetic 15-minute actual path exists for `2024-10-01` to `2025-09-30` (`365` days).
- This path is counterfactual/synthetic, not observed-market truth.
- No matching three-model quarter-hour scenario or prediction exports were found on that same `2024/2025` counterfactual year.

## Direct Answers

- A. The intended hourly test period is `2024-10-01 to 2025-09-30`.
- B. On that intended hourly period, no model currently has a thesis-grade scenario file with full end-to-end support through `2025-09-30`. LEAR FS3 and XGBoost thesis-grade scenarios cover `2024-10-01` to `2025-09-26`; LEAR Strict does not overlap the period at all.
- C. No. LEAR Strict is not available on the same hourly test period as LEAR FS3 and XGBoost.
- D. The LEAR Strict thesis-grade artifact was generated from the later observed quarter-hour bridge window, so its delivery support is `2026-02-05` to `2026-04-30`. Separately, the LEAR FS3 and XGBoost D-only scenario files inherit a multi-horizon cutoff that leaves the last four test-year days uncovered for `D`.
- E. Observed quarter-hour artifacts are the observed target store (`2025-09-27` to `2026-04-30`), the LEAR Strict deterministic extension on the same window, the LEAR/XGBoost parity forecasts (`2026-01-01` to `2026-04-30`), and the three-model quarter-hour scenario file with common support `2026-01-03` to `2026-04-30`.
- F. Counterfactual/synthetic quarter-hour artifacts are the frozen synthetic actual path under `frozen_actual_paths/canonical_v1`, covering `2024-10-01` to `2025-09-30`. It is suitable only for explicitly counterfactual experiments.
- G. Currently fair comparisons are: LEAR FS3 versus XGBoost hourly D-only diagnostics on `2024-10-01` to `2025-09-26`; and three-model quarter-hour observed-market comparisons on the common observed window, especially the held-out `2026-03-18` to `2026-04-30` test slice.
- H. Diagnostic-only comparisons are: two-model hourly validation tuning (LEAR FS3 versus XGBoost), any use of the legacy reconstructed integration-candidate scenario files, the available LEAR Strict D+4 forecast support without scenario exports, and any quarter-hour counterfactual run on the frozen synthetic path.
- I. Blocked comparisons are: the hourly three-model thesis comparison on `2024-10-01` to `2025-09-30`; the current selected-week hourly comparison; and any clean hourly-versus-quarter-hour granularity claim on a matched observed period.
- J. Next regeneration/export step: rerun or re-export the hourly D-only thesis-grade scenario set so all three hourly models expose the same delivery days on `2024-10-01` to `2025-09-30`, with explicit `forecast_origin_utc`, probabilities, and a D-only support definition that does not stop at `2025-09-26`.

## Readiness Calls

- `hourly_donly_three_model_test_year`: `blocked`
- `hourly_donly_selected_test_weeks`: `blocked`
- `hourly_donly_validation_cvar_tuning`: `partial`
- `hourly_dplus4_if_available`: `partial`
- `qh_counterfactual_full_year`: `partial`
- `qh_observed_market_window`: `ready`
- `qh_vs_hourly_matched_period_if_possible`: `blocked`

## Methodological Guardrails

- Quarter-hour observed-market experiments must score observed targets only.
- Quarter-hour counterfactual experiments must stay labelled counterfactual or synthetic and must not be reported as observed-market evidence.
- Hourly-versus-quarter-hour comparisons are not clean granularity comparisons unless period support and truth type are matched.
