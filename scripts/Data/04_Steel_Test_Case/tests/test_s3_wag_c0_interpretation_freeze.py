from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_diagnostic import run_c0_wag_diagnostic  # noqa: E402
from steel.wag_diagnostic_inputs import (  # noqa: E402
    DEFAULT_SELECTED_WAG_INPUT_PATH,
    DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
    load_fixed_activity_profile,
    load_selected_wag_inputs,
    load_wag_demand_coefficients,
)


PROFILE_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_provisional_dev_input"
    / "fixed_profiles"
    / "c0_wag_fixed_profile_24h_dev.csv"
)
VALIDATION_REGISTER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_candidate_review"
    / "s3_c0_wag_scale_and_interpretation_validation_register.csv"
)
FREEZE_REGISTER = VALIDATION_REGISTER.with_name("s3_c0_wag_mechanics_freeze_register.csv")
S2_BUILDER_PATH = TEST_CASE_ROOT / "steel" / "liquid_steel_smoke_builder.py"
WAG_MODULES = [
    TEST_CASE_ROOT / "steel" / "wag_diagnostic.py",
    TEST_CASE_ROOT / "steel" / "wag_diagnostic_inputs.py",
    TEST_CASE_ROOT / "steel" / "wag_diagnostic_runner.py",
    TEST_CASE_ROOT / "steel" / "wag_fixed_profile_builder.py",
]


def _central() -> dict[str, object]:
    return run_c0_wag_diagnostic(
        selected_inputs=load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH),
        demand_coefficients=load_wag_demand_coefficients(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH),
        profile_rows=load_fixed_activity_profile(PROFILE_PATH),
    )


def test_scale_validation_blocks_plant_level_interpretation_but_keeps_per_tonne_metrics():
    result = _central()
    scale = result["scale_consistency"]
    normalised = result["normalised_metrics"]
    assert result["production_scale_metadata"]["annualised_liquid_steel_t"] == pytest.approx(2974997.178)
    assert scale["model_to_reference_steel_scale_status"] == "not_assessable"
    assert scale["model_to_reference_coking_scale_ratio"] == pytest.approx(0.460132896864)
    assert scale["scale_classification"] == "scale_mismatch_material"
    assert scale["absolute_site_energy_scale_consistent"] is False
    assert scale["plant_level_grid_import_interpretation_ready"] is False
    assert scale["plant_level_power_offset_interpretation_ready"] is False
    assert normalised["wag_generation"]["total_wag_gj_per_t_liquid_steel"] == pytest.approx(7.04131806)
    assert normalised["electricity"]["potential_net_import_offset_mwh_per_t_liquid_steel"] == pytest.approx(0.484063945993)


def test_interpretation_labels_warnings_and_readiness_flags_are_separate():
    result = _central()
    flags = result["interpretation_readiness_flags"]
    assert "plant_accounting_ready" not in result["interpretation_class"]
    assert "potential_import_offset_upper_bound" in result["interpretation_class"]
    assert flags["wag_generation_mechanics_ready"] is True
    assert flags["allocation_balance_mechanics_ready"] is True
    assert flags["point_of_oxidation_emissions_ready"] is True
    assert flags["absolute_site_energy_scale_consistent"] is False
    assert flags["downstream_heat_boundary_complete"] is False
    assert flags["complete_direct_emissions_ledger_ready"] is False
    assert flags["plant_level_cost_accounting_ready"] is False
    assert flags["s3_cost_integration_ready"] is False
    assert flags["thesis_validation_ready"] is False
    warnings = set(result["warnings"])
    assert "natural_gas_substitution_zero_because_represented_wag_supply_exceeds_minimum_known_heat_demand" in warnings
    assert "flare_spill_near_zero_because_residual_wag_is_routed_to_potential_import_offset_proxy" in warnings
    assert "complete_site_emissions_unavailable_partial_wag_ledger_only" in warnings


def test_freeze_register_freezes_mechanics_not_plant_truth_or_c1():
    validation = pd.read_csv(VALIDATION_REGISTER, dtype=str, keep_default_na=False)
    freeze = pd.read_csv(FREEZE_REGISTER, dtype=str, keep_default_na=False)
    assert list(validation.columns) == [
        "validation_id",
        "validation_family",
        "metric",
        "value",
        "unit",
        "reference_value",
        "reference_unit",
        "reference_source_ids",
        "boundary_match",
        "scale_match",
        "validation_status",
        "interpretation_allowed",
        "freeze_eligible",
        "thesis_usability",
        "warning",
        "notes",
    ]
    assert validation["thesis_usability"].str.lower().eq("false").all()
    assert freeze["thesis_usability"].str.lower().eq("false").all()
    assert "frozen_development_mechanics" in set(freeze["freeze_status"])
    assert "validated_not_frozen_as_plant_truth" in set(freeze["freeze_status"])
    assert "blocked_scale_mismatch" in set(freeze["freeze_status"])
    c1 = freeze.loc[freeze["component"].str.contains("C1", regex=False)].iloc[0]
    assert c1["freeze_status"] == "blocked_incomplete_boundary"
    assert "No C1 mechanics" in c1["frozen_interpretation"]


def test_regression_no_market_fields_and_s2_builder_unchanged_by_diagnostic():
    before = S2_BUILDER_PATH.read_bytes()
    result = _central()
    after = S2_BUILDER_PATH.read_bytes()
    assert before == after
    flattened_keys = " ".join(str(key).lower() for key in result.keys())
    for forbidden in ("revenue", "da_price", "settlement", "gross_ets_cost_eur"):
        assert forbidden not in flattened_keys
    assert result["generation"]["BFG"]["volume_Nm3"] / result["production_fulfilment"]["bf_hot_metal_total_t"] == pytest.approx(1600.0)
    assert result["generation"]["BOFG_LD_gas"]["volume_Nm3"] / result["production_fulfilment"]["bof_liquid_steel_total_t"] == pytest.approx(75.0)
    assert result["max_balance_residual_gj"] <= 1e-6


def test_wag_modules_do_not_add_market_or_cost_logic():
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in WAG_MODULES)
    for forbidden in ("da_price", "settlement", "export_revenue", "profit", "gross_ets_cost_eur"):
        assert forbidden not in combined
