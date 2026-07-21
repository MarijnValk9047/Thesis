from __future__ import annotations

from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel import s4_4c5p_ba_c0_fixed_schedule_reporting as c0_reporting
from steel.s4_4c5p_ba_c0_fixed_schedule_reporting import _anchor_rows, _convert, _deadline_rows, _fixed_schedule_coke_diagnostic, _load_config
from steel.s4_4c_unified_physical_modelbuilder import _build_c0_inputs, _build_c0_model, _load_tables, S44B_INPUT_DIR
from pyomo.environ import value


def _utilities() -> list[dict]:
    return [
        {"metric": "final_product_output", "model_value": 2.155398, "unit": "Mt/y"},
        {"metric": "C0_BOF_crude_steel_output", "model_value": 2.155398, "unit": "Mt/y"},
        {"metric": "gross_electricity", "model_value": 3.0, "unit": "TWh/y"},
        {"metric": "internal_WAG_generator_electricity_offset", "model_value": 1.0, "unit": "TWh/y"},
        {"metric": "net_grid_import_after_internal_WAG_offset", "model_value": 2.0, "unit": "TWh/y"},
        {"metric": "named_NG_HSM_PEFA_boiler_energy", "model_value": 0.2, "unit": "PJ_LHV/y"},
        {"metric": "WAG_explicit_combustion_CO2", "model_value": 1.0, "unit": "MtCO2/y"},
    ]


def _carrier(carrier: str) -> dict:
    return {
        "carrier": carrier,
        "generation_MWh_LHV_y": 100.0,
        "process_or_self_use_MWh_LHV_y": 20.0,
        "steam_boiler_MWh_LHV_y": 20.0,
        "generator_MWh_LHV_y": 20.0,
    }


def test_unit_conversion_keeps_electricity_basis_explicit() -> None:
    assert _convert(3.0, "TWh/y", "PJ/y") == pytest.approx(10.8)
    assert _convert(10.8, "PJ/y", "TWh/y") == pytest.approx(3.0)
    assert _convert(1.0, "Mt/y", "PJ/y") is None


def test_c0_dsp_anchor_is_blocked_not_inferred_from_hsm() -> None:
    rows = _anchor_rows(_utilities(), [_carrier("BFG"), _carrier("COG"), _carrier("BOFG")])
    dsp = next(row for row in rows if row["anchor_id"] == "c0_dsp_raw_output_1_5")
    assert dsp["comparability_status"] == "blocked"
    assert dsp["model_numerator_metric"] == "C0_DSP_final_product"


def test_canonical_matrix_uses_explicit_c1_comparability_status(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "anchor_id": "active_final_product_target_6_75",
            "metric": "final_product_output",
            "model_value": "6.75",
            "anchor_value": "6.75",
            "unit": "Mt/y",
            "comparison_basis": "active_target",
            "source_rank": "active_model_target",
            "comparability_status": "comparable",
            "comparability_reason": "Exact active product denominator.",
        },
        {
            "anchor_id": "c1_official_total_site_electricity_17_8pj_missing",
            "metric": "gross_electricity",
            "model_value": "3.58",
            "anchor_value": "4.94",
            "unit": "TWh/y",
            "comparison_basis": "partial_site_boundary",
            "source_rank": "Rank 1",
            "comparability_status": "not_comparable",
            "comparability_reason": "The model boundary is partial.",
        },
    ]
    original_read_csv = c0_reporting._read_csv

    def _read_c1_fixture(path: Path) -> list[dict]:
        return original_read_csv(path) if path == c0_reporting.ANCHOR_REGISTER else rows

    monkeypatch.setattr(c0_reporting, "_read_csv", _read_c1_fixture)

    matrix = c0_reporting._canonical_anchor_matrix([], Path("c1"), "c0_test")
    active = next(row for row in matrix if row["anchor_id"] == "active_steel_target_6_75" and row["configuration"] == "C1_phase1_BF_BOF_plus_DRP_EAF")
    electricity = next(row for row in matrix if row["anchor_id"] == "c1_official_total_site_electricity_17_8pj_missing")
    assert active["comparability_status"] == "comparable"
    assert electricity["comparability_status"] == "not_comparable"


