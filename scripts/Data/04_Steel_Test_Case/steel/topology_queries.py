from __future__ import annotations

from dataclasses import dataclass, fields
import heapq
import re

from .topology_loader import (
    FORBIDDEN_HORIZON_PATTERNS,
    TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS,
    TOPOLOGY_FORBIDDEN_STAGE_PATTERNS,
    TOPOLOGY_REQUIRED_CONFIGURATION_IDS,
)
from .topology_objects import (
    SteelTopology,
    TopologyArc,
    TopologyCarrier,
    TopologyConfiguration,
    TopologyProcessUnit,
    TopologyRoute,
    TopologyStore,
)


def _scan_forbidden_scope(values: list[str], context: str) -> None:
    scope_pattern = "|".join(TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS)
    stage_pattern = "|".join(TOPOLOGY_FORBIDDEN_STAGE_PATTERNS)
    horizon_pattern = "|".join(FORBIDDEN_HORIZON_PATTERNS)
    scan = " ".join(value.lower() for value in values if value)
    if re.search(scope_pattern, scan):
        raise ValueError(f"{context} contains blocked pathway scope.")
    if re.search(stage_pattern, scan):
        raise ValueError(f"{context} contains later-stage scope.")
    if re.search(horizon_pattern, scan):
        raise ValueError(f"{context} contains forbidden D-only/D+4 scope.")


@dataclass(frozen=True)
class RouteTopologyView:
    configuration: TopologyConfiguration
    route: TopologyRoute
    process_units: tuple[TopologyProcessUnit, ...]
    stores: tuple[TopologyStore, ...]
    arcs: tuple[TopologyArc, ...]
    carriers: tuple[TopologyCarrier, ...]
    process_chain_node_ids: tuple[str, ...]
    source_like_node_ids: tuple[str, ...]
    sink_like_node_ids: tuple[str, ...]
    buffer_store_node_ids: tuple[str, ...]
    disconnected_node_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def summary_counts(self) -> dict[str, int]:
        return {
            "process_units": len(self.process_units),
            "stores": len(self.stores),
            "arcs": len(self.arcs),
            "carriers": len(self.carriers),
            "source_like_nodes": len(self.source_like_node_ids),
            "sink_like_nodes": len(self.sink_like_node_ids),
            "buffer_store_nodes": len(self.buffer_store_node_ids),
            "disconnected_nodes": len(self.disconnected_node_ids),
        }


@dataclass(frozen=True)
class ConfigurationTopologyView:
    configuration: TopologyConfiguration
    routes: tuple[TopologyRoute, ...]
    process_units: tuple[TopologyProcessUnit, ...]
    stores: tuple[TopologyStore, ...]
    arcs: tuple[TopologyArc, ...]
    carriers: tuple[TopologyCarrier, ...]
    source_like_node_ids: tuple[str, ...]
    sink_like_node_ids: tuple[str, ...]
    buffer_store_node_ids: tuple[str, ...]
    shared_downstream_node_ids: tuple[str, ...]
    external_supply_boundary_carrier_ids: tuple[str, ...]
    internal_metallic_carrier_ids: tuple[str, ...]
    disconnected_node_ids: tuple[str, ...]
    route_views: tuple[RouteTopologyView, ...]
    warnings: tuple[str, ...] = ()

    def summary_counts(self) -> dict[str, int]:
        return {
            "routes": len(self.routes),
            "process_units": len(self.process_units),
            "stores": len(self.stores),
            "arcs": len(self.arcs),
            "carriers": len(self.carriers),
            "source_like_nodes": len(self.source_like_node_ids),
            "sink_like_nodes": len(self.sink_like_node_ids),
            "buffer_store_nodes": len(self.buffer_store_node_ids),
            "shared_downstream_nodes": len(self.shared_downstream_node_ids),
            "disconnected_nodes": len(self.disconnected_node_ids),
        }


@dataclass(frozen=True)
class TopologyAssemblyBundle:
    topology: SteelTopology
    configuration_views: dict[str, ConfigurationTopologyView]
    route_views: dict[str, RouteTopologyView]
    warnings: tuple[str, ...] = ()


def incoming_arcs_by_node(
    topology: SteelTopology,
    configuration_id: str,
    node_id: str,
    route_id: str | None = None,
) -> list[TopologyArc]:
    return sorted(
        [
            arc
            for arc in topology.list_arcs(configuration_id=configuration_id, route_id=route_id)
            if arc.to_node == node_id
        ],
        key=lambda arc: arc.arc_id,
    )


def outgoing_arcs_by_node(
    topology: SteelTopology,
    configuration_id: str,
    node_id: str,
    route_id: str | None = None,
) -> list[TopologyArc]:
    return sorted(
        [
            arc
            for arc in topology.list_arcs(configuration_id=configuration_id, route_id=route_id)
            if arc.from_node == node_id
        ],
        key=lambda arc: arc.arc_id,
    )


