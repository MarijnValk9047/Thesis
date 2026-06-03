from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.lago_benchmark_data import audit_lago_data_coverage
from hourly_da.core.lago_benchmark_features import (
    EXOG_VALUE_COL,
    PRICE_VALUE_COL,
    _append_hour_vector,
    _day_slice,
    _ensure_local_columns,
    _is_complete_24h_day,
    _latest_known_snapshot,
    _resolve_x2_for_day,
    _vector_by_hour,
    _vector_by_hour_allow_missing,
    _weekday_dummies,
)
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_lear_model import LagoLearModel, _subset_last_n_days, _target_timestamp_utc
from hourly_da.core.lago_splits import LagoSplitConfig, build_split_days


FROZEN_RUN_DIR = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/frozen_results/"
    "d_only_lago_lear_20260507/run_outputs/20260507_161622_lago_lear_six_year_benchmark"
)
DEFAULT_OUTPUT_CSV = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/exports/"
    "lear_strict_donly_1092_test_year_dense/predictions_long.csv"
)
SELECTED_MODEL = "lago_lear_247_imputed_x2_1092"
SELECTED_WINDOW_DAYS = 1092


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a denser LEAR Strict D-only 1092 prediction export by reusing the frozen observed matrix "
            "and adding inference-only validation/test days that satisfy the strict no-leakage feature contract."
        )
    )
    parser.add_argument("--frozen-run-dir", type=Path, default=FROZEN_RUN_DIR)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--support-start-local-date", type=str, default="2023-10-01")
    parser.add_argument("--support-end-local-date", type=str, default="2025-09-30")
    parser.add_argument("--allow-official-cleaned-fallback", action="store_true")
    return parser.parse_args()


def _load_frozen_observed_matrix(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features_dir = run_dir / "features"
    x = pd.read_parquet(features_dir / "d_only_X.parquet")
    y = pd.read_parquet(features_dir / "d_only_Y.parquet")
    metadata = pd.read_parquet(features_dir / "d_only_metadata.parquet")
    metadata["delivery_local_date"] = pd.to_datetime(metadata["delivery_local_date"], errors="coerce").dt.date
    metadata["forecast_origin_utc"] = pd.to_datetime(metadata["forecast_origin_utc"], utc=True, errors="coerce")
    metadata["forecast_origin_local"] = pd.to_datetime(
        metadata["forecast_origin_local"],
        utc=True,
        errors="coerce",
    ).dt.tz_convert("Europe/Amsterdam")
    return x, y, metadata


def _load_existing_selected_predictions(run_dir: Path) -> pd.DataFrame:
    pred_path = run_dir / "predictions" / "predictions_long.csv"
    pred = pd.read_csv(pred_path, low_memory=False)
    pred = pred[pred["model"].astype(str) == SELECTED_MODEL].copy()
    pred["forecast_origin_utc"] = pd.to_datetime(pred["forecast_origin_utc"], utc=True, errors="coerce")
    pred["target_timestamp_utc"] = pd.to_datetime(pred["target_timestamp_utc"], utc=True, errors="coerce")
    pred["lead_day"] = pd.to_numeric(pred["lead_day"], errors="coerce").astype("Int64")
    pred["target_delivery_local_date"] = pd.to_datetime(pred["target_delivery_local_date"], errors="coerce").dt.date
    return pred


def _build_split_lookup() -> dict[date, str]:
    split_cfg = LagoSplitConfig(split_policy="thesis_official")
    config = replace(
        LagoLearBenchmarkConfig(),
        benchmark_start_local_date=split_cfg.thesis_official_train_start_local,
        benchmark_end_exclusive_local_date=split_cfg.thesis_official_test_end_local + timedelta(days=1),
    )
    split_days = build_split_days(config=config, split_config=split_cfg)
    split_days["delivery_local_date"] = pd.to_datetime(split_days["delivery_local_date"], errors="coerce").dt.date
    return {
        day: str(split)
        for day, split in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False)
        if pd.notna(day) and pd.notna(split)
    }


