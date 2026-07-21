from __future__ import annotations

import argparse

from steel.s4_4c5p_au_linde_n2_wag_emissions_boundary import (
    run_linde_n2_wag_emissions_boundary_diagnostic,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the C1 Linde N2 and WAG/emissions boundary diagnostic.")
    parser.add_argument("--run-id", default=None, help="Unique local diagnostic run directory name.")
    args = parser.parse_args()
    kwargs = {"run_id": args.run_id} if args.run_id else {}
    result = run_linde_n2_wag_emissions_boundary_diagnostic(**kwargs)
    print(result["summary"])
