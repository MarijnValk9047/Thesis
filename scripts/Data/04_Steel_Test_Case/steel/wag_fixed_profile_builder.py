from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

import pandas as pd
from pyomo.environ import Constraint, Objective, SolverFactory, SolverStatus, TerminationCondition, maximize, minimize, value

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from steel.liquid_steel_smoke_builder import build_liquid_steel_smoke_model
    from steel.model import collect_model_stats
    from steel.wag_diagnostic_inputs import load_selected_wag_inputs, load_wag_demand_coefficients
else:
    from .liquid_steel_smoke_builder import build_liquid_steel_smoke_model
    from .model import collect_model_stats
    from .wag_diagnostic_inputs import load_selected_wag_inputs, load_wag_demand_coefficients


REPO_ROOT = Path(__file__).resolve().parents[4]
C1_CONFIGURATION_ID = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"
C0_CONFIGURATION_ID = "C0_current_BF_BOF_reference"
BF_BOF_LIQUID_PROCESS_ID = "c1_bof_converter"
DRP_EAF_LIQUID_PROCESS_ID = "c1_eaf"
ROUTE_SHARE_TOLERANCE = 0.01
C1_ROUTE_SCENARIOS = {
    "c1_high_drp_eaf": {"bf_bof_share": 0.55, "drp_eaf_share": 0.45},
    "c1_central": {"bf_bof_share": 0.61, "drp_eaf_share": 0.39},
    "c1_low_drp_eaf": {"bf_bof_share": 0.68, "drp_eaf_share": 0.32},
}
C1_PROFILE_FILENAMES = {
    "c1_high_drp_eaf": "c1_high_drp_eaf_same_output_profile_24h_dev.csv",
    "c1_central": "c1_central_same_output_profile_24h_dev.csv",
    "c1_low_drp_eaf": "c1_low_drp_eaf_same_output_profile_24h_dev.csv",
}
DOWNSTREAM_ACCOUNTING_DRIVER_ROWS = (
    (
        "secondary_metallurgy_output_proxy",
        "secondary_metallurgy_output_proxy",
        "Secondary metallurgy accounting driver only; no scheduling flexibility or energy coefficient.",
    ),
    (
        "continuous_casting_liquid_steel_input",
        "continuous_casting_liquid_steel_input",
        "Continuous casting liquid-steel input accounting driver only.",
    ),
    (
        "continuous_casting_slab_output_proxy",
        "continuous_casting_slab_output_proxy",
        "Continuous casting slab-output proxy; no slab inventory or yard optimisation.",
    ),
    (
        "slab_handling_transfer_proxy",
        "slab_handling_transfer_proxy",
        "Slab handling and transfer accounting driver only; no slab-storage behaviour.",
    ),
    (
        "reheating_or_hot_charge_throughput_proxy",
        "reheating_or_hot_charge_throughput_proxy",
        "Reheating or hot-charge boundary accounting driver only; heat coefficient missing.",
    ),
    (
        "hot_strip_mill_throughput_proxy",
        "hot_strip_mill_throughput_proxy",
        "Hot strip mill throughput accounting driver only; no rolling-mill scheduling logic.",
    ),
    (
        "finished_product_boundary_proxy",
        "finished_product_boundary_proxy",
        "Finished-product boundary proxy for accounting continuity only.",
    ),
    (
        "oxygen_demand_auxiliary_driver",
        "oxygen_demand_auxiliary_driver",
        "ASU/oxygen auxiliary accounting driver; no oxygen-electricity coefficient is applied.",
    ),
    (
        "residual_downstream_auxiliary_boundary_driver",
        "residual_downstream_auxiliary_boundary_driver",
        "Residual downstream auxiliary boundary driver; missing coefficients are not hidden zeros.",
    ),
)
C1_ROUTE_ENERGY_INPUT_PATH = (
    REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_c1_route_energy_inputs.csv"
)


def load_c1_route_energy_inputs(path: Path | None = None) -> dict[str, dict[str, str]]:
    input_path = path or C1_ROUTE_ENERGY_INPUT_PATH
    frame = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    selected = frame.loc[
        frame["accepted_for_dev_use"].str.lower().eq("true")
        & frame["eligible_for_s3_0c_loader"].str.lower().eq("true")
    ]
    return {str(row["parameter_name"]): dict(row) for _, row in selected.iterrows()}


