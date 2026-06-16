from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
)

from .model import collect_model_stats
from .topology_loader import load_topology_skeleton
from .topology_objects import SteelTopology, build_steel_topology
from .topology_queries import TopologyAssemblyBundle, assemble_topology_views


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PROVISIONAL_DEV_INPUT_ROOT = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_provisional_dev_input"
)
DEFAULT_APPROVED_INPUT_ROOT = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"
)
DEFAULT_REVIEW_ROOT = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
)

ALLOWED_CONFIGURATION_IDS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
TARGET_NAME_BY_HOURS = {
    24: "horizon_total_target_24h_debug",
    168: "horizon_total_target_168h_one_week",
}
DEV_ONLY_STATUS_RULE = {
    "approval_status": "provisional_development_only",
    "executable_status": "dev_executable_only",
    "thesis_usability": "false",
    "reviewer_decision_required": "true",
    "codex_may_decide": "false",
}
REFUSED_APPROVAL_STATUSES = {"approved", "missing_required_dev_value", "formula_only_not_executable"}
REFUSED_EXECUTABLE_STATUSES = {"not_executable", "formula_only_not_executable"}
TARGET_CARRIER = "liquid_steel"
TOPOLOGY_CARRIER_NORMALISATION = {
    "crude_steel_or_liquid_steel": "liquid_steel",
    "hot_metal": "hot_metal",
    "DRI_or_HDRI": "DRI_or_HDRI",
}

# The provisional dev pack still uses candidate-review process labels. This bridge is
# intentionally local to the smoke builder and traceable to topology_routes_candidate_review.csv.
PROCESS_UNIT_COMPATIBILITY_MAP: dict[str, dict[str, str]] = {
    "C0_current_BF_BOF_reference": {
        "bf6": "c0_blast_furnace",
        "osf_converters": "c0_bof_converter",
    },
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF": {
        "bf6": "c1_blast_furnace",
        "osf_converters": "c1_bof_converter",
        "dri": "c1_ng_drp",
        "eaf": "c1_eaf",
    },
}
OUT_OF_SCOPE_PROCESS_ALIASES = {"continuous_casting", "hot_strip_mill"}
INVENTORY_TABLE_FILENAMES = {
    "store_capacities.csv",
    "initial_inventories.csv",
    "terminal_inventory_rules.csv",
    "inventory_endpoint_policies.csv",
}


class LiquidSteelSmokeBuilderError(ValueError):
    """Raised when the restricted smoke builder encounters forbidden or missing inputs."""


@dataclass(frozen=True)
class RefusedRow:
    table_name: str
    row_id: str
    reason: str


@dataclass(frozen=True)
class InputValidationReport:
    configuration_id: str
    horizon_hours: int
    available_configurations: tuple[str, ...]
    selected_configurations: tuple[str, ...]
    consumed_process_bound_rows: tuple[str, ...]
    consumed_conversion_rows: tuple[str, ...]
    consumed_production_target_rows: tuple[str, ...]
    refused_rows: tuple[RefusedRow, ...]
    encountered_non_executable_row: bool
    thesis_usability: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class PreparedSmokeInputs:
    validation_report: InputValidationReport
    topology: SteelTopology
    topology_views: TopologyAssemblyBundle
    process_bounds: dict[tuple[str, str], float]
    conversion_rows: pd.DataFrame
    production_target_value: float
    topology_process_ids: tuple[str, ...]
    liquid_steel_process_ids: tuple[str, ...]
    internal_balance_carriers: tuple[str, ...]


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _normalise_lower(value: Any) -> str:
    return str(value).strip().lower()


def _ensure_allowed_root(input_root: str | Path) -> Path:
    root = Path(input_root).resolve()
    if root == DEFAULT_APPROVED_INPUT_ROOT or root.name == "s2_approved_model_input":
        raise LiquidSteelSmokeBuilderError("S2.9a builder must refuse s2_approved_model_input.")
    if root.name != "s2_provisional_dev_input":
        raise LiquidSteelSmokeBuilderError("S2.9a builder must consume only s2_provisional_dev_input.")
    return root


