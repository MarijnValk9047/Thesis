from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
THRESHOLD_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_observed_threshold_table_daily_direction.csv"
FEATURES_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv"
NAIVE_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv"
LEAR_EXOG_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv"
XGB_EXOG_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv"
OUTPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv"

START_DATE = pd.Timestamp("2025-01-07")
CALIBRATION_END = pd.Timestamp("2025-06-30")
END_DATE = pd.Timestamp("2025-09-30")
COMPARISON_EPSILON = 1e-12

ALLOWED_MODELS = {
    "naive_lag_7d_same_direction": NAIVE_PATH,
    "lear_exogenous_small_da_aligned_daily_v1": LEAR_EXOG_PATH,
    "xgboost_exogenous_small_da_aligned_daily_v1": XGB_EXOG_PATH,
}
THRESHOLD_PROXIES = [
    "accepted_price_p75_eur_per_maw",
    "accepted_price_p90_eur_per_maw",
    "max_accepted_price_proxy_eur_per_maw",
]
MARKUP_RULES = [
    "direction_median_markup",
    "direction_p75_markup",
    "direction_p90_markup",
    "direction_daytype_median_markup",
]
METHOD_CAVEAT = "accepted_offer_threshold_proxy_rejected_bids_unobserved_not_full_bid_ladder"
KNOWN_AT_RULE = "threshold_observation_ex_post_calibration_only_average_price_forecasts_known_at_bid_time"
MARKET_DESIGN = "nl_ir_daily_capacity_threshold_calibration_v1"


def build_quality_flags(row: pd.Series) -> str:
    flags: list[str] = []
    source_flags = str(row.get("threshold_source_coverage_flags", ""))
    if "suspicious_extreme_price" in source_flags:
        flags.append("threshold_source_extreme_price_flag")
    if pd.isna(row["average_price_forecast"]):
        flags.append("missing_average_price_forecast")
    if pd.isna(row["observed_average_procurement_price"]):
        flags.append("missing_observed_average_price")
    if pd.isna(row["observed_threshold_proxy"]):
        flags.append("missing_threshold_proxy")
    if bool(row.get("daytype_markup_fallback_used", False)):
        flags.append("daytype_markup_fallback_to_direction_median")
    if bool(row.get("calibration_rule_not_available_bool", False)):
        flags.append("calibration_rule_not_available")
    return "ok" if not flags else "|".join(flags)


def load_thresholds() -> pd.DataFrame:
    df = pd.read_csv(
        THRESHOLD_PATH,
        parse_dates=["delivery_date_local", "delivery_start_utc", "delivery_end_utc"],
    )
    df = df.loc[(df["delivery_date_local"] >= START_DATE) & (df["delivery_date_local"] <= END_DATE)].copy()
    if df.empty:
        raise ValueError("Observed threshold table has no rows in the calibration/evaluation horizon.")
    if df.duplicated(["delivery_date_local", "direction"]).sum() != 0:
        raise ValueError("Observed threshold table has duplicate delivery_date_local x direction keys.")
    df = df.rename(columns={"coverage_flags": "threshold_source_coverage_flags"})
    return df


def load_observed_average() -> pd.DataFrame:
    df = pd.read_csv(
        FEATURES_PATH,
        usecols=["delivery_date_local", "direction", "target_average_procurement_price"],
        parse_dates=["delivery_date_local"],
    )
    df = df.loc[(df["delivery_date_local"] >= START_DATE) & (df["delivery_date_local"] <= END_DATE)].copy()
    if df.duplicated(["delivery_date_local", "direction"]).sum() != 0:
        raise ValueError("Observed average-price source has duplicate delivery_date_local x direction keys.")
    return df.rename(columns={"target_average_procurement_price": "observed_average_procurement_price"})


