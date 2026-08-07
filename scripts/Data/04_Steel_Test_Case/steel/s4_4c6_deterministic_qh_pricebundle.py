"""Build the governed annual QH price input for deterministic C0/C1 runs.

The resulting path is deliberately counterfactual: it keeps every accepted
realised hourly anchor and adds a frozen, zero-mean intra-hour shape.  It is
not a ledger of historically settled Dutch quarter-hour DA prices.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


QH_PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
if str(QH_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(QH_PACKAGE_ROOT))

from quarterhour_da.representative_regime_study import (  # noqa: E402
    build_shape_library,
    stable_seed,
    validate_overlay_contract,
)


PRICE_CONTRACT_VERSION = (
    "realised_hourly_anchor_plus_frozen_mean_preserving_qh_shape_v1"
)
CALENDAR_CONTRACT_VERSION = "lear_strict_donly_native_dst_qh_calendar_v1"
DEFAULT_SHAPE_ROOT = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/scenario_evaluation/"
    "strict_lear_dplus4_finalisation/20260729_strict_lear_dplus4_full_a03"
)
DEFAULT_HOURLY_LEDGER = REPO_ROOT / (
    "data/03_Optimisation/runs/steel_c6_deterministic_hourly_full_year_v1_20260806/"
    "deterministic_hourly_final_year_v60_20260807_01/annual_realised_price_ledger.csv"
)


class QHPriceBundleError(ValueError):
    """Raised when the frozen QH shape contract cannot be reproduced."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _shape_inputs(shape_root: Path) -> tuple[pd.DataFrame, ...]:
    files = {
        "hourly_points": shape_root / "optimisation_inputs/hourly_point_forecasts.parquet",
        "quarterhour_points": shape_root / "optimisation_inputs/quarterhour_point_forecasts.parquet",
        "hourly_scenarios": shape_root / "optimisation_inputs/hourly_scenarios_10.parquet",
        "quarterhour_scenarios": shape_root / "optimisation_inputs/quarterhour_scenarios_10.parquet",
        "actuals": shape_root / "evaluation_actuals.parquet",
    }
    missing = [str(path) for path in files.values() if not path.exists()]
    if missing:
        raise QHPriceBundleError(f"Frozen QH shape inputs are missing: {missing}")
    return tuple(pd.read_parquet(path) for path in files.values())


