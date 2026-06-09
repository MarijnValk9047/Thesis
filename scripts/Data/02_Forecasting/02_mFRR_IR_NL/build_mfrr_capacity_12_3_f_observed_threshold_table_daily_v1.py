from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
OFFER_INPUT = REPO_ROOT / "data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/parsed/12_3_f_nl_ir_offer_long.csv"
DAILY_INPUT = REPO_ROOT / "data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/aggregated/12_3_f_nl_ir_daily_direction_long.csv"
OUTPUT_PATH = REPO_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_observed_threshold_table_daily_direction.csv"

START_DATE = pd.Timestamp("2025-01-07")
CALIBRATION_END = pd.Timestamp("2025-06-30")
END_DATE = pd.Timestamp("2025-09-30")
WEIGHTED_PRICE_TOLERANCE = 1e-6
VALIDATION_EPSILON = 1e-9
PRICE_EXTREME_THRESHOLD = 1000.0
QUANTITY_EXTREME_THRESHOLD = 200.0

REQUIRED_OFFER_COLUMNS = [
    "native_offer_id",
    "flow_direction_code",
    "flow_direction_label",
    "target_delivery_local_date",
    "timestamp_utc",
    "interval_end_utc",
    "quantity_maw",
    "procurement_price_eur_per_maw",
    "known_at_rule",
]

REQUIRED_DAILY_COLUMNS = [
    "target_delivery_local_date",
    "flow_direction_code",
    "flow_direction_label",
    "offer_count",
    "total_quantity_maw",
    "quantity_weighted_price_eur_per_maw",
    "source_offer_rows",
]

DIRECTION_MAP = {"A01": "Up", "A02": "Down"}


def weighted_step_quantile(prices: pd.Series, weights: pd.Series, threshold: float) -> float:
    ordered = pd.DataFrame({"price": prices.astype(float), "weight": weights.astype(float)}).sort_values(
        ["price", "weight"], kind="mergesort"
    )
    cumulative_share = ordered["weight"].cumsum() / ordered["weight"].sum()
    idx = cumulative_share.ge(threshold).idxmax()
    return float(ordered.loc[idx, "price"])


def build_coverage_flag(row: pd.Series) -> str:
    flags: list[str] = []
    if row["accepted_offer_count"] <= 0:
        flags.append("missing_direction")
    if row["accepted_offer_count"] != row["source_offer_rows"]:
        flags.append("incomplete_day")
    if row["max_accepted_price_proxy_eur_per_maw"] >= PRICE_EXTREME_THRESHOLD:
        flags.append("suspicious_extreme_price")
    if row["max_offer_quantity_maw"] >= QUANTITY_EXTREME_THRESHOLD:
        flags.append("suspicious_extreme_quantity")
    if not row["weighted_price_crosscheck_ok"]:
        flags.append("crosscheck_weighted_price_mismatch")
    if not row["offer_count_crosscheck_ok"]:
        flags.append("crosscheck_offer_count_mismatch")
    if not row["quantity_sum_crosscheck_ok"]:
        flags.append("crosscheck_quantity_sum_mismatch")
    return "ok" if not flags else "|".join(flags)


def load_offer_data() -> pd.DataFrame:
    offer = pd.read_csv(
        OFFER_INPUT,
        usecols=REQUIRED_OFFER_COLUMNS,
        parse_dates=["timestamp_utc", "interval_end_utc"],
    )
    missing = sorted(set(REQUIRED_OFFER_COLUMNS) - set(offer.columns))
    if missing:
        raise ValueError(f"Offer-level file is missing required columns: {missing}")

    offer["delivery_date_local"] = pd.to_datetime(offer["target_delivery_local_date"])
    offer = offer.loc[(offer["delivery_date_local"] >= START_DATE) & (offer["delivery_date_local"] <= END_DATE)].copy()
    offer["direction"] = offer["flow_direction_code"].map(DIRECTION_MAP)
    if offer["direction"].isna().any():
        unresolved = sorted(offer.loc[offer["direction"].isna(), "flow_direction_code"].dropna().unique().tolist())
        raise ValueError(f"Ambiguous direction mapping for codes: {unresolved}")

    if (offer["quantity_maw"] <= 0).any():
        raise ValueError("Parsed offer-level file contains non-positive quantities in the selected horizon.")
    if (offer["procurement_price_eur_per_maw"] <= 0).any():
        raise ValueError("Parsed offer-level file contains non-positive prices in the selected horizon.")

    return offer


