from __future__ import annotations

from dataclasses import dataclass

from pyomo.environ import Constraint, Expression, NonNegativeReals, Objective, Var, minimize

from .downstream_scheduling_builder import DownstreamCaseOptions
from .downstream_scheduling_inputs import DownstreamAssumptions, load_downstream_assumptions
from .model import collect_model_stats
from .site_energy_economic_builder import (
    C0_CONFIGURATION_ID,
    C1_CONFIGURATION_ID,
    IntegratedCaseOptions,
    build_site_energy_economic_model,
)
from .site_energy_economic_inputs import GJ_PER_MWH, WAG_CARRIERS, load_site_energy_economic_assumptions
from .site_static_economics_inputs import (
    S32StaticEconomicsAssumptions,
    load_s3_2_static_economics_assumptions,
)


class S32StaticEconomicsBuildError(ValueError):
    """Raised when the S3.2 static economics layer cannot be attached safely."""


@dataclass(frozen=True)
class S32CaseOptions:
    smoke_case_id: str = "c0_static_economic_24h"
    downstream_options: DownstreamCaseOptions | None = None
    s3_1_sensitivity_case: str = "central"
    s3_2_sensitivity_case: str = "central"
    route_mode: str = "fixed"


def build_site_static_economics_model(
    *,
    configuration_id: str,
    horizon_hours: int = 24,
    assumptions: S32StaticEconomicsAssumptions | None = None,
    downstream_assumptions: DownstreamAssumptions | None = None,
    case_options: S32CaseOptions | None = None,
):
    case_options = case_options or S32CaseOptions()
    assumptions = assumptions or load_s3_2_static_economics_assumptions(
        sensitivity_case=case_options.s3_2_sensitivity_case
    )
    s3_1_assumptions = load_site_energy_economic_assumptions(
        sensitivity_case=case_options.s3_1_sensitivity_case
    )
    downstream_options = case_options.downstream_options or DownstreamCaseOptions(
        smoke_case_id=case_options.smoke_case_id
    )
    downstream_assumptions = downstream_assumptions or load_downstream_assumptions(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
    )
    model = build_site_energy_economic_model(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        assumptions=s3_1_assumptions,
        downstream_assumptions=downstream_assumptions,
        case_options=IntegratedCaseOptions(
            smoke_case_id=case_options.smoke_case_id,
            downstream_options=downstream_options,
            objective_mode="static_economic",
            sensitivity_case=case_options.s3_1_sensitivity_case,
        ),
    )
    _attach_s3_2_static_economics_layer(
        model,
        configuration_id=configuration_id,
        assumptions=assumptions,
        case_options=case_options,
    )
    return model


