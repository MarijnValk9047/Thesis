from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    XGBRegressor = None

from sklearn.ensemble import HistGradientBoostingRegressor


REPO_ROOT = Path(__file__).resolve().parents[4]
INPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_daily_direction.csv"
OUTPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_daily_direction_long.csv"

TARGET_COL = "target_average_procurement_price"
PREDICTOR_COLS = [
    "avg_price_lag_1d_same_direction",
    "avg_price_lag_2d_same_direction",
    "avg_price_lag_7d_same_direction",
    "avg_price_lag_14d_same_direction",
    "avg_price_roll_mean_7d_same_direction",
    "avg_price_roll_median_7d_same_direction",
    "avg_price_roll_std_7d_same_direction",
    "avg_price_roll_mean_28d_same_direction",
    "avg_price_roll_median_28d_same_direction",
    "avg_price_roll_std_28d_same_direction",
    "avg_price_roll_q25_28d_same_direction",
    "avg_price_roll_q75_28d_same_direction",
    "up_down_spread_lag_1d",
    "up_down_spread_lag_7d",
    "up_down_spread_roll_mean_7d",
    "up_down_spread_roll_std_28d",
    "day_of_week",
    "is_weekend",
    "month",
    "quarter",
    "day_of_year",
    "direction_code",
]
OUTPUT_COLS = [
    "forecast_origin_utc",
    "forecast_origin_local",
    "known_at_cutoff_utc",
    "delivery_start_utc",
    "delivery_end_utc",
    "delivery_date_local",
    "delivery_block_id",
    "direction",
    "model_name",
    "target_name",
    "y_true",
    "point_forecast",
    "average_procurement_price_unit",
    "dataset_split",
    "granularity",
    "market_design_regime",
    "source_data_version",
    "quality_flags",
    "feature_source",
    "forecast_quality_flags",
    "fit_runtime_seconds",
    "predict_runtime_seconds",
    "total_runtime_seconds",
    "n_predictors",
    "model_config_summary",
    "selected_model_type",
    "selected_hyperparameters",
]

if XGBOOST_AVAILABLE:
    MODEL_NAME = "xgboost_endogenous_daily_v1"
    CANDIDATES = [
        {
            "label": "config_a",
            "n_estimators": 100,
            "max_depth": 2,
            "learning_rate": 0.05,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "reg_lambda": 1.0,
            "objective": "reg:squarederror",
            "random_state": 42,
        },
        {
            "label": "config_b",
            "n_estimators": 200,
            "max_depth": 2,
            "learning_rate": 0.03,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "reg_lambda": 2.0,
            "objective": "reg:squarederror",
            "random_state": 42,
        },
        {
            "label": "config_c",
            "n_estimators": 100,
            "max_depth": 3,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_lambda": 2.0,
            "objective": "reg:squarederror",
            "random_state": 42,
        },
    ]
else:
    MODEL_NAME = "hgb_endogenous_daily_v1"
    CANDIDATES = [
        {"label": "config_a", "max_iter": 100, "max_leaf_nodes": 15, "learning_rate": 0.05, "l2_regularization": 0.0, "random_state": 42},
        {"label": "config_b", "max_iter": 200, "max_leaf_nodes": 15, "learning_rate": 0.03, "l2_regularization": 0.5, "random_state": 42},
        {"label": "config_c", "max_iter": 150, "max_leaf_nodes": 31, "learning_rate": 0.05, "l2_regularization": 1.0, "random_state": 42},
    ]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLS)
        writer.writeheader()
        writer.writerows(rows)


def monotonic_seconds() -> float:
    return time.monotonic()


def fmt_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def row_complete(row: dict[str, str]) -> bool:
    return all((row.get(col) or "") != "" for col in PREDICTOR_COLS)


def build_matrix(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[float(row[col]) for col in PREDICTOR_COLS] for row in rows], dtype=float)
    y = np.array([float(row[TARGET_COL]) for row in rows], dtype=float)
    return x, y


def make_model(config: dict[str, object]):
    if XGBOOST_AVAILABLE:
        kwargs = {k: v for k, v in config.items() if k != "label"}
        return XGBRegressor(**kwargs)
    kwargs = {k: v for k, v in config.items() if k != "label"}
    return HistGradientBoostingRegressor(**kwargs)


