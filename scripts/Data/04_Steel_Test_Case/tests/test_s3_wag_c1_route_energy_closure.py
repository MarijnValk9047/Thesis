from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_diagnostic_inputs import load_fixed_activity_profile  # noqa: E402
from steel.wag_diagnostic import run_c1_component_energy_diagnostic  # noqa: E402
from steel.wag_diagnostic_inputs import load_selected_wag_inputs  # noqa: E402
from steel.wag_fixed_profile_builder import (  # noqa: E402
    C1_PROFILE_FILENAMES,
    C1_ROUTE_SCENARIOS,
    build_c1_same_output_profile_frame,
    stable_frame_hash,
    summarise_c1_wag_generation_only,
)


S3_REVIEW_ROOT = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3" / "s3_candidate_review"
)
S3_DEV_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3" / "s3_provisional_dev_input"
SOURCE_EVIDENCE_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "source_evidence"

ROUTE_POLICY = S3_REVIEW_ROOT / "s3_c1_route_share_policy_register.csv"
EMISSIONS_CALIBRATION = S3_REVIEW_ROOT / "s3_c1_route_share_emissions_calibration_register.csv"
C1_ENERGY_INPUTS = S3_DEV_ROOT / "s3_c1_route_energy_inputs.csv"
RUNTIME_CLOSURE = S3_REVIEW_ROOT / "s3_wag_runtime_input_closure_register.csv"
IDENTIFIABILITY = S3_REVIEW_ROOT / "s3_c1_route_share_identifiability_register.csv"
READINESS = S3_REVIEW_ROOT / "s3_c1_scenario_wag_readiness_register.csv"
C0_PROFILE = S3_DEV_ROOT / "fixed_profiles" / "c0_wag_fixed_profile_24h_dev.csv"
FIXED_PROFILE_DIR = S3_DEV_ROOT / "fixed_profiles"
SOURCE_CARDS = SOURCE_EVIDENCE_ROOT / "steel_source_card_register.csv"
CANDIDATE_EVIDENCE = SOURCE_EVIDENCE_ROOT / "steel_candidate_parameter_evidence_register.csv"
TIER_B_REVIEW = S3_REVIEW_ROOT / "s3_c1_drp_eaf_tier_b_evidence_review.csv"
EVIDENCE_TIER_VOCABULARY = S3_REVIEW_ROOT / "s3_evidence_use_tier_vocabulary.csv"
MODEL_INPUT_USE_STATUS_VOCABULARY = S3_REVIEW_ROOT / "s3_model_input_use_status_vocabulary.csv"
THESIS_ASSUMPTION_ACCEPTANCE_POLICY = S3_REVIEW_ROOT / "s3_thesis_assumption_acceptance_policy.csv"
MATERIAL_PARAMETER_SENSITIVITY_MANDATE = S3_REVIEW_ROOT / "s3_material_parameter_sensitivity_mandate.csv"


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_c1_route_policy_registers_three_user_selected_same_output_scenarios():
    policy = _csv(ROUTE_POLICY)
    c0 = _csv(C0_PROFILE)
    c0_liquid_steel = c0.loc[c0["s2_activity_type"].eq("bof_liquid_steel_activity"), "activity_value"].astype(float).sum()

    assert set(policy["scenario_id"]) == set(C1_ROUTE_SCENARIOS)
    assert policy["route_share_basis"].eq("user_selected_development_scenario_within_s2_feasible_envelope").all()
    assert policy["selected_for_profile"].str.lower().eq("true").all()
    assert policy["development_only"].str.lower().eq("true").all()
    assert policy["thesis_usability"].str.lower().eq("false").all()
    for _, row in policy.iterrows():
        assert abs(float(row["bf_bof_share"]) + float(row["drp_eaf_share"]) - 1.0) <= 1e-9
        assert float(row["total_output_value"]) == c0_liquid_steel