def _build_inference_features(
    *,
    config: LagoLearBenchmarkConfig,
    support_start: date,
    support_end: date,
    existing_days: set[date],
    feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bundle = audit_lago_data_coverage(config)
    price = _ensure_local_columns(bundle.price_frame, config)
    x1 = _ensure_local_columns(bundle.exogenous_frames["da_total_load_forecast"], config)
    x2_candidate = _ensure_local_columns(bundle.exogenous_frames["da_res_generation_forecast_by_psr"], config)
    x2_agg = _ensure_local_columns(bundle.exogenous_frames["da_generation_forecast"], config)

    x_rows: list[dict[str, Any]] = []
    y_rows: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []
    skip_rows: list[dict[str, Any]] = []

    for delivery_day in pd.date_range(support_start, support_end, freq="D").date:
        if config.dst_policy == "skip_non_24h_local_days" and config.expected_hours_for_local_day(delivery_day) != 24:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": "dst_non_24h_day"})
            continue
        if delivery_day in existing_days:
            continue

        origin_utc = config.forecast_origin_utc_for_delivery_day(delivery_day)
        try:
            x1_snapshot = _latest_known_snapshot(x1, origin_utc, allow_missing_known_at=config.allow_missing_known_at)
            x2_snapshot = _latest_known_snapshot(
                x2_candidate,
                origin_utc,
                allow_missing_known_at=config.allow_missing_known_at,
            )
            x2_agg_snapshot = (
                _latest_known_snapshot(x2_agg, origin_utc, allow_missing_known_at=True) if not x2_agg.empty else pd.DataFrame()
            )
        except ValueError as exc:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": f"known_at_error::{exc}"})
            continue

        lag_days = {
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_2": delivery_day - timedelta(days=2),
            "d_minus_3": delivery_day - timedelta(days=3),
            "d_minus_7": delivery_day - timedelta(days=7),
        }
        price_vectors: dict[str, list[float]] = {}
        skip_reason: str | None = None
        for lag_label, lag_day in lag_days.items():
            lag_slice = _day_slice(price, lag_day)
            if not _is_complete_24h_day(lag_slice):
                skip_reason = f"missing_price_{lag_label}"
                break
            lag_vector = _vector_by_hour(lag_slice, PRICE_VALUE_COL)
            if lag_vector is None:
                skip_reason = f"missing_price_vector_{lag_label}"
                break
            price_vectors[lag_label] = lag_vector
        if skip_reason is not None:
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": skip_reason})
            continue

        x1_vectors: dict[str, list[float]] = {}
        for x1_label, x1_day in {
            "d": delivery_day,
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_7": delivery_day - timedelta(days=7),
        }.items():
            x1_vector = _vector_by_hour_allow_missing(_day_slice(x1_snapshot, x1_day), EXOG_VALUE_COL)
            if x1_vector is None:
                skip_reason = f"missing_x1_{x1_label}"
                break
            x1_vectors[x1_label] = x1_vector
        if skip_reason is not None and skip_reason.startswith("missing_x1_"):
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": skip_reason})
            continue

        x2_vectors: dict[str, list[float]] = {}
        for x2_label, x2_day in {
            "d": delivery_day,
            "d_minus_1": delivery_day - timedelta(days=1),
            "d_minus_7": delivery_day - timedelta(days=7),
        }.items():
            x2_vector, _ = _resolve_x2_for_day(
                x2_snapshot,
                x2_agg_snapshot,
                x2_day,
                x2_policy=config.x2_policy,
                allow_aggregate_fallback=config.allow_x2_aggregate_fallback,
                x2_missing_policy=config.x2_missing_policy,
            )
            if x2_vector is None:
                skip_reason = f"missing_x2_{x2_label}"
                break
            x2_vectors[x2_label] = x2_vector
        if skip_reason is not None and skip_reason.startswith("missing_x2_"):
            skip_rows.append({"delivery_local_date": delivery_day.isoformat(), "reason": skip_reason})
            continue

        features: dict[str, float] = {}
        _append_hour_vector(features, "price_d_minus_1", price_vectors["d_minus_1"])
        _append_hour_vector(features, "price_d_minus_2", price_vectors["d_minus_2"])
        _append_hour_vector(features, "price_d_minus_3", price_vectors["d_minus_3"])
        _append_hour_vector(features, "price_d_minus_7", price_vectors["d_minus_7"])
        _append_hour_vector(features, "x1_load_fcst_d", x1_vectors["d"])
        _append_hour_vector(features, "x2_gen_fcst_d", x2_vectors["d"])
        _append_hour_vector(features, "x1_load_fcst_d_minus_1", x1_vectors["d_minus_1"])
        _append_hour_vector(features, "x1_load_fcst_d_minus_7", x1_vectors["d_minus_7"])
        _append_hour_vector(features, "x2_gen_fcst_d_minus_1", x2_vectors["d_minus_1"])
        _append_hour_vector(features, "x2_gen_fcst_d_minus_7", x2_vectors["d_minus_7"])
        features.update(_weekday_dummies(delivery_day))

        x_rows.append({column: features.get(column, pd.NA) for column in feature_columns})
        y_rows.append({f"y_h{hour:02d}": pd.NA for hour in range(1, 25)})
        meta_rows.append(
            {
                "delivery_local_date": delivery_day,
                "forecast_origin_utc": origin_utc,
                "forecast_origin_local": origin_utc.tz_convert(config.local_timezone),
            }
        )

    return pd.DataFrame(x_rows), pd.DataFrame(y_rows), pd.DataFrame(meta_rows), pd.DataFrame(skip_rows)


def _predict_missing_days(
    *,
    observed_x: pd.DataFrame,
    observed_y: pd.DataFrame,
    observed_metadata: pd.DataFrame,
    candidate_x: pd.DataFrame,
    candidate_metadata: pd.DataFrame,
    split_lookup: dict[date, str],
    config: LagoLearBenchmarkConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidate_x.empty or candidate_metadata.empty:
        return pd.DataFrame(), pd.DataFrame()

    observed_matrix = pd.concat(
        [
            observed_metadata.reset_index(drop=True),
            observed_x.reset_index(drop=True),
            observed_y.reset_index(drop=True),
        ],
        axis=1,
    )
    y_cols = [f"y_h{hour:02d}" for hour in range(1, 25)]
    pred_rows: list[dict[str, Any]] = []
    skip_rows: list[dict[str, Any]] = []

    candidate_frame = pd.concat([candidate_metadata.reset_index(drop=True), candidate_x.reset_index(drop=True)], axis=1)
    candidate_frame = candidate_frame.sort_values("delivery_local_date").reset_index(drop=True)
    for row in candidate_frame.to_dict(orient="records"):
        delivery_day = row["delivery_local_date"]
        dataset_split = split_lookup.get(delivery_day)
        if dataset_split not in {"validation", "test"}:
            continue

        train = _subset_last_n_days(observed_matrix, "delivery_local_date", delivery_day, SELECTED_WINDOW_DAYS)
        train_day_count = int(train["delivery_local_date"].nunique())
        if train_day_count < 365:
            skip_rows.append(
                {
                    "delivery_local_date": delivery_day.isoformat(),
                    "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]).isoformat(),
                    "reason": f"insufficient_training_days<{365}",
                }
            )
            continue

        x_test = pd.DataFrame([{column: row[column] for column in observed_x.columns}])
        preds_for_window: list[float] = []
        fit_failed = False
        for hour_idx, y_col in enumerate(y_cols, start=1):
            y_train = pd.to_numeric(train[y_col], errors="coerce")
            valid = y_train.notna()
            x_train = train.loc[valid, observed_x.columns]
            y_train = y_train.loc[valid]
            if x_train.shape[0] < 365:
                skip_rows.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]).isoformat(),
                        "reason": f"insufficient_rows_hour_{hour_idx:02d}",
                    }
                )
                fit_failed = True
                break
            model = LagoLearModel(x2_missing_policy=config.x2_missing_policy)
            model.fit(x_train, y_train)
            if model.pipeline is None:
                skip_rows.append(
                    {
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": pd.Timestamp(row["forecast_origin_utc"]).isoformat(),
                        "reason": model.fit_warning or f"model_fit_failed_hour_{hour_idx:02d}",
                    }
                )
                fit_failed = True
                break
            preds_for_window.append(float(model.predict(x_test)[0]))

        if fit_failed or len(preds_for_window) != 24:
            continue

        origin_utc = pd.Timestamp(row["forecast_origin_utc"])
        if origin_utc.tzinfo is None:
            origin_utc = origin_utc.tz_localize("UTC")
        else:
            origin_utc = origin_utc.tz_convert("UTC")
        for hour_zero_based in range(24):
            pred_rows.append(
                {
                    "forecast_origin_utc": origin_utc,
                    "target_timestamp_utc": _target_timestamp_utc(delivery_day, hour_zero_based, config.local_timezone),
                    "lead_day": 0,
                    "y_pred": float(preds_for_window[hour_zero_based]),
                    "model": SELECTED_MODEL,
                    "model_family": "LEAR",
                    "dataset_split": dataset_split,
                    "target_delivery_local_date": delivery_day,
                }
            )

    return pd.DataFrame(pred_rows), pd.DataFrame(skip_rows)


