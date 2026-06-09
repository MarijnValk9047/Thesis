from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
BACKTEST_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv"
NAIVE_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv"
OUTPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv"

START_DATE = pd.Timestamp("2024-10-01")
OBSERVED_START = pd.Timestamp("2025-01-07")
END_DATE = pd.Timestamp("2025-09-30")
CALIBRATION_END = pd.Timestamp("2025-06-30")

THRESHOLD_MODEL_NAME = "12_3_f_additive_markup_threshold_proxy_v1"
SCENARIO_METHOD = "deterministic_three_role_additive_markup_scenarios_v1"
MARKET_DESIGN = "nl_ir_daily_capacity_threshold_scenarios_v1"
METHOD_CAVEAT = "accepted_offer_threshold_proxy_rejected_bids_unobserved_not_full_bid_ladder_not_observed_truth"

SCENARIOS = [
    {
        "scenario_id": "threshold_conservative_p75",
        "scenario_role": "conservative",
        "scenario_probability": 0.25,
        "threshold_proxy_name": "accepted_price_p75_eur_per_maw",
        "markup_rule_name": "direction_daytype_median_markup",
    },
    {
        "scenario_id": "threshold_central_p90",
        "scenario_role": "central_upper_normal",
        "scenario_probability": 0.50,
        "threshold_proxy_name": "accepted_price_p90_eur_per_maw",
        "markup_rule_name": "direction_daytype_median_markup",
    },
    {
        "scenario_id": "threshold_optimistic_max",
        "scenario_role": "optimistic_upper_bound",
        "scenario_probability": 0.25,
        "threshold_proxy_name": "max_accepted_price_proxy_eur_per_maw",
        "markup_rule_name": "direction_daytype_median_markup",
    },
]


def load_naive_test() -> pd.DataFrame:
    df = pd.read_csv(
        NAIVE_PATH,
        parse_dates=[
            "forecast_origin_utc",
            "forecast_origin_local",
            "known_at_cutoff_utc",
            "delivery_start_utc",
            "delivery_end_utc",
            "delivery_date_local",
        ],
    )
    df = df.loc[
        (df["dataset_split"] == "test")
        & (df["model_name"] == "naive_lag_7d_same_direction")
        & (df["delivery_date_local"] >= START_DATE)
        & (df["delivery_date_local"] <= END_DATE)
    ].copy()
    if df.duplicated(["delivery_date_local", "direction"]).sum() != 0:
        raise ValueError("Naive test forecast has duplicate delivery_date_local x direction keys.")
    if df["point_forecast"].isna().any():
        missing = df.loc[df["point_forecast"].isna(), ["delivery_date_local", "direction"]]
        raise ValueError(f"Naive test forecast is incomplete: {missing.head(5).to_dict('records')}")
    df["daytype"] = np.where(df["delivery_date_local"].dt.dayofweek >= 5, "weekend", "weekday")
    return df


def extract_markup_tables() -> dict[str, dict[tuple[str, str], float]]:
    df = pd.read_csv(BACKTEST_PATH, parse_dates=["delivery_date_local"])
    df = df.loc[
        (df["average_price_model_name"] == "naive_lag_7d_same_direction")
        & (df["markup_rule_name"] == "direction_daytype_median_markup")
        & (df["threshold_proxy_name"].isin([s["threshold_proxy_name"] for s in SCENARIOS]))
        & (df["delivery_date_local"] >= OBSERVED_START)
        & (df["delivery_date_local"] <= END_DATE)
    ].copy()
    if df.empty:
        raise ValueError("Backtest artifact is missing the selected Naive daytype-markup combinations.")

    df["daytype"] = np.where(df["delivery_date_local"].dt.dayofweek >= 5, "weekend", "weekday")
    calibration = df.loc[df["calibration_split"] == "calibration"].copy()
    if calibration.empty:
        raise ValueError("Calibration rows are missing from the backtest artifact.")

    markups: dict[str, dict[tuple[str, str], float]] = {}
    for proxy in [s["threshold_proxy_name"] for s in SCENARIOS]:
        subset = df.loc[df["threshold_proxy_name"] == proxy].copy()
        cal_subset = calibration.loc[calibration["threshold_proxy_name"] == proxy].copy()

        all_unique = subset.groupby(["direction", "daytype"])["calibrated_markup_value"].nunique(dropna=False)
        cal_unique = cal_subset.groupby(["direction", "daytype"])["calibrated_markup_value"].nunique(dropna=False)
        if (all_unique > 1).any():
            raise ValueError(f"Inconsistent calibrated markup values across rows for {proxy}.")
        if (cal_unique > 1).any():
            raise ValueError(f"Inconsistent calibration-only markup values for {proxy}.")

        all_values = subset.groupby(["direction", "daytype"])["calibrated_markup_value"].first().to_dict()
        cal_values = cal_subset.groupby(["direction", "daytype"])["calibrated_markup_value"].first().to_dict()
        if set(all_values.keys()) != set(cal_values.keys()):
            raise ValueError(f"Calibration coverage mismatch for {proxy}.")
        for key, value in cal_values.items():
            if pd.isna(value):
                raise ValueError(f"Missing calibrated markup for {proxy}, key={key}.")
            if not np.isclose(value, all_values[key]):
                raise ValueError(f"Calibration/evaluation mismatch for {proxy}, key={key}.")
        markups[proxy] = cal_values
    return markups