def test_c1_route_scenarios_lie_inside_or_near_s2_feasible_interval():
    policy = _csv(ROUTE_POLICY)
    identifiability = _csv(IDENTIFIABILITY).iloc[0]
    lower = float(identifiability["min_bf_bof_share"])
    upper = float(identifiability["max_bf_bof_share"])
    tolerance = 0.003

    for _, row in policy.iterrows():
        share = float(row["bf_bof_share"])
        assert lower - tolerance <= share <= upper + tolerance
        assert row["inside_s2_feasible_interval"] in {"inside", "inside_with_rounding_tolerance"}
    assert "s2_feasible_interval_midpoint" not in set(policy["route_share_basis"])


def test_c1_fixed_profiles_exist_and_use_same_output_without_run_folder_sources():
    c0 = _csv(C0_PROFILE)
    c0_total = c0.loc[c0["s2_activity_type"].eq("bof_liquid_steel_activity"), "activity_value"].astype(float).sum()

    for scenario_id, filename in C1_PROFILE_FILENAMES.items():
        path = FIXED_PROFILE_DIR / filename
        assert path.exists()
        rows = load_fixed_activity_profile(path)
        frame = _csv(path)
        assert len(rows) == 720
        assert set(frame["scenario_id"]) == {scenario_id}
        assert set(frame["profile_extraction_method"]) == {"s3_same_output_route_share_wrapper_not_s2_solver_split"}
        assert frame["thesis_usability"].str.lower().eq("false").all()
        assert not frame["source_artifact_path"].str.contains("/runs/|\\\\runs\\\\", regex=True).any()
        total = frame.loc[frame["s2_activity_type"].eq("total_liquid_steel_output"), "activity_value"].astype(float).sum()
        bf_bof = frame.loc[frame["s2_activity_type"].eq("bf_bof_route_liquid_steel_output"), "activity_value"].astype(float).sum()
        drp_eaf = frame.loc[frame["s2_activity_type"].eq("drp_eaf_route_liquid_steel_output"), "activity_value"].astype(float).sum()
        assert total == c0_total
        assert abs((bf_bof + drp_eaf) - total) <= 1e-6


def test_c1_wag_drivers_decline_with_higher_drp_eaf_share_and_no_flat_c0_credit():
    totals = {}
    for scenario_id, filename in C1_PROFILE_FILENAMES.items():
        frame = _csv(FIXED_PROFILE_DIR / filename)
        totals[scenario_id] = {
            "bfg": frame.loc[frame["s2_activity_type"].eq("bfg_generation_driver_hot_metal"), "activity_value"].astype(float).sum(),
            "bofg": frame.loc[frame["s2_activity_type"].eq("bofg_generation_driver_liquid_steel"), "activity_value"].astype(float).sum(),
            "cog": frame.loc[frame["s2_activity_type"].eq("cog_generation_driver_dry_coal"), "activity_value"].astype(float).sum(),
            "drp": frame.loc[frame["s2_activity_type"].eq("drp_eaf_route_liquid_steel_output"), "activity_value"].astype(float).sum(),
        }

    assert totals["c1_high_drp_eaf"]["drp"] > totals["c1_central"]["drp"] > totals["c1_low_drp_eaf"]["drp"]
    for key in ("bfg", "bofg", "cog"):
        assert totals["c1_high_drp_eaf"][key] < totals["c1_central"][key] < totals["c1_low_drp_eaf"][key]


