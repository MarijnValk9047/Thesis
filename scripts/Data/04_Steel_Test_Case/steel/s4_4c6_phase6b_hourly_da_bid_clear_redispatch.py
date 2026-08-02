"""Phase 6B hourly stochastic DA bid--clear--redispatch validation.

This module deliberately wraps the frozen Phase-5K steel physics.  It adds a
single market interface: scenario-independent incremental purchase volumes on
the governed steel DA price grid.  Realised prices are loaded only after the
submitted delivery-day bid has been produced.
"""

from __future__ import annotations

import csv
import copy
import gzip
import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from pyomo.environ import (
    Block,
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)
from pyomo.contrib.fbbt.fbbt import compute_bounds_on_expr

from .model import collect_model_stats
from .rolling_production_quota import build_rolling_production_quota_plan
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    HOURS_PER_YEAR,
    _c0_real_anchor_energy_recovery_interfaces,
    _c1_source_backed_energy_boundary,
    _campaign_progress_reference_routing,
    _downstream_origin_routing,
    _electricity_boundary_levers,
    _external_procurement_flow_coefficients,
    _generator_unit_interface,
    _model_target_multiplier,
    _reference_definition,
    _rolling_production_progress_contract,
    _scrap_supply_ledger,
    _source_bounded_sensitivity_levers,
    _source_coke_chain,
    _user_authorized_emulation_overlays,
    continuous_must_run_activities,
    load_future_cost_boundary_contract,
    load_route_boundary_contract,
)
from .s4_4c5p_phase4_terminal_inventory_equivalence import (
    _case_overrides as phase4_case_overrides,
    load_phase4_config,
)
from .s4_4c5p_phase5g_final_deterministic_freeze import CONFIGURATIONS as PHASE5_CONFIGURATIONS
from .s4_4c5p_phase5k_final_user_authorized_boundary_freeze import (
    boundary_maps,
    load_final_contract,
    load_wag_audit_contract,
    wag_yield_overrides,
)
from .s4_4c_component_ontology import load_cost_policy_modes, load_external_supply_costs
from .s4_4c_unified_physical_modelbuilder import (
    EAFHeatStateParameters,
    ModelTimeGrid,
    REPO_ROOT,
    S44B_INPUT_DIR,
    _add_rolling_production_progress_tracking,
    _apply_c0_initial_inventory_overrides,
    _apply_c1_initial_inventory_overrides,
    _apply_solver_time_limit,
    _apply_wag_generation_yield_overrides,
    _add_rolling_terminal_inventory_band,
    _build_c0_inputs,
    _build_c0_model,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
    scale_c0_inputs_to_time_grid,
    scale_c1_inputs_to_time_grid,
)
from .validation_tolerance_policy import TERMINAL_STATE_TOLERANCE_T


AMSTERDAM = ZoneInfo("Europe/Amsterdam")
UTC = ZoneInfo("UTC")
MODEL_ID = "lear_lago_direct_dplus4_strict_no_future_1092"
QH_MODEL_ID = "qh-fs1__mean_shape__hourly_anchor__lear_strict"
POLICIES = ("H-point", "H-S10", "price-insensitive", "true-PF")
QH_POLICIES = ("QH-point", "QH-S10", "price-insensitive", "true-PF")
SHORT_CONFIGURATION = {C0_CONFIGURATION: "C0", C1_CONFIGURATION: "C1"}
STEEL_BID_GRID = (
    -500.0, -5.0, 25.0, 50.0, 55.0, 80.0, 90.0, 110.0,
    130.0, 155.0, 159.420290, 175.0, 210.0, 245.0, 375.0, 3000.0,
)
GRID_CANONICAL_ID = "steel_phase6b_hourly_da_bid_grid_v1"
QH_GRID_CANONICAL_ID = "steel_phase6c_qh_da_bid_grid_v1"
MIP_GAP_LIMIT = 0.001
PROBABILITY_TOLERANCE = 1e-10
MONEY_TOLERANCE_EUR = 1e-4
ENERGY_TOLERANCE_MWH = 1e-5


class Phase6BError(RuntimeError):
    """Raised when an information, physical, or accounting gate fails."""


def _phase_mapping(config: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    if isinstance(config.get("phase6d"), Mapping):
        return "phase6d", config["phase6d"]
    if isinstance(config.get("phase6c"), Mapping):
        return "phase6c", config["phase6c"]
    if isinstance(config.get("phase6b"), Mapping):
        return "phase6b", config["phase6b"]
    raise Phase6BError("C6 config must contain phase6b, phase6c or phase6d settings.")


def _time_grid_from_phase(phase: Mapping[str, Any]) -> ModelTimeGrid:
    return ModelTimeGrid(
        horizon_hours=int(phase["planning_horizon_hours"]),
        execution_hours=int(phase["execution_hours"]),
        time_step_hours=float(phase.get("time_step_hours", 1.0)),
    )


def _policy_role(policy: str) -> str:
    return {
        "QH-point": "H-point",
        "QH-S10": "H-S10",
        "H-S30": "H-S10",
        "QH-S30": "H-S10",
    }.get(policy, policy)


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grid_sha256(grid: Sequence[float] = STEEL_BID_GRID) -> str:
    payload = json.dumps([format(float(item), ".12g") for item in grid], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, payload: Any) -> None:
    """Write a resumable checkpoint without exposing a partial JSON file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_gzip_json_atomic(path: Path, payload: Any) -> None:
    """Write a compact checkpoint atomically for bounded local retention."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, sort_keys=True, default=str, separators=(",", ":"))
        handle.write("\n")
    temporary.replace(path)


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["status"])
        writer.writeheader()
        writer.writerows(materialized)


def load_phase6b_config(path: str | Path) -> dict[str, Any]:
    config_path = _resolve(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("phase6b"), dict):
        raise Phase6BError("Phase-6B config must contain a phase6b mapping.")
    phase = payload["phase6b"]
    if payload.get("output_policy") != "diagnostics" or payload.get("run_class") != "diagnostic_validation":
        raise Phase6BError("Phase-6B output classification changed.")
    if tuple(float(item) for item in phase.get("bid_grid_eur_per_mwh", ())) != STEEL_BID_GRID:
        raise Phase6BError("The frozen steel price grid changed.")
    if int(phase.get("scenario_count", 0)) != 10 or float(phase.get("cvar_gamma", -1.0)) != 0.0:
        raise Phase6BError("Phase-6B requires exactly ten scenarios and cvar_gamma=0.")
    if tuple(phase.get("policies", ())) != POLICIES:
        raise Phase6BError("The Phase-6B policy matrix changed.")
    normal_day = date.fromisoformat(str(phase["normal_day_delivery_date"]))
    week_start = date.fromisoformat(str(phase["rolling_week_start_date"]))
    week_end = date.fromisoformat(str(phase["rolling_week_end_date"]))
    if normal_day != date(2026, 4, 27) or week_start != normal_day or week_end != date(2026, 5, 3):
        raise Phase6BError("The frozen engineering fixtures changed.")
    if int(phase.get("planning_horizon_hours", 0)) != 120 or int(phase.get("execution_hours", 0)) != 24:
        raise Phase6BError("Phase-6B is restricted to hourly D--D+4 planning and D execution.")
    if phase.get("actuals_use") != "clearing_settlement_and_isolated_pf_only":
        raise Phase6BError("Actual-price information timing changed.")
    if (
        phase.get("week_terminal_target_selection_policy") != "price_insensitive_reference"
        or float(phase.get("terminal_band_fraction", -1.0)) != 0.01
        or phase.get("terminal_inventory_horizon_policy")
        != "truncate_at_campaign_endpoint_and_replace_cyclic_inventory_equalities"
    ):
        raise Phase6BError("The frozen reachability-aware terminal policy changed.")
    return payload


def load_phase6c_config(path: str | Path) -> dict[str, Any]:
    config_path = _resolve(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("phase6c"), dict):
        raise Phase6BError("Phase-6C config must contain a phase6c mapping.")
    phase = payload["phase6c"]
    if payload.get("output_policy") != "diagnostics" or payload.get("run_class") != "diagnostic_validation":
        raise Phase6BError("Phase-6C output classification changed.")
    if phase.get("granularity") != "quarterhour" or float(phase.get("time_step_hours", 0.0)) != 0.25:
        raise Phase6BError("Phase-6C requires an explicit 15-minute time grid.")
    if phase.get("model_id") != QH_MODEL_ID:
        raise Phase6BError("The frozen quarter-hour forecast model changed.")
    if tuple(float(item) for item in phase.get("bid_grid_eur_per_mwh", ())) != STEEL_BID_GRID:
        raise Phase6BError("The frozen steel price grid changed.")
    if phase.get("bid_grid_id") != QH_GRID_CANONICAL_ID:
        raise Phase6BError("The quarter-hour bid-grid identity changed.")
    if int(phase.get("scenario_count", 0)) != 10 or float(phase.get("cvar_gamma", -1.0)) != 0.0:
        raise Phase6BError("Phase-6C requires exactly ten scenarios and cvar_gamma=0.")
    if tuple(phase.get("policies", ())) != QH_POLICIES:
        raise Phase6BError("The Phase-6C policy matrix changed.")
    week_start = date.fromisoformat(str(phase["rolling_week_start_date"]))
    week_end = date.fromisoformat(str(phase["rolling_week_end_date"]))
    if week_start != date(2026, 4, 27) or week_end != date(2026, 5, 3):
        raise Phase6BError("The frozen common-support week changed.")
    grid = _time_grid_from_phase(phase)
    if grid.horizon_steps != 480 or grid.execution_steps != 96:
        raise Phase6BError("Phase-6C requires a 120-hour plan and 24-hour execution.")
    if phase.get("actuals_use") != "clearing_settlement_and_isolated_pf_only":
        raise Phase6BError("Actual-price information timing changed.")
    if phase.get("terminal_inventory_horizon_policy") != (
        "reuse_hourly_band_and_truncate_at_campaign_endpoint"
    ):
        raise Phase6BError("The frozen cross-granularity terminal policy changed.")
    terminal_path = _resolve(phase["hourly_terminal_inventory_band"])
    hourly_summary = _resolve(phase["hourly_reference_summary"])
    hourly_run_root = _resolve(phase["hourly_reference_run_root"])
    hourly_required = (
        hourly_run_root / "realised_D_redispatch.csv",
        hourly_run_root / "solver_diagnostics.csv",
    )
    if (
        not terminal_path.exists()
        or not hourly_summary.exists()
        or any(not path.exists() for path in hourly_required)
    ):
        raise Phase6BError("The frozen hourly comparison artifacts are unavailable.")
    return payload


@dataclass(frozen=True)
class SteelPriceInformationBundle:
    delivery_day: date
    forecast_origin_utc: pd.Timestamp
    timestamps_utc: tuple[pd.Timestamp, ...]
    point_prices: tuple[float, ...]
    scenario_prices: Mapping[str, tuple[float, ...]]
    scenario_probabilities: Mapping[str, float]
    scenario_source_blocks: Mapping[str, str]
    model_id: str = MODEL_ID
    granularity: str = "hourly"
    time_step_hours: float = 1.0

    def assert_actual_free(self) -> None:
        forbidden = {"actual", "actual_price", "y_true", "error", "realised_price"}
        if forbidden.intersection(self.__dict__):
            raise Phase6BError("Actual/error information leaked into the bidding bundle.")


@dataclass(frozen=True)
class SteelActualPriceBundle:
    delivery_day: date
    timestamps_utc: tuple[pd.Timestamp, ...]
    prices: tuple[float, ...]
    granularity: str = "hourly"
    time_step_hours: float = 1.0


@dataclass
class SteelRollingState:
    episode_id: str
    configuration_id: str
    inventory_overrides: dict[str, float] = field(default_factory=dict)
    cumulative_production_t: float = 0.0
    executed_hours: int = 0
    executed_intervals: int = 0
    last_executed_timestamp_utc: str | None = None
    cumulative_route_progress_t: dict[str, float] = field(default_factory=dict)
    eaf_start_lag1: int = 0
    eaf_start_lag2: int = 0
    drp_last_pellet_input_t: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "configuration_id": self.configuration_id,
            "inventory_overrides": dict(self.inventory_overrides),
            "cumulative_production_t": float(self.cumulative_production_t),
            "executed_hours": int(self.executed_hours),
            "executed_intervals": int(self.executed_intervals),
            "last_executed_timestamp_utc": self.last_executed_timestamp_utc,
            "cumulative_route_progress_t": dict(self.cumulative_route_progress_t),
            "eaf_start_lag1": int(self.eaf_start_lag1),
            "eaf_start_lag2": int(self.eaf_start_lag2),
            "drp_last_pellet_input_t": (
                None
                if self.drp_last_pellet_input_t is None
                else float(self.drp_last_pellet_input_t)
            ),
        }


@dataclass
class SteelPhysicalContext:
    config: dict[str, Any]
    tables: Any
    plan: Any
    cost_flows: tuple[dict[str, Any], ...]
    cost_tolerance_eur: float
    c0_reference_routing: Mapping[str, Any] | None
    c1_reference_routing: Mapping[str, Any]
    generator_unit_interface: Mapping[str, Any] | None
    scrap_supply_ledger: Mapping[str, Any] | None
    source_coke_chain: Mapping[str, float]
    external_procurement_coefficients: Mapping[str, float] | None
    c0_continuous_activities: tuple[str, ...]
    c1_continuous_activities: tuple[str, ...]
    c1_energy_boundary: Mapping[str, float] | None
    wag_yields: Mapping[str, Mapping[str, float]]
    bf_electricity_scales: Mapping[str, float]
    generator_interface_cap_mode: str
    hsm_rolling_electricity: float | None
    c0_aggregate_generator: Mapping[str, Any] | None
    c0_full_site_energy_bridge: Mapping[str, Any] | None
    linde_n2_mwh_h: float
    eaf_secondary_electricity: float | None
    dsp_electricity: float | None
    site_background_by_configuration: Mapping[str, float]
    site_ng_by_configuration: Mapping[str, float]
    site_steam_by_configuration: Mapping[str, float]
    site_co2_by_configuration: Mapping[str, float]
    terminal_inventory_band: Mapping[str, Mapping[str, Mapping[str, float]]]
    time_grid: ModelTimeGrid
    phase_key: str
    model_id: str
    granularity: str
    grid_id: str
    eaf_heat_state_parameters: EAFHeatStateParameters | None = None
    economic_horizon_hours: int | None = None
    physical_feasibility_tail_active: bool = False


@dataclass
class SteelBidPlan:
    policy: str
    configuration_id: str
    delivery_day: date
    bids: list[dict[str, Any]]
    scenario_dispatch: list[dict[str, Any]]
    solver: dict[str, Any]
    expected_cost_eur: float
    input_scenario_ids: tuple[str, ...]
    input_probabilities: Mapping[str, float]


@dataclass
class SteelClearingResult:
    policy: str
    configuration_id: str
    delivery_day: date
    hourly: list[dict[str, Any]]
    settlement_cost_eur: float


@dataclass
class SteelRedispatchResult:
    policy: str
    configuration_id: str
    delivery_day: date
    hourly: list[dict[str, Any]]
    next_inventory_overrides: dict[str, float]
    produced_t: float
    other_represented_cost_eur: float
    solver: dict[str, Any]
    executed_route_progress_t: dict[str, float] = field(default_factory=dict)
    time_step_hours: float = 1.0


def expected_origin_utc(delivery_day: date) -> pd.Timestamp:
    local = datetime.combine(delivery_day - timedelta(days=1), wall_time(8, 0), tzinfo=AMSTERDAM)
    return pd.Timestamp(local.astimezone(UTC))


