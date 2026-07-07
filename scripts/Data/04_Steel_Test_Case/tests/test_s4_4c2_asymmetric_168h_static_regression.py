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
from steel.s4_4c_asymmetric_static_regression import C2_DIR, run_c1a_24h, run_c2_168h  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c2_runs_168h_only_after_24h_gate() -> None:
    run_b5a_correction()
    run_phase2_validation()
    run_c1a_24h()
    report = run_c2_168h()
    gate = report["phase_stage_gate"]
    audits = {row["configuration_id"]: row for row in report["configuration_build_audit"]}

    assert gate["decision"] == "pass_168h_static_physical_both_configs"
    assert gate["horizon_hours"] == 168
    assert audits["C0_current_BF_BOF_reference"]["build_status"] == "solved"
    assert audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["build_status"] == "solved"
    assert float(audits["C0_current_BF_BOF_reference"]["final_product_residual_t"]) == 0.0
    assert float(audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["final_product_residual_t"]) == 0.0

    c0_rows = _rows(C2_DIR / "s4_4c2_hourly_dispatch_c0.csv")
    c1_rows = _rows(C2_DIR / "s4_4c2_hourly_dispatch_c1.csv")
    daily_rows = _rows(C2_DIR / "s4_4c2_daily_summary.csv")
    analytics = _rows(C2_DIR / "s4_4c2_computational_analytics.csv")

    assert len(c0_rows) == 168
    assert len(c1_rows) == 168
    assert len(daily_rows) == 14
    assert all(row["runtime_scaling_ratio_vs_24h"] != "" for row in analytics)
    json.loads((C2_DIR / "s4_4c2_168h_static_physical_report.json").read_text(encoding="utf-8"))
