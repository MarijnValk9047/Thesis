from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .bidding import build_bid_curve_dataframe, validate_bid_price_grid
from .bidding_metrics import (
    compute_stochastic_expected_bid_metrics,
    compute_stochastic_scenario_clearing_metrics,
)
from .cvar import WeightedCvarResult, compute_weighted_cvar_from_frame
from .mfrr_da_recourse import align_hourly_da_obligations_to_delivery_hours
from .optimisation_model import (
    ModelStats,
    SolverResult,
    _apply_gurobi_license_env,
    _ensure_solver_package,
    _pulp_model_stats,
    _pyomo_model_stats,
    _resolve_pulp_solver,
    _resolve_pyomo_solver,
    pulp,
    pyo,
)
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .plots import (
    plot_scenario_cleared_used_unused_energy,
    plot_scenario_clearing_heatmap,
    plot_scenario_profit_distribution,
    plot_scenario_storage_trajectories,
    plot_submitted_bid_curves_for_hours,
)
from .run_registry import (
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
)


TOY_BIDDING_STRATEGY = "stochastic_hourly_bidding_toy"
TOY_BID_REGULARISATION_EUR_PER_MW = 1e-4


@dataclass(frozen=True)
class StochasticBiddingSolveResult:
    submitted_bids: pd.DataFrame
    scenario_clearing: pd.DataFrame
    scenario_dispatch: pd.DataFrame
    scenario_economics: pd.DataFrame
    summary: pd.DataFrame
    solver: SolverResult
    model_stats: ModelStats
    acceptance_table: pd.DataFrame
    risk_measure: str
    cvar_alpha: float | None
    cvar_gamma: float
    zeta_loss_eur: float | None
    cvar_loss_eur: float | None
    cvar_details: pd.DataFrame
    reserve_diagnostics: dict[str, Any]


@dataclass(frozen=True)
class PreparedReserveObligations:
    aligned: pd.DataFrame
    up_by_time_index: dict[int, float]
    down_by_time_index: dict[int, float]
    reserve_obligation_hours_count: int
    reserve_constraints_added_count: int
    max_required_up_reserve_mw: float
    max_required_down_reserve_mw: float
    energy_bid_obligation_hours_count: int
    joint_up_down_hours_count: int


def _empty_reserve_diagnostics() -> dict[str, Any]:
    return {
        "reserve_hook_active": False,
        "electrical_reserve_preservation_only": True,
        "reserve_obligation_hours_count": 0,
        "reserve_constraints_added_count": 0,
        "energy_bid_obligation_hours_count": 0,
        "joint_up_down_hours_count": 0,
        "max_required_up_reserve_mw": 0.0,
        "max_required_down_reserve_mw": 0.0,
        "min_available_up_reserve_mw": None,
        "min_available_down_reserve_mw": None,
    }


def _prepare_reserve_obligations(
    *,
    reserve_obligations_by_hour: pd.DataFrame | None,
    timestamps: pd.DatetimeIndex,
    site_max_load_mw: float,
    scenario_count: int,
) -> PreparedReserveObligations | None:
    if reserve_obligations_by_hour is None:
        return None
    if not isinstance(reserve_obligations_by_hour, pd.DataFrame):
        raise TypeError("reserve_obligations_by_hour must be a pandas DataFrame when provided.")

    aligned = align_hourly_da_obligations_to_delivery_hours(
        reserve_obligations_by_hour,
        delivery_timestamps_utc=timestamps,
        site_max_load_mw=float(site_max_load_mw),
    ).copy()
    aligned["accepted_up_reserve_mw_for_da"] = pd.to_numeric(
        aligned["accepted_up_reserve_mw_for_da"],
        errors="raise",
    )
    aligned["accepted_down_reserve_mw_for_da"] = pd.to_numeric(
        aligned["accepted_down_reserve_mw_for_da"],
        errors="raise",
    )
    if (aligned["accepted_up_reserve_mw_for_da"] < -1e-9).any():
        raise ValueError("accepted_up_reserve_mw_for_da must be nonnegative after alignment.")
    if (aligned["accepted_down_reserve_mw_for_da"] < -1e-9).any():
        raise ValueError("accepted_down_reserve_mw_for_da must be nonnegative after alignment.")
    joint = (
        aligned["accepted_up_reserve_mw_for_da"].astype(float)
        + aligned["accepted_down_reserve_mw_for_da"].astype(float)
    )
    infeasible_joint = aligned.loc[joint > float(site_max_load_mw) + 1e-9, [
        "delivery_timestamp",
        "accepted_up_reserve_mw_for_da",
        "accepted_down_reserve_mw_for_da",
    ]]
    if not infeasible_joint.empty:
        raise ValueError(
            "Accepted Up and Down reserve obligations exceed site_max_load_mw in the same delivery hour. "
            f"Example rows={infeasible_joint.head(3).to_dict(orient='records')}"
        )

    up_by_time_index = {
        int(idx): float(value)
        for idx, value in enumerate(aligned["accepted_up_reserve_mw_for_da"].astype(float).tolist())
    }
    down_by_time_index = {
        int(idx): float(value)
        for idx, value in enumerate(aligned["accepted_down_reserve_mw_for_da"].astype(float).tolist())
    }
    positive_up_hours = int((aligned["accepted_up_reserve_mw_for_da"].astype(float) > 1e-9).sum())
    positive_down_hours = int((aligned["accepted_down_reserve_mw_for_da"].astype(float) > 1e-9).sum())
    reserve_hour_mask = (
        (aligned["accepted_up_reserve_mw_for_da"].astype(float) > 1e-9)
        | (aligned["accepted_down_reserve_mw_for_da"].astype(float) > 1e-9)
    )
    return PreparedReserveObligations(
        aligned=aligned,
        up_by_time_index=up_by_time_index,
        down_by_time_index=down_by_time_index,
        reserve_obligation_hours_count=int(reserve_hour_mask.sum()),
        reserve_constraints_added_count=int(scenario_count * (positive_up_hours + positive_down_hours)),
        max_required_up_reserve_mw=float(aligned["accepted_up_reserve_mw_for_da"].max()),
        max_required_down_reserve_mw=float(aligned["accepted_down_reserve_mw_for_da"].max()),
        energy_bid_obligation_hours_count=int(aligned["energy_bid_obligation_created"].astype(bool).sum()),
        joint_up_down_hours_count=int(
            (
                (aligned["accepted_up_reserve_mw_for_da"].astype(float) > 1e-9)
                & (aligned["accepted_down_reserve_mw_for_da"].astype(float) > 1e-9)
            ).sum()
        ),
    )


def _build_reserve_diagnostics(
    prepared: PreparedReserveObligations | None,
    *,
    scenario_dispatch: pd.DataFrame | None = None,
    site_max_load_mw: float | None = None,
) -> dict[str, Any]:
    diagnostics = _empty_reserve_diagnostics()
    if prepared is None:
        return diagnostics
    diagnostics.update(
        {
            "reserve_hook_active": True,
            "reserve_obligation_hours_count": int(prepared.reserve_obligation_hours_count),
            "reserve_constraints_added_count": int(prepared.reserve_constraints_added_count),
            "energy_bid_obligation_hours_count": int(prepared.energy_bid_obligation_hours_count),
            "joint_up_down_hours_count": int(prepared.joint_up_down_hours_count),
            "max_required_up_reserve_mw": float(prepared.max_required_up_reserve_mw),
            "max_required_down_reserve_mw": float(prepared.max_required_down_reserve_mw),
        }
    )
    if scenario_dispatch is None or site_max_load_mw is None:
        return diagnostics

    dispatch = scenario_dispatch.copy()
    dispatch["delivery_start_utc"] = pd.to_datetime(dispatch["delivery_start_utc"], utc=True, errors="raise")
    dispatch["site_load_mw"] = dispatch["P_el_mw"].astype(float) + dispatch["P_comp_mw"].astype(float)
    dispatch["available_down_reserve_mw"] = float(site_max_load_mw) - dispatch["site_load_mw"].astype(float)

    up_hours = set(
        prepared.aligned.loc[
            prepared.aligned["accepted_up_reserve_mw_for_da"].astype(float) > 1e-9,
            "delivery_timestamp",
        ].tolist()
    )
    down_hours = set(
        prepared.aligned.loc[
            prepared.aligned["accepted_down_reserve_mw_for_da"].astype(float) > 1e-9,
            "delivery_timestamp",
        ].tolist()
    )
    if up_hours:
        diagnostics["min_available_up_reserve_mw"] = float(
            dispatch.loc[dispatch["delivery_start_utc"].isin(list(up_hours)), "site_load_mw"].min()
        )
    if down_hours:
        diagnostics["min_available_down_reserve_mw"] = float(
            dispatch.loc[dispatch["delivery_start_utc"].isin(list(down_hours)), "available_down_reserve_mw"].min()
        )
    return diagnostics


def build_toy_hourly_scenario_set(
    case_name: str = "mixed_clearing",
    *,
    forecast_origin_utc: str = "2024-12-31T07:00:00Z",
) -> pd.DataFrame:
    scenario_map: dict[str, dict[str, Any]] = {
        "mixed_clearing": {
            "scenario_source": "artificial_phase4a_toy",
            "probabilities": {"low": 0.50, "medium": 0.30, "high": 0.20},
            "prices": {
                "low": [70.0, 90.0, 120.0, 140.0],
                "medium": [130.0, 160.0, 180.0, 210.0],
                "high": [220.0, 240.0, 260.0, 290.0],
            },
        },
        "full_clearing": {
            "scenario_source": "artificial_phase4a_toy",
            "probabilities": {"low": 0.40, "medium": 0.35, "high": 0.25},
            "prices": {
                "low": [40.0, 60.0, 80.0, 100.0],
                "medium": [90.0, 110.0, 120.0, 140.0],
                "high": [150.0, 170.0, 190.0, 210.0],
            },
        },
        "no_clearing": {
            "scenario_source": "artificial_phase4a_toy",
            "probabilities": {"high_1": 0.60, "high_2": 0.40},
            "prices": {
                "high_1": [400.0, 420.0, 430.0, 450.0],
                "high_2": [460.0, 470.0, 480.0, 500.0],
            },
        },
        "cvar_stress": {
            "scenario_source": "artificial_phase5a_toy",
            "probabilities": {"low": 0.55, "medium": 0.25, "stress": 0.20},
            "prices": {
                "low": [65.0, 85.0, 105.0, 125.0],
                "medium": [135.0, 160.0, 190.0, 220.0],
                "stress": [250.0, 340.0, 520.0, 760.0],
            },
        },
        "cvar_high_price_exposure": {
            "scenario_source": "artificial_phase5b_toy",
            "probabilities": {"low": 0.60, "mid": 0.25, "stress": 0.15},
            "prices": {
                "low": [70.0, 70.0, 70.0, 70.0, 70.0, 70.0],
                "mid": [70.0, 70.0, 70.0, 70.0, 180.0, 180.0],
                "stress": [70.0, 70.0, 70.0, 70.0, 400.0, 800.0],
            },
        },
        "cvar_overprocurement_unused_energy": {
            "scenario_source": "artificial_phase5b_toy",
            "probabilities": {"low": 0.60, "delayed": 0.25, "stress": 0.15},
            "prices": {
                "low": [60.0, 60.0, 60.0, 60.0],
                "delayed": [500.0, 60.0, 60.0, 60.0],
                "stress": [500.0, 240.0, 500.0, 500.0],
            },
        },
    }
    if case_name not in scenario_map:
        raise ValueError(f"Unknown toy scenario case: {case_name}")

    spec = scenario_map[case_name]
    periods = len(next(iter(spec["prices"].values())))
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=periods, freq="h", tz="UTC")
    forecast_origin = pd.Timestamp(pd.to_datetime(forecast_origin_utc, utc=True, errors="raise"))
    rows: list[dict[str, Any]] = []
    for scenario_id, path in spec["prices"].items():
        probability = float(spec["probabilities"][scenario_id])
        for timestamp, price in zip(timestamps, path, strict=True):
            rows.append(
                {
                    "forecast_origin_utc": forecast_origin,
                    "delivery_start_utc": pd.Timestamp(timestamp),
                    "scenario_id": str(scenario_id),
                    "scenario_probability": probability,
                    "scenario_price_eur_per_mwh": float(price),
                    "granularity": "hourly",
                    "lead_day": 0,
                    "toy_case": case_name,
                    "scenario_source": str(spec.get("scenario_source", "artificial_toy")),
                }
            )
    return pd.DataFrame(rows)


