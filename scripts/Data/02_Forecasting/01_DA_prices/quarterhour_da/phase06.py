from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .phase05 import find_latest_phase05_run


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase06_milp_exports")


def find_latest_phase06_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase06_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _load_phase05_bundle(config: QuarterHourDAExtensionConfig) -> tuple[Path, dict[str, Any]]:
    phase05_run = find_latest_phase05_run(config)
    if phase05_run is None:
        raise FileNotFoundError("Phase 5 artifacts are required before Phase 6 can run.")
    bundle = {
        "run_summary": json.loads((phase05_run / "run_summary.json").read_text(encoding="utf-8")),
        "hourly_actuals": pd.read_csv(phase05_run / "hourly_actual_test_period.csv"),
        "hourly_forecasts": pd.read_csv(phase05_run / "hourly_forecast_selected_long.csv"),
        "flat_inputs": pd.read_csv(phase05_run / "counterfactual_flat_forecast_input_15min_long.csv"),
        "shape_inputs": pd.read_csv(phase05_run / "counterfactual_shape_forecast_input_15min_long.csv"),
        "realized": pd.read_csv(phase05_run / "counterfactual_realized_15min_long.csv", low_memory=False),
        "generation_summary": pd.read_csv(phase05_run / "counterfactual_generation_summary.csv"),
        "flat_summary": pd.read_csv(phase05_run / "counterfactual_flat_forecast_input_summary.csv"),
        "shape_summary": pd.read_csv(phase05_run / "counterfactual_shape_forecast_input_summary.csv"),
        "coverage_summary": pd.read_csv(phase05_run / "hourly_forecast_coverage_summary.csv"),
        "shape_model_summary": pd.read_csv(phase05_run / "shape_model_for_counterfactual_summary.csv"),
        "checks": pd.read_csv(phase05_run / "validation_checks.csv"),
    }
    return phase05_run, bundle


