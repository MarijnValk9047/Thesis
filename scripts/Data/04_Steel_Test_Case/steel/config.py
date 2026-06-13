from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .input_tables import InputGovernanceSummary, load_governed_toy_tables, summarize_input_governance


@dataclass(frozen=True)
class SolverConfig:
    preferred_solvers: list[str]
    tee: bool


@dataclass(frozen=True)
class InputTablesConfig:
    table_root: Path
    scenario_or_config: str
    input_mode: str


@dataclass(frozen=True)
class DiagnosticsConfig:
    case_label: str
    expected_infeasibility_class: str | None
    diagnostic_mode: bool


@dataclass(frozen=True)
class TimeConfig:
    horizon_hours: int
    start_index: int


@dataclass(frozen=True)
class ProcessConfig:
    name: str
    route: str
    capacity_min_tph: float
    capacity_max_tph: float
    operating_cost_per_tonne: float
    conversion: dict[str, float]
    toy_value_note: str


@dataclass(frozen=True)
class SourceConfig:
    name: str
    carrier: str
    unit_cost_per_tonne: float
    max_supply_tph: float


@dataclass(frozen=True)
class SinkConfig:
    name: str
    carrier: str
    description: str


@dataclass(frozen=True)
class StoreConfig:
    name: str
    carrier: str
    capacity_tonnes: float
    initial_inventory_tonnes: float
    terminal_min_tonnes: float
    terminal_max_tonnes: float
    charge_max_tph: float
    discharge_max_tph: float
    throughput_cost_per_tonne: float
    anti_free_battery: bool
    toy_value_note: str


@dataclass(frozen=True)
class RunConfig:
    output_root: str
    run_slug: str
    output_policy: str
    run_class: str
    lineage_role: str
    retention_status: str


@dataclass(frozen=True)
class ProductionTargetConfig:
    sink: str
    carrier: str
    total_tonnes: float


@dataclass(frozen=True)
class ModelMeta:
    stage: str
    scope_label: str
    timestamp_mode: str
    toy_values_not_approved: bool
    note: str


@dataclass(frozen=True)
class SteelToyConfig:
    config_path: Path
    raw: dict[str, Any]
    model: ModelMeta
    run: RunConfig
    solver: SolverConfig
    time: TimeConfig
    input_tables: InputTablesConfig | None
    diagnostics: DiagnosticsConfig
    carriers: list[str]
    processes: dict[str, ProcessConfig]
    sources: dict[str, SourceConfig]
    sinks: dict[str, SinkConfig]
    stores: dict[str, StoreConfig]
    production_target: ProductionTargetConfig
    flags: dict[str, bool]
    input_table_paths: dict[str, Path]
    input_table_row_counts: dict[str, int]
    input_governance: InputGovernanceSummary

    @property
    def time_indices(self) -> list[int]:
        start = self.time.start_index
        return list(range(start, start + self.time.horizon_hours))


