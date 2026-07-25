from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from steel.s4_4c5p_c0_real_anchor_mechanism_experiment import (
    EXPECTED_CANDIDATES,
    EXPECTED_PERIODS,
    EXPECTED_SCENARIOS,
    FINAL_DECISION,
    SPECIAL_NG_FLOWS,
    TIE_BREAK_INTERPRETATION,
    _mechanism_rows,
    basic_ledger_guardrails,
    bf_utilization_metrics,
    candidate_overrides,
    delta_inventory_price_correlation,
    frozen_scenario_matrix,
    load_mechanism_config,
    mwh_lhv_to_pj,
    solver_invoked_this_invocation,
    structural_parameter_invariance_rows,
    validate_mechanism_config,
    validate_unique_named_ng_pricing,
)


def test_exact_five_by_three_matrix_uses_only_two_development_weeks() -> None:
    config = load_mechanism_config()
    validate_mechanism_config(config)
    matrix = frozen_scenario_matrix(config)

    assert len(matrix) == 15
    assert tuple(dict.fromkeys(row["candidate_id"] for row in matrix)) == (
        EXPECTED_CANDIDATES
    )
    assert tuple(dict.fromkeys(row["scenario_id"] for row in matrix)) == (
        EXPECTED_SCENARIOS
    )
    assert tuple(
        row["period_id"] for row in config["experiment"]["development_periods"]
    ) == EXPECTED_PERIODS
    assert {row["dataset_split"] for row in matrix} == {"validation"}
    assert not any(row["final_held_out_selection_eligible"] for row in matrix)
    assert not any("test_" in row["period_id"] for row in matrix)


def test_candidates_preserve_physical_parameters_and_change_only_boundary_price() -> None:
    config = load_mechanism_config()
    candidates = {
        row["candidate_id"]: row for row in config["experiment"]["candidates"]
    }
    baseline = candidate_overrides(config, candidates["source_driven_baseline"])
    repair = candidate_overrides(config, candidates["recovery_bg30_ng30"])

    assert baseline["site_background_electricity_mwh_h_by_configuration"] == {
        C0_CONFIGURATION: 0.0,
        C1_CONFIGURATION: 0.0,
    }
    assert "c0_aggregate_generator_technical_interface" not in baseline
    assert "c0_full_site_energy_bridge" not in baseline
    assert baseline["price_scenario_overrides"] == {
        "natural_gas_ttf_proxy": "development_central"
    }
    assert repair["wag_generation_yield_overrides_by_configuration"] == {}
    assert repair["price_scenario_overrides"] == {
        "natural_gas_ttf_proxy": "development_low"
    }
    generator = repair["c0_aggregate_generator_technical_interface"]
    bridge = repair["c0_full_site_energy_bridge"]
    assert generator["electricity_efficiency"] == pytest.approx(0.345)
    assert generator["electrical_capacity_mw"] == pytest.approx(770.0)
    assert generator["total_fuel_volume_cap_nm3_h"] == pytest.approx(900000.0)
    assert generator["export_allowed"] is False
    assert bridge["inferred_low_case_full_site_ng_floor_pj_y"] == pytest.approx(
        8.005
    )
    assert bridge["flexible_other_site_heat_service_envelope_pj_y"] == pytest.approx(
        3.07
    )


def test_each_special_ng_flow_is_priced_once_and_residual_is_never_priced() -> None:
    rows = []
    for flow_id in SPECIAL_NG_FLOWS:
        for hour in range(2):
            rows.append(
                {
                    "configuration_id": C0_CONFIGURATION,
                    "replan_index": "0",
                    "executed_hour_index": str(hour),
                    "flow_id": flow_id,
                    "price_id": "natural_gas_ttf_proxy",
                    "price_eur_per_unit": "30.0",
                    "cost_route": "external_purchase",
                }
            )
    checks = validate_unique_named_ng_pricing(
        rows, expected_price_eur_per_mwh_lhv=30.0, executed_hours=2
    )
    assert len(checks) == 4
    assert all(row["status"] == "pass" for row in checks)

    duplicate = rows + [dict(rows[0])]
    checks = validate_unique_named_ng_pricing(
        duplicate, expected_price_eur_per_mwh_lhv=30.0, executed_hours=2
    )
    assert next(
        row for row in checks if row["check_id"] == "unique_pricing::C0_NG_GENERATOR"
    )["status"] == "fail"


