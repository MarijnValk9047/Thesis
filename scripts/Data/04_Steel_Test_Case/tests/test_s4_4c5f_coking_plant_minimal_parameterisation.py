from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import (  # noqa: E402
    C5F_DIR,
    C1,
    COG_GROSS_MWH_PER_T_COKE,
    COG_LHV_MJ_PER_NM3,
    COG_SURPLUS_MWH_PER_T_COKE,
    COG_YIELD_NM3_PER_T_COKE,
    DRY_COAL_PER_COKE_TPT,
    KGF_DIRECT_CO2_T_PER_T_COKE,
    KGF_ELECTRICITY_MWH_PER_T_COKE,
    KGF_STEAM_MWH_PER_T_COKE,
    KGF_UNDERFIRING_GJ_PER_T_COKE,
    KGF_UNDERFIRING_MWH_PER_T_COKE,
    run_s4_4c5f_coking_plant_minimal_parameterisation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5f_outputs() -> Path:
    run_s4_4c5f_coking_plant_minimal_parameterisation()
    return C5F_DIR


def test_c5f_parameter_register_contains_required_kgf_rows(c5f_outputs: Path):
    register = _read_csv(c5f_outputs / "s4_4c5f_plant_parameter_register.csv")
    values = _read_csv(c5f_outputs / "s4_4c5f_kgf_parameter_values.csv")
    required = {
        "DRY_COAL_PER_COKE_TPT",
        "COG_YIELD_NM3_PER_T_COKE",
        "COG_LHV_MJ_PER_NM3",
        "KGF_UNDERFIRING_GJ_PER_T_COKE",
        "COG_SURPLUS_MWH_PER_T_COKE",
        "KGF_ELECTRICITY_MWH_PER_T_COKE",
        "KGF_STEAM_GJ_PER_T_COKE",
        "KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC",
        "KGF_DIRECT_CO2_T_PER_T_COKE",
        "COG_CO2_POTENTIAL_T_PER_T_COKE",
    }
    assert required.issubset({row["parameter_id"] for row in register})
    assert required.issubset({row["parameter_id"] for row in values})
    assert any(row["evidence_status"] == "not_yet_parameterised" for row in register)
    assert all(row["thesis_usability"] == "false" for row in register)


def test_c5f_active_kgf_conversion_values_are_nonzero_and_source_based(c5f_outputs: Path):
    rows = _read_csv(c5f_outputs / "s4_4c5f_coking_plant_diagnostics.csv")
    active = [row for row in rows if row["active"] == "True"]
    assert active
    for row in active:
        assert float(row["dry_coal_input_raw_t_y"]) > 0.0
        assert float(row["coke_output_raw_t_y"]) > 0.0
        assert float(row["gross_COG_raw_MWh_LHV_y"]) > 0.0
        assert float(row["COG_to_KGF_underfiring_raw_MWh_LHV_y"]) > 0.0
        assert float(row["surplus_COG_raw_MWh_LHV_y"]) > 0.0
        assert float(row["KGF_electricity_raw_MWh_y"]) > 0.0
        assert float(row["KGF_steam_raw_MWh_proxy_y"]) > 0.0
        assert float(row["KGF_direct_CO2_raw_t_y"]) > 0.0
        assert float(row["COG_carbon_potential_tCO2_y"]) > 0.0
        assert float(row["coal_t_per_t_coke"]) == pytest.approx(DRY_COAL_PER_COKE_TPT)
        assert float(row["gross_COG_Nm3_per_t_coke"]) == pytest.approx(COG_YIELD_NM3_PER_T_COKE)
        assert float(row["gross_COG_MWh_per_t_coke"]) == pytest.approx(COG_GROSS_MWH_PER_T_COKE)
        assert float(row["COG_underfiring_MWh_per_t_coke"]) == pytest.approx(KGF_UNDERFIRING_MWH_PER_T_COKE)
        assert float(row["surplus_COG_MWh_per_t_coke"]) == pytest.approx(COG_SURPLUS_MWH_PER_T_COKE)
        assert float(row["KGF_electricity_MWh_per_t_coke"]) == pytest.approx(KGF_ELECTRICITY_MWH_PER_T_COKE)
        assert float(row["KGF_steam_MWh_proxy_per_t_coke"]) == pytest.approx(KGF_STEAM_MWH_PER_T_COKE, abs=1e-6)
        assert float(row["KGF_direct_CO2_t_per_t_coke"]) == pytest.approx(KGF_DIRECT_CO2_T_PER_T_COKE)
        assert row["COG_carbon_accounting_status"] == "diagnostic_only_not_counted_as_direct_KGF_CO2"
        assert row["surplus_status"] == "pass"


def test_c5f_cog_lhv_and_self_use_surplus_math(c5f_outputs: Path):
    rows = _read_csv(c5f_outputs / "s4_4c5f_coking_plant_diagnostics.csv")
    for row in rows:
        if row["active"] != "True":
            continue
        expected_mwh = float(row["gross_COG_Nm3_per_t_coke"]) * COG_LHV_MJ_PER_NM3 / 3600.0
        assert float(row["gross_COG_MWh_per_t_coke"]) == pytest.approx(expected_mwh)
        assert KGF_UNDERFIRING_GJ_PER_T_COKE / 3.6 == pytest.approx(float(row["COG_underfiring_MWh_per_t_coke"]))
        assert float(row["surplus_COG_MWh_per_t_coke"]) == pytest.approx(
            float(row["gross_COG_MWh_per_t_coke"]) - float(row["COG_underfiring_MWh_per_t_coke"])
        )

    lhv = _read_csv(c5f_outputs / "s4_4c5f_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)


def test_c5f_preserves_split_topology_anchor_and_downstream(c5f_outputs: Path):
    split = _read_csv(c5f_outputs / "s4_4c5f_kgf_split_diagnostics.csv")
    compact = _read_csv(c5f_outputs / "s4_4c5f_compact_table_for_chat.csv")
    anchor = _read_csv(c5f_outputs / "s4_4c5f_coke_anchor_gap_dashboard.csv")
    downstream = _read_csv(c5f_outputs / "s4_4c5f_downstream_continuation_dashboard.csv")

    c0 = [row for row in split if row["configuration"] == "C0_current_BF_BOF_reference"]
    assert c0
    for row in c0:
        assert float(row["kgf1_share"]) == pytest.approx(238 / 346, abs=1e-6)
        assert float(row["kgf2_share"]) == pytest.approx(108 / 346, abs=1e-6)
    assert all(row["constraint_used"] == "false" for row in anchor)
    assert all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2")
    assert all(float(row["main_product_raw_t_y"]) == 0.0 for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2")
    assert all(row["downstream_continuation_status"].startswith("pass") for row in downstream)


def test_c5f_wag_cog_balance_uses_surplus_not_gross(c5f_outputs: Path):
    cog_balance = _read_csv(c5f_outputs / "s4_4c5f_cog_wag_balance_by_plant.csv")
    reconciliation = _read_csv(c5f_outputs / "s4_4c5f_wag_compact_balance_reconciliation.csv")
    assert cog_balance
    assert all(row["status"] == "pass" for row in cog_balance)
    assert all(row["status"] == "pass" for row in reconciliation)

    kgf_rows = [row for row in cog_balance if row["plant_id"] in {"KGF1", "KGF2"}]
    for row in kgf_rows:
        gross = float(row["gross_generated_MWh_LHV_y"] or 0.0)
        self_use = float(row["self_used_MWh_LHV_y"] or 0.0)
        surplus = float(row["surplus_to_network_MWh_LHV_y"] or 0.0)
        assert gross == pytest.approx(self_use + surplus)
        assert surplus >= 0.0

    for row in reconciliation:
        assert float(row["generation_difference_MWh_LHV_y"]) <= 1.0


def test_c5f_stage_gate_and_no_retired_policy_strings(c5f_outputs: Path):
    gate = json.loads((c5f_outputs / "s4_4c5f_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_coking_plant_minimal_parameterisation_with_open_site_gaps"
    assert gate["steam_validation_anchor_active"] is False
    assert gate["legacy_equal_wag_ng_boiler_split_active"] is False
    assert gate["coke_anchor_used_as_constraint"] is False
    assert gate["c5e_downstream_continuation_preserved"] is True
    assert gate["lhv_consistency_fail_count"] == 0

    for output in c5f_outputs.glob("*"):
        text = output.read_text(encoding="utf-8")
        assert "9 PJ" not in text
        assert "50/50" not in text
        assert "50_50" not in text


def test_c5f_required_outputs_exist_and_parse(c5f_outputs: Path):
    required = [
        "s4_4c5f_stage_gate.json",
        "s4_4c5f_run_registry.csv",
        "s4_4c5f_24h_summary.csv",
        "s4_4c5f_168h_summary.csv",
        "s4_4c5f_minimal_plant_parameter_schema.csv",
        "s4_4c5f_plant_parameter_register.csv",
        "s4_4c5f_kgf_parameter_values.csv",
        "s4_4c5f_kgf_split_diagnostics.csv",
        "s4_4c5f_coke_anchor_gap_dashboard.csv",
        "s4_4c5f_cog_self_use_surplus_dashboard.csv",
        "s4_4c5f_cog_wag_balance_by_plant.csv",
        "s4_4c5f_coking_plant_diagnostics.csv",
        "s4_4c5f_wag_generation_consumption_by_plant.csv",
        "s4_4c5f_wag_compact_balance_reconciliation.csv",
        "s4_4c5f_lhv_consistency_checks.csv",
        "s4_4c5f_energy_by_plant.csv",
        "s4_4c5f_emissions_by_plant.csv",
        "s4_4c5f_plant_conversion_ratios.csv",
        "s4_4c5f_anchor_gap_dashboard.csv",
        "s4_4c5f_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5f_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
