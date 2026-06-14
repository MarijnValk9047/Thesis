from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
import re

from .topology_loader import (
    TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS,
    TOPOLOGY_FORBIDDEN_STAGE_PATTERNS,
    TOPOLOGY_REQUIRED_CONFIGURATION_IDS,
    FORBIDDEN_HORIZON_PATTERNS,
    TopologyTableBundle,
    load_topology_skeleton,
    validate_topology_skeleton,
)


def _parse_bool(raw_value: str) -> bool:
    value = str(raw_value).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"Expected boolean-like string, got {raw_value!r}")


def _split_tokens(raw_value: str) -> tuple[str, ...]:
    return tuple(token.strip() for token in str(raw_value).split(";") if token.strip())


def _dedupe_ids(items: list[Any], attr_name: str, collection_name: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        identifier = getattr(item, attr_name)
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    if duplicates:
        raise ValueError(f"{collection_name} contains duplicate IDs: {sorted(duplicates)}")


def _validate_scope_strings(values: list[str], context: str) -> None:
    forbidden_scope_pattern = "|".join(TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS)
    forbidden_stage_pattern = "|".join(TOPOLOGY_FORBIDDEN_STAGE_PATTERNS)
    horizon_pattern = "|".join(FORBIDDEN_HORIZON_PATTERNS)
    scan = " ".join(value.lower() for value in values if value)
    if re.search(forbidden_scope_pattern, scan):
        raise ValueError(f"{context} contains blocked pathway scope.")
    if re.search(forbidden_stage_pattern, scan):
        raise ValueError(f"{context} contains later-stage scope.")
    if re.search(horizon_pattern, scan):
        raise ValueError(f"{context} contains forbidden D-only/D+4 scope.")


@dataclass(frozen=True)
class TopologyConfiguration:
    configuration_id: str
    configuration_name: str
    role: str
    main_case_flag: bool
    sensitivity_only_flag: bool
    optional_later_flag: bool
    topology_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    notes: str


@dataclass(frozen=True)
class TopologyRoute:
    route_id: str
    configuration_id: str
    route_name: str
    route_role: str
    included_in_main_case: bool
    structural_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    source_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class TopologyProcessUnit:
    process_unit_id: str
    configuration_id: str
    route_ids: tuple[str, ...]
    process_unit_name: str
    process_class: str
    continuity_class: str
    structural_role: str
    included_in_s2: bool
    postponed_to_stage: str
    structural_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    source_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class TopologyCarrier:
    carrier_id: str
    carrier_name: str
    carrier_class: str
    material_or_energy: str
    s2_in_scope: bool
    external_supply_flag: bool
    internal_carrier_flag: bool
    structural_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    source_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class TopologyStore:
    store_id: str
    configuration_id: str
    route_ids: tuple[str, ...]
    carrier_id: str
    store_name: str
    store_class: str
    flexibility_role: str
    endpoint_policy: str
    initial_inventory_policy: str
    bounded_store_required: bool
    structural_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    source_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class TopologyArc:
    arc_id: str
    configuration_id: str
    route_ids: tuple[str, ...]
    from_node: str
    to_node: str
    carrier_id: str
    arc_role: str
    structural_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    source_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class TopologyInventoryPolicy:
    policy_id: str
    store_class: str
    endpoint_policy: str
    initial_inventory_policy: str
    terminal_inventory_policy: str
    allowed_use: str
    forbidden_use: str
    structural_status: str
    numerical_status: str
    executable_status: str
    thesis_usability: bool
    approval_status: str
    source_ids: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class SteelTopology:
    configurations: dict[str, TopologyConfiguration]
    routes: dict[str, TopologyRoute]
    process_units: dict[str, TopologyProcessUnit]
    carriers: dict[str, TopologyCarrier]
    stores: dict[str, TopologyStore]
    arcs: dict[str, TopologyArc]
    inventory_policies: dict[str, TopologyInventoryPolicy]
    warnings: tuple[str, ...] = ()

    def get_configuration(self, configuration_id: str) -> TopologyConfiguration:
        return self.configurations[configuration_id]

    def list_routes(self, configuration_id: str | None = None) -> list[TopologyRoute]:
        routes = list(self.routes.values())
        if configuration_id is not None:
            routes = [route for route in routes if route.configuration_id == configuration_id]
        return sorted(routes, key=lambda route: route.route_id)

    def list_process_units(
        self,
        configuration_id: str | None = None,
        route_id: str | None = None,
    ) -> list[TopologyProcessUnit]:
        units = list(self.process_units.values())
        if configuration_id is not None:
            units = [unit for unit in units if unit.configuration_id == configuration_id]
        if route_id is not None:
            units = [unit for unit in units if route_id in unit.route_ids]
        return sorted(units, key=lambda unit: unit.process_unit_id)

    def list_stores(self, configuration_id: str | None = None, route_id: str | None = None) -> list[TopologyStore]:
        stores = list(self.stores.values())
        if configuration_id is not None:
            stores = [store for store in stores if store.configuration_id == configuration_id]
        if route_id is not None:
            stores = [store for store in stores if route_id in store.route_ids]
        return sorted(stores, key=lambda store: store.store_id)

    def list_arcs(self, configuration_id: str | None = None, route_id: str | None = None) -> list[TopologyArc]:
        arcs = list(self.arcs.values())
        if configuration_id is not None:
            arcs = [arc for arc in arcs if arc.configuration_id == configuration_id]
        if route_id is not None:
            arcs = [arc for arc in arcs if route_id in arc.route_ids]
        return sorted(arcs, key=lambda arc: arc.arc_id)

    def list_carriers_in_scope(self) -> list[TopologyCarrier]:
        return sorted(
            [carrier for carrier in self.carriers.values() if carrier.s2_in_scope],
            key=lambda carrier: carrier.carrier_id,
        )

    def list_inventory_policies(self, store_class: str | None = None) -> list[TopologyInventoryPolicy]:
        policies = list(self.inventory_policies.values())
        if store_class is not None:
            policies = [policy for policy in policies if policy.store_class == store_class]
        return sorted(policies, key=lambda policy: policy.policy_id)

    def list_nodes(self, configuration_id: str, route_id: str | None = None) -> list[str]:
        node_ids = {
            unit.process_unit_id
            for unit in self.list_process_units(configuration_id=configuration_id, route_id=route_id)
        }
        node_ids.update(
            store.store_id
            for store in self.list_stores(configuration_id=configuration_id, route_id=route_id)
        )
        return sorted(node_ids)

    def source_like_nodes(self, configuration_id: str, route_id: str | None = None) -> list[str]:
        return self._boundary_nodes(configuration_id=configuration_id, route_id=route_id, direction="source")

    def sink_like_nodes(self, configuration_id: str, route_id: str | None = None) -> list[str]:
        return self._boundary_nodes(configuration_id=configuration_id, route_id=route_id, direction="sink")

    def _boundary_nodes(self, configuration_id: str, route_id: str | None, direction: str) -> list[str]:
        nodes = self.list_nodes(configuration_id=configuration_id, route_id=route_id)
        arcs = self.list_arcs(configuration_id=configuration_id, route_id=route_id)
        indegree = {node_id: 0 for node_id in nodes}
        outdegree = {node_id: 0 for node_id in nodes}
        for arc in arcs:
            if arc.from_node in outdegree:
                outdegree[arc.from_node] += 1
            if arc.to_node in indegree:
                indegree[arc.to_node] += 1
        if direction == "source":
            return sorted(node_id for node_id in nodes if outdegree[node_id] > 0 and indegree[node_id] == 0)
        if direction == "sink":
            return sorted(node_id for node_id in nodes if indegree[node_id] > 0 and outdegree[node_id] == 0)
        raise ValueError(f"Unknown direction: {direction}")

    def summary_counts(self) -> dict[str, int]:
        return {
            "configurations": len(self.configurations),
            "routes": len(self.routes),
            "process_units": len(self.process_units),
            "carriers": len(self.carriers),
            "stores": len(self.stores),
            "arcs": len(self.arcs),
            "inventory_policies": len(self.inventory_policies),
        }


def build_steel_topology(topology_bundle: TopologyTableBundle, *, validate: bool = True) -> SteelTopology:
    if validate:
        validate_topology_skeleton(topology_bundle)

    configuration_rows = topology_bundle.tables["configurations.csv"].to_dict(orient="records")
    route_rows = topology_bundle.tables["routes.csv"].to_dict(orient="records")
    process_rows = topology_bundle.tables["process_units.csv"].to_dict(orient="records")
    carrier_rows = topology_bundle.tables["carriers.csv"].to_dict(orient="records")
    store_rows = topology_bundle.tables["stores.csv"].to_dict(orient="records")
    arc_rows = topology_bundle.tables["topology_arcs.csv"].to_dict(orient="records")
    policy_rows = topology_bundle.tables["inventory_policy.csv"].to_dict(orient="records")

    configurations = [
        TopologyConfiguration(
            configuration_id=row["configuration_id"],
            configuration_name=row["configuration_name"],
            role=row["role"],
            main_case_flag=_parse_bool(row["main_case_flag"]),
            sensitivity_only_flag=_parse_bool(row["sensitivity_only_flag"]),
            optional_later_flag=_parse_bool(row["optional_later_flag"]),
            topology_status=row["topology_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            notes=row["notes"],
        )
        for row in configuration_rows
    ]
    routes = [
        TopologyRoute(
            route_id=row["route_id"],
            configuration_id=row["configuration_id"],
            route_name=row["route_name"],
            route_role=row["route_role"],
            included_in_main_case=_parse_bool(row["included_in_main_case"]),
            structural_status=row["structural_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            source_ids=_split_tokens(row["source_ids"]),
            notes=row["notes"],
        )
        for row in route_rows
    ]
    process_units = [
        TopologyProcessUnit(
            process_unit_id=row["process_unit_id"],
            configuration_id=row["configuration_id"],
            route_ids=_split_tokens(row["route_id"]),
            process_unit_name=row["process_unit_name"],
            process_class=row["process_class"],
            continuity_class=row["continuity_class"],
            structural_role=row["structural_role"],
            included_in_s2=_parse_bool(row["included_in_s2"]),
            postponed_to_stage=row["postponed_to_stage"],
            structural_status=row["structural_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            source_ids=_split_tokens(row["source_ids"]),
            notes=row["notes"],
        )
        for row in process_rows
    ]
    carriers = [
        TopologyCarrier(
            carrier_id=row["carrier_id"],
            carrier_name=row["carrier_name"],
            carrier_class=row["carrier_class"],
            material_or_energy=row["material_or_energy"],
            s2_in_scope=_parse_bool(row["s2_in_scope"]),
            external_supply_flag=_parse_bool(row["external_supply_flag"]),
            internal_carrier_flag=_parse_bool(row["internal_carrier_flag"]),
            structural_status=row["structural_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            source_ids=_split_tokens(row["source_ids"]),
            notes=row["notes"],
        )
        for row in carrier_rows
    ]
    stores = [
        TopologyStore(
            store_id=row["store_id"],
            configuration_id=row["configuration_id"],
            route_ids=_split_tokens(row["route_id"]),
            carrier_id=row["carrier_id"],
            store_name=row["store_name"],
            store_class=row["store_class"],
            flexibility_role=row["flexibility_role"],
            endpoint_policy=row["endpoint_policy"],
            initial_inventory_policy=row["initial_inventory_policy"],
            bounded_store_required=_parse_bool(row["bounded_store_required"]),
            structural_status=row["structural_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            source_ids=_split_tokens(row["source_ids"]),
            notes=row["notes"],
        )
        for row in store_rows
    ]
    arcs = [
        TopologyArc(
            arc_id=row["arc_id"],
            configuration_id=row["configuration_id"],
            route_ids=_split_tokens(row["route_id"]),
            from_node=row["from_node"],
            to_node=row["to_node"],
            carrier_id=row["carrier_id"],
            arc_role=row["arc_role"],
            structural_status=row["structural_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            source_ids=_split_tokens(row["source_ids"]),
            notes=row["notes"],
        )
        for row in arc_rows
    ]
    inventory_policies = [
        TopologyInventoryPolicy(
            policy_id=row["policy_id"],
            store_class=row["store_class"],
            endpoint_policy=row["endpoint_policy"],
            initial_inventory_policy=row["initial_inventory_policy"],
            terminal_inventory_policy=row["terminal_inventory_policy"],
            allowed_use=row["allowed_use"],
            forbidden_use=row["forbidden_use"],
            structural_status=row["structural_status"],
            numerical_status=row["numerical_status"],
            executable_status=row["executable_status"],
            thesis_usability=_parse_bool(row["thesis_usability"]),
            approval_status=row["approval_status"],
            source_ids=_split_tokens(row["source_ids"]),
            notes=row["notes"],
        )
        for row in policy_rows
    ]

    _dedupe_ids(configurations, "configuration_id", "configurations")
    _dedupe_ids(routes, "route_id", "routes")
    _dedupe_ids(process_units, "process_unit_id", "process_units")
    _dedupe_ids(carriers, "carrier_id", "carriers")
    _dedupe_ids(stores, "store_id", "stores")
    _dedupe_ids(arcs, "arc_id", "arcs")
    _dedupe_ids(inventory_policies, "policy_id", "inventory_policies")

    configuration_map = {item.configuration_id: item for item in configurations}
    route_map = {item.route_id: item for item in routes}
    process_map = {item.process_unit_id: item for item in process_units}
    carrier_map = {item.carrier_id: item for item in carriers}
    store_map = {item.store_id: item for item in stores}
    arc_map = {item.arc_id: item for item in arcs}
    policy_map = {item.policy_id: item for item in inventory_policies}

    if set(configuration_map) != TOPOLOGY_REQUIRED_CONFIGURATION_IDS:
        raise ValueError("SteelTopology must only contain C0 and C1 object branches.")
    for configuration in configuration_map.values():
        if configuration.sensitivity_only_flag or configuration.optional_later_flag:
            raise ValueError("SteelTopology must not create C1S or C2 object branches.")

    for route in route_map.values():
        if route.configuration_id not in configuration_map:
            raise ValueError(f"Route {route.route_id} references unknown configuration {route.configuration_id}.")

    for process_unit in process_map.values():
        if process_unit.configuration_id not in configuration_map:
            raise ValueError(f"Process unit {process_unit.process_unit_id} references unknown configuration.")
        if not process_unit.route_ids:
            raise ValueError(f"Process unit {process_unit.process_unit_id} must reference at least one route.")
        for route_id in process_unit.route_ids:
            route = route_map[route_id]
            if route.configuration_id != process_unit.configuration_id:
                raise ValueError(
                    f"Process unit {process_unit.process_unit_id} mixes configuration {process_unit.configuration_id} with route {route_id}."
                )

    for store in store_map.values():
        if store.configuration_id not in configuration_map:
            raise ValueError(f"Store {store.store_id} references unknown configuration.")
        if store.carrier_id not in carrier_map:
            raise ValueError(f"Store {store.store_id} references unknown carrier {store.carrier_id}.")
        if not store.route_ids:
            raise ValueError(f"Store {store.store_id} must reference at least one route.")
        for route_id in store.route_ids:
            route = route_map[route_id]
            if route.configuration_id != store.configuration_id:
                raise ValueError(f"Store {store.store_id} mixes configuration {store.configuration_id} with route {route_id}.")

    valid_nodes = set(process_map) | set(store_map)
    if len(valid_nodes) != (len(process_map) + len(store_map)):
        raise ValueError("Process-unit IDs and store IDs must not collide in the object layer.")

    for arc in arc_map.values():
        if arc.configuration_id not in configuration_map:
            raise ValueError(f"Arc {arc.arc_id} references unknown configuration.")
        if arc.carrier_id not in carrier_map:
            raise ValueError(f"Arc {arc.arc_id} references unknown carrier {arc.carrier_id}.")
        if arc.from_node not in valid_nodes or arc.to_node not in valid_nodes:
            raise ValueError(f"Arc {arc.arc_id} references unknown endpoints.")
        if not arc.route_ids:
            raise ValueError(f"Arc {arc.arc_id} must reference at least one route.")
        for route_id in arc.route_ids:
            route = route_map[route_id]
            if route.configuration_id != arc.configuration_id:
                raise ValueError(f"Arc {arc.arc_id} mixes configuration {arc.configuration_id} with route {route_id}.")

    object_text_values = []
    for collection in (configurations, routes, process_units, carriers, stores, arcs, inventory_policies):
        for item in collection:
            object_text_values.extend(str(getattr(item, field.name)) for field in fields(item))
            if item.executable_status != "non_executable":
                raise ValueError("Object layer must remain non_executable.")
            if item.thesis_usability:
                raise ValueError("Object layer must remain thesis_usability=false.")
            if "approved" in item.approval_status.lower() and item.approval_status.lower() != "not_approved":
                raise ValueError("Object layer must not contain approved rows.")

    _validate_scope_strings(object_text_values, "SteelTopology object layer")

    return SteelTopology(
        configurations=configuration_map,
        routes=route_map,
        process_units=process_map,
        carriers=carrier_map,
        stores=store_map,
        arcs=arc_map,
        inventory_policies=policy_map,
        warnings=(),
    )


def build_steel_topology_from_registry(review_root: str | Path) -> SteelTopology:
    topology_bundle = load_topology_skeleton(review_root)
    return build_steel_topology(topology_bundle, validate=True)
