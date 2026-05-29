# Script Classification Report (Dry Run)

- Date: 2026-05-14
- Scope: `scripts/Data/02_Forecasting/01_DA_prices/*.py` and `scripts/dev/*.py`
- Action taken: classification only, no moves/deletes

## Category Counts

| Category | Count |
|---|---:|
| campaign_or_oneoff_candidate | 21 |
| protected_legacy_support_runner | 17 |
| protected_canonical_runner | 16 |
| active_notebook_generator | 8 |
| dev_environment_check | 2 |

## Risk Counts

| Risk | Count |
|---|---:|
| medium | 29 |
| high | 17 |
| very_high | 16 |
| low | 2 |

## Files by Category

### active_notebook_generator

| Script | Last write | Size KB | Risk | Recommended action |
|---|---|---:|---|---|
| create_da_15min_extension_notebooks.py | 2026-05-03 17:46:12 | 82.8 | medium | keep_in_place_or_move_to_tools_non_destructively |
| create_da_price_scenario_notebook.py | 2026-04-30 19:21:58 | 82.3 | medium | keep_in_place_or_move_to_tools_non_destructively |
| create_da_prices_cleaning_notebook.py | 2026-04-29 15:04:06 | 35.6 | medium | keep_in_place_or_move_to_tools_non_destructively |
| create_endogenous_feature_notebook.py | 2026-04-29 15:04:06 | 34 | medium | keep_in_place_or_move_to_tools_non_destructively |
| create_qh_finalisation_notebooks.py | 2026-05-05 13:57:02 | 19.4 | medium | keep_in_place_or_move_to_tools_non_destructively |
| create_qh_phase3_notebooks.py | 2026-05-06 11:17:33 | 9.8 | medium | keep_in_place_or_move_to_tools_non_destructively |
| create_scenario_distribution_evaluation_notebook.py | 2026-05-12 19:21:00 | 146.2 | medium | keep_in_place_or_move_to_tools_non_destructively |
| generate_standardized_notebooks.py | 2026-04-29 15:04:06 | 250.6 | medium | keep_in_place_or_move_to_tools_non_destructively |

### campaign_or_oneoff_candidate

| Script | Last write | Size KB | Risk | Recommended action |
|---|---|---:|---|---|
| run_dplus4_applicability_scan.py | 2026-05-12 16:51:40 | 10.9 | medium | move_to_one_off_with_readme_and_ttl |
| run_fs3_taxonomy_inventory.py | 2026-04-29 15:04:06 | 1 | medium | move_to_one_off_with_readme_and_ttl |
| run_gap_audit.py | 2026-04-29 15:04:06 | 3.7 | medium | move_to_one_off_with_readme_and_ttl |
| run_hourly_donly_calibration_sensitivity.py | 2026-05-13 01:26:57 | 31.1 | medium | move_to_one_off_with_readme_and_ttl |
| run_hourly_donly_tail_diagnostics.py | 2026-05-12 18:23:50 | 15.6 | medium | move_to_one_off_with_readme_and_ttl |
| run_hourly_scenario_generation_with_lear_strict.py | 2026-05-12 19:24:10 | 39 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_lear_audit.py | 2026-05-07 13:53:43 | 62 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_lear_cleaning.py | 2026-05-06 19:30:10 | 48 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_lear_data_import.py | 2026-05-06 15:05:50 | 9.5 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_lear_export_for_qh.py | 2026-05-11 11:41:56 | 60.7 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_lear_res_forecast_import.py | 2026-05-06 16:43:08 | 13.5 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_lear_six_year_benchmark.py | 2026-05-08 11:30:37 | 63.8 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_multiday_feature_audit.py | 2026-05-07 15:40:53 | 16.5 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_settings_availability_audit.py | 2026-05-07 15:23:01 | 35.4 | medium | move_to_one_off_with_readme_and_ttl |
| run_lago_variant_decision_analysis.py | 2026-05-07 20:57:32 | 33.1 | medium | move_to_one_off_with_readme_and_ttl |
| run_option_ab_validation_sweep.py | 2026-04-29 20:13:52 | 16.1 | medium | move_to_one_off_with_readme_and_ttl |
| run_option_c_validation_sweep.py | 2026-04-29 19:41:03 | 20.2 | medium | move_to_one_off_with_readme_and_ttl |
| run_revised_parent_benchmark.py | 2026-04-29 15:04:06 | 4.1 | medium | move_to_one_off_with_readme_and_ttl |
| run_staged_block_ablation.py | 2026-04-29 15:04:06 | 21.9 | medium | move_to_one_off_with_readme_and_ttl |
| run_xgboost_fs3_tuning_pilot.py | 2026-04-29 15:04:06 | 14.9 | medium | move_to_one_off_with_readme_and_ttl |
| validate_frozen_d_only_lago.py | 2026-05-07 22:21:17 | 6.5 | medium | move_to_one_off_with_readme_and_ttl |

