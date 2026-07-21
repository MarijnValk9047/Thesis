from __future__ import annotations

import sys
from pathlib import Path

TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_au_linde_n2_wag_emissions_boundary import (
    _boundary_delta_rows,
    load_linde_n2_auxiliary_mwh_h,
)


def test_linde_n2_input_is_positive_and_fixed_context_load() -> None:
    assert load_linde_n2_auxiliary_mwh_h() == 45.0


def test_linde_boundary_delta_keeps_physical_quantities_unchanged() -> None:
    baseline = {
        "final_product_output": 6.7,
        "gross_electricity": 3.1,
        "ASU_electricity_development": 0.4,
        "Linde_N2_auxiliary_electricity_context": 0.0,
        "Linde_total_meter_electricity_context": 0.4,
        "net_grid_import_after_internal_WAG_offset": 2.5,
        "represented_oxygen_for_ASU": 900.0,
        "WAG_explicit_combustion_CO2": 4.5,
    }
    n2_case = {**baseline, "gross_electricity": 3.4942, "Linde_N2_auxiliary_electricity_context": 0.3942, "Linde_total_meter_electricity_context": 0.7942, "net_grid_import_after_internal_WAG_offset": 2.8942}
    deltas = {row["metric"]: row["delta"] for row in _boundary_delta_rows(baseline, n2_case)}
    assert deltas["final_product_output"] == 0.0
    assert deltas["represented_oxygen_for_ASU"] == 0.0
    assert deltas["WAG_explicit_combustion_CO2"] == 0.0
    assert deltas["Linde_N2_auxiliary_electricity_context"] == 0.3942
