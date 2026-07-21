from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_x_wag_milp_integration_mapping import (  # noqa: E402
    EMISSION_GATE_COLUMNS, GAP_COLUMNS, MAP_COLUMNS, MIGRATION_COLUMNS, OUTPUT_DIR,
    REPORT_PATH, VALIDATION_COLUMNS, run_s4_4c5p_x_wag_milp_integration_mapping,
)
from steel.s4_4b_unified_input_validator import validate_unified_dev_inputs  # noqa: E402
from steel.s4_4c_unified_physical_modelbuilder import S44B_INPUT_DIR  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_x_wag_milp_integration_mapping()
    return OUTPUT_DIR


def test_required_outputs_parse(outputs: Path):
    required = {
        "wag_milp_interface_map.csv": MAP_COLUMNS,
        "wag_milp_hardening_gap_register.csv": GAP_COLUMNS,
        "wag_milp_emission_integration_gate.csv": EMISSION_GATE_COLUMNS,
        "next_executable_migration_packet.csv": MIGRATION_COLUMNS,
        "validation_checks.csv": VALIDATION_COLUMNS,
    }
    for name, columns in required.items():
        rows = _read_csv(outputs / name)
        assert rows
        assert set(columns).issubset(rows[0])
    assert REPORT_PATH.exists()
    for name in ("input_manifest.json", "code_version.json", "s4_4c5p_x_stage_gate.json", "summary.json", "registry_entry.json"):
        assert json.loads((outputs / name).read_text(encoding="utf-8"))


def test_current_minimal_layer_is_not_silently_accepted(outputs: Path):
    gaps = _read_csv(outputs / "wag_milp_hardening_gap_register.csv")
    assert any(row["gap_id"] == "X_GAP_001" and row["severity"] == "blocking" for row in gaps)
    gate = json.loads((outputs / "s4_4c5p_x_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["activate_current_minimal_WAG_layer"] == "NO_GO"


def test_no_emission_or_sensitivity_promotion(outputs: Path):
    gate = json.loads((outputs / "s4_4c5p_x_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["explicit_fuel_emissions_in_MILP"] == "NO_GO_PENDING_WAG_GATE"
    assert gate["go_no_go"]["sensitivity_execution"] == "NO_GO_PENDING_RECONCILIATION_GATE"
    assert gate["guardrails"]["aggregate_process_co2_added"] is False


def test_map_preserves_carrier_specific_policy(outputs: Path):
    rows = _read_csv(outputs / "wag_milp_interface_map.csv")
    assert not any(row["carrier"] in {"aggregate_wag", "mixed_wag"} for row in rows)


def test_builder_default_uses_the_validated_corrected_input_surface():
    result = validate_unified_dev_inputs(S44B_INPUT_DIR)
    assert result["may_proceed_to_s4_4c"] is True
    assert result["failure_count"] == 0
