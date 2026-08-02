from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest
from pyomo.environ import value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    _c0_real_anchor_energy_recovery_interfaces,
)
from steel.s4_4c5p_phase5g_final_deterministic_freeze import (
    CONFIG_PATH,
    Phase5GFreezeError,
    candidate_percentages,
    load_config,
    load_overlap_contract,
    planned_outage_availability_context,
    select_shared_percentages,
    selected_contract_rows,
    validate_overlap_against_source,
)
from steel.s4_4c5p_phase5e_source_backed_anchor_closure import load_source_contract
from steel.s4_4c_component_ontology import load_future_cost_boundary_contract
from steel.s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _build_c0_model,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
)


CONTRACT_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_phase5g_final_freeze_contract"
)
SOURCE_CONTRACT = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_phase5e_source_backed_anchor_contract/source_backed_annual_service_contract.csv"
)
GENERATOR = {
    "enabled": True,
    "electricity_efficiency": 0.345,
    "total_fuel_volume_cap_nm3_h": 900_000.0,
    "natural_gas_lhv_mj_per_nm3": 35.8,
    "electrical_capacity_mw": 770.0,
    "export_allowed": False,
}
C1_ENERGY = {
    "drp_ng_gj_per_t_dri": 9.9,
    "drp_electricity_mwh_per_t_dri": 0.3 / 3.6,
    "eaf_arc_electricity_mwh_per_t_liquid_steel": 1.52 / 3.6,
    "eaf_ng_gj_per_t_liquid_steel": 0.05,
    "natural_gas_lhv_mj_per_nm3": 35.8,
}


def _selection_inputs():
    anchors = {
        (configuration, carrier): 100.0
        for configuration in ("C0", "C1")
        for carrier in ("electricity", "natural_gas")
    }
    explicit = dict(anchors)
    pools = dict(anchors)
    for key in explicit:
        explicit[key] = 82.0
        pools[key] = 40.0
    return explicit, pools, anchors


def test_phase5g_config_freezes_grid_periods_scope_and_hsm_policy() -> None:
    config = load_config(CONFIG_PATH)["phase5g"]

    assert candidate_percentages() == pytest.approx(tuple(index / 10 for index in range(1, 10)))
    assert len(config["validation_periods"]) == 4
    assert len(config["held_out_periods"]) == 4
    assert config["expected_total_models"] == 168
    assert config["policy"]["legacy_c0_fixed_bridge_active"] is False
    assert config["policy"]["held_out_reselection_allowed"] is False
    assert config["hsm_source_mix_policy_by_configuration"]["C0_current_BF_BOF_reference"]["block_hours"] == 24
    assert config["hsm_source_mix_policy_by_configuration"]["C1_phase1_BF_BOF_plus_DRP_EAF"]["ng_volume_fraction"] == pytest.approx(0.80)


def test_overlap_contract_maps_each_source_component_once_and_excludes_boundaries() -> None:
    overlap = load_overlap_contract(CONTRACT_ROOT / "source_service_overlap_contract.csv")
    source = load_source_contract(SOURCE_CONTRACT)
    validate_overlap_against_source(overlap, source)

    boundary = [row for row in overlap if row["overlap_classification"] == "boundary_remainder_ineligible"]
    assert {(row["configuration"], row["source_value_pj_y"]) for row in boundary} == {
        ("C0", 2.3), ("C1", 1.6)
    }
    assert all(row["baseload_eligible"] is False for row in boundary)
    fields = [
        (row["configuration"], row["carrier"], field)
        for row in overlap for field in row["dynamic_overlap_fields"]
    ]
    assert len(fields) == len(set(fields))


def test_selection_is_shared_by_carrier_and_ties_choose_lower_percentage() -> None:
    explicit, pools, anchors = _selection_inputs()
    selected, score = select_shared_percentages(explicit, pools, anchors)

    assert selected == {"electricity": pytest.approx(0.4), "natural_gas": pytest.approx(0.4)}
    assert all(not row["eligible_after_both_configuration_improvement_gate"] for row in score if row["candidate_share"] in {0.0, 1.0})
    assert sum(bool(row["selected"]) for row in score) == 2


def test_selection_fails_closed_when_one_configuration_cannot_improve() -> None:
    explicit, pools, anchors = _selection_inputs()
    explicit[("C1", "electricity")] = 120.0

    with pytest.raises(Phase5GFreezeError, match="improves both C0 and C1"):
        select_shared_percentages(explicit, pools, anchors)


def test_selected_hourly_conversion_is_nonnegative_and_closes_annual_identity() -> None:
    _, pools, _ = _selection_inputs()
    rows = selected_contract_rows({"electricity": 0.4, "natural_gas": 0.6}, pools)

    assert len(rows) == 4
    for row in rows:
        assert row["hourly_baseload_mwh_h"] >= 0.0
        assert row["hourly_baseload_mwh_h"] * 8760 * 3.6e-6 == pytest.approx(
            row["annual_baseload_pj_y"]
        )
    assert {row["selected_share"] for row in rows if row["carrier"] == "electricity"} == {0.4}
    assert {row["selected_share"] for row in rows if row["carrier"] == "natural_gas"} == {0.6}


