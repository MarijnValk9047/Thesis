from __future__ import annotations

from pathlib import Path
import sys

import pytest

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5h_four_residual_effect_gate import held_out_contract
from steel.s4_4c5p_phase5k_final_user_authorized_boundary_freeze import (
    CONFIG_PATH,
    boundary_maps,
    load_config,
    load_final_contract,
    load_wag_audit_contract,
    select_common_co2_increment,
    wag_yield_overrides,
)


def _repo(path: str) -> Path:
    return STEEL_ROOT.parents[2] / path


def test_phase5k_wag_fallback_is_c0_only_and_carrier_separated() -> None:
    phase = load_config()["phase5k"]
    rows = load_wag_audit_contract(_repo(phase["wag_carrier_audit_contract"]))
    assert wag_yield_overrides(rows) == {
        "C0_current_BF_BOF_reference": {"BFG": 1520.0, "COG": 346.75, "BOFG": 71.25}
    }
    assert sum(row["mer_source_production_pj_y"] for row in rows if row["configuration"] == "C0") == pytest.approx(52.9)
    assert sum(row["mer_source_production_pj_y"] for row in rows if row["configuration"] == "C1") == pytest.approx(25.1)


def test_phase5k_common_ng_and_co2_contract_identities() -> None:
    phase = load_config()["phase5k"]
    rows = load_final_contract(_repo(phase["final_boundary_contract"]))
    electricity, ng, co2 = boundary_maps(rows)
    assert electricity == pytest.approx({"C0_current_BF_BOF_reference": 141.37046680663974, "C1_phase1_BF_BOF_plus_DRP_EAF": 157.8475475859338})
    assert list(ng.values()) == pytest.approx([7.0 / (8760.0 * 3.6e-6)] * 2)
    assert list(co2.values()) == pytest.approx([2_000_000.0 / 8760.0] * 2)
    assert all(row["annual_quantity"] == 0.0 for row in rows if row["residual_family"] == "residual_steam")


def test_phase5k_common_co2_grid_selection_is_deterministic() -> None:
    selected, rows = select_common_co2_increment(
        {"C0": 10.0918, "C1": 6.7045}, {"C0": 12.62, "C1": 8.3},
        [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
    )
    assert selected == 2.0
    assert len(rows) == 7


def test_phase5k_fresh_periods_are_distinct_and_unopened() -> None:
    phase = load_config(CONFIG_PATH)["phase5k"]
    fresh, _ = held_out_contract(_repo(phase["held_out_contract"]))
    old, _ = held_out_contract(_repo(phase["phase5j_held_out_contract"]))
    assert len(fresh) == 4
    assert {row["frozen_forecast_start_origin_utc"] for row in fresh}.isdisjoint(
        row["frozen_forecast_start_origin_utc"] for row in old
    )
    assert all(row["status"] == "frozen_unopened" for row in fresh)


def test_phase5k_policy_makes_flare_warning_nonblocking_and_co2_non_ets() -> None:
    policy = load_config()["phase5k"]["policy"]
    assert policy["flare_is_reporting_warning_not_hard_freeze_gate"] is True
    assert policy["residual_co2_reporting_only"] is True
    assert policy["residual_co2_in_cost_or_ets"] is False
    assert policy["adaptive_parameter_sweep_allowed"] is False
    assert policy["heldout_reselection_allowed"] is False
