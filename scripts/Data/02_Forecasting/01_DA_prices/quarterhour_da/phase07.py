from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.data_loading import build_canonical_hourly_frame, load_hourly_price_frame
from hourly_da.core.external_features import build_feature_context_for_origin, load_external_feature_store
from hourly_da.core.feature_value import instantiate_model_from_parent_context
from hourly_da.core.time_utils import known_at_utc_for_delivery_date, local_date_to_utc_bounds

from .config import QuarterHourDAExtensionConfig
from .phase02 import find_latest_phase02_run
from .phase03 import find_latest_phase03_run
from .phase04 import (
    ALL_MODEL_ORDER,
    _build_feature_frame,
    _build_prediction_frame,
    _check_split_nonoverlap,
    _example_days,
    _fit_lear,
    _fit_mean_shape,
    _fit_xgboost,
    _mae_by_hour,
    _performance_by_condition,
    _predict_mean_shape,
    _prepare_shape_target,
    _price_metrics,
    _shape_metrics,
    _train_regime_thresholds,
)
from .phase05 import _enrich_hourly_anchor_frame, _expand_hourly_to_quarters


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase07_realistic_track_a")


def find_latest_phase07_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase07_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _load_phase02_shape_target(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame]:
    phase02_run = find_latest_phase02_run(config)
    if phase02_run is None:
        raise FileNotFoundError("Phase 2 artifacts are required before Phase 7 can run.")
    frame = pd.read_csv(phase02_run / "shape_target_long.csv")
    if frame.empty:
        raise ValueError("Phase 2 shape target is empty.")
    return phase02_run, frame


def _load_phase03_selection(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame]:
    phase03_run = find_latest_phase03_run(config)
    if phase03_run is None:
        raise FileNotFoundError("Phase 3 artifacts are required before Phase 7 can run.")
    selected_anchor_models = pd.read_csv(phase03_run / "selected_anchor_models.csv")
    return phase03_run, selected_anchor_models


def _load_phase04_price_metrics(config: QuarterHourDAExtensionConfig) -> tuple[Path | None, pd.DataFrame]:
    from .phase04 import find_latest_phase04_run

    phase04_run = find_latest_phase04_run(config)
    if phase04_run is None:
        return None, pd.DataFrame()
    metrics_path = phase04_run / "reconstructed_price_metrics.csv"
    if not metrics_path.exists():
        return phase04_run, pd.DataFrame()
    return phase04_run, pd.read_csv(metrics_path)


def _hourly_extension_config(config: QuarterHourDAExtensionConfig, *, input_csv: Path) -> HourlyDAPipelineConfig:
    return HourlyDAPipelineConfig(
        input_csv=input_csv,
        market_area=config.market_area,
        business_timezone=config.business_timezone,
        train_start_local=date(2022, 1, 1),
        train_end_local=date(2025, 12, 31),
        validation_start_local=date(2026, 1, 1),
        validation_end_local=date(2026, 2, 28),
        test_start_local=date(2026, 3, 1),
        test_end_local=date(2026, 4, 30),
    )


def _build_hourly_bridge(shape_target: pd.DataFrame, *, config: QuarterHourDAExtensionConfig, run_dir: Path) -> tuple[Path, pd.DataFrame]:
    cutoff_local = pd.Timestamp(config.cleaning_cutoff_local_date).tz_localize("Europe/Brussels")
    cutoff_utc = cutoff_local.tz_convert("UTC")

    aggregated_prices = pd.read_csv(config.shared_all_regions_aggregated_csv, low_memory=False)
    aggregated_prices = aggregated_prices[aggregated_prices["region"].astype(str).isin(["BE", "DE", config.market_area])].copy()
    aggregated_prices["timestamp_utc"] = pd.to_datetime(aggregated_prices["timestamp_utc"], utc=True, errors="coerce")
    aggregated_prices["price_eur_per_mwh"] = pd.to_numeric(aggregated_prices["price_eur_per_mwh"], errors="coerce")
    aggregated_prices["resolution_minutes"] = pd.to_numeric(aggregated_prices["resolution_minutes"], errors="coerce")
    aggregated_prices = aggregated_prices.dropna(subset=["timestamp_utc"]).sort_values(["timestamp_utc", "region"]).reset_index(drop=True)

    official_hourly = aggregated_prices[
        (aggregated_prices["timestamp_utc"] < cutoff_utc) & (aggregated_prices["resolution_minutes"] == 60)
    ][["timestamp_utc", "region", "price_eur_per_mwh"]].copy()

    post_cutoff_quarters = aggregated_prices[
        (aggregated_prices["timestamp_utc"] >= cutoff_utc) & (aggregated_prices["resolution_minutes"] == 15)
    ][["timestamp_utc", "region", "price_eur_per_mwh"]].copy()
    post_cutoff_quarters["hour_start_utc"] = post_cutoff_quarters["timestamp_utc"].dt.floor("h")
    derived_hourly = (
        post_cutoff_quarters.groupby(["region", "hour_start_utc"], as_index=False)
        .agg(
            price_eur_per_mwh=("price_eur_per_mwh", "mean"),
            quarter_count=("timestamp_utc", "size"),
        )
        .rename(columns={"hour_start_utc": "timestamp_utc"})
    )
    derived_hourly = derived_hourly[derived_hourly["quarter_count"] == 4].copy()
    derived_hourly["bridge_source"] = "derived_hourly_mean_from_observed_15min"

    official_basic = official_hourly.copy()
    official_basic["bridge_source"] = "official_hourly_market"

    combined = pd.concat(
        [
            official_basic,
            derived_hourly[["timestamp_utc", "region", "price_eur_per_mwh", "bridge_source"]],
        ],
        ignore_index=True,
    )
    combined["timestamp_utc"] = pd.to_datetime(combined["timestamp_utc"], utc=True, errors="coerce")
    combined["price_eur_per_mwh"] = pd.to_numeric(combined["price_eur_per_mwh"], errors="coerce")
    combined = (
        combined.sort_values(["timestamp_utc", "region", "bridge_source"])
        .drop_duplicates(subset=["timestamp_utc", "region"], keep="last")
        .reset_index(drop=True)
    )
    bridge_csv = run_dir / "bridged_hourly_target_input_all_regions.csv"
    combined.to_csv(bridge_csv, index=False)

    summary = pd.DataFrame(
        [
            {
                "dataset": "official_hourly_market_all_regions",
                "start_timestamp_utc": official_basic["timestamp_utc"].min().isoformat(),
                "end_timestamp_utc": official_basic["timestamp_utc"].max().isoformat(),
                "rows": int(official_basic.shape[0]),
                "notes": "Original pre-cutoff hourly BE/DE/NL DAM series from the aggregated cleaned source.",
            },
            {
                "dataset": "derived_hourly_mean_from_observed_15min",
                "start_timestamp_utc": derived_hourly["timestamp_utc"].min().isoformat(),
                "end_timestamp_utc": derived_hourly["timestamp_utc"].max().isoformat(),
                "rows": int(derived_hourly.shape[0]),
                "notes": "Observed hourly mean from complete four-quarter blocks in the post-cutoff quarter-hour DAM market for BE, DE, and NL.",
            },
            {
                "dataset": "bridged_hourly_target_series_all_regions",
                "start_timestamp_utc": combined["timestamp_utc"].min().isoformat(),
                "end_timestamp_utc": combined["timestamp_utc"].max().isoformat(),
                "rows": int(combined.shape[0]),
                "notes": (
                    "Pre-cutoff hourly series from the original market plus post-cutoff hourly means derived "
                    "from complete quarter-hour blocks for BE, DE, and NL."
                ),
            },
        ]
    )
    return bridge_csv, summary


def _phase07_split_lookup(shape_target: pd.DataFrame) -> tuple[dict[date, str], pd.DataFrame]:
    split_frame = (
        shape_target[["delivery_local_date", "dataset_split"]]
        .drop_duplicates(subset=["delivery_local_date"])
        .sort_values("delivery_local_date")
        .reset_index(drop=True)
    )
    lookup = {
        pd.Timestamp(row["delivery_local_date"]).date(): str(row["dataset_split"])
        for row in split_frame.to_dict(orient="records")
    }
    return lookup, split_frame


def _load_selected_model_payload(selected_row: dict[str, Any]) -> dict[str, Any]:
    source_run_dir = Path(str(selected_row["source_run_dir"]))
    settings_summary = pd.read_csv(source_run_dir / "model_settings_summary.csv")
    internal_model_name = str(selected_row.get("internal_model_name") or "").strip()
    if internal_model_name:
        target = settings_summary[settings_summary["model"].astype(str) == internal_model_name].copy()
    else:
        target = settings_summary[
            (settings_summary["model_family"].astype(str) == str(selected_row["model_family"]))
            & (settings_summary["fs_level"].astype(str) == str(selected_row["fs_level"]))
        ].copy()
    if target.empty:
        raise RuntimeError(
            f"Could not resolve model settings row for candidate '{selected_row['candidate_key']}' from {source_run_dir}."
        )
    row = target.iloc[0].to_dict()
    settings_payload = json.loads(str(row["settings_json"]))
    return {
        "model_name": str(row["model"]),
        "model_family": str(row["model_family"]),
        "fs_level": str(row["fs_level"]),
        "settings_payload": settings_payload,
    }


