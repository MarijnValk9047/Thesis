"""Native-QH annual input contract for deterministic C0/C1 execution.

This adapter deliberately shares the annual physical builder and state
contracts with the hourly path.  It owns only the QH calendar/price boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from .s4_4c6_deterministic_hourly_temporal_validation import (
    C0_ANNUAL_QH_CONTRACT_VERSION,
    C1_ANNUAL_QH_CONTRACT_VERSION,
    HourlyTemporalValidationError,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


CONFIG_PATH = REPO_ROOT / (
    "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c6_deterministic_qh_full_year.yaml"
)
OUTPUT_ROOT = REPO_ROOT / (
    "data/03_Optimisation/runs/steel_c6_deterministic_qh_full_year_v1_20260807"
)
QH_CALENDAR_CONTRACT_VERSION = "lear_strict_donly_native_dst_qh_calendar_v1"
QH_PRICE_CONTRACT_VERSION = (
    "realised_hourly_anchor_plus_frozen_mean_preserving_qh_shape_v1"
)


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if config.get("mode") != "deterministic_qh_c0_c1_pi_pf_full_year":
        raise HourlyTemporalValidationError("Unexpected QH annual runner mode.")
    if config.get("calendar_contract_version") != QH_CALENDAR_CONTRACT_VERSION:
        raise HourlyTemporalValidationError("QH annual calendar contract changed.")
    if config.get("price_contract_version") != QH_PRICE_CONTRACT_VERSION:
        raise HourlyTemporalValidationError("QH annual price contract changed.")
    if config.get("scope", {}).get("full_four_week_matrix_authorized") is not False:
        raise HourlyTemporalValidationError("The QH annual runner must retain the matrix stop flag.")
    return config


def load_qh_annual_calendar_and_prices(
    config_path: Path = CONFIG_PATH,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Load and fail-close the complete native-DST QH PF ledger."""

    config = _load_config(config_path)
    bundle_path = REPO_ROOT / str(config["qh_price_bundle"]["path"])
    summary_path = REPO_ROOT / str(config["qh_price_bundle"]["summary_path"])
    if not bundle_path.exists() or not summary_path.exists():
        raise HourlyTemporalValidationError("Annual QH price bundle is incomplete.")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("calendar_contract_version") != QH_CALENDAR_CONTRACT_VERSION:
        raise HourlyTemporalValidationError("QH bundle calendar contract mismatch.")
    if summary.get("price_contract_version") != QH_PRICE_CONTRACT_VERSION:
        raise HourlyTemporalValidationError("QH bundle price contract mismatch.")
    if summary.get("classification") != config["qh_price_bundle"]["classification"]:
        raise HourlyTemporalValidationError("QH bundle classification mismatch.")
    if bool(summary.get("historical_qh_da_prices_claimed")):
        raise HourlyTemporalValidationError("Synthetic QH prices cannot be labelled historical.")
    if not all(bool(value) for value in summary.get("checks", {}).values()):
        raise HourlyTemporalValidationError("QH bundle static checks did not pass.")

    ledger = pd.read_parquet(bundle_path).copy()
    required = {
        "target_timestamp_utc", "hour_start_utc", "quarterhour_price",
        "hourly_anchor_price", "quarterhour_delta", "calendar_day_index",
        "local_date", "counterfactual", "path_kind", "scenario_id",
    }
    missing = required - set(ledger.columns)
    if missing:
        raise HourlyTemporalValidationError(f"QH price ledger lacks {sorted(missing)}.")
    ledger["target_timestamp_utc"] = pd.to_datetime(ledger["target_timestamp_utc"], utc=True)
    ledger["hour_start_utc"] = pd.to_datetime(ledger["hour_start_utc"], utc=True)
    ledger = ledger.sort_values("target_timestamp_utc").reset_index(drop=True)
    qh_times = pd.DatetimeIndex(ledger["target_timestamp_utc"])
    expected = pd.date_range(qh_times[0], periods=35_040, freq="15min", tz="UTC")
    if len(ledger) != 35_040 or not qh_times.equals(expected) or not qh_times.is_unique:
        raise HourlyTemporalValidationError("QH annual price ledger must be exactly contiguous 35,040 UTC intervals.")
    if not ledger["counterfactual"].astype(bool).all():
        raise HourlyTemporalValidationError("QH annual price ledger lost its counterfactual label.")
    if not ledger["path_kind"].eq("counterfactual_actual").all() or not ledger["scenario_id"].eq("ACTUAL").all():
        raise HourlyTemporalValidationError("PF must use only the ACTUAL counterfactual QH path.")
    day_lengths = ledger.groupby("calendar_day_index").size()
    if (len(day_lengths) != 365 or int(day_lengths.eq(92).sum()) != 1
            or int(day_lengths.eq(100).sum()) != 1 or not day_lengths.isin([92, 96, 100]).all()):
        raise HourlyTemporalValidationError("Native QH DST day contract failed.")
    means = ledger.groupby("hour_start_utc")["quarterhour_price"].mean()
    anchors = ledger.groupby("hour_start_utc")["hourly_anchor_price"].first()
    maximum = float((means - anchors).abs().max())
    tolerance = float(config["qh_price_bundle"]["mean_preservation_tolerance_eur_per_mwh"])
    if maximum > tolerance:
        raise HourlyTemporalValidationError("QH hourly-anchor mean preservation failed.")
    ledger["local_day_length_qh"] = ledger.groupby("calendar_day_index")["calendar_day_index"].transform("size")
    ledger["local_day_length_hours"] = ledger["local_day_length_qh"] / 4
    ledger["price_eur_per_mwh"] = ledger["quarterhour_price"]
    ledger["timestamp_utc"] = ledger["target_timestamp_utc"]
    ledger["granularity"] = "QH"
    return config, ledger


def qh_annual_contract_manifest(config_path: Path = CONFIG_PATH) -> Mapping[str, Any]:
    config, ledger = load_qh_annual_calendar_and_prices(config_path)
    return {
        "calendar_contract_version": QH_CALENDAR_CONTRACT_VERSION,
        "price_contract_version": QH_PRICE_CONTRACT_VERSION,
        "temporal_contract_versions": {
            "C0": C0_ANNUAL_QH_CONTRACT_VERSION,
            "C1": C1_ANNUAL_QH_CONTRACT_VERSION,
        },
        "qh_intervals": int(len(ledger)),
        "calendar_days": int(ledger["calendar_day_index"].nunique()),
        "scope": dict(config["scope"]),
        "full_four_week_matrix_authorized": False,
    }


__all__ = [
    "CONFIG_PATH", "OUTPUT_ROOT", "load_qh_annual_calendar_and_prices",
    "qh_annual_contract_manifest",
]
