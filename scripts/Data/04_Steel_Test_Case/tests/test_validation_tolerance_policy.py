from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.validation_tolerance_policy import (
    ELECTRICITY_BALANCE_TOLERANCE_MWH,
    LEGACY_RUNNER_INVENTORY_COUNT,
    LEGACY_RUNNER_INVENTORY_SHA256,
    LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_COUNT,
    LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_SHA256,
    POLICY_ENFORCED_RUNNERS,
    POLICY_ENFORCED_STEEL_MODULES,
    POLICY_FINGERPRINT,
    SOLVER_NUMERICAL_TOLERANCE,
    ValidationTolerancePolicyError,
    constraint_family_rule,
    exact_input_fingerprint,
    hourly_money_identity_record,
    policy_contract,
    presentation_value,
    require_exact_input_fingerprint,
    require_new_file_policy_registration,
    repository_policy_registration_diagnostics,
    resolve_policy_contract,
    threshold_comparison_record,
    threshold_comparison_rule,
    trajectory_cost_record,
    validate_hourly_and_trajectory_costs,
    validation_record,
)


def test_canonical_policy_identity_is_self_verifying() -> None:
    contract = policy_contract()
    assert contract["policy_fingerprint_sha256"] == POLICY_FINGERPRINT
    assert resolve_policy_contract(contract) == contract
    with pytest.raises(ValidationTolerancePolicyError):
        resolve_policy_contract({**contract, "policy_version": "changed"})


def test_preserved_volatile_deadline_residual_passes_against_one_tonne() -> None:
    rule = constraint_family_rule("rolling_production_deadline")
    record = validation_record(
        validation_id="rolling_production_deadline[24]",
        purpose=rule.purpose,
        unit=rule.unit,
        raw_residual=1.0000003385357559e-6,
        allowed_tolerance=rule.tolerance,
        aggregation=rule.aggregation,
        used_relaxation=1.0000003385357559e-6,
    )
    assert rule.tolerance == 1.0
    assert record["status"] == "pass"


def test_cumulative_production_residual_above_one_tonne_fails() -> None:
    rule = constraint_family_rule("rolling_production_deadline")
    record = validation_record(
        validation_id="rolling_production_deadline[24]",
        purpose=rule.purpose,
        unit=rule.unit,
        raw_residual=1.000001,
        allowed_tolerance=rule.tolerance,
        aggregation=rule.aggregation,
        used_relaxation=1.0,
    )
    assert record["status"] == "fail"


def test_one_eur_per_mwh_ng_input_mutation_fails_exact_fingerprint() -> None:
    frozen = {
        "price_id": "natural_gas_ttf_proxy",
        "unit": "EUR/MWh_LHV",
        "value": 55.0,
    }
    expected = exact_input_fingerprint(frozen)
    with pytest.raises(ValidationTolerancePolicyError):
        require_exact_input_fingerprint(
            {**frozen, "value": 56.0},
            expected_fingerprint=expected,
            purpose="frozen NG input price",
        )


def test_one_eur_aggregate_residual_passes_for_multi_million_total() -> None:
    record = trajectory_cost_record(
        "yearly_cost",
        1.0,
        comparison_scale_eur=50_000_000.0,
    )
    assert record["allowed_tolerance"] == 1.0
    assert record["status"] == "pass"


def test_excessive_hourly_money_or_electricity_balance_residual_fails() -> None:
    assert hourly_money_identity_record("hour[0]", 0.010001)["status"] == "fail"
    electricity = validation_record(
        validation_id="gross_site_electricity_balance[0]",
        purpose="hourly_electricity_balance_identity",
        unit="MWh_e",
        raw_residual=2e-6,
        allowed_tolerance=ELECTRICITY_BALANCE_TOLERANCE_MWH,
        aggregation="per_hour_no_accumulation",
    )
    assert electricity["status"] == "fail"


def test_exact_preserved_electricity_threshold_roundoff_passes() -> None:
    raw_residual = 1.0000000543186616e-6
    record = threshold_comparison_record(
        validation_id="preserved_full_matrix[electricity_identity]",
        purpose="electricity_identity",
        raw_residual=raw_residual,
    )
    assert record["raw_residual"] == raw_residual
    assert record["allowed_tolerance"] == 1e-6
    assert record["governed_tolerance"] == 1e-6
    assert record["positive_excess"] == raw_residual - 1e-6
    assert record["comparison_roundoff_allowance"] == 256 * math.ulp(1.0)
    assert record["positive_excess"] <= record["comparison_roundoff_allowance"]
    assert record["normalized_residual"] == raw_residual / 1e-6
    assert record["tolerance_accumulation_allowed"] is False
    assert record["status"] == "pass"


