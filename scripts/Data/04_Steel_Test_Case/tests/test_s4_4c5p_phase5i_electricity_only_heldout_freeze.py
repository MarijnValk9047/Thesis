from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pyomo.environ import value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5h_four_residual_effect_gate import held_out_contract
from steel.s4_4c5p_phase5i_electricity_only_heldout_freeze import (
    CLASSIFICATION, CONFIG_PATH, electricity_maps, load_config,
    load_selected_contract, promoted_rows, validate_pool_identity,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT, S44B_INPUT_DIR, _build_c0_inputs, _build_c0_model, _load_tables,
)


CONTRACT_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_phase5i_electricity_only_contract"
HELDOUT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_phase5h_four_residual_contract/fresh_held_out_period_contract.csv"
POOL = REPO_ROOT / "data/03_Optimisation/runs/steel_c5_phase5h_four_residual_final_selection_gate_v1_20260728/source_service_pool.csv"


def test_phase5i_contract_has_exact_ten_percent_identity_and_zero_other_residuals() -> None:
    rows = load_selected_contract(CONTRACT_ROOT / "electricity_only_baseload_contract.csv")
    electricity = [row for row in rows if row["residual_family"] == "electricity"]

    assert {row["selected_share"] for row in electricity} == {0.1}
    assert {row["classification"] for row in electricity} == {CLASSIFICATION}
    assert sorted(row["hourly_quantity_mwh_h"] for row in electricity) == pytest.approx([
        15.707829645182194, 17.53861639843709
    ])
    for row in electricity:
        assert row["hourly_quantity_mwh_h"] * 8760 * 3.6e-6 == pytest.approx(
            row["annual_quantity_pj_y"]
        )
        assert row["price_responsive"] == "false"
        assert row["status"] == "heldout_validated_promoted"
        assert row["executable"] == "true"
    zero = [row for row in rows if row["residual_family"] != "electricity"]
    assert all(row["selected_share"] == row["annual_quantity_pj_y"] == row["hourly_quantity_mwh_h"] == 0 for row in zero)


def test_phase5i_contract_reproduces_frozen_phase5h_pools() -> None:
    rows = load_selected_contract(CONTRACT_ROOT / "electricity_only_baseload_contract.csv")
    checks = validate_pool_identity(rows, POOL)

    assert len(checks) == 2
    assert all(row["status"] == "pass" for row in checks)


def test_phase5i_config_blocks_every_other_residual_and_reselection() -> None:
    phase = load_config(CONFIG_PATH)["phase5i"]

    assert phase["expected_models"] == 56
    assert phase["selected_electricity_share"] == pytest.approx(0.1)
    assert phase["policy"]["no_reselection_after_heldout"] is True
    assert phase["policy"]["phase5g_failed_baseload_active"] is False
    assert phase["policy"]["legacy_phase5d_ng_bridges_active"] is False
    assert phase["policy"]["residual_ng_active"] is False
    assert phase["policy"]["residual_steam_active"] is False
    assert phase["policy"]["residual_direct_co2_active"] is False
    assert phase["policy"]["baseload_price_responsive"] is False


def test_fresh_heldout_contract_remains_the_exact_unopened_four_period_set() -> None:
    rows, fingerprint = held_out_contract(HELDOUT)

    assert len(rows) == 4
    assert {row["status"] for row in rows} == {"frozen_unopened"}
    assert len(fingerprint) == 64


def test_electricity_background_enters_gross_demand_once_and_other_residuals_are_zero() -> None:
    rows = load_selected_contract(CONTRACT_ROOT / "electricity_only_baseload_contract.csv")
    electricity = electricity_maps(rows)
    inputs = _build_c0_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=1, target_multiplier=1.0)
    model = _build_c0_model(
        inputs, enable_minimal_wag_layer=True,
        development_controller_activation="full",
        site_background_electricity_mwh_h=electricity["C0_current_BF_BOF_reference"],
        site_baseload_ng_mwh_h=0.0, site_residual_steam_t_h=0.0,
        site_residual_direct_co2_t_h=0.0,
    )

    assert value(model.site_background_electricity_mwh[0]) == pytest.approx(15.707829645182194)
    assert value(model.gross_electricity_mwh[0]) == pytest.approx(
        value(model.represented_gross_electricity_before_background_mwh[0])
        + value(model.site_background_electricity_mwh[0])
    )
    assert value(model.site_baseload_ng_mwh[0]) == 0
    assert value(model.residual_steam_15bar_demand_t[0]) == 0
    assert value(model.residual_unmodelled_direct_co2_t[0]) == 0
    assert model.hsm_ng_displaces_fixed_bridge is False


def test_promotion_changes_only_electricity_status_after_gate_pass() -> None:
    rows = load_selected_contract(CONTRACT_ROOT / "electricity_only_baseload_contract.csv")
    promoted = promoted_rows(rows)

    assert all(row["status"] == "heldout_validated_promoted" and row["executable"] == "true" for row in promoted if row["residual_family"] == "electricity")
    assert all(row["status"] == "reporting_only_zero" and row["executable"] == "false" for row in promoted if row["residual_family"] != "electricity")


def test_runner_has_no_share_selection_or_additional_test_period_search() -> None:
    source = (STEEL_ROOT / "steel/s4_4c5p_phase5i_electricity_only_heldout_freeze.py").read_text(encoding="utf-8")

    assert "candidate_percentages" not in source
    assert "select_shared_percentages" not in source
    assert "selected_electricity_share" in source
    assert "requires the frozen 10% electricity share" in source
    assert "held_out_contract(heldout_path)" in source
    assert "reselection_after_heldout\": False" in source
