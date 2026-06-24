from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from steel.wag_diagnostic import run_c0_wag_diagnostic, run_c1_component_energy_diagnostic
    from steel.wag_diagnostic_inputs import (
        DEFAULT_SELECTED_WAG_INPUT_PATH,
        DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
        load_fixed_activity_profile,
        load_selected_wag_inputs,
        load_wag_demand_coefficients,
    )
    from steel.wag_fixed_profile_builder import C1_PROFILE_FILENAMES, C1_ROUTE_SCENARIOS
else:
    from .wag_diagnostic import run_c0_wag_diagnostic, run_c1_component_energy_diagnostic
    from .wag_diagnostic_inputs import (
        DEFAULT_SELECTED_WAG_INPUT_PATH,
        DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
        load_fixed_activity_profile,
        load_selected_wag_inputs,
        load_wag_demand_coefficients,
    )
    from .wag_fixed_profile_builder import C1_PROFILE_FILENAMES, C1_ROUTE_SCENARIOS


REPO_ROOT = Path(__file__).resolve().parents[4]
S3_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3"
S3_REVIEW_ROOT = S3_ROOT / "s3_candidate_review"
S3_DEV_ROOT = S3_ROOT / "s3_provisional_dev_input"
FIXED_PROFILE_ROOT = S3_DEV_ROOT / "fixed_profiles"

C0_CONFIGURATION_ID = "C0_current_BF_BOF_reference"
C1_CONFIGURATION_ID = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"
C0_SCENARIO_ID = "c0_reference"
C0_PROFILE_PATH = FIXED_PROFILE_ROOT / "c0_wag_fixed_profile_24h_dev.csv"

SITE_STATIC_ACCOUNTING_BOUNDARY_REGISTER = S3_REVIEW_ROOT / "s3_site_static_accounting_boundary_register.csv"
STATIC_ACCOUNTING_PARAMETER_STATUS_REGISTER = S3_REVIEW_ROOT / "s3_static_accounting_parameter_status_register.csv"
ELECTRICITY_BOUNDARY_SENSITIVITY_REGISTER = S3_REVIEW_ROOT / "s3_electricity_boundary_sensitivity_register.csv"
SITE_STATIC_ACCOUNTING_RESULT_REGISTER = S3_REVIEW_ROOT / "s3_site_static_accounting_result_register.csv"
EMISSIONS_BOUNDARY_POLICY_REGISTER = S3_REVIEW_ROOT / "s3_emissions_boundary_policy_register.csv"
EMISSIONS_COMPONENT_STATUS_REGISTER = S3_REVIEW_ROOT / "s3_emissions_component_status_register.csv"

GJ_PER_MWH = 3.6
WAG_CARRIER_KEYS = ("BFG", "COG", "BOFG_LD_gas")
DOWNSTREAM_DRIVER_TYPES = {
    "secondary_metallurgy_output_proxy",
    "continuous_casting_liquid_steel_input",
    "continuous_casting_slab_output_proxy",
    "slab_handling_transfer_proxy",
    "reheating_or_hot_charge_throughput_proxy",
    "hot_strip_mill_throughput_proxy",
    "finished_product_boundary_proxy",
    "oxygen_demand_auxiliary_driver",
    "residual_downstream_auxiliary_boundary_driver",
}


@dataclass(frozen=True)
class ElectricityBoundaryCase:
    boundary_case_id: str
    selected_annual_mwh: float
    description: str

    @property
    def average_mw(self) -> float:
        return self.selected_annual_mwh / 8760.0

    @property
    def mwh_24h(self) -> float:
        return self.selected_annual_mwh / 365.0


ELECTRICITY_BOUNDARY_CASES = (
    ElectricityBoundaryCase("low_proxy_site_electricity_boundary", 2_250_000.0, "low Tier D user-selected proxy"),
    ElectricityBoundaryCase("central_proxy_site_electricity_boundary", 3_000_000.0, "central Tier D user-selected proxy"),
    ElectricityBoundaryCase("high_proxy_site_electricity_boundary", 3_750_000.0, "high Tier D user-selected proxy"),
)


@dataclass(frozen=True)
class StaticEmissionsPolicy:
    emissions_policy_id: str
    policy_name: str
    wag_generation_emissions_counted: bool
    wag_use_emissions_counted: bool
    drp_direct_co2_proxy_counted: bool
    drp_ng_combustion_co2_counted: bool
    electricity_scope2_counted: bool
    downstream_emissions_counted: bool
    complete_direct_emissions_ready: bool
    ets_ready: bool


CURRENT_EMISSIONS_POLICY = StaticEmissionsPolicy(
    emissions_policy_id="current_partial_direct_proxy_policy",
    policy_name="Current partial direct-emissions proxy with DRP direct CO2 non-double-counting",
    wag_generation_emissions_counted=False,
    wag_use_emissions_counted=True,
    drp_direct_co2_proxy_counted=True,
    drp_ng_combustion_co2_counted=False,
    electricity_scope2_counted=False,
    downstream_emissions_counted=False,
    complete_direct_emissions_ready=False,
    ets_ready=False,
)