def mae(truth: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - truth)))


def base_output(row: dict[str, str]) -> dict[str, str]:
    return {
        "forecast_origin_utc": row["forecast_origin_utc"],
        "forecast_origin_local": row["forecast_origin_local"],
        "known_at_cutoff_utc": row["known_at_cutoff_utc"],
        "delivery_start_utc": row["delivery_start_utc"],
        "delivery_end_utc": row["delivery_end_utc"],
        "delivery_date_local": row["delivery_date_local"],
        "delivery_block_id": "daily_full_day",
        "direction": row["direction"],
        "model_name": MODEL_NAME,
        "target_name": "average_procurement_price",
        "y_true": row[TARGET_COL],
        "average_procurement_price_unit": row["average_procurement_price_unit"],
        "dataset_split": row["dataset_split"],
        "granularity": "daily",
        "market_design_regime": "nl_ir_daily_capacity_v1",
        "source_data_version": row["source_data_version"],
        "quality_flags": row["quality_flags"],
        "feature_source": "endogenous_daily_v1",
    }


def main() -> None:
    rows = read_rows(INPUT_PATH)
    train_rows = [row for row in rows if row["dataset_split"] == "train" and row_complete(row)]
    validation_rows = [row for row in rows if row["dataset_split"] == "validation" and row_complete(row)]
    if not train_rows or not validation_rows:
        raise RuntimeError("Insufficient complete train/validation rows for model selection.")

    x_train, y_train = build_matrix(train_rows)
    x_val, y_val = build_matrix(validation_rows)

    best_config = None
    best_model = None
    best_val_mae = float("inf")
    fit_start = monotonic_seconds()
    for config in CANDIDATES:
        model = make_model(config)
        model.fit(x_train, y_train)
        preds = model.predict(x_val)
        current_mae = mae(y_val, preds)
        if current_mae < best_val_mae:
            best_val_mae = current_mae
            best_config = config
            best_model = model
    fit_runtime = monotonic_seconds() - fit_start
    if best_model is None or best_config is None:
        raise RuntimeError("Validation-based model selection failed.")

    predict_start = monotonic_seconds()
    complete_rows = [row for row in rows if row_complete(row)]
    pred_by_key: dict[tuple[str, str], float] = {}
    if complete_rows:
        x_all, _ = build_matrix(complete_rows)
        preds = best_model.predict(x_all)
        pred_by_key = {
            (row["delivery_date_local"], row["direction"]): float(pred)
            for row, pred in zip(complete_rows, preds)
        }
    predict_runtime = monotonic_seconds() - predict_start
    total_runtime = fit_runtime + predict_runtime

    selected_model_type = "XGBRegressor" if XGBOOST_AVAILABLE else "HistGradientBoostingRegressor_fallback"
    selected_hyperparameters = dict(best_config)
    if not XGBOOST_AVAILABLE:
        selected_hyperparameters["reason"] = "xgboost_unavailable"

    output_rows: list[dict[str, str]] = []
    for row in rows:
        out = base_output(row)
        key = (row["delivery_date_local"], row["direction"])
        if key in pred_by_key:
            out["point_forecast"] = fmt_float(pred_by_key[key])
            out["forecast_quality_flags"] = "ok"
        else:
            out["point_forecast"] = ""
            out["forecast_quality_flags"] = "excluded_due_to_missing_predictors"
        out["fit_runtime_seconds"] = fmt_float(fit_runtime)
        out["predict_runtime_seconds"] = fmt_float(predict_runtime)
        out["total_runtime_seconds"] = fmt_float(total_runtime)
        out["n_predictors"] = str(len(PREDICTOR_COLS))
        out["model_config_summary"] = "validation_selected_from_fixed_small_candidate_set"
        out["selected_model_type"] = selected_model_type
        out["selected_hyperparameters"] = json.dumps(selected_hyperparameters, sort_keys=True)
        output_rows.append(out)

    write_rows(OUTPUT_PATH, output_rows)


if __name__ == "__main__":
    main()
