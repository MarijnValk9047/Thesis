from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

REFERENCE_PRICE_BID_EUR_PER_MWH = 158.0
HIGH_PRICE_BID_EUR_PER_MWH = 3000.0

DEFAULT_BID_PRICE_GRID_EUR_PER_MWH: tuple[float, ...] = (
    -500.0,
    -100.0,
    0.0,
    50.0,
    100.0,
    125.0,
    144.0,
    158.0,
    175.0,
    200.0,
    250.0,
    500.0,
    1000.0,
    3000.0,
)
NEGATIVE_BID_QUANTITY_TOLERANCE_MW = 1e-9


def _extract_grid_from_mapping(mapping: dict[str, Any]) -> list[Any] | None:
    bidding = mapping.get("bidding")
    if isinstance(bidding, dict) and "bid_price_grid_eur_per_mwh" in bidding:
        return list(bidding["bid_price_grid_eur_per_mwh"])
    if "bid_price_grid_eur_per_mwh" in mapping:
        return list(mapping["bid_price_grid_eur_per_mwh"])
    return None


def _read_config_mapping(config: Any) -> dict[str, Any] | None:
    if config is None:
        return None
    if isinstance(config, dict):
        return config
    if hasattr(config, "config_path"):
        config_path = Path(getattr(config, "config_path"))
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    bidding_attr = getattr(config, "bidding", None)
    if isinstance(bidding_attr, dict):
        return {"bidding": bidding_attr}
    return None


def validate_bid_price_grid(grid: Iterable[Any]) -> list[float]:
    values = list(grid)
    if not values:
        raise ValueError("Bid price grid is empty.")

    try:
        parsed = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("Bid price grid contains nonnumeric values.") from exc

    if any(not np.isfinite(value) for value in parsed):
        raise ValueError("Bid price grid contains NaN or infinite values.")
    if len(set(parsed)) != len(parsed):
        raise ValueError("Bid price grid contains duplicate values.")
    if any(parsed[idx] >= parsed[idx + 1] for idx in range(len(parsed) - 1)):
        raise ValueError("Bid price grid must be strictly increasing.")
    return parsed


def build_bid_price_grid(config: Any = None) -> list[float]:
    mapping = _read_config_mapping(config)
    configured = _extract_grid_from_mapping(mapping) if mapping is not None else None
    if configured is None:
        configured = list(DEFAULT_BID_PRICE_GRID_EUR_PER_MWH)
    return validate_bid_price_grid(configured)


def _coerce_timestamp(value: Any, *, field_name: str) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True, errors="raise")
    if isinstance(timestamp, pd.DatetimeIndex):
        raise ValueError(f"{field_name} must be a single timestamp, not a sequence.")
    return pd.Timestamp(timestamp)


def _coerce_delivery_index(delivery_start_utc: Any) -> pd.DatetimeIndex:
    timestamps = pd.to_datetime(delivery_start_utc, utc=True, errors="raise")
    index = pd.DatetimeIndex(timestamps)
    if index.empty:
        raise ValueError("delivery_start_utc is empty.")
    if not index.is_unique:
        raise ValueError("delivery_start_utc contains duplicate timestamps.")
    return index


def _coerce_quantity_matrix(
    bid_quantities_mw: Any,
    *,
    periods: int,
    blocks: int,
) -> np.ndarray:
    array = np.asarray(bid_quantities_mw, dtype=float)
    if array.ndim == 0:
        array = np.full((periods, blocks), float(array))
    elif array.ndim == 1:
        if array.shape[0] != blocks:
            raise ValueError(
                f"1D bid quantity input must have length equal to number of bid blocks ({blocks})."
            )
        array = np.tile(array.reshape(1, blocks), (periods, 1))
    elif array.ndim == 2:
        if array.shape != (periods, blocks):
            raise ValueError(
                f"2D bid quantity input must have shape ({periods}, {blocks}), got {array.shape}."
            )
    else:
        raise ValueError("bid_quantities_mw must be scalar, 1D, or 2D.")

    if not np.isfinite(array).all():
        raise ValueError("bid_quantities_mw contains NaN or infinite values.")
    min_value = float(array.min()) if array.size else 0.0
    if min_value < -NEGATIVE_BID_QUANTITY_TOLERANCE_MW:
        raise ValueError("bid_quantities_mw cannot contain negative values.")
    if min_value < 0.0:
        array = np.where(array < 0.0, 0.0, array)
    return array


