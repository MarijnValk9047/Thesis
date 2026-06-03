from __future__ import annotations

import json
import time
import warnings

import pandas as pd

from ..models.base import ForecastModel
from .config import HourlyDAPipelineConfig
from .external_features import ExternalFeatureStore, build_feature_context_for_origin
from .monitoring import FitTimeMonitor
from .schedule import build_target_schedule_for_origin, generate_forecast_origins


def run_walk_forward_for_split(
    canonical_frame: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    split_name: str,
    models: list[ForecastModel],
    run_id: str,
    external_feature_store: ExternalFeatureStore | None = None,
    origin_schedule: pd.DataFrame | None = None,
    progress_bar=None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions: list[pd.DataFrame] = []
    timing_rows: list[dict[str, object]] = []
    if origin_schedule is None:
        origin_schedule = generate_forecast_origins(config, split_name)
    monitors = {model.name: FitTimeMonitor(config.monitoring) for model in models}

    for origin_row in origin_schedule.to_dict(orient="records"):
        forecast_origin_utc = pd.Timestamp(origin_row["forecast_origin_utc"])
        delivery_start_local_date = pd.Timestamp(origin_row["delivery_start_local_date"]).date()

        history = canonical_frame[canonical_frame[config.known_at_col] <= forecast_origin_utc].copy()
        if history.empty:
            continue

        target_schedule = build_target_schedule_for_origin(config, delivery_start_local_date)
        out_of_split = target_schedule[target_schedule["dataset_split"] != split_name].copy()
        if not out_of_split.empty:
            raise RuntimeError(
                f"Target schedule for origin {forecast_origin_utc.isoformat()} crossed split boundaries. "
                "Origins must be generated only when the full D..D+4 local-delivery horizon stays inside the split."
            )

        target_frame = target_schedule.merge(
            canonical_frame[[config.timestamp_col, config.target_col, "is_observed_target"]].rename(
                columns={config.timestamp_col: "target_timestamp_utc"}
            ),
            on="target_timestamp_utc",
            how="left",
        )
        target_index_utc = pd.DatetimeIndex(target_frame["target_timestamp_utc"])
        feature_context = (
            build_feature_context_for_origin(external_feature_store, forecast_origin_utc)
            if external_feature_store is not None
            else None
        )

        for model in models:
            fit_started = time.perf_counter()
            model.fit(
                history=history,
                target_index_utc=target_index_utc,
                config=config,
                feature_context=feature_context,
            )
            fit_time_sec = time.perf_counter() - fit_started

            monitor_row = monitors[model.name].evaluate(fit_time_sec)
            if monitor_row["fit_time_warning"]:
                warning_message = (
                    f"{model.name} fit at {forecast_origin_utc.isoformat()} took {fit_time_sec:.2f}s "
                    f"(absolute={monitor_row['fit_time_warning_absolute']}, "
                    f"relative={monitor_row['fit_time_warning_relative']})."
                )
                warnings.warn(warning_message, RuntimeWarning)
            else:
                warning_message = ""

            predict_started = time.perf_counter()
            preds = model.predict(
                history=history,
                target_index_utc=target_index_utc,
                config=config,
                feature_context=feature_context,
            )
            predict_time_sec = time.perf_counter() - predict_started

            if not preds.index.equals(target_index_utc):
                preds = preds.reindex(target_index_utc)

            runtime_info = model.get_last_runtime_info()
            timing_row = {
                "run_id": run_id,
                "dataset_split": split_name,
                "model": model.name,
                "model_family": model.family,
                "fs_level": model.fs_level,
                "forecast_origin_utc": forecast_origin_utc.isoformat(),
                "fit_time_sec": fit_time_sec,
                "predict_time_sec": predict_time_sec,
                "warning_message": warning_message,
                "runtime_info_json": json.dumps(runtime_info, sort_keys=True),
            }
            timing_row.update(monitor_row)
            timing_rows.append(timing_row)

            model_predictions = target_frame.copy()
            model_predictions["run_id"] = run_id
            model_predictions["model"] = model.name
            model_predictions["model_family"] = model.family
            model_predictions["fs_level"] = model.fs_level
            model_predictions["dataset_split"] = split_name
            model_predictions["forecast_origin_utc"] = forecast_origin_utc
            model_predictions["y_true"] = model_predictions[config.target_col].where(
                model_predictions["is_observed_target"].fillna(False).astype(bool)
            )
            model_predictions["y_pred"] = preds.to_numpy(dtype=float)
            model_predictions["fit_time_sec"] = fit_time_sec
            model_predictions["predict_time_sec"] = predict_time_sec
            model_predictions["fit_time_warning"] = bool(monitor_row["fit_time_warning"])
            model_predictions["fit_time_warning_absolute"] = bool(monitor_row["fit_time_warning_absolute"])
            model_predictions["fit_time_warning_relative"] = bool(monitor_row["fit_time_warning_relative"])
            model_predictions["runtime_info_json"] = json.dumps(runtime_info, sort_keys=True)
            model_predictions = model_predictions[
                [
                    "run_id",
                    "model",
                    "model_family",
                    "fs_level",
                    "dataset_split",
                    "forecast_origin_utc",
                    "target_timestamp_utc",
                    "target_delivery_local_date",
                    "target_hour_local",
                    "target_known_at_utc",
                    "lead_day",
                    "lead_day_label",
                    "horizon_index",
                    "y_true",
                    "y_pred",
                    "is_observed_target",
                    "fit_time_sec",
                    "predict_time_sec",
                    "fit_time_warning",
                    "fit_time_warning_absolute",
                    "fit_time_warning_relative",
                    "runtime_info_json",
                ]
            ]
            predictions.append(model_predictions)
            if progress_bar is not None:
                if hasattr(progress_bar, "step"):
                    progress_bar.step(
                        increment=1,
                        split_name=split_name,
                        model_name=model.name,
                        forecast_origin_utc=forecast_origin_utc,
                    )
                else:
                    progress_bar.update(1)

    predictions_df = (
        pd.concat(predictions, ignore_index=True)
        .sort_values(["dataset_split", "model", "forecast_origin_utc", "target_timestamp_utc"])
        .reset_index(drop=True)
        if predictions
        else pd.DataFrame()
    )
    timing_df = (
        pd.DataFrame(timing_rows).sort_values(["dataset_split", "model", "forecast_origin_utc"]).reset_index(drop=True)
        if timing_rows
        else pd.DataFrame()
    )
    return predictions_df, timing_df, origin_schedule