def _validate_export(frame: pd.DataFrame) -> dict[str, Any]:
    issues: list[str] = []
    if frame.empty:
        issues.append("export_is_empty")
    if frame.duplicated(subset=["forecast_origin_utc", "target_timestamp_utc"]).any():
        issues.append("duplicate_forecast_origin_target_pairs")
    if frame["forecast_origin_utc"].isna().any():
        issues.append("null_forecast_origin_utc")
    lead_values = sorted(frame["lead_day"].dropna().astype(int).unique().tolist()) if not frame.empty else []
    if lead_values != [0]:
        issues.append(f"unexpected_lead_days:{lead_values}")

    day_counts = (
        frame.groupby("target_delivery_local_date", dropna=False)["target_timestamp_utc"].nunique().sort_index()
        if not frame.empty
        else pd.Series(dtype=int)
    )
    bad_days = day_counts[day_counts != 24]
    if not bad_days.empty:
        issues.append(f"non_24h_export_days:{len(bad_days)}")

    split_summary: list[dict[str, Any]] = []
    if not frame.empty:
        for split_name, group in frame.groupby("dataset_split", dropna=False):
            delivery_days = sorted(pd.to_datetime(group["target_delivery_local_date"], errors="coerce").dt.date.dropna().unique().tolist())
            split_summary.append(
                {
                    "dataset_split": str(split_name),
                    "rows": int(group.shape[0]),
                    "complete_days": int(len(delivery_days)),
                    "delivery_day_min": delivery_days[0].isoformat() if delivery_days else None,
                    "delivery_day_max": delivery_days[-1].isoformat() if delivery_days else None,
                }
            )

    return {
        "row_count": int(frame.shape[0]),
        "unique_delivery_days": int(frame["target_delivery_local_date"].nunique()) if not frame.empty else 0,
        "issues": issues,
        "split_summary": split_summary,
    }


