from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger import (  # noqa: E402
    COVERAGE_COLUMNS,
    LEDGER_COLUMNS,
    OUTPUT_DIR,
    REPORT_PATH,
    RESIDUAL_COLUMNS,
    TOTAL_COLUMNS,
    VALIDATION_COLUMNS,
    run_s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "modelwide_emissions_ledger.csv": LEDGER_COLUMNS,
        "asset_emissions_coverage.csv": COVERAGE_COLUMNS,
        "explicit_fuel_total_vs_scope1.csv": TOTAL_COLUMNS,
        "residual_energy_policy_kpis.csv": RESIDUAL_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_v_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))
    assert REPORT_PATH.exists()


def test_explicit_total_contains_only_wag_and_named_ng(outputs: Path):
    rows = _read_csv(outputs / "modelwide_emissions_ledger.csv")
    included = [row for row in rows if row["included_in_explicit_fuel_total"] == "true"]
    assert included
    assert {row["emission_category"] for row in included} <= {
        "explicit_WAG_point_of_oxidation",
        "explicit_modelled_NG_point_of_oxidation",
    }
    assert not any(row["emission_category"] == "aggregate_process_validation_only" for row in included)


def test_ng_is_counted_only_for_named_modelled_consumers(outputs: Path):
    rows = _read_csv(outputs / "modelwide_emissions_ledger.csv")
    ng = [row for row in rows if row["carrier"] == "NG"]
    assert ng
    assert all(row["status"] == "represented_named_NG_consumer" for row in ng)
    assert not any("residual" in row["emission_component_id"].lower() for row in ng)


def test_capture_and_aggregate_components_remain_separate(outputs: Path):
    rows = _read_csv(outputs / "modelwide_emissions_ledger.csv")
    capture = [row for row in rows if row["emission_category"] == "capture_reporting_only"]
    aggregate = [row for row in rows if row["emission_category"] == "aggregate_process_validation_only"]
    assert capture and aggregate
    assert all(row["included_in_explicit_fuel_total"] == "false" for row in capture + aggregate)


def test_residual_energy_has_no_emissions_inferred(outputs: Path):
    rows = _read_csv(outputs / "residual_energy_policy_kpis.csv")
    assert all(row["active_as_model_load_or_allocation"] == "false" for row in rows)
    assert all(row["co2_inferred_from_residual"] == "false" for row in rows)


def test_stage_gate_stays_non_ets_and_non_economic(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_v_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["modelwide_explicit_fuel_CO2_subtotal"] == "GO_DIAGNOSTIC_ONLY"
    assert gate["go_no_go"]["consolidated_site_or_ETS_CO2"] == "NO_GO"
    assert gate["guardrails"]["aggregate_process_counter_added_to_total"] is False
    assert gate["guardrails"]["residual_energy_allocated_or_emitted"] is False
