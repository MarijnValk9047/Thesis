from __future__ import annotations

import inspect
import csv
import io
import json
from pathlib import Path
import sys

import pytest
from pyomo.environ import value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    ClosedLoopFeasibilityError,
    HOURS_PER_YEAR,
    PJ_PER_MWH,
    _c0_real_anchor_energy_recovery_interfaces,
    _config,
    _deterministic_cost_policy,
    _annual_model_metrics,
    _annual_physical_boundary_ledger,
    _generator_electricity_reporting_split,
)
from steel.s4_4c_component_ontology import (
    load_external_supply_costs,
    load_future_cost_boundary_contract,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _build_c0_model,
    _costed_c0_ng_reporting_value,
    _load_tables,
    run_s44c_unified_physical_regression,
)


GENERATOR_CONFIG = {
    "enabled": True,
    "electricity_efficiency": 0.345,
    "total_fuel_volume_cap_nm3_h": 900_000.0,
    "natural_gas_lhv_mj_per_nm3": 35.8,
    "electrical_capacity_mw": 770.0,
    "export_allowed": False,
}
BRIDGE_CONFIG = {
    "enabled": True,
    "inferred_low_case_full_site_ng_floor_pj_y": 8.005,
    "already_represented_fixed_ng_pj_y": 0.0,
    "already_represented_fixed_ng_component_id": "none_identified",
    "already_represented_fixed_ng_derivation": "explicit_zero_no_overlap_identified",
    "flexible_other_site_heat_service_envelope_pj_y": 3.07,
    "normal_case_flexible_ng_validation_reference_pj_y": 1.65,
}


def _resolved_interfaces():
    return _c0_real_anchor_energy_recovery_interfaces(
        {
            "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
            "c0_full_site_energy_bridge": BRIDGE_CONFIG,
        }
    )


def test_real_anchor_interfaces_are_opt_in_and_threaded_to_public_builder() -> None:
    assert _c0_real_anchor_energy_recovery_interfaces({}) == (None, None)
    parameters = inspect.signature(run_s44c_unified_physical_regression).parameters
    assert "c0_aggregate_generator_technical_interface" in parameters
    assert "c0_full_site_energy_bridge" in parameters


def test_real_anchor_interface_converts_only_approved_annual_terms() -> None:
    generator, bridge = _resolved_interfaces()
    assert generator["electricity_efficiency"] == pytest.approx(0.345)
    assert generator["total_fuel_volume_cap_nm3_h"] == pytest.approx(900_000.0)
    assert generator["electrical_capacity_mw"] == pytest.approx(770.0)
    assert bridge["fixed_full_site_ng_component_mwh_h"] == pytest.approx(
        8.005 / (HOURS_PER_YEAR * PJ_PER_MWH)
    )
    assert bridge["flexible_other_site_heat_service_envelope_mwh_h"] == pytest.approx(
        3.07 / (HOURS_PER_YEAR * PJ_PER_MWH)
    )
    assert bridge["normal_case_flexible_ng_validation_reference_mwh_h"] == pytest.approx(
        1.65 / (HOURS_PER_YEAR * PJ_PER_MWH)
    )
    assert bridge["flexible_ng_allocation_policy"] == "dispatch_endogenous"


def test_normal_case_source_emulation_fixes_only_existing_flexible_heat_split() -> None:
    generator, bridge = _c0_real_anchor_energy_recovery_interfaces(
        {
            "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
            "c0_full_site_energy_bridge": {
                **BRIDGE_CONFIG,
                "flexible_ng_allocation_policy": "normal_case_reference_exact_hourly",
            },
        }
    )
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=1, target_multiplier=1.0
    )
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        aggregate_generator_technical_interface=generator,
        full_site_energy_bridge=bridge,
    )
    ng_reference = 1.65 / (HOURS_PER_YEAR * PJ_PER_MWH)
    total_service = 3.07 / (HOURS_PER_YEAR * PJ_PER_MWH)
    model.flexible_other_site_heat_ng_mwh[0].set_value(ng_reference)
    model.bfg_to_flexible_other_site_heat[0].set_value(total_service - ng_reference)
    model.cog_to_flexible_other_site_heat[0].set_value(0.0)
    model.bofg_to_flexible_other_site_heat[0].set_value(0.0)

    assert model.flexible_ng_allocation_policy == "normal_case_reference_exact_hourly"
    assert value(model.flexible_other_site_heat_ng_source_emulation[0].body) == pytest.approx(
        ng_reference
    )
    assert value(model.flexible_other_site_heat_ng_source_emulation[0].lower) == pytest.approx(
        ng_reference
    )
    assert value(model.flexible_other_site_heat_balance[0].body) == pytest.approx(total_service)
    assert value(model.flexible_other_site_heat_balance[0].upper) == pytest.approx(total_service)


