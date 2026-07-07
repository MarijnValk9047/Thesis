from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import C0, C1  # noqa: E402
from steel.s4_4c5n_a_pefa_pelletizing_layer import C5N_A_DIR  # noqa: E402
from steel.s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy import (  # noqa: E402
    C5N_B_DIR,
    STAGE,
    run_s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy,
)


SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/PELLETIZING_Parameters.md")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


@pytest.fixture(scope="module")
def c5n_b_outputs() -> Path:
    run_s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy()
    return C5N_B_DIR


def test_c5n_b_required_outputs_and_stage_status(c5n_b_outputs: Path):
    required = [
        "s4_4c5n_b_stage_gate.json",
        "s4_4c5n_b_run_registry.csv",
        "s4_4c5n_b_pellet_burden_development_input_rows.csv",
        "s4_4c5n_b_pellet_validation_anchors.csv",
        "s4_4c5n_b_pellet_balance_report.csv",
        "s4_4c5n_b_pellet_inventory_dashboard.csv",
        "s4_4c5n_b_bulk_solid_storage_policy_dashboard.csv",
        "s4_4c5n_b_compact_healthcheck.csv",
        "s4_4c5n_b_red_flags.csv",
        "s4_4c5n_b_compact_table_for_chat.csv",
        "s4_4c5n_b_pellet_burden_balance_report.json",
        "s4_4c5n_b_summary.json",
    ]
    for name in required:
        path = c5n_b_outputs / name
        assert path.exists(), name
        if path.suffix == ".csv":
            assert _read_csv(path)
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    gate = json.loads((c5n_b_outputs / "s4_4c5n_b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["stage_id"] == STAGE
    assert gate["decision"] == "pass_development_pellet_burden_balance_and_bulk_storage_policy"
    assert gate["status"] == "development_only"
    assert gate["thesis_usability"] is False
    assert gate["hidden_solver_slack_active"] is False
    assert gate["validation_anchors_used_as_hourly_constraints"] is False


def test_pelletizing_source_card_documents_burden_and_storage_policy():
    text = SOURCE_CARD.read_text(encoding="utf-8")
    assert "Simplified pellet burden / BF-DRP balance layer" in text
    assert "fired_pellets_proxy" in text
    assert "single_fired_pellets_proxy" in text
    assert "BF_PELLET_INPUT_T_PER_T_HM_C0_DERIVED" in text
    assert "BF_PELLET_INPUT_T_PER_T_HM_C1_RESIDUAL" in text
    assert "DRP_PELLET_INPUT_T_PER_T_DRI" in text
    assert "practically_non_binding_bulk_solid_storage" in text
    assert "not Tata operating truth and not thesis-approved" in text


def test_pellet_development_input_rows_are_governed(c5n_b_outputs: Path):
    rows = _read_csv(c5n_b_outputs / "s4_4c5n_b_pellet_burden_development_input_rows.csv")
    by_id = {row["parameter_id"]: row for row in rows}
    required = {
        "PELLET_GRADE_MODE",
        "BF_PELLET_INPUT_T_PER_T_HM_C0_DERIVED",
        "BF_PELLET_INPUT_T_PER_T_HM_C1_RESIDUAL",
        "BF_PELLET_INPUT_T_PER_T_HM_GENERIC_BREF",
        "DRP_PELLET_INPUT_T_PER_T_DRI",
        "IMPORTED_PELLETS_ALLOWED",
        "IMPORTED_PELLETS_C0_ANCHOR_MT_Y",
        "IMPORTED_PELLETS_C1_BASE_MT_Y",
        "COKE_STORAGE_CAPACITY_MODE",
        "SINTER_STORAGE_CAPACITY_MODE",
        "PELLET_STORAGE_CAPACITY_MODE",
        "PELLET_GAP_TOLERANCE_REL",
        "PELLET_GAP_TOLERANCE_MT_Y",
    }
    assert required <= set(by_id)
    for row in rows:
        assert row["thesis_usability"] == "false"
        assert row["human_review_required"] == "true"
        assert row["codex_may_decide"] == "false"
        assert row["source_card"].endswith("PELLETIZING_Parameters.md")
        assert row["caveat"]

    anchors = _read_csv(c5n_b_outputs / "s4_4c5n_b_pellet_validation_anchors.csv")
    assert {row["anchor_status"] for row in anchors} == {
        "validation_anchor_and_development_reconciliation_not_hourly_constraint"
    }


def test_c0_pellet_balance_closes_without_drp(c5n_b_outputs: Path):
    rows = _keyed(_read_csv(c5n_b_outputs / "s4_4c5n_b_pellet_balance_report.csv"))
    c0 = rows[(C0, 24)]
    supply = _num(c0["PEFA_fired_pellets_output_site_t_y"]) + _num(c0["imported_pellets_site_t_y"])
    demand = _num(c0["BF_pellet_demand_site_t_y"]) + _num(c0["DRP_pellet_demand_site_t_y"])
    assert supply == pytest.approx(demand, abs=1e-6)
    assert _num(c0["resolved_BF_pellet_input_t_per_t_HM"]) == pytest.approx((4.6 + 1.5) / 6.3, rel=1e-6)
    assert _num(c0["DRP_pellet_demand_site_t_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(c0["pellet_gap_site_t_y"]) == pytest.approx(0.0, abs=1e-6)
    assert _num(c0["pellet_surplus_site_t_y"]) == pytest.approx(0.0, abs=1e-6)


def test_c1_pellet_balance_closes_with_dynamic_residual_bf_coefficient(c5n_b_outputs: Path):
    rows = _keyed(_read_csv(c5n_b_outputs / "s4_4c5n_b_pellet_balance_report.csv"))
    c1 = rows[(C1, 24)]
    drp_coeff = 1.0 / 0.74
    assert _num(c1["resolved_DRP_pellet_input_t_per_t_DRI"]) == pytest.approx(drp_coeff, rel=1e-6)
    assert _num(c1["DRP_pellet_demand_site_t_y"]) == pytest.approx(
        _num(c1["DRP_DRI_output_site_t_y"]) * drp_coeff,
        abs=1e-6,
    )
    supply = _num(c1["PEFA_fired_pellets_output_site_t_y"]) + _num(c1["imported_pellets_site_t_y"])
    demand = _num(c1["BF_pellet_demand_site_t_y"]) + _num(c1["DRP_pellet_demand_site_t_y"])
    assert supply == pytest.approx(demand, abs=1e-6)
    assert _num(c1["resolved_BF_pellet_input_t_per_t_HM"]) == pytest.approx(0.501786, rel=1e-6)
    assert c1["resolved_BF_pellet_coeff_source"] == "dynamic_C1_residual_from_scaled_PEFA_import_DRP_context"
    assert _num(c1["pellet_gap_site_t_y"]) == pytest.approx(0.0, abs=1e-6)


def test_pellet_imports_are_fixed_and_gap_is_diagnostic_not_slack(c5n_b_outputs: Path):
    rows = _read_csv(c5n_b_outputs / "s4_4c5n_b_pellet_balance_report.csv")
    for row in rows:
        assert row["imported_pellets_policy"] == "fixed_exogenous_scaled_development_supply_not_slack"
        assert row["pellet_gap_or_surplus_is_solver_slack"] == "false"
        assert row["validation_anchors_used_as_hourly_constraints"] == "false"
        assert row["pellet_balance_within_tolerance"] == "true"


def test_bulk_solid_storage_policy_is_nonbinding(c5n_b_outputs: Path):
    rows = _read_csv(c5n_b_outputs / "s4_4c5n_b_bulk_solid_storage_policy_dashboard.csv")
    carriers = {row["bulk_solid_carrier"] for row in rows}
    assert {"coke", "sinter", "fired_pellets_proxy"} <= carriers
    for row in rows:
        assert row["storage_capacity_mode"] == "practically_non_binding_bulk_solid_storage"
        assert row["thesis_usability"] == "false"
        assert int(row["capacity_bind_count"]) == 0
        assert row["production_or_yield_changed"] == "false"

    inventory = _read_csv(c5n_b_outputs / "s4_4c5n_b_pellet_inventory_dashboard.csv")
    for row in inventory:
        assert row["storage_capacity_mode"] == "practically_non_binding_bulk_solid_storage"
        assert row["negative_inventory_flag"] == "false"
        assert int(row["capacity_bind_count"]) == 0
        assert _num(row["pellet_inventory_start_t"]) == pytest.approx(_num(row["pellet_inventory_end_t"]), abs=1e-6)


def test_healthcheck_redflags_are_failures_false_with_required_caveats(c5n_b_outputs: Path):
    health = _read_csv(c5n_b_outputs / "s4_4c5n_b_compact_healthcheck.csv")
    redflags = _read_csv(c5n_b_outputs / "s4_4c5n_b_red_flags.csv")
    for row in health:
        assert row["status"] == "development_only"
        assert row["thesis_usability"] == "false"
        assert row["pellet_grade_quality_modelled"] == "false"
        assert "PELLET_GRADE_PROXY_ACTIVE" in row["caveats"]
        assert row["red_flags"] == ""

    for row in redflags:
        assert row["PELLET_GRADE_PROXY_ACTIVE"] == "true"
        assert int(row["failure_count"]) == 0
        assert row["status"] == "pass_with_caveats"
        if row["configuration"] == C1:
            assert row["C1_BF_PELLET_COEFF_IS_RESIDUAL_NOT_TECHNOLOGY_SOURCE"] == "true"


def test_c5n_a_pefa_behaviour_still_passes(c5n_b_outputs: Path):
    gate = json.loads((C5N_A_DIR / "s4_4c5n_a_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_pefa_pelletizing_layer"
    redflags = _read_csv(C5N_A_DIR / "s4_4c5n_a_red_flags.csv")
    assert all(int(row["failure_count"]) == 0 for row in redflags)

    c5n_b_gate = json.loads((c5n_b_outputs / "s4_4c5n_b_stage_gate.json").read_text(encoding="utf-8"))
    assert c5n_b_gate["bulk_solid_storage_capacity_mode"] == "practically_non_binding_bulk_solid_storage"
