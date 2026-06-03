#!/usr/bin/env python3
"""Validate frozen D-only Lago LEAR benchmark artifacts without retraining."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Dict, List


DEFAULT_FREEZE_ROOT = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/frozen_results/d_only_lago_lear_20260507"
)
TOL = 1e-9
SELECTED_MODEL = "lago_lear_247_imputed_x2_1092"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_float(value: str) -> float:
    return float(value)


def _is_nan_like(value: str) -> bool:
    v = (value or "").strip().lower()
    return v == "" or v == "nan"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-root", type=Path, default=DEFAULT_FREEZE_ROOT)
    args = parser.parse_args()

    freeze_root = args.freeze_root
    errors: List[str] = []

    manifest_path = freeze_root / "frozen_manifest.json"
    hashes_path = freeze_root / "file_hashes_sha256.csv"
    run_dir = freeze_root / "run_outputs" / "20260507_161622_lago_lear_six_year_benchmark"

    if not manifest_path.exists():
        errors.append(f"Missing manifest: {manifest_path}")
    if not hashes_path.exists():
        errors.append(f"Missing hash file: {hashes_path}")
    if not run_dir.exists():
        errors.append(f"Missing frozen run directory: {run_dir}")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 1) Verify copied files exist and hashes match.
    checked_files = 0
    with hashes_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel = row["relative_path"]
            expected = row["sha256"]
            file_path = freeze_root / rel
            if not file_path.exists():
                errors.append(f"Missing copied file: {rel}")
                continue
            actual = _sha256(file_path)
            if actual != expected:
                errors.append(f"SHA256 mismatch: {rel}")
            checked_files += 1

    # 2) Verify key metrics match manifest.
    metrics_path = run_dir / "metrics" / "metrics_by_reporting_level.csv"
    val_row: Dict[str, str] | None = None
    test_row: Dict[str, str] | None = None
    with metrics_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("model") != SELECTED_MODEL:
                continue
            if row.get("reporting_level") != "d_only":
                continue
            if row.get("dataset_split") == "validation":
                val_row = row
            elif row.get("dataset_split") == "test":
                test_row = row

    if val_row is None:
        errors.append("Missing validation d_only row for selected model in metrics_by_reporting_level.csv")
    if test_row is None:
        errors.append("Missing test d_only row for selected model in metrics_by_reporting_level.csv")

    def _check_metric(split_name: str, metric_name: str, row: Dict[str, str], expected: float) -> None:
        actual = _to_float(row[metric_name])
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=TOL):
            errors.append(
                f"Metric mismatch {split_name}.{metric_name}: expected={expected}, actual={actual}"
            )

    if val_row is not None:
        for m in ("mae", "rmse", "rmae"):
            _check_metric("validation", m, val_row, float(manifest["validation_metrics"][m]))
    if test_row is not None:
        for m in ("mae", "rmse", "rmae"):
            _check_metric("test", m, test_row, float(manifest["test_metrics"][m]))

    # 3) Verify feature_count is 247.
    variant_counts = run_dir / "features" / "variant_feature_counts.csv"
    feature_count = None
    with variant_counts.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("model_variant") == "LEAR_LAGO_247_IMPUTED_X2":
                feature_count = int(float(row["feature_count"]))
                break
    if feature_count != 247:
        errors.append(f"feature_count expected 247, got {feature_count}")

    # 4) Verify D-only rows: no D+ rows, no NaN y_pred, observed-target scoring.
    predictions_path = run_dir / "predictions" / "predictions_long.csv"
    all_lead_days = set()
    selected_lead_days = set()
    nan_y_pred_rows = 0
    observed_target_violations = 0
    with predictions_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        has_observed_col = "is_observed_target" in (reader.fieldnames or [])
        for row in reader:
            lead = int(float(row["lead_day"]))
            all_lead_days.add(lead)
            if row.get("model") == SELECTED_MODEL:
                selected_lead_days.add(lead)
            if _is_nan_like(row.get("y_pred", "")):
                nan_y_pred_rows += 1
            if has_observed_col:
                y_true_nan = _is_nan_like(row.get("y_true", ""))
                is_observed = (row.get("is_observed_target", "") or "").strip().lower() == "true"
                if (not y_true_nan) and (not is_observed):
                    observed_target_violations += 1

    if all_lead_days != {0}:
        errors.append(f"Predictions contain non-D lead days: {sorted(all_lead_days)}")
    if nan_y_pred_rows != 0:
        errors.append(f"Found NaN/empty y_pred rows: {nan_y_pred_rows}")
    if observed_target_violations != 0:
        errors.append(f"Found scored rows that are not observed targets: {observed_target_violations}")

    manifest_leads = set(int(x) for x in manifest.get("lead_day_values", []))
    if manifest_leads != selected_lead_days:
        errors.append(
            f"Manifest lead_day_values mismatch: manifest={sorted(manifest_leads)} actual_selected_model={sorted(selected_lead_days)}"
        )

    print(f"Checked files: {checked_files}")
    print(f"Detected lead days (all predictions): {sorted(all_lead_days)}")
    print(f"Selected model lead days: {sorted(selected_lead_days)}")
    print(f"Feature count: {feature_count}")

    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        return 1

    print("[PASS] Frozen D-only Lago artifacts validated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