def test_real_anchor_interface_rejects_export_and_fixed_ng_double_count() -> None:
    with pytest.raises(ClosedLoopFeasibilityError, match="export"):
        _c0_real_anchor_energy_recovery_interfaces(
            {
                "c0_aggregate_generator_technical_interface": {
                    **GENERATOR_CONFIG,
                    "export_allowed": True,
                },
                "c0_full_site_energy_bridge": BRIDGE_CONFIG,
            }
        )
    with pytest.raises(ClosedLoopFeasibilityError, match="below"):
        _c0_real_anchor_energy_recovery_interfaces(
            {
                "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
                "c0_full_site_energy_bridge": {
                    **BRIDGE_CONFIG,
                    "already_represented_fixed_ng_pj_y": 8.0,
                },
            }
        )
    with pytest.raises(ClosedLoopFeasibilityError, match="component id"):
        _c0_real_anchor_energy_recovery_interfaces(
            {
                "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
                "c0_full_site_energy_bridge": {
                    **BRIDGE_CONFIG,
                    "already_represented_fixed_ng_component_id": "",
                },
            }
        )
    with pytest.raises(ClosedLoopFeasibilityError, match="non-negative"):
        _c0_real_anchor_energy_recovery_interfaces(
            {
                "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
                "c0_full_site_energy_bridge": {
                    **BRIDGE_CONFIG,
                    "already_represented_fixed_ng_pj_y": -0.1,
                },
            }
        )


def test_c0_aggregate_generator_and_heat_bridge_preserve_carrier_identities() -> None:
    generator, bridge = _resolved_interfaces()
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=1, target_multiplier=1.0
    )
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        aggregate_generator_technical_interface=generator,
        full_site_energy_bridge=bridge,
    )
    model.bfg_to_vattenfall[0].set_value(100.0)
    model.cog_to_vattenfall[0].set_value(0.0)
    model.bofg_to_vattenfall[0].set_value(0.0)
    model.ng_to_vattenfall_mwh[0].set_value(200.0)
    assert value(model.wag_generator_electricity_mwh[0]) == pytest.approx(34.5)
    assert value(model.ng_generator_electricity_mwh[0]) == pytest.approx(69.0)
    assert value(model.total_generator_electricity_mwh[0]) == pytest.approx(103.5)
    assert value(model.generator_total_fuel_mwh[0]) == pytest.approx(300.0)
    assert model.vattenfall_total_volume_cap[0].upper == pytest.approx(900_000.0)
    assert model.aggregate_generator_electrical_capacity[0].upper == pytest.approx(770.0)
    assert value(model.no_export_from_total_generation[0].upper) == pytest.approx(0.0)
    assert value(model.no_export_from_total_generation[0].body) <= 0.0
    assert value(model.gross_site_electricity_identity_residual_mwh[0]) == pytest.approx(
        0.0
    )

    demand = bridge["flexible_other_site_heat_service_envelope_mwh_h"]
    model.bfg_to_flexible_other_site_heat[0].set_value(10.0)
    model.cog_to_flexible_other_site_heat[0].set_value(0.0)
    model.bofg_to_flexible_other_site_heat[0].set_value(0.0)
    model.flexible_other_site_heat_ng_mwh[0].set_value(demand - 10.0)
    assert value(model.flexible_other_site_heat_balance[0].body) == pytest.approx(demand)
    assert value(model.flexible_other_site_heat_balance[0].upper) == pytest.approx(demand)
    assert value(model.normal_case_flexible_ng_validation_reference_mwh[0]) == pytest.approx(
        1.65 / (HOURS_PER_YEAR * PJ_PER_MWH)
    )
    assert value(model.full_site_energy_bridge_named_ng_mwh[0]) == pytest.approx(
        bridge["fixed_full_site_ng_component_mwh_h"] + demand - 10.0
    )