def test_c1_wag_generation_only_validation_is_available_but_not_full_diagnostic():
    readiness = _csv(READINESS)
    assert set(readiness["scenario_id"]) == set(C1_ROUTE_SCENARIOS)
    assert readiness["route_profile_ready"].str.lower().eq("true").all()
    assert readiness["bfg_generation_ready"].str.lower().eq("true").all()
    assert readiness["bofg_generation_ready"].str.lower().eq("true").all()
    assert readiness["cog_generation_ready"].str.lower().eq("true").all()
    assert readiness["diagnostic_allowed"].eq("component_energy_boundary_diagnostic").all()
    assert readiness["full_c1_diagnostic_ready"].str.lower().eq("false").all()

    profile = _csv(FIXED_PROFILE_DIR / C1_PROFILE_FILENAMES["c1_central"])
    summary = summarise_c1_wag_generation_only(profile)
    assert summary["validation_class"] == "wag_generation_only"
    assert float(summary["bfg_energy_gj"]) > 0.0
    assert float(summary["cog_energy_gj"]) > 0.0
    assert float(summary["bofg_energy_gj"]) > 0.0


def test_selected_drp_eaf_energy_inputs_enable_component_diagnostic_without_full_plant_readiness():
    energy = _csv(C1_ENERGY_INPUTS)
    selected = energy.loc[energy["accepted_for_dev_use"].str.lower().eq("true")]
    assert {"ng_drp_natural_gas_consumption", "ng_drp_electricity_consumption", "eaf_electricity_consumption"}.issubset(
        set(selected["parameter_name"])
    )
    assert selected["eligible_for_s3_0c_loader"].str.lower().eq("true").all()
    assert selected["thesis_usability"].str.lower().eq("false").all()
    assert selected.loc[selected["parameter_name"].eq("ng_drp_natural_gas_consumption"), "unit"].iloc[0] == "m3_NG/t_pellets"
    assert selected.loc[selected["parameter_name"].eq("eaf_electricity_consumption"), "unit"].iloc[0] == "MWh/t_DRI"
    assert "scenario_scope" in energy.columns

    readiness = _csv(READINESS)
    assert readiness["drp_natural_gas_ready"].str.lower().eq("true").all()
    assert readiness["drp_electricity_ready"].str.lower().eq("true").all()
    assert readiness["eaf_electricity_ready"].str.lower().eq("true").all()
    assert readiness["full_c1_diagnostic_ready"].str.lower().eq("false").all()
    assert readiness["blocking_reason"].str.contains("Full plant diagnostic blocked").all()


def test_athanasiadis_source_card_has_human_verified_tier_b_table_locators():
    source_cards = _csv(SOURCE_CARDS)
    row = source_cards.loc[source_cards["source_card_id"].eq("STEEL-SC-0021")].iloc[0]

    assert row["source_review_status"] == "human_verified_tier_b_locator_complete_for_eaf_and_ng_drp_tables"
    assert row["locator_complete"].lower() == "true"
    assert row["eligible_for_candidate_evidence"].lower() == "true"
    assert row["eligible_for_dev_input_review"].lower() == "true"
    assert row["thesis_usability"].lower() == "false"
    assert "Table 1 p.56" in row["page_table_or_section"]
    assert "Table 2 p.57" in row["page_table_or_section"]
    assert "Athanasiadis" in row["source_title"] or "Athanasiadis" in row["author_or_organisation"]


def test_tier_b_candidate_evidence_rows_are_caveated_and_selectable():
    evidence = _csv(CANDIDATE_EVIDENCE)
    review = _csv(TIER_B_REVIEW)
    required = {
        "eaf_electricity_consumption",
        "eaf_dri_to_crude_steel_efficiency",
        "eaf_scrap_consumption",
        "ng_drp_natural_gas_consumption",
        "ng_drp_electricity_consumption",
        "ng_drp_pellets_to_dri_efficiency",
        "ng_drp_direct_co2_factor",
    }
    rows = evidence.loc[evidence["parameter_name"].isin(required)]
    assert required.issubset(set(rows["parameter_name"]))
    assert rows["source_card_ids"].eq("STEEL-SC-0021").all()
    assert rows["eligible_for_thesis_input"].str.lower().eq("false").all()
    assert rows["thesis_usability"].str.lower().eq("false").all()
    assert rows["source_locator"].str.contains("p.56|p.57", regex=True).all()

    review_rows = review.loc[review["parameter_name"].isin(required)]
    assert required.issubset(set(review_rows["parameter_name"]))
    assert review_rows["evidence_tier"].eq("B_public_secondary_literature_derived").all()
    assert review_rows["thesis_model_assumption_eligible"].str.lower().isin({"true", "false"}).all()
    assert review_rows["tata_exact_claim_allowed"].str.lower().eq("false").all()
    assert review_rows["thesis_validation_claim_eligible"].str.lower().eq("false").all()


