from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

MARKET_TZ = "Europe/Amsterdam"
ISP_DURATION = pd.Timedelta(minutes=15)
HOUR_DURATION = pd.Timedelta(hours=1)
ALLOWED_CAPACITY_PRODUCT_STRUCTURES: tuple[str, ...] = ("observed_daily",)

RAW_REQUIRED_COLUMNS: tuple[str, ...] = (
    "branch_id",
    "forecast_origin",
    "delivery_date",
    "delivery_start",
    "delivery_end",
    "capacity_contract_block_id",
    "capacity_product_structure",
    "direction",
    "offered_capacity_mw",
    "accepted_capacity_mw",
    "accepted_flag",
    "capacity_price_eur_per_mw_isp",
    "contract_isp_count",
    "energy_bid_obligation_if_accepted",
    "activation_modelled",
)

HOURLY_REQUIRED_COLUMNS: tuple[str, ...] = (
    "delivery_timestamp",
    "accepted_up_reserve_mw_for_da",
    "accepted_down_reserve_mw_for_da",
    "reserve_obligation_active",
    "energy_bid_obligation_created",
    "branch_id",
    "capacity_contract_block_id",
)


@dataclass(frozen=True)
class CapacityResultRecord:
    branch_id: str
    forecast_origin: Any
    delivery_date: str
    delivery_start: Any
    delivery_end: Any
    capacity_contract_block_id: str
    capacity_product_structure: str
    direction: str
    offered_capacity_mw: float
    accepted_capacity_mw: float
    accepted_flag: bool
    capacity_price_eur_per_mw_isp: float | None
    contract_isp_count: int
    energy_bid_obligation_if_accepted: bool
    activation_modelled: bool


def _coerce_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field_name} must be boolean-like. Got: {value!r}")


def _coerce_timestamp(value: Any, *, field_name: str) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, errors="raise")
    if isinstance(timestamp, pd.DatetimeIndex):
        raise ValueError(f"{field_name} must be a single timestamp.")
    parsed = pd.Timestamp(timestamp)
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware. Got naive timestamp: {value!r}")
    return parsed.tz_convert("UTC")


def _coerce_numeric(value: Any, *, field_name: str) -> float:
    parsed = float(value)
    if not np.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite. Got: {value!r}")
    return parsed


def _records_to_frame(records: pd.DataFrame | Iterable[CapacityResultRecord | dict[str, Any]]) -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        return records.copy()
    rows: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, CapacityResultRecord):
            rows.append(asdict(record))
        elif isinstance(record, dict):
            rows.append(dict(record))
        else:
            raise TypeError(
                "records must be a pandas DataFrame or an iterable of CapacityResultRecord / dict rows. "
                f"Got: {type(record)!r}"
            )
    return pd.DataFrame(rows)


def _join_unique_text(values: pd.Series) -> str:
    unique = [str(value) for value in values.dropna().astype(str).tolist() if str(value).strip()]
    if not unique:
        return ""
    return "|".join(sorted(set(unique)))


def _derived_contract_isp_count(delivery_start_utc: pd.Timestamp, delivery_end_utc: pd.Timestamp) -> int:
    duration = delivery_end_utc - delivery_start_utc
    if duration <= pd.Timedelta(0):
        raise ValueError("delivery_end must be strictly after delivery_start.")
    isps = duration / ISP_DURATION
    rounded = int(round(float(isps)))
    if not np.isclose(float(isps), float(rounded), atol=1e-9):
        raise ValueError(
            "delivery_start and delivery_end must define an integer number of 15-minute ISPs. "
            f"Got duration={duration}."
        )
    if rounded <= 0:
        raise ValueError("contract block must contain at least one ISP.")
    return rounded


