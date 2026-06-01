# Known Issues (Hydrogen Test Case)

## 0) Final hourly three-model test-year comparison is still blocked by support, not by the MILP

Support-map status as of May 16, 2026:

- intended final hourly D-only comparison period:
  - `2024-10-01` to `2025-09-30`
- current thesis-grade hourly support:
  - `hourly_lear_strict`: `2026-02-05` to `2026-04-30`
  - `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`: `2024-10-01` to `2025-09-26` on the intended test year
  - `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate`: `2024-10-01` to `2025-09-26` on the intended test year
- result:
  - **no** three-model common-support window exists inside the intended hourly test year

Impact:

- the final hourly thesis comparison cannot yet be reported
- any current hourly three-model experiment on `2024-10-01` to `2025-09-30` would silently compare different periods

Required action:

- regenerate or re-export the hourly D-only thesis-grade scenario set so all three hourly models expose the same delivery days on `2024-10-01` to `2025-09-30`
- if `2025-09-30` is a hard end date for the D-only study, the export must not stop at `2025-09-26`

Likely upstream reason:

- LEAR FS3 and XGBoost D-only scenario files appear to inherit a shared `D..D+4` origin cutoff, so the last D-only delivery is `2025-09-26`
- LEAR Strict support comes from the later observed quarter-hour bridge window, not from the intended `2024/2025` hourly thesis year

## 1) Hourly thesis-grade catalog validation now passes for all three hourly artifacts, but common support does not

Status as of May 16, 2026:

- `scenario_catalog.yaml` default artifact remains `hourly_lear_strict`.
- The catalog path for that artifact now points to:
  - `.../20260516_002902/scenario_prices_long.csv`
- `hourly_lear_strict` now passes thesis-grade validation through the hydrogen scenario loader.
- A second thesis-grade hourly catalog entry now exists and passes validation:
  - `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`
- A third thesis-grade hourly catalog entry now exists and passes validation:
  - `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate`

Impact:

- loader/schema validation is no longer the main blocker for hourly thesis-grade scenario use
- the current blocker is **support mismatch across artifacts**
- valid daily coverage ranges are currently:
  - `hourly_lear_strict`: `2026-02-05` to `2026-04-29`
  - `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`: `2023-10-05` to `2025-09-26`
  - `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate`: `2023-10-05` to `2025-09-26`
- there is therefore **no common three-model selected-week support window** at present

Required action:

- keep the thesis-grade hourly artifacts on disk
- regenerate or recover a LEAR Strict hourly artifact whose valid delivery support overlaps the LEAR FS3 and XGBoost hourly thesis-grade windows if three-model parity is required

## 2) XGBoost hourly is now thesis-grade, but three-model selected-week comparison is still blocked by LEAR Strict support mismatch

Status:

- `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate` now exists in the catalog
- it passes thesis-grade validator checks
- it has explicit forecast-origin provenance with no reconstruction fallback
- it shares the same `75`-scenario D-only hourly regime as the current LEAR FS3 thesis-grade entry

Audit diagnosis:

- the selected-week blocker is no longer XGBoost provenance
- the selected-week blocker is that the current LEAR Strict thesis-grade artifact does not overlap the LEAR FS3 / XGBoost thesis-grade support window

Impact:

- two-model thesis-grade selected-week comparison is possible for:
  - LEAR FS3 pruned candidate
  - XGBoost FS3 pruned candidate
- a clean three-model thesis-grade selected-week comparison is still not possible

Required action:

- regenerate or recover LEAR Strict hourly support on the same delivery window as LEAR FS3 and XGBoost if three-model comparison parity is required

Phase 6a-2 status:

- completed for two integration-candidate exports:
  - `hourly_lear_fs3_promoted_base_plus_b_integration_candidate`
  - `hourly_xgboost_fs3_pruned_base_plus_b_integration_candidate`
- these artifacts:
  - preserve provenance
  - reconstruct `forecast_origin_utc` explicitly
  - validate probability mass after one-variant selection
  - remain non-thesis-grade because origin reconstruction was required

## 3) Scenario quality is still not thesis-ready even before optimiser hookup

Status:

- `scenario_milp_readiness_summary.csv` marks all inspected hourly and quarter-hour models with `coverage_acceptable = fail`
- hourly recommendations currently say `add tail/stress scenarios`

Impact:

- even after the missing hourly export is repaired, real stochastic bidding results will still need to carry explicit scenario-quality warnings
- robust downside-risk claims remain unsupported until scenario coverage is repaired and revalidated

Required action:

- retain scenario-quality diagnostics alongside any future optimisation run
- do not treat repaired export availability as equivalent to full thesis readiness

## 4) Forecast-origin reconstruction remains a legacy-only fallback

Status:

- reconstruction is only acceptable for legacy smoke diagnostics
- thesis-grade artifacts should store explicit `forecast_origin_utc`

Impact:

- reconstruction weakens provenance and makes schema auditing harder

Required action:

- upstream scenario export must write explicit UTC forecast origins

Dry-run caveat:

- the derived legacy integration-candidate artifacts now write reconstructed `forecast_origin_utc` explicitly for compatibility
- this is acceptable for integration testing only, not final thesis-grade scenario provenance

## 5) Production target reporting semantics

Status:

- the hydrogen target is intentionally treated as a lower-bound reference requirement, not as a fixed production or sales cap
- some strategies can therefore produce or compress/sell more hydrogen than the daily target

Impact:

- fulfilment ratios above `1.0` should not be interpreted as better reliability
- reporting must separate:
  - capped reliability fulfilment
  - uncapped production-to-target ratio
  - above-target hydrogen volume

Required action:

- keep above-target production physically allowed unless a later thesis variant introduces explicit offtake constraints
- use capped fulfilment only as a reliability metric
