"""Governed electricity-price series slicing for future rolling DAM integration."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import yaml

from .s4_4c_component_ontology import load_external_supply_costs


REPO_ROOT = Path(__file__).resolve().parents[4]
PRICE_SERIES_CONTRACT_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "c5_component_ontology"
    / "c5_price_series_contract.csv"
)
DPLUS4_SOURCE_CONTRACT_PATH = (
    PRICE_SERIES_CONTRACT_PATH.parent
    / "c5_hourly_da_dplus4_forecast_source_contract.yaml"
)
DPLUS4_PRICE_SERIES_ID = "hourly_da_dplus4_point_forecast"


class PriceSeriesInterfaceError(ValueError):
    """Raised when rolling price indexing or information timing fails closed."""


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise PriceSeriesInterfaceError("Price timestamps must be timezone-aware.")
    return result.astimezone(timezone.utc)


def load_price_series_contract() -> dict[str, dict[str, str]]:
    with PRICE_SERIES_CONTRACT_PATH.open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "price_series_id",
        "market_area",
        "currency",
        "price_unit",
        "resolution_minutes",
        "forecast_realised_classification",
        "start_timestamp_utc",
        "information_availability_policy",
        "missing_price_policy",
        "settlement_status",
        "model_use_status",
    }
    if not rows or not required.issubset(rows[0]):
        raise PriceSeriesInterfaceError("Price-series contract schema is incomplete.")
    if len({row["price_series_id"] for row in rows}) != len(rows):
        raise PriceSeriesInterfaceError("Price-series IDs must be unique.")
    for row in rows:
        if int(row["resolution_minutes"]) != 60:
            raise PriceSeriesInterfaceError("Current steel interface requires hourly prices.")
        if row["price_unit"] != "EUR_per_MWh_e" or row["currency"] != "EUR":
            raise PriceSeriesInterfaceError("Electricity price currency/unit must be EUR/MWh_e.")
        if "realised" in row["forecast_realised_classification"].lower():
            raise PriceSeriesInterfaceError(
                "Realised prices are prohibited in the pre-DAM rolling interface."
            )
        _timestamp(row["start_timestamp_utc"])
    return {row["price_series_id"]: row for row in rows}


def load_dplus4_source_contract(
    path: str | Path = DPLUS4_SOURCE_CONTRACT_PATH,
) -> dict[str, Any]:
    contract_path = Path(path).resolve()
    payload = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    required = {
        "contract_id",
        "price_series_id",
        "source_run_id",
        "source_run_relative_files",
        "source_file_sha256",
        "source_file_size_bytes",
        "source_split_policy",
        "model_id",
        "feature_variant",
        "allowed_dataset_splits",
        "allowed_lead_days",
        "optimisation_price_field",
        "ex_post_outcome_field",
        "required_prediction_schema",
        "timezone_policy",
        "validation_start_origin_utc",
        "test_start_origin_utc",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise PriceSeriesInterfaceError("D+4 forecast source contract is incomplete.")
    if payload["price_series_id"] != DPLUS4_PRICE_SERIES_ID:
        raise PriceSeriesInterfaceError("D+4 source and price-series contracts disagree.")
    if payload["optimisation_price_field"] != "y_pred":
        raise PriceSeriesInterfaceError("Only y_pred may enter the optimisation interface.")
    if payload["ex_post_outcome_field"] != "y_true":
        raise PriceSeriesInterfaceError("The ex-post outcome field must remain y_true.")
    if set(payload["allowed_lead_days"]) != {0, 1, 2, 3, 4}:
        raise PriceSeriesInterfaceError("The governed forecast must contain lead days 0 through 4.")
    if payload["source_split_policy"] != "thesis_official":
        raise PriceSeriesInterfaceError("The governed source split policy must remain thesis_official.")
    required_schema = {
        "run_id", "model", "feature_variant", "dataset_split",
        "forecast_origin_utc", "forecast_origin_local", "target_timestamp_utc",
        "target_delivery_local_date", "target_hour_local", "target_known_at_utc",
        "lead_day", "y_pred", "y_true",
    }
    if set(payload["required_prediction_schema"]) != required_schema:
        raise PriceSeriesInterfaceError("The governed D+4 Parquet schema contract is incomplete.")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_dplus4_source_files(
    contract: Mapping[str, Any], forecast_run_root: str | Path | None
) -> dict[str, Path]:
    root_value = forecast_run_root or os.environ.get("STEEL_DA_FORECAST_RUN_ROOT")
    if not root_value:
        raise PriceSeriesInterfaceError(
            "D+4 forecast root must be supplied explicitly or through STEEL_DA_FORECAST_RUN_ROOT."
        )
    root = Path(root_value).resolve()
    return _resolve_dplus4_source_files_cached(
        str(root), json.dumps(dict(contract), sort_keys=True, default=str)
    )


@lru_cache(maxsize=8)
def _resolve_dplus4_source_files_cached(
    root_value: str, contract_json: str
) -> dict[str, Path]:
    contract = json.loads(contract_json)
    root = Path(root_value)
    paths = {
        key: root / str(relative)
        for key, relative in contract["source_run_relative_files"].items()
    }
    for key, path in paths.items():
        if not path.is_file():
            raise PriceSeriesInterfaceError(f"D+4 source file is missing: {key}.")
        expected_size = int(contract["source_file_size_bytes"][key])
        if path.stat().st_size != expected_size:
            raise PriceSeriesInterfaceError(
                f"D+4 source file-size mismatch for {key}: {path.stat().st_size}."
            )
        expected = str(contract["source_file_sha256"][key])
        actual = _sha256(path)
        if actual != expected:
            raise PriceSeriesInterfaceError(
                f"D+4 source fingerprint mismatch for {key}: {actual}."
            )
    summary = json.loads(paths["run_summary"].read_text(encoding="utf-8"))
    if summary.get("run_id") != contract["source_run_id"]:
        raise PriceSeriesInterfaceError("D+4 run-summary identity does not match the source contract.")
    if summary.get("requested_flags", {}).get("run_dplus4") is not True:
        raise PriceSeriesInterfaceError("D+4 source run did not request the D+4 model.")
    if summary.get("feature_variants", {}).get("dplus4") != contract["feature_variant"]:
        raise PriceSeriesInterfaceError("D+4 feature variant does not match the source contract.")
    if summary.get("split_policy") != contract["source_split_policy"]:
        raise PriceSeriesInterfaceError("D+4 run-summary split policy does not match the source contract.")
    required_stages = {"data_audit", "split_selection", "feature_build", "run_dplus4", "evaluation"}
    if any(summary.get("stages", {}).get(stage) != "completed" for stage in required_stages):
        raise PriceSeriesInterfaceError("D+4 source run is not complete.")
    return paths


def _validate_dplus4_rows(
    rows: list[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any],
    dataset_split: str,
    origin: datetime,
    expected_horizon_hours: int | None,
    price_field: str = "y_pred",
) -> list[dict[str, Any]]:
    if not rows:
        raise PriceSeriesInterfaceError("No governed D+4 forecast rows matched the replan origin.")
    required = {
        "run_id", "model", "feature_variant", "dataset_split",
        "forecast_origin_utc", "forecast_origin_local", "target_timestamp_utc",
        "target_delivery_local_date", "target_hour_local", "target_known_at_utc",
        "lead_day", price_field,
    }
    if not required.issubset(rows[0]):
        raise PriceSeriesInterfaceError("D+4 forecast schema is incomplete.")
    if dataset_split not in set(contract["allowed_dataset_splits"]):
        raise PriceSeriesInterfaceError(f"Dataset split is not governed: {dataset_split}.")
    selected: list[dict[str, Any]] = []
    for source in rows:
        if source["run_id"] != contract["source_run_id"]:
            raise PriceSeriesInterfaceError("D+4 row run identity mismatch.")
        if source["model"] != contract["model_id"]:
            raise PriceSeriesInterfaceError("D+4 row model identity mismatch.")
        if source["feature_variant"] != contract["feature_variant"]:
            raise PriceSeriesInterfaceError("D+4 row feature identity mismatch.")
        if source["dataset_split"] != dataset_split:
            raise PriceSeriesInterfaceError("D+4 row split identity mismatch.")
        row_origin = source["forecast_origin_utc"]
        if not isinstance(row_origin, datetime):
            row_origin = _timestamp(str(row_origin))
        else:
            row_origin = row_origin.astimezone(timezone.utc)
        if row_origin != origin:
            raise PriceSeriesInterfaceError("D+4 row origin mismatch.")
        delivery = source["target_timestamp_utc"]
        if not isinstance(delivery, datetime):
            delivery = _timestamp(str(delivery))
        else:
            delivery = delivery.astimezone(timezone.utc)
        information = _timestamp(str(source["target_known_at_utc"]))
        if information != origin or delivery <= origin:
            raise PriceSeriesInterfaceError("D+4 information timing is not strictly pre-delivery.")
        lead = int(source["lead_day"])
        if lead not in set(contract["allowed_lead_days"]):
            raise PriceSeriesInterfaceError("D+4 row contains an ungoverned lead day.")
        raw_price = source[price_field]
        if raw_price is None:
            raise PriceSeriesInterfaceError(
                f"D+4 {price_field} contains a missing price."
            )
        price = float(raw_price)
        if not math.isfinite(price):
            raise PriceSeriesInterfaceError(
                f"D+4 {price_field} contains a missing or non-finite price."
            )
        local = delivery.astimezone(ZoneInfo("Europe/Amsterdam"))
        if str(source["target_delivery_local_date"]) != local.date().isoformat():
            raise PriceSeriesInterfaceError("D+4 local delivery date is inconsistent with UTC.")
        if int(source["target_hour_local"]) != local.hour:
            raise PriceSeriesInterfaceError("D+4 local delivery hour is inconsistent with UTC.")
        selected.append(
            {
                "delivery": delivery,
                "information": information,
                "lead_day": lead,
                "price": price,
                "forecast_origin_local": str(source["forecast_origin_local"]),
                "target_delivery_local_date": str(source["target_delivery_local_date"]),
                "target_hour_local": int(source["target_hour_local"]),
            }
        )
    selected.sort(key=lambda row: row["delivery"])
    deliveries = [row["delivery"] for row in selected]
    if len(deliveries) != len(set(deliveries)):
        raise PriceSeriesInterfaceError("D+4 forecast has duplicate delivery timestamps.")
    if expected_horizon_hours is not None and len(selected) != expected_horizon_hours:
        raise PriceSeriesInterfaceError(
            f"D+4 forecast has {len(selected)} hours; expected {expected_horizon_hours}."
        )
    if any(later - earlier != timedelta(hours=1) for earlier, later in zip(deliveries, deliveries[1:])):
        raise PriceSeriesInterfaceError("D+4 UTC delivery timestamps are not contiguous.")
    local_dates: list[str] = []
    for row in selected:
        if row["target_delivery_local_date"] not in local_dates:
            local_dates.append(row["target_delivery_local_date"])
        if row["lead_day"] != local_dates.index(row["target_delivery_local_date"]):
            raise PriceSeriesInterfaceError("D+4 lead-day labels do not match local delivery days.")
    if len(local_dates) != 5 or {row["lead_day"] for row in selected} != {0, 1, 2, 3, 4}:
        raise PriceSeriesInterfaceError("D+4 slice must preserve exactly five local delivery days.")
    return selected


def build_dplus4_forecast_slice(
    *,
    forecast_run_root: str | Path | None,
    dataset_split: str,
    start_origin_utc: str,
    replan_index: int,
    planning_horizon_hours: int | None,
    price_override_eur_per_mwh: float | None = None,
    price_field: str = "y_pred",
    perfect_foresight_oracle: bool = False,
    source_contract_path: str | Path = DPLUS4_SOURCE_CONTRACT_PATH,
) -> list[dict[str, Any]]:
    """Load one frozen D-D+4 origin for operation or a labelled oracle.

    The default path exposes only ``y_pred``. ``y_true`` is accepted solely
    when the caller explicitly labels the solve as a perfect-foresight oracle;
    it is never a fallback for the operational forecast interface.
    """

    if replan_index < 0:
        raise PriceSeriesInterfaceError("D+4 replan index must be non-negative.")
    contract = load_dplus4_source_contract(source_contract_path)
    if price_field not in {"y_pred", "y_true"}:
        raise PriceSeriesInterfaceError(f"Unsupported D+4 price field: {price_field}.")
    if (price_field == "y_true") != bool(perfect_foresight_oracle):
        raise PriceSeriesInterfaceError(
            "D+4 y_true is permitted only in an explicitly labelled perfect-foresight oracle."
        )
    if price_override_eur_per_mwh is not None and price_field != "y_pred":
        raise PriceSeriesInterfaceError(
            "A flat validation override cannot be combined with the y_true oracle."
        )
    paths = _resolve_dplus4_source_files(contract, forecast_run_root)
    base_origin = _timestamp(start_origin_utc)
    delivery_zone = ZoneInfo("Europe/Amsterdam")
    # The governed source issues each forecast 16 hours before the first local
    # delivery-day midnight. Reconstruct origins from that local calendar
    # contract so the UTC issue hour moves across DST exactly as the source
    # does; adding fixed 24-hour UTC increments would miss spring origins.
    base_first_delivery_date = (
        base_origin + timedelta(hours=16)
    ).astimezone(delivery_zone).date()
    target_first_delivery_date = base_first_delivery_date + timedelta(
        days=replan_index
    )
    target_midnight_local = datetime.combine(
        target_first_delivery_date,
        datetime.min.time(),
        tzinfo=delivery_zone,
    )
    origin = target_midnight_local.astimezone(timezone.utc) - timedelta(
        hours=16
    )
    columns = [
        "run_id", "model", "feature_variant", "dataset_split",
        "forecast_origin_utc", "forecast_origin_local", "target_timestamp_utc",
        "target_delivery_local_date", "target_hour_local", "target_known_at_utc",
        "lead_day", price_field,
    ]
    table = pq.read_table(
        paths["predictions"], columns=columns,
        filters=[
            ("run_id", "=", contract["source_run_id"]),
            ("model", "=", contract["model_id"]),
            ("feature_variant", "=", contract["feature_variant"]),
            ("dataset_split", "=", dataset_split),
            ("forecast_origin_utc", "=", origin),
        ],
    )
    selected = _validate_dplus4_rows(
        table.to_pylist(), contract=contract, dataset_split=dataset_split,
        origin=origin, expected_horizon_hours=planning_horizon_hours,
        price_field=price_field,
    )
    if price_override_eur_per_mwh is not None and not math.isfinite(float(price_override_eur_per_mwh)):
        raise PriceSeriesInterfaceError("D+4 validation price override must be finite.")
    result: list[dict[str, Any]] = []
    for model_hour, row in enumerate(selected):
        result.append(
            {
                "model_hour": model_hour,
                "delivery_timestamp_utc": row["delivery"].isoformat(),
                "information_available_timestamp_utc": (
                    row["delivery"].isoformat()
                    if perfect_foresight_oracle
                    else row["information"].isoformat()
                ),
                "price_eur_per_mwh_e": (
                    float(price_override_eur_per_mwh)
                    if price_override_eur_per_mwh is not None
                    else row["price"]
                ),
                "market_area": contract["market_area"],
                "price_unit": contract["price_unit"],
                "forecast_realised_classification": (
                    "perfect_foresight_oracle_ex_post_truth"
                    if perfect_foresight_oracle
                    else "external_point_forecast"
                ),
                "source_run_id": contract["source_run_id"],
                "forecast_model_id": contract["model_id"],
                "feature_variant": contract["feature_variant"],
                "dataset_split": dataset_split,
                "forecast_origin_utc": origin.isoformat(),
                "forecast_origin_local": row["forecast_origin_local"],
                "target_delivery_local_date": row["target_delivery_local_date"],
                "target_hour_local": row["target_hour_local"],
                "lead_day": row["lead_day"],
                "predictions_sha256": contract["source_file_sha256"]["predictions"],
                "price_override_status": (
                    "flat_parity_validation_only"
                    if price_override_eur_per_mwh is not None
                    else "inactive"
                ),
                "optimisation_price_field": price_field,
                "perfect_foresight_oracle": perfect_foresight_oracle,
            }
        )
    return result


def dplus4_timestamp_plan(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive actual local-day execution and deadline hours from a D-D+4 slice."""

    if not rows:
        raise PriceSeriesInterfaceError("A timestamp plan requires forecast rows.")
    local_dates: list[str] = []
    counts: dict[str, int] = {}
    for row in rows:
        local_date = str(row["target_delivery_local_date"])
        if local_date not in local_dates:
            local_dates.append(local_date)
        counts[local_date] = counts.get(local_date, 0) + 1
    if len(local_dates) != 5:
        raise PriceSeriesInterfaceError(
            "A D-D+4 timestamp plan must contain exactly five local delivery days."
        )
    day_hours = [counts[local_date] for local_date in local_dates]
    if any(hours not in {23, 24, 25} for hours in day_hours):
        raise PriceSeriesInterfaceError(
            f"Unexpected local delivery-day duration: {day_hours}."
        )
    deadlines: list[int] = []
    cumulative = 0
    for hours in day_hours:
        cumulative += hours
        deadlines.append(cumulative)
    return {
        "planning_horizon_hours": cumulative,
        "execution_block_hours": day_hours[0],
        "cumulative_deadline_hours": deadlines,
        "local_delivery_dates": local_dates,
        "local_delivery_day_hours": day_hours,
    }


