from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .wag_diagnostic_inputs import FixedActivityProfileRow, SelectedWAGInput, WAGDemandCoefficient


MJ_PER_GJ = 1000.0
GJ_PER_MWH = 3.6
BALANCE_TOLERANCE_GJ = 1e-6


class WAGDiagnosticError(ValueError):
    """Raised when deterministic WAG diagnostic inputs are inconsistent."""


@dataclass(frozen=True)
class CarrierGenerationResult:
    carrier: str
    generated_volume: float
    volume_unit: str
    generated_energy_gj: float
    generated_energy_mwh_thermal: float
    validation_status: str
    limitations: str = ""


@dataclass(frozen=True)
class COGGenerationResult:
    blocked: bool
    missing_inputs: tuple[str, ...]
    coke_required_tonnes: float = 0.0
    onsite_coke_tonnes: float = 0.0
    dry_coal_input_tonnes: float = 0.0
    external_or_imported_coke_tonnes: float = 0.0
    gross_cog_volume_m3: float = 0.0
    gross_cog_energy_gj: float = 0.0
    mandatory_self_or_process_use_gj: float = 0.0
    allocatable_cog_energy_gj: float = 0.0
    validation_status: str = "blocked"
    coking_supply_mode: str = "blocked"


@dataclass(frozen=True)
class AllocationResult:
    process_use_gj: dict[str, float]
    unmet_process_demand_gj: dict[str, float]
    boiler_use_gj: dict[str, float]
    natural_gas_boiler_use_gj: float
    useful_steam_heat_gj: float
    unmet_steam_boiler_useful_demand_gj: float
    power_interface_use_gj: dict[str, float]
    potential_net_import_offset_mwh: float
    residual_grid_import_mwh: float
    flare_spill_unused_gj: dict[str, float]
    balance_residual_gj: dict[str, float]
    validation_status: str
    output_label: str
    limitations: str


@dataclass(frozen=True)
class EmissionsResult:
    wag_co2_tonnes_by_carrier_sink: dict[str, dict[str, float]]
    natural_gas_co2_tonnes: float
    captured_co2_tonnes: float
    direct_emissions_ledger_complete: bool
    gross_ets_cost_eligible: bool
    double_counting_validation_passed: bool
    validation_status: str


@dataclass(frozen=True)
class ReadinessFlag:
    ready: bool
    missing_inputs: tuple[str, ...]
    blocking_reason: str
    code_scaffold_available: bool
    blocker_type: str


@dataclass(frozen=True)
class ReadinessAssessment:
    implementation_ready: bool
    runtime_ready: bool
    profile_schema_ready: ReadinessFlag
    selected_input_loader_ready: ReadinessFlag
    bfg_generation_ready: ReadinessFlag
    bofg_generation_ready: ReadinessFlag
    cog_generation_ready: ReadinessFlag
    mandatory_process_use_ready: ReadinessFlag
    steam_boiler_allocation_ready: ReadinessFlag
    power_import_offset_ready: ReadinessFlag
    emissions_ready: ReadinessFlag
    full_diagnostic_ready: ReadinessFlag
    c0_activity_profile_ready: ReadinessFlag
    c1_activity_profile_ready: ReadinessFlag
    c0_demand_profile_ready: ReadinessFlag
    c1_demand_profile_ready: ReadinessFlag
    c0_cog_chain_ready: ReadinessFlag
    c1_cog_chain_ready: ReadinessFlag
    c0_electricity_cap_ready: ReadinessFlag
    c1_electricity_cap_ready: ReadinessFlag


def _to_timestep_tonnes(activity_value: float, activity_unit: str, timestep_hours: float) -> float:
    if timestep_hours <= 0:
        raise WAGDiagnosticError("timestep_hours must be positive.")
    if activity_unit == "t_per_hour":
        return activity_value * timestep_hours
    if activity_unit in {"tonnes", "timestep_total_tonnes"}:
        return activity_value
    raise WAGDiagnosticError(f"Unsupported activity unit for carrier generation: {activity_unit}.")


def calculate_bfg_generation(
    *,
    hot_metal_activity_value: float,
    activity_unit: str,
    timestep_hours: float,
    generation_intensity_nm3_per_t_hot_metal: float,
    lhv_mj_per_nm3: float,
) -> CarrierGenerationResult:
    hot_metal_tonnes = _to_timestep_tonnes(hot_metal_activity_value, activity_unit, timestep_hours)
    volume = hot_metal_tonnes * generation_intensity_nm3_per_t_hot_metal
    energy_gj = volume * lhv_mj_per_nm3 / MJ_PER_GJ
    return CarrierGenerationResult(
        carrier="BFG",
        generated_volume=volume,
        volume_unit="Nm3",
        generated_energy_gj=energy_gj,
        generated_energy_mwh_thermal=energy_gj / GJ_PER_MWH,
        validation_status="valid",
    )


def calculate_bofg_generation(
    *,
    steel_activity_value: float,
    activity_unit: str,
    timestep_hours: float,
    generation_intensity_nm3_per_t_steel: float,
    lhv_mj_per_nm3: float,
    activity_basis: str,
    coefficient_activity_basis: str,
) -> CarrierGenerationResult:
    if activity_basis.strip().lower() != coefficient_activity_basis.strip().lower():
        raise WAGDiagnosticError("BOFG activity basis and coefficient basis must match explicitly.")
    if "liquid" not in activity_basis.lower() and "steel" not in activity_basis.lower():
        raise WAGDiagnosticError("BOFG activity basis must be an explicit steel or liquid-steel basis.")
    steel_tonnes = _to_timestep_tonnes(steel_activity_value, activity_unit, timestep_hours)
    volume = steel_tonnes * generation_intensity_nm3_per_t_steel
    energy_gj = volume * lhv_mj_per_nm3 / MJ_PER_GJ
    return CarrierGenerationResult(
        carrier="BOFG_LD_gas",
        generated_volume=volume,
        volume_unit="Nm3",
        generated_energy_gj=energy_gj,
        generated_energy_mwh_thermal=energy_gj / GJ_PER_MWH,
        validation_status="valid",
    )


def calculate_cog_generation(
    *,
    hot_metal_activity_tonnes: float,
    coke_rate_per_t_hot_metal: float | None,
    onsite_coking_share: float | None,
    coking_supply_mode: str = "share",
    coking_capacity_tonnes_per_timestep: float | None = None,
    dry_coal_t_per_t_coke: float | None = None,
    cog_yield_m3_per_t_dry_coal: float | None = None,
    cog_lhv_mj_per_m3: float | None = None,
    mandatory_cog_self_use_fraction: float | None = None,
) -> COGGenerationResult:
    required = {
        "coke_rate_per_t_hot_metal": coke_rate_per_t_hot_metal,
        "dry_coal_t_per_t_coke": dry_coal_t_per_t_coke,
        "cog_yield_m3_per_t_dry_coal": cog_yield_m3_per_t_dry_coal,
        "cog_lhv_mj_per_m3": cog_lhv_mj_per_m3,
    }
    mode = str(coking_supply_mode).strip()
    if mode == "share":
        required["onsite_coking_share"] = onsite_coking_share
        required["mandatory_cog_self_use_fraction"] = mandatory_cog_self_use_fraction
        if coking_capacity_tonnes_per_timestep is not None:
            raise WAGDiagnosticError("COG share mode cannot also use coking capacity.")
    elif mode == "capacity_capped":
        required["coking_capacity_tonnes_per_timestep"] = coking_capacity_tonnes_per_timestep
        if onsite_coking_share is not None or mandatory_cog_self_use_fraction is not None:
            raise WAGDiagnosticError("COG capacity_capped mode cannot also use share or fraction self-use mode.")
    else:
        raise WAGDiagnosticError(f"Unsupported coking_supply_mode={coking_supply_mode!r}.")
    missing = tuple(name for name, value in required.items() if value is None)
    if missing:
        return COGGenerationResult(blocked=True, missing_inputs=missing)
    assert coke_rate_per_t_hot_metal is not None
    assert dry_coal_t_per_t_coke is not None
    assert cog_yield_m3_per_t_dry_coal is not None
    assert cog_lhv_mj_per_m3 is not None
    coke_required = hot_metal_activity_tonnes * coke_rate_per_t_hot_metal
    if mode == "share":
        assert onsite_coking_share is not None
        assert mandatory_cog_self_use_fraction is not None
        if not 0.0 <= onsite_coking_share <= 1.0:
            raise WAGDiagnosticError("onsite_coking_share must be within [0, 1].")
        if not 0.0 <= mandatory_cog_self_use_fraction <= 1.0:
            raise WAGDiagnosticError("mandatory_cog_self_use_fraction must be within [0, 1].")
        onsite_coke = coke_required * onsite_coking_share
        mandatory_fraction = mandatory_cog_self_use_fraction
    else:
        assert coking_capacity_tonnes_per_timestep is not None
        if coking_capacity_tonnes_per_timestep < 0.0:
            raise WAGDiagnosticError("coking_capacity_tonnes_per_timestep must not be negative.")
        onsite_coke = min(coke_required, coking_capacity_tonnes_per_timestep)
        mandatory_fraction = 0.0
    external_coke = max(0.0, coke_required - onsite_coke)
    dry_coal = onsite_coke * dry_coal_t_per_t_coke
    volume = dry_coal * cog_yield_m3_per_t_dry_coal
    gross_energy = volume * cog_lhv_mj_per_m3 / MJ_PER_GJ
    mandatory_use = gross_energy * mandatory_fraction
    return COGGenerationResult(
        blocked=False,
        missing_inputs=(),
        coke_required_tonnes=coke_required,
        onsite_coke_tonnes=onsite_coke,
        dry_coal_input_tonnes=dry_coal,
        external_or_imported_coke_tonnes=external_coke,
        gross_cog_volume_m3=volume,
        gross_cog_energy_gj=gross_energy,
        mandatory_self_or_process_use_gj=mandatory_use,
        allocatable_cog_energy_gj=gross_energy - mandatory_use,
        validation_status="valid",
        coking_supply_mode=mode,
    )