def validate_scenario_probabilities(probabilities: Mapping[str, float], expected_count: int = 10) -> None:
    if len(probabilities) != expected_count:
        raise Phase6BError(f"Expected {expected_count} scenario probabilities, found {len(probabilities)}.")
    if any(not math.isfinite(float(item)) or float(item) < 0.0 for item in probabilities.values()):
        raise Phase6BError("Scenario probabilities must be finite and non-negative.")
    if abs(sum(float(item) for item in probabilities.values()) - 1.0) > PROBABILITY_TOLERANCE:
        raise Phase6BError("Scenario probabilities do not sum to one.")


def _local_day_mask(series: pd.Series, delivery_day: date) -> pd.Series:
    utc = pd.to_datetime(series, utc=True)
    return utc.dt.tz_convert("Europe/Amsterdam").dt.date == delivery_day


def _load_price_information(
    forecast_root: str | Path,
    delivery_day: date,
    scenario_count: int,
    *,
    granularity: str,
    model_id: str,
) -> SteelPriceInformationBundle:
    if scenario_count != 10:
        raise Phase6BError("Only the frozen nested ten-scenario set is authorized.")
    root = _resolve(forecast_root)
    prefix = "quarterhour" if granularity == "quarterhour" else "hourly"
    time_step_hours = 0.25 if granularity == "quarterhour" else 1.0
    point_path = root / "optimisation_inputs" / f"{prefix}_point_forecasts.parquet"
    scenario_path = root / "optimisation_inputs" / f"{prefix}_scenarios_10.parquet"
    point = pd.read_parquet(point_path)
    scenarios = pd.read_parquet(scenario_path)
    origin = expected_origin_utc(delivery_day)
    for frame in (point, scenarios):
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True)
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True)
    p = point[(point["forecast_origin_utc"] == origin) & (point["model_id"] == model_id)].copy()
    s = scenarios[
        (scenarios["forecast_origin_utc"] == origin)
        & (scenarios["model_id"] == model_id)
        & (scenarios["scenario_set_size"] == scenario_count)
    ].copy()
    if p.empty or s.empty:
        raise Phase6BError(f"Missing D--D+4 support for origin {origin.isoformat()}.")
    p = p.sort_values("target_timestamp_utc")
    timestamps = tuple(p["target_timestamp_utc"])
    expected_lengths = {476, 480, 484} if granularity == "quarterhour" else {119, 120, 121}
    if len(timestamps) not in expected_lengths or len(set(timestamps)) != len(timestamps):
        raise Phase6BError("Point path is not one unique DST-aware D--D+4 horizon.")
    if p["granularity"].nunique() != 1 or p["granularity"].iloc[0] != granularity:
        raise Phase6BError("Point forecast granularity changed.")
    if p["lead_day"].min() != 0 or p["lead_day"].max() != 4:
        raise Phase6BError("Point path does not cover D through D+4.")
    scenario_prices: dict[str, tuple[float, ...]] = {}
    probabilities: dict[str, float] = {}
    source_blocks: dict[str, str] = {}
    for scenario_id, group in s.groupby("scenario_id", sort=True):
        group = group.sort_values("target_timestamp_utc")
        if tuple(group["target_timestamp_utc"]) != timestamps:
            raise Phase6BError(f"Scenario {scenario_id} does not match the point timestamp support.")
        probability_values = group["scenario_probability"].drop_duplicates().tolist()
        block_values = group["source_residual_block_id"].drop_duplicates().tolist()
        if len(probability_values) != 1 or len(block_values) != 1:
            raise Phase6BError("Scenario probability or source-block identity changes within a path.")
        scenario_prices[str(scenario_id)] = tuple(float(item) for item in group["scenario_price"])
        probabilities[str(scenario_id)] = float(probability_values[0])
        source_blocks[str(scenario_id)] = str(block_values[0])
    if len(scenario_prices) != scenario_count:
        raise Phase6BError(f"Expected {scenario_count} scenarios, found {len(scenario_prices)}.")
    validate_scenario_probabilities(probabilities, scenario_count)
    bundle = SteelPriceInformationBundle(
        delivery_day=delivery_day,
        forecast_origin_utc=origin,
        timestamps_utc=timestamps,
        point_prices=tuple(float(item) for item in p["point_forecast"]),
        scenario_prices=scenario_prices,
        scenario_probabilities=probabilities,
        scenario_source_blocks=source_blocks,
        model_id=model_id,
        granularity=granularity,
        time_step_hours=time_step_hours,
    )
    bundle.assert_actual_free()
    return bundle


def load_hourly_price_information(
    forecast_root: str | Path,
    delivery_day: date,
    scenario_count: int = 10,
) -> SteelPriceInformationBundle:
    return _load_price_information(
        forecast_root, delivery_day, scenario_count,
        granularity="hourly", model_id=MODEL_ID,
    )


def load_qh_price_information(
    forecast_root: str | Path,
    delivery_day: date,
    scenario_count: int = 10,
) -> SteelPriceInformationBundle:
    return _load_price_information(
        forecast_root, delivery_day, scenario_count,
        granularity="quarterhour", model_id=QH_MODEL_ID,
    )


def _load_actual_prices(
    forecast_root: str | Path,
    delivery_day: date,
    *,
    granularity: str,
) -> SteelActualPriceBundle:
    root = _resolve(forecast_root)
    frame = pd.read_parquet(root / "evaluation_actuals.parquet")
    frame = frame[frame["granularity"] == granularity].copy()
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True)
    frame = frame[_local_day_mask(frame["target_timestamp_utc"], delivery_day)]
    prices_by_timestamp = frame.groupby("target_timestamp_utc", as_index=False)["actual_price"].agg(
        lambda values: float(values.iloc[0]) if max(values) - min(values) <= 1e-10 else math.nan
    )
    if prices_by_timestamp["actual_price"].isna().any():
        raise Phase6BError("Actual-price duplicates disagree across origins/leads.")
    prices_by_timestamp = prices_by_timestamp.sort_values("target_timestamp_utc")
    time_step_hours = 0.25 if granularity == "quarterhour" else 1.0
    expected = {92, 96, 100} if granularity == "quarterhour" else {23, 24, 25}
    if len(prices_by_timestamp) not in expected:
        raise Phase6BError(
            f"Delivery day {delivery_day} has {len(prices_by_timestamp)} actual intervals."
        )
    return SteelActualPriceBundle(
        delivery_day=delivery_day,
        timestamps_utc=tuple(prices_by_timestamp["target_timestamp_utc"]),
        prices=tuple(float(item) for item in prices_by_timestamp["actual_price"]),
        granularity=granularity,
        time_step_hours=time_step_hours,
    )


def load_hourly_actual_prices(forecast_root: str | Path, delivery_day: date) -> SteelActualPriceBundle:
    return _load_actual_prices(forecast_root, delivery_day, granularity="hourly")


def load_qh_actual_prices(forecast_root: str | Path, delivery_day: date) -> SteelActualPriceBundle:
    return _load_actual_prices(forecast_root, delivery_day, granularity="quarterhour")


def _load_oracle_prices(
    forecast_root: str | Path,
    price_bundle: SteelPriceInformationBundle,
) -> SteelActualPriceBundle:
    """Load the isolated, configuration-matched D--D+4 true-PF path."""

    root = _resolve(forecast_root)
    frame = pd.read_parquet(root / "evaluation_actuals.parquet")
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True)
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True)
    frame = frame[
        (frame["granularity"] == price_bundle.granularity)
        & (frame["forecast_origin_utc"] == price_bundle.forecast_origin_utc)
    ].sort_values("target_timestamp_utc")
    if tuple(frame["target_timestamp_utc"]) != price_bundle.timestamps_utc:
        raise Phase6BError("True-PF actual path does not exactly cover the forecast D--D+4 support.")
    if frame["actual_price"].isna().any():
        raise Phase6BError("True-PF path contains missing actual prices.")
    return SteelActualPriceBundle(
        delivery_day=price_bundle.delivery_day,
        timestamps_utc=tuple(frame["target_timestamp_utc"]),
        prices=tuple(float(item) for item in frame["actual_price"]),
        granularity=price_bundle.granularity,
        time_step_hours=price_bundle.time_step_hours,
    )


def load_hourly_oracle_prices(
    forecast_root: str | Path,
    price_bundle: SteelPriceInformationBundle,
) -> SteelActualPriceBundle:
    return _load_oracle_prices(forecast_root, price_bundle)


def load_qh_oracle_prices(
    forecast_root: str | Path,
    price_bundle: SteelPriceInformationBundle,
) -> SteelActualPriceBundle:
    return _load_oracle_prices(forecast_root, price_bundle)


def _cost_policy() -> tuple[tuple[dict[str, Any], ...], float]:
    policies = load_cost_policy_modes()
    tolerance = float(policies["deterministic_cost_tolerance_eur"]["policy_value"])
    prices = {(row["price_id"], row["scenario_id"]): row for row in load_external_supply_costs()}
    flows: list[dict[str, Any]] = []
    for row in load_future_cost_boundary_contract():
        if row.get("objective_enabled") != "true" and row.get("flow_id") != "C0_NG_GENERATOR":
            continue
        price_id = str(row["price_id"])
        scenario_id = "development_central" if price_id == "natural_gas_ttf_proxy" else str(row["price_scenario_id"])
        key = (price_id, scenario_id)
        if price_id != "grid_electricity_flat_nl" and key not in prices:
            raise Phase6BError(f"Missing governed price for flow {row['flow_id']}: {key}.")
        flows.append({
            **dict(row),
            "scenario_id": scenario_id,
            "constant_price_eur": None if price_id == "grid_electricity_flat_nl" else float(prices[key]["value"]),
        })
    if not flows:
        raise Phase6BError("No represented procurement-cost flows are active.")
    return tuple(flows), tolerance


def _load_terminal_inventory_band_csv(
    path: str | Path,
) -> dict[str, dict[str, dict[str, float]]]:
    rows = list(csv.DictReader(_resolve(path).open("r", encoding="utf-8", newline="")))
    result: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        result.setdefault(str(row["configuration_id"]), {})[str(row["state_id"])] = {
            "target_t": float(row["target_t"]),
            "lower_t": float(row["lower_t"]),
            "upper_t": float(row["upper_t"]),
        }
    if set(result) != set(CONFIGURATIONS):
        raise Phase6BError("Hourly terminal-band reference is incomplete.")
    return result


def prepare_physical_context(config: Mapping[str, Any]) -> SteelPhysicalContext:
    phase_key, phase = _phase_mapping(config)
    time_grid = _time_grid_from_phase(phase)
    physical = yaml.safe_load(_resolve(phase["physical_config"]).read_text(encoding="utf-8"))
    phase4 = load_phase4_config(_resolve(phase["phase4_config"]))
    terminal_contract = json.loads(_resolve(phase["terminal_target_contract"]).read_text(encoding="utf-8"))
    targets = terminal_contract["targets"]
    source_period = str(phase["terminal_target_source_period"])
    target_row = next((row for row in targets if row["period_id"] == source_period), None)
    if target_row is None:
        raise Phase6BError("Frozen terminal target source is unavailable.")
    placeholder_case = {
        "case_id": f"{phase_key}_context",
        "dataset_split": "test",
        "forecast_start_origin_utc": expected_origin_utc(date(2026, 4, 27)).isoformat(),
        "flat_price_eur_per_mwh": None,
        "price_field": "y_pred",
        "perfect_foresight_oracle": False,
    }
    physical.update(phase4_case_overrides(
        phase4, placeholder_case, _resolve(phase["forecast_root"]), 168, target_row["terminal_band"]
    ))
    phase5g = yaml.safe_load(_resolve(phase["phase5g_config"]).read_text(encoding="utf-8"))["phase5g"]
    final_rows = load_final_contract(_resolve(phase["phase5k_boundary_contract"]))
    wag_rows = load_wag_audit_contract(_resolve(phase["phase5k_wag_contract"]))
    electricity, ng, co2 = boundary_maps(final_rows)
    physical.update({
        "site_background_electricity_mwh_h": 0.0,
        "site_background_electricity_mwh_h_by_configuration": electricity,
        "site_baseload_ng_mwh_h_by_configuration": ng,
        "site_residual_steam_t_h_by_configuration": {key: 0.0 for key in CONFIGURATIONS},
        "site_residual_direct_co2_t_h_by_configuration": co2,
        "wag_generation_yield_overrides_by_configuration": wag_yield_overrides(wag_rows),
        "hsm_source_mix_policy_by_configuration": {
            key: dict(value) for key, value in phase5g["hsm_source_mix_policy_by_configuration"].items()
        },
        "c0_full_site_energy_bridge": None,
        "phase5g_generator_without_legacy_bridge": True,
        "phase5k_user_authorized_boundary_active": True,
        "solver_time_limit_seconds": float(phase["solver_time_limit_seconds"]),
    })
    if tuple(CONFIGURATIONS) != tuple(PHASE5_CONFIGURATIONS):
        raise Phase6BError("Phase-5K and Phase-6B configuration identities diverge.")
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=int(phase["planning_horizon_hours"]),
        execution_block_hours=int(phase["execution_hours"]),
        quota_per_execution_block_t=float(physical["quota_per_execution_block_t"]),
    )
    source_coke = _source_coke_chain(physical)
    external = _external_procurement_flow_coefficients(physical, load_route_boundary_contract())
    generator_mode, hsm_electricity = _source_bounded_sensitivity_levers(physical)
    c1_energy = _c1_source_backed_energy_boundary(physical)
    wag_yields, bf_scales, c1_energy = _user_authorized_emulation_overlays(physical, c1_energy)
    c0_aggregate, c0_bridge = _c0_real_anchor_energy_recovery_interfaces(physical)
    _, c0_routing, c1_bands = _reference_definition(physical, horizon_hours=plan.planning_horizon_hours)
    c1_routing = _downstream_origin_routing(physical, horizon_hours=plan.planning_horizon_hours, reference_bands=c1_bands)
    deadlines = sorted(plan.cumulative_deadline_targets_t)
    if c0_routing is not None:
        c0_routing["reference_band_deadline_hours"] = deadlines
    c1_routing["reference_band_deadline_hours"] = deadlines
    generator = _generator_unit_interface(physical, horizon_hours=plan.planning_horizon_hours, deadline_hours=deadlines)
    scrap = _scrap_supply_ledger(
        physical, horizon_hours=plan.planning_horizon_hours,
        execution_block_hours=plan.execution_block_hours, deadline_hours=deadlines,
    )
    linde, eaf_secondary, dsp, background, background_by = _electricity_boundary_levers(physical)
    flows, cost_tolerance = _cost_policy()
    heat_settings = phase.get("eaf_heat_state")
    eaf_heat_state = (
        EAFHeatStateParameters(
            active=bool(heat_settings.get("active", True)),
            heat_size_t_liquid_steel=float(heat_settings["heat_size_t_liquid_steel"]),
            total_qh_steps=int(heat_settings["total_qh_steps"]),
            melting_qh_steps=int(heat_settings["melting_qh_steps"]),
            tapping_qh_steps=int(heat_settings["tapping_qh_steps"]),
            arc_electricity_mwh_per_t_liquid_steel=float(
                heat_settings["arc_electricity_mwh_per_t_liquid_steel"]
            ),
            secondary_electricity_mwh_per_t_liquid_steel=float(
                heat_settings["secondary_electricity_mwh_per_t_liquid_steel"]
            ),
            design_liquid_steel_rate_t_h=float(
                heat_settings["design_liquid_steel_rate_t_h"]
            ),
            quantization_allowance_t=float(
                heat_settings["quantization_allowance_t"]
            ),
            maintenance_intervals=tuple(
                int(item) for item in heat_settings.get("maintenance_intervals", ())
            ),
        )
        if phase_key == "phase6d" and isinstance(heat_settings, Mapping)
        else None
    )
    terminal_band = (
        _load_terminal_inventory_band_csv(phase["hourly_terminal_inventory_band"])
        if phase_key == "phase6c"
        else target_row["terminal_band"]
    )
    return SteelPhysicalContext(
        config=physical, tables=_load_tables(S44B_INPUT_DIR), plan=plan,
        cost_flows=flows, cost_tolerance_eur=cost_tolerance,
        c0_reference_routing=c0_routing, c1_reference_routing=c1_routing,
        generator_unit_interface=generator, scrap_supply_ledger=scrap,
        source_coke_chain=source_coke, external_procurement_coefficients=external,
        c0_continuous_activities=tuple(continuous_must_run_activities(C0_CONFIGURATION)),
        # Phase-6B/6C keep C1 availability endogenous.  Phase-6D changes only
        # the EAF formulation and must not reopen the separate C1
        # continuous-must-run reconciliation.
        c1_continuous_activities=(),
        c1_energy_boundary=c1_energy,
        wag_yields=wag_yields, bf_electricity_scales=bf_scales,
        generator_interface_cap_mode=generator_mode, hsm_rolling_electricity=hsm_electricity,
        c0_aggregate_generator=c0_aggregate, c0_full_site_energy_bridge=c0_bridge,
        linde_n2_mwh_h=linde, eaf_secondary_electricity=eaf_secondary,
        dsp_electricity=dsp, site_background_by_configuration=background_by,
        site_ng_by_configuration=physical["site_baseload_ng_mwh_h_by_configuration"],
        site_steam_by_configuration=physical["site_residual_steam_t_h_by_configuration"],
        site_co2_by_configuration=physical["site_residual_direct_co2_t_h_by_configuration"],
        terminal_inventory_band=terminal_band,
        time_grid=time_grid,
        phase_key=phase_key,
        model_id=str(phase.get("model_id", MODEL_ID)),
        granularity=str(phase.get("granularity", "hourly")),
        grid_id=str(phase.get("bid_grid_id", GRID_CANONICAL_ID)),
        eaf_heat_state_parameters=eaf_heat_state,
        economic_horizon_hours=(
            int(phase["economic_horizon_hours"])
            if phase.get("economic_horizon_hours") is not None
            else None
        ),
        physical_feasibility_tail_active=bool(
            phase.get("physical_feasibility_tail_active", False)
        ),
    )


