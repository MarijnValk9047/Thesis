from __future__ import annotations

import argparse
import json
from pathlib import Path

from steel.runner import run_from_config


DEFAULT_CONFIG = Path(__file__).resolve().parent / "configs" / "base_s2_toy_smoke.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the S2.0 steel toy deterministic material-flow smoke case.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--run-id", type=str, default=None)
    args = parser.parse_args()

    result = run_from_config(
        args.config,
        output_root_override=args.output_root,
        run_id_override=args.run_id,
    )
    print(json.dumps(
        {
            "run_id": result["run_id"],
            "run_dir": str(result["run_dir"]),
            "solver_name": result["solver_name"],
            "solver_status": result["solver_status"],
            "termination_condition": result["termination_condition"],
            "objective_value": result["objective_value"],
            "runtime_seconds": result["runtime_seconds"],
            "model_stats": result["model_stats"],
            "infeasibility_class": result["infeasibility_class"],
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
