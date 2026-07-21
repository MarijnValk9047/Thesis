from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ai_c1_electricity_boundary_decomposition import (
    build_decomposition_rows,
    build_reconciliation_rows,
    build_residual_rows,
)


def test_named_c1_loads_are_reconstructed_without_new_parameters() -> None:
    rows, values = build_decomposition_rows()
    named = {row["bucket"]: row for row in rows}
    assert float(named["DRP"]["current_model_mwh"]) > 0.0
    assert float(named["EAF"]["current_model_mwh"]) > 0.0
    assert named["HSM_WBW_rolling"]["current_model_mwh"] == ""
    assert float(named["HSM_WBW_rolling"]["contract_implied_mwh"]) > 0.0
    assert named["ASU_oxygen"]["current_model_mwh"] == ""
    assert abs(values["unattributed_represented_mwh"]) < 1e-5
    assert values["gross_mwh"] > 0.0


def test_reconciliation_keeps_generator_offset_separate() -> None:
    _, values = build_decomposition_rows()
    row = build_reconciliation_rows(values)[0]
    assert abs(float(row["identity_residual_mwh"])) < 1e-5
    assert "C5p_o" in row["wag_interpretation"]


def test_residual_is_reporting_not_optimizer_load() -> None:
    _, values = build_decomposition_rows()
    rows = build_residual_rows(values)
    assert rows[0]["status"] == "diagnostic_only_not_an_optimizer_load"
    assert rows[0]["signed_residual_mwh_y"] != ""