def _attach_s3_2_static_economics_layer(
    model,
    *,
    configuration_id: str,
    assumptions: S32StaticEconomicsAssumptions,
    case_options: S32CaseOptions,
) -> None:
    if not hasattr(model, "s3_1_metadata"):
        raise S32StaticEconomicsBuildError("S3.2 requires the S3.1 integrated energy/emissions layer.")
    if not assumptions.static_cost_ready:
        raise S32StaticEconomicsBuildError("S3.2 static economics requires selected static prices.")
    if not assumptions.route_cost_coverage_complete:
        raise S32StaticEconomicsBuildError("S3.2 route-cost coverage must be complete.")

    materials = assumptions.materials
    prices = assumptions.prices
    s3_1 = model.s3_1_assumptions
    if hasattr(model, "wag_power_base_dispatch_block"):
        model.wag_power_base_dispatch_block.deactivate()

    model.s3_2_assumptions = assumptions
    model.s3_2_case_options = case_options

    model.s3_2_wag_power_fraction_cap = Constraint(
        model.TIME,
        rule=lambda m, t: sum(m.wag_power_use_gj[carrier, t] for carrier in m.WAG_CARRIERS)
        <= prices.wag_power_residual_utilisation_fraction
        * sum(
            m.wag_generated_gj[carrier, t]
            - m.wag_process_use_gj[carrier, t]
            - m.wag_steam_boiler_use_gj[carrier, t]
            - m.wag_reheating_use_gj[carrier, t]
            - m.wag_utility_heat_use_gj[carrier, t]
            for carrier in m.WAG_CARRIERS
        ),
    )

    model.coking_coal_t = Expression(model.TIME, rule=lambda m, t: m.cog_dry_coal_driver_t[t])
    model.purchased_coke_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.purchased_coke_t_per_t_bof * m.bof_liquid_steel_output[t],
    )
    model.iron_ore_sinter_feed_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.iron_ore_sinter_feed_t_per_t_bof * m.bof_liquid_steel_output[t],
    )
    model.bf_pellets_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.bf_pellets_t_per_t_bof * m.bof_liquid_steel_output[t],
    )
    model.bof_scrap_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.bof_scrap_t_per_t_bof * m.bof_liquid_steel_output[t],
    )
    model.bf_bof_flux_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.bf_bof_flux_t_per_t_bof * m.bof_liquid_steel_output[t],
    )
    model.dr_pellets_t = Expression(
        model.TIME,
        rule=lambda m, t: s3_1.c1_route.pellets_required_per_t_steel * m.eaf_liquid_steel_output[t],
    )
    model.eaf_scrap_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.eaf_scrap_t_per_t_eaf * m.eaf_liquid_steel_output[t],
    )
    model.eaf_flux_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.eaf_flux_t_per_t_eaf * m.eaf_liquid_steel_output[t],
    )
    model.eaf_electrode_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.electrode_t_per_t_eaf * m.eaf_liquid_steel_output[t],
    )

    model.coking_coal_cost_eur = Expression(
        expr=sum(model.coking_coal_t[t] for t in model.TIME) * materials.coking_coal_price_eur_per_t
    )
    model.purchased_coke_cost_eur = Expression(
        expr=sum(model.purchased_coke_t[t] for t in model.TIME) * materials.purchased_coke_price_eur_per_t
    )
    model.iron_ore_sinter_feed_cost_eur = Expression(
        expr=sum(model.iron_ore_sinter_feed_t[t] for t in model.TIME)
        * materials.iron_ore_sinter_feed_price_eur_per_t
    )
    model.bf_pellets_cost_eur = Expression(
        expr=sum(model.bf_pellets_t[t] for t in model.TIME) * materials.bf_pellets_price_eur_per_t
    )
    model.scrap_cost_eur = Expression(
        expr=(
            sum(model.bof_scrap_t[t] for t in model.TIME)
            + sum(model.eaf_scrap_t[t] for t in model.TIME)
        )
        * materials.scrap_price_eur_per_t
    )
    model.flux_cost_eur = Expression(
        expr=(
            sum(model.bf_bof_flux_t[t] for t in model.TIME)
            + sum(model.eaf_flux_t[t] for t in model.TIME)
        )
        * materials.flux_price_eur_per_t
    )
    model.dr_pellets_cost_eur = Expression(
        expr=sum(model.dr_pellets_t[t] for t in model.TIME) * materials.dr_pellets_price_eur_per_t
    )
    model.eaf_electrode_cost_eur = Expression(
        expr=sum(model.eaf_electrode_t[t] for t in model.TIME) * materials.electrode_price_eur_per_t
    )
    model.total_material_cost_eur = Expression(
        expr=(
            model.coking_coal_cost_eur
            + model.purchased_coke_cost_eur
            + model.iron_ore_sinter_feed_cost_eur
            + model.bf_pellets_cost_eur
            + model.scrap_cost_eur
            + model.flux_cost_eur
            + model.dr_pellets_cost_eur
            + model.eaf_electrode_cost_eur
        )
    )

    model.electricity_cost_eur = Expression(
        expr=model.horizon_grid_import_mwh * prices.electricity_price_eur_per_mwh
    )
    model.natural_gas_cost_eur = Expression(
        expr=model.horizon_natural_gas_import_gj * prices.natural_gas_price_eur_per_gj
    )

    model.drp_ng_combustion_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: s3_1.wag.natural_gas_co2_t_per_gj * m.drp_natural_gas_gj[t],
    )
    model.drp_residual_process_co2_t = Var(model.TIME, domain=NonNegativeReals)
    model.drp_direct_co2_decomposition = Constraint(
        model.TIME,
        rule=lambda m, t: m.drp_ng_combustion_co2_t[t] + m.drp_residual_process_co2_t[t]
        == m.drp_direct_co2_proxy_t[t],
    )
    model.bf_bof_aggregate_direct_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: materials.bf_bof_aggregate_direct_co2_t_per_t_bof
        * m.bof_liquid_steel_output[t],
    )
    model.bf_bof_non_wag_residual_direct_co2_t = Var(model.TIME, domain=NonNegativeReals)
    model.bf_bof_direct_co2_decomposition = Constraint(
        model.TIME,
        rule=lambda m, t: m.bf_bof_non_wag_residual_direct_co2_t[t]
        + sum(m.wag_co2_t[carrier, t] for carrier in m.WAG_CARRIERS)
        == m.bf_bof_aggregate_direct_co2_t[t],
    )
    model.s3_2_total_direct_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: (
            sum(m.wag_co2_t[carrier, t] for carrier in m.WAG_CARRIERS)
            + m.drp_ng_combustion_co2_t[t]
            + m.drp_residual_process_co2_t[t]
            + m.bf_bof_non_wag_residual_direct_co2_t[t]
            + m.reheating_ng_co2_t[t]
            + m.utility_heat_ng_co2_t[t]
            + m.steam_ng_co2_t[t]
        ),
    )
    model.horizon_drp_ng_combustion_co2_t = Expression(
        expr=sum(model.drp_ng_combustion_co2_t[t] for t in model.TIME)
    )
    model.horizon_drp_residual_process_co2_t = Expression(
        expr=sum(model.drp_residual_process_co2_t[t] for t in model.TIME)
    )
    model.horizon_bf_bof_non_wag_residual_direct_co2_t = Expression(
        expr=sum(model.bf_bof_non_wag_residual_direct_co2_t[t] for t in model.TIME)
    )
    model.horizon_s3_2_total_direct_co2_t = Expression(
        expr=sum(model.s3_2_total_direct_co2_t[t] for t in model.TIME)
    )
    model.scope2_operational_co2_t = Expression(
        expr=model.horizon_grid_import_mwh * prices.scope2_operational_tco2_per_mwh
    )
    model.grid_lifecycle_co2e_sensitivity_t = Expression(
        expr=model.horizon_grid_import_mwh * prices.grid_lifecycle_tco2e_per_mwh
    )
    model.gross_direct_co2_cost_eur = Expression(
        expr=model.horizon_s3_2_total_direct_co2_t * prices.gross_co2_price_eur_per_t
    )
    model.total_static_operating_cost_eur = Expression(
        expr=(
            model.total_material_cost_eur
            + model.electricity_cost_eur
            + model.natural_gas_cost_eur
            + model.gross_direct_co2_cost_eur
        )
    )
    model.eur_per_t_final_product = Expression(
        expr=model.total_static_operating_cost_eur / model.s2_13_assumptions.final_product_target_t
    )
    model.reheating_heat_avoided_all_cold_reference_gj = Expression(
        expr=(
            model.horizon_final_product_output
            - model.horizon_reheated_tonnage
        )
        * s3_1.reheating_heat_gj_per_t_cold_slab
    )
    model.total_location_based_direct_plus_scope2_t = Expression(
        expr=model.horizon_s3_2_total_direct_co2_t + model.scope2_operational_co2_t
    )
    model.horizon_wag_power_use_gj = Expression(
        expr=sum(model.wag_power_use_gj[carrier, t] for carrier in model.WAG_CARRIERS for t in model.TIME)
    )

    if hasattr(model, "s3_1_diagnostic_objective"):
        model.s3_1_diagnostic_objective.deactivate()
    model.s3_2_static_cost_objective = Objective(
        expr=1_000_000.0 * model.final_product_overproduction + model.total_static_operating_cost_eur,
        sense=minimize,
    )

    model.s3_2_metadata = {
        "scope": "S3.2 static material energy carbon economics",
        "configuration_id": configuration_id,
        "smoke_case_id": case_options.smoke_case_id,
        "assumption_set_id": assumptions.assumption_set_id,
        "sensitivity_case": assumptions.sensitivity_case,
        "objective_type": "static_operating_cost",
        "static_cost_result": True,
        "route_mode": case_options.route_mode,
        "route_cost_coverage_complete": assumptions.route_cost_coverage_complete,
        "wag_power_interface_policy": "bounded_residual_wag_fraction_no_export",
        "wag_power_residual_utilisation_fraction": prices.wag_power_residual_utilisation_fraction,
        "scope2_operational_counted": True,
        "scope2_ets_costed": False,
        "complete_direct_emissions_ready": assumptions.complete_direct_emissions_ready,
        "market_logic_active": False,
        "settlement_logic_active": False,
        "shortfall_slack_active": False,
        "thesis_usability": assumptions.thesis_usability,
        "s2_s2_13_physical_logic_changed": False,
        "model_boundary": "fixed final hot-rolled-product fulfilment",
    }
    model.s3_2_model_stats = collect_model_stats(model)


def c1_endogenous_route_options(smoke_case_id: str) -> DownstreamCaseOptions:
    return DownstreamCaseOptions(
        smoke_case_id=smoke_case_id,
        route_share_mode="endogenous_bounded",
        bf_bof_share_lower=0.5471962,
        bf_bof_share_upper=0.67988981,
    )


__all__ = [
    "C0_CONFIGURATION_ID",
    "C1_CONFIGURATION_ID",
    "S32CaseOptions",
    "S32StaticEconomicsBuildError",
    "build_site_static_economics_model",
    "c1_endogenous_route_options",
]
