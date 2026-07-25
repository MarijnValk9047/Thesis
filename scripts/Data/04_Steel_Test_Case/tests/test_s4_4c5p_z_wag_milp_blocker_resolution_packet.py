from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyomo.environ import ConcreteModel, RangeSet, Var, value


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_z_wag_milp_blocker_resolution_packet import (  # noqa: E402
    OUTPUT_DIR,
    REPORT_PATH,
    run_s4_4c5p_z_wag_milp_blocker_resolution_packet,
)
from steel.wag_milp_input_contract import load_governed_wag_factor_maps  # noqa: E402
from steel.s4_4c_unified_physical_modelbuilder import (  # noqa: E402
    _add_c0_minimal_wag_layer,
    load_development_controller_profile,
)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def outputs() -> Path:
    run_s4_4c5p_z_wag_milp_blocker_resolution_packet()
    return OUTPUT_DIR


def test_governed_factor_maps_have_selected_units():
    lhv, factors = load_governed_wag_factor_maps()
    assert lhv == {"BFG": 3.35, "COG": 18.7, "BOFG": 9.58}
    assert factors["BFG"] == pytest.approx(0.89064)
    assert factors["COG"] == pytest.approx(0.15408)
    assert factors["BOFG"] == pytest.approx(0.69084)


def test_builder_applies_cog_only_kgf_and_mode_b_factor_route():
    model = ConcreteModel()
    model.TIME = RangeSet(0, 0)
    for name in (
        "bf6_hot_iron_output", "bf7_hot_iron_output", "coking_plant_1",
        "coking_plant_2", "basic_oxygen_furnace", "bof_crude_steel_output", "sintering_plant", "sinter_output",
    ):
        setattr(model, name, Var(model.TIME))
        getattr(model, name)[0].set_value(1.0)
    inputs = SimpleNamespace(
        bfg_mwh_per_t_hot_iron=1.0,
        cog_mwh_per_t_coke=1.0,
        bofg_mwh_per_t_liquid_steel=1.0,
        kgf_underfiring_mwh_per_t_coke=3.5 / 3.6,
        sinter_cog_mwh_per_t_sinter=0.0,
        boiler_wag_cap_mwh_h=10.0,
        boiler_total_placeholder_mwh_h=0.0,
        eta_boiler_steam=0.9,
    )
    _add_c0_minimal_wag_layer(model, inputs)
    for name in ("bfg_to_boiler", "cog_to_boiler", "ng_to_boiler_mwh", "bfg_flared", "cog_flared", "bofg_flared"):
        getattr(model, name)[0].set_value(0.0)
    assert value(model.bfg_to_kgf1[0]) == pytest.approx(0.0)
    assert value(model.cog_to_kgf1[0]) == pytest.approx(3.5 / 3.6)
    _, factors = load_governed_wag_factor_maps()
    assert value(model.cog_explicit_combustion_co2_t[0]) == pytest.approx(factors["COG"] * 2.0 * (3.5 / 3.6))
    assert value(model.site_background_electricity_mwh[0]) == 0.0
    assert value(model.gross_total_electricity_mwh[0]) == pytest.approx(
        value(model.represented_gross_electricity_before_background_mwh[0])
    )


def test_checkpoint2_legacy_wag_alias_stays_total_while_true_wag_excludes_ng():
    model = ConcreteModel()
    model.TIME = RangeSet(0, 0)
    for name in (
        "bf6_hot_iron_output", "bf7_hot_iron_output", "coking_plant_1",
        "coking_plant_2", "basic_oxygen_furnace", "bof_crude_steel_output", "sintering_plant", "sinter_output",
    ):
        setattr(model, name, Var(model.TIME))
        getattr(model, name)[0].set_value(1.0)
    inputs = SimpleNamespace(
        bfg_mwh_per_t_hot_iron=1.0,
        cog_mwh_per_t_coke=1.0,
        bofg_mwh_per_t_liquid_steel=1.0,
        kgf_underfiring_mwh_per_t_coke=3.5 / 3.6,
        sinter_cog_mwh_per_t_sinter=0.0,
        boiler_wag_cap_mwh_h=10.0,
        boiler_total_placeholder_mwh_h=0.0,
        eta_boiler_steam=0.9,
    )
    interface = {
        "operating_mode": "development",
        "vn25_electricity_efficiency": 0.345,
        "vn25_electric_capacity_mw": 350.0,
        "unit_volume_caps_nm3_h": {"vn25": 1_000_000.0, "ij01": 1_000_000.0},
        "validation_anchors_pj_y": {},
        "ij01_total_fuel_horizon_cap_mwh": 100.0,
        "ij01_total_fuel_deadline_caps_mwh": {1: 100.0},
    }
    _add_c0_minimal_wag_layer(
        model,
        inputs,
        enable_generator_interface=True,
        generator_unit_interface=interface,
        development_profile=load_development_controller_profile("C0_current_BF_BOF_reference"),
        gross_electricity_rule=lambda _m, _t: 100.0,
        site_background_electricity_mwh_h=2.0,
    )
    for carrier in ("bfg", "cog", "bofg"):
        getattr(model, f"{carrier}_to_vn25")[0].set_value(4.0 if carrier == "bfg" else 0.0)
        getattr(model, f"{carrier}_to_ij01")[0].set_value(0.0)
    model.ng_to_vn25_mwh[0].set_value(2.0)

    assert value(model.wag_generator_electricity_mwh[0]) == pytest.approx(0.345 * 4.0)
    assert value(model.ng_generator_electricity_mwh[0]) == pytest.approx(0.345 * 2.0)
    assert value(model.total_generator_electricity_mwh[0]) == pytest.approx(0.345 * 6.0)
    assert value(model.wag_electricity_mwh[0]) == pytest.approx(
        value(model.total_generator_electricity_mwh[0])
    )
    assert value(model.gross_total_electricity_mwh[0]) == 102.0
    assert value(model.gross_grid_import_mwh[0]) == pytest.approx(102.0 - 0.345 * 6.0)
    assert value(model.gross_site_electricity_identity_residual_mwh[0]) == pytest.approx(0.0)


def test_direct_builder_fixes_are_verified(outputs: Path):
    checks = {row["check_id"]: row for row in _rows(outputs / "direct_builder_patch_verification.csv")}
    assert all(row["status"] == "pass" for row in checks.values())
    assert checks["Z_CHECK_001"]["status"] == "pass"
    assert checks["Z_CHECK_002"]["status"] == "pass"


def test_mode_b_keeps_aggregate_process_counters_out(outputs: Path):
    rows = {row["component"]: row for row in _rows(outputs / "mode_b_explicit_fuel_co2_policy.csv")}
    assert rows["aggregate process CO2"]["included_now"] == "no"
    assert rows["residual NG/electricity"]["included_now"] == "no"


def test_unresolved_controller_contracts_remain_visible(outputs: Path):
    resolutions = _rows(outputs / "blocker_resolution_register.csv")
    hot_stove = next(row for row in resolutions if row["area"] == "BF hot-stove controller")
    assert hot_stove["status"] == "blocked_by_development_input_selection"
    gate = json.loads((outputs / "s4_4c5p_z_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["go_no_go"]["bf_hot_stove_activation"] == "NO_GO"
    assert gate["go_no_go"]["whole_site_scope1_or_ETS"] == "NO_GO"
    assert REPORT_PATH.exists()
