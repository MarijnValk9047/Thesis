from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Iterable

import numpy as np

try:
    from sklearn.linear_model import Lasso
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise RuntimeError("scikit-learn is required for MFRR_CAPACITY_LEAR_DAILY_V1") from exc


REPO_ROOT = Path(__file__).resolve().parents[4]
INPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_daily_direction.csv"
NAIVE_OUTPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_daily_direction_long.csv"
LEAR_OUTPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_daily_direction_long.csv"

TARGET_COL = "target_average_procurement_price"
MODEL_NAME_LEAR = "lear_endogenous_daily_v1"
MODEL_NAME_NAIVE = "naive_lag_7d_same_direction"
ALPHA_GRID = [0.0001, 0.001, 0.01, 0.1, 1.0]
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
COMMON_OUTPUT_COLS = [
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
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def monotonic_seconds() -> float:
    return time.monotonic()


def mae(rows: Iterable[dict[str, str]]) -> float:
    pairs = [(float(row["point_forecast"]), float(row["y_true"])) for row in rows if row["point_forecast"]]
    if not pairs:
        return float("inf")
    return sum(abs(pred - truth) for pred, truth in pairs) / len(pairs)


def base_output_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "forecast_origin_utc": row["forecast_origin_utc"],
        "forecast_origin_local": row["forecast_origin_local"],
        "known_at_cutoff_utc": row["known_at_cutoff_utc"],
        "delivery_start_utc": row["delivery_start_utc"],
        "delivery_end_utc": row["delivery_end_utc"],
        "delivery_date_local": row["delivery_date_local"],
        "delivery_block_id": "daily_full_day",
        "direction": row["direction"],
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


def build_naive_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    predict_start = monotonic_seconds()
    output_rows: list[dict[str, str]] = []
    for row in rows:
        point_forecast = row["avg_price_lag_7d_same_direction"]
        out = base_output_row(row)
        out["model_name"] = MODEL_NAME_NAIVE
        out["point_forecast"] = point_forecast
        out["forecast_quality_flags"] = "ok" if point_forecast else "missing_due_to_lag_warmup"
        output_rows.append(out)
    predict_runtime = monotonic_seconds() - predict_start
    for out in output_rows:
        out["fit_runtime_seconds"] = fmt_float(0.0)
        out["predict_runtime_seconds"] = fmt_float(predict_runtime)
        out["total_runtime_seconds"] = fmt_float(predict_runtime)
        out["n_predictors"] = "1"
        out["model_config_summary"] = MODEL_NAME_NAIVE
    return output_rows


def row_has_complete_predictors(row: dict[str, str]) -> bool:
    return all((row.get(column) or "") != "" for column in PREDICTOR_COLS)


def matrix_from_rows(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[float(row[column]) for column in PREDICTOR_COLS] for row in rows], dtype=float)
    y = np.array([float(row[TARGET_COL]) for row in rows], dtype=float)
    return x, y


def build_lear_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], float, str, float, float]:
    train_rows = [row for row in rows if row["dataset_split"] == "train" and row_has_complete_predictors(row)]
    validation_rows = [row for row in rows if row["dataset_split"] == "validation" and row_has_complete_predictors(row)]
    if not train_rows or not validation_rows:
        raise RuntimeError("Insufficient complete train/validation rows for LEAR fitting.")

    x_train, y_train = matrix_from_rows(train_rows)
    x_val, _ = matrix_from_rows(validation_rows)

    best_alpha = None
    best_model = None
    best_val_mae = float("inf")
    fit_start = monotonic_seconds()
    for alpha in ALPHA_GRID:
        model = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("regressor", Lasso(alpha=alpha, max_iter=100000, random_state=0)),
            ]
        )
        model.fit(x_train, y_train)
        preds = model.predict(x_val)
        val_rows = []
        for source_row, pred in zip(validation_rows, preds):
            val_rows.append({"point_forecast": str(pred), "y_true": source_row[TARGET_COL]})
        current_mae = mae(val_rows)
        if current_mae < best_val_mae:
            best_val_mae = current_mae
            best_alpha = alpha
            best_model = model
    fit_runtime = monotonic_seconds() - fit_start
    if best_model is None or best_alpha is None:
        raise RuntimeError("LEAR model selection failed.")

    predict_start = monotonic_seconds()
    output_rows: list[dict[str, str]] = []
    complete_rows = [row for row in rows if row_has_complete_predictors(row)]
    if complete_rows:
        x_all, _ = matrix_from_rows(complete_rows)
        preds = best_model.predict(x_all)
        pred_by_key = {
            (row["delivery_date_local"], row["direction"]): float(pred)
            for row, pred in zip(complete_rows, preds)
        }
    else:
        pred_by_key = {}
    predict_runtime = monotonic_seconds() - predict_start
    total_runtime = fit_runtime + predict_runtime

    for row in rows:
        out = base_output_row(row)
        out["model_name"] = MODEL_NAME_LEAR
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
        out["model_config_summary"] = f"lasso_standardscaled_alpha_grid_{'-'.join(str(alpha) for alpha in ALPHA_GRID)}"
        out["selected_alpha"] = fmt_float(best_alpha)
        out["selected_model_type"] = "Lasso"
        output_rows.append(out)
    return output_rows, best_alpha, "Lasso", fit_runtime, predict_runtime


def main() -> None:
    rows = read_csv_rows(INPUT_PATH)
    naive_rows = build_naive_rows(rows)
    write_csv_rows(NAIVE_OUTPUT_PATH, naive_rows, COMMON_OUTPUT_COLS)

    lear_rows, _, _, _, _ = build_lear_rows(rows)
    lear_cols = COMMON_OUTPUT_COLS + ["selected_alpha", "selected_model_type"]
    write_csv_rows(LEAR_OUTPUT_PATH, lear_rows, lear_cols)


if __name__ == "__main__":
    main()
