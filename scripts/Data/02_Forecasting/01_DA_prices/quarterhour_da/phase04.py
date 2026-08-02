from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import load_candidate_predictions

from .config import QuarterHourDAExtensionConfig
from .phase02 import find_latest_phase02_run
from .phase03 import find_latest_phase03_run


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

LEARNED_MODEL_ORDER = ("lear_shape", "xgboost_shape")
ALL_MODEL_ORDER = ("flat_repeat", "mean_shape", "lear_shape", "xgboost_shape")


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase04_empirical_validation")


def find_latest_phase04_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase04_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _load_shape_target(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame]:
    phase02_run = find_latest_phase02_run(config)
    if phase02_run is None:
        raise FileNotFoundError("Phase 2 artifacts are required before Phase 4 can run.")
    frame = pd.read_csv(phase02_run / "shape_target_long.csv")
    if frame.empty:
        raise ValueError("Phase 2 shape target is empty.")
    return phase02_run, frame


def _load_phase03_context(config: QuarterHourDAExtensionConfig) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    phase03_run = find_latest_phase03_run(config)
    if phase03_run is None:
        raise FileNotFoundError("Phase 3 artifacts are required before Phase 4 can run.")
    selected_anchor_models = pd.read_csv(phase03_run / "selected_anchor_models.csv")
    candidate_frame = pd.read_csv(phase03_run / "candidate_frame_latest.csv")
    return phase03_run, selected_anchor_models, candidate_frame


def _prepare_shape_target(frame: pd.DataFrame, *, timezone: str) -> pd.DataFrame:
    working = frame.copy()
    for column in ("timestamp_utc", "hour_start_utc"):
        working[column] = pd.to_datetime(working[column], utc=True, errors="coerce")
    for column in ("timestamp_local", "hour_start_local"):
        working[column] = pd.to_datetime(working[column], utc=True, errors="coerce").dt.tz_convert(timezone)
    for column in ("delivery_local_date", "hour_local_date"):
        working[column] = pd.to_datetime(working[column], errors="coerce").dt.date
    bool_columns = (
        "is_interpolated_value",
        "is_flagged_missing_value",
        "hour_contains_interpolation",
        "hour_contains_flagged_missing",
    )
    for column in bool_columns:
        working[column] = working[column].astype(bool)
    numeric_columns = (
        "local_hour_of_day",
        "local_minute",
        "quarter_index",
        "price_eur_per_mwh",
        "hourly_mean_eur_per_mwh",
        "delta_eur_per_mwh",
        "abs_delta_eur_per_mwh",
        "delta_zero_mean_check_abs",
    )
    for column in numeric_columns:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    if working["hour_start_utc"].duplicated().sum() == 0:
        pass
    working = working.sort_values(["hour_start_utc", "quarter_index"]).reset_index(drop=True)
    return working


def _season_for_month(month_value: int) -> str:
    return SEASON_MAP.get(int(month_value), "unknown")