def build_bid_curve_dataframe(
    *,
    run_id: str,
    strategy: str,
    delivery_start_utc: Any,
    bid_quantities_mw: Any,
    forecast_origin_utc: Any,
    granularity: str,
    horizon: str,
    timestep_hours: float,
    bid_price_grid: Iterable[Any] | None = None,
    config: Any = None,
    forecast_model: str | None = None,
    scenario_model: str | None = None,
    max_total_quantity_mw: float | None = None,
) -> pd.DataFrame:
    grid = validate_bid_price_grid(bid_price_grid) if bid_price_grid is not None else build_bid_price_grid(config)
    if timestep_hours <= 0:
        raise ValueError("timestep_hours must be positive.")

    timestamps = _coerce_delivery_index(delivery_start_utc)
    forecast_origin = _coerce_timestamp(forecast_origin_utc, field_name="forecast_origin_utc")
    quantity_matrix = _coerce_quantity_matrix(
        bid_quantities_mw,
        periods=len(timestamps),
        blocks=len(grid),
    )

    if max_total_quantity_mw is not None:
        if max_total_quantity_mw < 0:
            raise ValueError("max_total_quantity_mw must be nonnegative when provided.")
        row_sums = quantity_matrix.sum(axis=1)
        if (row_sums > float(max_total_quantity_mw) + 1e-9).any():
            raise ValueError("Submitted quantity exceeds max_total_quantity_mw for at least one hour.")

    rows: list[dict[str, Any]] = []
    for period_idx, delivery_ts in enumerate(timestamps):
        for block_idx, bid_price in enumerate(grid):
            rows.append(
                {
                    "run_id": str(run_id),
                    "strategy": str(strategy),
                    "forecast_model": forecast_model,
                    "scenario_model": scenario_model,
                    "granularity": str(granularity),
                    "horizon": str(horizon),
                    "forecast_origin_utc": forecast_origin,
                    "delivery_start_utc": pd.Timestamp(delivery_ts),
                    "bid_block": int(block_idx),
                    "bid_price_eur_per_mwh": float(bid_price),
                    "bid_quantity_mw": float(quantity_matrix[period_idx, block_idx]),
                    "timestep_hours": float(timestep_hours),
                }
            )

    bid_curve = pd.DataFrame(rows)
    duplicate_rows = bid_curve.duplicated(subset=["delivery_start_utc", "bid_block"], keep=False)
    if bool(duplicate_rows.any()):
        raise ValueError("Duplicate bid rows detected for the same delivery_start_utc and bid_block.")
    return bid_curve


def _resolve_dispatch_column(frame: pd.DataFrame, candidates: Iterable[str], *, label: str) -> str:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    raise ValueError(f"Dispatch schedule is missing a {label} column. Checked: {list(candidates)}")


def _resolve_schedule_metadata(
    dispatch_timeseries: pd.DataFrame,
    *,
    granularity: str | None,
    horizon: str | None,
    forecast_model: str | None,
    scenario_model: str | None,
) -> dict[str, Any]:
    resolved_granularity = granularity
    resolved_horizon = horizon
    resolved_forecast_model = forecast_model
    resolved_scenario_model = scenario_model

    if resolved_forecast_model is None and "forecast_model" in dispatch_timeseries.columns:
        nonnull = dispatch_timeseries["forecast_model"].dropna()
        resolved_forecast_model = str(nonnull.iloc[0]) if not nonnull.empty else None
    if resolved_scenario_model is None:
        if "scenario_model" in dispatch_timeseries.columns:
            nonnull = dispatch_timeseries["scenario_model"].dropna()
            resolved_scenario_model = str(nonnull.iloc[0]) if not nonnull.empty else None
        elif "model_id" in dispatch_timeseries.columns:
            nonnull = dispatch_timeseries["model_id"].dropna()
            resolved_scenario_model = str(nonnull.iloc[0]) if not nonnull.empty else None

    if resolved_granularity is None:
        delivery_index = pd.DatetimeIndex(
            pd.to_datetime(dispatch_timeseries["delivery_start_utc"], utc=True, errors="raise")
        ).sort_values()
        if len(delivery_index) >= 2:
            step_hours = (delivery_index[1] - delivery_index[0]).total_seconds() / 3600.0
            resolved_granularity = "quarter_hourly" if abs(step_hours - 0.25) < 1e-9 else "hourly"
        else:
            resolved_granularity = "hourly"
    if resolved_horizon is None:
        if "horizon" in dispatch_timeseries.columns:
            nonnull = dispatch_timeseries["horizon"].dropna()
            resolved_horizon = str(nonnull.iloc[0]) if not nonnull.empty else "unknown"
        elif "lead_day" in dispatch_timeseries.columns:
            lead_day = pd.to_numeric(dispatch_timeseries["lead_day"], errors="coerce").dropna()
            resolved_horizon = "D_only" if not lead_day.empty and int(lead_day.iloc[0]) == 0 else "unknown"
        else:
            resolved_horizon = "unknown"

    return {
        "granularity": str(resolved_granularity),
        "horizon": str(resolved_horizon),
        "forecast_model": resolved_forecast_model,
        "scenario_model": resolved_scenario_model,
    }


