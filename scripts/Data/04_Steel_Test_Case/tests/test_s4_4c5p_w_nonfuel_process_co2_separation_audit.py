from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_w_nonfuel_process_co2_separation_audit import (  # noqa: E402
    BOUNDARY_COLUMNS,
    ELIGIBILITY_COLUMNS,
    OUTPUT_DIR,
    PRIORITY_COLUMNS,
    REGISTER_COLUMNS,
    REPORT_PATH,
    VALIDATION_COLUMNS,
    run_s4_4c5p_w_nonfuel_process_co2_separation_audit,
)
from steel.s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger import OUTPUT_DIR as C5P_V_DIR  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_w_nonfuel_process_co2_separation_audit()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "nonfuel_process_co2_separation_register.csv": REGISTER_COLUMNS,
        "carbon_boundary_decision_matrix.csv": BOUNDARY_COLUMNS,
        "source_repair_priority.csv": PRIORITY_COLUMNS,
        "modelwide_ledger_addition_eligibility.csv": ELIGIBILITY_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_w_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_no_reviewed_process_component_is_added_now(outputs: Path):
    rows = _read_csv(outputs / "modelwide_ledger_addition_eligibility.csv")
    assert rows
    assert all(row["may_enter_c5p_v_explicit_total_now"] != "yes" for row in rows)
    assert all(row["would_change_current_total"] == "false" for row in rows)
    assert all(row["current_total_preserved"] == "true" for row in rows)


def test_explicit_fuel_totals_are_unchanged(outputs: Path):
    summary = json.loads((outputs / "summary.json").read_text(encoding="utf-8"))
    source = _read_csv(C5P_V_DIR / "explicit_fuel_total_vs_scope1.csv")
    expected = {row["configuration"]: float(row["explicit_fuel_co2_total_mt_y"]) for row in source}
    assert summary["explicit_fuel_totals_mt_y"] == expected


def test_capture_and_residuals_stay_out_of_scope(outputs: Path):
    rows = _read_csv(outputs / "nonfuel_process_co2_separation_register.csv")
    drp = next(row for row in rows if row["asset"] == "DRP")
    assert drp["decision"] == "report separately"
    assert drp["eligible_for_current_explicit_total"] == "no"


def test_stage_gate_is_not_ets_or_economic(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_w_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["add_BF_BOF_KGF_PEFA_sinter_EAF_nonfuel_terms"] == "NO_GO"
    assert gate["go_no_go"]["full_site_or_ETS_CO2"] == "NO_GO"
    assert gate["guardrails"]["aggregate_process_counter_added_to_total"] is False
    assert gate["guardrails"]["residual_energy_allocated_or_emitted"] is False
