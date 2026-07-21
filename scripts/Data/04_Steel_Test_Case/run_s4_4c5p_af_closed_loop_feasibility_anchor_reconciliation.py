"""Run closed-loop rolling feasibility and annual anchor reconciliation."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    run_closed_loop_feasibility_anchor_reconciliation,
    run_source_boundary_evidence_repair_family,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--paired-repair", action="store_true")
    parser.add_argument("--repair-stage", choices=("downstream", "generator", "electricity"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--ex-post-cost-accounting", action="store_true")
    parser.add_argument("--physical-parent", default=None)
    args = parser.parse_args()
    if args.ex_post_cost_accounting:
        if args.config or args.paired_repair or args.repair_stage or args.run_id:
            parser.error("ex-post cost accounting does not accept physical-run options")
        from steel.s4_4c5p_bc_ex_post_deterministic_cost_accounting import (
            run_ex_post_cost_accounting,
        )

        result = run_ex_post_cost_accounting(
            **(
                {"parent_run_directory": args.physical_parent}
                if args.physical_parent
                else {}
            ),
            **({"output_directory": args.output_root} if args.output_root else {}),
        )
    elif args.paired_repair:
        if not args.config:
            parser.error("--paired-repair requires --config")
        result = run_source_boundary_evidence_repair_family(
            config_path=args.config,
            **({"output_root": args.output_root} if args.output_root else {}),
            **({"repair_stage": args.repair_stage} if args.repair_stage else {}),
            **({"run_id": args.run_id} if args.run_id else {}),
        )
    else:
        result = run_closed_loop_feasibility_anchor_reconciliation(
            **({"config_path": args.config} if args.config else {}),
            **({"output_root": args.output_root} if args.output_root else {}),
        )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
