from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c4c_full_wag_static_regression import C4C_DIR, run_168h, run_24h, run_phase1  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c4c_24h_full_wag_layer_runs_for_both_configs() -> None:
    phase1 = run_phase1()
    phase2 = run_24h()

    assert phase1["decision"] == "pass_to_phase2_24h_full_wag_rerun"
    assert phase2["phase_stage_gate"]["decision"] == "pass_to_phase3_168h_full_wag_rerun"

    gate = json.loads((C4C_DIR / "s4_4c4c_24h_stage_gate.json").read_text(encoding="utf-8"))
    carrier_rows = _rows(C4C_DIR / "s4_4c4c_24h_wag_by_carrier.csv")
    electricity_rows = _rows(C4C_DIR / "s4_4c4c_24h_electricity_summary.csv")
    c1_dispatch = _rows(C4C_DIR / "s4_4c4c_24h_hourly_dispatch_c1.csv")

    c1_bfg = next(row for row in carrier_rows if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF" and row["carrier"] == "BFG")
    c1_electricity = next(row for row in electricity_rows if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF")

    assert gate["max_abs_wag_balance_residual_mwh"] == 0.0
    assert float(c1_bfg["generated_mwh"]) > 0.0
    assert float(c1_bfg["max_abs_balance_residual_mwh"]) == 0.0
    assert float(c1_electricity["wag_internal_generation_mwh"]) > 0.0
    assert float(c1_electricity["net_grid_import_mwh"]) < float(c1_electricity["gross_electricity_demand_mwh"])
    assert all(float(row["C1_BF7_activity_t_h"]) == 0.0 for row in c1_dispatch)
    assert all(float(row["C1_KGF2_activity_t_h"]) == 0.0 for row in c1_dispatch)
    assert gate["direct_wag_market_valuation_active"] is False
    assert gate["export_revenue_active"] is False


def test_s4_4c4c_168h_full_wag_layer_runs_after_24h_gate() -> None:
    run_phase1()
    run_24h()
    phase3 = run_168h()

    assert phase3["phase_stage_gate"]["decision"] == "pass_168h_static_physical_with_full_wag_caveats"
    gate = json.loads((C4C_DIR / "s4_4c4c_168h_stage_gate.json").read_text(encoding="utf-8"))
    carrier_rows = _rows(C4C_DIR / "s4_4c4c_168h_wag_by_carrier.csv")
    co2_rows = _rows(C4C_DIR / "s4_4c4c_168h_co2_flaring_summary.csv")
    daily_rows = _rows(C4C_DIR / "s4_4c4c_168h_daily_summary.csv")

    c0_rows = [row for row in carrier_rows if row["configuration_id"] == "C0_current_BF_BOF_reference"]
    c1_rows = [row for row in carrier_rows if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"]

    assert gate["max_abs_wag_balance_residual_mwh"] == 0.0
    assert any(float(row["generated_mwh"]) > 0.0 for row in c0_rows)
    assert any(float(row["generated_mwh"]) > 0.0 for row in c1_rows)
    assert all(row["co2_cost_objective_active"] == "false" for row in co2_rows)
    assert len(daily_rows) == 14
