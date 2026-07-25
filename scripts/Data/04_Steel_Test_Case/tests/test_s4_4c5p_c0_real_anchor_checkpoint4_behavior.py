from __future__ import annotations

import csv
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
from steel.s4_4c5p_c0_real_anchor_checkpoint4_behavior import (
    Checkpoint4BehaviorError,
    DEFAULT_CONFIG_PATH,
    EXPECTED_CANDIDATES,
    EXPECTED_PERIODS,
    EXPECTED_SCENARIOS,
    candidate_overrides,
    executed_prices_for_hourly,
    frozen_scenario_matrix,
    load_checkpoint4_config,
    prepare_checkpoint4,
    scenario_response_contract_rows,
    validate_checkpoint4_config,
)


def test_checkpoint4_freezes_exact_two_by_six_matrix_and_two_periods() -> None:
    config = load_checkpoint4_config()
    validate_checkpoint4_config(config)
    matrix = frozen_scenario_matrix(config)

    assert len(matrix) == 12
    assert tuple(dict.fromkeys(row["candidate_id"] for row in matrix)) == (
        EXPECTED_CANDIDATES
    )
    assert tuple(dict.fromkeys(row["scenario_id"] for row in matrix)) == (
        EXPECTED_SCENARIOS
    )
    assert tuple(
        row["period_id"] for row in config["checkpoint_4"]["development_periods"]
    ) == EXPECTED_PERIODS
    assert all(
        row["final_held_out_selection_eligible"] is False for row in matrix
    )


def test_checkpoint4_y_true_is_isolated_to_explicit_oracle() -> None:
    config = load_checkpoint4_config()
    scenarios = config["checkpoint_4"]["scenarios"]
    y_true = [row for row in scenarios if row["price_field"] == "y_true"]

    assert [row["scenario_id"] for row in y_true] == [
        "volatile_negative_oracle_y_true"
    ]
    assert y_true[0]["perfect_foresight_oracle"] is True
    assert all(
        row["price_field"] == "y_pred"
        and row["perfect_foresight_oracle"] is False
        for row in scenarios
        if row["scenario_id"] != "volatile_negative_oracle_y_true"
    )


def test_executed_price_join_uses_global_executed_hour_not_local_hour() -> None:
    prices = [
        {
            "replan_index": "0",
            "executed_hour_index": "0",
            "model_hour": "0",
            "price_eur_per_mwh_e": "40.0",
        },
        {
            "replan_index": "1",
            "executed_hour_index": "24",
            "model_hour": "0",
            "price_eur_per_mwh_e": "120.0",
        },
    ]
    hourly = [
        {
            "replan_index": "1",
            "executed_hour_index": "24",
            "hour_index": "0",
        },
        {
            "replan_index": "0",
            "executed_hour_index": "0",
            "hour_index": "99",
        },
    ]

    assert executed_prices_for_hourly(prices, hourly) == [120.0, 40.0]
    with pytest.raises(Checkpoint4BehaviorError, match="executed_hour_index"):
        executed_prices_for_hourly(
            prices,
            [{"replan_index": "0", "hour_index": "0"}],
        )


def test_checkpoint4_candidate_overrides_preserve_reviewed_pair() -> None:
    config = load_checkpoint4_config()
    baseline, recovery = config["checkpoint_4"]["candidates"]

    baseline_overrides = candidate_overrides(config, baseline)
    recovery_overrides = candidate_overrides(config, recovery)

    assert baseline_overrides[
        "site_background_electricity_mwh_h_by_configuration"
    ] == {C0_CONFIGURATION: 0.0, C1_CONFIGURATION: 0.0}
    assert "c0_aggregate_generator_technical_interface" not in baseline_overrides
    assert "c0_full_site_energy_bridge" not in baseline_overrides
    assert recovery_overrides[
        "site_background_electricity_mwh_h_by_configuration"
    ] == {
        C0_CONFIGURATION: pytest.approx(90.46803652968036),
        C1_CONFIGURATION: 0.0,
    }
    interface = recovery_overrides["c0_aggregate_generator_technical_interface"]
    assert interface["electricity_efficiency"] == pytest.approx(0.345)
    assert interface["electrical_capacity_mw"] == pytest.approx(770.0)
    assert interface["total_fuel_volume_cap_nm3_h"] == pytest.approx(900000.0)
    assert recovery["candidate_classification"] == "emulation_sensitivity_only"
    assert recovery["promotable_central_from_checkpoint4"] is False


def test_checkpoint4_expectations_and_proxy_are_frozen_without_bypass() -> None:
    config = load_checkpoint4_config()
    expectations = {
        row["expectation_id"]: row
        for row in scenario_response_contract_rows(config)
    }
    required = {
        "all_physical_and_accounting_guardrails",
        "recovery_low_vs_high_energy_response",
        "recovery_high_vs_low_energy_response",
        "baseline_flexible_bridge_response",
        "volatile_predicted_price_response",
        "negative_price_redistribution",
        "oracle_first_window_realised_cost_dominance",
        "aggregate_vn25_off_proxy_response",
        "c1_unchanged_by_c0_repair",
    }
    assert set(expectations) == required
    assert expectations["baseline_flexible_bridge_response"]["applicability"] == (
        "not_applicable"
    )
    assert expectations["oracle_first_window_realised_cost_dominance"][
        "uses_realised_future_information_operationally"
    ] is True
    assert all(row["frozen_before_solver_execution"] for row in expectations.values())

    stress = config["checkpoint_4"]["physical_stress_contract"]
    assert stress["stress_id"] == "aggregate_vn25_off_proxy"
    assert stress["execution_availability"] == "structurally_unavailable"
    assert stress["proposed_electrical_capacity_mw"] == pytest.approx(420.0)
    assert stress["proposed_total_fuel_volume_cap_nm3_h"] == pytest.approx(300000.0)
    assert stress["historical_tata_event"] is False
    assert stress["exact_vn25_ij01_split"] is False
    assert stress["safeguard_bypass_allowed"] is False


def test_checkpoint4_prepare_is_non_solver_and_persists_frozen_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_solver(*args: object, **kwargs: object) -> None:
        raise AssertionError("prepare_checkpoint4 must never invoke the rolling runner")

    monkeypatch.setattr(
        "steel.s4_4c5p_c0_real_anchor_checkpoint4_behavior."
        "run_closed_loop_feasibility_anchor_reconciliation",
        forbidden_solver,
    )
    result = prepare_checkpoint4(DEFAULT_CONFIG_PATH)
    output = Path(result["output_root"])

    assert result["status"] == "checkpoint4_prepared_reviewed_checkpoint3"
    assert result["rolling_case_count"] == 12
    assert result["solver_invoked"] is False
    with (output / "scenario_response_contract.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        contract = list(csv.DictReader(handle))
    with (output / "scenario_matrix.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        matrix = list(csv.DictReader(handle))
    assert len(contract) == 9
    assert len(matrix) == 12
    assert not any(
        row["price_field"] == "y_true"
        and row["scenario_id"] != "volatile_negative_oracle_y_true"
        for row in matrix
    )