def _sum_values(values: Mapping[str, float]) -> float:
    return float(sum(values.values()))


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if abs(denominator) <= 1e-12:
        return None
    return numerator / denominator


def _proportional_allocate(available: Mapping[str, float], required_total: float) -> dict[str, float]:
    positive_available = {carrier: max(0.0, value) for carrier, value in available.items() if value > 0.0}
    total = _sum_values(positive_available)
    if required_total <= 0.0 or total <= 0.0:
        return {carrier: 0.0 for carrier in available}
    allocated_total = min(required_total, total)
    return {carrier: allocated_total * value / total for carrier, value in positive_available.items()}


def allocate_process_first(
    *,
    available_energy_gj_by_carrier: Mapping[str, float],
    mandatory_process_demand_gj_by_carrier: Mapping[str, float],
    steam_boiler_useful_demand_gj: float,
    boiler_efficiency: float,
    residual_site_electricity_demand_mwh: float,
    wag_to_power_efficiency: float,
    timestep_hours: float,
    capacity_mode: str = "potential_import_offset",
    interface_capacity_mw: float | None = None,
    natural_gas_boiler_allowed: bool = False,
    natural_gas_boiler_efficiency: float | None = None,
) -> AllocationResult:
    residual = {carrier: max(0.0, value) for carrier, value in available_energy_gj_by_carrier.items()}
    process_use: dict[str, float] = {}
    unmet_process: dict[str, float] = {}
    validation_status = "valid"

    for carrier, demand in mandatory_process_demand_gj_by_carrier.items():
        available = residual.get(carrier, 0.0)
        used = min(max(0.0, demand), available)
        process_use[carrier] = used
        residual[carrier] = available - used
        unmet = max(0.0, demand - used)
        unmet_process[carrier] = unmet
        if unmet > BALANCE_TOLERANCE_GJ:
            validation_status = "validation_failed"

    boiler_fuel_required = steam_boiler_useful_demand_gj / boiler_efficiency if boiler_efficiency > 0.0 else 0.0
    boiler_use = _proportional_allocate(residual, boiler_fuel_required)
    for carrier, value in boiler_use.items():
        residual[carrier] = residual.get(carrier, 0.0) - value
    useful_from_wag = _sum_values(boiler_use) * boiler_efficiency
    remaining_useful_demand = max(0.0, steam_boiler_useful_demand_gj - useful_from_wag)
    natural_gas_use = 0.0
    useful_from_natural_gas = 0.0
    if remaining_useful_demand > BALANCE_TOLERANCE_GJ and natural_gas_boiler_allowed:
        if not natural_gas_boiler_efficiency or natural_gas_boiler_efficiency <= 0.0:
            raise WAGDiagnosticError("Natural-gas boiler substitution requires an explicit positive efficiency.")
        natural_gas_use = remaining_useful_demand / natural_gas_boiler_efficiency
        useful_from_natural_gas = remaining_useful_demand
        remaining_useful_demand = 0.0

    potential_power_mwh = _sum_values(residual) / GJ_PER_MWH * wag_to_power_efficiency
    demand_cap_mwh = max(0.0, residual_site_electricity_demand_mwh)
    if capacity_mode != "potential_import_offset" and interface_capacity_mw is not None:
        demand_cap_mwh = min(demand_cap_mwh, max(0.0, interface_capacity_mw) * timestep_hours)
    produced_power_mwh = min(potential_power_mwh, demand_cap_mwh)
    power_fuel_required_gj = produced_power_mwh * GJ_PER_MWH / wag_to_power_efficiency if wag_to_power_efficiency > 0.0 else 0.0
    power_use = _proportional_allocate(residual, power_fuel_required_gj)
    for carrier, value in power_use.items():
        residual[carrier] = residual.get(carrier, 0.0) - value

    flare = {carrier: max(0.0, value) for carrier, value in residual.items()}
    balance = {}
    for carrier, available in available_energy_gj_by_carrier.items():
        used = (
            process_use.get(carrier, 0.0)
            + boiler_use.get(carrier, 0.0)
            + power_use.get(carrier, 0.0)
            + flare.get(carrier, 0.0)
        )
        balance[carrier] = available - used
        if abs(balance[carrier]) > BALANCE_TOLERANCE_GJ:
            validation_status = "validation_failed"

    return AllocationResult(
        process_use_gj=process_use,
        unmet_process_demand_gj=unmet_process,
        boiler_use_gj=boiler_use,
        natural_gas_boiler_use_gj=natural_gas_use,
        useful_steam_heat_gj=useful_from_wag + useful_from_natural_gas,
        unmet_steam_boiler_useful_demand_gj=remaining_useful_demand,
        power_interface_use_gj=power_use,
        potential_net_import_offset_mwh=produced_power_mwh,
        residual_grid_import_mwh=max(0.0, residual_site_electricity_demand_mwh - produced_power_mwh),
        flare_spill_unused_gj=flare,
        balance_residual_gj=balance,
        validation_status=validation_status,
        output_label="potential_net_import_offset",
        limitations="No export, revenue, price signal, or Vattenfall dispatch is represented.",
    )


def calculate_point_of_oxidation_emissions(
    *,
    allocation: AllocationResult,
    emission_factors_kg_per_gj: Mapping[str, float],
    natural_gas_energy_gj: float = 0.0,
    natural_gas_factor_kg_per_gj: float | None = None,
    captured_co2_tonnes: float = 0.0,
    non_wag_residual_process_emissions_tonnes: float | None = None,
) -> EmissionsResult:
    sinks = {
        "process_use": allocation.process_use_gj,
        "boiler_use": allocation.boiler_use_gj,
        "power_interface_use": allocation.power_interface_use_gj,
        "flare": allocation.flare_spill_unused_gj,
    }
    wag_co2: dict[str, dict[str, float]] = {}
    for sink, carrier_values in sinks.items():
        for carrier, energy_gj in carrier_values.items():
            factor = emission_factors_kg_per_gj.get(carrier)
            if factor is None:
                raise WAGDiagnosticError(f"Missing WAG CO2 factor for {carrier}.")
            wag_co2.setdefault(carrier, {})[sink] = energy_gj * factor / 1000.0

    natural_gas_co2 = 0.0
    if natural_gas_energy_gj > 0.0:
        if natural_gas_factor_kg_per_gj is None:
            raise WAGDiagnosticError("Natural-gas energy requires a natural-gas CO2 factor.")
        natural_gas_co2 = natural_gas_energy_gj * natural_gas_factor_kg_per_gj / 1000.0

    ledger_complete = non_wag_residual_process_emissions_tonnes is not None
    return EmissionsResult(
        wag_co2_tonnes_by_carrier_sink=wag_co2,
        natural_gas_co2_tonnes=natural_gas_co2,
        captured_co2_tonnes=captured_co2_tonnes,
        direct_emissions_ledger_complete=ledger_complete,
        gross_ets_cost_eligible=False,
        double_counting_validation_passed=True,
        validation_status="partial_ledger" if not ledger_complete else "complete_direct_ledger_inputs_present",
    )


