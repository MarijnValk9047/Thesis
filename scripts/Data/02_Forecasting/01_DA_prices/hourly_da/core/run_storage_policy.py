from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .storage import PREDICTION_PARQUET_COMPRESSION

FULL_RETENTION_RUN_LABELS: tuple[str, ...] = (
    "naive_benchmark",
    "lear_fs1_benchmark",
    "lear_fs2_benchmark",
    "lear_fs2_pruned_candidate_benchmark",
    "xgboost_fs1_benchmark",
    "xgboost_fs2_benchmark",
    "xgboost_fs2_pruned_candidate_benchmark",
    "prophet_benchmark",
    "fs1_model_comparison",
    "model_comparison",
    "model_comparison_fs2_pruned_candidate",
    "lear_fs3_combo_promoted_benchmark",
    "lear_fs3_combo_pruned_candidate_benchmark",
    "xgboost_fs3_combo_promoted_benchmark",
    "xgboost_fs3_combo_pruned_candidate_benchmark",
    "fs3_day1_only_lear_day1_crossborder_bundle_parent",
    "fs3_day1_only_xgboost_day1_crossborder_bundle_parent",
    "fs3_combo_promoted_confirm",
    "case_week_selection",
    "visual_case_weeks",
)

PREDICTION_ARTIFACT_STEMS: tuple[str, ...] = (
    "predictions_long",
    "predictions_scored",
)

LEGACY_LIGHT_ARCHIVE_DIRS: tuple[str, ...] = (
    "archived_post_phase_b",
)


@dataclass(frozen=True)
class StoragePolicySummary:
    complete_runs_seen: int
    kept_full_runs: int
    light_archived_runs: int
    converted_predictions_long_to_parquet: int
    deleted_artifacts: int
    bytes_before: int
    bytes_after: int

    @property
    def bytes_saved(self) -> int:
        return int(self.bytes_before - self.bytes_after)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["bytes_saved"] = int(self.bytes_saved)
        return payload


def run_label_from_run_id(run_id: str) -> str:
    parts = str(run_id).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_id)


def _run_root(output_root: Path) -> Path:
    return output_root / "runs"


def _complete_run_directories(root_dir: Path) -> list[Path]:
    if not root_dir.exists():
        return []
    return sorted(directory for directory in root_dir.iterdir() if directory.is_dir() and (directory / "run_summary.json").exists())


def _managed_complete_run_directories(output_root: Path) -> tuple[list[Path], list[Path]]:
    active_runs = _complete_run_directories(_run_root(output_root))
    legacy_runs: list[Path] = []
    for relative_dir in LEGACY_LIGHT_ARCHIVE_DIRS:
        legacy_runs.extend(_complete_run_directories(output_root / relative_dir))
    return active_runs, sorted(legacy_runs)


def _artifact_paths_for_stem(run_dir: Path, stem: str) -> list[Path]:
    return [
        run_dir / f"{stem}.parquet",
        run_dir / f"{stem}.csv",
    ]


def _directory_size_bytes(run_dir: Path) -> int:
    return sum(path.stat().st_size for path in run_dir.rglob("*") if path.is_file())