def list_process_chain_by_route(topology: SteelTopology, configuration_id: str, route_id: str) -> list[str]:
    nodes = topology.list_nodes(configuration_id=configuration_id, route_id=route_id)
    arcs = topology.list_arcs(configuration_id=configuration_id, route_id=route_id)
    indegree = {node_id: 0 for node_id in nodes}
    adjacency = {node_id: [] for node_id in nodes}
    for arc in arcs:
        adjacency[arc.from_node].append(arc.to_node)
        indegree[arc.to_node] += 1

    heap = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(heap)
    ordered_nodes: list[str] = []
    while heap:
        node_id = heapq.heappop(heap)
        ordered_nodes.append(node_id)
        for next_node in sorted(adjacency[node_id]):
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                heapq.heappush(heap, next_node)

    remaining = sorted(node_id for node_id, degree in indegree.items() if degree > 0)
    return ordered_nodes + remaining


def identify_buffer_store_nodes(
    topology: SteelTopology,
    configuration_id: str,
    route_id: str | None = None,
) -> list[str]:
    return [
        store.store_id
        for store in topology.list_stores(configuration_id=configuration_id, route_id=route_id)
    ]


def identify_shared_downstream_nodes(topology: SteelTopology, configuration_id: str) -> list[str]:
    shared_nodes: set[str] = set()
    for process_unit in topology.list_process_units(configuration_id=configuration_id):
        if len(process_unit.route_ids) > 1 and "shared" in process_unit.continuity_class.lower():
            shared_nodes.add(process_unit.process_unit_id)
    for store in topology.list_stores(configuration_id=configuration_id):
        if len(store.route_ids) > 1:
            shared_nodes.add(store.store_id)
    return sorted(shared_nodes)


def identify_external_supply_boundary_carriers(topology: SteelTopology) -> list[str]:
    return sorted(
        carrier.carrier_id
        for carrier in topology.list_carriers_in_scope()
        if carrier.external_supply_flag
    )


def identify_internal_metallic_carriers(topology: SteelTopology) -> list[str]:
    return sorted(
        carrier.carrier_id
        for carrier in topology.list_carriers_in_scope()
        if carrier.internal_carrier_flag and carrier.carrier_class in {"intermediate_metal", "semi_finished_metal"}
    )


def stores_with_endpoint_policies(topology: SteelTopology, configuration_id: str) -> list[dict[str, str]]:
    return [
        {
            "store_id": store.store_id,
            "carrier_id": store.carrier_id,
            "store_class": store.store_class,
            "endpoint_policy": store.endpoint_policy,
            "initial_inventory_policy": store.initial_inventory_policy,
        }
        for store in topology.list_stores(configuration_id=configuration_id)
    ]


def detect_disconnected_nodes(
    topology: SteelTopology,
    configuration_id: str,
    route_id: str | None = None,
) -> list[str]:
    nodes = topology.list_nodes(configuration_id=configuration_id, route_id=route_id)
    disconnected = []
    for node_id in nodes:
        if not incoming_arcs_by_node(topology, configuration_id, node_id, route_id=route_id) and not outgoing_arcs_by_node(
            topology, configuration_id, node_id, route_id=route_id
        ):
            disconnected.append(node_id)
    return sorted(disconnected)


def route_level_sources_and_sinks(topology: SteelTopology, configuration_id: str, route_id: str) -> dict[str, tuple[str, ...]]:
    return {
        "source_like_node_ids": tuple(topology.source_like_nodes(configuration_id=configuration_id, route_id=route_id)),
        "sink_like_node_ids": tuple(topology.sink_like_nodes(configuration_id=configuration_id, route_id=route_id)),
    }


def assemble_route_view(topology: SteelTopology, configuration_id: str, route_id: str) -> RouteTopologyView:
    configuration = topology.get_configuration(configuration_id)
    route = topology.routes[route_id]
    if route.configuration_id != configuration_id:
        raise ValueError(f"Route {route_id} does not belong to configuration {configuration_id}.")

    process_units = tuple(topology.list_process_units(configuration_id=configuration_id, route_id=route_id))
    stores = tuple(topology.list_stores(configuration_id=configuration_id, route_id=route_id))
    arcs = tuple(topology.list_arcs(configuration_id=configuration_id, route_id=route_id))
    carrier_ids = sorted({arc.carrier_id for arc in arcs} | {store.carrier_id for store in stores})
    carriers = tuple(topology.carriers[carrier_id] for carrier_id in carrier_ids)
    process_chain_node_ids = tuple(list_process_chain_by_route(topology, configuration_id, route_id))
    source_like_node_ids = tuple(topology.source_like_nodes(configuration_id=configuration_id, route_id=route_id))
    sink_like_node_ids = tuple(topology.sink_like_nodes(configuration_id=configuration_id, route_id=route_id))
    buffer_store_node_ids = tuple(identify_buffer_store_nodes(topology, configuration_id, route_id=route_id))
    disconnected_node_ids = tuple(detect_disconnected_nodes(topology, configuration_id, route_id=route_id))

    _validate_structural_only_view(
        [configuration, route, *process_units, *stores, *arcs, *carriers],
        context=f"RouteTopologyView[{configuration_id}:{route_id}]",
    )

    return RouteTopologyView(
        configuration=configuration,
        route=route,
        process_units=process_units,
        stores=stores,
        arcs=arcs,
        carriers=carriers,
        process_chain_node_ids=process_chain_node_ids,
        source_like_node_ids=source_like_node_ids,
        sink_like_node_ids=sink_like_node_ids,
        buffer_store_node_ids=buffer_store_node_ids,
        disconnected_node_ids=disconnected_node_ids,
        warnings=(),
    )