def main() -> None:
    args = _parse_args()
    frozen_run_dir = args.frozen_run_dir.resolve()
    output_csv = args.output_csv.resolve()
    support_start = pd.Timestamp(args.support_start_local_date).date()
    support_end = pd.Timestamp(args.support_end_local_date).date()

    observed_x, observed_y, observed_metadata = _load_frozen_observed_matrix(frozen_run_dir)
    existing = _load_existing_selected_predictions(frozen_run_dir)
    split_lookup = _build_split_lookup()

    existing = existing[
        existing["target_delivery_local_date"].between(support_start, support_end, inclusive="both")
    ].copy()
    existing["dataset_split"] = existing["target_delivery_local_date"].map(split_lookup)
    existing = existing[existing["dataset_split"].isin(["validation", "test"])].copy()
    existing_days = set(existing["target_delivery_local_date"].dropna().tolist())

    feature_config = replace(
        LagoLearBenchmarkConfig(),
        benchmark_start_local_date=split_lookup and min(split_lookup.keys()),
        benchmark_end_exclusive_local_date=max(split_lookup.keys()) + timedelta(days=1),
        x2_policy="res_forecast_if_available",
        x2_missing_policy="impute_training_median",
        allow_official_cleaned_fallback=bool(args.allow_official_cleaned_fallback),
    )
    candidate_x, candidate_y, candidate_meta, candidate_skips = _build_inference_features(
        config=feature_config,
        support_start=support_start,
        support_end=support_end,
        existing_days=existing_days,
        feature_columns=observed_x.columns.tolist(),
    )
    generated, generation_skips = _predict_missing_days(
        observed_x=observed_x,
        observed_y=observed_y,
        observed_metadata=observed_metadata,
        candidate_x=candidate_x,
        candidate_metadata=candidate_meta,
        split_lookup=split_lookup,
        config=feature_config,
    )

    existing_out = existing[
        [
            "forecast_origin_utc",
            "target_timestamp_utc",
            "lead_day",
            "y_pred",
            "model",
            "model_family",
            "dataset_split",
            "target_delivery_local_date",
        ]
    ].copy()
    export = pd.concat([existing_out, generated], ignore_index=True)
    export["forecast_origin_utc"] = pd.to_datetime(export["forecast_origin_utc"], utc=True, errors="coerce")
    export["target_timestamp_utc"] = pd.to_datetime(export["target_timestamp_utc"], utc=True, errors="coerce")
    export["lead_day"] = pd.to_numeric(export["lead_day"], errors="coerce").astype("Int64")
    export["target_delivery_local_date"] = pd.to_datetime(export["target_delivery_local_date"], errors="coerce").dt.date
    export = export.sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)

    validation = _validate_export(export)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_csv, index=False)

    summary = {
        "frozen_run_dir": str(frozen_run_dir),
        "output_csv": str(output_csv),
        "selected_model": SELECTED_MODEL,
        "selected_window_days": SELECTED_WINDOW_DAYS,
        "support_start_local_date": support_start.isoformat(),
        "support_end_local_date": support_end.isoformat(),
        "existing_rows_reused": int(existing_out.shape[0]),
        "existing_complete_days_reused": int(existing_out["target_delivery_local_date"].nunique()) if not existing_out.empty else 0,
        "candidate_rows_built": int(candidate_x.shape[0]),
        "generated_rows": int(generated.shape[0]),
        "generated_complete_days": int(generated["target_delivery_local_date"].nunique()) if not generated.empty else 0,
        "candidate_skip_reason_counts": candidate_skips["reason"].astype(str).value_counts().to_dict() if not candidate_skips.empty else {},
        "generation_skip_reason_counts": generation_skips["reason"].astype(str).value_counts().to_dict() if not generation_skips.empty else {},
        "validation": validation,
    }
    summary_path = output_csv.parent / "export_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))

    if validation["issues"]:
        raise SystemExit(f"Validation failed: {validation['issues']}")


if __name__ == "__main__":
    main()