def emissions_double_counting_warning(policy: StaticEmissionsPolicy) -> str:
    warnings: list[str] = []
    if policy.wag_generation_emissions_counted and policy.wag_use_emissions_counted:
        warnings.append("wag_generation_and_use_both_counted")
    if policy.drp_direct_co2_proxy_counted and policy.drp_ng_combustion_co2_counted:
        warnings.append("drp_direct_proxy_and_ng_combustion_both_counted")
    return ";".join(warnings)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _sum_profile(profile: pd.DataFrame, activity_type: str) -> float:
    values = profile.loc[profile["s2_activity_type"].eq(activity_type), "activity_value"]
    if values.empty:
        return 0.0
    return float(values.astype(float).sum())


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _nested_value(payload: dict[str, Any], *keys: str) -> float:
    current: Any = payload
    for key in keys:
        current = current[key]
    return float(current)


def _wag_generation_gj(diagnostic: dict[str, Any], carrier: str) -> float:
    return _nested_value(diagnostic, "generation", carrier, "energy_GJ")


def _wag_co2_t(diagnostic: dict[str, Any], carrier: str) -> float:
    return float(diagnostic["wag_co2_tonnes_by_carrier"].get(carrier, 0.0))


def _uncapped_power_potential_mwh(diagnostic: dict[str, Any], power_efficiency: float) -> float:
    use_by_sink = diagnostic.get("use_by_sink_gj", {})
    power_gj = sum(float(value) for value in use_by_sink.get("power_interface", {}).values())
    unused_gj = sum(float(value) for value in use_by_sink.get("flare_spill_unused", {}).values())
    return (power_gj + unused_gj) * power_efficiency / GJ_PER_MWH


def _power_efficiency() -> float:
    selected = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    matches = [
        row
        for row in selected.values()
        if row.parameter_name == "integrated_mill_offgas_power_efficiency_range"
    ]
    if len(matches) != 1 or matches[0].selected_number is None:
        raise ValueError("Expected one selected WAG power-conversion efficiency.")
    return float(matches[0].selected_number) / 100.0


def build_boundary_register() -> pd.DataFrame:
    rows = [
        {
            "accounting_boundary_id": "S30E_BOUNDARY_C0_STATIC",
            "configuration_id": C0_CONFIGURATION_ID,
            "scenario_id": C0_SCENARIO_ID,
            "included_physical_components": "BF/BOF WAG generation drivers; coking proxy; minimum known coking heat sink; downstream accounting drivers; proxy site electricity boundary sensitivity",
            "included_energy_carriers": "BFG; COG; BOFG/LDG; proxy grid electricity boundary",
            "included_emissions_components": "WAG oxidation emissions by carrier and sink",
            "included_economic_components": "formula hooks only for electricity import, natural gas, WAG avoided import value, CO2/ETS proxy, tariff/network costs",
            "excluded_components": "complete downstream electricity; ASU electricity coefficient; heat/steam closure; product revenue; DA prices; bidding; settlement; gross ETS result; route optimisation",
            "diagnostic_level": "minimum_known_heat_sink_c0_static_accounting",
            "plant_level_claim_allowed": "false",
            "cost_result_allowed": "false",
            "da_market_result_allowed": "false",
            "complete_direct_emissions_ready": "false",
            "complete_site_energy_ready": "false",
            "limitations": "Static proxy ledger only; not Tata-exact, not cost-ready, not DA-ready.",
            "notes": "Uses current governed C0 fixed profile snapshot; no S2 rebuild.",
        }
    ]
    for scenario_id in C1_ROUTE_SCENARIOS:
        rows.append(
            {
                "accounting_boundary_id": f"S30E_BOUNDARY_{scenario_id.upper()}_STATIC",
                "configuration_id": C1_CONFIGURATION_ID,
                "scenario_id": scenario_id,
                "included_physical_components": "retained BF/BOF WAG generation drivers; retained coking proxy; DRP natural gas; DRP/EAF electricity; downstream accounting drivers; proxy site electricity boundary sensitivity",
                "included_energy_carriers": "BFG; COG; BOFG/LDG; natural gas; component electricity; proxy grid electricity boundary",
                "included_emissions_components": "WAG oxidation emissions by carrier; DRP direct CO2 proxy",
                "included_economic_components": "formula hooks only for electricity import, natural gas, WAG avoided import value, CO2/ETS proxy, tariff/network costs",
                "excluded_components": "complete downstream electricity; ASU electricity coefficient; heat/steam closure; natural-gas combustion add-on without non-double-counting policy; electricity scope-2; product revenue; DA prices; bidding; settlement; gross ETS result; route optimisation",
                "diagnostic_level": "component_energy_boundary_static_accounting",
                "plant_level_claim_allowed": "false",
                "cost_result_allowed": "false",
                "da_market_result_allowed": "false",
                "complete_direct_emissions_ready": "false",
                "complete_site_energy_ready": "false",
                "limitations": "Static proxy ledger only; same-output C1 scenario, not Tata-exact, not cost-ready, not DA-ready.",
                "notes": "Uses current governed C1 fixed profile snapshot; no S2 rebuild and no route-share change.",
            }
        )
    return pd.DataFrame(rows)


def build_electricity_boundary_register() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "boundary_case_id": case.boundary_case_id,
                "annual_mwh": _round(case.selected_annual_mwh, 3),
                "average_mw": _round(case.average_mw, 6),
                "mwh_24h": _round(case.mwh_24h, 6),
                "formula": "average_mw = annual_mwh / 8760; mwh_24h = annual_mwh / 365",
                "source_or_policy_basis": "Tier D user-selected scenario policy",
                "sensitivity_required": "true",
                "not_tata_exact": "true",
                "validation_claim_eligible": "false",
                "cost_da_ready": "false",
                "plant_level_claim_allowed": "false",
                "limitations": "Proxy boundary only; not observed site import, not hourly truth, not settlement input.",
                "notes": case.description,
            }
            for case in ELECTRICITY_BOUNDARY_CASES
        ]
    )


