from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_u_wag_explicit_co2_anchor_reconciliation import (  # noqa: E402
    ANCHOR_COLUMNS,
    MODE_COLUMNS,
    OUTPUT_DIR,
    POLICY_COLUMNS,
    REPORT_PATH,
    RESIDUAL_COLUMNS,
    VALIDATION_COLUMNS,
    WAG_LEDGER_COLUMNS,
    run_s4_4c5p_u_wag_explicit_co2_anchor_reconciliation,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_u_wag_explicit_co2_anchor_reconciliation()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "wag_point_of_oxidation_co2_ledger.csv": WAG_LEDGER_COLUMNS,
        "co2_reconciliation_by_mode.csv": MODE_COLUMNS,
        "co2_component_inclusion_policy.csv": POLICY_COLUMNS,
        "co2_anchor_comparison.csv": ANCHOR_COLUMNS,
        "residual_boundary_kpis.csv": RESIDUAL_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_u_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_wag_ledger_is_carrier_specific_and_excludes_ng(outputs: Path):
    rows = _read_csv(outputs / "wag_point_of_oxidation_co2_ledger.csv")
    assert {row["carrier"] for row in rows} <= {"BFG", "COG", "BOFG"}
    assert all("No NG" in row["caveat"] for row in rows)


def test_wag_mode_excludes_overlapping_aggregate_components(outputs: Path):
    rows = _read_csv(outputs / "co2_component_inclusion_policy.csv")
    excluded = {row["component"] for row in rows if row["may_be_added_to_wag_explicit_total"] == "no"}
    assert {"PEFA aggregate diagnostic CO2", "BF/BOF/KGF aggregate CO2 candidates", "DRP capture stream"} <= excluded


def test_scope1_residuals_remain_visible_and_signed(outputs: Path):
    rows = _read_csv(outputs / "co2_reconciliation_by_mode.csv")
    assert all(float(row["residual_to_scope1_anchor_mt_y"]) >= 0.0 for row in rows)
    assert all(row["comparison_status"] == "partial_validation_only" for row in rows)


def test_energy_residuals_are_not_activated(outputs: Path):
    rows = _read_csv(outputs / "residual_boundary_kpis.csv")
    assert all(row["active_as_model_load_or_allocation"] == "false" for row in rows)
    assert {row["metric"] for row in rows} == {"gross_electricity_boundary_residual", "full_site_NG_boundary_residual"}


def test_stage_gate_does_not_unlock_ets_or_residual_allocation(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_u_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["WAG_explicit_CO2_subtotal"] == "GO_DIAGNOSTIC_ONLY"
    assert gate["go_no_go"]["consolidated_site_or_ETS_CO2"] == "NO_GO"
    assert gate["guardrails"]["residual_energy_allocated"] is False
    assert gate["guardrails"]["invented_wag_ng_ratio"] is False