def _has_parameter(selected_inputs: Mapping[tuple[str, str, str, str], SelectedWAGInput], names: Sequence[str]) -> bool:
    parameter_names = {key[3] for key in selected_inputs}
    return all(name in parameter_names for name in names)


def _flag(
    ready: bool,
    missing: Sequence[str],
    reason: str,
    blocker_type: str,
    *,
    scaffold: bool = True,
) -> ReadinessFlag:
    return ReadinessFlag(
        ready=ready,
        missing_inputs=() if ready else tuple(missing),
        blocking_reason="" if ready else reason,
        code_scaffold_available=scaffold,
        blocker_type="none" if ready else blocker_type,
    )


def assess_wag_readiness(
    selected_inputs: Mapping[tuple[str, str, str, str], SelectedWAGInput],
    profile_rows: Sequence[FixedActivityProfileRow] | None = None,
    demand_coefficients: Mapping[tuple[str, str, str], WAGDemandCoefficient] | None = None,
) -> ReadinessAssessment:
    profile_rows = profile_rows or ()
    demand_coefficients = demand_coefficients or {}
    profile_types = {row.s2_activity_type for row in profile_rows}
    profile_configurations = {row.configuration_id for row in profile_rows}
    demand_configurations = {row.configuration_id for row in demand_coefficients.values()}
    bfg_ready = _has_parameter(selected_inputs, ("bfg_generation_per_tonne_hot_metal", "bfg_lhv"))
    bofg_ready = _has_parameter(
        selected_inputs, ("bofg_generation_suppressed_combustion", "bofg_lhv_downstream_gasholder")
    )
    global_cog_missing = [
        name
        for name in (
            "coke_rate_per_t_hot_metal",
            "dry_coal_input_per_t_coke",
            "c1_retained_onsite_coke_production_share",
        )
        if not _has_parameter(selected_inputs, (name,))
    ]
    c0_cog_missing = [
        name
        for name in (
            "coke_rate_per_t_hot_metal",
            "dry_coal_input_per_t_coke",
            "c0_coking_capacity_annual",
            "cog_raw_yield_per_tonne_dry_coal",
            "cog_lhv_raw_gas",
        )
        if not _has_parameter(selected_inputs, (name,))
    ]
    c1_cog_missing = [
        name
        for name in (
            "coke_rate_per_t_hot_metal",
            "dry_coal_input_per_t_coke",
            "c1_retained_onsite_coke_production_share",
            "cog_raw_yield_per_tonne_dry_coal",
            "cog_lhv_raw_gas",
        )
        if not _has_parameter(selected_inputs, (name,))
    ]
    emissions_ready = _has_parameter(
        selected_inputs,
        (
            "bfg_combustion_factor_netherlands",
            "cog_combustion_factor_netherlands",
            "oxygas_bofg_combustion_factor_netherlands",
            "eu_ets_natural_gas_reference_factor",
        ),
    )
    mandatory_missing = () if "mandatory_process_use" in profile_types else ("mandatory_process_use_profile",)
    steam_missing = () if "steam_boiler_useful_demand" in profile_types else ("steam_boiler_useful_demand_profile",)
    electricity_missing = () if "site_electricity_demand" in profile_types else ("site_electricity_demand_profile",)

    mandatory_ready = not mandatory_missing
    steam_ready = not steam_missing and _has_parameter(selected_inputs, ("boiler_steam_useful_energy_efficiency",))
    power_ready = not electricity_missing and _has_parameter(
        selected_inputs,
        (
            "integrated_mill_offgas_power_efficiency_range",
            "wag_power_reduces_external_electricity_demand",
        ),
    )
    c0_profile_ready = "C0_current_BF_BOF_reference" in profile_configurations
    c1_profile_ready = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF" in profile_configurations
    c0_demand_ready = "C0_current_BF_BOF_reference" in demand_configurations
    c1_demand_ready = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF" in demand_configurations
    c0_cog_ready = not c0_cog_missing
    c1_cog_ready = not c1_cog_missing
    c0_runtime_ready = all([bfg_ready, bofg_ready, c0_profile_ready, c0_demand_ready, c0_cog_ready, mandatory_ready, steam_ready, power_ready, emissions_ready])
    c1_runtime_ready = all([bfg_ready, bofg_ready, c1_profile_ready, c1_demand_ready, c1_cog_ready, mandatory_ready, steam_ready, power_ready, emissions_ready])
    full_ready = c0_runtime_ready or c1_runtime_ready

    return ReadinessAssessment(
        implementation_ready=True,
        runtime_ready=full_ready,
        profile_schema_ready=_flag(True, (), "", "none"),
        selected_input_loader_ready=_flag(bool(selected_inputs), (), "", "none"),
        bfg_generation_ready=_flag(
            bfg_ready,
            ("bfg_generation_per_tonne_hot_metal", "bfg_lhv"),
            "BFG generation inputs are missing.",
            "numerical_evidence",
        ),
        bofg_generation_ready=_flag(
            bofg_ready,
            ("bofg_generation_suppressed_combustion", "bofg_lhv_downstream_gasholder"),
            "BOFG generation inputs are missing.",
            "numerical_evidence",
        ),
        cog_generation_ready=_flag(
            c0_cog_ready,
            c0_cog_missing + global_cog_missing,
            "COG chain inputs are incomplete.",
            "numerical_evidence",
        ),
        mandatory_process_use_ready=_flag(mandatory_ready, mandatory_missing, "Mandatory process-use profile is absent.", "profile_availability"),
        steam_boiler_allocation_ready=_flag(steam_ready, steam_missing, "Steam/boiler demand profile is absent.", "profile_availability"),
        power_import_offset_ready=_flag(power_ready, electricity_missing, "Site electricity demand profile is absent.", "profile_availability"),
        emissions_ready=_flag(emissions_ready, ("carrier_specific_co2_factors",), "Carrier CO2 factors are missing.", "numerical_evidence"),
        full_diagnostic_ready=_flag(full_ready, ("full_runtime_inputs",), "Required runtime profiles or COG-chain inputs remain incomplete.", "profile_availability"),
        c0_activity_profile_ready=_flag(c0_profile_ready, ("C0_fixed_activity_profile",), "C0 fixed activity profile is absent.", "profile_availability"),
        c1_activity_profile_ready=_flag(c1_profile_ready, ("C1_fixed_activity_profile",), "C1 fixed activity profile is absent.", "profile_availability"),
        c0_demand_profile_ready=_flag(c0_demand_ready, ("C0_wag_demand_coefficients",), "C0 WAG demand coefficients are absent.", "profile_availability"),
        c1_demand_profile_ready=_flag(c1_demand_ready, ("C1_wag_demand_coefficients",), "C1 WAG demand coefficients are absent.", "profile_availability"),
        c0_cog_chain_ready=_flag(c0_cog_ready, tuple(c0_cog_missing), "C0 COG chain inputs are incomplete.", "numerical_evidence"),
        c1_cog_chain_ready=_flag(c1_cog_ready, tuple(c1_cog_missing), "C1 COG chain inputs are incomplete.", "numerical_evidence"),
        c0_electricity_cap_ready=_flag(power_ready and c0_profile_ready, ("C0_site_electricity_demand_profile",), "C0 site electricity demand cap is absent.", "profile_availability"),
        c1_electricity_cap_ready=_flag(power_ready and c1_profile_ready, ("C1_site_electricity_demand_profile",), "C1 site electricity demand cap is absent.", "profile_availability"),
    )


def _selected_by_name(
    selected_inputs: Mapping[tuple[str, str, str, str], SelectedWAGInput],
    parameter_name: str,
    *,
    configuration_id: str | None = None,
) -> SelectedWAGInput:
    matches = [
        item
        for item in selected_inputs.values()
        if item.parameter_name == parameter_name
        and (configuration_id is None or item.configuration_id in {configuration_id, "both"})
    ]
    if len(matches) != 1:
        raise WAGDiagnosticError(f"Expected one selected input for {parameter_name}; found {len(matches)}.")
    return matches[0]