def build_phase4a_toy_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    experiment_name: str = "hydrogen_phase4a_toy_stochastic_bidding",
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    return replace(
        base,
        experiment=replace(
            base.experiment,
            name=experiment_name,
            execution_mode="toy_scenarios",
            custom_start="2025-01-01",
            custom_end="2025-01-01",
        ),
        economics=replace(
            base.economics,
            daily_target_kg=5200.0,
            shortfall_penalty_eur_per_kg=2.0,
        ),
    )


def build_phase5a_toy_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    experiment_name: str = "hydrogen_phase5a_toy_cvar_stochastic_bidding",
) -> HydrogenConfig:
    base = build_phase4a_toy_config(config_or_path, experiment_name=experiment_name)
    return replace(
        base,
        experiment=replace(base.experiment, name=experiment_name),
        economics=replace(base.economics, shortfall_penalty_eur_per_kg=10.0),
    )


def build_phase5b_toy_case_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    toy_case: str,
    experiment_name: str = "hydrogen_phase5b_toy_cvar_case_validation",
) -> HydrogenConfig:
    base = build_phase5a_toy_config(config_or_path, experiment_name=experiment_name)
    if toy_case == "cvar_high_price_exposure":
        return replace(
            base,
            experiment=replace(base.experiment, name=experiment_name),
            economics=replace(
                base.economics,
                daily_target_kg=8000.0,
                shortfall_penalty_eur_per_kg=8.0,
            ),
        )
    if toy_case == "cvar_overprocurement_unused_energy":
        return replace(
            base,
            experiment=replace(base.experiment, name=experiment_name),
            economics=replace(
                base.economics,
                daily_target_kg=2500.0,
                shortfall_penalty_eur_per_kg=4.0,
                unused_energy_penalty_eur_per_mwh=10.0,
            ),
        )
    raise ValueError(f"Unsupported Phase 5b toy case: {toy_case!r}")