def build_emissions_boundary_policy_register() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "emissions_policy_id": CURRENT_EMISSIONS_POLICY.emissions_policy_id,
                "policy_name": CURRENT_EMISSIONS_POLICY.policy_name,
                "configuration_scope": "C0 and C1 static accounting snapshots",
                "included_emissions_components": "WAG oxidation/use by carrier; C1 DRP direct CO2 proxy",
                "excluded_emissions_components": "WAG generation-only emissions; separate DRP natural-gas combustion CO2; electricity scope-2; downstream/reheating emissions; retained BF/BOF non-WAG process emissions; gross ETS cost",
                "double_counting_rule": "Count WAG carbon at point of oxidation/use, not at generation; count DRP direct CO2 proxy or explicit NG combustion under an alternative policy, never both.",
                "wag_generation_counted": str(CURRENT_EMISSIONS_POLICY.wag_generation_emissions_counted).lower(),
                "wag_use_counted": str(CURRENT_EMISSIONS_POLICY.wag_use_emissions_counted).lower(),
                "drp_direct_co2_proxy_counted": str(CURRENT_EMISSIONS_POLICY.drp_direct_co2_proxy_counted).lower(),
                "drp_ng_combustion_co2_counted": str(CURRENT_EMISSIONS_POLICY.drp_ng_combustion_co2_counted).lower(),
                "electricity_scope2_counted": str(CURRENT_EMISSIONS_POLICY.electricity_scope2_counted).lower(),
                "downstream_emissions_counted": str(CURRENT_EMISSIONS_POLICY.downstream_emissions_counted).lower(),
                "complete_direct_emissions_ready": str(CURRENT_EMISSIONS_POLICY.complete_direct_emissions_ready).lower(),
                "ets_ready": str(CURRENT_EMISSIONS_POLICY.ets_ready).lower(),
                "model_use_status": "selected_current_policy",
                "evidence_tier": "D user-selected accounting policy plus Tier B/C/D component assumptions",
                "sensitivity_required": "true",
                "limitations": "Partial direct-emissions proxy only; not complete site emissions, not ETS-ready, not Tata-exact.",
                "notes": "Natural-gas volume remains in physical/future fuel-cost accounting, but no separate DRP NG combustion CO2 is added while the direct CO2 proxy is active.",
            },
            {
                "emissions_policy_id": "future_explicit_ng_combustion_policy",
                "policy_name": "Future explicit natural-gas combustion decomposition",
                "configuration_scope": "C1 or later configurations only if reviewed factors and process boundary are selected",
                "included_emissions_components": "WAG oxidation/use by carrier; explicit natural-gas combustion CO2 where applicable",
                "excluded_emissions_components": "DRP direct CO2 proxy while explicit NG combustion policy is active; electricity scope-2 unless factor selected; downstream emissions unless coefficients selected",
                "double_counting_rule": "This policy would replace the DRP direct proxy for the DRP fuel component; it cannot run simultaneously with drp_direct_proxy_policy.",
                "wag_generation_counted": "false",
                "wag_use_counted": "true",
                "drp_direct_co2_proxy_counted": "false",
                "drp_ng_combustion_co2_counted": "true_if_selected_later",
                "electricity_scope2_counted": "false_until_factor_selected",
                "downstream_emissions_counted": "false_until_coefficients_selected",
                "complete_direct_emissions_ready": "false",
                "ets_ready": "false",
                "model_use_status": "future_not_selected",
                "evidence_tier": "policy not selected",
                "sensitivity_required": "true",
                "limitations": "Not active; requires explicit NG factor, process split, and complete non-double-counting boundary.",
                "notes": "Reserved to avoid adding generic NG combustion CO2 on top of the selected DRP direct proxy.",
            },
            {
                "emissions_policy_id": "future_complete_direct_emissions_policy",
                "policy_name": "Future complete direct-emissions ledger policy",
                "configuration_scope": "future plant-level S3/S4 boundary",
                "included_emissions_components": "WAG use; DRP direct or decomposed NG policy; retained BF/BOF non-WAG process emissions; coking non-WAG emissions; downstream/reheating direct emissions; residual site emissions",
                "excluded_emissions_components": "scope-2 unless separately selected; free allocation; monetary ETS result until CO2 price and policy are selected",
                "double_counting_rule": "Every carbon source must be assigned to one counted driver or explicitly excluded with rationale; no hidden zeros.",
                "wag_generation_counted": "false",
                "wag_use_counted": "true",
                "drp_direct_co2_proxy_counted": "policy_choice_required",
                "drp_ng_combustion_co2_counted": "policy_choice_required",
                "electricity_scope2_counted": "false_until_factor_selected",
                "downstream_emissions_counted": "true_if_coefficients_selected_later",
                "complete_direct_emissions_ready": "false",
                "ets_ready": "false",
                "model_use_status": "future_target_not_selected",
                "evidence_tier": "policy not selected",
                "sensitivity_required": "true",
                "limitations": "Target architecture only; missing material direct-emissions components block readiness.",
                "notes": "Needed before gross ETS cost or plant-level direct-emissions claims.",
            },
        ]
    )