def episode_planning_horizon_hours(
    *,
    fixture_id: str,
    day_index: int,
    day_count: int,
    nominal_horizon_hours: int = 120,
) -> int:
    """Apply the frozen campaign-endpoint truncation policy to a fixture."""
    if fixture_id != "rolling_week":
        return int(nominal_horizon_hours)
    remaining = (int(day_count) - int(day_index)) * 24
    if remaining <= 0:
        raise Phase6BError("The rolling-week campaign endpoint must follow the replan origin.")
    return min(int(nominal_horizon_hours), remaining)


def _progress_contract(
    context: SteelPhysicalContext,
    state: SteelRollingState,
    *,
    terminal_day: bool,
    planning_horizon_hours: int,
) -> tuple[Any, dict[str, Any]]:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=int(planning_horizon_hours),
        execution_block_hours=context.plan.execution_block_hours,
        quota_per_execution_block_t=context.plan.quota_per_execution_block_t,
    )
    base_multiplier = _model_target_multiplier(context.config, plan)
    cumulative = {key: 0.0 for key in CONFIGURATIONS}
    cumulative[state.configuration_id] = float(state.cumulative_production_t)
    progress = _rolling_production_progress_contract(
        plan=plan,
        replan_index=int(state.executed_hours // plan.execution_block_hours),
        cumulative_before=cumulative,
        base_target_multiplier=base_multiplier,
        enabled=True,
        envelope_fraction=0.005,
        terminal_exact=terminal_day,
        central_target_before_t=(
            float(context.config["annual_reference_target_mt_y"])
            * 1_000_000.0 * float(state.executed_hours) / HOURS_PER_YEAR
        ),
        terminal_recoverability_enabled=False,
        exact_deadline_hour=plan.execution_block_hours if terminal_day else None,
    )
    return plan, progress


def _horizon_dependent_interfaces(
    context: SteelPhysicalContext,
    plan: Any,
    state: SteelRollingState,
    *,
    campaign_endpoint_active: bool,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None]:
    definition_rows, c0_routing, c1_bands = _reference_definition(
        context.config, horizon_hours=plan.planning_horizon_hours
    )
    c1_routing = _downstream_origin_routing(
        context.config,
        horizon_hours=plan.planning_horizon_hours,
        reference_bands=c1_bands,
    )
    deadlines = sorted(plan.cumulative_deadline_targets_t)
    if campaign_endpoint_active:
        executed_rows = [{
            "configuration_id": state.configuration_id,
            **state.cumulative_route_progress_t,
        }]
        if state.configuration_id == C0_CONFIGURATION:
            c0_routing = _campaign_progress_reference_routing(
                c0_routing,
                definition_rows=definition_rows,
                configuration=C0_CONFIGURATION,
                executed_rows=executed_rows,
                executed_hours_before=state.executed_hours,
                deadline_hours=deadlines,
            )
        else:
            c1_routing = _campaign_progress_reference_routing(
                c1_routing,
                definition_rows=definition_rows,
                configuration=C1_CONFIGURATION,
                executed_rows=executed_rows,
                executed_hours_before=state.executed_hours,
                deadline_hours=deadlines,
            )
    if c0_routing is not None:
        c0_routing["reference_band_deadline_hours"] = deadlines
    c1_routing["reference_band_deadline_hours"] = deadlines
    generator = _generator_unit_interface(
        context.config,
        horizon_hours=plan.planning_horizon_hours,
        deadline_hours=deadlines,
    )
    scrap = _scrap_supply_ledger(
        context.config,
        horizon_hours=plan.planning_horizon_hours,
        execution_block_hours=plan.execution_block_hours,
        deadline_hours=deadlines,
    )
    if context.eaf_heat_state_parameters is not None:
        allowance = context.eaf_heat_state_parameters.quantization_allowance_t
        c1_routing = copy.deepcopy(c1_routing)
        eaf_band = c1_routing.get("reference_validation_bands", {}).get(
            "eaf_liquid_steel"
        )
        if eaf_band is None:
            raise Phase6BError(
                "Phase-6D requires the cumulative EAF liquid-steel route band."
            )
        eaf_band["quantization_allowance_t"] = allowance
        deadline_bands = c1_routing.get("reference_deadline_bands", {}).get(
            "eaf_liquid_steel", {}
        )
        for band in deadline_bands.values():
            band["quantization_allowance_t"] = allowance
        c1_routing["eaf_heat_quantization_policy"] = (
            "original_cumulative_band_plus_half_heat_each_side"
        )
    return c0_routing, c1_routing, generator, scrap


_RATE_FIELD_SUFFIXES = ("_mwh_h", "_t_h", "_nm3_h", "_max_t_h")
_RATE_FIELD_NAMES = {
    "electrical_capacity_mw",
    "vn25_electric_capacity_mw",
}


def _scale_interval_rate_fields(value_in: Any, time_step_hours: float, *, parent_key: str = "") -> Any:
    """Scale known hourly-rate fields without touching totals or intensities."""

    if isinstance(value_in, Mapping):
        result: dict[Any, Any] = {}
        for key, value in value_in.items():
            key_text = str(key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and (
                    key_text.endswith(_RATE_FIELD_SUFFIXES)
                    or key_text in _RATE_FIELD_NAMES
                    or parent_key.endswith(("_nm3_h", "_mwh_h", "_t_h"))
                )
            ):
                result[key] = float(value) * time_step_hours
            else:
                result[key] = _scale_interval_rate_fields(
                    value, time_step_hours, parent_key=key_text
                )
        return result
    if isinstance(value_in, list):
        return [
            _scale_interval_rate_fields(value, time_step_hours, parent_key=parent_key)
            for value in value_in
        ]
    if isinstance(value_in, tuple):
        return tuple(
            _scale_interval_rate_fields(value, time_step_hours, parent_key=parent_key)
            for value in value_in
        )
    return copy.deepcopy(value_in)


def _convert_deadline_keys(mapping: Mapping[int, Any], grid: ModelTimeGrid) -> dict[int, Any]:
    return {grid.hours_to_steps(int(hour)): copy.deepcopy(value) for hour, value in mapping.items()}


def _scale_interfaces_to_time_grid(
    grid: ModelTimeGrid,
    c0_routing: Mapping[str, Any] | None,
    c1_routing: Mapping[str, Any],
    generator: Mapping[str, Any] | None,
    scrap: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None]:
    c0 = None if c0_routing is None else _scale_interval_rate_fields(c0_routing, grid.time_step_hours)
    c1 = _scale_interval_rate_fields(c1_routing, grid.time_step_hours)
    gen = None if generator is None else _scale_interval_rate_fields(generator, grid.time_step_hours)
    scrap_scaled = None if scrap is None else _scale_interval_rate_fields(scrap, grid.time_step_hours)
    for routing in (c0, c1):
        if routing is None:
            continue
        if "reference_band_deadline_hours" in routing:
            routing["reference_band_deadline_hours"] = [
                grid.hours_to_steps(int(hour))
                for hour in routing["reference_band_deadline_hours"]
            ]
        if "reference_deadline_bands" in routing:
            routing["reference_deadline_bands"] = {
                metric: _convert_deadline_keys(deadlines, grid)
                for metric, deadlines in routing["reference_deadline_bands"].items()
            }
    if gen is not None and "ij01_total_fuel_deadline_caps_mwh" in gen:
        gen["ij01_total_fuel_deadline_caps_mwh"] = _convert_deadline_keys(
            gen["ij01_total_fuel_deadline_caps_mwh"], grid
        )
    if scrap_scaled is not None:
        for key in (
            "site_total_scrap_supply_deadline_caps_t",
            "bof_scrap_supply_deadline_caps_t",
            "eaf_scrap_supply_deadline_caps_t",
        ):
            if key in scrap_scaled:
                scrap_scaled[key] = _convert_deadline_keys(scrap_scaled[key], grid)
    return c0, c1, gen, scrap_scaled


def _build_physical_model(
    context: SteelPhysicalContext,
    configuration: str,
    state: SteelRollingState,
    *,
    terminal_day: bool,
    planning_horizon_hours: int = 120,
    terminal_hour_in_horizon: int | None = None,
) -> ConcreteModel:
    grid = ModelTimeGrid(
        horizon_hours=int(planning_horizon_hours),
        execution_hours=context.time_grid.execution_hours,
        time_step_hours=context.time_grid.time_step_hours,
    )
    plan, progress = _progress_contract(
        context,
        state,
        terminal_day=terminal_day,
        planning_horizon_hours=planning_horizon_hours,
    )
    if terminal_hour_in_horizon is not None and int(terminal_hour_in_horizon) != plan.planning_horizon_hours:
        raise Phase6BError("The campaign endpoint must equal the truncated planning horizon.")
    c0_routing, c1_routing, generator, scrap = _horizon_dependent_interfaces(
        context,
        plan,
        state,
        campaign_endpoint_active=terminal_hour_in_horizon is not None,
    )
    c0_routing, c1_routing, generator, scrap = _scale_interfaces_to_time_grid(
        grid, c0_routing, c1_routing, generator, scrap
    )
    multiplier = float(progress["target_multiplier_by_configuration"][configuration])
    deadline_targets = {
        grid.hours_to_steps(int(hour)): float(target)
        for hour, target in progress["deadline_targets_by_configuration_t"][configuration].items()
    }
    commitment_day_lengths = [grid.hours_to_steps(24)] * (plan.planning_horizon_hours // 24)
    hsm_source_mix = copy.deepcopy(
        context.config["hsm_source_mix_policy_by_configuration"][configuration]
    )
    hsm_source_mix["block_hours"] = grid.hours_to_steps(int(hsm_source_mix["block_hours"]))
    aggregate_generator = (
        None
        if context.c0_aggregate_generator is None
        else _scale_interval_rate_fields(
            context.c0_aggregate_generator, grid.time_step_hours
        )
    )
    if configuration == C0_CONFIGURATION:
        inputs = _build_c0_inputs(
            context.tables,
            horizon_hours_override=plan.planning_horizon_hours,
            target_multiplier=multiplier,
        )
        inputs = _apply_wag_generation_yield_overrides(inputs, context.wag_yields.get(configuration))
        inputs = _apply_c0_initial_inventory_overrides(inputs, state.inventory_overrides)
        inputs = scale_c0_inputs_to_time_grid(inputs, grid)
        model = _build_c0_model(
            inputs, time_step_hours=grid.time_step_hours,
            fix_binary_schedule=False, enable_minimal_wag_layer=True,
            enable_internal_wag_power=True,
            development_controller_activation=str(context.config["development_controller_activation"]),
            rolling_production_deadline_targets_t=deadline_targets,
            commitment_granularity=str(context.config["commitment_granularity"]),
            commitment_day_lengths=commitment_day_lengths,
            continuous_must_run_activities=context.c0_continuous_activities,
            c0_coke_chain_reconciliation=context.source_coke_chain,
            c0_downstream_reference_routing=c0_routing,
            linde_n2_auxiliary_electricity_mwh_h=context.linde_n2_mwh_h * grid.time_step_hours,
            site_background_electricity_mwh_h=float(context.site_background_by_configuration[configuration]) * grid.time_step_hours,
            site_baseload_ng_mwh_h=float(context.site_ng_by_configuration[configuration]) * grid.time_step_hours,
            site_residual_steam_t_h=float(context.site_steam_by_configuration[configuration]) * grid.time_step_hours,
            site_residual_direct_co2_t_h=float(context.site_co2_by_configuration[configuration]) * grid.time_step_hours,
            external_procurement_flow_coefficients=context.external_procurement_coefficients,
            bf_electricity_intensity_scale=float(context.bf_electricity_scales[configuration]),
            aggregate_generator_technical_interface=aggregate_generator,
            full_site_energy_bridge=context.c0_full_site_energy_bridge,
            hsm_source_mix_policy=hsm_source_mix,
        )
    elif configuration == C1_CONFIGURATION:
        inputs = _build_c1_inputs(
            context.tables,
            horizon_hours_override=plan.planning_horizon_hours,
            target_multiplier=multiplier,
            include_retained_bf_bof=True,
        )
        inputs = _apply_wag_generation_yield_overrides(inputs, context.wag_yields.get(configuration))
        inputs = _apply_c1_initial_inventory_overrides(inputs, state.inventory_overrides)
        inputs = scale_c1_inputs_to_time_grid(inputs, grid)
        heat_state = (
            replace(
                context.eaf_heat_state_parameters,
                initial_start_lag1=int(state.eaf_start_lag1),
                initial_start_lag2=int(state.eaf_start_lag2),
                require_idle_terminal_state=bool(terminal_day),
            )
            if context.eaf_heat_state_parameters is not None
            else None
        )
        model = _build_c1_model(
            inputs, time_step_hours=grid.time_step_hours,
            enable_minimal_wag_layer=True, enable_c1_retained_bf_bof_route=True,
            enable_internal_wag_power=True,
            development_controller_activation=str(context.config["development_controller_activation"]),
            hsm_rolling_electricity_mwh_per_t_hrc_override=context.hsm_rolling_electricity,
            rolling_production_deadline_targets_t=deadline_targets,
            fix_c1_hybrid_schedule=False, c1_retained_route_policy="quota_driven_topology",
            commitment_granularity=str(context.config["commitment_granularity"]),
            commitment_day_lengths=commitment_day_lengths,
            eaf_material_balance=context.config["eaf_material_balance"],
            bof_material_balance=context.config["bof_material_balance"],
            scrap_supply_ledger=scrap,
            downstream_origin_routing=c1_routing,
            c1_liquid_steel_route_band=None,
            continuous_must_run_activities=context.c1_continuous_activities,
            c1_coke_chain_reconciliation=context.source_coke_chain,
            linde_n2_auxiliary_electricity_mwh_h=context.linde_n2_mwh_h * grid.time_step_hours,
            site_background_electricity_mwh_h=float(context.site_background_by_configuration[configuration]) * grid.time_step_hours,
            site_baseload_ng_mwh_h=float(context.site_ng_by_configuration[configuration]) * grid.time_step_hours,
            site_residual_steam_t_h=float(context.site_steam_by_configuration[configuration]) * grid.time_step_hours,
            site_residual_direct_co2_t_h=float(context.site_co2_by_configuration[configuration]) * grid.time_step_hours,
            hsm_source_mix_policy=hsm_source_mix,
            generator_interface_cap_mode=context.generator_interface_cap_mode,
            generator_unit_interface=generator,
            c1_energy_boundary=context.c1_energy_boundary,
            eaf_secondary_electricity_mwh_per_t_ls_override=context.eaf_secondary_electricity,
            dsp_electricity_mwh_per_t_coil_override=context.dsp_electricity,
            external_procurement_flow_coefficients=context.external_procurement_coefficients,
            bf_electricity_intensity_scale=float(context.bf_electricity_scales[configuration]),
            eaf_heat_state_parameters=heat_state,
            initial_drp_pellet_input_t=state.drp_last_pellet_input_t,
        )
    else:
        raise Phase6BError(f"Unknown steel configuration: {configuration}.")
    _add_rolling_production_progress_tracking(
        model, execution_block_hours=grid.execution_steps,
        next_execution_target_t=float(progress["progress_target_by_configuration_t"][configuration]),
        hard_exact_execution_target=terminal_day,
        exact_deadline_hour=(
            grid.hours_to_steps(int(terminal_hour_in_horizon))
            if terminal_hour_in_horizon is not None
            else None
        ),
        exact_deadline_target_t=(
            float(context.config["annual_reference_target_mt_y"])
            * 1_000_000.0
            * float(state.executed_hours + int(terminal_hour_in_horizon))
            / HOURS_PER_YEAR
            - float(state.cumulative_production_t)
            if terminal_hour_in_horizon is not None
            else None
        ),
    )
    if terminal_hour_in_horizon is not None:
        _add_rolling_terminal_inventory_band(
            model,
            terminal_hour=grid.hours_to_steps(int(terminal_hour_in_horizon)),
            bounds_t=context.terminal_inventory_band[configuration],
        )
    model.static_price_naive_objective.deactivate()
    return model


def _applicable_cost_flows(context: SteelPhysicalContext, configuration: str) -> list[Mapping[str, Any]]:
    short = SHORT_CONFIGURATION[configuration]
    return [flow for flow in context.cost_flows if flow.get("configuration") in {short, "both"}]


def _represented_cost_expression(
    context: SteelPhysicalContext,
    model: Any,
    configuration: str,
    electricity_prices: Sequence[float],
    *,
    zero_electricity_hours: int = 0,
    objective_hours: Sequence[int] | None = None,
) -> Any:
    terms: list[Any] = []
    selected_hours = tuple(int(t) for t in (objective_hours if objective_hours is not None else model.TIME))
    for flow in _applicable_cost_flows(context, configuration):
        attributes = str(flow["model_component_attribute"]).split(";")
        is_grid = str(flow["price_id"]) == "grid_electricity_flat_nl"
        for attribute in attributes:
            if not hasattr(model, attribute):
                raise Phase6BError(f"Frozen physical cost component is missing: {attribute}.")
            component = getattr(model, attribute)
            for t in selected_hours:
                price = (
                    0.0 if is_grid and int(t) < zero_electricity_hours
                    else float(electricity_prices[int(t)]) if is_grid
                    else float(flow["constant_price_eur"])
                )
                terms.append(price * component[t])
    return sum(terms)


def _solver_gap(result: Any) -> float | None:
    try:
        gap = result.solver.get("gap")
        return None if gap is None else abs(float(gap))
    except Exception:
        return None


def _solve_active_objective(model: ConcreteModel, solver: Any, tier: str) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    result = solver.solve(model)
    runtime = time.perf_counter() - started
    termination = str(result.solver.termination_condition).lower()
    gap = _solver_gap(result)
    accepted = termination in {"optimal", "feasible"} or (
        termination in {"maxtimelimit", "maxTimeLimit".lower()} and gap is not None and gap <= MIP_GAP_LIMIT
    )
    if not accepted:
        raise Phase6BError(f"{tier} solve failed: {result.solver.status}/{result.solver.termination_condition}, gap={gap}.")
    return result, {
        "tier": tier, "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "mip_gap": gap, "runtime_seconds": runtime,
    }


def _import_upper_bound(model: ConcreteModel) -> float:
    bounds = [compute_bounds_on_expr(model.net_grid_import_mwh[t])[1] for t in model.TIME]
    finite = [float(item) for item in bounds if item is not None and math.isfinite(float(item))]
    if len(finite) != len(model.TIME) or min(finite) < 0.0:
        raise Phase6BError("A finite physical hourly import upper bound could not be proved.")
    return max(finite)


def _scenario_inputs(
    policy: str,
    price_bundle: SteelPriceInformationBundle,
    actuals: SteelActualPriceBundle | None,
) -> tuple[dict[str, tuple[float, ...]], dict[str, float]]:
    horizon = len(price_bundle.timestamps_utc)
    duration_hours = horizon * float(price_bundle.time_step_hours)
    if duration_hours < 24.0 or duration_hours > 120.0 or duration_hours % 24.0:
        raise Phase6BError("Planning support must contain one to five complete delivery days.")
    role = _policy_role(policy)
    if role == "H-S10":
        return dict(price_bundle.scenario_prices), dict(price_bundle.scenario_probabilities)
    if role == "H-point":
        return {"point": price_bundle.point_prices}, {"point": 1.0}
    if role == "price-insensitive":
        return {"flat80": tuple(80.0 for _ in range(horizon))}, {"flat80": 1.0}
    if role == "true-PF":
        if actuals is None:
            raise Phase6BError("True PF requires the isolated actual-price oracle.")
        if tuple(price_bundle.timestamps_utc[: len(actuals.timestamps_utc)]) != actuals.timestamps_utc:
            raise Phase6BError("PF actual D timestamps do not match the forecast horizon.")
        if len(actuals.prices) != horizon or actuals.timestamps_utc != price_bundle.timestamps_utc:
            raise Phase6BError("True PF requires the complete matched actual D--D+4 path.")
        return {"oracle": tuple(actuals.prices)}, {"oracle": 1.0}
    raise Phase6BError(f"Unknown C6 policy: {policy}.")


def solve_hourly_da_bid_plan(
    context: SteelPhysicalContext,
    configuration: str,
    price_bundle: SteelPriceInformationBundle,
    bid_grid: Sequence[float],
    rolling_state: SteelRollingState,
    policy: str,
    *,
    actuals_oracle: SteelActualPriceBundle | None = None,
    terminal_day: bool = False,
    terminal_hour_in_horizon: int | None = None,
    audit_future_paths: bool = False,
) -> SteelBidPlan:
    if tuple(float(item) for item in bid_grid) != STEEL_BID_GRID:
        raise Phase6BError("Bid grid differs from the frozen Phase-6B grid.")
    if _policy_role(policy) != "true-PF" and actuals_oracle is not None:
        raise Phase6BError("Actual prices were supplied to an executable non-oracle bid.")
    scenario_prices, probabilities = _scenario_inputs(policy, price_bundle, actuals_oracle)
    planning_hours = (
        int(terminal_hour_in_horizon)
        if terminal_hour_in_horizon is not None
        else int(round(len(price_bundle.timestamps_utc) * price_bundle.time_step_hours))
    )
    planning_intervals = int(round(planning_hours / price_bundle.time_step_hours))
    if planning_hours < 24 or planning_hours > 120 or planning_hours % 24 != 0:
        raise Phase6BError("Phase-6B engineering horizons must contain one to five complete days.")
    scenario_prices = {
        scenario_id: tuple(prices[:planning_intervals])
        for scenario_id, prices in scenario_prices.items()
    }
    base = _build_physical_model(
        context, configuration, rolling_state, terminal_day=terminal_day,
        planning_horizon_hours=planning_hours,
        terminal_hour_in_horizon=terminal_hour_in_horizon,
    )
    root = ConcreteModel()
    scenario_ids = tuple(sorted(scenario_prices))
    root.SCENARIO = Set(initialize=scenario_ids, ordered=True)
    root.TIME = Set(initialize=tuple(range(planning_intervals)), ordered=True)
    root.BID = Set(initialize=tuple(float(item) for item in bid_grid), ordered=True)
    root.bid_volume_mwh = Var(root.TIME, root.BID, domain=NonNegativeReals)
    root.scenario = Block(root.SCENARIO)
    for scenario_id in scenario_ids:
        root.scenario[scenario_id].transfer_attributes_from(base.clone())
    if _policy_role(policy) == "price-insensitive":
        for t in root.TIME:
            for bid_price in root.BID:
                if float(bid_price) != max(STEEL_BID_GRID):
                    root.bid_volume_mwh[t, bid_price].fix(0.0)
    root.scenario_clearing = Constraint(
        root.SCENARIO, root.TIME,
        rule=lambda m, s, t: m.scenario[s].net_grid_import_mwh[t]
        == sum(
            m.bid_volume_mwh[t, b]
            for b in m.BID
            if float(b) >= float(scenario_prices[str(s)][int(t)])
        ),
    )
    progress_expr = sum(
        float(probabilities[str(s)]) * root.scenario[s].rolling_production_progress_deviation_t
        for s in root.SCENARIO
    )
    cost_expr = sum(
        float(probabilities[str(s)])
        * _represented_cost_expression(
            context, root.scenario[s], configuration, scenario_prices[str(s)],
            objective_hours=(
                tuple(range(int(round(24.0 / price_bundle.time_step_hours))))
                if _policy_role(policy) == "true-PF"
                else None
            ),
        )
        for s in root.SCENARIO
    )
    tie_expr = sum(
        float(probabilities[str(s)]) * root.scenario[s].static_price_naive_objective.expr
        for s in root.SCENARIO
    )
    solver_name, solver = _select_solver()
    if solver is None or not str(solver_name).startswith("gurobi"):
        raise Phase6BError("Phase-6B requires the frozen Gurobi solver family.")
    _apply_solver_time_limit(solver_name, solver, float(context.config["solver_time_limit_seconds"]))
    solver.options["MIPGap"] = MIP_GAP_LIMIT
    tiers: list[dict[str, Any]] = []
    root.progress_objective = Objective(expr=progress_expr, sense=minimize)
    _, record = _solve_active_objective(root, solver, "production_progress")
    tiers.append(record)
    progress_optimum = float(value(progress_expr))
    root.progress_preservation = Constraint(expr=progress_expr <= progress_optimum + 1e-6)
    root.progress_objective.deactivate()
    root.expected_cost_objective = Objective(expr=cost_expr, sense=minimize)
    _, record = _solve_active_objective(root, solver, "expected_represented_cost")
    tiers.append(record)
    cost_optimum = float(value(cost_expr))
    root.cost_preservation = Constraint(expr=cost_expr <= cost_optimum + context.cost_tolerance_eur)
    root.expected_cost_objective.deactivate()
    root.physical_tiebreak_objective = Objective(expr=tie_expr, sense=minimize)
    _, record = _solve_active_objective(root, solver, "physical_tiebreak")
    tiers.append(record)
    tie_optimum = float(value(tie_expr))
    root.tie_preservation = Constraint(expr=tie_expr <= tie_optimum + 1e-6)
    root.physical_tiebreak_objective.deactivate()
    root.canonical_bid_objective = Objective(
        expr=sum(
            (1.0 + 1e-6 * (len(STEEL_BID_GRID) - index)) * root.bid_volume_mwh[t, b]
            for t in root.TIME for index, b in enumerate(root.BID)
        ), sense=minimize,
    )
    final_result, record = _solve_active_objective(root, solver, "canonical_bid_curve")
    tiers.append(record)
    bids: list[dict[str, Any]] = []
    execution_intervals = int(round(24.0 / price_bundle.time_step_hours))
    for t in range(execution_intervals):
        timestamp = price_bundle.timestamps_utc[t]
        for bid_price in STEEL_BID_GRID:
            quantity = float(value(root.bid_volume_mwh[t, bid_price]))
            bids.append({
                "policy": policy, "configuration_id": configuration,
                "delivery_day": price_bundle.delivery_day.isoformat(),
                "forecast_origin_utc": price_bundle.forecast_origin_utc.isoformat(),
                "target_timestamp_utc": timestamp.isoformat(),
                "interval_index": t,
                "hour_index": t if price_bundle.granularity == "hourly" else "",
                "time_step_hours": price_bundle.time_step_hours,
                "granularity": price_bundle.granularity,
                "bid_grid_id": context.grid_id, "bid_grid_sha256": grid_sha256(),
                "bid_price_eur_per_mwh": bid_price, "incremental_bid_volume_mwh": quantity,
                "information_timing": "isolated_oracle" if _policy_role(policy) == "true-PF" else "forecast_origin_only",
            })
    scenario_dispatch: list[dict[str, Any]] = []
    dispatch_intervals = planning_intervals if audit_future_paths else execution_intervals
    for scenario_id in scenario_ids:
        block = root.scenario[scenario_id]
        for t in range(dispatch_intervals):
            scenario_dispatch.append({
                "policy": policy, "configuration_id": configuration,
                "scenario_id": scenario_id, "scenario_probability": probabilities[scenario_id],
                "interval_index": t,
                "hour_index": t if price_bundle.granularity == "hourly" else "",
                "time_step_hours": price_bundle.time_step_hours,
                "granularity": price_bundle.granularity,
                "target_timestamp_utc": price_bundle.timestamps_utc[t].isoformat(),
                "scenario_price_eur_per_mwh": scenario_prices[scenario_id][t],
                "planned_net_grid_import_mwh": float(value(block.net_grid_import_mwh[t])),
                "planned_final_product_t": float(value(block.final_product_output[t])),
            })
    stats = collect_model_stats(root)
    solver_record = {
        "solver_name": solver_name, "solver_status": str(final_result.solver.status),
        "termination_condition": str(final_result.solver.termination_condition),
        "mip_gap": _solver_gap(final_result), "variable_count": stats.variables,
        "binary_count": stats.binaries, "constraint_count": stats.constraints,
        "scenario_count": len(scenario_ids), "planning_hours": planning_hours,
        "planning_intervals": planning_intervals,
        "time_step_hours": price_bundle.time_step_hours,
        "granularity": price_bundle.granularity,
        "scenario_ids_json": json.dumps(scenario_ids),
        "scenario_probability_sum": sum(float(item) for item in probabilities.values()),
        "scenario_probabilities_json": json.dumps(probabilities, sort_keys=True),
        "scenario_source_blocks_json": json.dumps(
            {
                scenario_id: price_bundle.scenario_source_blocks.get(
                    scenario_id, "not_applicable_synthetic_or_single_path"
                )
                for scenario_id in scenario_ids
            },
            sort_keys=True,
        ),
        "bid_grid_steps": len(STEEL_BID_GRID),
        "bid_quantity_bound": "endogenous_frozen_physical_import_constraints_and_canonical_minimum_total_bid_volume",
        "canonical_bid_tiebreak": "minimum_total_volume_then_highest_willingness_price",
        "tier_solves": tiers, "total_solver_seconds": sum(item["runtime_seconds"] for item in tiers),
    }
    return SteelBidPlan(
        policy=policy, configuration_id=configuration, delivery_day=price_bundle.delivery_day,
        bids=bids, scenario_dispatch=scenario_dispatch, solver=solver_record,
        expected_cost_eur=cost_optimum, input_scenario_ids=scenario_ids,
        input_probabilities=probabilities,
    )


def clear_hourly_da_bids(
    submitted_D_bids: Sequence[Mapping[str, Any]],
    realised_D_prices: SteelActualPriceBundle,
) -> SteelClearingResult:
    if not submitted_D_bids:
        raise Phase6BError("No D bids were submitted.")
    policy = str(submitted_D_bids[0]["policy"])
    configuration = str(submitted_D_bids[0]["configuration_id"])
    by_timestamp: dict[str, list[Mapping[str, Any]]] = {}
    for row in submitted_D_bids:
        by_timestamp.setdefault(str(row["target_timestamp_utc"]), []).append(row)
    if set(by_timestamp) != {item.isoformat() for item in realised_D_prices.timestamps_utc}:
        raise Phase6BError("Submitted D bids and actual-price timestamps differ.")
    rows: list[dict[str, Any]] = []
    for timestamp, actual in zip(realised_D_prices.timestamps_utc, realised_D_prices.prices):
        tiers = by_timestamp[timestamp.isoformat()]
        cleared = sum(
            float(row["incremental_bid_volume_mwh"])
            for row in tiers if float(row["bid_price_eur_per_mwh"]) >= float(actual)
        )
        rows.append({
            "policy": policy, "configuration_id": configuration,
            "delivery_day": realised_D_prices.delivery_day.isoformat(),
            "target_timestamp_utc": timestamp.isoformat(),
            "granularity": realised_D_prices.granularity,
            "time_step_hours": realised_D_prices.time_step_hours,
            "realised_price_eur_per_mwh": float(actual),
            "cleared_energy_mwh": cleared,
            "settlement_cost_eur": cleared * float(actual),
            "acceptance_rule": "bid_price_greater_than_or_equal_to_actual_price",
        })
    return SteelClearingResult(
        policy=policy, configuration_id=configuration,
        delivery_day=realised_D_prices.delivery_day, hourly=rows,
        settlement_cost_eur=sum(float(row["settlement_cost_eur"]) for row in rows),
    )


def _solve_redispatch_model(
    context: SteelPhysicalContext,
    configuration: str,
    state: SteelRollingState,
    clearing: SteelClearingResult,
    future_point_prices: Sequence[float],
    *,
    terminal_day: bool,
    terminal_hour_in_horizon: int | None,
    oracle_execute_D_cost_only: bool,
) -> tuple[ConcreteModel, dict[str, Any], float]:
    planning_hours = (
        int(terminal_hour_in_horizon)
        if terminal_hour_in_horizon is not None
        else context.plan.planning_horizon_hours
    )
    planning_intervals = int(round(planning_hours / context.time_grid.time_step_hours))
    if len(future_point_prices) < planning_intervals:
        raise Phase6BError("Redispatch future-price support is shorter than its physical horizon.")
    model = _build_physical_model(
        context, configuration, state, terminal_day=terminal_day,
        planning_horizon_hours=planning_hours,
        terminal_hour_in_horizon=terminal_hour_in_horizon,
    )
    cleared = [float(row["cleared_energy_mwh"]) for row in clearing.hourly]
    model.PHASE6B_EXECUTION = Set(initialize=tuple(range(len(cleared))), ordered=True)
    model.phase6b_cleared_import = Constraint(
        model.PHASE6B_EXECUTION,
        rule=lambda m, t: m.net_grid_import_mwh[t] == cleared[int(t)],
    )
    progress_expr = model.rolling_production_progress_deviation_t
    prices = (
        tuple(0.0 for _ in cleared)
        + tuple(float(item) for item in future_point_prices[len(cleared):planning_intervals])
    )
    cost_expr = _represented_cost_expression(
        context, model, configuration, prices, zero_electricity_hours=len(cleared),
        objective_hours=tuple(range(len(cleared))) if oracle_execute_D_cost_only else None,
    )
    tie_expr = model.static_price_naive_objective.expr
    solver_name, solver = _select_solver()
    if solver is None or not str(solver_name).startswith("gurobi"):
        raise Phase6BError("Phase-6B redispatch requires Gurobi.")
    _apply_solver_time_limit(solver_name, solver, float(context.config["solver_time_limit_seconds"]))
    solver.options["MIPGap"] = MIP_GAP_LIMIT
    tiers: list[dict[str, Any]] = []
    model.phase6b_progress_objective = Objective(expr=progress_expr, sense=minimize)
    _, record = _solve_active_objective(model, solver, "redispatch_production_progress")
    tiers.append(record)
    progress_optimum = float(value(progress_expr))
    model.phase6b_progress_preservation = Constraint(expr=progress_expr <= progress_optimum + 1e-6)
    model.phase6b_progress_objective.deactivate()
    model.phase6b_cost_objective = Objective(expr=cost_expr, sense=minimize)
    _, record = _solve_active_objective(model, solver, "redispatch_represented_cost")
    tiers.append(record)
    cost_optimum = float(value(cost_expr))
    model.phase6b_cost_preservation = Constraint(expr=cost_expr <= cost_optimum + context.cost_tolerance_eur)
    model.phase6b_cost_objective.deactivate()
    model.phase6b_tie_objective = Objective(expr=tie_expr, sense=minimize)
    result, record = _solve_active_objective(model, solver, "redispatch_physical_tiebreak")
    tiers.append(record)
    stats = collect_model_stats(model)
    solver_record = {
        "solver_name": solver_name, "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "mip_gap": _solver_gap(result), "variable_count": stats.variables,
        "binary_count": stats.binaries, "constraint_count": stats.constraints,
        "planning_hours": planning_hours,
        "planning_intervals": planning_intervals,
        "time_step_hours": context.time_grid.time_step_hours,
        "granularity": context.granularity,
        "tier_solves": tiers, "total_solver_seconds": sum(item["runtime_seconds"] for item in tiers),
    }
    return model, solver_record, cost_optimum


def _component_value(model: ConcreteModel, name: str, t: int) -> float:
    return float(value(getattr(model, name)[t])) if hasattr(model, name) else 0.0


def _route_progress_values(
    context: SteelPhysicalContext,
    model: ConcreteModel,
    configuration: str,
    t: int,
) -> dict[str, float]:
    if configuration == C0_CONFIGURATION:
        return {
            "C0_BOF_crude_steel_output_t": _component_value(model, "bof_crude_steel_output", t),
            "C0_HSM_final_product_t": _component_value(model, "c0_hsm_final_product_output", t),
            "C0_DSP_final_product_t": _component_value(model, "c0_dsp_final_product_output", t),
        }
    return {
        "C1_BOF_liquid_steel_output_t_h": _component_value(model, "bof_crude_steel_output", t),
        "C1_EAF_liquid_steel_output_t_h": _component_value(model, "eaf_liquid_steel_output", t),
        "C1_HSM_final_product_output_t": (
            float(context.c1_reference_routing["hsm_final_t_per_t_slab"])
            * _component_value(model, "hot_strip_mill", t)
        ),
        "C1_DSP_final_product_output_t": _component_value(model, "dsp_final_product_output", t),
        "C1_imported_slab_to_HSM_t_h": _component_value(model, "imported_slab_to_hsm", t),
    }


def _inventory_overrides(model: ConcreteModel, configuration: str, index: int) -> dict[str, float]:
    result = {
        "coke_store_initial_t": _component_value(model, "coke_inventory", index),
        "sinter_store_initial_t": _component_value(model, "sinter_inventory", index),
        "hot_iron_store_initial_t": _component_value(model, "hot_iron_inventory", index),
        "cold_slab_store_initial_t": _component_value(model, "cold_slab_inventory", index),
    }
    if configuration == C1_CONFIGURATION:
        result["dri_buffer_initial_t"] = _component_value(model, "dri_inventory", index)
    return result


def _executed_non_grid_cost(
    context: SteelPhysicalContext, model: ConcreteModel, configuration: str, hours: int
) -> float:
    total = 0.0
    for flow in _applicable_cost_flows(context, configuration):
        if str(flow["price_id"]) == "grid_electricity_flat_nl":
            continue
        for attribute in str(flow["model_component_attribute"]).split(";"):
            component = getattr(model, attribute)
            total += float(flow["constant_price_eur"]) * sum(float(value(component[t])) for t in range(hours))
    return total


def solve_hourly_actual_redispatch(
    context: SteelPhysicalContext,
    configuration: str,
    clearing_result: SteelClearingResult,
    rolling_state: SteelRollingState,
    point_prices: Sequence[float],
    *,
    terminal_day: bool = False,
    terminal_hour_in_horizon: int | None = None,
    oracle_execute_D_cost_only: bool = False,
) -> SteelRedispatchResult:
    model, solver_record, _ = _solve_redispatch_model(
        context, configuration, rolling_state, clearing_result, point_prices,
        terminal_day=terminal_day,
        terminal_hour_in_horizon=terminal_hour_in_horizon,
        oracle_execute_D_cost_only=oracle_execute_D_cost_only,
    )
    hourly: list[dict[str, Any]] = []
    for t, clearing_row in enumerate(clearing_result.hourly):
        net_import = _component_value(model, "net_grid_import_mwh", t)
        cleared = float(clearing_row["cleared_energy_mwh"])
        route_progress = _route_progress_values(context, model, configuration, t)
        hourly.append({
            **dict(clearing_row),
            "redispatched_net_grid_import_mwh": net_import,
            "cleared_import_residual_mwh": net_import - cleared,
            "final_product_output_t": _component_value(model, "final_product_output", t),
            "gross_electricity_mwh": _component_value(model, "gross_electricity_mwh", t),
            "total_internal_generation_mwh": _component_value(model, "total_generator_electricity_mwh", t),
            "gross_grid_export_mwh": _component_value(model, "gross_grid_export_mwh", t),
            "total_named_ng_procurement_mwh": _component_value(model, "total_named_ng_procurement_mwh", t),
            "coke_inventory_t": _component_value(model, "coke_inventory", t),
            "sinter_inventory_t": _component_value(model, "sinter_inventory", t),
            "hot_iron_inventory_t": _component_value(model, "hot_iron_inventory", t),
            "cold_slab_inventory_t": _component_value(model, "cold_slab_inventory", t),
            "dri_inventory_t": _component_value(model, "dri_inventory", t),
            **route_progress,
        })
    if max(abs(float(row["cleared_import_residual_mwh"])) for row in hourly) > ENERGY_TOLERANCE_MWH:
        raise Phase6BError("Redispatch did not use the cleared D profile exactly.")
    if max(abs(float(row["gross_grid_export_mwh"])) for row in hourly) > ENERGY_TOLERANCE_MWH:
        raise Phase6BError("Unexpected steel electricity export appeared in redispatch.")
    produced = sum(float(row["final_product_output_t"]) for row in hourly)
    route_fields = tuple(_route_progress_values(context, model, configuration, 0))
    executed_route_progress = {
        field: sum(float(row[field]) for row in hourly)
        for field in route_fields
    }
    return SteelRedispatchResult(
        policy=clearing_result.policy, configuration_id=configuration,
        delivery_day=clearing_result.delivery_day, hourly=hourly,
        next_inventory_overrides=_inventory_overrides(model, configuration, len(hourly) - 1),
        produced_t=produced,
        other_represented_cost_eur=_executed_non_grid_cost(context, model, configuration, len(hourly)),
        solver=solver_record,
        executed_route_progress_t=executed_route_progress,
        time_step_hours=context.time_grid.time_step_hours,
    )


def advance_steel_state(
    previous_state: SteelRollingState,
    redispatch_result: SteelRedispatchResult,
) -> SteelRollingState:
    if previous_state.configuration_id != redispatch_result.configuration_id:
        raise Phase6BError("State and redispatch configuration identities differ.")
    if redispatch_result.delivery_day and previous_state.last_executed_timestamp_utc:
        previous_end = pd.Timestamp(previous_state.last_executed_timestamp_utc)
        next_start = pd.Timestamp(redispatch_result.hourly[0]["target_timestamp_utc"])
        if next_start != previous_end + pd.Timedelta(hours=redispatch_result.time_step_hours):
            raise Phase6BError("Rolling state would jump across a support gap.")
    executed_duration = len(redispatch_result.hourly) * redispatch_result.time_step_hours
    if abs(executed_duration - round(executed_duration)) > 1e-9:
        raise Phase6BError("Executed delivery-day duration is not an integer number of hours.")
    return SteelRollingState(
        episode_id=previous_state.episode_id,
        configuration_id=previous_state.configuration_id,
        inventory_overrides=dict(redispatch_result.next_inventory_overrides),
        cumulative_production_t=(
            float(previous_state.cumulative_production_t) + float(redispatch_result.produced_t)
        ),
        executed_hours=int(previous_state.executed_hours) + int(round(executed_duration)),
        executed_intervals=int(previous_state.executed_intervals) + len(redispatch_result.hourly),
        last_executed_timestamp_utc=str(redispatch_result.hourly[-1]["target_timestamp_utc"]),
        cumulative_route_progress_t={
            key: float(previous_state.cumulative_route_progress_t.get(key, 0.0))
            + float(redispatch_result.executed_route_progress_t.get(key, 0.0))
            for key in set(previous_state.cumulative_route_progress_t)
            | set(redispatch_result.executed_route_progress_t)
        },
    )


def validate_bid_monotonicity(bids: Sequence[Mapping[str, Any]], prices: Sequence[float]) -> bool:
    curve = sorted((float(price), sum(
        float(row["incremental_bid_volume_mwh"])
        for row in bids if float(row["bid_price_eur_per_mwh"]) >= float(price)
    )) for price in prices)
    return all(curve[index][1] + ENERGY_TOLERANCE_MWH >= curve[index + 1][1] for index in range(len(curve) - 1))


def _policy_trajectory(
    context: SteelPhysicalContext,
    config: Mapping[str, Any],
    *,
    fixture_id: str,
    delivery_days: Sequence[date],
    policy: str,
    configuration: str,
    audit_future_paths: bool,
    apply_campaign_terminal: bool = True,
) -> dict[str, Any]:
    _, phase = _phase_mapping(config)
    execution_intervals = context.time_grid.execution_steps
    state = SteelRollingState(episode_id=fixture_id, configuration_id=configuration)
    initial_state = state.snapshot()
    bids: list[dict[str, Any]] = []
    clearing_rows: list[dict[str, Any]] = []
    redispatch_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    scenario_dispatch: list[dict[str, Any]] = []
    for day_index, delivery_day in enumerate(delivery_days):
        terminal_day = fixture_id.startswith("rolling_week") and day_index == len(delivery_days) - 1
        planning_hours = (
            episode_planning_horizon_hours(
                fixture_id=fixture_id,
                day_index=day_index,
                day_count=len(delivery_days),
                nominal_horizon_hours=int(phase["planning_horizon_hours"]),
            )
            if apply_campaign_terminal
            else int(phase["planning_horizon_hours"])
        )
        terminal_hour_in_horizon = (
            planning_hours
            if apply_campaign_terminal
            and fixture_id == "rolling_week"
            and (len(delivery_days) - day_index) * 24 <= int(phase["planning_horizon_hours"])
            else None
        )
        price_bundle = (
            load_qh_price_information(phase["forecast_root"], delivery_day, 10)
            if context.granularity == "quarterhour"
            else load_hourly_price_information(phase["forecast_root"], delivery_day, 10)
        )
        target_selection = fixture_id == "rolling_week_terminal_target_selection"
        actuals = (
            SteelActualPriceBundle(
                delivery_day=delivery_day,
                timestamps_utc=tuple(price_bundle.timestamps_utc[:execution_intervals]),
                prices=tuple(80.0 for _ in range(execution_intervals)),
                granularity=context.granularity,
                time_step_hours=context.time_grid.time_step_hours,
            )
            if target_selection
            else (
                load_qh_actual_prices(phase["forecast_root"], delivery_day)
                if context.granularity == "quarterhour"
                else load_hourly_actual_prices(phase["forecast_root"], delivery_day)
            )
        )
        if tuple(price_bundle.timestamps_utc[: len(actuals.timestamps_utc)]) != actuals.timestamps_utc:
            raise Phase6BError("Forecast D timestamps and actual D timestamps differ.")
        before = state.snapshot()
        oracle = (
            _load_oracle_prices(phase["forecast_root"], price_bundle)
            if _policy_role(policy) == "true-PF"
            else None
        )
        try:
            bid_plan = solve_hourly_da_bid_plan(
                context, configuration, price_bundle, STEEL_BID_GRID, state, policy,
                actuals_oracle=oracle,
                terminal_day=terminal_day,
                terminal_hour_in_horizon=terminal_hour_in_horizon,
                audit_future_paths=audit_future_paths and day_index == 0,
            )
        except Phase6BError as exc:
            raise Phase6BError(
                f"Bidding failed for fixture={fixture_id}, policy={policy}, "
                f"configuration={configuration}, delivery_day={delivery_day}, "
                f"planning_hours={planning_hours}, state_before={json.dumps(before, sort_keys=True)}: {exc}"
            ) from exc
        if not validate_bid_monotonicity(bid_plan.bids, sorted(set(actuals.prices))):
            raise Phase6BError("Submitted purchase curve is not monotone in market price.")
        clearing = clear_hourly_da_bids(bid_plan.bids, actuals)
        try:
            redispatch = solve_hourly_actual_redispatch(
                context, configuration, clearing, state,
                (
                    oracle.prices
                    if oracle is not None
                    else tuple(80.0 for _ in price_bundle.point_prices)
                    if target_selection
                    else price_bundle.point_prices
                ),
                terminal_day=terminal_day,
                terminal_hour_in_horizon=terminal_hour_in_horizon,
                oracle_execute_D_cost_only=_policy_role(policy) == "true-PF",
            )
        except Phase6BError as exc:
            raise Phase6BError(
                f"Redispatch failed for fixture={fixture_id}, policy={policy}, "
                f"configuration={configuration}, delivery_day={delivery_day}, "
                f"planning_hours={planning_hours}, state_before={json.dumps(before, sort_keys=True)}: {exc}"
            ) from exc
        state = advance_steel_state(state, redispatch)
        bids.extend({"fixture_id": fixture_id, **row} for row in bid_plan.bids)
        clearing_rows.extend({"fixture_id": fixture_id, **row} for row in clearing.hourly)
        redispatch_rows.extend({"fixture_id": fixture_id, **row} for row in redispatch.hourly)
        scenario_dispatch.extend(
            {"fixture_id": fixture_id, **row} for row in bid_plan.scenario_dispatch
        )
        solver_rows.extend([
            {"fixture_id": fixture_id, "delivery_day": delivery_day.isoformat(), "policy": policy,
             "configuration_id": configuration, "solve_role": "bidding", **bid_plan.solver},
            {"fixture_id": fixture_id, "delivery_day": delivery_day.isoformat(), "policy": policy,
             "configuration_id": configuration, "solve_role": "redispatch", **redispatch.solver},
        ])
        state_rows.append({
            "fixture_id": fixture_id, "delivery_day": delivery_day.isoformat(),
            "policy": policy, "configuration_id": configuration,
            "planning_horizon_hours": planning_hours,
            "planning_horizon_intervals": int(
                round(planning_hours / context.time_grid.time_step_hours)
            ),
            "time_step_hours": context.time_grid.time_step_hours,
            "granularity": context.granularity,
            "price_information_role": (
                "flat80_terminal_target_selection"
                if target_selection
                else "isolated_oracle"
                if _policy_role(policy) == "true-PF"
                else "forecast_and_realised_settlement"
            ),
            "state_before_json": json.dumps(before, sort_keys=True),
            "state_after_json": json.dumps(state.snapshot(), sort_keys=True),
            "produced_t": redispatch.produced_t,
            "cumulative_production_t": state.cumulative_production_t,
            "settlement_cost_eur": clearing.settlement_cost_eur,
            "other_represented_cost_eur": redispatch.other_represented_cost_eur,
            "total_realised_cost_eur": clearing.settlement_cost_eur + redispatch.other_represented_cost_eur,
        })
    return {
        "fixture_id": fixture_id, "policy": policy, "configuration_id": configuration,
        "initial_state": initial_state, "final_state": state.snapshot(),
        "bids": bids, "clearing": clearing_rows, "redispatch": redispatch_rows,
        "states": state_rows, "solver": solver_rows, "scenario_dispatch": scenario_dispatch,
        "total_realised_cost_eur": sum(float(row["total_realised_cost_eur"]) for row in state_rows),
    }


def _terminal_band_from_price_insensitive_selection(
    selections: Sequence[Mapping[str, Any]],
    capacity_reference: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, dict[str, dict[str, float]]]:
    override_to_state = {
        "coke_store_initial_t": "coke_inventory_t",
        "sinter_store_initial_t": "sinter_inventory_t",
        "hot_iron_store_initial_t": "hot_iron_inventory_t",
        "cold_slab_store_initial_t": "cold_slab_inventory_t",
        "dri_buffer_initial_t": "dri_inventory_t",
    }
    result: dict[str, dict[str, dict[str, float]]] = {}
    for trajectory in selections:
        configuration = str(trajectory["configuration_id"])
        overrides = trajectory["final_state"]["inventory_overrides"]
        bounds: dict[str, dict[str, float]] = {}
        for override, state_id in override_to_state.items():
            if override not in overrides:
                continue
            target = float(overrides[override])
            reference = capacity_reference[configuration][state_id]
            if abs(target) <= TERMINAL_STATE_TOLERANCE_T:
                lower = upper = 0.0
            else:
                lower = max(0.0, 0.99 * target)
                upper = 1.01 * target
            bounds[state_id] = {
                "target_t": target,
                "lower_t": lower,
                "upper_t": upper,
                "band_fraction": 0.01,
                "capacity_t": float(reference["capacity_t"]),
            }
        result[configuration] = bounds
    if set(result) != set(CONFIGURATIONS):
        raise Phase6BError("Price-insensitive terminal target selection is incomplete.")
    return result


def _terminal_band_checks(
    trajectories: Sequence[Mapping[str, Any]],
    terminal_band: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> list[dict[str, Any]]:
    override_by_state = {
        "coke_inventory_t": "coke_store_initial_t",
        "sinter_inventory_t": "sinter_store_initial_t",
        "hot_iron_inventory_t": "hot_iron_store_initial_t",
        "cold_slab_inventory_t": "cold_slab_store_initial_t",
        "dri_inventory_t": "dri_buffer_initial_t",
    }
    rows: list[dict[str, Any]] = []
    for trajectory in trajectories:
        configuration = str(trajectory["configuration_id"])
        final = trajectory["final_state"]["inventory_overrides"]
        for state_id, bounds in terminal_band[configuration].items():
            observed = float(final[override_by_state[state_id]])
            lower = float(bounds["lower_t"])
            upper = float(bounds["upper_t"])
            rows.append({
                "fixture_id": trajectory["fixture_id"],
                "policy": trajectory["policy"],
                "configuration_id": configuration,
                "check_id": f"common_terminal_band::{state_id}",
                "observed_t": observed,
                "lower_t": lower,
                "upper_t": upper,
                "status": (
                    "pass"
                    if lower - TERMINAL_STATE_TOLERANCE_T <= observed
                    <= upper + TERMINAL_STATE_TOLERANCE_T
                    else "fail"
                ),
            })
    return rows


def _trajectory_checks(trajectory: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    redispatch = trajectory["redispatch"]
    states = trajectory["states"]
    bids = trajectory["bids"]
    solver_rows = trajectory["solver"]
    bidding_solvers = [row for row in solver_rows if row["solve_role"] == "bidding"]
    expected_route_fields = (
        {
            "C0_BOF_crude_steel_output_t",
            "C0_HSM_final_product_t",
            "C0_DSP_final_product_t",
        }
        if trajectory["configuration_id"] == C0_CONFIGURATION
        else {
            "C1_BOF_liquid_steel_output_t_h",
            "C1_EAF_liquid_steel_output_t_h",
            "C1_HSM_final_product_output_t",
            "C1_DSP_final_product_output_t",
            "C1_imported_slab_to_HSM_t_h",
        }
    )
    snapshots = [json.loads(str(row["state_before_json"])) for row in states]
    after_snapshots = [json.loads(str(row["state_after_json"])) for row in states]
    handoff_exact = all(
        after_snapshots[index - 1] == snapshots[index]
        for index in range(1, len(states))
    )
    unique_bid_keys = {
        (
            row["target_timestamp_utc"],
            row["bid_price_eur_per_mwh"],
        )
        for row in bids
    }
    solver_acceptable = all(
        str(row["termination_condition"]).lower() == "optimal"
        or (
            row.get("mip_gap") not in {None, ""}
            and float(row["mip_gap"]) <= MIP_GAP_LIMIT
        )
        for row in solver_rows
    )
    solver_strictly_optimal = all(
        str(row["termination_condition"]).lower() == "optimal"
        and all(
            str(tier["termination_condition"]).lower() == "optimal"
            for tier in row.get("tier_solves", ())
        )
        for row in solver_rows
    )
    time_step_hours = float(redispatch[0].get("time_step_hours", 1.0))
    execution_intervals = int(round(24.0 / time_step_hours))
    expected_grid_id = (
        QH_GRID_CANONICAL_ID if time_step_hours == 0.25 else GRID_CANONICAL_ID
    )
    expected_scenarios = 10 if _policy_role(str(trajectory["policy"])) == "H-S10" else 1
    rows.extend([
        {"check_id": "cleared_import_equals_redispatch", "status": "pass" if max(abs(float(row["cleared_import_residual_mwh"])) for row in redispatch) <= ENERGY_TOLERANCE_MWH else "fail"},
        {"check_id": "zero_export", "status": "pass" if max(abs(float(row["gross_grid_export_mwh"])) for row in redispatch) <= ENERGY_TOLERANCE_MWH else "fail"},
        {"check_id": "settlement_identity", "status": "pass" if max(abs(float(row["settlement_cost_eur"]) - float(row["cleared_energy_mwh"]) * float(row["realised_price_eur_per_mwh"])) for row in redispatch) <= MONEY_TOLERANCE_EUR else "fail"},
        {"check_id": "executed_D_only", "status": "pass" if len(redispatch) == execution_intervals * len(states) else "fail"},
        {"check_id": "state_hours_advance", "status": "pass" if int(trajectory["final_state"]["executed_hours"]) == 24 * len(states) else "fail"},
        {"check_id": "state_intervals_advance", "status": "pass" if int(trajectory["final_state"].get("executed_intervals", 0)) == execution_intervals * len(states) else "fail"},
        {"check_id": "complete_state_handoff_exact", "status": "pass" if handoff_exact else "fail"},
        {"check_id": "cumulative_route_progress_complete", "status": "pass" if set(trajectory["final_state"]["cumulative_route_progress_t"]) == expected_route_fields else "fail"},
        {"check_id": "bid_keys_unique", "status": "pass" if len(unique_bid_keys) == len(bids) else "fail"},
        {"check_id": "frozen_grid_identity", "status": "pass" if all(row["bid_grid_id"] == expected_grid_id and row["bid_grid_sha256"] == grid_sha256() for row in bids) else "fail"},
        {"check_id": "bidding_outputs_actual_free", "status": "pass" if not any(any(token in str(key).lower() for token in ("actual", "realised", "error")) for row in bids for key in row) else "fail"},
        {"check_id": "scenario_count_contract", "status": "pass" if all(int(row["scenario_count"]) == expected_scenarios for row in bidding_solvers) else "fail"},
        {"check_id": "scenario_probability_sum", "status": "pass" if all(abs(float(row["scenario_probability_sum"]) - 1.0) <= PROBABILITY_TOLERANCE for row in bidding_solvers) else "fail"},
        {"check_id": "solver_status_and_gap", "status": "pass" if solver_acceptable else "fail"},
        {"check_id": "strict_optimal_termination", "status": "pass" if solver_strictly_optimal else "fail"},
    ])
    for row in rows:
        row.update({
            "fixture_id": trajectory["fixture_id"], "policy": trajectory["policy"],
            "configuration_id": trajectory["configuration_id"],
        })
    return rows


def _pf_dominance_checks(trajectories: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    lookup = {(row["fixture_id"], row["configuration_id"], row["policy"]): row for row in trajectories}
    checks: list[dict[str, Any]] = []
    for fixture in sorted({row["fixture_id"] for row in trajectories}):
        for configuration in CONFIGURATIONS:
            oracle = float(lookup[(fixture, configuration, "true-PF")]["total_realised_cost_eur"])
            policies = (
                ("QH-point", "QH-S10", "price-insensitive")
                if (fixture, configuration, "QH-point") in lookup
                else ("H-point", "H-S10", "price-insensitive")
            )
            for policy in policies:
                case = float(lookup[(fixture, configuration, policy)]["total_realised_cost_eur"])
                tolerance = max(1.0, 1e-6 * abs(case))
                checks.append({
                    "fixture_id": fixture, "configuration_id": configuration,
                    "policy": policy, "check_id": "configuration_matched_pf_not_worse",
                    "case_cost_eur": case, "pf_cost_eur": oracle, "tolerance_eur": tolerance,
                    "status": "pass" if oracle <= case + tolerance else "fail",
                })
    return checks


def run_phase6b(
    config_path: str | Path,
    *,
    fixture: str = "all",
) -> dict[str, Any]:
    if fixture not in {"day", "week", "all"}:
        raise Phase6BError("fixture must be day, week, or all.")
    started = time.perf_counter()
    config_file = _resolve(config_path)
    config = load_phase6b_config(config_file)
    phase = config["phase6b"]
    output = _resolve(config["output_root"])
    comparison = _resolve(config["comparison_root"])
    if output.exists() or comparison.exists():
        raise Phase6BError("Phase-6B governed output already exists.")
    context = prepare_physical_context(config)
    normal_day = date.fromisoformat(str(phase["normal_day_delivery_date"]))
    week_start = date.fromisoformat(str(phase["rolling_week_start_date"]))
    week_end = date.fromisoformat(str(phase["rolling_week_end_date"]))
    fixtures: list[tuple[str, list[date], bool]] = []
    if fixture in {"day", "all"}:
        fixtures.append(("normal_day", [normal_day], True))
    trajectories: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for fixture_id, days, audit in fixtures:
        for policy in POLICIES:
            for configuration in CONFIGURATIONS:
                trajectory = _policy_trajectory(
                    context, config, fixture_id=fixture_id, delivery_days=days,
                    policy=policy, configuration=configuration, audit_future_paths=audit,
                )
                trajectories.append(trajectory)
                checks.extend(_trajectory_checks(trajectory))
    checks.extend(_pf_dominance_checks(trajectories))
    day_checks = list(checks)
    target_selection_trajectories: list[dict[str, Any]] = []
    selected_terminal_band: Mapping[str, Mapping[str, Mapping[str, float]]] | None = None
    if fixture in {"week", "all"}:
        if fixture == "all" and any(row["status"] != "pass" for row in day_checks):
            raise Phase6BError("Normal-day gate failed; rolling-week execution is blocked.")
        week_days = [week_start + timedelta(days=index) for index in range((week_end - week_start).days + 1)]
        frozen_capacity_reference = context.terminal_inventory_band
        for configuration in CONFIGURATIONS:
            target_selection_trajectories.append(_policy_trajectory(
                context,
                config,
                fixture_id="rolling_week_terminal_target_selection",
                delivery_days=week_days,
                policy="price-insensitive",
                configuration=configuration,
                audit_future_paths=False,
                apply_campaign_terminal=False,
            ))
        selected_terminal_band = _terminal_band_from_price_insensitive_selection(
            target_selection_trajectories,
            frozen_capacity_reference,
        )
        context.terminal_inventory_band = selected_terminal_band
        week_trajectories: list[dict[str, Any]] = []
        for policy in POLICIES:
            for configuration in CONFIGURATIONS:
                trajectory = _policy_trajectory(
                    context, config, fixture_id="rolling_week", delivery_days=week_days,
                    policy=policy, configuration=configuration, audit_future_paths=False,
                )
                week_trajectories.append(trajectory)
                checks.extend(_trajectory_checks(trajectory))
        trajectories.extend(week_trajectories)
        checks.extend(_pf_dominance_checks(week_trajectories))
        checks.extend(_terminal_band_checks(week_trajectories, selected_terminal_band))
    passed = bool(trajectories) and all(row["status"] == "pass" for row in checks)
    bids = [row for trajectory in trajectories for row in trajectory["bids"]]
    clearing = [row for trajectory in trajectories for row in trajectory["clearing"]]
    redispatch = [row for trajectory in trajectories for row in trajectory["redispatch"]]
    states = [row for trajectory in trajectories for row in trajectory["states"]]
    solvers = [row for trajectory in trajectories for row in trajectory["solver"]]
    scenario_dispatch = [row for trajectory in trajectories for row in trajectory["scenario_dispatch"]]
    target_selection_states = [
        row
        for trajectory in target_selection_trajectories
        for row in trajectory["states"]
    ]
    target_selection_solvers = [
        row
        for trajectory in target_selection_trajectories
        for row in trajectory["solver"]
    ]
    target_band_rows = [
        {
            "configuration_id": configuration,
            "state_id": state_id,
            **dict(bounds),
            "selection_policy": "price-insensitive",
            "selection_timing": "frozen_before_responsive_week_trajectories",
        }
        for configuration, states_by_id in (selected_terminal_band or {}).items()
        for state_id, bounds in states_by_id.items()
    ]
    summary_rows = [{
        "fixture_id": row["fixture_id"], "policy": row["policy"],
        "configuration_id": row["configuration_id"],
        "executed_days": len(row["states"]),
        "settlement_cost_eur": sum(float(item["settlement_cost_eur"]) for item in row["states"]),
        "other_represented_cost_eur": sum(float(item["other_represented_cost_eur"]) for item in row["states"]),
        "total_realised_cost_eur": row["total_realised_cost_eur"],
        "produced_t": sum(float(item["produced_t"]) for item in row["states"]),
        "final_state_json": json.dumps(row["final_state"], sort_keys=True),
    } for row in trajectories]
    output.mkdir(parents=True)
    comparison.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _write_csv(output / "submitted_D_bid_curves.csv", bids)
    _write_csv(output / "realised_D_clearing.csv", clearing)
    _write_csv(output / "realised_D_redispatch.csv", redispatch)
    _write_csv(output / "rolling_state_handoffs.csv", states)
    _write_csv(output / "solver_diagnostics.csv", solvers)
    _write_csv(output / "validation_checks.csv", checks)
    _write_csv(output / "planned_scenario_dispatch_audit.csv", scenario_dispatch)
    _write_csv(output / "terminal_target_selection_state_handoffs.csv", target_selection_states)
    _write_csv(output / "terminal_target_selection_solver_diagnostics.csv", target_selection_solvers)
    _write_csv(output / "common_week_terminal_inventory_band.csv", target_band_rows)
    _write_csv(comparison / "phase6b_fixture_summary.csv", summary_rows)
    _write_csv(comparison / "phase6b_acceptance_checks.csv", checks)
    inputs = [
        config_file, _resolve(phase["physical_config"]), _resolve(phase["phase4_config"]),
        _resolve(phase["terminal_target_contract"]), _resolve(phase["phase5g_config"]),
        _resolve(phase["phase5k_boundary_contract"]), _resolve(phase["phase5k_wag_contract"]),
        _resolve(phase["forecast_root"]) / "optimisation_inputs" / "hourly_point_forecasts.parquet",
        _resolve(phase["forecast_root"]) / "optimisation_inputs" / "hourly_scenarios_10.parquet",
        _resolve(phase["forecast_root"]) / "evaluation_actuals.parquet", Path(__file__).resolve(),
    ]
    _write_json(output / "input_manifest.json", {
        "inputs": [{"path": path.relative_to(REPO_ROOT).as_posix(), "sha256": _sha256(path), "size_bytes": path.stat().st_size} for path in inputs]
    })
    decision = (
        "hourly_stochastic_DA_bid_clear_redispatch_validated_on_engineering_fixtures"
        if passed and {row["fixture_id"] for row in trajectories} == {"normal_day", "rolling_week"}
        else "phase6b_engineering_validation_incomplete_or_failed"
    )
    result = {
        "run_id": config["run_id"], "status": "pass" if passed else "fail",
        "decision": decision, "fixture_scope": sorted({row["fixture_id"] for row in trajectories}),
        "trajectory_count": len(trajectories), "validation_check_count": len(checks),
        "terminal_target_selection_trajectory_count": len(target_selection_trajectories),
        "failure_count": sum(row["status"] != "pass" for row in checks),
        "runtime_seconds": time.perf_counter() - started,
        "output_policy": config["output_policy"], "run_class": config["run_class"],
        "lineage_role": config["lineage_role"], "bid_grid_id": GRID_CANONICAL_ID,
        "bid_grid_sha256": grid_sha256(), "scenario_undercoverage_warning": True,
    }
    _write_json(output / "run_summary.json", result)
    _write_json(output / "code_version.json", {"git_head": _git_head(), "dirty_worktree_preserved": True})
    _write_json(output / "registry_entry.json", {
        "run_id": config["run_id"], "run_class": config["run_class"],
        "output_policy": config["output_policy"], "lineage_role": config["lineage_role"],
        "decision": decision,
    })
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- These day/week results are engineering validation, not economic evaluation or tuning evidence.\n"
        "- The Strict LEAR ten-scenario set undercovers on evaluation; no calibrated risk-coverage claim is made.\n"
        "- The common week-end inventory band is selected once from an unbanded price-insensitive run on the same engineering episode, before point, S10 and oracle results are evaluated.\n"
        "- QH, CVaR, mFRR, export, ETS and product revenue remain outside scope.\n"
        "- Phase 6A remains a historical quantity-only bridge and is not a matched clearing comparator.\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Phase 6B hourly DA engineering validation\n\n"
        "Frozen Phase-5K steel physics with hourly Strict LEAR D--D+4 point/S10 bids, realised D clearing, exact physical redispatch and rolling state handoff. The common week-end inventory band follows the frozen Phase-4 price-insensitive target-selection and campaign-endpoint truncation policy.\n",
        encoding="utf-8",
    )
    return result


def _trajectory_metrics(trajectory: Mapping[str, Any]) -> dict[str, Any]:
    redispatch = list(trajectory["redispatch"])
    states = list(trajectory["states"])
    solvers = list(trajectory["solver"])
    final_state = dict(trajectory["final_state"])
    cleared_mwh = sum(float(row["cleared_energy_mwh"]) for row in redispatch)
    settlement = sum(float(row["settlement_cost_eur"]) for row in states)
    other = sum(float(row["other_represented_cost_eur"]) for row in states)
    time_step = float(redispatch[0].get("time_step_hours", 1.0))
    ranges: list[float] = []
    if time_step == 0.25:
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(
                [row["target_timestamp_utc"] for row in redispatch], utc=True
            ),
            "import_mw": [
                float(row["redispatched_net_grid_import_mwh"]) / time_step
                for row in redispatch
            ],
        })
        frame["local_hour"] = frame["timestamp"].dt.tz_convert("Europe/Amsterdam").dt.floor("h")
        ranges = [
            float(value_in)
            for value_in in (
                frame.groupby("local_hour")["import_mw"].max()
                - frame.groupby("local_hour")["import_mw"].min()
            )
        ]
    gaps = [
        float(row["mip_gap"])
        for row in solvers
        if row.get("mip_gap") not in {None, ""}
    ]
    return {
        "fixture_id": trajectory["fixture_id"],
        "policy": trajectory["policy"],
        "configuration_id": trajectory["configuration_id"],
        "executed_days": len(states),
        "settlement_cost_eur": settlement,
        "other_represented_cost_eur": other,
        "total_realised_cost_eur": settlement + other,
        "cleared_import_mwh": cleared_mwh,
        "volume_weighted_paid_price_eur_per_mwh": (
            settlement / cleared_mwh if abs(cleared_mwh) > ENERGY_TOLERANCE_MWH else math.nan
        ),
        "produced_t": sum(float(row["produced_t"]) for row in states),
        "route_totals_json": json.dumps(
            final_state.get("cumulative_route_progress_t", {}), sort_keys=True
        ),
        "final_inventories_json": json.dumps(
            final_state.get("inventory_overrides", {}), sort_keys=True
        ),
        "executed_hours": int(final_state["executed_hours"]),
        "executed_intervals": int(final_state.get("executed_intervals", 0)),
        "last_executed_timestamp_utc": final_state["last_executed_timestamp_utc"],
        "intrahour_import_range_mean_mw": (
            sum(ranges) / len(ranges) if ranges else math.nan
        ),
        "intrahour_import_range_p95_mw": (
            float(pd.Series(ranges).quantile(0.95)) if ranges else math.nan
        ),
        "intrahour_import_range_max_mw": max(ranges) if ranges else math.nan,
        "solver_seconds": sum(float(row["total_solver_seconds"]) for row in solvers),
        "max_variable_count": max(int(row["variable_count"]) for row in solvers),
        "max_binary_count": max(int(row["binary_count"]) for row in solvers),
        "max_constraint_count": max(int(row["constraint_count"]) for row in solvers),
        "max_mip_gap": max(gaps) if gaps else 0.0,
        "final_state_json": json.dumps(final_state, sort_keys=True),
    }


def _hourly_reference_metrics(phase: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries = pd.read_csv(_resolve(phase["hourly_reference_summary"]))
    summaries = summaries[summaries["fixture_id"] == "rolling_week"].copy()
    run_root = _resolve(phase["hourly_reference_run_root"])
    redispatch = pd.read_csv(run_root / "realised_D_redispatch.csv")
    redispatch = redispatch[redispatch["fixture_id"] == "rolling_week"].copy()
    solvers = pd.read_csv(run_root / "solver_diagnostics.csv")
    solvers = solvers[solvers["fixture_id"] == "rolling_week"].copy()
    rows: list[dict[str, Any]] = []
    for summary in summaries.to_dict("records"):
        policy = str(summary["policy"])
        configuration = str(summary["configuration_id"])
        dispatch_case = redispatch[
            (redispatch["policy"] == policy)
            & (redispatch["configuration_id"] == configuration)
        ]
        solver_case = solvers[
            (solvers["policy"] == policy)
            & (solvers["configuration_id"] == configuration)
        ]
        final_state = json.loads(str(summary["final_state_json"]))
        cleared = float(dispatch_case["cleared_energy_mwh"].sum())
        settlement = float(summary["settlement_cost_eur"])
        gap_values = pd.to_numeric(solver_case["mip_gap"], errors="coerce").dropna()
        rows.append({
            "policy": policy,
            "configuration_id": configuration,
            "settlement_cost_eur": settlement,
            "other_represented_cost_eur": float(summary["other_represented_cost_eur"]),
            "total_realised_cost_eur": float(summary["total_realised_cost_eur"]),
            "cleared_import_mwh": cleared,
            "volume_weighted_paid_price_eur_per_mwh": (
                settlement / cleared if abs(cleared) > ENERGY_TOLERANCE_MWH else math.nan
            ),
            "produced_t": float(summary["produced_t"]),
            "route_totals_json": json.dumps(
                final_state.get("cumulative_route_progress_t", {}), sort_keys=True
            ),
            "final_inventories_json": json.dumps(
                final_state.get("inventory_overrides", {}), sort_keys=True
            ),
            "solver_seconds": float(solver_case["total_solver_seconds"].sum()),
            "max_variable_count": int(solver_case["variable_count"].max()),
            "max_binary_count": int(solver_case["binary_count"].max()),
            "max_constraint_count": int(solver_case["constraint_count"].max()),
            "max_mip_gap": float(gap_values.max()) if not gap_values.empty else 0.0,
        })
    if len(rows) != len(CONFIGURATIONS) * len(POLICIES):
        raise Phase6BError("Hourly common-support reference is incomplete.")
    return rows


def _common_support_comparison_rows(
    qh_metrics: Sequence[Mapping[str, Any]],
    hourly_metrics: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    hourly = {
        (str(row["configuration_id"]), str(row["policy"])): row
        for row in hourly_metrics
    }
    qh = {
        (str(row["configuration_id"]), str(row["policy"])): row
        for row in qh_metrics
    }
    qh_to_hourly = {"QH-point": "H-point", "QH-S10": "H-S10"}
    rows: list[dict[str, Any]] = []
    for qh_row in qh_metrics:
        configuration = str(qh_row["configuration_id"])
        qh_policy = str(qh_row["policy"])
        hourly_policy = qh_to_hourly.get(qh_policy, qh_policy)
        hourly_row = hourly[(configuration, hourly_policy)]
        qh_pi = qh[(configuration, "price-insensitive")]
        qh_pf = qh[(configuration, "true-PF")]
        hourly_pi = hourly[(configuration, "price-insensitive")]
        hourly_pf = hourly[(configuration, "true-PF")]
        qh_total = float(qh_row["total_realised_cost_eur"])
        hourly_total = float(hourly_row["total_realised_cost_eur"])
        delta = qh_total - hourly_total
        rows.append({
            "configuration_id": configuration,
            "strategy": qh_policy,
            "matched_hourly_strategy": hourly_policy,
            "period_start_local": "2026-04-27",
            "period_end_local": "2026-05-03",
            "hourly_settlement_cost_eur": hourly_row["settlement_cost_eur"],
            "qh_settlement_cost_eur": qh_row["settlement_cost_eur"],
            "hourly_other_represented_cost_eur": hourly_row["other_represented_cost_eur"],
            "qh_other_represented_cost_eur": qh_row["other_represented_cost_eur"],
            "hourly_total_represented_cost_eur": hourly_total,
            "qh_total_represented_cost_eur": qh_total,
            "qh_minus_hourly_cost_eur": delta,
            "absolute_qh_hourly_cost_difference_eur": abs(delta),
            "qh_minus_hourly_cost_pct": (
                100.0 * delta / abs(hourly_total) if hourly_total else math.nan
            ),
            "hourly_saving_vs_price_insensitive_eur": (
                float(hourly_pi["total_realised_cost_eur"]) - hourly_total
            ),
            "qh_saving_vs_price_insensitive_eur": (
                float(qh_pi["total_realised_cost_eur"]) - qh_total
            ),
            "hourly_regret_vs_true_pf_eur": (
                hourly_total - float(hourly_pf["total_realised_cost_eur"])
            ),
            "qh_regret_vs_true_pf_eur": qh_total - float(qh_pf["total_realised_cost_eur"]),
            "hourly_cleared_import_mwh": hourly_row["cleared_import_mwh"],
            "qh_cleared_import_mwh": qh_row["cleared_import_mwh"],
            "hourly_volume_weighted_paid_price_eur_per_mwh": hourly_row[
                "volume_weighted_paid_price_eur_per_mwh"
            ],
            "qh_volume_weighted_paid_price_eur_per_mwh": qh_row[
                "volume_weighted_paid_price_eur_per_mwh"
            ],
            "hourly_produced_t": hourly_row["produced_t"],
            "qh_produced_t": qh_row["produced_t"],
            "hourly_route_totals_json": hourly_row["route_totals_json"],
            "qh_route_totals_json": qh_row["route_totals_json"],
            "hourly_final_inventories_json": hourly_row["final_inventories_json"],
            "qh_final_inventories_json": qh_row["final_inventories_json"],
            "qh_intrahour_import_range_mean_mw": qh_row[
                "intrahour_import_range_mean_mw"
            ],
            "qh_intrahour_import_range_p95_mw": qh_row[
                "intrahour_import_range_p95_mw"
            ],
            "qh_intrahour_import_range_max_mw": qh_row[
                "intrahour_import_range_max_mw"
            ],
            "hourly_solver_seconds": hourly_row["solver_seconds"],
            "qh_solver_seconds": qh_row["solver_seconds"],
            "hourly_max_variable_count": hourly_row["max_variable_count"],
            "qh_max_variable_count": qh_row["max_variable_count"],
            "hourly_max_binary_count": hourly_row["max_binary_count"],
            "qh_max_binary_count": qh_row["max_binary_count"],
            "hourly_max_constraint_count": hourly_row["max_constraint_count"],
            "qh_max_constraint_count": qh_row["max_constraint_count"],
            "hourly_max_mip_gap": hourly_row["max_mip_gap"],
            "qh_max_mip_gap": qh_row["max_mip_gap"],
            "interpretation_scope": (
                "combined_QH_price_signals_and_QH_physical_flexibility_not_forecast_shape_only"
            ),
        })
    return rows


def _qh_hourly_input_coupling_checks(
    phase: Mapping[str, Any], delivery_days: Sequence[date]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for delivery_day in delivery_days:
        qh = load_qh_price_information(phase["forecast_root"], delivery_day, 10)
        hourly = load_hourly_price_information(phase["forecast_root"], delivery_day, 10)
        qh_index = pd.DatetimeIndex(qh.timestamps_utc)
        point_means = pd.Series(qh.point_prices, index=qh_index).groupby(qh_index.floor("h")).mean()
        hourly_point = pd.Series(hourly.point_prices, index=pd.DatetimeIndex(hourly.timestamps_utc))
        point_error = float((point_means - hourly_point).abs().max())
        identity_ok = (
            set(qh.scenario_prices) == set(hourly.scenario_prices)
            and qh.scenario_source_blocks == hourly.scenario_source_blocks
            and all(
                abs(qh.scenario_probabilities[key] - hourly.scenario_probabilities[key])
                <= PROBABILITY_TOLERANCE
                for key in qh.scenario_prices
            )
        )
        scenario_error = 0.0
        if identity_ok:
            for scenario_id, prices in qh.scenario_prices.items():
                means = pd.Series(prices, index=qh_index).groupby(qh_index.floor("h")).mean()
                anchor = pd.Series(
                    hourly.scenario_prices[scenario_id],
                    index=pd.DatetimeIndex(hourly.timestamps_utc),
                )
                scenario_error = max(scenario_error, float((means - anchor).abs().max()))
        checks.extend([
            {
                "fixture_id": "rolling_week",
                "policy": "all",
                "configuration_id": "all",
                "delivery_day": delivery_day.isoformat(),
                "check_id": "qh_point_hourly_anchor_identity",
                "max_abs_error_eur_per_mwh": point_error,
                "status": "pass" if point_error <= 1e-9 else "fail",
            },
            {
                "fixture_id": "rolling_week",
                "policy": "QH-S10",
                "configuration_id": "all",
                "delivery_day": delivery_day.isoformat(),
                "check_id": "qh_scenario_identity_probability_and_source_coupling",
                "status": "pass" if identity_ok else "fail",
            },
            {
                "fixture_id": "rolling_week",
                "policy": "QH-S10",
                "configuration_id": "all",
                "delivery_day": delivery_day.isoformat(),
                "check_id": "qh_scenarios_hourly_anchor_identity",
                "max_abs_error_eur_per_mwh": scenario_error,
                "status": "pass" if identity_ok and scenario_error <= 1e-9 else "fail",
            },
        ])
    return checks


def _phase6c_fingerprint_manifest(
    config_file: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    phase = config["phase6c"]
    forecast = _resolve(phase["forecast_root"])
    hourly_run = _resolve(phase["hourly_reference_run_root"])
    paths = [
        config_file,
        _resolve(phase["physical_config"]),
        _resolve(phase["phase4_config"]),
        _resolve(phase["terminal_target_contract"]),
        _resolve(phase["phase5g_config"]),
        _resolve(phase["phase5k_boundary_contract"]),
        _resolve(phase["phase5k_wag_contract"]),
        forecast / "optimisation_inputs" / "quarterhour_point_forecasts.parquet",
        forecast / "optimisation_inputs" / "quarterhour_scenarios_10.parquet",
        forecast / "evaluation_actuals.parquet",
        _resolve(phase["hourly_reference_summary"]),
        _resolve(phase["hourly_terminal_inventory_band"]),
        hourly_run / "realised_D_redispatch.csv",
        hourly_run / "solver_diagnostics.csv",
        Path(__file__).resolve(),
        Path(__file__).with_name("s4_4c_unified_physical_modelbuilder.py").resolve(),
    ]
    entries = [
        {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]
    fingerprint = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "fingerprint_sha256": fingerprint,
        "git_head": _git_head(),
        "config_sha256": _sha256(config_file),
        "code_sha256": _sha256(Path(__file__).resolve()),
        "forecast_point_sha256": _sha256(paths[7]),
        "forecast_s10_sha256": _sha256(paths[8]),
        "forecast_actuals_sha256": _sha256(paths[9]),
        "hourly_reference_sha256": _sha256(paths[10]),
        "terminal_band_sha256": _sha256(paths[11]),
        "inputs": entries,
    }


def _checkpoint_name(policy: str, configuration: str) -> str:
    policy_slug = policy.lower().replace("-", "_")
    return f"{SHORT_CONFIGURATION[configuration].lower()}__{policy_slug}.json.gz"


def _phase6c_shape_checks(trajectories: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bids = [row for trajectory in trajectories for row in trajectory["bids"]]
    redispatch = [row for trajectory in trajectories for row in trajectory["redispatch"]]
    states = [row for trajectory in trajectories for row in trajectory["states"]]
    target = 129452.05479452055
    production_tolerance = max(0.01, 1e-6 * target)
    checks = [
        {
            "fixture_id": "rolling_week", "policy": "all", "configuration_id": "all",
            "check_id": "trajectory_count", "observed": len(trajectories), "expected": 8,
            "status": "pass" if len(trajectories) == 8 else "fail",
        },
        {
            "fixture_id": "rolling_week", "policy": "all", "configuration_id": "all",
            "check_id": "submitted_bid_row_count", "observed": len(bids), "expected": 86016,
            "status": "pass" if len(bids) == 86016 else "fail",
        },
        {
            "fixture_id": "rolling_week", "policy": "all", "configuration_id": "all",
            "check_id": "redispatch_interval_count", "observed": len(redispatch), "expected": 5376,
            "status": "pass" if len(redispatch) == 5376 else "fail",
        },
        {
            "fixture_id": "rolling_week", "policy": "all", "configuration_id": "all",
            "check_id": "state_handoff_count", "observed": len(states), "expected": 56,
            "status": "pass" if len(states) == 56 else "fail",
        },
    ]
    for trajectory in trajectories:
        final = trajectory["final_state"]
        checks.extend([
            {
                "fixture_id": "rolling_week", "policy": trajectory["policy"],
                "configuration_id": trajectory["configuration_id"],
                "check_id": "weekly_production_target",
                "observed_t": final["cumulative_production_t"], "expected_t": target,
                "status": "pass" if abs(float(final["cumulative_production_t"]) - target) <= production_tolerance else "fail",
            },
            {
                "fixture_id": "rolling_week", "policy": trajectory["policy"],
                "configuration_id": trajectory["configuration_id"],
                "check_id": "weekly_final_elapsed_time_and_timestamp",
                "status": "pass" if (
                    int(final["executed_hours"]) == 168
                    and int(final["executed_intervals"]) == 672
                    and final["last_executed_timestamp_utc"] == "2026-05-03T21:45:00+00:00"
                ) else "fail",
            },
        ])
    return checks


def run_phase6c_smoke(config_path: str | Path) -> dict[str, Any]:
    """Run the required one-day, eight-trajectory QH gate without artifacts."""

    config = load_phase6c_config(config_path)
    phase = config["phase6c"]
    context = prepare_physical_context(config)
    delivery_day = date.fromisoformat(str(phase["rolling_week_start_date"]))
    trajectories = [
        _policy_trajectory(
            context,
            config,
            fixture_id="qh_one_day_smoke",
            delivery_days=[delivery_day],
            policy=policy,
            configuration=configuration,
            audit_future_paths=False,
            apply_campaign_terminal=False,
        )
        for policy in QH_POLICIES
        for configuration in CONFIGURATIONS
    ]
    checks = [row for trajectory in trajectories for row in _trajectory_checks(trajectory)]
    checks.extend(_pf_dominance_checks(trajectories))
    return {
        "status": "pass" if all(row["status"] == "pass" for row in checks) else "fail",
        "trajectory_count": len(trajectories),
        "failure_count": sum(row["status"] != "pass" for row in checks),
        "checks": checks,
        "metrics": [_trajectory_metrics(row) for row in trajectories],
    }


def run_phase6c(
    config_path: str | Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the bounded Phase-6C QH week with fingerprinted trajectory checkpoints."""

    started = time.perf_counter()
    config_file = _resolve(config_path)
    config = load_phase6c_config(config_file)
    phase = config["phase6c"]
    output = _resolve(config["output_root"])
    comparison = _resolve(config["comparison_root"])
    manifest = _phase6c_fingerprint_manifest(config_file, config)
    manifest_path = output / "fingerprint_manifest.json"
    if output.exists():
        if not resume:
            raise Phase6BError("Phase-6C governed output exists; pass resume=True to continue.")
        if not manifest_path.exists():
            raise Phase6BError("Existing Phase-6C output has no fingerprint manifest.")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("fingerprint_sha256") != manifest["fingerprint_sha256"]:
            raise Phase6BError("Phase-6C resume fingerprint differs from the current inputs or code.")
    else:
        output.mkdir(parents=True)
        (output / "resolved_config.yaml").write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        _write_json_atomic(manifest_path, manifest)
        _write_json_atomic(output / "input_manifest.json", {"inputs": manifest["inputs"]})
    if comparison.exists():
        if resume and (output / "run_summary.json").exists():
            return json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
        raise Phase6BError("Phase-6C comparison output already exists.")
    context = prepare_physical_context(config)
    week_start = date.fromisoformat(str(phase["rolling_week_start_date"]))
    week_end = date.fromisoformat(str(phase["rolling_week_end_date"]))
    delivery_days = [
        week_start + timedelta(days=index)
        for index in range((week_end - week_start).days + 1)
    ]
    trajectories: list[dict[str, Any]] = []
    for policy in QH_POLICIES:
        for configuration in CONFIGURATIONS:
            checkpoint = output / "checkpoints" / _checkpoint_name(policy, configuration)
            if checkpoint.exists():
                payload = _read_gzip_json(checkpoint)
                if payload.get("fingerprint_sha256") != manifest["fingerprint_sha256"]:
                    raise Phase6BError(f"Checkpoint fingerprint mismatch: {checkpoint.name}.")
                trajectory = payload["trajectory"]
            else:
                trajectory = _policy_trajectory(
                    context,
                    config,
                    fixture_id="rolling_week",
                    delivery_days=delivery_days,
                    policy=policy,
                    configuration=configuration,
                    audit_future_paths=False,
                )
                _write_gzip_json_atomic(checkpoint, {
                    "fingerprint_sha256": manifest["fingerprint_sha256"],
                    "policy": policy,
                    "configuration_id": configuration,
                    "trajectory": trajectory,
                })
            trajectories.append(trajectory)
    checks = [row for trajectory in trajectories for row in _trajectory_checks(trajectory)]
    checks.extend(_pf_dominance_checks(trajectories))
    checks.extend(_terminal_band_checks(trajectories, context.terminal_inventory_band))
    checks.extend(_phase6c_shape_checks(trajectories))
    checks.extend(_qh_hourly_input_coupling_checks(phase, delivery_days))
    passed = len(trajectories) == 8 and all(row["status"] == "pass" for row in checks)
    bids = [row for trajectory in trajectories for row in trajectory["bids"]]
    clearing = [row for trajectory in trajectories for row in trajectory["clearing"]]
    redispatch = [row for trajectory in trajectories for row in trajectory["redispatch"]]
    states = [row for trajectory in trajectories for row in trajectory["states"]]
    solvers = [row for trajectory in trajectories for row in trajectory["solver"]]
    scenario_dispatch = [
        row for trajectory in trajectories for row in trajectory["scenario_dispatch"]
    ]
    qh_metrics = [_trajectory_metrics(trajectory) for trajectory in trajectories]
    hourly_metrics = _hourly_reference_metrics(phase)
    comparison_rows = _common_support_comparison_rows(qh_metrics, hourly_metrics)
    terminal_rows = [
        {"configuration_id": configuration, "state_id": state_id, **dict(bounds)}
        for configuration, states in context.terminal_inventory_band.items()
        for state_id, bounds in states.items()
    ]
    comparison.mkdir(parents=True)
    _write_csv(output / "submitted_D_bid_curves.csv", bids)
    _write_csv(output / "realised_D_clearing.csv", clearing)
    _write_csv(output / "realised_D_redispatch.csv", redispatch)
    _write_csv(output / "rolling_state_handoffs.csv", states)
    _write_csv(output / "solver_diagnostics.csv", solvers)
    _write_csv(output / "validation_checks.csv", checks)
    _write_csv(output / "planned_scenario_dispatch_audit.csv", scenario_dispatch)
    _write_csv(output / "frozen_hourly_terminal_inventory_band.csv", terminal_rows)
    _write_csv(comparison / "phase6c_week_summary.csv", qh_metrics)
    _write_csv(comparison / "hourly_qh_common_support_comparison.csv", comparison_rows)
    decision = (
        "qh_da_bid_clear_redispatch_validated_on_bounded_common_week"
        if passed
        else "qh_engineering_validation_incomplete"
    )
    result = {
        "run_id": config["run_id"],
        "status": "pass" if passed else "fail",
        "decision": decision,
        "period_start_local": week_start.isoformat(),
        "period_end_local": week_end.isoformat(),
        "trajectory_count": len(trajectories),
        "replan_count": len(states),
        "model_build_count": len(solvers),
        "submitted_bid_row_count": len(bids),
        "redispatch_interval_count": len(redispatch),
        "validation_check_count": len(checks),
        "failure_count": sum(row["status"] != "pass" for row in checks),
        "runtime_seconds": time.perf_counter() - started,
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "bid_grid_id": QH_GRID_CANONICAL_ID,
        "bid_grid_sha256": grid_sha256(),
        "qh_s10_p05_p95_coverage_percent": 74.27,
        "scenario_undercoverage_warning": True,
        "fingerprint_sha256": manifest["fingerprint_sha256"],
    }
    _write_json_atomic(output / "run_summary.json", result)
    _write_json_atomic(output / "code_version.json", {
        "git_head": _git_head(), "dirty_worktree_preserved": True,
        "code_sha256": manifest["code_sha256"],
    })
    _write_json_atomic(output / "registry_entry.json", {
        "run_id": config["run_id"], "run_class": config["run_class"],
        "output_policy": config["output_policy"], "lineage_role": config["lineage_role"],
        "decision": decision,
    })
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This seven-day result is bounded engineering validation; it is not annualised and is not a profit claim.\n"
        "- The hourly/QH difference combines QH price signals and QH physical flexibility; it does not identify forecast-shape value separately.\n"
        "- QH-S10 p05--p95 coverage is 74.27%, so S10 is not a calibrated 90% risk set.\n"
        "- Missing plant-specific QH ramp, start, minimum-load, outage and CHP data make QH flexibility an explicit upper bound, not Tata operational truth.\n"
        "- CVaR, mFRR, ETS, export, product revenue, imbalance and long-run economic conclusions remain outside scope.\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Phase 6C quarter-hour DA engineering validation\n\n"
        "Granularity-aware Phase-5K steel physics with frozen QH Strict LEAR D--D+4 point/S10 inputs, realised quarter-hour clearing, exact redispatch and hourly-band terminal matching over 27 April--3 May 2026.\n",
        encoding="utf-8",
    )
    return result