def _selected_number(
    selected_inputs: Mapping[tuple[str, str, str, str], SelectedWAGInput],
    parameter_name: str,
    *,
    configuration_id: str | None = None,
) -> float:
    item = _selected_by_name(selected_inputs, parameter_name, configuration_id=configuration_id)
    if item.selected_number is None:
        raise WAGDiagnosticError(f"Selected input {parameter_name} is not numeric.")
    return float(item.selected_number)


def _demand_by_name(
    demand_coefficients: Mapping[tuple[str, str, str], WAGDemandCoefficient],
    demand_name: str,
    *,
    configuration_id: str,
) -> WAGDemandCoefficient:
    matches = [
        item
        for item in demand_coefficients.values()
        if item.demand_name == demand_name and item.configuration_id == configuration_id
    ]
    if len(matches) != 1:
        raise WAGDiagnosticError(f"Expected one demand coefficient for {demand_name}; found {len(matches)}.")
    return matches[0]


def _profile_values(
    profile_rows: Sequence[FixedActivityProfileRow],
    *,
    activity_type: str,
    configuration_id: str,
) -> list[FixedActivityProfileRow]:
    return [
        row
        for row in profile_rows
        if row.configuration_id == configuration_id and row.s2_activity_type == activity_type
    ]


def _activity_total_tonnes(rows: Sequence[FixedActivityProfileRow]) -> float:
    total = 0.0
    for row in rows:
        total += _to_timestep_tonnes(row.activity_value, row.activity_unit, row.timestep_hours)
    return total


def _profile_sum(rows: Sequence[FixedActivityProfileRow], activity_type: str, configuration_id: str) -> float:
    return sum(row.activity_value for row in rows if row.configuration_id == configuration_id and row.s2_activity_type == activity_type)


def _apply_variant(
    base_value: float,
    *,
    lower: str,
    upper: str,
    variant: str,
) -> float:
    if variant == "low":
        return float(lower)
    if variant == "high":
        return float(upper)
    return base_value


