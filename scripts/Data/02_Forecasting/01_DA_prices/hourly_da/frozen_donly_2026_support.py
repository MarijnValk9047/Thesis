from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
from joblib import Parallel, delayed


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.lago_benchmark_data import load_lago_exogenous_frames
from hourly_da.core.lago_benchmark_features import build_lago_d_only_daily_matrix
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_lear_model import LagoLearModel, _subset_last_n_days, _target_timestamp_utc


MODEL_ID = "lear_strict_donly_1092_support_extension_2026"
FROZEN_MODEL_NAME = "lago_lear_247_imputed_x2_1092"
WINDOW_DAYS = 1092
MIN_TRAINING_DAYS = 365


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_historical_run() -> Path:
    return _repo_root().parent / (
        "Thesis/data/02_Forecasting/01_DA_prices/hourly_da/frozen_results/"
        "d_only_lago_lear_20260507/run_outputs/20260507_161622_lago_lear_six_year_benchmark"
    )


def _parse_args() -> argparse.Namespace:
    repo = _repo_root()
    final_root = repo / (
        "data/02_Forecasting/01_DA_prices/scenario_evaluation/strict_lear_dplus4_finalisation/"
        "20260729_strict_lear_dplus4_full_a03"
    )
    parser = argparse.ArgumentParser(
        description="Extend the frozen Strict LEAR D-only 1092 model to the fixed 2026 common support."
    )
    parser.add_argument("--historical-run", type=Path, default=_default_historical_run())
    parser.add_argument(
        "--price-bridge",
        type=Path,
        default=repo / "tmp/strict_lear_stage_20260729_strict_lear/hourly_price_bridge.csv",
    )
    parser.add_argument(
        "--staged-cleaned-root",
        type=Path,
        default=repo / "tmp/strict_lear_stage_20260729_strict_lear/cleaned",
    )
    parser.add_argument(
        "--dplus4-root",
        type=Path,
        default=final_root,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=final_root / "optimisation_inputs",
    )
    parser.add_argument("--overlap-days", type=int, default=3)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_frozen_matrix(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features = run_dir / "features"
    x = pd.read_parquet(features / "d_only_X.parquet")
    y = pd.read_parquet(features / "d_only_Y.parquet")
    meta = pd.read_parquet(features / "d_only_metadata.parquet")
    meta["delivery_local_date"] = pd.to_datetime(meta["delivery_local_date"], errors="raise").dt.date
    meta["forecast_origin_utc"] = pd.to_datetime(meta["forecast_origin_utc"], utc=True, errors="raise")
    return x, y, meta


def _load_frozen_predictions(run_dir: Path) -> pd.DataFrame:
    frame = pd.read_csv(run_dir / "predictions/predictions_long.csv", low_memory=False)
    frame = frame.loc[frame["model"].astype(str).eq(FROZEN_MODEL_NAME)].copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="raise")
    frame["target_delivery_local_date"] = pd.to_datetime(
        frame["target_delivery_local_date"], errors="raise"
    ).dt.date
    return frame


