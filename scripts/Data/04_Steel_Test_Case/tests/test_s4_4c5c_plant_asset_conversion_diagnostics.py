from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5c_plant_asset_conversion_diagnostics import (  # noqa: E402
    C5C_DIR,
    run_s4_4c5c_plant_asset_conversion_diagnostics,
)


C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5c_outputs() -> Path:
    run_s4_4c5c_plant_asset_conversion_diagnostics()
    return C5C_DIR


def test_c5c_stage_gate_preserves_c5b_no_regressions(c5c_outputs: Path):
    gate = json.loads((c5c_outputs / "s4_4c5c_stage_gate.json").read_text(encoding="utf-8"))

    assert gate["required_runs_executed"] is True
    assert gate["c1_kgf1_active"] is True
    assert gate["c1_kgf2_inactive"] is True
    assert gate["c1_bf7_inactive"] is True
    assert gate["steam_validation_anchor_active"] is False
    assert gate["fixed_50_50_wag_ng_boiler_split_active"] is False
    assert gate["wag_first_allocation_preserved"] is True
    assert gate["vattenfall_cap_policy"] == "combined_BFG_COG_BOFG_volume_cap_not_per_carrier"
    assert gate["anchors_used_as_constraints"] is False


def test_c5c_topology_rows_and_kgf1_io_are_visible(c5c_outputs: Path):
    compact = _read_csv(c5c_outputs / "s4_4c5c_compact_table_for_chat.csv")
    rows_24h = {
        (row["configuration"], row["plant"]): row
        for row in compact
        if row["horizon_hours"] == "24"
    }

    assert rows_24h[(C0, "KGF1")]["active"] == "True"
    assert rows_24h[(C0, "KGF2")]["active"] == "True"
    assert rows_24h[(C1, "KGF1")]["active"] == "True"
    assert rows_24h[(C1, "KGF2")]["active"] == "False"
    assert rows_24h[(C1, "BF6")]["active"] == "True"
    assert rows_24h[(C1, "BF7")]["active"] == "False"

    io_rows = _read_csv(c5c_outputs / "s4_4c5c_plant_carrier_io_hourly.csv")
    c1_kgf1_rows = [
        row for row in io_rows
        if row["configuration"] == C1 and row["plant_id"] == "KGF1" and row["quantity"] not in {"", "0.0", "0", "NaN"}
    ]
    c1_kgf2_rows = [
        row for row in io_rows
        if row["configuration"] == C1 and row["plant_id"] == "KGF2"
    ]

    assert c1_kgf1_rows
    assert c1_kgf2_rows
    assert all(row["asset_status"] == "structurally_inactive" for row in c1_kgf2_rows)


def test_c5c_coking_diagnostics_classify_missing_coefficients(c5c_outputs: Path):
    coking = _read_csv(c5c_outputs / "s4_4c5c_coking_plant_diagnostics.csv")
    active_rows = [row for row in coking if row["active"] == "True"]
    inactive_rows = [row for row in coking if row["configuration"] == C1 and row["plant_id"] == "KGF2"]

    assert inactive_rows
    assert all(row["status"] == "structurally_inactive" for row in inactive_rows)
    for row in active_rows:
        assert float(row["coke_output_t_y"]) > 0.0
        assert row["coal_input_t_y"] != "" or row["status"] == "missing_executable_coefficient"
        assert row["coal_t_per_t_coke"] != "NaN" or row["status"] == "missing_executable_coefficient"
        assert row["COG_output_MWh_LHV_y"] != "" or row["status"] == "missing_executable_coefficient"
        assert row["CO2_t_y"] != "NaN" or "CO2" in row["missing_fields"]


def test_c5c_wag_balance_closes_with_rounding_tolerance(c5c_outputs: Path):
    wag_rows = _read_csv(c5c_outputs / "s4_4c5c_wag_generation_consumption_by_plant.csv")
    site_rows = [row for row in wag_rows if row["plant_id"] == "SITE_TOTAL"]

    assert site_rows
    assert all(row["status"] == "closed" for row in site_rows)
    assert all(abs(float(row["balance_error_MWh_LHV_y"])) <= 0.01 for row in site_rows)
