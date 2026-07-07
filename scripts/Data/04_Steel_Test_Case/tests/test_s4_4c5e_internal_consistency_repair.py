from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5e_internal_consistency_repair import (  # noqa: E402
    C5E_DIR,
    C1,
    KGF1_SHARE,
    KGF2_SHARE,
    run_s4_4c5e_internal_consistency_repair,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def c5e_outputs() -> Path:
    run_s4_4c5e_internal_consistency_repair()
    return C5E_DIR


def test_c5e_downstream_continuation_uses_bof_plus_eaf(c5e_outputs: Path):
    downstream = _read_csv(c5e_outputs / "s4_4c5e_downstream_continuation_dashboard.csv")
    compact = _read_csv(c5e_outputs / "s4_4c5e_compact_table_for_chat.csv")
    c1_24h = next(row for row in downstream if row["configuration"] == C1 and row["horizon_hours"] == "24")

    retained = float(c1_24h["retained_bof_liquid_steel_site_t_y"])
    eaf = float(c1_24h["eaf_liquid_steel_site_t_y"])
    total = float(c1_24h["total_liquid_steel_site_t_y"])
    final_proxy = float(c1_24h["final_product_proxy_site_t_y"])
    hsm = next(row for row in compact if row["configuration"] == C1 and row["plant"] == "HSM")

    assert eaf > 0.0
    assert final_proxy > retained
    assert abs(final_proxy - (retained + eaf)) <= 1.0
    assert abs(final_proxy - total) <= 1.0
    assert abs(float(hsm["main_product_site_t_y"]) - total) <= 1.0
    assert c1_24h["downstream_continuation_status"].startswith("pass")


def test_c5e_kgf_split_uses_frozen_238_108_development_assumption(c5e_outputs: Path):
    diagnostics = _read_csv(c5e_outputs / "s4_4c5e_kgf_split_diagnostics.csv")
    compact = _read_csv(c5e_outputs / "s4_4c5e_compact_table_for_chat.csv")

    c0_rows = [row for row in diagnostics if row["configuration"] == "C0_current_BF_BOF_reference"]
    assert c0_rows
    for row in c0_rows:
        assert float(row["kgf1_share_raw"]) == pytest.approx(KGF1_SHARE, abs=1e-6)
        assert float(row["kgf2_share_raw"]) == pytest.approx(KGF2_SHARE, abs=1e-6)
        assert row["assumption_status"] == "frozen_for_development"
        assert row["sensitivity_required"] == "True"
        assert row["red_flags"] == ""

    c1_kgf1 = next(row for row in compact if row["configuration"] == C1 and row["plant"] == "KGF1")
    c1_kgf2 = next(row for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2")
    assert c1_kgf1["active"] == "True"
    assert float(c1_kgf1["main_product_raw_t_y"]) > 0.0
    assert c1_kgf2["active"] == "False"
    assert float(c1_kgf2["main_product_raw_t_y"]) == 0.0


def test_c5e_wag_compact_balance_reconciles_raw_and_site_scaled(c5e_outputs: Path):
    reconciliation = _read_csv(c5e_outputs / "s4_4c5e_wag_compact_balance_reconciliation.csv")
    compact = _read_csv(c5e_outputs / "s4_4c5e_compact_table_for_chat.csv")

    assert reconciliation
    assert all(row["status"] == "pass" for row in reconciliation)
    assert {row["scale_basis"] for row in reconciliation} == {"raw", "site_scaled"}
    assert {row["carrier"] for row in reconciliation} == {"BFG", "COG", "BOFG"}
    assert any(row["plant"].startswith("WAG_TOTAL_") for row in compact)

    for row in reconciliation:
        generated = float(row["balance_generated_MWh_LHV_y"])
        used = (
            float(row["balance_consumed_direct_MWh_LHV_y"])
            + float(row["balance_consumed_boiler_MWh_LHV_y"])
            + float(row["balance_consumed_vattenfall_MWh_LHV_y"])
        )
        flared = float(row["balance_flared_MWh_LHV_y"])
        assert float(row["generation_difference_MWh_LHV_y"]) <= 1.0
        assert flared <= generated - used + 1.0


def test_c5e_preserves_c5d_lhv_topology_and_policy_fixes(c5e_outputs: Path):
    gate = json.loads((c5e_outputs / "s4_4c5e_stage_gate.json").read_text(encoding="utf-8"))
    compact = _read_csv(c5e_outputs / "s4_4c5e_compact_table_for_chat.csv")
    lhv = _read_csv(c5e_outputs / "s4_4c5e_lhv_consistency_checks.csv")

    assert gate["decision"] == "pass_development_internal_consistency_repair_with_open_physical_gaps"
    assert gate["steam_validation_anchor_active"] is False
    assert gate["legacy_equal_wag_ng_boiler_split_active"] is False
    assert gate["wag_first_allocation_preserved"] is True
    assert gate["vattenfall_cap_policy"] == "combined_BFG_COG_BOFG_volume_cap_not_per_carrier"
    assert all(row["status"] == "pass" for row in lhv)
    assert any(row["configuration"] == C1 and row["plant"] == "KGF1" and row["active"] == "True" for row in compact)
    assert all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2")
    assert all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "BF7")

    for output in c5e_outputs.glob("*"):
        text = output.read_text(encoding="utf-8")
        assert "9 PJ" not in text
        assert "50/50" not in text
        assert "50_50" not in text


def test_c5e_required_outputs_exist_and_parse(c5e_outputs: Path):
    required = [
        "s4_4c5e_stage_gate.json",
        "s4_4c5e_run_registry.csv",
        "s4_4c5e_24h_summary.csv",
        "s4_4c5e_168h_summary.csv",
        "s4_4c5e_downstream_continuation_dashboard.csv",
        "s4_4c5e_kgf_split_diagnostics.csv",
        "s4_4c5e_wag_compact_balance_reconciliation.csv",
        "s4_4c5e_scale_audit.csv",
        "s4_4c5e_lhv_consistency_checks.csv",
        "s4_4c5e_plant_carrier_io_annualised.csv",
        "s4_4c5e_plant_conversion_ratios.csv",
        "s4_4c5e_wag_generation_consumption_by_plant.csv",
        "s4_4c5e_vattenfall_cap_hourly.csv",
        "s4_4c5e_anchor_gap_dashboard.csv",
        "s4_4c5e_compact_table_for_chat.csv",
    ]
    for filename in required:
        path = c5e_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)
