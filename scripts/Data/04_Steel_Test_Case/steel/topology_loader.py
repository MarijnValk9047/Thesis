from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd


TOPOLOGY_SKELETON_DIRNAME = "s2_topology_skeleton"
TOPOLOGY_SKELETON_FILE_SPECS: dict[str, list[str]] = {
    "configurations.csv": [
        "configuration_id",
        "configuration_name",
        "role",
        "main_case_flag",
        "sensitivity_only_flag",
        "optional_later_flag",
        "topology_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "notes",
    ],
    "routes.csv": [
        "route_id",
        "configuration_id",
        "route_name",
        "route_role",
        "included_in_main_case",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "process_units.csv": [
        "process_unit_id",
        "configuration_id",
        "route_id",
        "process_unit_name",
        "process_class",
        "continuity_class",
        "structural_role",
        "included_in_s2",
        "postponed_to_stage",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "carriers.csv": [
        "carrier_id",
        "carrier_name",
        "carrier_class",
        "material_or_energy",
        "s2_in_scope",
        "external_supply_flag",
        "internal_carrier_flag",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "stores.csv": [
        "store_id",
        "configuration_id",
        "route_id",
        "carrier_id",
        "store_name",
        "store_class",
        "flexibility_role",
        "endpoint_policy",
        "initial_inventory_policy",
        "bounded_store_required",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "topology_arcs.csv": [
        "arc_id",
        "configuration_id",
        "route_id",
        "from_node",
        "to_node",
        "carrier_id",
        "arc_role",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "inventory_policy.csv": [
        "policy_id",
        "store_class",
        "endpoint_policy",
        "initial_inventory_policy",
        "terminal_inventory_policy",
        "allowed_use",
        "forbidden_use",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
}

TOPOLOGY_REQUIRED_CONFIGURATION_IDS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
TOPOLOGY_REQUIRED_ROUTE_ROWS = {
    ("C0_current_BF_BOF_reference", "C0_ROUTE_BF_BOF"),
    ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_RETAINED_BF_BOF"),
    ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_NG_DRP_EAF"),
}
TOPOLOGY_ALLOWED_NUMERICAL_STATUSES = {"no_numerical_value", "candidate_not_approved", "not_applicable"}
TOPOLOGY_ALLOWED_EXECUTABLE_STATUSES = {"non_executable"}
TOPOLOGY_ALLOWED_APPROVAL_STATUSES = {"structural_candidate", "scope_freeze_only", "not_approved", "blocked"}
TOPOLOGY_REQUIRED_EXTERNAL_BOUNDARY_CARRIERS = {
    "coal_or_coke_input_boundary",
    "iron_ore_or_pellet_input_boundary",
    "scrap_input_boundary",
    "flux_input_boundary",
}
TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS = (
    r"phase 2",
    r"phase2",
    r"phase_2",
    r"phase 3",
    r"phase3",
    r"phase_3",
    r"full_hydrogen",
    r"full hydrogen",
    r"on_site_electrolysis",
    r"on-site electrolysis",
    r"hydrogen_production",
    r"hydrogen storage",
    r"hydrogen_storage",
    r"saf",
    r"ccs",
)
TOPOLOGY_FORBIDDEN_STAGE_PATTERNS = (
    r"wag",
    r"internal_energy",
    r"stochastic",
    r"mfrr",
    r"cvar",
    r"order_book",
    r"deadline",
)
TOPOLOGY_FORBIDDEN_COLUMN_PATTERNS = (
    r"(?:^|_)capacity(?:_|$)",
    r"(?:^|_)coefficient(?:_|$)",
    r"(?:^|_)cost(?:_|$)",
    r"(?:^|_)emission(?:_|$)",
    r"(?:^|_)tariff(?:_|$)",
    r"(?:^|_)bid_quantity(?:_|$)",
    r"(?:^|_)objective_value(?:_|$)",
)
FORBIDDEN_HORIZON_PATTERNS = (
    r"(?:^|[^a-z0-9])d-only(?:[^a-z0-9]|$)",
    r"(?:^|[^a-z0-9])d_only(?:[^a-z0-9]|$)",
    r"(?:^|[^a-z0-9])d\+4(?:[^a-z0-9]|$)",
    r"(?:^|[^a-z0-9])d_plus_4(?:[^a-z0-9]|$)",
)


@dataclass(frozen=True)
class TopologyTableBundle:
    root: Path
    tables: dict[str, pd.DataFrame]

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: int(len(frame)) for name, frame in self.tables.items()}


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _load_bundle(root: str | Path, file_specs: dict[str, list[str]]) -> TopologyTableBundle:
    base = Path(root).resolve()
    tables: dict[str, pd.DataFrame] = {}
    for filename, required_columns in file_specs.items():
        path = base / filename
        frame = _read_csv(path)
        missing = [column for column in required_columns if column not in frame.columns]
        if missing:
            raise ValueError(f"{filename} is missing required columns: {missing}")
        if frame.empty:
            raise ValueError(f"{filename} must contain at least one topology row.")
        for column in required_columns:
            if column == "notes":
                continue
            if frame[column].astype(str).str.strip().eq("").any():
                raise ValueError(f"{filename} contains empty values in required column {column}.")
        tables[filename] = frame
    return TopologyTableBundle(root=base, tables=tables)


def load_topology_skeleton(review_root: str | Path) -> TopologyTableBundle:
    return _load_bundle(Path(review_root).resolve() / TOPOLOGY_SKELETON_DIRNAME, TOPOLOGY_SKELETON_FILE_SPECS)


def _split_multi_value_field(raw_value: str) -> list[str]:
    return [token.strip() for token in str(raw_value).split(";") if token.strip()]


def validate_topology_skeleton(topology_bundle: TopologyTableBundle) -> dict[str, Any]:
    tables = topology_bundle.tables
    configurations = tables["configurations.csv"]
    routes = tables["routes.csv"]
    process_units = tables["process_units.csv"]
    carriers = tables["carriers.csv"]
    stores = tables["stores.csv"]
    topology_arcs = tables["topology_arcs.csv"]
    inventory_policy = tables["inventory_policy.csv"]

    forbidden_column_pattern = "|".join(TOPOLOGY_FORBIDDEN_COLUMN_PATTERNS)
    horizon_pattern = "|".join(FORBIDDEN_HORIZON_PATTERNS)
    forbidden_scope_pattern = "|".join(TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS)
    forbidden_stage_pattern = "|".join(TOPOLOGY_FORBIDDEN_STAGE_PATTERNS)

    for filename, frame in tables.items():
        lowered_columns = {column.lower() for column in frame.columns}
        if any(re.search(forbidden_column_pattern, column) for column in lowered_columns):
            raise ValueError(f"{filename} contains forbidden column names for numerical or later-stage content.")
        if (~frame["executable_status"].astype(str).str.strip().str.lower().isin(TOPOLOGY_ALLOWED_EXECUTABLE_STATUSES)).any():
            raise ValueError(f"{filename} must keep every row non_executable.")
        if (~frame["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"{filename} must keep thesis_usability=false for every row.")
        if (~frame["approval_status"].astype(str).str.strip().str.lower().isin(TOPOLOGY_ALLOWED_APPROVAL_STATUSES)).any():
            raise ValueError(f"{filename} contains approval_status values outside the allowed structural candidate set.")
        if (~frame["numerical_status"].astype(str).str.strip().str.lower().isin(TOPOLOGY_ALLOWED_NUMERICAL_STATUSES)).any():
            raise ValueError(f"{filename} contains numerical_status values outside the allowed non-executable set.")

        scan = frame.astype(str).agg(" ".join, axis=1).str.lower()
        if scan.str.contains(horizon_pattern, regex=True).any():
            raise ValueError(f"{filename} must not introduce D-only/D+4 comparison categories.")

    configuration_ids = set(configurations["configuration_id"].astype(str).str.strip())
    if configuration_ids != TOPOLOGY_REQUIRED_CONFIGURATION_IDS:
        missing = sorted(TOPOLOGY_REQUIRED_CONFIGURATION_IDS - configuration_ids)
        extra = sorted(configuration_ids - TOPOLOGY_REQUIRED_CONFIGURATION_IDS)
        raise ValueError(f"configurations.csv must contain only C0 and C1. missing={missing} extra={extra}")
    if (~configurations["main_case_flag"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("configurations.csv must mark C0 and C1 as the only main physical configurations.")
    if configurations["sensitivity_only_flag"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("configurations.csv must not implement C1S as a topology branch.")
    if configurations["optional_later_flag"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("configurations.csv must not implement C2 as a topology branch.")

    route_pairs = {
        (str(row["configuration_id"]).strip(), str(row["route_id"]).strip())
        for row in routes.to_dict(orient="records")
    }
    if route_pairs != TOPOLOGY_REQUIRED_ROUTE_ROWS:
        missing = sorted(TOPOLOGY_REQUIRED_ROUTE_ROWS - route_pairs)
        extra = sorted(route_pairs - TOPOLOGY_REQUIRED_ROUTE_ROWS)
        raise ValueError(f"routes.csv must contain only the frozen C0/C1 route rows. missing={missing} extra={extra}")
    if (~routes["included_in_main_case"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("routes.csv must mark the frozen C0/C1 routes as included in the main structural set.")
    route_scan = routes[["route_id", "route_name", "notes"]].astype(str).agg(" ".join, axis=1).str.lower()
    if route_scan.str.contains(forbidden_scope_pattern, regex=True).any():
        raise ValueError("routes.csv contains blocked pathway or technology scope.")
    if route_scan.str.contains(forbidden_stage_pattern, regex=True).any():
        raise ValueError("routes.csv contains later-stage scope that does not belong in S2 topology.")

    valid_route_ids = set(routes["route_id"].astype(str).str.strip())
    for filename, frame, route_field in (
        ("process_units.csv", process_units, "route_id"),
        ("stores.csv", stores, "route_id"),
        ("topology_arcs.csv", topology_arcs, "route_id"),
    ):
        for raw_value in frame[route_field]:
            route_tokens = _split_multi_value_field(raw_value)
            if not set(route_tokens).issubset(valid_route_ids):
                raise ValueError(f"{filename} references route_id values outside the frozen route set: {raw_value}")

    if (~process_units["configuration_id"].astype(str).str.strip().isin(TOPOLOGY_REQUIRED_CONFIGURATION_IDS)).any():
        raise ValueError("process_units.csv references configurations outside C0/C1.")
    if (~process_units["included_in_s2"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("process_units.csv must keep every listed process unit in S2 structural scope.")
    if process_units["process_unit_name"].astype(str).str.lower().str.contains(forbidden_scope_pattern, regex=True).any():
        raise ValueError("process_units.csv contains blocked pathway names.")
    if process_units["notes"].astype(str).str.lower().str.contains(forbidden_stage_pattern, regex=True).any():
        raise ValueError("process_units.csv contains later-stage scope in notes.")

    if (~carriers["s2_in_scope"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("carriers.csv must keep every listed carrier in S2 structural scope.")
    if carriers["material_or_energy"].astype(str).str.strip().str.lower().ne("material").any():
        raise ValueError("carriers.csv must stay material-only for the S2 topology registry.")
    carrier_ids = set(carriers["carrier_id"].astype(str).str.strip())
    if not TOPOLOGY_REQUIRED_EXTERNAL_BOUNDARY_CARRIERS.issubset(carrier_ids):
        missing = sorted(TOPOLOGY_REQUIRED_EXTERNAL_BOUNDARY_CARRIERS - carrier_ids)
        raise ValueError(f"carriers.csv is missing required external supply boundary carriers: {missing}")
    boundary_rows = carriers["carrier_id"].astype(str).str.strip().isin(TOPOLOGY_REQUIRED_EXTERNAL_BOUNDARY_CARRIERS)
    if (~carriers.loc[boundary_rows, "external_supply_flag"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("External raw-material boundary carriers must be marked external_supply_flag=true.")
    if (~carriers.loc[boundary_rows, "internal_carrier_flag"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("External raw-material boundary carriers must not be marked as internal carriers.")

    if (~stores["configuration_id"].astype(str).str.strip().isin(TOPOLOGY_REQUIRED_CONFIGURATION_IDS)).any():
        raise ValueError("stores.csv references configurations outside C0/C1.")
    if (~stores["carrier_id"].astype(str).str.strip().isin(carrier_ids)).any():
        raise ValueError("stores.csv references carriers outside carriers.csv.")
    if (~stores["bounded_store_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("stores.csv must keep every internal store structurally bounded.")
    if stores["store_name"].astype(str).str.lower().str.contains(r"coke|sinter|pellet", regex=True).any():
        raise ValueError("stores.csv must not create coke, sinter, or pellet internal buffers in the main topology registry.")
    if stores["notes"].astype(str).str.lower().str.contains("unbounded", regex=False).any():
        raise ValueError("stores.csv must not describe any internal store as unbounded.")

    process_unit_ids = set(process_units["process_unit_id"].astype(str).str.strip())
    store_ids = set(stores["store_id"].astype(str).str.strip())
    valid_nodes = process_unit_ids | store_ids
    if (~topology_arcs["configuration_id"].astype(str).str.strip().isin(TOPOLOGY_REQUIRED_CONFIGURATION_IDS)).any():
        raise ValueError("topology_arcs.csv references configurations outside C0/C1.")
    if (~topology_arcs["carrier_id"].astype(str).str.strip().isin(carrier_ids)).any():
        raise ValueError("topology_arcs.csv references carriers outside carriers.csv.")
    if (~topology_arcs["from_node"].astype(str).str.strip().isin(valid_nodes)).any():
        raise ValueError("topology_arcs.csv contains from_node values outside process_units.csv and stores.csv.")
    if (~topology_arcs["to_node"].astype(str).str.strip().isin(valid_nodes)).any():
        raise ValueError("topology_arcs.csv contains to_node values outside process_units.csv and stores.csv.")
    arc_scan = topology_arcs.astype(str).agg(" ".join, axis=1).str.lower()
    if arc_scan.str.contains(forbidden_scope_pattern, regex=True).any():
        raise ValueError("topology_arcs.csv contains blocked pathway scope.")
    if arc_scan.str.contains(forbidden_stage_pattern, regex=True).any():
        raise ValueError("topology_arcs.csv contains later-stage scope.")

    if inventory_policy["policy_id"].astype(str).str.contains("CYC50", case=False, regex=False).sum() == 0:
        raise ValueError("inventory_policy.csv must include at least one CYC50 policy candidate row.")
    cyc50_rows = inventory_policy["endpoint_policy"].astype(str).str.contains("CYC50", case=False, regex=False)
    if not cyc50_rows.any():
        raise ValueError("inventory_policy.csv must record CYC50 as a policy candidate.")
    if inventory_policy.loc[cyc50_rows, "numerical_status"].astype(str).str.strip().str.lower().ne("no_numerical_value").any():
        raise ValueError("CYC50 policy rows must remain non-numerical structural candidates.")
    if inventory_policy.loc[cyc50_rows, "executable_status"].astype(str).str.strip().str.lower().ne("non_executable").any():
        raise ValueError("CYC50 policy rows must remain non_executable.")

    return {
        "topology_skeleton_files_checked": len(TOPOLOGY_SKELETON_FILE_SPECS),
        "topology_configuration_rows_checked": int(len(configurations)),
        "topology_route_rows_checked": int(len(routes)),
        "topology_process_unit_rows_checked": int(len(process_units)),
        "topology_carrier_rows_checked": int(len(carriers)),
        "topology_store_rows_checked": int(len(stores)),
        "topology_arc_rows_checked": int(len(topology_arcs)),
        "topology_inventory_policy_rows_checked": int(len(inventory_policy)),
        "topology_loader_warnings": [],
    }