def test_default_c0_path_retains_zero_bridge_and_no_aggregate_ng() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=1, target_multiplier=1.0
    )
    model = _build_c0_model(
        inputs, enable_minimal_wag_layer=True, enable_internal_wag_power=True
    )
    assert model.aggregate_generator_technical_interface_active is False
    assert model.full_site_energy_bridge_active is False
    assert value(model.ng_to_vattenfall_mwh[0]) == pytest.approx(0.0)
    assert value(model.full_site_energy_bridge_named_ng_mwh[0]) == pytest.approx(0.0)


def test_generator_reporting_alias_keeps_wag_ng_and_total_separate() -> None:
    split = _generator_electricity_reporting_split(
        [
            {
                "WAG_generator_electricity_mwh": 34.5,
                "NG_generator_electricity_mwh": 69.0,
                "total_generator_electricity_mwh": 103.5,
            }
        ]
    )
    assert split["WAG_generator_electricity_mwh"] == pytest.approx(34.5)
    assert split["NG_generator_electricity_mwh"] == pytest.approx(69.0)
    assert split["generator_internal_electricity_total_mwh"] == pytest.approx(103.5)
    assert split["sum_identity_residual_mwh"] == pytest.approx(0.0)


def test_wag_anchor_and_shared_named_ng_subtotal_use_nonoverlapping_fields() -> None:
    row = {
        "configuration_id": "C0_current_BF_BOF_reference",
        "WAG_generator_electricity_mwh": 10.0,
        "NG_generator_electricity_mwh": 5.0,
        "total_generator_electricity_mwh": 15.0,
        "generator_electricity_mwh": 15.0,
        "wag_electricity_mwh": 15.0,
        "generator_named_ng_mwh": 2.0,
        "full_site_fixed_ng_component_mwh": 3.0,
        "flexible_other_site_heat_ng_mwh": 4.0,
        "aggregate_generator_technical_interface_active": 1.0,
    }
    metrics, _ = _annual_model_metrics([row])
    c0 = metrics["C0_current_BF_BOF_reference"]
    assert c0["wag_power_twh_y"] == pytest.approx(10.0 * HOURS_PER_YEAR / 1e6)
    assert c0["ng_generator_electricity_twh_y"] == pytest.approx(
        5.0 * HOURS_PER_YEAR / 1e6
    )
    assert c0["represented_ng_pj_y"] == pytest.approx(
        (2.0 + 3.0 + 4.0) * HOURS_PER_YEAR * PJ_PER_MWH
    )
    ledger = _annual_physical_boundary_ledger([row])
    keyed = {(item["ledger_family"], item["component"]): item for item in ledger}
    assert keyed[("named_NG", "represented_named_NG")]["annual_value"] == pytest.approx(
        9.0 * HOURS_PER_YEAR
    )
    ng_co2 = 9.0 * HOURS_PER_YEAR * 3.6 * 56.1 / 1000.0
    assert keyed[("Mode_B_CO2", "represented_named_NG_combustion")][
        "annual_value"
    ] == pytest.approx(ng_co2)


def test_new_c0_named_ng_cost_rows_are_enabled_exactly_once() -> None:
    rows = load_future_cost_boundary_contract()
    expected = {
        "generator_named_ng_mwh",
        "full_site_fixed_ng_component_mwh",
        "flexible_other_site_heat_ng_mwh",
    }
    policy = _deterministic_cost_policy(
        {
            "execution_mode": "fixed_reference_cost",
            "price_series_id": "flat_central_reference_v1",
            "c0_aggregate_generator_technical_interface": GENERATOR_CONFIG,
            "c0_full_site_energy_bridge": BRIDGE_CONFIG,
        },
        rows,
        horizon_hours=1,
        execution_block_hours=1,
    )
    priced = [
        row
        for row in policy["flows"]
        if row["physical_quantity_attribute"] in expected
    ]
    assert {row["physical_quantity_attribute"] for row in priced} == expected
    assert len(priced) == 3
    assert {row["price_id"] for row in priced} == {"natural_gas_ttf_proxy"}
    contract_rows = [
        row for row in rows if row["physical_quantity_attribute"] in expected
    ]
    assert len({row["double_count_group"] for row in contract_rows}) == 3
    baseline_policy = _deterministic_cost_policy(
        {
            "execution_mode": "fixed_reference_cost",
            "price_series_id": "flat_central_reference_v1",
        },
        rows,
        horizon_hours=1,
        execution_block_hours=1,
    )
    assert not expected.intersection(
        row["physical_quantity_attribute"] for row in baseline_policy["flows"]
    )


