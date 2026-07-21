"""Run the pre-DAM steel operational-boundary closure."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bi_pre_dam_operational_boundary_closure import (
    repair_existing_audit_only,
    run_pre_dam_operational_boundary_closure,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    parser.add_argument("--repair-existing-audit", action="store_true")
    args = parser.parse_args()
    runner = (
        repair_existing_audit_only
        if args.repair_existing_audit
        else run_pre_dam_operational_boundary_closure
    )
    result = runner(
        **({"output_directory": args.output} if args.output else {})
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
