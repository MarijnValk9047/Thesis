from __future__ import annotations

import csv
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import sys

import pytest
import yaml


STEEL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.c5_source_emulation_validation import DEFAULT_CONFIG_PATH, load_config
from steel.c5_source_emulation_evaluation import (
    STRATEGIES,
    _case_id,
    _case_ready,
    _strategy_overrides,
)


RUN_ROOT = REPO_ROOT / "data/03_Optimisation/runs/steel_c5_source_emulation_validation_v1_20260721"
CONTRACT_PATH = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract"
    / "representative_week_selection_contract.csv"
)


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_selected_periods_are_split_separated_nonoverlapping_and_complete():
    rows = _csv(CONTRACT_PATH)
    assert len(rows) == 8
    assert len({row["period_id"] for row in rows}) == 8
    for split, role in (("validation", "development"), ("test", "held_out")):
        selected = [row for row in rows if row["dataset_split"] == split]
        assert len(selected) == 4
        assert {row["period_role"] for row in selected} == {role}
        intervals = sorted(
            (date.fromisoformat(row["delivery_start_local_date"]), date.fromisoformat(row["delivery_end_local_date"]))
            for row in selected
        )
        assert all(left[1] < right[0] for left, right in zip(intervals, intervals[1:]))
        assert all(row["replan_count"] == "7" for row in selected)


def test_timestamps_and_weights_match_the_frozen_experiment_config():
    config = load_config(DEFAULT_CONFIG_PATH)
    actual = [
        {
            "period_id": row["period_id"],
            "frozen_forecast_start_origin_utc": row["frozen_forecast_start_origin_utc"],
            "split_weight": float(row["split_weight"]),
        }
        for row in _csv(CONTRACT_PATH)
    ]
    expected = [
        {
            "period_id": row["period_id"],
            "frozen_forecast_start_origin_utc": row["frozen_forecast_start_origin_utc"],
            "split_weight": float(row["split_weight"]),
        }
        for row in config["frozen_selection"]
    ]
    assert actual == expected
    for split in ("validation", "test"):
        assert sum(row["split_weight"] for row in actual if row["period_id"].startswith(f"{split}_")) == pytest.approx(1.0)


def test_origin_support_is_seven_days_information_safe_and_dst_aware():
    periods = _csv(CONTRACT_PATH)
    support = _csv(RUN_ROOT / "representative_week_origin_support.csv")
    assert len(support) == 56
    for period in periods:
        rows = [row for row in support if row["period_id"] == period["period_id"]]
        assert [int(row["replan_index"]) for row in rows] == list(range(7))
        assert len({row["delivery_local_date"] for row in rows}) == 7
        assert all(row["y_pred_complete"] == "True" for row in rows)
        assert all(row["y_true_ex_post_complete_for_execution"] == "True" for row in rows)
        assert all(row["information_timing_pass"] == "True" for row in rows)
        assert all(row["y_true_exposed_to_operational_interface"] == "False" for row in rows)
        assert all(
            datetime.fromisoformat(row["forecast_origin_utc"])
            < datetime.fromisoformat(row["delivery_start_utc"])
            for row in rows
        )
        assert sum(int(row["execution_hours"]) for row in rows) == int(period["execution_hours"])
    for split in ("validation", "test"):
        split_periods = [row for row in periods if row["dataset_split"] == split]
        assert any(int(row["execution_hours"]) in {167, 169} for row in split_periods)


def test_selection_has_no_optimisation_or_anchor_dependent_inputs():
    config = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    features = set(config["selection"]["feature_fields"])
    assert features <= {
        "calendar_position_fraction",
        "realised_mean_eur_per_mwh",
        "realised_volatility_eur_per_mwh",
        "negative_price_share",
        "forecast_mae_eur_per_mwh",
    }
    assert config["selection"]["y_true_use"] == "ex_post_regime_classification_only_never_optimizer_input"
    assert config["selection_solver_runs_enabled"] is False
    rows = _csv(CONTRACT_PATH)
    assert all(row["optimisation_result_inputs_used"] == "False" for row in rows)
    assert all(row["anchor_residual_inputs_used"] == "False" for row in rows)
    assert all(row["operational_price_field"] == "y_pred" for row in rows)
    assert all(row["annualisation_label"] == "representative_period_annualised" for row in rows)