def _c1_route_energy_number(inputs: dict[str, dict[str, str]], parameter_name: str) -> float:
    row = inputs.get(parameter_name)
    if row is None or str(row.get("selected_value", "")).strip() == "":
        raise ValueError(f"C1 route-energy input {parameter_name} is not selected.")
    return float(row["selected_value"])


def _available_solver():
    for solver_name in ("gurobi", "appsi_highs", "highs", "cbc", "glpk"):
        solver = SolverFactory(solver_name)
        if solver is not None and solver.available(exception_flag=False):
            return solver_name, solver
    return None, None


def _solve_route_objective(*, sense, solver_name: str, solver) -> dict[str, Any]:
    model = build_liquid_steel_smoke_model(
        configuration_id=C1_CONFIGURATION_ID,
        horizon_hours=24,
        target_variant="feasible_smoke",
        inventory_mode="first_buffers",
    )
    model.minimise_overproduction_objective.deactivate()
    if getattr(model, "diagnostic_maximise_min_inventory_margin_objective", None) is not None:
        model.diagnostic_maximise_min_inventory_margin_objective.deactivate()
    model.s3_route_share_no_overproduction = Constraint(expr=model.overproduction <= 1e-6)
    bf_bof_expr = sum(model.process_activity[BF_BOF_LIQUID_PROCESS_ID, t] for t in model.TIME)
    drp_eaf_expr = sum(model.process_activity[DRP_EAF_LIQUID_PROCESS_ID, t] for t in model.TIME)
    model.s3_route_share_objective = Objective(expr=bf_bof_expr, sense=sense)
    started = time.perf_counter()
    result = solver.solve(model, tee=False)
    runtime = time.perf_counter() - started
    stats = collect_model_stats(model)
    feasible = (
        result.solver.status in {SolverStatus.ok, SolverStatus.warning}
        and result.solver.termination_condition in {TerminationCondition.optimal, TerminationCondition.feasible}
    )
    payload = {
        "solver_name": solver_name,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "runtime_seconds": round(runtime, 6),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "objective": None,
        "bf_bof_output": None,
        "drp_eaf_output": None,
        "total_output": None,
    }
    if feasible:
        payload.update(
            {
                "objective": float(value(model.s3_route_share_objective)),
                "bf_bof_output": float(value(bf_bof_expr)),
                "drp_eaf_output": float(value(drp_eaf_expr)),
                "total_output": float(value(model.horizon_total_liquid_steel_output)),
            }
        )
    return payload


def evaluate_c1_route_share_identifiability() -> dict[str, Any]:
    solver_name, solver = _available_solver()
    if solver is None:
        return {
            "diagnostic_id": "S30B_C1_ROUTE_SHARE_001",
            "configuration_id": C1_CONFIGURATION_ID,
            "target_case": "feasible_smoke_24h_first_buffers_no_overproduction_auxiliary_lp",
            "solver_available": False,
            "route_share_identified": False,
            "blocks_canonical_profile": True,
            "notes": "No LP solver available for C1 route-share identifiability diagnostic.",
        }

    minimum = _solve_route_objective(sense=minimize, solver_name=solver_name, solver=solver)
    maximum = _solve_route_objective(sense=maximize, solver_name=solver_name, solver=solver)
    total = maximum["total_output"] or minimum["total_output"] or 0.0
    min_share = float(minimum["bf_bof_output"]) / total if total else 0.0
    max_share = float(maximum["bf_bof_output"]) / total if total else 0.0
    route_share_identified = (max_share - min_share) <= ROUTE_SHARE_TOLERANCE
    return {
        "diagnostic_id": "S30B_C1_ROUTE_SHARE_001",
        "configuration_id": C1_CONFIGURATION_ID,
        "target_case": "feasible_smoke_24h_first_buffers_no_overproduction_auxiliary_lp",
        "min_bf_bof_output": round(float(minimum["bf_bof_output"]), 6),
        "max_bf_bof_output": round(float(maximum["bf_bof_output"]), 6),
        "min_drp_eaf_output": round(float(maximum["drp_eaf_output"]), 6),
        "max_drp_eaf_output": round(float(minimum["drp_eaf_output"]), 6),
        "total_output": round(float(total), 6),
        "min_bf_bof_share": round(min_share, 8),
        "max_bf_bof_share": round(max_share, 8),
        "identifiability_tolerance": ROUTE_SHARE_TOLERANCE,
        "route_share_identified": str(route_share_identified).lower(),
        "selected_profile_share": "",
        "selection_method": "not_selected_non_identified_auxiliary_lp_interval",
        "source_card_ids": "",
        "candidate_evidence_ids": "",
        "development_only": "true",
        "thesis_usability": "false",
        "blocks_canonical_profile": str(not route_share_identified).lower(),
        "notes": (
            f"solver={solver_name}; min_status={minimum['termination_condition']}; "
            f"max_status={maximum['termination_condition']}; min_runtime={minimum['runtime_seconds']}; "
            f"max_runtime={maximum['runtime_seconds']}; vars={maximum['variable_count']}; "
            f"binaries={maximum['binary_count']}; constraints={maximum['constraint_count']}; "
            "diagnostic objectives only; frozen S2 model file unchanged."
        ),
    }