def build_quality_flag(row: pd.Series) -> str:
    flags: list[str] = []
    if pd.isna(row["average_price_forecast"]):
        flags.append("missing_average_price_forecast")
    if pd.isna(row["calibrated_markup_value"]):
        flags.append("missing_calibrated_markup")
    if row["threshold_price_scenario"] < 0:
        flags.append("negative_threshold_scenario")
    if row["threshold_source_scope"] == "synthetic_proxy_pre_12_3_f_overlap":
        flags.append("synthetic_pre_12_3_f_overlap")
    else:
        flags.append("observed_overlap_proxy_evaluable")
    if bool(row.get("scenario_order_violation", False)):
        flags.append("scenario_order_violation")
    return "|".join(flags)


def generate_scenarios(naive_test: pd.DataFrame, markups: dict[str, dict[tuple[str, str], float]]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for spec in SCENARIOS:
        frame = naive_test.copy()
        proxy = spec["threshold_proxy_name"]
        frame["average_price_model_name"] = frame["model_name"]
        frame["average_price_forecast"] = frame["point_forecast"]
        frame["threshold_model_name"] = THRESHOLD_MODEL_NAME
        frame["scenario_id"] = spec["scenario_id"]
        frame["scenario_role"] = spec["scenario_role"]
        frame["scenario_probability"] = spec["scenario_probability"]
        frame["threshold_proxy_name"] = proxy
        frame["markup_rule_name"] = spec["markup_rule_name"]
        frame["calibrated_markup_value"] = frame.apply(
            lambda r: markups[proxy].get((r["direction"], r["daytype"]), np.nan), axis=1
        )
        frame["threshold_price_scenario"] = frame["average_price_forecast"] + frame["calibrated_markup_value"]
        frame["threshold_source_scope"] = np.where(
            frame["delivery_date_local"] < OBSERVED_START,
            "synthetic_proxy_pre_12_3_f_overlap",
            "observed_overlap_proxy_evaluable",
        )
        frame["threshold_observed_overlap_flag"] = frame["delivery_date_local"] >= OBSERVED_START
        frame["scenario_generation_method"] = SCENARIO_METHOD
        frame["granularity"] = "daily"
        frame["market_design_regime"] = MARKET_DESIGN
        frame["source_data_version"] = "naive7d_test_plus_12_3_f_daytype_markup_roles_v1"
        frame["methodological_caveat"] = METHOD_CAVEAT
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    pivot = combined.pivot_table(
        index=["delivery_date_local", "direction"],
        columns="scenario_id",
        values="threshold_price_scenario",
        aggfunc="first",
    )
    violation_index = pivot.index[
        (pivot["threshold_conservative_p75"] > pivot["threshold_central_p90"])
        | (pivot["threshold_central_p90"] > pivot["threshold_optimistic_max"])
    ]
    combined["scenario_order_violation"] = combined.set_index(["delivery_date_local", "direction"]).index.isin(violation_index)
    combined["quality_flags"] = combined.apply(build_quality_flag, axis=1)

    keep_cols = [
        "forecast_origin_utc",
        "forecast_origin_local",
        "known_at_cutoff_utc",
        "delivery_start_utc",
        "delivery_end_utc",
        "delivery_date_local",
        "delivery_block_id",
        "direction",
        "average_price_model_name",
        "average_price_forecast",
        "threshold_model_name",
        "scenario_id",
        "scenario_role",
        "scenario_probability",
        "threshold_proxy_name",
        "markup_rule_name",
        "calibrated_markup_value",
        "threshold_price_scenario",
        "threshold_source_scope",
        "threshold_observed_overlap_flag",
        "scenario_generation_method",
        "granularity",
        "market_design_regime",
        "source_data_version",
        "quality_flags",
        "methodological_caveat",
    ]
    return combined[keep_cols].sort_values(["delivery_date_local", "direction", "scenario_id"]).reset_index(drop=True)


def validate_output(df: pd.DataFrame) -> dict[str, object]:
    expected_rows = 730 * 3
    if len(df) != expected_rows:
        raise ValueError(f"Output row count mismatch: got {len(df)}, expected {expected_rows}.")
    if df.duplicated(["delivery_date_local", "direction", "scenario_id"]).sum() != 0:
        raise ValueError("Duplicate delivery_date_local x direction x scenario_id keys found.")
    if df["delivery_date_local"].min() != START_DATE or df["delivery_date_local"].max() != END_DATE:
        raise ValueError("Scenario horizon does not match 2024-10-01 to 2025-09-30.")
    if set(df["direction"].unique()) != {"Up", "Down"}:
        raise ValueError("Unexpected direction values found.")
    if set(df["scenario_id"].unique()) != {s["scenario_id"] for s in SCENARIOS}:
        raise ValueError("Unexpected scenario IDs found.")
    if set(df["average_price_model_name"].unique()) != {"naive_lag_7d_same_direction"}:
        raise ValueError("Unexpected average_price_model_name values found.")
    if set(df["threshold_model_name"].unique()) != {THRESHOLD_MODEL_NAME}:
        raise ValueError("Unexpected threshold_model_name values found.")
    if df["average_price_forecast"].isna().any():
        raise ValueError("Missing average_price_forecast values found in the output.")
    if df["calibrated_markup_value"].isna().any():
        raise ValueError("Missing calibrated_markup_value values found in the output.")
    if df["threshold_price_scenario"].isna().any():
        raise ValueError("Missing threshold_price_scenario values found in the output.")
    if not np.allclose(df["threshold_price_scenario"], df["average_price_forecast"] + df["calibrated_markup_value"]):
        raise ValueError("threshold_price_scenario does not equal average_price_forecast + calibrated_markup_value.")

    probability_sums = df.groupby(["delivery_date_local", "direction"])["scenario_probability"].sum()
    if not np.allclose(probability_sums.values, 1.0):
        raise ValueError("Scenario probabilities do not sum to 1.0 for every delivery_date_local x direction.")
    rows_per_key = df.groupby(["delivery_date_local", "direction"]).size()
    if not rows_per_key.eq(3).all():
        raise ValueError("There are not exactly three scenario rows per delivery_date_local x direction.")

    pre_overlap = df["delivery_date_local"] < OBSERVED_START
    if not (~df.loc[pre_overlap, "threshold_observed_overlap_flag"]).all():
        raise ValueError("Pre-overlap rows are incorrectly marked as observed overlap.")
    if not (df.loc[~pre_overlap, "threshold_observed_overlap_flag"]).all():
        raise ValueError("Observed-overlap rows are incorrectly marked as synthetic.")
    if set(df.loc[pre_overlap, "threshold_source_scope"].unique()) != {"synthetic_proxy_pre_12_3_f_overlap"}:
        raise ValueError("Incorrect threshold_source_scope values in pre-overlap rows.")
    if set(df.loc[~pre_overlap, "threshold_source_scope"].unique()) != {"observed_overlap_proxy_evaluable"}:
        raise ValueError("Incorrect threshold_source_scope values in observed-overlap rows.")

    role_map = {s["scenario_id"]: s for s in SCENARIOS}
    for scenario_id, spec in role_map.items():
        subset = df.loc[df["scenario_id"] == scenario_id]
        if set(subset["threshold_proxy_name"].unique()) != {spec["threshold_proxy_name"]}:
            raise ValueError(f"{scenario_id} has the wrong threshold_proxy_name.")
        if set(subset["markup_rule_name"].unique()) != {spec["markup_rule_name"]}:
            raise ValueError(f"{scenario_id} has the wrong markup_rule_name.")
        if set(subset["scenario_role"].unique()) != {spec["scenario_role"]}:
            raise ValueError(f"{scenario_id} has the wrong scenario_role.")
        if not np.allclose(subset["scenario_probability"].unique(), [spec["scenario_probability"]]):
            raise ValueError(f"{scenario_id} has the wrong scenario_probability.")

    pivot = df.pivot_table(
        index=["delivery_date_local", "direction"],
        columns="scenario_id",
        values="threshold_price_scenario",
        aggfunc="first",
    )
    viol1 = pivot["threshold_conservative_p75"] > pivot["threshold_central_p90"]
    viol2 = pivot["threshold_central_p90"] > pivot["threshold_optimistic_max"]
    if int(viol1.sum()) != 0 or int(viol2.sum()) != 0:
        raise ValueError("Scenario ordering violations remain in the final output.")

    return {
        "row_count": len(df),
        "date_min": df["delivery_date_local"].min().strftime("%Y-%m-%d"),
        "date_max": df["delivery_date_local"].max().strftime("%Y-%m-%d"),
        "scenario_counts": df["scenario_id"].value_counts().to_dict(),
        "quality_flags": df["quality_flags"].value_counts().to_dict(),
        "synthetic_rows": int(pre_overlap.sum()),
        "observed_overlap_rows": int((~pre_overlap).sum()),
    }


def main() -> None:
    naive_test = load_naive_test()
    markups = extract_markup_tables()
    output = generate_scenarios(naive_test, markups)
    validate_output(output)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(output)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
