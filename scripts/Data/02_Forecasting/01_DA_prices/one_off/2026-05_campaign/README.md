# One-Off Script Bundle: 2026-05 Campaign

Purpose:
- Store bounded experiment and audit runners outside the canonical DA runner surface.
- Reduce clutter in `scripts/Data/02_Forecasting/01_DA_prices`.

Created on:
- 2026-05-14

Retention / TTL:
- Review after: 2026-05-28
- If not referenced by active notebooks/docs and no new dependent runs are created, move to `archive/one_off_expired/` first.
- Hard deletion only after archive grace period and manual confirmation.

Scope moved in this bundle:
- `run_dplus4_applicability_scan.py`
- `run_fs3_taxonomy_inventory.py`
- `run_gap_audit.py`
- `run_hourly_donly_calibration_sensitivity.py`
- `run_hourly_donly_tail_diagnostics.py`
- `run_hourly_scenario_generation_with_lear_strict.py`
- `run_lago_lear_audit.py`
- `run_lago_lear_cleaning.py`
- `run_lago_lear_data_import.py`
- `run_lago_lear_export_for_qh.py`
- `run_lago_lear_res_forecast_import.py`
- `run_lago_lear_six_year_benchmark.py`
- `run_lago_multiday_feature_audit.py`
- `run_lago_settings_availability_audit.py`
- `run_lago_variant_decision_analysis.py`
- `run_option_ab_validation_sweep.py`
- `run_option_c_validation_sweep.py`
- `run_revised_parent_benchmark.py`
- `run_staged_block_ablation.py`
- `run_xgboost_fs3_tuning_pilot.py`
- `validate_frozen_d_only_lago.py`

Notes:
- Canonical hourly and quarter-hour deterministic runners remain in their original top-level script location.
- This bundle is organizational only; no model logic was modified.
