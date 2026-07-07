from __future__ import annotations

import csv
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5_anchor_route_denominator_diagnostics import (  # noqa: E402
    ANCHOR_COLUMNS,
    DECISION_COLUMNS,
    DENOM_COLUMNS,
    OUT_DIR,
    REPORT_PATH,
    ROUTE_COLUMNS,
    UTILITY_COLUMNS,
    build_outputs,
)
from steel.s4_4c5p_a_linde_asu_oxygen_accounting import (  # noqa: E402
    run_s4_4c5p_a_linde_asu_oxygen_accounting,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_c5_anchor_route_diagnostics_outputs_parse_and_have_required_columns():
    run_s4_4c5p_a_linde_asu_oxygen_accounting()
    result = build_outputs()
    assert result["status"] == "pass_diagnostic_only"
    assert REPORT_PATH.exists()

    expected = {
        OUT_DIR / "c5_anchor_reconciliation_matrix.csv": ANCHOR_COLUMNS,
        OUT_DIR / "c5_reconciliation_decision_register.csv": DECISION_COLUMNS,
        OUT_DIR / "c5_final_product_denominator_diagnostics.csv": DENOM_COLUMNS,
        OUT_DIR / "c5_route_origin_and_scrap_diagnostics.csv": ROUTE_COLUMNS,
        OUT_DIR / "c5_utility_readiness_diagnostics.csv": UTILITY_COLUMNS,
    }
    for path, columns in expected.items():
        rows = _read_csv(path)
        assert rows, path
        assert set(columns).issubset(rows[0].keys())


def test_c5_anchor_route_diagnostics_cover_required_decisions_and_caveats():
    run_s4_4c5p_a_linde_asu_oxygen_accounting()
    build_outputs()

    anchor_rows = _read_csv(OUT_DIR / "c5_anchor_reconciliation_matrix.csv")
    anchor_ids = {row["anchor_id"] for row in anchor_rows}
    for required in {
        "final_product_proxy",
        "eaf_dri_input",
        "dsp_output",
        "bf_coke_demand",
        "drp_oxygen",
        "eaf_oxygen",
        "process_electricity_total",
        "diagnostic_co2_total",
        "linde_total_oxygen_demand",
        "linde_asu_electricity",
        "linde_residual_unmodelled_oxygen",
    }:
        assert required in anchor_ids

    decisions = _read_csv(OUT_DIR / "c5_reconciliation_decision_register.csv")
    decision_ids = {row["decision_id"] for row in decisions}
    assert "C5_DECISION_FINAL_DENOMINATOR" in decision_ids
    assert "C5_DECISION_COKE_RECONCILIATION" in decision_ids
    assert "C5_DECISION_EAF_DRI_COEFF" in decision_ids
    coke_decision = next(row for row in decisions if row["decision_id"] == "C5_DECISION_COKE_RECONCILIATION")
    assert "active development baseline" in coke_decision["current_choice"]
    assert "fallback-only" in coke_decision["current_choice"]

    route_rows = _read_csv(OUT_DIR / "c5_route_origin_and_scrap_diagnostics.csv")
    assert any(
        row["topic"] == "DSP_route_origin"
        and row["status"] == "route_origin_not_fully_tracked"
        for row in route_rows
    )
    assert any(
        row["topic"] == "internal_scrap"
        and row["flow_or_asset"] == "DSP_internal_scrap_loss"
        and row["status"] == "reporting_only"
        for row in route_rows
    )

    utility_rows = _read_csv(OUT_DIR / "c5_utility_readiness_diagnostics.csv")
    utility_areas = {row["utility_area"] for row in utility_rows}
    assert {"Linde_ASU_oxygen", "boilers_steam", "Vattenfall_IJ01_VN25_generators"}.issubset(
        utility_areas
    )
    linde = next(row for row in utility_rows if row["utility_area"] == "Linde_ASU_oxygen")
    assert linde["current_status"] == "implemented_accounting_only_after_C5p_a"

    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "diagnostic-only review" in report
    assert "C1 has only a pooled liquid-steel-to-DSP interface" in report
    assert "A future economics denominator must be frozen" in report
    assert "Linde/ASU oxygen now adds current-C5 process electricity accounting" in report
