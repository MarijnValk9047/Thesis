from __future__ import annotations

from pathlib import Path
import sys


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from steel.s4_4c5p_phase3_operation_route_robustness import (
    CONFIG_PATH,
    _bf_source_availability,
    _case_disposition,
    _case_overrides,
    check_phase3_config,
    frozen_case_matrix,
    load_phase3_config,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT
from steel.validation_tolerance_policy import (
    policy_contract,
    require_new_file_policy_registration,
)


def test_frozen_phase3_matrix_stays_within_authorized_cap() -> None:
    config = load_phase3_config()
    check_phase3_config(config)
    rows = frozen_case_matrix(config)
    assert len(rows) == 6
    assert sum(int(row["expected_model_count"]) for row in rows) == 84
    assert {row["dataset_split"] for row in rows} == {"validation"}
    assert {row["price_field"] for row in rows} == {"y_pred"}
    assert not any(row["perfect_foresight_oracle"] for row in rows)
    assert config["phase3"]["validation_tolerance_policy"] == policy_contract()


def test_overrides_freeze_central_boundary_and_only_route_band_varies() -> None:
    config = load_phase3_config()
    rows = frozen_case_matrix(config)
    forecast_root = REPO_ROOT.parent / "Thesis" / "forecast-placeholder"
    free = _case_overrides(config, rows[0], forecast_root)
    band = _case_overrides(config, rows[2], forecast_root)
    exact = _case_overrides(config, rows[4], forecast_root)
    assert "c1_liquid_steel_route_band" not in free
    assert band["c1_liquid_steel_route_band"] == {
        "bof_lower_share": 0.45,
        "bof_upper_share": 0.55,
    }
    assert exact["c1_liquid_steel_route_band"] == {
        "bof_lower_share": 0.503703704,
        "bof_upper_share": 0.503703704,
    }
    for payload in (free, band, exact):
        assert payload["mechanism_candidate_id"] == "recovery_bg30_ng55"
        assert payload["mechanism_ng_price_eur_per_mwh_lhv"] == 55.0
        assert payload["wag_generation_yield_overrides_by_configuration"] == {}
        assert payload["named_process_electricity_intensity_scales_by_configuration"] == {}
        assert payload["site_background_electricity_mwh_h_by_configuration"] == {
            C0_CONFIGURATION: 108.56164383561644,
            C1_CONFIGURATION: 0.0,
        }
        forbidden = {
            "product_revenue_enabled",
            "co2_ets_objective_enabled",
            "perfect_foresight_oracle",
            "sale_credit_enabled",
        }
        assert not forbidden.intersection(payload) - {"perfect_foresight_oracle"}
        assert payload["perfect_foresight_oracle"] is False


def test_route_check_reclassification_is_exact_and_fail_closed() -> None:
    config = load_phase3_config()
    free, band = frozen_case_matrix(config)[0], frozen_case_matrix(config)[2]
    models = [
        {
            "replan_index": str(replan),
            "configuration_id": configuration,
            "termination_condition": "optimal",
            "solver_status": "ok",
        }
        for replan in range(7)
        for configuration in (C0_CONFIGURATION, C1_CONFIGURATION)
    ]
    free_artifact = {
        "models": models,
        "checks": [{"check_id": "no_fixed_route_split", "status": "pass"}],
    }
    band_artifact = {
        "models": models,
        "checks": [
            {"check_id": "no_fixed_route_split", "status": "fail"},
            {"check_id": "material_balance", "status": "pass"},
        ],
    }
    assert _case_disposition(free, free_artifact) == ("pass", [])
    assert _case_disposition(band, band_artifact) == ("pass", [])
    band_artifact["checks"].append(
        {"check_id": "unexpected_physical_failure", "status": "fail"}
    )
    disposition, failures = _case_disposition(band, band_artifact)
    assert disposition == "implementation_failure"
    assert failures == ["unexpected_physical_failure"]


def test_exact_route_solver_infeasibility_is_a_physical_outcome() -> None:
    case = frozen_case_matrix(load_phase3_config())[4]
    models = [
        {
            "replan_index": str(replan),
            "configuration_id": configuration,
            "termination_condition": (
                "optimal" if configuration == C0_CONFIGURATION else "infeasible"
            ),
            "solver_status": (
                "ok" if configuration == C0_CONFIGURATION else "warning"
            ),
        }
        for replan in range(7)
        for configuration in (C0_CONFIGURATION, C1_CONFIGURATION)
    ]
    disposition, reasons = _case_disposition(
        case,
        {
            "models": models,
            "checks": [],
            "summary": {
                "c0_rolling_status": "pass",
                "c1_rolling_status": "infeasible",
            },
        },
    )
    assert disposition == "physically_explained_infeasible"
    assert "C1_solver_proven_infeasible_7_of_7" in reasons[0]


def test_bf_variants_fail_closed_without_modelbuilder_change() -> None:
    rows = _bf_source_availability(load_phase3_config())
    assert rows[0]["status"] == "evaluable"
    assert rows[1]["status"] == "not_evaluable_missing_evidence"
    assert rows[1]["execution_action"] == "not_run"


def test_new_module_is_registered_with_shared_policy() -> None:
    module_path = (
        STEEL_ROOT / "steel/s4_4c5p_phase3_operation_route_robustness.py"
    )
    require_new_file_policy_registration(
        str(module_path.relative_to(STEEL_ROOT)).replace("\\", "/"),
        module_path.read_text(encoding="utf-8"),
    )
    assert CONFIG_PATH.is_file()
