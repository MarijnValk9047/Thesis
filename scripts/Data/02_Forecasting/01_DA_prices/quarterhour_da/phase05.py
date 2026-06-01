from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import build_stitched_d_only_predictions, load_candidate_predictions

from .config import QuarterHourDAExtensionConfig
from .phase03 import find_latest_phase03_run
from .phase04 import (
    _build_feature_frame,
    _build_modeling_table,
    _fit_lear,
    _fit_mean_shape,
    _fit_xgboost,
    _predict_mean_shape,
    _prepare_shape_target,
    find_latest_phase04_run,
)
from .phase02 import find_latest_phase02_run


SEASON_MAP = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}

NUMERIC_FEATURE_COLUMNS = [
    "weekend_flag",
    "hourly_mean_eur_per_mwh",
    "prev_hour_anchor",
    "next_hour_anchor",
    "prev_hour_missing_flag",
    "next_hour_missing_flag",
    "ramp_in",
    "ramp_out",
    "abs_ramp_in",
    "abs_ramp_out",
    "daily_anchor_mean",
    "daily_anchor_min",
    "daily_anchor_max",
    "daily_anchor_spread",
    "daily_anchor_rank_pct",
    "negative_anchor_flag",
    "high_price_anchor_flag",
]


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase05_counterfactual_generation")


