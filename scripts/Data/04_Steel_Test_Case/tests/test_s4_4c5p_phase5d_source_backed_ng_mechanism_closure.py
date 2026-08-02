from __future__ import annotations

import sys
from pathlib import Path

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5d_source_backed_ng_mechanism_closure import (  # noqa: E402
    heat_verification_rows,
    load_config,
    mechanism_candidates,
)


def test_phase5d_is_one_source_backed_non_endogenous_allocation() -> None:
    config = load_config()
    policy = config["phase5d"]["policy"]
    assert policy["flexible_ng_allocation_policy"] == "normal_case_reference_exact_hourly"
    assert policy["flexible_heat_ng_pj_lhv_y"] == pytest.approx(1.65)
    assert policy["flexible_heat_wag_pj_lhv_y"] == pytest.approx(1.42)
    assert policy["total_flexible_heat_service_pj_lhv_y"] == pytest.approx(3.07)
    assert policy["external_export_allowed"] is False
    assert policy["changes_total_heat_demand"] is False
    assert policy["changes_physics"] is False
    assert policy["held_out_periods_used"] is False


def test_phase5d_screens_out_unsourced_plant_specific_ng_shares() -> None:
    decisions = {row["candidate_id"]: row["decision"] for row in mechanism_candidates()}
    assert decisions == {
        "athanasiadis_normal_case_flexible_heat_allocation": "execute",
        "force_hsm_or_pefa_ng_share": "screen_out",
        "force_boiler_ng_share": "screen_out",
        "force_generator_ng_share": "screen_out",
    }


def test_heat_verification_uses_the_executed_c0_schema() -> None:
    rows = heat_verification_rows(
        "development",
        [
            {
                "configuration_id": "C0_current_BF_BOF_reference",
                "C0_HSM_final_product_t": 10.0,
                "BFG_to_HSM_mwh": 1.0,
                "COG_to_HSM_mwh": 0.0,
                "BOFG_to_HSM_mwh": 0.0,
                "NG_to_HSM_mwh": 0.0,
                "BOFG_to_PEFA_malerij_mwh": 0.0,
                "NG_to_PEFA_malerij_mwh": 0.0,
                "COG_to_PEFA_branderij_mwh": 0.0,
                "NG_to_PEFA_branderij_mwh": 0.0,
            }
        ],
    )
    hsm = next(row for row in rows if row["heat_sink"] == "HSM_reheat")
    assert hsm["demand_mwh"] > 0.0