def _emissions_component_row(
    component_id: str,
    configuration_scope: str,
    emissions_component: str,
    driver: str,
    factor_or_proxy: str,
    unit: str,
    counted_in_current_policy: bool,
    counting_method: str,
    source_or_policy_basis: str,
    evidence_tier: str,
    model_use_status: str,
    double_counting_risk: str,
    blocks_complete_direct_emissions: bool,
    sensitivity_required: bool,
    limitations: str,
    next_action: str,
) -> dict[str, str]:
    return {
        "component_id": component_id,
        "configuration_scope": configuration_scope,
        "emissions_component": emissions_component,
        "driver": driver,
        "factor_or_proxy": factor_or_proxy,
        "unit": unit,
        "counted_in_current_policy": str(counted_in_current_policy).lower(),
        "counting_method": counting_method,
        "source_or_policy_basis": source_or_policy_basis,
        "evidence_tier": evidence_tier,
        "model_use_status": model_use_status,
        "double_counting_risk": double_counting_risk,
        "blocks_complete_direct_emissions": str(blocks_complete_direct_emissions).lower(),
        "sensitivity_required": str(sensitivity_required).lower(),
        "limitations": limitations,
        "next_action": next_action,
    }


def build_emissions_component_status_register() -> pd.DataFrame:
    rows = [
        _emissions_component_row("bfg_oxidation", "C0 and C1", "BFG oxidation", "BFG use at process/boiler/power/flare sinks", "selected WAG CO2 factor", "t CO2/GJ converted from kg CO2/GJ", True, "point_of_oxidation_use", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "partial_direct_proxy_counted", "low if generation remains uncounted", False, False, "Counts BFG carbon once at represented use/oxidation sinks; not complete site emissions.", "Retain point-of-oxidation convention."),
        _emissions_component_row("cog_oxidation", "C0 and C1", "COG oxidation", "COG use at process/boiler/power/flare sinks", "selected WAG CO2 factor", "t CO2/GJ converted from kg CO2/GJ", True, "point_of_oxidation_use", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "partial_direct_proxy_counted", "low if generation remains uncounted", False, False, "Counts COG carbon once at represented use/oxidation sinks; coking non-WAG emissions remain missing.", "Retain point-of-oxidation convention and later add coking non-WAG process emissions."),
        _emissions_component_row("bofg_oxidation", "C0 and C1", "BOFG/LDG oxidation", "BOFG/LDG use at process/boiler/power/flare sinks", "selected WAG CO2 factor", "t CO2/GJ converted from kg CO2/GJ", True, "point_of_oxidation_use", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "partial_direct_proxy_counted", "low if generation remains uncounted", False, False, "Counts BOFG/LDG carbon once at represented use/oxidation sinks; not complete site emissions.", "Retain point-of-oxidation convention."),
        _emissions_component_row("wag_flare_spill", "C0 and C1", "WAG flare/spill oxidation", "flare_spill_unused sink where present", "selected WAG CO2 factors", "t CO2/GJ converted from kg CO2/GJ", True, "point_of_oxidation_use_if_profile_routes_to_flare", "current WAG diagnostic allocation sinks", "D/E development assumption", "partial_direct_proxy_counted", "low; flare is a use/oxidation sink, not a generation count", False, True, "Currently near zero or scenario-dependent; not validated actual flare.", "Keep explicit sink and avoid interpreting zero as plant truth."),
        _emissions_component_row("drp_direct_co2_proxy", "C1 only", "DRP direct CO2 proxy", "drp_direct_co2_proxy profile rows", "ng_drp_direct_co2_factor", "t CO2/t pellets converted to t CO2/t steel proxy", True, "direct_proxy_non_double_counting_policy", "s3_c1_route_energy_inputs.csv", "B public secondary literature derived", "partial_direct_proxy_counted", "high if NG combustion CO2 is also added", False, True, "Selected Tier B proxy is partial and not Tata-exact; counted instead of separate DRP NG combustion CO2.", "Retain sensitivity status and review before thesis-final use."),
        _emissions_component_row("drp_ng_combustion_co2", "C1 only", "DRP natural-gas combustion CO2", "DRP natural-gas volume", "natural-gas CO2 factor", "t CO2/GJ or t CO2/m3", False, "not_counted_by_current_policy", "non-double-counting policy", "policy blocked", "blocked_while_drp_direct_proxy_active", "high if added to DRP direct proxy", True, True, "Not physically zero; blank in results because current policy blocks additive NG combustion CO2 for DRP.", "Select explicit NG combustion decomposition only as an alternative to the DRP direct proxy."),
        _emissions_component_row("retained_bf_bof_non_wag_process", "C0 and retained C1 BF/BOF", "Retained BF/BOF non-WAG process emissions", "BF/BOF process activity", "missing", "t CO2/t process output", False, "missing_not_zero", "not selected", "not selected", "blocked", "material omission if complete ledger claimed", True, True, "Missing material direct-emissions component blocks complete direct-emissions readiness.", "Select or explicitly exclude retained BF/BOF non-WAG process emissions."),
        _emissions_component_row("coking_non_wag_process", "C0 and retained C1 coking", "Coking non-WAG process emissions", "coking/coke/dry-coal proxy", "missing", "t CO2/t coke or t CO2/t dry coal", False, "missing_not_zero", "not selected", "not selected", "blocked", "material omission if complete ledger claimed", True, True, "COG oxidation is counted, but coking process emissions beyond WAG oxidation are not represented.", "Select coking direct-emissions boundary or explicit exclusion policy."),
        _emissions_component_row("downstream_reheating_emissions", "C0 and C1 downstream", "Downstream/reheating emissions", "downstream accounting drivers", "missing", "t CO2/t or GJ/t plus fuel factor", False, "missing_not_zero", "s3_downstream_accounting_boundary_register.csv", "not selected", "blocked", "material omission if complete ledger claimed", True, True, "Downstream driver rows do not imply downstream emissions and are not hidden zeros.", "Select downstream/reheating emissions coefficients or explicit exclusion policy."),
        _emissions_component_row("electricity_scope2", "C0 and C1", "Electricity scope-2 emissions", "proxy residual grid import or selected electricity boundary", "missing", "t CO2/MWh", False, "factor_missing_not_counted", "not selected", "not selected", "blocked", "scope-2 must stay separate from direct emissions", False, True, "No selected grid emissions factor; proxy import is reported only in MWh.", "Select an explicit electricity emissions factor only if scope-2 reporting is reopened."),
        _emissions_component_row("oxygen_asu_emissions", "C0 and C1 auxiliary", "Oxygen/ASU emissions", "oxygen_demand_auxiliary_driver", "missing", "MWh/t O2 plus scope/fuel factor", False, "missing_not_zero", "s3_downstream_accounting_boundary_register.csv", "not selected", "blocked", "material auxiliary omission if complete ledger claimed", True, True, "Oxygen/ASU driver exists without electricity or emissions coefficients.", "Select ASU/oxygen electricity and emissions boundary."),
        _emissions_component_row("residual_site_emissions", "C0 and C1 site boundary", "Residual site emissions boundary", "residual site processes and utilities", "missing", "various", False, "missing_not_zero", "S3.0d plant-boundary gate", "policy not selected", "blocked", "material omission if complete ledger claimed", True, True, "Residual direct-emissions components are not closed.", "Review residual site emissions boundary."),
        _emissions_component_row("gross_ets_cost_basis", "C0 and C1 economics", "Gross ETS cost basis", "eligible direct CO2 under future complete policy", "missing CO2 price and complete emissions boundary", "EUR/t CO2", False, "blocked_no_monetary_result", "S3.0e economic-accounting policy", "policy not selected", "blocked", "ETS cost cannot be calculated from partial proxy", True, True, "Gross ETS cost remains blocked; free allocation out of scope.", "Close complete emissions policy before ETS price or gross cost result."),
    ]
    return pd.DataFrame(rows)