def _load_price_bridge(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    if "region" in frame.columns:
        frame = frame.loc[frame["region"].astype(str).eq("NL")].copy()
    required = {"timestamp_utc", "price_eur_per_mwh"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Price bridge is missing {sorted(missing)}")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    if "is_interpolated_value" in frame.columns:
        frame = frame.loc[~frame["is_interpolated_value"].fillna(False).astype(bool)].copy()
    return frame.sort_values("timestamp_utc").reset_index(drop=True)


def _build_refreshed_matrix(
    *, price_bridge: Path, staged_cleaned_root: Path, start_date: Any, end_exclusive: Any
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = replace(
        LagoLearBenchmarkConfig(),
        benchmark_start_local_date=pd.Timestamp(start_date).date(),
        benchmark_end_exclusive_local_date=pd.Timestamp(end_exclusive).date(),
        lago_windows_days=(WINDOW_DAYS,),
        x2_policy="res_a69_psr_sum",
        x2_missing_policy="impute_training_median",
        staged_cleaned_root=staged_cleaned_root.resolve(),
        allow_official_cleaned_fallback=False,
        allow_x2_aggregate_fallback=False,
    )
    exogenous = load_lago_exogenous_frames(config)
    x2 = exogenous.get("da_res_generation_forecast", pd.DataFrame())
    matrix = build_lago_d_only_daily_matrix(
        _load_price_bridge(price_bridge),
        exogenous.get("da_total_load_forecast", pd.DataFrame()),
        x2,
        config,
    )
    meta = matrix.metadata.copy()
    meta["delivery_local_date"] = pd.to_datetime(meta["delivery_local_date"], errors="raise").dt.date
    meta["forecast_origin_utc"] = pd.to_datetime(meta["forecast_origin_utc"], utc=True, errors="raise")
    return matrix.X, matrix.Y, meta, matrix.skipped_rows


def _combined_matrix(
    frozen_x: pd.DataFrame,
    frozen_y: pd.DataFrame,
    frozen_meta: pd.DataFrame,
    refreshed_x: pd.DataFrame,
    refreshed_y: pd.DataFrame,
    refreshed_meta: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if list(frozen_x.columns) != list(refreshed_x.columns):
        raise ValueError("Frozen and refreshed D-only feature schemas differ.")
    if list(frozen_y.columns) != list(refreshed_y.columns):
        raise ValueError("Frozen and refreshed D-only target schemas differ.")
    frozen_last = max(frozen_meta["delivery_local_date"])
    keep_new = refreshed_meta["delivery_local_date"].gt(frozen_last).to_numpy()
    x = pd.concat([frozen_x, refreshed_x.loc[keep_new]], ignore_index=True)
    y = pd.concat([frozen_y, refreshed_y.loc[keep_new]], ignore_index=True)
    meta = pd.concat([frozen_meta, refreshed_meta.loc[keep_new]], ignore_index=True)
    order = np.argsort(pd.to_datetime(meta["delivery_local_date"]).to_numpy())
    return x.iloc[order].reset_index(drop=True), y.iloc[order].reset_index(drop=True), meta.iloc[order].reset_index(drop=True)


def _predict_day(
    *, matrix: pd.DataFrame, feature_columns: list[str], delivery_day: Any, config: LagoLearBenchmarkConfig
) -> list[float]:
    delivery_day = pd.Timestamp(delivery_day).date()
    candidates = matrix.loc[matrix["delivery_local_date"].eq(delivery_day)]
    if len(candidates) != 1:
        raise ValueError(f"Expected one feature row for {delivery_day}, found {len(candidates)}")
    train = _subset_last_n_days(matrix, "delivery_local_date", delivery_day, WINDOW_DAYS)
    if train["delivery_local_date"].nunique() < MIN_TRAINING_DAYS:
        raise ValueError(f"Insufficient causal training support for {delivery_day}")
    x_test = candidates[feature_columns]
    def fit_hour(hour: int) -> float:
        y_col = f"y_h{hour:02d}"
        valid = pd.to_numeric(train[y_col], errors="coerce").notna()
        model = LagoLearModel(x2_missing_policy=config.x2_missing_policy)
        model.fit(train.loc[valid, feature_columns], pd.to_numeric(train.loc[valid, y_col], errors="raise"))
        if model.pipeline is None:
            raise RuntimeError(f"D-only fit failed for {delivery_day} hour {hour}: {model.fit_warning}")
        return float(model.predict(x_test)[0])

    return Parallel(n_jobs=8, prefer="threads")(delayed(fit_hour)(hour) for hour in range(1, 25))


def _support_origins(point_path: Path) -> pd.DataFrame:
    point = pd.read_parquet(point_path)
    point["forecast_origin_utc"] = pd.to_datetime(point["forecast_origin_utc"], utc=True, errors="raise")
    point["target_timestamp_utc"] = pd.to_datetime(point["target_timestamp_utc"], utc=True, errors="raise")
    lead_d = point.loc[pd.to_numeric(point["lead_day"], errors="raise").eq(0)].copy()
    lead_d["delivery_local_date"] = lead_d["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam").dt.date
    origins = lead_d[["forecast_origin_utc", "delivery_local_date"]].drop_duplicates()
    counts = lead_d.groupby("forecast_origin_utc")["target_timestamp_utc"].nunique()
    if len(origins) != 116 or not counts.eq(24).all():
        raise ValueError(f"Expected 116 complete 24-hour lead-D origins; found {len(origins)} origins and counts {counts.value_counts().to_dict()}")
    return origins.sort_values("forecast_origin_utc").reset_index(drop=True)


def _build_scenarios(donly_point: pd.DataFrame, d4_scenarios: pd.DataFrame, set_size: int) -> pd.DataFrame:
    source = d4_scenarios.loc[
        pd.to_numeric(d4_scenarios["lead_day"], errors="raise").eq(0)
        & pd.to_numeric(d4_scenarios["scenario_set_size"], errors="raise").eq(set_size)
    ].copy()
    source["forecast_origin_utc"] = pd.to_datetime(source["forecast_origin_utc"], utc=True, errors="raise")
    source["target_timestamp_utc"] = pd.to_datetime(source["target_timestamp_utc"], utc=True, errors="raise")
    anchors = donly_point.rename(columns={"point_forecast": "donly_point"})[
        ["forecast_origin_utc", "target_timestamp_utc", "donly_point"]
    ]
    merged = source.merge(anchors, on=["forecast_origin_utc", "target_timestamp_utc"], how="inner", validate="many_to_one")
    if len(merged) != len(source):
        raise ValueError(f"D-only scenario anchor merge lost {len(source) - len(merged)} rows for set {set_size}")
    innovation = merged["scenario_price"].astype(float) - merged["point_forecast"].astype(float)
    merged["point_forecast"] = merged["donly_point"].astype(float)
    merged["scenario_price"] = merged["donly_point"].astype(float) + innovation
    merged["model_id"] = MODEL_ID
    merged["granularity"] = "hourly"
    return merged[d4_scenarios.columns].sort_values(
        ["forecast_origin_utc", "target_timestamp_utc", "scenario_id"]
    ).reset_index(drop=True)


def main() -> None:
    args = _parse_args()
    started = perf_counter()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / "hourly_donly_point_forecasts.partial.parquet"
    point_path = args.dplus4_root.resolve() / "optimisation_inputs/hourly_point_forecasts.parquet"
    origins = _support_origins(point_path)

    frozen_x, frozen_y, frozen_meta = _load_frozen_matrix(args.historical_run.resolve())
    refresh_start = max(frozen_meta["delivery_local_date"]) + timedelta(days=1)
    refresh_end = max(origins["delivery_local_date"]) + timedelta(days=1)
    refreshed_x, refreshed_y, refreshed_meta, skips = _build_refreshed_matrix(
        price_bridge=args.price_bridge.resolve(),
        staged_cleaned_root=args.staged_cleaned_root.resolve(),
        start_date=refresh_start,
        end_exclusive=refresh_end,
    )
    x, y, meta = _combined_matrix(frozen_x, frozen_y, frozen_meta, refreshed_x, refreshed_y, refreshed_meta)
    matrix = pd.concat([meta, x, y], axis=1)
    config = replace(LagoLearBenchmarkConfig(), lago_windows_days=(WINDOW_DAYS,), x2_missing_policy="impute_training_median")

    existing = pd.read_parquet(checkpoint) if args.resume and checkpoint.exists() else pd.DataFrame()
    completed = set(pd.to_datetime(existing.get("forecast_origin_utc", pd.Series(dtype=str)), utc=True).tolist())
    rows = existing.to_dict(orient="records")
    for row in origins.to_dict(orient="records"):
        origin = pd.Timestamp(row["forecast_origin_utc"])
        if origin in completed:
            continue
        delivery_day = row["delivery_local_date"]
        values = _predict_day(matrix=matrix, feature_columns=list(x.columns), delivery_day=delivery_day, config=config)
        for hour, value in enumerate(values):
            rows.append(
                {
                    "model_id": MODEL_ID,
                    "granularity": "hourly",
                    "forecast_origin_utc": origin,
                    "target_timestamp_utc": _target_timestamp_utc(delivery_day, hour, config.local_timezone),
                    "lead_day": 0,
                    "point_forecast": value,
                }
            )
        pd.DataFrame(rows).to_parquet(checkpoint, index=False)

    point = pd.DataFrame(rows)
    point["forecast_origin_utc"] = pd.to_datetime(point["forecast_origin_utc"], utc=True, errors="raise")
    point["target_timestamp_utc"] = pd.to_datetime(point["target_timestamp_utc"], utc=True, errors="raise")
    point = point.sort_values(["forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)
    if len(point) != 116 * 24 or point.duplicated(["forecast_origin_utc", "target_timestamp_utc"]).any():
        raise ValueError(f"Invalid D-only point support: {point.shape}")

    frozen_predictions = _load_frozen_predictions(args.historical_run.resolve())
    overlap_days = sorted(frozen_predictions["target_delivery_local_date"].unique())[-int(args.overlap_days) :]
    overlap_rows: list[dict[str, Any]] = []
    for delivery_day in overlap_days:
        predicted = _predict_day(matrix=matrix, feature_columns=list(x.columns), delivery_day=delivery_day, config=config)
        reference = frozen_predictions.loc[
            frozen_predictions["target_delivery_local_date"].eq(delivery_day)
        ].sort_values("target_timestamp_utc")
        if len(reference) != 24:
            raise ValueError(f"Historical overlap day {delivery_day} has {len(reference)} reference rows")
        for hour, (new_value, old_value) in enumerate(zip(predicted, reference["y_pred"].astype(float).tolist())):
            overlap_rows.append(
                {
                    "delivery_local_date": str(delivery_day),
                    "hour": hour,
                    "new_prediction": new_value,
                    "frozen_prediction": old_value,
                    "absolute_difference": abs(new_value - old_value),
                }
            )
    overlap = pd.DataFrame(overlap_rows)
    max_overlap_diff = float(overlap["absolute_difference"].max()) if not overlap.empty else np.nan
    if not np.isfinite(max_overlap_diff) or max_overlap_diff > 1e-8:
        raise ValueError(f"Frozen overlap reproduction failed: max absolute difference={max_overlap_diff}")

    point_output = output_dir / "hourly_donly_point_forecasts.parquet"
    point.to_parquet(point_output, index=False)
    overlap.to_csv(output_dir / "hourly_donly_overlap_reproduction.csv", index=False)
    scenario_outputs: dict[str, str] = {}
    for set_size in (30, 10):
        source_path = args.dplus4_root.resolve() / f"optimisation_inputs/hourly_scenarios_{set_size}.parquet"
        scenarios = _build_scenarios(point, pd.read_parquet(source_path), set_size)
        output = output_dir / f"hourly_donly_scenarios_{set_size}.parquet"
        scenarios.to_parquet(output, index=False)
        scenario_outputs[str(set_size)] = str(output)

    manifest = {
        "model_id": MODEL_ID,
        "lineage_role": "support_extension_of_frozen_selected_model",
        "frozen_model_name": FROZEN_MODEL_NAME,
        "window_days": WINDOW_DAYS,
        "origin_count": int(point["forecast_origin_utc"].nunique()),
        "point_rows": int(len(point)),
        "support_start": str(min(origins["delivery_local_date"])),
        "support_end": str(max(origins["delivery_local_date"])),
        "historical_overlap_days": [str(value) for value in overlap_days],
        "historical_overlap_max_abs_difference": max_overlap_diff,
        "causal_training_rule": "last_1092_available_delivery_days_strictly_before_delivery_day",
        "scenario_rule": "frozen_D_anchor_plus_H-D4_lead-D_innovation",
        "undercoverage_warning_inherited": True,
        "runtime_seconds": perf_counter() - started,
        "inputs": {
            "historical_run": str(args.historical_run.resolve()),
            "price_bridge": str(args.price_bridge.resolve()),
            "staged_cleaned_root": str(args.staged_cleaned_root.resolve()),
            "dplus4_point": str(point_path),
        },
        "input_sha256": {
            "price_bridge": _sha256(args.price_bridge.resolve()),
            "dplus4_point": _sha256(point_path),
        },
        "outputs": {"point": str(point_output), "scenarios": scenario_outputs},
        "skipped_refresh_reason_counts": (
            skips["reason"].astype(str).value_counts().to_dict() if not skips.empty and "reason" in skips else {}
        ),
    }
    (output_dir / "hourly_donly_support_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if checkpoint.exists():
        checkpoint.unlink()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