def dispatch_schedule_to_one_block_bid_curve(
    dispatch_timeseries: pd.DataFrame,
    *,
    run_id: str,
    source_strategy: str,
    bridge_strategy: str,
    bid_price_eur_per_mwh: float,
    granularity: str | None = None,
    horizon: str | None = None,
    forecast_model: str | None = None,
    scenario_model: str | None = None,
    timestep_hours: float | None = None,
    forecast_origin_utc: Any | None = None,
) -> pd.DataFrame:
    if dispatch_timeseries.empty:
        raise ValueError("dispatch_timeseries is empty.")
    try:
        bid_price = float(bid_price_eur_per_mwh)
    except (TypeError, ValueError) as exc:
        raise ValueError("bid_price_eur_per_mwh must be numeric.") from exc
    if not np.isfinite(bid_price):
        raise ValueError("bid_price_eur_per_mwh must be finite.")

    work = dispatch_timeseries.copy()
    work["delivery_start_utc"] = pd.to_datetime(work["delivery_start_utc"], utc=True, errors="raise")
    work = work.sort_values("delivery_start_utc").reset_index(drop=True)
    if work["delivery_start_utc"].duplicated().any():
        raise ValueError("Dispatch schedule contains duplicate delivery_start_utc rows.")

    p_el_column = _resolve_dispatch_column(work, ("P_el_mw", "electrolyser_power_mw"), label="electrolyser power")
    p_comp_column = _resolve_dispatch_column(work, ("P_comp_mw", "compressor_power_mw"), label="compressor power")
    work[p_el_column] = pd.to_numeric(work[p_el_column], errors="raise")
    work[p_comp_column] = pd.to_numeric(work[p_comp_column], errors="raise")
    work["scheduled_load_mw"] = work[p_el_column] + work[p_comp_column]
    if (work["scheduled_load_mw"] < -1e-9).any():
        raise ValueError("Dispatch schedule produced negative scheduled_load_mw.")
    work["scheduled_load_mw"] = work["scheduled_load_mw"].clip(lower=0.0)

    if timestep_hours is None:
        if len(work) >= 2:
            timestep_hours = float(
                (work["delivery_start_utc"].iloc[1] - work["delivery_start_utc"].iloc[0]).total_seconds() / 3600.0
            )
        else:
            timestep_hours = 1.0
    if timestep_hours <= 0.0:
        raise ValueError("timestep_hours must be positive.")

    resolved_metadata = _resolve_schedule_metadata(
        work,
        granularity=granularity,
        horizon=horizon,
        forecast_model=forecast_model,
        scenario_model=scenario_model,
    )
    if forecast_origin_utc is None:
        if "forecast_origin_utc" not in work.columns:
            raise ValueError("Dispatch schedule is missing forecast_origin_utc and no override was provided.")
        nonnull = work["forecast_origin_utc"].dropna()
        if nonnull.empty:
            raise ValueError("Dispatch schedule does not contain a usable forecast_origin_utc.")
        forecast_origin_utc = pd.Timestamp(pd.to_datetime(nonnull.iloc[0], utc=True, errors="raise"))
    else:
        forecast_origin_utc = pd.Timestamp(pd.to_datetime(forecast_origin_utc, utc=True, errors="raise"))

    bid_curve = pd.DataFrame(
        {
            "run_id": str(run_id),
            "strategy": f"{source_strategy}__{bridge_strategy}",
            "source_strategy": str(source_strategy),
            "bridge_strategy": str(bridge_strategy),
            "forecast_model": resolved_metadata["forecast_model"],
            "scenario_model": resolved_metadata["scenario_model"],
            "granularity": resolved_metadata["granularity"],
            "horizon": resolved_metadata["horizon"],
            "forecast_origin_utc": forecast_origin_utc,
            "delivery_start_utc": work["delivery_start_utc"],
            "bid_block": 0,
            "bid_price_eur_per_mwh": bid_price,
            "bid_quantity_mw": work["scheduled_load_mw"].astype(float),
            "timestep_hours": float(timestep_hours),
        }
    )
    duplicate_rows = bid_curve.duplicated(
        subset=["run_id", "strategy", "forecast_origin_utc", "delivery_start_utc", "bid_block"],
        keep=False,
    )
    if bool(duplicate_rows.any()):
        raise ValueError("Duplicate one-block bridge bid rows detected.")
    return bid_curve.reset_index(drop=True)
