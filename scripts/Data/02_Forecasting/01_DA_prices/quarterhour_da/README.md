# Quarter-Hour DA Extension

This package hosts the downstream 15-minute Dutch DA extension that sits after the established hourly DA forecasting workstream.

The package now has two distinct tracks:

- `observed_deterministic.py`
  - canonical observed-market deterministic quarter-hour DA forecast path
  - mirrors the audited hourly `D..D+4` framework as closely as possible
  - uses observed targets only for scoring
  - writes official artifacts under `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/<run_id>/`
- `counterfactual_canonical.py`
  - canonical full-year counterfactual quarter-hour evaluation path against `frozen_actual_paths/canonical_v1`
  - compares the frozen upstream hourly thesis candidates after quarter-hour extension
  - labels outputs explicitly as synthetic scenario-readiness benchmarking, not observed-market accuracy
- legacy/staging phase workflow
  - `phase02/03/04/07` and downstream frozen-actual support
  - kept for reproducibility, diagnostics, and downstream synthetic-path support
  - not the canonical observed-market forecast-evaluation path

Current implemented phases:

- `Phase 0`: foundation contracts for paths, schemas, updater authority, notebook ownership, and output roots
- `Phase 1`: hourly and quarter-hour DAM data refresh orchestration plus diagnostics
- `Phase 2`: canonical within-hour shape-target construction, completeness checks, and empirical split diagnostics
- `Phase 3`: dynamic hourly anchor discovery using the existing hourly scenario-selection logic
- `Phase 4`: empirical 15-minute shape-model validation under the diagnostic/oracle anchor, plus realistic-anchor availability checks
- `Phase 5`: legacy exploratory full-year counterfactual 15-minute generation for the official hourly test period

Canonical observed-market deterministic runner:

- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_observed_deterministic_forecast.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_canonical_v1_counterfactual_evaluation.py`
- selection and evaluation rules:
  - forecast origin `08:00` on `D-1` local
  - horizon `D..D+4`
  - deterministic origin-based chronological split over the observed 15-minute period
  - observed-target-only metrics, `rMAE`, and DM tests
  - repeated-hourly structural benchmark plus causal quarter-hour naive benchmarks
  - frozen hourly backbone selected on validation only without quarter-hour test feedback

Canonical counterfactual evaluation runner:

- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_canonical_v1_counterfactual_evaluation.py`
- counterfactual rules:
  - truth comes from `frozen_actual_paths/canonical_v1`
  - frozen hourly backbone candidate set is fixed to the upstream hourly thesis candidates
  - no quarter-hour observed-period or canonical_v1 performance selection is allowed
  - the run reports full-year counterfactual scenario-readiness metrics only

Canonical actual-path governance:

- `run_15min_frozen_actual_path.py`: builds and freezes the authoritative synthetic 15-minute actual path for downstream bidding work
- canonical frozen artifacts live under `data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/<version_id>/`
- the canonical actual path is separate from forecast/scenario artifacts and must be treated as read-only downstream input
- for thesis-grade downstream work, `canonical_v1` is currently the only authorised realised 15-minute actual-market-truth source
- thesis-grade results must report the canonical version id and authoritative CSV SHA-256 checksum

Legacy note:

- The earlier combined `Phase 5/6` exploratory path packaged realized and forecast-side artifacts too closely for downstream thesis use.
- The frozen-actual firewall now supersedes that combined path for authoritative bidding inputs.
- Legacy Phase 5/6 realised paths remain available only for exploratory diagnostics and reproducibility. They are not authorised actual market truth for thesis-grade bidding or optimisation runs.

Repo-native choices for the current phase:

- The shared cleaned hourly NL DAM output remains the authoritative observed hourly source.
- The shared cleaned quarterly NL DAM output remains the authoritative downstream quarter-hour source for compatibility.
- The dedicated `nl_quarterly_da_prices_pipeline.py` path is kept as the continuation updater and audit companion.
- Dynamic hourly anchor selection in the legacy phase workflow still inherits the existing scenario-generation logic from `hourly_da.core.scenario_generation`.
- The canonical observed-market deterministic runner does **not** use the scenario-generation test-preferred slice selector for backbone or benchmark selection.

Primary thesis-grade runner order:

- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase01_refresh.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase02_shape_targets.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase03_anchor_selection.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase04_empirical_validation.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_frozen_actual_path.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase07_realistic_track_a.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_observed_deterministic_forecast.py`

Legacy exploratory runners:

- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase05_counterfactual_generation.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_phase06_milp_exports.py`

Generated notebook entry point:

- `scripts/Data/02_Forecasting/01_DA_prices/create_da_15min_extension_notebooks.py`
