from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from hydrogen.common_support import run_common_support_audit, write_common_support_outputs


DEFAULT_ARTIFACTS = [
    "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support",
    "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
    "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reselect exact-common-support validation and test weeks for the three-model hourly D-only hydrogen bidding study."
    )
    parser.add_argument(
        "--config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
        help="Path to the hydrogen config YAML.",
    )
    parser.add_argument(
        "--docs-dir",
        default="scripts/Data/03_Hydrogen_Test_Case/docs",
        help="Directory where CSV and Markdown outputs will be written.",
    )
    parser.add_argument(
        "--configs-dir",
        default="scripts/Data/03_Hydrogen_Test_Case/configs",
        help="Directory where the optional selected_weeks_common_support.yaml file will be written.",
    )
    parser.add_argument(
        "--artifacts",
        nargs="*",
        default=DEFAULT_ARTIFACTS,
        help="Artifact keys to audit. Defaults to the three thesis-grade hourly D-only candidates.",
    )
    args = parser.parse_args()

    result = run_common_support_audit(
        config=args.config,
        artifact_keys=[str(value) for value in args.artifacts],
    )
    output_paths = write_common_support_outputs(
        result,
        docs_dir=Path(args.docs_dir),
        configs_dir=Path(args.configs_dir),
    )
    summary = {
        "artifacts": [str(value) for value in args.artifacts],
        "validation_support_start": result.metadata["validation_support_start"],
        "validation_support_end": result.metadata["validation_support_end"],
        "validation_support_day_count": result.metadata["validation_support_day_count"],
        "test_support_start": result.metadata["test_support_start"],
        "test_support_end": result.metadata["test_support_end"],
        "test_support_day_count": result.metadata["test_support_day_count"],
        "eligible_validation_weeks": result.metadata["eligible_validation_weeks"],
        "eligible_test_weeks": result.metadata["eligible_test_weeks"],
        "selected_validation_week_labels": result.selected_weeks.loc[
            result.selected_weeks["period_type"] == "validation", "week_label"
        ].astype(str).tolist(),
        "selected_test_week_labels": result.selected_weeks.loc[
            result.selected_weeks["period_type"] == "test", "week_label"
        ].astype(str).tolist(),
        "output_paths": {key: str(path) for key, path in output_paths.items()},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
