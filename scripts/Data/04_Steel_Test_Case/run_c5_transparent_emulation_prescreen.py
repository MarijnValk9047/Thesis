"""Run the checkpoint-8 analytical KGF/PeFa emulation screen."""

from __future__ import annotations

import argparse

from steel.c5_transparent_emulation_prescreen import run_transparent_emulation_prescreen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    kwargs = {"config_path": args.config} if args.config else {}
    result = run_transparent_emulation_prescreen(**kwargs)
    print(result["output_directory"])
    print(result["summary"]["promotion_status"])


if __name__ == "__main__":
    main()
