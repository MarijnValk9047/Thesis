from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_y_wag_governed_input_contract import (  # noqa: E402
    BLOCKER_COLUMNS, CARRIER_COLUMNS, DEMAND_COLUMNS, OUTPUT_DIR, REPORT_PATH,
    ROUTE_COLUMNS, VALIDATION_COLUMNS, run_s4_4c5p_y_wag_governed_input_contract,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_y_wag_governed_input_contract()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "governed_carrier_parameter_register.csv": CARRIER_COLUMNS,
        "governed_route_status.csv": ROUTE_COLUMNS,
        "demand_binding_status.csv": DEMAND_COLUMNS,
        "blocked_activation_register.csv": BLOCKER_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    assert REPORT_PATH.exists()
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_y_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))


def test_contract_preserves_only_physical_carriers(outputs: Path):
    routes = _read_csv(outputs / "governed_route_status.csv")
    assert routes
    assert {row["carrier"] for row in routes} <= {"BFG", "COG", "BOFG"}


def test_kgf_bfg_route_is_blocked(outputs: Path):
    routes = _read_csv(outputs / "governed_route_status.csv")
    assert any(row["carrier"] == "BFG" and row["sink_asset"] == "WAG_COK1_mixer" and row["physical_MILP_status"] == "blocked" for row in routes)


def test_no_route_or_emissions_is_activated(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_y_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["physical_WAG_MILP_activation"] == "NO_GO"
    assert gate["go_no_go"]["emissions_expression_activation"] == "NO_GO"
    assert gate["guardrails"]["aggregate_or_mixed_WAG_promoted"] is False
