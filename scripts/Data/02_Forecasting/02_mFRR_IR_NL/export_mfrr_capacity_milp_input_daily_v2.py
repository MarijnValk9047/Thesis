from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[4]
ROOT = PROJECT_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity"
SCENARIO_PATH = ROOT / "nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv"
NAIVE_PATH = ROOT / "nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv"
XGB_PATH = ROOT / "nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv"
LEAR_PATH = ROOT / "nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv"
V1_EXPORT_PATH = ROOT / "milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v1.csv"
OUTPUT_DIR = ROOT / "milp_exports"
OUTPUT_PATH = OUTPUT_DIR / "nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv"

MARKET = "NL_incident_reserve"
PRODUCT = "mFRRda_capacity"
BIDDING_STAGE = "capacity_auction_D_minus_1_09am"
KNOWN_AT_ASSUMPTION = "assumed_nl_incident_reserve_capacity_auction_d_minus_1_09am_europe_amsterdam"
CAPACITY_PRODUCT_STRUCTURE = "observed_daily"
CAPACITY_PRICE_UNIT = "EUR_per_MW_per_ISP"
EXPORT_VERSION = "nl_ir_capacity_milp_input_daily_direction_scenarios_v2"
ACCEPTANCE_RULE = "bid_price_eur_per_mw_isp_less_or_equal_acceptance_threshold_price_eur_per_mw_isp"
REVENUE_RULE = "accepted_times_bid_price_eur_per_mw_isp_times_offered_capacity_mw_times_contract_isp_count"
AVAILABILITY_NOTE = (
    "accepted_capacity_requires_deliverable_up_or_down_flexibility_across_contract_period_energy_bid_obligation_"
    "preserved_activation_deferred"
)
REVENUE_EXAMPLE_BID_PRICE = 2.22
REVENUE_EXAMPLE_CAPACITY_MW = 35.0
REVENUE_EXAMPLE_ISP_COUNT = 96
REVENUE_EXAMPLE_TOTAL_EUR = 7459.20
REVENUE_EXAMPLE_ONE_ISP_ONLY_EUR = 77.70

EXPECTED_SCENARIO_IDS = [
    "threshold_central_p90",
    "threshold_conservative_p75",
    "threshold_optimistic_max",
]
EXPECTED_DIRECTIONS = ["Down", "Up"]
EXPECTED_ROWS = 2190
TEST_START = "2024-10-01"
TEST_END = "2025-09-30"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
UTC = timezone.utc