def _flat_price(price_id: str, scenario_id: str) -> float:
    rows = [
        row
        for row in load_external_supply_costs()
        if row["price_id"] == price_id and row["scenario_id"] == scenario_id
    ]
    if len(rows) != 1 or rows[0]["unit"] != "EUR_per_MWh_e":
        raise PriceSeriesInterfaceError(
            f"Governed flat electricity fallback is missing or incompatible: {price_id}/{scenario_id}."
        )
    return float(rows[0]["value"])


def _external_series_slice(
    path: Path,
    *,
    series_id: str,
    replan_time: datetime,
    delivery_start: datetime,
    horizon_hours: int,
) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "price_series_id",
        "delivery_timestamp_utc",
        "information_available_timestamp_utc",
        "price_eur_per_mwh_e",
        "market_area",
        "price_unit",
        "forecast_realised_classification",
    }
    if not rows or not required.issubset(rows[0]):
        raise PriceSeriesInterfaceError("External price-series schema is incomplete.")
    delivery_end = delivery_start + timedelta(hours=horizon_hours)
    eligible: dict[datetime, tuple[datetime, dict[str, str]]] = {}
    for row in rows:
        if row["price_series_id"] != series_id:
            continue
        delivery = _timestamp(row["delivery_timestamp_utc"])
        information = _timestamp(row["information_available_timestamp_utc"])
        if not delivery_start <= delivery < delivery_end or information > replan_time:
            continue
        if "realised" in row["forecast_realised_classification"].lower():
            raise PriceSeriesInterfaceError(
                "Realised-future prices cannot enter an earlier rolling decision."
            )
        if delivery not in eligible or information > eligible[delivery][0]:
            eligible[delivery] = (information, row)
    result: list[dict[str, Any]] = []
    for hour in range(horizon_hours):
        delivery = delivery_start + timedelta(hours=hour)
        if delivery not in eligible:
            raise PriceSeriesInterfaceError(
                f"Missing eligible price for {delivery.isoformat()}."
            )
        information, row = eligible[delivery]
        result.append(
            {
                "model_hour": hour,
                "delivery_timestamp_utc": delivery.isoformat(),
                "information_available_timestamp_utc": information.isoformat(),
                "price_eur_per_mwh_e": float(row["price_eur_per_mwh_e"]),
                "market_area": row["market_area"],
                "price_unit": row["price_unit"],
                "forecast_realised_classification": row[
                    "forecast_realised_classification"
                ],
            }
        )
    return result