def build_parameter_status_register() -> pd.DataFrame:
    rows = [
        _parameter_row("physical_accounting", "WAG generation coefficients", "WAG generation by carrier", "selected_dev_input", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "static_physical_ledger", "selected per BFG/COG/BOFG rows", "Nm3 or m3 per activity unit", "true", False, False, False, "Development only; sensitivity required for material WAG generation.", "Keep in sensitivity register before thesis use."),
        _parameter_row("physical_accounting", "WAG LHV", "WAG energy conversion", "selected_dev_input", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "static_physical_ledger", "selected per BFG/COG/BOFG rows", "MJ/Nm3", "false", False, False, False, "Public generic gas-property basis; composition caveat.", "Review if thesis-grade source is selected."),
        _parameter_row("physical_accounting", "WAG power conversion efficiency", "proxy WAG offset", "selected_dev_input", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "static_physical_ledger", "37.15", "% net electric efficiency", "true", False, False, False, "Potential offset only; no dispatch, price response, export, or settlement.", "Keep as sensitivity before DA/cost use."),
        _parameter_row("physical_accounting", "DRP natural-gas coefficient", "C1 DRP natural-gas volume", "selected_tier_b_assumption", "s3_c1_route_energy_inputs.csv", "B public secondary literature derived", "static_physical_ledger", "195", "m3_NG/t_pellets", "true", False, False, False, "Not Tata-exact; liquid/crude-steel proxy caveat.", "Retain sensitivity status."),
        _parameter_row("physical_accounting", "DRP electricity coefficient", "C1 DRP electricity", "selected_tier_b_assumption", "s3_c1_route_energy_inputs.csv", "B public secondary literature derived", "static_physical_ledger", "0.1", "MWh/t_pellets", "true", False, False, False, "Not Tata-exact; material C1 assumption.", "Retain sensitivity status."),
        _parameter_row("physical_accounting", "EAF electricity coefficient", "C1 EAF electricity", "selected_tier_b_assumption", "s3_c1_route_energy_inputs.csv", "B public secondary literature derived", "static_physical_ledger", "0.5", "MWh/t_DRI", "true", False, False, False, "Not Tata-exact; material C1 assumption.", "Retain sensitivity status."),
        _parameter_row("physical_accounting", "downstream accounting drivers", "downstream throughput continuity", "profile_driver_present", "fixed_profiles/*.csv and downstream registers", "D user-selected scenario policy", "driver_only_no_energy_coefficient", "selected driver rows", "t_per_hour proxy", "false", False, True, True, "Drivers are present but coefficients are missing; do not treat as zero energy.", "Select electricity/heat coefficients before cost readiness."),
        _parameter_row("physical_accounting", "downstream electricity coefficient", "complete site electricity ledger", "missing", "s3_downstream_accounting_boundary_register.csv", "not selected", "blocked", "", "MWh/t", "true", True, False, True, "Missing coefficient blocks complete site-energy and monetary ledger; it is not a hidden zero.", "Select reviewed downstream electricity coefficients."),
        _parameter_row("physical_accounting", "ASU/oxygen electricity coefficient", "auxiliary electricity ledger", "missing", "s3_downstream_accounting_boundary_register.csv", "not selected", "blocked", "", "MWh/t or MWh/Nm3 O2", "true", True, False, True, "Oxygen driver exists but electricity coefficient is missing.", "Select reviewed ASU/oxygen electricity coefficient."),
        _parameter_row("physical_accounting", "heat/steam/reheating coefficient", "heat and reheating ledger", "missing", "s3_downstream_accounting_boundary_register.csv", "not selected", "blocked", "", "GJ/t or MWh/t", "true", True, True, True, "Heat/steam closure missing; not hidden as zero.", "Select reviewed heat/steam/reheating coefficients."),
        _parameter_row("physical_accounting", "residual electricity boundary policy", "proxy gross electricity import exposure", "selected_proxy_sensitivity", "s3_electricity_boundary_sensitivity_register.csv", "D user-selected scenario policy", "static_proxy_only", "2.25/3.00/3.75 million", "MWh/year", "true", False, False, True, "Proxy boundary only; not plant import truth and not cost-ready.", "Review residual/site-load policy before DA/cost use."),
        _parameter_row("emissions_accounting", "WAG CO2 factors", "WAG oxidation emissions", "selected_dev_input", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "partial_emissions_proxy", "selected per BFG/COG/BOFG rows", "kg CO2/GJ", "false", False, False, False, "Point-of-oxidation proxy only; public reporting factors.", "Retain no-double-counting separation."),
        _parameter_row("emissions_accounting", "DRP direct CO2 proxy", "C1 direct emissions proxy", "selected_tier_b_assumption", "s3_c1_route_energy_inputs.csv", "B public secondary literature derived", "partial_emissions_proxy", "derived in fixed profiles", "t CO2/t liquid-steel proxy", "true", False, False, False, "Direct proxy is partial and not a complete plant emissions ledger.", "Review with complete emissions boundary."),
        _parameter_row("emissions_accounting", "natural-gas CO2 factor", "natural-gas combustion emissions", "factor_exists_policy_blocked", "s3_wag_selected_dev_inputs.csv", "D/E development assumption", "not_additive_without_policy", "56.1", "kg CO2/GJ", "true", False, True, True, "Not added to DRP direct CO2 proxy without explicit non-double-counting policy.", "Decide DRP direct-vs-combustion treatment before ETS."),
        _parameter_row("emissions_accounting", "electricity scope-2 factor", "optional indirect electricity reporting", "missing", "not selected", "not selected", "blocked", "", "t CO2/MWh", "true", False, True, True, "No selected factor; scope-2 not computed.", "Select only if thesis reporting needs indirect emissions."),
        _parameter_row("emissions_accounting", "downstream emissions factors", "complete direct emissions ledger", "missing", "s3_downstream_accounting_boundary_register.csv", "not selected", "blocked", "", "various", "true", False, True, True, "Downstream emissions missing; complete direct emissions false.", "Select reviewed downstream emissions policy/factors."),
        _parameter_row("emissions_accounting", "complete direct-emissions ledger policy", "gross ETS readiness", "missing", "STEEL_S3_0D gate and downstream closure", "policy not selected", "blocked", "", "policy", "true", False, True, True, "Partial direct emissions only; no gross ETS result.", "Close direct-emissions boundary and double-counting policy."),
        _parameter_row("economic_accounting", "electricity price input", "electricity import cost", "missing", "not selected", "not selected", "formula_hook_only", "", "EUR/MWh", "true", False, False, True, "Missing static price blocks monetary result; no DA price.", "Select static non-DA price only after boundary review."),
        _parameter_row("economic_accounting", "natural-gas price input", "natural-gas cost", "missing", "not selected", "not selected", "formula_hook_only", "", "EUR/MWh or EUR/m3", "true", False, False, True, "Missing price blocks monetary result.", "Select static price and unit conversion policy."),
        _parameter_row("economic_accounting", "CO2/ETS price input", "CO2/ETS gross cost proxy", "missing", "not selected", "not selected", "formula_hook_only", "", "EUR/t CO2", "true", False, True, True, "Missing price and complete emissions ledger block ETS result.", "Select ETS price only after emissions boundary review."),
        _parameter_row("economic_accounting", "tariff/network cost input", "network and tariff accounting", "missing", "not selected", "not selected", "blocked", "", "EUR/MWh or tariff schedule", "true", False, False, True, "No tariff logic or settlement implemented.", "Keep outside static S3.0e-a ledger."),
        _parameter_row("economic_accounting", "WAG avoided-cost valuation policy", "future avoided import value", "policy_blocked", "S3.0d plant-boundary gate", "policy not selected", "formula_hook_only", "", "policy", "true", False, False, True, "WAG offset is not revenue and not cost saving until price/boundary policy exists.", "Define valuation policy before monetary reporting."),
        _parameter_row("economic_accounting", "product revenue input", "product economics", "out_of_scope_missing", "not selected", "not selected", "blocked", "", "EUR/t product", "true", False, False, True, "Product revenue is out of scope for S3.0e-a.", "Reopen only in later economic model stage."),
    ]
    return pd.DataFrame(rows)


