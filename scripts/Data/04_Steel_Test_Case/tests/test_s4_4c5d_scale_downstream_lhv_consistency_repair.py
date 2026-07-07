from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5d_scale_downstream_lhv_consistency_repair import (  # noqa: E402
    C5D_DIR,
    SCALE_COLUMNS,
    run_s4_4c5d_scale_downstream_lhv_consistency_repair,
)


C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
WAG_LHV = {"BFG": 3.85, "COG": 18.5, "BOFG": 8.6}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5d_outputs() -> Path:
    run_s4_4c5d_scale_downstream_lhv_consistency_repair()
    return C5D_DIR


def test_c5d_scale_columns_exist(c5d_outputs: Path):
    for filename in (
        "s4_4c5d_compact_table_for_chat.csv",
        "s4_4c5d_plant_carrier_io_annualised.csv",
        "s4_4c5d_plant_conversion_ratios.csv",
        "s4_4c5d_wag_generation_consumption_by_plant.csv",
        "s4_4c5d_anchor_gap_dashboard.csv",
    ):
        rows = _read_csv(c5d_outputs / filename)
        assert rows
        assert SCALE_COLUMNS.issubset(rows[0])


def test_c5d_scale_audit_blocks_unflagged_raw_anchor_comparisons(c5d_outputs: Path):
    rows = _read_csv(c5d_outputs / "s4_4c5d_scale_audit.csv")
    required_flags = {
        "raw_module_compared_to_full_site_anchor",
        "full_site_proxy_scaled_again",
        "scale_mode_missing",
        "scale_factor_missing_for_module_metric",
        "site_scaled_quantity_missing",
    }

    assert not [row for row in rows if row["red_flag"] in required_flags]
    assert any(
        row["metric"] == "Athanasiadis:electricity_total"
        and row["configuration"] == "C0_current_BF_BOF_reference"
        and row["scale_mode"] == "full_site_proxy_do_not_scale"
        and float(row["scale_factor"]) == 1.0
        for row in rows
    )


def test_c5d_c1_eaf_continues_to_final_product_proxy(c5d_outputs: Path):
    rows = _read_csv(c5d_outputs / "s4_4c5d_downstream_continuation_dashboard.csv")
    c1_24h = next(row for row in rows if row["configuration"] == C1 and row["horizon_hours"] == "24")

    retained = float(c1_24h["retained_bof_liquid_steel_raw_t_y"])
    eaf = float(c1_24h["eaf_liquid_steel_raw_t_y"])
    final_proxy = float(c1_24h["final_product_proxy_raw_t_y"])
    assert eaf > 0.0
    assert final_proxy > retained
    assert abs(final_proxy - retained - eaf) <= 1e-6
    assert c1_24h["downstream_continuation_status"].startswith("pass")


def test_c5d_lhv_checks_pass_for_wag_carriers(c5d_outputs: Path):
    constants = _read_csv(c5d_outputs / "s4_4c5d_carrier_conversion_constants.csv")
    for carrier, lhv in WAG_LHV.items():
        row = next(item for item in constants if item["carrier"] == carrier)
        assert float(row["LHV_MJ_per_Nm3"]) == lhv
    ng = next(item for item in constants if item["carrier"] == "NaturalGas")
    assert float(ng["HHV_MJ_per_Nm3"]) == 39.8
    assert ng["basis"] == "NG_HHV_validation"

    checks = _read_csv(c5d_outputs / "s4_4c5d_lhv_consistency_checks.csv")
    assert checks
    assert all(row["status"] == "pass" for row in checks)
    for row in checks[:100]:
        if row["carrier"] in WAG_LHV:
            expected = float(row["quantity_Nm3"]) * WAG_LHV[row["carrier"]] / 3600.0
            assert abs(float(row["reported_MWh_LHV"]) - expected) <= 1e-6


def test_c5d_preserves_topology_and_stage_gate_no_regressions(c5d_outputs: Path):
    gate = json.loads((c5d_outputs / "s4_4c5d_stage_gate.json").read_text(encoding="utf-8"))
    compact = _read_csv(c5d_outputs / "s4_4c5d_compact_table_for_chat.csv")

    assert gate["steam_validation_anchor_active"] is False
    assert gate["legacy_equal_wag_ng_boiler_split_active"] is False
    assert gate["wag_first_allocation_preserved"] is True
    assert gate["vattenfall_cap_policy"] == "combined_BFG_COG_BOFG_volume_cap_not_per_carrier"
    assert gate["anchors_used_as_constraints"] is False
    assert any(row["configuration"] == C1 and row["plant"] == "KGF1" and row["active"] == "True" for row in compact)
    assert all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2")
    assert all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "BF7")

    for output in c5d_outputs.glob("*"):
        text = output.read_text(encoding="utf-8")
        assert "9 PJ" not in text
        assert "50/50" not in text
        assert "50_50" not in text
