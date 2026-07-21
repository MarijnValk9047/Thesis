"""Run the C5 pre-economics physical anchor sprint."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_ak_pre_economics_physical_anchor_sprint import run_pre_economics_physical_anchor_sprint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    result = run_pre_economics_physical_anchor_sprint(
        **({"output_dir": args.output_dir} if args.output_dir else {})
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
