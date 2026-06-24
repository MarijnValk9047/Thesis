from __future__ import annotations

from dataclasses import dataclass

from pyomo.environ import Constraint, Expression, NonNegativeReals, Objective, Set, Var, minimize

from .downstream_scheduling_builder import DownstreamCaseOptions, build_downstream_scheduling_model
from .downstream_scheduling_inputs import DownstreamAssumptions, load_downstream_assumptions
from .model import collect_model_stats
from .site_energy_economic_inputs import (
    GJ_PER_MWH,
    WAG_CARRIERS,
    SiteEnergyEconomicAssumptions,
    load_site_energy_economic_assumptions,
)


C0_CONFIGURATION_ID = "C0_current_BF_BOF_reference"
C1_CONFIGURATION_ID = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"


class SiteEnergyEconomicBuildError(ValueError):
    """Raised when the S3.1 integrated accounting layer cannot be attached safely."""


@dataclass(frozen=True)
class IntegratedCaseOptions:
    smoke_case_id: str = "c0_integrated_central"
    downstream_options: DownstreamCaseOptions | None = None
    objective_mode: str = "energy_emissions_diagnostic"
    sensitivity_case: str = "central"


def _emission_factor(assumptions: SiteEnergyEconomicAssumptions, carrier: str) -> float:
    if carrier == "BFG":
        return assumptions.wag.bfg_co2_t_per_gj
    if carrier == "COG":
        return assumptions.wag.cog_co2_t_per_gj
    if carrier == "BOFG_LD_gas":
        return assumptions.wag.bofg_co2_t_per_gj
    raise SiteEnergyEconomicBuildError(f"Unsupported WAG carrier {carrier!r}.")


def build_site_energy_economic_model(
    *,
    configuration_id: str,
    horizon_hours: int = 24,
    assumptions: SiteEnergyEconomicAssumptions | None = None,
    downstream_assumptions: DownstreamAssumptions | None = None,
    case_options: IntegratedCaseOptions | None = None,
):
    case_options = case_options or IntegratedCaseOptions()
    assumptions = assumptions or load_site_energy_economic_assumptions(
        sensitivity_case=case_options.sensitivity_case
    )
    downstream_options = case_options.downstream_options or DownstreamCaseOptions(
        smoke_case_id=case_options.smoke_case_id
    )
    downstream_assumptions = downstream_assumptions or load_downstream_assumptions(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
    )
    model = build_downstream_scheduling_model(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        assumptions=downstream_assumptions,
        case_options=downstream_options,
    )
    _attach_energy_economic_layer(
        model,
        configuration_id=configuration_id,
        assumptions=assumptions,
        case_options=case_options,
    )
    return model


