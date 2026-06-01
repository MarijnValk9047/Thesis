from __future__ import annotations

import argparse
import json

from quarterhour_da import (
    QuarterHourDAExtensionConfig,
    smoke_check_qh_phase3_endogenous_ablation,
    write_phase3_qh_fs1_ablation_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Phase 3 QH-FS1 endogenous feature-family ablation scaffolding artifacts.")
    parser.add_argument(
        "--include-existing-child-predictions",
        action="store_true",
        help="Include any pre-existing child prediction artifacts from the Phase 3 output root.",
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run smoke checks and print results without writing a new bundle.",
    )
    parser.add_argument(
        "--run-child-training",
        action="store_true",
        help="Execute heavy Phase 3B child training/evaluation for all planned QH-FS1 endogenous ablations.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = QuarterHourDAExtensionConfig()
    smoke = smoke_check_qh_phase3_endogenous_ablation(config)
    print(smoke.to_string(index=False))

    failed = smoke[smoke["status"].astype(str) != "pass"]
    if not failed.empty:
        raise RuntimeError(f"Phase 3 smoke checks failed: {failed['check_name'].tolist()}")

    if args.smoke_only:
        print("Smoke-only mode completed. No bundle was written.")
        return

    paths = write_phase3_qh_fs1_ablation_bundle(
        config,
        include_existing_child_predictions=bool(args.include_existing_child_predictions),
        run_child_training=bool(args.run_child_training),
    )
    summary = json.loads(paths.ablation_run_summary_json.read_text(encoding="utf-8"))
    print("Phase 3 endogenous ablation scaffold bundle written:")
    print(paths.run_dir)
    print("Run summary status:", summary.get("status"))
    print("Parent model count:", summary.get("parent_model_count"))
    print("Child model count:", summary.get("child_model_count"))
    print("Child prediction rows available:", summary.get("child_prediction_rows_available"))
    print("Heavy child training executed:", bool(summary.get("scope", {}).get("full_heavy_ablation_executed")))


if __name__ == "__main__":
    main()