def test_checkpoint_preserves_selection_and_output_is_minimal():
    summary = json.loads((RUN_ROOT / "run_summary.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((RUN_ROOT / "checkpoint_state.json").read_text(encoding="utf-8"))
    assert summary["selected_period_count"] == 8
    if checkpoint["completed_checkpoint"] == 4:
        assert summary["solver_run_performed"] is False
    else:
        assert checkpoint["completed_checkpoint"] == 7
        assert summary["solver_run_performed"] is True
        assert summary["reporting_revision_solver_run_performed"] is False
        assert summary["native_mip_gap_available"] is False
        assert summary["maximum_derived_primary_cost_relative_gap_fraction"] == pytest.approx(
            9.5526982051253285e-5, rel=1e-7
        )
        assert summary["whole_period_cost_comparison_policy"] == (
            "arithmetic_only_before_terminal_inventory_value_bridge_no_uplift_or_adverse_forecast_value_claim"
        )
        assert summary["decision"] == "source_valid_emulation_rejected"
        assert summary["reporting_revision"] == "final_reviewer_closeout_aggregate_and_manifest_only"
        assert summary["reporting_revision_scope"] == "aggregate_and_manifest_only_no_case_or_solver_rerun"
        assert summary["post_review_reporting_correction"] == "named_ng_PJ_to_MWh_factor_20260722"
        assert summary["post_review_reporting_correction_solver_run_performed"] is False
        assert summary["immutable_solver_model_config_and_physical_input_hashes_preserved"] is True
        assert checkpoint["next_gate"] == (
            "thesis_manuscript_integration_of_bounded_source_driven_D-Dplus4_interpretation"
        )
    assert summary["physical_parameters_changed"] is False
    assert summary["model_logic_changed"] is False
    assert checkpoint["decision"] == "source_valid_emulation_rejected"
    assert checkpoint["independent_review_required"] is False
    assert checkpoint["independent_reviewer_decision"] == "complete"
    artifacts = [path for path in RUN_ROOT.iterdir() if path.is_file()]
    assert len(artifacts) <= 35
    assert sum(path.stat().st_size for path in artifacts) <= 25 * 1024 * 1024


def test_evaluation_contract_is_exactly_three_distinct_strategies_and_24_cases():
    config = load_config(DEFAULT_CONFIG_PATH)
    periods = _csv(CONTRACT_PATH)
    assert tuple(config["evaluation"]["strategies"]) == STRATEGIES
    assert STRATEGIES == ("price_insensitive", "governed_y_pred", "oracle_y_true")
    assert len(periods) * len(STRATEGIES) == config["evaluation"]["expected_case_count"] == 24
    case_ids = [_case_id(period["period_id"], strategy) for period in periods for strategy in STRATEGIES]
    assert len(case_ids) == len(set(case_ids))
    assert "flat_price_parity" not in STRATEGIES
    assert config["evaluation"]["flat_price_parity_policy"].startswith("reuse_accepted_")


def test_post_validation_governance_references_are_mutable_and_historical_hashes_preserved():
    manifest = json.loads((RUN_ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    strict = {row["path"]: row for row in manifest["repository_files"]}
    mutable = {row["path"]: row for row in manifest["mutable_governance_references"]}
    expected = {
        "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/calibratable_parameter_contract.csv": "f0815c353b997e1905d8ecf099eb4084288809dde815c1e1eb63cc426c3f37a7",
        "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/calibration_validation_target_contract.csv": "8a3ef3dc907d23f42dc24fa40e3022d2b206910d6a1d12bd15b34da98dc78547",
        "data/03_Optimisation/runs/steel_c5_tata_benchmark_v1_20260721/checkpoint_state.json": "b2416f1555736eff2cf1037772cef8c049b50c99e0470509baf7a4c834d54193",
    }
    assert set(mutable) == set(expected)
    assert not set(expected).intersection(strict)
    for path, solve_time_sha256 in expected.items():
        row = mutable[path]
        current = REPO_ROOT / path
        assert row["solve_time_sha256"] == solve_time_sha256
        assert row["current_sha256"] == hashlib.sha256(current.read_bytes()).hexdigest()
        assert row["current_sha256"] != row["solve_time_sha256"]
        assert row["status"] == "post_validation_checkpoint8_evolved"
        assert row["role"] == "governance_context_not_solver_model_config_or_physical_input"
        assert row["solve_time_snapshot_available"] is False
        assert "not byte-for-byte reproducible" in row["caveat"]

    for path, row in strict.items():
        repository_path = REPO_ROOT / path
        assert repository_path.is_file()
        assert row["sha256"] == hashlib.sha256(repository_path.read_bytes()).hexdigest()
    assert manifest["evaluation_case_cache"]["case_count"] == 24
    assert len(manifest["evaluation_case_cache"]["run_summary_sha256"]) == 24


def test_only_oracle_exposes_y_true_and_flat_benchmark_preserves_timestamps():
    period = _csv(CONTRACT_PATH)[0]
    flat = _strategy_overrides(period, "price_insensitive")
    forecast = _strategy_overrides(period, "governed_y_pred")
    oracle = _strategy_overrides(period, "oracle_y_true")
    assert flat["timestamped_dplus4_rolling_enabled"] is True
    assert flat["forecast_price_override_eur_per_mwh"] == 80.0
    assert flat["forecast_price_field"] == "y_pred"
    assert forecast["forecast_price_field"] == "y_pred"
    assert oracle["forecast_price_field"] == "y_true"
    assert oracle["perfect_foresight_oracle"] is True
    assert flat["perfect_foresight_oracle"] is False
    assert forecast["perfect_foresight_oracle"] is False
    physical_exclusions = {
        "c1_generator_boundary",
        "represented_electricity_boundary",
        "c1_source_backed_energy_boundary",
        "bof_material_balance",
        "eaf_material_balance",
        "scrap_supply_ledger",
        "production_envelope_tolerance_fraction",
    }
    assert not physical_exclusions.intersection(flat)
    assert not physical_exclusions.intersection(forecast)
    assert not physical_exclusions.intersection(oracle)


def test_completed_smoke_is_recognised_as_resumable_cache():
    smoke = REPO_ROOT / "tmp/c5_source_emulation_validation_v1_20260721_cases/eval__validation_2024_07_29__price_insensitive"
    assert _case_ready(smoke)
    summary = json.loads((smoke / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "pass"
    assert summary["executed_hours"] == 168
    assert summary["c0_rolling_status"] == "pass"
    assert summary["c1_rolling_status"] == "pass"


def test_completed_evaluation_matrix_and_oracle_contract_if_checkpoint_seven():
    checkpoint = json.loads((RUN_ROOT / "checkpoint_state.json").read_text(encoding="utf-8"))
    if checkpoint["completed_checkpoint"] != 7:
        pytest.skip("Full escalated evaluation has not completed yet.")
    cases = _csv(RUN_ROOT / "evaluation_case_status.csv")
    assert len(cases) == 24
    assert all(row["status"] == "pass" for row in cases)
    assert {row["strategy"] for row in cases} == set(STRATEGIES)
    assert len({row["period_id"] for row in cases}) == 8
    assert all(row["physical_parameter_overrides"] == "False" for row in cases)
    assert all(
        (row["strategy"] == "oracle_y_true")
        == (row["forecast_price_field"] == "y_true" and row["perfect_foresight_oracle"] == "True")
        for row in cases
    )
    assert all(
        (row["strategy"] == "oracle_y_true") == (row["y_true_operational_use"] == "True")
        for row in cases
    )
    assert all(
        (row["strategy"] != "oracle_y_true")
        == (row["non_anticipative_deployment_eligible"] == "True")
        for row in cases
    )


def test_completed_evaluation_guardrails_and_solver_metrics_if_checkpoint_seven():
    checkpoint = json.loads((RUN_ROOT / "checkpoint_state.json").read_text(encoding="utf-8"))
    if checkpoint["completed_checkpoint"] != 7:
        pytest.skip("Full escalated evaluation has not completed yet.")
    guardrails = _csv(RUN_ROOT / "physical_guardrails.csv")
    assert guardrails
    assert all(row["status"] == "pass" for row in guardrails)
    required = {
        "exact_terminal_production_quota",
        "material_conservation",
        "origin_conservation",
        "carrier_specific_wag_balance",
        "gross_internal_grid_electricity_identity",
        "named_ng_component_identity",
        "represented_steam_boundary_identity",
        "represented_cost_identity",
        "mode_b_explicit_fuel_separation",
        "no_aggregate_or_mixed_wag_physical_use",
        "no_residual_electricity_or_ng_input",
        "export_prohibited",
        "price_information_timing_non_anticipative",
        "identical_state_first_window_oracle_dominance",
    }
    assert required <= {row["check_id"] for row in guardrails}
    metrics = _csv(RUN_ROOT / "solver_runtime_metrics.csv")
    assert len(metrics) == 24 * 7 * 2
    assert all(row["solver_name"] == "gurobi" for row in metrics)
    assert all(row["solver_status"] == "ok" for row in metrics)
    assert all(row["termination_condition"] == "optimal" for row in metrics)
    assert all(int(row["variable_count"]) > 0 and int(row["constraint_count"]) > 0 for row in metrics)
    assert all(row["native_mip_gap"] == "" for row in metrics)
    assert all(
        row["mip_gap_source"] == "derived_from_primary_cost_objective_and_best_bound"
        for row in metrics
    )
    assert max(float(row["reported_mip_gap_fraction"]) for row in metrics) == pytest.approx(
        9.5526982051253285e-5, rel=1e-7
    )


def test_completed_evaluation_strategy_production_and_oracle_contract_if_checkpoint_seven():
    checkpoint = json.loads((RUN_ROOT / "checkpoint_state.json").read_text(encoding="utf-8"))
    if checkpoint["completed_checkpoint"] != 7:
        pytest.skip("Full escalated evaluation has not completed yet.")
    rows = _csv(RUN_ROOT / "period_strategy_summary.csv")
    assert len(rows) == 8 * 3 * 2
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["period_id"], row["configuration_id"]), []).append(row)
    for values in grouped.values():
        assert len(values) == 3
        production = [float(row["final_product_t_y"]) for row in values]
        assert max(production) - min(production) <= 1.0
        assert all(row["annualisation_label"] == "representative_period_annualised" for row in values)
        assert all(row["residual_electricity_input_mwh_y"] == "0.0" for row in values)
        assert all(row["residual_ng_input_mwh_lhv_y"] == "0.0" for row in values)
    weighted_ledger = _csv(RUN_ROOT / "weighted_annual_equivalent_ledger.csv")
    named_ng_subtotals = {
        (row["dataset_split"], row["strategy"], row["configuration_id"]): row
        for row in weighted_ledger
        if row["ledger_family"] == "named_NG"
        and row["flow_role"] == "subtotal"
        and row["component"] == "represented_named_NG"
    }
    for key, values in {
        key: [
            row
            for row in rows
            if (row["dataset_split"], row["strategy"], row["configuration_id"]) == key
        ]
        for key in named_ng_subtotals
    }.items():
        weighted_summary = sum(
            float(row["split_weight"]) * float(row["named_ng_mwh_lhv_y"])
            for row in values
        )
        assert weighted_summary == pytest.approx(
            float(named_ng_subtotals[key]["weighted_annual_equivalent_value"]),
            rel=1e-9,
        )
    comparisons = _csv(RUN_ROOT / "strategy_comparison.csv")
    governed_rows = [row for row in comparisons if row["strategy"] == "governed_y_pred"]
    assert len(governed_rows) == 8 * 2
    assert all(row["identical_state_first_window_oracle_dominance_status"] == "pass" for row in governed_rows)
    assert all(
        row["whole_period_rolling_oracle_role"]
        == "rolling_D_to_Dplus4_oracle_not_global_week_foresight_upper_bound"
        for row in governed_rows
    )
    assert all(
        row["oracle_upper_bound_claim_scope"]
        == "identical_state_first_planning_window_only"
        for row in governed_rows
    )
    assert all(
        row["whole_period_cost_difference_interpretation"]
        == "arithmetic_only_before_terminal_inventory_value_bridge"
        for row in comparisons
    )
    assert all(
        row["economic_uplift_or_adverse_forecast_value_claim_allowed"] == "False"
        and row["inventory_value_bridge_available"] == "False"
        and row["value_captured_vs_oracle_fraction"] == ""
        for row in comparisons
    )
    assert all(
        "realised_cost_saving_vs_price_insensitive_eur_y" not in row
        and "within_period_procurement_cost_difference_before_terminal_inventory_bridge_eur_y" in row
        for row in comparisons
    )
    terminal = _csv(RUN_ROOT / "terminal_inventory_comparison.csv")
    assert len(terminal) == 8 * 2 * 2 * 5
    assert {row["inventory_id"] for row in terminal} == {
        "coke",
        "sinter",
        "hot_iron",
        "cold_slab",
        "DRI",
    }
    assert all(row["inventory_value_bridge_available"] == "False" for row in terminal)
    assert all(row["economic_uplift_claim_allowed"] == "False" for row in terminal)
    assert {row["terminal_state_equivalence_status"] for row in terminal} <= {
        "equivalent",
        "different",
        "not_represented",
    }


def test_completed_evaluation_weighted_ledgers_and_classifications_if_checkpoint_seven():
    checkpoint = json.loads((RUN_ROOT / "checkpoint_state.json").read_text(encoding="utf-8"))
    if checkpoint["completed_checkpoint"] != 7:
        pytest.skip("Full escalated evaluation has not completed yet.")
    ledger = _csv(RUN_ROOT / "weighted_annual_equivalent_ledger.csv")
    assert ledger
    assert all(row["annualisation_label"] == "representative_period_annualised" for row in ledger)
    assert all(float(row["weight_sum"]) == pytest.approx(1.0) for row in ledger)
    for split in ("validation", "test"):
        for strategy in STRATEGIES:
            for configuration in ("C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF"):
                selected = [
                    row for row in ledger
                    if row["dataset_split"] == split
                    and row["strategy"] == strategy
                    and row["configuration_id"] == configuration
                    and row["ledger_family"] == "electricity"
                ]
                values = {row["component"]: float(row["weighted_annual_equivalent_value"]) for row in selected}
                assert values["represented_gross_electricity"] == pytest.approx(
                    values["generator_internal_electricity_total"]
                    + values["represented_net_grid_import"],
                    abs=1e-3,
                )
    allowed = {
        "aligned",
        "directionally_aligned",
        "partially_aligned",
        "not_aligned",
        "not_comparable",
        "evidence_missing",
    }
    behaviour = _csv(RUN_ROOT / "behavioural_comparison.csv")
    anchors = _csv(RUN_ROOT / "anchor_comparison.csv")
    assert behaviour and anchors
    assert {row["classification"] for row in behaviour} <= allowed
    assert {row["classification"] for row in anchors} <= allowed
    assert all(row["calibration_use"] == "False" for row in behaviour + anchors)
    assert all(row["emulation_candidate_status"] == "not_available_no_qualified_candidate" for row in anchors)
    mer_dri = [row for row in anchors if row["target_id"] == "mer_c1_dri_output_2_8"]
    assert len(mer_dri) == 1
    assert mer_dri[0]["dataset_split"] == "test"
    assert float(mer_dri[0]["source_driven_baseline_value"]) == pytest.approx(2.728601866)
    assert float(mer_dri[0]["signed_residual"]) == pytest.approx(-0.071398134)
    assert float(mer_dri[0]["residual_share"]) == pytest.approx(-0.0254993336)
    assert mer_dri[0]["validation_role"] == "scenario_definition_consistency_check"
    assert mer_dri[0]["calibration_use"] == "False"
    assert mer_dri[0]["validation_use"] == "False"
    assert mer_dri[0]["independent_validation_use"] == "False"
    assert mer_dri[0]["overlap_double_counting_risk"] == "high_direct_parameter_overlap"
    parity = _csv(RUN_ROOT / "flat_price_parity_checks.csv")
    assert sum(row["status"] == "pass" for row in parity) == 6
    assert sum(row["status"] == "not_comparable" for row in parity) == 2
