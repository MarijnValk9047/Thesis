from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .production_target import (
    PRODUCTION_TARGETS_MODE_LEGACY_DAILY_MINIMUM,
    PRODUCTION_TARGETS_MODE_ROLLING_DEADLINE_ENVELOPE,
    RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM,
    RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION,
    RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY,
    RESERVE_FEASIBILITY_PROXY_MODE_NONE,
    RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM,
    TERMINAL_INVENTORY_VALUE_MODE_LEGACY,
    validate_production_targets_mode,
    validate_reserve_feasibility_proxy_down_source,
    validate_reserve_feasibility_proxy_mode,
    validate_reserve_feasibility_proxy_up_source,
    validate_terminal_inventory_value_mode,
)


def _to_path(value: str | Path | None, *, base: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


@dataclass(frozen=True)
class ExperimentSettings:
    name: str
    granularity: str
    horizon_mode: str
    execution_mode: str
    selected_weeks_source: Path
    selected_week_labels: tuple[str, ...]
    custom_start: str | None
    custom_end: str | None
    dataset_split: str
    random_seed: int


@dataclass(frozen=True)
class ModelSettings:
    include: tuple[str, ...]
    scenario_catalog: Path


@dataclass(frozen=True)
class RiskSettings:
    alpha: float
    gamma_grid: tuple[float, ...]
    gamma: float
    gamma_selection: str
    frozen_gamma_path: Path | None


@dataclass(frozen=True)
class BiddingSettings:
    bid_price_grid_eur_per_mwh: tuple[float, ...]
    price_insensitive_bid_price_eur_per_mwh: float


@dataclass(frozen=True)
class MFRRCapacityPilotSettings:
    enabled: bool
    export_path: Path | None
    pilot_start_date: str | None
    pilot_end_date: str | None
    capacity_offer_big_m_mw: float
    offer_continuous_mw: bool


@dataclass(frozen=True)
class ProductionSettings:
    target_semantics: str
    allow_above_target_production: bool
    allow_above_target_sales: bool


@dataclass(frozen=True)
class ProductionTargetEntry:
    delivery_id: str
    due_date: str
    required_quantity_kg: float
    earliest_production_date: str | None = None
    product_type: str | None = None
    priority: str | float | int | None = None
    inventory_allowed: bool | None = None
    maximum_inventory_or_credit_kg: float | None = None


@dataclass(frozen=True)
class ProductionTargetsSettings:
    mode: str
    initial_inventory_kg: float
    max_inventory_kg: float | None
    terminal_inventory_value_mode: str
    targets: tuple[ProductionTargetEntry, ...]


@dataclass(frozen=True)
class ReserveFeasibilityProxySettings:
    enabled: bool
    mode: str
    down_activation_duration_hours: float
    up_activation_duration_hours: float
    down_output_absorption_source: str
    up_recovery_source: str


@dataclass(frozen=True)
class HydrogenSystemSettings:
    electrolyser_nominal_mw: float
    electrolyser_min_mw: float
    electrolyser_ramp_mw_per_h: float
    h2_efficiency_kg_per_mwh: float
    compressor_max_mw: float
    compressor_specific_mwh_per_kg: float
    storage_capacity_kg: float
    storage_initial_kg: float
    reserve_fraction: float
    reserve_sensitivity: tuple[float, ...]

    @property
    def reserve_kg(self) -> float:
        return float(self.reserve_fraction * self.storage_capacity_kg)


@dataclass(frozen=True)
class EconomicSettings:
    h2_sale_price_eur_per_kg: float
    daily_target_kg: float
    p_ref_eur_per_mwh: float
    terminal_inventory_location: str
    shortfall_penalty_eur_per_kg: float
    unused_energy_penalty_eur_per_mwh: float = 4000.0

    def terminal_inventory_value_per_kg(self, compressor_specific_mwh_per_kg: float) -> float:
        location = str(self.terminal_inventory_location).strip().lower()
        if location == "before_compression":
            return float(self.h2_sale_price_eur_per_kg - compressor_specific_mwh_per_kg * self.p_ref_eur_per_mwh)
        if location == "after_compression":
            return float(self.h2_sale_price_eur_per_kg)
        raise ValueError(
            "terminal_inventory_location must be 'before_compression' or 'after_compression'. "
            f"Got: {self.terminal_inventory_location!r}"
        )


@dataclass(frozen=True)
class SolverSettings:
    package_preference: str
    solver_name: str
    mip_gap: float
    time_limit_seconds: int
    grb_license_file: Path | None


@dataclass(frozen=True)
class OutputSettings:
    root: Path
    save_figures: bool
    save_timeseries: bool
    save_solver_log: bool


@dataclass(frozen=True)
class HydrogenConfig:
    repo_root: Path
    config_path: Path
    experiment: ExperimentSettings
    models: ModelSettings
    strategies: tuple[str, ...]
    risk: RiskSettings
    bidding: BiddingSettings
    mfrr_capacity_pilot: MFRRCapacityPilotSettings
    production: ProductionSettings
    production_targets: ProductionTargetsSettings
    reserve_feasibility_proxy: ReserveFeasibilityProxySettings
    hydrogen_system: HydrogenSystemSettings
    economics: EconomicSettings
    solver: SolverSettings
    outputs: OutputSettings

    @property
    def terminal_inventory_value_per_kg(self) -> float:
        return self.economics.terminal_inventory_value_per_kg(self.hydrogen_system.compressor_specific_mwh_per_kg)

    @property
    def delta_t_hours(self) -> float:
        granularity = str(self.experiment.granularity).strip().lower()
        if granularity == "hourly":
            return 1.0
        if granularity in {"quarter_hour", "quarter-hour", "15min", "15_min"}:
            return 0.25
        raise ValueError(f"Unsupported granularity: {self.experiment.granularity}")

    @property
    def run_output_root(self) -> Path:
        return self.outputs.root


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid config section: {key}")
    return value


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _parse_date_string(value: Any, *, field_name: str) -> str:
    if value is None:
        raise ValueError(f"Missing required production target field: {field_name}")
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid date for {field_name}: {value!r}") from exc


def _parse_optional_nonnegative_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if parsed < 0.0:
        raise ValueError(f"{field_name} must be nonnegative. Got: {value!r}")
    return parsed


def _parse_priority(value: Any) -> str | float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return str(value)


def _parse_production_targets_settings(payload: dict[str, Any]) -> ProductionTargetsSettings:
    raw = payload.get("production_targets", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Invalid config section: production_targets")

    mode = validate_production_targets_mode(raw.get("mode", PRODUCTION_TARGETS_MODE_LEGACY_DAILY_MINIMUM))
    terminal_inventory_value_mode = validate_terminal_inventory_value_mode(
        raw.get("terminal_inventory_value_mode", TERMINAL_INVENTORY_VALUE_MODE_LEGACY)
    )
    initial_inventory_kg = float(raw.get("initial_inventory_kg", 0.0))
    if initial_inventory_kg < 0.0:
        raise ValueError(f"production_targets.initial_inventory_kg must be nonnegative. Got: {initial_inventory_kg!r}")
    max_inventory_kg = _parse_optional_nonnegative_float(
        raw.get("max_inventory_kg"),
        field_name="production_targets.max_inventory_kg",
    )

    raw_targets = raw.get("targets", [])
    if raw_targets is None:
        raw_targets = []
    if not isinstance(raw_targets, list):
        raise ValueError("production_targets.targets must be a list.")

    targets: list[ProductionTargetEntry] = []
    seen_delivery_ids: set[str] = set()
    for idx, target_raw in enumerate(raw_targets):
        if not isinstance(target_raw, dict):
            raise ValueError(f"production_targets.targets[{idx}] must be a mapping.")
        delivery_id = str(target_raw.get("delivery_id", "")).strip()
        if not delivery_id:
            raise ValueError(f"production_targets.targets[{idx}].delivery_id is required.")
        if delivery_id in seen_delivery_ids:
            raise ValueError(f"Duplicate production_targets delivery_id: {delivery_id!r}")
        seen_delivery_ids.add(delivery_id)
        due_date = _parse_date_string(target_raw.get("due_date"), field_name=f"production_targets.targets[{idx}].due_date")
        if "required_quantity_kg" not in target_raw:
            raise ValueError(f"production_targets.targets[{idx}].required_quantity_kg is required.")
        required_quantity_kg = float(target_raw["required_quantity_kg"])
        if required_quantity_kg < 0.0:
            raise ValueError(
                f"production_targets.targets[{idx}].required_quantity_kg must be nonnegative. "
                f"Got: {required_quantity_kg!r}"
            )
        earliest_production_date = (
            _parse_date_string(
                target_raw.get("earliest_production_date"),
                field_name=f"production_targets.targets[{idx}].earliest_production_date",
            )
            if target_raw.get("earliest_production_date") is not None
            else None
        )
        product_type = str(target_raw["product_type"]) if target_raw.get("product_type") is not None else None
        inventory_allowed = (
            bool(target_raw["inventory_allowed"]) if target_raw.get("inventory_allowed") is not None else None
        )
        maximum_inventory_or_credit_kg = _parse_optional_nonnegative_float(
            target_raw.get("maximum_inventory_or_credit_kg"),
            field_name=f"production_targets.targets[{idx}].maximum_inventory_or_credit_kg",
        )
        targets.append(
            ProductionTargetEntry(
                delivery_id=delivery_id,
                due_date=due_date,
                required_quantity_kg=required_quantity_kg,
                earliest_production_date=earliest_production_date,
                product_type=product_type,
                priority=_parse_priority(target_raw.get("priority")),
                inventory_allowed=inventory_allowed,
                maximum_inventory_or_credit_kg=maximum_inventory_or_credit_kg,
            )
        )

    if mode == PRODUCTION_TARGETS_MODE_ROLLING_DEADLINE_ENVELOPE and not targets:
        raise ValueError("production_targets.targets must be non-empty when production_targets.mode=rolling_deadline_envelope.")

    return ProductionTargetsSettings(
        mode=mode,
        initial_inventory_kg=initial_inventory_kg,
        max_inventory_kg=max_inventory_kg,
        terminal_inventory_value_mode=terminal_inventory_value_mode,
        targets=tuple(targets),
    )


def _parse_reserve_feasibility_proxy_settings(payload: dict[str, Any]) -> ReserveFeasibilityProxySettings:
    raw = payload.get("reserve_feasibility_proxy", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Invalid config section: reserve_feasibility_proxy")

    enabled = bool(raw.get("enabled", False))
    mode = validate_reserve_feasibility_proxy_mode(raw.get("mode", RESERVE_FEASIBILITY_PROXY_MODE_NONE))
    down_activation_duration_hours = float(raw.get("down_activation_duration_hours", 0.25))
    if down_activation_duration_hours <= 0.0:
        raise ValueError(
            "reserve_feasibility_proxy.down_activation_duration_hours must be positive. "
            f"Got: {down_activation_duration_hours!r}"
        )
    up_activation_duration_hours = float(raw.get("up_activation_duration_hours", 0.25))
    if up_activation_duration_hours <= 0.0:
        raise ValueError(
            "reserve_feasibility_proxy.up_activation_duration_hours must be positive. "
            f"Got: {up_activation_duration_hours!r}"
        )
    down_output_absorption_source = validate_reserve_feasibility_proxy_down_source(
        raw.get(
            "down_output_absorption_source",
            RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM,
        )
    )
    up_recovery_source = validate_reserve_feasibility_proxy_up_source(
        raw.get(
            "up_recovery_source",
            RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM,
        )
    )
    if not enabled:
        if mode != RESERVE_FEASIBILITY_PROXY_MODE_NONE:
            raise ValueError(
                "reserve_feasibility_proxy.mode must be 'none' when reserve_feasibility_proxy.enabled=false."
            )
    else:
        if mode not in {
            RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION,
            RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY,
        }:
            raise ValueError(
                "reserve_feasibility_proxy.mode must be a supported conservative mode when enabled."
            )
        if down_output_absorption_source != RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM:
            raise ValueError(
                "Unsupported reserve_feasibility_proxy.down_output_absorption_source for this implementation: "
                f"{down_output_absorption_source!r}"
            )
        if up_recovery_source != RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM:
            raise ValueError(
                "Unsupported reserve_feasibility_proxy.up_recovery_source for this implementation: "
                f"{up_recovery_source!r}"
            )

    return ReserveFeasibilityProxySettings(
        enabled=enabled,
        mode=mode,
        down_activation_duration_hours=down_activation_duration_hours,
        up_activation_duration_hours=up_activation_duration_hours,
        down_output_absorption_source=down_output_absorption_source,
        up_recovery_source=up_recovery_source,
    )


def load_hydrogen_config(config_path: str | Path) -> HydrogenConfig:
    repo_root = _resolve_repo_root()
    config_file = _to_path(config_path, base=repo_root)
    if config_file is None or not config_file.exists():
        raise FileNotFoundError(f"Hydrogen config file not found: {config_path}")
    payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML payload in {config_file}")

    experiment_raw = _require_dict(payload, "experiment")
    models_raw = _require_dict(payload, "models")
    risk_raw = _require_dict(payload, "risk")
    bidding_raw = _require_dict(payload, "bidding")
    mfrr_raw = payload.get("mfrr_capacity_pilot", {})
    if not isinstance(mfrr_raw, dict):
        raise ValueError("Invalid config section: mfrr_capacity_pilot")
    production_raw = _require_dict(payload, "production")
    production_targets = _parse_production_targets_settings(payload)
    reserve_feasibility_proxy = _parse_reserve_feasibility_proxy_settings(payload)
    hydrogen_raw = _require_dict(payload, "hydrogen_system")
    economics_raw = _require_dict(payload, "economics")
    solver_raw = _require_dict(payload, "solver")
    outputs_raw = _require_dict(payload, "outputs")

    experiment = ExperimentSettings(
        name=str(experiment_raw["name"]),
        granularity=str(experiment_raw["granularity"]),
        horizon_mode=str(experiment_raw["horizon_mode"]),
        execution_mode=str(experiment_raw["execution_mode"]),
        selected_weeks_source=_to_path(experiment_raw.get("selected_weeks_source"), base=repo_root) or Path(""),
        selected_week_labels=tuple(str(value) for value in experiment_raw.get("selected_week_labels", [])),
        custom_start=experiment_raw.get("custom_start"),
        custom_end=experiment_raw.get("custom_end"),
        dataset_split=str(experiment_raw.get("dataset_split", "test")),
        random_seed=int(experiment_raw.get("random_seed", 42)),
    )
    models = ModelSettings(
        include=tuple(str(value) for value in models_raw.get("include", [])),
        scenario_catalog=_to_path(models_raw.get("scenario_catalog"), base=repo_root) or Path(""),
    )
    risk = RiskSettings(
        alpha=float(risk_raw["alpha"]),
        gamma_grid=tuple(float(value) for value in risk_raw.get("gamma_grid", [])),
        gamma=float(risk_raw["gamma"]),
        gamma_selection=str(risk_raw.get("gamma_selection", "validation_only")),
        frozen_gamma_path=_to_path(risk_raw.get("frozen_gamma_path"), base=repo_root),
    )
    bidding = BiddingSettings(
        bid_price_grid_eur_per_mwh=tuple(float(value) for value in bidding_raw.get("bid_price_grid_eur_per_mwh", [])),
        price_insensitive_bid_price_eur_per_mwh=float(bidding_raw.get("price_insensitive_bid_price_eur_per_mwh", 3000.0)),
    )
    mfrr_capacity_pilot = MFRRCapacityPilotSettings(
        enabled=bool(mfrr_raw.get("enabled", False)),
        export_path=_to_path(mfrr_raw.get("export_path"), base=repo_root),
        pilot_start_date=mfrr_raw.get("pilot_start_date"),
        pilot_end_date=mfrr_raw.get("pilot_end_date"),
        capacity_offer_big_m_mw=float(
            mfrr_raw.get(
                "capacity_offer_big_m_mw",
                float(hydrogen_raw["electrolyser_nominal_mw"]) + float(hydrogen_raw["compressor_max_mw"]),
            )
        ),
        offer_continuous_mw=bool(mfrr_raw.get("offer_continuous_mw", True)),
    )
    production = ProductionSettings(
        target_semantics=str(production_raw.get("target_semantics", "lower_bound_reference")),
        allow_above_target_production=bool(production_raw.get("allow_above_target_production", True)),
        allow_above_target_sales=bool(production_raw.get("allow_above_target_sales", True)),
    )
    hydrogen_system = HydrogenSystemSettings(
        electrolyser_nominal_mw=float(hydrogen_raw["electrolyser_nominal_mw"]),
        electrolyser_min_mw=float(hydrogen_raw["electrolyser_min_mw"]),
        electrolyser_ramp_mw_per_h=float(hydrogen_raw["electrolyser_ramp_mw_per_h"]),
        h2_efficiency_kg_per_mwh=float(hydrogen_raw["h2_efficiency_kg_per_mwh"]),
        compressor_max_mw=float(hydrogen_raw["compressor_max_mw"]),
        compressor_specific_mwh_per_kg=float(hydrogen_raw["compressor_specific_mwh_per_kg"]),
        storage_capacity_kg=float(hydrogen_raw["storage_capacity_kg"]),
        storage_initial_kg=float(hydrogen_raw["storage_initial_kg"]),
        reserve_fraction=float(hydrogen_raw["reserve_fraction"]),
        reserve_sensitivity=tuple(float(value) for value in hydrogen_raw.get("reserve_sensitivity", [])),
    )
    economics = EconomicSettings(
        h2_sale_price_eur_per_kg=float(economics_raw["h2_sale_price_eur_per_kg"]),
        daily_target_kg=float(economics_raw["daily_target_kg"]),
        p_ref_eur_per_mwh=float(economics_raw["p_ref_eur_per_mwh"]),
        terminal_inventory_location=str(economics_raw["terminal_inventory_location"]),
        shortfall_penalty_eur_per_kg=float(economics_raw["shortfall_penalty_eur_per_kg"]),
        unused_energy_penalty_eur_per_mwh=float(economics_raw.get("unused_energy_penalty_eur_per_mwh", 4000.0)),
    )
    solver = SolverSettings(
        package_preference=str(solver_raw.get("package_preference", "auto")),
        solver_name=str(solver_raw.get("solver_name", "auto")),
        mip_gap=float(solver_raw.get("mip_gap", 0.001)),
        time_limit_seconds=int(solver_raw.get("time_limit_seconds", 300)),
        grb_license_file=_to_path(solver_raw.get("grb_license_file"), base=repo_root),
    )
    outputs = OutputSettings(
        root=_to_path(outputs_raw.get("root"), base=repo_root) or (repo_root / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "runs"),
        save_figures=bool(outputs_raw.get("save_figures", True)),
        save_timeseries=bool(outputs_raw.get("save_timeseries", True)),
        save_solver_log=bool(outputs_raw.get("save_solver_log", True)),
    )
    return HydrogenConfig(
        repo_root=repo_root,
        config_path=config_file,
        experiment=experiment,
        models=models,
        strategies=tuple(str(value) for value in payload.get("strategies", [])),
        risk=risk,
        bidding=bidding,
        mfrr_capacity_pilot=mfrr_capacity_pilot,
        production=production,
        production_targets=production_targets,
        reserve_feasibility_proxy=reserve_feasibility_proxy,
        hydrogen_system=hydrogen_system,
        economics=economics,
        solver=solver,
        outputs=outputs,
    )