def build_rolling_price_slice(
    *,
    price_series_id: str,
    replan_index: int,
    planning_horizon_hours: int,
    execution_block_hours: int,
    flat_scenario_id: str | None = None,
    external_series_path: str | Path | None = None,
    forecast_run_root: str | Path | None = None,
    forecast_dataset_split: str | None = None,
    forecast_start_origin_utc: str | None = None,
    forecast_price_override_eur_per_mwh: float | None = None,
    forecast_price_field: str = "y_pred",
    perfect_foresight_oracle: bool = False,
) -> list[dict[str, Any]]:
    """Return one information-safe hourly price slice for a rolling replan."""

    contracts = load_price_series_contract()
    if price_series_id not in contracts:
        raise PriceSeriesInterfaceError(f"Unknown price_series_id: {price_series_id}")
    contract = contracts[price_series_id]
    if replan_index < 0 or planning_horizon_hours <= 0 or execution_block_hours <= 0:
        raise PriceSeriesInterfaceError("Rolling price-slice indices must be positive.")
    series_start = _timestamp(contract["start_timestamp_utc"])
    replan_time = series_start + timedelta(hours=replan_index * execution_block_hours)
    delivery_start = replan_time
    if price_series_id == DPLUS4_PRICE_SERIES_ID:
        if not forecast_dataset_split or not forecast_start_origin_utc:
            raise PriceSeriesInterfaceError(
                "D+4 forecast requires dataset split and frozen start origin."
            )
        rows = build_dplus4_forecast_slice(
            forecast_run_root=forecast_run_root,
            dataset_split=forecast_dataset_split,
            start_origin_utc=forecast_start_origin_utc,
            replan_index=replan_index,
            planning_horizon_hours=planning_horizon_hours,
            price_override_eur_per_mwh=forecast_price_override_eur_per_mwh,
            price_field=forecast_price_field,
            perfect_foresight_oracle=perfect_foresight_oracle,
        )
        replan_time = _timestamp(rows[0]["forecast_origin_utc"])
        delivery_start = _timestamp(rows[0]["delivery_timestamp_utc"])
    elif external_series_path is not None:
        rows = _external_series_slice(
            Path(external_series_path).resolve(),
            series_id=price_series_id,
            replan_time=replan_time,
            delivery_start=delivery_start,
            horizon_hours=planning_horizon_hours,
        )
    else:
        scenario = flat_scenario_id or contract["flat_fallback_scenario_id"]
        base_price = _flat_price(contract["flat_fallback_price_id"], scenario)
        issue_time = (
            series_start - timedelta(hours=24)
            if price_series_id == "flat_central_reference_v1"
            else replan_time - timedelta(seconds=1)
        )
        rows = []
        for hour in range(planning_horizon_hours):
            delivery = delivery_start + timedelta(hours=hour)
            price = base_price
            if price_series_id == "synthetic_indexing_test_v1":
                delivery_hour = delivery.hour
                price += -20.0 if delivery_hour < 6 else 20.0 if 17 <= delivery_hour < 21 else 0.0
            elif price_series_id == "synthetic_vn25_break_even_step_v1":
                # Governed synthetic validation only: both levels are known
                # before the replan, and straddle 55/0.345 = 159.42 EUR/MWh_e.
                price = 100.0 if delivery.hour < 12 else 220.0
            rows.append(
                {
                    "model_hour": hour,
                    "delivery_timestamp_utc": delivery.isoformat(),
                    "information_available_timestamp_utc": issue_time.isoformat(),
                    "price_eur_per_mwh_e": price,
                    "market_area": contract["market_area"],
                    "price_unit": contract["price_unit"],
                    "forecast_realised_classification": contract[
                        "forecast_realised_classification"
                    ],
                }
            )
    if len(rows) != planning_horizon_hours:
        raise PriceSeriesInterfaceError("Price slice does not cover the planning horizon.")
    for expected_hour, row in enumerate(rows):
        if int(row["model_hour"]) != expected_hour:
            raise PriceSeriesInterfaceError("Price slice model-hour indexing is not contiguous.")
        delivery = _timestamp(str(row["delivery_timestamp_utc"]))
        information = _timestamp(str(row["information_available_timestamp_utc"]))
        expected_delivery = delivery_start + timedelta(hours=expected_hour)
        if delivery != expected_delivery:
            raise PriceSeriesInterfaceError("Price timestamps do not align with model timesteps.")
        if information > replan_time and not perfect_foresight_oracle:
            raise PriceSeriesInterfaceError(
                "Future information leaked into an earlier rolling decision."
            )
    return [
        {
            "price_series_id": price_series_id,
            "replan_index": replan_index,
            "replan_timestamp_utc": replan_time.isoformat(),
            "resolution_minutes": 60,
            "currency": "EUR",
            "missing_price_policy": contract["missing_price_policy"],
            "settlement_status": contract["settlement_status"],
            **row,
        }
        for row in rows
    ]
