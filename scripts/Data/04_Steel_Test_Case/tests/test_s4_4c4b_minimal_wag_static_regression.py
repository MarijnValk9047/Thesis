from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c4b_minimal_wag_static_regression import (  # noqa: E402
    C4B_168H_DIR,
    C4B_24H_DIR,
    C4B_IMPL_DIR,
    run_168h,
    run_24h,
    run_phase1,
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c4b_phase1_and_24h_minimal_wag_layer() -> None:
    phase1 = run_phase1()
    phase2 = run_24h()

    assert phase1["decision"] == "pass_to_phase2_24h_wag_rerun"
    assert phase2["phase_stage_gate"]["decision"] == "pass_to_phase3_168h_wag_rerun"

    gate = json.loads((C4B_24H_DIR / "s4_4c4b_24h_stage_gate.json").read_text(encoding="utf-8"))
    carrier_rows = _rows(C4B_24H_DIR / "s4_4c4b_24h_wag_by_carrier.csv")
    sink_rows = _rows(C4B_24H_DIR / "s4_4c4b_24h_wag_by_sink.csv")
    c0_cog = next(row for row in carrier_rows if row["configuration_id"] == "C0_current_BF_BOF_reference" and row["carrier"] == "COG")
    sinter = next(row for row in sink_rows if row["configuration_id"] == "C0_current_BF_BOF_reference" and row["sink"] == "Sinter")
    vattenfall = next(row for row in sink_rows if row["configuration_id"] == "C0_current_BF_BOF_reference" and row["sink"] == "Vattenfall")

    assert float(c0_cog["used_mwh"]) > 0.0
    assert float(c0_cog["max_abs_balance_residual_mwh"]) == 0.0
    assert float(sinter["used_or_flared_mwh"]) > 0.0
    assert float(vattenfall["used_or_flared_mwh"]) == 0.0
    assert gate["direct_wag_market_valuation_active"] is False
    assert gate["vattenfall_dispatch_active"] is False
    assert gate["wag_storage_active"] is False


def test_s4_4c4b_168h_runs_with_declared_caveat() -> None:
    run_phase1()
    run_24h()
    phase3 = run_168h()

    assert phase3["phase_stage_gate"]["decision"] == "pass_168h_with_wag_caveats"
    gate = json.loads((C4B_168H_DIR / "s4_4c4b_168h_stage_gate.json").read_text(encoding="utf-8"))
    carrier_rows = _rows(C4B_168H_DIR / "s4_4c4b_168h_wag_by_carrier.csv")
    c0_rows = [row for row in carrier_rows if row["configuration_id"] == "C0_current_BF_BOF_reference"]
    c1_rows = [row for row in carrier_rows if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"]

    assert gate["max_abs_wag_balance_residual_mwh"] == 0.0
    assert any(float(row["generated_mwh"]) > 0 for row in c0_rows)
    assert all(float(row["generated_mwh"]) == 0 for row in c1_rows)
    assert all("retained BF-BOF WAG route" in row["caveat"] for row in c1_rows)
    assert (C4B_IMPL_DIR / "s4_4c4b_parameter_values_used.csv").exists()
