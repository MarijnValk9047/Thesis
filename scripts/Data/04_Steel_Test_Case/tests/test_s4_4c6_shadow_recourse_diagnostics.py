from __future__ import annotations

from pathlib import Path
import sys


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_shadow_recourse_diagnostics import (  # noqa: E402
    classify_shadow_recourse,
    load_shadow_recourse_config,
)


def test_shadow_recourse_config_is_bounded_and_non_final() -> None:
    config = load_shadow_recourse_config()
    assert config["delivery_day"] == "2025-03-02"
    assert config["diagnostic_contract"]["scenario_count"] == 10
    assert config["forbidden_scope"]["final_regime_weeks"]
    assert config["forbidden_scope"]["S30_replanning"]
    assert config["forbidden_scope"]["robust_bid_curve_promotion"]


def test_inside_envelope_path_splicing_requires_method_decision() -> None:
    result = classify_shadow_recourse(
        exact_infeasible=True,
        nearest_complete_feasible=True,
        outside_quantity_envelope_count=0,
        minimum_deviation_mwh=2.5,
    )
    assert result["classification"] == (
        "structural_path_splicing_inside_quantity_envelope"
    )
    assert result["requires_methodological_decision"]
    assert not result["implementation_or_contract_error"]