def test_new_evidence_policy_allows_tier_b_only_with_complete_locator_and_sensitivity_review():
    tiers = _csv(EVIDENCE_TIER_VOCABULARY)
    statuses = _csv(MODEL_INPUT_USE_STATUS_VOCABULARY)
    acceptance = _csv(THESIS_ASSUMPTION_ACCEPTANCE_POLICY)
    sensitivity = _csv(MATERIAL_PARAMETER_SENSITIVITY_MANDATE)

    tier_b = tiers.loc[tiers["evidence_tier"].eq("B")].iloc[0]
    assert tier_b["tier_name"] == "public_secondary_literature_derived"
    assert tier_b["development_model_eligible"].lower() == "true"
    assert tier_b["thesis_model_assumption_eligible"].lower() == "true"
    assert tier_b["complete_locator_required"].lower() == "true"
    assert tier_b["tata_exact_claim_allowed"].lower() == "false"
    assert tier_b["thesis_validation_claim_eligible"].lower() == "false"

    thesis_assumption = statuses.loc[statuses["model_use_status"].eq("thesis_model_assumption")].iloc[0]
    assert thesis_assumption["executable_in_final_thesis_model"].lower() == "true"
    assert thesis_assumption["usable_for_validation_claim"].lower() == "false"

    tier_b_policy = acceptance.loc[
        acceptance["evidence_tier"].eq("B")
        & acceptance["model_use_status"].eq("thesis_model_assumption")
    ].iloc[0]
    assert "missing_locator" in tier_b_policy["blocked_if"]
    assert "source_card_ids;source_locator;unit;activity_basis;limitations;main_caveat" == tier_b_policy[
        "required_fields"
    ]

    material_families = set(sensitivity["parameter_family"])
    assert {"DRP natural-gas consumption", "DRP electricity consumption", "EAF electricity consumption"}.issubset(
        material_families
    )


def test_selected_c1_rows_are_user_scenarios_not_source_backed_energy_coefficients():
    energy = _csv(C1_ENERGY_INPUTS)
    selected = energy.loc[energy["accepted_for_dev_use"].str.lower().eq("true")]
    assert {"route_share", "coking_proxy", "energy_demand", "conversion_basis", "derived_route_output_conversion"}.issubset(
        set(selected["input_family"])
    )
    assert selected["thesis_usability"].str.lower().eq("false").all()
    assert selected.loc[
        selected["parameter_name"].eq("ng_drp_natural_gas_consumption"), "selection_method"
    ].iloc[0] == "tier_b_thesis_model_assumption_human_verified_locator"
    assert selected["source_card_ids"].str.contains("STEEL-SC-0021|^$", regex=True).all()


def test_derived_c1_route_output_conversions_are_explicit():
    energy = _csv(C1_ENERGY_INPUTS)
    values = {row["parameter_name"]: float(row["selected_value"]) for _, row in energy.iterrows() if row["input_family"] == "derived_route_output_conversion"}
    assert abs(values["dri_required_per_t_steel"] - (1 / 0.95)) <= 1e-9
    assert abs(values["pellets_required_per_t_steel"] - ((1 / 0.95) / 0.74)) <= 1e-9
    assert abs(values["eaf_electricity_per_t_steel"] - ((1 / 0.95) * 0.5)) <= 1e-9
    assert abs(values["drp_electricity_per_t_steel"] - (((1 / 0.95) / 0.74) * 0.1)) <= 1e-9
    assert abs(values["drp_natural_gas_per_t_steel"] - (((1 / 0.95) / 0.74) * 195)) <= 1e-9
    assert abs(values["scrap_per_t_steel"] - ((1 / 0.95) * 0.2)) <= 1e-9
    assert abs(values["drp_direct_co2_proxy_per_t_steel"] - (((1 / 0.95) / 0.74) * 0.5)) <= 1e-9
    assert energy.loc[
        energy["parameter_name"].eq("dri_required_per_t_steel"), "limitations"
    ].iloc[0].startswith("Derived value; liquid-steel route output is treated as crude-steel proxy")