def test_failed_canonical_selection_is_not_promoted_and_held_out_is_gate_ordered() -> None:
    with (CONTRACT_ROOT / "selected_site_baseload_contract.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {row["selection_status"] for row in rows} == {
        "selected_validation_failed_not_promoted"
    }

    module_text = (
        STEEL_ROOT / "steel/s4_4c5p_phase5g_final_deterministic_freeze.py"
    ).read_text(encoding="utf-8")
    failed_gate = module_text.index("if not selected_validation_pass:")
    held_out_open = module_text.index(
        "held_out_artifacts, held_out_status = _stage_artifacts("
    )
    assert failed_gate < held_out_open


def test_phase5g_can_retain_generator_without_legacy_bridge_only_by_explicit_gate() -> None:
    resolved, bridge = _c0_real_anchor_energy_recovery_interfaces(
        {
            "c0_aggregate_generator_technical_interface": GENERATOR,
            "c0_full_site_energy_bridge": None,
            "phase5g_generator_without_legacy_bridge": True,
        }
    )
    assert resolved is not None
    assert bridge is None
    with pytest.raises(Exception, match="only allowed by the Phase-5G gate"):
        _c0_real_anchor_energy_recovery_interfaces(
            {"c0_aggregate_generator_technical_interface": GENERATOR}
        )


def test_ng_baseload_is_constant_additive_and_not_hsm_bridge_displaced() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=1, target_multiplier=1.0
    )
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        development_controller_activation="full",
        site_baseload_ng_mwh_h=10.0,
    )

    assert value(model.site_baseload_ng_mwh[0]) == pytest.approx(10.0)
    assert value(model.full_site_energy_bridge_named_ng_mwh[0]) == pytest.approx(0.0)
    assert model.hsm_ng_displaces_fixed_bridge is False
    cost_rows = [
        row for row in load_future_cost_boundary_contract()
        if row["flow_id"] in {
            "C0_EL_SITE_BASELOAD", "C1_EL_SITE_BASELOAD",
            "C0_NG_SITE_BASELOAD", "C1_NG_SITE_BASELOAD",
        }
    ]
    assert len(cost_rows) == 4
    ng_rows = [row for row in cost_rows if row["carrier"] == "NG"]
    electricity_rows = [row for row in cost_rows if row["carrier"] == "electricity"]
    assert all(row["model_component_attribute"] == "site_baseload_ng_mwh" for row in ng_rows)
    assert all(float(row["parameter_value"]) == pytest.approx(7.0e6 / 3.6 / 8760.0) for row in ng_rows)
    assert all(row["source_status"] == "accepted_development" for row in ng_rows)
    assert all(row["residual_status"] == "not_residual" for row in ng_rows)
    assert all(row["objective_enabled"] == "true" and row["accounting_enabled"] == "true" for row in ng_rows)
    assert all("c5_phase5k_final_user_authorized_boundary_contract" in row["source_locator"] for row in ng_rows)
    assert all(row["objective_enabled"] == "false" and row["accounting_enabled"] == "false" for row in electricity_rows)
    assert len({row["double_count_group"] for row in cost_rows}) == 4


def test_dri_heracless_reporting_split_and_electricity_identity_do_not_change_total() -> None:
    inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=1,
        include_retained_bf_bof=True,
    )
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        development_controller_activation="full_electricity_boundary",
        c1_energy_boundary=C1_ENERGY,
    )
    model.drp_pellet_input[0].set_value(100.0)
    output = value(model.drp_dri_output[0])

    assert value(model.drp_reduction_ng_mwh[0]) * 3.6 / output == pytest.approx(8.1)
    assert value(model.drp_furnace_ng_mwh[0]) * 3.6 / output == pytest.approx(1.8)
    assert value(model.drp_named_ng_mwh[0]) * 3.6 / output == pytest.approx(9.9)
    assert value(model.drp_heracless_ng_split_residual_mwh[0]) == pytest.approx(0.0)
    assert value(model.drp_electricity_mwh[0]) * 3.6 / output == pytest.approx(0.3)


def test_heracless_outage_ranges_remain_annual_validation_context() -> None:
    availability = planned_outage_availability_context()

    assert availability["DRI"] == pytest.approx((0.9096, 0.9425), abs=5e-5)
    assert availability["EAF"] == pytest.approx((0.9142, 0.9525), abs=5e-5)
    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    assert "vn25_ij01_operating_time_context: [0.85, 0.15]" in config_text
    assert "ng_volume_fraction: 0.85" not in config_text
    assert "cog_volume_fraction: 0.15" not in config_text
