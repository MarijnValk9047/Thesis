from __future__ import annotations

from pathlib import Path
import sys

from pyomo.environ import ConcreteModel, Expression, RangeSet, Var
import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5b_c0_export_sensitivity import (
    CONFIG_PATH,
    EXPECTED_PERIODS,
    EXPECTED_POLICIES,
    MATERIAL_THRESHOLD_TWH_E_Y,
    _fingerprintable_overrides,
    frozen_case_matrix,
    install_terminal_validation_extension,
    load_config,
    validate_config,
)
from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    _campaign_progress_reference_routing,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    _capture_sale_state_preservation_targets,
)


def test_phase5b_matrix_is_exactly_one_pair_over_two_development_weeks() -> None:
    config = load_config(CONFIG_PATH)
    validate_config(config)
    rows = frozen_case_matrix(config)
    assert len(rows) == 4
    assert tuple(dict.fromkeys(row["period_id"] for row in rows)) == EXPECTED_PERIODS
    assert tuple(dict.fromkeys(row["policy_id"] for row in rows)) == EXPECTED_POLICIES
    assert sum(row["expected_model_count"] for row in rows) == 56
    assert {row["dataset_split"] for row in rows} == {"validation"}
    assert {row["price_field"] for row in rows} == {"y_pred"}
    assert not any(row["perfect_foresight_oracle"] for row in rows)
    assert config["phase5b"]["material_threshold_twh_e_y"] == MATERIAL_THRESHOLD_TWH_E_Y


def test_only_export_switch_and_capture_metadata_are_excluded_from_pair_fingerprint() -> None:
    common = {"physical": 1, "terminal_band": {"x": 2}, "price_field": "y_pred"}
    comparator = {
        **common, "run_id": "normal", "lineage_role": "child",
        "normal_solution_capture": {"directory": "capture"},
        "phase5b_export_switch": False,
    }
    sale = {
        **common, "run_id": "sale", "lineage_role": "child",
        "c0_electricity_sale_sensitivity": {"enabled": True},
        "phase5b_export_switch": True,
    }
    assert _fingerprintable_overrides(comparator) == _fingerprintable_overrides(sale)


def test_central_config_remains_no_export_and_phase5b_is_sensitivity_only() -> None:
    config = load_config(CONFIG_PATH)
    assert config["phase5b"]["frozen_interface"]["central_model_export_allowed"] is False
    assert config["git_eligible"] is False
    assert config["output_policy"] == "minimal"


def test_phase4_terminal_rows_get_only_the_canonical_terminal_validation_rule() -> None:
    manifest = install_terminal_validation_extension()
    assert manifest["scope"] == "isolated_sale_containment_validation_clone_only"
    assert manifest["families"] == [
        "rolling_terminal_inventory_lower_bounds",
        "rolling_terminal_inventory_upper_bounds",
    ]
    assert manifest["rule"] == {
        "purpose": "terminal_or_carried_material_state",
        "unit": "t",
        "tolerance": 1.0,
        "aggregation": "terminal_snapshot",
        "relaxation_allowed": True,
    }


def test_route_progress_capture_prevents_february_replan_3_rhs_drift() -> None:
    annual_upper_mt_y = 5.309021739
    comparator_executed_hsm_t = 43_427.63550800001
    drift_t = 52.369865
    definition_rows = [
        {
            "configuration": "C0",
            "metric": "hsm_final_output",
            "annual_band_lower_mt_y": 5.256195652,
            "annual_band_upper_mt_y": annual_upper_mt_y,
        }
    ]
    routing = {
        "reference_validation_bands": {
            "hsm_final_output": {"lower_t": 0.0, "upper_t": 0.0}
        }
    }

    def resolved_upper(executed_hsm_t: float) -> float:
        resolved = _campaign_progress_reference_routing(
            routing,
            definition_rows=definition_rows,
            configuration=C0_CONFIGURATION,
            executed_rows=[
                {
                    "configuration_id": C0_CONFIGURATION,
                    "C0_HSM_final_product_t": executed_hsm_t,
                }
            ],
            executed_hours_before=72,
            deadline_hours=[72],
        )
        assert resolved is not None
        return resolved["reference_deadline_bands"]["hsm_final_output"][72][
            "upper_t"
        ]

    comparator_upper = resolved_upper(comparator_executed_hsm_t)
    drifted_upper = resolved_upper(comparator_executed_hsm_t + drift_t)
    assert comparator_upper == pytest.approx(43_843.95472213699)
    assert drifted_upper == pytest.approx(43_791.58485713699)
    assert comparator_upper - drifted_upper == pytest.approx(drift_t)

    model = ConcreteModel()
    model.TIME = RangeSet(0, 1)
    model.final_product_output = Expression(model.TIME, rule=lambda _m, _t: 10.0)
    model.bof_crude_steel_output = Expression(model.TIME, rule=lambda _m, _t: 11.0)
    model.c0_hsm_final_product_output = Expression(model.TIME, rule=lambda _m, _t: 8.0)
    model.c0_dsp_final_product_output = Expression(model.TIME, rule=lambda _m, _t: 2.0)
    for component in (
        "coke_inventory",
        "sinter_inventory",
        "hot_iron_inventory",
        "cold_slab_inventory",
    ):
        setattr(model, component, Var(model.TIME, initialize=1.0))
    capture = _capture_sale_state_preservation_targets(
        model,
        contract={
            "schema_version": "steel_phase2_sale_state_preservation_v4",
            "enabled": True,
            "configuration_id": C0_CONFIGURATION,
            "replan_index": 3,
            "execution_hours": 2,
            "implementation_sha256": "a" * 64,
        },
        saved_capture={
            "configuration_id": C0_CONFIGURATION,
            "replan_index": 3,
            "provenance": {"implementation_sha256": "a" * 64},
        },
    )
    assert capture["targets"]["executed_bof_liquid_steel_t"] == 22.0
    assert capture["targets"]["executed_hsm_final_output_t"] == 16.0
    assert capture["targets"]["executed_dsp_final_output_t"] == 4.0