def _parameter_row(
    parameter_family: str,
    parameter_name: str,
    required_for: str,
    current_status: str,
    source_or_policy_basis: str,
    evidence_tier: str,
    model_use_status: str,
    selected_value: str,
    unit: str,
    sensitivity_required: str,
    blocks_physical_ledger: bool,
    blocks_emissions_ledger: bool,
    blocks_monetary_ledger: bool,
    limitations: str,
    next_action: str,
) -> dict[str, str]:
    return {
        "parameter_family": parameter_family,
        "parameter_name": parameter_name,
        "required_for": required_for,
        "current_status": current_status,
        "source_or_policy_basis": source_or_policy_basis,
        "evidence_tier": evidence_tier,
        "model_use_status": model_use_status,
        "selected_value": selected_value,
        "unit": unit,
        "sensitivity_required": sensitivity_required,
        "blocks_physical_ledger": str(blocks_physical_ledger).lower(),
        "blocks_emissions_ledger": str(blocks_emissions_ledger).lower(),
        "blocks_monetary_ledger": str(blocks_monetary_ledger).lower(),
        "limitations": limitations,
        "next_action": next_action,
    }


def build_result_register() -> pd.DataFrame:
    power_efficiency = _power_efficiency()
    rows: list[dict[str, Any]] = []
    selected_inputs = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    demand_coefficients = load_wag_demand_coefficients(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH)

    c0_profile = _read_csv(C0_PROFILE_PATH)
    c0_diagnostic = run_c0_wag_diagnostic(
        selected_inputs=selected_inputs,
        demand_coefficients=demand_coefficients,
        profile_rows=load_fixed_activity_profile(C0_PROFILE_PATH),
    )
    rows.extend(
        _result_rows_for_profile(
            configuration_id=C0_CONFIGURATION_ID,
            scenario_id=C0_SCENARIO_ID,
            profile=c0_profile,
            diagnostic=c0_diagnostic,
            diagnostic_level="minimum_known_heat_sink_c0_static_accounting",
            bf_bof_share=1.0,
            drp_eaf_share=0.0,
            power_efficiency=power_efficiency,
            component_electricity_mwh=None,
            drp_natural_gas_m3=0.0,
            drp_electricity_mwh=0.0,
            eaf_electricity_mwh=0.0,
            drp_direct_co2_proxy_t=0.0,
            plant_level_claim_allowed=False,
        )
    )

    for scenario_id, filename in C1_PROFILE_FILENAMES.items():
        profile_path = FIXED_PROFILE_ROOT / filename
        profile = _read_csv(profile_path)
        diagnostic = run_c1_component_energy_diagnostic(
            selected_inputs=selected_inputs,
            profile_rows=load_fixed_activity_profile(profile_path),
        )
        shares = C1_ROUTE_SCENARIOS[scenario_id]
        rows.extend(
            _result_rows_for_profile(
                configuration_id=C1_CONFIGURATION_ID,
                scenario_id=scenario_id,
                profile=profile,
                diagnostic=diagnostic,
                diagnostic_level="component_energy_boundary_static_accounting",
                bf_bof_share=shares["bf_bof_share"],
                drp_eaf_share=shares["drp_eaf_share"],
                power_efficiency=power_efficiency,
                component_electricity_mwh=_sum_profile(profile, "component_electricity_demand_before_wag_offset"),
                drp_natural_gas_m3=_sum_profile(profile, "drp_natural_gas_demand"),
                drp_electricity_mwh=_sum_profile(profile, "drp_electricity_demand"),
                eaf_electricity_mwh=_sum_profile(profile, "eaf_electricity_demand"),
                drp_direct_co2_proxy_t=_sum_profile(profile, "drp_direct_co2_proxy"),
                plant_level_claim_allowed=False,
            )
        )
    return pd.DataFrame(rows)


