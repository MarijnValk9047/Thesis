from __future__ import annotations

import argparse

from steel.s4_4c5p_at_c1_central_metallics_wag_steam_utility_reconciliation import (
    run_c1_central_metallics_wag_steam_utility_reconciliation,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the C1 central physical utility reconciliation diagnostic.")
    parser.add_argument("--run-id", default=None, help="Unique local diagnostic run directory name.")
    parser.add_argument("--config", default=None, help="Optional source-bounded metallics feasibility YAML.")
    parser.add_argument("--scenario-id", default=None, help="Scenario identifier in the metallics YAML.")
    parser.add_argument(
        "--hsm-rolling-electricity-mwh-per-t-hrc",
        type=float,
        default=None,
        help="Optional bounded sensitivity coefficient; it never changes the default development value.",
    )
    parser.add_argument(
        "--linde-n2-auxiliary-electricity-mwh-h",
        type=float,
        default=None,
        help="Optional explicit Linde/N2 context load; it is never a residual electricity plug.",
    )
    parser.add_argument(
        "--downstream-boundary-case",
        choices=("endogenous_6_75", "mer_site_product"),
        default="mer_site_product",
        help="Origin-tagged downstream case; imported slab is zero only in the all-endogenous stress case.",
    )
    args = parser.parse_args()
    kwargs = {"run_id": args.run_id} if args.run_id else {}
    if args.hsm_rolling_electricity_mwh_per_t_hrc is not None:
        kwargs["hsm_rolling_electricity_mwh_per_t_hrc_override"] = args.hsm_rolling_electricity_mwh_per_t_hrc
    if args.linde_n2_auxiliary_electricity_mwh_h is not None:
        kwargs["linde_n2_auxiliary_electricity_mwh_h"] = args.linde_n2_auxiliary_electricity_mwh_h
    if args.config:
        kwargs["metallics_config_path"] = args.config
    if args.scenario_id:
        kwargs["scenario_id"] = args.scenario_id
    kwargs["downstream_boundary_case"] = args.downstream_boundary_case
    result = run_c1_central_metallics_wag_steam_utility_reconciliation(**kwargs)
    print(result["summary"])