### dev_environment_check

| Script | Last write | Size KB | Risk | Recommended action |
|---|---|---:|---|---|
| check_gurobi_license.py | 2026-05-14 15:16:37 | 1.5 | low | move_to_scripts_dev_keep |
| check_pyomo_gurobi.py | 2026-05-14 15:16:41 | 1.6 | low | move_to_scripts_dev_keep |

### protected_canonical_runner

| Script | Last write | Size KB | Risk | Recommended action |
|---|---|---:|---|---|
| run_15min_canonical_v1_counterfactual_evaluation.py | 2026-05-03 18:46:31 | 0.6 | very_high | keep_in_place |
| run_15min_canonical_v1_counterfactual_smoke_checks.py | 2026-05-03 18:46:31 | 3.6 | very_high | keep_in_place |
| run_15min_observed_deterministic_forecast.py | 2026-05-03 17:44:31 | 0.6 | very_high | keep_in_place |
| run_15min_observed_deterministic_smoke_checks.py | 2026-05-03 17:58:53 | 3.5 | very_high | keep_in_place |
| run_case_week_selection.py | 2026-04-29 15:04:06 | 4.2 | very_high | keep_in_place |
| run_data_overview.py | 2026-04-29 15:04:06 | 1.5 | very_high | keep_in_place |
| run_endogenous_feature_diagnostics.py | 2026-04-29 15:04:06 | 10.8 | very_high | keep_in_place |
| run_feature_family_ablation.py | 2026-04-29 15:04:06 | 8.8 | very_high | keep_in_place |
| run_fs3_ordered_benchmarks.py | 2026-04-29 15:04:06 | 96.4 | very_high | keep_in_place |
| run_lear_benchmark.py | 2026-04-29 15:04:06 | 2.7 | very_high | keep_in_place |
| run_model_comparison.py | 2026-04-29 15:04:06 | 15.3 | very_high | keep_in_place |
| run_naive_benchmark.py | 2026-04-29 15:04:06 | 1.1 | very_high | keep_in_place |
| run_prophet_benchmark.py | 2026-04-29 15:04:06 | 3.1 | very_high | keep_in_place |
| run_storage_cleanup.py | 2026-04-29 15:04:06 | 0.4 | very_high | keep_in_place |
| run_visual_case_weeks.py | 2026-04-29 15:04:06 | 9 | very_high | keep_in_place |
| run_xgboost_benchmark.py | 2026-04-29 15:04:06 | 3 | very_high | keep_in_place |

### protected_legacy_support_runner

| Script | Last write | Size KB | Risk | Recommended action |
|---|---|---:|---|---|
| run_15min_frozen_actual_path.py | 2026-05-02 13:52:15 | 0.8 | high | keep_in_place |
| run_15min_phase01_refresh.py | 2026-05-01 11:39:27 | 0.7 | high | keep_in_place |
| run_15min_phase02_shape_targets.py | 2026-05-01 11:49:55 | 0.8 | high | keep_in_place |
| run_15min_phase03_anchor_selection.py | 2026-05-01 12:15:09 | 0.7 | high | keep_in_place |
| run_15min_phase04_empirical_validation.py | 2026-05-01 12:31:35 | 0.8 | high | keep_in_place |
| run_15min_phase05_counterfactual_generation.py | 2026-05-02 14:43:32 | 1 | high | keep_in_place |
| run_15min_phase06_milp_exports.py | 2026-05-02 14:43:38 | 0.8 | high | keep_in_place |
| run_15min_phase07_realistic_track_a.py | 2026-05-01 16:13:33 | 0.9 | high | keep_in_place |
| run_15min_phase07_upstream_refresh.py | 2026-05-01 18:48:15 | 0.8 | high | keep_in_place |
| run_15min_qh_fs1_endogenous_ablation.py | 2026-05-06 11:17:05 | 2.2 | high | keep_in_place |
| run_15min_qh_fs1_model_comparison.py | 2026-05-05 14:23:29 | 1.4 | high | keep_in_place |
| run_15min_qh_fs1_phase2_7_hourly_parity.py | 2026-05-06 11:09:26 | 0.8 | high | keep_in_place |
| run_15min_qh_model3_lear_strict.py | 2026-05-11 20:34:39 | 1.8 | high | keep_in_place |
| run_15min_qh_scenario_generation.py | 2026-05-12 15:41:19 | 3.1 | high | keep_in_place |
| run_15min_qh_scenario_preflight.py | 2026-05-12 15:42:27 | 1.9 | high | keep_in_place |
| run_15min_qh_three_model_comparison.py | 2026-05-11 20:37:45 | 1.5 | high | keep_in_place |
| run_15min_thesis_governance_smoke_checks.py | 2026-05-02 14:45:47 | 3.4 | high | keep_in_place |

