from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da import QuarterHourDAExtensionConfig, find_latest_canonical_counterfactual_run


def _fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = find_latest_canonical_counterfactual_run(config)
    if run_dir is None:
        return _fail("No canonical_v1 counterfactual evaluation run exists yet.")

    required_files = [
        "run_summary.json",
        "predictions_long.csv",
        "metrics_overall.csv",
        "backbone_comparison_metrics.csv",
        "extension_comparison_metrics.csv",
        "canonical_hourly_reconciliation_summary.json",
        "canonical_truth_source_manifest.json",
    ]
    missing = [name for name in required_files if not (run_dir / name).exists()]
    if missing:
        return _fail(f"Missing required counterfactual artifacts in {run_dir}: {missing}")

    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "canonical_truth_source_manifest.json").read_text(encoding="utf-8"))
    reconciliation = json.loads((run_dir / "canonical_hourly_reconciliation_summary.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(run_dir / "predictions_long.csv", low_memory=False)

    if bool(manifest.get("forecast_outputs_used")) or bool(manifest.get("optimisation_outputs_used")) or bool(
        manifest.get("economic_results_used_for_selection")
    ):
        return _fail("canonical_v1 manifest flags are inconsistent with the counterfactual firewall.")

    if not bool(reconciliation.get("passes_tolerance")):
        return _fail("canonical_v1 hourly reconciliation check did not pass tolerance.")

    if bool(run_summary.get("truth_source_is_observed_market")):
        return _fail("Run summary incorrectly labels canonical_v1 counterfactual truth as observed market truth.")

    expected_candidates = {"lear_fs3_pruned_candidate", "xgboost_fs3_pruned_candidate"}
    present_candidates = set(predictions["backbone_candidate_key"].astype(str).unique().tolist())
    if present_candidates != expected_candidates:
        return _fail(f"Unexpected frozen backbone candidate set: {sorted(present_candidates)}")

    expected_models = {"repeated_hourly_backbone", "mean_shape_deviation", "xgboost_deviation"}
    present_models = set(predictions["model"].astype(str).unique().tolist())
    if present_models != expected_models:
        return _fail(f"Unexpected quarter-hour extension model set: {sorted(present_models)}")

    if predictions["truth_source"].astype(str).nunique() != 1 or predictions["truth_source"].astype(str).iloc[0] != "canonical_v1_counterfactual":
        return _fail("Predictions are not consistently labelled as canonical_v1 counterfactual truth.")

    if predictions["target_truth_is_observed_market"].fillna(True).astype(bool).any():
        return _fail("Some prediction rows are incorrectly marked as observed-market truth.")

    print(f"[OK] Latest canonical_v1 counterfactual evaluation run: {run_dir}")
    print(f"[OK] Backbone candidates: {sorted(present_candidates)}")
    print(f"[OK] Quarter-hour extension models: {sorted(present_models)}")
    print(f"[OK] Reconciliation max abs error: {reconciliation['max_shared_hourly_actual_abs_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
