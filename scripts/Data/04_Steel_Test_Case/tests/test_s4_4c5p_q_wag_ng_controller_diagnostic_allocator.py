from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_q_wag_ng_controller_diagnostic_allocator import (  # noqa: E402
    BALANCE_COLUMNS,
    BLOCKED_COLUMNS,
    MIX_COLUMNS,
    OUTPUT_DIR,
    RECONCILIATION_COLUMNS,
    REPORT_PATH,
    VALIDATION_COLUMNS,
    WAG_CO2_COLUMNS,
    run_s4_4c5p_q_wag_ng_controller_diagnostic_allocator,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_q_wag_ng_controller_diagnostic_allocator()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "controller_mix_allocation.csv": MIX_COLUMNS,
        "carrier_balance_after_allocation.csv": BALANCE_COLUMNS,
        "process_controller_reconciliation.csv": RECONCILIATION_COLUMNS,
        "blocked_cases.csv": BLOCKED_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
        "wag_point_of_oxidation_co2_ledger.csv": WAG_CO2_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_q_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_only_carrier_specific_physical_rows_are_emitted(outputs: Path):
    rows = _read_csv(outputs / "controller_mix_allocation.csv")
    assert {row["carrier"] for row in rows} <= {"BFG", "COG", "BOFG", "NG"}
    assert not any(row["carrier"] in {"aggregate_wag", "mixed_wag"} for row in rows)


def test_c5p_k_is_not_allocation_provenance(outputs: Path):
    rows = _read_csv(outputs / "controller_mix_allocation.csv")
    assert not any("C5p_k" in row["allocation_provenance"] for row in rows)


def test_blocked_cases_preserve_missing_controllers(outputs: Path):
    rows = _read_csv(outputs / "blocked_cases.csv")
    blocked_sinks = {row["sink_or_controller"] for row in rows}
    assert {"KGF_underfiring", "BF_hot_stove", "PEFA_Malerij_and_Branderij", "common_plant_WAG_NG_split"} <= blocked_sinks
    assert any(row["carrier"] == "mixed_wag" for row in rows)


def test_balance_is_preserved_without_reallocation(outputs: Path):
    rows = _read_csv(outputs / "carrier_balance_after_allocation.csv")
    assert rows
    assert all(row["allocator_effect"] == "none; C5p_q compiles existing controller mixes only" for row in rows)
    assert all(row["balance_status"] == "pass" for row in rows)


def test_process_remainder_is_visible_not_reallocated(outputs: Path):
    rows = _read_csv(outputs / "process_controller_reconciliation.csv")
    assert rows
    assert any(row["reconciliation_status"] == "partial" for row in rows)
    assert all(
        row["reconciliation_status"] == "pass"
        for row in rows
        if row["carrier"] == "BFG"
    )
    assert all("not reallocated" in row["caveat"] for row in rows)


def test_stage_gate_remains_diagnostic_only(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_q_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["status"] == "partial_diagnostic_allocation"
    assert gate["guardrails"]["new_physical_allocator_created"] is False
    assert gate["guardrails"]["invented_wag_ng_ratio"] is False
    assert gate["go_no_go"]["complete_common_plant_WAG_NG_physical_allocation"] == "NO_GO"
    assert gate["go_no_go"]["NG_residual_policy"] == "NO_GO"
    assert gate["go_no_go"]["WAG_explicit_CO2_ledger"] == "GO_DIAGNOSTIC_ONLY_PARTIAL"
    assert gate["go_no_go"]["consolidated_site_or_ETS_CO2"] == "NO_GO"


def test_wag_explicit_co2_is_carrier_specific_and_excludes_ng_residuals(outputs: Path):
    rows = _read_csv(outputs / "wag_point_of_oxidation_co2_ledger.csv")
    assert rows
    assert {row["carrier"] for row in rows} <= {"BFG", "COG", "BOFG"}
    assert all(row["carbon_accounting_mode"] == "point_of_oxidation_partial_WAG_explicit" for row in rows)
    assert all("aggregate BF/BOF/KGF/PEFA process counters" in row["caveat"] for row in rows)
    summary = json.loads((outputs / "summary.json").read_text(encoding="utf-8"))
    assert set(summary["wag_explicit_co2_partial_totals_t_y"]) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
    }
    assert all(value > 0.0 for value in summary["wag_explicit_co2_partial_totals_t_y"].values())


def test_wobbe_is_out_of_scope_not_an_unlocked_mixing_requirement(outputs: Path):
    rows = _read_csv(outputs / "blocked_cases.csv")
    mixed = next(row for row in rows if row["carrier"] == "mixed_wag")
    assert "outside thesis scope" in mixed["missing_requirement"]
    assert mixed["unlocks_after"] == "Not planned in current thesis scope."


def test_athanasiadis_alignment_remains_methodological_only(outputs: Path):
    rows = _read_csv(outputs / "athanasiadis_alignment_check.csv")
    assert rows
    assert {row["alignment_status"] for row in rows} <= {"aligned", "partially_aligned"}
    assert any("No Athanasiadis PDF" in row["caveat"] for row in rows)
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "not a numeric replication" in report