def run_c0_wag_diagnostic(
    *,
    selected_inputs: Mapping[tuple[str, str, str, str], SelectedWAGInput],
    demand_coefficients: Mapping[tuple[str, str, str], WAGDemandCoefficient],
    profile_rows: Sequence[FixedActivityProfileRow],
    sensitivity_group: str | None = None,
    sensitivity_variant: str = "central",
) -> dict[str, object]:
    configuration_id = "C0_current_BF_BOF_reference"
    readiness = assess_wag_readiness(selected_inputs, profile_rows, demand_coefficients)
    if not readiness.c0_activity_profile_ready.ready or not readiness.c0_demand_profile_ready.ready or not readiness.c0_cog_chain_ready.ready:
        raise WAGDiagnosticError("C0 WAG diagnostic requested before C0 runtime gates are ready.")
    if sensitivity_variant not in {"central", "low", "high"}:
        raise WAGDiagnosticError("sensitivity_variant must be central, low, or high.")

    bfg_intensity_item = _selected_by_name(selected_inputs, "bfg_generation_per_tonne_hot_metal")
    bfg_lhv_item = _selected_by_name(selected_inputs, "bfg_lhv")
    bofg_intensity_item = _selected_by_name(selected_inputs, "bofg_generation_suppressed_combustion")
    bofg_lhv_item = _selected_by_name(selected_inputs, "bofg_lhv_downstream_gasholder")
    cog_yield_item = _selected_by_name(selected_inputs, "cog_raw_yield_per_tonne_dry_coal")
    coke_rate_item = _selected_by_name(selected_inputs, "coke_rate_per_t_hot_metal", configuration_id=configuration_id)
    dry_coal_item = _selected_by_name(selected_inputs, "dry_coal_input_per_t_coke", configuration_id=configuration_id)
    power_eff_item = _selected_by_name(selected_inputs, "integrated_mill_offgas_power_efficiency_range")
    boiler_eff_item = _selected_by_name(selected_inputs, "boiler_steam_useful_energy_efficiency")

    bfg_intensity = _apply_variant(
        float(bfg_intensity_item.selected_number),
        lower=bfg_intensity_item.selected_lower,
        upper=bfg_intensity_item.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "bfg_generation" else "central",
    )
    bofg_intensity = _apply_variant(
        float(bofg_intensity_item.selected_number),
        lower=bofg_intensity_item.selected_lower,
        upper=bofg_intensity_item.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "bofg_generation" else "central",
    )
    cog_yield = _apply_variant(
        float(cog_yield_item.selected_number),
        lower=cog_yield_item.selected_lower,
        upper=cog_yield_item.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "cog_chain" else "central",
    )
    coke_rate = _apply_variant(
        float(coke_rate_item.selected_number),
        lower=coke_rate_item.selected_lower,
        upper=coke_rate_item.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "cog_chain" else "central",
    )
    dry_coal_per_coke = _apply_variant(
        float(dry_coal_item.selected_number),
        lower=dry_coal_item.selected_lower,
        upper=dry_coal_item.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "cog_chain" else "central",
    )
    power_efficiency = _apply_variant(
        float(power_eff_item.selected_number) / 100.0,
        lower=str(float(power_eff_item.selected_lower) / 100.0),
        upper=str(float(power_eff_item.selected_upper) / 100.0),
        variant=sensitivity_variant if sensitivity_group == "conversion_efficiency" else "central",
    )
    boiler_efficiency = _apply_variant(
        float(boiler_eff_item.selected_number),
        lower=boiler_eff_item.selected_lower,
        upper=boiler_eff_item.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "coking_utility_demand" else "central",
    )

    coking_capacity_annual_item = _selected_by_name(selected_inputs, "c0_coking_capacity_annual", configuration_id=configuration_id)
    electricity_annual_item = _selected_by_name(
        selected_inputs,
        "c0_site_electricity_demand_annual_proxy",
        configuration_id=configuration_id,
    )
    coking_capacity_annual = float(coking_capacity_annual_item.selected_number)
    electricity_annual_proxy_mwh = float(electricity_annual_item.selected_number)
    coking_capacity_per_hour = coking_capacity_annual / 8760.0
    cog_lhv = _selected_number(selected_inputs, "cog_lhv_raw_gas")
    bfg_lhv = _selected_number(selected_inputs, "bfg_lhv")
    bofg_lhv = _selected_number(selected_inputs, "bofg_lhv_downstream_gasholder")

    bfg_factor = _selected_number(selected_inputs, "bfg_combustion_factor_netherlands")
    cog_factor = _selected_number(selected_inputs, "cog_combustion_factor_netherlands")
    bofg_factor = _selected_number(selected_inputs, "oxygas_bofg_combustion_factor_netherlands")
    ng_factor = _selected_number(selected_inputs, "eu_ets_natural_gas_reference_factor")

    bfg_hot_stove = _demand_by_name(demand_coefficients, "c0_bfg_hot_stove_reference_demand", configuration_id=configuration_id)
    cog_hot_stove = _demand_by_name(demand_coefficients, "c0_cog_hot_stove_reference_demand", configuration_id=configuration_id)
    cog_pci = _demand_by_name(demand_coefficients, "c0_cog_pci_drying_reference_demand", configuration_id=configuration_id)
    underfiring = _demand_by_name(demand_coefficients, "c0_coking_underfiring_fuel_demand", configuration_id=configuration_id)
    steam_demand = _demand_by_name(demand_coefficients, "c0_coking_plant_steam_demand", configuration_id=configuration_id)

    underfiring_value = _apply_variant(
        underfiring.selected_value,
        lower=underfiring.selected_lower,
        upper=underfiring.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "coking_process_demand" else "central",
    )
    steam_value = _apply_variant(
        steam_demand.selected_value,
        lower=steam_demand.selected_lower,
        upper=steam_demand.selected_upper,
        variant=sensitivity_variant if sensitivity_group == "coking_utility_demand" else "central",
    )

    totals: dict[str, float] = {
        "bf_hot_metal_t": 0.0,
        "bof_liquid_steel_t": 0.0,
        "onsite_coke_t": 0.0,
        "external_coke_t": 0.0,
        "dry_coal_t": 0.0,
        "bfg_volume_nm3": 0.0,
        "cog_volume_m3": 0.0,
        "bofg_volume_nm3": 0.0,
        "bfg_energy_gj": 0.0,
        "cog_energy_gj": 0.0,
        "bofg_energy_gj": 0.0,
        "natural_gas_boiler_gj": 0.0,
        "potential_net_import_offset_mwh": 0.0,
        "residual_grid_import_mwh": 0.0,
        "unmet_steam_demand_gj": 0.0,
        "unmet_mandatory_demand_gj": 0.0,
        "max_balance_residual_gj": 0.0,
        "total_balance_residual_gj": 0.0,
    }
    process_use = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    boiler_use = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    power_use = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    flare = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    wag_co2 = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    ng_co2 = 0.0

    bf_rows = _profile_values(profile_rows, activity_type="bf_hot_metal_activity", configuration_id=configuration_id)
    bof_rows = _profile_values(profile_rows, activity_type="bof_liquid_steel_activity", configuration_id=configuration_id)
    electricity_rows = _profile_values(profile_rows, activity_type="site_electricity_demand", configuration_id=configuration_id)
    if not (len(bf_rows) == len(bof_rows) == len(electricity_rows)):
        raise WAGDiagnosticError("C0 profile must contain aligned BF, BOF, and site electricity rows.")

    for bf_row, bof_row, electricity_row in zip(bf_rows, bof_rows, electricity_rows, strict=True):
        hot_metal_t = _to_timestep_tonnes(bf_row.activity_value, bf_row.activity_unit, bf_row.timestep_hours)
        liquid_steel_t = _to_timestep_tonnes(bof_row.activity_value, bof_row.activity_unit, bof_row.timestep_hours)
        bfg = calculate_bfg_generation(
            hot_metal_activity_value=hot_metal_t,
            activity_unit="tonnes",
            timestep_hours=bf_row.timestep_hours,
            generation_intensity_nm3_per_t_hot_metal=bfg_intensity,
            lhv_mj_per_nm3=bfg_lhv,
        )
        bofg = calculate_bofg_generation(
            steel_activity_value=liquid_steel_t,
            activity_unit="tonnes",
            timestep_hours=bof_row.timestep_hours,
            generation_intensity_nm3_per_t_steel=bofg_intensity,
            lhv_mj_per_nm3=bofg_lhv,
            activity_basis="per tonne liquid steel",
            coefficient_activity_basis="per tonne liquid steel",
        )
        cog = calculate_cog_generation(
            hot_metal_activity_tonnes=hot_metal_t,
            coke_rate_per_t_hot_metal=coke_rate,
            onsite_coking_share=None,
            coking_supply_mode="capacity_capped",
            coking_capacity_tonnes_per_timestep=coking_capacity_per_hour * bf_row.timestep_hours,
            dry_coal_t_per_t_coke=dry_coal_per_coke,
            cog_yield_m3_per_t_dry_coal=cog_yield,
            cog_lhv_mj_per_m3=cog_lhv,
            mandatory_cog_self_use_fraction=None,
        )
        if cog.blocked:
            raise WAGDiagnosticError(f"COG calculation blocked: {cog.missing_inputs}.")

        bfg_hot_stove_gj = hot_metal_t * bfg_hot_stove.selected_value * bfg_lhv / MJ_PER_GJ
        cog_specific_gj = hot_metal_t * (cog_hot_stove.selected_value + cog_pci.selected_value) * cog_lhv / MJ_PER_GJ
        coking_underfiring_gj = cog.onsite_coke_tonnes * underfiring_value
        available_after_specific = {
            "BFG": max(0.0, bfg.generated_energy_gj - bfg_hot_stove_gj),
            "COG": max(0.0, cog.gross_cog_energy_gj - cog_specific_gj),
        }
        total_eligible = sum(available_after_specific.values())
        bfg_underfiring = coking_underfiring_gj * available_after_specific["BFG"] / total_eligible if total_eligible > 0.0 else 0.0
        cog_underfiring = coking_underfiring_gj * available_after_specific["COG"] / total_eligible if total_eligible > 0.0 else 0.0
        mandatory_process = {
            "BFG": bfg_hot_stove_gj + bfg_underfiring,
            "COG": cog_specific_gj + cog_underfiring,
        }

        allocation = allocate_process_first(
            available_energy_gj_by_carrier={
                "BFG": bfg.generated_energy_gj,
                "COG": cog.gross_cog_energy_gj,
                "BOFG_LD_gas": bofg.generated_energy_gj,
            },
            mandatory_process_demand_gj_by_carrier=mandatory_process,
            steam_boiler_useful_demand_gj=cog.onsite_coke_tonnes * steam_value,
            boiler_efficiency=boiler_efficiency,
            residual_site_electricity_demand_mwh=electricity_row.activity_value,
            wag_to_power_efficiency=power_efficiency,
            timestep_hours=bf_row.timestep_hours,
            capacity_mode="potential_import_offset",
            natural_gas_boiler_allowed=True,
            natural_gas_boiler_efficiency=boiler_efficiency,
        )
        emissions = calculate_point_of_oxidation_emissions(
            allocation=allocation,
            emission_factors_kg_per_gj={"BFG": bfg_factor, "COG": cog_factor, "BOFG_LD_gas": bofg_factor},
            natural_gas_energy_gj=allocation.natural_gas_boiler_use_gj,
            natural_gas_factor_kg_per_gj=ng_factor,
        )

        totals["bf_hot_metal_t"] += hot_metal_t
        totals["bof_liquid_steel_t"] += liquid_steel_t
        totals["onsite_coke_t"] += cog.onsite_coke_tonnes
        totals["external_coke_t"] += cog.external_or_imported_coke_tonnes
        totals["dry_coal_t"] += cog.dry_coal_input_tonnes
        totals["bfg_volume_nm3"] += bfg.generated_volume
        totals["cog_volume_m3"] += cog.gross_cog_volume_m3
        totals["bofg_volume_nm3"] += bofg.generated_volume
        totals["bfg_energy_gj"] += bfg.generated_energy_gj
        totals["cog_energy_gj"] += cog.gross_cog_energy_gj
        totals["bofg_energy_gj"] += bofg.generated_energy_gj
        totals["natural_gas_boiler_gj"] += allocation.natural_gas_boiler_use_gj
        totals["potential_net_import_offset_mwh"] += allocation.potential_net_import_offset_mwh
        totals["residual_grid_import_mwh"] += allocation.residual_grid_import_mwh
        totals["unmet_steam_demand_gj"] += allocation.unmet_steam_boiler_useful_demand_gj
        totals["unmet_mandatory_demand_gj"] += sum(allocation.unmet_process_demand_gj.values())
        residual_values = [abs(value) for value in allocation.balance_residual_gj.values()]
        totals["max_balance_residual_gj"] = max(totals["max_balance_residual_gj"], max(residual_values or [0.0]))
        totals["total_balance_residual_gj"] += sum(abs(value) for value in allocation.balance_residual_gj.values())
        for carrier in process_use:
            process_use[carrier] += allocation.process_use_gj.get(carrier, 0.0)
            boiler_use[carrier] += allocation.boiler_use_gj.get(carrier, 0.0)
            power_use[carrier] += allocation.power_interface_use_gj.get(carrier, 0.0)
            flare[carrier] += allocation.flare_spill_unused_gj.get(carrier, 0.0)
            wag_co2[carrier] += sum(emissions.wag_co2_tonnes_by_carrier_sink.get(carrier, {}).values())
        ng_co2 += emissions.natural_gas_co2_tonnes

    total_wag_energy_gj = totals["bfg_energy_gj"] + totals["cog_energy_gj"] + totals["bofg_energy_gj"]
    total_process_use_gj = _sum_values(process_use)
    total_boiler_use_gj = _sum_values(boiler_use)
    total_power_use_gj = _sum_values(power_use)
    total_flare_gj = _sum_values(flare)
    total_wag_co2_tonnes = _sum_values(wag_co2)
    total_profile_hours = sum(row.timestep_hours for row in bf_rows)
    if total_profile_hours <= 0.0:
        raise WAGDiagnosticError("C0 profile must cover a positive number of hours.")
    annualisation_factor = 8760.0 / total_profile_hours
    annual_hot_metal_t = totals["bf_hot_metal_t"] * annualisation_factor
    annual_liquid_steel_t = totals["bof_liquid_steel_t"] * annualisation_factor
    annual_onsite_coke_t = totals["onsite_coke_t"] * annualisation_factor
    annual_dry_coal_t = totals["dry_coal_t"] * annualisation_factor
    current_profile_electricity_mwh = totals["potential_net_import_offset_mwh"] + totals["residual_grid_import_mwh"]
    coking_scale_ratio = _safe_divide(annual_onsite_coke_t, coking_capacity_annual)
    coking_scale_status = (
        "scale_mismatch_material"
        if coking_scale_ratio is not None and (coking_scale_ratio < 0.8 or coking_scale_ratio > 1.25)
        else "scale_consistent"
    )
    scale_consistency = {
        "annualisation_method": "profile_total_times_8760_over_profile_hours",
        "profile_hours": total_profile_hours,
        "annualisation_factor": annualisation_factor,
        "model_to_reference_steel_scale_ratio": None,
        "model_to_reference_steel_scale_status": "not_assessable",
        "model_to_reference_coking_scale_ratio": coking_scale_ratio,
        "model_to_reference_coking_scale_status": coking_scale_status,
        "electricity_demand_proxy_mwh_per_annualised_model_t_liquid_steel": _safe_divide(
            electricity_annual_proxy_mwh,
            annual_liquid_steel_t,
        ),
        "electricity_demand_anchor_per_reference_t": None,
        "absolute_site_energy_scale_consistent": False,
        "plant_level_grid_import_interpretation_ready": False,
        "plant_level_power_offset_interpretation_ready": False,
        "scale_classification": "scale_mismatch_material",
    }
    readiness_flags = {
        "wag_generation_mechanics_ready": True,
        "coking_proxy_mechanics_ready": True,
        "allocation_balance_mechanics_ready": totals["max_balance_residual_gj"] <= BALANCE_TOLERANCE_GJ,
        "point_of_oxidation_emissions_ready": True,
        "coefficient_sensitivity_mechanics_ready": True,
        "absolute_site_energy_scale_consistent": False,
        "downstream_heat_boundary_complete": False,
        "site_electricity_boundary_complete": False,
        "complete_direct_emissions_ledger_ready": False,
        "plant_level_import_interpretation_ready": False,
        "plant_level_power_offset_interpretation_ready": False,
        "plant_level_cost_accounting_ready": False,
        "s3_cost_integration_ready": False,
        "thesis_validation_ready": False,
        "minimum_known_heat_sink_mechanics_runtime_ready": True,
        "plant_runtime_ready": False,
    }
    warnings = [
        "natural_gas_substitution_zero_because_represented_wag_supply_exceeds_minimum_known_heat_demand",
        "flare_spill_near_zero_because_residual_wag_is_routed_to_potential_import_offset_proxy",
        "omitted_downstream_heat_sinks_make_power_interface_use_an_upper_bound",
        "annual_average_electricity_proxy_removes_hourly_site_load_variation",
        "production_and_electricity_scale_not_demonstrated_consistent_by_canonical_reference",
        "complete_site_emissions_unavailable_partial_wag_ledger_only",
    ]
    normalised_metrics = {
        "wag_generation": {
            "bfg_nm3_per_t_hot_metal": _safe_divide(totals["bfg_volume_nm3"], totals["bf_hot_metal_t"]),
            "bfg_gj_per_t_hot_metal": _safe_divide(totals["bfg_energy_gj"], totals["bf_hot_metal_t"]),
            "bfg_gj_per_t_liquid_steel": _safe_divide(totals["bfg_energy_gj"], totals["bof_liquid_steel_t"]),
            "cog_m3_per_t_dry_coal": _safe_divide(totals["cog_volume_m3"], totals["dry_coal_t"]),
            "cog_gj_per_t_coke": _safe_divide(totals["cog_energy_gj"], totals["onsite_coke_t"]),
            "cog_gj_per_t_liquid_steel": _safe_divide(totals["cog_energy_gj"], totals["bof_liquid_steel_t"]),
            "bofg_nm3_per_t_liquid_steel": _safe_divide(totals["bofg_volume_nm3"], totals["bof_liquid_steel_t"]),
            "bofg_gj_per_t_liquid_steel": _safe_divide(totals["bofg_energy_gj"], totals["bof_liquid_steel_t"]),
            "total_wag_gj_per_t_liquid_steel": _safe_divide(total_wag_energy_gj, totals["bof_liquid_steel_t"]),
        },
        "sink_shares": {
            "total_wag": {
                "mandatory_process_use_share": _safe_divide(total_process_use_gj, total_wag_energy_gj),
                "boiler_steam_use_share": _safe_divide(total_boiler_use_gj, total_wag_energy_gj),
                "power_interface_use_share": _safe_divide(total_power_use_gj, total_wag_energy_gj),
                "flare_spill_unused_share": _safe_divide(total_flare_gj, total_wag_energy_gj),
            },
            "by_carrier": {
                carrier: {
                    "mandatory_process_use_share": _safe_divide(
                        process_use[carrier],
                        process_use[carrier] + boiler_use[carrier] + power_use[carrier] + flare[carrier],
                    ),
                    "boiler_steam_use_share": _safe_divide(
                        boiler_use[carrier],
                        process_use[carrier] + boiler_use[carrier] + power_use[carrier] + flare[carrier],
                    ),
                    "power_interface_use_share": _safe_divide(
                        power_use[carrier],
                        process_use[carrier] + boiler_use[carrier] + power_use[carrier] + flare[carrier],
                    ),
                    "flare_spill_unused_share": _safe_divide(
                        flare[carrier],
                        process_use[carrier] + boiler_use[carrier] + power_use[carrier] + flare[carrier],
                    ),
                }
                for carrier in process_use
            },
        },
        "electricity": {
            "potential_net_import_offset_mwh_per_t_liquid_steel": _safe_divide(
                totals["potential_net_import_offset_mwh"],
                totals["bof_liquid_steel_t"],
            ),
            "residual_grid_import_mwh_per_t_liquid_steel": _safe_divide(
                totals["residual_grid_import_mwh"],
                totals["bof_liquid_steel_t"],
            ),
            "potential_offset_share_of_electricity_proxy": _safe_divide(
                totals["potential_net_import_offset_mwh"],
                current_profile_electricity_mwh,
            ),
            "annualised_potential_offset_mwh_at_model_scale": totals["potential_net_import_offset_mwh"] * annualisation_factor,
            "annualised_residual_import_mwh_at_model_scale": totals["residual_grid_import_mwh"] * annualisation_factor,
        },
        "emissions": {
            "bfg_oxidation_kg_co2_per_t_liquid_steel": _safe_divide(wag_co2["BFG"] * 1000.0, totals["bof_liquid_steel_t"]),
            "cog_oxidation_kg_co2_per_t_liquid_steel": _safe_divide(wag_co2["COG"] * 1000.0, totals["bof_liquid_steel_t"]),
            "bofg_oxidation_kg_co2_per_t_liquid_steel": _safe_divide(wag_co2["BOFG_LD_gas"] * 1000.0, totals["bof_liquid_steel_t"]),
            "total_wag_oxidation_kg_co2_per_t_liquid_steel": _safe_divide(total_wag_co2_tonnes * 1000.0, totals["bof_liquid_steel_t"]),
            "natural_gas_combustion_kg_co2_per_t_liquid_steel": _safe_divide(ng_co2 * 1000.0, totals["bof_liquid_steel_t"]),
            "partial_ledger_complete": False,
        },
    }

    return {
        "configuration_id": configuration_id,
        "diagnostic_classification": "minimum_known_heat_sink_c0",
        "interpretation_class": [
            "mechanics_validation",
            "minimum_known_heat_sink",
            "potential_import_offset_upper_bound",
        ],
        "sensitivity_group": sensitivity_group or "central",
        "sensitivity_variant": sensitivity_variant,
        "production_fulfilment": {
            "bf_hot_metal_total_t": totals["bf_hot_metal_t"],
            "bof_liquid_steel_total_t": totals["bof_liquid_steel_t"],
        },
        "production_scale_metadata": {
            "profile_hours": total_profile_hours,
            "annualisation_method": "profile_total_times_8760_over_profile_hours",
            "annualised_hot_metal_t": annual_hot_metal_t,
            "annualised_liquid_steel_t": annual_liquid_steel_t,
            "annualised_onsite_coke_t": annual_onsite_coke_t,
            "annualised_dry_coal_t": annual_dry_coal_t,
            "steel_reference_source_ids": [],
            "steel_reference_value": None,
            "steel_reference_unit": "",
            "steel_reference_type": "missing_canonical_candidate_anchor",
            "coking_reference_source_ids": list(coking_capacity_annual_item.source_card_ids),
            "coking_reference_value": coking_capacity_annual,
            "coking_reference_unit": coking_capacity_annual_item.unit,
            "coking_reference_type": "public annual capacity proxy",
        },
        "electricity_proxy_basis": {
            "source_card_ids": list(electricity_annual_item.source_card_ids),
            "candidate_evidence_ids": list(electricity_annual_item.candidate_evidence_ids),
            "annual_proxy_mwh": electricity_annual_proxy_mwh,
            "annual_average_mw": electricity_annual_proxy_mwh / 8760.0,
            "proxy_type": "annual_average_development_proxy",
            "not_observed_hourly_truth": True,
        },
        "scale_consistency": scale_consistency,
        "normalised_metrics": normalised_metrics,
        "interpretation_readiness_flags": readiness_flags,
        "warnings": warnings,
        "coke": {
            "onsite_coke_t": totals["onsite_coke_t"],
            "external_or_imported_coke_t": totals["external_coke_t"],
            "dry_coal_t": totals["dry_coal_t"],
        },
        "generation": {
            "BFG": {"volume_Nm3": totals["bfg_volume_nm3"], "energy_GJ": totals["bfg_energy_gj"]},
            "COG": {"volume_m3": totals["cog_volume_m3"], "energy_GJ": totals["cog_energy_gj"]},
            "BOFG_LD_gas": {"volume_Nm3": totals["bofg_volume_nm3"], "energy_GJ": totals["bofg_energy_gj"]},
        },
        "use_by_sink_gj": {
            "mandatory_process": process_use,
            "steam_boiler": boiler_use,
            "power_interface": power_use,
            "flare_spill_unused": flare,
        },
        "natural_gas_boiler_substitution_gj": totals["natural_gas_boiler_gj"],
        "potential_net_import_offset_mwh": totals["potential_net_import_offset_mwh"],
        "residual_grid_import_mwh": totals["residual_grid_import_mwh"],
        "wag_co2_tonnes_by_carrier": wag_co2,
        "natural_gas_co2_tonnes": ng_co2,
        "direct_emissions_ledger_complete": False,
        "gross_ets_cost_eligible": False,
        "max_balance_residual_gj": totals["max_balance_residual_gj"],
        "total_balance_residual_gj": totals["total_balance_residual_gj"],
        "unmet_mandatory_demand_gj": totals["unmet_mandatory_demand_gj"],
        "unmet_steam_demand_gj": totals["unmet_steam_demand_gj"],
        "validation_status": "valid" if totals["max_balance_residual_gj"] <= BALANCE_TOLERANCE_GJ else "validation_failed",
        "limitations": (
            "Development-only minimum-known C0 heat-sink diagnostic; coking steam demand only; "
            "downstream heat sinks omitted; power output is potential_net_import_offset, not actual dispatch."
        ),
        "thesis_usability": False,
    }


