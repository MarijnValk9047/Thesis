"""Run the deterministic steel rolling production-feasibility smoke stage."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_ae_rolling_production_feasibility import run_rolling_production_feasibility


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--quota-per-execution-block-t", type=float, default=None)
    args = parser.parse_args()
    result = run_rolling_production_feasibility(
        **({"config_path": args.config} if args.config else {}),
        **({"output_root": args.output_root} if args.output_root else {}),
        **({"run_id_override": args.run_id} if args.run_id else {}),
        **(
            {"quota_per_execution_block_t_override": args.quota_per_execution_block_t}
            if args.quota_per_execution_block_t is not None
            else {}
        ),
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