def _result_rows_for_profile(
    *,
    configuration_id: str,
    scenario_id: str,
    profile: pd.DataFrame,
    diagnostic: dict[str, Any],
    diagnostic_level: str,
    bf_bof_share: float,
    drp_eaf_share: float,
    power_efficiency: float,
    component_electricity_mwh: float | None,
    drp_natural_gas_m3: float,
    drp_electricity_mwh: float,
    eaf_electricity_mwh: float,
    drp_direct_co2_proxy_t: float,
    plant_level_claim_allowed: bool,
) -> list[dict[str, Any]]:
    bfg = _wag_generation_gj(diagnostic, "BFG")
    cog = _wag_generation_gj(diagnostic, "COG")
    bofg = _wag_generation_gj(diagnostic, "BOFG_LD_gas")
    total_wag = bfg + cog + bofg
    wag_co2 = sum(_wag_co2_t(diagnostic, carrier) for carrier in WAG_CARRIER_KEYS)
    drp_direct_counted = CURRENT_EMISSIONS_POLICY.drp_direct_co2_proxy_counted and drp_eaf_share > 0.0
    double_counting_warning = emissions_double_counting_warning(CURRENT_EMISSIONS_POLICY)
    total_output = (
        _sum_profile(profile, "total_liquid_steel_output")
        or _sum_profile(profile, "bof_liquid_steel_activity")
        or _sum_profile(profile, "continuous_casting_liquid_steel_input")
    )
    uncapped_power_potential = _uncapped_power_potential_mwh(diagnostic, power_efficiency)
    total_partial_co2 = wag_co2 + (drp_direct_co2_proxy_t if drp_direct_counted else 0.0)
    rows = []
    for case in ELECTRICITY_BOUNDARY_CASES:
        wag_offset = min(uncapped_power_potential, case.mwh_24h)
        residual_import = max(0.0, case.mwh_24h - wag_offset)
        rows.append(
            {
                "result_id": f"S30E_STATIC_{scenario_id}_{case.boundary_case_id}",
                "configuration_id": configuration_id,
                "scenario_id": scenario_id,
                "boundary_case_id": case.boundary_case_id,
                "diagnostic_level": diagnostic_level,
                "total_output_t_24h": _round(total_output),
                "bf_bof_share": _round(bf_bof_share, 6),
                "drp_eaf_share": _round(drp_eaf_share, 6),
                "bfg_gj_24h": _round(bfg),
                "cog_gj_24h": _round(cog),
                "bofg_gj_24h": _round(bofg),
                "total_wag_gj_24h": _round(total_wag),
                "drp_natural_gas_m3_24h": _round(drp_natural_gas_m3),
                "drp_electricity_mwh_24h": _round(drp_electricity_mwh),
                "eaf_electricity_mwh_24h": _round(eaf_electricity_mwh),
                "component_electricity_mwh_24h": _round(component_electricity_mwh),
                "gross_proxy_electricity_boundary_mwh_24h": _round(case.mwh_24h),
                "uncapped_wag_power_potential_mwh_24h": _round(uncapped_power_potential),
                "wag_offset_mwh_24h": _round(wag_offset),
                "residual_proxy_grid_import_mwh_24h": _round(residual_import),
                "emissions_policy_id": CURRENT_EMISSIONS_POLICY.emissions_policy_id,
                "wag_generation_emissions_counted": str(CURRENT_EMISSIONS_POLICY.wag_generation_emissions_counted).lower(),
                "wag_use_emissions_counted": str(CURRENT_EMISSIONS_POLICY.wag_use_emissions_counted).lower(),
                "drp_direct_co2_proxy_counted": str(drp_direct_counted).lower(),
                "drp_ng_combustion_co2_counted": str(CURRENT_EMISSIONS_POLICY.drp_ng_combustion_co2_counted).lower(),
                "electricity_scope2_counted": str(CURRENT_EMISSIONS_POLICY.electricity_scope2_counted).lower(),
                "downstream_emissions_counted": str(CURRENT_EMISSIONS_POLICY.downstream_emissions_counted).lower(),
                "wag_co2_t_24h": _round(wag_co2),
                "drp_direct_co2_proxy_t_24h": _round(drp_direct_co2_proxy_t),
                "drp_ng_combustion_co2_t_24h": None,
                "electricity_scope2_t_24h": None,
                "downstream_co2_t_24h": None,
                "total_partial_direct_co2_proxy_t_24h": _round(total_partial_co2),
                "electricity_cost_eur_24h": None,
                "natural_gas_cost_eur_24h": None,
                "co2_cost_eur_24h": None,
                "total_static_cost_proxy_eur_24h": None,
                "monetary_values_ready": "false",
                "complete_direct_emissions_ready": str(CURRENT_EMISSIONS_POLICY.complete_direct_emissions_ready).lower(),
                "ets_ready": str(CURRENT_EMISSIONS_POLICY.ets_ready).lower(),
                "double_counting_warning": double_counting_warning,
                "plant_level_claim_allowed": str(plant_level_claim_allowed).lower(),
                "cost_da_ready": "false",
                "limitations": "Proxy static accounting only; DRP NG combustion, electricity scope-2, and downstream emissions are policy-blocked or missing, not hidden zeros; monetary values blocked because prices and complete cost/emissions boundaries are not selected.",
                "notes": "WAG offset is capped by proxy gross electricity boundary and is not revenue, settlement, zero-emission electricity for external reporting, or actual plant import.",
            }
        )
    return rows