def _required_feature_columns_from_payload(settings_payload: dict[str, Any]) -> dict[str, Any]:
    branch_mode = str(settings_payload.get("branch_mode") or "")
    if branch_mode == "d_only_vs_guidance":
        d_only_payload = dict(settings_payload.get("d_only_model_settings") or {})
        experiment_payload = dict(d_only_payload.get("fs3_experiment") or {})
        return {
            "branch_mode": branch_mode,
            "branch_scope": "d_only",
            "direct_columns": tuple(str(value) for value in experiment_payload.get("direct_columns", ()) or ()),
            "lagged_columns": tuple(str(value) for value in experiment_payload.get("lagged_columns", ()) or ()),
            "lag_hours": tuple(int(value) for value in experiment_payload.get("lag_hours", ()) or ()),
        }
    experiment_payload = dict(settings_payload.get("fs3_experiment") or {})
    return {
        "branch_mode": branch_mode or "single_model",
        "branch_scope": "single_model",
        "direct_columns": tuple(str(value) for value in experiment_payload.get("direct_columns", ()) or ()),
        "lagged_columns": tuple(str(value) for value in experiment_payload.get("lagged_columns", ()) or ()),
        "lag_hours": tuple(int(value) for value in experiment_payload.get("lag_hours", ()) or ()),
    }


def _last_fully_supported_local_day(max_timestamp_utc: pd.Timestamp | None, local_dates: list[date], timezone: str) -> date | None:
    if max_timestamp_utc is None or pd.isna(max_timestamp_utc):
        return None
    feasible: list[date] = []
    for local_day in local_dates:
        _, end_utc_exclusive = local_date_to_utc_bounds(local_day, timezone)
        last_hour_utc = end_utc_exclusive - pd.Timedelta(hours=1)
        if last_hour_utc <= max_timestamp_utc:
            feasible.append(local_day)
    return max(feasible) if feasible else None


