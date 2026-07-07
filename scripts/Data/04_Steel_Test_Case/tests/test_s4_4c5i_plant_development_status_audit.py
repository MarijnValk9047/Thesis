from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5i_plant_development_status_audit import (  # noqa: E402
    C5H_DIR,
    C5I_DIR,
    DEVELOPMENT_STATUSES,
    NEXT_ACTION_CLASSES,
    run_s4_4c5i_plant_development_status_audit,
)


REQUIRED_PLANTS = {
    "KGF1",
    "KGF2",
    "BF6",
    "BF7",
    "Controller_Blast_Furnace",
    "Sinter",
    "PEFA_Malerij",
    "PEFA_Branderij",
    "BOF",
    "DRP",
    "EAF",
    "casting_slab_downstream_proxy",
    "HSM",
    "DSP",
    "boilers",
    "Vattenfall",
    "flaring",
    "residual_background_electricity_load",
    "residual_background_NG_load",
    "residual_unvalidated_steam_placeholder",
    "oxygen_Linde_ASU",
    "material_store_coke",
    "material_store_sinter",
    "material_store_pellets",
    "material_store_hot_metal",
    "material_store_DRI",
    "material_store_slab_final_product_proxy",
}

ACTIVE_MARKERS = {"true", "expected_active_missing_executable", "proxy", "proxy_or_solver_internal"}
STATUS_COLUMNS = [
    "topology_status",
    "main_product_status",
    "material_conversion_status",
    "electricity_status",
    "fuel_wag_steam_status",
    "co2_status",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5i_outputs() -> Path:
    run_s4_4c5i_plant_development_status_audit()
    return C5I_DIR


def test_c5i_required_outputs_exist_and_parse(c5i_outputs: Path):
    required = [
        "s4_4c5i_stage_gate.json",
        "s4_4c5i_run_registry.csv",
        "s4_4c5i_latest_input_manifest.csv",
        "s4_4c5i_plant_development_status_matrix.csv",
        "s4_4c5i_plant_missing_parameter_matrix.csv",
        "s4_4c5i_plant_red_flag_register.csv",
        "s4_4c5i_plant_electricity_status.csv",
        "s4_4c5i_plant_co2_status.csv",
        "s4_4c5i_plant_material_conversion_status.csv",
        "s4_4c5i_plant_wag_fuel_steam_status.csv",
        "s4_4c5i_anchor_constraint_misuse_audit.csv",
        "s4_4c5i_recommended_next_plant_order.csv",
        "s4_4c5i_compact_status_table_for_chat.csv",
    ]
    for filename in required:
        path = c5i_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5i_outputs / "s4_4c5i_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_status_audit_with_known_gaps"
    assert gate["latest_input_stage"] == "S4.4c5h_blast_furnace_controller_parameterisation"
    assert gate["anchor_constraint_misuse_fail_count"] == 0
    assert gate["latest_wag_invariant_fail_count"] == 0
    assert gate["topology_fail_count"] == 0
    assert gate["direct_WAG_market_valuation_detected"] is False
    assert gate["steam_9PJ_anchor_active"] is False
    assert gate["legacy_equal_wag_ng_boiler_split_active"] is False
    assert gate["forbidden_economic_features_added"] is False


def test_c5i_status_matrix_includes_required_plants_and_classifications(c5i_outputs: Path):
    matrix = _read_csv(c5i_outputs / "s4_4c5i_plant_development_status_matrix.csv")
    assert {row["plant"] for row in matrix} == REQUIRED_PLANTS
    assert len(matrix) == len(REQUIRED_PLANTS)

    for row in matrix:
        assert row["development_status"] in DEVELOPMENT_STATUSES
        assert row["next_action_class"] in NEXT_ACTION_CLASSES
        if row["active_C0"] in ACTIVE_MARKERS or row["active_C1"] in ACTIVE_MARKERS:
            for column in STATUS_COLUMNS:
                assert row[column]


def test_c5i_preserves_c1_topology(c5i_outputs: Path):
    rows = {row["plant"]: row for row in _read_csv(c5i_outputs / "s4_4c5i_plant_development_status_matrix.csv")}
    assert rows["BF6"]["active_C1"] == "true"
    assert rows["BF7"]["active_C1"] == "false"
    assert rows["KGF1"]["active_C1"] == "true"
    assert rows["KGF2"]["active_C1"] == "false"
    assert rows["DRP"]["active_C1"] == "true"
    assert rows["EAF"]["active_C1"] == "true"


def test_c5i_missing_values_are_flagged_not_clean_zero(c5i_outputs: Path):
    rows = {row["plant"]: row for row in _read_csv(c5i_outputs / "s4_4c5i_plant_development_status_matrix.csv")}

    assert "missing" in rows["HSM"]["electricity_status"]
    assert "missing_HSM_gas_coefficient" in rows["HSM"]["red_flags"]
    assert "missing_direct_CO2_coefficient" in rows["Sinter"]["co2_status"]
    assert "active_expected_CO2_zero_or_missing" in rows["BOF"]["red_flags"]
    assert "residual_unvalidated_steam_placeholder" in rows["boilers"]["red_flags"]
    assert rows["PEFA_Malerij"]["development_status"] == "needs_source_research_before_parameterisation"
    assert rows["PEFA_Branderij"]["development_status"] == "needs_source_research_before_parameterisation"

    missing = _read_csv(c5i_outputs / "s4_4c5i_plant_missing_parameter_matrix.csv")
    missing_keys = {(row["plant"], row["parameter_group"]) for row in missing}
    assert ("HSM", "electricity") in missing_keys
    assert ("Sinter", "co2") in missing_keys
    assert ("boilers", "fuel_wag_steam") in missing_keys


def test_c5i_anchor_misuse_and_wag_invariant_stay_clean(c5i_outputs: Path):
    anchor = _read_csv(c5i_outputs / "s4_4c5i_anchor_constraint_misuse_audit.csv")
    assert anchor
    assert all(row["status"] == "pass" for row in anchor)
    assert all(row["constraint_used"] in {"", "false", "0"} for row in anchor)

    wag = _read_csv(C5H_DIR / "s4_4c5h_wag_aggregate_invariant.csv")
    assert wag
    assert all(row["status"] == "pass" for row in wag)


def test_c5i_kgf_and_bf_are_implemented_but_monitored(c5i_outputs: Path):
    rows = {row["plant"]: row for row in _read_csv(c5i_outputs / "s4_4c5i_plant_development_status_matrix.csv")}
    for plant in ("KGF1", "KGF2", "BF6", "BF7", "Controller_Blast_Furnace"):
        assert rows[plant]["development_status"] == "development_sufficient_for_current_physical_accounting"

    assert "bf_coke_demand_exceeds_kgf_coke_output" in rows["BF6"]["red_flags"]
    assert "bf_coke_demand_exceeds_kgf_coke_output" in rows["BF7"]["red_flags"]


def test_c5i_recommends_next_non_kgf_bf_parameterisation(c5i_outputs: Path):
    order = _read_csv(c5i_outputs / "s4_4c5i_recommended_next_plant_order.csv")
    assert order
    assert any(
        row["development_status"] == "needs_minimal_parameterisation_next"
        and row["plant"] not in {"KGF1", "KGF2", "BF6", "BF7"}
        for row in order
    )
    top_plants = {row["plant"] for row in order[:5]}
    assert {"HSM", "BOF", "Sinter", "boilers"}.issubset(top_plants)


def test_c5i_compact_status_table_has_no_duplicate_plants(c5i_outputs: Path):
    compact = _read_csv(c5i_outputs / "s4_4c5i_compact_status_table_for_chat.csv")
    plants = [row["plant"] for row in compact]
    assert len(plants) == len(set(plants))
    assert set(plants) == REQUIRED_PLANTS
