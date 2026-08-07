from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
STEEL_ROOT = REPO_ROOT / "scripts/Data/04_Steel_Test_Case"
for path in (REPO_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_deterministic_behaviour_anchor_validation import (  # noqa: E402
    STANDARD_FIGURE_PACKAGE_VERSION,
    balance_identity_rows,
    before_after_validation_delta,
    c1_external_materials_audit,
    expected_plant_response_contract,
    load_representative_week_prices,
    load_validation_config,
    paired_counterfactual_validation_rows,
    partial_anchor_rows,
    representative_week_kpis,
    supplemental_annual_operational_rows,
    synthetic_price_profiles,
)
from steel.s4_4c6_deterministic_temporal_repair import (  # noqa: E402
    CALENDAR_CONTRACT_VERSION,
    OBJECTIVE_MODE,
    TEMPORAL_CONTRACT_VERSION,
    load_temporal_repair_config,
)


@pytest.fixture(scope="module")
def validation_config():
    return load_validation_config()


@pytest.fixture(scope="module")
def temporal_config(validation_config):
    return load_temporal_repair_config(
        REPO_ROOT / validation_config["base_temporal_config"]
    )


def test_validation_contract_versions_and_forbidden_scope(validation_config):
    assert validation_config["temporal_contract_version"] == TEMPORAL_CONTRACT_VERSION
    assert validation_config["calendar_contract_version"] == CALENDAR_CONTRACT_VERSION
    assert validation_config["objective_mode"] == OBJECTIVE_MODE
    assert validation_config["forbidden_scope"]["full_four_week_matrix_authorized"] is False
    for key in ("dam", "bids", "mfrr", "stochasticity", "cvar", "s10"):
        assert validation_config["forbidden_scope"][key] is True


def test_standard_figure_package_contract_is_versioned():
    assert STANDARD_FIGURE_PACKAGE_VERSION == (
        "deterministic_plant_behaviour_figures_v3"
    )


def test_gate_defining_solve_quality_contract_is_bounded(validation_config):
    contract = validation_config["behaviour_contract"]
    assert contract["extend_time_limited_gate_cases"] is True
    assert contract["diagnostic_extended_time_limit_seconds"] == 60
    assert contract["continuous_incumbent_polish_time_limit_seconds"] == 15


def test_expected_contract_is_fixed_before_results_and_covers_asset_classes(
    temporal_config,
):
    rows = expected_plant_response_contract(temporal_config)
    assert rows
    assert all(row["fixed_before_results"] is True for row in rows)
    assets = {row["asset"] for row in rows}
    assert {
        "sintering_plant",
        "blast_furnace_6",
        "coking_plant_1",
        "drp_pellet_input",
        "basic_oxygen_furnace",
        "hot_strip_mill",
        "direct_sheet_plant",
        "eaf",
        "vn25",
        "ij01",
        "material_buffers",
        "external_materials",
    } == assets
    assert {row["asset_category"] for row in rows} == {
        "continuous_thermal_process",
        "batch_process",
        "generator_or_utility",
        "buffers_and_inventories",
        "external_material_flow",
    }


def test_synthetic_profiles_change_only_electricity_prices(validation_config):
    profiles = synthetic_price_profiles(validation_config)
    assert set(profiles) == {
        "flat",
        "cheap_to_expensive",
        "expensive_to_cheap",
        "negative_price_block",
        "positive_price_spike",
    }
    assert all(len(values) == 96 for values in profiles.values())
    assert profiles["cheap_to_expensive"][:48] == (20.0,) * 48
    assert profiles["expensive_to_cheap"][:48] == (120.0,) * 48
    assert min(profiles["negative_price_block"]) < 0.0


def test_exact_four_governed_week_definitions_are_reused(validation_config):
    manifest, prices = load_representative_week_prices(validation_config)
    assert [(row["regime_role"], row["start_date"], row["end_date"]) for row in manifest] == [
        ("typical_winter", "2024-12-02", "2024-12-08"),
        ("high_prices", "2025-01-13", "2025-01-19"),
        ("high_volatility", "2024-11-04", "2024-11-10"),
        ("typical_summer", "2025-07-14", "2025-07-20"),
    ]
    assert all(row["counterfactual_not_observed_truth"] is True for row in manifest)
    assert all(row["causal_state_handoff_between_days"] is True for row in manifest)
    assert all(row["same_initial_state_within_week"] is False for row in manifest)
    assert all(len(values) == 672 for values in prices.values())


def test_representative_week_kpis_are_explicit_week_aggregates(
    validation_config, temporal_config
):
    rows = []
    for q in range(4):
        rows.append(
            {
                "experiment_type": "representative_week_counterfactual",
                "case_id": "week_a_day_1",
                "day_index": 1,
                "interval": q,
                "electricity_price_eur_per_mwh": 50.0 + q,
                "sintering_plant_t_h": 160.0 + q,
                "blast_furnace_6_t_h": 120.0 + q,
                "coking_plant_1_t_h": 150.0,
                "drp_pellet_input_t_h": 350.0 + q,
                "bof_liquid_steel_t_h": 100.0,
                "hsm_input_t_h": 100.0,
                "dsp_output_t_h": 50.0,
                "eaf_start": float(q == 0),
                "eaf_tap": float(q == 2),
                "dri_inventory_t": 10.0 + q,
                "coke_inventory_t": 20.0,
                "sinter_inventory_t": 30.0,
                "hot_iron_inventory_t": 40.0,
                "cold_slab_inventory_t": 50.0,
                "vn25_output_mw": 175.0,
                "vn25_wag_mwh_lhv": 40.0,
                "vn25_named_ng_mwh_lhv": 0.0,
                "total_flare_mwh_lhv": 0.0,
                "gross_grid_import_mwh": 100.0,
                "net_grid_import_mwh": 100.0,
                "gross_grid_export_mwh": 0.0,
                "internal_generation_mwh": 43.75,
                "final_product_t": 10.0,
            }
        )
    aggregates = representative_week_kpis(
        rows, temporal_config, validation_config
    )
    assert aggregates
    assert all(row["aggregation_level"] == "week" for row in aggregates)
    assert any(
        row["asset"] == "eaf"
        and row["metric"] == "heat_taps"
        and row["value"] == 1.0
        for row in aggregates
    )
    assert any(
        row["asset"] == "vn25" and row["metric"] == "wag_fuel_total"
        for row in aggregates
    )


def test_partial_anchor_rows_keep_cumulative_prorata_and_annualised_separate():
    rows = partial_anchor_rows(
        [
            {
                "metric_id": "x",
                "metric": "Example",
                "family": "material",
                "source_value": 100.0,
                "source_unit": "t/y",
                "model_annual_equivalent": 90.0,
                "absolute_deviation": -10.0,
                "relative_deviation": -0.1,
                "model_coverage": "represented",
                "boundary_denominator": "example boundary",
                "comparability": "comparable",
                "source_locator": "source",
                "caveat": "",
            }
        ],
        8688,
    )
    row = rows[0]
    assert row["model_cumulative_8688h"] == pytest.approx(90.0 * 8688 / 8760)
    assert row["comparable_period_source_value"] == pytest.approx(100.0 * 8688 / 8760)
    assert row["provisional_annualised_model_diagnostic"] == 90.0
    assert row["validation_status"] == "not_full_year_validated"
    assert row["baseline_comparison_status"] == "not_available_no_comparable_baseline"


def test_external_material_origin_caps_and_base_hbi():
    rows = c1_external_materials_audit(
        {
            "external_scrap_to_bof_t": 500_000.0,
            "external_scrap_to_eaf_t": 700_000.0,
            "internal_scrap_to_bof_t": 399_000.0,
            "internal_scrap_to_eaf_t": 200_000.0,
            "imported_hbi_to_eaf_t": 0.0,
        },
        executed_hours=8688,
    )
    by_id = {row["material_flow"]: row for row in rows}
    assert by_id["HBI"]["status"] == "pass"
    assert by_id["external_scrap_total"]["status"] == "pass"
    assert by_id["internal_scrap_total"]["status"] == "pass"
    assert by_id["site_scrap_total"]["status"] == "pass"
    assert by_id["internal_scrap_to_BOF"]["procurement_cost_treatment"] == "internal_reuse_not_purchased"
    assert by_id["external_scrap_to_BOF"]["procurement_cost_treatment"] == "external_purchase_priced_once"
    assert (
        by_id["external_scrap_to_BOF"]["rolling_budget_carry_status"]
        == "validated_no_reuse_between_replans"
    )


def test_paired_counterfactual_gate_uses_same_state_and_direction():
    state_hash = "abc"
    kpis = []
    for case_id, mean_qh, taps, vn25 in (
        ("synthetic_flat", 50.0, 26.0, 175.0),
        ("synthetic_cheap_to_expensive", 40.0, 26.0, 175.0),
        ("synthetic_expensive_to_cheap", 60.0, 26.0, 175.0),
        ("synthetic_negative_price_block", 45.0, 28.0, 175.0),
        ("synthetic_positive_price_spike", 50.0, 26.0, 300.0),
    ):
        for asset, metric, value in (
            ("eaf", "heat_start_mean_qh", mean_qh),
            ("eaf", "heat_taps", taps),
            ("vn25", "maximum_output", vn25),
        ):
            kpis.append(
                {
                    "experiment_type": "synthetic_paired_counterfactual",
                    "case_id": case_id,
                    "aggregation_level": "day",
                    "asset": asset,
                    "metric": metric,
                    "value": value,
                }
            )
    results = [
        {
            "experiment_type": "synthetic_paired_counterfactual",
            "state_before_sha256": state_hash,
            "solver_status": "optimal",
            "hard_constraint_max_violation": 0.0,
        }
        for _ in range(5)
    ]
    rows = paired_counterfactual_validation_rows(
        kpis,
        results,
        expected_state_sha256=state_hash,
        negative_fixed_count_oracle_rows=[
            {
                "fixed_taps": count,
                "status": "optimal",
                "objective_eur": {26: 102.0, 27: 101.0, 28: 100.0}[count],
            }
            for count in (26, 27, 28)
        ],
    )
    assert len(rows) == 5
    assert all(row["status"] == "pass" for row in rows)


def test_balance_gate_fails_nonzero_residual():
    rows = balance_identity_rows(
        {
            "bfg_balance_residual": 0.0,
            "cog_balance_residual": 0.0,
            "bofg_balance_residual": 0.0,
            "generator_fuel_identity_residual_mwh": 2e-6,
            "gross_site_electricity_identity_residual_mwh": 0.0,
        }
    )
    assert sum(row["status"] == "fail" for row in rows) == 1


def test_balance_gate_covers_material_steam_wag_electricity_and_co2():
    rows = balance_identity_rows(
        {
            "steam_15bar_supply_t": 10.0,
            "steam_15bar_demand_t": 9.0,
            "steam_15bar_spill_t": 1.0,
            "bof_scrap_supply_t": 10.0,
            "external_scrap_to_bof_t": 6.0,
            "internal_scrap_to_bof_t": 4.0,
            "eaf_scrap_supply_t": 10.0,
            "external_scrap_to_eaf_t": 7.0,
            "internal_scrap_to_eaf_t": 3.0,
        }
    )
    identities = {row["identity"] for row in rows}
    assert {
        "steam_15bar_balance_residual_t",
        "bof_scrap_origin_balance_residual_t",
        "eaf_scrap_origin_balance_residual_t",
        "bfg_balance_residual",
        "gross_site_electricity_identity_residual_mwh",
        "co2_double_count_residual_t",
    } <= identities
    assert all(row["status"] == "pass" for row in rows)


def test_supplemental_anchors_cover_hsm_dsp_ore_and_steam():
    rows = supplemental_annual_operational_rows(
        {
            "sintering_plant": 2_000_000.0,
            "hot_strip_mill": 5_000_000.0,
            "dsp_final_product_output": 1_000_000.0,
            "steam_production_mwh": 100.0,
            "steam_15bar_supply_t": 90.0,
            "steam_15bar_demand_t": 90.0,
            "steam_15bar_spill_t": 0.0,
        },
        executed_hours=8688,
        hsm_final_t_per_t_slab=0.95,
    )
    by_id = {row["metric_id"]: row for row in rows}
    assert {
        "represented_sinter_ore_feed",
        "hsm_final_output",
        "dsp_final_output",
        "steam_production",
        "steam_15bar_supply",
        "steam_15bar_demand",
        "steam_15bar_spill",
    } == set(by_id)
    assert by_id["hsm_final_output"]["comparability"] == "not_comparable"


def test_before_after_delta_records_repaired_material_gate(tmp_path):
    (tmp_path / "behaviour_validation_results.csv").write_text(
        "experiment_type,case_id,asset,check_id,observed,status\n"
        "synthetic,c1,drp,direction_reversals,13,fail\n",
        encoding="utf-8",
    )
    (tmp_path / "c1_external_materials_audit.csv").write_text(
        "material_flow,model_cumulative_t,annual_cap_t,status\n"
        "internal_scrap_total,596000,595000,fail\n",
        encoding="utf-8",
    )
    (tmp_path / "balance_identity_gate.csv").write_text(
        "identity,residual,status\n"
        "electricity,0,pass\n",
        encoding="utf-8",
    )
    (tmp_path / "validation_gate.json").write_text(
        '{"judgement":"needs_bounded_fix","behaviour_failure_count":1,'
        '"balance_failure_count":0,"material_failure_count":1,"figure_count":7}',
        encoding="utf-8",
    )
    rows = before_after_validation_delta(
        tmp_path,
        behaviour_rows=[
            {
                "experiment_type": "synthetic",
                "case_id": "c1",
                "asset": "drp",
                "check_id": "direction_reversals",
                "observed": 13,
                "status": "fail",
            }
        ],
        material_rows=[
            {
                "material_flow": "internal_scrap_total",
                "model_cumulative_t": 596000,
                "annual_cap_t": 600000,
                "status": "pass",
            }
        ],
        balance_rows=[{"identity": "electricity", "residual": 0, "status": "pass"}],
        validation_gate={
            "judgement": "needs_bounded_fix",
            "behaviour_failure_count": 1,
            "balance_failure_count": 0,
            "material_failure_count": 0,
            "figure_count": 7,
        },
    )
    material_status = next(
        row
        for row in rows
        if row["artifact"] == "c1_external_materials_audit.csv"
        and row["metric"] == "annual_cap_t"
    )
    assert material_status["before_status"] == "fail"
    assert material_status["after_status"] == "pass"
    assert material_status["change_classification"] == "status_changed"
    gate_delta = next(
        row
        for row in rows
        if row["artifact"] == "validation_gate.json"
        and row["metric"] == "material_failure_count"
    )
    assert gate_delta["delta_after_minus_before"] == -1.0