def test_costed_c0_fixed_ng_survives_hourly_csv_precision_for_120h_ledger() -> None:
    exact_hourly_mwh = 8.005 / (HOURS_PER_YEAR * PJ_PER_MWH)
    reported_hourly_mwh = _costed_c0_ng_reporting_value(exact_hourly_mwh)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["full_site_fixed_ng_component_mwh"]
    )
    writer.writeheader()
    writer.writerow(
        {"full_site_fixed_ng_component_mwh": reported_hourly_mwh}
    )
    buffer.seek(0)
    reloaded_hourly_mwh = float(
        next(csv.DictReader(buffer))["full_site_fixed_ng_component_mwh"]
    )
    ng_price = next(
        float(row["value"])
        for row in load_external_supply_costs()
        if row["price_id"] == "natural_gas_ttf_proxy"
        and row["scenario_id"] == "development_central"
    )
    reporting_residual_eur = abs(
        (reloaded_hourly_mwh - exact_hourly_mwh) * 120.0 * ng_price
    )

    assert reported_hourly_mwh == pytest.approx(253.836884830036, abs=1e-12)
    assert reporting_residual_eur <= 1e-4
    assert (
        abs((round(exact_hourly_mwh, 6) - exact_hourly_mwh) * 120.0 * ng_price)
        > 1e-4
    )
    assert _costed_c0_ng_reporting_value(0.0) == 0.0


def test_real_first_contract_config_and_checkpoint_snapshot_are_machine_readable() -> None:
    repo = STEEL_ROOT.parents[2]
    contract_root = (
        repo
        / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract"
    )
    with (contract_root / "user_authorized_emulation_anchor_overlay.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        anchors = {row["overlay_id"]: row for row in csv.DictReader(handle)}
    assert anchors["uae_c0_wag_generator_electricity"]["value_central"] == "2.528"
    assert anchors["uae_c0_wag_generator_electricity"]["implementation_ledger"] == (
        "WAG_generator_electricity_mwh"
    )
    for overlay_id in (
        "uae_c0_gross_site_electricity",
        "uae_c0_wag_generator_electricity",
        "uae_c0_figure91_ng_band",
    ):
        assert anchors[overlay_id]["target_role"] == "primary_real_anchor"
        assert anchors[overlay_id]["calibration_stage"] == "boundary_freeze"
        assert anchors[overlay_id]["arithmetic_caveat"]
    assert anchors["real_anchor_c0_flexible_heat_service_envelope"][
        "value_central"
    ] == "3.07"
    assert anchors["real_anchor_c0_normal_case_flexible_ng_reference"][
        "target_role"
    ] == "validation_reference"

    with (contract_root / "user_authorized_emulation_parameter_overlay.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        parameters = {row["parameter_id"]: row for row in csv.DictReader(handle)}
    assert parameters["uae_c0_generator_efficiency"]["baseline_central"] == "0.345"
    assert parameters["real_anchor_c0_generator_mixed_volume_envelope"][
        "baseline_central"
    ] == "900000"
    assert parameters["real_anchor_c0_generator_electrical_capacity"][
        "baseline_central"
    ] == "770"

    config = _config(
        repo
        / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_real_anchor_energy_recovery.yaml"
    )
    assert config["execution_authorized"] is True
    assert config["rolling_production_progress_state_enabled"] is True
    assert config["production_envelope_tolerance_fraction"] == pytest.approx(0.005)
    assert config["c0_full_site_energy_bridge"][
        "already_represented_fixed_ng_derivation"
    ].startswith("explicit_zero")
    state = json.loads(
        (
            repo
            / "data/03_Optimisation/runs/steel_c5_real_anchor_energy_recovery_v1_20260722/checkpoint_state.json"
        ).read_text(encoding="utf-8")
    )
    assert state["status"] == "complete"
    assert state["solver_invoked"] is True
    assert state["completed_checkpoints"] == [1, 2, 3, 4, 5, 6]
    assert state["model_count"] == state["model_count_expected"] == 672
    assert state["recovery_bg25_promoted"] is False
    assert state["source_driven_baseline_status"] == "central_retained"