def _hourly_anchor_rows(hourly_ledger: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp_utc", "price_eur_per_mwh", "local_date"}
    missing = required - set(hourly_ledger.columns)
    if missing:
        raise QHPriceBundleError(f"Hourly annual ledger lacks {sorted(missing)}.")
    anchors = hourly_ledger.loc[:, ["timestamp_utc", "price_eur_per_mwh", "local_date"]].copy()
    anchors["timestamp_utc"] = pd.to_datetime(anchors["timestamp_utc"], utc=True)
    anchors["price_eur_per_mwh"] = pd.to_numeric(anchors["price_eur_per_mwh"], errors="raise")
    anchors = anchors.sort_values("timestamp_utc").reset_index(drop=True)
    if len(anchors) != 8_760 or anchors["timestamp_utc"].duplicated().any():
        raise QHPriceBundleError("Hourly annual anchor must contain exactly 8,760 unique UTC hours.")
    expected = pd.date_range(anchors["timestamp_utc"].iloc[0], periods=8_760, freq="h", tz="UTC")
    if not anchors["timestamp_utc"].equals(pd.Series(expected)):
        raise QHPriceBundleError("Hourly annual anchor has missing or non-contiguous UTC hours.")
    return anchors


def _annual_actual_overlay(
    anchors: pd.DataFrame,
    *,
    actual_shape_library: pd.DataFrame,
    random_seed: int,
) -> pd.DataFrame:
    """Vector-light annual equivalent of the frozen ``counterfactual_actual`` arm.

    ``apply_counterfactual_shape_overlay`` performs this selection per
    representative week.  Here we preserve its actual-path selection key
    (seed, annual day and weekend flag) while avoiding rebuilding the same
    11,136-row candidate pool 365 times.
    """

    candidates: dict[bool, list[tuple[str, dict[int, np.ndarray]]]] = {False: [], True: []}
    for (source_date, weekend), profile in actual_shape_library.groupby(
        ["source_local_date", "weekend"], sort=True
    ):
        if len(profile) != 96:
            continue
        by_hour = {
            int(hour): group.sort_values("quarter_index")["quarterhour_delta"].to_numpy(dtype=float)
            for hour, group in profile.groupby("local_hour", sort=True)
        }
        candidates[bool(weekend)].append((str(source_date), by_hour))
    if not candidates[False] or not candidates[True]:
        raise QHPriceBundleError("Frozen actual-shape pool lacks a complete weekday or weekend profile.")
    rows: list[dict[str, Any]] = []
    work = anchors.copy()
    local = work["timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    work["local_date"] = local.dt.date.astype(str)
    work["local_hour"] = local.dt.hour
    work["weekend"] = local.dt.dayofweek.ge(5)
    for local_date, day in work.groupby("local_date", sort=True):
        weekend = bool(day["weekend"].iloc[0])
        pool = candidates[weekend]
        choice = stable_seed(random_seed, f"annual__{local_date}", local_date, "actual_shape") % len(pool)
        source_profile_id, by_hour = pool[choice]
        for row in day.itertuples(index=False):
            deltas = by_hour[int(row.local_hour)]
            centred = deltas - float(np.mean(deltas))
            for offset, delta in enumerate(centred):
                rows.append(
                    {
                        "week_id": f"annual__{local_date}",
                        "path_kind": "counterfactual_actual",
                        "scenario_id": "ACTUAL",
                        "scenario_probability": 1.0,
                        "scenario_set_size": 1,
                        "target_timestamp_utc": row.timestamp_utc + pd.Timedelta(minutes=15 * offset),
                        "hour_start_utc": row.timestamp_utc,
                        "quarter_index": offset + 1,
                        "hourly_anchor_price": float(row.price_eur_per_mwh),
                        "quarterhour_delta": float(delta),
                        "quarterhour_price": float(row.price_eur_per_mwh + delta),
                        "source_profile_id": source_profile_id,
                        "counterfactual": True,
                    }
                )
    return pd.DataFrame(rows)


def build_annual_qh_pricebundle(
    *,
    output: Path,
    hourly_ledger_path: Path = DEFAULT_HOURLY_LEDGER,
    shape_root: Path = DEFAULT_SHAPE_ROOT,
    random_seed: int = 20260731,
    tolerance: float = 1e-10,
) -> Mapping[str, Any]:
    """Materialise and validate all 35,040 QH PF prices from frozen evidence."""

    if output.exists() and any(output.iterdir()):
        raise QHPriceBundleError(f"Refusing to overwrite existing QH bundle: {output}")
    output.mkdir(parents=True, exist_ok=True)
    anchors = _hourly_anchor_rows(pd.read_csv(hourly_ledger_path))
    library = build_shape_library(*_shape_inputs(shape_root), tolerance=tolerance)
    bundle = _annual_actual_overlay(
        anchors,
        actual_shape_library=library["actual"],
        random_seed=random_seed,
    ).sort_values("target_timestamp_utc").reset_index(drop=True)
    bundle["local_timestamp"] = bundle["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    bundle["local_date"] = bundle["local_timestamp"].dt.date.astype(str)
    bundle["calendar_day_index"] = pd.factorize(bundle["local_date"], sort=False)[0] + 1
    checks = validate_overlay_contract(bundle, tolerance=tolerance)
    qh_times = pd.DatetimeIndex(bundle["target_timestamp_utc"])
    expected_qh = pd.date_range(qh_times[0], periods=35_040, freq="15min", tz="UTC")
    hourly_means = bundle.groupby("hour_start_utc")["quarterhour_price"].mean()
    anchor_map = anchors.set_index("timestamp_utc")["price_eur_per_mwh"]
    reconstruction = (hourly_means - anchor_map.reindex(hourly_means.index)).abs()
    day_lengths = bundle.groupby("calendar_day_index").size()
    static_checks = {
        "qh_interval_count": int(len(bundle)) == 35_040,
        "contiguous_qh_utc": qh_times.equals(expected_qh),
        "unique_qh_utc": not bundle["target_timestamp_utc"].duplicated().any(),
        "four_qh_per_utc_hour": bool(bundle.groupby("hour_start_utc").size().eq(4).all()),
        "native_dst_day_lengths": sorted(day_lengths.unique().tolist()) == [92, 96, 100]
        and int(day_lengths.eq(92).sum()) == 1 and int(day_lengths.eq(100).sum()) == 1,
        "hourly_anchor_reconstruction": float(reconstruction.max()) <= tolerance,
        "overlay_contract": bool(checks["status"].eq("pass").all()),
    }
    if not all(static_checks.values()):
        raise QHPriceBundleError(f"Annual QH price bundle failed: {static_checks}")
    bundle.to_parquet(output / "annual_qh_price_ledger.parquet", index=False)
    bundle.to_csv(output / "annual_qh_price_ledger.csv", index=False)
    summary: dict[str, Any] = {
        "calendar_contract_version": CALENDAR_CONTRACT_VERSION,
        "price_contract_version": PRICE_CONTRACT_VERSION,
        "classification": "counterfactual_mean_preserving_qh_prices_on_realised_hourly_anchor",
        "historical_qh_da_prices_claimed": False,
        "random_seed": random_seed,
        "hourly_anchor_sha256": _sha256_file(hourly_ledger_path),
        "shape_source_run": str(shape_root.relative_to(REPO_ROOT)).replace("\\", "/"),
        "shape_source_run_summary_sha256": _sha256_file(shape_root / "run_summary.json"),
        "qh_intervals": int(len(bundle)),
        "calendar_days": int(bundle["calendar_day_index"].nunique()),
        "maximum_hourly_anchor_reconstruction_difference_eur_per_mwh": float(reconstruction.max()),
        "checks": static_checks,
        "overlay_checks": checks.to_dict(orient="records"),
    }
    (output / "annual_qh_pricebundle_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


__all__ = ["build_annual_qh_pricebundle", "QHPriceBundleError"]