def test_c0_config_rejects_free_binary_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda _self, **_kwargs: """run_id: x\nconfiguration_id: C0_current_BF_BOF_reference\ncanonical_c1_run_id: y\nplanning_horizon_hours: 24\nexecution_block_hours: 24\nquota_per_execution_block_t: 1\nbase_quota_per_execution_block_t: 1\nc0_schedule_policy: quota_driven_binary_capacity\nc0_fixed_schedule:\n  schedule_id: inherited\n  source_status: inherited_static_regression_not_source_backed\n  source_hierarchy: historical\n  source_locator: x\n  caveat: x\n  active_hours_by_process:\n    coking_plant_1: [0]\n    coking_plant_2: [0]\n    sintering_plant: [0]\n    blast_furnace_6: [0]\n    blast_furnace_7: [0]\n    basic_oxygen_furnace: [0]\n    hot_strip_mill: [0]\ndevelopment_controller_activation: full\noutput_policy: diagnostics\nrun_class: x\nlineage_role: x\nretention: x\nsource_coke_chain:\n  dry_coal_t_per_t_coke: 1.285\n  bf_coke_t_per_t_hot_metal: 0.359\nmarket_prices_enabled: false\nenergy_cost_objective_enabled: false\nproduct_revenue_enabled: false\nco2_ets_objective_enabled: false\n""",
    )
    with pytest.raises(ValueError, match="forbids free C0 binary planning"):
        _load_config(Path("invalid.yaml"))


def test_c0_full_controller_reporting_does_not_require_an_eaf_component() -> None:
    inputs = _build_c0_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=1)
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
    )
    assert hasattr(model, "eaf_total_electricity_mwh")


def test_export_precision_does_not_fail_an_exact_quota() -> None:
    rows = [{"hour_index": 0, "final_product_output_t": 9.999998}]
    deadline = _deadline_rows(rows, {1: 10.0})
    assert deadline[0]["status"] == "pass"


def test_source_coke_chain_keeps_coal_and_coke_bases_distinct() -> None:
    inputs = _build_c0_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=1)
    model = _build_c0_model(
        inputs,
        c0_coke_chain_reconciliation={"dry_coal_t_per_t_coke": 1.285, "bf_coke_t_per_t_hot_metal": 0.359},
    )
    model.coking_plant_1[0].set_value(128.5)
    model.coking_plant_2[0].set_value(0.0)
    assert value(model.coke_output[0]) == pytest.approx(100.0)


def test_explicit_c0_schedule_profile_fixes_pyomo_on_variables() -> None:
    schedule = _load_config(
        STEEL_ROOT / "configs" / "steel_c0_fixed_schedule_reporting.yaml"
    )["c0_fixed_schedule"]["active_hours_by_process"]
    inputs = _build_c0_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=24)
    model = _build_c0_model(
        inputs,
        fix_binary_schedule=True,
        c0_fixed_schedule_hours_by_process=schedule,
    )
    assert value(model.coking_plant_1_on[0]) == 1
    assert value(model.coking_plant_1_on[1]) == 0
    assert value(model.coking_plant_2_on[1]) == 1
    assert value(model.blast_furnace_6_on[8]) == 1
    assert value(model.blast_furnace_6_on[9]) == 0


def test_fixed_c0_schedule_has_a_pre_solve_coke_shortfall_after_source_repair() -> None:
    schedule = _load_config(
        STEEL_ROOT / "configs" / "steel_c0_fixed_schedule_reporting.yaml"
    )["c0_fixed_schedule"]
    diagnostic = _fixed_schedule_coke_diagnostic(
        _load_tables(S44B_INPUT_DIR),
        {"dry_coal_t_per_t_coke": 1.285, "bf_coke_t_per_t_hot_metal": 0.359},
        schedule,
    )
    assert diagnostic[0]["status"] == "fail"
    assert diagnostic[0]["daily_coke_gap_t"] < 0.0
    assert diagnostic[0]["schedule_source_status"] == "inherited_static_regression_not_source_backed"