def route_share_register_frame(row: dict[str, Any]) -> pd.DataFrame:
    columns = [
        "diagnostic_id",
        "configuration_id",
        "target_case",
        "min_bf_bof_output",
        "max_bf_bof_output",
        "min_drp_eaf_output",
        "max_drp_eaf_output",
        "total_output",
        "min_bf_bof_share",
        "max_bf_bof_share",
        "identifiability_tolerance",
        "route_share_identified",
        "selected_profile_share",
        "selection_method",
        "source_card_ids",
        "candidate_evidence_ids",
        "development_only",
        "thesis_usability",
        "blocks_canonical_profile",
        "notes",
    ]
    return pd.DataFrame([{column: row.get(column, "") for column in columns}], columns=columns)


def stable_frame_hash(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _input_surface_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _add_downstream_accounting_driver_rows(
    add_row: Callable[[int, str, str, float, str, str, str], None],
    *,
    time_index: int,
    throughput_value: float,
    activity_prefix: str,
) -> None:
    for activity_suffix, activity_type, notes in DOWNSTREAM_ACCOUNTING_DRIVER_ROWS:
        add_row(
            time_index,
            f"{activity_prefix}_{activity_suffix}",
            activity_type,
            throughput_value,
            "t_per_hour",
            "accounting_driver",
            notes,
        )


def _selected_number(selected, parameter_name: str) -> float:
    matches = [item for item in selected.values() if item.parameter_name == parameter_name and item.configuration_id in {C0_CONFIGURATION_ID, "both"}]
    if len(matches) != 1 or matches[0].selected_number is None:
        raise ValueError(f"Expected one numeric selected input for {parameter_name}.")
    return float(matches[0].selected_number)


def _demand_value(demand, demand_name: str) -> float:
    matches = [item for item in demand.values() if item.demand_name == demand_name and item.configuration_id == C0_CONFIGURATION_ID]
    if len(matches) != 1:
        raise ValueError(f"Expected one C0 demand coefficient for {demand_name}.")
    return float(matches[0].selected_value)


def _solve_c0_profile_model():
    solver_name, solver = _available_solver()
    if solver is None:
        raise RuntimeError("No LP solver available for C0 fixed-profile construction.")
    model = build_liquid_steel_smoke_model(
        configuration_id=C0_CONFIGURATION_ID,
        horizon_hours=24,
        target_variant="feasible_smoke",
        inventory_mode="first_buffers",
    )
    model.s3_c0_profile_no_overproduction = Constraint(expr=model.overproduction <= 1e-6)
    result = solver.solve(model, tee=False)
    feasible = (
        result.solver.status in {SolverStatus.ok, SolverStatus.warning}
        and result.solver.termination_condition in {TerminationCondition.optimal, TerminationCondition.feasible}
    )
    if not feasible:
        raise RuntimeError(f"C0 fixed-profile source model failed: {result.solver.status}/{result.solver.termination_condition}.")
    return solver_name, result, model


def build_c0_fixed_profile_frame() -> pd.DataFrame:
    selected = load_selected_wag_inputs()
    demand = load_wag_demand_coefficients()
    solver_name, result, model = _solve_c0_profile_model()
    source_hash = _input_surface_hash(
        [
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/process_bounds.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/conversion_coefficients.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/production_targets.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/store_capacities.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/initial_inventories.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/terminal_inventory_rules.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input/inventory_endpoint_policies.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_wag_selected_dev_inputs.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_wag_demand_coefficients.csv",
        ]
    )

    coke_rate = _selected_number(selected, "coke_rate_per_t_hot_metal")
    dry_coal_per_coke = _selected_number(selected, "dry_coal_input_per_t_coke")
    coking_capacity_per_hour = _selected_number(selected, "c0_coking_capacity_annual") / 8760.0
    annual_electricity_mwh = _selected_number(selected, "c0_site_electricity_demand_annual_proxy")
    site_electricity_mwh_per_hour = annual_electricity_mwh / 8760.0
    bfg_lhv = _selected_number(selected, "bfg_lhv")
    cog_lhv = _selected_number(selected, "cog_lhv_raw_gas")
    bfg_hot_stove = _demand_value(demand, "c0_bfg_hot_stove_reference_demand")
    cog_hot_stove = _demand_value(demand, "c0_cog_hot_stove_reference_demand")
    cog_pci = _demand_value(demand, "c0_cog_pci_drying_reference_demand")
    underfiring = _demand_value(demand, "c0_coking_underfiring_fuel_demand")
    steam = _demand_value(demand, "c0_coking_plant_steam_demand")

    rows: list[dict[str, object]] = []
    package_id = "S30B_C0_WAG_FIXED_PROFILE_24H_DEV"
    base_timestamp = pd.Timestamp("2026-01-01T00:00:00Z")
    row_counter = 1

    def add_row(time_index: int, activity_id: str, activity_type: str, value_out: float, unit: str, direction: str, notes: str) -> None:
        nonlocal row_counter
        rows.append(
            {
                "profile_package_id": package_id,
                "profile_row_id": f"S30B_C0_PROFILE_ROW_{row_counter:04d}",
                "configuration_id": C0_CONFIGURATION_ID,
                "scenario_label": "fixed_s2_profile",
                "time_index": time_index,
                "timestamp_utc": (base_timestamp + pd.Timedelta(hours=time_index)).isoformat().replace("+00:00", "Z"),
                "timestep_hours": 1.0,
                "s2_activity_id": activity_id,
                "s2_activity_type": activity_type,
                "activity_value": round(float(value_out), 10),
                "activity_unit": unit,
                "activity_direction": direction,
                "source_stage": "S2.11;S2.12;S3.0b-b3",
                "source_artifact_id": "S2_C0_FEASIBLE_SMOKE_FIRST_BUFFERS_PROFILE",
                "source_artifact_path": "data/03_Optimisation/inputs/assets/steel/S2/s2_provisional_dev_input",
                "source_artifact_hash": source_hash,
                "profile_extraction_method": "documented_fixed_profile_extraction",
                "review_status": "reviewed_for_diagnostic",
                "thesis_usability": "false",
                "profile_is_synthetic_or_diagnostic": "true",
                "source_config_id": "C0_feasible_smoke_24h_first_buffers_no_overproduction",
                "route_share_policy": "not_applicable_single_c0_bf_bof_route",
                "inventory_preserving_diagnostic_status": "first_buffer_cyc50_active",
                "annual_average_electricity_proxy": "true" if activity_type == "site_electricity_demand" else "false",
                "profile_content_hash": "",
                "notes": notes,
            }
        )
        row_counter += 1

    for time_index in model.TIME:
        bf_tph = float(value(model.process_activity["c0_blast_furnace", time_index]))
        bof_tph = float(value(model.process_activity["c0_bof_converter", time_index]))
        coke_required = bf_tph * coke_rate
        onsite_coke = min(coke_required, coking_capacity_per_hour)
        external_coke = max(0.0, coke_required - onsite_coke)
        dry_coal = onsite_coke * dry_coal_per_coke
        add_row(time_index, "c0_blast_furnace", "bf_hot_metal_activity", bf_tph, "t_per_hour", "production", "Frozen C0 S2 feasible-smoke BF activity.")
        add_row(time_index, "c0_bof_converter", "bof_liquid_steel_activity", bof_tph, "t_per_hour", "production", "Frozen C0 S2 feasible-smoke BOF activity.")
        add_row(time_index, "c0_coking_proxy", "coking_proxy_onsite_coke", onsite_coke, "tonnes", "production", "Capacity-capped on-site coke proxy; external coke receives no COG credit.")
        add_row(time_index, "c0_external_coke_residual", "coking_proxy_external_coke", external_coke, "tonnes", "consumption", "External/imported coke residual; no on-site COG credit.")
        add_row(time_index, "c0_dry_coal_input", "coking_proxy_dry_coal_input", dry_coal, "tonnes", "consumption", "Dry coal input for on-site coke only.")
        add_row(time_index, "c0_bfg_hot_stove_reference_demand", "mandatory_process_use", bf_tph * bfg_hot_stove * bfg_lhv / 1000.0, "GJ", "consumption", "Mandatory BFG hot-stove reference demand.")
        add_row(time_index, "c0_cog_hot_stove_pci_reference_demand", "mandatory_process_use", bf_tph * (cog_hot_stove + cog_pci) * cog_lhv / 1000.0, "GJ", "consumption", "Mandatory COG hot-stove plus PCI drying reference demand.")
        add_row(time_index, "c0_coking_underfiring_fuel_demand", "mandatory_process_use", onsite_coke * underfiring, "GJ", "consumption", "Coking underfiring fuel demand allocated proportionally to BFG and COG.")
        add_row(time_index, "c0_coking_plant_steam_demand", "steam_boiler_useful_demand", onsite_coke * steam, "GJ_useful", "consumption", "Minimum-known coking-plant steam demand only.")
        add_row(time_index, "c0_site_electricity_demand_annual_average_proxy", "site_electricity_demand", site_electricity_mwh_per_hour, "MWh", "consumption", "Annual-average proxy; not observed hourly truth.")
        _add_downstream_accounting_driver_rows(
            add_row,
            time_index=time_index,
            throughput_value=bof_tph,
            activity_prefix="c0",
        )

    frame = pd.DataFrame(rows)
    content_hash = stable_frame_hash(frame.drop(columns=["profile_content_hash"]))
    frame["profile_content_hash"] = content_hash
    return frame


def _profile_total(frame: pd.DataFrame, activity_type: str) -> float:
    return float(frame.loc[frame["s2_activity_type"].eq(activity_type), "activity_value"].astype(float).sum())


def _c0_profile_path() -> Path:
    return (
        REPO_ROOT
        / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/fixed_profiles/c0_wag_fixed_profile_24h_dev.csv"
    )


def _load_c0_profile_frame(path: Path | None = None) -> pd.DataFrame:
    profile_path = path or _c0_profile_path()
    return pd.read_csv(profile_path, dtype=str, keep_default_na=False)


def _c0_rows_by_time(frame: pd.DataFrame, activity_type: str) -> dict[int, float]:
    rows = frame.loc[frame["s2_activity_type"].eq(activity_type)]
    return {int(row["time_index"]): float(row["activity_value"]) for _, row in rows.iterrows()}


def build_c1_same_output_profile_frame(scenario_id: str, c0_profile_path: Path | None = None) -> pd.DataFrame:
    if scenario_id not in C1_ROUTE_SCENARIOS:
        raise ValueError(f"Unsupported C1 route scenario: {scenario_id}.")
    selected = load_selected_wag_inputs()
    c0_frame = _load_c0_profile_frame(c0_profile_path)
    scenario = C1_ROUTE_SCENARIOS[scenario_id]
    bf_bof_share = scenario["bf_bof_share"]
    drp_eaf_share = scenario["drp_eaf_share"]
    if abs((bf_bof_share + drp_eaf_share) - 1.0) > 1e-9:
        raise ValueError(f"C1 route shares must sum to 1 for {scenario_id}.")

    c0_bf_by_time = _c0_rows_by_time(c0_frame, "bf_hot_metal_activity")
    c0_bof_by_time = _c0_rows_by_time(c0_frame, "bof_liquid_steel_activity")
    if set(c0_bf_by_time) != set(c0_bof_by_time):
        raise ValueError("C0 BF and BOF profile time indices do not align.")

    coke_rate = _selected_number(selected, "coke_rate_per_t_hot_metal")
    dry_coal_per_coke = _selected_number(selected, "dry_coal_input_per_t_coke")
    route_energy = load_c1_route_energy_inputs()
    dri_per_t_steel = _c1_route_energy_number(route_energy, "dri_required_per_t_steel")
    pellets_per_t_steel = _c1_route_energy_number(route_energy, "pellets_required_per_t_steel")
    drp_ng_per_t_steel = _c1_route_energy_number(route_energy, "drp_natural_gas_per_t_steel")
    drp_electricity_per_t_steel = _c1_route_energy_number(route_energy, "drp_electricity_per_t_steel")
    eaf_electricity_per_t_steel = _c1_route_energy_number(route_energy, "eaf_electricity_per_t_steel")
    scrap_per_t_steel = _c1_route_energy_number(route_energy, "scrap_per_t_steel")
    drp_direct_co2_per_t_steel = _c1_route_energy_number(route_energy, "drp_direct_co2_proxy_per_t_steel")
    source_hash = _input_surface_hash(
        [
            _c0_profile_path(),
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_c1_route_share_policy_register.csv",
            REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/s3_wag_selected_dev_inputs.csv",
            C1_ROUTE_ENERGY_INPUT_PATH,
        ]
    )
    total_output = _profile_total(c0_frame, "bof_liquid_steel_activity")
    rows: list[dict[str, object]] = []
    package_id = f"S30C_{scenario_id.upper()}_SAME_OUTPUT_PROFILE_24H_DEV"
    row_counter = 1

    def add_row(time_index: int, activity_id: str, activity_type: str, value_out: float, unit: str, direction: str, notes: str) -> None:
        nonlocal row_counter
        timestamp = pd.Timestamp(str(c0_frame.loc[c0_frame["time_index"].eq(str(time_index)), "timestamp_utc"].iloc[0]))
        rows.append(
            {
                "profile_package_id": package_id,
                "profile_row_id": f"S30C_{scenario_id.upper()}_PROFILE_ROW_{row_counter:04d}",
                "scenario_id": scenario_id,
                "configuration_id": C1_CONFIGURATION_ID,
                "scenario_label": scenario_id,
                "time_index": time_index,
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "timestep_hours": 1.0,
                "s2_activity_id": activity_id,
                "s2_activity_type": activity_type,
                "activity_value": round(float(value_out), 10),
                "activity_unit": unit,
                "activity_direction": direction,
                "total_output_value": round(total_output, 10),
                "total_output_unit": "t_liquid_steel_per_24h",
                "bf_bof_share": bf_bof_share,
                "drp_eaf_share": drp_eaf_share,
                "source_stage": "S3.0c-b",
                "source_artifact_id": "S30C_C1_ROUTE_SCENARIO_POLICY",
                "source_artifact_path": "data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_c1_route_share_policy_register.csv",
                "source_artifact_hash": source_hash,
                "profile_extraction_method": "s3_same_output_route_share_wrapper_not_s2_solver_split",
                "review_status": "development_scenario_policy",
                "thesis_usability": "false",
                "profile_is_synthetic_or_diagnostic": "true",
                "source_config_id": "C1_same_output_s3_route_scenario",
                "route_share_policy": f"S30C_C1_ROUTE_POLICY_{scenario_id}",
                "inventory_preserving_diagnostic_status": "not_applicable_s3_wrapper",
                "annual_average_electricity_proxy": "false",
                "profile_content_hash": "",
                "notes": notes,
            }
        )
        row_counter += 1

    for time_index in sorted(c0_bof_by_time):
        c0_bf = c0_bf_by_time[time_index]
        c0_liquid = c0_bof_by_time[time_index]
        bf_hot_metal = c0_bf * bf_bof_share
        bf_bof_liquid = c0_liquid * bf_bof_share
        drp_eaf_liquid = c0_liquid * drp_eaf_share
        coke_required = bf_hot_metal * coke_rate
        dry_coal = coke_required * dry_coal_per_coke
        dri_required = drp_eaf_liquid * dri_per_t_steel
        pellets_required = drp_eaf_liquid * pellets_per_t_steel
        drp_natural_gas = drp_eaf_liquid * drp_ng_per_t_steel
        drp_electricity = drp_eaf_liquid * drp_electricity_per_t_steel
        eaf_electricity = drp_eaf_liquid * eaf_electricity_per_t_steel
        scrap_required = drp_eaf_liquid * scrap_per_t_steel
        drp_direct_co2 = drp_eaf_liquid * drp_direct_co2_per_t_steel
        component_electricity = drp_electricity + eaf_electricity
        add_row(time_index, "c1_total_liquid_steel_output", "total_liquid_steel_output", c0_liquid, "t_per_hour", "production", "Same-output C1 total liquid-steel basis copied from C0 profile.")
        add_row(time_index, "c1_bf_bof_route_output", "bf_bof_route_liquid_steel_output", bf_bof_liquid, "t_per_hour", "production", "User-selected C1 BF-BOF route-share scenario output.")
        add_row(time_index, "c1_drp_eaf_route_output", "drp_eaf_route_liquid_steel_output", drp_eaf_liquid, "t_per_hour", "production", "User-selected C1 DRP-EAF route-share scenario output.")
        add_row(time_index, "c1_blast_furnace_proxy", "bf_hot_metal_activity", bf_hot_metal, "t_per_hour", "production", "Retained BF hot-metal proxy scaled from C0 by selected BF-BOF share.")
        add_row(time_index, "c1_bof_converter_proxy", "bof_liquid_steel_activity", bf_bof_liquid, "t_per_hour", "production", "Retained BOF liquid-steel proxy scaled by selected BF-BOF share.")
        add_row(time_index, "c1_drp_proxy", "drp_activity_proxy", drp_eaf_liquid, "t_per_hour", "production", "DRP route-output proxy; no gas or electricity coefficient is applied here.")
        add_row(time_index, "c1_eaf_proxy", "eaf_activity_proxy", drp_eaf_liquid, "t_per_hour", "production", "EAF route-output proxy; no electricity coefficient is applied here.")
        add_row(time_index, "c1_retained_coking_proxy", "coking_proxy_onsite_coke", coke_required, "tonnes", "production", "Scenario retained coking proxy follows retained BF route; not a retained capacity claim.")
        add_row(time_index, "c1_dry_coal_input_proxy", "coking_proxy_dry_coal_input", dry_coal, "tonnes", "consumption", "Dry coal proxy for retained route coking only.")
        add_row(time_index, "c1_bfg_generation_driver", "bfg_generation_driver_hot_metal", bf_hot_metal, "t_per_hour", "production", "BFG generation driver follows retained BF hot-metal proxy.")
        add_row(time_index, "c1_bofg_generation_driver", "bofg_generation_driver_liquid_steel", bf_bof_liquid, "t_per_hour", "production", "BOFG generation driver follows retained BOF route proxy.")
        add_row(time_index, "c1_cog_generation_driver", "cog_generation_driver_dry_coal", dry_coal, "tonnes", "consumption", "COG generation driver follows retained coking dry-coal proxy.")
        add_row(time_index, "c1_drp_pellets_input", "drp_pellets_input", pellets_required, "t_per_hour", "consumption", "NG-DRP pellets input derived from Tier B Athanasiadis pellets-to-DRI and EAF yield assumptions.")
        add_row(time_index, "c1_drp_dri_output", "drp_dri_output", dri_required, "t_per_hour", "production", "DRI output required by EAF route; liquid/crude steel proxy basis caveat applies.")
        add_row(time_index, "c1_drp_natural_gas_demand", "drp_natural_gas_demand", drp_natural_gas, "m3_NG_per_hour", "consumption", "NG-DRP natural-gas demand derived from Tier B public-thesis parameter table.")
        add_row(time_index, "c1_drp_electricity_demand", "drp_electricity_demand", drp_electricity, "MWh", "consumption", "NG-DRP electricity demand derived from pellets throughput.")
        add_row(time_index, "c1_eaf_dri_input", "eaf_dri_input", dri_required, "t_per_hour", "consumption", "EAF DRI input derived from DRI-to-crude-steel efficiency.")
        add_row(time_index, "c1_eaf_scrap_input", "eaf_scrap_input", scrap_required, "t_per_hour", "consumption", "EAF scrap input derived from Tier B scrap-per-DRI assumption.")
        add_row(time_index, "c1_eaf_electricity_demand", "eaf_electricity_demand", eaf_electricity, "MWh", "consumption", "EAF electricity demand derived from DRI input.")
        add_row(time_index, "c1_component_electricity_demand_before_wag_offset", "component_electricity_demand_before_wag_offset", component_electricity, "MWh", "consumption", "Component-only C1 electricity boundary: DRP plus EAF electricity demand; no full-site load anchor.")
        add_row(time_index, "c1_drp_direct_co2_proxy", "drp_direct_co2_proxy", drp_direct_co2, "t_CO2_per_hour", "emissions_proxy", "Direct DRP CO2 proxy from Tier B public-thesis parameter table; partial ledger only.")
        _add_downstream_accounting_driver_rows(
            add_row,
            time_index=time_index,
            throughput_value=c0_liquid,
            activity_prefix="c1",
        )

    frame = pd.DataFrame(rows)
    content_hash = stable_frame_hash(frame.drop(columns=["profile_content_hash"]))
    frame["profile_content_hash"] = content_hash
    return frame


def summarise_c1_wag_generation_only(profile: pd.DataFrame) -> dict[str, float | str]:
    selected = load_selected_wag_inputs()
    bfg_intensity = _selected_number(selected, "bfg_generation_per_tonne_hot_metal")
    bfg_lhv = _selected_number(selected, "bfg_lhv")
    bofg_intensity = _selected_number(selected, "bofg_generation_suppressed_combustion")
    bofg_lhv = _selected_number(selected, "bofg_lhv_downstream_gasholder")
    cog_yield = _selected_number(selected, "cog_raw_yield_per_tonne_dry_coal")
    cog_lhv = _selected_number(selected, "cog_lhv_raw_gas")
    bf_hot_metal = _profile_total(profile, "bfg_generation_driver_hot_metal")
    bof_liquid = _profile_total(profile, "bofg_generation_driver_liquid_steel")
    dry_coal = _profile_total(profile, "cog_generation_driver_dry_coal")
    bfg_volume = bf_hot_metal * bfg_intensity
    bofg_volume = bof_liquid * bofg_intensity
    cog_volume = dry_coal * cog_yield
    return {
        "scenario_id": str(profile["scenario_id"].iloc[0]),
        "validation_class": "wag_generation_only",
        "bf_hot_metal_t": bf_hot_metal,
        "bof_liquid_steel_t": bof_liquid,
        "dry_coal_t": dry_coal,
        "bfg_volume_nm3": bfg_volume,
        "bfg_energy_gj": bfg_volume * bfg_lhv / 1000.0,
        "bofg_volume_nm3": bofg_volume,
        "bofg_energy_gj": bofg_volume * bofg_lhv / 1000.0,
        "cog_volume_m3": cog_volume,
        "cog_energy_gj": cog_volume * cog_lhv / 1000.0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate governed S3.0b fixed-profile support artifacts.")
    parser.add_argument("--validate-only", action="store_true", help="Run route-share validation without writing outputs.")
    parser.add_argument("--route-share-register-path", type=Path, default=None, help="Explicit output path for route-share register.")
    parser.add_argument("--c0-profile-output-path", type=Path, default=None, help="Explicit output path for C0 fixed-profile CSV.")
    parser.add_argument("--c1-profile-output-dir", type=Path, default=None, help="Explicit output directory for all C1 same-output scenario profiles.")
    parser.add_argument("--c1-wag-generation-only", action="store_true", help="Print C1 WAG-generation-only summaries for the route profiles.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    row = evaluate_c1_route_share_identifiability()
    frame = route_share_register_frame(row)
    payload = {
        "route_share": row,
        "content_hash": stable_frame_hash(frame),
        "writes_enabled": bool((args.route_share_register_path or args.c0_profile_output_path) and not args.validate_only),
    }
    if args.c0_profile_output_path:
        c0_profile = build_c0_fixed_profile_frame()
        payload["c0_profile"] = {
            "rows": int(len(c0_profile)),
            "content_hash": str(c0_profile["profile_content_hash"].iloc[0]),
            "output_path": str(args.c0_profile_output_path),
            "write_enabled": not args.validate_only,
        }
    if args.c1_profile_output_dir:
        c1_profiles = {}
        c1_generation = {}
        for scenario_id, filename in C1_PROFILE_FILENAMES.items():
            profile = build_c1_same_output_profile_frame(scenario_id)
            c1_profiles[scenario_id] = {
                "rows": int(len(profile)),
                "content_hash": str(profile["profile_content_hash"].iloc[0]),
                "output_path": str(args.c1_profile_output_dir / filename),
                "write_enabled": not args.validate_only,
            }
            if args.c1_wag_generation_only:
                c1_generation[scenario_id] = summarise_c1_wag_generation_only(profile)
        payload["c1_profiles"] = c1_profiles
        if args.c1_wag_generation_only:
            payload["c1_wag_generation_only"] = c1_generation
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.route_share_register_path and not args.validate_only:
        args.route_share_register_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.route_share_register_path, index=False)
    if args.c0_profile_output_path and not args.validate_only:
        args.c0_profile_output_path.parent.mkdir(parents=True, exist_ok=True)
        c0_profile.to_csv(args.c0_profile_output_path, index=False)
    if args.c1_profile_output_dir and not args.validate_only:
        args.c1_profile_output_dir.mkdir(parents=True, exist_ok=True)
        for scenario_id, filename in C1_PROFILE_FILENAMES.items():
            build_c1_same_output_profile_frame(scenario_id).to_csv(args.c1_profile_output_dir / filename, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