def _external_feature_coverage(
    *,
    config: QuarterHourDAExtensionConfig,
    hourly_config: HourlyDAPipelineConfig,
    selected_anchor_models: pd.DataFrame,
    split_lookup_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    store = load_external_feature_store(hourly_config)
    values = store.values.copy()
    values["timestamp_utc"] = pd.to_datetime(values["timestamp_utc"], utc=True, errors="coerce")
    available_columns = set(values.columns)
    observed_dates = [pd.Timestamp(value).date() for value in split_lookup_frame["delivery_local_date"].tolist()]
    split_dates = {
        split_name: [pd.Timestamp(value).date() for value in split_lookup_frame.loc[split_lookup_frame["dataset_split"].astype(str) == split_name, "delivery_local_date"].tolist()]
        for split_name in ("train", "validation", "test")
    }
    requested_end_local_date = max(observed_dates)

    coverage_rows: list[dict[str, Any]] = []
    feasibility_rows: list[dict[str, Any]] = []

    for selected_row in selected_anchor_models.to_dict(orient="records"):
        settings_row = _load_selected_model_payload(selected_row)
        requirements = _required_feature_columns_from_payload(settings_row["settings_payload"])
        direct_columns = list(requirements["direct_columns"])
        lagged_columns = list(requirements["lagged_columns"])
        column_maxima: dict[str, pd.Timestamp | None] = {}
        missing_direct: list[str] = []
        missing_lagged: list[str] = []

        for usage_mode, columns in (("direct", direct_columns), ("lagged", lagged_columns)):
            for column_name in columns:
                if column_name not in available_columns:
                    column_maxima[column_name] = None
                    if usage_mode == "direct":
                        missing_direct.append(column_name)
                    else:
                        missing_lagged.append(column_name)
                    coverage_rows.append(
                        {
                            "candidate_key": str(selected_row["candidate_key"]),
                            "candidate_label": str(selected_row["candidate_label"]),
                            "role": str(selected_row["role"]),
                            "branch_scope": requirements["branch_scope"],
                            "feature_usage": usage_mode,
                            "column_name": column_name,
                            "max_available_timestamp_utc": None,
                            "max_available_local_date": None,
                            "present_in_store": False,
                            "covers_requested_test_end": False,
                            "notes": "Column is missing from the current cleaned external feature store.",
                        }
                    )
                    continue
                observed = values.loc[values[column_name].notna(), "timestamp_utc"]
                max_ts = pd.Timestamp(observed.max()) if not observed.empty else None
                column_maxima[column_name] = max_ts
                max_local_date = max_ts.tz_convert(config.business_timezone).date() if max_ts is not None else None
                coverage_rows.append(
                    {
                        "candidate_key": str(selected_row["candidate_key"]),
                        "candidate_label": str(selected_row["candidate_label"]),
                        "role": str(selected_row["role"]),
                        "branch_scope": requirements["branch_scope"],
                        "feature_usage": usage_mode,
                        "column_name": column_name,
                        "max_available_timestamp_utc": max_ts.isoformat() if max_ts is not None else None,
                        "max_available_local_date": str(max_local_date) if max_local_date is not None else None,
                        "present_in_store": True,
                        "covers_requested_test_end": bool(max_local_date is not None and max_local_date >= requested_end_local_date),
                        "notes": "",
                    }
                )

        direct_maxima = [value for key, value in column_maxima.items() if key in direct_columns and value is not None]
        min_direct_max_ts = min(direct_maxima) if direct_maxima else None
        feasible_end_local_date = _last_fully_supported_local_day(
            min_direct_max_ts,
            local_dates=observed_dates,
            timezone=config.business_timezone,
        )
        covers_train = bool(split_dates["train"]) and feasible_end_local_date is not None and feasible_end_local_date >= max(split_dates["train"])
        covers_validation = bool(split_dates["validation"]) and feasible_end_local_date is not None and feasible_end_local_date >= max(split_dates["validation"])
        covers_test = bool(split_dates["test"]) and feasible_end_local_date is not None and feasible_end_local_date >= max(split_dates["test"])

        if missing_direct:
            status = "blocked_missing_direct_columns"
            notes = "Required direct external-feature columns are missing from the cleaned store."
        elif not covers_validation or not covers_test:
            status = "blocked_insufficient_future_feature_coverage"
            notes = (
                "Selected hourly anchor models require direct external features beyond the current cleaned store horizon. "
                "Realistic Jan-Apr 2026 D-only hourly anchors cannot be generated repo-natively yet."
            )
        else:
            status = "ready_for_full_phase07"
            notes = "Required direct external features cover the observed train, validation, and test windows."

        feasibility_rows.append(
            {
                "candidate_key": str(selected_row["candidate_key"]),
                "candidate_label": str(selected_row["candidate_label"]),
                "role": str(selected_row["role"]),
                "model_family": str(selected_row["model_family"]),
                "fs_level": str(selected_row["fs_level"]),
                "branch_scope": requirements["branch_scope"],
                "feasible_end_local_date": str(feasible_end_local_date) if feasible_end_local_date is not None else None,
                "covers_train": bool(covers_train),
                "covers_validation": bool(covers_validation),
                "covers_test": bool(covers_test),
                "missing_direct_columns_count": int(len(missing_direct)),
                "missing_lagged_columns_count": int(len(missing_lagged)),
                "min_direct_feature_max_timestamp_utc": min_direct_max_ts.isoformat() if min_direct_max_ts is not None else None,
                "status": status,
                "notes": notes,
            }
        )

    return (
        pd.DataFrame(coverage_rows).sort_values(["candidate_key", "feature_usage", "column_name"]).reset_index(drop=True),
        pd.DataFrame(feasibility_rows).sort_values(["role", "candidate_key"]).reset_index(drop=True),
    )


def _instantiate_selected_models(selected_anchor_models: pd.DataFrame) -> list[dict[str, Any]]:
    model_specs: list[dict[str, Any]] = []
    for selected_row in selected_anchor_models.to_dict(orient="records"):
        settings_row = _load_selected_model_payload(selected_row)
        parent_like = SimpleNamespace(
            settings_payload=settings_row["settings_payload"],
            fs_level=settings_row["fs_level"],
            model_family=settings_row["model_family"],
            model_name=settings_row["model_name"],
        )
        model = instantiate_model_from_parent_context(
            parent_like,
            name_override=str(settings_row["model_name"]),
        )
        model_specs.append(
            {
                "candidate_key": str(selected_row["candidate_key"]),
                "candidate_label": str(selected_row["candidate_label"]),
                "role": str(selected_row["role"]),
                "role_description": str(selected_row["role_description"]),
                "source_run_id": str(selected_row["source_run_id"]),
                "source_run_label": str(selected_row["source_run_label"]),
                "internal_model_name": str(settings_row["model_name"]),
                "model": model,
            }
        )
    return model_specs


def _lead_day_label(lead_day: int) -> str:
    return "D" if int(lead_day) == 0 else f"D+{int(lead_day)}"


def _build_origin_schedule(
    split_lookup: dict[date, str],
    *,
    timezone: str,
    horizon_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for local_day, split_name in sorted(split_lookup.items()):
        origin_local = pd.Timestamp(f"{(local_day - pd.Timedelta(days=1)).isoformat()} 08:00:00", tz=timezone)
        target_start_local_date = local_day
        target_end_local_date = local_day + pd.Timedelta(days=max(int(horizon_days) - 1, 0))
        expected_target_hours = 0
        for lead_day in range(int(horizon_days)):
            delivery_local_date = local_day + pd.Timedelta(days=lead_day)
            start_utc, end_utc_exclusive = local_date_to_utc_bounds(delivery_local_date, timezone)
            expected_target_hours += int((end_utc_exclusive - start_utc) / pd.Timedelta(hours=1))
        rows.append(
            {
                "dataset_split": str(split_name),
                "delivery_start_local_date": str(local_day),
                "delivery_end_local_date": str(target_end_local_date),
                "horizon_days": int(horizon_days),
                "forecast_origin_local": origin_local.isoformat(),
                "forecast_origin_utc": origin_local.tz_convert("UTC").isoformat(),
                "target_start_local_date": str(target_start_local_date),
                "target_end_local_date": str(target_end_local_date),
                "expected_target_hours": expected_target_hours,
            }
        )
    return pd.DataFrame(rows)


def _build_d_only_origin_schedule(split_lookup: dict[date, str], *, timezone: str) -> pd.DataFrame:
    return _build_origin_schedule(split_lookup, timezone=timezone, horizon_days=1)


def _build_target_schedule(
    delivery_start_local_date: date,
    *,
    split_name: str,
    config: HourlyDAPipelineConfig,
    horizon_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    timezone = config.resolved_business_timezone()
    horizon_index = 0
    for lead_day in range(int(horizon_days)):
        delivery_local_date = delivery_start_local_date + pd.Timedelta(days=lead_day)
        start_utc, end_utc_exclusive = local_date_to_utc_bounds(delivery_local_date, timezone)
        target_known_at_utc = known_at_utc_for_delivery_date(delivery_local_date, config)
        target_index = pd.date_range(start=start_utc, end=end_utc_exclusive, freq="h", inclusive="left", tz="UTC")
        for target_timestamp_utc in target_index:
            horizon_index += 1
            target_local = target_timestamp_utc.tz_convert(timezone)
            rows.append(
                {
                    "target_timestamp_utc": target_timestamp_utc,
                    "target_delivery_local_date": delivery_local_date,
                    "target_hour_local": int(target_local.hour),
                    "target_known_at_utc": target_known_at_utc,
                    "lead_day": int(lead_day),
                    "lead_day_label": _lead_day_label(int(lead_day)),
                    "horizon_index": int(horizon_index),
                    "dataset_split": str(split_name),
                }
            )
    return pd.DataFrame(rows)


def _build_d_only_target_schedule(
    delivery_local_date: date,
    *,
    split_name: str,
    config: HourlyDAPipelineConfig,
) -> pd.DataFrame:
    return _build_target_schedule(
        delivery_local_date,
        split_name=split_name,
        config=config,
        horizon_days=1,
    )


def _run_hourly_extension(
    *,
    canonical_frame: pd.DataFrame,
    hourly_config: HourlyDAPipelineConfig,
    external_feature_store,
    model_specs: list[dict[str, Any]],
    origin_schedule: pd.DataFrame,
    run_id: str,
    horizon_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions_frames: list[pd.DataFrame] = []
    timing_rows: list[dict[str, Any]] = []
    target_lookup_frame = canonical_frame[[hourly_config.timestamp_col, hourly_config.target_col, "is_observed_target"]].rename(
        columns={hourly_config.timestamp_col: "target_timestamp_utc"}
    )

    for origin_row in origin_schedule.to_dict(orient="records"):
        split_name = str(origin_row["dataset_split"])
        delivery_start_local_date = pd.Timestamp(origin_row["delivery_start_local_date"]).date()
        forecast_origin_utc = pd.Timestamp(origin_row["forecast_origin_utc"])
        history = canonical_frame[canonical_frame[hourly_config.known_at_col] <= forecast_origin_utc].copy()
        if history.empty:
            continue
        target_schedule = _build_target_schedule(
            delivery_start_local_date,
            split_name=split_name,
            config=hourly_config,
            horizon_days=horizon_days,
        )
        target_frame = target_schedule.merge(target_lookup_frame, on="target_timestamp_utc", how="left")
        target_index_utc = pd.DatetimeIndex(target_frame["target_timestamp_utc"])
        feature_context = build_feature_context_for_origin(external_feature_store, forecast_origin_utc)

        for model_spec in model_specs:
            model = model_spec["model"]
            fit_started = time.perf_counter()
            model.fit(
                history=history,
                target_index_utc=target_index_utc,
                config=hourly_config,
                feature_context=feature_context,
            )
            fit_time_sec = time.perf_counter() - fit_started

            predict_started = time.perf_counter()
            preds = model.predict(
                history=history,
                target_index_utc=target_index_utc,
                config=hourly_config,
                feature_context=feature_context,
            )
            predict_time_sec = time.perf_counter() - predict_started
            if not preds.index.equals(target_index_utc):
                preds = preds.reindex(target_index_utc)

            runtime_info = model.get_last_runtime_info()
            timing_rows.append(
                {
                    "run_id": run_id,
                    "dataset_split": split_name,
                    "candidate_key": model_spec["candidate_key"],
                    "candidate_label": model_spec["candidate_label"],
                    "role": model_spec["role"],
                    "model": model.name,
                    "model_family": model.family,
                    "fs_level": model.fs_level,
                    "forecast_origin_utc": forecast_origin_utc.isoformat(),
                    "fit_time_sec": fit_time_sec,
                    "predict_time_sec": predict_time_sec,
                    "runtime_info_json": json.dumps(runtime_info, sort_keys=True, default=str),
                }
            )

            model_predictions = target_frame.copy()
            model_predictions["run_id"] = run_id
            model_predictions["candidate_key"] = model_spec["candidate_key"]
            model_predictions["candidate_label"] = model_spec["candidate_label"]
            model_predictions["role"] = model_spec["role"]
            model_predictions["role_description"] = model_spec["role_description"]
            model_predictions["source_run_id"] = model_spec["source_run_id"]
            model_predictions["source_run_label"] = model_spec["source_run_label"]
            model_predictions["model"] = model.name
            model_predictions["model_family"] = model.family
            model_predictions["fs_level"] = model.fs_level
            model_predictions["forecast_origin_utc"] = forecast_origin_utc
            model_predictions["y_true"] = pd.to_numeric(model_predictions[hourly_config.target_col], errors="coerce")
            model_predictions["y_pred"] = preds.to_numpy(dtype=float)
            model_predictions["fit_time_sec"] = fit_time_sec
            model_predictions["predict_time_sec"] = predict_time_sec
            model_predictions["runtime_info_json"] = json.dumps(runtime_info, sort_keys=True, default=str)
            predictions_frames.append(
                model_predictions[
                    [
                        "run_id",
                        "candidate_key",
                        "candidate_label",
                        "role",
                        "role_description",
                        "source_run_id",
                        "source_run_label",
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
                        "runtime_info_json",
                    ]
                ].copy()
            )

    predictions = (
        pd.concat(predictions_frames, ignore_index=True)
        .sort_values(["candidate_key", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
        .reset_index(drop=True)
        if predictions_frames
        else pd.DataFrame()
    )
    timing = (
        pd.DataFrame(timing_rows).sort_values(["candidate_key", "dataset_split", "forecast_origin_utc"]).reset_index(drop=True)
        if timing_rows
        else pd.DataFrame()
    )
    return predictions, timing


def _run_hourly_d_only_extension(
    *,
    canonical_frame: pd.DataFrame,
    hourly_config: HourlyDAPipelineConfig,
    external_feature_store,
    model_specs: list[dict[str, Any]],
    origin_schedule: pd.DataFrame,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _run_hourly_extension(
        canonical_frame=canonical_frame,
        hourly_config=hourly_config,
        external_feature_store=external_feature_store,
        model_specs=model_specs,
        origin_schedule=origin_schedule,
        run_id=run_id,
        horizon_days=1,
    )


def _hourly_anchor_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    working = predictions.copy()
    working["target_timestamp_utc"] = pd.to_datetime(working["target_timestamp_utc"], utc=True, errors="coerce")
    working["target_timestamp_local"] = working["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    working["delivery_local_date"] = pd.to_datetime(working["target_delivery_local_date"], errors="coerce").dt.date
    working["error"] = pd.to_numeric(working["y_pred"], errors="coerce") - pd.to_numeric(working["y_true"], errors="coerce")
    working["abs_error"] = working["error"].abs()

    metrics_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for (candidate_key, split_name), group in working.groupby(["candidate_key", "dataset_split"], dropna=False):
        observed = group[group["y_pred"].notna() & group["y_true"].notna()].copy()
        delivery_hours = group.groupby("delivery_local_date")["target_timestamp_utc"].size().rename("expected_hours")
        available_hours = (
            group.assign(pred_available=group["y_pred"].notna())
            .groupby("delivery_local_date")["pred_available"]
            .sum()
            .rename("available_hours")
        )
        day_cover = delivery_hours.to_frame().join(available_hours, how="left").fillna(0.0).reset_index()
        day_cover["full_day_coverage"] = day_cover["available_hours"] >= day_cover["expected_hours"]
        coverage_rows.append(
            {
                "candidate_key": str(candidate_key),
                "dataset_split": str(split_name),
                "period_start_local_date": str(min(day_cover["delivery_local_date"])) if not day_cover.empty else None,
                "period_end_local_date": str(max(day_cover["delivery_local_date"])) if not day_cover.empty else None,
                "number_of_days": int(day_cover.shape[0]),
                "number_of_hours": int(group.shape[0]),
                "available_prediction_hours": int(group["y_pred"].notna().sum()),
                "days_with_full_hourly_anchor_coverage": int(day_cover["full_day_coverage"].sum()),
            }
        )
        metrics_rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(group["candidate_label"].iloc[0]),
                "role": str(group["role"].iloc[0]),
                "dataset_split": str(split_name),
                "mae": float(observed["abs_error"].mean()) if not observed.empty else np.nan,
                "rmse": float(np.sqrt(np.mean(np.square(observed["error"])))) if not observed.empty else np.nan,
                "bias": float(observed["error"].mean()) if not observed.empty else np.nan,
                "n_hours": int(group.shape[0]),
                "n_hours_with_predictions": int(group["y_pred"].notna().sum()),
            }
        )
    return (
        pd.DataFrame(metrics_rows).sort_values(["candidate_key", "dataset_split"]).reset_index(drop=True),
        pd.DataFrame(coverage_rows).sort_values(["candidate_key", "dataset_split"]).reset_index(drop=True),
    )


def _build_realistic_modeling_table(shape_target: pd.DataFrame, hourly_predictions: pd.DataFrame) -> pd.DataFrame:
    observed = shape_target[
        [
            "timestamp_utc",
            "timestamp_local",
            "delivery_local_date",
            "hour_start_utc",
            "hour_start_local",
            "hour_local_date",
            "local_hour_of_day",
            "local_minute",
            "quarter_index",
            "dataset_split",
            "price_eur_per_mwh",
            "hourly_mean_eur_per_mwh",
            "delta_eur_per_mwh",
            "abs_delta_eur_per_mwh",
            "delta_zero_mean_check_abs",
            "hour_group_quality",
            "hour_contains_interpolation",
            "hour_contains_flagged_missing",
        ]
    ].rename(columns={"hourly_mean_eur_per_mwh": "actual_hourly_mean_eur_per_mwh"}).copy()
    observed["timestamp_utc"] = pd.to_datetime(observed["timestamp_utc"], utc=True, errors="coerce")
    observed["hour_start_utc"] = pd.to_datetime(observed["hour_start_utc"], utc=True, errors="coerce")

    frames: list[pd.DataFrame] = []
    hourly_working = hourly_predictions.copy()
    hourly_working["target_timestamp_utc"] = pd.to_datetime(hourly_working["target_timestamp_utc"], utc=True, errors="coerce")
    hourly_working["target_timestamp_local"] = pd.to_datetime(hourly_working["target_timestamp_utc"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
    hourly_working["forecast_origin_utc"] = pd.to_datetime(hourly_working["forecast_origin_utc"], utc=True, errors="coerce")
    if "forecast_origin_local" in hourly_working.columns:
        hourly_working["forecast_origin_local"] = pd.to_datetime(hourly_working["forecast_origin_local"], utc=True, errors="coerce")
    else:
        hourly_working["forecast_origin_local"] = hourly_working["forecast_origin_utc"].dt.tz_convert("Europe/Amsterdam")
    hourly_working["delivery_local_date"] = pd.to_datetime(hourly_working["target_delivery_local_date"], errors="coerce").dt.date
    hourly_working["local_hour_of_day"] = pd.to_numeric(hourly_working["target_hour_local"], errors="coerce").astype(int)

    for candidate_key, group in hourly_working.groupby("candidate_key", dropna=False):
        hourly_frame = group[
            [
                "candidate_key",
                "candidate_label",
                "role",
                "role_description",
                "source_run_id",
                "source_run_label",
                "dataset_split",
                "forecast_origin_utc",
                "forecast_origin_local",
                "lead_day",
                "lead_day_label",
                "horizon_index",
                "target_timestamp_utc",
                "target_timestamp_local",
                "delivery_local_date",
                "local_hour_of_day",
                "y_true",
                "y_pred",
            ]
        ].copy()
        hourly_frame = hourly_frame.rename(
            columns={
                "target_timestamp_utc": "hour_start_utc",
                "target_timestamp_local": "hour_start_local",
                "y_pred": "hourly_anchor_price_eur_per_mwh",
                "y_true": "hourly_anchor_actual_eur_per_mwh",
            }
        )
        hourly_frame["hourly_anchor_error_eur_per_mwh"] = (
            pd.to_numeric(hourly_frame["hourly_anchor_price_eur_per_mwh"], errors="coerce")
            - pd.to_numeric(hourly_frame["hourly_anchor_actual_eur_per_mwh"], errors="coerce")
        )
        hourly_enriched = _enrich_hourly_anchor_frame(hourly_frame)
        expanded = _expand_hourly_to_quarters(
            hourly_enriched,
            source_type="forecast_15min_shape_realistic_anchor",
            shape_method="hourly_anchor_extension",
            scenario_variant="realistic_track_a",
        )
        merged = expanded.merge(
            observed,
            on=["timestamp_utc", "hour_start_utc"],
            how="inner",
            suffixes=("", "_observed"),
        )
        merged["timestamp_local"] = pd.to_datetime(merged["timestamp_local"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
        merged["hour_start_local"] = pd.to_datetime(merged["hour_start_local"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
        merged["delivery_local_date"] = pd.to_datetime(merged["delivery_local_date_observed"], errors="coerce").dt.date
        merged["hour_local_date"] = pd.to_datetime(merged["hour_local_date"], errors="coerce").dt.date
        merged["hourly_mean_eur_per_mwh"] = pd.to_numeric(merged["hourly_anchor_price_eur_per_mwh"], errors="coerce")
        merged["target_timestamp_utc"] = pd.to_datetime(merged["timestamp_utc"], utc=True, errors="coerce")
        merged["target_timestamp_local"] = pd.to_datetime(merged["timestamp_local"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam")
        merged["feature_mode"] = "minimal_realistic_anchor_features_v1"
        merged["anchor_mode"] = "realistic_forecast"
        frames.append(merged)

    return pd.concat(frames, ignore_index=True).sort_values(
        ["candidate_key", "forecast_origin_utc", "hour_start_utc", "quarter_index"]
    ).reset_index(drop=True)


def _model_configuration_rows(
    *,
    candidate_key: str,
    candidate_label: str,
    role: str,
    selected_tuning: dict[str, dict[str, Any]],
    candidate_model_table: pd.DataFrame,
) -> pd.DataFrame:
    split_summary = (
        candidate_model_table.groupby("dataset_split", dropna=False)["delivery_local_date"]
        .agg(["min", "max"])
        .rename(columns={"min": "start_date", "max": "end_date"})
        .reset_index()
    )
    split_lookup = {
        str(row["dataset_split"]): (str(row["start_date"]), str(row["end_date"]))
        for row in split_summary.to_dict(orient="records")
    }
    rows: list[dict[str, Any]] = []
    for model_name in ALL_MODEL_ORDER:
        if model_name == "flat_repeat":
            model_type = "baseline_flat_repeat"
            params_json = "{}"
        elif model_name == "mean_shape":
            model_type = "baseline_mean_shape"
            params_json = json.dumps({"grouping": ["local_hour_of_day", "quarter_index", "weekend_flag"], "fallbacks": ["hour_quarter", "quarter_global"]})
        else:
            model_type = "learned_shape_model"
            params_json = json.dumps(selected_tuning.get(model_name, {}), sort_keys=True)
        rows.append(
            {
                "candidate_key": candidate_key,
                "candidate_label": candidate_label,
                "role": role,
                "model": model_name,
                "model_type": model_type,
                "feature_set": "minimal_realistic_anchor_features_v1",
                "training_period": f"{split_lookup['train'][0]} to {split_lookup['train'][1]}",
                "validation_period": f"{split_lookup['validation'][0]} to {split_lookup['validation'][1]}",
                "test_period": f"{split_lookup['test'][0]} to {split_lookup['test'][1]}",
                "key_hyperparameters": params_json,
                "retraining_policy": "train_only_for_validation_then_refit_train_plus_validation_for_test",
                "zero_mean_correction_applied": True,
                "diagnostic_oracle_anchor_used": False,
                "realistic_hourly_anchor_used": True,
            }
        )
    return pd.DataFrame(rows)


def _phase07_temporal_validation(
    modeling_table: pd.DataFrame,
    predictions: pd.DataFrame,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    checks: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []

    if modeling_table.empty:
        diagnostic_rows.append(
            {
                "diagnostic_name": "modeling_table_rows",
                "dataset_split": None,
                "candidate_key": None,
                "model": None,
                "lead_day": None,
                "value": 0,
                "details": "No realistic modeling rows were available for temporal validation.",
            }
        )
        return checks, pd.DataFrame(diagnostic_rows)

    if "forecast_origin_utc" not in modeling_table.columns:
        checks.append(_check_split_nonoverlap(modeling_table))
        diagnostic_rows.append(
            {
                "diagnostic_name": "split_nonoverlap_mode",
                "dataset_split": None,
                "candidate_key": None,
                "model": None,
                "lead_day": None,
                "value": None,
                "details": "Legacy D-only/local-date validation path used because forecast_origin_utc is not present.",
            }
        )
        return checks, pd.DataFrame(diagnostic_rows)

    working = modeling_table.copy()
    working["dataset_split"] = working["dataset_split"].astype(str)
    working["forecast_origin_utc"] = pd.to_datetime(working["forecast_origin_utc"], utc=True, errors="coerce")
    working["target_timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True, errors="coerce")
    working["candidate_key"] = working["candidate_key"].astype(str) if "candidate_key" in working.columns else "unknown_candidate"
    working["lead_day"] = pd.to_numeric(working["lead_day"], errors="coerce")
    working = working.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "dataset_split", "candidate_key"]).copy()

    origin_split_map = (
        working[["dataset_split", "forecast_origin_utc"]]
        .drop_duplicates()
        .groupby("forecast_origin_utc", dropna=False)["dataset_split"]
        .nunique()
    )
    origins_in_multiple_splits = int((origin_split_map > 1).sum())
    origin_split_details = []
    if origins_in_multiple_splits:
        sample = (
            working[["dataset_split", "forecast_origin_utc"]]
            .drop_duplicates()
            .groupby("forecast_origin_utc", dropna=False)["dataset_split"]
            .agg(lambda values: sorted({str(value) for value in values}))
        )
        for origin_value, splits in sample[sample.apply(len) > 1].head(5).items():
            origin_split_details.append(f"{pd.Timestamp(origin_value).isoformat()}->{splits}")

    checks.append(
        {
            "check_name": "split_nonoverlap",
            "status": "pass" if origins_in_multiple_splits == 0 else "fail",
            "severity": "error" if origins_in_multiple_splits else "info",
            "details": (
                "Forecast origins belong to exactly one split. Rolling-origin target timestamp overlap across different origins is allowed."
                if origins_in_multiple_splits == 0
                else "Forecast origins assigned to multiple splits: " + "; ".join(origin_split_details)
            ),
        }
    )

    split_origin_summary = (
        working[["dataset_split", "forecast_origin_utc"]]
        .drop_duplicates()
        .groupby("dataset_split", dropna=False)["forecast_origin_utc"]
        .agg(["nunique", "min", "max"])
        .reset_index()
    )
    for row in split_origin_summary.to_dict(orient="records"):
        diagnostic_rows.append(
            {
                "diagnostic_name": "forecast_origins_by_split",
                "dataset_split": str(row["dataset_split"]),
                "candidate_key": None,
                "model": None,
                "lead_day": None,
                "value": int(row["nunique"]),
                "details": f"min_origin_utc={pd.Timestamp(row['min']).isoformat()}; max_origin_utc={pd.Timestamp(row['max']).isoformat()}",
            }
        )

    origin_ranges = {
        str(row["dataset_split"]): (pd.Timestamp(row["min"]), pd.Timestamp(row["max"]))
        for row in split_origin_summary.to_dict(orient="records")
    }
    ordering_failures: list[str] = []
    expected_order = [split for split in ("train", "validation", "test") if split in origin_ranges]
    for left, right in zip(expected_order, expected_order[1:]):
        if origin_ranges[left][1] >= origin_ranges[right][0]:
            ordering_failures.append(
                f"{left}_max_origin={origin_ranges[left][1].isoformat()} >= {right}_min_origin={origin_ranges[right][0].isoformat()}"
            )
    checks.append(
        {
            "check_name": "split_origin_ordering",
            "status": "pass" if not ordering_failures else "fail",
            "severity": "error" if ordering_failures else "info",
            "details": (
                "Chronological forecast-origin ordering is train < validation < test."
                if not ordering_failures
                else "; ".join(ordering_failures)
            ),
        }
    )

    expected_lead_days = sorted({int(value) for value in working["lead_day"].dropna().astype(int).tolist()})
    lead_day_coverage = (
        working[["dataset_split", "lead_day", "forecast_origin_utc"]]
        .dropna(subset=["lead_day"])
        .drop_duplicates()
        .groupby(["dataset_split", "lead_day"], dropna=False)["forecast_origin_utc"]
        .nunique()
        .reset_index(name="origin_count")
        .sort_values(["dataset_split", "lead_day"])
        .reset_index(drop=True)
    )
    for row in lead_day_coverage.to_dict(orient="records"):
        diagnostic_rows.append(
            {
                "diagnostic_name": "lead_day_coverage_by_split",
                "dataset_split": str(row["dataset_split"]),
                "candidate_key": None,
                "model": None,
                "lead_day": int(row["lead_day"]),
                "value": int(row["origin_count"]),
                "details": f"lead_day_label={_lead_day_label(int(row['lead_day']))}",
            }
        )
    for split_name in sorted(working["dataset_split"].unique().tolist()):
        split_lead_days = sorted(
            {
                int(value)
                for value in working.loc[working["dataset_split"] == split_name, "lead_day"].dropna().astype(int).tolist()
            }
        )
        missing = [value for value in expected_lead_days if value not in split_lead_days]
        checks.append(
            {
                "check_name": f"lead_day_coverage::{split_name}",
                "status": "pass" if not missing else "fail",
                "severity": "error" if missing else "info",
                "details": (
                    f"lead_days_present={split_lead_days}; expected={expected_lead_days}"
                    if not missing
                    else f"missing_lead_days={missing}; present={split_lead_days}; expected={expected_lead_days}"
                ),
            }
        )

    modeling_duplicate_counts = (
        working.groupby(["candidate_key", "forecast_origin_utc", "target_timestamp_utc"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    modeling_duplicate_groups = modeling_duplicate_counts[modeling_duplicate_counts["row_count"] > 1].copy()
    modeling_duplicate_rows = int((modeling_duplicate_groups["row_count"] - 1).sum()) if not modeling_duplicate_groups.empty else 0
    checks.append(
        {
            "check_name": "duplicate_candidate_origin_target_rows",
            "status": "pass" if modeling_duplicate_rows == 0 else "fail",
            "severity": "error" if modeling_duplicate_rows else "info",
            "details": (
                "No duplicate modeling-table rows for (candidate_key, forecast_origin_utc, target_timestamp_utc)."
                if modeling_duplicate_rows == 0
                else (
                    f"duplicate_groups={int(modeling_duplicate_groups.shape[0])}; "
                    f"duplicate_rows={modeling_duplicate_rows}"
                )
            ),
        }
    )
    diagnostic_rows.append(
        {
            "diagnostic_name": "duplicate_count_by_candidate_origin_target",
            "dataset_split": None,
            "candidate_key": None,
            "model": None,
            "lead_day": None,
            "value": modeling_duplicate_rows,
            "details": (
                f"duplicate_groups={int(modeling_duplicate_groups.shape[0])}; key=(candidate_key, forecast_origin_utc, target_timestamp_utc)"
            ),
        }
    )

    target_overlap = (
        working.groupby("target_timestamp_utc", dropna=False)
        .agg(
            origin_count=("forecast_origin_utc", "nunique"),
            split_count=("dataset_split", "nunique"),
            lead_day_count=("lead_day", "nunique"),
        )
        .reset_index()
    )
    overlapping_targets = target_overlap[target_overlap["origin_count"] > 1].copy()
    overlapping_target_count = int(overlapping_targets.shape[0])
    overlapping_target_extra_assignments = int((overlapping_targets["origin_count"] - 1).sum()) if not overlapping_targets.empty else 0
    overlapping_lead_day_targets = int(overlapping_targets.loc[overlapping_targets["lead_day_count"] > 1].shape[0]) if not overlapping_targets.empty else 0
    diagnostic_rows.append(
        {
            "diagnostic_name": "target_timestamp_overlap_across_origins",
            "dataset_split": None,
            "candidate_key": None,
            "model": None,
            "lead_day": None,
            "value": overlapping_target_count,
            "details": (
                f"targets_with_multiple_origins={overlapping_target_count}; "
                f"extra_origin_assignments={overlapping_target_extra_assignments}; "
                f"targets_spanning_multiple_lead_days={overlapping_lead_day_targets}; "
                "Expected in multi-horizon rolling-origin evaluation."
            ),
        }
    )

    diagnostic_rows.append(
        {
            "diagnostic_name": "forecast_origin_multi_split_count",
            "dataset_split": None,
            "candidate_key": None,
            "model": None,
            "lead_day": None,
            "value": origins_in_multiple_splits,
            "details": "Count of unique forecast_origin_utc values assigned to more than one dataset split.",
        }
    )

    if not predictions.empty:
        prediction_working = predictions.copy()
        prediction_working["forecast_origin_utc"] = pd.to_datetime(prediction_working["forecast_origin_utc"], utc=True, errors="coerce")
        prediction_working["target_timestamp_utc"] = pd.to_datetime(prediction_working["target_timestamp_utc"], utc=True, errors="coerce")
        prediction_working["candidate_key"] = prediction_working["hourly_anchor_candidate_key"].astype(str)
        prediction_working["model"] = prediction_working["model"].astype(str)
        prediction_working = prediction_working.dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "candidate_key", "model"])
        prediction_duplicate_counts = (
            prediction_working.groupby(
                ["candidate_key", "model", "forecast_origin_utc", "target_timestamp_utc"],
                dropna=False,
            )
            .size()
            .reset_index(name="row_count")
        )
        prediction_duplicate_groups = prediction_duplicate_counts[prediction_duplicate_counts["row_count"] > 1].copy()
        prediction_duplicate_rows = int((prediction_duplicate_groups["row_count"] - 1).sum()) if not prediction_duplicate_groups.empty else 0
        checks.append(
            {
                "check_name": "duplicate_prediction_origin_target_rows",
                "status": "pass" if prediction_duplicate_rows == 0 else "fail",
                "severity": "error" if prediction_duplicate_rows else "info",
                "details": (
                    "No duplicate prediction rows for (candidate_key, model, forecast_origin_utc, target_timestamp_utc)."
                    if prediction_duplicate_rows == 0
                    else (
                        f"duplicate_groups={int(prediction_duplicate_groups.shape[0])}; "
                        f"duplicate_rows={prediction_duplicate_rows}"
                    )
                ),
            }
        )

    return checks, pd.DataFrame(diagnostic_rows)


def _phase07_checks(
    *,
    modeling_table: pd.DataFrame,
    predictions: pd.DataFrame,
    feasibility: pd.DataFrame,
    hourly_coverage: pd.DataFrame,
    blocked: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = [
        {
            "check_name": "shape_target_zero_mean",
            "status": "pass" if float(modeling_table["delta_zero_mean_check_abs"].max()) < 1e-9 else "fail",
            "severity": "error" if float(modeling_table["delta_zero_mean_check_abs"].max()) >= 1e-9 else "info",
            "details": f"max_abs_hourly_delta_mean={float(modeling_table['delta_zero_mean_check_abs'].max()):.6g}",
        },
    ]
    temporal_checks, temporal_diagnostics = _phase07_temporal_validation(modeling_table, predictions)
    rows.extend(temporal_checks)
    for row in feasibility.to_dict(orient="records"):
        available = bool(row["covers_validation"]) and bool(row["covers_test"])
        rows.append(
            {
                "check_name": f"realistic_anchor_feasibility::{row['candidate_key']}",
                "status": "pass" if available else "warning",
                "severity": "warning" if not available else "info",
                "details": str(row["notes"]),
            }
        )
    if blocked:
        checks = pd.DataFrame(rows)
        failures = checks[checks["status"].astype(str) == "fail"]
        if not failures.empty:
            raise ValueError(f"Phase 7 validation checks failed: {failures['check_name'].tolist()}")
        return checks, temporal_diagnostics

    for row in hourly_coverage.to_dict(orient="records"):
        full = int(row["days_with_full_hourly_anchor_coverage"]) == int(row["number_of_days"])
        rows.append(
            {
                "check_name": f"hourly_anchor_day_coverage::{row['candidate_key']}::{row['dataset_split']}",
                "status": "pass" if full else "warning",
                "severity": "warning" if not full else "info",
                "details": (
                    f"days_with_full_coverage={row['days_with_full_hourly_anchor_coverage']} / {row['number_of_days']}"
                ),
            }
        )
    for (candidate_key, split_name, model_name), group in predictions.groupby(
        ["hourly_anchor_candidate_key", "dataset_split", "model"],
        dropna=False,
    ):
        max_abs = float(group["predicted_delta_zero_mean_abs"].max())
        rows.append(
            {
                "check_name": f"predicted_zero_mean_after_correction::{candidate_key}::{split_name}::{model_name}",
                "status": "pass" if max_abs < 1e-9 else "fail",
                "severity": "error" if max_abs >= 1e-9 else "info",
                "details": f"max_abs_hourly_delta_mean={max_abs:.6g}",
            }
        )
        preservation_group_columns = ["hour_start_utc"]
        if "forecast_origin_utc" in group.columns:
            preservation_group_columns = ["forecast_origin_utc", "hour_start_utc"]
        preservation = (
            group.groupby(preservation_group_columns)["predicted_price_eur_per_mwh"].mean()
            - group.groupby(preservation_group_columns)["hourly_forecast_anchor_price_eur_per_mwh"].first()
        ).abs()
        max_preservation = float(preservation.max()) if not preservation.empty else 0.0
        rows.append(
            {
                "check_name": f"reconstructed_hourly_mean_equals_anchor::{candidate_key}::{split_name}::{model_name}",
                "status": "pass" if max_preservation < 1e-9 else "fail",
                "severity": "error" if max_preservation >= 1e-9 else "info",
                "details": f"max_abs_hourly_mean_preservation_error={max_preservation:.6g}",
            }
        )
    checks = pd.DataFrame(rows)
    failures = checks[checks["status"].astype(str) == "fail"]
    if not failures.empty:
        raise ValueError(f"Phase 7 validation checks failed: {failures['check_name'].tolist()}")
    return checks, temporal_diagnostics


def smoke_check_phase07_temporal_validation() -> pd.DataFrame:
    modeling_table = pd.DataFrame(
        [
            {
                "candidate_key": "cand_a",
                "dataset_split": "train",
                "forecast_origin_utc": "2026-01-01T07:00:00Z",
                "timestamp_utc": "2026-01-02T00:00:00Z",
                "lead_day": 0,
                "delta_zero_mean_check_abs": 0.0,
            },
            {
                "candidate_key": "cand_a",
                "dataset_split": "train",
                "forecast_origin_utc": "2026-01-01T07:00:00Z",
                "timestamp_utc": "2026-01-03T00:00:00Z",
                "lead_day": 1,
                "delta_zero_mean_check_abs": 0.0,
            },
            {
                "candidate_key": "cand_a",
                "dataset_split": "validation",
                "forecast_origin_utc": "2026-01-02T07:00:00Z",
                "timestamp_utc": "2026-01-03T00:00:00Z",
                "lead_day": 0,
                "delta_zero_mean_check_abs": 0.0,
            },
            {
                "candidate_key": "cand_a",
                "dataset_split": "validation",
                "forecast_origin_utc": "2026-01-02T07:00:00Z",
                "timestamp_utc": "2026-01-04T00:00:00Z",
                "lead_day": 1,
                "delta_zero_mean_check_abs": 0.0,
            },
            {
                "candidate_key": "cand_a",
                "dataset_split": "test",
                "forecast_origin_utc": "2026-01-03T07:00:00Z",
                "timestamp_utc": "2026-01-04T00:00:00Z",
                "lead_day": 0,
                "delta_zero_mean_check_abs": 0.0,
            },
            {
                "candidate_key": "cand_a",
                "dataset_split": "test",
                "forecast_origin_utc": "2026-01-03T07:00:00Z",
                "timestamp_utc": "2026-01-05T00:00:00Z",
                "lead_day": 1,
                "delta_zero_mean_check_abs": 0.0,
            },
        ]
    )
    predictions = pd.DataFrame(
        [
            {
                "hourly_anchor_candidate_key": "cand_a",
                "dataset_split": row["dataset_split"],
                "model": model_name,
                "forecast_origin_utc": row["forecast_origin_utc"],
                "target_timestamp_utc": row["timestamp_utc"],
                "predicted_delta_zero_mean_abs": 0.0,
                "predicted_price_eur_per_mwh": 10.0,
                "hourly_forecast_anchor_price_eur_per_mwh": 10.0,
                "hour_start_utc": row["timestamp_utc"],
            }
            for row in modeling_table.to_dict(orient="records")
            for model_name in ("flat_repeat", "lear_shape")
        ]
    )
    feasibility = pd.DataFrame(
        [
            {
                "candidate_key": "cand_a",
                "covers_validation": True,
                "covers_test": True,
                "notes": "smoke",
            }
        ]
    )
    hourly_coverage = pd.DataFrame(
        [
            {
                "candidate_key": "cand_a",
                "dataset_split": split_name,
                "days_with_full_hourly_anchor_coverage": 2,
                "number_of_days": 2,
            }
            for split_name in ("train", "validation", "test")
        ]
    )
    checks, diagnostics = _phase07_checks(
        modeling_table=modeling_table,
        predictions=predictions,
        feasibility=feasibility,
        hourly_coverage=hourly_coverage,
        blocked=False,
    )
    diagnostics = diagnostics.copy()
    diagnostics["smoke_status"] = "ok"
    return pd.concat(
        [
            checks.assign(result_type="check").rename(columns={"check_name": "name"}),
            diagnostics.assign(result_type="diagnostic").rename(columns={"diagnostic_name": "name"}),
        ],
        ignore_index=True,
        sort=False,
    )


def run_phase07_realistic_track_a(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    horizon_days: int = 5,
) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    if int(horizon_days) < 1:
        raise ValueError("Phase07 horizon_days must be at least 1.")
    run_id = _timestamped_run_id()
    run_dir = config.phase07_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    phase02_run, raw_shape_target = _load_phase02_shape_target(config)
    phase03_run, selected_anchor_models = _load_phase03_selection(config)
    phase04_run, phase04_price_metrics = _load_phase04_price_metrics(config)

    shape_target = _prepare_shape_target(raw_shape_target, timezone=config.business_timezone)
    split_lookup, split_lookup_frame = _phase07_split_lookup(shape_target)

    bridge_csv, bridge_summary = _build_hourly_bridge(shape_target, config=config, run_dir=run_dir)
    bridge_summary.to_csv(run_dir / "hourly_bridge_summary.csv", index=False)

    hourly_config = _hourly_extension_config(config, input_csv=bridge_csv)
    source_frame = load_hourly_price_frame(hourly_config)
    canonical_frame = build_canonical_hourly_frame(source_frame, hourly_config)
    canonical_frame.to_csv(run_dir / "hourly_bridge_canonical_frame.csv", index=False)

    external_coverage, feasibility = _external_feature_coverage(
        config=config,
        hourly_config=hourly_config,
        selected_anchor_models=selected_anchor_models,
        split_lookup_frame=split_lookup_frame,
    )
    external_coverage.to_csv(run_dir / "external_feature_coverage.csv", index=False)
    feasibility.to_csv(run_dir / "hourly_anchor_feasibility.csv", index=False)
    selected_anchor_models.to_csv(run_dir / "selected_hourly_anchor_models.csv", index=False)

    full_run_ready = bool(feasibility["covers_validation"].all() and feasibility["covers_test"].all()) if not feasibility.empty else False
    status_summary = pd.DataFrame(
        [
            {
                "phase07_status": "ready_for_full_realistic_track_a" if full_run_ready else "blocked_before_realistic_validation",
                "realistic_track_a_completed": bool(full_run_ready),
                "hourly_anchor_horizon_days": int(horizon_days),
                "observed_15min_start": str(shape_target["delivery_local_date"].min()),
                "observed_15min_end": str(shape_target["delivery_local_date"].max()),
                "notes": (
                    "Phase 7 can proceed with full realistic end-to-end validation."
                    if full_run_ready
                    else "Selected FS3 hourly anchor models do not yet have repo-native external feature coverage through the observed Jan-Apr 2026 validation/test window."
                ),
            }
        ]
    )
    status_summary.to_csv(run_dir / "status_summary.csv", index=False)

    if not full_run_ready:
        checks, temporal_diagnostics = _phase07_checks(
            modeling_table=shape_target,
            predictions=pd.DataFrame(),
            feasibility=feasibility,
            hourly_coverage=pd.DataFrame(),
            blocked=True,
        )
        checks.to_csv(run_dir / "validation_checks.csv", index=False)
        temporal_diagnostics.to_csv(run_dir / "validation_temporal_diagnostics.csv", index=False)
        run_summary = {
            "run_id": run_id,
            "phase": "phase07_realistic_track_a",
            "status": "blocked_before_realistic_validation",
            "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
            "phase02_run_dir": str(phase02_run),
            "phase03_run_dir": str(phase03_run),
            "phase04_run_dir": str(phase04_run) if phase04_run is not None else None,
            "hourly_bridge_input_csv": str(bridge_csv),
            "hourly_anchor_horizon_days": int(horizon_days),
            "notes": (
                "Phase 7 code is in place, but the realistic Jan-Apr 2026 end-to-end validation remains blocked because the "
                "selected FS3 hourly anchor models require direct external features that currently stop at 2025-12-31 in the cleaned store."
            ),
            "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
        return run_dir

    external_feature_store = load_external_feature_store(hourly_config)
    model_specs = _instantiate_selected_models(selected_anchor_models)
    origin_schedule = _build_origin_schedule(
        split_lookup,
        timezone=config.business_timezone,
        horizon_days=int(horizon_days),
    )
    origin_schedule.to_csv(run_dir / "hourly_anchor_origin_schedule.csv", index=False)

    hourly_predictions, hourly_timing = _run_hourly_extension(
        canonical_frame=canonical_frame,
        hourly_config=hourly_config,
        external_feature_store=external_feature_store,
        model_specs=model_specs,
        origin_schedule=origin_schedule,
        run_id=run_id,
        horizon_days=int(horizon_days),
    )
    hourly_predictions.to_csv(run_dir / "hourly_anchor_predictions_long.csv", index=False)
    hourly_timing.to_csv(run_dir / "hourly_anchor_timing.csv", index=False)

    hourly_metrics, hourly_coverage = _hourly_anchor_metrics(hourly_predictions)
    hourly_metrics.to_csv(run_dir / "hourly_anchor_metrics.csv", index=False)
    hourly_coverage.to_csv(run_dir / "hourly_anchor_coverage_summary.csv", index=False)

    realistic_modeling_table = _build_realistic_modeling_table(shape_target, hourly_predictions)
    realistic_modeling_table.to_csv(run_dir / "realistic_modeling_table.csv", index=False)

    prediction_frames: list[pd.DataFrame] = []
    shape_metric_frames: list[pd.DataFrame] = []
    price_metric_frames: list[pd.DataFrame] = []
    condition_frames: list[pd.DataFrame] = []
    mae_hour_frames: list[pd.DataFrame] = []
    tuning_rows: list[dict[str, Any]] = []
    model_config_frames: list[pd.DataFrame] = []
    feature_summary_frames: list[pd.DataFrame] = []
    exclusion_frames: list[pd.DataFrame] = []
    recommendation_rows: list[dict[str, Any]] = []

    for candidate_key, candidate_table in realistic_modeling_table.groupby("candidate_key", dropna=False):
        candidate_table = candidate_table.sort_values(["forecast_origin_utc", "hour_start_utc", "quarter_index"]).reset_index(drop=True)
        candidate_label = str(candidate_table["candidate_label"].iloc[0])
        role = str(candidate_table["role"].iloc[0])

        X, feature_columns, feature_summary = _build_feature_frame(candidate_table)
        missing_feature_mask = X.isna().any(axis=1)
        feature_summary["rows_before_exclusion"] = int(candidate_table.shape[0])
        feature_summary["rows_excluded_missing_features"] = int(missing_feature_mask.sum())
        feature_summary["rows_after_exclusion"] = int((~missing_feature_mask).sum())
        feature_summary["candidate_key"] = candidate_key
        feature_summary["candidate_label"] = candidate_label
        feature_summary["role"] = role
        feature_summary_frames.append(feature_summary)
        if missing_feature_mask.any():
            exclusions = candidate_table.loc[
                missing_feature_mask,
                ["dataset_split", "forecast_origin_utc", "delivery_local_date", "hour_start_utc", "quarter_index", "lead_day", "lead_day_label", "horizon_index"],
            ].copy()
            exclusions["candidate_key"] = candidate_key
            exclusions["candidate_label"] = candidate_label
            exclusions["role"] = role
            exclusions["excluded_reason"] = "missing_realistic_anchor_features"
            exclusion_frames.append(exclusions)
            candidate_table = candidate_table.loc[~missing_feature_mask].reset_index(drop=True)
            X = X.loc[~missing_feature_mask].reset_index(drop=True)

        train_mask = candidate_table["dataset_split"].astype(str) == "train"
        validation_mask = candidate_table["dataset_split"].astype(str) == "validation"
        test_mask = candidate_table["dataset_split"].astype(str) == "test"
        trainval_mask = train_mask | validation_mask

        train_table = candidate_table.loc[train_mask].reset_index(drop=True)
        validation_table = candidate_table.loc[validation_mask].reset_index(drop=True)
        test_table = candidate_table.loc[test_mask].reset_index(drop=True)

        X_train = X.loc[train_mask].reset_index(drop=True)
        X_validation = X.loc[validation_mask].reset_index(drop=True)
        X_test = X.loc[test_mask].reset_index(drop=True)
        X_trainval = X.loc[trainval_mask].reset_index(drop=True)
        y_train = train_table["delta_eur_per_mwh"].reset_index(drop=True)
        y_trainval = candidate_table.loc[trainval_mask, "delta_eur_per_mwh"].reset_index(drop=True)

        candidate_predictions: list[pd.DataFrame] = []
        selected_tuning: dict[str, dict[str, Any]] = {}

        flat_validation = _build_prediction_frame(
            validation_table,
            model_name="flat_repeat",
            model_family="baseline",
            dataset_split="validation",
            delta_pred_raw=np.zeros(validation_table.shape[0], dtype=float),
            feature_mode="none_flat_repeat",
            anchor_mode="realistic_forecast",
        )
        flat_test = _build_prediction_frame(
            test_table,
            model_name="flat_repeat",
            model_family="baseline",
            dataset_split="test",
            delta_pred_raw=np.zeros(test_table.shape[0], dtype=float),
            feature_mode="none_flat_repeat",
            anchor_mode="realistic_forecast",
        )
        candidate_predictions.extend([flat_validation, flat_test])

        mean_shape_state_validation = _fit_mean_shape(train_table)
        mean_shape_validation = _build_prediction_frame(
            validation_table,
            model_name="mean_shape",
            model_family="baseline",
            dataset_split="validation",
            delta_pred_raw=_predict_mean_shape(mean_shape_state_validation, validation_table),
            feature_mode="calendar_shape_mean_with_weekend_fallback",
            anchor_mode="realistic_forecast",
        )
        mean_shape_state_test = _fit_mean_shape(candidate_table.loc[trainval_mask].reset_index(drop=True))
        mean_shape_test = _build_prediction_frame(
            test_table,
            model_name="mean_shape",
            model_family="baseline",
            dataset_split="test",
            delta_pred_raw=_predict_mean_shape(mean_shape_state_test, test_table),
            feature_mode="calendar_shape_mean_with_weekend_fallback",
            anchor_mode="realistic_forecast",
        )
        candidate_predictions.extend([mean_shape_validation, mean_shape_test])

        lear_grid = [0.001, 0.005, 0.01, 0.05, 0.1]
        best_lear_mae = np.inf
        best_lear_alpha = None
        best_lear_validation_frame: pd.DataFrame | None = None
        for alpha in lear_grid:
            learner = _fit_lear(X_train, y_train, alpha=alpha)
            validation_frame = _build_prediction_frame(
                validation_table,
                model_name="lear_shape",
                model_family="lear",
                dataset_split="validation",
                delta_pred_raw=learner.predict(X_validation),
                feature_mode="minimal_realistic_anchor_features_v1",
                anchor_mode="realistic_forecast",
            )
            validation_mae = float(validation_frame["abs_price_error_eur_per_mwh"].mean())
            tuning_rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": candidate_label,
                    "role": role,
                    "model": "lear_shape",
                    "candidate_id": f"alpha_{alpha}",
                    "candidate_params_json": json.dumps({"alpha": alpha}),
                    "selection_metric": "validation_price_mae",
                    "validation_price_mae": validation_mae,
                    "validation_delta_mae": float(validation_frame["abs_delta_error_eur_per_mwh"].mean()),
                }
            )
            if validation_mae < best_lear_mae:
                best_lear_mae = validation_mae
                best_lear_alpha = alpha
                best_lear_validation_frame = validation_frame
        if best_lear_alpha is None or best_lear_validation_frame is None:
            raise RuntimeError(f"LEAR tuning failed for candidate '{candidate_key}'.")
        selected_tuning["lear_shape"] = {"alpha": best_lear_alpha}
        candidate_predictions.append(best_lear_validation_frame)

        final_lear_model = _fit_lear(X_trainval, y_trainval, alpha=best_lear_alpha)
        candidate_predictions.append(
            _build_prediction_frame(
                test_table,
                model_name="lear_shape",
                model_family="lear",
                dataset_split="test",
                delta_pred_raw=final_lear_model.predict(X_test),
                feature_mode="minimal_realistic_anchor_features_v1",
                anchor_mode="realistic_forecast",
            )
        )

        xgb_grid = [
            {"n_estimators": 80, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.9, "colsample_bytree": 0.9},
            {"n_estimators": 120, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.9, "colsample_bytree": 0.9},
            {"n_estimators": 80, "max_depth": 4, "learning_rate": 0.05, "subsample": 0.9, "colsample_bytree": 0.9},
            {"n_estimators": 120, "max_depth": 4, "learning_rate": 0.08, "subsample": 0.9, "colsample_bytree": 0.9},
        ]
        best_xgb_mae = np.inf
        best_xgb_params: dict[str, Any] | None = None
        best_xgb_validation_frame: pd.DataFrame | None = None
        for idx, params in enumerate(xgb_grid, start=1):
            learner = _fit_xgboost(X_train, y_train, params)
            validation_frame = _build_prediction_frame(
                validation_table,
                model_name="xgboost_shape",
                model_family="xgboost",
                dataset_split="validation",
                delta_pred_raw=learner.predict(X_validation),
                feature_mode="minimal_realistic_anchor_features_v1",
                anchor_mode="realistic_forecast",
            )
            validation_mae = float(validation_frame["abs_price_error_eur_per_mwh"].mean())
            tuning_rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": candidate_label,
                    "role": role,
                    "model": "xgboost_shape",
                    "candidate_id": f"xgb_config_{idx}",
                    "candidate_params_json": json.dumps(params, sort_keys=True),
                    "selection_metric": "validation_price_mae",
                    "validation_price_mae": validation_mae,
                    "validation_delta_mae": float(validation_frame["abs_delta_error_eur_per_mwh"].mean()),
                }
            )
            if validation_mae < best_xgb_mae:
                best_xgb_mae = validation_mae
                best_xgb_params = dict(params)
                best_xgb_validation_frame = validation_frame
        if best_xgb_params is None or best_xgb_validation_frame is None:
            raise RuntimeError(f"XGBoost tuning failed for candidate '{candidate_key}'.")
        selected_tuning["xgboost_shape"] = best_xgb_params
        candidate_predictions.append(best_xgb_validation_frame)

        final_xgb_model = _fit_xgboost(X_trainval, y_trainval, best_xgb_params)
        candidate_predictions.append(
            _build_prediction_frame(
                test_table,
                model_name="xgboost_shape",
                model_family="xgboost",
                dataset_split="test",
                delta_pred_raw=final_xgb_model.predict(X_test),
                feature_mode="minimal_realistic_anchor_features_v1",
                anchor_mode="realistic_forecast",
            )
        )

        candidate_predictions_long = pd.concat(candidate_predictions, ignore_index=True)
        candidate_predictions_long["hourly_forecast_anchor_price_eur_per_mwh"] = candidate_predictions_long["oracle_anchor_price_eur_per_mwh"]
        candidate_predictions_long["actual_hourly_mean_eur_per_mwh"] = pd.concat(
            [validation_table, test_table, validation_table, test_table, validation_table, test_table, validation_table, test_table],
            ignore_index=True,
        )["actual_hourly_mean_eur_per_mwh"].to_numpy(dtype=float)
        candidate_predictions_long["hourly_anchor_candidate_key"] = candidate_key
        candidate_predictions_long["hourly_anchor_candidate_label"] = candidate_label
        candidate_predictions_long["hourly_anchor_role"] = role
        candidate_predictions_long["hourly_anchor_role_description"] = str(candidate_table["role_description"].iloc[0])
        candidate_predictions_long = candidate_predictions_long.drop(columns=["oracle_anchor_price_eur_per_mwh"])
        prediction_frames.append(candidate_predictions_long)

        shape_metrics = _shape_metrics(candidate_predictions_long)
        shape_metrics["hourly_anchor_candidate_key"] = candidate_key
        shape_metrics["hourly_anchor_candidate_label"] = candidate_label
        shape_metrics["hourly_anchor_role"] = role
        shape_metric_frames.append(shape_metrics)

        price_metrics = _price_metrics(candidate_predictions_long)
        price_metrics["hourly_anchor_candidate_key"] = candidate_key
        price_metrics["hourly_anchor_candidate_label"] = candidate_label
        price_metrics["hourly_anchor_role"] = role
        price_metric_frames.append(price_metrics)

        thresholds = _train_regime_thresholds(train_table)
        by_condition = _performance_by_condition(candidate_predictions_long, thresholds)
        if not by_condition.empty:
            by_condition["hourly_anchor_candidate_key"] = candidate_key
            by_condition["hourly_anchor_candidate_label"] = candidate_label
            by_condition["hourly_anchor_role"] = role
            condition_frames.append(by_condition)

        by_hour = _mae_by_hour(candidate_predictions_long)
        if not by_hour.empty:
            by_hour["hourly_anchor_candidate_key"] = candidate_key
            by_hour["hourly_anchor_candidate_label"] = candidate_label
            by_hour["hourly_anchor_role"] = role
            mae_hour_frames.append(by_hour)

        model_config_frames.append(
            _model_configuration_rows(
                candidate_key=candidate_key,
                candidate_label=candidate_label,
                role=role,
                selected_tuning=selected_tuning,
                candidate_model_table=candidate_table,
            )
        )

        validation_price = price_metrics[price_metrics["dataset_split"].astype(str) == "validation"].copy()
        test_price = price_metrics[price_metrics["dataset_split"].astype(str) == "test"].copy()
        recommended_validation_row = validation_price.sort_values(["mae", "model"]).iloc[0].to_dict() if not validation_price.empty else {}
        best_test_row = test_price.sort_values(["mae", "model"]).iloc[0].to_dict() if not test_price.empty else {}
        recommendation_rows.append(
            {
                "candidate_key": candidate_key,
                "candidate_label": candidate_label,
                "role": role,
                "selection_basis": "validation_reconstructed_price_mae",
                "recommended_model": str(recommended_validation_row.get("model", "")),
                "recommended_validation_mae": recommended_validation_row.get("mae"),
                "best_test_model": str(best_test_row.get("model", "")),
                "best_test_mae": best_test_row.get("mae"),
                "notes": "Recommendation is based on realistic end-to-end hourly-forecast-anchor validation.",
            }
        )

    predictions_long = pd.concat(prediction_frames, ignore_index=True).sort_values(
        ["hourly_anchor_candidate_key", "dataset_split", "model", "forecast_origin_utc", "target_timestamp_utc"]
    ).reset_index(drop=True)
    predictions_long.to_csv(run_dir / "predictions_long.csv", index=False)

    tuning_results = pd.DataFrame(tuning_rows).sort_values(
        ["candidate_key", "model", "validation_price_mae", "candidate_id"]
    ).reset_index(drop=True)
    tuning_results.to_csv(run_dir / "tuning_results.csv", index=False)

    shape_metrics = pd.concat(shape_metric_frames, ignore_index=True).sort_values(
        ["hourly_anchor_candidate_key", "dataset_split", "model"]
    ).reset_index(drop=True)
    shape_metrics.to_csv(run_dir / "shape_only_metrics.csv", index=False)

    price_metrics = pd.concat(price_metric_frames, ignore_index=True).sort_values(
        ["hourly_anchor_candidate_key", "dataset_split", "model"]
    ).reset_index(drop=True)
    price_metrics.to_csv(run_dir / "reconstructed_price_metrics.csv", index=False)

    performance_by_condition = (
        pd.concat(condition_frames, ignore_index=True).sort_values(
            ["hourly_anchor_candidate_key", "condition_group", "condition_value", "model"]
        ).reset_index(drop=True)
        if condition_frames
        else pd.DataFrame()
    )
    performance_by_condition.to_csv(run_dir / "performance_by_condition.csv", index=False)

    mae_by_hour = (
        pd.concat(mae_hour_frames, ignore_index=True).sort_values(
            ["hourly_anchor_candidate_key", "model", "local_hour_of_day"]
        ).reset_index(drop=True)
        if mae_hour_frames
        else pd.DataFrame()
    )
    mae_by_hour.to_csv(run_dir / "mae_by_hour.csv", index=False)

    model_configuration = pd.concat(model_config_frames, ignore_index=True).sort_values(
        ["candidate_key", "model"]
    ).reset_index(drop=True)
    model_configuration.to_csv(run_dir / "model_configuration_summary.csv", index=False)

    feature_summary = pd.concat(feature_summary_frames, ignore_index=True).sort_values(
        ["candidate_key", "feature_group", "feature"]
    ).reset_index(drop=True)
    feature_summary.to_csv(run_dir / "feature_column_summary.csv", index=False)
    if exclusion_frames:
        pd.concat(exclusion_frames, ignore_index=True).sort_values(
            ["candidate_key", "dataset_split", "forecast_origin_utc", "hour_start_utc", "quarter_index"]
        ).reset_index(drop=True).to_csv(run_dir / "modeling_row_exclusions.csv", index=False)
    else:
        pd.DataFrame(
            columns=[
                "dataset_split",
                "forecast_origin_utc",
                "delivery_local_date",
                "hour_start_utc",
                "quarter_index",
                "lead_day",
                "lead_day_label",
                "horizon_index",
                "candidate_key",
                "candidate_label",
                "role",
                "excluded_reason",
            ]
        ).to_csv(run_dir / "modeling_row_exclusions.csv", index=False)

    recommendation_summary = pd.DataFrame(recommendation_rows).sort_values(["role", "candidate_key"]).reset_index(drop=True)
    recommendation_summary.to_csv(run_dir / "recommended_model_summary.csv", index=False)

    example_days = _example_days(
        realistic_modeling_table[
            [
                "hour_start_utc",
                "hour_local_date",
                "hourly_mean_eur_per_mwh",
                "daily_anchor_spread",
                "abs_ramp_out",
            ]
        ]
        .drop_duplicates(subset=["hour_start_utc"])
        .copy()
    )
    example_days.to_csv(run_dir / "example_days.csv", index=False)

    comparison_rows: list[dict[str, Any]] = []
    if not phase04_price_metrics.empty:
        oracle_test = phase04_price_metrics[phase04_price_metrics["dataset_split"].astype(str) == "test"].copy()
        realistic_test = price_metrics[price_metrics["dataset_split"].astype(str) == "test"].copy()
        for candidate_key, group in realistic_test.groupby("hourly_anchor_candidate_key", dropna=False):
            merged = group.merge(
                oracle_test[["model", "mae"]].rename(columns={"mae": "oracle_test_mae"}),
                on="model",
                how="left",
            )
            merged["mae_gap_realistic_minus_oracle"] = merged["mae"] - merged["oracle_test_mae"]
            merged["candidate_key"] = candidate_key
            comparison_rows.extend(merged.to_dict(orient="records"))
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(run_dir / "oracle_vs_realistic_comparison.csv", index=False)

    checks, temporal_diagnostics = _phase07_checks(
        modeling_table=realistic_modeling_table,
        predictions=predictions_long,
        feasibility=feasibility,
        hourly_coverage=hourly_coverage,
        blocked=False,
    )
    checks.to_csv(run_dir / "validation_checks.csv", index=False)
    temporal_diagnostics.to_csv(run_dir / "validation_temporal_diagnostics.csv", index=False)

    run_summary = {
        "run_id": run_id,
        "phase": "phase07_realistic_track_a",
        "status": "completed",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "phase02_run_dir": str(phase02_run),
        "phase03_run_dir": str(phase03_run),
        "phase04_run_dir": str(phase04_run) if phase04_run is not None else None,
        "hourly_bridge_input_csv": str(bridge_csv),
        "selected_hourly_anchor_candidates": selected_anchor_models.to_dict(orient="records"),
        "status_summary": status_summary.iloc[0].to_dict(),
        "hourly_anchor_horizon_days": int(horizon_days),
        "hourly_anchor_scope": "rolling_origin_d_only" if int(horizon_days) == 1 else f"rolling_origin_d_to_d_plus_{int(horizon_days) - 1}",
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