def load_daily_crosscheck() -> pd.DataFrame:
    daily = pd.read_csv(DAILY_INPUT, usecols=REQUIRED_DAILY_COLUMNS)
    missing = sorted(set(REQUIRED_DAILY_COLUMNS) - set(daily.columns))
    if missing:
        raise ValueError(f"Aggregated daily file is missing required columns: {missing}")

    daily["delivery_date_local"] = pd.to_datetime(daily["target_delivery_local_date"])
    daily = daily.loc[(daily["delivery_date_local"] >= START_DATE) & (daily["delivery_date_local"] <= END_DATE)].copy()
    daily["direction"] = daily["flow_direction_code"].map(DIRECTION_MAP)
    if daily["direction"].isna().any():
        unresolved = sorted(daily.loc[daily["direction"].isna(), "flow_direction_code"].dropna().unique().tolist())
        raise ValueError(f"Ambiguous daily direction mapping for codes: {unresolved}")
    return daily


def aggregate_observed_thresholds(offer: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for (delivery_date, direction), group in offer.groupby(["delivery_date_local", "direction"], sort=True):
        quantity_sum = float(group["quantity_maw"].sum())
        weighted_price = float(np.average(group["procurement_price_eur_per_maw"], weights=group["quantity_maw"]))
        p10 = weighted_step_quantile(group["procurement_price_eur_per_maw"], group["quantity_maw"], 0.10)
        p25 = weighted_step_quantile(group["procurement_price_eur_per_maw"], group["quantity_maw"], 0.25)
        p50 = weighted_step_quantile(group["procurement_price_eur_per_maw"], group["quantity_maw"], 0.50)
        p75 = weighted_step_quantile(group["procurement_price_eur_per_maw"], group["quantity_maw"], 0.75)
        p90 = weighted_step_quantile(group["procurement_price_eur_per_maw"], group["quantity_maw"], 0.90)
        min_price = float(group["procurement_price_eur_per_maw"].min())
        max_price = float(group["procurement_price_eur_per_maw"].max())

        records.append(
            {
                "delivery_date_local": delivery_date,
                "direction": direction,
                "delivery_start_utc": group["timestamp_utc"].min(),
                "delivery_end_utc": group["interval_end_utc"].max(),
                "delivery_block_id": "daily_full_day",
                "granularity": "daily",
                "market_design_regime": "nl_ir_daily_capacity_threshold_proxy_v1",
                "accepted_offer_count": int(len(group)),
                "accepted_quantity_sum_maw": quantity_sum,
                "weighted_accepted_price_eur_per_maw": weighted_price,
                "accepted_price_p10_eur_per_maw": p10,
                "accepted_price_p25_eur_per_maw": p25,
                "accepted_price_p50_eur_per_maw": p50,
                "accepted_price_p75_eur_per_maw": p75,
                "accepted_price_p90_eur_per_maw": p90,
                "min_accepted_price_eur_per_maw": min_price,
                "max_accepted_price_proxy_eur_per_maw": max_price,
                "stack_spread_eur_per_maw": max_price - min_price,
                "source_offer_rows": int(len(group)),
                "max_offer_quantity_maw": float(group["quantity_maw"].max()),
                "quantity_weighting_method": "step_weighted_quantile_by_accepted_quantity",
                "source_dataset": "12_3_F_NL_IR",
                "source_data_version": "cleaned_offer_long_crosschecked_daily_v1",
                "known_at_rule": "observed_ex_post_accepted_offer_data_not_forecast_safe",
                "coverage_flags": "",
                "calibration_split": (
                    "calibration" if delivery_date <= CALIBRATION_END else "evaluation"
                ),
                "methodological_caveat": "accepted_offers_only_rejected_bids_unobserved_threshold_proxy_not_full_bid_ladder",
            }
        )

    result = pd.DataFrame.from_records(records).sort_values(["delivery_date_local", "direction"]).reset_index(drop=True)
    return result


def crosscheck_with_daily(result: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    mapped = daily.rename(
        columns={
            "offer_count": "daily_offer_count",
            "total_quantity_maw": "daily_total_quantity_maw",
            "quantity_weighted_price_eur_per_maw": "daily_quantity_weighted_price_eur_per_maw",
            "source_offer_rows": "daily_source_offer_rows",
        }
    )[
        [
            "delivery_date_local",
            "direction",
            "daily_offer_count",
            "daily_total_quantity_maw",
            "daily_quantity_weighted_price_eur_per_maw",
            "daily_source_offer_rows",
        ]
    ]
    merged = result.merge(mapped, on=["delivery_date_local", "direction"], how="left", validate="one_to_one")

    if merged["daily_offer_count"].isna().any():
        missing = merged.loc[merged["daily_offer_count"].isna(), ["delivery_date_local", "direction"]]
        raise ValueError(f"Daily cross-check coverage is missing rows: {missing.head(5).to_dict('records')}")

    merged["weighted_price_abs_diff"] = (
        merged["weighted_accepted_price_eur_per_maw"] - merged["daily_quantity_weighted_price_eur_per_maw"]
    ).abs()
    merged["quantity_sum_abs_diff"] = (
        merged["accepted_quantity_sum_maw"] - merged["daily_total_quantity_maw"]
    ).abs()
    merged["weighted_price_crosscheck_ok"] = merged["weighted_price_abs_diff"] <= WEIGHTED_PRICE_TOLERANCE
    merged["offer_count_crosscheck_ok"] = merged["accepted_offer_count"] == merged["daily_offer_count"]
    merged["quantity_sum_crosscheck_ok"] = merged["quantity_sum_abs_diff"] <= WEIGHTED_PRICE_TOLERANCE

    if not merged["weighted_price_crosscheck_ok"].all():
        bad = merged.loc[~merged["weighted_price_crosscheck_ok"], ["delivery_date_local", "direction", "weighted_price_abs_diff"]]
        raise ValueError(f"Weighted price cross-check failed: {bad.head(5).to_dict('records')}")
    if not merged["offer_count_crosscheck_ok"].all():
        bad = merged.loc[~merged["offer_count_crosscheck_ok"], ["delivery_date_local", "direction", "accepted_offer_count", "daily_offer_count"]]
        raise ValueError(f"Offer count cross-check failed: {bad.head(5).to_dict('records')}")
    if not merged["quantity_sum_crosscheck_ok"].all():
        bad = merged.loc[~merged["quantity_sum_crosscheck_ok"], ["delivery_date_local", "direction", "quantity_sum_abs_diff"]]
        raise ValueError(f"Quantity sum cross-check failed: {bad.head(5).to_dict('records')}")

    merged["coverage_flags"] = merged.apply(build_coverage_flag, axis=1)
    return merged


def validate_output(output: pd.DataFrame) -> dict[str, object]:
    expected_dates = pd.date_range(START_DATE, END_DATE, freq="D")
    expected_rows = len(expected_dates) * 2
    split_counts = output["calibration_split"].value_counts().to_dict()
    flag_counts = output["coverage_flags"].value_counts().to_dict()

    checks = {
        "row_count": len(output),
        "expected_rows": expected_rows,
        "date_min": output["delivery_date_local"].min().strftime("%Y-%m-%d"),
        "date_max": output["delivery_date_local"].max().strftime("%Y-%m-%d"),
        "split_counts": split_counts,
        "flag_counts": flag_counts,
    }

    assert len(output) == expected_rows
    assert output["delivery_date_local"].min() == START_DATE
    assert output["delivery_date_local"].max() == END_DATE
    assert output["delivery_date_local"].duplicated().sum() != len(output)
    assert output.duplicated(["delivery_date_local", "direction"]).sum() == 0
    assert set(output["direction"].unique()) == {"Up", "Down"}
    assert output.groupby("delivery_date_local")["direction"].nunique().eq(2).all()
    assert set(output["calibration_split"].unique()) == {"calibration", "evaluation"}
    assert (output.loc[output["delivery_date_local"] <= CALIBRATION_END, "calibration_split"] == "calibration").all()
    assert (output.loc[output["delivery_date_local"] > CALIBRATION_END, "calibration_split"] == "evaluation").all()
    assert (output["delivery_block_id"] == "daily_full_day").all()
    assert (output["granularity"] == "daily").all()
    assert (output["market_design_regime"] == "nl_ir_daily_capacity_threshold_proxy_v1").all()
    assert (output["accepted_offer_count"] > 0).all()
    assert (output["accepted_quantity_sum_maw"] > 0).all()

    price_cols = [
        "weighted_accepted_price_eur_per_maw",
        "accepted_price_p10_eur_per_maw",
        "accepted_price_p25_eur_per_maw",
        "accepted_price_p50_eur_per_maw",
        "accepted_price_p75_eur_per_maw",
        "accepted_price_p90_eur_per_maw",
        "min_accepted_price_eur_per_maw",
        "max_accepted_price_proxy_eur_per_maw",
    ]
    assert (output[price_cols] > 0).all().all()
    assert (output["weighted_accepted_price_eur_per_maw"] >= output["min_accepted_price_eur_per_maw"] - VALIDATION_EPSILON).all()
    assert (output["weighted_accepted_price_eur_per_maw"] <= output["max_accepted_price_proxy_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert (output["accepted_price_p10_eur_per_maw"] <= output["accepted_price_p25_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert (output["accepted_price_p25_eur_per_maw"] <= output["accepted_price_p50_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert (output["accepted_price_p50_eur_per_maw"] <= output["accepted_price_p75_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert (output["accepted_price_p75_eur_per_maw"] <= output["accepted_price_p90_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert (output["min_accepted_price_eur_per_maw"] <= output["accepted_price_p10_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert (output["accepted_price_p90_eur_per_maw"] <= output["max_accepted_price_proxy_eur_per_maw"] + VALIDATION_EPSILON).all()
    assert np.allclose(
        output["stack_spread_eur_per_maw"],
        output["max_accepted_price_proxy_eur_per_maw"] - output["min_accepted_price_eur_per_maw"],
    )
    assert output["methodological_caveat"].notna().all()
    assert output["known_at_rule"].eq("observed_ex_post_accepted_offer_data_not_forecast_safe").all()

    return checks


def main() -> None:
    offer = load_offer_data()
    daily = load_daily_crosscheck()
    result = aggregate_observed_thresholds(offer)
    result = crosscheck_with_daily(result, daily)

    keep_cols = [
        "delivery_date_local",
        "direction",
        "delivery_start_utc",
        "delivery_end_utc",
        "delivery_block_id",
        "granularity",
        "market_design_regime",
        "accepted_offer_count",
        "accepted_quantity_sum_maw",
        "weighted_accepted_price_eur_per_maw",
        "accepted_price_p10_eur_per_maw",
        "accepted_price_p25_eur_per_maw",
        "accepted_price_p50_eur_per_maw",
        "accepted_price_p75_eur_per_maw",
        "accepted_price_p90_eur_per_maw",
        "min_accepted_price_eur_per_maw",
        "max_accepted_price_proxy_eur_per_maw",
        "stack_spread_eur_per_maw",
        "source_offer_rows",
        "quantity_weighting_method",
        "source_dataset",
        "source_data_version",
        "known_at_rule",
        "coverage_flags",
        "calibration_split",
        "methodological_caveat",
    ]
    output = result[keep_cols].copy()
    validate_output(output)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {len(output)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