def normalize_capacity_result_records(
    records: pd.DataFrame | Iterable[CapacityResultRecord | dict[str, Any]],
    *,
    allow_zero_acceptance: bool = False,
    allowed_product_structures: tuple[str, ...] = ALLOWED_CAPACITY_PRODUCT_STRUCTURES,
) -> pd.DataFrame:
    frame = _records_to_frame(records)
    missing = set(RAW_REQUIRED_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Capacity-result records are missing required columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError("Capacity-result records are empty.")

    frame["branch_id"] = frame["branch_id"].astype(str)
    frame["delivery_date"] = frame["delivery_date"].astype(str)
    frame["capacity_contract_block_id"] = frame["capacity_contract_block_id"].astype(str)
    frame["capacity_product_structure"] = frame["capacity_product_structure"].astype(str)
    frame["direction"] = frame["direction"].astype(str)
    frame["forecast_origin_utc"] = frame["forecast_origin"].map(
        lambda value: _coerce_timestamp(value, field_name="forecast_origin")
    )
    frame["delivery_start_utc"] = frame["delivery_start"].map(
        lambda value: _coerce_timestamp(value, field_name="delivery_start")
    )
    frame["delivery_end_utc"] = frame["delivery_end"].map(
        lambda value: _coerce_timestamp(value, field_name="delivery_end")
    )
    frame["accepted_flag"] = frame["accepted_flag"].map(
        lambda value: _coerce_bool(value, field_name="accepted_flag")
    )
    frame["energy_bid_obligation_if_accepted"] = frame["energy_bid_obligation_if_accepted"].map(
        lambda value: _coerce_bool(value, field_name="energy_bid_obligation_if_accepted")
    )
    frame["activation_modelled"] = frame["activation_modelled"].map(
        lambda value: _coerce_bool(value, field_name="activation_modelled")
    )
    frame["offered_capacity_mw"] = frame["offered_capacity_mw"].map(
        lambda value: _coerce_numeric(value, field_name="offered_capacity_mw")
    )
    frame["accepted_capacity_mw"] = frame["accepted_capacity_mw"].map(
        lambda value: _coerce_numeric(value, field_name="accepted_capacity_mw")
    )
    frame["contract_isp_count"] = frame["contract_isp_count"].map(
        lambda value: int(_coerce_numeric(value, field_name="contract_isp_count"))
    )
    frame["capacity_price_eur_per_mw_isp"] = frame["capacity_price_eur_per_mw_isp"].apply(
        lambda value: np.nan if pd.isna(value) else _coerce_numeric(value, field_name="capacity_price_eur_per_mw_isp")
    )

    if not frame["direction"].isin({"Up", "Down"}).all():
        invalid = sorted(frame.loc[~frame["direction"].isin({"Up", "Down"}), "direction"].unique().tolist())
        raise ValueError(f"direction must be Up or Down. Got: {invalid}")
    if not frame["capacity_product_structure"].isin(allowed_product_structures).all():
        invalid_structures = sorted(
            frame.loc[~frame["capacity_product_structure"].isin(allowed_product_structures), "capacity_product_structure"]
            .unique()
            .tolist()
        )
        raise ValueError(
            "Unknown capacity_product_structure values were found. "
            f"Allowed={list(allowed_product_structures)}, got={invalid_structures}"
        )
    if (frame["offered_capacity_mw"] < 0.0).any():
        raise ValueError("offered_capacity_mw must be nonnegative.")
    if (frame["accepted_capacity_mw"] < 0.0).any():
        raise ValueError("accepted_capacity_mw must be nonnegative.")
    if (frame["contract_isp_count"] <= 0).any():
        raise ValueError("contract_isp_count must be positive.")

    local_start_dates = (
        pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
        .dt.tz_convert(MARKET_TZ)
        .dt.date.astype(str)
    )
    if not frame["delivery_date"].eq(local_start_dates).all():
        mismatches = frame.loc[~frame["delivery_date"].eq(local_start_dates), ["delivery_date", "delivery_start_utc"]]
        raise ValueError(
            "delivery_date must match the Europe/Amsterdam local date of delivery_start. "
            f"Example mismatches={mismatches.head(3).to_dict(orient='records')}"
        )

    derived_counts = [
        _derived_contract_isp_count(start_utc, end_utc)
        for start_utc, end_utc in zip(frame["delivery_start_utc"], frame["delivery_end_utc"], strict=True)
    ]
    if not np.array_equal(np.asarray(derived_counts, dtype=int), frame["contract_isp_count"].astype(int).to_numpy()):
        raise ValueError("contract_isp_count does not match delivery_start/delivery_end.")

    for row in frame.itertuples(index=False):
        if bool(row.accepted_flag):
            if row.accepted_capacity_mw <= 0.0 and not allow_zero_acceptance:
                raise ValueError(
                    "accepted_flag=true requires accepted_capacity_mw > 0 unless allow_zero_acceptance=True is passed."
                )
            if row.accepted_capacity_mw - row.offered_capacity_mw > 1e-9:
                raise ValueError("accepted_capacity_mw cannot exceed offered_capacity_mw.")
        else:
            if abs(float(row.accepted_capacity_mw)) > 1e-9:
                raise ValueError("accepted_flag=false requires accepted_capacity_mw = 0.")
        if bool(row.activation_modelled):
            raise ValueError("activation_modelled must remain false in this adapter stage.")

    frame["accepted_capacity_revenue_eur_if_available"] = np.where(
        frame["accepted_flag"] & frame["capacity_price_eur_per_mw_isp"].notna(),
        frame["accepted_capacity_mw"] * frame["capacity_price_eur_per_mw_isp"] * frame["contract_isp_count"],
        np.nan,
    )
    return frame.sort_values(
        ["branch_id", "delivery_start_utc", "capacity_contract_block_id", "direction"]
    ).reset_index(drop=True)


def convert_capacity_results_to_hourly_da_obligations(
    records: pd.DataFrame | Iterable[CapacityResultRecord | dict[str, Any]],
    *,
    allow_zero_acceptance: bool = False,
    allowed_product_structures: tuple[str, ...] = ALLOWED_CAPACITY_PRODUCT_STRUCTURES,
) -> pd.DataFrame:
    normalized = normalize_capacity_result_records(
        records,
        allow_zero_acceptance=allow_zero_acceptance,
        allowed_product_structures=allowed_product_structures,
    )
    expanded_rows: list[dict[str, Any]] = []

    for row in normalized.itertuples(index=False):
        hour_starts = pd.date_range(
            row.delivery_start_utc.floor("h"),
            row.delivery_end_utc.ceil("h") - HOUR_DURATION,
            freq="h",
            tz="UTC",
        )
        for hour_start in hour_starts:
            hour_end = hour_start + HOUR_DURATION
            overlap = min(row.delivery_end_utc, hour_end) - max(row.delivery_start_utc, hour_start)
            if overlap <= pd.Timedelta(0):
                continue
            accepted_capacity = float(row.accepted_capacity_mw) if bool(row.accepted_flag) else 0.0
            expanded_rows.append(
                {
                    "branch_id": str(row.branch_id),
                    "capacity_contract_block_id": str(row.capacity_contract_block_id),
                    "delivery_timestamp": pd.Timestamp(hour_start),
                    "accepted_up_reserve_mw_for_da": accepted_capacity if str(row.direction) == "Up" else 0.0,
                    "accepted_down_reserve_mw_for_da": accepted_capacity if str(row.direction) == "Down" else 0.0,
                    "reserve_obligation_active": bool(row.accepted_flag and accepted_capacity > 0.0),
                    "energy_bid_obligation_created": bool(
                        row.accepted_flag and accepted_capacity > 0.0 and row.energy_bid_obligation_if_accepted
                    ),
                }
            )

    expanded = pd.DataFrame(expanded_rows)
    if expanded.empty:
        raise ValueError("No hourly DA obligation rows were produced from the input capacity-result records.")

    grouped = (
        expanded.groupby(
            ["branch_id", "capacity_contract_block_id", "delivery_timestamp"],
            as_index=False,
        )
        .agg(
            accepted_up_reserve_mw_for_da=("accepted_up_reserve_mw_for_da", "max"),
            accepted_down_reserve_mw_for_da=("accepted_down_reserve_mw_for_da", "max"),
            reserve_obligation_active=("reserve_obligation_active", "max"),
            energy_bid_obligation_created=("energy_bid_obligation_created", "max"),
        )
        .sort_values(["branch_id", "delivery_timestamp"])
        .reset_index(drop=True)
    )
    grouped["delivery_start_utc"] = grouped["delivery_timestamp"]
    return grouped


def align_hourly_da_obligations_to_delivery_hours(
    hourly_obligations: pd.DataFrame,
    *,
    delivery_timestamps_utc: pd.DatetimeIndex,
    site_max_load_mw: float,
) -> pd.DataFrame:
    missing = set(HOURLY_REQUIRED_COLUMNS).difference(hourly_obligations.columns)
    if missing:
        raise ValueError(f"Hourly DA reserve obligations are missing required columns: {sorted(missing)}")
    if delivery_timestamps_utc.empty:
        raise ValueError("delivery_timestamps_utc is empty.")
    if float(site_max_load_mw) <= 0.0:
        raise ValueError("site_max_load_mw must be positive.")

    frame = hourly_obligations.copy()
    frame["delivery_timestamp"] = pd.to_datetime(frame["delivery_timestamp"], utc=True, errors="raise")
    frame["accepted_up_reserve_mw_for_da"] = pd.to_numeric(frame["accepted_up_reserve_mw_for_da"], errors="raise")
    frame["accepted_down_reserve_mw_for_da"] = pd.to_numeric(frame["accepted_down_reserve_mw_for_da"], errors="raise")
    frame["reserve_obligation_active"] = frame["reserve_obligation_active"].map(
        lambda value: _coerce_bool(value, field_name="reserve_obligation_active")
    )
    frame["energy_bid_obligation_created"] = frame["energy_bid_obligation_created"].map(
        lambda value: _coerce_bool(value, field_name="energy_bid_obligation_created")
    )

    if (frame["accepted_up_reserve_mw_for_da"] < -1e-9).any() or (frame["accepted_down_reserve_mw_for_da"] < -1e-9).any():
        raise ValueError("Hourly DA reserve obligations must be nonnegative.")
    if (frame["accepted_up_reserve_mw_for_da"] > float(site_max_load_mw) + 1e-9).any():
        raise ValueError("accepted_up_reserve_mw_for_da exceeds site_max_load_mw.")
    if (frame["accepted_down_reserve_mw_for_da"] > float(site_max_load_mw) + 1e-9).any():
        raise ValueError("accepted_down_reserve_mw_for_da exceeds site_max_load_mw.")

    grouped = (
        frame.groupby("delivery_timestamp", as_index=False)
        .agg(
            branch_id=("branch_id", _join_unique_text),
            capacity_contract_block_id=("capacity_contract_block_id", _join_unique_text),
            accepted_up_reserve_mw_for_da=("accepted_up_reserve_mw_for_da", "max"),
            accepted_down_reserve_mw_for_da=("accepted_down_reserve_mw_for_da", "max"),
            reserve_obligation_active=("reserve_obligation_active", "max"),
            energy_bid_obligation_created=("energy_bid_obligation_created", "max"),
        )
        .sort_values("delivery_timestamp")
        .reset_index(drop=True)
    )

    delivery_index = pd.DatetimeIndex(pd.to_datetime(delivery_timestamps_utc, utc=True, errors="raise"))
    extra = sorted(set(grouped["delivery_timestamp"].tolist()).difference(set(delivery_index.tolist())))
    if extra:
        raise ValueError(f"Hourly DA reserve obligations contain timestamps outside the delivery horizon: {extra}")

    aligned = pd.DataFrame({"delivery_timestamp": delivery_index})
    aligned = aligned.merge(grouped, on="delivery_timestamp", how="left")
    for column in ("branch_id", "capacity_contract_block_id"):
        if column not in aligned.columns:
            aligned[column] = ""
        aligned[column] = aligned[column].fillna("").astype(str)
    for column in ("accepted_up_reserve_mw_for_da", "accepted_down_reserve_mw_for_da"):
        aligned[column] = pd.to_numeric(aligned[column], errors="coerce").fillna(0.0)
    for column in ("reserve_obligation_active", "energy_bid_obligation_created"):
        aligned[column] = aligned[column].fillna(False).astype(bool)
    aligned["delivery_start_utc"] = aligned["delivery_timestamp"]
    return aligned


def run_adapter_self_check() -> pd.DataFrame:
    records = [
        CapacityResultRecord(
            branch_id="accepted_up",
            forecast_origin="2025-07-10T06:00:00Z",
            delivery_date="2025-07-11",
            delivery_start="2025-07-11T00:00:00+02:00",
            delivery_end="2025-07-11T02:00:00+02:00",
            capacity_contract_block_id="observed_daily_up",
            capacity_product_structure="observed_daily",
            direction="Up",
            offered_capacity_mw=22.0,
            accepted_capacity_mw=22.0,
            accepted_flag=True,
            capacity_price_eur_per_mw_isp=2.5,
            contract_isp_count=8,
            energy_bid_obligation_if_accepted=True,
            activation_modelled=False,
        ),
        CapacityResultRecord(
            branch_id="rejected_down",
            forecast_origin="2025-07-10T06:00:00Z",
            delivery_date="2025-07-11",
            delivery_start="2025-07-11T02:00:00+02:00",
            delivery_end="2025-07-11T04:00:00+02:00",
            capacity_contract_block_id="observed_daily_down",
            capacity_product_structure="observed_daily",
            direction="Down",
            offered_capacity_mw=58.0,
            accepted_capacity_mw=0.0,
            accepted_flag=False,
            capacity_price_eur_per_mw_isp=2.5,
            contract_isp_count=8,
            energy_bid_obligation_if_accepted=True,
            activation_modelled=False,
        ),
    ]
    return convert_capacity_results_to_hourly_da_obligations(records)


if __name__ == "__main__":
    print(run_adapter_self_check().head(4).to_string(index=False))
