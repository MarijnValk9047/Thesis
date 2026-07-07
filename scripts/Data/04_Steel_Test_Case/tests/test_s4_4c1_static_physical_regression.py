from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4b5_c0_c1_assumption_completion import run_completion  # noqa: E402
from steel.s4_4c1_static_physical_regression import (  # noqa: E402
    S44C1_DIR,
    run_s4_4c1_static_physical_regression,
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c1_runs_both_completed_configurations() -> None:
    run_completion()
    report = run_s4_4c1_static_physical_regression()
    gate = report["s4_4c1_stage_gate"]
    audits = {row["configuration_id"]: row for row in report["configuration_build_audit"]}

    assert gate["decision"] == "pass_24h_static_physical_both_configs"
    assert audits["C0_current_BF_BOF_reference"]["build_status"] == "solved"
    assert audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["build_status"] == "solved"
    assert float(audits["C0_current_BF_BOF_reference"]["final_product_residual_t"]) == 0.0
    assert float(audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["final_product_residual_t"]) == 0.0


def test_s4_4c1_outputs_parse_and_split_hourly_dispatch() -> None:
    run_completion()
    run_s4_4c1_static_physical_regression()
    for name in [
        "s4_4c1_static_physical_report.json",
        "s4_4c1_stage_gate.json",
    ]:
        json.loads((S44C1_DIR / name).read_text(encoding="utf-8"))

    c0_rows = _rows(S44C1_DIR / "s4_4c1_hourly_dispatch_c0.csv")
    c1_rows = _rows(S44C1_DIR / "s4_4c1_hourly_dispatch_c1.csv")
    analytics = _rows(S44C1_DIR / "s4_4c1_computational_analytics.csv")
    metrics = _rows(S44C1_DIR / "s4_4c1_run_metrics.csv")

    assert len(c0_rows) == 24
    assert len(c1_rows) == 24
    assert {row["configuration_id"] for row in analytics} == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
    }
    assert all(float(row["total_runtime_seconds"]) > 0 for row in analytics)
    assert all(row["build_status"] == "solved" for row in metrics)


def test_s4_4c1_forbidden_terms_remain_inactive() -> None:
    run_completion()
    run_s4_4c1_static_physical_regression()
    gate = json.loads((S44C1_DIR / "s4_4c1_stage_gate.json").read_text(encoding="utf-8"))

    assert gate["hourly_da_price_taking_active"] == "false"
    assert gate["product_revenue_active"] == "false"
    assert gate["export_revenue_active"] == "false"
    assert gate["grid_tariff_objective_active"] == "false"
    assert gate["direct_wag_market_valuation_active"] == "false"
    assert gate["co2_ets_objective_active"] == "false"
    assert gate["may_proceed_to_168h"] == "false"
