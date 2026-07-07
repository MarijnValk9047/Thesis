from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c4_wag_steam_gas_readiness_audit import C4_DIR, run_s4_4c4_audit  # noqa: E402


REQUIRED_OUTPUTS = [
    "s4_4c4_wag_source_inventory.csv",
    "s4_4c4_existing_wag_input_mapping.csv",
    "s4_4c4_existing_model_equation_mapping.csv",
    "s4_4c4_abstraction_gap_matrix.csv",
    "s4_4c4_parameter_readiness.csv",
    "s4_4c4_policy_decisions_required.csv",
    "s4_4c4_implementation_plan.csv",
    "s4_4c4_stage_gate.json",
    "s4_4c4_stage_gate.csv",
]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c4_audit_creates_required_outputs() -> None:
    result = run_s4_4c4_audit()

    assert result["stage_gate"]["decision"] == "ready_for_s4_4c4b_with_policy_decisions"
    for name in REQUIRED_OUTPUTS:
        path = C4_DIR / name
        assert path.exists(), name
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        else:
            assert _rows(path), name


def test_s4_4c4_audit_records_current_wag_barriers() -> None:
    run_s4_4c4_audit()

    equations = {row["concept"]: row for row in _rows(C4_DIR / "s4_4c4_existing_model_equation_mapping.csv")}
    readiness = {row["parameter"]: row for row in _rows(C4_DIR / "s4_4c4_parameter_readiness.csv")}
    gate = json.loads((C4_DIR / "s4_4c4_stage_gate.json").read_text(encoding="utf-8"))

    assert equations["WAG flare aggregate"]["active_now"] == "yes"
    assert equations["Process-linked WAG sinks"]["active_now"] == "no"
    assert equations["Direct WAG valuation active"]["active_now"] == "no"
    assert readiness["alpha_fuel_HSM"]["readiness_class"] == "blocked_missing_source"
    assert readiness["alpha_fuel_Sinter_COG"]["readiness_class"] == "policy_decision_required"
    assert gate["raw_pdfs_inspected"] is False
    assert gate["model_equations_modified"] is False
    assert gate["thesis_usable"] is False