def build_all_registers() -> dict[Path, pd.DataFrame]:
    return {
        SITE_STATIC_ACCOUNTING_BOUNDARY_REGISTER: build_boundary_register(),
        STATIC_ACCOUNTING_PARAMETER_STATUS_REGISTER: build_parameter_status_register(),
        ELECTRICITY_BOUNDARY_SENSITIVITY_REGISTER: build_electricity_boundary_register(),
        EMISSIONS_BOUNDARY_POLICY_REGISTER: build_emissions_boundary_policy_register(),
        EMISSIONS_COMPONENT_STATUS_REGISTER: build_emissions_component_status_register(),
        SITE_STATIC_ACCOUNTING_RESULT_REGISTER: build_result_register(),
    }


def write_registers() -> dict[str, int]:
    payload: dict[str, int] = {}
    for path, frame in build_all_registers().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, lineterminator="\n")
        payload[str(path.relative_to(REPO_ROOT))] = int(len(frame))
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build S3.0e-a static site accounting registers.")
    parser.add_argument("--write-registers", action="store_true", help="Write governed S3 accounting registers.")
    parser.add_argument("--validate-only", action="store_true", help="Build registers in memory without writing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.write_registers:
        payload = write_registers()
    else:
        payload = {str(path.relative_to(REPO_ROOT)): int(len(frame)) for path, frame in build_all_registers().items()}
    print(pd.Series(payload, name="rows").to_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