def _require_mapping(payload: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError(f"{field_name} must be a mapping.")
    return payload


def _build_config_from_input_tables(path: Path, raw: dict[str, Any]) -> SteelToyConfig:
    inputs_raw = _require_mapping(raw["input_tables"], "input_tables")
    diagnostics_raw = _require_mapping(raw["diagnostics"], "diagnostics")
    table_root = (path.parent / inputs_raw["table_root"]).resolve()
    input_mode = str(inputs_raw["input_mode"])
    bundle = load_governed_toy_tables(
        table_root,
        inputs_raw["scenario_or_config"],
        input_mode=input_mode,
    )
    tables = bundle.tables
    input_governance = summarize_input_governance(tables, input_mode=input_mode)

    processes: dict[str, ProcessConfig] = {}
    conversion_rows = tables["conversion_coefficients"]
    for row in tables["process_units"].to_dict(orient="records"):
        process_id = str(row["process_id"])
        process_conversions = {
            str(conv["carrier_id"]): float(conv["coefficient"])
            for conv in conversion_rows[conversion_rows["process_id"] == process_id].to_dict(orient="records")
        }
        processes[process_id] = ProcessConfig(
            name=process_id,
            route=str(row["route"]),
            capacity_min_tph=float(row["capacity_min_tph"]),
            capacity_max_tph=float(row["capacity_max_tph"]),
            operating_cost_per_tonne=float(row["operating_cost_per_tonne"]),
            conversion=process_conversions,
            toy_value_note=str(row["notes"]),
        )

    sources = {
        str(row["source_id"]): SourceConfig(
            name=str(row["source_id"]),
            carrier=str(row["carrier_id"]),
            unit_cost_per_tonne=float(row["unit_cost_per_tonne"]),
            max_supply_tph=float(row["max_supply_tph"]),
        )
        for row in tables["sources"].to_dict(orient="records")
    }
    sinks = {
        str(row["sink_id"]): SinkConfig(
            name=str(row["sink_id"]),
            carrier=str(row["carrier_id"]),
            description=str(row["description"]),
        )
        for row in tables["sinks"].to_dict(orient="records")
    }

    initial_inventory_rows = tables["initial_inventories"].set_index("store_id")
    terminal_rows = tables["terminal_inventory_rules"].set_index("store_id")
    stores: dict[str, StoreConfig] = {}
    for row in tables["stores"].to_dict(orient="records"):
        store_id = str(row["store_id"])
        stores[store_id] = StoreConfig(
            name=store_id,
            carrier=str(row["carrier_id"]),
            capacity_tonnes=float(row["capacity_tonnes"]),
            initial_inventory_tonnes=float(initial_inventory_rows.loc[store_id, "initial_inventory_tonnes"]),
            terminal_min_tonnes=float(terminal_rows.loc[store_id, "terminal_min_tonnes"]),
            terminal_max_tonnes=float(terminal_rows.loc[store_id, "terminal_max_tonnes"]),
            charge_max_tph=float(row["charge_max_tph"]),
            discharge_max_tph=float(row["discharge_max_tph"]),
            throughput_cost_per_tonne=float(row["throughput_cost_per_tonne"]),
            anti_free_battery=bool(row["anti_free_battery"]),
            toy_value_note=str(row["notes"]),
        )

    target_row = tables["production_targets"].to_dict(orient="records")[0]
    return SteelToyConfig(
        config_path=path,
        raw=raw,
        model=ModelMeta(**raw["model"]),
        run=RunConfig(**raw["run"]),
        solver=SolverConfig(**raw["solver"]),
        time=TimeConfig(**raw["time"]),
        input_tables=InputTablesConfig(
            table_root=table_root,
            scenario_or_config=str(inputs_raw["scenario_or_config"]),
            input_mode=input_mode,
        ),
        diagnostics=DiagnosticsConfig(
            case_label=str(diagnostics_raw["case_label"]),
            expected_infeasibility_class=(
                None if diagnostics_raw.get("expected_infeasibility_class") in {None, ""} else str(diagnostics_raw["expected_infeasibility_class"])
            ),
            diagnostic_mode=bool(diagnostics_raw["diagnostic_mode"]),
        ),
        carriers=tables["carriers"]["carrier_id"].astype(str).tolist(),
        processes=processes,
        sources=sources,
        sinks=sinks,
        stores=stores,
        production_target=ProductionTargetConfig(
            sink=str(target_row["sink_id"]),
            carrier=str(target_row["carrier_id"]),
            total_tonnes=float(target_row["total_tonnes"]),
        ),
        flags={str(key): bool(value) for key, value in _require_mapping(raw["flags"], "flags").items()},
        input_table_paths=bundle.table_paths,
        input_table_row_counts=bundle.row_counts,
        input_governance=input_governance,
    )


def load_config(config_path: str | Path) -> SteelToyConfig:
    path = Path(config_path).resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("Top-level config payload must be a mapping.")

    if "input_tables" in raw:
        return _build_config_from_input_tables(path, raw)

    processes_raw = _require_mapping(raw["processes"], "processes")
    sources_raw = _require_mapping(raw["sources"], "sources")
    sinks_raw = _require_mapping(raw["sinks"], "sinks")
    stores_raw = _require_mapping(raw["stores"], "stores")
    flags_raw = _require_mapping(raw["flags"], "flags")

    processes = {
        name: ProcessConfig(name=name, **payload)
        for name, payload in processes_raw.items()
    }
    sources = {
        name: SourceConfig(name=name, max_supply_tph=float("inf"), **payload)
        for name, payload in sources_raw.items()
    }
    sinks = {
        name: SinkConfig(name=name, **payload)
        for name, payload in sinks_raw.items()
    }
    stores = {
        name: StoreConfig(name=name, **payload)
        for name, payload in stores_raw.items()
    }

    return SteelToyConfig(
        config_path=path,
        raw=raw,
        model=ModelMeta(**raw["model"]),
        run=RunConfig(**raw["run"]),
        solver=SolverConfig(**raw["solver"]),
        time=TimeConfig(**raw["time"]),
        input_tables=None,
        diagnostics=DiagnosticsConfig(case_label="legacy_yaml", expected_infeasibility_class=None, diagnostic_mode=False),
        carriers=list(raw["carriers"]),
        processes=processes,
        sources=sources,
        sinks=sinks,
        stores=stores,
        production_target=ProductionTargetConfig(**raw["production_target"]),
        flags={str(key): bool(value) for key, value in flags_raw.items()},
        input_table_paths={},
        input_table_row_counts={},
        input_governance=InputGovernanceSummary(
            input_mode="legacy_yaml",
            contains_toy_values=True,
            contains_candidate_not_approved_values=False,
            contains_validation_only_values=False,
            contains_sensitivity_only_values=False,
            all_required_inputs_approved=False,
            thesis_usable=False,
            thesis_usability_reason="Legacy inline YAML scaffold is not approved model input and is not thesis-usable.",
        ),
    )
