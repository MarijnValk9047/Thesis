from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ap_component_ontology_route_reconciliation import _scenario_overrides
from steel.s4_4c_component_ontology import continuous_must_run_activities, load_builder_component_ontology, load_route_policy_scenarios
from steel.s4_4c_unified_physical_modelbuilder import _build_c1_inputs, _build_c1_model, _load_tables


def test_existing_s44b2_registry_is_reused_by_c5_adapter() -> None:
    rows = load_builder_component_ontology()
    assert rows
    assert any(row["asset_id"] == "blast_furnace_6" for row in rows)


def test_c1_continuous_classes_are_source_scoped() -> None:
    activities = continuous_must_run_activities("C1_phase1_BF_BOF_plus_DRP_EAF")
    assert activities == ("coking_plant_1", "sintering_plant", "blast_furnace_6", "drp_pellet_input")


def test_route_scenario_keeps_default_free_case_unconstrained() -> None:
    scenario = next(row for row in load_route_policy_scenarios() if row["scenario_id"] == "free_route_reference")
    overrides = _scenario_overrides(scenario, horizon_hours=168)
    assert "c1_liquid_steel_route_band" not in overrides
    assert "eaf_material_balance" not in overrides


def test_named_scrap_scenario_normalises_annual_cap_to_horizon() -> None:
    scenario = next(row for row in load_route_policy_scenarios() if row["scenario_id"] == "central_source_ratio_named_scrap")
    overrides = _scenario_overrides(scenario, horizon_hours=168)
    assert overrides["eaf_material_balance"]["scrap_supply_cap_t"] == 1_000_000.0 * 168 / 8760


def test_builder_adds_route_band_and_continuous_on_fixes() -> None:
    tables = _load_tables()
    inputs = _build_c1_inputs(tables, horizon_hours_override=2, include_retained_bf_bof=True)
    model = _build_c1_model(
        inputs,
        enable_c1_retained_bf_bof_route=True,
        c1_retained_route_policy="quota_driven_topology",
        c1_liquid_steel_route_band={"bof_lower_share": 0.45, "bof_upper_share": 0.55},
        continuous_must_run_activities=continuous_must_run_activities("C1_phase1_BF_BOF_plus_DRP_EAF"),
    )
    assert hasattr(model, "bof_liquid_steel_lower_share")
    assert model.blast_furnace_6_on[0].fixed
    assert model.drp_on[1].fixed
