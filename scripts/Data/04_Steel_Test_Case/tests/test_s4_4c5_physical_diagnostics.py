from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5_physical_diagnostics import C1, C5_DIR, run_s4_4c5_physical_diagnostics  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c5_full_diagnostics_pass_with_bottom_up_retained_route() -> None:
    result = run_s4_4c5_physical_diagnostics()

    assert result["phase1_gate"]["decision"] == "pass_to_phase2_bottom_up_24h"
    assert result["phase2_gate"]["decision"] == "pass_to_168h_c5_diagnostics"
    assert result["phase3_gate"]["decision"] == "pass_s4_4c5_calibration_readiness_with_caveats"

    combined = json.loads((C5_DIR / "s4_4c5_stage_gate.json").read_text(encoding="utf-8"))
    route_rows = _rows(C5_DIR / "s4_4c5_168h_route_split.csv")
    c1_route = next(row for row in route_rows if row["configuration_id"] == C1)

    assert combined["decision"] == "pass_s4_4c5_calibration_readiness_with_caveats"
    assert c1_route["policy"] == "bottom_up_fixed_retained_route"
    assert float(c1_route["retained_bf_bof_final_product_t"]) == 17675.0
    assert float(c1_route["drp_eaf_final_product_t"]) == 23661.4


def test_s4_4c5_reports_cp2_activation_and_hhv_residual_basis() -> None:
    run_s4_4c5_physical_diagnostics()

    plant_rows = _rows(C5_DIR / "s4_4c5_24h_plant_diagnostics.csv")
    cp2_rows = [
        row
        for row in plant_rows
        if row["configuration_id"] == "C0_current_BF_BOF_reference" and row["plant_id"] == "KGF2_CokingPlant2"
    ]
    residual_rows = _rows(C5_DIR / "s4_4c5_168h_residual_load_report.csv")
    phase1_rows = _rows(C5_DIR / "s4_4c5_phase1_structure_audit.csv")

    assert sum(float(row["activity_t_h"]) for row in cp2_rows) > 0.0
    assert any(row["metric"] == "natural_gas_CH4_HHV_basis" and "HHV" in row["basis_warning"] for row in residual_rows)
    assert any(
        row["audit_item"] == "Vattenfall_WAG_cap"
        and row["status"] == "combined_volume_cap"
        and float(row["total_Nm3_h"]) == 900000.0
        for row in phase1_rows
    )