def _write_manifest(
    run_dir: Path,
    *,
    storage_tier: str,
    retained_prediction_artifacts: list[str],
    removed_prediction_artifacts: list[str],
) -> None:
    payload = {
        "managed_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name,
        "run_label": run_label_from_run_id(run_dir.name),
        "storage_tier": storage_tier,
        "retained_prediction_artifacts": retained_prediction_artifacts,
        "removed_prediction_artifacts": removed_prediction_artifacts,
        "full_retention_run_labels": list(FULL_RETENTION_RUN_LABELS),
        "prediction_artifact_policy": {
            "full_runs": ["predictions_long.parquet"],
            "light_archive_runs": [],
        },
    }
    (run_dir / "storage_policy.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _ensure_predictions_long_parquet(run_dir: Path) -> tuple[bool, list[str]]:
    csv_path = run_dir / "predictions_long.csv"
    parquet_path = run_dir / "predictions_long.parquet"
    removed_artifacts: list[str] = []
    converted = False

    if csv_path.exists() and not parquet_path.exists():
        frame = pd.read_csv(csv_path)
        frame.to_parquet(parquet_path, index=False, compression=PREDICTION_PARQUET_COMPRESSION)
        converted = True

    if csv_path.exists():
        csv_path.unlink()
        removed_artifacts.append(csv_path.name)

    return converted, removed_artifacts


def _remove_prediction_artifacts(run_dir: Path) -> list[str]:
    removed_artifacts: list[str] = []
    for stem in PREDICTION_ARTIFACT_STEMS:
        for artifact_path in _artifact_paths_for_stem(run_dir, stem):
            if artifact_path.exists():
                artifact_path.unlink()
                removed_artifacts.append(artifact_path.name)
    return removed_artifacts


def apply_default_storage_policy(output_root: Path) -> StoragePolicySummary:
    active_runs, legacy_runs = _managed_complete_run_directories(output_root)
    complete_runs = [*active_runs, *legacy_runs]
    latest_full_runs: dict[str, Path] = {}
    for run_dir in active_runs:
        run_label = run_label_from_run_id(run_dir.name)
        if run_label in FULL_RETENTION_RUN_LABELS:
            latest_full_runs[run_label] = run_dir

    bytes_before = 0
    bytes_after = 0
    converted_predictions_long_to_parquet = 0
    deleted_artifacts = 0
    kept_full_runs = 0
    light_archived_runs = 0

    for run_dir in complete_runs:
        bytes_before += _directory_size_bytes(run_dir)
        run_label = run_label_from_run_id(run_dir.name)
        keep_full = latest_full_runs.get(run_label) == run_dir
        removed_artifacts: list[str] = []
        retained_prediction_artifacts: list[str] = []

        if keep_full:
            kept_full_runs += 1
            converted, removed_from_conversion = _ensure_predictions_long_parquet(run_dir)
            if converted:
                converted_predictions_long_to_parquet += 1
            removed_artifacts.extend(removed_from_conversion)
            for artifact_path in _artifact_paths_for_stem(run_dir, "predictions_scored"):
                if artifact_path.exists():
                    artifact_path.unlink()
                    removed_artifacts.append(artifact_path.name)
            parquet_path = run_dir / "predictions_long.parquet"
            if parquet_path.exists():
                retained_prediction_artifacts.append(parquet_path.name)
            _write_manifest(
                run_dir,
                storage_tier="full",
                retained_prediction_artifacts=retained_prediction_artifacts,
                removed_prediction_artifacts=removed_artifacts,
            )
        else:
            light_archived_runs += 1
            removed_artifacts = _remove_prediction_artifacts(run_dir)
            _write_manifest(
                run_dir,
                storage_tier="light_archive",
                retained_prediction_artifacts=[],
                removed_prediction_artifacts=removed_artifacts,
            )

        deleted_artifacts += len(removed_artifacts)
        bytes_after += _directory_size_bytes(run_dir)

    return StoragePolicySummary(
        complete_runs_seen=len(complete_runs),
        kept_full_runs=kept_full_runs,
        light_archived_runs=light_archived_runs,
        converted_predictions_long_to_parquet=converted_predictions_long_to_parquet,
        deleted_artifacts=deleted_artifacts,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
    )


def format_storage_summary_lines(summary: StoragePolicySummary) -> list[str]:
    def _format_gb(value: int) -> str:
        return f"{value / (1024 ** 3):.3f} GB"

    return [
        "Storage policy applied.",
        f"Complete runs managed: {summary.complete_runs_seen}",
        f"Full runs kept: {summary.kept_full_runs}",
        f"Light-archived runs: {summary.light_archived_runs}",
        f"predictions_long conversions to Parquet: {summary.converted_predictions_long_to_parquet}",
        f"Prediction artifacts removed: {summary.deleted_artifacts}",
        f"Storage before: {_format_gb(summary.bytes_before)}",
        f"Storage after: {_format_gb(summary.bytes_after)}",
        f"Storage saved: {_format_gb(summary.bytes_saved)}",
    ]
