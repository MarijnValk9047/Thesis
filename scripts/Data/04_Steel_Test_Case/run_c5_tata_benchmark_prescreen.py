from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


STEEL_ROOT = Path(__file__).resolve().parent
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.c5_tata_benchmark_prescreen import DEFAULT_CONFIG_PATH, run_prescreen
from steel.c5_user_authorized_emulation_checkpoint4 import run_checkpoint4


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the C5 Tata benchmark analytical prescreen.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--forecast-run-root", default=None)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if config.get("mode") == "user_authorized_full_site_emulation_checkpoint4":
        if not args.forecast_run_root:
            parser.error("Checkpoint 4 requires --forecast-run-root")
        summary = run_checkpoint4(
            args.config,
            forecast_run_root=args.forecast_run_root,
            scratch_root=args.scratch_root,
            aggregate_only=args.aggregate_only,
        )
    else:
        summary = run_prescreen(args.config)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