def load_anchor_forecasts() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for expected_model_name, path in ALLOWED_MODELS.items():
        df = pd.read_csv(
            path,
            usecols=["delivery_date_local", "direction", "model_name", "point_forecast", "feature_source"],
            parse_dates=["delivery_date_local"],
        )
        df = df.loc[(df["delivery_date_local"] >= START_DATE) & (df["delivery_date_local"] <= END_DATE)].copy()
        if set(df["model_name"].unique()) != {expected_model_name}:
            raise ValueError(f"Forecast artifact {path.name} has unexpected model names.")
        if df.duplicated(["delivery_date_local", "direction"]).sum() != 0:
            raise ValueError(f"Forecast artifact {path.name} has duplicate delivery_date_local x direction keys.")
        df = df.rename(
            columns={
                "model_name": "average_price_model_name",
                "point_forecast": "average_price_forecast",
                "feature_source": "average_price_source_dataset",
            }
        )
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def prepare_base_frame() -> pd.DataFrame:
    thresholds = load_thresholds()
    observed_avg = load_observed_average()
    anchors = load_anchor_forecasts()

    merged = thresholds.merge(observed_avg, on=["delivery_date_local", "direction"], how="left", validate="one_to_one")
    missing_avg = merged["observed_average_procurement_price"].isna()
    if missing_avg.any():
        sample = merged.loc[missing_avg, ["delivery_date_local", "direction"]].head(5).to_dict("records")
        raise ValueError(f"Observed average-price join is incomplete: {sample}")

    merged = merged.merge(anchors, on=["delivery_date_local", "direction"], how="inner", validate="one_to_many")
    expected_rows = len(thresholds) * len(ALLOWED_MODELS)
    if len(merged) != expected_rows:
        raise ValueError(f"Average-price join coverage mismatch: got {len(merged)} rows, expected {expected_rows}.")

    eval_missing_forecast = merged.loc[
        (merged["calibration_split"] == "evaluation") & merged["average_price_forecast"].isna(),
        ["delivery_date_local", "direction", "average_price_model_name"],
    ]
    if not eval_missing_forecast.empty:
        raise ValueError(f"Evaluation rows are missing average-price forecasts: {eval_missing_forecast.head(5).to_dict('records')}")

    merged["daytype"] = np.where(merged["delivery_date_local"].dt.dayofweek >= 5, "weekend", "weekday")
    return merged


def compute_markup_tables(base: pd.DataFrame) -> dict[str, dict[str, pd.DataFrame | pd.Series]]:
    calibration = base.loc[base["calibration_split"] == "calibration"].copy()
    tables: dict[str, dict[str, pd.DataFrame | pd.Series]] = {}
    for proxy in THRESHOLD_PROXIES:
        calibration_proxy = calibration[["delivery_date_local", "direction", "daytype", "observed_average_procurement_price", proxy]].copy()
        calibration_proxy["observed_markup"] = calibration_proxy[proxy] - calibration_proxy["observed_average_procurement_price"]
        direction_median = calibration_proxy.groupby("direction")["observed_markup"].median()
        direction_p75 = calibration_proxy.groupby("direction")["observed_markup"].quantile(0.75)
        direction_p90 = calibration_proxy.groupby("direction")["observed_markup"].quantile(0.90)
        daytype_median = calibration_proxy.groupby(["direction", "daytype"])["observed_markup"].median().reset_index()
        tables[proxy] = {
            "direction_median_markup": direction_median,
            "direction_p75_markup": direction_p75,
            "direction_p90_markup": direction_p90,
            "direction_daytype_median_markup": daytype_median,
        }
    return tables


