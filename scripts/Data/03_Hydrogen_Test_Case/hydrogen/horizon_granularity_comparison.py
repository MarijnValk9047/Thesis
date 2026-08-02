from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

from scripts.optimisation_performance import peak_working_set_mb

from .bidding_model import solve_stochastic_da_bidding
from .clearing import aggregate_cleared_energy, clear_da_bids
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .production_target import build_weekly_quota_deadline_plan, build_weekly_quota_deadlines
from .redispatch import solve_actual_redispatch_from_cleared_energy
from .rolling_horizon import RollingHydrogenState


LOCAL_TZ = "Europe/Amsterdam"
SCENARIO_UNDERCOVERAGE_WARNING = (
    "The technically valid D-D+4 scenarios under-cover on evaluation; no calibrated 90% risk-coverage claim is permitted."
)


def load_comparison_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid comparison config: {config_path}")
    repo_root = Path(__file__).resolve().parents[4]
    return payload, repo_root


def _resolved(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_scenarios(path: Path, set_size: int, lead_days: Iterable[int]) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="raise")
    frame = frame.loc[
        pd.to_numeric(frame["scenario_set_size"], errors="raise").eq(int(set_size))
        & pd.to_numeric(frame["lead_day"], errors="raise").isin([int(value) for value in lead_days])
    ].copy()
    return frame.rename(
        columns={
            "target_timestamp_utc": "delivery_start_utc",
            "scenario_price": "scenario_price_eur_per_mwh",
            "point_forecast": "point_forecast_eur_per_mwh",
        }
    )


def _read_actuals(path: Path, granularity: str) -> pd.DataFrame:
    source_granularity = "quarterhour" if granularity == "quarter_hour" else "hourly"
    frame = pd.read_parquet(path)
    frame = frame.loc[frame["granularity"].astype(str).eq(source_granularity)].copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="raise")
    return frame.rename(
        columns={"target_timestamp_utc": "delivery_start_utc", "actual_price": "actual_price_eur_per_mwh"}
    )