def test_cost_physical_no_export_and_carrier_guardrails_close() -> None:
    physical = [
        {
            "configuration_id": C0_CONFIGURATION,
            "ledger_family": "electricity",
            "component": "gross_grid_export",
            "carrier_or_material": "electricity",
            "flow_role": "gross_export",
            "annual_value": "0.0",
        },
        {
            "configuration_id": C0_CONFIGURATION,
            "ledger_family": "electricity",
            "component": "electricity_identity",
            "carrier_or_material": "electricity",
            "flow_role": "accounting_residual",
            "annual_value": "0.001",
        },
        {
            "configuration_id": C0_CONFIGURATION,
            "ledger_family": "WAG",
            "component": "BFG_generated",
            "carrier_or_material": "BFG",
            "flow_role": "generation",
            "annual_value": "10.0",
        },
    ]
    cost_rows = [{"cost_eur": "20.0"}, {"cost_eur": "30.0"}]
    checks = basic_ledger_guardrails(
        physical,
        cost_rows,
        configuration=C0_CONFIGURATION,
        reported_cost_eur=50.0,
    )
    assert {row["check_id"] for row in checks} == {
        "all_accounting_residuals",
        "no_export",
        "no_mixed_WAG",
        "cost_ledger_identity",
    }
    assert all(row["status"] == "pass" for row in checks)


def test_badarinath_metric_uses_delta_inventory_not_inventory_level() -> None:
    inventory = [0.0, 1.0, 1.0, 3.0]
    prices = [100.0, 10.0, 20.0, 30.0]
    expected = pytest.approx(0.5)

    assert delta_inventory_price_correlation(inventory, prices) == expected
    assert delta_inventory_price_correlation(inventory[:2], prices[:2]) is None


def test_bf_metric_is_utilization_and_share_at_max() -> None:
    metrics = bf_utilization_metrics([120.0, 170.0, 170.0, 150.0], 170.0)

    assert metrics["mean_utilization"] == pytest.approx(610.0 / 4.0 / 170.0)
    assert metrics["share_hours_at_max"] == pytest.approx(0.5)


def test_named_ng_anchor_conversion_is_mwh_lhv_to_pj() -> None:
    assert mwh_lhv_to_pj(2_685_000.0) == pytest.approx(9.666)


def test_structural_invariance_is_a_gate_but_realised_wag_spread_is_diagnostic() -> None:
    config = load_mechanism_config()
    structural = structural_parameter_invariance_rows(config)

    assert len(structural) == 4
    assert all(row["status"] == "pass" for row in structural)
    assert all("eta=0.345" in row["interpretation"] for row in structural)

    output = STEEL_ROOT.parents[2] / config["output_root"]
    with (output / "candidate_scenario_metrics.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        metrics = list(csv.DictReader(handle))
    rows, decision = _mechanism_rows(metrics, config)
    diagnostics = [
        row
        for row in rows
        if row["comparison_id"]
        == "bg25_bg30_bg31_realised_wag_generation_spread_diagnostic"
    ]

    assert decision == FINAL_DECISION
    assert len(diagnostics) == 3
    assert all(row["status"] == "reported_diagnostic_not_gate" for row in diagnostics)
    expected = {
        "calm_price_insensitive": (17_213.386, 0.10785),
        "volatile_negative_governed_y_pred": (19_420.107, 0.12187),
        "volatile_negative_oracle_y_true": (2_965.919, 0.01859),
    }
    for row in diagnostics:
        spread, percent = expected[row["scenario_id"]]
        assert row["spread_mwh_lhv_y"] == pytest.approx(spread, abs=0.001)
        assert row["spread_percent_of_mean"] == pytest.approx(percent, abs=0.00001)
        assert "endogenous dispatch" in row["interpretation"]
        assert "not parameter drift" in row["interpretation"]


def test_lower_ng_result_uses_exact_tiebreak_classification() -> None:
    config = load_mechanism_config()
    output = STEEL_ROOT.parents[2] / config["output_root"]
    with (output / "run_summary.json").open(encoding="utf-8") as handle:
        summary = json.load(handle)
    with (output / "mechanism_comparison.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    classification = next(
        row
        for row in rows
        if row["comparison_id"] == "allocation_location_tiebreak_interpretation"
    )

    assert summary["decision"] == FINAL_DECISION
    assert classification["status"] == "reported_non_identifiable"
    assert classification["interpretation"] == TIE_BREAK_INTERPRETATION
    assert "flexible-heat NG" in classification["interpretation"]
    assert "not proof" in classification["interpretation"]


def test_solver_invocation_flag_depends_on_new_solve_not_runner_mode() -> None:
    reused = [{"source": "reused_current_experiment_cache"} for _ in range(15)]

    assert solver_invoked_this_invocation(reused) is False
    assert solver_invoked_this_invocation(
        [*reused, {"source": "new_solve"}]
    ) is True


def test_final_manifest_hash_matches_current_mechanism_module() -> None:
    config = load_mechanism_config()
    output = STEEL_ROOT.parents[2] / config["output_root"]
    manifest = json.loads(
        (output / "input_manifest.json").read_text(encoding="utf-8")
    )
    module_relative = (
        "scripts/Data/04_Steel_Test_Case/steel/"
        "s4_4c5p_c0_real_anchor_mechanism_experiment.py"
    )
    module = STEEL_ROOT.parents[2] / module_relative
    expected_sha = hashlib.sha256(module.read_bytes()).hexdigest()
    observed = next(
        row["sha256"]
        for row in manifest["repository_files"]
        if row["path"] == module_relative
    )

    assert observed == expected_sha