def _load_topology(review_root: str | Path) -> tuple[SteelTopology, TopologyAssemblyBundle]:
    topology_bundle = load_topology_skeleton(review_root)
    topology = build_steel_topology(topology_bundle, validate=True)
    return topology, assemble_topology_views(topology)


def _scan_forbidden_statuses(frame: pd.DataFrame, *, table_name: str) -> None:
    if "approval_status" in frame.columns:
        approval_statuses = frame["approval_status"].astype(str).str.strip().str.lower()
        if approval_statuses.eq("approved").any():
            raise LiquidSteelSmokeBuilderError(f"{table_name} contains forbidden approval_status=approved rows.")
        if approval_statuses.eq("missing_required_dev_value").any():
            # The restricted builder must fail on unresolved required values before model construction.
            raise LiquidSteelSmokeBuilderError(
                f"{table_name} still contains missing_required_dev_value rows, which are out of scope for S2.9a."
            )
    if "thesis_usability" in frame.columns and (~frame["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise LiquidSteelSmokeBuilderError(f"{table_name} contains forbidden thesis_usability values.")


def _require_dev_only_row(row: pd.Series, *, table_name: str) -> None:
    for field_name, expected_value in DEV_ONLY_STATUS_RULE.items():
        if _normalise_lower(row[field_name]) != expected_value:
            raise LiquidSteelSmokeBuilderError(
                f"{table_name} row {row['row_id']} is not dev-only executable: {field_name}={row[field_name]!r}."
            )


def _load_dev_tables(root: Path) -> dict[str, pd.DataFrame]:
    filenames = (
        "process_bounds.csv",
        "conversion_coefficients.csv",
        "production_targets.csv",
        "store_capacities.csv",
        "initial_inventories.csv",
        "terminal_inventory_rules.csv",
        "inventory_endpoint_policies.csv",
    )
    tables = {filename: _read_csv(root / filename) for filename in filenames}
    for filename, frame in tables.items():
        _scan_forbidden_statuses(frame, table_name=filename)
    return tables


def _selected_target_name(horizon_hours: int) -> str:
    try:
        return TARGET_NAME_BY_HOURS[horizon_hours]
    except KeyError as exc:
        raise LiquidSteelSmokeBuilderError(
            f"Unsupported horizon_hours={horizon_hours}. Allowed values: {sorted(TARGET_NAME_BY_HOURS)}."
        ) from exc


def _expected_aliases(configuration_id: str) -> set[str]:
    return set(PROCESS_UNIT_COMPATIBILITY_MAP[configuration_id])


def _infer_output_carrier(topology: SteelTopology, configuration_id: str, topology_process_id: str) -> str:
    arcs = [
        arc
        for arc in topology.list_arcs(configuration_id=configuration_id)
        if arc.from_node == topology_process_id
    ]
    carriers = {
        TOPOLOGY_CARRIER_NORMALISATION[arc.carrier_id]
        for arc in arcs
        if arc.carrier_id in TOPOLOGY_CARRIER_NORMALISATION
    }
    if len(carriers) != 1:
        raise LiquidSteelSmokeBuilderError(
            f"Could not infer a unique stage output carrier for process {topology_process_id} in {configuration_id}."
        )
    return next(iter(carriers))


def _prepare_process_bounds(
    frame: pd.DataFrame,
    *,
    configuration_id: str,
    refused_rows: list[RefusedRow],
) -> dict[tuple[str, str], float]:
    alias_map = PROCESS_UNIT_COMPATIBILITY_MAP[configuration_id]
    selected = frame.loc[frame["configuration_id"].eq(configuration_id)].copy()
    process_bounds: dict[tuple[str, str], float] = {}

    for row in selected.to_dict(orient="records"):
        row_id = row["row_id"]
        alias_id = row["process_unit_id"]
        executable_status = _normalise_lower(row["executable_status"])
        if alias_id in OUT_OF_SCOPE_PROCESS_ALIASES:
            refused_rows.append(RefusedRow("process_bounds.csv", row_id, "downstream_or_casting_out_of_scope"))
            continue
        if alias_id not in alias_map:
            raise LiquidSteelSmokeBuilderError(
                f"process_bounds.csv row {row_id} uses unsupported process_unit_id={alias_id!r} for {configuration_id}."
            )
        if executable_status != "dev_executable_only":
            if executable_status in REFUSED_EXECUTABLE_STATUSES:
                raise LiquidSteelSmokeBuilderError(
                    f"process_bounds.csv row {row_id} is marked {executable_status} and must be refused in S2.9a."
                )
            raise LiquidSteelSmokeBuilderError(
                f"process_bounds.csv row {row_id} is required for smoke scope but is not dev_executable_only."
            )
        _require_dev_only_row(pd.Series(row), table_name="process_bounds.csv")
        value = pd.to_numeric(row["value"], errors="coerce")
        if pd.isna(value) or float(value) <= 0.0:
            raise LiquidSteelSmokeBuilderError(f"process_bounds.csv row {row_id} must carry a positive numeric t/h value.")
        if _normalise_lower(row["unit"]) != "t_per_hour":
            raise LiquidSteelSmokeBuilderError(f"process_bounds.csv row {row_id} must use unit=t_per_hour.")
        if "annual_anchor=" not in _normalise_lower(row["translation_basis"]):
            raise LiquidSteelSmokeBuilderError(
                f"process_bounds.csv row {row_id} must keep an explicit annual-anchor translation basis."
            )
        topology_process_id = alias_map[alias_id]
        process_bounds[(topology_process_id, row["parameter_name"])] = float(value)

    missing_by_alias = {
        alias_id
        for alias_id in _expected_aliases(configuration_id)
        if alias_id not in selected.loc[
            selected["process_unit_id"].isin(_expected_aliases(configuration_id))
            & selected["executable_status"].str.lower().eq("dev_executable_only"),
            "process_unit_id",
        ].tolist()
    }
    if missing_by_alias:
        raise LiquidSteelSmokeBuilderError(
            f"Missing required smoke-scope process bounds for {configuration_id}: {sorted(missing_by_alias)}."
        )
    return process_bounds


def _prepare_conversion_rows(
    frame: pd.DataFrame,
    *,
    configuration_id: str,
    refused_rows: list[RefusedRow],
) -> pd.DataFrame:
    alias_map = PROCESS_UNIT_COMPATIBILITY_MAP[configuration_id]
    selected = frame.loc[frame["configuration_id"].eq(configuration_id)].copy()
    consumed_rows: list[dict[str, Any]] = []
    for row in selected.to_dict(orient="records"):
        row_id = row["row_id"]
        alias_id = row["process_unit_id"]
        if alias_id in OUT_OF_SCOPE_PROCESS_ALIASES:
            refused_rows.append(RefusedRow("conversion_coefficients.csv", row_id, "downstream_or_casting_out_of_scope"))
            continue
        if alias_id not in alias_map:
            raise LiquidSteelSmokeBuilderError(
                f"conversion_coefficients.csv row {row_id} uses unsupported process_unit_id={alias_id!r} for {configuration_id}."
            )
        if _normalise_lower(row["executable_status"]) != "dev_executable_only":
            if _normalise_lower(row["executable_status"]) in REFUSED_EXECUTABLE_STATUSES:
                raise LiquidSteelSmokeBuilderError(
                    f"conversion_coefficients.csv row {row_id} is marked {_normalise_lower(row['executable_status'])} and must be refused in S2.9a."
                )
            raise LiquidSteelSmokeBuilderError(
                f"conversion_coefficients.csv row {row_id} is required for smoke scope but is not dev_executable_only."
            )
        _require_dev_only_row(pd.Series(row), table_name="conversion_coefficients.csv")
        value = pd.to_numeric(row["value"], errors="coerce")
        if pd.isna(value) or float(value) <= 0.0:
            raise LiquidSteelSmokeBuilderError(
                f"conversion_coefficients.csv row {row_id} must carry a positive numeric value."
            )
        consumed_row = dict(row)
        consumed_row["topology_process_unit_id"] = alias_map[alias_id]
        consumed_row["value"] = float(value)
        consumed_rows.append(consumed_row)

    if not consumed_rows:
        raise LiquidSteelSmokeBuilderError(f"No in-scope conversion coefficients were found for {configuration_id}.")
    return pd.DataFrame(consumed_rows)


def _prepare_production_target(
    frame: pd.DataFrame,
    *,
    configuration_id: str,
    horizon_hours: int,
    refused_rows: list[RefusedRow],
) -> float:
    target_name = _selected_target_name(horizon_hours)
    selected = frame.loc[frame["configuration_id"].eq(configuration_id)].copy()
    for row in selected.loc[~selected["target_name"].eq(target_name)].to_dict(orient="records"):
        refused_rows.append(RefusedRow("production_targets.csv", row["row_id"], "horizon_not_selected"))
    chosen = selected.loc[selected["target_name"].eq(target_name)]
    if len(chosen) != 1:
        raise LiquidSteelSmokeBuilderError(
            f"Expected exactly one production-target row for {configuration_id} and {target_name}, found {len(chosen)}."
        )
    row = chosen.iloc[0]
    if _normalise_lower(row["carrier_id"]) != TARGET_CARRIER:
        raise LiquidSteelSmokeBuilderError("The restricted smoke scope requires a liquid_steel target basis.")
    if "route_neutral" not in _normalise_lower(row["value_basis"]):
        raise LiquidSteelSmokeBuilderError("Production targets must remain route-neutral in the default smoke model.")
    _require_dev_only_row(row, table_name="production_targets.csv")
    value = pd.to_numeric(row["value"], errors="coerce")
    if pd.isna(value) or float(value) <= 0.0:
        raise LiquidSteelSmokeBuilderError("Production target must carry a positive numeric horizon-total value.")
    return float(value)


def validate_liquid_steel_smoke_inputs(
    *,
    configuration_id: str,
    horizon_hours: int = 24,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    enable_inventory_rows: bool = False,
) -> PreparedSmokeInputs:
    if configuration_id not in ALLOWED_CONFIGURATION_IDS:
        raise LiquidSteelSmokeBuilderError(
            f"S2.9a only supports {sorted(ALLOWED_CONFIGURATION_IDS)}. Got {configuration_id!r}."
        )
    if enable_inventory_rows:
        raise LiquidSteelSmokeBuilderError("S2.9a must refuse store-capacity and inventory activation.")

    dev_root = _ensure_allowed_root(provisional_dev_input_root)
    topology, topology_views = _load_topology(review_root)
    dev_tables = _load_dev_tables(dev_root)

    refused_rows: list[RefusedRow] = []
    process_bounds = _prepare_process_bounds(
        dev_tables["process_bounds.csv"],
        configuration_id=configuration_id,
        refused_rows=refused_rows,
    )
    conversion_rows = _prepare_conversion_rows(
        dev_tables["conversion_coefficients.csv"],
        configuration_id=configuration_id,
        refused_rows=refused_rows,
    )
    production_target_value = _prepare_production_target(
        dev_tables["production_targets.csv"],
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        refused_rows=refused_rows,
    )

    encountered_non_executable = False
    for filename in INVENTORY_TABLE_FILENAMES:
        frame = dev_tables[filename]
        selected = frame.loc[frame["configuration_id"].eq(configuration_id)]
        for row in selected.to_dict(orient="records"):
            refused_rows.append(RefusedRow(filename, row["row_id"], "inventory_scope_deferred"))
            if _normalise_lower(row["executable_status"]) != "dev_executable_only":
                encountered_non_executable = True

    topology_process_ids = tuple(
        sorted({row["topology_process_unit_id"] for row in conversion_rows.to_dict(orient="records")})
    )
    liquid_steel_process_ids = tuple(
        sorted(
            process_unit_id
            for process_unit_id in topology_process_ids
            if _infer_output_carrier(topology, configuration_id, process_unit_id) == TARGET_CARRIER
        )
    )
    internal_balance_carriers = tuple(
        sorted(
            {
                carrier_id
                for carrier_id in conversion_rows["carrier_id"].astype(str)
                if carrier_id in {"hot_metal", "DRI_or_HDRI"}
            }
        )
    )

    target_aliases = set(_expected_aliases(configuration_id))
    alias_rows = conversion_rows["process_unit_id"].astype(str)
    if not target_aliases.issubset(set(alias_rows)):
        missing = sorted(target_aliases - set(alias_rows))
        raise LiquidSteelSmokeBuilderError(f"Missing required conversion-coefficient aliases for {configuration_id}: {missing}")

    validation_report = InputValidationReport(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        available_configurations=tuple(sorted(ALLOWED_CONFIGURATION_IDS)),
        selected_configurations=(configuration_id,),
        consumed_process_bound_rows=tuple(
            dev_tables["process_bounds.csv"]
            .loc[
                dev_tables["process_bounds.csv"]["configuration_id"].eq(configuration_id)
                & dev_tables["process_bounds.csv"]["process_unit_id"].isin(_expected_aliases(configuration_id))
                & dev_tables["process_bounds.csv"]["executable_status"].str.lower().eq("dev_executable_only"),
                "row_id",
            ]
            .tolist()
        ),
        consumed_conversion_rows=tuple(conversion_rows["row_id"].astype(str).tolist()),
        consumed_production_target_rows=tuple(
            dev_tables["production_targets.csv"]
            .loc[
                dev_tables["production_targets.csv"]["configuration_id"].eq(configuration_id)
                & dev_tables["production_targets.csv"]["target_name"].eq(_selected_target_name(horizon_hours)),
                "row_id",
            ]
            .tolist()
        ),
        refused_rows=tuple(refused_rows),
        encountered_non_executable_row=encountered_non_executable,
        thesis_usability=False,
        notes=(
            "Consumes only dev_executable_only provisional rows.",
            "Inventory and downstream scopes remain refused in S2.9a.",
        ),
    )
    return PreparedSmokeInputs(
        validation_report=validation_report,
        topology=topology,
        topology_views=topology_views,
        process_bounds=process_bounds,
        conversion_rows=conversion_rows,
        production_target_value=production_target_value,
        topology_process_ids=topology_process_ids,
        liquid_steel_process_ids=liquid_steel_process_ids,
        internal_balance_carriers=internal_balance_carriers,
    )


def build_liquid_steel_smoke_model(
    *,
    configuration_id: str,
    horizon_hours: int = 24,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    enable_inventory_rows: bool = False,
    allow_target_shortfall: bool = False,
):
    if allow_target_shortfall:
        raise LiquidSteelSmokeBuilderError("Default S2.9a smoke builder does not allow shortfall slack.")

    prepared = validate_liquid_steel_smoke_inputs(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        provisional_dev_input_root=provisional_dev_input_root,
        review_root=review_root,
        enable_inventory_rows=enable_inventory_rows,
    )

    output_carrier_by_process = {
        process_unit_id: _infer_output_carrier(prepared.topology, configuration_id, process_unit_id)
        for process_unit_id in prepared.topology_process_ids
    }

    input_coefficients: dict[tuple[str, str], float] = {}
    output_reference_coefficients: dict[tuple[str, str], float] = {}
    for row in prepared.conversion_rows.to_dict(orient="records"):
        key = (row["topology_process_unit_id"], row["carrier_id"])
        role = row["coefficient_role"]
        if role == "input_consumption":
            input_coefficients[key] = float(row["value"])
        elif role == "output_production":
            output_reference_coefficients[key] = float(row["value"])

    model = ConcreteModel(name=f"s2_liquid_steel_smoke_{configuration_id}_{horizon_hours}h")
    model.TIME = Set(initialize=list(range(horizon_hours)), ordered=True)
    model.PROCESSES = Set(initialize=list(prepared.topology_process_ids), ordered=True)
    model.INTERNAL_CARRIERS = Set(initialize=list(prepared.internal_balance_carriers), ordered=True)

    model.process_activity = Var(model.PROCESSES, model.TIME, domain=NonNegativeReals)

    min_bounds = {
        process_unit_id: bound
        for (process_unit_id, parameter_name), bound in prepared.process_bounds.items()
        if parameter_name in {"min_continuous_rate", "minimum_continuous_rate"}
    }
    max_bounds = {
        process_unit_id: bound
        for (process_unit_id, parameter_name), bound in prepared.process_bounds.items()
        if parameter_name in {"max_continuous_rate", "maximum_continuous_rate", "maximum_batch_equivalent_rate"}
    }

    def _process_min_rule(m, process_unit_id: str, time_index: int):
        return m.process_activity[process_unit_id, time_index] >= min_bounds.get(process_unit_id, 0.0)

    def _process_max_rule(m, process_unit_id: str, time_index: int):
        if process_unit_id not in max_bounds:
            raise LiquidSteelSmokeBuilderError(f"Missing maximum bound for process {process_unit_id}.")
        return m.process_activity[process_unit_id, time_index] <= max_bounds[process_unit_id]

    model.process_min_bound = Constraint(model.PROCESSES, model.TIME, rule=_process_min_rule)
    model.process_max_bound = Constraint(model.PROCESSES, model.TIME, rule=_process_max_rule)

    def _carrier_balance_rule(m, carrier_id: str, time_index: int):
        production_terms = []
        consumption_terms = []
        for process_unit_id in m.PROCESSES:
            default_output_carrier = output_carrier_by_process[process_unit_id]
            output_reference = output_reference_coefficients.get((process_unit_id, carrier_id))
            if output_reference is not None:
                production_terms.append(output_reference * m.process_activity[process_unit_id, time_index])
            elif default_output_carrier == carrier_id:
                production_terms.append(m.process_activity[process_unit_id, time_index])
            input_value = input_coefficients.get((process_unit_id, carrier_id))
            if input_value is not None:
                consumption_terms.append(input_value * m.process_activity[process_unit_id, time_index])
        if not production_terms and not consumption_terms:
            raise LiquidSteelSmokeBuilderError(f"No balance terms were found for internal carrier {carrier_id}.")
        return sum(production_terms) == sum(consumption_terms)

    model.internal_material_balance = Constraint(model.INTERNAL_CARRIERS, model.TIME, rule=_carrier_balance_rule)

    def _liquid_steel_output_rule(m, time_index: int):
        return sum(m.process_activity[process_unit_id, time_index] for process_unit_id in prepared.liquid_steel_process_ids)

    model.liquid_steel_output = Expression(model.TIME, rule=_liquid_steel_output_rule)
    model.horizon_total_liquid_steel_output = Expression(expr=sum(model.liquid_steel_output[t] for t in model.TIME))
    model.production_target = Constraint(expr=model.horizon_total_liquid_steel_output >= prepared.production_target_value)
    model.zero_objective = Objective(expr=0.0, sense=minimize)

    validation_report = prepared.validation_report
    model.s2_validation_report = validation_report
    model.s2_metadata = {
        "scope": "restricted_liquid_steel_smoke_lp",
        "configuration_id": configuration_id,
        "horizon_hours": horizon_hours,
        "thesis_usability": False,
        "input_surface": "s2_provisional_dev_input",
        "production_target_carrier": TARGET_CARRIER,
        "route_neutral_target": True,
        "inventory_scope_active": False,
        "downstream_scope_active": False,
        "allow_target_shortfall": False,
    }
    model.s2_model_stats = collect_model_stats(model)
    return model
