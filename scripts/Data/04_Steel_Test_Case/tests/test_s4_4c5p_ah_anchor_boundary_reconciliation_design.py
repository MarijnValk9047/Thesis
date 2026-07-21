from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ah_anchor_boundary_reconciliation_design import build_decision_rows, build_summary


def test_athanasiadis_wag_stays_context_only() -> None:
    row = next(item for item in build_decision_rows() if item["decision_id"] == "AH_01")
    assert row["status"] == "context_only_not_scoreable"
    assert row["go_no_go"] == "NO_GO_FOR_SCORING"


def test_residuals_stay_reporting_only_and_c5p_o_stays_authoritative() -> None:
    rows = build_decision_rows()
    residual = next(item for item in rows if item["decision_id"] == "AH_05")
    wag = next(item for item in rows if item["decision_id"] == "AH_06")
    assert residual["go_no_go"] == "GO_FOR_REPORTING_ONLY"
    assert wag["status"] == "C5p_o_authoritative"


def test_summary_keeps_model_changes_and_sensitivity_off() -> None:
    summary = build_summary(build_decision_rows())
    assert summary["combined_anchor_scoring"] == "NO_GO"
    assert summary["c1_non_wag_electricity_decomposition"] == "GO_DIAGNOSTIC_ONLY"
    assert not summary["guardrails"]["sensitivity_run"]
    assert not summary["guardrails"]["model_equations_changed"]