def find_latest_phase05_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase05_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _load_phase02_model_table(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    phase02_run = find_latest_phase02_run(config)
    if phase02_run is None:
        raise FileNotFoundError("Phase 2 artifacts are required before Phase 5 can run.")
    raw = pd.read_csv(phase02_run / "shape_target_long.csv")
    prepared = _prepare_shape_target(raw, timezone=config.business_timezone)
    model_table, hour_table = _build_modeling_table(prepared)
    return phase02_run, model_table, hour_table


def _load_phase03_context(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    phase03_run = find_latest_phase03_run(config)
    if phase03_run is None:
        raise FileNotFoundError("Phase 3 artifacts are required before Phase 5 can run.")
    selected_anchor_models = pd.read_csv(phase03_run / "selected_anchor_models.csv")
    candidate_frame = pd.read_csv(phase03_run / "candidate_frame_latest.csv")
    return phase03_run, selected_anchor_models, candidate_frame


def _load_phase04_context(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    phase04_run = find_latest_phase04_run(config)
    if phase04_run is None:
        raise FileNotFoundError("Phase 4 artifacts are required before Phase 5 can run.")
    recommended = pd.read_csv(phase04_run / "recommended_model_summary.csv")
    model_config = pd.read_csv(phase04_run / "model_configuration_summary.csv")
    return phase04_run, recommended, model_config


def _season_for_month(month_value: int) -> str:
    return SEASON_MAP.get(int(month_value), "unknown")


def _load_hourly_actuals(config: QuarterHourDAExtensionConfig) -> pd.DataFrame:
    hourly_config = HourlyDAPipelineConfig(output_root=config.hourly_da_output_root)
    frame = pd.read_csv(config.shared_hourly_csv)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)
    frame["timestamp_local"] = frame["timestamp_utc"].dt.tz_convert(config.business_timezone)
    frame["delivery_local_date"] = frame["timestamp_local"].dt.date
    frame = frame[
        frame["delivery_local_date"].between(hourly_config.test_start_local, hourly_config.test_end_local)
    ].copy()
    if frame.empty:
        raise ValueError("Official hourly test-period actuals could not be loaded from the shared cleaned hourly dataset.")
    frame["hour_start_utc"] = frame["timestamp_utc"]
    frame["hour_start_local"] = frame["timestamp_local"]
    frame["local_hour_of_day"] = frame["timestamp_local"].dt.hour.astype(int)
    frame["weekday"] = frame["timestamp_local"].dt.dayofweek.astype(int)
    frame["weekend_flag"] = frame["weekday"].isin([5, 6]).astype(int)
    frame["month"] = frame["timestamp_local"].dt.month.astype(int)
    frame["season"] = frame["month"].map(_season_for_month)
    frame["hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(frame["price_eur_per_mwh"], errors="coerce")
    frame["source_type"] = "actual_hourly"
    return frame.reset_index(drop=True)


def _enrich_hourly_anchor_frame(hourly_frame: pd.DataFrame) -> pd.DataFrame:
    sort_columns = ["hour_start_utc"]
    group_columns = ["delivery_local_date"]
    if "forecast_origin_utc" in hourly_frame.columns:
        sort_columns = ["forecast_origin_utc", "hour_start_utc"]
        group_columns = ["forecast_origin_utc", "delivery_local_date"]
    working = hourly_frame.copy().sort_values(sort_columns).reset_index(drop=True)
    day_group = working.groupby(group_columns)["hourly_anchor_price_eur_per_mwh"]
    working["prev_hour_anchor_raw"] = day_group.shift(1)
    working["next_hour_anchor_raw"] = day_group.shift(-1)
    working["prev_hour_missing_flag"] = working["prev_hour_anchor_raw"].isna().astype(int)
    working["next_hour_missing_flag"] = working["next_hour_anchor_raw"].isna().astype(int)
    working["prev_hour_anchor"] = working["prev_hour_anchor_raw"].fillna(working["hourly_anchor_price_eur_per_mwh"])
    working["next_hour_anchor"] = working["next_hour_anchor_raw"].fillna(working["hourly_anchor_price_eur_per_mwh"])
    working["ramp_in"] = working["hourly_anchor_price_eur_per_mwh"] - working["prev_hour_anchor"]
    working["ramp_out"] = working["next_hour_anchor"] - working["hourly_anchor_price_eur_per_mwh"]
    working["abs_ramp_in"] = working["ramp_in"].abs()
    working["abs_ramp_out"] = working["ramp_out"].abs()
    working["hourly_ramp_abs"] = working[["abs_ramp_in", "abs_ramp_out"]].max(axis=1)
    working["daily_anchor_mean"] = day_group.transform("mean")
    working["daily_anchor_min"] = day_group.transform("min")
    working["daily_anchor_max"] = day_group.transform("max")
    working["daily_anchor_spread"] = working["daily_anchor_max"] - working["daily_anchor_min"]
    working["daily_anchor_rank_pct"] = day_group.rank(method="average", pct=True)
    working["negative_anchor_flag"] = working["hourly_anchor_price_eur_per_mwh"].lt(0.0).astype(int)

    def _high_price_flag(group: pd.Series) -> pd.Series:
        threshold = float(group.quantile(0.75))
        return group.ge(threshold).astype(int)

    working["high_price_anchor_flag"] = day_group.transform(_high_price_flag).astype(int)
    working["hourly_mean_eur_per_mwh"] = working["hourly_anchor_price_eur_per_mwh"]
    return working


def _expand_hourly_to_quarters(hourly_frame: pd.DataFrame, *, source_type: str, shape_method: str, scenario_variant: str | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    quarter_offsets = [0, 15, 30, 45]
    for row in hourly_frame.to_dict(orient="records"):
        hour_start_utc = pd.Timestamp(row["hour_start_utc"])
        for quarter_index, minute in enumerate(quarter_offsets, start=1):
            timestamp_utc = hour_start_utc + pd.Timedelta(minutes=minute)
            timestamp_local = timestamp_utc.tz_convert("Europe/Amsterdam")
            rows.append(
                {
                    **row,
                    "timestamp_utc": timestamp_utc,
                    "timestamp_local": timestamp_local,
                    "local_minute": int(minute),
                    "quarter_index": int(quarter_index),
                    "source_type": source_type,
                    "shape_method": shape_method,
                    "scenario_variant": scenario_variant,
                }
            )
    expanded = pd.DataFrame(rows).sort_values(["hour_start_utc", "quarter_index"]).reset_index(drop=True)
    expanded["delivery_local_date"] = expanded["timestamp_local"].dt.date
    expanded["local_hour_of_day"] = expanded["timestamp_local"].dt.hour.astype(int)
    expanded["weekday"] = expanded["timestamp_local"].dt.dayofweek.astype(int)
    expanded["weekend_flag"] = expanded["weekday"].isin([5, 6]).astype(int)
    expanded["month"] = expanded["timestamp_local"].dt.month.astype(int)
    expanded["season"] = expanded["month"].map(_season_for_month)
    return expanded


def _build_prediction_features(expanded_frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    X, _, _ = _build_feature_frame(expanded_frame)
    return X.reindex(columns=feature_columns, fill_value=0.0)


def _load_selected_hourly_forecasts(
    config: QuarterHourDAExtensionConfig,
    *,
    candidate_frame: pd.DataFrame,
    selected_anchor_models: pd.DataFrame,
) -> pd.DataFrame:
    hourly_config = HourlyDAPipelineConfig(output_root=config.hourly_da_output_root)
    selected_keys = set(selected_anchor_models["candidate_key"].astype(str).tolist())
    selected_candidates = candidate_frame[candidate_frame["candidate_key"].astype(str).isin(selected_keys)].copy()
    predictions = load_candidate_predictions(candidate_frame=selected_candidates, config=hourly_config)
    stitched = build_stitched_d_only_predictions(predictions, split_name="test")
    if stitched.empty:
        raise ValueError("No stitched D-only hourly forecasts were available for the selected hourly anchor candidates.")
    role_lookup = selected_anchor_models[
        ["candidate_key", "role", "role_description", "candidate_label", "source_run_id", "source_run_label"]
    ].drop_duplicates()
    stitched = stitched.merge(role_lookup, on="candidate_key", how="left", suffixes=("", "_selected"))
    if "candidate_label_selected" in stitched.columns:
        stitched["candidate_label"] = stitched["candidate_label_selected"].fillna(stitched.get("candidate_label"))
        stitched = stitched.drop(columns=["candidate_label_selected"])
    if "source_run_id_selected" in stitched.columns:
        stitched["source_run_id"] = stitched["source_run_id_selected"].fillna(stitched.get("source_run_id"))
        stitched = stitched.drop(columns=["source_run_id_selected"])
    if "source_run_label_selected" in stitched.columns:
        stitched["source_run_label"] = stitched["source_run_label_selected"].fillna(stitched.get("source_run_label"))
        stitched = stitched.drop(columns=["source_run_label_selected"])
    stitched["target_timestamp_utc"] = pd.to_datetime(stitched["target_timestamp_utc"], utc=True, errors="coerce")
    stitched["target_timestamp_local"] = pd.to_datetime(stitched["target_timestamp_local"], utc=True, errors="coerce").dt.tz_convert(
        config.business_timezone
    )
    stitched["target_local_date"] = pd.to_datetime(stitched["target_local_date"], errors="coerce").dt.date
    stitched["hour_start_utc"] = stitched["target_timestamp_utc"]
    stitched["hour_start_local"] = stitched["target_timestamp_local"]
    stitched["delivery_local_date"] = stitched["target_local_date"]
    stitched["local_hour_of_day"] = pd.to_numeric(stitched["target_local_hour"], errors="coerce").astype(int)
    stitched["weekday"] = stitched["target_timestamp_local"].dt.dayofweek.astype(int)
    stitched["weekend_flag"] = stitched["weekday"].isin([5, 6]).astype(int)
    stitched["month"] = stitched["target_timestamp_local"].dt.month.astype(int)
    stitched["season"] = stitched["month"].map(_season_for_month)
    stitched["hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(stitched["y_pred"], errors="coerce")
    stitched["source_type"] = "forecast_hourly"
    stitched = stitched.sort_values(["candidate_key", "hour_start_utc"]).reset_index(drop=True)
    return stitched


def _select_shape_model_context(recommended: pd.DataFrame, model_config: pd.DataFrame) -> dict[str, Any]:
    if recommended.empty:
        raise ValueError("Phase 4 recommended model summary is empty.")
    recommended_model = str(recommended.iloc[0]["recommended_model"])
    config_row = model_config[model_config["model"].astype(str) == recommended_model].copy()
    if config_row.empty:
        raise ValueError(f"Recommended Phase 4 model '{recommended_model}' was missing from the model configuration summary.")
    hyperparams_json = str(config_row.iloc[0]["key_hyperparameters"])
    hyperparams = json.loads(hyperparams_json) if hyperparams_json and hyperparams_json != "nan" else {}
    return {
        "recommended_model": recommended_model,
        "feature_set": str(config_row.iloc[0]["feature_set"]),
        "retraining_policy": str(config_row.iloc[0]["retraining_policy"]),
        "hyperparameters": hyperparams,
    }


def _fit_shape_model_on_full_observed(
    model_context: dict[str, Any],
    model_table: pd.DataFrame,
) -> tuple[dict[str, Any], list[str]]:
    X_full, feature_columns, _ = _build_feature_frame(model_table)
    y_full = model_table["delta_eur_per_mwh"].astype(float).reset_index(drop=True)
    recommended_model = model_context["recommended_model"]
    if recommended_model == "mean_shape":
        state = _fit_mean_shape(model_table.reset_index(drop=True))
        return {"type": "mean_shape", "state": state}, feature_columns
    if recommended_model == "lear_shape":
        alpha = float(model_context["hyperparameters"].get("alpha", 0.01))
        learner = _fit_lear(X_full.reset_index(drop=True), y_full, alpha=alpha)
        return {"type": "lear_shape", "model": learner}, feature_columns
    if recommended_model == "xgboost_shape":
        params = dict(model_context["hyperparameters"])
        learner = _fit_xgboost(X_full.reset_index(drop=True), y_full, params)
        return {"type": "xgboost_shape", "model": learner}, feature_columns
    raise ValueError(f"Unsupported recommended shape model: {recommended_model}")


def _predict_shape_deltas(
    shape_model: dict[str, Any],
    expanded_frame: pd.DataFrame,
    feature_columns: list[str],
) -> np.ndarray:
    model_type = str(shape_model["type"])
    if model_type == "mean_shape":
        return _predict_mean_shape(shape_model["state"], expanded_frame)
    X_pred = _build_prediction_features(expanded_frame, feature_columns)
    if model_type == "lear_shape":
        return shape_model["model"].predict(X_pred)
    if model_type == "xgboost_shape":
        return shape_model["model"].predict(X_pred)
    raise ValueError(f"Unsupported shape model type: {model_type}")


def _apply_zero_mean(prediction_frame: pd.DataFrame) -> pd.DataFrame:
    working = prediction_frame.copy()
    working["delta_pred_raw"] = pd.to_numeric(working["delta_pred_raw"], errors="coerce").astype(np.float64)
    hourly_mean = working.groupby("hour_start_utc")["delta_pred_raw"].transform("mean").astype(np.float64)
    working["delta_pred_adjusted"] = working["delta_pred_raw"] - hourly_mean
    residual_mean = working.groupby("hour_start_utc")["delta_pred_adjusted"].transform("mean").astype(np.float64)
    working["delta_pred_adjusted"] = working["delta_pred_adjusted"] - residual_mean
    working["hourly_mean_preservation_error"] = (
        working.groupby("hour_start_utc")["delta_pred_adjusted"].transform("mean").astype(np.float64)
    )
    working["predicted_price_eur_per_mwh"] = (
        working["hourly_anchor_price_eur_per_mwh"].astype(np.float64) + working["delta_pred_adjusted"]
    )
    return working


def _build_shape_forecast_inputs(
    hourly_forecasts: pd.DataFrame,
    *,
    shape_model: dict[str, Any],
    feature_columns: list[str],
    model_context: dict[str, Any],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for candidate_key, group in hourly_forecasts.groupby("candidate_key", dropna=False):
        hourly_enriched = _enrich_hourly_anchor_frame(group.copy())
        expanded = _expand_hourly_to_quarters(
            hourly_enriched,
            source_type="counterfactual_15min_shape_forecast_input",
            shape_method=str(model_context["recommended_model"]),
            scenario_variant="point_forecast",
        )
        delta_pred_raw = _predict_shape_deltas(shape_model, expanded, feature_columns)
        expanded["delta_pred_raw"] = delta_pred_raw
        expanded = _apply_zero_mean(expanded)
        expanded["hourly_anchor_candidate_key"] = str(candidate_key)
        rows.append(expanded)
    return pd.concat(rows, ignore_index=True).sort_values(["hourly_anchor_candidate_key", "hour_start_utc", "quarter_index"]).reset_index(drop=True)


def _build_flat_forecast_inputs(hourly_forecasts: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for candidate_key, group in hourly_forecasts.groupby("candidate_key", dropna=False):
        hourly_enriched = _enrich_hourly_anchor_frame(group.copy())
        expanded = _expand_hourly_to_quarters(
            hourly_enriched,
            source_type="counterfactual_15min_flat_forecast_input",
            shape_method="flat_repeat",
            scenario_variant="point_forecast",
        )
        expanded["delta_pred_raw"] = 0.0
        expanded = _apply_zero_mean(expanded)
        expanded["hourly_anchor_candidate_key"] = str(candidate_key)
        rows.append(expanded)
    return pd.concat(rows, ignore_index=True).sort_values(["hourly_anchor_candidate_key", "hour_start_utc", "quarter_index"]).reset_index(drop=True)


def _build_observed_shape_library(model_table: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    hour_level = (
        model_table.groupby("hour_start_utc", dropna=False)
        .agg(
            hour_start_local=("hour_start_local", "first"),
            delivery_local_date=("hour_local_date", "first"),
            local_hour_of_day=("local_hour_of_day", "first"),
            weekend_flag=("weekend_flag", "first"),
            month=("month", "first"),
            season=("season", "first"),
            hourly_anchor_price_eur_per_mwh=("hourly_mean_eur_per_mwh", "first"),
            ramp_in=("ramp_in", "first"),
            ramp_out=("ramp_out", "first"),
            daily_anchor_spread=("daily_anchor_spread", "first"),
        )
        .reset_index()
    )
    pivot = (
        model_table.pivot(index="hour_start_utc", columns="quarter_index", values="delta_eur_per_mwh")
        .rename(columns={1: "delta_q1", 2: "delta_q2", 3: "delta_q3", 4: "delta_q4"})
        .reset_index()
    )
    library = hour_level.merge(pivot, on="hour_start_utc", how="inner")
    library["abs_ramp_in"] = library["ramp_in"].abs()
    library["abs_ramp_out"] = library["ramp_out"].abs()
    library["hourly_ramp_abs"] = library[["abs_ramp_in", "abs_ramp_out"]].max(axis=1)
    library["max_abs_delta"] = library[["delta_q1", "delta_q2", "delta_q3", "delta_q4"]].abs().max(axis=1)
    library["mean_abs_delta"] = library[["delta_q1", "delta_q2", "delta_q3", "delta_q4"]].abs().mean(axis=1)
    library["intra_hour_spread"] = library[["delta_q1", "delta_q2", "delta_q3", "delta_q4"]].max(axis=1) - library[
        ["delta_q1", "delta_q2", "delta_q3", "delta_q4"]
    ].min(axis=1)

    nonnegative_anchor = library.loc[library["hourly_anchor_price_eur_per_mwh"].ge(0.0), "hourly_anchor_price_eur_per_mwh"]
    thresholds = {
        "daily_spread_low": float(library["daily_anchor_spread"].quantile(1 / 3)),
        "daily_spread_high": float(library["daily_anchor_spread"].quantile(2 / 3)),
        "hourly_ramp_low": float(library["hourly_ramp_abs"].quantile(1 / 3)),
        "hourly_ramp_high": float(library["hourly_ramp_abs"].quantile(2 / 3)),
        "high_price_threshold": float(nonnegative_anchor.quantile(0.75)) if not nonnegative_anchor.empty else float("nan"),
        "stress_intra_hour_spread_q90": float(library["intra_hour_spread"].quantile(0.90)),
    }
    library = _assign_anchor_regimes(library, thresholds)
    return library, thresholds


def _assign_anchor_regimes(frame: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    working = frame.copy()

    def _bucket_spread(value: float) -> str:
        if value <= thresholds["daily_spread_low"]:
            return "low"
        if value <= thresholds["daily_spread_high"]:
            return "medium"
        return "high"

    def _bucket_ramp(value: float) -> str:
        if value <= thresholds["hourly_ramp_low"]:
            return "low"
        if value <= thresholds["hourly_ramp_high"]:
            return "medium"
        return "high"

    def _bucket_price(value: float) -> str:
        if value < 0.0:
            return "negative"
        if np.isnan(thresholds["high_price_threshold"]):
            return "normal"
        return "high" if value >= thresholds["high_price_threshold"] else "normal"

    working["daily_spread_regime"] = working["daily_anchor_spread"].astype(float).map(_bucket_spread)
    working["hourly_ramp_regime"] = working["hourly_ramp_abs"].astype(float).map(_bucket_ramp)
    working["hourly_price_regime"] = working["hourly_anchor_price_eur_per_mwh"].astype(float).map(_bucket_price)
    return working


def _sample_shape_row(
    library: pd.DataFrame,
    stress_library: pd.DataFrame,
    target_row: pd.Series,
    rng: np.random.Generator,
    *,
    use_stress: bool,
) -> tuple[np.ndarray, str, str | None]:
    hour_value = int(target_row["local_hour_of_day"])
    weekend_flag = int(target_row["weekend_flag"])
    ramp_regime = str(target_row["hourly_ramp_regime"])
    price_regime = str(target_row["hourly_price_regime"])

    if use_stress:
        hierarchy = [
            ("stress_hour_weekend", stress_library[(stress_library["local_hour_of_day"] == hour_value) & (stress_library["weekend_flag"] == weekend_flag)]),
            ("stress_hour_only", stress_library[stress_library["local_hour_of_day"] == hour_value]),
            ("stress_global", stress_library),
            ("global_any", library),
        ]
    else:
        hierarchy = [
            (
                "hour_ramp_price",
                library[
                    (library["local_hour_of_day"] == hour_value)
                    & (library["hourly_ramp_regime"].astype(str) == ramp_regime)
                    & (library["hourly_price_regime"].astype(str) == price_regime)
                ],
            ),
            (
                "hour_weekend",
                library[(library["local_hour_of_day"] == hour_value) & (library["weekend_flag"] == weekend_flag)],
            ),
            ("hour_only", library[library["local_hour_of_day"] == hour_value]),
            ("global_any", library),
        ]

    for level_name, pool in hierarchy:
        if pool.empty:
            continue
        selected = pool.iloc[int(rng.integers(0, pool.shape[0]))]
        delta_vector = np.asarray(
            [selected["delta_q1"], selected["delta_q2"], selected["delta_q3"], selected["delta_q4"]],
            dtype=float,
        )
        return delta_vector, level_name, pd.Timestamp(selected["hour_start_utc"]).isoformat()
    raise ValueError("No empirical shape library rows were available for sampling.")


def _build_stress_library(library: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    stress = library[
        (library["hourly_ramp_regime"].astype(str) == "high")
        & (library["daily_spread_regime"].astype(str) == "high")
    ].copy()
    tail = library[library["intra_hour_spread"].astype(float) >= thresholds["stress_intra_hour_spread_q90"]].copy()
    if stress.empty:
        return tail.reset_index(drop=True)
    combined = pd.concat([stress, tail], ignore_index=True).drop_duplicates(subset=["hour_start_utc"])
    return combined.reset_index(drop=True)


def _generate_counterfactual_realized_paths(
    hourly_actuals: pd.DataFrame,
    *,
    library: pd.DataFrame,
    thresholds: dict[str, float],
    random_seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly_enriched = _enrich_hourly_anchor_frame(hourly_actuals.copy())
    target_hours = _assign_anchor_regimes(hourly_enriched, thresholds).copy()
    stress_library = _build_stress_library(library, thresholds)
    rng = np.random.default_rng(int(random_seed))

    records: list[dict[str, Any]] = []
    quarter_rows: list[dict[str, Any]] = []
    variant_scale = {
        "flat": 0.0,
        "low_volatility": 0.5,
        "empirical_medium": 1.0,
        "high_volatility": 1.5,
    }
    quarter_offsets = [0, 15, 30, 45]

    for row in target_hours.to_dict(orient="records"):
        hour_row = pd.Series(row)
        base_delta, base_backoff, base_source = _sample_shape_row(library, stress_library, hour_row, rng, use_stress=False)
        stress_delta, stress_backoff, stress_source = _sample_shape_row(library, stress_library, hour_row, rng, use_stress=True)
        sampled_lookup = {
            "flat": (np.zeros(4, dtype=float), "deterministic_flat", None),
            "low_volatility": (base_delta * variant_scale["low_volatility"], base_backoff, base_source),
            "empirical_medium": (base_delta * variant_scale["empirical_medium"], base_backoff, base_source),
            "high_volatility": (base_delta * variant_scale["high_volatility"], base_backoff, base_source),
            "stress": (stress_delta.copy(), stress_backoff, stress_source),
        }

        for variant_name, (delta_vector, backoff_level, sampled_source_hour_start_utc) in sampled_lookup.items():
            adjusted = delta_vector - float(np.mean(delta_vector))
            hour_start_utc = pd.Timestamp(row["hour_start_utc"])
            hour_start_local = pd.Timestamp(row["hour_start_local"])
            for quarter_index, minute in enumerate(quarter_offsets, start=1):
                timestamp_utc = hour_start_utc + pd.Timedelta(minutes=minute)
                timestamp_local = timestamp_utc.tz_convert("Europe/Amsterdam")
                sampled_delta = float(adjusted[quarter_index - 1])
                quarter_rows.append(
                    {
                        **row,
                        "timestamp_utc": timestamp_utc,
                        "timestamp_local": timestamp_local,
                        "delivery_local_date": timestamp_local.date(),
                        "local_hour_of_day": int(timestamp_local.hour),
                        "local_minute": int(minute),
                        "quarter_index": int(quarter_index),
                        "source_type": "counterfactual_15min_realized",
                        "shape_method": "empirical_block_sampler",
                        "scenario_variant": variant_name,
                        "sampled_delta_eur_per_mwh": sampled_delta,
                        "sampled_delta_source_hour_start_utc": sampled_source_hour_start_utc,
                        "sampler_backoff_level": backoff_level,
                        "predicted_price_eur_per_mwh": float(row["hourly_anchor_price_eur_per_mwh"]) + sampled_delta,
                    }
                )
            records.append(
                {
                    "scenario_variant": variant_name,
                    "hour_start_utc": pd.Timestamp(row["hour_start_utc"]).isoformat(),
                    "sampler_backoff_level": backoff_level,
                    "sampled_delta_source_hour_start_utc": sampled_source_hour_start_utc,
                }
            )

    realized = pd.DataFrame(quarter_rows).sort_values(["scenario_variant", "hour_start_utc", "quarter_index"]).reset_index(drop=True)
    realized["hourly_mean_preservation_error"] = realized.groupby(["scenario_variant", "hour_start_utc"])["sampled_delta_eur_per_mwh"].transform("mean")
    backoff = pd.DataFrame(records)
    return realized, backoff


def _counterfactual_generation_summary(realized: pd.DataFrame, backoff: pd.DataFrame, *, observed_start: str, observed_end: str, random_seed: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant_name, group in realized.groupby("scenario_variant", dropna=False):
        preservation = group.groupby("hour_start_utc")["hourly_mean_preservation_error"].first().abs()
        abs_delta = group["sampled_delta_eur_per_mwh"].abs()
        day_count = int(group["delivery_local_date"].astype(str).nunique())
        rows.append(
            {
                "scenario_variant": str(variant_name),
                "anchor_period_start": str(group["delivery_local_date"].min()),
                "anchor_period_end": str(group["delivery_local_date"].max()),
                "source_shape_library_period": f"{observed_start} to {observed_end}",
                "number_of_generated_days": day_count,
                "number_of_generated_quarterhours": int(group.shape[0]),
                "average_hourly_mean_preservation_error": float(preservation.mean()),
                "max_hourly_mean_preservation_error": float(preservation.max()),
                "average_absolute_quarterhour_deviation": float(abs_delta.mean()),
                "p95_absolute_quarterhour_deviation": float(abs_delta.quantile(0.95)),
                "random_seed": int(random_seed),
                "notes": "All generated quarter-hour series preserve the hourly mean exactly after zero-mean normalization of the sampled shape vector.",
            }
        )
    summary = pd.DataFrame(rows).sort_values("scenario_variant").reset_index(drop=True)
    backoff_summary = (
        backoff.groupby(["scenario_variant", "sampler_backoff_level"], dropna=False)
        .size()
        .rename("hour_count")
        .reset_index()
        .sort_values(["scenario_variant", "sampler_backoff_level"])
        .reset_index(drop=True)
    )
    return summary, backoff_summary


def _forecast_input_summary(frame: pd.DataFrame, *, source_type: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(["hourly_anchor_candidate_key"], dropna=False):
        candidate_key = keys
        preservation = group.groupby("hour_start_utc")["hourly_mean_preservation_error"].first().abs()
        rows.append(
            {
                "source_type": source_type,
                "hourly_anchor_candidate_key": str(candidate_key),
                "period_start_local_date": str(group["delivery_local_date"].min()),
                "period_end_local_date": str(group["delivery_local_date"].max()),
                "number_of_generated_days": int(group["delivery_local_date"].astype(str).nunique()),
                "number_of_generated_quarterhours": int(group.shape[0]),
                "average_hourly_mean_preservation_error": float(preservation.mean()),
                "max_hourly_mean_preservation_error": float(preservation.max()),
                "average_absolute_quarterhour_deviation": float(group["delta_pred_adjusted"].abs().mean()),
                "p95_absolute_quarterhour_deviation": float(group["delta_pred_adjusted"].abs().quantile(0.95)),
            }
        )
    return pd.DataFrame(rows).sort_values("hourly_anchor_candidate_key").reset_index(drop=True)


def _hourly_forecast_coverage_summary(hourly_forecasts: pd.DataFrame) -> pd.DataFrame:
    return (
        hourly_forecasts.groupby(["candidate_key", "candidate_label", "role"], dropna=False)
        .agg(
            period_start_local_date=("delivery_local_date", "min"),
            period_end_local_date=("delivery_local_date", "max"),
            number_of_days=("delivery_local_date", lambda values: int(pd.Series(values).astype(str).nunique())),
            number_of_hours=("hour_start_utc", "size"),
        )
        .reset_index()
        .sort_values(["role", "candidate_label"])
        .reset_index(drop=True)
    )


def _build_checks(
    realized: pd.DataFrame,
    flat_inputs: pd.DataFrame,
    shape_inputs: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, frame, delta_col, group_cols in (
        ("counterfactual_realized", realized, "sampled_delta_eur_per_mwh", ["scenario_variant", "hour_start_utc"]),
        ("flat_forecast_input", flat_inputs, "delta_pred_adjusted", ["hourly_anchor_candidate_key", "hour_start_utc"]),
        ("shape_forecast_input", shape_inputs, "delta_pred_adjusted", ["hourly_anchor_candidate_key", "hour_start_utc"]),
    ):
        preservation = frame.groupby(group_cols, dropna=False)[delta_col].mean().abs()
        rows.append(
            {
                "check_name": f"hourly_mean_preservation::{name}",
                "status": "pass" if float(preservation.max()) < 1e-9 else "fail",
                "details": f"max_abs_hourly_mean_preservation_error={float(preservation.max()):.6g}",
            }
        )
    checks = pd.DataFrame(rows)
    failures = checks[checks["status"].astype(str) == "fail"]
    if not failures.empty:
        raise ValueError(f"Phase 5 preservation checks failed: {failures['check_name'].tolist()}")
    return checks


def run_phase05_counterfactual_generation(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = config.phase05_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    phase02_run, model_table, _ = _load_phase02_model_table(config)
    phase03_run, selected_anchor_models, candidate_frame = _load_phase03_context(config)
    phase04_run, recommended, model_config = _load_phase04_context(config)

    model_context = _select_shape_model_context(recommended, model_config)
    shape_model, feature_columns = _fit_shape_model_on_full_observed(model_context, model_table.reset_index(drop=True))

    observed_start = str(model_table["delivery_local_date"].min())
    observed_end = str(model_table["delivery_local_date"].max())
    library, thresholds = _build_observed_shape_library(model_table.reset_index(drop=True))

    hourly_actuals = _load_hourly_actuals(config)
    hourly_actuals = _enrich_hourly_anchor_frame(hourly_actuals)
    hourly_actuals.to_csv(run_dir / "hourly_actual_test_period.csv", index=False)

    hourly_forecasts = _load_selected_hourly_forecasts(
        config,
        candidate_frame=candidate_frame,
        selected_anchor_models=selected_anchor_models,
    )
    hourly_forecasts.to_csv(run_dir / "hourly_forecast_selected_long.csv", index=False)
    coverage_summary = _hourly_forecast_coverage_summary(hourly_forecasts)
    coverage_summary.to_csv(run_dir / "hourly_forecast_coverage_summary.csv", index=False)

    realized, backoff = _generate_counterfactual_realized_paths(
        hourly_actuals,
        library=library,
        thresholds=thresholds,
        random_seed=42,
    )
    realized.to_csv(run_dir / "counterfactual_realized_15min_long.csv", index=False)
    backoff.to_csv(run_dir / "counterfactual_sampler_backoff_log.csv", index=False)
    generation_summary, backoff_summary = _counterfactual_generation_summary(
        realized,
        backoff,
        observed_start=observed_start,
        observed_end=observed_end,
        random_seed=42,
    )
    generation_summary.to_csv(run_dir / "counterfactual_generation_summary.csv", index=False)
    backoff_summary.to_csv(run_dir / "counterfactual_backoff_summary.csv", index=False)

    flat_inputs = _build_flat_forecast_inputs(hourly_forecasts)
    flat_inputs.to_csv(run_dir / "counterfactual_flat_forecast_input_15min_long.csv", index=False)
    flat_summary = _forecast_input_summary(flat_inputs, source_type="counterfactual_15min_flat_forecast_input")
    flat_summary.to_csv(run_dir / "counterfactual_flat_forecast_input_summary.csv", index=False)

    shape_inputs = _build_shape_forecast_inputs(
        hourly_forecasts,
        shape_model=shape_model,
        feature_columns=feature_columns,
        model_context=model_context,
    )
    shape_inputs.to_csv(run_dir / "counterfactual_shape_forecast_input_15min_long.csv", index=False)
    shape_summary = _forecast_input_summary(shape_inputs, source_type="counterfactual_15min_shape_forecast_input")
    shape_summary.to_csv(run_dir / "counterfactual_shape_forecast_input_summary.csv", index=False)

    checks = _build_checks(realized, flat_inputs, shape_inputs)
    checks.to_csv(run_dir / "validation_checks.csv", index=False)

    shape_model_summary = pd.DataFrame(
        [
            {
                "recommended_model": model_context["recommended_model"],
                "feature_set": model_context["feature_set"],
                "retraining_policy": model_context["retraining_policy"],
                "hyperparameters_json": json.dumps(model_context["hyperparameters"], sort_keys=True),
                "fit_observed_start": observed_start,
                "fit_observed_end": observed_end,
                "fit_rows": int(model_table.shape[0]),
                "feature_count": int(len(feature_columns)),
            }
        ]
    )
    shape_model_summary.to_csv(run_dir / "shape_model_for_counterfactual_summary.csv", index=False)

    run_summary = {
        "run_id": run_id,
        "phase": "phase05_counterfactual_generation",
        "legacy_exploratory_only": True,
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "phase02_run_dir": str(phase02_run),
        "phase03_run_dir": str(phase03_run),
        "phase04_run_dir": str(phase04_run),
        "recommended_shape_model": shape_model_summary.iloc[0].to_dict(),
        "observed_shape_library_rows": int(library.shape[0]),
        "observed_shape_library_start": observed_start,
        "observed_shape_library_end": observed_end,
        "hourly_actual_period_start": str(hourly_actuals["delivery_local_date"].min()),
        "hourly_actual_period_end": str(hourly_actuals["delivery_local_date"].max()),
        "hourly_forecast_period_start": str(hourly_forecasts["delivery_local_date"].min()),
        "hourly_forecast_period_end": str(hourly_forecasts["delivery_local_date"].max()),
        "hourly_forecast_days_available": int(hourly_forecasts["delivery_local_date"].astype(str).nunique()),
        "counterfactual_variants": generation_summary.to_dict(orient="records"),
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