def _attach_energy_economic_layer(
    model,
    *,
    configuration_id: str,
    assumptions: SiteEnergyEconomicAssumptions,
    case_options: IntegratedCaseOptions,
) -> None:
    if not hasattr(model, "secondary_metallurgy_input") or not hasattr(model, "final_product_output"):
        raise SiteEnergyEconomicBuildError("S3.1 integration requires a built S2.13 downstream model.")
    if assumptions.wag.wag_power_base_mode != "potential_only_no_base_dispatch":
        raise SiteEnergyEconomicBuildError("Only potential-only WAG-to-power base dispatch is currently enabled.")

    model.WAG_CARRIERS = Set(initialize=WAG_CARRIERS, ordered=True)
    model.s3_1_assumptions = assumptions
    model.s3_1_case_options = case_options

    model.wag_process_use_gj = Var(model.WAG_CARRIERS, model.TIME, domain=NonNegativeReals)
    model.wag_steam_boiler_use_gj = Var(model.WAG_CARRIERS, model.TIME, domain=NonNegativeReals)
    model.wag_reheating_use_gj = Var(model.WAG_CARRIERS, model.TIME, domain=NonNegativeReals)
    model.wag_utility_heat_use_gj = Var(model.WAG_CARRIERS, model.TIME, domain=NonNegativeReals)
    model.wag_power_use_gj = Var(model.WAG_CARRIERS, model.TIME, domain=NonNegativeReals)
    model.flare_spill_gj = Var(model.WAG_CARRIERS, model.TIME, domain=NonNegativeReals)
    model.natural_gas_steam_gj = Var(model.TIME, domain=NonNegativeReals)
    model.natural_gas_reheating_gj = Var(model.TIME, domain=NonNegativeReals)
    model.natural_gas_utility_heat_gj = Var(model.TIME, domain=NonNegativeReals)
    model.grid_import_mwh = Var(model.TIME, domain=NonNegativeReals)

    model.bf_hot_metal_driver_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.bf_hot_metal_t_per_t_bof_liquid_steel
        * m.bof_liquid_steel_output[t],
    )
    model.cog_dry_coal_driver_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.dry_coal_t_per_t_hot_metal * m.bf_hot_metal_driver_t[t],
    )
    model.bfg_generated_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.bfg_gj_per_t_hot_metal * m.bf_hot_metal_driver_t[t],
    )
    model.cog_generated_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.cog_gj_per_t_dry_coal * m.cog_dry_coal_driver_t[t],
    )
    model.bofg_generated_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.bofg_gj_per_t_liquid_steel * m.bof_liquid_steel_output[t],
    )

    def _wag_generated_rule(m, carrier, t):
        if carrier == "BFG":
            return m.bfg_generated_gj[t]
        if carrier == "COG":
            return m.cog_generated_gj[t]
        return m.bofg_generated_gj[t]

    model.wag_generated_gj = Expression(model.WAG_CARRIERS, model.TIME, rule=_wag_generated_rule)
    model.total_wag_generated_gj = Expression(
        model.TIME,
        rule=lambda m, t: sum(m.wag_generated_gj[carrier, t] for carrier in m.WAG_CARRIERS),
    )

    model.bfg_specific_process_demand_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.bfg_hot_stove_gj_per_t_hot_metal * m.bf_hot_metal_driver_t[t],
    )
    model.cog_specific_process_demand_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.cog_hot_stove_pci_gj_per_t_hot_metal * m.bf_hot_metal_driver_t[t],
    )
    model.coking_underfire_process_demand_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.coking_underfire_gj_per_t_hot_metal * m.bf_hot_metal_driver_t[t],
    )
    model.coking_steam_useful_demand_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.coking_steam_useful_gj_per_t_hot_metal * m.bf_hot_metal_driver_t[t],
    )

    def _process_demand_rule(m, t):
        return (
            m.wag_process_use_gj["BFG", t]
            + m.wag_process_use_gj["COG", t]
            == m.bfg_specific_process_demand_gj[t]
            + m.cog_specific_process_demand_gj[t]
            + m.coking_underfire_process_demand_gj[t]
        )

    model.wag_process_demand_satisfied = Constraint(model.TIME, rule=_process_demand_rule)
    model.bfg_specific_process_minimum = Constraint(
        model.TIME,
        rule=lambda m, t: m.wag_process_use_gj["BFG", t] >= m.bfg_specific_process_demand_gj[t],
    )
    model.cog_specific_process_minimum = Constraint(
        model.TIME,
        rule=lambda m, t: m.wag_process_use_gj["COG", t] >= m.cog_specific_process_demand_gj[t],
    )
    model.bofg_process_use_zero = Constraint(
        model.TIME,
        rule=lambda m, t: m.wag_process_use_gj["BOFG_LD_gas", t] == 0.0,
    )

    model.wag_steam_boiler_balance = Constraint(
        model.TIME,
        rule=lambda m, t: (
            sum(m.wag_steam_boiler_use_gj[carrier, t] for carrier in m.WAG_CARRIERS)
            + m.natural_gas_steam_gj[t]
        )
        * assumptions.wag.boiler_efficiency
        == m.coking_steam_useful_demand_gj[t],
    )

    model.reheating_heat_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.reheating_heat_gj_per_t_cold_slab * m.reheat_cold_slab_input[t],
    )
    model.reheating_heat_balance = Constraint(
        model.TIME,
        rule=lambda m, t: (
            sum(m.wag_reheating_use_gj[carrier, t] for carrier in m.WAG_CARRIERS)
            + m.natural_gas_reheating_gj[t]
            == m.reheating_heat_gj[t]
        ),
    )
    model.downstream_light_side_utility_heat_demand_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.downstream_light_side_utility_heat_demand_gj_per_h,
    )
    model.downstream_light_side_utility_heat_balance = Constraint(
        model.TIME,
        rule=lambda m, t: (
            sum(m.wag_utility_heat_use_gj[carrier, t] for carrier in m.WAG_CARRIERS)
            + m.natural_gas_utility_heat_gj[t]
            == m.downstream_light_side_utility_heat_demand_gj[t]
        ),
    )
    model.downstream_light_side_minimum_ng = Constraint(
        model.TIME,
        rule=lambda m, t: m.natural_gas_utility_heat_gj[t]
        >= assumptions.downstream_light_side_minimum_ng_gj_per_h,
    )
    model.wag_power_output_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.wag_to_power_efficiency
        * sum(m.wag_power_use_gj[carrier, t] for carrier in m.WAG_CARRIERS)
        / GJ_PER_MWH,
    )
    model.wag_power_base_dispatch_block = Constraint(
        model.TIME,
        rule=lambda m, t: sum(m.wag_power_use_gj[carrier, t] for carrier in m.WAG_CARRIERS) == 0.0,
    )

    model.wag_carrier_balance = Constraint(
        model.WAG_CARRIERS,
        model.TIME,
        rule=lambda m, carrier, t: m.wag_generated_gj[carrier, t]
        == m.wag_process_use_gj[carrier, t]
        + m.wag_steam_boiler_use_gj[carrier, t]
        + m.wag_reheating_use_gj[carrier, t]
        + m.wag_utility_heat_use_gj[carrier, t]
        + m.wag_power_use_gj[carrier, t]
        + m.flare_spill_gj[carrier, t],
    )

    model.potential_wag_power_output_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.wag_to_power_efficiency
        * sum(m.flare_spill_gj[carrier, t] for carrier in m.WAG_CARRIERS)
        / GJ_PER_MWH,
    )

    model.secondary_metallurgy_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.secondary_metallurgy_electricity_mwh_per_t
        * m.secondary_metallurgy_output[t],
    )
    model.casting_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.casting_electricity_mwh_per_t * m.caster_input[t],
    )
    model.slab_handling_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.slab_handling_electricity_mwh_per_t * m.cast_slab_output[t],
    )
    model.dsp_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.dsp_electricity_mwh_per_t * m.dsp_hot_slab_input[t],
    )
    model.reheating_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.reheating_aux_electricity_mwh_per_t * m.reheat_cold_slab_input[t],
    )
    model.hsm_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.hsm_electricity_mwh_per_t * m.hsm_total_slab_input[t],
    )

    model.drp_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.c1_route.drp_electricity_mwh_per_t_steel * m.eaf_liquid_steel_output[t],
    )
    model.eaf_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.c1_route.eaf_electricity_mwh_per_t_steel * m.eaf_liquid_steel_output[t],
    )
    model.drp_natural_gas_m3 = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.c1_route.drp_natural_gas_m3_per_t_steel * m.eaf_liquid_steel_output[t],
    )
    model.drp_natural_gas_gj = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.natural_gas_energy_content_gj_per_m3 * m.drp_natural_gas_m3[t],
    )

    model.bof_oxygen_demand_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.bof_oxygen_t_per_t_bof * m.bof_liquid_steel_output[t],
    )
    model.eaf_oxygen_demand_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.c1_route.eaf_oxygen_t_per_t_dri
        * assumptions.c1_route.dri_required_per_t_steel
        * m.eaf_liquid_steel_output[t],
    )
    model.drp_oxygen_demand_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.c1_route.drp_oxygen_t_per_t_pellets
        * assumptions.c1_route.pellets_required_per_t_steel
        * m.eaf_liquid_steel_output[t],
    )
    model.oxygen_demand_t = Expression(
        model.TIME,
        rule=lambda m, t: m.bof_oxygen_demand_t[t] + m.eaf_oxygen_demand_t[t] + m.drp_oxygen_demand_t[t],
    )
    model.asu_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.asu_electricity_mwh_per_t_o2 * m.oxygen_demand_t[t],
    )
    model.residual_auxiliary_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.residual_auxiliary_electricity_mwh_per_t_final * m.final_product_output[t],
    )
    model.gross_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            m.secondary_metallurgy_electricity_mwh[t]
            + m.casting_electricity_mwh[t]
            + m.slab_handling_electricity_mwh[t]
            + m.dsp_electricity_mwh[t]
            + m.reheating_electricity_mwh[t]
            + m.hsm_electricity_mwh[t]
            + m.asu_electricity_mwh[t]
            + m.residual_auxiliary_electricity_mwh[t]
            + m.drp_electricity_mwh[t]
            + m.eaf_electricity_mwh[t]
        ),
    )
    model.grid_import_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.grid_import_mwh[t] + m.wag_power_output_mwh[t] == m.gross_electricity_mwh[t],
    )
    model.natural_gas_import_gj = Expression(
        model.TIME,
        rule=lambda m, t: (
            m.drp_natural_gas_gj[t]
            + m.natural_gas_steam_gj[t]
            + m.natural_gas_reheating_gj[t]
            + m.natural_gas_utility_heat_gj[t]
        ),
    )

    model.wag_co2_t = Expression(
        model.WAG_CARRIERS,
        model.TIME,
        rule=lambda m, carrier, t: _emission_factor(assumptions, carrier)
        * (
            m.wag_process_use_gj[carrier, t]
            + m.wag_steam_boiler_use_gj[carrier, t]
            + m.wag_reheating_use_gj[carrier, t]
            + m.wag_utility_heat_use_gj[carrier, t]
            + m.wag_power_use_gj[carrier, t]
            + m.flare_spill_gj[carrier, t]
        ),
    )
    model.wag_reheating_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: sum(
            _emission_factor(assumptions, carrier) * m.wag_reheating_use_gj[carrier, t]
            for carrier in m.WAG_CARRIERS
        ),
    )
    model.wag_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: sum(
            _emission_factor(assumptions, carrier) * m.flare_spill_gj[carrier, t]
            for carrier in m.WAG_CARRIERS
        ),
    )
    model.drp_direct_co2_proxy_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.c1_route.drp_direct_co2_t_per_t_steel * m.eaf_liquid_steel_output[t],
    )
    model.reheating_ng_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.natural_gas_co2_t_per_gj * m.natural_gas_reheating_gj[t],
    )
    model.utility_heat_ng_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.natural_gas_co2_t_per_gj * m.natural_gas_utility_heat_gj[t],
    )
    model.steam_ng_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: assumptions.wag.natural_gas_co2_t_per_gj * m.natural_gas_steam_gj[t],
    )
    model.total_direct_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: (
            sum(m.wag_co2_t[carrier, t] for carrier in m.WAG_CARRIERS)
            + m.drp_direct_co2_proxy_t[t]
            + m.reheating_ng_co2_t[t]
            + m.utility_heat_ng_co2_t[t]
            + m.steam_ng_co2_t[t]
        ),
    )

    model.horizon_gross_electricity_mwh = Expression(expr=sum(model.gross_electricity_mwh[t] for t in model.TIME))
    model.horizon_grid_import_mwh = Expression(expr=sum(model.grid_import_mwh[t] for t in model.TIME))
    model.horizon_wag_power_output_mwh = Expression(expr=sum(model.wag_power_output_mwh[t] for t in model.TIME))
    model.horizon_potential_wag_power_output_mwh = Expression(
        expr=sum(model.potential_wag_power_output_mwh[t] for t in model.TIME)
    )
    model.horizon_natural_gas_import_gj = Expression(expr=sum(model.natural_gas_import_gj[t] for t in model.TIME))
    model.horizon_drp_natural_gas_m3 = Expression(expr=sum(model.drp_natural_gas_m3[t] for t in model.TIME))
    model.horizon_reheating_heat_gj = Expression(expr=sum(model.reheating_heat_gj[t] for t in model.TIME))
    model.horizon_downstream_light_side_utility_heat_gj = Expression(
        expr=sum(model.downstream_light_side_utility_heat_demand_gj[t] for t in model.TIME)
    )
    model.horizon_natural_gas_utility_heat_gj = Expression(
        expr=sum(model.natural_gas_utility_heat_gj[t] for t in model.TIME)
    )
    model.horizon_total_wag_generated_gj = Expression(expr=sum(model.total_wag_generated_gj[t] for t in model.TIME))
    model.horizon_flare_spill_gj = Expression(
        expr=sum(model.flare_spill_gj[carrier, t] for carrier in model.WAG_CARRIERS for t in model.TIME)
    )
    model.horizon_total_direct_co2_t = Expression(expr=sum(model.total_direct_co2_t[t] for t in model.TIME))
    model.horizon_drp_direct_co2_proxy_t = Expression(expr=sum(model.drp_direct_co2_proxy_t[t] for t in model.TIME))
    model.horizon_wag_reheating_co2_t = Expression(expr=sum(model.wag_reheating_co2_t[t] for t in model.TIME))
    model.horizon_reheating_ng_co2_t = Expression(expr=sum(model.reheating_ng_co2_t[t] for t in model.TIME))
    model.horizon_utility_heat_ng_co2_t = Expression(expr=sum(model.utility_heat_ng_co2_t[t] for t in model.TIME))
    model.horizon_reheating_co2_t = Expression(
        expr=model.horizon_wag_reheating_co2_t + model.horizon_reheating_ng_co2_t
    )

    if hasattr(model, "primary_objective"):
        model.primary_objective.deactivate()
    if hasattr(model, "secondary_objective"):
        model.secondary_objective.deactivate()

    model.s3_1_diagnostic_objective = Objective(
        expr=(
            1_000_000.0 * model.final_product_overproduction
            + model.horizon_grid_import_mwh
            + 0.05 * model.horizon_natural_gas_import_gj
            + 0.001 * model.horizon_flare_spill_gj
            + 0.01 * model.horizon_startup_count
            + 0.001
            * sum(
                model.dsp_throughput_variation[t]
                + model.reheater_throughput_variation[t]
                + model.hsm_throughput_variation[t]
                for t in model.TIME
            )
        ),
        sense=minimize,
    )

    model.s3_1_metadata = {
        "scope": "S3.1 downstream-aware deterministic energy emissions static economic integration",
        "configuration_id": configuration_id,
        "smoke_case_id": case_options.smoke_case_id,
        "assumption_set_id": assumptions.assumption_set_id,
        "sensitivity_case": assumptions.sensitivity_case,
        "objective_mode": case_options.objective_mode,
        "monetary_values_ready": assumptions.monetary_values_ready,
        "missing_price_inputs": ";".join(assumptions.missing_price_inputs),
        "wag_allocation_policy": "process_first_then_steam_then_reheating_then_potential_power_then_flare",
        "wag_power_base_mode": assumptions.wag.wag_power_base_mode,
        "wag_driver_basis_status": "reconciled_s3_1_b",
        "bfg_driver": "bf_hot_metal_driver_t",
        "cog_driver": "cog_dry_coal_driver_t",
        "bofg_driver": "bof_liquid_steel_output",
        "scope2_electricity_counted": assumptions.scope2_electricity_counted,
        "complete_direct_emissions_ready": assumptions.complete_direct_emissions_ready,
        "ets_ready": assumptions.ets_ready,
        "market_logic_active": False,
        "shortfall_slack_active": False,
        "product_revenue_active": False,
        "thesis_usability": False,
    }
    model.s3_1_model_stats = collect_model_stats(model)