@pytest.mark.parametrize("raw_residual", [1.001e-6, 1e-6 + 1e-9])
def test_substantive_electricity_threshold_excess_fails(
    raw_residual: float,
) -> None:
    record = threshold_comparison_record(
        validation_id="electricity_threshold_failure",
        purpose="wag_and_ng_generation_exactly_separate",
        raw_residual=raw_residual,
    )
    assert record["positive_excess"] > record["comparison_roundoff_allowance"]
    assert record["status"] == "fail"


def test_unknown_threshold_comparison_purpose_fails_closed() -> None:
    with pytest.raises(ValidationTolerancePolicyError, match="Unregistered"):
        threshold_comparison_rule("future_unregistered_guardrail")


def test_threshold_roundoff_policy_does_not_change_other_tolerances() -> None:
    assert hourly_money_identity_record("hour[0]", 0.010001)["status"] == "fail"
    assert trajectory_cost_record(
        "trajectory", 1.000001, comparison_scale_eur=1.0
    )["status"] == "fail"
    state = validation_record(
        validation_id="state",
        purpose="terminal_or_carried_material_state",
        unit="t",
        raw_residual=1.000001,
        allowed_tolerance=1.0,
        aggregation="terminal_snapshot",
    )
    assert state["status"] == "fail"


def test_unknown_constraint_family_fails_closed() -> None:
    with pytest.raises(ValidationTolerancePolicyError):
        constraint_family_rule("future_unregistered_family")


def test_hourly_tolerances_cannot_accumulate_to_hide_trajectory_error() -> None:
    result = validate_hourly_and_trajectory_costs(
        [0.005] * 300,
        trajectory_residual_eur=1.5,
        comparison_scale_eur=10_000_000.0,
    )
    assert all(row["status"] == "pass" for row in result["hourly"])
    assert result["trajectory"]["allowed_tolerance"] == 1.0
    assert result["trajectory"]["status"] == "fail"
    assert result["status"] == "fail"
    assert result["tolerance_accumulation_allowed"] is False


def test_binary_and_physical_validation_remain_solver_strict() -> None:
    rule = constraint_family_rule("grid_import_capacity")
    assert rule.tolerance == SOLVER_NUMERICAL_TOLERANCE
    assert rule.relaxation_allowed is False


def test_machine_precision_is_separate_from_user_facing_formatting() -> None:
    assert presentation_value(
        1.0000003385357559e-6,
        unit="t",
        purpose="cumulative_production_acceptance",
        tolerance=1.0,
        status="pass",
    ) == "<0.001 t (tol 1.0 t): PASS"
    assert presentation_value(
        0.009,
        unit="EUR",
        purpose="hourly_money_identity",
    ) == "EUR 0.01"


def test_complete_steel_runner_and_validation_module_inventories_are_frozen() -> None:
    diagnostics = repository_policy_registration_diagnostics(STEEL_ROOT)
    assert diagnostics["status"] == "pass"
    assert diagnostics["failure_ids"] == []
    assert diagnostics["runner_count"] == (
        LEGACY_RUNNER_INVENTORY_COUNT + len(POLICY_ENFORCED_RUNNERS)
    )
    assert diagnostics["legacy_runner_inventory_sha256"] == (
        LEGACY_RUNNER_INVENTORY_SHA256
    )
    assert diagnostics["policy_relevant_module_count"] == (
        LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_COUNT
        + len(POLICY_ENFORCED_STEEL_MODULES)
    )
    assert diagnostics["legacy_policy_relevant_module_inventory_sha256"] == (
        LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_SHA256
    )


def test_unregistered_future_optimization_runner_fails_closed() -> None:
    with pytest.raises(
        ValidationTolerancePolicyError,
        match="must import the shared validation tolerance policy",
    ):
        require_new_file_policy_registration(
            "scripts/Data/04_Steel_Test_Case/run_future_optimisation.py",
            "def main():\n    return 0\n",
        )


def test_unregistered_tolerance_bearing_validation_module_fails_closed() -> None:
    with pytest.raises(
        ValidationTolerancePolicyError,
        match="must import the shared validation tolerance policy",
    ):
        require_new_file_policy_registration(
            "scripts/Data/04_Steel_Test_Case/steel/future_containment_evidence.py",
            (
                "def validate_containment(value, tolerance=0.1):\n"
                "    return value <= tolerance\n"
            ),
        )


def test_frozen_physical_constant_alone_is_not_a_policy_registration_target() -> None:
    require_new_file_policy_registration(
        "scripts/Data/04_Steel_Test_Case/steel/future_physical_inputs.py",
        "FROZEN_PHYSICAL_EFFICIENCY = 0.345\n",
    )
