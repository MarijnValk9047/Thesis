from __future__ import annotations

from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c_unified_physical_modelbuilder import run_s44c_unified_physical_regression  # noqa: E402


def test_c1_full_controller_gross_electricity_includes_existing_hsm_pefa_contracts() -> None:
    report = run_s44c_unified_physical_regression(
        run_id="test_c1_retained_route_electricity_integration",
        write_report=False,
        horizon_hours_override=24,
        fix_c0_binary_schedule=True,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        fix_c1_hybrid_schedule=True,
        c1_retained_route_policy="bottom_up_fixed_retained_route",
        development_controller_activation="full",
        solver_time_limit_seconds=25,
    )
    rows = [row for row in report["hourly_rows"] if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"]
    assert rows
    for row in rows:
        assert float(row["gross_electricity_mwh"]) == pytest.approx(
            float(row["base_process_electricity_mwh"])
            + float(row["development_controller_electricity_mwh"])
        )