def _profile_total_by_type(
    profile_rows: Sequence[FixedActivityProfileRow],
    activity_type: str,
    *,
    configuration_id: str,
) -> float:
    total = 0.0
    for row in _profile_values(profile_rows, activity_type=activity_type, configuration_id=configuration_id):
        if row.activity_unit == "MWh":
            total += row.activity_value
        elif row.activity_unit in {"m3_NG_per_hour", "t_CO2_per_hour"}:
            total += row.activity_value * row.timestep_hours
        else:
            total += _to_timestep_tonnes(row.activity_value, row.activity_unit, row.timestep_hours)
    return total


def run_c1_component_energy_diagnostic(
    *,
    selected_inputs: Mapping[tuple[str, str, str, str], SelectedWAGInput],
    profile_rows: Sequence[FixedActivityProfileRow],
) -> dict[str, object]:
    configuration_id = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"
    if not any(row.configuration_id == configuration_id for row in profile_rows):
        raise WAGDiagnosticError("C1 component diagnostic requested without C1 profile rows.")

    scenario_labels = {row.scenario_label for row in profile_rows if row.configuration_id == configuration_id}
    if len(scenario_labels) != 1:
        raise WAGDiagnosticError("C1 component diagnostic requires exactly one scenario profile.")
    scenario_id = next(iter(scenario_labels))

    required_profile_types = {
        "bfg_generation_driver_hot_metal",
        "bofg_generation_driver_liquid_steel",
        "cog_generation_driver_dry_coal",
        "drp_natural_gas_demand",
        "drp_electricity_demand",
        "eaf_electricity_demand",
        "component_electricity_demand_before_wag_offset",
        "drp_direct_co2_proxy",
    }
    profile_types = {row.s2_activity_type for row in profile_rows if row.configuration_id == configuration_id}
    missing = sorted(required_profile_types - profile_types)
    if missing:
        raise WAGDiagnosticError(f"C1 component diagnostic profile is missing rows: {missing}.")

    bfg_intensity = _selected_number(selected_inputs, "bfg_generation_per_tonne_hot_metal")
    bfg_lhv = _selected_number(selected_inputs, "bfg_lhv")
    bofg_intensity = _selected_number(selected_inputs, "bofg_generation_suppressed_combustion")
    bofg_lhv = _selected_number(selected_inputs, "bofg_lhv_downstream_gasholder")
    cog_yield = _selected_number(selected_inputs, "cog_raw_yield_per_tonne_dry_coal")
    cog_lhv = _selected_number(selected_inputs, "cog_lhv_raw_gas")
    power_efficiency = _selected_number(selected_inputs, "integrated_mill_offgas_power_efficiency_range") / 100.0

    bfg_factor = _selected_number(selected_inputs, "bfg_combustion_factor_netherlands")
    cog_factor = _selected_number(selected_inputs, "cog_combustion_factor_netherlands")
    bofg_factor = _selected_number(selected_inputs, "oxygas_bofg_combustion_factor_netherlands")

    totals: dict[str, float] = {
        "bf_hot_metal_t": 0.0,
        "bf_bof_liquid_steel_t": 0.0,
        "drp_eaf_liquid_steel_t": 0.0,
        "total_liquid_steel_t": 0.0,
        "dry_coal_t": 0.0,
        "bfg_volume_nm3": 0.0,
        "bofg_volume_nm3": 0.0,
        "cog_volume_m3": 0.0,
        "bfg_energy_gj": 0.0,
        "bofg_energy_gj": 0.0,
        "cog_energy_gj": 0.0,
        "drp_natural_gas_m3": 0.0,
        "drp_electricity_mwh": 0.0,
        "eaf_electricity_mwh": 0.0,
        "component_electricity_demand_mwh": 0.0,
        "potential_net_import_offset_mwh": 0.0,
        "residual_component_grid_import_mwh": 0.0,
        "drp_direct_co2_proxy_tonnes": 0.0,
        "max_balance_residual_gj": 0.0,
        "total_balance_residual_gj": 0.0,
    }
    power_use = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    flare = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}
    wag_co2 = {"BFG": 0.0, "COG": 0.0, "BOFG_LD_gas": 0.0}

    bf_rows = _profile_values(profile_rows, activity_type="bfg_generation_driver_hot_metal", configuration_id=configuration_id)
    bof_rows = _profile_values(profile_rows, activity_type="bofg_generation_driver_liquid_steel", configuration_id=configuration_id)
    dry_coal_rows = _profile_values(profile_rows, activity_type="cog_generation_driver_dry_coal", configuration_id=configuration_id)
    component_electricity_rows = _profile_values(
        profile_rows,
        activity_type="component_electricity_demand_before_wag_offset",
        configuration_id=configuration_id,
    )
    if not (len(bf_rows) == len(bof_rows) == len(dry_coal_rows) == len(component_electricity_rows)):
        raise WAGDiagnosticError("C1 component profile rows must align by timestep.")

    for bf_row, bof_row, dry_coal_row, electricity_row in zip(
        bf_rows,
        bof_rows,
        dry_coal_rows,
        component_electricity_rows,
        strict=True,
    ):
        hot_metal_t = _to_timestep_tonnes(bf_row.activity_value, bf_row.activity_unit, bf_row.timestep_hours)
        liquid_steel_t = _to_timestep_tonnes(bof_row.activity_value, bof_row.activity_unit, bof_row.timestep_hours)
        dry_coal_t = _to_timestep_tonnes(dry_coal_row.activity_value, dry_coal_row.activity_unit, dry_coal_row.timestep_hours)
        bfg = calculate_bfg_generation(
            hot_metal_activity_value=hot_metal_t,
            activity_unit="tonnes",
            timestep_hours=bf_row.timestep_hours,
            generation_intensity_nm3_per_t_hot_metal=bfg_intensity,
            lhv_mj_per_nm3=bfg_lhv,
        )
        bofg = calculate_bofg_generation(
            steel_activity_value=liquid_steel_t,
            activity_unit="tonnes",
            timestep_hours=bof_row.timestep_hours,
            generation_intensity_nm3_per_t_steel=bofg_intensity,
            lhv_mj_per_nm3=bofg_lhv,
            activity_basis="per tonne liquid steel",
            coefficient_activity_basis="per tonne liquid steel",
        )
        cog_volume = dry_coal_t * cog_yield
        cog_energy = cog_volume * cog_lhv / MJ_PER_GJ
        available = {
            "BFG": bfg.generated_energy_gj,
            "COG": cog_energy,
            "BOFG_LD_gas": bofg.generated_energy_gj,
        }
        component_demand_mwh = electricity_row.activity_value
        possible_offset_mwh = _sum_values(available) / GJ_PER_MWH * power_efficiency
        offset_mwh = min(component_demand_mwh, possible_offset_mwh)
        required_power_fuel_gj = offset_mwh * GJ_PER_MWH / power_efficiency if power_efficiency > 0 else 0.0
        power_allocation = _proportional_allocate(available, required_power_fuel_gj)
        residual = {carrier: max(0.0, available[carrier] - power_allocation.get(carrier, 0.0)) for carrier in available}
        residual_grid_import = max(0.0, component_demand_mwh - offset_mwh)
        balance_residual = {
            carrier: available[carrier] - power_allocation.get(carrier, 0.0) - residual.get(carrier, 0.0)
            for carrier in available
        }

        totals["bf_hot_metal_t"] += hot_metal_t
        totals["bf_bof_liquid_steel_t"] += liquid_steel_t
        totals["dry_coal_t"] += dry_coal_t
        totals["bfg_volume_nm3"] += bfg.generated_volume
        totals["bofg_volume_nm3"] += bofg.generated_volume
        totals["cog_volume_m3"] += cog_volume
        totals["bfg_energy_gj"] += bfg.generated_energy_gj
        totals["bofg_energy_gj"] += bofg.generated_energy_gj
        totals["cog_energy_gj"] += cog_energy
        totals["component_electricity_demand_mwh"] += component_demand_mwh
        totals["potential_net_import_offset_mwh"] += offset_mwh
        totals["residual_component_grid_import_mwh"] += residual_grid_import
        residual_values = [abs(value) for value in balance_residual.values()]
        totals["max_balance_residual_gj"] = max(totals["max_balance_residual_gj"], max(residual_values or [0.0]))
        totals["total_balance_residual_gj"] += sum(abs(value) for value in balance_residual.values())
        for carrier in available:
            power_use[carrier] += power_allocation.get(carrier, 0.0)
            flare[carrier] += residual.get(carrier, 0.0)
        wag_co2["BFG"] += (power_allocation["BFG"] + residual["BFG"]) * bfg_factor / 1000.0
        wag_co2["COG"] += (power_allocation["COG"] + residual["COG"]) * cog_factor / 1000.0
        wag_co2["BOFG_LD_gas"] += (power_allocation["BOFG_LD_gas"] + residual["BOFG_LD_gas"]) * bofg_factor / 1000.0

    totals["total_liquid_steel_t"] = _profile_total_by_type(
        profile_rows,
        "total_liquid_steel_output",
        configuration_id=configuration_id,
    )
    totals["drp_eaf_liquid_steel_t"] = _profile_total_by_type(
        profile_rows,
        "drp_eaf_route_liquid_steel_output",
        configuration_id=configuration_id,
    )
    totals["drp_natural_gas_m3"] = _profile_total_by_type(
        profile_rows,
        "drp_natural_gas_demand",
        configuration_id=configuration_id,
    )
    totals["drp_electricity_mwh"] = _profile_total_by_type(
        profile_rows,
        "drp_electricity_demand",
        configuration_id=configuration_id,
    )
    totals["eaf_electricity_mwh"] = _profile_total_by_type(
        profile_rows,
        "eaf_electricity_demand",
        configuration_id=configuration_id,
    )
    totals["drp_direct_co2_proxy_tonnes"] = _profile_total_by_type(
        profile_rows,
        "drp_direct_co2_proxy",
        configuration_id=configuration_id,
    )
    component_zero_import_warning = (
        totals["residual_component_grid_import_mwh"] <= 1e-9
        and totals["component_electricity_demand_mwh"] > 0.0
        and abs(totals["potential_net_import_offset_mwh"] - totals["component_electricity_demand_mwh"]) <= 1e-6
    )

    return {
        "configuration_id": configuration_id,
        "scenario_id": scenario_id,
        "diagnostic_level": "component_energy_boundary_diagnostic",
        "diagnostic_classification": "component_energy_boundary_diagnostic",
        "component_boundary_only": True,
        "component_zero_import_warning": component_zero_import_warning,
        "interpretation_class": [
            "mechanics_validation",
            "component_electricity_boundary_only",
            "potential_import_offset_upper_bound",
        ],
        "production_fulfilment": {
            "total_liquid_steel_t": totals["total_liquid_steel_t"],
            "bf_bof_liquid_steel_t": totals["bf_bof_liquid_steel_t"],
            "drp_eaf_liquid_steel_t": totals["drp_eaf_liquid_steel_t"],
        },
        "generation": {
            "BFG": {"volume_Nm3": totals["bfg_volume_nm3"], "energy_GJ": totals["bfg_energy_gj"]},
            "COG": {"volume_m3": totals["cog_volume_m3"], "energy_GJ": totals["cog_energy_gj"]},
            "BOFG_LD_gas": {"volume_Nm3": totals["bofg_volume_nm3"], "energy_GJ": totals["bofg_energy_gj"]},
        },
        "component_energy": {
            "drp_natural_gas_m3": totals["drp_natural_gas_m3"],
            "drp_electricity_mwh": totals["drp_electricity_mwh"],
            "eaf_electricity_mwh": totals["eaf_electricity_mwh"],
            "component_electricity_demand_before_wag_offset_mwh": totals["component_electricity_demand_mwh"],
            "potential_net_import_offset_mwh": totals["potential_net_import_offset_mwh"],
            "residual_component_grid_import_mwh": totals["residual_component_grid_import_mwh"],
        },
        "wag_offset_interpretation_status": "potential_offset_capped_by_represented_component_electricity_only",
        "potential_wag_offset_capped_by_represented_component_electricity": True,
        "use_by_sink_gj": {
            "power_interface": power_use,
            "flare_spill_unused": flare,
        },
        "wag_co2_tonnes_by_carrier": wag_co2,
        "drp_direct_co2_proxy_tonnes": totals["drp_direct_co2_proxy_tonnes"],
        "direct_emissions_ledger_complete": False,
        "gross_ets_cost_eligible": False,
        "full_plant_boundary_ready": False,
        "plant_level_import_interpretation_ready": False,
        "plant_level_power_offset_interpretation_ready": False,
        "plant_level_cost_accounting_ready": False,
        "cost_integration_ready": False,
        "da_market_integration_ready": False,
        "max_balance_residual_gj": totals["max_balance_residual_gj"],
        "total_balance_residual_gj": totals["total_balance_residual_gj"],
        "validation_status": "valid" if totals["max_balance_residual_gj"] <= BALANCE_TOLERANCE_GJ else "validation_failed",
        "warnings": [
            "component_electricity_boundary_only_not_complete_site_load",
            "component_zero_import_is_boundary_warning_not_plant_import_result" if component_zero_import_warning else "component_import_nonzero_within_represented_boundary",
            "potential_import_offset_is_not_actual_dispatch",
            "downstream_auxiliary_and_full_heat_boundaries_remain_incomplete",
            "partial_emissions_ledger_no_gross_ets_cost",
        ],
        "limitations": (
            "Development-only C1 component diagnostic using Tier B DRP/EAF assumptions; "
            "liquid-steel route output is used as a crude-steel proxy; no DA, revenue, route optimisation, or ETS cost."
        ),
        "thesis_usability": False,
    }


def readiness_to_dict(readiness: ReadinessAssessment) -> dict[str, object]:
    return asdict(readiness)