def assemble_topology_view(topology: SteelTopology, configuration_id: str) -> ConfigurationTopologyView:
    configuration = topology.get_configuration(configuration_id)
    routes = tuple(topology.list_routes(configuration_id=configuration_id))
    process_units = tuple(topology.list_process_units(configuration_id=configuration_id))
    stores = tuple(topology.list_stores(configuration_id=configuration_id))
    arcs = tuple(topology.list_arcs(configuration_id=configuration_id))
    carrier_ids = sorted({arc.carrier_id for arc in arcs} | {store.carrier_id for store in stores})
    carriers = tuple(topology.carriers[carrier_id] for carrier_id in carrier_ids)
    route_views = tuple(assemble_route_view(topology, configuration_id, route.route_id) for route in routes)
    source_like_node_ids = tuple(topology.source_like_nodes(configuration_id=configuration_id))
    sink_like_node_ids = tuple(topology.sink_like_nodes(configuration_id=configuration_id))
    buffer_store_node_ids = tuple(identify_buffer_store_nodes(topology, configuration_id))
    shared_downstream_node_ids = tuple(identify_shared_downstream_nodes(topology, configuration_id))
    external_supply_boundary_carrier_ids = tuple(
        carrier_id
        for carrier_id in identify_external_supply_boundary_carriers(topology)
        if carrier_id in {carrier.carrier_id for carrier in carriers}
    )
    internal_metallic_carrier_ids = tuple(
        carrier_id
        for carrier_id in identify_internal_metallic_carriers(topology)
        if carrier_id in {carrier.carrier_id for carrier in carriers}
    )
    disconnected_node_ids = tuple(detect_disconnected_nodes(topology, configuration_id))

    _validate_structural_only_view(
        [configuration, *routes, *process_units, *stores, *arcs, *carriers],
        context=f"ConfigurationTopologyView[{configuration_id}]",
    )

    return ConfigurationTopologyView(
        configuration=configuration,
        routes=routes,
        process_units=process_units,
        stores=stores,
        arcs=arcs,
        carriers=carriers,
        source_like_node_ids=source_like_node_ids,
        sink_like_node_ids=sink_like_node_ids,
        buffer_store_node_ids=buffer_store_node_ids,
        shared_downstream_node_ids=shared_downstream_node_ids,
        external_supply_boundary_carrier_ids=external_supply_boundary_carrier_ids,
        internal_metallic_carrier_ids=internal_metallic_carrier_ids,
        disconnected_node_ids=disconnected_node_ids,
        route_views=route_views,
        warnings=(),
    )


def assemble_topology_views(topology: SteelTopology) -> TopologyAssemblyBundle:
    configuration_ids = set(topology.configurations)
    if configuration_ids != TOPOLOGY_REQUIRED_CONFIGURATION_IDS:
        raise ValueError("TopologyAssemblyBundle must only expose C0 and C1 configuration views.")

    configuration_views = {
        configuration_id: assemble_topology_view(topology, configuration_id)
        for configuration_id in sorted(configuration_ids)
    }
    route_views = {
        route_view.route.route_id: route_view
        for configuration_view in configuration_views.values()
        for route_view in configuration_view.route_views
    }
    return TopologyAssemblyBundle(
        topology=topology,
        configuration_views=configuration_views,
        route_views=route_views,
        warnings=(),
    )


def _validate_structural_only_view(objects: list[object], *, context: str) -> None:
    banned_field_tokens = {"capacity", "yield", "coefficient", "cost", "emission", "tariff", "bid_quantity", "objective_value"}
    text_values: list[str] = []
    for item in objects:
        for field in fields(item):
            if field.name in banned_field_tokens:
                raise ValueError(f"{context} exposes forbidden numerical field {field.name}.")
            value = getattr(item, field.name)
            text_values.append(str(value))
        if getattr(item, "executable_status", "non_executable") != "non_executable":
            raise ValueError(f"{context} contains executable rows.")
        if getattr(item, "thesis_usability", False):
            raise ValueError(f"{context} contains thesis-usable rows.")
        approval_status = str(getattr(item, "approval_status", ""))
        if "approved" in approval_status.lower() and approval_status.lower() != "not_approved":
            raise ValueError(f"{context} contains approved rows.")
    _scan_forbidden_scope(text_values, context)
