from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5a_anchor_scaling_correction import C5A_DIR, run_s4_4c5a_anchor_scaling_correction  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c5a_selects_675_mt_anchor_and_table_anchors() -> None:
    result = run_s4_4c5a_anchor_scaling_correction()

    assert result["stage_gate"]["decision"] == "pass_s4_4c5a_validation_hardening_with_caveats"

    production = _rows(C5A_DIR / "s4_4c5a_production_anchor_selection.csv")
    selected = next(row for row in production if row["selected"] == "True")
    anchors = _rows(C5A_DIR / "s4_4c5a_corrected_anchor_table.csv")

    assert float(selected["value_t_y"]) == 6_750_000.0
    assert any(row["configuration_id"].startswith("C0") and row["anchor_metric"] == "electricity_total" and float(row["anchor_value"]) == 3_170_000.0 for row in anchors)
    assert any(row["configuration_id"].startswith("C1") and row["anchor_metric"] == "natural_gas" and float(row["anchor_nm3_h"]) == 151_673.52 for row in anchors)


def test_s4_4c5a_reports_module_scale_hhv_and_accounting_nodes() -> None:
    run_s4_4c5a_anchor_scaling_correction()

    scale_rows = _rows(C5A_DIR / "s4_4c5a_scale_mode_findings.csv")
    ng_rows = _rows(C5A_DIR / "s4_4c5a_ng_hhv_lhv_accounting.csv")
    plant_rows = _rows(C5A_DIR / "s4_4c5a_168h_plant_diagnostics.csv")
    wag_rows = _rows(C5A_DIR / "s4_4c5a_wag_rules_audit.csv")

    assert all(row["scale_mode"] == "module_scale" for row in scale_rows)
    assert all(row["wag_energy_basis"] == "LHV" and float(row["ng_hhv_mj_per_nm3"]) == 39.8 for row in ng_rows)
    assert any(row["plant_id"] == "BoilerSteamUtility" for row in plant_rows)
    assert any(row["plant_id"] == "VattenfallInternalGeneration" for row in plant_rows)
    assert any(row["plant_id"] == "KGF1_WAG_mixing_station" for row in plant_rows)
    assert any(row["rule"] == "Vattenfall_combined_cap" and float(row["total_Nm3_h"]) == 900000.0 for row in wag_rows)


def test_s4_4c5a_stage_gate_does_not_force_anchors() -> None:
    run_s4_4c5a_anchor_scaling_correction()

    gate = json.loads((C5A_DIR / "s4_4c5a_stage_gate.json").read_text(encoding="utf-8"))
    electricity = _rows(C5A_DIR / "s4_4c5a_electricity_accounting_separation.csv")

    assert gate["anchors_are_constraints"] is False
    assert gate["optimiser_outputs_forced_to_match_anchors"] is False
    assert all(row["residual_load_in_optimizer"] == "False" for row in electricity)