def test_c1_component_profiles_and_diagnostics_are_component_boundary_only():
    selected = load_selected_wag_inputs()
    for scenario_id, filename in C1_PROFILE_FILENAMES.items():
        rows = load_fixed_activity_profile(FIXED_PROFILE_DIR / filename)
        frame = _csv(FIXED_PROFILE_DIR / filename)
        assert set(frame["scenario_id"]) == {scenario_id}
        assert {"drp_natural_gas_demand", "drp_electricity_demand", "eaf_electricity_demand", "component_electricity_demand_before_wag_offset"}.issubset(
            set(frame["s2_activity_type"])
        )
        drp = frame.loc[frame["s2_activity_type"].eq("drp_electricity_demand"), "activity_value"].astype(float).sum()
        eaf = frame.loc[frame["s2_activity_type"].eq("eaf_electricity_demand"), "activity_value"].astype(float).sum()
        component = frame.loc[
            frame["s2_activity_type"].eq("component_electricity_demand_before_wag_offset"), "activity_value"
        ].astype(float).sum()
        assert abs((drp + eaf) - component) <= 1e-6
        diagnostic = run_c1_component_energy_diagnostic(selected_inputs=selected, profile_rows=rows)
        assert diagnostic["diagnostic_classification"] == "component_energy_boundary_diagnostic"
        assert diagnostic["full_plant_boundary_ready"] is False
        assert diagnostic["gross_ets_cost_eligible"] is False
        assert diagnostic["component_energy"]["potential_net_import_offset_mwh"] <= component + 1e-6
        assert diagnostic["component_energy"]["residual_component_grid_import_mwh"] >= 0.0


def test_c1_emissions_calibration_is_plausibility_only():
    calibration = _csv(EMISSIONS_CALIBRATION)
    assert set(calibration["scenario_id"]) == set(C1_ROUTE_SCENARIOS)
    assert calibration["target_match_status"].eq("plausibility_context_only").all()
    assert calibration["proxy_completeness"].eq("partial_context_only").all()
    assert calibration["thesis_usability"].str.lower().eq("false").all()
    assert calibration["c1_emissions_proxy"].eq("not_calculated").all()


def test_c1_profiles_are_deterministic_for_same_policy_inputs():
    rebuilt = build_c1_same_output_profile_frame("c1_central")
    stored = _csv(FIXED_PROFILE_DIR / C1_PROFILE_FILENAMES["c1_central"])
    assert stable_frame_hash(rebuilt.drop(columns=["profile_content_hash"])) == stored["profile_content_hash"].iloc[0]


def test_no_forbidden_market_or_revenue_logic_in_c1_surfaces():
    surfaces = [
        ROUTE_POLICY,
        EMISSIONS_CALIBRATION,
        C1_ENERGY_INPUTS,
        READINESS,
        FIXED_PROFILE_DIR / C1_PROFILE_FILENAMES["c1_high_drp_eaf"],
        FIXED_PROFILE_DIR / C1_PROFILE_FILENAMES["c1_central"],
        FIXED_PROFILE_DIR / C1_PROFILE_FILENAMES["c1_low_drp_eaf"],
    ]
    forbidden = ("da_price", "settlement", "revenue", "route_optimisation", "gross_ets_cost")
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in surfaces)
    for term in forbidden:
        assert term not in text
