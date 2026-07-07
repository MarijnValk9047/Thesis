from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5b_site_scale_downstream_steam_wag_reconciliation import (  # noqa: E402
    C5B_DIR,
    C1_ELECTRICITY_GAP_CLASS,
    run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation,
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c5b_writes_required_outputs_and_stage_gate() -> None:
    result = run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation()

    required = [
        "s4_4c5b_stage_gate.json",
        "s4_4c5b_run_registry.csv",
        "s4_4c5b_24h_summary.csv",
        "s4_4c5b_168h_summary.csv",
        "s4_4c5b_annual_validation_dashboard.csv",
        "s4_4c5b_anchor_gap_dashboard.csv",
        "s4_4c5b_route_capacity_dashboard.csv",
        "s4_4c5b_downstream_continuation_dashboard.csv",
        "s4_4c5b_steam_accounting_dashboard.csv",
        "s4_4c5b_ng_accounting_dashboard.csv",
        "s4_4c5b_electricity_accounting_dashboard.csv",
        "s4_4c5b_co2_accounting_dashboard.csv",
        "s4_4c5b_vattenfall_cap_hourly.csv",
        "s4_4c5b_wag_allocation_hourly.csv",
        "s4_4c5b_plant_carrier_io_hourly.csv",
        "s4_4c5b_component_gap_register.csv",
    ]
    assert result["stage_gate"]["decision"] == "pass_s4_4c5b_development_accounting_reconciliation_with_caveats"
    assert all((C5B_DIR / name).exists() for name in required)

    gate = json.loads((C5B_DIR / "s4_4c5b_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["anchors_are_constraints"] is False
    assert gate["steam_validation_anchor_active"] is False
    assert gate["fixed_50_50_wag_ng_boiler_split_active"] is False
    assert gate["wag_first_allocation_implemented"] is True
    assert gate["vattenfall_cap_policy"] == "combined_BFG_COG_BOFG_volume_cap_not_per_carrier"


def test_s4_4c5b_freezes_target_and_downstream_continuation() -> None:
    run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation()

    downstream = _rows(C5B_DIR / "s4_4c5b_downstream_continuation_dashboard.csv")
    routes = _rows(C5B_DIR / "s4_4c5b_route_capacity_dashboard.csv")
    c1_routes = [row for row in routes if row["configuration_id"].startswith("C1")]

    assert all(float(row["production_residual_t"]) == 0.0 for row in downstream)
    assert all(row["target_basis"] == "liquid_steel_equivalent_with_downstream_continuation" for row in downstream)
    assert all(float(row["external_slab_import_t"]) == 0.0 for row in downstream)
    assert {round(float(row["retained_route_share"]), 9) for row in c1_routes} == {0.427589243}
    assert all(row["Heracless_anchor_status"] == "missing_reviewed_or_migrated_source_in_C5a_inputs" for row in routes)


def test_s4_4c5b_wag_steam_electricity_and_gap_rows() -> None:
    run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation()

    steam = _rows(C5B_DIR / "s4_4c5b_steam_accounting_dashboard.csv")
    allocation = _rows(C5B_DIR / "s4_4c5b_wag_allocation_hourly.csv")
    electricity = _rows(C5B_DIR / "s4_4c5b_electricity_accounting_dashboard.csv")
    gaps = _rows(C5B_DIR / "s4_4c5b_component_gap_register.csv")

    assert all(row["steam_basis"] == "residual_unvalidated_placeholder" for row in steam)
    assert all(row["steam_validation_anchor_active"] == "False" for row in steam)
    assert any(row["allocation_category"] == "boiler_steam_wag_first" for row in allocation)
    assert any(row["carrier"] == "NaturalGas" and row["allocation_category"] == "boiler_steam_ng_supplement" for row in allocation)
    assert any(row["sink"] == "WAGs_COK1" and row["carrier"] in {"BFG", "COG"} for row in allocation)
    assert not any(row["sink"] == "WAGs_COK1" and row["carrier"] == "NaturalGas" for row in allocation)
    assert any(row["status"] == "missing_executable_coefficient" for row in allocation)
    assert any(row["configuration_id"].startswith("C0") and row["scale_mode"] == "full_site_proxy_no_module_upscale" for row in electricity)
    assert any(row["configuration_id"].startswith("C1") and row["gap_classification"] == C1_ELECTRICITY_GAP_CLASS for row in electricity)
    assert any(row["component"] == "HSM COG/NG use" and row["status"] == "missing_executable_coefficient" for row in gaps)


def test_s4_4c5b_long_format_and_vattenfall_cap() -> None:
    run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation()

    io_rows = _rows(C5B_DIR / "s4_4c5b_plant_carrier_io_hourly.csv")
    cap_rows = _rows(C5B_DIR / "s4_4c5b_vattenfall_cap_hourly.csv")
    required_columns = {
        "configuration",
        "horizon_hours",
        "hour",
        "plant",
        "component",
        "carrier",
        "direction",
        "quantity",
        "unit",
        "accounting_class",
        "source_or_assumption",
        "status",
    }

    assert required_columns.issubset(io_rows[0].keys())
    assert max(float(row["combined_vattenfall_wag_volume_Nm3_h"]) for row in cap_rows) <= 900000.0
    assert any(int(float(row["binding_hours"])) > 0 for row in cap_rows if row["configuration_id"].startswith("C1"))
