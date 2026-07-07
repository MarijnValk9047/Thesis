from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4b5a_asymmetric_correction import run_b5a_correction  # noqa: E402
from steel.s4_4b5a_corrected_input_validation import run_phase2_validation  # noqa: E402
from steel.s4_4c_asymmetric_static_regression import C1A_DIR, run_c1a_24h  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c1a_runs_corrected_24h_for_both_configurations() -> None:
    run_b5a_correction()
    run_phase2_validation()
    report = run_c1a_24h()
    gate = report["phase_stage_gate"]
    audits = {row["configuration_id"]: row for row in report["configuration_build_audit"]}

    assert gate["decision"] == "pass_to_phase4_week_run"
    assert audits["C0_current_BF_BOF_reference"]["build_status"] == "solved"
    assert audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["build_status"] == "solved"
    assert float(audits["C0_current_BF_BOF_reference"]["final_product_residual_t"]) == 0.0
    assert float(audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["final_product_residual_t"]) == 0.0


def test_s4_4c1a_outputs_parse_and_keep_forbidden_terms_inactive() -> None:
    run_b5a_correction()
    run_phase2_validation()
    run_c1a_24h()

    for name in [
        "s4_4c1a_static_physical_report.json",
        "s4_4c1a_stage_gate.json",
    ]:
        json.loads((C1A_DIR / name).read_text(encoding="utf-8"))

    c0_rows = _rows(C1A_DIR / "s4_4c1a_hourly_dispatch_c0.csv")
    c1_rows = _rows(C1A_DIR / "s4_4c1a_hourly_dispatch_c1.csv")
    analytics = _rows(C1A_DIR / "s4_4c1a_computational_analytics.csv")
    gate = json.loads((C1A_DIR / "s4_4c1a_stage_gate.json").read_text(encoding="utf-8"))

    assert len(c0_rows) == 24
    assert len(c1_rows) == 24
    assert {row["configuration_id"] for row in analytics} == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
    }
    assert gate["hourly_da_price_taking_active"] == "false"
    assert gate["product_revenue_active"] == "false"
    assert gate["export_revenue_active"] == "false"
    assert gate["direct_wag_market_valuation_active"] == "false"