def expand_backtest(base: pd.DataFrame, markup_tables: dict[str, dict[str, pd.DataFrame | pd.Series]]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for proxy in THRESHOLD_PROXIES:
        for rule_name in MARKUP_RULES:
            frame = base.copy()
            frame["threshold_proxy_name"] = proxy
            frame["observed_threshold_proxy"] = frame[proxy]
            frame["observed_markup_vs_observed_avg"] = (
                frame["observed_threshold_proxy"] - frame["observed_average_procurement_price"]
            )
            frame["markup_rule_name"] = rule_name
            frame["daytype_markup_fallback_used"] = False
            frame["calibration_rule_not_available_bool"] = False

            if rule_name == "direction_daytype_median_markup":
                daytype_table = markup_tables[proxy][rule_name].rename(columns={"observed_markup": "calibrated_markup_value"})
                frame = frame.merge(daytype_table, on=["direction", "daytype"], how="left")
                direction_fallback = markup_tables[proxy]["direction_median_markup"].rename("direction_median_markup_value")
                frame = frame.merge(direction_fallback, on="direction", how="left")
                frame["daytype_markup_fallback_used"] = frame["calibrated_markup_value"].isna() & frame["direction_median_markup_value"].notna()
                frame["calibrated_markup_value"] = frame["calibrated_markup_value"].fillna(frame["direction_median_markup_value"])
                frame["calibration_rule_not_available_bool"] = frame["calibrated_markup_value"].isna()
                frame = frame.drop(columns=["direction_median_markup_value"])
            else:
                series = markup_tables[proxy][rule_name]
                assert isinstance(series, pd.Series)
                frame = frame.merge(series.rename("calibrated_markup_value"), on="direction", how="left")
                frame["calibration_rule_not_available_bool"] = frame["calibrated_markup_value"].isna()

            frame["predicted_threshold_proxy"] = frame["average_price_forecast"] + frame["calibrated_markup_value"]
            missing_prediction = frame["average_price_forecast"].isna() | frame["calibrated_markup_value"].isna()
            frame.loc[missing_prediction, "predicted_threshold_proxy"] = np.nan

            frame["threshold_error"] = frame["predicted_threshold_proxy"] - frame["observed_threshold_proxy"]
            frame["threshold_absolute_error"] = frame["threshold_error"].abs()
            valid_mask = frame["predicted_threshold_proxy"].notna() & frame["observed_threshold_proxy"].notna()
            diff = frame["predicted_threshold_proxy"] - frame["observed_threshold_proxy"]
            frame["accepted_proxy"] = pd.Series(pd.NA, index=frame.index, dtype="boolean")
            frame.loc[valid_mask, "accepted_proxy"] = (diff.loc[valid_mask] <= COMPARISON_EPSILON).astype("boolean")
            frame["overbid_proxy"] = pd.Series(pd.NA, index=frame.index, dtype="boolean")
            frame.loc[valid_mask, "overbid_proxy"] = (diff.loc[valid_mask] > COMPARISON_EPSILON).astype("boolean")
            frame["underbid_margin"] = frame["observed_threshold_proxy"] - frame["predicted_threshold_proxy"]
            frame["unit_revenue_proxy_eur_per_maw"] = np.where(
                frame["accepted_proxy"].fillna(False),
                frame["predicted_threshold_proxy"],
                0.0,
            )
            frame.loc[frame["predicted_threshold_proxy"].isna(), "unit_revenue_proxy_eur_per_maw"] = np.nan
            frame["offered_mw_assumption"] = 1
            frame["threshold_source_dataset"] = frame["source_dataset"]
            frame["known_at_rule"] = KNOWN_AT_RULE
            frame["methodological_caveat"] = METHOD_CAVEAT
            frame["market_design_regime"] = MARKET_DESIGN
            frame["quality_flags"] = frame.apply(build_quality_flags, axis=1)
            frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    keep_cols = [
        "delivery_date_local",
        "direction",
        "delivery_start_utc",
        "delivery_end_utc",
        "delivery_block_id",
        "granularity",
        "market_design_regime",
        "calibration_split",
        "average_price_model_name",
        "average_price_forecast",
        "observed_average_procurement_price",
        "threshold_proxy_name",
        "observed_threshold_proxy",
        "observed_markup_vs_observed_avg",
        "markup_rule_name",
        "calibrated_markup_value",
        "predicted_threshold_proxy",
        "threshold_error",
        "threshold_absolute_error",
        "overbid_proxy",
        "accepted_proxy",
        "underbid_margin",
        "unit_revenue_proxy_eur_per_maw",
        "offered_mw_assumption",
        "threshold_source_dataset",
        "average_price_source_dataset",
        "quantity_weighting_method",
        "known_at_rule",
        "methodological_caveat",
        "quality_flags",
    ]
    return combined[keep_cols].sort_values(
        ["delivery_date_local", "direction", "average_price_model_name", "threshold_proxy_name", "markup_rule_name"]
    ).reset_index(drop=True)


def metric_summary(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["calibration_split", "direction", "average_price_model_name", "threshold_proxy_name", "markup_rule_name"]
    rows: list[dict[str, object]] = []
    for keys, group in df.groupby(group_cols, dropna=False):
        valid = group.loc[group["threshold_absolute_error"].notna()].copy()
        accepted = valid.loc[valid["accepted_proxy"] == True]  # noqa: E712
        row = dict(zip(group_cols, keys))
        row["count"] = int(len(valid))
        row["threshold_mae"] = float(valid["threshold_absolute_error"].mean()) if not valid.empty else np.nan
        row["threshold_rmse"] = float(np.sqrt((valid["threshold_error"] ** 2).mean())) if not valid.empty else np.nan
        row["threshold_bias"] = float(valid["threshold_error"].mean()) if not valid.empty else np.nan
        row["median_absolute_error"] = float(valid["threshold_absolute_error"].median()) if not valid.empty else np.nan
        row["p90_absolute_error"] = float(valid["threshold_absolute_error"].quantile(0.90)) if not valid.empty else np.nan
        row["overbid_proxy_rate"] = float(valid["overbid_proxy"].mean()) if not valid.empty else np.nan
        row["accepted_proxy_rate"] = float(valid["accepted_proxy"].mean()) if not valid.empty else np.nan
        row["mean_underbid_margin_on_accepted_proxy_rows"] = float(accepted["underbid_margin"].mean()) if not accepted.empty else np.nan
        row["mean_unit_revenue_proxy"] = float(valid["unit_revenue_proxy_eur_per_maw"].mean()) if not valid.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def validate_output(df: pd.DataFrame) -> dict[str, object]:
    expected_rows = 534 * 3 * 3 * 4
    if len(df) != expected_rows:
        raise ValueError(f"Output row count mismatch: got {len(df)}, expected {expected_rows}.")
    if df.duplicated(
        ["delivery_date_local", "direction", "average_price_model_name", "threshold_proxy_name", "markup_rule_name"]
    ).sum() != 0:
        raise ValueError("Output has duplicate expanded keys.")
    if set(df["average_price_model_name"].unique()) != set(ALLOWED_MODELS.keys()):
        raise ValueError("Output has unexpected average_price_model_name values.")
    if set(df["threshold_proxy_name"].unique()) != set(THRESHOLD_PROXIES):
        raise ValueError("Output has unexpected threshold_proxy_name values.")
    if set(df["markup_rule_name"].unique()) != set(MARKUP_RULES):
        raise ValueError("Output has unexpected markup_rule_name values.")
    if set(df["calibration_split"].unique()) != {"calibration", "evaluation"}:
        raise ValueError("Output has unexpected calibration_split values.")
    if df["delivery_date_local"].min() != START_DATE or df["delivery_date_local"].max() != END_DATE:
        raise ValueError("Output date range does not match the required horizon.")

    if not np.allclose(
        df["threshold_error"],
        df["predicted_threshold_proxy"] - df["observed_threshold_proxy"],
        equal_nan=True,
    ):
        raise ValueError("threshold_error definition mismatch.")
    if not np.allclose(
        df["threshold_absolute_error"],
        (df["predicted_threshold_proxy"] - df["observed_threshold_proxy"]).abs(),
        equal_nan=True,
    ):
        raise ValueError("threshold_absolute_error definition mismatch.")

    valid = df.loc[df["predicted_threshold_proxy"].notna() & df["observed_threshold_proxy"].notna()].copy()
    if not ((valid["accepted_proxy"] == (~valid["overbid_proxy"])) | (valid["accepted_proxy"] & (~valid["overbid_proxy"]))).all():
        raise ValueError("accepted_proxy and overbid_proxy are not logical complements.")
    equal_rows = (valid["predicted_threshold_proxy"] - valid["observed_threshold_proxy"]).abs() <= COMPARISON_EPSILON
    if not (valid.loc[equal_rows, "accepted_proxy"].fillna(False)).all():
        raise ValueError("accepted_proxy should be true on exact equality rows.")
    if (valid.loc[valid["overbid_proxy"] == True, "unit_revenue_proxy_eur_per_maw"] != 0).any():  # noqa: E712
        raise ValueError("unit_revenue_proxy should be zero when overbid_proxy is true.")
    accepted_rows = valid["accepted_proxy"] == True  # noqa: E712
    if not np.allclose(
        valid.loc[accepted_rows, "unit_revenue_proxy_eur_per_maw"],
        valid.loc[accepted_rows, "predicted_threshold_proxy"],
    ):
        raise ValueError("unit_revenue_proxy should equal predicted_threshold_proxy when accepted_proxy is true.")

    evaluation = df.loc[df["calibration_split"] == "evaluation"]
    if evaluation["average_price_forecast"].isna().any():
        raise ValueError("Evaluation rows are missing average-price forecasts.")
    if evaluation["observed_average_procurement_price"].isna().any():
        raise ValueError("Evaluation rows are missing observed average prices.")

    return {
        "row_count": len(df),
        "date_min": df["delivery_date_local"].min().strftime("%Y-%m-%d"),
        "date_max": df["delivery_date_local"].max().strftime("%Y-%m-%d"),
        "split_counts": df["calibration_split"].value_counts().to_dict(),
        "quality_flag_counts": df["quality_flags"].value_counts().to_dict(),
    }


def main() -> None:
    base = prepare_base_frame()
    markup_tables = compute_markup_tables(base)
    output = expand_backtest(base, markup_tables)
    validate_output(output)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(output)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