def _build_modeling_table(shape_target: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = shape_target.copy()
    working["weekday"] = working["timestamp_local"].dt.dayofweek.astype(int)
    working["weekend_flag"] = working["weekday"].isin([5, 6]).astype(int)
    working["month"] = working["timestamp_local"].dt.month.astype(int)
    working["season"] = working["month"].map(_season_for_month)

    hour_table = (
        working[
            [
                "hour_start_utc",
                "hour_start_local",
                "hour_local_date",
                "local_hour_of_day",
                "hourly_mean_eur_per_mwh",
                "dataset_split",
                "hour_group_quality",
                "hour_contains_interpolation",
                "hour_contains_flagged_missing",
            ]
        ]
        .drop_duplicates(subset=["hour_start_utc"])
        .sort_values("hour_start_utc")
        .reset_index(drop=True)
    )
    hour_table["prev_hour_anchor_raw"] = hour_table.groupby("hour_local_date")["hourly_mean_eur_per_mwh"].shift(1)
    hour_table["next_hour_anchor_raw"] = hour_table.groupby("hour_local_date")["hourly_mean_eur_per_mwh"].shift(-1)
    hour_table["prev_hour_missing_flag"] = hour_table["prev_hour_anchor_raw"].isna().astype(int)
    hour_table["next_hour_missing_flag"] = hour_table["next_hour_anchor_raw"].isna().astype(int)
    hour_table["prev_hour_anchor"] = hour_table["prev_hour_anchor_raw"].fillna(hour_table["hourly_mean_eur_per_mwh"])
    hour_table["next_hour_anchor"] = hour_table["next_hour_anchor_raw"].fillna(hour_table["hourly_mean_eur_per_mwh"])
    hour_table["ramp_in"] = hour_table["hourly_mean_eur_per_mwh"] - hour_table["prev_hour_anchor"]
    hour_table["ramp_out"] = hour_table["next_hour_anchor"] - hour_table["hourly_mean_eur_per_mwh"]
    hour_table["abs_ramp_in"] = hour_table["ramp_in"].abs()
    hour_table["abs_ramp_out"] = hour_table["ramp_out"].abs()

    day_group = hour_table.groupby("hour_local_date")["hourly_mean_eur_per_mwh"]
    hour_table["daily_anchor_mean"] = day_group.transform("mean")
    hour_table["daily_anchor_min"] = day_group.transform("min")
    hour_table["daily_anchor_max"] = day_group.transform("max")
    hour_table["daily_anchor_spread"] = hour_table["daily_anchor_max"] - hour_table["daily_anchor_min"]
    hour_table["daily_anchor_rank_pct"] = day_group.rank(method="average", pct=True)
    hour_table["negative_anchor_flag"] = hour_table["hourly_mean_eur_per_mwh"].lt(0.0).astype(int)

    def _high_price_flag(group: pd.Series) -> pd.Series:
        threshold = float(group.quantile(0.75))
        return group.ge(threshold).astype(int)

    hour_table["high_price_anchor_flag"] = day_group.transform(_high_price_flag).astype(int)

    model_table = working.merge(
        hour_table[
            [
                "hour_start_utc",
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
        ],
        on="hour_start_utc",
        how="left",
    )

    model_table["feature_mode"] = "diagnostic_oracle_anchor_features"
    model_table["anchor_mode"] = "diagnostic_oracle"
    model_table["realistic_anchor_available"] = False
    return model_table.sort_values(["hour_start_utc", "quarter_index"]).reset_index(drop=True), hour_table


def _build_feature_frame(model_table: pd.DataFrame) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    working = model_table.copy()
    working["hour_of_day_cat"] = pd.Categorical(working["local_hour_of_day"], categories=list(range(24)))
    working["quarter_cat"] = pd.Categorical(working["quarter_index"], categories=[1, 2, 3, 4])
    working["weekday_cat"] = pd.Categorical(working["weekday"], categories=list(range(7)))
    working["month_cat"] = pd.Categorical(working["month"], categories=list(range(1, 13)))
    working["season_cat"] = pd.Categorical(working["season"], categories=["winter", "spring", "summer", "autumn"])

    categorical = working[["hour_of_day_cat", "quarter_cat", "weekday_cat", "month_cat", "season_cat"]]
    encoded = pd.get_dummies(categorical, prefix=["hour", "quarter", "weekday", "month", "season"], dtype=float)

    numeric_columns = [
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
    numeric = working[numeric_columns].astype(float).reset_index(drop=True)
    X = pd.concat([numeric, encoded.reset_index(drop=True)], axis=1)
    feature_columns = list(X.columns)

    feature_summary_rows: list[dict[str, Any]] = []
    for column in feature_columns:
        feature_summary_rows.append(
            {
                "feature": column,
                "feature_group": "categorical_dummy" if column not in numeric_columns else "numeric_anchor_or_calendar",
                "non_null_rows": int(X[column].notna().sum()),
                "mean_value": float(X[column].mean()),
                "std_value": float(X[column].std(ddof=0)),
            }
        )
    feature_summary = pd.DataFrame(feature_summary_rows).sort_values(["feature_group", "feature"]).reset_index(drop=True)
    return X, feature_columns, feature_summary


def _check_split_nonoverlap(model_table: pd.DataFrame) -> dict[str, Any]:
    dates_by_split = {
        split: set(model_table.loc[model_table["dataset_split"].astype(str) == split, "delivery_local_date"].tolist())
        for split in ("train", "validation", "test")
    }
    overlaps = []
    split_names = list(dates_by_split.keys())
    for i, left in enumerate(split_names):
        for right in split_names[i + 1 :]:
            shared = sorted(dates_by_split[left].intersection(dates_by_split[right]))
            if shared:
                overlaps.append(f"{left}:{right}:{shared[:5]}")
    return {
        "check_name": "split_nonoverlap",
        "status": "pass" if not overlaps else "fail",
        "severity": "error" if overlaps else "info",
        "details": "No local-date overlap between train, validation, and test." if not overlaps else "; ".join(overlaps),
    }


def _fit_mean_shape(train_table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    with_weekend = (
        train_table.groupby(["local_hour_of_day", "quarter_index", "weekend_flag"], dropna=False)["delta_eur_per_mwh"]
        .mean()
        .reset_index()
        .rename(columns={"delta_eur_per_mwh": "delta_pred"})
    )
    by_hour = (
        train_table.groupby(["local_hour_of_day", "quarter_index"], dropna=False)["delta_eur_per_mwh"]
        .mean()
        .reset_index()
        .rename(columns={"delta_eur_per_mwh": "delta_pred"})
    )
    global_quarter = (
        train_table.groupby(["quarter_index"], dropna=False)["delta_eur_per_mwh"]
        .mean()
        .reset_index()
        .rename(columns={"delta_eur_per_mwh": "delta_pred"})
    )
    global_mean = float(train_table["delta_eur_per_mwh"].mean())
    return {
        "with_weekend": with_weekend,
        "by_hour": by_hour,
        "global_quarter": global_quarter,
        "global_mean": global_mean,
    }


def _predict_mean_shape(state: dict[str, Any], eval_table: pd.DataFrame) -> np.ndarray:
    # Merges below create a positional RangeIndex. Normalise the input index as
    # well so that fallback masks remain aligned after callers filter rows.
    working = eval_table[["local_hour_of_day", "quarter_index", "weekend_flag"]].reset_index(drop=True)
    merged = working.merge(state["with_weekend"], on=["local_hour_of_day", "quarter_index", "weekend_flag"], how="left")
    missing_mask = merged["delta_pred"].isna()
    if missing_mask.any():
        fallback = working.loc[missing_mask, ["local_hour_of_day", "quarter_index"]].merge(
            state["by_hour"],
            on=["local_hour_of_day", "quarter_index"],
            how="left",
        )
        merged.loc[missing_mask, "delta_pred"] = fallback["delta_pred"].to_numpy()
    missing_mask = merged["delta_pred"].isna()
    if missing_mask.any():
        fallback = working.loc[missing_mask, ["quarter_index"]].merge(
            state["global_quarter"],
            on=["quarter_index"],
            how="left",
        )
        merged.loc[missing_mask, "delta_pred"] = fallback["delta_pred"].to_numpy()
    merged["delta_pred"] = merged["delta_pred"].fillna(state["global_mean"])
    return merged["delta_pred"].to_numpy(dtype=float)


def _fit_lear(train_X: pd.DataFrame, train_y: pd.Series, *, alpha: float) -> Pipeline:
    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("lasso", Lasso(alpha=float(alpha), max_iter=5000)),
        ]
    )
    model.fit(train_X, train_y)
    return model


def _fit_xgboost(train_X: pd.DataFrame, train_y: pd.Series, params: dict[str, Any]) -> XGBRegressor:
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=int(params["n_estimators"]),
        max_depth=int(params["max_depth"]),
        learning_rate=float(params["learning_rate"]),
        subsample=float(params.get("subsample", 0.9)),
        colsample_bytree=float(params.get("colsample_bytree", 0.9)),
        reg_alpha=float(params.get("reg_alpha", 0.0)),
        reg_lambda=float(params.get("reg_lambda", 1.0)),
        random_state=42,
        n_jobs=1,
    )
    model.fit(train_X, train_y)
    return model


def _apply_zero_mean_correction(prediction_frame: pd.DataFrame) -> pd.DataFrame:
    working = prediction_frame.copy()
    hour_group_columns = ["hour_start_utc"]
    if "forecast_origin_utc" in working.columns:
        hour_group_columns = ["forecast_origin_utc", "hour_start_utc"]
    hourly_mean = working.groupby(hour_group_columns)["delta_pred_raw"].transform("mean")
    working["delta_pred_adjusted"] = working["delta_pred_raw"] - hourly_mean
    working["predicted_delta_zero_mean_abs"] = (
        working.groupby(hour_group_columns)["delta_pred_adjusted"].transform("mean").abs()
    )
    working["predicted_price_eur_per_mwh"] = working["hourly_mean_eur_per_mwh"] + working["delta_pred_adjusted"]
    working["delta_error_eur_per_mwh"] = working["delta_pred_adjusted"] - working["delta_eur_per_mwh"]
    working["price_error_eur_per_mwh"] = working["predicted_price_eur_per_mwh"] - working["price_eur_per_mwh"]
    working["abs_delta_error_eur_per_mwh"] = working["delta_error_eur_per_mwh"].abs()
    working["abs_price_error_eur_per_mwh"] = working["price_error_eur_per_mwh"].abs()
    return working


def _build_prediction_frame(
    eval_table: pd.DataFrame,
    *,
    model_name: str,
    model_family: str,
    dataset_split: str,
    delta_pred_raw: np.ndarray,
    feature_mode: str,
    anchor_mode: str = "diagnostic_oracle",
) -> pd.DataFrame:
    base_columns = [
        "timestamp_utc",
        "timestamp_local",
        "delivery_local_date",
        "hour_start_utc",
        "hour_start_local",
        "hour_local_date",
        "dataset_split",
        "local_hour_of_day",
        "quarter_index",
        "weekday",
        "weekend_flag",
        "month",
        "season",
        "price_eur_per_mwh",
        "hourly_mean_eur_per_mwh",
        "delta_eur_per_mwh",
        "daily_anchor_spread",
        "ramp_in",
        "ramp_out",
        "negative_anchor_flag",
        "high_price_anchor_flag",
    ]
    optional_columns = [
        "forecast_origin_utc",
        "forecast_origin_local",
        "lead_day",
        "lead_day_label",
        "horizon_index",
        "target_timestamp_utc",
        "target_timestamp_local",
    ]
    working = eval_table[[column for column in base_columns + optional_columns if column in eval_table.columns]].copy()
    if "target_timestamp_utc" not in working.columns:
        working["target_timestamp_utc"] = working["timestamp_utc"]
    if "target_timestamp_local" not in working.columns:
        working["target_timestamp_local"] = working["timestamp_local"]
    working["model"] = model_name
    working["model_family"] = model_family
    working["dataset_split"] = dataset_split
    working["anchor_mode"] = anchor_mode
    working["feature_mode"] = feature_mode
    working["delta_pred_raw"] = np.asarray(delta_pred_raw, dtype=float)
    working["oracle_anchor_price_eur_per_mwh"] = working["hourly_mean_eur_per_mwh"]
    working = _apply_zero_mean_correction(working)
    return working


def _safe_quantile(series: pd.Series, q: float) -> float:
    if series.empty:
        return float("nan")
    return float(series.quantile(q))


def _scalar_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    error = predicted.astype(float) - actual.astype(float)
    abs_error = error.abs()
    return {
        "mae": float(abs_error.mean()),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
        "bias": float(error.mean()),
        "median_ae": float(abs_error.median()),
        "p90_ae": _safe_quantile(abs_error, 0.90),
        "p95_ae": _safe_quantile(abs_error, 0.95),
    }


def _shape_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(["dataset_split", "model"], dropna=False):
        split_name, model_name = keys
        metrics = _scalar_metrics(group["delta_eur_per_mwh"], group["delta_pred_adjusted"])
        anchor_mode = str(group["anchor_mode"].iloc[0]) if "anchor_mode" in group.columns else "diagnostic_oracle"
        rows.append(
            {
                "dataset_split": str(split_name),
                "model": str(model_name),
                "anchor_mode": anchor_mode,
                "delta_mae": metrics["mae"],
                "delta_rmse": metrics["rmse"],
                "delta_bias": metrics["bias"],
                "delta_p90_ae": metrics["p90_ae"],
                "delta_p95_ae": metrics["p95_ae"],
                "n_quarterhours": int(group.shape[0]),
            }
        )
    return pd.DataFrame(rows).sort_values(["dataset_split", "model"]).reset_index(drop=True)


def _hour_level_decision_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = ["dataset_split", "model", "hour_start_utc"]
    if "forecast_origin_utc" in predictions.columns:
        group_columns = ["dataset_split", "model", "forecast_origin_utc", "hour_start_utc"]
    for keys, group in predictions.groupby(group_columns, dropna=False):
        if len(group_columns) == 4:
            split_name, model_name, forecast_origin_utc, hour_start_utc = keys
        else:
            split_name, model_name, hour_start_utc = keys
            forecast_origin_utc = None
        actual_price = group["price_eur_per_mwh"].astype(float)
        predicted_price = group["predicted_price_eur_per_mwh"].astype(float)
        actual_quarters = group["quarter_index"].astype(int)
        predicted_cheapest = set(actual_quarters[predicted_price.eq(predicted_price.min())].tolist())
        actual_cheapest = set(actual_quarters[actual_price.eq(actual_price.min())].tolist())
        predicted_expensive = set(actual_quarters[predicted_price.eq(predicted_price.max())].tolist())
        actual_expensive = set(actual_quarters[actual_price.eq(actual_price.max())].tolist())

        actual_two = set(group.sort_values(["price_eur_per_mwh", "quarter_index"]).head(2)["quarter_index"].astype(int).tolist())
        predicted_two = set(group.sort_values(["predicted_price_eur_per_mwh", "quarter_index"]).head(2)["quarter_index"].astype(int).tolist())
        if actual_price.nunique(dropna=True) < 2 or predicted_price.nunique(dropna=True) < 2:
            within_hour_rank_corr = np.nan
        else:
            within_hour_rank_corr = float(actual_price.corr(predicted_price, method="spearman"))

        rows.append(
            {
                "dataset_split": str(split_name),
                "model": str(model_name),
                "forecast_origin_utc": pd.Timestamp(forecast_origin_utc).isoformat() if forecast_origin_utc is not None and pd.notna(forecast_origin_utc) else None,
                "hour_start_utc": pd.Timestamp(hour_start_utc).isoformat(),
                "cheapest_quarter_hit": float(bool(actual_cheapest.intersection(predicted_cheapest))),
                "most_expensive_quarter_hit": float(bool(actual_expensive.intersection(predicted_expensive))),
                "cheapest_two_overlap_ratio": float(len(actual_two.intersection(predicted_two)) / 2.0),
                "within_hour_rank_corr": within_hour_rank_corr,
                "daily_anchor_spread": float(group["daily_anchor_spread"].iloc[0]),
                "hourly_ramp_abs": float(max(abs(float(group["ramp_in"].iloc[0])), abs(float(group["ramp_out"].iloc[0])))),
                "negative_anchor_flag": int(group["negative_anchor_flag"].iloc[0]),
                "high_price_anchor_flag": int(group["high_price_anchor_flag"].iloc[0]),
            }
        )
    sort_columns = ["dataset_split", "model", "hour_start_utc"]
    if rows and "forecast_origin_utc" in pd.DataFrame(rows).columns:
        sort_columns = ["dataset_split", "model", "forecast_origin_utc", "hour_start_utc"]
    return pd.DataFrame(rows).sort_values(sort_columns).reset_index(drop=True)


def _price_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    decision = _hour_level_decision_metrics(predictions)
    rows: list[dict[str, Any]] = []
    for keys, group in predictions.groupby(["dataset_split", "model"], dropna=False):
        split_name, model_name = keys
        metrics = _scalar_metrics(group["price_eur_per_mwh"], group["predicted_price_eur_per_mwh"])
        anchor_mode = str(group["anchor_mode"].iloc[0]) if "anchor_mode" in group.columns else "diagnostic_oracle"
        decision_slice = decision[
            (decision["dataset_split"].astype(str) == str(split_name))
            & (decision["model"].astype(str) == str(model_name))
        ].copy()
        rows.append(
            {
                "dataset_split": str(split_name),
                "model": str(model_name),
                "anchor_mode": anchor_mode,
                "mae": metrics["mae"],
                "rmse": metrics["rmse"],
                "bias": metrics["bias"],
                "median_ae": metrics["median_ae"],
                "p90_ae": metrics["p90_ae"],
                "p95_ae": metrics["p95_ae"],
                "cheapest_quarter_hit_rate": float(decision_slice["cheapest_quarter_hit"].mean()),
                "most_expensive_quarter_hit_rate": float(decision_slice["most_expensive_quarter_hit"].mean()),
                "cheapest_two_overlap_ratio": float(decision_slice["cheapest_two_overlap_ratio"].mean()),
                "within_hour_rank_corr": float(decision_slice["within_hour_rank_corr"].mean()),
                "n_quarterhours": int(group.shape[0]),
                "n_hours": int(decision_slice.shape[0]),
            }
        )
    frame = pd.DataFrame(rows).sort_values(["dataset_split", "model"]).reset_index(drop=True)
    frame["rmae_vs_flat_repeat"] = np.nan
    for split_name in frame["dataset_split"].astype(str).unique():
        mask = frame["dataset_split"].astype(str) == split_name
        baseline = frame.loc[mask & frame["model"].astype(str).eq("flat_repeat"), "mae"]
        if baseline.empty or float(baseline.iloc[0]) == 0.0:
            continue
        denominator = float(baseline.iloc[0])
        frame.loc[mask, "rmae_vs_flat_repeat"] = frame.loc[mask, "mae"] / denominator
    return frame


def _train_regime_thresholds(train_table: pd.DataFrame) -> dict[str, float]:
    hourly_ramp_abs = np.maximum(train_table["abs_ramp_in"].astype(float), train_table["abs_ramp_out"].astype(float))
    nonnegative_anchor = train_table.loc[train_table["hourly_mean_eur_per_mwh"].astype(float) >= 0.0, "hourly_mean_eur_per_mwh"].astype(float)
    return {
        "daily_spread_low": _safe_quantile(train_table["daily_anchor_spread"].astype(float), 1 / 3),
        "daily_spread_high": _safe_quantile(train_table["daily_anchor_spread"].astype(float), 2 / 3),
        "hourly_ramp_low": _safe_quantile(hourly_ramp_abs, 1 / 3),
        "hourly_ramp_high": _safe_quantile(hourly_ramp_abs, 2 / 3),
        "high_price_threshold": _safe_quantile(nonnegative_anchor, 0.75) if not nonnegative_anchor.empty else float("nan"),
    }


def _assign_regimes(predictions: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    working = predictions.copy()
    working["hourly_ramp_abs"] = np.maximum(working["ramp_in"].astype(float).abs(), working["ramp_out"].astype(float).abs())

    def _spread_bucket(value: float) -> str:
        if value <= thresholds["daily_spread_low"]:
            return "low"
        if value <= thresholds["daily_spread_high"]:
            return "medium"
        return "high"

    def _ramp_bucket(value: float) -> str:
        if value <= thresholds["hourly_ramp_low"]:
            return "low"
        if value <= thresholds["hourly_ramp_high"]:
            return "medium"
        return "high"

    def _price_bucket(value: float) -> str:
        if value < 0.0:
            return "negative"
        if np.isnan(thresholds["high_price_threshold"]):
            return "normal"
        return "high" if value >= thresholds["high_price_threshold"] else "normal"

    working["daily_spread_regime"] = working["daily_anchor_spread"].astype(float).map(_spread_bucket)
    working["hourly_ramp_regime"] = working["hourly_ramp_abs"].astype(float).map(_ramp_bucket)
    working["hourly_price_regime"] = working["hourly_mean_eur_per_mwh"].astype(float).map(_price_bucket)
    return working


def _performance_by_condition(predictions: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    working = _assign_regimes(predictions, thresholds)
    test_only = working[working["dataset_split"].astype(str) == "test"].copy()
    if test_only.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    condition_specs = [
        ("hour_of_day", "local_hour_of_day"),
        ("quarter_index", "quarter_index"),
        ("weekday_weekend", "weekend_flag"),
        ("month", "month"),
        ("daily_spread_regime", "daily_spread_regime"),
        ("hourly_ramp_regime", "hourly_ramp_regime"),
        ("hourly_price_regime", "hourly_price_regime"),
    ]
    flat_lookup: dict[tuple[str, str], float] = {}
    for group_name, column_name in condition_specs:
        flat_group = test_only[test_only["model"].astype(str) == "flat_repeat"].copy()
        for value, group in flat_group.groupby(column_name, dropna=False):
            flat_lookup[(group_name, str(value))] = float(group["abs_price_error_eur_per_mwh"].mean())

        for (model_name, value), group in test_only.groupby(["model", column_name], dropna=False):
            mae = float(group["abs_price_error_eur_per_mwh"].mean())
            denominator = flat_lookup.get((group_name, str(value)))
            rows.append(
                {
                    "dataset_split": "test",
                    "model": str(model_name),
                    "condition_group": group_name,
                    "condition_value": str(value),
                    "count": int(group.shape[0]),
                    "mae": mae,
                    "rmae_vs_flat_repeat": float(mae / denominator) if denominator not in (None, 0.0) else np.nan,
                }
            )
    return pd.DataFrame(rows).sort_values(["condition_group", "condition_value", "model"]).reset_index(drop=True)


def _mae_by_hour(predictions: pd.DataFrame) -> pd.DataFrame:
    working = predictions[predictions["dataset_split"].astype(str) == "test"].copy()
    if working.empty:
        return pd.DataFrame()
    return (
        working.groupby(["model", "local_hour_of_day"], dropna=False)["abs_price_error_eur_per_mwh"]
        .mean()
        .reset_index()
        .rename(columns={"abs_price_error_eur_per_mwh": "mae"})
        .sort_values(["model", "local_hour_of_day"])
        .reset_index(drop=True)
    )


def _example_days(hour_table: pd.DataFrame) -> pd.DataFrame:
    daily = (
        hour_table.groupby("hour_local_date", dropna=False)
        .agg(
            daily_anchor_spread=("daily_anchor_spread", "first"),
            min_anchor_price=("hourly_mean_eur_per_mwh", "min"),
            max_abs_ramp=("abs_ramp_out", "max"),
        )
        .reset_index()
    )
    rows: list[dict[str, Any]] = []
    if not daily.empty:
        median_spread = float(daily["daily_anchor_spread"].median())
        normal = daily.iloc[(daily["daily_anchor_spread"] - median_spread).abs().argsort()[:1]]
        volatile = daily.nlargest(1, "daily_anchor_spread")
        rows.append({"example_type": "normal_day", "hour_local_date": str(normal.iloc[0]["hour_local_date"])})
        rows.append({"example_type": "volatile_day", "hour_local_date": str(volatile.iloc[0]["hour_local_date"])})
        negative_days = daily[daily["min_anchor_price"].lt(0.0)].sort_values(["min_anchor_price", "hour_local_date"])
        if not negative_days.empty:
            rows.append({"example_type": "negative_price_day", "hour_local_date": str(negative_days.iloc[0]["hour_local_date"])})
        high_ramp = daily.nlargest(1, "max_abs_ramp")
        rows.append({"example_type": "high_ramp_day", "hour_local_date": str(high_ramp.iloc[0]["hour_local_date"])})
    return pd.DataFrame(rows).drop_duplicates(subset=["example_type"]).reset_index(drop=True)


def _realistic_anchor_availability(
    *,
    config: QuarterHourDAExtensionConfig,
    phase03_candidate_frame: pd.DataFrame,
    selected_anchor_models: pd.DataFrame,
    model_table: pd.DataFrame,
) -> pd.DataFrame:
    hourly_config = HourlyDAPipelineConfig(output_root=config.hourly_da_output_root)
    selected_keys = set(selected_anchor_models["candidate_key"].astype(str).tolist())
    candidate_frame = phase03_candidate_frame[phase03_candidate_frame["candidate_key"].astype(str).isin(selected_keys)].copy()
    predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=hourly_config)

    split_windows = (
        model_table.groupby("dataset_split", dropna=False)
        .agg(
            local_start_date=("delivery_local_date", "min"),
            local_end_date=("delivery_local_date", "max"),
        )
        .reset_index()
    )
    rows: list[dict[str, Any]] = []
    for row in selected_anchor_models.to_dict(orient="records"):
        candidate_key = str(row["candidate_key"])
        candidate_preds = predictions[predictions["candidate_key"].astype(str) == candidate_key].copy()
        if candidate_preds.empty:
            rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": str(row["candidate_label"]),
                    "role": str(row["role"]),
                    "min_target_timestamp_utc": None,
                    "max_target_timestamp_utc": None,
                    "covers_observed_validation_window": False,
                    "covers_observed_test_window": False,
                    "status": "unavailable",
                    "notes": "No saved hourly predictions were available for this selected candidate.",
                }
            )
            continue
        candidate_preds["target_timestamp_utc"] = pd.to_datetime(candidate_preds["target_timestamp_utc"], utc=True, errors="coerce")
        candidate_preds["target_local_date"] = candidate_preds["target_timestamp_utc"].dt.tz_convert(config.business_timezone).dt.date
        coverage = {}
        for split_name in ("validation", "test"):
            window = split_windows[split_windows["dataset_split"].astype(str) == split_name]
            if window.empty:
                coverage[split_name] = False
                continue
            start_date = window.iloc[0]["local_start_date"]
            end_date = window.iloc[0]["local_end_date"]
            local_dates = set(
                candidate_preds.loc[
                    candidate_preds["target_local_date"].between(start_date, end_date),
                    "target_local_date",
                ].tolist()
            )
            required_dates = set(pd.date_range(start=start_date, end=end_date, freq="D").date)
            coverage[split_name] = required_dates.issubset(local_dates)
        rows.append(
            {
                "candidate_key": candidate_key,
                "candidate_label": str(row["candidate_label"]),
                "role": str(row["role"]),
                "min_target_timestamp_utc": candidate_preds["target_timestamp_utc"].min().isoformat(),
                "max_target_timestamp_utc": candidate_preds["target_timestamp_utc"].max().isoformat(),
                "covers_observed_validation_window": bool(coverage["validation"]),
                "covers_observed_test_window": bool(coverage["test"]),
                "status": "available" if coverage["validation"] and coverage["test"] else "partial_or_unavailable",
                "notes": (
                    "Saved hourly benchmark predictions do not extend into the observed 15-minute period, so realistic Track A "
                    "evaluation remains unavailable in Phase 4."
                    if not (coverage["validation"] and coverage["test"])
                    else "Saved hourly predictions cover the observed 15-minute validation and test windows."
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_checks(
    *,
    model_table: pd.DataFrame,
    predictions: pd.DataFrame,
    realistic_anchor_status: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        {
            "check_name": "shape_target_zero_mean",
            "status": "pass" if float(model_table["delta_zero_mean_check_abs"].max()) < 1e-9 else "fail",
            "severity": "error" if float(model_table["delta_zero_mean_check_abs"].max()) >= 1e-9 else "info",
            "details": f"max_abs_hourly_delta_mean={float(model_table['delta_zero_mean_check_abs'].max()):.6g}",
        },
        _check_split_nonoverlap(model_table),
        {
            "check_name": "duplicate_timestamp_utc_in_modeling_table",
            "status": "pass" if int(model_table["timestamp_utc"].duplicated().sum()) == 0 else "fail",
            "severity": "error" if int(model_table["timestamp_utc"].duplicated().sum()) > 0 else "info",
            "details": f"duplicate_rows={int(model_table['timestamp_utc'].duplicated().sum())}",
        },
    ]
    for (split_name, model_name), group in predictions.groupby(["dataset_split", "model"], dropna=False):
        max_abs = float(group["predicted_delta_zero_mean_abs"].max())
        rows.append(
            {
                "check_name": f"predicted_zero_mean_after_correction::{split_name}::{model_name}",
                "status": "pass" if max_abs < 1e-9 else "fail",
                "severity": "error" if max_abs >= 1e-9 else "info",
                "details": f"max_abs_hourly_delta_mean={max_abs:.6g}",
            }
        )
    for row in realistic_anchor_status.to_dict(orient="records"):
        available = bool(row["covers_observed_validation_window"]) and bool(row["covers_observed_test_window"])
        rows.append(
            {
                "check_name": f"realistic_anchor_availability::{row['candidate_key']}",
                "status": "pass" if available else "warning",
                "severity": "warning" if not available else "info",
                "details": str(row["notes"]),
            }
        )
    checks = pd.DataFrame(rows)
    failures = checks[checks["status"].astype(str) == "fail"]
    if not failures.empty:
        raise ValueError(f"Phase 4 validation checks failed: {failures['check_name'].tolist()}")
    return checks


def _model_configuration_summary(
    *,
    tuning_results: pd.DataFrame,
    selected_tuning: dict[str, dict[str, Any]],
    model_table: pd.DataFrame,
) -> pd.DataFrame:
    split_summary = (
        model_table.groupby("dataset_split", dropna=False)["delivery_local_date"]
        .agg(["min", "max"])
        .rename(columns={"min": "start_date", "max": "end_date"})
        .reset_index()
    )
    split_lookup = {
        str(row["dataset_split"]): (str(row["start_date"]), str(row["end_date"]))
        for row in split_summary.to_dict(orient="records")
    }
    rows = []
    for model_name in ALL_MODEL_ORDER:
        if model_name == "flat_repeat":
            key_hyperparameters = "{}"
            model_type = "baseline_flat_repeat"
        elif model_name == "mean_shape":
            key_hyperparameters = json.dumps({"grouping": ["local_hour_of_day", "quarter_index", "weekend_flag"], "fallbacks": ["hour_quarter", "quarter_global"]})
            model_type = "baseline_mean_shape"
        else:
            key_hyperparameters = json.dumps(selected_tuning.get(model_name, {}), sort_keys=True)
            model_type = "learned_shape_model"
        rows.append(
            {
                "model": model_name,
                "model_type": model_type,
                "feature_set": "minimal_oracle_anchor_features_v1",
                "training_period": f"{split_lookup['train'][0]} to {split_lookup['train'][1]}",
                "validation_period": f"{split_lookup['validation'][0]} to {split_lookup['validation'][1]}",
                "test_period": f"{split_lookup['test'][0]} to {split_lookup['test'][1]}",
                "key_hyperparameters": key_hyperparameters,
                "retraining_policy": "train_only_for_validation_then_refit_train_plus_validation_for_test",
                "zero_mean_correction_applied": True,
                "diagnostic_oracle_anchor_used": True,
                "realistic_hourly_anchor_used": False,
            }
        )
    return pd.DataFrame(rows)


def run_phase04_empirical_validation(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = config.phase04_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    phase02_run, raw_shape_target = _load_shape_target(config)
    phase03_run, selected_anchor_models, phase03_candidate_frame = _load_phase03_context(config)

    shape_target = _prepare_shape_target(raw_shape_target, timezone=config.business_timezone)
    model_table, hour_table = _build_modeling_table(shape_target)
    X, feature_columns, feature_summary = _build_feature_frame(model_table)

    model_table.to_csv(run_dir / "modeling_table.csv", index=False)
    feature_summary.to_csv(run_dir / "feature_column_summary.csv", index=False)
    selected_anchor_models.to_csv(run_dir / "selected_hourly_anchor_models.csv", index=False)

    train_mask = model_table["dataset_split"].astype(str) == "train"
    validation_mask = model_table["dataset_split"].astype(str) == "validation"
    test_mask = model_table["dataset_split"].astype(str) == "test"
    trainval_mask = train_mask | validation_mask

    train_table = model_table.loc[train_mask].reset_index(drop=True)
    validation_table = model_table.loc[validation_mask].reset_index(drop=True)
    test_table = model_table.loc[test_mask].reset_index(drop=True)

    X_train = X.loc[train_mask].reset_index(drop=True)
    X_validation = X.loc[validation_mask].reset_index(drop=True)
    X_test = X.loc[test_mask].reset_index(drop=True)
    X_trainval = X.loc[trainval_mask].reset_index(drop=True)

    y_train = train_table["delta_eur_per_mwh"].reset_index(drop=True)
    y_trainval = model_table.loc[trainval_mask, "delta_eur_per_mwh"].reset_index(drop=True)

    predictions_frames: list[pd.DataFrame] = []
    tuning_rows: list[dict[str, Any]] = []
    selected_tuning: dict[str, dict[str, Any]] = {}

    flat_validation = _build_prediction_frame(
        validation_table,
        model_name="flat_repeat",
        model_family="baseline",
        dataset_split="validation",
        delta_pred_raw=np.zeros(validation_table.shape[0], dtype=float),
        feature_mode="none_flat_repeat",
    )
    flat_test = _build_prediction_frame(
        test_table,
        model_name="flat_repeat",
        model_family="baseline",
        dataset_split="test",
        delta_pred_raw=np.zeros(test_table.shape[0], dtype=float),
        feature_mode="none_flat_repeat",
    )
    predictions_frames.extend([flat_validation, flat_test])

    mean_shape_state_validation = _fit_mean_shape(train_table)
    mean_shape_validation = _build_prediction_frame(
        validation_table,
        model_name="mean_shape",
        model_family="baseline",
        dataset_split="validation",
        delta_pred_raw=_predict_mean_shape(mean_shape_state_validation, validation_table),
        feature_mode="calendar_shape_mean_with_weekend_fallback",
    )
    mean_shape_state_test = _fit_mean_shape(model_table.loc[trainval_mask].reset_index(drop=True))
    mean_shape_test = _build_prediction_frame(
        test_table,
        model_name="mean_shape",
        model_family="baseline",
        dataset_split="test",
        delta_pred_raw=_predict_mean_shape(mean_shape_state_test, test_table),
        feature_mode="calendar_shape_mean_with_weekend_fallback",
    )
    predictions_frames.extend([mean_shape_validation, mean_shape_test])

    lear_grid = [0.001, 0.005, 0.01, 0.05, 0.1]
    best_lear_mae = np.inf
    best_lear_model: Pipeline | None = None
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
            feature_mode="minimal_oracle_anchor_features_v1",
        )
        validation_mae = float(validation_frame["abs_price_error_eur_per_mwh"].mean())
        tuning_rows.append(
            {
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
            best_lear_model = learner
            best_lear_alpha = alpha
            best_lear_validation_frame = validation_frame
    if best_lear_model is None or best_lear_validation_frame is None or best_lear_alpha is None:
        raise RuntimeError("LEAR tuning failed to produce a validation model.")
    selected_tuning["lear_shape"] = {"alpha": best_lear_alpha}
    predictions_frames.append(best_lear_validation_frame)

    final_lear_model = _fit_lear(X_trainval, y_trainval, alpha=best_lear_alpha)
    lear_test = _build_prediction_frame(
        test_table,
        model_name="lear_shape",
        model_family="lear",
        dataset_split="test",
        delta_pred_raw=final_lear_model.predict(X_test),
        feature_mode="minimal_oracle_anchor_features_v1",
    )
    predictions_frames.append(lear_test)

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
            feature_mode="minimal_oracle_anchor_features_v1",
        )
        validation_mae = float(validation_frame["abs_price_error_eur_per_mwh"].mean())
        tuning_rows.append(
            {
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
        raise RuntimeError("XGBoost tuning failed to produce a validation model.")
    selected_tuning["xgboost_shape"] = best_xgb_params
    predictions_frames.append(best_xgb_validation_frame)

    final_xgb_model = _fit_xgboost(X_trainval, y_trainval, best_xgb_params)
    xgb_test = _build_prediction_frame(
        test_table,
        model_name="xgboost_shape",
        model_family="xgboost",
        dataset_split="test",
        delta_pred_raw=final_xgb_model.predict(X_test),
        feature_mode="minimal_oracle_anchor_features_v1",
    )
    predictions_frames.append(xgb_test)

    predictions_long = pd.concat(predictions_frames, ignore_index=True)
    predictions_long["model"] = pd.Categorical(predictions_long["model"], categories=list(ALL_MODEL_ORDER), ordered=True)
    predictions_long = predictions_long.sort_values(["dataset_split", "model", "hour_start_utc", "quarter_index"]).reset_index(drop=True)
    predictions_long.to_csv(run_dir / "predictions_long.csv", index=False)

    tuning_results = pd.DataFrame(tuning_rows).sort_values(["model", "validation_price_mae", "candidate_id"]).reset_index(drop=True)
    tuning_results.to_csv(run_dir / "tuning_results.csv", index=False)

    shape_metrics = _shape_metrics(predictions_long)
    price_metrics = _price_metrics(predictions_long)
    shape_metrics.to_csv(run_dir / "shape_only_metrics.csv", index=False)
    price_metrics.to_csv(run_dir / "reconstructed_price_metrics.csv", index=False)

    thresholds = _train_regime_thresholds(train_table)
    performance_by_condition = _performance_by_condition(predictions_long, thresholds)
    performance_by_condition.to_csv(run_dir / "performance_by_condition.csv", index=False)

    mae_by_hour = _mae_by_hour(predictions_long)
    mae_by_hour.to_csv(run_dir / "mae_by_hour.csv", index=False)

    realistic_anchor_status = _realistic_anchor_availability(
        config=config,
        phase03_candidate_frame=phase03_candidate_frame,
        selected_anchor_models=selected_anchor_models,
        model_table=model_table,
    )
    realistic_anchor_status.to_csv(run_dir / "realistic_anchor_availability.csv", index=False)

    checks = _build_checks(
        model_table=model_table,
        predictions=predictions_long,
        realistic_anchor_status=realistic_anchor_status,
    )
    checks.to_csv(run_dir / "validation_checks.csv", index=False)

    model_config = _model_configuration_summary(
        tuning_results=tuning_results,
        selected_tuning=selected_tuning,
        model_table=model_table,
    )
    model_config.to_csv(run_dir / "model_configuration_summary.csv", index=False)

    example_days = _example_days(hour_table)
    example_days.to_csv(run_dir / "example_days.csv", index=False)

    lasso_step = final_lear_model.named_steps["lasso"]
    lear_coefficients = pd.DataFrame(
        {
            "feature": feature_columns,
            "coefficient": np.asarray(lasso_step.coef_, dtype=float),
        }
    )
    lear_coefficients["abs_coefficient"] = lear_coefficients["coefficient"].abs()
    lear_coefficients = lear_coefficients.sort_values(["abs_coefficient", "feature"], ascending=[False, True]).reset_index(drop=True)
    lear_coefficients.to_csv(run_dir / "lear_coefficients.csv", index=False)

    gain_scores = final_xgb_model.get_booster().get_score(importance_type="gain")
    weight_scores = final_xgb_model.get_booster().get_score(importance_type="weight")
    xgb_importance_rows = [
        {
            "feature": feature,
            "gain": float(gain_scores.get(feature, 0.0)),
            "split_count": float(weight_scores.get(feature, 0.0)),
        }
        for feature in feature_columns
    ]
    xgb_importance = pd.DataFrame(xgb_importance_rows).sort_values(["gain", "split_count", "feature"], ascending=[False, False, True]).reset_index(drop=True)
    xgb_importance.to_csv(run_dir / "xgboost_feature_importance.csv", index=False)

    validation_price = price_metrics[price_metrics["dataset_split"].astype(str) == "validation"].copy()
    test_price = price_metrics[price_metrics["dataset_split"].astype(str) == "test"].copy()
    recommended_validation_row = validation_price.sort_values(["mae", "model"]).iloc[0].to_dict() if not validation_price.empty else {}
    best_test_row = test_price.sort_values(["mae", "model"]).iloc[0].to_dict() if not test_price.empty else {}

    recommended_model_summary = pd.DataFrame(
        [
            {
                "selection_basis": "validation_reconstructed_price_mae",
                "recommended_model": str(recommended_validation_row.get("model", "")),
                "recommended_validation_mae": recommended_validation_row.get("mae"),
                "best_test_model": str(best_test_row.get("model", "")),
                "best_test_mae": best_test_row.get("mae"),
                "realistic_track_a_available": bool(
                    realistic_anchor_status["covers_observed_validation_window"].all()
                    and realistic_anchor_status["covers_observed_test_window"].all()
                )
                if not realistic_anchor_status.empty
                else False,
                "notes": (
                    "Recommendation is based on diagnostic/oracle-anchor validation only. Realistic end-to-end Track A "
                    "remains unavailable in Phase 4 because matching hourly forecast anchors were not yet generated "
                    "for the observed 15-minute period."
                ),
            }
        ]
    )
    recommended_model_summary.to_csv(run_dir / "recommended_model_summary.csv", index=False)

    run_summary = {
        "run_id": run_id,
        "phase": "phase04_empirical_shape_model_validation",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "phase02_run_dir": str(phase02_run),
        "phase03_run_dir": str(phase03_run),
        "shape_target_rows": int(model_table.shape[0]),
        "feature_count": int(len(feature_columns)),
        "feature_mode": "minimal_oracle_anchor_features_v1",
        "anchor_mode_evaluated": "diagnostic_oracle",
        "realistic_track_a_available": bool(
            realistic_anchor_status["covers_observed_validation_window"].all()
            and realistic_anchor_status["covers_observed_test_window"].all()
        )
        if not realistic_anchor_status.empty
        else False,
        "selected_hourly_anchor_candidates": selected_anchor_models.to_dict(orient="records"),
        "selected_shape_model_by_validation": recommended_model_summary.iloc[0].to_dict(),
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