SCENARIO_REQUIRED_COLUMNS = [
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
FORECAST_REQUIRED_COLUMNS = [
    "forecast_origin_utc",
    "forecast_origin_local",
    "known_at_cutoff_utc",
    "delivery_start_utc",
    "delivery_end_utc",
    "delivery_date_local",
    "delivery_block_id",
    "direction",
    "model_name",
    "point_forecast",
    "dataset_split",
]
V1_REQUIRED_COLUMNS = [
    "delivery_date_local",
    "direction",
    "scenario_id",
    "acceptance_threshold_price",
]
OUTPUT_COLUMNS = [
    "market",
    "product",
    "bidding_stage",
    "forecast_origin_utc",
    "forecast_origin_local",
    "known_at_cutoff_utc",
    "known_at_assumption",
    "delivery_date_local",
    "delivery_block_id",
    "granularity",
    "direction",
    "scenario_id",
    "scenario_role",
    "scenario_probability",
    "delivery_start_local",
    "delivery_end_local",
    "delivery_start_utc",
    "delivery_end_utc",
    "contract_isp_count",
    "capacity_product_structure",
    "capacity_price_unit",
    "acceptance_threshold_price_eur_per_mw_isp",
    "threshold_proxy_name",
    "threshold_model_name",
    "threshold_source_scope",
    "threshold_observed_overlap_flag",
    "average_price_forecast_threshold_anchor",
    "average_price_model_threshold_anchor",
    "average_price_forecast_primary",
    "average_price_model_primary",
    "average_price_forecast_comparator",
    "average_price_model_comparator",
    "scenario_generation_method",
    "market_design_regime",
    "source_data_version",
    "export_version",
    "methodological_caveat",
    "quality_flags",
    "capacity_bid_price_is_decision_variable",
    "acceptance_rule_proxy",
    "capacity_revenue_rule_proxy",
    "energy_bid_obligation_if_accepted",
    "activation_modelling_in_scope",
    "mari_modelling_in_scope",
    "availability_obligation_note",
]


def require_columns(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}")


def load_csv(path: Path, required: list[str], label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {path}")
    df = pd.read_csv(path)
    require_columns(df, required, label)
    return df


def prepare_forecast_reference(path: Path, expected_model_name: str, label: str) -> pd.DataFrame:
    df = load_csv(path, FORECAST_REQUIRED_COLUMNS, label)
    df = df[df["dataset_split"] == "test"].copy()
    if df.empty:
        raise ValueError(f"{label} contains no test rows.")
    model_names = sorted(df["model_name"].dropna().unique().tolist())
    if model_names != [expected_model_name]:
        raise ValueError(f"{label} has unexpected model names: {model_names}")
    duplicate_keys = int(df.duplicated(["delivery_date_local", "direction"]).sum())
    if duplicate_keys:
        raise ValueError(f"{label} has duplicate delivery_date_local x direction keys.")
    return df[["delivery_date_local", "direction", "model_name", "point_forecast"]].rename(
        columns={
            "model_name": f"{label}_model_name",
            "point_forecast": f"{label}_point_forecast",
        }
    )


def validate_repaired_timing(df: pd.DataFrame, label: str) -> None:
    for row in df.itertuples(index=False):
        delivery_date = datetime.strptime(str(row.delivery_date_local), "%Y-%m-%d").date()
        expected_local = datetime.combine(delivery_date - timedelta(days=1), time(9, 0), tzinfo=AMSTERDAM)
        expected_utc = expected_local.astimezone(UTC)
        parsed_local = datetime.fromisoformat(str(row.forecast_origin_local))
        parsed_cutoff_utc = datetime.fromisoformat(str(row.known_at_cutoff_utc).replace("Z", "+00:00"))
        if parsed_local != expected_local:
            raise ValueError(f"{label}: forecast_origin_local mismatch for {row.delivery_date_local} {row.direction}")
        if parsed_cutoff_utc != expected_utc:
            raise ValueError(f"{label}: known_at_cutoff_utc mismatch for {row.delivery_date_local} {row.direction}")


def parse_utc_series(series: pd.Series, label: str) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True)
    if parsed.isna().any():
        raise ValueError(f"{label} contains invalid UTC timestamps.")
    return parsed


def as_iso8601(series: pd.Series, tz: ZoneInfo | timezone) -> pd.Series:
    converted = series.dt.tz_convert(tz)
    return converted.map(lambda ts: ts.isoformat())


def compute_contract_isp_count(delivery_start_utc: pd.Series, delivery_end_utc: pd.Series) -> pd.Series:
    duration = (delivery_end_utc - delivery_start_utc) / pd.Timedelta(minutes=15)
    rounded = duration.round().astype("Int64")
    if rounded.isna().any():
        raise ValueError("contract_isp_count computation produced missing values.")
    if not duration.round(12).eq(rounded.astype(float)).all():
        raise ValueError("delivery interval duration is not an integer number of 15-minute ISPs.")
    if (rounded <= 0).any():
        raise ValueError("contract_isp_count must be strictly positive.")
    return rounded.astype(int)


def validate_example_revenue_rule() -> None:
    total = round(REVENUE_EXAMPLE_BID_PRICE * REVENUE_EXAMPLE_CAPACITY_MW * REVENUE_EXAMPLE_ISP_COUNT, 2)
    one_isp_only = round(REVENUE_EXAMPLE_BID_PRICE * REVENUE_EXAMPLE_CAPACITY_MW, 2)
    if total != REVENUE_EXAMPLE_TOTAL_EUR:
        raise ValueError("Revenue example total is inconsistent with the documented ISP-scaled rule.")
    if one_isp_only != REVENUE_EXAMPLE_ONE_ISP_ONLY_EUR:
        raise ValueError("Revenue example one-ISP value is inconsistent with the documented cautionary example.")


def build_export() -> tuple[pd.DataFrame, dict[str, Any]]:
    validate_example_revenue_rule()

    scenario = load_csv(SCENARIO_PATH, SCENARIO_REQUIRED_COLUMNS, "Scenario artifact")
    validate_repaired_timing(scenario, "Scenario artifact")

    if len(scenario) != EXPECTED_ROWS:
        raise ValueError(f"Scenario artifact row count mismatch: {len(scenario)} != {EXPECTED_ROWS}")
    if sorted(scenario["direction"].dropna().unique().tolist()) != EXPECTED_DIRECTIONS:
        raise ValueError("Scenario artifact has unexpected directions.")
    if sorted(scenario["scenario_id"].dropna().unique().tolist()) != EXPECTED_SCENARIO_IDS:
        raise ValueError("Scenario artifact has unexpected scenario IDs.")
    if int(scenario.duplicated(["delivery_date_local", "direction", "scenario_id"]).sum()) != 0:
        raise ValueError("Scenario artifact has duplicate delivery_date_local x direction x scenario_id keys.")

    naive = prepare_forecast_reference(NAIVE_PATH, "naive_lag_7d_same_direction", "naive")
    xgb = prepare_forecast_reference(XGB_PATH, "xgboost_exogenous_small_da_aligned_daily_v1", "primary")
    lear = prepare_forecast_reference(LEAR_PATH, "lear_exogenous_small_da_aligned_daily_v1", "comparator")

    expected_ref_rows = 730
    for name, df in [("naive", naive), ("primary", xgb), ("comparator", lear)]:
        if len(df) != expected_ref_rows:
            raise ValueError(f"{name} forecast reference row count mismatch: {len(df)} != {expected_ref_rows}")

    merged = scenario.merge(
        naive,
        on=["delivery_date_local", "direction"],
        how="left",
        validate="many_to_one",
    )
    merged = merged.merge(
        xgb,
        on=["delivery_date_local", "direction"],
        how="left",
        validate="many_to_one",
    )
    merged = merged.merge(
        lear,
        on=["delivery_date_local", "direction"],
        how="left",
        validate="many_to_one",
    )

    if merged[["naive_point_forecast", "primary_point_forecast", "comparator_point_forecast"]].isna().any().any():
        raise ValueError("Average-price reference joins are incomplete.")

    anchor_match = merged["average_price_forecast"].round(12).eq(merged["naive_point_forecast"].round(12)).all()
    if not anchor_match:
        raise ValueError("Scenario threshold anchor forecast does not match repaired Naive7d forecast artifact.")

    delivery_start_utc = parse_utc_series(merged["delivery_start_utc"], "delivery_start_utc")
    delivery_end_utc = parse_utc_series(merged["delivery_end_utc"], "delivery_end_utc")
    contract_isp_count = compute_contract_isp_count(delivery_start_utc, delivery_end_utc)

    export = pd.DataFrame(
        {
            "market": MARKET,
            "product": PRODUCT,
            "bidding_stage": BIDDING_STAGE,
            "forecast_origin_utc": merged["forecast_origin_utc"],
            "forecast_origin_local": merged["forecast_origin_local"],
            "known_at_cutoff_utc": merged["known_at_cutoff_utc"],
            "known_at_assumption": KNOWN_AT_ASSUMPTION,
            "delivery_date_local": merged["delivery_date_local"],
            "delivery_block_id": merged["delivery_block_id"],
            "granularity": merged["granularity"],
            "direction": merged["direction"],
            "scenario_id": merged["scenario_id"],
            "scenario_role": merged["scenario_role"],
            "scenario_probability": merged["scenario_probability"],
            "delivery_start_local": as_iso8601(delivery_start_utc, AMSTERDAM),
            "delivery_end_local": as_iso8601(delivery_end_utc, AMSTERDAM),
            "delivery_start_utc": as_iso8601(delivery_start_utc, UTC),
            "delivery_end_utc": as_iso8601(delivery_end_utc, UTC),
            "contract_isp_count": contract_isp_count,
            "capacity_product_structure": CAPACITY_PRODUCT_STRUCTURE,
            "capacity_price_unit": CAPACITY_PRICE_UNIT,
            "acceptance_threshold_price_eur_per_mw_isp": merged["threshold_price_scenario"],
            "threshold_proxy_name": merged["threshold_proxy_name"],
            "threshold_model_name": merged["threshold_model_name"],
            "threshold_source_scope": merged["threshold_source_scope"],
            "threshold_observed_overlap_flag": merged["threshold_observed_overlap_flag"],
            "average_price_forecast_threshold_anchor": merged["average_price_forecast"],
            "average_price_model_threshold_anchor": merged["average_price_model_name"],
            "average_price_forecast_primary": merged["primary_point_forecast"],
            "average_price_model_primary": merged["primary_model_name"],
            "average_price_forecast_comparator": merged["comparator_point_forecast"],
            "average_price_model_comparator": merged["comparator_model_name"],
            "scenario_generation_method": merged["scenario_generation_method"],
            "market_design_regime": merged["market_design_regime"],
            "source_data_version": merged["source_data_version"],
            "export_version": EXPORT_VERSION,
            "methodological_caveat": merged["methodological_caveat"],
            "quality_flags": merged["quality_flags"],
            "capacity_bid_price_is_decision_variable": True,
            "acceptance_rule_proxy": ACCEPTANCE_RULE,
            "capacity_revenue_rule_proxy": REVENUE_RULE,
            "energy_bid_obligation_if_accepted": True,
            "activation_modelling_in_scope": False,
            "mari_modelling_in_scope": False,
            "availability_obligation_note": AVAILABILITY_NOTE,
        }
    )

    export = export[OUTPUT_COLUMNS]
    contract_isp_count_counts = export["contract_isp_count"].value_counts().sort_index().to_dict()

    summary = {
        "row_count": int(len(export)),
        "date_range": (
            str(pd.to_datetime(export["delivery_date_local"]).min().date()),
            str(pd.to_datetime(export["delivery_date_local"]).max().date()),
        ),
        "scenario_ids": sorted(export["scenario_id"].dropna().unique().tolist()),
        "directions": sorted(export["direction"].dropna().unique().tolist()),
        "contract_isp_count_counts": {int(k): int(v) for k, v in contract_isp_count_counts.items()},
        "primary_model_name": sorted(export["average_price_model_primary"].dropna().unique().tolist()),
        "comparator_model_name": sorted(export["average_price_model_comparator"].dropna().unique().tolist()),
        "threshold_anchor_model_name": sorted(
            export["average_price_model_threshold_anchor"].dropna().unique().tolist()
        ),
    }
    return export, summary


def validate_export(export: pd.DataFrame) -> dict[str, Any]:
    issues: list[str] = []
    if len(export) != EXPECTED_ROWS:
        issues.append("unexpected_row_count")
    if export.columns.tolist() != OUTPUT_COLUMNS:
        issues.append("unexpected_output_schema")
    date_min = str(pd.to_datetime(export["delivery_date_local"]).min().date())
    date_max = str(pd.to_datetime(export["delivery_date_local"]).max().date())
    if (date_min, date_max) != (TEST_START, TEST_END):
        issues.append("unexpected_date_range")
    if sorted(export["direction"].dropna().unique().tolist()) != EXPECTED_DIRECTIONS:
        issues.append("unexpected_directions")
    if sorted(export["scenario_id"].dropna().unique().tolist()) != EXPECTED_SCENARIO_IDS:
        issues.append("unexpected_scenario_ids")
    if int(export.duplicated(["delivery_date_local", "direction", "scenario_id"]).sum()) != 0:
        issues.append("duplicate_keys")

    scenario_counts = export.groupby(["delivery_date_local", "direction"]).size()
    if not scenario_counts.eq(3).all():
        issues.append("scenario_count_per_key_mismatch")
    prob_sums = export.groupby(["delivery_date_local", "direction"], as_index=False)["scenario_probability"].sum()
    if not prob_sums["scenario_probability"].round(12).eq(1.0).all():
        issues.append("scenario_probability_sum_mismatch")

    validate_repaired_timing(export, "MILP export")
    if export["forecast_origin_local"].astype(str).str.contains("T10:00:00").any():
        issues.append("active_10am_timing_present")
    if sorted(export["known_at_assumption"].dropna().unique().tolist()) != [KNOWN_AT_ASSUMPTION]:
        issues.append("known_at_assumption_mismatch")
    if sorted(export["capacity_product_structure"].dropna().unique().tolist()) != [CAPACITY_PRODUCT_STRUCTURE]:
        issues.append("capacity_product_structure_mismatch")
    if sorted(export["capacity_price_unit"].dropna().unique().tolist()) != [CAPACITY_PRICE_UNIT]:
        issues.append("capacity_price_unit_mismatch")
    if sorted(export["energy_bid_obligation_if_accepted"].dropna().unique().tolist()) != [True]:
        issues.append("energy_bid_obligation_flag_mismatch")
    if sorted(export["activation_modelling_in_scope"].dropna().unique().tolist()) != [False]:
        issues.append("activation_scope_mismatch")
    if sorted(export["mari_modelling_in_scope"].dropna().unique().tolist()) != [False]:
        issues.append("mari_scope_mismatch")
    if any("per_period" in column.lower() for column in export.columns):
        issues.append("ambiguous_per_period_column_present")

    if sorted(export["product"].dropna().unique().tolist()) != [PRODUCT]:
        issues.append("unexpected_product")
    if sorted(export["market"].dropna().unique().tolist()) != [MARKET]:
        issues.append("unexpected_market")
    if sorted(export["bidding_stage"].dropna().unique().tolist()) != [BIDDING_STAGE]:
        issues.append("unexpected_bidding_stage")
    if export["contract_isp_count"].isna().any():
        issues.append("missing_contract_isp_count")
    unique_contract_isp_count = sorted(export["contract_isp_count"].dropna().unique().tolist())
    if not all(isinstance(value, int) for value in unique_contract_isp_count):
        issues.append("non_integer_contract_isp_count")

    required_non_missing = [
        "acceptance_threshold_price_eur_per_mw_isp",
        "delivery_start_local",
        "delivery_end_local",
        "delivery_start_utc",
        "delivery_end_utc",
        "average_price_forecast_threshold_anchor",
        "average_price_model_threshold_anchor",
        "average_price_forecast_primary",
        "average_price_model_primary",
        "average_price_forecast_comparator",
        "average_price_model_comparator",
        "threshold_proxy_name",
        "threshold_model_name",
        "threshold_source_scope",
        "threshold_observed_overlap_flag",
        "scenario_generation_method",
        "methodological_caveat",
    ]
    for column in required_non_missing:
        if export[column].isna().any():
            issues.append(f"missing_{column}")

    scenario_source = load_csv(SCENARIO_PATH, SCENARIO_REQUIRED_COLUMNS, "Scenario artifact")
    comparison = export.merge(
        scenario_source[
            [
                "delivery_date_local",
                "direction",
                "scenario_id",
                "scenario_probability",
                "threshold_proxy_name",
                "threshold_model_name",
                "threshold_source_scope",
                "threshold_observed_overlap_flag",
                "scenario_generation_method",
                "methodological_caveat",
                "threshold_price_scenario",
                "average_price_forecast",
                "average_price_model_name",
            ]
        ],
        on=["delivery_date_local", "direction", "scenario_id"],
        how="left",
        validate="one_to_one",
        suffixes=("_export", "_source"),
    )
    if not comparison["acceptance_threshold_price_eur_per_mw_isp"].round(12).equals(
        comparison["threshold_price_scenario"].round(12)
    ):
        issues.append("threshold_value_not_preserved")
    if not comparison["average_price_forecast_threshold_anchor"].round(12).equals(
        comparison["average_price_forecast"].round(12)
    ):
        issues.append("threshold_anchor_forecast_not_preserved")
    if not comparison["average_price_model_threshold_anchor"].equals(comparison["average_price_model_name"]):
        issues.append("threshold_anchor_model_not_preserved")
    preserved_equal_columns = [
        "scenario_probability",
        "threshold_proxy_name",
        "threshold_model_name",
        "threshold_source_scope",
        "threshold_observed_overlap_flag",
        "scenario_generation_method",
        "methodological_caveat",
    ]
    for column in preserved_equal_columns:
        if not comparison[f"{column}_export"].equals(comparison[f"{column}_source"]):
            issues.append(f"{column}_not_preserved")

    delivery_start_utc = parse_utc_series(export["delivery_start_utc"], "delivery_start_utc")
    delivery_end_utc = parse_utc_series(export["delivery_end_utc"], "delivery_end_utc")
    recomputed_contract_isp_count = compute_contract_isp_count(delivery_start_utc, delivery_end_utc)
    if not recomputed_contract_isp_count.equals(export["contract_isp_count"]):
        issues.append("contract_isp_count_not_derived_from_delivery_interval")

    v1 = load_csv(V1_EXPORT_PATH, V1_REQUIRED_COLUMNS, "v1 export")
    if len(v1) != len(export):
        issues.append("v1_v2_row_count_mismatch")
    if sorted(v1["direction"].dropna().unique().tolist()) != sorted(export["direction"].dropna().unique().tolist()):
        issues.append("v1_v2_direction_mismatch")
    if sorted(v1["scenario_id"].dropna().unique().tolist()) != sorted(export["scenario_id"].dropna().unique().tolist()):
        issues.append("v1_v2_scenario_id_mismatch")
    v1_comparison = export.merge(
        v1[["delivery_date_local", "direction", "scenario_id", "acceptance_threshold_price"]],
        on=["delivery_date_local", "direction", "scenario_id"],
        how="left",
        validate="one_to_one",
    )
    if not v1_comparison["acceptance_threshold_price_eur_per_mw_isp"].round(12).equals(
        v1_comparison["acceptance_threshold_price"].round(12)
    ):
        issues.append("v1_threshold_values_not_preserved")

    if "y_true" in export.columns:
        issues.append("observed_truth_present")

    return {
        "issues": issues,
        "row_count": int(len(export)),
        "date_range": (date_min, date_max),
        "scenario_counts_per_key_unique": sorted(scenario_counts.unique().tolist()),
        "scenario_probability_values": sorted(export["scenario_probability"].dropna().unique().tolist()),
        "contract_isp_count_values": unique_contract_isp_count,
        "contract_isp_count_counts": {
            int(k): int(v) for k, v in export["contract_isp_count"].value_counts().sort_index().to_dict().items()
        },
        "timing_assumption": KNOWN_AT_ASSUMPTION,
        "example_revenue_total_eur": REVENUE_EXAMPLE_TOTAL_EUR,
        "example_one_isp_only_eur": REVENUE_EXAMPLE_ONE_ISP_ONLY_EUR,
    }


def main() -> None:
    export, summary = build_export()
    validation = validate_export(export)
    if validation["issues"]:
        raise ValueError(validation)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    export.to_csv(OUTPUT_PATH, index=False)
    print({"summary": summary, "validation": validation, "output_path": str(OUTPUT_PATH)})


if __name__ == "__main__":
    main()