def validate_toy_scenario_probabilities(scenarios: pd.DataFrame, tolerance: float = 1e-9) -> float:
    required = {
        "forecast_origin_utc",
        "delivery_start_utc",
        "scenario_id",
        "scenario_probability",
        "scenario_price_eur_per_mwh",
    }
    missing = required.difference(scenarios.columns)
    if missing:
        raise ValueError(f"Scenario frame is missing required columns: {sorted(missing)}")

    probabilities = (
        scenarios[["scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["scenario_id"])
        .sort_values("scenario_id")
    )
    total_probability = float(probabilities["scenario_probability"].sum())
    if abs(total_probability - 1.0) > tolerance:
        raise ValueError(f"Scenario probabilities must sum to 1.0, got {total_probability:.12f}")
    if (probabilities["scenario_probability"].astype(float) < -tolerance).any():
        raise ValueError("Scenario probabilities must be nonnegative.")
    return total_probability


def build_scenario_acceptance_table(
    scenarios: pd.DataFrame,
    bid_price_grid_eur_per_mwh: list[float] | tuple[float, ...],
) -> pd.DataFrame:
    grid = validate_bid_price_grid(bid_price_grid_eur_per_mwh)
    validate_toy_scenario_probabilities(scenarios)

    frame = scenarios.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    frame["scenario_price_eur_per_mwh"] = pd.to_numeric(frame["scenario_price_eur_per_mwh"], errors="raise")
    rows: list[dict[str, Any]] = []
    for row in frame.sort_values(["scenario_id", "delivery_start_utc"]).to_dict(orient="records"):
        for block_idx, bid_price in enumerate(grid):
            rows.append(
                {
                    "forecast_origin_utc": row["forecast_origin_utc"],
                    "delivery_start_utc": row["delivery_start_utc"],
                    "scenario_id": str(row["scenario_id"]),
                    "scenario_probability": float(row["scenario_probability"]),
                    "scenario_price_eur_per_mwh": float(row["scenario_price_eur_per_mwh"]),
                    "bid_block": int(block_idx),
                    "bid_price_eur_per_mwh": float(bid_price),
                    "accepted": bool(float(bid_price) >= float(row["scenario_price_eur_per_mwh"])),
                    "acceptance_indicator": int(float(bid_price) >= float(row["scenario_price_eur_per_mwh"])),
                }
            )
    return pd.DataFrame(rows)


def _resolve_price_panel(
    scenarios: pd.DataFrame,
    bid_price_grid_eur_per_mwh: list[float] | tuple[float, ...],
) -> tuple[pd.DatetimeIndex, list[str], list[int], dict[str, float], dict[tuple[str, int], float], dict[tuple[str, int, int], int]]:
    frame = scenarios.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    timestamps = pd.DatetimeIndex(sorted(frame["delivery_start_utc"].drop_duplicates().tolist()))
    scenario_meta = (
        frame[["scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["scenario_id"])
        .sort_values("scenario_id")
        .reset_index(drop=True)
    )
    scenario_ids = scenario_meta["scenario_id"].astype(str).tolist()
    probabilities = {str(row["scenario_id"]): float(row["scenario_probability"]) for row in scenario_meta.to_dict(orient="records")}
    block_ids = list(range(len(validate_bid_price_grid(bid_price_grid_eur_per_mwh))))
    time_index = {timestamp: idx for idx, timestamp in enumerate(timestamps)}
    price_lookup: dict[tuple[str, int], float] = {}
    for row in frame.to_dict(orient="records"):
        price_lookup[(str(row["scenario_id"]), time_index[pd.Timestamp(row["delivery_start_utc"])])] = float(row["scenario_price_eur_per_mwh"])
    acceptance_table = build_scenario_acceptance_table(frame, bid_price_grid_eur_per_mwh)
    acceptance_lookup = {
        (str(row["scenario_id"]), time_index[pd.Timestamp(row["delivery_start_utc"])], int(row["bid_block"])): int(row["acceptance_indicator"])
        for row in acceptance_table.to_dict(orient="records")
    }
    return timestamps, scenario_ids, block_ids, probabilities, price_lookup, acceptance_lookup


def _build_submitted_bids(
    *,
    run_id: str,
    strategy: str,
    scenario_model: str | None,
    timestamps: pd.DatetimeIndex,
    forecast_origin_utc: pd.Timestamp,
    bid_price_grid_eur_per_mwh: list[float],
    q_solution: np.ndarray,
    timestep_hours: float,
) -> pd.DataFrame:
    return build_bid_curve_dataframe(
        run_id=run_id,
        strategy=strategy,
        delivery_start_utc=list(timestamps),
        bid_quantities_mw=q_solution,
        forecast_origin_utc=forecast_origin_utc,
        granularity="hourly",
        horizon="D_only",
        timestep_hours=timestep_hours,
        bid_price_grid=bid_price_grid_eur_per_mwh,
        scenario_model=scenario_model,
        max_total_quantity_mw=None,
    )


def _extract_q_matrix_from_pyomo(model: Any, horizon_steps: int, block_count: int) -> np.ndarray:
    matrix = np.zeros((horizon_steps, block_count), dtype=float)
    for t in range(horizon_steps):
        for b in range(block_count):
            matrix[t, b] = float(pyo.value(model.q[t, b]) or 0.0)
    return matrix


def _extract_q_matrix_from_pulp(q: dict[tuple[int, int], Any], horizon_steps: int, block_count: int) -> np.ndarray:
    matrix = np.zeros((horizon_steps, block_count), dtype=float)
    for t in range(horizon_steps):
        for b in range(block_count):
            matrix[t, b] = float(q[(t, b)].value() or 0.0)
    return matrix


def _normalize_hourly_floor_mw(
    hourly_floor_mw: list[float] | tuple[float, ...] | np.ndarray | None,
    *,
    horizon_steps: int,
    site_max_bid_mw: float,
) -> np.ndarray:
    if hourly_floor_mw is None:
        return np.zeros(horizon_steps, dtype=float)
    values = np.asarray(hourly_floor_mw, dtype=float).reshape(-1)
    if values.shape[0] != int(horizon_steps):
        raise ValueError(
            f"firm_bid_floor_mw must have one value per hour; expected {horizon_steps}, got {values.shape[0]}."
        )
    if not np.isfinite(values).all():
        raise ValueError("firm_bid_floor_mw contains NaN or infinite values.")
    if (values < -1e-9).any():
        raise ValueError("firm_bid_floor_mw cannot contain negative values.")
    if (values > float(site_max_bid_mw) + 1e-9).any():
        raise ValueError(
            f"firm_bid_floor_mw cannot exceed site_max_bid_mw={site_max_bid_mw:.6f}."
        )
    return np.where(values < 0.0, 0.0, values.astype(float))


def _scenario_dispatch_from_pyomo(
    model: Any,
    *,
    strategy: str,
    scenario_model: str | None,
    timestamps: pd.DatetimeIndex,
    scenario_ids: list[str],
    probabilities: dict[str, float],
    price_lookup: dict[tuple[str, int], float],
    acceptance_lookup: dict[tuple[str, int, int], int],
    q_matrix: np.ndarray,
    bid_price_grid_eur_per_mwh: list[float],
    run_id: str,
    forecast_origin_utc: pd.Timestamp,
    timestep_hours: float,
    daily_target_kg: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dispatch_rows: list[dict[str, Any]] = []
    clearing_rows: list[dict[str, Any]] = []
    for scenario_id in scenario_ids:
        scenario_total_hydrogen = 0.0
        for t, timestamp in enumerate(timestamps):
            cleared_energy = float(
                timestep_hours
                * sum(
                    acceptance_lookup[(scenario_id, t, b)] * q_matrix[t, b]
                    for b in range(len(bid_price_grid_eur_per_mwh))
                )
            )
            used_energy = float(pyo.value(model.used_energy[scenario_id, t]) or 0.0)
            unused_energy = float(pyo.value(model.unused_cleared_energy[scenario_id, t]) or 0.0)
            emergency_import = (
                float(pyo.value(model.emergency_import[scenario_id, t]) or 0.0)
                if hasattr(model, "emergency_import")
                else 0.0
            )
            hydrogen_sold = float(pyo.value(model.H_comp[scenario_id, t]) or 0.0)
            scenario_total_hydrogen += hydrogen_sold
            dispatch_rows.append(
                {
                    "run_id": run_id,
                    "strategy": strategy,
                    "forecast_origin_utc": forecast_origin_utc,
                    "scenario_id": scenario_id,
                    "scenario_probability": probabilities[scenario_id],
                    "delivery_start_utc": pd.Timestamp(timestamp),
                    "granularity": "hourly",
                    "horizon": "D_only",
                    "scenario_model": scenario_model,
                    "scenario_price_eur_per_mwh": float(price_lookup[(scenario_id, t)]),
                    "cleared_energy_mwh": cleared_energy,
                    "used_energy_mwh": used_energy,
                    "unused_cleared_energy_mwh": unused_energy,
                    "emergency_import_mwh": emergency_import,
                    "P_el_mw": float(pyo.value(model.P_el[scenario_id, t]) or 0.0),
                    "u_el": float(pyo.value(model.u_el[scenario_id, t]) or 0.0),
                    "H_prod_kg": float(pyo.value(model.H_prod[scenario_id, t]) or 0.0),
                    "P_comp_mw": float(pyo.value(model.P_comp[scenario_id, t]) or 0.0),
                    "H_comp_kg": hydrogen_sold,
                    "H_buf_kg": float(pyo.value(model.H_buf[scenario_id, t]) or 0.0),
                    "shortfall_kg": float(pyo.value(model.shortfall[scenario_id]) or 0.0),
                    "timestep_hours": timestep_hours,
                }
            )
            for b, bid_price in enumerate(bid_price_grid_eur_per_mwh):
                accepted = bool(acceptance_lookup[(scenario_id, t, b)])
                bid_quantity_mw = float(q_matrix[t, b])
                clearing_rows.append(
                    {
                        "run_id": run_id,
                        "strategy": strategy,
                        "forecast_origin_utc": forecast_origin_utc,
                        "scenario_id": scenario_id,
                        "scenario_probability": probabilities[scenario_id],
                        "delivery_start_utc": pd.Timestamp(timestamp),
                        "granularity": "hourly",
                        "horizon": "D_only",
                        "scenario_model": scenario_model,
                        "scenario_price_eur_per_mwh": float(price_lookup[(scenario_id, t)]),
                        "bid_block": int(b),
                        "bid_price_eur_per_mwh": float(bid_price),
                        "bid_quantity_mw": bid_quantity_mw,
                        "accepted": accepted,
                        "cleared_quantity_mw": bid_quantity_mw if accepted else 0.0,
                        "cleared_energy_mwh": timestep_hours * bid_quantity_mw if accepted else 0.0,
                        "timestep_hours": timestep_hours,
                    }
                )
        above_target = max(scenario_total_hydrogen - daily_target_kg, 0.0)
        for row in dispatch_rows[-len(timestamps):]:
            row["hydrogen_above_target_kg"] = above_target
    return pd.DataFrame(dispatch_rows), pd.DataFrame(clearing_rows)


def _scenario_dispatch_from_pulp(
    *,
    strategy: str,
    scenario_model: str | None,
    q: dict[tuple[int, int], Any],
    p_el: dict[tuple[str, int], Any],
    u_el: dict[tuple[str, int], Any],
    h_prod: dict[tuple[str, int], Any],
    p_comp: dict[tuple[str, int], Any],
    h_comp: dict[tuple[str, int], Any],
    h_buf: dict[tuple[str, int], Any],
    used_energy: dict[tuple[str, int], Any],
    unused_energy: dict[tuple[str, int], Any],
    emergency_import: dict[tuple[str, int], Any] | None,
    shortfall: dict[str, Any],
    timestamps: pd.DatetimeIndex,
    scenario_ids: list[str],
    probabilities: dict[str, float],
    price_lookup: dict[tuple[str, int], float],
    acceptance_lookup: dict[tuple[str, int, int], int],
    bid_price_grid_eur_per_mwh: list[float],
    run_id: str,
    forecast_origin_utc: pd.Timestamp,
    timestep_hours: float,
    daily_target_kg: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    q_matrix = _extract_q_matrix_from_pulp(q, len(timestamps), len(bid_price_grid_eur_per_mwh))
    dispatch_rows: list[dict[str, Any]] = []
    clearing_rows: list[dict[str, Any]] = []
    for scenario_id in scenario_ids:
        scenario_total_hydrogen = 0.0
        for t, timestamp in enumerate(timestamps):
            cleared_energy = float(
                timestep_hours
                * sum(
                    acceptance_lookup[(scenario_id, t, b)] * q_matrix[t, b]
                    for b in range(len(bid_price_grid_eur_per_mwh))
                )
            )
            hydrogen_sold = float(h_comp[(scenario_id, t)].value() or 0.0)
            scenario_total_hydrogen += hydrogen_sold
            emergency_import_value = (
                float(emergency_import[(scenario_id, t)].value() or 0.0)
                if emergency_import is not None
                else 0.0
            )
            dispatch_rows.append(
                {
                    "run_id": run_id,
                    "strategy": strategy,
                    "forecast_origin_utc": forecast_origin_utc,
                    "scenario_id": scenario_id,
                    "scenario_probability": probabilities[scenario_id],
                    "delivery_start_utc": pd.Timestamp(timestamp),
                    "granularity": "hourly",
                    "horizon": "D_only",
                    "scenario_model": scenario_model,
                    "scenario_price_eur_per_mwh": float(price_lookup[(scenario_id, t)]),
                    "cleared_energy_mwh": cleared_energy,
                    "used_energy_mwh": float(used_energy[(scenario_id, t)].value() or 0.0),
                    "unused_cleared_energy_mwh": float(unused_energy[(scenario_id, t)].value() or 0.0),
                    "emergency_import_mwh": emergency_import_value,
                    "P_el_mw": float(p_el[(scenario_id, t)].value() or 0.0),
                    "u_el": float(u_el[(scenario_id, t)].value() or 0.0),
                    "H_prod_kg": float(h_prod[(scenario_id, t)].value() or 0.0),
                    "P_comp_mw": float(p_comp[(scenario_id, t)].value() or 0.0),
                    "H_comp_kg": hydrogen_sold,
                    "H_buf_kg": float(h_buf[(scenario_id, t)].value() or 0.0),
                    "shortfall_kg": float(shortfall[scenario_id].value() or 0.0),
                    "timestep_hours": timestep_hours,
                }
            )
            for b, bid_price in enumerate(bid_price_grid_eur_per_mwh):
                accepted = bool(acceptance_lookup[(scenario_id, t, b)])
                bid_quantity_mw = float(q_matrix[t, b])
                clearing_rows.append(
                    {
                        "run_id": run_id,
                        "strategy": strategy,
                        "forecast_origin_utc": forecast_origin_utc,
                        "scenario_id": scenario_id,
                        "scenario_probability": probabilities[scenario_id],
                        "delivery_start_utc": pd.Timestamp(timestamp),
                        "granularity": "hourly",
                        "horizon": "D_only",
                        "scenario_model": scenario_model,
                        "scenario_price_eur_per_mwh": float(price_lookup[(scenario_id, t)]),
                        "bid_block": int(b),
                        "bid_price_eur_per_mwh": float(bid_price),
                        "bid_quantity_mw": bid_quantity_mw,
                        "accepted": accepted,
                        "cleared_quantity_mw": bid_quantity_mw if accepted else 0.0,
                        "cleared_energy_mwh": timestep_hours * bid_quantity_mw if accepted else 0.0,
                        "timestep_hours": timestep_hours,
                    }
                )
        above_target = max(scenario_total_hydrogen - daily_target_kg, 0.0)
        for row in dispatch_rows[-len(timestamps):]:
            row["hydrogen_above_target_kg"] = above_target
    return pd.DataFrame(dispatch_rows), pd.DataFrame(clearing_rows)


def _build_scenario_economics(
    *,
    scenario_dispatch: pd.DataFrame,
    config: HydrogenConfig,
    total_probability: float,
    shortfall_penalty_eur_per_kg: float,
    emergency_import_price_eur_per_mwh: float | None = None,
) -> pd.DataFrame:
    economics = config.economics
    rows: list[dict[str, Any]] = []
    effective_emergency_price = (
        None
        if emergency_import_price_eur_per_mwh is None
        else float(emergency_import_price_eur_per_mwh)
    )
    for scenario_id, dispatch in scenario_dispatch.groupby("scenario_id", sort=True):
        probability = float(dispatch["scenario_probability"].iloc[0])
        settlement_cost = float((dispatch["scenario_price_eur_per_mwh"] * dispatch["cleared_energy_mwh"]).sum())
        hydrogen_revenue = float(economics.h2_sale_price_eur_per_kg * dispatch["H_comp_kg"].sum())
        unused_penalty = float(economics.unused_energy_penalty_eur_per_mwh * dispatch["unused_cleared_energy_mwh"].sum())
        emergency_import_mwh = float(
            pd.to_numeric(pd.Series(dispatch.get("emergency_import_mwh", 0.0)), errors="coerce").fillna(0.0).sum()
        )
        emergency_import_cost = float(emergency_import_mwh * effective_emergency_price) if effective_emergency_price is not None else 0.0
        shortfall_kg = float(dispatch["shortfall_kg"].iloc[0])
        shortfall_penalty = float(shortfall_penalty_eur_per_kg * shortfall_kg)
        terminal_correction = float(
            config.terminal_inventory_value_per_kg
            * (float(dispatch["H_buf_kg"].iloc[-1]) - float(config.hydrogen_system.storage_initial_kg))
        )
        adjusted_profit = float(
            hydrogen_revenue
            - settlement_cost
            - unused_penalty
            - emergency_import_cost
            - shortfall_penalty
            + terminal_correction
        )
        rows.append(
            {
                "scenario_id": str(scenario_id),
                "scenario_probability": probability,
                "probability_sum_check": total_probability,
                "settlement_cost_eur": settlement_cost,
                "hydrogen_revenue_eur": hydrogen_revenue,
                "unused_energy_penalty_eur": unused_penalty,
                "emergency_import_mwh": emergency_import_mwh,
                "emergency_import_cost_eur": emergency_import_cost,
                "shortfall_penalty_eur": shortfall_penalty,
                "terminal_inventory_correction_eur": terminal_correction,
                "adjusted_profit_eur": adjusted_profit,
                "expected_adjusted_profit_contribution_eur": probability * adjusted_profit,
                "cleared_energy_mwh": float(dispatch["cleared_energy_mwh"].sum()),
                "used_energy_mwh": float(dispatch["used_energy_mwh"].sum()),
                "unused_cleared_energy_mwh": float(dispatch["unused_cleared_energy_mwh"].sum()),
                "hydrogen_sold_kg": float(dispatch["H_comp_kg"].sum()),
                "hydrogen_produced_kg": float(dispatch["H_prod_kg"].sum()),
                "hydrogen_above_target_kg": float(dispatch["hydrogen_above_target_kg"].iloc[0]),
                "shortfall_kg": shortfall_kg,
                "average_price_paid_eur_per_mwh": settlement_cost / float(dispatch["cleared_energy_mwh"].sum())
                if float(dispatch["cleared_energy_mwh"].sum()) > 0.0
                else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("scenario_id").reset_index(drop=True)


def _attach_cvar_metrics_to_scenario_economics(
    scenario_economics: pd.DataFrame,
    *,
    risk_measure: str,
    cvar_alpha: float,
    cvar_gamma: float,
    zeta_loss_eur: float | None = None,
    xi_lookup: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, WeightedCvarResult]:
    frame = scenario_economics.copy().sort_values("scenario_id").reset_index(drop=True)
    frame["loss_eur"] = -frame["adjusted_profit_eur"].astype(float)
    posthoc = compute_weighted_cvar_from_frame(
        frame,
        loss_column="loss_eur",
        probability_column="scenario_probability",
        alpha=float(cvar_alpha),
    )
    if zeta_loss_eur is None:
        zeta = float(posthoc.zeta)
    else:
        zeta = float(zeta_loss_eur)
    if xi_lookup is None:
        xi_values = posthoc.xi.astype(float)
    else:
        xi_values = np.asarray([float(xi_lookup.get(str(scenario_id), 0.0)) for scenario_id in frame["scenario_id"]], dtype=float)
    cvar_loss = float(zeta + (1.0 / (1.0 - float(cvar_alpha))) * np.sum(frame["scenario_probability"].astype(float).to_numpy() * xi_values))
    frame["risk_measure"] = str(risk_measure)
    frame["cvar_alpha"] = float(cvar_alpha)
    frame["cvar_gamma"] = float(cvar_gamma)
    frame["loss_eur"] = frame["loss_eur"].astype(float)
    frame["zeta_loss_eur"] = zeta
    frame["xi_loss_excess_eur"] = xi_values
    frame["cvar_loss_eur"] = cvar_loss
    frame["loss_minus_zeta_eur"] = frame["loss_eur"] - zeta
    frame["is_worst_scenario"] = frame["adjusted_profit_eur"].astype(float) == frame["adjusted_profit_eur"].astype(float).min()
    return frame, WeightedCvarResult(
        alpha=float(cvar_alpha),
        zeta=zeta,
        cvar=cvar_loss,
        expected_loss=float(np.sum(frame["scenario_probability"].astype(float) * frame["loss_eur"].astype(float))),
        losses=frame["loss_eur"].astype(float).to_numpy(),
        probabilities=frame["scenario_probability"].astype(float).to_numpy(),
        xi=xi_values,
    )


def _build_summary(
    *,
    run_id: str,
    toy_case: str,
    submitted_bids: pd.DataFrame,
    scenario_economics: pd.DataFrame,
    scenario_dispatch: pd.DataFrame,
    solver: SolverResult,
    model_stats: ModelStats,
    probability_sum: float,
    bid_regularisation_eur_per_mw: float,
    risk_measure: str,
    cvar_alpha: float,
    cvar_gamma: float,
    cvar_result: WeightedCvarResult,
) -> pd.DataFrame:
    expected = compute_stochastic_expected_bid_metrics(
        submitted_bids=submitted_bids,
        scenario_dispatch=scenario_dispatch,
        scenario_economics=scenario_economics,
    )
    total_submitted_energy_mwh = float(
        submitted_bids["bid_quantity_mw"].astype(float).sum() * float(submitted_bids["timestep_hours"].iloc[0])
    )
    regularisation_term = bid_regularisation_eur_per_mw * float(submitted_bids["bid_quantity_mw"].astype(float).sum())
    high_bid_250 = submitted_bids.loc[submitted_bids["bid_price_eur_per_mwh"].astype(float) >= 250.0, "bid_quantity_mw"].astype(float).sum() * float(submitted_bids["timestep_hours"].iloc[0])
    high_bid_3000 = submitted_bids.loc[submitted_bids["bid_price_eur_per_mwh"].astype(float) >= 3000.0, "bid_quantity_mw"].astype(float).sum() * float(submitted_bids["timestep_hours"].iloc[0])
    weighted_average_bid_price = float(
        (submitted_bids["bid_price_eur_per_mwh"].astype(float) * submitted_bids["bid_quantity_mw"].astype(float)).sum()
        / submitted_bids["bid_quantity_mw"].astype(float).sum()
    ) if float(submitted_bids["bid_quantity_mw"].astype(float).sum()) > 0.0 else float("nan")
    worst_scenario_profit = float(scenario_economics["adjusted_profit_eur"].astype(float).min())
    worst_scenario_loss = float(scenario_economics["loss_eur"].astype(float).max())
    worst_scenario_shortfall = float(scenario_economics["shortfall_kg"].astype(float).max())
    minimum_scenario_cleared_energy = float(scenario_economics["cleared_energy_mwh"].astype(float).min())
    expected_emergency_import_mwh = float(
        np.sum(
            pd.to_numeric(scenario_economics["scenario_probability"], errors="coerce").to_numpy()
            * pd.to_numeric(pd.Series(scenario_economics.get("emergency_import_mwh", 0.0)), errors="coerce").fillna(0.0).to_numpy()
        )
    ) if not scenario_economics.empty else 0.0
    expected_emergency_import_cost = float(
        np.sum(
            pd.to_numeric(scenario_economics["scenario_probability"], errors="coerce").to_numpy()
            * pd.to_numeric(pd.Series(scenario_economics.get("emergency_import_cost_eur", 0.0)), errors="coerce").fillna(0.0).to_numpy()
        )
    ) if not scenario_economics.empty else 0.0
    summary_row = {
        "run_id": run_id,
        "strategy": str(submitted_bids["strategy"].iloc[0]) if "strategy" in submitted_bids.columns and not submitted_bids.empty else TOY_BIDDING_STRATEGY,
        "toy_case": toy_case,
        "objective_convention": "maximize_expected_adjusted_profit_minus_gamma_times_cvar_loss",
        "risk_measure": str(risk_measure),
        "cvar_alpha": float(cvar_alpha),
        "cvar_gamma": float(cvar_gamma),
        "expected_adjusted_profit_eur": expected["expected_adjusted_profit_eur"],
        "expected_settlement_cost_eur": expected["expected_settlement_cost_eur"],
        "expected_hydrogen_revenue_eur": expected["expected_hydrogen_revenue_eur"],
        "expected_unused_energy_penalty_eur": expected["expected_unused_energy_penalty_eur"],
        "expected_shortfall_penalty_eur": expected["expected_shortfall_penalty_eur"],
        "expected_terminal_inventory_correction_eur": expected["expected_terminal_inventory_correction_eur"],
        "expected_cleared_energy_mwh": expected["expected_cleared_energy_mwh"],
        "expected_used_energy_mwh": expected["expected_used_energy_mwh"],
        "expected_unused_cleared_energy_mwh": expected["expected_unused_cleared_energy_mwh"],
        "expected_emergency_import_mwh": expected_emergency_import_mwh,
        "expected_emergency_import_cost_eur": expected_emergency_import_cost,
        "expected_hydrogen_sold_kg": expected["expected_hydrogen_sold_kg"],
        "expected_hydrogen_above_target_kg": expected["expected_hydrogen_above_target_kg"],
        "expected_shortfall_kg": expected["expected_shortfall_kg"],
        "VaR_loss_zeta": float(cvar_result.zeta),
        "CVaR_loss": float(cvar_result.cvar),
        "expected_loss_eur": float(cvar_result.expected_loss),
        "worst_scenario_profit": worst_scenario_profit,
        "worst_scenario_loss": worst_scenario_loss,
        "downside_tail_loss_mean": float(cvar_result.cvar),
        "minimum_scenario_cleared_energy_mwh": minimum_scenario_cleared_energy,
        "worst_scenario_shortfall_kg": worst_scenario_shortfall,
        "total_submitted_energy_mwh": total_submitted_energy_mwh,
        "submitted_energy_mwh_ge_250": float(high_bid_250),
        "submitted_energy_mwh_ge_3000": float(high_bid_3000),
        "high_bid_energy_share_ge_250": float(high_bid_250 / total_submitted_energy_mwh) if total_submitted_energy_mwh > 0.0 else 0.0,
        "high_bid_energy_share_ge_3000": float(high_bid_3000 / total_submitted_energy_mwh) if total_submitted_energy_mwh > 0.0 else 0.0,
        "weighted_average_bid_price_eur_per_mwh": weighted_average_bid_price,
        "clearing_reliability_min_scenario_over_submitted": float(minimum_scenario_cleared_energy / total_submitted_energy_mwh) if total_submitted_energy_mwh > 0.0 else 0.0,
        "scenario_count": int(model_stats.scenario_count),
        "horizon_steps": int(model_stats.horizon_steps),
        "solver_status": solver.status,
        "objective_value": solver.objective_value,
        "objective_with_regularisation": solver.objective_value,
        "expected_adjusted_profit_without_regularisation": expected["expected_adjusted_profit_eur"],
        "objective_without_regularisation": float(solver.objective_value + regularisation_term) if solver.objective_value is not None else None,
        "regularisation_term": regularisation_term,
        "solve_time_seconds": solver.runtime_seconds,
        "variable_count": model_stats.variable_count,
        "binary_variable_count": model_stats.binary_variable_count,
        "constraint_count": model_stats.constraint_count,
        "probabilities_sum": probability_sum,
        "regularisation_weight": bid_regularisation_eur_per_mw,
        "bid_regularisation_eur_per_mw": bid_regularisation_eur_per_mw,
        "nonanticipativity_evidence": "submitted_bids_has_no_scenario_index",
    }
    return pd.DataFrame([summary_row])


def _solve_with_pyomo(
    *,
    scenarios: pd.DataFrame,
    config: HydrogenConfig,
    bid_price_grid_eur_per_mwh: list[float],
    run_id: str,
    strategy_name: str,
    solver_log_path: str | None,
    toy_case: str,
    risk_measure: str,
    cvar_alpha: float,
    cvar_gamma: float,
    production_target_mode: str,
    shortfall_penalty_eur_per_kg: float | None,
    inventory_start_kg: float | None,
    reserve_kg: float | None,
    target_hydrogen_min_kg: float | None,
    target_hydrogen_max_kg: float | None,
    terminal_reference_start_kg: float | None,
    firm_bid_floor_mw: list[float] | tuple[float, ...] | np.ndarray | None,
    emergency_import_price_eur_per_mwh: float | None,
    reserve_obligations_by_hour: pd.DataFrame | None,
) -> StochasticBiddingSolveResult:
    if pyo is None:
        raise RuntimeError("Pyomo backend requested but Pyomo is not installed.")

    build_started = perf_counter()
    timestep_hours = float(config.delta_t_hours)
    effective_shortfall_penalty = float(
        config.economics.shortfall_penalty_eur_per_kg
        if shortfall_penalty_eur_per_kg is None
        else shortfall_penalty_eur_per_kg
    )
    timestamps, scenario_ids, block_ids, probabilities, price_lookup, acceptance_lookup = _resolve_price_panel(
        scenarios,
        bid_price_grid_eur_per_mwh,
    )
    total_probability = validate_toy_scenario_probabilities(scenarios)
    forecast_origin = pd.Timestamp(pd.to_datetime(scenarios["forecast_origin_utc"].iloc[0], utc=True, errors="raise"))
    scenario_model = str(scenarios["model_id"].dropna().iloc[0]) if "model_id" in scenarios.columns and not scenarios["model_id"].dropna().empty else "toy_artificial_phase4a"
    site_max_load_mw = float(config.hydrogen_system.electrolyser_nominal_mw + config.hydrogen_system.compressor_max_mw)
    site_max_bid_mw = float(site_max_load_mw)
    firm_bid_floor_mw_values = _normalize_hourly_floor_mw(
        firm_bid_floor_mw,
        horizon_steps=len(timestamps),
        site_max_bid_mw=site_max_bid_mw,
    )
    prepared_reserve = _prepare_reserve_obligations(
        reserve_obligations_by_hour=reserve_obligations_by_hour,
        timestamps=timestamps,
        site_max_load_mw=site_max_load_mw,
        scenario_count=len(scenario_ids),
    )
    inventory_start_kg_value = float(config.hydrogen_system.storage_initial_kg if inventory_start_kg is None else inventory_start_kg)
    reserve_kg_value = float(config.hydrogen_system.reserve_kg if reserve_kg is None else reserve_kg)
    target_hydrogen_min_kg_value = float(config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg)
    target_hydrogen_max_kg_value = None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    terminal_reference_start_kg_value = float(inventory_start_kg_value if terminal_reference_start_kg is None else terminal_reference_start_kg)
    emergency_import_price_value = (
        None
        if emergency_import_price_eur_per_mwh is None
        else float(emergency_import_price_eur_per_mwh)
    )
    emergency_import_enabled = emergency_import_price_value is not None and emergency_import_price_value > 0.0

    model = pyo.ConcreteModel(name="hydrogen_stochastic_hourly_bidding")
    model.T = pyo.RangeSet(0, len(timestamps) - 1)
    model.S = pyo.Set(initialize=scenario_ids, ordered=True)
    model.B = pyo.RangeSet(0, len(block_ids) - 1)

    model.q = pyo.Var(model.T, model.B, domain=pyo.NonNegativeReals)
    model.P_el = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.u_el = pyo.Var(model.S, model.T, domain=pyo.Binary)
    model.H_prod = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.P_comp = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.H_comp = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.H_buf = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.used_energy = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.unused_cleared_energy = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    if emergency_import_enabled:
        model.emergency_import = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.shortfall = pyo.Var(model.S, domain=pyo.NonNegativeReals)
    if str(risk_measure) == "cvar" and float(cvar_gamma) > 0.0:
        model.zeta = pyo.Var()
        model.xi = pyo.Var(model.S, domain=pyo.NonNegativeReals)
    model.available_up_reserve_mw = pyo.Expression(
        model.S,
        model.T,
        rule=lambda m, s, t: m.P_el[s, t] + m.P_comp[s, t],
    )
    model.available_down_reserve_mw = pyo.Expression(
        model.S,
        model.T,
        rule=lambda m, s, t: site_max_load_mw - (m.P_el[s, t] + m.P_comp[s, t]),
    )

    model.constraints = pyo.ConstraintList()
    for t in range(len(timestamps)):
        model.constraints.add(sum(model.q[t, b] for b in block_ids) <= site_max_bid_mw)
        model.constraints.add(model.q[t, block_ids[-1]] >= float(firm_bid_floor_mw_values[t]))
        for scenario_id in scenario_ids:
            cleared_energy_expr = timestep_hours * sum(
                acceptance_lookup[(scenario_id, t, b)] * model.q[t, b] for b in block_ids
            )
            model.constraints.add(model.P_el[scenario_id, t] >= config.hydrogen_system.electrolyser_min_mw * model.u_el[scenario_id, t])
            model.constraints.add(model.P_el[scenario_id, t] <= config.hydrogen_system.electrolyser_nominal_mw * model.u_el[scenario_id, t])
            model.constraints.add(model.H_prod[scenario_id, t] == config.hydrogen_system.h2_efficiency_kg_per_mwh * model.P_el[scenario_id, t] * timestep_hours)
            model.constraints.add(model.P_comp[scenario_id, t] <= config.hydrogen_system.compressor_max_mw)
            model.constraints.add(
                model.P_comp[scenario_id, t] * timestep_hours
                == config.hydrogen_system.compressor_specific_mwh_per_kg * model.H_comp[scenario_id, t]
            )
            model.constraints.add(model.used_energy[scenario_id, t] == timestep_hours * (model.P_el[scenario_id, t] + model.P_comp[scenario_id, t]))
            if emergency_import_enabled:
                model.constraints.add(
                    model.used_energy[scenario_id, t]
                    + model.unused_cleared_energy[scenario_id, t]
                    == cleared_energy_expr + model.emergency_import[scenario_id, t]
                )
            else:
                model.constraints.add(model.used_energy[scenario_id, t] + model.unused_cleared_energy[scenario_id, t] == cleared_energy_expr)
            if t == 0:
                model.constraints.add(
                    model.H_buf[scenario_id, t]
                    == inventory_start_kg_value + model.H_prod[scenario_id, t] - model.H_comp[scenario_id, t]
                )
            else:
                model.constraints.add(
                    model.H_buf[scenario_id, t]
                    == model.H_buf[scenario_id, t - 1] + model.H_prod[scenario_id, t] - model.H_comp[scenario_id, t]
                )
                model.constraints.add(
                    model.P_el[scenario_id, t] - model.P_el[scenario_id, t - 1]
                    <= config.hydrogen_system.electrolyser_ramp_mw_per_h * timestep_hours
                )
                model.constraints.add(
                    model.P_el[scenario_id, t - 1] - model.P_el[scenario_id, t]
                    <= config.hydrogen_system.electrolyser_ramp_mw_per_h * timestep_hours
                )
            model.constraints.add(model.H_buf[scenario_id, t] >= reserve_kg_value)
            model.constraints.add(model.H_buf[scenario_id, t] <= config.hydrogen_system.storage_capacity_kg)
            if prepared_reserve is not None:
                required_up = float(prepared_reserve.up_by_time_index[int(t)])
                required_down = float(prepared_reserve.down_by_time_index[int(t)])
                if required_up > 1e-9:
                    model.constraints.add(model.available_up_reserve_mw[scenario_id, t] >= required_up)
                if required_down > 1e-9:
                    model.constraints.add(model.available_down_reserve_mw[scenario_id, t] >= required_down)

    for scenario_id in scenario_ids:
        if str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}:
            model.constraints.add(
                sum(model.H_comp[scenario_id, t] for t in range(len(timestamps)))
                >= target_hydrogen_min_kg_value
            )
            if target_hydrogen_max_kg_value is not None:
                model.constraints.add(
                    sum(model.H_comp[scenario_id, t] for t in range(len(timestamps)))
                    <= target_hydrogen_max_kg_value
                )
            model.constraints.add(model.shortfall[scenario_id] == 0.0)
        else:
            model.constraints.add(
                sum(model.H_comp[scenario_id, t] for t in range(len(timestamps))) + model.shortfall[scenario_id]
                >= target_hydrogen_min_kg_value
            )

    expected_profit_expr = 0.0
    scenario_profit_exprs: dict[str, Any] = {}
    for scenario_id in scenario_ids:
        settlement = sum(
            price_lookup[(scenario_id, t)]
            * timestep_hours
            * sum(acceptance_lookup[(scenario_id, t, b)] * model.q[t, b] for b in block_ids)
            for t in range(len(timestamps))
        )
        revenue = config.economics.h2_sale_price_eur_per_kg * sum(model.H_comp[scenario_id, t] for t in range(len(timestamps)))
        unused_penalty = config.economics.unused_energy_penalty_eur_per_mwh * sum(
            model.unused_cleared_energy[scenario_id, t] for t in range(len(timestamps))
        )
        emergency_import_cost = (
            emergency_import_price_value * sum(model.emergency_import[scenario_id, t] for t in range(len(timestamps)))
            if emergency_import_enabled
            else 0.0
        )
        shortfall_penalty = effective_shortfall_penalty * model.shortfall[scenario_id]
        terminal_correction = config.terminal_inventory_value_per_kg * (
            model.H_buf[scenario_id, len(timestamps) - 1] - terminal_reference_start_kg_value
        )
        scenario_profit = revenue - settlement - unused_penalty - emergency_import_cost - shortfall_penalty + terminal_correction
        scenario_profit_exprs[scenario_id] = scenario_profit
        expected_profit_expr += probabilities[scenario_id] * scenario_profit
    bid_regularisation = TOY_BID_REGULARISATION_EUR_PER_MW * sum(model.q[t, b] for t in range(len(timestamps)) for b in block_ids)
    if str(risk_measure) == "cvar" and float(cvar_gamma) > 0.0:
        for scenario_id in scenario_ids:
            scenario_loss = -scenario_profit_exprs[scenario_id]
            model.constraints.add(model.xi[scenario_id] >= scenario_loss - model.zeta)
        cvar_expr = model.zeta + (1.0 / (1.0 - float(cvar_alpha))) * sum(probabilities[scenario_id] * model.xi[scenario_id] for scenario_id in scenario_ids)
        model.objective = pyo.Objective(expr=expected_profit_expr - float(cvar_gamma) * cvar_expr - bid_regularisation, sense=pyo.maximize)
    else:
        model.objective = pyo.Objective(expr=expected_profit_expr - bid_regularisation, sense=pyo.maximize)

    model_build_time = perf_counter() - build_started
    solver, solver_name = _resolve_pyomo_solver(config.solver, solver_log_path)
    started = perf_counter()
    try:
        if solver_log_path is not None:
            results = solver.solve(model, tee=False, logfile=solver_log_path)
        else:
            results = solver.solve(model, tee=False)
    except TypeError:
        results = solver.solve(model, tee=False)
    solver_runtime = perf_counter() - started

    solver_status = getattr(getattr(results, "solver", None), "status", None)
    termination = getattr(getattr(results, "solver", None), "termination_condition", None)
    termination_text = str(termination).strip().lower() if termination is not None else ""
    status_text = "Optimal" if termination_text == "optimal" else f"{solver_status}:{termination}"

    postprocess_started = perf_counter()
    q_matrix = _extract_q_matrix_from_pyomo(model, len(timestamps), len(block_ids))
    submitted_bids = _build_submitted_bids(
        run_id=run_id,
        strategy=strategy_name,
        scenario_model=scenario_model,
        timestamps=timestamps,
        forecast_origin_utc=forecast_origin,
        bid_price_grid_eur_per_mwh=bid_price_grid_eur_per_mwh,
        q_solution=q_matrix,
        timestep_hours=timestep_hours,
    )
    scenario_dispatch, scenario_clearing = _scenario_dispatch_from_pyomo(
        model,
        strategy=strategy_name,
        scenario_model=scenario_model,
        timestamps=timestamps,
        scenario_ids=scenario_ids,
        probabilities=probabilities,
        price_lookup=price_lookup,
        acceptance_lookup=acceptance_lookup,
        q_matrix=q_matrix,
        bid_price_grid_eur_per_mwh=bid_price_grid_eur_per_mwh,
        run_id=run_id,
        forecast_origin_utc=forecast_origin,
        timestep_hours=timestep_hours,
        daily_target_kg=target_hydrogen_min_kg_value,
    )
    raw_scenario_economics = _build_scenario_economics(
        scenario_dispatch=scenario_dispatch,
        config=config,
        total_probability=total_probability,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        emergency_import_price_eur_per_mwh=emergency_import_price_value,
    )
    xi_lookup = None
    zeta_value = None
    if str(risk_measure) == "cvar" and float(cvar_gamma) > 0.0:
        xi_lookup = {scenario_id: float(pyo.value(model.xi[scenario_id]) or 0.0) for scenario_id in scenario_ids}
        zeta_value = float(pyo.value(model.zeta) or 0.0)
    scenario_economics, cvar_result = _attach_cvar_metrics_to_scenario_economics(
        raw_scenario_economics,
        risk_measure=risk_measure,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        zeta_loss_eur=zeta_value,
        xi_lookup=xi_lookup,
    )
    model_stats = _pyomo_model_stats(
        model,
        scenario_count=len(scenario_ids),
        horizon_steps=len(timestamps),
        delta_t_hours=timestep_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
    solver_result = SolverResult(
        status=status_text,
        objective_value=float(pyo.value(model.objective)) if pyo.value(model.objective) is not None else None,
        runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
        mip_gap=float(config.solver.mip_gap),
        solver_package="pyomo",
        solver_name=str(solver_name),
        termination_condition=str(termination) if termination is not None else None,
        model_build_time_seconds=float(model_build_time),
        solver_time_seconds=float(solver_runtime),
        postprocess_time_seconds=float(postprocess_time),
    )
    summary = _build_summary(
        run_id=run_id,
        toy_case=toy_case,
        submitted_bids=submitted_bids,
        scenario_economics=scenario_economics,
        scenario_dispatch=scenario_dispatch,
        solver=solver_result,
        model_stats=model_stats,
        probability_sum=total_probability,
        bid_regularisation_eur_per_mw=TOY_BID_REGULARISATION_EUR_PER_MW,
        risk_measure=risk_measure,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        cvar_result=cvar_result,
    )
    acceptance_table = build_scenario_acceptance_table(scenarios, bid_price_grid_eur_per_mwh)
    reserve_diagnostics = _build_reserve_diagnostics(
        prepared_reserve,
        scenario_dispatch=scenario_dispatch,
        site_max_load_mw=site_max_load_mw,
    )
    return StochasticBiddingSolveResult(
        submitted_bids=submitted_bids,
        scenario_clearing=scenario_clearing,
        scenario_dispatch=scenario_dispatch,
        scenario_economics=scenario_economics,
        summary=summary,
        solver=solver_result,
        model_stats=model_stats,
        acceptance_table=acceptance_table,
        risk_measure=str(risk_measure),
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        zeta_loss_eur=float(cvar_result.zeta),
        cvar_loss_eur=float(cvar_result.cvar),
        cvar_details=scenario_economics[["scenario_id", "loss_eur", "xi_loss_excess_eur", "zeta_loss_eur", "cvar_loss_eur"]].copy(),
        reserve_diagnostics=reserve_diagnostics,
    )


def _solve_with_pulp(
    *,
    scenarios: pd.DataFrame,
    config: HydrogenConfig,
    bid_price_grid_eur_per_mwh: list[float],
    run_id: str,
    strategy_name: str,
    solver_log_path: str | None,
    toy_case: str,
    risk_measure: str,
    cvar_alpha: float,
    cvar_gamma: float,
    production_target_mode: str,
    shortfall_penalty_eur_per_kg: float | None,
    inventory_start_kg: float | None,
    reserve_kg: float | None,
    target_hydrogen_min_kg: float | None,
    target_hydrogen_max_kg: float | None,
    terminal_reference_start_kg: float | None,
    firm_bid_floor_mw: list[float] | tuple[float, ...] | np.ndarray | None,
    emergency_import_price_eur_per_mwh: float | None,
    reserve_obligations_by_hour: pd.DataFrame | None,
) -> StochasticBiddingSolveResult:
    if pulp is None:
        raise RuntimeError("PuLP backend requested but PuLP is not installed.")

    build_started = perf_counter()
    timestep_hours = float(config.delta_t_hours)
    effective_shortfall_penalty = float(
        config.economics.shortfall_penalty_eur_per_kg
        if shortfall_penalty_eur_per_kg is None
        else shortfall_penalty_eur_per_kg
    )
    timestamps, scenario_ids, block_ids, probabilities, price_lookup, acceptance_lookup = _resolve_price_panel(
        scenarios,
        bid_price_grid_eur_per_mwh,
    )
    total_probability = validate_toy_scenario_probabilities(scenarios)
    forecast_origin = pd.Timestamp(pd.to_datetime(scenarios["forecast_origin_utc"].iloc[0], utc=True, errors="raise"))
    scenario_model = str(scenarios["model_id"].dropna().iloc[0]) if "model_id" in scenarios.columns and not scenarios["model_id"].dropna().empty else "toy_artificial_phase4a"
    site_max_load_mw = float(config.hydrogen_system.electrolyser_nominal_mw + config.hydrogen_system.compressor_max_mw)
    site_max_bid_mw = float(site_max_load_mw)
    firm_bid_floor_mw_values = _normalize_hourly_floor_mw(
        firm_bid_floor_mw,
        horizon_steps=len(timestamps),
        site_max_bid_mw=site_max_bid_mw,
    )
    prepared_reserve = _prepare_reserve_obligations(
        reserve_obligations_by_hour=reserve_obligations_by_hour,
        timestamps=timestamps,
        site_max_load_mw=site_max_load_mw,
        scenario_count=len(scenario_ids),
    )
    inventory_start_kg_value = float(config.hydrogen_system.storage_initial_kg if inventory_start_kg is None else inventory_start_kg)
    reserve_kg_value = float(config.hydrogen_system.reserve_kg if reserve_kg is None else reserve_kg)
    target_hydrogen_min_kg_value = float(config.economics.daily_target_kg if target_hydrogen_min_kg is None else target_hydrogen_min_kg)
    target_hydrogen_max_kg_value = None if target_hydrogen_max_kg is None else float(target_hydrogen_max_kg)
    terminal_reference_start_kg_value = float(inventory_start_kg_value if terminal_reference_start_kg is None else terminal_reference_start_kg)
    emergency_import_price_value = (
        None
        if emergency_import_price_eur_per_mwh is None
        else float(emergency_import_price_eur_per_mwh)
    )
    emergency_import_enabled = emergency_import_price_value is not None and emergency_import_price_value > 0.0

    model = pulp.LpProblem("hydrogen_stochastic_hourly_bidding", pulp.LpMaximize)
    q = {(t, b): pulp.LpVariable(f"q_{t}_{b}", lowBound=0.0) for t in range(len(timestamps)) for b in block_ids}
    p_el = {(s, t): pulp.LpVariable(f"P_el_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    u_el = {(s, t): pulp.LpVariable(f"u_el_{s}_{t}", lowBound=0.0, upBound=1.0, cat=pulp.LpBinary) for s in scenario_ids for t in range(len(timestamps))}
    h_prod = {(s, t): pulp.LpVariable(f"H_prod_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    p_comp = {(s, t): pulp.LpVariable(f"P_comp_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    h_comp = {(s, t): pulp.LpVariable(f"H_comp_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    h_buf = {(s, t): pulp.LpVariable(f"H_buf_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    used_energy = {(s, t): pulp.LpVariable(f"used_energy_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    unused_energy = {(s, t): pulp.LpVariable(f"unused_energy_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))}
    emergency_import = {(s, t): pulp.LpVariable(f"emergency_import_{s}_{t}", lowBound=0.0) for s in scenario_ids for t in range(len(timestamps))} if emergency_import_enabled else None
    shortfall = {s: pulp.LpVariable(f"shortfall_{s}", lowBound=0.0) for s in scenario_ids}
    if str(risk_measure) == "cvar" and float(cvar_gamma) > 0.0:
        zeta = pulp.LpVariable("zeta")
        xi = {s: pulp.LpVariable(f"xi_{s}", lowBound=0.0) for s in scenario_ids}

    for t in range(len(timestamps)):
        model += pulp.lpSum(q[(t, b)] for b in block_ids) <= site_max_bid_mw, f"submitted_cap_{t}"
        model += q[(t, block_ids[-1])] >= float(firm_bid_floor_mw_values[t]), f"firm_floor_{t}"
        for scenario_id in scenario_ids:
            cleared_energy_expr = timestep_hours * pulp.lpSum(
                acceptance_lookup[(scenario_id, t, b)] * q[(t, b)] for b in block_ids
            )
            model += p_el[(scenario_id, t)] >= config.hydrogen_system.electrolyser_min_mw * u_el[(scenario_id, t)], f"el_min_{scenario_id}_{t}"
            model += p_el[(scenario_id, t)] <= config.hydrogen_system.electrolyser_nominal_mw * u_el[(scenario_id, t)], f"el_max_{scenario_id}_{t}"
            model += h_prod[(scenario_id, t)] == config.hydrogen_system.h2_efficiency_kg_per_mwh * p_el[(scenario_id, t)] * timestep_hours, f"h_prod_{scenario_id}_{t}"
            model += p_comp[(scenario_id, t)] <= config.hydrogen_system.compressor_max_mw, f"comp_max_{scenario_id}_{t}"
            model += p_comp[(scenario_id, t)] * timestep_hours == config.hydrogen_system.compressor_specific_mwh_per_kg * h_comp[(scenario_id, t)], f"comp_specific_{scenario_id}_{t}"
            model += used_energy[(scenario_id, t)] == timestep_hours * (p_el[(scenario_id, t)] + p_comp[(scenario_id, t)]), f"used_balance_{scenario_id}_{t}"
            if emergency_import_enabled:
                model += used_energy[(scenario_id, t)] + unused_energy[(scenario_id, t)] == cleared_energy_expr + emergency_import[(scenario_id, t)], f"cleared_balance_{scenario_id}_{t}"
            else:
                model += used_energy[(scenario_id, t)] + unused_energy[(scenario_id, t)] == cleared_energy_expr, f"cleared_balance_{scenario_id}_{t}"
            if t == 0:
                model += h_buf[(scenario_id, t)] == inventory_start_kg_value + h_prod[(scenario_id, t)] - h_comp[(scenario_id, t)], f"storage_{scenario_id}_{t}"
            else:
                model += h_buf[(scenario_id, t)] == h_buf[(scenario_id, t - 1)] + h_prod[(scenario_id, t)] - h_comp[(scenario_id, t)], f"storage_{scenario_id}_{t}"
                model += p_el[(scenario_id, t)] - p_el[(scenario_id, t - 1)] <= config.hydrogen_system.electrolyser_ramp_mw_per_h * timestep_hours, f"ramp_up_{scenario_id}_{t}"
                model += p_el[(scenario_id, t - 1)] - p_el[(scenario_id, t)] <= config.hydrogen_system.electrolyser_ramp_mw_per_h * timestep_hours, f"ramp_down_{scenario_id}_{t}"
            model += h_buf[(scenario_id, t)] >= reserve_kg_value, f"reserve_{scenario_id}_{t}"
            model += h_buf[(scenario_id, t)] <= config.hydrogen_system.storage_capacity_kg, f"storage_cap_{scenario_id}_{t}"
            if prepared_reserve is not None:
                required_up = float(prepared_reserve.up_by_time_index[int(t)])
                required_down = float(prepared_reserve.down_by_time_index[int(t)])
                if required_up > 1e-9:
                    model += p_el[(scenario_id, t)] + p_comp[(scenario_id, t)] >= required_up, f"reserve_up_{scenario_id}_{t}"
                if required_down > 1e-9:
                    model += site_max_load_mw - (p_el[(scenario_id, t)] + p_comp[(scenario_id, t)]) >= required_down, f"reserve_down_{scenario_id}_{t}"

    for scenario_id in scenario_ids:
        if str(production_target_mode).strip() in {"hard_daily_target", "weekly_hard_band_target"}:
            model += (
                pulp.lpSum(h_comp[(scenario_id, t)] for t in range(len(timestamps)))
                >= target_hydrogen_min_kg_value
            ), f"daily_target_lb_{scenario_id}"
            if target_hydrogen_max_kg_value is not None:
                model += (
                    pulp.lpSum(h_comp[(scenario_id, t)] for t in range(len(timestamps)))
                    <= target_hydrogen_max_kg_value
                ), f"daily_target_ub_{scenario_id}"
            model += shortfall[scenario_id] == 0.0, f"hard_target_shortfall_zero_{scenario_id}"
        else:
            model += (
                pulp.lpSum(h_comp[(scenario_id, t)] for t in range(len(timestamps))) + shortfall[scenario_id]
                >= target_hydrogen_min_kg_value
            ), f"daily_target_lb_{scenario_id}"

    scenario_profit_exprs: dict[str, Any] = {}
    for scenario_id in scenario_ids:
        scenario_profit_exprs[scenario_id] = (
            config.economics.h2_sale_price_eur_per_kg * pulp.lpSum(h_comp[(scenario_id, t)] for t in range(len(timestamps)))
            - pulp.lpSum(
                price_lookup[(scenario_id, t)]
                * timestep_hours
                * pulp.lpSum(acceptance_lookup[(scenario_id, t, b)] * q[(t, b)] for b in block_ids)
                for t in range(len(timestamps))
            )
            - config.economics.unused_energy_penalty_eur_per_mwh * pulp.lpSum(unused_energy[(scenario_id, t)] for t in range(len(timestamps)))
            - (
                emergency_import_price_value * pulp.lpSum(emergency_import[(scenario_id, t)] for t in range(len(timestamps)))
                if emergency_import_enabled
                else 0.0
            )
            - effective_shortfall_penalty * shortfall[scenario_id]
            + config.terminal_inventory_value_per_kg * (
                h_buf[(scenario_id, len(timestamps) - 1)] - terminal_reference_start_kg_value
            )
        )
    expected_profit = pulp.lpSum(probabilities[scenario_id] * scenario_profit_exprs[scenario_id] for scenario_id in scenario_ids)
    bid_regularisation = TOY_BID_REGULARISATION_EUR_PER_MW * pulp.lpSum(q[(t, b)] for t in range(len(timestamps)) for b in block_ids)
    if str(risk_measure) == "cvar" and float(cvar_gamma) > 0.0:
        for scenario_id in scenario_ids:
            model += xi[scenario_id] >= -scenario_profit_exprs[scenario_id] - zeta, f"cvar_excess_{scenario_id}"
        cvar_expr = zeta + (1.0 / (1.0 - float(cvar_alpha))) * pulp.lpSum(probabilities[scenario_id] * xi[scenario_id] for scenario_id in scenario_ids)
        model += expected_profit - float(cvar_gamma) * cvar_expr - bid_regularisation
    else:
        model += expected_profit - bid_regularisation

    model_build_time = perf_counter() - build_started
    solver_backend, solver_name = _resolve_pulp_solver(config.solver, log_path=solver_log_path)
    started = perf_counter()
    model.solve(solver_backend)
    solver_runtime = perf_counter() - started

    postprocess_started = perf_counter()
    q_matrix = _extract_q_matrix_from_pulp(q, len(timestamps), len(block_ids))
    submitted_bids = _build_submitted_bids(
        run_id=run_id,
        strategy=strategy_name,
        scenario_model=scenario_model,
        timestamps=timestamps,
        forecast_origin_utc=forecast_origin,
        bid_price_grid_eur_per_mwh=bid_price_grid_eur_per_mwh,
        q_solution=q_matrix,
        timestep_hours=timestep_hours,
    )
    scenario_dispatch, scenario_clearing = _scenario_dispatch_from_pulp(
        strategy=strategy_name,
        scenario_model=scenario_model,
        q=q,
        p_el=p_el,
        u_el=u_el,
        h_prod=h_prod,
        p_comp=p_comp,
        h_comp=h_comp,
        h_buf=h_buf,
        used_energy=used_energy,
        unused_energy=unused_energy,
        emergency_import=emergency_import,
        shortfall=shortfall,
        timestamps=timestamps,
        scenario_ids=scenario_ids,
        probabilities=probabilities,
        price_lookup=price_lookup,
        acceptance_lookup=acceptance_lookup,
        bid_price_grid_eur_per_mwh=bid_price_grid_eur_per_mwh,
        run_id=run_id,
        forecast_origin_utc=forecast_origin,
        timestep_hours=timestep_hours,
        daily_target_kg=target_hydrogen_min_kg_value,
    )
    raw_scenario_economics = _build_scenario_economics(
        scenario_dispatch=scenario_dispatch,
        config=config,
        total_probability=total_probability,
        shortfall_penalty_eur_per_kg=effective_shortfall_penalty,
        emergency_import_price_eur_per_mwh=emergency_import_price_value,
    )
    xi_lookup = None
    zeta_value = None
    if str(risk_measure) == "cvar" and float(cvar_gamma) > 0.0:
        xi_lookup = {scenario_id: float(xi[scenario_id].value() or 0.0) for scenario_id in scenario_ids}
        zeta_value = float(zeta.value() or 0.0)
    scenario_economics, cvar_result = _attach_cvar_metrics_to_scenario_economics(
        raw_scenario_economics,
        risk_measure=risk_measure,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        zeta_loss_eur=zeta_value,
        xi_lookup=xi_lookup,
    )
    model_stats = _pulp_model_stats(
        model,
        scenario_count=len(scenario_ids),
        horizon_steps=len(timestamps),
        delta_t_hours=timestep_hours,
    )
    postprocess_time = perf_counter() - postprocess_started
    solver_result = SolverResult(
        status=str(pulp.LpStatus.get(model.status, str(model.status))),
        objective_value=float(model.objective.value()) if model.objective.value() is not None else None,
        runtime_seconds=float(model_build_time + solver_runtime + postprocess_time),
        mip_gap=float(config.solver.mip_gap),
        solver_package="pulp",
        solver_name=solver_name,
        termination_condition=str(pulp.LpStatus.get(model.status, str(model.status))),
        model_build_time_seconds=float(model_build_time),
        solver_time_seconds=float(solver_runtime),
        postprocess_time_seconds=float(postprocess_time),
    )
    summary = _build_summary(
        run_id=run_id,
        toy_case=toy_case,
        submitted_bids=submitted_bids,
        scenario_economics=scenario_economics,
        scenario_dispatch=scenario_dispatch,
        solver=solver_result,
        model_stats=model_stats,
        probability_sum=total_probability,
        bid_regularisation_eur_per_mw=TOY_BID_REGULARISATION_EUR_PER_MW,
        risk_measure=risk_measure,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        cvar_result=cvar_result,
    )
    acceptance_table = build_scenario_acceptance_table(scenarios, bid_price_grid_eur_per_mwh)
    reserve_diagnostics = _build_reserve_diagnostics(
        prepared_reserve,
        scenario_dispatch=scenario_dispatch,
        site_max_load_mw=site_max_load_mw,
    )
    return StochasticBiddingSolveResult(
        submitted_bids=submitted_bids,
        scenario_clearing=scenario_clearing,
        scenario_dispatch=scenario_dispatch,
        scenario_economics=scenario_economics,
        summary=summary,
        solver=solver_result,
        model_stats=model_stats,
        acceptance_table=acceptance_table,
        risk_measure=str(risk_measure),
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        zeta_loss_eur=float(cvar_result.zeta),
        cvar_loss_eur=float(cvar_result.cvar),
        cvar_details=scenario_economics[["scenario_id", "loss_eur", "xi_loss_excess_eur", "zeta_loss_eur", "cvar_loss_eur"]].copy(),
        reserve_diagnostics=reserve_diagnostics,
    )


def solve_stochastic_hourly_bidding(
    *,
    scenarios: pd.DataFrame,
    config: HydrogenConfig,
    run_id: str = "toy_stochastic_bidding",
    strategy_name: str = TOY_BIDDING_STRATEGY,
    bid_price_grid_eur_per_mwh: list[float] | tuple[float, ...] | None = None,
    solver_log_path: str | None = None,
    toy_case: str = "custom",
    risk_measure: str = "risk_neutral",
    cvar_alpha: float = 0.95,
    cvar_gamma: float = 0.0,
    production_target_mode: str = "current_soft_target",
    shortfall_penalty_eur_per_kg: float | None = None,
    inventory_start_kg: float | None = None,
    reserve_kg: float | None = None,
    target_hydrogen_min_kg: float | None = None,
    target_hydrogen_max_kg: float | None = None,
    terminal_reference_start_kg: float | None = None,
    firm_bid_floor_mw: list[float] | tuple[float, ...] | np.ndarray | None = None,
    emergency_import_price_eur_per_mwh: float | None = None,
    reserve_obligations_by_hour: pd.DataFrame | None = None,
) -> StochasticBiddingSolveResult:
    _ensure_solver_package(config.solver)
    _apply_gurobi_license_env(config.solver)
    risk_measure_value = str(risk_measure).strip().lower()
    if risk_measure_value not in {"risk_neutral", "cvar"}:
        raise ValueError(f"Unsupported risk_measure={risk_measure!r}. Expected 'risk_neutral' or 'cvar'.")
    if not (0.0 < float(cvar_alpha) < 1.0):
        raise ValueError(f"cvar_alpha must lie strictly between 0 and 1, got {cvar_alpha!r}.")
    if float(cvar_gamma) < 0.0:
        raise ValueError(f"cvar_gamma must be nonnegative, got {cvar_gamma!r}.")
    grid = validate_bid_price_grid(
        bid_price_grid_eur_per_mwh if bid_price_grid_eur_per_mwh is not None else list(config.bidding.bid_price_grid_eur_per_mwh)
    )
    preference = str(config.solver.package_preference).strip().lower()
    if preference in {"pyomo", "auto"} and pyo is not None:
        try:
            return _solve_with_pyomo(
                scenarios=scenarios,
                config=config,
                bid_price_grid_eur_per_mwh=grid,
                run_id=run_id,
                strategy_name=strategy_name,
                solver_log_path=solver_log_path,
                toy_case=toy_case,
                risk_measure=risk_measure_value,
                cvar_alpha=float(cvar_alpha),
                cvar_gamma=float(cvar_gamma),
                production_target_mode=production_target_mode,
                shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
                inventory_start_kg=inventory_start_kg,
                reserve_kg=reserve_kg,
                target_hydrogen_min_kg=target_hydrogen_min_kg,
                target_hydrogen_max_kg=target_hydrogen_max_kg,
                terminal_reference_start_kg=terminal_reference_start_kg,
                firm_bid_floor_mw=firm_bid_floor_mw,
                emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
                reserve_obligations_by_hour=reserve_obligations_by_hour,
            )
        except RuntimeError:
            if preference == "pyomo":
                raise
    return _solve_with_pulp(
        scenarios=scenarios,
        config=config,
        bid_price_grid_eur_per_mwh=grid,
        run_id=run_id,
        strategy_name=strategy_name,
        solver_log_path=solver_log_path,
        toy_case=toy_case,
        risk_measure=risk_measure_value,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
        production_target_mode=production_target_mode,
        shortfall_penalty_eur_per_kg=shortfall_penalty_eur_per_kg,
        inventory_start_kg=inventory_start_kg,
        reserve_kg=reserve_kg,
        target_hydrogen_min_kg=target_hydrogen_min_kg,
        target_hydrogen_max_kg=target_hydrogen_max_kg,
        terminal_reference_start_kg=terminal_reference_start_kg,
        firm_bid_floor_mw=firm_bid_floor_mw,
        emergency_import_price_eur_per_mwh=emergency_import_price_eur_per_mwh,
        reserve_obligations_by_hour=reserve_obligations_by_hour,
    )


def write_stochastic_bidding_toy_run(
    *,
    config: HydrogenConfig,
    toy_case: str = "mixed_clearing",
    output_root: Path | None = None,
    bid_price_grid_eur_per_mwh: list[float] | tuple[float, ...] | None = None,
    risk_measure: str = "risk_neutral",
    cvar_alpha: float = 0.95,
    cvar_gamma: float = 0.0,
) -> tuple[Path, StochasticBiddingSolveResult]:
    scenarios = build_toy_hourly_scenario_set(toy_case)
    run_config = build_phase5a_toy_config(config) if str(risk_measure).strip().lower() == "cvar" else build_phase4a_toy_config(config)
    if output_root is not None:
        run_config = replace(run_config, outputs=replace(run_config.outputs, root=Path(output_root)))
    run_id, run_dir = create_run_folder(run_config)
    save_config_resolved(run_dir, run_config)
    save_inputs_manifest(run_dir, [run_config.config_path])
    solver_log_path = str(run_dir / "solver_log.txt") if run_config.outputs.save_solver_log else None

    result = solve_stochastic_hourly_bidding(
        scenarios=scenarios,
        config=run_config,
        run_id=run_id,
        bid_price_grid_eur_per_mwh=bid_price_grid_eur_per_mwh,
        solver_log_path=solver_log_path,
        toy_case=toy_case,
        risk_measure=risk_measure,
        cvar_alpha=float(cvar_alpha),
        cvar_gamma=float(cvar_gamma),
    )

    save_frame_parquet(run_dir, "submitted_bids.parquet", result.submitted_bids)
    save_frame_parquet(run_dir, "scenario_clearing.parquet", result.scenario_clearing)
    save_frame_parquet(run_dir, "scenario_dispatch.parquet", result.scenario_dispatch)
    save_frame_csv(run_dir, "scenario_settlement_results.csv", result.scenario_economics)
    save_frame_csv(run_dir, "stochastic_bidding_toy_summary.csv", result.summary)
    save_json(
        run_dir,
        "model_stats.json",
        {
            "variable_count": result.model_stats.variable_count,
            "binary_variable_count": result.model_stats.binary_variable_count,
            "constraint_count": result.model_stats.constraint_count,
            "scenario_count": result.model_stats.scenario_count,
            "horizon_steps": result.model_stats.horizon_steps,
            "timestep_hours": result.model_stats.timestep_hours,
            "solver_status": result.solver.status,
            "objective_value": result.solver.objective_value,
            "solver_name": result.solver.solver_name,
            "solver_package": result.solver.solver_package,
            "solve_time_seconds": result.solver.runtime_seconds,
        },
    )
    save_json(
        run_dir,
        "input_manifest.json",
        {
            "scenario_source": "artificial_phase4a_toy",
            "toy_case": toy_case,
            "risk_measure": str(result.risk_measure),
            "cvar_alpha": result.cvar_alpha,
            "cvar_gamma": result.cvar_gamma,
            "bid_price_grid_eur_per_mwh": (
                list(bid_price_grid_eur_per_mwh)
                if bid_price_grid_eur_per_mwh is not None
                else list(run_config.bidding.bid_price_grid_eur_per_mwh)
            ),
            "scenario_probabilities": result.scenario_economics[["scenario_id", "scenario_probability"]].to_dict(orient="records"),
            "known_limitations": [
                "toy_scenarios_only",
                "hourly_only",
                "single_delivery_day_only",
                "no_real_thesis_grade_scenarios",
                "no_mfrr",
                "no_exclusive_group_bids",
                "no_endogenous_bid_prices",
            ],
        },
    )

    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    plot_submitted_bid_curves_for_hours(
        submitted_bids=result.submitted_bids,
        selected_hours=list(pd.DatetimeIndex(result.submitted_bids["delivery_start_utc"]).unique()[:2]),
        output_dir=figures_dir,
        filename="submitted_bid_curve_selected_hours.png",
    )
    plot_scenario_clearing_heatmap(
        scenario_clearing=result.scenario_clearing,
        output_dir=figures_dir,
        filename="scenario_clearing_heatmap.png",
    )
    plot_scenario_cleared_used_unused_energy(
        scenario_dispatch=result.scenario_dispatch,
        output_dir=figures_dir,
        filename="scenario_cleared_used_unused_energy.png",
    )
    plot_scenario_storage_trajectories(
        scenario_dispatch=result.scenario_dispatch,
        output_dir=figures_dir,
        filename="scenario_storage_trajectories.png",
    )
    plot_scenario_profit_distribution(
        scenario_economics=result.scenario_economics,
        output_dir=figures_dir,
        filename="scenario_profit_cost_distribution.png",
    )

    clearing_metrics = compute_stochastic_scenario_clearing_metrics(result.scenario_clearing)
    summary_text = result.summary.to_csv(index=False).strip()
    settlement_text = result.scenario_economics.to_csv(index=False).strip()
    clearing_text = clearing_metrics.to_csv(index=False).strip()
    readme_lines = [
        "# Stochastic Hourly Bidding Toy Run",
        "",
        "This toy stochastic hourly bidding run solves the Phase 4 model on artificial scenarios only.",
        "",
        f"- Run ID: `{run_id}`",
        f"- Toy case: `{toy_case}`",
        f"- Risk measure: `{result.risk_measure}`",
        f"- CVaR alpha: `{result.cvar_alpha}`",
        f"- CVaR gamma: `{result.cvar_gamma}`",
        "- First-stage bid quantities are shared across all scenarios.",
        "- Scenario clearing uses fixed bid-price tiers and pay-as-cleared settlement.",
        "- Scenario recourse can only use cleared electricity.",
        "- Accepted electricity always pays the scenario market price, never the bid price.",
        "",
        "## Summary",
        "",
        "```csv",
        summary_text,
        "```",
        "",
        "## Scenario Clearing",
        "",
        "```csv",
        clearing_text,
        "```",
        "",
        "## Scenario Economics",
        "",
        "```csv",
        settlement_text,
        "```",
        "",
        "## Known Limitations",
        "",
        "- Toy artificial scenarios only.",
        "- Hourly and D-only only.",
        "- No realised historical clearing in this run.",
        "- No mFRR, exclusive group bids, endogenous bid prices, or real scenario integration.",
        "- The tiny bid regularisation term only removes degenerate never-clearing bids; it is not an economic feature.",
    ]
    save_text(run_dir, "README_stochastic_bidding_toy.md", "\n".join(readme_lines))
    return run_dir, result
