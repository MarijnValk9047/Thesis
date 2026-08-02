from __future__ import annotations

from pathlib import Path
import sys

import pytest

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5h_four_residual_effect_gate import held_out_contract
from steel.s4_4c5p_phase5j_wag_electricity_closure import (
    CONFIG_PATH,
    _external_validity_checks,
    electricity_maps,
    load_config,
    load_selected_contract,
)


def test_phase5j_contract_is_exact_shared_90_percent_electricity_only() -> None:
    config = load_config()
    phase = config["phase5j"]
    rows = load_selected_contract(STEEL_ROOT.parents[2] / phase["selected_contract"])
    electricity = [row for row in rows if row["residual_family"] == "electricity"]
    assert {row["selected_share"] for row in electricity} == {0.9}
    assert electricity_maps(rows) == pytest.approx(
        {
            "C0_current_BF_BOF_reference": 141.37046680663974,
            "C1_phase1_BF_BOF_plus_DRP_EAF": 157.8475475859338,
        }
    )
    assert all(
        row["selected_share"] == row["annual_quantity_pj_y"] == row["hourly_quantity_mwh_h"] == 0.0
        for row in rows
        if row["residual_family"] != "electricity"
    )


def test_phase5j_fresh_periods_are_frozen_and_distinct() -> None:
    config = load_config(CONFIG_PATH)
    path = STEEL_ROOT.parents[2] / config["phase5j"]["held_out_contract"]
    rows, fingerprint = held_out_contract(path)
    assert len(rows) == 4
    assert len({row["period_id"] for row in rows}) == 4
    assert all(row["status"] == "frozen_unopened" for row in rows)
    assert len(fingerprint) == 64


def test_phase5j_external_validity_limits_are_absolute_and_predeclared() -> None:
    phase = load_config()["phase5j"]
    totals = {("C0", "electricity"): 12.3237579, ("C1", "electricity"): 17.2303980}
    anchors = {("C0", "electricity"): 13.7, ("C1", "electricity"): 17.8}
    flow = [
        {"configuration": "C0", "metric": "WAG_flared", "value": 0.55},
        {"configuration": "C1", "metric": "WAG_flared", "value": 0.17},
    ]
    checks = _external_validity_checks(totals, anchors, flow, phase)
    assert len(checks) == 4
    assert all(row["status"] == "pass" for row in checks)
    assert phase["policy"]["wag_yields_changed"] is False
    assert phase["policy"]["exact_anchor_closure_required"] is False
