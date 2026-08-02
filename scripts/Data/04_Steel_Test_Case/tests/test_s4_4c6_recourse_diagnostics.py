from __future__ import annotations

from pathlib import Path
import sys

import numpy as np


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_recourse_diagnostics import (  # noqa: E402
    classify_recourse_cause,
    load_recourse_diagnostic_config,
    quantity_envelope_clip,
)


def test_recourse_config_is_bounded_and_diagnostic_only() -> None:
    config = load_recourse_diagnostic_config()
    assert config["case_id"] == "S0_C1_responsive"
    assert config["diagnostic_contract"]["scenario_counts"] == [10, 30]
    assert config["output_policy"] == "minimal"
    assert config["run_class"] == "diagnostic_validation"
    assert all(config["forbidden_scope"].values())


def test_quantity_clip_uses_intervalwise_scenario_envelope() -> None:
    cleared = np.asarray([0.0, 5.0, 12.0])
    paths = np.asarray([[2.0, 4.0, 9.0], [3.0, 8.0, 10.0]])
    clipped, lower, upper = quantity_envelope_clip(cleared, paths)
    np.testing.assert_array_equal(lower, [2.0, 4.0, 9.0])
    np.testing.assert_array_equal(upper, [3.0, 8.0, 10.0])
    np.testing.assert_array_equal(clipped, [2.0, 5.0, 10.0])


def test_classification_identifies_combined_support_and_splicing() -> None:
    result = classify_recourse_cause(
        contract_checks_pass=True,
        nearest_controls_feasible=True,
        s10_exact_infeasible=True,
        s10_clipped_infeasible=True,
        s30_exact_infeasible=True,
        s10_price_undercoverage_count=10,
        s30_price_undercoverage_count=4,
    )
    assert result["classification"] == (
        "combination_support_undercoverage_and_structural_path_splicing"
    )
    assert result["requires_methodological_decision"]


def test_classification_prioritises_contract_error() -> None:
    result = classify_recourse_cause(
        contract_checks_pass=False,
        nearest_controls_feasible=False,
        s10_exact_infeasible=True,
        s10_clipped_infeasible=True,
        s30_exact_infeasible=True,
        s10_price_undercoverage_count=10,
        s30_price_undercoverage_count=4,
    )
    assert result["classification"] == "implementation_or_contract_error"
    assert not result["requires_methodological_decision"]


def test_classification_does_not_call_missing_plans_a_contract_error() -> None:
    result = classify_recourse_cause(
        contract_checks_pass=True,
        nearest_controls_feasible=None,
        s10_exact_infeasible=False,
        s10_clipped_infeasible=False,
        s30_exact_infeasible=None,
        s10_price_undercoverage_count=10,
        s30_price_undercoverage_count=4,
    )
    assert result["classification"] == "incomplete_planning_or_recourse_evidence"
    assert not result["implementation_or_contract_error"]
    assert not result["requires_methodological_decision"]


def test_classification_recognises_verified_bid_step_fix() -> None:
    result = classify_recourse_cause(
        contract_checks_pass=True,
        nearest_controls_feasible=True,
        s10_exact_infeasible=False,
        s10_clipped_infeasible=False,
        s30_exact_infeasible=None,
        pre_fix_exact_infeasible=True,
        s10_price_undercoverage_count=10,
        s30_price_undercoverage_count=4,
    )
    assert result["bid_step_canonicalisation_fix_verified"]
    assert result["implementation_or_contract_error"]
    assert not result["requires_methodological_decision"]
