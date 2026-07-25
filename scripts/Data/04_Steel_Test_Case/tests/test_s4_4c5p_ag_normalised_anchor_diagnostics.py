from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ag_normalised_anchor_diagnostics import _anchor_intensity_rows, _controller_sink_rows, _model_totals


def test_existing_carrier_and_controller_wiring_passes() -> None:
    rows = _controller_sink_rows()
    assert len(rows) == 10
    assert all(row["status"] == "pass_wiring" for row in rows)


def test_athanasiadis_wag_comparison_is_conditional_not_a_score() -> None:
    totals, _ = _model_totals()
    rows = _anchor_intensity_rows(totals)
    c0_wag = next(row for row in rows if row["anchor_id"] == "athan_table8_current_wag_2_74")
    assert c0_wag["comparison_status"] == "conditional_not_a_score"
    assert float(c0_wag["ratio_model_to_anchor"]) > 1.0