def _delivery_day(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["delivery_start_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.date


def _weighted_ev(frame: pd.DataFrame) -> pd.DataFrame:
    probabilities = frame[["scenario_id", "scenario_probability"]].drop_duplicates("scenario_id")
    probability = probabilities.set_index("scenario_id")["scenario_probability"].astype(float)
    work = frame.copy()
    work["weighted_price"] = work["scenario_price_eur_per_mwh"].astype(float) * work["scenario_id"].map(probability)
    ev = work.groupby(["forecast_origin_utc", "delivery_start_utc"], as_index=False).agg(
        scenario_price_eur_per_mwh=("weighted_price", "sum")
    )
    ev["scenario_id"] = "EV30"
    ev["scenario_probability"] = 1.0
    return ev


def _price_insensitive_path(frame: pd.DataFrame) -> pd.DataFrame:
    base = frame[["forecast_origin_utc", "delivery_start_utc"]].drop_duplicates().copy()
    base["scenario_id"] = "PRICE_INSENSITIVE"
    base["scenario_probability"] = 1.0
    base["scenario_price_eur_per_mwh"] = 0.0
    return base


def _perfect_foresight_path(frame: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    keys = frame[["forecast_origin_utc", "delivery_start_utc"]].drop_duplicates()
    actual = actuals[["forecast_origin_utc", "delivery_start_utc", "actual_price_eur_per_mwh"]].drop_duplicates()
    merged = keys.merge(actual, on=["forecast_origin_utc", "delivery_start_utc"], how="left", validate="one_to_one")
    if merged["actual_price_eur_per_mwh"].isna().any():
        raise ValueError("Perfect-foresight path has missing actual prices.")
    merged["scenario_id"] = "TRUE_PF"
    merged["scenario_probability"] = 1.0
    return merged.rename(columns={"actual_price_eur_per_mwh": "scenario_price_eur_per_mwh"})


def build_policy_scenarios(
    *, policy: str, scenario_30: pd.DataFrame, scenario_10: pd.DataFrame, actuals: pd.DataFrame
) -> tuple[pd.DataFrame, list[float]]:
    def optimisation_only(frame: pd.DataFrame) -> pd.DataFrame:
        forbidden = [
            column
            for column in frame.columns
            if column.lower().startswith("actual") or "error" in column.lower() or "y_true" in column.lower()
        ]
        return frame.drop(columns=forbidden, errors="ignore")

    if policy == "stochastic_30":
        return optimisation_only(scenario_30.copy()), []
    if policy == "stochastic_10":
        return optimisation_only(scenario_10.copy()), []
    if policy == "ev_30":
        return optimisation_only(_weighted_ev(scenario_30)), []
    if policy == "price_insensitive":
        return optimisation_only(_price_insensitive_path(scenario_30)), [3000.0]
    if policy == "true_pf":
        return optimisation_only(_perfect_foresight_path(scenario_30, actuals)), []
    raise ValueError(f"Unsupported policy: {policy}")


def validate_support_contract(
    *, forecast_root: Path, comparison_config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    actuals_path = forecast_root / "evaluation_actuals.parquet"
    hourly_actual = _read_actuals(actuals_path, "hourly")
    qh_actual = _read_actuals(actuals_path, "quarter_hour")
    origins = hourly_actual[["forecast_origin_utc"]].drop_duplicates().sort_values("forecast_origin_utc")
    checks: list[dict[str, Any]] = []
    checks.append({"check": "statistical_origins", "observed": len(origins), "expected": 116, "passed": len(origins) == 116})

    hourly_point = pd.read_parquet(forecast_root / "optimisation_inputs/hourly_point_forecasts.parquet")
    qh_point = pd.read_parquet(forecast_root / "optimisation_inputs/quarterhour_point_forecasts.parquet")
    for frame in (hourly_point, qh_point):
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="raise")
    qh_point_hourly = (
        qh_point.assign(hour_utc=qh_point["target_timestamp_utc"].dt.floor("h"))
        .groupby(["forecast_origin_utc", "hour_utc", "lead_day"], as_index=False)["point_forecast"]
        .mean()
    )
    point_parity = qh_point_hourly.merge(
        hourly_point.rename(columns={"target_timestamp_utc": "hour_utc", "point_forecast": "hourly_point"})[
            ["forecast_origin_utc", "hour_utc", "lead_day", "hourly_point"]
        ],
        on=["forecast_origin_utc", "hour_utc", "lead_day"],
        validate="one_to_one",
    )
    max_point_parity_diff = float((point_parity["point_forecast"] - point_parity["hourly_point"]).abs().max())
    checks.append(
        {
            "check": "qh_point_means_to_hourly_point",
            "observed": max_point_parity_diff,
            "expected": 0.0,
            "passed": max_point_parity_diff <= 1e-10,
        }
    )

    qh_per_hour = (
        qh_actual.assign(hour_utc=qh_actual["delivery_start_utc"].dt.floor("h"))
        .groupby(["forecast_origin_utc", "hour_utc", "lead_day"])["delivery_start_utc"]
        .nunique()
    )
    checks.append(
        {
            "check": "four_observed_quarters_per_hour",
            "observed": sorted(qh_per_hour.unique().tolist()),
            "expected": [4],
            "passed": bool(qh_per_hour.eq(4).all()),
        }
    )

    qh_mean = (
        qh_actual.assign(hour_utc=qh_actual["delivery_start_utc"].dt.floor("h"))
        .groupby(["forecast_origin_utc", "hour_utc", "lead_day"], as_index=False)["actual_price_eur_per_mwh"]
        .mean()
    )
    h = hourly_actual.rename(columns={"delivery_start_utc": "hour_utc", "actual_price_eur_per_mwh": "hourly_actual"})
    aligned = qh_mean.merge(h, on=["forecast_origin_utc", "hour_utc", "lead_day"], validate="one_to_one")
    max_actual_diff = float((aligned["actual_price_eur_per_mwh"] - aligned["hourly_actual"]).abs().max())
    checks.append({"check": "qh_actual_means_to_hourly", "observed": max_actual_diff, "expected": 0.0, "passed": max_actual_diff <= 1e-10})

    episode_days: dict[str, list[str]] = {}
    available_days = set(_delivery_day(hourly_actual.loc[hourly_actual["lead_day"].eq(0)]).astype(str))
    for episode_id, spec in comparison_config["episodes"].items():
        wanted = pd.date_range(spec["start"], spec["end"], freq="D").strftime("%Y-%m-%d").tolist()
        observed = [day for day in wanted if day in available_days]
        episode_days[episode_id] = observed
        checks.append(
            {
                "check": f"episode_{episode_id}_days",
                "observed": len(observed),
                "expected": int(spec["expected_days"]),
                "passed": observed == wanted and len(observed) == int(spec["expected_days"]),
            }
        )

    scenario_meta: dict[str, dict[int, pd.DataFrame]] = {}
    for config_id, spec in comparison_config["configurations"].items():
        scenario_meta[config_id] = {}
        for set_size_text, relative_path in spec["scenario_files"].items():
            set_size = int(set_size_text)
            path = forecast_root / relative_path
            frame = _read_scenarios(path, set_size, spec["horizon_lead_days"])
            scenario_meta[config_id][set_size] = frame
            forbidden_columns = [
                column
                for column in frame.columns
                if column.lower().startswith("actual")
                or "error" in column.lower()
                or "y_true" in column.lower()
            ]
            checks.append(
                {
                    "check": f"{config_id}_{set_size}_no_future_information_columns",
                    "observed": forbidden_columns,
                    "expected": [],
                    "passed": not forbidden_columns,
                }
            )
            actual_reference = qh_actual if spec["granularity"] == "quarter_hour" else hourly_actual
            expected_keys = (
                actual_reference.loc[actual_reference["lead_day"].isin(spec["horizon_lead_days"]), [
                    "forecast_origin_utc",
                    "delivery_start_utc",
                    "lead_day",
                ]]
                .drop_duplicates()
                .sort_values(["forecast_origin_utc", "delivery_start_utc"])
                .reset_index(drop=True)
            )
            observed_keys = (
                frame[["forecast_origin_utc", "delivery_start_utc", "lead_day"]]
                .drop_duplicates()
                .sort_values(["forecast_origin_utc", "delivery_start_utc"])
                .reset_index(drop=True)
            )
            complete_paths = observed_keys.equals(expected_keys)
            checks.append(
                {
                    "check": f"{config_id}_{set_size}_complete_observed_paths",
                    "observed": len(observed_keys),
                    "expected": len(expected_keys),
                    "passed": complete_paths,
                }
            )
            probability = frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]].drop_duplicates()
            sums = probability.groupby("forecast_origin_utc")["scenario_probability"].sum()
            checks.append(
                {
                    "check": f"{config_id}_{set_size}_probability_sum",
                    "observed": float((sums - 1.0).abs().max()),
                    "expected": 0.0,
                    "passed": bool((sums - 1.0).abs().max() <= 1e-10),
                }
            )
            duplicate = frame.duplicated(["forecast_origin_utc", "delivery_start_utc", "scenario_id"]).any()
            checks.append({"check": f"{config_id}_{set_size}_unique_keys", "observed": bool(duplicate), "expected": False, "passed": not duplicate})

    for set_size in (30, 10):
        h = scenario_meta["H-D4"][set_size]
        q = scenario_meta["QH-D4"][set_size]
        metadata_columns = [
            "forecast_origin_utc",
            "scenario_id",
            "scenario_probability",
            "source_residual_block_id",
        ]
        h_meta = (
            h[metadata_columns]
            .drop_duplicates()
            .sort_values(["forecast_origin_utc", "scenario_id"])
            .reset_index(drop=True)
        )
        q_meta = (
            q[metadata_columns]
            .drop_duplicates()
            .sort_values(["forecast_origin_utc", "scenario_id"])
            .reset_index(drop=True)
        )
        same = h_meta.equals(q_meta)
        checks.append({"check": f"hourly_qh_linked_metadata_{set_size}", "observed": same, "expected": True, "passed": same})

        q_hourly = (
            q.assign(hour_utc=q["delivery_start_utc"].dt.floor("h"))
            .groupby(["forecast_origin_utc", "hour_utc", "lead_day", "scenario_id"], as_index=False)[
                "scenario_price_eur_per_mwh"
            ]
            .mean()
        )
        h_prices = h.rename(
            columns={
                "delivery_start_utc": "hour_utc",
                "scenario_price_eur_per_mwh": "hourly_scenario_price",
            }
        )[
            ["forecast_origin_utc", "hour_utc", "lead_day", "scenario_id", "hourly_scenario_price"]
        ]
        scenario_parity = q_hourly.merge(
            h_prices,
            on=["forecast_origin_utc", "hour_utc", "lead_day", "scenario_id"],
            validate="one_to_one",
        )
        max_scenario_parity_diff = float(
            (
                scenario_parity["scenario_price_eur_per_mwh"]
                - scenario_parity["hourly_scenario_price"]
            )
            .abs()
            .max()
        )
        checks.append(
            {
                "check": f"qh_scenarios_mean_to_hourly_{set_size}",
                "observed": max_scenario_parity_diff,
                "expected": 0.0,
                "passed": max_scenario_parity_diff <= 1e-10,
            }
        )

        d = scenario_meta["H-D"][set_size]
        d4_lead_d = h.loc[h["lead_day"].eq(0)]
        d_meta = (
            d[metadata_columns]
            .drop_duplicates()
            .sort_values(["forecast_origin_utc", "scenario_id"])
            .reset_index(drop=True)
        )
        d4_meta = (
            d4_lead_d[metadata_columns]
            .drop_duplicates()
            .sort_values(["forecast_origin_utc", "scenario_id"])
            .reset_index(drop=True)
        )
        same_donly = d_meta.equals(d4_meta)
        checks.append(
            {
                "check": f"donly_dplus4_linked_metadata_{set_size}",
                "observed": same_donly,
                "expected": True,
                "passed": same_donly,
            }
        )
        donly_anchor = d[[
            "forecast_origin_utc",
            "delivery_start_utc",
            "scenario_id",
            "point_forecast_eur_per_mwh",
            "scenario_price_eur_per_mwh",
        ]].rename(
            columns={
                "point_forecast_eur_per_mwh": "d_point",
                "scenario_price_eur_per_mwh": "d_scenario",
            }
        )
        d4_anchor = d4_lead_d[[
            "forecast_origin_utc",
            "delivery_start_utc",
            "scenario_id",
            "point_forecast_eur_per_mwh",
            "scenario_price_eur_per_mwh",
        ]].rename(
            columns={
                "point_forecast_eur_per_mwh": "d4_point",
                "scenario_price_eur_per_mwh": "d4_scenario",
            }
        )
        innovation = donly_anchor.merge(
            d4_anchor,
            on=["forecast_origin_utc", "delivery_start_utc", "scenario_id"],
            validate="one_to_one",
        )
        max_innovation_diff = float(
            ((innovation["d_scenario"] - innovation["d_point"]) - (innovation["d4_scenario"] - innovation["d4_point"]))
            .abs()
            .max()
        )
        checks.append(
            {
                "check": f"donly_inherits_dplus4_lead_D_innovation_{set_size}",
                "observed": max_innovation_diff,
                "expected": 0.0,
                "passed": max_innovation_diff <= 1e-10,
            }
        )

    mapping_path = forecast_root / comparison_config["scenario_reduction_mapping_file"]
    mapping = pd.read_csv(mapping_path)
    mapping["forecast_origin_utc"] = pd.to_datetime(mapping["forecast_origin_utc"], utc=True, errors="raise")
    counts = mapping.groupby("forecast_origin_utc")["parent_scenario_id_30"].nunique()
    parent_probability = mapping.groupby(
        ["forecast_origin_utc", "child_scenario_id_10"], as_index=False
    )["parent_probability_30"].sum()
    child_probability = mapping[
        ["forecast_origin_utc", "child_scenario_id_10", "child_probability_10"]
    ].drop_duplicates()
    nested = parent_probability.merge(
        child_probability,
        on=["forecast_origin_utc", "child_scenario_id_10"],
        how="outer",
        validate="one_to_one",
    )
    max_nested_probability_diff = float(
        (nested["parent_probability_30"] - nested["child_probability_10"]).abs().max()
    )
    checks.append(
        {
            "check": "scenario_10_is_weighted_reduction_of_30",
            "observed": max_nested_probability_diff,
            "expected": 0.0,
            "passed": bool(counts.eq(30).all() and max_nested_probability_diff <= 1e-10),
        }
    )

    checks_frame = pd.DataFrame(checks)
    if not checks_frame["passed"].all():
        raise ValueError(f"Support contract failed: {checks_frame.loc[~checks_frame['passed']].to_dict(orient='records')}")
    return checks_frame, {"episodes": episode_days, "statistical_origin_count": int(len(origins))}


def _week_id_for_day(deadlines: Iterable[Any], delivery_day: str) -> str:
    for deadline in deadlines:
        if delivery_day in deadline.included_delivery_days:
            return deadline.week_id
    raise KeyError(delivery_day)


def _accepted_status(status: str, termination: str | None, mip_gap: float | None, max_gap: float) -> bool:
    status_text = str(status).strip().lower()
    termination_text = str(termination or "").strip().lower()
    solver_optimal = status_text in {"ok", "optimal"} and termination_text in {
        "optimal",
        "globallyoptimal",
        "globally optimal",
    }
    return solver_optimal and (mip_gap is None or float(mip_gap) <= float(max_gap) + 1e-12)


def run_rolling_policy(
    *,
    config_id: str,
    policy: str,
    episode_id: str,
    episode_days: list[str],
    scenario_30: pd.DataFrame,
    scenario_10: pd.DataFrame,
    actuals: pd.DataFrame,
    hydrogen_config: HydrogenConfig,
    comparison_config: dict[str, Any],
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    input_resolution_started = perf_counter()
    performance_mode = str(
        comparison_config.get("performance", {}).get(
            "performance_mode", comparison_config.get("performance_mode", "optimized_equivalent")
        )
    )
    delta_t = hydrogen_config.delta_t_hours
    state = RollingHydrogenState(
        episode_id=episode_id,
        storage_inventory_kg=float(hydrogen_config.hydrogen_system.storage_initial_kg),
        previous_electrolyser_power_mw=0.0,
        previous_electrolyser_on=0,
    )
    deadlines = build_weekly_quota_deadlines(
        episode_id=episode_id,
        included_delivery_days=episode_days,
        daily_target_kg=float(comparison_config["daily_target_kg"]),
    )
    daily_rows: list[dict[str, Any]] = []
    dispatch_rows: list[pd.DataFrame] = []
    solver_rows: list[dict[str, Any]] = []
    policy_scenarios, override_grid = build_policy_scenarios(
        policy=policy, scenario_30=scenario_30, scenario_10=scenario_10, actuals=actuals
    )
    lead0 = scenario_30.loc[scenario_30["lead_day"].eq(0)].copy()
    lead0["delivery_day"] = _delivery_day(lead0).astype(str)
    origin_by_day = lead0[["delivery_day", "forecast_origin_utc"]].drop_duplicates().set_index("delivery_day")["forecast_origin_utc"]
    horizon_by_origin = {
        pd.Timestamp(origin): group.copy()
        for origin, group in policy_scenarios.groupby("forecast_origin_utc", sort=False)
    }
    actuals_indexed = actuals.copy()
    actuals_indexed["delivery_day"] = _delivery_day(actuals_indexed).astype(str)
    actual_by_origin_day = {
        (pd.Timestamp(origin), str(day)): group[["delivery_start_utc", "actual_price_eur_per_mwh"]].copy()
        for (origin, day), group in actuals_indexed.groupby(
            ["forecast_origin_utc", "delivery_day"], sort=False
        )
    }
    input_resolution_seconds = perf_counter() - input_resolution_started
    initial_inventory = float(state.storage_inventory_kg)
    warm_start_snapshot = None

    for delivery_day in episode_days:
        day_started = perf_counter()
        storage_start = float(state.storage_inventory_kg)
        power_start = float(state.previous_electrolyser_power_mw)
        origin = pd.Timestamp(origin_by_day.loc[delivery_day])
        array_started = perf_counter()
        horizon = horizon_by_origin.get(origin)
        if horizon is not None:
            horizon = horizon.copy(deep=False)
        if horizon is None or horizon.empty:
            raise ValueError(f"No scenarios for {config_id}/{policy}/{delivery_day}")
        actual_day = actual_by_origin_day.get((origin, str(delivery_day)))
        if actual_day is None or actual_day.empty:
            raise ValueError(f"No actuals for {config_id}/{policy}/{delivery_day}")
        horizon_timestamps = pd.DatetimeIndex(sorted(horizon["delivery_start_utc"].unique()))
        quota_plan = build_weekly_quota_deadline_plan(
            episode_id=episode_id,
            included_delivery_days=episode_days,
            timestamps_utc=horizon_timestamps,
            realised_compression_by_week_kg=state.realised_compression_by_week_kg,
            hydrogen=hydrogen_config.hydrogen_system,
            daily_target_kg=float(comparison_config["daily_target_kg"]),
            delta_t_hours=delta_t,
        )
        array_preparation_seconds = perf_counter() - array_started
        bidding = solve_stochastic_da_bidding(
            granularity=hydrogen_config.experiment.granularity,
            horizon=hydrogen_config.experiment.horizon_mode,
            scenarios=horizon,
            config=hydrogen_config,
            run_id=run_id,
            strategy_name=policy,
            bid_price_grid_eur_per_mwh=(override_grid or hydrogen_config.bidding.bid_price_grid_eur_per_mwh),
            risk_measure="risk_neutral",
            cvar_alpha=float(comparison_config["cvar_alpha"]),
            cvar_gamma=0.0,
            production_target_mode="current_soft_target",
            inventory_start_kg=float(state.storage_inventory_kg),
            reserve_kg=float(hydrogen_config.hydrogen_system.reserve_kg),
            target_hydrogen_min_kg=0.0,
            terminal_reference_start_kg=float(state.storage_inventory_kg),
            emergency_import_price_eur_per_mwh=float(comparison_config["emergency_import_price_eur_per_mwh"]),
            previous_electrolyser_power_mw=float(state.previous_electrolyser_power_mw),
            weekly_quota_plan=quota_plan,
            performance_mode=performance_mode,
            warm_start_snapshot=warm_start_snapshot,
            output_extraction_mode=str(
                comparison_config.get("performance", {}).get(
                    "output_extraction", "executed_day_only"
                )
            ),
            executed_timestamps_utc=pd.DatetimeIndex(actual_day["delivery_start_utc"]),
        )
        warm_start_snapshot = bidding.warm_start_snapshot
        bids = bidding.submitted_bids.copy()
        executed_timestamps = set(pd.DatetimeIndex(actual_day["delivery_start_utc"]))
        executed_bids = bids.loc[bids["delivery_start_utc"].isin(executed_timestamps)].copy()
        clearing = clear_da_bids(executed_bids, actual_day)
        profile = aggregate_cleared_energy(clearing)
        profile["timestep_hours"] = delta_t
        profile["forecast_model"] = config_id
        profile["scenario_model"] = config_id
        profile["redispatch_case"] = policy
        day_quota_plan = build_weekly_quota_deadline_plan(
            episode_id=episode_id,
            included_delivery_days=episode_days,
            timestamps_utc=pd.DatetimeIndex(profile["delivery_start_utc"]),
            realised_compression_by_week_kg=state.realised_compression_by_week_kg,
            hydrogen=hydrogen_config.hydrogen_system,
            daily_target_kg=float(comparison_config["daily_target_kg"]),
            delta_t_hours=delta_t,
        )
        redispatch = solve_actual_redispatch_from_cleared_energy(
            profile,
            config=hydrogen_config,
            inventory_start_kg=float(state.storage_inventory_kg),
            reserve_kg=float(hydrogen_config.hydrogen_system.reserve_kg),
            target_hydrogen_kg=0.0,
            terminal_reference_start_kg=float(state.storage_inventory_kg),
            production_target_mode="current_soft_target",
            emergency_import_price_eur_per_mwh=float(comparison_config["emergency_import_price_eur_per_mwh"]),
            previous_electrolyser_power_mw=float(state.previous_electrolyser_power_mw),
            weekly_quota_plan=day_quota_plan,
            performance_mode=performance_mode,
        )
        dispatch = redispatch.timeseries.copy()
        summary = redispatch.summary.iloc[0].to_dict()
        week_id = _week_id_for_day(deadlines, delivery_day)
        produced = float(summary["hydrogen_compressed_or_sold_kg"])
        state.realised_compression_by_week_kg[week_id] = float(
            state.realised_compression_by_week_kg.get(week_id, 0.0) + produced
        )
        state.fulfilled_quota_by_week_kg[week_id] = min(
            state.realised_compression_by_week_kg[week_id],
            next(item.required_quantity_kg for item in deadlines if item.week_id == week_id),
        )
        state.storage_inventory_kg = float(dispatch["H_buf_kg"].iloc[-1])
        state.previous_electrolyser_power_mw = float(dispatch["P_el_mw"].iloc[-1])
        state.previous_electrolyser_on = int(round(float(dispatch["u_el"].iloc[-1])))
        state.last_executed_timestamp_utc = pd.Timestamp(dispatch["delivery_start_utc"].iloc[-1]).isoformat()

        prices = actual_day["actual_price_eur_per_mwh"].astype(float)
        cleared = profile["cleared_energy_mwh"].astype(float)
        q25, q75 = float(prices.quantile(0.25)), float(prices.quantile(0.75))
        total_energy = float(cleared.sum())
        terminal_correction = float(summary.get("terminal_inventory_correction_eur", 0.0))
        realised_profit_ex_terminal = float(summary["realised_adjusted_profit_eur"] - terminal_correction)
        bidding_summary = bidding.summary.iloc[0].to_dict()
        daily_rows.append(
            {
                "episode_id": episode_id,
                "configuration": config_id,
                "policy": policy,
                "delivery_day": delivery_day,
                "forecast_origin_utc": origin,
                "realised_adjusted_profit_ex_terminal_eur": realised_profit_ex_terminal,
                "planning_horizon_expected_adjusted_profit_eur": float(
                    bidding_summary.get("expected_adjusted_profit_eur", np.nan)
                ),
                "equivalent_net_cost_eur": -realised_profit_ex_terminal,
                "da_cost_eur": float(summary["realised_DA_settlement_cost_eur"]),
                "average_paid_price_eur_per_mwh": float(summary["realised_DA_settlement_cost_eur"] / total_energy) if total_energy > 1e-12 else np.nan,
                "hydrogen_produced_kg": float(summary["hydrogen_produced_kg"]),
                "hydrogen_compressed_kg": produced,
                "shortfall_kg": float(summary["shortfall_kg"]),
                "emergency_import_mwh": float(summary["emergency_import_mwh"]),
                "emergency_import_cost_eur": float(summary["emergency_import_cost_eur"]),
                "storage_min_kg": float(summary["storage_min_kg"]),
                "storage_max_kg": float(summary["storage_max_kg"]),
                "storage_start_kg": storage_start,
                "storage_end_kg": float(state.storage_inventory_kg),
                "electrolyser_power_start_mw": power_start,
                "electrolyser_power_end_mw": float(state.previous_electrolyser_power_mw),
                "weekly_quota_id": week_id,
                "weekly_quota_progress_kg": float(state.realised_compression_by_week_kg[week_id]),
                "high_price_energy_share": float(cleared.loc[prices.ge(q75).to_numpy()].sum() / total_energy) if total_energy > 1e-12 else np.nan,
                "high_price_avoidance": float(1.0 - cleared.loc[prices.ge(q75).to_numpy()].sum() / total_energy) if total_energy > 1e-12 else np.nan,
                "low_price_energy_share": float(cleared.loc[prices.le(q25).to_numpy()].sum() / total_energy) if total_energy > 1e-12 else np.nan,
                "low_price_capture": float(cleared.loc[prices.le(q25).to_numpy()].sum() / total_energy) if total_energy > 1e-12 else np.nan,
                "wall_time_seconds": perf_counter() - day_started,
            }
        )
        dispatch.insert(0, "delivery_day", delivery_day)
        dispatch.insert(0, "policy", policy)
        dispatch.insert(0, "configuration", config_id)
        dispatch.insert(0, "episode_id", episode_id)
        dispatch_rows.append(dispatch)
        for stage, result in (("bidding", bidding), ("redispatch", redispatch)):
            performance = getattr(result, "performance", None) or {}
            solver_rows.append(
                {
                    "episode_id": episode_id,
                    "configuration": config_id,
                    "policy": policy,
                    "delivery_day": delivery_day,
                    "stage": stage,
                    "solver_status": result.solver.status,
                    "termination_condition": result.solver.termination_condition,
                    "objective_value": result.solver.objective_value,
                    "runtime_seconds": result.solver.runtime_seconds,
                    "build_time_seconds": result.solver.model_build_time_seconds,
                    "solver_time_seconds": result.solver.solver_time_seconds,
                    "postprocess_time_seconds": result.solver.postprocess_time_seconds,
                    "model_build_seconds": result.solver.model_build_time_seconds,
                    "presolve_solver_seconds": result.solver.solver_time_seconds,
                    "postprocessing_seconds": result.solver.postprocess_time_seconds,
                    "wall_time_seconds": result.solver.runtime_seconds,
                    "mip_gap": result.solver.mip_gap,
                    "variables": result.model_stats.variable_count,
                    "binaries": result.model_stats.binary_variable_count,
                    "constraints": result.model_stats.constraint_count,
                    "horizon_steps": result.model_stats.horizon_steps,
                    "scenario_count": result.model_stats.scenario_count,
                    "timesteps": result.model_stats.horizon_steps,
                    "scenarios": result.model_stats.scenario_count,
                    "timestep_hours": result.model_stats.timestep_hours,
                    "performance_mode": performance_mode,
                    "input_resolution_seconds": (
                        input_resolution_seconds / max(len(episode_days), 1) if stage == "bidding" else 0.0
                    ),
                    "array_preparation_seconds": array_preparation_seconds if stage == "bidding" else 0.0,
                    "dataframe_construction_seconds": result.solver.postprocess_time_seconds,
                    "output_io_seconds": 0.0,
                    "peak_working_set_mb": peak_working_set_mb(),
                    "bid_ladder_steps": len(override_grid or hydrogen_config.bidding.bid_price_grid_eur_per_mwh),
                    "structural_signature": performance.get("structural_signature"),
                    "model_reuse_status": performance.get("model_reuse_status", "not_supported"),
                    "cache_status": performance.get("cache_status", "not_supported"),
                    "warm_start_status": performance.get("warm_start_status", "not_supported"),
                    "warm_start_values_applied": performance.get("warm_start_values_applied", 0),
                    "pyomo_model_rebuilt": performance.get("pyomo_model_rebuilt", True),
                    "accepted_for_headline": _accepted_status(
                        result.solver.status,
                        result.solver.termination_condition,
                        result.solver.mip_gap,
                        float(comparison_config["solver"]["mip_gap"]),
                    ),
                }
            )

    daily = pd.DataFrame(daily_rows)
    terminal_episode_correction = float(
        hydrogen_config.terminal_inventory_value_per_kg * (state.storage_inventory_kg - initial_inventory)
    )
    metadata = {
        "episode_id": episode_id,
        "configuration": config_id,
        "policy": policy,
        "initial_inventory_kg": initial_inventory,
        "final_inventory_kg": state.storage_inventory_kg,
        "episode_terminal_inventory_correction_eur": terminal_episode_correction,
        "episode_realised_adjusted_profit_eur": float(daily["realised_adjusted_profit_ex_terminal_eur"].sum() + terminal_episode_correction),
        "weekly_quota_realised_kg": state.realised_compression_by_week_kg,
        "weekly_quota_required_kg": {item.week_id: item.required_quantity_kg for item in deadlines},
    }
    return daily, pd.concat(dispatch_rows, ignore_index=True), pd.DataFrame(solver_rows), metadata


def circular_moving_block_bootstrap(
    values: np.ndarray, *, draws: int = 10_000, block_length: int = 7, seed: int = 42
) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {"mean": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    rng = np.random.default_rng(seed)
    n = len(values)
    blocks = int(np.ceil(n / block_length))
    estimates = np.empty(draws, dtype=float)
    offsets = np.arange(block_length)
    for draw in range(draws):
        starts = rng.integers(0, n, size=blocks)
        indices = ((starts[:, None] + offsets[None, :]) % n).reshape(-1)[:n]
        estimates[draw] = float(values[indices].mean())
    low, high = np.quantile(estimates, [0.025, 0.975])
    return {"mean": float(values.mean()), "ci_low": float(low), "ci_high": float(high)}


def build_comparison_tables(daily: pd.DataFrame, metadata: pd.DataFrame, bootstrap_cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    aggregate = daily.groupby(["episode_id", "configuration", "policy"], as_index=False).agg(
        realised_adjusted_profit_ex_terminal_eur=("realised_adjusted_profit_ex_terminal_eur", "sum"),
        da_cost_eur=("da_cost_eur", "sum"),
        hydrogen_produced_kg=("hydrogen_produced_kg", "sum"),
        hydrogen_compressed_kg=("hydrogen_compressed_kg", "sum"),
        shortfall_kg=("shortfall_kg", "sum"),
        emergency_import_mwh=("emergency_import_mwh", "sum"),
        emergency_import_cost_eur=("emergency_import_cost_eur", "sum"),
        mean_high_price_energy_share=("high_price_energy_share", "mean"),
        mean_low_price_energy_share=("low_price_energy_share", "mean"),
        wall_time_seconds=("wall_time_seconds", "sum"),
        execution_days=("delivery_day", "nunique"),
    ).merge(metadata, on=["episode_id", "configuration", "policy"], validate="one_to_one")
    aggregate["realised_adjusted_profit_eur"] = (
        aggregate["realised_adjusted_profit_ex_terminal_eur"] + aggregate["episode_terminal_inventory_correction_eur"]
    )
    lookup = aggregate.set_index(["episode_id", "configuration", "policy"])["realised_adjusted_profit_eur"]
    def benchmark_value(row: Any, policy: str) -> float:
        key = (row.episode_id, row.configuration, policy)
        return float(lookup.loc[key]) if key in lookup.index else np.nan

    price_insensitive = [benchmark_value(row, "price_insensitive") for row in aggregate.itertuples()]
    perfect_foresight = [benchmark_value(row, "true_pf") for row in aggregate.itertuples()]
    aggregate["uplift_vs_price_insensitive_eur"] = [
        row.realised_adjusted_profit_eur - benchmark if np.isfinite(benchmark) else np.nan
        for row, benchmark in zip(aggregate.itertuples(), price_insensitive)
    ]
    aggregate["oracle_regret_eur"] = [
        benchmark - row.realised_adjusted_profit_eur if np.isfinite(benchmark) else np.nan
        for row, benchmark in zip(aggregate.itertuples(), perfect_foresight)
    ]
    denominators = [
        pf - pi if np.isfinite(pf) and np.isfinite(pi) else np.nan
        for pf, pi in zip(perfect_foresight, price_insensitive)
    ]
    aggregate["value_captured"] = [
        row.uplift_vs_price_insensitive_eur / denom if np.isfinite(denom) and denom > 1e-8 else np.nan
        for row, denom in zip(aggregate.itertuples(), denominators)
    ]

    effects: list[dict[str, Any]] = []
    primary = daily.loc[daily["episode_id"].eq("primary")].copy()
    for policy in ("stochastic_30", "stochastic_10", "ev_30"):
        pivot = primary.loc[primary["policy"].eq(policy)].pivot(
            index="delivery_day", columns="configuration", values="realised_adjusted_profit_ex_terminal_eur"
        )
        for label, lhs, rhs in (
            ("horizon_value", "H-D4", "H-D"),
            ("granularity_value", "QH-D4", "H-D4"),
            ("total_value", "QH-D4", "H-D"),
        ):
            if lhs not in pivot or rhs not in pivot:
                continue
            difference = (pivot[lhs] - pivot[rhs]).dropna().to_numpy()
            for block_length in [
                int(bootstrap_cfg["primary_block_length_days"]),
                *[int(value) for value in bootstrap_cfg["sensitivity_block_lengths_days"]],
            ]:
                result = circular_moving_block_bootstrap(
                    difference,
                    draws=int(bootstrap_cfg["draws"]),
                    block_length=block_length,
                    seed=int(bootstrap_cfg["seed"]),
                )
                effects.append(
                    {
                        "effect": label,
                        "policy": policy,
                        "lhs": lhs,
                        "rhs": rhs,
                        "paired_days": len(difference),
                        "block_length_days": block_length,
                        "mean_daily_effect_eur": result["mean"],
                        "ci95_low_eur_per_day": result["ci_low"],
                        "ci95_high_eur_per_day": result["ci_high"],
                        "total_observed_effect_eur": float(difference.sum()),
                    }
                )
    return aggregate, pd.DataFrame(effects)


def write_run_governance(
    *, run_dir: Path, comparison_dir: Path, config: dict[str, Any], config_path: Path, input_paths: list[Path]
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    comparison_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": {"path": str(config_path), "sha256": _sha256(config_path)},
        "inputs": [
            {"path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256(path)} for path in input_paths
        ],
    }
    (run_dir / "input_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n- " + "\n- ".join([SCENARIO_UNDERCOVERAGE_WARNING, *config["methodological_warnings"]]) + "\n",
        encoding="utf-8",
    )
    registry = {
        "run_class": config["outputs"]["run_class"],
        "lineage_role": config["outputs"]["lineage_role"],
        "parent_output_policy": config["outputs"]["parent_output_policy"],
        "child_output_policy": config["outputs"]["child_output_policy"],
    }
    (run_dir / "registry_entry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")


def resolved_hydrogen_config(
    base: HydrogenConfig, *, granularity: str, horizon_mode: str, comparison_config: dict[str, Any]
) -> HydrogenConfig:
    return replace(
        base,
        experiment=replace(base.experiment, granularity=granularity, horizon_mode=horizon_mode),
        risk=replace(base.risk, gamma=0.0, gamma_grid=(0.0,), gamma_selection="frozen_risk_neutral"),
        solver=replace(
            base.solver,
            mip_gap=float(comparison_config["solver"]["mip_gap"]),
            time_limit_seconds=int(comparison_config["solver"]["time_limit_seconds"]),
        ),
        outputs=replace(base.outputs, save_figures=False, save_solver_log=False),
    )
