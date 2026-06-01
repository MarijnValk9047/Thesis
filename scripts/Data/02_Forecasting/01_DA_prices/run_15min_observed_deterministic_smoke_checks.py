from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da import QuarterHourDAExtensionConfig, find_latest_observed_deterministic_run


def _fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = find_latest_observed_deterministic_run(config)
    if run_dir is None:
        return _fail("No observed-market deterministic quarter-hour run exists yet.")

    required_files = [
        "run_summary.json",
        "predictions_long.csv",
        "metrics_overall.csv",
        "official_naive_reference.json",
        "scenario_generation_compatibility.json",
        "observed_target_coverage_summary.csv",
    ]
    missing = [name for name in required_files if not (run_dir / name).exists()]
    if missing:
        return _fail(f"Missing required artifacts in {run_dir}: {missing}")

    predictions = pd.read_csv(run_dir / "predictions_long.csv", low_memory=False)
    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    scenario_payload = json.loads((run_dir / "scenario_generation_compatibility.json").read_text(encoding="utf-8"))

    required_prediction_columns = {
        "model",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "y_true",
        "y_pred",
        "is_observed_target",
    }
    missing_prediction_columns = sorted(required_prediction_columns - set(predictions.columns))
    if missing_prediction_columns:
        return _fail(f"Prediction artifact is missing required columns: {missing_prediction_columns}")

    predictions["is_observed_target"] = predictions["is_observed_target"].fillna(False).astype(bool)
    non_observed_truth = predictions.loc[~predictions["is_observed_target"], "y_true"]
    if non_observed_truth.notna().any():
        return _fail("Found non-observed quarter-hour targets with non-null y_true values.")

    unique_schedule = predictions[
        ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "y_true", "is_observed_target"]
    ].drop_duplicates(subset=["dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
    if unique_schedule.duplicated(subset=["forecast_origin_utc", "target_timestamp_utc"]).any():
        return _fail("Duplicate target rows were found for the same forecast origin and quarter-hour target.")

    if not bool(scenario_payload.get("compatible")):
        return _fail("Scenario-generation compatibility payload reports incompatible artifacts.")

    if str(run_summary.get("resolution")) != "15min":
        return _fail("Run summary resolution is not 15min.")

    if bool(run_summary.get("mFRR_in_scope")):
        return _fail("Run summary incorrectly marks mFRR as in scope.")

    print(f"[OK] Latest observed-market deterministic quarter-hour run: {run_dir}")
    print(f"[OK] Unique scored schedule rows: {int(unique_schedule.shape[0])}")
    print(f"[OK] Observed schedule rows: {int(unique_schedule['y_true'].notna().sum())}")
    print("[OK] Non-observed targets keep y_true = NaN and scenario payload is compatible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
