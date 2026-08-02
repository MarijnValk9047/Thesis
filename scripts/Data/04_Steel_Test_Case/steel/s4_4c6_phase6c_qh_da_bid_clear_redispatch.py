"""Thin Phase-6C wrapper around the shared hourly/QH C6 market engine."""

from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    CONFIGURATIONS,
    ENERGY_TOLERANCE_MWH,
    QH_GRID_CANONICAL_ID,
    QH_MODEL_ID,
    QH_POLICIES,
    STEEL_BID_GRID,
    Phase6BError,
    SteelActualPriceBundle,
    SteelPriceInformationBundle,
    SteelRedispatchResult,
    SteelRollingState,
    advance_steel_state,
    clear_hourly_da_bids,
    grid_sha256,
    load_qh_actual_prices,
    load_qh_oracle_prices,
    load_qh_price_information,
    load_phase6c_config,
    prepare_physical_context,
    run_phase6c,
    run_phase6c_smoke,
    solve_hourly_actual_redispatch,
    solve_hourly_da_bid_plan,
    validate_bid_monotonicity,
    validate_scenario_probabilities,
)


solve_qh_da_bid_plan = solve_hourly_da_bid_plan
clear_qh_da_bids = clear_hourly_da_bids
solve_qh_actual_redispatch = solve_hourly_actual_redispatch


__all__ = [
    "CONFIGURATIONS",
    "ENERGY_TOLERANCE_MWH",
    "QH_GRID_CANONICAL_ID",
    "QH_MODEL_ID",
    "QH_POLICIES",
    "STEEL_BID_GRID",
    "Phase6BError",
    "SteelActualPriceBundle",
    "SteelPriceInformationBundle",
    "SteelRedispatchResult",
    "SteelRollingState",
    "advance_steel_state",
    "clear_qh_da_bids",
    "grid_sha256",
    "load_qh_actual_prices",
    "load_qh_oracle_prices",
    "load_qh_price_information",
    "load_phase6c_config",
    "prepare_physical_context",
    "run_phase6c",
    "run_phase6c_smoke",
    "solve_qh_actual_redispatch",
    "solve_qh_da_bid_plan",
    "validate_bid_monotonicity",
    "validate_scenario_probabilities",
]