def _write_export_bundle(
    *,
    export_root: Path,
    artifact_name: str,
    frame: pd.DataFrame,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    artifact_slug = f"artifact_{hashlib.md5(artifact_name.encode('utf-8')).hexdigest()[:12]}"
    artifact_dir = export_root / artifact_slug
    artifact_dir.mkdir(parents=True, exist_ok=True)
    csv_path = artifact_dir / "data.csv"
    parquet_path = artifact_dir / "data.parquet"
    metadata_path = artifact_dir / "metadata.json"
    frame.to_csv(csv_path, index=False)
    frame.to_parquet(parquet_path, index=False)
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return {
        "artifact_name": artifact_name,
        "artifact_slug": artifact_slug,
        "artifact_dir": str(artifact_dir),
        "csv_path": str(csv_path),
        "parquet_path": str(parquet_path),
        "metadata_path": str(metadata_path),
        "row_count": int(frame.shape[0]),
    }


def _actual_hourly_export(hourly_actuals: pd.DataFrame) -> pd.DataFrame:
    frame = hourly_actuals.copy()
    return frame[
        [
            "timestamp_utc",
            "timestamp_local",
            "delivery_local_date",
            "local_hour_of_day",
            "price_eur_per_mwh",
            "hourly_anchor_price_eur_per_mwh",
            "gap_fix_action",
            "is_interpolated_value",
            "is_flagged_missing_value",
            "missing_datapoint_source",
            "source_type",
        ]
    ].rename(columns={"hourly_anchor_price_eur_per_mwh": "anchor_price_eur_per_mwh"})


def _forecast_hourly_export(hourly_forecasts: pd.DataFrame) -> pd.DataFrame:
    frame = hourly_forecasts.copy()
    frame["price_eur_per_mwh"] = pd.to_numeric(frame["y_pred"], errors="coerce")
    frame["actual_price_eur_per_mwh"] = pd.to_numeric(frame["y_true"], errors="coerce")
    return frame[
        [
            "candidate_key",
            "candidate_label",
            "role",
            "source_run_id",
            "source_run_label",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "target_timestamp_local",
            "delivery_local_date",
            "local_hour_of_day",
            "price_eur_per_mwh",
            "actual_price_eur_per_mwh",
            "lead_day",
            "lead_day_label",
            "source_type",
        ]
    ]


def _forecast_input_export(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    working["price_eur_per_mwh"] = pd.to_numeric(working["predicted_price_eur_per_mwh"], errors="coerce")
    return working[
        [
            "hourly_anchor_candidate_key",
            "candidate_label",
            "role",
            "source_run_id",
            "source_run_label",
            "timestamp_utc",
            "timestamp_local",
            "delivery_local_date",
            "hour_start_utc",
            "hour_start_local",
            "local_hour_of_day",
            "local_minute",
            "quarter_index",
            "price_eur_per_mwh",
            "hourly_anchor_price_eur_per_mwh",
            "delta_pred_adjusted",
            "shape_method",
            "scenario_variant",
            "source_type",
        ]
    ]


def _realized_export(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    working["price_eur_per_mwh"] = pd.to_numeric(working["predicted_price_eur_per_mwh"], errors="coerce")
    return working[
        [
            "timestamp_utc",
            "timestamp_local",
            "delivery_local_date",
            "hour_start_utc",
            "hour_start_local",
            "local_hour_of_day",
            "local_minute",
            "quarter_index",
            "price_eur_per_mwh",
            "hourly_anchor_price_eur_per_mwh",
            "sampled_delta_eur_per_mwh",
            "sampled_delta_source_hour_start_utc",
            "sampler_backoff_level",
            "scenario_variant",
            "shape_method",
            "source_type",
        ]
    ]


def _schema_check(artifact_name: str, frame: pd.DataFrame, required_columns: list[str]) -> dict[str, Any]:
    missing = [column for column in required_columns if column not in frame.columns]
    return {
        "artifact_name": artifact_name,
        "status": "pass" if not missing else "fail",
        "missing_columns": ",".join(missing),
    }


def run_phase06_milp_exports(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = config.phase06_runs_root / run_id
    export_root = run_dir / "milp_ready_exports"
    run_dir.mkdir(parents=True, exist_ok=True)
    export_root.mkdir(parents=True, exist_ok=True)

    phase05_run, bundle = _load_phase05_bundle(config)
    phase05_summary = bundle["run_summary"]
    shape_model_summary = bundle["shape_model_summary"].iloc[0].to_dict() if not bundle["shape_model_summary"].empty else {}
    export_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    created_at_utc = pd.Timestamp.now(tz="UTC").isoformat()

    actual_hourly_frame = _actual_hourly_export(bundle["hourly_actuals"])
    actual_hourly_metadata = {
        "creation_timestamp_utc": created_at_utc,
        "source_type": "actual_hourly",
        "frequency": "hourly",
        "period_start_local_date": str(actual_hourly_frame["delivery_local_date"].min()),
        "period_end_local_date": str(actual_hourly_frame["delivery_local_date"].max()),
        "observed_15min_data_range": {
            "start": phase05_summary["observed_shape_library_start"],
            "end": phase05_summary["observed_shape_library_end"],
        },
        "hourly_anchor_source": "actual_hourly",
        "shape_model_used": None,
        "feature_set_used": None,
        "train_validation_test_reference": None,
        "retraining_policy": None,
        "data_nature": "actual",
        "random_seed": None,
        "volatility_scenario": None,
        "hourly_mean_preservation_enforced": None,
        "maximum_hourly_mean_preservation_error": None,
        "average_hourly_mean_preservation_error": None,
        "notes": "Official hourly actual prices for the repo test period.",
        "thesis_grade_15min_actual_market_truth_authorized": "not_applicable_hourly",
    }
    export_info = _write_export_bundle(
        export_root=export_root,
        artifact_name="actual_hourly_official_test_period",
        frame=actual_hourly_frame,
        metadata=actual_hourly_metadata,
    )
    export_rows.append(
        {
            "artifact_name": export_info["artifact_name"],
            "path": export_info["parquet_path"],
            "csv_path": export_info["csv_path"],
            "metadata_path": export_info["metadata_path"],
            "frequency": "hourly",
            "period": f"{actual_hourly_metadata['period_start_local_date']} to {actual_hourly_metadata['period_end_local_date']}",
            "source_type": "actual_hourly",
            "anchor_type": "actual_hourly",
            "hourly_anchor_model_role_candidate": "",
            "shape_method": "",
            "scenario_count_if_applicable": "",
            "purpose": "Hourly realized benchmark for later MILP comparison.",
            "safe_to_use_for_forecast_validation": "yes",
            "thesis_grade_15min_actual_market_truth_authorized": "not_applicable_hourly",
            "row_count": export_info["row_count"],
            "warnings": "",
        }
    )
    schema_rows.append(_schema_check(export_info["artifact_name"], actual_hourly_frame, ["timestamp_utc", "price_eur_per_mwh", "source_type"]))

    for candidate_key, group in bundle["hourly_forecasts"].groupby("candidate_key", dropna=False):
        candidate_label = str(group["candidate_label"].iloc[0])
        role = str(group["role"].iloc[0])
        export_frame = _forecast_hourly_export(group)
        metadata = {
            "creation_timestamp_utc": created_at_utc,
            "source_type": "forecast_hourly",
            "frequency": "hourly",
            "period_start_local_date": str(export_frame["delivery_local_date"].min()),
            "period_end_local_date": str(export_frame["delivery_local_date"].max()),
            "observed_15min_data_range": {
                "start": phase05_summary["observed_shape_library_start"],
                "end": phase05_summary["observed_shape_library_end"],
            },
            "hourly_anchor_source": f"selected_hourly_candidate::{candidate_key}",
            "dynamic_hourly_model_label": candidate_label,
            "dynamic_hourly_model_role": role,
            "shape_model_used": None,
            "feature_set_used": None,
            "retraining_policy": "official_hourly_saved_artifact",
            "data_nature": "forecasted",
            "random_seed": None,
            "volatility_scenario": None,
            "hourly_mean_preservation_enforced": None,
            "maximum_hourly_mean_preservation_error": None,
            "average_hourly_mean_preservation_error": None,
            "notes": "Official saved hourly D-only forecast artifact. Coverage ends at the saved hourly benchmark boundary.",
            "thesis_grade_15min_actual_market_truth_authorized": "no",
        }
        export_info = _write_export_bundle(
            export_root=export_root,
            artifact_name=f"forecast_hourly__{role}__{candidate_key}",
            frame=export_frame,
            metadata=metadata,
        )
        export_rows.append(
            {
                "artifact_name": export_info["artifact_name"],
                "path": export_info["parquet_path"],
                "csv_path": export_info["csv_path"],
                "metadata_path": export_info["metadata_path"],
                "frequency": "hourly",
                "period": f"{metadata['period_start_local_date']} to {metadata['period_end_local_date']}",
                "source_type": "forecast_hourly",
                "anchor_type": "forecast_hourly",
                "hourly_anchor_model_role_candidate": f"{role}::{candidate_key}",
                "shape_method": "",
                "scenario_count_if_applicable": "",
                "purpose": "Hourly forecast anchor for later MILP comparison.",
                "safe_to_use_for_forecast_validation": "yes",
                "thesis_grade_15min_actual_market_truth_authorized": "no",
                "row_count": export_info["row_count"],
                "warnings": "Saved hourly D-only coverage stops before the last four local test days.",
            }
        )
        schema_rows.append(_schema_check(export_info["artifact_name"], export_frame, ["target_timestamp_utc", "price_eur_per_mwh", "source_type"]))

    for source_name, source_frame in (
        ("counterfactual_15min_flat_forecast_input", bundle["flat_inputs"]),
        ("counterfactual_15min_shape_forecast_input", bundle["shape_inputs"]),
    ):
        for candidate_key, group in source_frame.groupby("hourly_anchor_candidate_key", dropna=False):
            candidate_label = str(group["candidate_label"].iloc[0])
            role = str(group["role"].iloc[0])
            export_frame = _forecast_input_export(group)
            preservation = group.groupby("hour_start_utc")["hourly_mean_preservation_error"].first().abs()
            metadata = {
                "creation_timestamp_utc": created_at_utc,
                "source_type": source_name,
                "frequency": "15min",
                "period_start_local_date": str(export_frame["delivery_local_date"].min()),
                "period_end_local_date": str(export_frame["delivery_local_date"].max()),
                "observed_15min_data_range": {
                    "start": phase05_summary["observed_shape_library_start"],
                    "end": phase05_summary["observed_shape_library_end"],
                },
                "hourly_anchor_source": f"forecast_hourly::{candidate_key}",
                "dynamic_hourly_model_label": candidate_label,
                "dynamic_hourly_model_role": role,
                "shape_model_used": str(group["shape_method"].iloc[0]),
                "feature_set_used": shape_model_summary.get("feature_set"),
                "retraining_policy": shape_model_summary.get("retraining_policy"),
                "data_nature": "counterfactual_forecast_input",
                "random_seed": None,
                "volatility_scenario": "point_forecast",
                "hourly_mean_preservation_enforced": True,
                "maximum_hourly_mean_preservation_error": float(preservation.max()),
                "average_hourly_mean_preservation_error": float(preservation.mean()),
                "notes": "Counterfactual 15-minute forecast input for the pre-implementation hourly test period. Not valid as actual historical 15-minute forecast evidence.",
                "thesis_grade_15min_actual_market_truth_authorized": "no",
            }
            export_info = _write_export_bundle(
                export_root=export_root,
                artifact_name=f"{source_name}__{role}__{candidate_key}",
                frame=export_frame,
                metadata=metadata,
            )
            export_rows.append(
                {
                    "artifact_name": export_info["artifact_name"],
                    "path": export_info["parquet_path"],
                    "csv_path": export_info["csv_path"],
                    "metadata_path": export_info["metadata_path"],
                    "frequency": "15min",
                    "period": f"{metadata['period_start_local_date']} to {metadata['period_end_local_date']}",
                    "source_type": source_name,
                    "anchor_type": "forecast_hourly",
                    "hourly_anchor_model_role_candidate": f"{role}::{candidate_key}",
                    "shape_method": str(group["shape_method"].iloc[0]),
                    "scenario_count_if_applicable": "",
                    "purpose": "15-minute forecast input for later MILP comparison.",
                    "safe_to_use_for_forecast_validation": "no",
                    "thesis_grade_15min_actual_market_truth_authorized": "no",
                    "row_count": export_info["row_count"],
                    "warnings": "Counterfactual 15-minute forecast input built on the pre-implementation hourly test period.",
                }
            )
            schema_rows.append(_schema_check(export_info["artifact_name"], export_frame, ["timestamp_utc", "quarter_index", "price_eur_per_mwh", "source_type"]))

    for scenario_variant, group in bundle["realized"].groupby("scenario_variant", dropna=False):
        export_frame = _realized_export(group)
        preservation = group.groupby("hour_start_utc")["hourly_mean_preservation_error"].first().abs()
        metadata = {
            "creation_timestamp_utc": created_at_utc,
            "source_type": "counterfactual_15min_realized",
            "frequency": "15min",
            "period_start_local_date": str(export_frame["delivery_local_date"].min()),
            "period_end_local_date": str(export_frame["delivery_local_date"].max()),
            "observed_15min_data_range": {
                "start": phase05_summary["observed_shape_library_start"],
                "end": phase05_summary["observed_shape_library_end"],
            },
            "hourly_anchor_source": "actual_hourly",
            "dynamic_hourly_model_label": None,
            "dynamic_hourly_model_role": None,
            "shape_model_used": "empirical_block_sampler",
            "feature_set_used": None,
            "retraining_policy": "sampling_from_observed_post_implementation_shape_library",
            "data_nature": "counterfactual_realized",
            "random_seed": 42,
            "volatility_scenario": str(scenario_variant),
            "hourly_mean_preservation_enforced": True,
            "maximum_hourly_mean_preservation_error": float(preservation.max()),
            "average_hourly_mean_preservation_error": float(preservation.mean()),
            "notes": "Counterfactual realized 15-minute path anchored to actual hourly prices for the pre-implementation hourly test period.",
            "thesis_grade_15min_actual_market_truth_authorized": "no_legacy_phase06",
        }
        export_info = _write_export_bundle(
            export_root=export_root,
            artifact_name=f"counterfactual_15min_realized__{scenario_variant}",
            frame=export_frame,
            metadata=metadata,
        )
        export_rows.append(
            {
                "artifact_name": export_info["artifact_name"],
                "path": export_info["parquet_path"],
                "csv_path": export_info["csv_path"],
                "metadata_path": export_info["metadata_path"],
                "frequency": "15min",
                "period": f"{metadata['period_start_local_date']} to {metadata['period_end_local_date']}",
                "source_type": "counterfactual_15min_realized",
                "anchor_type": "actual_hourly",
                "hourly_anchor_model_role_candidate": "",
                "shape_method": "empirical_block_sampler",
                "scenario_count_if_applicable": "1",
                "purpose": "Counterfactual realized 15-minute path for later perfect-foresight and scenario MILP cases.",
                "safe_to_use_for_forecast_validation": "no",
                "thesis_grade_15min_actual_market_truth_authorized": "no_legacy_phase06",
                "row_count": export_info["row_count"],
                "warnings": "Pre-2025-10 15-minute realized paths are synthetic/counterfactual, not historical truth. They are not authorised actual market truth for thesis-grade runs; use frozen_actual_paths/canonical_v1 instead.",
            }
        )
        schema_rows.append(_schema_check(export_info["artifact_name"], export_frame, ["timestamp_utc", "quarter_index", "price_eur_per_mwh", "source_type"]))

    export_manifest = pd.DataFrame(export_rows).sort_values(["source_type", "artifact_name"]).reset_index(drop=True)
    export_manifest.to_csv(run_dir / "export_manifest.csv", index=False)

    schema_checks = pd.DataFrame(schema_rows)
    schema_checks.to_csv(run_dir / "export_schema_checks.csv", index=False)
    failed = schema_checks[schema_checks["status"].astype(str) == "fail"]
    if not failed.empty:
        raise ValueError(f"Phase 6 export schema checks failed: {failed['artifact_name'].tolist()}")

    run_summary = {
        "run_id": run_id,
        "phase": "phase06_milp_ready_exports",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "phase05_run_dir": str(phase05_run),
        "export_root": str(export_root),
        "artifact_count": int(export_manifest.shape[0]),
        "legacy_exploratory_only": True,
        "created_at_utc": created_at_utc,
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
