"""Closed-loop rolling steel feasibility plus annual-equivalent anchor reporting.

The runner executes only the first 24-hour block of each solved 168-hour
window, carries its represented material inventories forward, then re-solves.
Annualisation is reporting-only and never feeds the optimisation model.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Mapping

import yaml
from pyomo.environ import Objective, maximize, value

from scripts.optimisation_performance import peak_working_set_mb

from .model import collect_model_stats
from .rolling_production_quota import (
    build_rolling_production_quota_plan,
    build_timestamped_rolling_production_quota_plan,
)
from .s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from .s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger import _ng_factor
from .s4_4c5p_bf_price_series_interface import (
    DPLUS4_SOURCE_CONTRACT_PATH,
    PRICE_SERIES_CONTRACT_PATH,
    build_dplus4_forecast_slice,
    build_rolling_price_slice,
    dplus4_timestamp_plan,
)
from .s4_4c_component_ontology import (
    COST_POLICY_MODES_PATH,
    EXTERNAL_SUPPLY_COSTS_PATH,
    FIXED_REFERENCE_SCENARIO_CONTRACT_PATH,
    FUTURE_COST_BOUNDARY_CONTRACT_PATH,
    FUTURE_DETERMINISTIC_COST_RESULT_FIELDS,
    GENERATOR_OPERATING_MODE_CONTRACT_PATH,
    ROUTE_BOUNDARY_CONTRACT_PATH,
    continuous_must_run_activities,
    load_fixed_reference_scenario_contract,
    load_cost_policy_modes,
    load_external_supply_costs,
    load_future_cost_boundary_contract,
    load_generator_operating_mode_contract,
    load_route_boundary_contract,
)
from .s4_4c5p_ae_rolling_production_feasibility import _c1_capacity_diagnosis
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
    run_s44c_unified_physical_regression,
)
from .validation_tolerance_policy import (
    HOURLY_MONEY_IDENTITY_TOLERANCE_EUR,
    SOLVER_NUMERICAL_TOLERANCE,
    TERMINAL_STATE_TOLERANCE_T,
    ValidationTolerancePolicyError,
    exact_input_fingerprint,
    policy_contract as validation_tolerance_policy_contract,
    require_exact_input_fingerprint,
    trajectory_cost_record,
)


DEFAULT_CONFIG_PATH = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_closed_loop_feasibility_anchor_reconciliation.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
ANCHOR_REGISTER_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "c5_model_anchor_register" / "c5_model_anchor_evidence_register.csv"
USER_AUTHORIZED_EMULATION_PARAMETER_OVERLAY_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "c5_tata_benchmark_target_contract" / "user_authorized_emulation_parameter_overlay.csv"
CONFIGURATIONS = ("C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF")
PJ_PER_MWH = 3.6e-6
TOLERANCE_T = 1e-5
# Hourly dispatch rows are persisted at six decimals. A 24-hour reconstructed
# inventory identity can therefore accumulate up to 24 microtonnes of pure
# serialization noise even though the solved Pyomo equality is exact.
HOURLY_REPORTING_MATERIAL_TOLERANCE_T = 3e-5
ANNUALISED_ACCOUNTING_TOLERANCE_MWH = 0.01
HOURS_PER_YEAR = 8760.0
C0_CONFIGURATION = CONFIGURATIONS[0]
C1_CONFIGURATION = CONFIGURATIONS[1]

FIRST_ORDER_FULL_SITE_CO2_TARGET_MT_Y = {
    C0_CONFIGURATION: 13.24,
    C1_CONFIGURATION: 9.107793,
}

# Reporting-only selected activity factors. These are deliberately separate
# from the carrier-explicit Mode-B ledger and never enter dispatch or ETS.
FIRST_ORDER_PROCESS_CO2_FACTORS = (
    {
        "component": "BF_direct_CO2",
        "factor": 1.495,
        "unit": "tCO2/t_hot_metal",
        "activity_fields": {
            C0_CONFIGURATION: "C0_BF_hot_iron_output_t",
            C1_CONFIGURATION: "C1_retained_BF_hot_iron_output_t_h",
        },
        "source_locator": "s4_4c5h_blast_furnace_controller_parameterisation.py: BF_CO2_COUNTER_AGG_T_PER_T_HM; source_cards/Blast_Furnace_Parameters.md",
    },
    {
        "component": "BOF_direct_CO2",
        "factor": 0.0825,
        "unit": "tCO2/t_liquid_steel",
        "activity_fields": {
            C0_CONFIGURATION: "C0_BOF_crude_steel_output_t",
            C1_CONFIGURATION: "C1_BOF_liquid_steel_output_t_h",
        },
        "source_locator": "s4_4c5k_bof_osf_coefficient_rows_inherited_from_c5j.csv: BOF_DIRECT_CO2_T_PER_T_LS",
    },
    {
        "component": "KGF_direct_CO2",
        "factor": 0.20,
        "unit": "tCO2/t_coke",
        "activity_fields": {
            C0_CONFIGURATION: "C0_coke_output_t_h",
            C1_CONFIGURATION: "C1_retained_coke_output_t_h",
        },
        "source_locator": "s4_4c5f_kgf_parameter_values.csv: KGF_DIRECT_CO2_T_PER_T_COKE; source_cards/Coking_Plants_Parameters.md",
    },
    {
        "component": "sinter_direct_CO2",
        "factor": 0.248,
        "unit": "tCO2/t_sinter",
        "activity_fields": {
            C0_CONFIGURATION: "C0_sinter_output_t_h",
            C1_CONFIGURATION: "C1_retained_sinter_output_t_h",
        },
        "source_locator": "s4_4c5m_sinter_development_input_rows.csv: SINTER_DIRECT_CO2_T_PER_T_SINTER",
    },
    {
        "component": "PeFa_direct_CO2",
        "factor": 0.105,
        "unit": "tCO2/t_pellets",
        "activity_fields": {
            C0_CONFIGURATION: "PEFA_pellet_output_t",
            C1_CONFIGURATION: "PEFA_pellet_output_t",
        },
        "source_locator": "s4_4c5n_a_pefa_development_input_rows.csv: PEFA_DIRECT_CO2_T_PER_T",
    },
    {
        "component": "EAF_direct_CO2",
        "factor": 0.126,
        "unit": "tCO2/t_liquid_steel",
        "activity_fields": {C1_CONFIGURATION: "C1_EAF_liquid_steel_output_t_h"},
        "source_locator": "s4_4c5o_b_eaf_development_input_rows.csv: EAF_DIRECT_CO2_T_PER_T_LS_BREF_MIDPOINT",
    },
)


class ClosedLoopFeasibilityError(ValueError):
    """Raised when the closed-loop feasibility setup is invalid."""


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _file_fingerprints(paths: list[Path]) -> list[dict[str, str]]:
    return [
        {
            "path": str(path.resolve().relative_to(REPO_ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(paths)
    ]


def _input_manifest(
    config_file: Path, *, resolved_config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    model_inputs = list(S44B_INPUT_DIR.glob("*.csv"))
    if not model_inputs:
        raise ClosedLoopFeasibilityError(
            f"No active model inputs found for run fingerprinting in {S44B_INPUT_DIR}."
        )
    evidence_paths = [
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/SINTER_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/DRP_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/HSM_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/EAF_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/DSP_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/BOF_OSF_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/Blast_Furnace_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/Coking_Plants_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/PELLETIZING_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/LINDE_OXYGEN_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/BOILER_STEAM_CIRCUIT_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/WAG_CARRIERS_CO2_FACTORS_Parameters.md",
        ROUTE_BOUNDARY_CONTRACT_PATH,
        FUTURE_COST_BOUNDARY_CONTRACT_PATH,
        FIXED_REFERENCE_SCENARIO_CONTRACT_PATH,
        PRICE_SERIES_CONTRACT_PATH,
        DPLUS4_SOURCE_CONTRACT_PATH,
        GENERATOR_OPERATING_MODE_CONTRACT_PATH,
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c5m_Sinter_minimal_parameterisation/s4_4c5m_sinter_development_input_rows.csv",
    ]
    manifest = {
        "config_path": str(config_file.relative_to(REPO_ROOT)),
        "config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest(),
        "anchor_register": str(ANCHOR_REGISTER_PATH.relative_to(REPO_ROOT)),
        "anchor_register_sha256": hashlib.sha256(ANCHOR_REGISTER_PATH.read_bytes()).hexdigest(),
        "modelbuilder": "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        "active_model_input_files": _file_fingerprints(model_inputs),
        "direct_source_evidence_files": _file_fingerprints(evidence_paths),
    }
    if resolved_config is not None:
        resolved_payload = yaml.safe_dump(dict(resolved_config), sort_keys=True).encode("utf-8")
        manifest["resolved_config_sha256"] = hashlib.sha256(resolved_payload).hexdigest()
    return manifest


def _float(value: Any) -> float:
    return 0.0 if value in (None, "") else float(value)


def _initialize_normal_solution_capture_directory(
    policy: Mapping[str, Any],
) -> Path:
    directory = Path(str(policy["directory"])).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ClosedLoopFeasibilityError("Closed-loop configuration must be a YAML mapping.")
    for key in ("run_id", "planning_horizon_hours", "execution_block_hours", "replan_count", "quota_per_execution_block_t"):
        if key not in payload:
            raise ClosedLoopFeasibilityError(f"Missing configuration key: {key}")
    if int(payload["replan_count"]) < 2:
        raise ClosedLoopFeasibilityError("Closed-loop execution requires at least two replans.")
    for key in ("market_prices_enabled", "product_revenue_enabled", "co2_ets_objective_enabled"):
        if payload.get(key) is not False:
            raise ClosedLoopFeasibilityError(f"Closed-loop feasibility forbids {key}.")
    horizon_hours = int(payload["planning_horizon_hours"])
    execution_hours = int(payload["execution_block_hours"])
    dplus4_horizon = bool(payload.get("dplus4_horizon_contract_active", False))
    if execution_hours != 24 or (
        horizon_hours != 168 and not (dplus4_horizon and horizon_hours == 120)
    ):
        raise ClosedLoopFeasibilityError(
            "Rolling execution requires 24-hour blocks and either the governed 168-hour "
            "physical horizon or the explicit 120-hour D-D+4 forecast horizon."
        )
    timestamped_dplus4 = payload.get(
        "timestamped_dplus4_rolling_enabled", False
    )
    if not isinstance(timestamped_dplus4, bool):
        raise ClosedLoopFeasibilityError(
            "timestamped_dplus4_rolling_enabled must be boolean."
        )
    if timestamped_dplus4 and not dplus4_horizon:
        raise ClosedLoopFeasibilityError(
            "Timestamp-derived rolling durations require the D-D+4 horizon contract."
        )
    forecast_price_field = str(payload.get("forecast_price_field", "y_pred"))
    oracle = payload.get("perfect_foresight_oracle", False)
    if not isinstance(oracle, bool):
        raise ClosedLoopFeasibilityError(
            "perfect_foresight_oracle must be boolean."
        )
    if forecast_price_field not in {"y_pred", "y_true"}:
        raise ClosedLoopFeasibilityError(
            "forecast_price_field must be y_pred or y_true."
        )
    if (forecast_price_field == "y_true") != oracle:
        raise ClosedLoopFeasibilityError(
            "y_true is allowed only in an explicitly labelled perfect-foresight oracle."
        )
    payload["timestamped_dplus4_rolling_enabled"] = timestamped_dplus4
    payload["forecast_price_field"] = forecast_price_field
    payload["perfect_foresight_oracle"] = oracle
    if payload.get("c1_boundary_case") not in {"endogenous_6_75", "mer_site_product"}:
        raise ClosedLoopFeasibilityError("c1_boundary_case must be endogenous_6_75 or mer_site_product.")
    execution_mode = str(payload.get("execution_mode", "endogenous_feasibility"))
    if execution_mode not in {
        "endogenous_feasibility",
        "reference_validation",
        "fixed_reference_physical",
        "fixed_reference_cost",
    }:
        raise ClosedLoopFeasibilityError(
            "Unsupported rolling execution_mode."
        )
    if execution_mode == "reference_validation" and not isinstance(payload.get("reference_validation"), Mapping):
        raise ClosedLoopFeasibilityError("reference_validation mode requires its governed definition mapping.")
    cost_enabled = payload.get("energy_cost_objective_enabled")
    if execution_mode == "fixed_reference_cost":
        if cost_enabled is not True:
            raise ClosedLoopFeasibilityError(
                "fixed_reference_cost requires energy_cost_objective_enabled: true."
            )
    elif cost_enabled is not False:
        raise ClosedLoopFeasibilityError(
            "Only fixed_reference_cost may activate the deterministic cost objective."
        )
    if execution_mode.startswith("fixed_reference") and not payload.get(
        "fixed_reference_scenario_id"
    ):
        raise ClosedLoopFeasibilityError(
            "Fixed-reference modes require fixed_reference_scenario_id."
        )
    progress_enabled = payload.get(
        "rolling_production_progress_state_enabled", False
    )
    if not isinstance(progress_enabled, bool):
        raise ClosedLoopFeasibilityError(
            "rolling_production_progress_state_enabled must be boolean."
        )
    if progress_enabled and not execution_mode.startswith("fixed_reference"):
        raise ClosedLoopFeasibilityError(
            "Rolling production-progress hardening is governed for fixed-reference modes only."
        )
    envelope_fraction = float(
        payload.get("production_envelope_tolerance_fraction", 0.005)
    )
    if progress_enabled and abs(envelope_fraction - 0.005) > 1e-12:
        raise ClosedLoopFeasibilityError(
            "The governed fixed-reference production envelope must remain +/-0.5 percent."
        )
    payload["rolling_production_progress_state_enabled"] = progress_enabled
    terminal_exact = payload.get("exact_terminal_production_quota_enabled", False)
    if not isinstance(terminal_exact, bool):
        raise ClosedLoopFeasibilityError(
            "exact_terminal_production_quota_enabled must be boolean."
        )
    if terminal_exact and not progress_enabled:
        raise ClosedLoopFeasibilityError(
            "Exact terminal production quota requires rolling production progress state."
        )
    payload["exact_terminal_production_quota_enabled"] = terminal_exact
    terminal_hours = payload.get("terminal_executed_hours_target")
    if terminal_hours not in {None, ""}:
        terminal_hours = int(terminal_hours)
        if terminal_hours <= int(payload.get("initial_executed_hours", 0)):
            raise ClosedLoopFeasibilityError(
                "terminal_executed_hours_target must exceed the initial executed hours."
            )
        if not terminal_exact:
            raise ClosedLoopFeasibilityError(
                "A global terminal execution target requires exact terminal quota enforcement."
            )
        payload["terminal_executed_hours_target"] = terminal_hours
    payload["production_envelope_tolerance_fraction"] = envelope_fraction
    payload["execution_mode"] = execution_mode
    repair_stage = str(payload.get("repair_stage", "none"))
    if repair_stage not in {"none", "downstream", "generator", "electricity"}:
        raise ClosedLoopFeasibilityError(
            "repair_stage must be none, downstream, generator or electricity."
        )
    payload["repair_stage"] = repair_stage
    return payload


def _validate_required_solver_family(
    config: Mapping[str, Any], build_audit_rows: Collection[Mapping[str, Any]]
) -> None:
    """Fail acceptance instead of silently substituting another solver family."""

    required_solver = str(config.get("required_solver_family", "")).lower()
    if not required_solver:
        return
    used_solvers = {
        str(row.get("solver_name", "")).lower()
        for row in build_audit_rows
        if row.get("solver_name")
    }
    accepted_solvers = (
        {"gurobi", "gurobi_direct"}
        if required_solver == "gurobi"
        else {required_solver}
    )
    if not used_solvers or not used_solvers.issubset(accepted_solvers):
        raise ClosedLoopFeasibilityError(
            f"Accepted repair run requires {sorted(accepted_solvers)}, got {sorted(used_solvers)}."
        )


def _source_coke_chain(config: Mapping[str, Any]) -> dict[str, float]:
    payload = config.get("source_coke_chain")
    required = {"dry_coal_t_per_t_coke", "bf_coke_t_per_t_hot_metal"}
    if not isinstance(payload, Mapping) or not required.issubset(payload):
        raise ClosedLoopFeasibilityError(f"source_coke_chain must provide {sorted(required)}.")
    result = {key: float(payload[key]) for key in required}
    if min(result.values()) <= 0.0:
        raise ClosedLoopFeasibilityError("source_coke_chain values must be positive.")
    return result


def _external_procurement_flow_coefficients(
    config: Mapping[str, Any],
    route_rows: Collection[Mapping[str, str]],
) -> dict[str, float] | None:
    """Resolve physical PCI and PEFA-ore coefficients from the route contract."""

    if not bool(config.get("external_procurement_flows_enabled", False)):
        return None
    by_id = {row["route_id"]: row for row in route_rows}
    required = {"C0_BF_PCI", "C1_BF_PCI", "C0_PEFA_ORE", "C1_PEFA_ORE"}
    missing = required.difference(by_id)
    if missing:
        raise ClosedLoopFeasibilityError(
            f"External procurement route rows are missing: {sorted(missing)}"
        )

    def coefficient(route_id: str) -> float:
        token = str(by_id[route_id]["conversion_factor"]).split()[0]
        try:
            result = float(token)
        except ValueError as exc:
            raise ClosedLoopFeasibilityError(
                f"External procurement coefficient is not numeric: {route_id}"
            ) from exc
        if result <= 0.0:
            raise ClosedLoopFeasibilityError(
                f"External procurement coefficient must be positive: {route_id}"
            )
        return result

    pci = coefficient("C0_BF_PCI")
    c1_pci = coefficient("C1_BF_PCI")
    pefa = coefficient("C0_PEFA_ORE")
    c1_pefa = coefficient("C1_PEFA_ORE")
    if abs(pci - c1_pci) > 1e-12 or abs(pefa - c1_pefa) > 1e-12:
        raise ClosedLoopFeasibilityError(
            "C0/C1 procurement coefficients must preserve their shared source basis."
        )
    return {
        "pci_t_per_t_hot_metal": pci,
        "pefa_iron_ore_t_per_t_pellets": pefa,
    }


def _deterministic_cost_policy(
    config: Mapping[str, Any],
    cost_rows: Collection[Mapping[str, str]],
    *,
    horizon_hours: int,
    nominal_forecast_horizon_hours: int | None = None,
    replan_index: int = 0,
    execution_block_hours: int = 24,
) -> dict[str, Any] | None:
    """Build a price-valued model contract without embedding prices in Python."""

    if config.get("execution_mode") != "fixed_reference_cost":
        return None
    policies = load_cost_policy_modes()
    if policies["cost_objective_enabled"]["policy_value"] != "true":
        raise ClosedLoopFeasibilityError(
            "Governed fixed-reference cost objective is disabled."
        )
    scenario_overrides = config.get("price_scenario_overrides", {})
    if not isinstance(scenario_overrides, Mapping):
        raise ClosedLoopFeasibilityError(
            "price_scenario_overrides must be a mapping."
        )
    price_rows = {
        (row["price_id"], row["scenario_id"]): row
        for row in load_external_supply_costs()
    }
    price_series_id = str(
        config.get("price_series_id", "flat_central_reference_v1")
    )
    grid_scenario_id = str(
        scenario_overrides.get(
            "grid_electricity_flat_nl", "development_central"
        )
    )
    forecast_horizon_hours = int(
        nominal_forecast_horizon_hours or horizon_hours
    )
    if forecast_horizon_hours < horizon_hours:
        raise ClosedLoopFeasibilityError(
            "The nominal forecast horizon cannot be shorter than the physical plan."
        )
    electricity_price_slice = build_rolling_price_slice(
        price_series_id=price_series_id,
        replan_index=replan_index,
        planning_horizon_hours=forecast_horizon_hours,
        execution_block_hours=execution_block_hours,
        flat_scenario_id=grid_scenario_id,
        external_series_path=config.get("electricity_price_series_path"),
        forecast_run_root=config.get("forecast_run_root"),
        forecast_dataset_split=config.get("forecast_dataset_split"),
        forecast_start_origin_utc=config.get("forecast_start_origin_utc"),
        forecast_price_override_eur_per_mwh=config.get(
            "forecast_price_override_eur_per_mwh"
        ),
        forecast_price_field=str(config.get("forecast_price_field", "y_pred")),
        perfect_foresight_oracle=bool(
            config.get("perfect_foresight_oracle", False)
        ),
        realised_price_gap_patch_by_timestamp_utc=config.get(
            "realised_price_gap_patch_by_timestamp_utc"
        ),
    )
    electricity_price_slice = electricity_price_slice[:horizon_hours]
    real_anchor_c0_generator_cost_active = bool(
        isinstance(config.get("c0_aggregate_generator_technical_interface"), Mapping)
        and config["c0_aggregate_generator_technical_interface"].get("enabled", False)
    )
    real_anchor_c0_bridge_costs_active = bool(
        isinstance(config.get("c0_full_site_energy_bridge"), Mapping)
        and config["c0_full_site_energy_bridge"].get("enabled", False)
    )
    flows: list[dict[str, Any]] = []
    for row in cost_rows:
        opt_in_real_anchor_flow = (
            real_anchor_c0_generator_cost_active
            and row.get("flow_id") == "C0_NG_GENERATOR"
        ) or (
            real_anchor_c0_bridge_costs_active
            and row.get("flow_id")
            in {"C0_NG_FIXED_FULL_SITE", "C0_NG_FLEXIBLE_OTHER_SITE_HEAT"}
        )
        if row.get("objective_enabled") != "true" and not opt_in_real_anchor_flow:
            continue
        price_id = row["price_id"]
        scenario_id = str(
            scenario_overrides.get(price_id, row["price_scenario_id"])
        )
        key = (price_id, scenario_id)
        if key not in price_rows:
            raise ClosedLoopFeasibilityError(
                f"Cost scenario is missing for {row['flow_id']}: {key}"
            )
        price = price_rows[key]
        if price["unit"] != row["price_unit"]:
            raise ClosedLoopFeasibilityError(
                f"Cost unit mismatch for {row['flow_id']}."
            )
        hourly_prices = (
            [float(item["price_eur_per_mwh_e"]) for item in electricity_price_slice]
            if price_id == "grid_electricity_flat_nl"
            else [float(price["value"])] * horizon_hours
        )
        flows.append(
            {
                "flow_id": row["flow_id"],
                "configuration": row["configuration"],
                "component": row["component"],
                "model_component_attribute": row["model_component_attribute"],
                "physical_quantity_attribute": row["physical_quantity_attribute"],
                "price_id": price_id,
                "scenario_id": scenario_id,
                "price_unit": row["price_unit"],
                "quantity_unit": row["physical_unit"],
                "cost_route": row["cost_route"],
                "price_eur_by_hour": hourly_prices,
            }
        )
    if not flows:
        raise ClosedLoopFeasibilityError(
            "No objective-enabled external procurement flows are governed."
        )
    return {
        "mode": "fixed_reference_procurement_cost",
        "flows": flows,
        "objective_tolerance_eur": float(
            policies["deterministic_cost_tolerance_eur"]["policy_value"]
        ),
        "price_scenario_overrides": dict(scenario_overrides),
        "price_series_id": price_series_id,
        "electricity_price_series_slice": electricity_price_slice,
    }


def _cost_component_for_attribute(component: str, attribute: str) -> str:
    aliases = {
        "NG_to_PEFA_malerij_mwh": "PEFA_malerij",
        "NG_to_PEFA_branderij_mwh": "PEFA_branderij",
        "natural_gas_boiler_mwh": "represented_15bar_boiler",
        "VN25_NG_fuel_mwh": "VN25",
        "generator_named_ng_mwh": "aggregate_generator",
        "full_site_fixed_ng_component_mwh": "fixed_full_site_component",
        "flexible_other_site_heat_ng_mwh": "flexible_other_site_heat",
        "site_baseload_ng_mwh": "source_bounded_site_baseload",
    }
    return aliases.get(attribute, component)


_FROZEN_PROCUREMENT_PRICE_IDS = frozenset(
    {
        "grid_electricity_flat_nl",
        "natural_gas_ttf_proxy",
        "coking_coal_hcc_proxy",
        "pci_coal_proxy",
        "iron_ore_62fe_proxy",
        "imported_dr_pellets_proxy",
        "purchased_scrap_proxy",
        "imported_slab_proxy",
    }
)
_GOVERNED_SALE_PRICE_ID = "governed_y_pred_sale_value"
_GOVERNED_SALE_POLICY_IDENTITY = {
    "enabled": True,
    "policy_id": "athanasiadis_sale_enabled",
    "price_basis": "same_governed_y_pred_as_import",
    "revenue_scope": "gross_grid_export_only",
    "settlement_claim": False,
}


def _planning_horizon_cost_preservation_validation(
    *,
    primary_cost_eur: float,
    tie_break_cost_eur: float,
    endpoint_cost_eur: float,
) -> dict[str, Any]:
    """Validate planning-horizon cost preservation as aggregate EUR records."""

    tie_break = trajectory_cost_record(
        "tie_break_cost_preservation",
        tie_break_cost_eur - primary_cost_eur,
        comparison_scale_eur=max(abs(primary_cost_eur), abs(tie_break_cost_eur)),
    )
    endpoint = trajectory_cost_record(
        "allocation_envelope_endpoint_cost_preservation",
        endpoint_cost_eur - primary_cost_eur,
        comparison_scale_eur=max(abs(primary_cost_eur), abs(endpoint_cost_eur)),
    )
    return {
        "status": (
            "pass"
            if tie_break["status"] == "pass" and endpoint["status"] == "pass"
            else "fail"
        ),
        "tie_break": tie_break,
        "endpoint": endpoint,
    }
_GOVERNED_SALE_LEDGER_IDENTITY = {
    "configuration_id": C0_CONFIGURATION,
    "flow_id": "C0_EL_EXPORT",
    "component": "gross_grid_export",
    "cost_route": "represented_electricity_sale_sensitivity",
    "physical_quantity_attribute": "gross_grid_export_mwh",
    "price_scenario_id": "same_governed_y_pred_as_import",
}


def _ledger_price_input_identity(
    *,
    price_id: str,
    price_scenario_id: str,
    plan_hour_index: int,
    price_eur_per_unit: float,
) -> dict[str, Any]:
    return {
        "price_id": str(price_id),
        "price_scenario_id": str(price_scenario_id),
        "plan_hour_index": int(plan_hour_index),
        "price_eur_per_unit": float(price_eur_per_unit),
    }


def _ledger_price_input_fingerprint(row: Mapping[str, Any]) -> str:
    return exact_input_fingerprint(
        _ledger_price_input_identity(
            price_id=str(row["price_id"]),
            price_scenario_id=str(row["price_scenario_id"]),
            plan_hour_index=int(row["plan_hour_index"]),
            price_eur_per_unit=float(row["price_eur_per_unit"]),
        )
    )


def _governed_cost_ledger_validation(
    config: Mapping[str, Any],
    ledger: Collection[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate the frozen procurement ledger plus the one opt-in sale family."""

    raw_sale_policy = config.get("c0_electricity_sale_sensitivity")
    sale_enabled = bool(
        isinstance(raw_sale_policy, Mapping)
        and raw_sale_policy.get("enabled") is True
    )
    sale_policy_valid = bool(
        sale_enabled
        and all(
            raw_sale_policy.get(key) == expected
            for key, expected in _GOVERNED_SALE_POLICY_IDENTITY.items()
        )
    )
    expected_price_ids = set(_FROZEN_PROCUREMENT_PRICE_IDS)
    if sale_policy_valid:
        expected_price_ids.add(_GOVERNED_SALE_PRICE_ID)
    actual_price_ids = {str(row.get("price_id")) for row in ledger}
    price_fingerprint_diagnostics: list[dict[str, Any]] = []
    for index, row in enumerate(ledger):
        expected_fingerprint = str(
            row.get("price_input_fingerprint_sha256", "")
        )
        try:
            require_exact_input_fingerprint(
                _ledger_price_input_identity(
                    price_id=str(row["price_id"]),
                    price_scenario_id=str(row["price_scenario_id"]),
                    plan_hour_index=int(row["plan_hour_index"]),
                    price_eur_per_unit=float(row["price_eur_per_unit"]),
                ),
                expected_fingerprint=expected_fingerprint,
                purpose=f"procurement ledger price row {index}",
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationTolerancePolicyError,
        ) as exc:
            price_fingerprint_diagnostics.append(
                {
                    "ledger_row_index": index,
                    "status": "fail",
                    "price_id": row.get("price_id"),
                    "failure": type(exc).__name__,
                }
            )
        else:
            price_fingerprint_diagnostics.append(
                {
                    "ledger_row_index": index,
                    "status": "pass",
                    "price_id": row.get("price_id"),
                    "price_input_fingerprint_sha256": expected_fingerprint,
                }
            )
    price_input_fingerprints_valid = bool(ledger) and all(
        row["status"] == "pass" for row in price_fingerprint_diagnostics
    )
    sale_rows = [
        (index, row)
        for index, row in enumerate(ledger)
        if str(row.get("price_id")) == _GOVERNED_SALE_PRICE_ID
    ]
    sale_row_diagnostics: list[dict[str, Any]] = []
    for index, row in sale_rows:
        failures = [
            f"wrong_{key}"
            for key, expected in _GOVERNED_SALE_LEDGER_IDENTITY.items()
            if row.get(key) != expected
        ]
        try:
            quantity = float(row.get("quantity"))
            price = float(row.get("price_eur_per_unit"))
            cost = float(row.get("cost_eur"))
        except (TypeError, ValueError):
            quantity = price = cost = math.nan
        if not math.isfinite(quantity):
            failures.append("nonfinite_quantity")
        elif quantity < 0.0:
            failures.append("negative_quantity")
        if not math.isfinite(price):
            failures.append("nonfinite_price")
        if not math.isfinite(cost):
            failures.append("nonfinite_cost")
        if (
            math.isfinite(quantity)
            and math.isfinite(price)
            and math.isfinite(cost)
            and abs(cost + quantity * price)
            > HOURLY_MONEY_IDENTITY_TOLERANCE_EUR
        ):
            failures.append("sale_cost_not_negative_quantity_times_price")
        sale_row_diagnostics.append(
            {
                "ledger_row_index": index,
                "status": "pass" if not failures else "fail",
                "failure_ids": failures,
            }
        )
    sale_rows_valid = bool(
        (
            sale_policy_valid
            and sale_rows
            and all(row["status"] == "pass" for row in sale_row_diagnostics)
        )
        or (not sale_enabled and not sale_rows)
    )
    forbidden_flags_absent = all(
        config.get(key) is False
        for key in (
            "market_prices_enabled",
            "product_revenue_enabled",
            "co2_ets_objective_enabled",
        )
    )
    missing_price_ids = sorted(expected_price_ids.difference(actual_price_ids))
    unauthorized_price_ids = sorted(actual_price_ids.difference(expected_price_ids))
    price_family_contract_valid = not missing_price_ids and not unauthorized_price_ids
    status = bool(
        price_family_contract_valid
        and price_input_fingerprints_valid
        and sale_rows_valid
        and forbidden_flags_absent
        and (not sale_enabled or sale_policy_valid)
    )
    return {
        "status": "pass" if status else "fail",
        "expected_price_ids": sorted(expected_price_ids),
        "actual_price_ids": sorted(actual_price_ids),
        "missing_price_ids": missing_price_ids,
        "unauthorized_price_ids": unauthorized_price_ids,
        "price_family_contract_valid": price_family_contract_valid,
        "price_input_comparison": "exact_fingerprint_no_numeric_tolerance",
        "price_input_fingerprints_valid": price_input_fingerprints_valid,
        "price_fingerprint_diagnostics": price_fingerprint_diagnostics,
        "sale_enabled": sale_enabled,
        "sale_policy_valid": sale_policy_valid,
        "sale_row_count": len(sale_rows),
        "sale_rows_valid": sale_rows_valid,
        "sale_row_diagnostics": sale_row_diagnostics,
        "forbidden_economic_flags_absent": forbidden_flags_absent,
    }


def _cost_acceptance_readiness(
    *,
    pre_cost_boundary_ready: bool,
    cost_mode_active: bool,
    cost_objectives_active: bool,
    cost_objective_reconciliation_pass: bool,
    cost_ledger_validation: Mapping[str, Any],
) -> bool:
    return bool(
        pre_cost_boundary_ready
        and (
            not cost_mode_active
            or (
                cost_objectives_active
                and cost_objective_reconciliation_pass
                and cost_ledger_validation.get("status") == "pass"
            )
        )
    )


def _procurement_cost_ledger(
    hourly_rows: Collection[Mapping[str, Any]],
    deterministic_cost_policy: Mapping[str, Any] | None,
    *,
    run_id: str,
    replan_index: int | None = None,
) -> list[dict[str, Any]]:
    """Price represented solved purchases without changing the physical model."""

    if deterministic_cost_policy is None:
        return []
    ledger: list[dict[str, Any]] = []
    for row in hourly_rows:
        configuration_id = str(row["configuration_id"])
        configuration = "C0" if configuration_id.startswith("C0_") else "C1"
        plan_hour = int(row["hour_index"])
        executed_hour = row.get("executed_hour_index", "")
        block = int(row.get("replan_index", replan_index or 0))
        for flow in deterministic_cost_policy["flows"]:
            if flow["configuration"] not in {configuration, "both"}:
                continue
            price = float(flow["price_eur_by_hour"][plan_hour])
            for attribute in str(flow["physical_quantity_attribute"]).split(";"):
                if attribute not in row:
                    raise ClosedLoopFeasibilityError(
                        f"Cost reporting quantity is missing: {flow['flow_id']}/{attribute}."
                    )
                quantity = _float(row[attribute])
                if quantity < -TOLERANCE_T:
                    raise ClosedLoopFeasibilityError(
                        f"External procurement flow is negative: {flow['flow_id']}/{attribute}."
                    )
                ledger_row = {
                        "configuration_id": configuration_id,
                        "replan_index": block,
                        "plan_hour_index": plan_hour,
                        "executed_hour_index": executed_hour,
                        "flow_id": flow["flow_id"],
                        "component": _cost_component_for_attribute(
                            str(flow["component"]), attribute
                        ),
                        "cost_route": flow["cost_route"],
                        "physical_quantity_attribute": attribute,
                        "quantity": round(max(0.0, quantity), 9),
                        "quantity_unit": flow["quantity_unit"],
                        "price_id": flow["price_id"],
                        "price_scenario_id": flow["scenario_id"],
                        "price_eur_per_unit": price,
                        "cost_eur": round(max(0.0, quantity) * price, 9),
                        "run_id": run_id,
                    }
                ledger_row["price_input_fingerprint_sha256"] = (
                    _ledger_price_input_fingerprint(ledger_row)
                )
                ledger.append(ledger_row)
        sale = deterministic_cost_policy.get("electricity_sale_sensitivity")
        if (
            configuration == "C0"
            and isinstance(sale, Mapping)
            and sale.get("enabled") is True
        ):
            prices = list(sale.get("sale_price_eur_by_hour", ()))
            horizon = len(next(iter(deterministic_cost_policy["flows"]))["price_eur_by_hour"])
            if len(prices) != horizon:
                raise ClosedLoopFeasibilityError(
                    "Electricity-sale reporting price horizon mismatch."
                )
            exported = _float(row.get("gross_grid_export_mwh"))
            if exported < -TOLERANCE_T:
                raise ClosedLoopFeasibilityError("Gross grid export cannot be negative.")
            ledger_row = {
                    "configuration_id": configuration_id,
                    "replan_index": block,
                    "plan_hour_index": plan_hour,
                    "executed_hour_index": executed_hour,
                    "flow_id": "C0_EL_EXPORT",
                    "component": "gross_grid_export",
                    "cost_route": "represented_electricity_sale_sensitivity",
                    "physical_quantity_attribute": "gross_grid_export_mwh",
                    "quantity": round(max(0.0, exported), 9),
                    "quantity_unit": "MWh_e",
                    "price_id": "governed_y_pred_sale_value",
                    "price_scenario_id": "same_governed_y_pred_as_import",
                    "price_eur_per_unit": float(prices[plan_hour]),
                    "cost_eur": round(
                        -max(0.0, exported) * float(prices[plan_hour]), 9
                    ),
                    "run_id": run_id,
                }
            ledger_row["price_input_fingerprint_sha256"] = (
                _ledger_price_input_fingerprint(ledger_row)
            )
            ledger.append(ledger_row)
    return ledger


def _procurement_cost_summaries(
    ledger: Collection[Mapping[str, Any]],
    executed_hourly_rows: Collection[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    totals: dict[str, float] = defaultdict(float)
    by_component: dict[tuple[str, str, str, str], float] = defaultdict(float)
    by_route: dict[tuple[str, str], float] = defaultdict(float)
    for row in ledger:
        configuration = str(row["configuration_id"])
        cost = float(row["cost_eur"])
        totals[configuration] += cost
        by_component[(configuration, str(row["flow_id"]), str(row["component"]), str(row["price_id"]))] += cost
        by_route[(configuration, str(row["cost_route"]))] += cost
    final_product: dict[str, float] = defaultdict(float)
    for row in executed_hourly_rows:
        final_product[str(row["configuration_id"])] += _float(
            row.get("final_product_output_t")
        )
    configuration_rows = [
        {
            "configuration_id": configuration,
            "executed_procurement_cost_eur": round(total, 6),
            "executed_final_product_t": round(final_product[configuration], 6),
            "procurement_cost_eur_per_t_final_product": round(
                total / final_product[configuration], 9
            ),
            "annualised_procurement_cost_eur_y": round(
                total * HOURS_PER_YEAR / (7 * 24), 6
            ),
        }
        for configuration, total in sorted(totals.items())
    ]
    component_rows = [
        {
            "configuration_id": key[0],
            "flow_id": key[1],
            "component": key[2],
            "price_id": key[3],
            "cost_eur": round(cost, 6),
        }
        for key, cost in sorted(by_component.items())
    ]
    route_rows = [
        {
            "configuration_id": key[0],
            "cost_route": key[1],
            "cost_eur": round(cost, 6),
        }
        for key, cost in sorted(by_route.items())
    ]
    return configuration_rows, component_rows, route_rows


def _source_bounded_sensitivity_levers(config: Mapping[str, Any]) -> tuple[str, float | None]:
    generator_mode = str(config.get("generator_interface_cap_mode", "inherited_profile"))
    if generator_mode not in {"inherited_profile", "volume_envelope_only"}:
        raise ClosedLoopFeasibilityError("Unsupported generator-interface sensitivity mode.")
    raw_hsm_electricity = config.get("hsm_rolling_electricity_mwh_per_t_hrc")
    hsm_electricity = None if raw_hsm_electricity in {None, ""} else float(raw_hsm_electricity)
    if hsm_electricity is not None and not 0.028 <= hsm_electricity <= 0.111:
        raise ClosedLoopFeasibilityError(
            "HSM rolling-electricity sensitivity must stay inside the source-card 0.028-0.111 MWh/t HRC range."
        )
    return generator_mode, hsm_electricity


def _generator_unit_interface(
    config: Mapping[str, Any], *, horizon_hours: int,
    deadline_hours: Collection[int] | None = None,
) -> dict[str, Any] | None:
    """Resolve Table-5.5 C1 generator caps without fixing a carrier or WAG/NG ratio."""

    if str(config.get("repair_stage", "none")) not in {"generator", "electricity"}:
        return None
    payload = config.get("c1_generator_boundary")
    if not isinstance(payload, Mapping):
        raise ClosedLoopFeasibilityError(
            "Generator/electricity repair stages require c1_generator_boundary."
        )
    required = {
        "vn25_bfg_pj_y": 8.4,
        "vn25_bofg_pj_y": 1.2,
        "vn25_cog_pj_y": 0.1,
        "vn25_ng_cap_pj_y": 4.1,
        "vn25_total_fuel_pj_y": 13.7,
        "vn25_electricity_efficiency": 0.345,
        "vn25_volume_cap_nm3_h": 600_000.0,
        "ij01_bfg_pj_y": 0.7,
        "ij01_bofg_pj_y": 0.1,
        "ij01_cog_pj_y": 0.0,
        "ij01_total_fuel_pj_y": 0.8,
        "ij01_volume_cap_nm3_h": 300_000.0,
    }
    missing = set(required).difference(payload)
    if missing:
        raise ClosedLoopFeasibilityError(
            f"c1_generator_boundary is missing: {sorted(missing)}"
        )
    efficiency_sensitivity = bool(
        config.get("source_bounded_generator_efficiency_sensitivity", False)
    )
    mode_id = str(
        config.get(
            "generator_operating_mode",
            "bounded_generator_sensitivity"
            if efficiency_sensitivity
            else "price_insensitive_reference",
        )
    )
    modes = load_generator_operating_mode_contract()
    if mode_id not in modes:
        raise ClosedLoopFeasibilityError(
            f"Unknown generator_operating_mode: {mode_id}"
        )
    mode = modes[mode_id]
    price_series_id = str(
        config.get("price_series_id", "flat_central_reference_v1")
    )
    if (
        mode["price_series_policy"] == "flat_central_reference_v1"
        and price_series_id != "flat_central_reference_v1"
    ):
        raise ClosedLoopFeasibilityError(
            "price_insensitive_reference requires the governed flat price series."
        )
    if mode_id == "bounded_generator_sensitivity" and not efficiency_sensitivity:
        raise ClosedLoopFeasibilityError(
            "bounded_generator_sensitivity requires its explicit source-bounded sensitivity flag."
        )
    if mode_id == "development_price_responsive" and efficiency_sensitivity:
        raise ClosedLoopFeasibilityError(
            "The central development price-responsive mode must retain efficiency 0.345."
        )
    for key, expected in required.items():
        if key == "vn25_electricity_efficiency" and efficiency_sensitivity:
            efficiency = float(payload[key])
            if not 0.34 <= efficiency <= 0.35:
                raise ClosedLoopFeasibilityError(
                    "VN25 efficiency sensitivity must stay inside the source-card 0.34-0.35 development range."
                )
            continue
        if abs(float(payload[key]) - expected) > 1e-9:
            raise ClosedLoopFeasibilityError(
                f"Generator source-boundary value {key} must remain {expected}, got {payload[key]}."
            )
    active_efficiency = float(payload["vn25_electricity_efficiency"])
    allowed_efficiencies = {
        float(item) for item in mode["allowed_efficiencies"].split(";")
    }
    if active_efficiency not in allowed_efficiencies:
        raise ClosedLoopFeasibilityError(
            f"VN25 efficiency {active_efficiency} is not allowed in mode {mode_id}."
        )
    return {
        "operating_mode": mode_id,
        "hourly_price_response": mode["hourly_price_response"] == "true",
        "vn25_electricity_efficiency": active_efficiency,
        "vn25_electric_capacity_mw": float(mode["vn25_electric_capacity_mw"]),
        "unit_volume_caps_nm3_h": {"vn25": 600_000.0, "ij01": 300_000.0},
        "ij01_total_fuel_horizon_cap_mwh": 0.8
        * float(horizon_hours)
        / HOURS_PER_YEAR
        / PJ_PER_MWH,
        "ij01_total_fuel_deadline_caps_mwh": {
            deadline: 0.8 * float(deadline) / HOURS_PER_YEAR / PJ_PER_MWH
            for deadline in (
                sorted(int(value) for value in deadline_hours)
                if deadline_hours is not None
                else range(24, horizon_hours + 1, 24)
            )
        },
        "validation_anchors_pj_y": {
            "vn25": {"BFG": 8.4, "COG": 0.1, "BOFG": 1.2, "NG": 4.1, "total": 13.7},
            "ij01": {"BFG": 0.7, "COG": 0.0, "BOFG": 0.1, "NG": 0.0, "total": 0.8},
        },
        "ij01_ng_allowed": False,
        "ij01_price_response": False,
        "export_allowed": False,
        "omitted_operational_features": (
            "minimum_load",
            "startup_shutdown",
            "ramp",
            "outage_schedule",
            "chp_steam_obligation",
        ),
        "boundary_role": (
            "source_bounded_generator_efficiency_sensitivity_no_fixed_mix"
            if efficiency_sensitivity
            else "source_eligibility_and_development_capacity_with_ij01_backup_envelope_no_fixed_mix"
        ),
    }


def _c0_real_anchor_energy_recovery_interfaces(
    config: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve the opt-in C0 aggregate generator and full-site NG bridge."""

    generator = config.get("c0_aggregate_generator_technical_interface")
    bridge = config.get("c0_full_site_energy_bridge")
    if generator is None and bridge is None:
        return None, None
    if not isinstance(generator, Mapping) or not bool(generator.get("enabled", False)):
        raise ClosedLoopFeasibilityError(
            "C0 real-anchor energy recovery requires the enabled aggregate generator interface."
        )
    required_generator = {
        "electricity_efficiency": 0.345,
        "total_fuel_volume_cap_nm3_h": 900_000.0,
        "natural_gas_lhv_mj_per_nm3": 35.8,
        "electrical_capacity_mw": 770.0,
    }
    for key, expected in required_generator.items():
        if key not in generator or abs(float(generator[key]) - expected) > 1e-9:
            raise ClosedLoopFeasibilityError(
                f"C0 aggregate generator {key} must remain {expected}."
            )
    if bool(generator.get("export_allowed", False)):
        raise ClosedLoopFeasibilityError("C0 aggregate generator export must remain disabled.")

    resolved_generator = {
        "electricity_efficiency": 0.345,
        "total_fuel_volume_cap_nm3_h": 900_000.0,
        "natural_gas_lhv_mj_per_nm3": 35.8,
        "electrical_capacity_mw": 770.0,
        "export_allowed": False,
    }
    if bridge is None:
        if not bool(config.get("phase5g_generator_without_legacy_bridge", False)):
            raise ClosedLoopFeasibilityError(
                "C0 generator without the legacy full-site bridge is only allowed by the Phase-5G gate."
            )
        return resolved_generator, None
    if not isinstance(bridge, Mapping) or not bool(bridge.get("enabled", False)):
        raise ClosedLoopFeasibilityError(
            "C0 real-anchor energy recovery requires an enabled bridge or the Phase-5G bridge-retirement flag."
        )

    required_bridge = {
        "inferred_low_case_full_site_ng_floor_pj_y",
        "already_represented_fixed_ng_pj_y",
        "already_represented_fixed_ng_component_id",
        "already_represented_fixed_ng_derivation",
        "flexible_other_site_heat_service_envelope_pj_y",
        "normal_case_flexible_ng_validation_reference_pj_y",
    }
    missing = required_bridge.difference(bridge)
    if missing:
        raise ClosedLoopFeasibilityError(
            f"C0 full-site energy bridge is missing: {sorted(missing)}"
        )
    fixed_target_pj_y = float(bridge["inferred_low_case_full_site_ng_floor_pj_y"])
    already_represented_pj_y = float(bridge["already_represented_fixed_ng_pj_y"])
    overlap_component_id = str(bridge["already_represented_fixed_ng_component_id"]).strip()
    overlap_derivation = str(bridge["already_represented_fixed_ng_derivation"]).strip()
    flexible_service_pj_y = float(
        bridge["flexible_other_site_heat_service_envelope_pj_y"]
    )
    normal_case_flexible_ng_pj_y = float(
        bridge["normal_case_flexible_ng_validation_reference_pj_y"]
    )
    flexible_ng_allocation_policy = str(
        bridge.get("flexible_ng_allocation_policy", "dispatch_endogenous")
    )
    if flexible_ng_allocation_policy not in {
        "dispatch_endogenous",
        "normal_case_reference_exact_hourly",
    }:
        raise ClosedLoopFeasibilityError(
            "Unsupported C0 flexible-heat NG allocation policy: "
            f"{flexible_ng_allocation_policy}"
        )
    if not 8.0 <= fixed_target_pj_y <= 8.12:
        raise ClosedLoopFeasibilityError(
            "The inferred fixed full-site NG component must stay inside 8.0-8.12 PJ/y."
        )
    if not 0.0 <= already_represented_pj_y < 8.0:
        raise ClosedLoopFeasibilityError(
            "Already-represented fixed NG must be non-negative and below the 8.0 PJ/y inferred floor."
        )
    if not overlap_component_id or not overlap_derivation:
        raise ClosedLoopFeasibilityError(
            "Fixed-NG overlap subtraction requires an explicit component id and derivation."
        )
    if already_represented_pj_y == 0.0 and "zero" not in overlap_derivation.lower():
        raise ClosedLoopFeasibilityError(
            "A zero fixed-NG overlap must be stated explicitly in its derivation."
        )
    net_fixed_pj_y = fixed_target_pj_y - already_represented_pj_y
    if (
        abs(flexible_service_pj_y - 3.07) > 1e-9
        or abs(normal_case_flexible_ng_pj_y - 1.65) > 1e-9
    ):
        raise ClosedLoopFeasibilityError(
            "C0 flexible heat must retain the 3.07 PJ/y service envelope and 1.65 PJ/y normal-case validation reference."
        )
    pj_y_to_mwh_h = 1.0 / (HOURS_PER_YEAR * PJ_PER_MWH)
    return (
        resolved_generator,
        {
            "fixed_full_site_ng_component_mwh_h": net_fixed_pj_y * pj_y_to_mwh_h,
            "flexible_other_site_heat_service_envelope_mwh_h": flexible_service_pj_y
            * pj_y_to_mwh_h,
            "normal_case_flexible_ng_validation_reference_mwh_h": normal_case_flexible_ng_pj_y
            * pj_y_to_mwh_h,
            "flexible_ng_allocation_policy": flexible_ng_allocation_policy,
        },
    )


def _electricity_boundary_levers(
    config: Mapping[str, Any]
) -> tuple[float, float | None, float | None, float, dict[str, float]]:
    """Return explicit named electricity additions; unknown site load remains outside dispatch."""

    payload = config.get("represented_electricity_boundary")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    background = float(
        config.get(
            "site_background_electricity_mwh_h",
            payload_mapping.get("site_background_electricity_mwh_h", 0.0),
        )
    )
    raw_background_by_configuration = config.get(
        "site_background_electricity_mwh_h_by_configuration",
        payload_mapping.get("site_background_electricity_mwh_h_by_configuration", {}),
    )
    if not isinstance(raw_background_by_configuration, Mapping):
        raise ClosedLoopFeasibilityError(
            "site_background_electricity_mwh_h_by_configuration must be a mapping."
        )
    background_by_configuration = {
        str(key): float(value) for key, value in raw_background_by_configuration.items()
    }
    unknown = set(background_by_configuration).difference(CONFIGURATIONS)
    if unknown:
        raise ClosedLoopFeasibilityError(
            f"Unknown site-background configuration(s): {sorted(unknown)}."
        )
    resolved_background_by_configuration = {
        configuration: background_by_configuration.get(configuration, background)
        for configuration in CONFIGURATIONS
    }
    if background < 0.0 or any(
        value < 0.0 for value in resolved_background_by_configuration.values()
    ):
        raise ClosedLoopFeasibilityError("Site background electricity must be non-negative.")
    if str(config.get("repair_stage", "none")) != "electricity":
        return 0.0, None, None, background, resolved_background_by_configuration
    if not isinstance(payload, Mapping):
        raise ClosedLoopFeasibilityError(
            "Electricity repair requires represented_electricity_boundary."
        )
    linde_n2 = float(payload.get("linde_n2_auxiliary_mw", -1.0))
    if abs(linde_n2 - 45.0) > 1e-9:
        raise ClosedLoopFeasibilityError(
            "The accepted development Linde N2 auxiliary context must remain 45 MW."
        )
    raw_eaf_secondary = payload.get("eaf_secondary_electricity_mwh_per_t_ls")
    eaf_secondary = None if raw_eaf_secondary in {None, ""} else float(raw_eaf_secondary)
    if eaf_secondary is not None and abs(eaf_secondary - 0.031) > 1e-12:
        raise ClosedLoopFeasibilityError(
            "EAF secondary metallurgy electricity must remain the MER 0.031 MWh/t-LS central value."
        )
    raw_dsp = payload.get("dsp_electricity_mwh_per_t_coil")
    dsp = None if raw_dsp in {None, ""} else float(raw_dsp)
    if dsp is not None and abs(dsp - 0.056) > 1e-12:
        raise ClosedLoopFeasibilityError("DSP electricity must remain the 0.056 MWh/t source-card value.")
    return linde_n2, eaf_secondary, dsp, background, resolved_background_by_configuration


def _site_baseload_ng_levers(config: Mapping[str, Any]) -> dict[str, float]:
    payload = config.get("source_backed_site_baseload")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    raw = config.get(
        "site_baseload_ng_mwh_h_by_configuration",
        payload_mapping.get("site_baseload_ng_mwh_h_by_configuration", {}),
    )
    if not isinstance(raw, Mapping):
        raise ClosedLoopFeasibilityError(
            "site_baseload_ng_mwh_h_by_configuration must be a mapping."
        )
    values = {str(key): float(value) for key, value in raw.items()}
    unknown = set(values).difference(CONFIGURATIONS)
    if unknown:
        raise ClosedLoopFeasibilityError(
            f"Unknown site-baseload NG configuration(s): {sorted(unknown)}."
        )
    if any(value < 0.0 for value in values.values()):
        raise ClosedLoopFeasibilityError(
            "Every configuration-specific site baseload NG value must be non-negative."
        )
    return {configuration: values.get(configuration, 0.0) for configuration in CONFIGURATIONS}


def _site_residual_levers(
    config: Mapping[str, Any], field: str
) -> dict[str, float]:
    raw = config.get(field, {})
    if not isinstance(raw, Mapping):
        raise ClosedLoopFeasibilityError(f"{field} must be a mapping.")
    values = {str(key): float(value) for key, value in raw.items()}
    unknown = set(values).difference(CONFIGURATIONS)
    if unknown:
        raise ClosedLoopFeasibilityError(
            f"Unknown {field} configuration(s): {sorted(unknown)}."
        )
    if any(value < 0.0 for value in values.values()):
        raise ClosedLoopFeasibilityError(f"Every {field} value must be non-negative.")
    return {configuration: values.get(configuration, 0.0) for configuration in CONFIGURATIONS}


def _c1_source_backed_energy_boundary(config: Mapping[str, Any]) -> dict[str, float] | None:
    """Close named C1 DRP/EAF energy rows on their primary MER activity bases."""

    if str(config.get("repair_stage", "none")) != "electricity":
        return None
    payload = config.get("c1_source_backed_energy_boundary")
    if not isinstance(payload, Mapping):
        raise ClosedLoopFeasibilityError(
            "Electricity repair requires c1_source_backed_energy_boundary."
        )
    expected = {
        "drp_ng_gj_per_t_dri": 9.9,
        "drp_electricity_mwh_per_t_dri": 0.3 / 3.6,
        "eaf_arc_electricity_mwh_per_t_liquid_steel": 1.52 / 3.6,
        "eaf_ng_gj_per_t_liquid_steel": 0.05,
        "natural_gas_lhv_mj_per_nm3": 35.8,
    }
    missing = set(expected).difference(payload)
    if missing:
        raise ClosedLoopFeasibilityError(
            f"c1_source_backed_energy_boundary is missing: {sorted(missing)}"
        )
    resolved = {key: float(payload[key]) for key in expected}
    for key, expected_value in expected.items():
        if abs(resolved[key] - expected_value) > 1e-9:
            raise ClosedLoopFeasibilityError(
                f"C1 source-backed energy value {key} must remain {expected_value}, got {resolved[key]}."
            )
    return resolved


def _c0_downstream_routing(
    config: Mapping[str, Any], *, horizon_hours: int, reference_tolerance: float | None = None
) -> tuple[dict[str, Any] | None, dict[str, float] | None]:
    """Build one source-balanced C0 BOF/HSM/DSP interface without reusing raw rows as targets."""

    payload = config.get("c0_downstream_routing")
    if payload is None:
        return None, None
    if not isinstance(payload, Mapping):
        raise ClosedLoopFeasibilityError("c0_downstream_routing must be a mapping when supplied.")
    required = {
        "raw_liquid_steel_mt_y",
        "raw_hsm_final_mt_y",
        "raw_dsp_final_mt_y",
        "bof_hot_metal_t_per_t_liquid_steel",
        "bof_scrap_t_per_t_liquid_steel",
        "annual_bof_scrap_cap_mt_y",
        "dsp_liquid_steel_input_t_per_t_coil",
    }
    missing = required.difference(payload)
    if missing:
        raise ClosedLoopFeasibilityError(
            f"c0_downstream_routing is missing: {sorted(missing)}"
        )
    values = {key: float(payload[key]) for key in required}
    expected = {
        "raw_liquid_steel_mt_y": _anchor_value("c0_public_liquid_steel_7_2"),
        "raw_hsm_final_mt_y": _anchor_value("c0_hsm_wbw_raw_output_5_4"),
        "raw_dsp_final_mt_y": _anchor_value("c0_dsp_raw_output_1_5"),
        "bof_hot_metal_t_per_t_liquid_steel": 0.875,
        "bof_scrap_t_per_t_liquid_steel": 0.208,
        "annual_bof_scrap_cap_mt_y": 1.5,
        "dsp_liquid_steel_input_t_per_t_coil": 1.05,
    }
    for key, expected_value in expected.items():
        if abs(values[key] - expected_value) > 1e-9:
            raise ClosedLoopFeasibilityError(
                f"C0 source-boundary value {key} must remain {expected_value}, got {values[key]}."
            )

    hsm_input_mt_y = (
        values["raw_liquid_steel_mt_y"]
        - values["raw_dsp_final_mt_y"]
        * values["dsp_liquid_steel_input_t_per_t_coil"]
    )
    hsm_input_per_output = hsm_input_mt_y / values["raw_hsm_final_mt_y"]
    if hsm_input_per_output <= 1.0:
        raise ClosedLoopFeasibilityError("Derived C0 HSM input/output factor must exceed one.")

    scale_to_horizon = float(horizon_hours) / HOURS_PER_YEAR * 1_000_000.0
    target_mt_y = float(config["annual_reference_target_mt_y"])
    raw_final_mt_y = values["raw_hsm_final_mt_y"] + values["raw_dsp_final_mt_y"]
    active_scale = target_mt_y / raw_final_mt_y
    central = {
        "bof_liquid_steel": values["raw_liquid_steel_mt_y"] * active_scale,
        "hsm_final_output": values["raw_hsm_final_mt_y"] * active_scale,
        "dsp_final_output": values["raw_dsp_final_mt_y"] * active_scale,
    }
    bands: dict[str, dict[str, float]] = {}
    if reference_tolerance is not None:
        for metric, annual_mt in central.items():
            bands[metric] = {
                "lower_t": annual_mt * (1.0 - reference_tolerance) * scale_to_horizon,
                "upper_t": annual_mt * (1.0 + reference_tolerance) * scale_to_horizon,
            }
    routing = {
        "hsm_final_t_per_t_slab": 1.0 / hsm_input_per_output,
        "hsm_slab_input_t_per_t_hrc": hsm_input_per_output,
        "dsp_liquid_steel_input_t_per_t_coil": values[
            "dsp_liquid_steel_input_t_per_t_coil"
        ],
        "dsp_final_product_horizon_cap_t": values["raw_dsp_final_mt_y"]
        * scale_to_horizon,
        "dsp_final_product_max_t_h": values["raw_dsp_final_mt_y"]
        * 1_000_000.0
        / HOURS_PER_YEAR,
        "bof_hot_metal_t_per_t_liquid_steel": values[
            "bof_hot_metal_t_per_t_liquid_steel"
        ],
        "bof_scrap_t_per_t_liquid_steel": values[
            "bof_scrap_t_per_t_liquid_steel"
        ],
        "bof_total_scrap_horizon_cap_t": values["annual_bof_scrap_cap_mt_y"]
        * scale_to_horizon,
        "bof_total_scrap_max_t_h": values["annual_bof_scrap_cap_mt_y"]
        * 1_000_000.0
        / HOURS_PER_YEAR,
        "raw_anchor_use_policy": "derive_conversion_once_not_three_simultaneous_targets",
    }
    if reference_tolerance is not None:
        routing["reference_validation_bands"] = bands
    return routing, central


def _fixed_reference_definition(
    config: Mapping[str, Any],
    *,
    horizon_hours: int,
    c0_routing: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Resolve governed annual scenario rows to cumulative horizon bands."""

    scenario_id = str(config["fixed_reference_scenario_id"])
    rows = load_fixed_reference_scenario_contract(scenario_id)
    annual_target = float(config["annual_reference_target_mt_y"])
    quota_rows = [
        row for row in rows if row["metric"] == "site_final_product_quota"
    ]
    if len(quota_rows) != 2 or any(
        abs(float(row["active_central_mt_y"]) - annual_target) > 1e-9
        for row in quota_rows
    ):
        raise ClosedLoopFeasibilityError(
            "Fixed-reference scenario quota rows do not match the configured denominator."
        )
    scale_to_horizon = float(horizon_hours) / HOURS_PER_YEAR * 1_000_000.0
    bands: dict[str, dict[str, dict[str, float]]] = {"C0": {}, "C1": {}}
    definition_rows: list[dict[str, Any]] = []
    for row in rows:
        definition_rows.append(
            {
                "scenario_id": scenario_id,
                "configuration": row["configuration"],
                "metric": row["metric"],
                "raw_mer_value_mt_y": _float(row["raw_source_value_mt_y"]),
                "active_scaled_central_mt_y": _float(row["active_central_mt_y"]),
                "annual_band_lower_mt_y": _float(row["annual_lower_mt_y"]),
                "annual_band_upper_mt_y": _float(row["annual_upper_mt_y"]),
                "horizon_band_lower_t": (
                    round(_float(row["annual_lower_mt_y"]) * scale_to_horizon, 6)
                    if row["annual_lower_mt_y"]
                    else ""
                ),
                "horizon_band_upper_t": (
                    round(_float(row["annual_upper_mt_y"]) * scale_to_horizon, 6)
                    if row["annual_upper_mt_y"]
                    else ""
                ),
                "chosen_denominator": "6.75_Mt_y_site_final_product_proxy",
                "scaling_rule": "governed fixed-reference scenario contract",
                "scenario_definition_status": row["scenario_definition_status"],
                "constraint_status": row["constraint_status"],
                "independent_validation_status": row[
                    "independent_validation_status"
                ],
                "source_boundary": row["source_locator"],
            }
        )
        if row["constraint_status"] == "cumulative_reference_band":
            bands[row["configuration"]][row["metric"]] = {
                "lower_t": _float(row["annual_lower_mt_y"]) * scale_to_horizon,
                "upper_t": _float(row["annual_upper_mt_y"]) * scale_to_horizon,
            }
    required_c0 = {"bof_liquid_steel", "hsm_final_output", "dsp_final_output"}
    required_c1 = {
        "bof_liquid_steel",
        "eaf_liquid_steel",
        "hsm_final_output",
        "dsp_final_output",
        "imported_slab",
    }
    if set(bands["C0"]) != required_c0 or set(bands["C1"]) != required_c1:
        raise ClosedLoopFeasibilityError(
            "Fixed-reference scenario does not define the complete C0/C1 route bands."
        )
    c0_resolved = {
        **dict(c0_routing),
        "reference_validation_bands": bands["C0"],
        "fixed_reference_scenario_id": scenario_id,
    }
    return definition_rows, c0_resolved, bands["C1"]


def _reference_definition(
    config: Mapping[str, Any], *, horizon_hours: int
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve raw MER rows to one active-scaled, cumulative-band scenario."""

    reference_mode = config.get("execution_mode", "endogenous_feasibility") == "reference_validation"
    reference_payload = config.get("reference_validation", {})
    reference_tolerance = (
        float(reference_payload["band_relative_tolerance"])
        if reference_mode and isinstance(reference_payload, Mapping)
        else None
    )
    c0_routing, c0_central = _c0_downstream_routing(
        config,
        horizon_hours=horizon_hours,
        reference_tolerance=reference_tolerance,
    )
    if str(config.get("execution_mode", "")).startswith("fixed_reference"):
        return _fixed_reference_definition(
            config,
            horizon_hours=horizon_hours,
            c0_routing=c0_routing,
        )
    if not reference_mode:
        return [], c0_routing, None
    payload = config["reference_validation"]
    required = {
        "band_relative_tolerance",
        "c1_liquid_steel_raw_mt_y",
        "c1_bof_raw_mt_y",
        "c1_eaf_raw_mt_y",
        "c1_hsm_raw_mt_y",
        "c1_dsp_raw_mt_y",
        "c1_imported_slab_raw_mt_y",
    }
    missing = required.difference(payload)
    if missing:
        raise ClosedLoopFeasibilityError(f"reference_validation is missing: {sorted(missing)}")
    raw = {key: float(payload[key]) for key in required if key != "band_relative_tolerance"}
    expected = {
        "c1_liquid_steel_raw_mt_y": _anchor_value("c1_public_liquid_steel_6_8"),
        "c1_hsm_raw_mt_y": _anchor_value("c1_hsm_wbw_raw_output_5_5"),
        "c1_dsp_raw_mt_y": _anchor_value("c1_dsp_raw_output_1_5"),
        "c1_imported_slab_raw_mt_y": _anchor_value("c1_imported_slab_0_6"),
    }
    expected.update({"c1_bof_raw_mt_y": 3.4, "c1_eaf_raw_mt_y": 3.3})
    for key, expected_value in expected.items():
        if abs(raw[key] - expected_value) > 1e-9:
            raise ClosedLoopFeasibilityError(
                f"Reference raw value {key} must remain {expected_value}, got {raw[key]}."
            )
    tolerance = float(payload["band_relative_tolerance"])
    if not 0.0 < tolerance <= 0.02:
        raise ClosedLoopFeasibilityError("Reference band tolerance must be inside (0, 0.02].")
    target_mt_y = float(config["annual_reference_target_mt_y"])
    hsm_input_per_hrc = float(config["hsm_slab_input_t_per_t_hrc"])
    dsp_input_per_coil = float(config.get("dsp_liquid_steel_input_t_per_t_coil", 1.05))

    c1_final_raw = raw["c1_hsm_raw_mt_y"] + raw["c1_dsp_raw_mt_y"]
    c1_scale = target_mt_y / c1_final_raw
    central: dict[str, dict[str, float]] = {
        "C1": {
            "hsm_final_output": raw["c1_hsm_raw_mt_y"] * c1_scale,
            "dsp_final_output": raw["c1_dsp_raw_mt_y"] * c1_scale,
            "imported_slab": raw["c1_imported_slab_raw_mt_y"] * c1_scale,
        },
    }
    c1_endogenous_liquid = (
        central["C1"]["hsm_final_output"] * hsm_input_per_hrc
        + central["C1"]["dsp_final_output"] * dsp_input_per_coil
        - central["C1"]["imported_slab"]
    )
    bof_share = raw["c1_bof_raw_mt_y"] / (raw["c1_bof_raw_mt_y"] + raw["c1_eaf_raw_mt_y"])
    central["C1"]["bof_liquid_steel"] = c1_endogenous_liquid * bof_share
    central["C1"]["eaf_liquid_steel"] = c1_endogenous_liquid * (1.0 - bof_share)
    if c0_central is not None:
        central["C0"] = c0_central

    scale_to_horizon = float(horizon_hours) / HOURS_PER_YEAR * 1_000_000.0
    def bands(configuration: str) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for metric, annual_mt in central[configuration].items():
            result[metric] = {
                "lower_t": annual_mt * (1.0 - tolerance) * scale_to_horizon,
                "upper_t": annual_mt * (1.0 + tolerance) * scale_to_horizon,
            }
        return result

    definition_rows: list[dict[str, Any]] = []
    raw_lookup = {
        ("C1", "bof_liquid_steel"): raw["c1_bof_raw_mt_y"],
        ("C1", "eaf_liquid_steel"): raw["c1_eaf_raw_mt_y"],
        ("C1", "hsm_final_output"): raw["c1_hsm_raw_mt_y"],
        ("C1", "dsp_final_output"): raw["c1_dsp_raw_mt_y"],
        ("C1", "imported_slab"): raw["c1_imported_slab_raw_mt_y"],
    }
    if c0_central is not None:
        raw_lookup.update(
            {
                ("C0", "bof_liquid_steel"): _anchor_value("c0_public_liquid_steel_7_2"),
                ("C0", "hsm_final_output"): _anchor_value("c0_hsm_wbw_raw_output_5_4"),
                ("C0", "dsp_final_output"): _anchor_value("c0_dsp_raw_output_1_5"),
            }
        )
    for configuration, values in central.items():
        for metric, active_value in values.items():
            definition_rows.append(
                {
                    "configuration": configuration,
                    "metric": metric,
                    "raw_mer_value_mt_y": round(raw_lookup[(configuration, metric)], 9),
                    "active_scaled_central_mt_y": round(active_value, 9),
                    "annual_band_lower_mt_y": round(active_value * (1.0 - tolerance), 9),
                    "annual_band_upper_mt_y": round(active_value * (1.0 + tolerance), 9),
                    "horizon_band_lower_t": round(active_value * (1.0 - tolerance) * scale_to_horizon, 6),
                    "horizon_band_upper_t": round(active_value * (1.0 + tolerance) * scale_to_horizon, 6),
                    "chosen_denominator": "6.75_Mt_y_site_final_product_proxy",
                    "scaling_rule": (
                        "raw downstream share scaled by 6.75/(HSM+DSP); route liquid steel then closes governed HSM/DSP/import material boundary"
                    ),
                    "scenario_definition_status": "scenario_definition_excluded_from_validation",
                    "source_boundary": "MER annual rounded reference volumes; cumulative horizon band only",
                }
            )
    return definition_rows, c0_routing, bands("C1")


def _campaign_progress_reference_routing(
    routing: Mapping[str, Any] | None,
    *,
    definition_rows: Collection[Mapping[str, Any]],
    configuration: str,
    executed_rows: Collection[Mapping[str, Any]],
    executed_hours_before: int,
    deadline_hours: Collection[int],
) -> dict[str, Any] | None:
    """Convert local route bands to cumulative campaign-progress bands."""

    if routing is None or routing.get("reference_validation_bands") is None:
        return None if routing is None else dict(routing)
    configuration_label = "C0" if configuration == C0_CONFIGURATION else "C1"
    field_by_metric = {
        C0_CONFIGURATION: {
            "bof_liquid_steel": "C0_BOF_crude_steel_output_t",
            "hsm_final_output": "C0_HSM_final_product_t",
            "dsp_final_output": "C0_DSP_final_product_t",
        },
        C1_CONFIGURATION: {
            "bof_liquid_steel": "C1_BOF_liquid_steel_output_t_h",
            "eaf_liquid_steel": "C1_EAF_liquid_steel_output_t_h",
            "hsm_final_output": "C1_HSM_final_product_output_t",
            "dsp_final_output": "C1_DSP_final_product_output_t",
            "imported_slab": "C1_imported_slab_to_HSM_t_h",
        },
    }[configuration]
    definitions = {
        str(row["metric"]): row
        for row in definition_rows
        if str(row.get("configuration")) == configuration_label
    }
    deadlines = sorted({int(value) for value in deadline_hours})
    if not deadlines:
        raise ClosedLoopFeasibilityError(
            "Campaign-progress route bands require deadline hours."
        )
    rows = [
        row for row in executed_rows
        if row.get("configuration_id") == configuration
    ]
    final_bands: dict[str, dict[str, float]] = {}
    deadline_bands: dict[str, dict[int, dict[str, float]]] = {}
    for metric in routing["reference_validation_bands"]:
        if metric not in definitions or metric not in field_by_metric:
            raise ClosedLoopFeasibilityError(
                f"Campaign-progress route definition is missing for {configuration}/{metric}."
            )
        definition = definitions[metric]
        executed_value = sum(
            float(row.get(field_by_metric[metric]) or 0.0) for row in rows
        )
        annual_lower_t = float(definition["annual_band_lower_mt_y"]) * 1_000_000.0
        annual_upper_t = float(definition["annual_band_upper_mt_y"]) * 1_000_000.0
        metric_deadlines: dict[int, dict[str, float]] = {}
        for deadline in deadlines:
            absolute_hour = int(executed_hours_before) + deadline
            lower_t = max(
                0.0,
                annual_lower_t * absolute_hour / HOURS_PER_YEAR - executed_value,
            )
            upper_t = (
                annual_upper_t * absolute_hour / HOURS_PER_YEAR - executed_value
            )
            if upper_t < lower_t - TOLERANCE_T:
                raise ClosedLoopFeasibilityError(
                    f"Executed {configuration}/{metric} progress is outside the "
                    "remaining campaign band."
                )
            metric_deadlines[deadline] = {
                "lower_t": lower_t,
                "upper_t": max(lower_t, upper_t),
            }
        deadline_bands[metric] = metric_deadlines
        final_bands[metric] = dict(metric_deadlines[deadlines[-1]])
    resolved = dict(routing)
    resolved["reference_validation_bands"] = final_bands
    resolved["reference_deadline_bands"] = deadline_bands
    resolved["reference_band_progress_policy"] = (
        "cumulative_campaign_progress_subtract_executed_route_quantities"
    )
    return resolved


def _downstream_origin_routing(
    config: Mapping[str, Any], *, horizon_hours: int, reference_bands: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    case_id = str(config["c1_boundary_case"])
    annual_cap = 0.0 if case_id == "endogenous_6_75" else float(config.get("imported_slab_annual_cap_mt_y", 0.6))
    if case_id == "mer_site_product" and abs(annual_cap - 0.6) > 1e-12:
        raise ClosedLoopFeasibilityError("Gate 2 MER-site imported slab cap must remain 0.6 Mt/y.")
    values = load_source_values()
    hsm_input_per_hrc = float(
        config.get("hsm_slab_input_t_per_t_hrc", values["hsm_input_per_hrc"])
    )
    dsp_input_per_coil = float(
        config.get(
            "dsp_liquid_steel_input_t_per_t_coil", values["dsp_input_per_coil"]
        )
    )
    if not 1.01 <= hsm_input_per_hrc <= 1.073:
        raise ClosedLoopFeasibilityError(
            "HSM slab input must remain inside the governed 1.01-1.073 t/t Gate-2 development range."
        )
    if not 1.03 <= dsp_input_per_coil <= 1.07:
        raise ClosedLoopFeasibilityError(
            "DSP liquid-steel input must remain inside the governed 1.03-1.07 t/t development range."
        )
    values["hsm_input_per_hrc"] = hsm_input_per_hrc
    values["dsp_input_per_coil"] = dsp_input_per_coil
    routing = build_c1_uniform_import_routing(
        values,
        horizon_hours=horizon_hours,
        imported_slab_annual_cap_mt_y=annual_cap,
        minimize_imported_slab=(
            case_id == "mer_site_product"
            and config.get("execution_mode", "endogenous_feasibility") == "endogenous_feasibility"
        ),
    )
    if reference_bands is not None:
        routing["reference_validation_bands"] = dict(reference_bands)
    return routing


def _scrap_supply_ledger(
    config: Mapping[str, Any], *, horizon_hours: int,
    execution_block_hours: int = 24,
    deadline_hours: Collection[int] | None = None,
) -> dict[str, Any] | None:
    payload = config.get("scrap_supply_ledger")
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ClosedLoopFeasibilityError("scrap_supply_ledger must be a mapping when supplied.")
    required = {
        "annual_site_scrap_cap_t_y",
        "annual_bof_scrap_cap_t_y",
        "annual_eaf_scrap_cap_t_y",
    }
    missing = required.difference(payload)
    if missing:
        raise ClosedLoopFeasibilityError(
            f"scrap_supply_ledger is missing annual caps: {sorted(missing)}"
        )
    annual = {key: float(payload[key]) for key in required}
    if min(annual.values()) < 0.0:
        raise ClosedLoopFeasibilityError("scrap_supply_ledger annual caps must be non-negative.")
    if max(
        annual["annual_bof_scrap_cap_t_y"],
        annual["annual_eaf_scrap_cap_t_y"],
    ) > annual["annual_site_scrap_cap_t_y"] + TOLERANCE_T:
        raise ClosedLoopFeasibilityError(
            "Each route scrap cap must not exceed the site-total annual cap."
        )
    scale = float(horizon_hours) / HOURS_PER_YEAR
    # The static horizon cap already enforces the final deadline. Keep only
    # intermediate rolling caps here to avoid duplicating the same constraint.
    deadlines = (
        [int(value) for value in deadline_hours if int(value) < horizon_hours]
        if deadline_hours is not None
        else range(execution_block_hours, horizon_hours, execution_block_hours)
    )
    ledger = {
        "site_total_scrap_supply_cap_t": annual["annual_site_scrap_cap_t_y"] * scale,
        "bof_scrap_supply_cap_t": annual["annual_bof_scrap_cap_t_y"] * scale,
        "eaf_scrap_supply_cap_t": annual["annual_eaf_scrap_cap_t_y"] * scale,
    }
    if deadlines:
        ledger.update({
            "site_total_scrap_supply_deadline_caps_t": {
            deadline: annual["annual_site_scrap_cap_t_y"] * deadline / HOURS_PER_YEAR
            for deadline in deadlines
            },
            "bof_scrap_supply_deadline_caps_t": {
            deadline: annual["annual_bof_scrap_cap_t_y"] * deadline / HOURS_PER_YEAR
            for deadline in deadlines
            },
            "eaf_scrap_supply_deadline_caps_t": {
            deadline: annual["annual_eaf_scrap_cap_t_y"] * deadline / HOURS_PER_YEAR
            for deadline in deadlines
            },
        })
    return ledger


def _user_authorized_emulation_overlays(
    config: Mapping[str, Any],
    c1_energy_boundary: Mapping[str, float] | None,
) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, float] | None]:
    """Resolve the frozen Checkpoint-4 yield and named-load overlays."""

    raw_yields = config.get("wag_generation_yield_overrides_by_configuration", {})
    raw_scales = config.get(
        "named_process_electricity_intensity_scales_by_configuration", {}
    )
    if not isinstance(raw_yields, Mapping) or not isinstance(raw_scales, Mapping):
        raise ClosedLoopFeasibilityError(
            "User-authorized yield and named-process electricity overlays must be mappings."
        )
    unknown_configurations = (set(raw_yields) | set(raw_scales)).difference(
        CONFIGURATIONS
    )
    if unknown_configurations:
        raise ClosedLoopFeasibilityError(
            f"Unknown user-authorized overlay configuration(s): {sorted(unknown_configurations)}."
        )
    yield_overrides: dict[str, dict[str, float]] = {}
    for configuration, carrier_values in raw_yields.items():
        if not isinstance(carrier_values, Mapping):
            raise ClosedLoopFeasibilityError(
                f"{configuration} WAG yield overrides must be a mapping."
            )
        unknown_carriers = set(carrier_values).difference({"BFG", "COG", "BOFG"})
        if unknown_carriers:
            raise ClosedLoopFeasibilityError(
                f"Unsupported WAG yield carrier(s): {sorted(unknown_carriers)}."
            )
        resolved = {str(key): float(value) for key, value in carrier_values.items()}
        if any(value <= 0.0 for value in resolved.values()):
            raise ClosedLoopFeasibilityError("Every WAG yield override must be positive.")
        yield_overrides[str(configuration)] = resolved

    allowed_processes = {
        C0_CONFIGURATION: {"BF"},
        C1_CONFIGURATION: {"EAF_arc"},
    }
    process_scales: dict[str, dict[str, float]] = {}
    for configuration, process_values in raw_scales.items():
        if not isinstance(process_values, Mapping):
            raise ClosedLoopFeasibilityError(
                f"{configuration} named-process electricity scales must be a mapping."
            )
        unknown_processes = set(process_values).difference(
            allowed_processes[str(configuration)]
        )
        if unknown_processes:
            raise ClosedLoopFeasibilityError(
                f"Unsupported named-process electricity scale(s) for {configuration}: "
                f"{sorted(unknown_processes)}."
            )
        resolved = {str(key): float(value) for key, value in process_values.items()}
        if any(value <= 0.0 for value in resolved.values()):
            raise ClosedLoopFeasibilityError(
                "Every named-process electricity-intensity scale must be positive."
            )
        process_scales[str(configuration)] = resolved

    bf_scales = {
        C0_CONFIGURATION: process_scales.get(C0_CONFIGURATION, {}).get("BF", 1.0),
        C1_CONFIGURATION: 1.0,
    }
    resolved_c1_energy = (
        None if c1_energy_boundary is None else dict(c1_energy_boundary)
    )
    eaf_scale = process_scales.get(C1_CONFIGURATION, {}).get("EAF_arc", 1.0)
    if eaf_scale != 1.0:
        if resolved_c1_energy is None:
            raise ClosedLoopFeasibilityError(
                "EAF-arc electricity scaling requires the existing C1 source-backed energy boundary."
            )
        resolved_c1_energy["eaf_arc_electricity_mwh_per_t_liquid_steel"] *= eaf_scale
    return yield_overrides, bf_scales, resolved_c1_energy


def _model_target_multiplier(config: Mapping[str, Any], plan: Any) -> float:
    """Translate an explicit execution-block quota to the builder's source target basis.

    Existing configurations omit the optional base quota and preserve their
    historical horizon multiplier. Thesis-scale configurations provide the
    source-table 24-hour final-product target explicitly, so the final rolling
    deadline and the model's exact final-product equality use the same basis.
    """
    base_quota = config.get("base_quota_per_execution_block_t")
    if base_quota in (None, ""):
        return float(plan.planning_horizon_hours) / float(plan.execution_block_hours)
    base_value = float(base_quota)
    if base_value <= 0.0:
        raise ClosedLoopFeasibilityError("base_quota_per_execution_block_t must be positive when supplied.")
    return float(plan.total_quota_t) / base_value


def _rolling_production_progress_contract(
    *,
    plan: Any,
    replan_index: int,
    cumulative_before: Mapping[str, float],
    base_target_multiplier: float,
    enabled: bool,
    envelope_fraction: float = 0.005,
    terminal_exact: bool = False,
    central_target_before_t: float | None = None,
    terminal_recoverability_enabled: bool = False,
    recoverable_credit_t: float | None = None,
    exact_deadline_hour: int | None = None,
) -> dict[str, Any]:
    """Carry executed production credit/debt into the next rolling solve.

    The local deadline requirements are the remaining part of the global
    central trajectory.  A separate lexicographic objective targets the next
    executed block after applying the same credit/debt.  Existing fixed-
    reference route bands remain untouched and continue to provide the
    governed +/- envelope without fixing hourly operation or route shares.
    """

    if not 0.0 <= envelope_fraction < 1.0:
        raise ClosedLoopFeasibilityError(
            "Rolling production envelope fraction must lie in [0, 1)."
        )
    deadlines = tuple(sorted(int(hour) for hour in plan.cumulative_deadline_targets_t))
    if not deadlines or deadlines[-1] != int(plan.planning_horizon_hours):
        raise ClosedLoopFeasibilityError(
            "Rolling production progress requires the complete deadline horizon."
        )
    state_by_configuration: dict[str, dict[str, Any]] = {}
    deadline_targets_by_configuration: dict[str, dict[int, float]] = {}
    target_multiplier_by_configuration: dict[str, float] = {}
    progress_target_by_configuration: dict[str, float] = {}
    for configuration in CONFIGURATIONS:
        executed_before = float(cumulative_before.get(configuration, 0.0))
        central_before = (
            float(central_target_before_t)
            if central_target_before_t is not None
            else float(replan_index) * float(plan.quota_per_execution_block_t)
        )
        credit_before = executed_before - central_before
        if enabled:
            targets = {
                deadline: max(
                    0.0,
                    central_before
                    + float(plan.cumulative_deadline_targets_t[deadline])
                    - executed_before,
                )
                for deadline in deadlines
            }
            next_target = targets[int(plan.execution_block_hours)]
            multiplier = (
                float(base_target_multiplier)
                * targets[int(plan.planning_horizon_hours)]
                / float(plan.total_quota_t)
            )
        else:
            targets = {
                int(hour): float(target)
                for hour, target in plan.cumulative_deadline_targets_t.items()
            }
            next_target = float(plan.quota_per_execution_block_t)
            multiplier = float(base_target_multiplier)
        next_central = central_before + float(plan.quota_per_execution_block_t)
        if terminal_exact:
            next_lower = next_central
            next_upper = next_central
        elif terminal_recoverability_enabled:
            margin = (
                float(recoverable_credit_t)
                if recoverable_credit_t is not None
                else float(plan.quota_per_execution_block_t) * envelope_fraction
            )
            next_lower = next_central - margin
            next_upper = next_central + margin
        else:
            next_lower = next_central * (1.0 - envelope_fraction)
            next_upper = next_central * (1.0 + envelope_fraction)
        state_by_configuration[configuration] = {
            "replan_index": replan_index,
            "configuration_id": configuration,
            "executed_before_t": executed_before,
            "central_target_before_t": central_before,
            "carried_credit_before_t": credit_before,
            "carried_debt_before_t": -credit_before,
            "next_execution_target_t": next_target,
            "next_cumulative_central_target_t": next_central,
            "next_cumulative_lower_envelope_t": next_lower,
            "next_cumulative_upper_envelope_t": next_upper,
            "local_horizon_target_t": targets[int(plan.planning_horizon_hours)],
            "progress_state_enabled": enabled,
            "terminal_exact_quota_active": terminal_exact,
            "terminal_exact_deadline_hour": exact_deadline_hour,
        }
        deadline_targets_by_configuration[configuration] = targets
        target_multiplier_by_configuration[configuration] = multiplier
        if enabled:
            progress_target_by_configuration[configuration] = next_target
    return {
        "state_by_configuration": state_by_configuration,
        "deadline_targets_by_configuration_t": deadline_targets_by_configuration,
        "target_multiplier_by_configuration": target_multiplier_by_configuration,
        "progress_target_by_configuration_t": progress_target_by_configuration,
        "progress_lower_bound_by_configuration_t": {
            configuration: max(
                0.0,
                state_by_configuration[configuration][
                    "next_cumulative_lower_envelope_t"
                ]
                - float(cumulative_before.get(configuration, 0.0)),
            )
            for configuration in CONFIGURATIONS
        }
        if enabled and terminal_recoverability_enabled
        else {},
        "progress_upper_bound_by_configuration_t": {
            configuration: max(
                0.0,
                state_by_configuration[configuration][
                    "next_cumulative_upper_envelope_t"
                ]
                - float(cumulative_before.get(configuration, 0.0)),
            )
            for configuration in CONFIGURATIONS
        }
        if enabled and terminal_recoverability_enabled
        else {},
    }


def campaign_terminal_timestamp_plan(
    timing: Mapping[str, Any],
    *,
    remaining_terminal_hours: int,
) -> dict[str, Any]:
    """Truncate a D-D+4 plan to a complete-day campaign endpoint."""

    horizon = int(timing["planning_horizon_hours"])
    remaining = int(remaining_terminal_hours)
    resolved = dict(timing)
    resolved["nominal_planning_horizon_hours"] = horizon
    resolved["campaign_terminal_endpoint_active"] = 0 < remaining <= horizon
    resolved["campaign_terminal_horizon_truncated"] = False
    if remaining > horizon:
        return resolved
    if remaining <= 0:
        raise ClosedLoopFeasibilityError(
            "The campaign terminal must remain after the current replan start."
        )
    deadlines = [
        int(value)
        for value in timing["cumulative_deadline_hours"]
        if int(value) <= remaining
    ]
    if not deadlines or deadlines[-1] != remaining:
        raise ClosedLoopFeasibilityError(
            "Campaign-terminal horizon truncation must end on a complete local "
            "delivery-day boundary."
        )
    day_count = len(deadlines)
    resolved.update(
        {
            "planning_horizon_hours": remaining,
            "cumulative_deadline_hours": deadlines,
            "local_delivery_dates": list(timing["local_delivery_dates"])[
                :day_count
            ],
            "local_delivery_day_hours": list(
                timing["local_delivery_day_hours"]
            )[:day_count],
            "campaign_terminal_horizon_truncated": remaining < horizon,
        }
    )
    return resolved


def _rolling_plans_from_config(
    config: Mapping[str, Any],
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Resolve fixed or timestamp-derived rolling plans before any solve."""

    replan_count = int(config["replan_count"])
    terminal_band_enabled = bool(
        config.get("terminal_inventory_band_by_configuration")
    )
    expected_terminal_policy = (
        "truncate_at_campaign_endpoint_and_replace_cyclic_inventory_equalities"
    )
    if terminal_band_enabled and config.get(
        "terminal_inventory_horizon_policy"
    ) != expected_terminal_policy:
        raise ClosedLoopFeasibilityError(
            "A terminal inventory band requires the governed horizon-truncation "
            "and cyclic-replacement policy."
        )
    if not bool(config.get("timestamped_dplus4_rolling_enabled", False)):
        if terminal_band_enabled:
            raise ClosedLoopFeasibilityError(
                "Campaign-terminal horizon truncation is implemented only for "
                "timestamp-derived D-D+4 plans."
            )
        plan = build_rolling_production_quota_plan(
            planning_horizon_hours=int(config["planning_horizon_hours"]),
            execution_block_hours=int(config["execution_block_hours"]),
            quota_per_execution_block_t=float(
                config["quota_per_execution_block_t"]
            ),
        )
        return [plan] * replan_count, [
            {
                "replan_index": index,
                "planning_horizon_hours": plan.planning_horizon_hours,
                "execution_block_hours": plan.execution_block_hours,
                "cumulative_deadline_hours": ";".join(
                    str(value)
                    for value in sorted(plan.cumulative_deadline_targets_t)
                ),
                "duration_basis": "fixed_hour_contract",
            }
            for index in range(replan_count)
        ]
    if str(config.get("price_series_id")) != "hourly_da_dplus4_point_forecast":
        raise ClosedLoopFeasibilityError(
            "Timestamp-derived plans require the governed D-D+4 price series."
        )
    annual_target_t = float(config["annual_reference_target_mt_y"]) * 1_000_000.0
    quota_per_hour_t = annual_target_t / HOURS_PER_YEAR
    nominal_hourly_quota = float(config["quota_per_execution_block_t"]) / float(
        config["execution_block_hours"]
    )
    if abs(quota_per_hour_t - nominal_hourly_quota) > 1e-6:
        raise ClosedLoopFeasibilityError(
            "Timestamped rolling quota disagrees with the governed annual target."
        )
    plans: list[Any] = []
    timing_rows: list[dict[str, Any]] = []
    executed_hours_before = int(config.get("initial_executed_hours", 0))
    terminal_hours_target = config.get("terminal_executed_hours_target")
    for replan_index in range(replan_count):
        forecast_rows = build_dplus4_forecast_slice(
            forecast_run_root=config.get("forecast_run_root"),
            dataset_split=str(config["forecast_dataset_split"]),
            start_origin_utc=str(config["forecast_start_origin_utc"]),
            replan_index=replan_index,
            planning_horizon_hours=None,
        )
        nominal_timing = dplus4_timestamp_plan(forecast_rows)
        timing = dict(nominal_timing)
        timing["nominal_planning_horizon_hours"] = int(
            nominal_timing["planning_horizon_hours"]
        )
        timing["campaign_terminal_endpoint_active"] = False
        timing["campaign_terminal_horizon_truncated"] = False
        if terminal_band_enabled:
            if terminal_hours_target in {None, ""}:
                raise ClosedLoopFeasibilityError(
                    "A terminal inventory band requires terminal_executed_hours_target."
                )
            timing = campaign_terminal_timestamp_plan(
                nominal_timing,
                remaining_terminal_hours=(
                    int(terminal_hours_target) - executed_hours_before
                ),
            )
        plan = build_timestamped_rolling_production_quota_plan(
            planning_horizon_hours=int(timing["planning_horizon_hours"]),
            execution_block_hours=int(timing["execution_block_hours"]),
            cumulative_deadline_hours=timing["cumulative_deadline_hours"],
            quota_per_hour_t=quota_per_hour_t,
        )
        plans.append(plan)
        timing_rows.append(
            {
                "replan_index": replan_index,
                "forecast_origin_utc": forecast_rows[0]["forecast_origin_utc"],
                "delivery_start_utc": forecast_rows[0][
                    "delivery_timestamp_utc"
                ],
                "delivery_end_utc": forecast_rows[
                    plan.planning_horizon_hours - 1
                ][
                    "delivery_timestamp_utc"
                ],
                "planning_horizon_hours": plan.planning_horizon_hours,
                "nominal_planning_horizon_hours": timing[
                    "nominal_planning_horizon_hours"
                ],
                "execution_block_hours": plan.execution_block_hours,
                "cumulative_deadline_hours": ";".join(
                    str(value)
                    for value in sorted(plan.cumulative_deadline_targets_t)
                ),
                "local_delivery_dates": ";".join(
                    timing["local_delivery_dates"]
                ),
                "local_delivery_day_hours": ";".join(
                    str(value) for value in timing["local_delivery_day_hours"]
                ),
                "duration_basis": "actual_UTC_hours_by_local_delivery_day",
                "campaign_terminal_endpoint_active": timing[
                    "campaign_terminal_endpoint_active"
                ],
                "campaign_terminal_horizon_truncated": timing[
                    "campaign_terminal_horizon_truncated"
                ],
            }
        )
        executed_hours_before += plan.execution_block_hours
    return plans, timing_rows


def terminal_inventory_activation_hour(
    *,
    terminal_executed_hours_target: int,
    executed_hours_so_far: int,
    planning_horizon_hours: int,
) -> int | None:
    """Return the one-based in-plan campaign endpoint when it is reachable."""

    terminal = int(terminal_executed_hours_target)
    executed = int(executed_hours_so_far)
    horizon = int(planning_horizon_hours)
    if terminal <= 0 or executed < 0 or horizon <= 0:
        raise ClosedLoopFeasibilityError(
            "Terminal activation requires positive terminal/horizon hours and non-negative execution."
        )
    remaining = terminal - executed
    return remaining if 0 < remaining <= horizon else None


def _write_unsolved_run(
    *,
    run_directory: Path,
    config: Mapping[str, Any],
    config_file: Path,
    plan: Any,
    report: Mapping[str, Any],
    target_multiplier: float,
) -> dict[str, Any]:
    """Persist a minimal, reproducible infeasibility record instead of raising on empty dispatch."""
    build_audit = list(report.get("configuration_build_audit", []))
    resolved = dict(config)
    resolved["deadline_targets_t"] = plan.cumulative_deadline_targets_t
    resolved["model_target_multiplier"] = target_multiplier
    resolved["annualisation_policy"] = "not run because the thesis-scale physical model did not solve"
    (run_directory / "config_resolved.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    _write_json(run_directory / "input_manifest.json", _input_manifest(config_file))
    _write_json(run_directory / "code_version.json", {"git_commit": report.get("git_commit"), "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_csv(run_directory / "first_window_model_metrics.csv", build_audit)
    _write_csv(run_directory / "rolling_execution.csv", [])
    _write_csv(run_directory / "inventory_handoff.csv", [])
    _write_csv(run_directory / "annual_plant_metrics.csv", [])
    _write_csv(run_directory / "annual_anchor_reconciliation.csv", [])
    _write_csv(run_directory / "validation_checks.csv", [
        {"check_id": "thesis_scale_physical_feasibility", "status": "fail", "evidence": "first_window_model_metrics.csv"},
        {"check_id": "annual_anchor_comparison", "status": "blocked", "evidence": "No annualisation is valid without a solved physical run."},
        {"check_id": "market_terms_disabled", "status": "pass", "evidence": "resolved config"},
    ])
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The thesis-scale quota was infeasible or did not return an accepted solution in the first planning window.\n"
        "- No energy, WAG, NG or CO2 anchor comparison is reported because production scale did not close.\n"
        "- This is a capacity/availability/route feasibility finding; residuals and energy parameters were not used as repair variables.\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": config["run_id"], "status": "fail", "failure_mode": "first_window_not_solved_at_thesis_scale",
        "planning_horizon_hours": plan.planning_horizon_hours, "execution_block_hours": plan.execution_block_hours,
        "quota_per_execution_block_t": plan.quota_per_execution_block_t, "model_target_multiplier": target_multiplier,
        "configuration_build_audit": build_audit, "market_prices_enabled": False,
    }
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": "rolling_feasibility_anchor_reconciliation", "lineage_role": "pre_economics_physical_gate", "output_policy": config.get("output_policy", "minimal"), "status": "fail"})
    return {"run_directory": run_directory, "summary": summary, "execution_rows": [], "anchor_rows": []}


def _window_endpoint_rows(
    hourly_rows: list[dict[str, Any]],
    execution_hours: int,
    configurations: tuple[str, ...] = CONFIGURATIONS,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for configuration in configurations:
        rows = [
            row for row in hourly_rows
            if row.get("configuration_id") == configuration and int(row.get("hour_index", -1)) < execution_hours
        ]
        if not rows:
            raise ClosedLoopFeasibilityError(f"No execution rows available for {configuration}.")
        result[configuration] = max(rows, key=lambda row: int(row["hour_index"]))
    return result


def _next_inventory_overrides(endpoints: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    fields = {
        "coke_store_initial_t": "coke_inventory_t",
        "sinter_store_initial_t": "sinter_inventory_t",
        "hot_iron_store_initial_t": "hot_iron_inventory_t",
        "cold_slab_store_initial_t": "cold_slab_inventory_t",
    }
    output: dict[str, dict[str, float]] = {}
    for configuration, endpoint in endpoints.items():
        values = {
            target: _float(
                endpoint.get(f"{source}_unrounded", endpoint.get(source))
            )
            for target, source in fields.items()
        }
        if configuration == "C1_phase1_BF_BOF_plus_DRP_EAF":
            values["dri_buffer_initial_t"] = _float(
                endpoint.get(
                    "DRI_inventory_t_unrounded",
                    endpoint.get("DRI_inventory_t"),
                )
            )
        output[configuration] = values
    return output


HANDOFF_STATE_SCHEMA_BY_CONFIGURATION = {
    C0_CONFIGURATION: {
        "coke_store_initial_t",
        "sinter_store_initial_t",
        "hot_iron_store_initial_t",
        "cold_slab_store_initial_t",
    },
    C1_CONFIGURATION: {
        "coke_store_initial_t",
        "sinter_store_initial_t",
        "hot_iron_store_initial_t",
        "cold_slab_store_initial_t",
        "dri_buffer_initial_t",
    },
}


def _validate_inventory_handoff_contract(
    rows: Collection[Mapping[str, Any]],
    *,
    replan_count: int,
    phase2_single_window_preflight: bool,
    tolerance: float = TERMINAL_STATE_TOLERANCE_T,
) -> dict[str, Any]:
    """Validate terminal state snapshots and every governed rolling transition."""

    result: dict[str, Any] = {
        "status": "fail",
        "validation_scope": (
            "phase2_single_window_terminal_snapshot_only"
            if phase2_single_window_preflight
            else "complete_multi_window_handoff_chain"
        ),
        "terminal_handoff_snapshot_complete": False,
        "inter_window_handoff_continuity": "fail",
        "checked_transition_count": 0,
        "checked_state_value_count": 0,
        "max_state_residual": 0.0,
        "allowed_state_tolerance_t": tolerance,
        "validation_tolerance_policy": validation_tolerance_policy_contract(),
        "failure_reasons": [],
    }
    if replan_count == 1 and not phase2_single_window_preflight:
        result["validation_scope"] = "invalid_unflagged_single_window"
        result["failure_reasons"].append(
            "one_replan_requires_explicit_phase2_single_window_preflight"
        )
        return result
    if phase2_single_window_preflight and replan_count != 1:
        result["failure_reasons"].append(
            "phase2_single_window_preflight_requires_replan_count_1"
        )
        return result
    expected_keys = {
        (configuration, replan_index)
        for configuration in CONFIGURATIONS
        for replan_index in range(replan_count)
    }
    keyed: dict[tuple[str, int], Mapping[str, Any]] = {}
    try:
        for row in rows:
            key = (str(row["configuration_id"]), int(row["replan_index"]))
            if key in keyed:
                result["failure_reasons"].append(f"duplicate_row:{key}")
            keyed[key] = row
    except (KeyError, TypeError, ValueError) as exc:
        result["failure_reasons"].append(f"invalid_row_key:{type(exc).__name__}")
        return result
    missing = sorted(expected_keys.difference(keyed))
    extra = sorted(set(keyed).difference(expected_keys))
    if missing:
        result["failure_reasons"].append(f"missing_rows:{missing}")
    if extra:
        result["failure_reasons"].append(f"unexpected_rows:{extra}")
    terminal_complete = not missing and not extra and len(keyed) == len(expected_keys)
    parsed: dict[tuple[str, int], tuple[dict[str, float], dict[str, float]]] = {}
    for key in sorted(expected_keys.intersection(keyed)):
        row = keyed[key]
        expected_schema = HANDOFF_STATE_SCHEMA_BY_CONFIGURATION[key[0]]
        try:
            start = json.loads(str(row["start_overrides"]))
            end = json.loads(str(row["next_overrides"]))
            if not isinstance(start, dict) or not isinstance(end, dict):
                raise TypeError("handoff containers must be mappings")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result["failure_reasons"].append(
                f"invalid_handoff_payload:{key}:{type(exc).__name__}"
            )
            terminal_complete = False
            continue
        if set(end) != expected_schema or not end:
            result["failure_reasons"].append(f"incomplete_next_schema:{key}")
            terminal_complete = False
        if key[1] > 0 and set(start) != expected_schema:
            result["failure_reasons"].append(f"incomplete_start_schema:{key}")
        try:
            start_float = {name: float(value) for name, value in start.items()}
            end_float = {name: float(value) for name, value in end.items()}
        except (TypeError, ValueError):
            result["failure_reasons"].append(f"non_numeric_state:{key}")
            terminal_complete = False
            continue
        if not all(math.isfinite(value) for value in end_float.values()):
            result["failure_reasons"].append(f"nonfinite_terminal_state:{key}")
            terminal_complete = False
        if key[1] > 0 and not all(
            math.isfinite(value) for value in start_float.values()
        ):
            result["failure_reasons"].append(f"nonfinite_start_state:{key}")
        parsed[key] = (start_float, end_float)
    result["terminal_handoff_snapshot_complete"] = terminal_complete
    if phase2_single_window_preflight:
        result["inter_window_handoff_continuity"] = "not_applicable"
        result["status"] = "pass" if terminal_complete and not result["failure_reasons"] else "fail"
        return result
    continuity_ok = True
    for configuration in CONFIGURATIONS:
        for replan_index in range(1, replan_count):
            previous = parsed.get((configuration, replan_index - 1))
            current = parsed.get((configuration, replan_index))
            if previous is None or current is None:
                continuity_ok = False
                continue
            previous_end = previous[1]
            current_start = current[0]
            expected_schema = HANDOFF_STATE_SCHEMA_BY_CONFIGURATION[configuration]
            result["checked_transition_count"] += 1
            if set(previous_end) != expected_schema or set(current_start) != expected_schema:
                continuity_ok = False
                continue
            for state in sorted(expected_schema):
                result["checked_state_value_count"] += 1
                residual = abs(previous_end[state] - current_start[state])
                result["max_state_residual"] = max(
                    result["max_state_residual"], residual
                )
                if not math.isfinite(residual) or residual > tolerance:
                    continuity_ok = False
    expected_transitions = len(CONFIGURATIONS) * (replan_count - 1)
    continuity_ok = (
        continuity_ok
        and result["checked_transition_count"] == expected_transitions
        and not any(
            reason.startswith(("incomplete_start_schema", "nonfinite_start_state"))
            for reason in result["failure_reasons"]
        )
    )
    result["inter_window_handoff_continuity"] = (
        "pass" if continuity_ok else "fail"
    )
    result["status"] = (
        "pass"
        if terminal_complete and continuity_ok and not result["failure_reasons"]
        else "fail"
    )
    return result


def _execution_rows(
    report: Mapping[str, Any],
    *,
    replan_index: int,
    execution_hours: int,
    quota_t: float,
    cumulative_before: Mapping[str, float],
    start_overrides: Mapping[str, Mapping[str, float]],
    production_progress_state: Mapping[str, Mapping[str, Any]] | None = None,
    configurations: tuple[str, ...] = CONFIGURATIONS,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    endpoints = _window_endpoint_rows(list(report["hourly_rows"]), execution_hours, configurations)
    next_overrides = _next_inventory_overrides(endpoints)
    rows: list[dict[str, Any]] = []
    for configuration in configurations:
        block = [
            row for row in report["hourly_rows"]
            if row.get("configuration_id") == configuration and int(row.get("hour_index", -1)) < execution_hours
        ]
        produced = sum(
            _float(
                row.get(
                    "final_product_output_t_unrounded",
                    row.get("final_product_output_t"),
                )
            )
            for row in block
        )
        cumulative = float(cumulative_before.get(configuration, 0.0)) + produced
        progress = dict((production_progress_state or {}).get(configuration, {}))
        required = float(
            progress.get(
                "next_cumulative_central_target_t",
                (replan_index + 1) * quota_t,
            )
        )
        lower_envelope = float(
            progress.get("next_cumulative_lower_envelope_t", 0.995 * required)
        )
        upper_envelope = float(
            progress.get("next_cumulative_upper_envelope_t", 1.005 * required)
        )
        next_execution_target = float(
            progress.get("next_execution_target_t", quota_t)
        )
        endpoint = endpoints[configuration]
        material_residuals = _execution_material_residuals(configuration, block)
        imported_slab_t = sum(_float(row.get("C1_imported_slab_to_HSM_t_h")) for row in block)
        origin_input_residual_t = sum(
            _float(row.get("C1_retained_HSM_input_t_h"))
            - _float(row.get("C1_cold_slab_draw_to_HSM_t_h"))
            - _float(row.get("C1_EAF_to_HSM_slab_t_h"))
            - _float(row.get("C1_imported_slab_to_HSM_t_h"))
            for row in block
        )
        wag_residual = max(
            (
                abs(_float(row.get(field)))
                for row in block
                for field in ("BFG_balance_residual_mwh", "COG_balance_residual_mwh", "BOFG_balance_residual_mwh")
            ),
            default=0.0,
        )
        rows.append(
            {
                "replan_index": replan_index,
                "configuration_id": configuration,
                "execution_hours": execution_hours,
                "executed_final_product_t": round(produced, 6),
                "executed_final_product_t_unrounded": produced,
                "cumulative_executed_final_product_t": round(cumulative, 6),
                "cumulative_executed_final_product_t_unrounded": cumulative,
                "cumulative_required_final_product_t": round(required, 6),
                "cumulative_quota_residual_t": round(cumulative - required, 6),
                "quota_status": "pass" if cumulative >= required - TOLERANCE_T else "fail",
                "rolling_progress_state_enabled": str(
                    bool(progress.get("progress_state_enabled", False))
                ).lower(),
                "carried_production_credit_before_t": round(
                    float(progress.get("carried_credit_before_t", 0.0)), 6
                ),
                "carried_production_debt_before_t": round(
                    float(progress.get("carried_debt_before_t", 0.0)), 6
                ),
                "next_execution_progress_target_t": round(
                    next_execution_target, 6
                ),
                "execution_progress_target_residual_t": round(
                    produced - next_execution_target, 6
                ),
                "carried_production_credit_after_t": round(
                    cumulative - required, 6
                ),
                "cumulative_lower_envelope_t": round(lower_envelope, 6),
                "cumulative_upper_envelope_t": round(upper_envelope, 6),
                "cumulative_envelope_status": (
                    "pass"
                    if lower_envelope - TOLERANCE_T
                    <= cumulative
                    <= upper_envelope + TOLERANCE_T
                    else "fail"
                ),
                "start_coke_inventory_t": start_overrides.get(configuration, {}).get("coke_store_initial_t", "base_input"),
                "end_coke_inventory_t": round(_float(endpoint.get("coke_inventory_t")), 6),
                "start_sinter_inventory_t": start_overrides.get(configuration, {}).get("sinter_store_initial_t", "base_input"),
                "end_sinter_inventory_t": round(_float(endpoint.get("sinter_inventory_t")), 6),
                "start_hot_iron_inventory_t": start_overrides.get(configuration, {}).get("hot_iron_store_initial_t", "base_input"),
                "end_hot_iron_inventory_t": round(_float(endpoint.get("hot_iron_inventory_t")), 6),
                "start_cold_slab_inventory_t": start_overrides.get(configuration, {}).get("cold_slab_store_initial_t", "base_input"),
                "end_cold_slab_inventory_t": round(_float(endpoint.get("cold_slab_inventory_t")), 6),
                "start_dri_inventory_t": start_overrides.get(configuration, {}).get("dri_buffer_initial_t", "not_applicable"),
                "end_dri_inventory_t": round(_float(endpoint.get("DRI_inventory_t")), 6),
                "gross_electricity_mwh": round(sum(_float(row.get("gross_electricity_mwh")) for row in block), 6),
                "net_grid_import_mwh": round(sum(_float(row.get("net_grid_import_mwh")) for row in block), 6),
                "represented_ng_nm3": round(sum(_float(row.get("natural_gas_nm3")) for row in block), 6),
                "steam_mwh": round(sum(_float(row.get("steam")) for row in block), 6),
                "wag_generated_mwh": round(sum(_float(row.get("WAG_generated")) for row in block), 6),
                "wag_used_mwh": round(sum(_float(row.get("WAG_used")) for row in block), 6),
                "wag_flared_mwh": round(sum(_float(row.get("WAG_flared")) for row in block), 6),
                "imported_slab_to_hsm_t": round(imported_slab_t, 6),
                "imported_slab_annualised_t_y": round(imported_slab_t * HOURS_PER_YEAR / execution_hours, 6),
                "hsm_origin_input_residual_t": round(origin_input_residual_t, 9),
                "max_abs_material_balance_residual_t": round(max((abs(value) for value in material_residuals.values()), default=0.0), 9),
                "max_abs_carrier_wag_balance_residual_mwh": round(wag_residual, 9),
                **{f"{name}_balance_residual_t": round(value, 9) for name, value in material_residuals.items()},
            }
        )
    return rows, next_overrides


def _execution_material_residuals(configuration: str, block: list[dict[str, Any]]) -> dict[str, float]:
    """Recalculate represented inventory identities over one executed block."""
    if not block:
        return {}
    if configuration == C0_CONFIGURATION:
        flows = {
            "coke": ("coke_inventory_t", ("C0_coke_output_t_h",), ("C0_BF_coke_demand_t_h",)),
            "sinter": ("sinter_inventory_t", ("C0_sinter_output_t_h",), ("C0_BF_sinter_input_t_h",)),
            "hot_iron": ("hot_iron_inventory_t", ("C0_BF_hot_iron_output_t",), ("C0_BOF_hot_iron_input_t_h",)),
            "cold_slab": ("cold_slab_inventory_t", ("C0_BOF_crude_steel_output_t",), ("C0_HSM_input_t_h", "C0_DSP_liquid_steel_input_t")),
        }
    else:
        flows = {
            "coke": ("coke_inventory_t", ("C1_retained_coke_output_t_h",), ("C1_retained_BF_coke_demand_t_h",)),
            "sinter": ("sinter_inventory_t", ("C1_retained_sinter_output_t_h",), ("C1_retained_BF6_sinter_input_t_h",)),
            "hot_iron": ("hot_iron_inventory_t", ("C1_retained_BF_hot_iron_output_t_h",), ("C1_retained_BOF_hot_iron_input_t_h",)),
            "cold_slab": ("cold_slab_inventory_t", ("C1_BOF_to_HSM_slab_t_h",), ("C1_cold_slab_draw_to_HSM_t_h",)),
            "dri": ("DRI_inventory_t", ("C1_DRP_DRI_output_t_h",), ("C1_EAF_activity_t_DRI_h",)),
        }
    residuals: dict[str, float] = {}
    first = block[0]
    last = block[-1]
    for name, (inventory, production_fields, consumption_fields) in flows.items():
        inferred_start = (
            _float(first.get(inventory))
            - sum(_float(first.get(field)) for field in production_fields)
            + sum(_float(first.get(field)) for field in consumption_fields)
        )
        residuals[name] = (
            inferred_start
            + sum(sum(_float(row.get(field)) for field in production_fields) for row in block)
            - sum(sum(_float(row.get(field)) for field in consumption_fields) for row in block)
            - _float(last.get(inventory))
        )
    return residuals


def _annual_model_metrics(hourly_rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    metrics: dict[str, dict[str, Any]] = {}
    plant_rows: list[dict[str, Any]] = []
    plant_fields = {
        "C0_KGF1_input_t_h": "KGF1/coking activity",
        "C0_KGF2_input_t_h": "KGF2/coking activity",
        "C0_sintering_input_t_h": "sinter activity",
        "C0_BF6_sinter_input_t_h": "BF6 sinter input",
        "C0_BF7_sinter_input_t_h": "BF7 sinter input",
        "C0_BOF_hot_iron_input_t_h": "BOF hot-metal input",
        "C0_BOF_scrap_input_t": "BOF external scrap input",
        "C0_BOF_material_loss_t": "BOF material loss",
        "C0_HSM_input_t_h": "HSM slab input",
        "C0_HSM_final_product_t": "HSM final HRC output",
        "C0_HSM_material_loss_t": "HSM governed material loss",
        "C0_DSP_final_product_t": "DSP final coil output",
        "C1_retained_coking_input_t_h": "KGF1/coking activity",
        "C1_retained_sintering_input_t_h": "sinter activity",
        "C1_retained_BF6_sinter_input_t_h": "BF6 sinter input",
        "C1_retained_BOF_hot_iron_input_t_h": "BOF hot-metal input",
        "C1_retained_HSM_input_t_h": "HSM slab input",
        "C1_HSM_final_product_output_t": "HSM final HRC output",
        "C1_HSM_material_loss_t": "HSM governed material loss",
        "C1_DSP_final_product_output_t": "DSP final coil output",
        "C1_DRP_activity_t_pellets_h": "NG-DRP pellet input",
        "C1_EAF_activity_t_DRI_h": "EAF DRI input",
    }
    for configuration in CONFIGURATIONS:
        rows = [row for row in hourly_rows if row.get("configuration_id") == configuration]
        if not rows:
            continue
        executed_hours = len(rows)
        factor = HOURS_PER_YEAR / float(executed_hours)
        def total(field: str) -> float:
            return sum(_float(row.get(field)) for row in rows)
        gross = total("gross_electricity_mwh")
        net = total("net_grid_import_mwh")
        wag_generated = total("WAG_generated")
        wag_used = total("WAG_used")
        wag_flared = total("WAG_flared")
        wag_power = total("WAG_generator_electricity_mwh")
        ng_generator_electricity_mwh = total("NG_generator_electricity_mwh")
        generator_fuel = total("vattenfall_fuel_mwh")
        generator_named_ng_mwh = total("generator_named_ng_mwh")
        generator_total_fuel_mwh = total("generator_total_fuel_mwh")
        generator_electricity_mwh = total("generator_electricity_mwh")
        explicit_wag_co2 = total("WAG_explicit_combustion_co2_t")
        flare_co2 = total("flaring_co2_t")
        drp_ng_mwh = total("DRP_named_NG_mwh")
        if drp_ng_mwh <= 0.0:
            drp_ng_mwh = total("natural_gas_nm3") * 35.8 / 3600.0
        eaf_ng_mwh = total("EAF_named_NG_mwh")
        hsm_ng_mwh = total("NG_to_HSM_mwh")
        pefa_ng_mwh = total("NG_to_PEFA_malerij_mwh") + total("NG_to_PEFA_branderij_mwh")
        boiler_ng_mwh = total("natural_gas_boiler_mwh")
        fixed_bridge_ng_mwh = total("full_site_fixed_ng_component_mwh")
        flexible_bridge_ng_mwh = total("flexible_other_site_heat_ng_mwh")
        site_baseload_ng_mwh = total("site_baseload_ng_mwh")
        represented_ng_mwh = (
            drp_ng_mwh
            + eaf_ng_mwh
            + hsm_ng_mwh
            + pefa_ng_mwh
            + boiler_ng_mwh
            + generator_named_ng_mwh
            + fixed_bridge_ng_mwh
            + flexible_bridge_ng_mwh
            + site_baseload_ng_mwh
        )
        hsm_slab_field = "C0_HSM_input_t_h" if configuration.startswith("C0") else "C1_retained_HSM_input_t_h"
        hsm_output_field = "C0_HSM_final_product_t" if configuration.startswith("C0") else "C1_HSM_final_product_output_t"
        hsm_loss_field = "C0_HSM_material_loss_t" if configuration.startswith("C0") else "C1_HSM_material_loss_t"
        dsp_field = "C0_DSP_final_product_t" if configuration.startswith("C0") else "C1_DSP_final_product_output_t"
        bof_field = "C0_BOF_crude_steel_output_t" if configuration.startswith("C0") else "C1_BOF_liquid_steel_output_t_h"
        eaf_liquid = 0.0 if configuration.startswith("C0") else total("C1_EAF_liquid_steel_output_t_h")
        bof_liquid = total(bof_field)
        named_ng_co2 = represented_ng_mwh * 3.6 * _ng_factor() / 1000.0
        metrics[configuration] = {
            "final_product_proxy_mt_y": total("final_product_output_t") * factor / 1_000_000.0,
            "bof_liquid_steel_mt_y": bof_liquid * factor / 1_000_000.0,
            "eaf_liquid_steel_mt_y": eaf_liquid * factor / 1_000_000.0,
            "endogenous_liquid_steel_mt_y": (bof_liquid + eaf_liquid) * factor / 1_000_000.0,
            "hsm_slab_input_mt_y": total(hsm_slab_field) * factor / 1_000_000.0,
            "hsm_hrc_output_mt_y": total(hsm_output_field) * factor / 1_000_000.0,
            "hsm_material_loss_mt_y": total(hsm_loss_field) * factor / 1_000_000.0,
            "hsm_output_contract_active": (
                not configuration.startswith("C0")
                or total(hsm_loss_field) > TOLERANCE_T
                or total(dsp_field) > TOLERANCE_T
            ),
            "dsp_output_mt_y": total(dsp_field) * factor / 1_000_000.0,
            "dsp_topology_active": total(dsp_field) > TOLERANCE_T,
            "imported_slab_mt_y": total("C1_imported_slab_to_HSM_t_h") * factor / 1_000_000.0,
            "gross_electricity_twh_y": gross * factor / 1_000_000.0,
            "gross_electricity_pj_y": gross * factor * PJ_PER_MWH,
            "average_power_mw": gross / float(executed_hours),
            "net_grid_import_twh_y": net * factor / 1_000_000.0,
            "net_grid_import_pj_y": net * factor * PJ_PER_MWH,
            "wag_generation_twh_y": wag_generated * factor / 1_000_000.0,
            "wag_generation_pj_y": wag_generated * factor * PJ_PER_MWH,
            "wag_use_pj_y": wag_used * factor * PJ_PER_MWH,
            "generator_wag_pj_y": generator_fuel * factor * PJ_PER_MWH,
            "generator_wag_plus_flare_pj_y": (generator_fuel + wag_flared) * factor * PJ_PER_MWH,
            "generator_total_fuel_pj_y": generator_total_fuel_mwh * factor * PJ_PER_MWH,
            "generator_total_fuel_plus_flare_pj_y": (generator_total_fuel_mwh + wag_flared) * factor * PJ_PER_MWH,
            "generator_electricity_twh_y": generator_electricity_mwh * factor / 1_000_000.0,
            "ng_generator_electricity_twh_y": ng_generator_electricity_mwh
            * factor
            / 1_000_000.0,
            "vn25_total_fuel_pj_y": total("VN25_total_fuel_mwh") * factor * PJ_PER_MWH,
            "ij01_total_fuel_pj_y": total("IJ01_total_fuel_mwh") * factor * PJ_PER_MWH,
            "wag_power_twh_y": wag_power * factor / 1_000_000.0,
            "wag_flare_pj_y": wag_flared * factor * PJ_PER_MWH,
            "represented_ng_pj_y": represented_ng_mwh * factor * PJ_PER_MWH,
            "drp_named_ng_pj_y": drp_ng_mwh * factor * PJ_PER_MWH,
            "eaf_named_ng_pj_y": eaf_ng_mwh * factor * PJ_PER_MWH,
            "hsm_named_ng_pj_y": hsm_ng_mwh * factor * PJ_PER_MWH,
            "pefa_named_ng_pj_y": pefa_ng_mwh * factor * PJ_PER_MWH,
            "boiler_named_ng_pj_y": boiler_ng_mwh * factor * PJ_PER_MWH,
            "generator_named_ng_pj_y": generator_named_ng_mwh * factor * PJ_PER_MWH,
            "fixed_bridge_named_ng_pj_y": fixed_bridge_ng_mwh * factor * PJ_PER_MWH,
            "flexible_bridge_named_ng_pj_y": flexible_bridge_ng_mwh * factor * PJ_PER_MWH,
            "site_baseload_named_ng_pj_y": site_baseload_ng_mwh * factor * PJ_PER_MWH,
            "generator_named_ng_available": (
                total("generator_unit_interface_active") > 0.0
                or total("aggregate_generator_technical_interface_active") > 0.0
            ),
            "max_abs_generator_fuel_identity_residual_mwh": max(
                (abs(_float(row.get("generator_fuel_identity_residual_mwh"))) for row in rows),
                default=0.0,
            ),
            "explicit_wag_co2_mt_y": (explicit_wag_co2 + flare_co2) * factor / 1_000_000.0,
            "mode_b_explicit_fuel_co2_mt_y": (
                explicit_wag_co2 + flare_co2 + named_ng_co2
            ) * factor / 1_000_000.0,
            "steam_15bar_kt_y": total("steam_15bar_supply_t") * factor / 1000.0,
            "oxygen_kt_y": total("oxygen_t") * factor / 1000.0,
        }
        for field, plant in plant_fields.items():
            value = total(field)
            if value:
                plant_rows.append(
                    {
                        "configuration_id": configuration,
                        "plant_or_metric": plant,
                        "model_field": field,
                        "executed_blocks_total_t": round(value, 6),
                        "annualised_value_t_y": round(value * factor, 6),
                        "annualisation_basis": f"8760/{executed_hours} from concatenated executed 24-hour blocks",
                        "boundary_status": (
                            "HSM_output_basis_HRC" if "HSM final HRC" in plant
                            else "HSM_input_basis_slab" if "HSM slab" in plant
                            else "HSM_material_loss" if "HSM governed" in plant
                            else "modelled_activity_not_necessarily_public_anchor_denominator"
                        ),
                    }
                )
    return metrics, plant_rows


def _annual_equivalent_views(
    executed_hourly_rows: list[dict[str, Any]],
    planned_horizon_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep startup, stable execution and plan-equivalent annualisations distinct."""

    views = {
        "complete_executed_blocks": executed_hourly_rows,
        "first_block_transient": [
            row for row in executed_hourly_rows if int(row.get("replan_index", -1)) == 0
        ],
        "stable_executed_blocks": [
            row for row in executed_hourly_rows if int(row.get("replan_index", -1)) >= 1
        ],
        "first_planned_168h_horizon": planned_horizon_rows,
    }
    fields = (
        "final_product_proxy_mt_y", "endogenous_liquid_steel_mt_y",
        "bof_liquid_steel_mt_y", "eaf_liquid_steel_mt_y",
        "hsm_slab_input_mt_y", "hsm_material_loss_mt_y", "hsm_hrc_output_mt_y",
        "dsp_output_mt_y", "imported_slab_mt_y",
        "wag_generation_pj_y", "wag_use_pj_y", "generator_wag_pj_y", "wag_flare_pj_y",
        "gross_electricity_twh_y", "wag_power_twh_y", "net_grid_import_twh_y",
        "represented_ng_pj_y", "steam_15bar_kt_y", "mode_b_explicit_fuel_co2_mt_y",
    )
    result: list[dict[str, Any]] = []
    for view_id, rows in views.items():
        metrics, _ = _annual_model_metrics(rows)
        for configuration, values in metrics.items():
            for metric in fields:
                result.append(
                    {
                        "view_id": view_id,
                        "configuration_id": configuration,
                        "metric": metric,
                        "annual_equivalent_value": round(float(values[metric]), 9),
                        "reporting_hours": len([row for row in rows if row.get("configuration_id") == configuration]),
                        "truth_status": "representative_deterministic_annual_equivalent_not_simulated_year",
                        "transient_status": (
                            "startup_transient_only" if view_id == "first_block_transient"
                            else "startup_excluded" if view_id == "stable_executed_blocks"
                            else "includes_startup_transient" if view_id == "complete_executed_blocks"
                            else "planned_horizon_not_executed_calendar"
                        ),
                    }
                )
    return result


def _inventory_effects(executed_hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        selected = [row for row in executed_hourly_rows if row.get("configuration_id") == configuration]
        if not selected:
            continue
        if configuration == C0_CONFIGURATION:
            contracts = {
                "coke": ("coke_inventory_t", ("C0_coke_output_t_h",), ("C0_BF_coke_demand_t_h",)),
                "sinter": ("sinter_inventory_t", ("C0_sinter_output_t_h",), ("C0_BF_sinter_input_t_h",)),
                "hot_iron": ("hot_iron_inventory_t", ("C0_BF_hot_iron_output_t",), ("C0_BOF_hot_iron_input_t_h",)),
                "cold_slab": ("cold_slab_inventory_t", ("C0_BOF_crude_steel_output_t",), ("C0_HSM_input_t_h", "C0_DSP_liquid_steel_input_t")),
            }
        else:
            contracts = {
                "coke": ("coke_inventory_t", ("C1_retained_coke_output_t_h",), ("C1_retained_BF_coke_demand_t_h",)),
                "sinter": ("sinter_inventory_t", ("C1_retained_sinter_output_t_h",), ("C1_retained_BF6_sinter_input_t_h",)),
                "hot_iron": ("hot_iron_inventory_t", ("C1_retained_BF_hot_iron_output_t_h",), ("C1_retained_BOF_hot_iron_input_t_h",)),
                "cold_slab": ("cold_slab_inventory_t", ("C1_BOF_to_HSM_slab_t_h",), ("C1_cold_slab_draw_to_HSM_t_h",)),
                "DRI": ("DRI_inventory_t", ("C1_DRP_DRI_output_t_h",), ("C1_EAF_activity_t_DRI_h",)),
            }
        first = selected[0]
        for inventory, (field, production_fields, consumption_fields) in contracts.items():
            values = [_float(row.get(field)) for row in selected if row.get(field) not in {None, ""}]
            if not values:
                continue
            initial = (
                values[0]
                - sum(_float(first.get(name)) for name in production_fields)
                + sum(_float(first.get(name)) for name in consumption_fields)
            )
            final = values[-1]
            result.append(
                {
                    "configuration_id": configuration,
                    "inventory": inventory,
                    "inferred_initial_inventory_t": round(initial, 6),
                    "final_executed_hour_end_t": round(final, 6),
                    "reported_end_to_end_effect_t": round(final - initial, 6),
                    "boundary_status": "initial inferred from hour-0 material balance; final is last executed hour end",
                }
            )
    return result


def _anchor_value(anchor_id: str) -> float:
    for row in _read_csv(ANCHOR_REGISTER_PATH):
        if row["anchor_id"] == anchor_id:
            value = row.get("converted_value") or row.get("raw_value")
            if value in {None, "", "not_found", "qualitative"}:
                break
            return float(value)
    raise ClosedLoopFeasibilityError(f"Missing numeric anchor value for {anchor_id}.")


def _first_order_full_site_co2_ledger(
    hourly_rows: list[dict[str, Any]],
    *,
    constant_mt_y_by_configuration: Mapping[str, float] | None = None,
    target_mt_y_by_configuration: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build a reporting-only process-factor ledger; never feed it to Mode B."""

    constants = constant_mt_y_by_configuration or {}
    targets = target_mt_y_by_configuration or FIRST_ORDER_FULL_SITE_CO2_TARGET_MT_Y
    result: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        selected = [row for row in hourly_rows if row.get("configuration_id") == configuration]
        if not selected:
            continue
        annualisation_factor = HOURS_PER_YEAR / len(selected)
        subtotal_t = 0.0
        for definition in FIRST_ORDER_PROCESS_CO2_FACTORS:
            activity_field = definition["activity_fields"].get(configuration)
            activity_available = bool(
                activity_field
                and any(activity_field in row and row.get(activity_field) not in {None, ""} for row in selected)
            )
            activity_t_y = (
                sum(_float(row.get(activity_field)) for row in selected) * annualisation_factor
                if activity_available
                else 0.0
            )
            emissions_t_y = activity_t_y * float(definition["factor"])
            subtotal_t += emissions_t_y
            result.append(
                {
                    "configuration_id": configuration,
                    "component": definition["component"],
                    "activity_field": activity_field or "",
                    "annual_activity_t_y": round(activity_t_y, 6),
                    "factor_value": definition["factor"],
                    "factor_unit": definition["unit"],
                    "annual_co2_t_y": round(emissions_t_y, 6),
                    "inclusion_status": "included_selected_activity_factor" if activity_available else "omitted_activity_unavailable",
                    "included_in_mode_b_co2": "false",
                    "feeds_dispatch": "false",
                    "source_locator": definition["source_locator"],
                    "caveat": "Selected diagnostic factor; not Mode-B, ETS-ready, or Tata truth.",
                }
            )
        # 0.286 tCO2/t DRI is a capture-stream coefficient, not direct emissions.
        result.append(
            {
                "configuration_id": configuration,
                "component": "DRP_capture_stream_CO2",
                "activity_field": "C1_DRP_DRI_output_t_h" if configuration == C1_CONFIGURATION else "",
                "annual_activity_t_y": "",
                "factor_value": 0.286,
                "factor_unit": "tCO2_captured/t_DRI",
                "annual_co2_t_y": 0.0,
                "inclusion_status": "excluded_capture_stream_not_direct_CO2",
                "included_in_mode_b_co2": "false",
                "feeds_dispatch": "false",
                "source_locator": "s4_4c5o_a_drp_development_input_rows.csv: DRP_CAPTURED_CO2_T_PER_T_DRI",
                "caveat": "Capture-stream quantity; never added as direct process emissions.",
            }
        )
        target_mt_y = float(targets[configuration])
        subtotal_mt_y = subtotal_t / 1_000_000.0
        if subtotal_mt_y > target_mt_y + 1e-9:
            raise ClosedLoopFeasibilityError(
                f"{configuration} selected process-factor subtotal {subtotal_mt_y:.6f} MtCO2/y "
                f"exceeds target {target_mt_y:.6f}; a negative constant is forbidden."
            )
        constant_mt_y = float(constants.get(configuration, 0.0))
        if constant_mt_y < 0.0:
            raise ClosedLoopFeasibilityError(
                f"{configuration} first-order CO2 constant must be non-negative."
            )
        total_mt_y = subtotal_mt_y + constant_mt_y
        if total_mt_y > target_mt_y + 1e-9:
            raise ClosedLoopFeasibilityError(
                f"{configuration} first-order CO2 subtotal plus constant {total_mt_y:.6f} "
                f"MtCO2/y exceeds configured target {target_mt_y:.6f}."
            )
        result.extend(
            [
                {
                    "configuration_id": configuration,
                    "component": "selected_process_factor_subtotal",
                    "annual_co2_t_y": round(subtotal_t, 6),
                    "annual_co2_mt_y": round(subtotal_mt_y, 9),
                    "target_mt_y": target_mt_y,
                    "constant_share_of_total": 0.0,
                    "inclusion_status": "subtotal_before_nonnegative_constant",
                    "included_in_mode_b_co2": "false",
                    "feeds_dispatch": "false",
                    "caveat": "Validated at or below target before any constant is applied.",
                },
                {
                    "configuration_id": configuration,
                    "component": "explicit_nonnegative_constant",
                    "annual_co2_t_y": round(constant_mt_y * 1_000_000.0, 6),
                    "annual_co2_mt_y": round(constant_mt_y, 9),
                    "target_mt_y": target_mt_y,
                    "constant_share_of_total": round(constant_mt_y / total_mt_y, 9) if total_mt_y else 0.0,
                    "inclusion_status": "explicit_reporting_only_constant",
                    "included_in_mode_b_co2": "false",
                    "feeds_dispatch": "false",
                    "caveat": "Visible configuration-specific constant; never a hidden physical flow.",
                },
                {
                    "configuration_id": configuration,
                    "component": "first_order_full_site_CO2_total",
                    "annual_co2_t_y": round(total_mt_y * 1_000_000.0, 6),
                    "annual_co2_mt_y": round(total_mt_y, 9),
                    "target_mt_y": target_mt_y,
                    "constant_share_of_total": round(constant_mt_y / total_mt_y, 9) if total_mt_y else 0.0,
                    "inclusion_status": "selected_factors_plus_explicit_constant",
                    "included_in_mode_b_co2": "false",
                    "feeds_dispatch": "false",
                    "caveat": "First-order emulation diagnostic only; not Scope 1, ETS-ready, Mode-B, or Tata truth.",
                },
            ]
        )
    return result


def _full_site_coverage_share_rows(
    hourly_rows: list[dict[str, Any]],
    first_order_co2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Report represented versus explicit-bridge coverage for electricity and CO2."""

    result: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        selected = [row for row in hourly_rows if row.get("configuration_id") == configuration]
        if not selected:
            continue
        factor = HOURS_PER_YEAR / len(selected)
        represented_electricity = sum(
            _float(row.get("represented_gross_electricity_before_background_mwh", row.get("gross_electricity_mwh")))
            for row in selected
        ) * factor
        background_electricity = sum(
            _float(row.get("site_background_electricity_mwh")) for row in selected
        ) * factor
        full_electricity = represented_electricity + background_electricity
        subtotal = next(
            (_float(row.get("annual_co2_t_y")) for row in first_order_co2_rows
             if row.get("configuration_id") == configuration and row.get("component") == "selected_process_factor_subtotal"),
            0.0,
        )
        constant = next(
            (_float(row.get("annual_co2_t_y")) for row in first_order_co2_rows
             if row.get("configuration_id") == configuration and row.get("component") == "explicit_nonnegative_constant"),
            0.0,
        )
        for family, represented, bridge, full, unit in (
            ("gross_site_electricity", represented_electricity, background_electricity, full_electricity, "MWh_e/y"),
            ("first_order_full_site_CO2", subtotal, constant, subtotal + constant, "tCO2/y"),
        ):
            result.append(
                {
                    "configuration_id": configuration,
                    "coverage_family": family,
                    "physically_represented_value": round(represented, 6),
                    "explicit_bridge_value": round(bridge, 6),
                    "full_site_emulation_value": round(full, 6),
                    "unit": unit,
                    "physically_represented_share": round(represented / full, 9) if full else 0.0,
                    "explicit_bridge_share": round(bridge / full, 9) if full else 0.0,
                    "coverage_status": "represented_plus_explicit_reporting_bridge",
                    "feeds_dispatch": str(family == "gross_site_electricity").lower(),
                    "caveat": "Coverage share is descriptive and is not evidence of Tata truth.",
                }
            )
    return result


def _parameter_range_exception_report(
    candidate_rows: list[dict[str, Any]],
    *,
    overlay_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Classify candidate values against prior and user-authorized relaxed ranges."""

    definitions = overlay_rows or _read_csv(USER_AUTHORIZED_EMULATION_PARAMETER_OVERLAY_PATH)
    by_id = {str(row["parameter_id"]): row for row in definitions}
    result: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        parameter_id = str(candidate["parameter_id"])
        if parameter_id not in by_id:
            raise ClosedLoopFeasibilityError(f"Unknown emulation parameter_id: {parameter_id}")
        definition = by_id[parameter_id]
        value = float(candidate["candidate_value"])
        prior_low = float(definition["baseline_low"])
        prior_high = float(definition["baseline_high"])
        relaxed_low = float(definition["first_relaxed_low"])
        relaxed_high = float(definition["first_relaxed_high"])
        selected_process = str(candidate.get("selected_process", "")).strip()
        affected_processes = str(definition.get("affected_processes", ""))
        allowed_processes = {item.strip() for item in affected_processes.split(";") if item.strip()}
        selection_rule = str(definition.get("selection_rule", ""))
        normalized_rule = selection_rule.lower()
        requires_named_process = any(
            marker in normalized_rule
            for marker in (
                "exactly one recorded named process",
                "exactly one recorded hsm",
                "one recorded coking-input",
            )
        )
        if requires_named_process and selected_process not in allowed_processes:
            raise ClosedLoopFeasibilityError(
                f"{parameter_id} requires one selected_process from {sorted(allowed_processes)}."
            )
        prior_exception = max(prior_low - value, value - prior_high, 0.0)
        relaxed_exception = max(relaxed_low - value, value - relaxed_high, 0.0)
        status = (
            "within_prior_range"
            if prior_exception == 0.0
            else "within_user_authorized_relaxed_range"
            if relaxed_exception == 0.0
            else "outside_user_authorized_relaxed_range"
        )
        result.append(
            {
                "parameter_id": parameter_id,
                "configuration": candidate.get("configuration", definition.get("configuration", "")),
                "parameter_family": definition.get("parameter_family", ""),
                "selected_process": selected_process,
                "affected_targets": definition.get("affected_targets", ""),
                "affected_processes": affected_processes,
                "selection_rule": selection_rule,
                "baseline_central": definition.get("baseline_central", ""),
                "prior_low": prior_low,
                "prior_high": prior_high,
                "relaxed_low": relaxed_low,
                "relaxed_high": relaxed_high,
                "candidate_value": value,
                "prior_range_exception_magnitude": round(prior_exception, 12),
                "relaxed_range_exception_magnitude": round(relaxed_exception, 12),
                "range_status": status,
                "unit": definition.get("unit", ""),
                "user_authorized_sensitivity": str(prior_exception > 0.0).lower(),
                "source_locator": definition.get("source_locator", ""),
                "caveat": definition.get("caveat", ""),
            }
        )
    return result


def _generator_electricity_reporting_split(
    hourly_rows: list[dict[str, Any]],
) -> dict[str, float]:
    """Attribute solved generator output to WAG and named NG for reporting only."""

    if all("WAG_generator_electricity_mwh" in row for row in hourly_rows):
        wag_generator = sum(_float(row.get("WAG_generator_electricity_mwh")) for row in hourly_rows)
        ng_generator = sum(_float(row.get("NG_generator_electricity_mwh")) for row in hourly_rows)
        total_generator = sum(_float(row.get("total_generator_electricity_mwh")) for row in hourly_rows)
        return {
            "WAG_generator_electricity_mwh": wag_generator,
            "NG_generator_electricity_mwh": ng_generator,
            "generator_internal_electricity_total_mwh": total_generator,
            "sum_identity_residual_mwh": total_generator - wag_generator - ng_generator,
        }

    total_generator = sum(
        _float(row.get("generator_electricity_mwh", row.get("wag_electricity_mwh")))
        for row in hourly_rows
    )
    ng_generator = 0.0
    for row in hourly_rows:
        vn25_fuel = _float(row.get("VN25_total_fuel_mwh"))
        named_ng = _float(row.get("generator_named_ng_mwh"))
        vn25_electricity = _float(row.get("VN25_electricity_mwh"))
        if vn25_fuel > TOLERANCE_T:
            ng_generator += vn25_electricity * named_ng / vn25_fuel
        elif named_ng > TOLERANCE_T:
            raise ClosedLoopFeasibilityError(
                "Cannot attribute named-NG generator electricity without VN25 fuel."
            )
    wag_generator = total_generator - ng_generator
    if wag_generator < -TOLERANCE_T:
        raise ClosedLoopFeasibilityError(
            "Named-NG generator attribution exceeds total generator electricity."
        )
    return {
        "WAG_generator_electricity_mwh": max(0.0, wag_generator),
        "NG_generator_electricity_mwh": ng_generator,
        "generator_internal_electricity_total_mwh": total_generator,
        "sum_identity_residual_mwh": total_generator - wag_generator - ng_generator,
    }


def _annual_physical_boundary_ledger(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annualise solved executed blocks without feeding residuals back to dispatch."""

    rows_out: list[dict[str, Any]] = []
    ng_factor_kg_per_gj = _ng_factor()
    full_site_anchors = {
        C0_CONFIGURATION: {
            "electricity_pj": _anchor_value("c0_official_total_site_electricity_13_7pj_missing"),
            "ng_pj": _anchor_value("c0_full_site_ng_12_5pj_missing"),
            "scope1_mt": _anchor_value("c0_official_scope1_12_6_missing"),
        },
        C1_CONFIGURATION: {
            "electricity_pj": _anchor_value("c1_official_total_site_electricity_17_8pj_missing"),
            "ng_pj": _anchor_value("c1_full_site_ng_46_5pj_missing"),
            "scope1_mt": _anchor_value("c1_official_scope1_8_3_missing"),
        },
    }
    wag_sinks = {
        "BFG": (
            "BFG_to_BF_hot_stove_mwh", "BFG_to_KGF1_mwh", "BFG_to_HSM_mwh",
            "BFG_to_boiler_mwh", "BFG_to_vattenfall_mwh",
            "BFG_to_flexible_other_site_heat_mwh",
        ),
        "COG": (
            "COG_to_KGF1_mwh", "COG_to_KGF2_mwh", "COG_to_sinter_mwh",
            "COG_to_HSM_mwh", "COG_to_PEFA_branderij_mwh", "COG_to_boiler_mwh",
            "COG_to_vattenfall_mwh", "COG_to_flexible_other_site_heat_mwh",
        ),
        "BOFG": (
            "BOFG_to_HSM_mwh", "BOFG_to_PEFA_malerij_mwh", "BOFG_to_boiler_mwh",
            "BOFG_to_vattenfall_mwh", "BOFG_to_flexible_other_site_heat_mwh",
        ),
    }

    for configuration in CONFIGURATIONS:
        selected = [row for row in hourly_rows if row.get("configuration_id") == configuration]
        if not selected:
            continue
        factor = HOURS_PER_YEAR / len(selected)

        def total(field: str) -> float:
            return sum(_float(row.get(field)) for row in selected) * factor

        def add(
            family: str,
            carrier: str,
            role: str,
            component: str,
            value: float | str,
            unit: str,
            boundary: str,
            *,
            physical: bool,
            mode_b: bool = False,
            caveat: str = "",
        ) -> None:
            rows_out.append(
                {
                    "configuration_id": configuration,
                    "ledger_family": family,
                    "carrier_or_material": carrier,
                    "flow_role": role,
                    "component": component,
                    "annual_value": round(value, 6) if isinstance(value, (int, float)) else value,
                    "unit": unit,
                    "boundary_status": boundary,
                    "included_in_physical_balance": str(physical).lower(),
                    "included_in_mode_b_co2": str(mode_b).lower(),
                    "annualisation_basis": f"8760/{len(selected)} from solved executed blocks",
                    "caveat": caveat,
                }
            )

        add("material", "final_product", "output", "site_final_product", total("final_product_output_t"), "t/y", "site_final_product_proxy", physical=True)
        add("material", "liquid_steel", "output", "BOF_liquid_steel", total("C0_BOF_crude_steel_output_t" if configuration == C0_CONFIGURATION else "C1_BOF_liquid_steel_output_t_h"), "t/y", "represented_route_output", physical=True)
        add("material", "liquid_steel", "output", "EAF_liquid_steel", 0.0 if configuration == C0_CONFIGURATION else total("C1_EAF_liquid_steel_output_t_h"), "t/y", "represented_route_output", physical=True)
        add("material", "slab", "input", "HSM_slab_input", total("C0_HSM_input_t_h" if configuration == C0_CONFIGURATION else "C1_retained_HSM_input_t_h"), "t/y", "HSM_input_boundary", physical=True)
        add("material", "HRC", "output", "HSM_final_HRC_output", total("C0_HSM_final_product_t" if configuration == C0_CONFIGURATION else "C1_HSM_final_product_output_t"), "t/y", "HSM_output_boundary", physical=True)
        add("material", "material_loss", "loss", "HSM_governed_material_loss", total("C0_HSM_material_loss_t" if configuration == C0_CONFIGURATION else "C1_HSM_material_loss_t"), "t/y", "HSM_input_minus_output", physical=True)
        add("material", "coil", "output", "DSP_final_output", total("C0_DSP_final_product_t" if configuration == C0_CONFIGURATION else "C1_DSP_final_product_output_t"), "t/y", "DSP_output_boundary", physical=True)
        if configuration == C1_CONFIGURATION:
            add("material", "slab", "external_input", "imported_slab_to_HSM", total("C1_imported_slab_to_HSM_t_h"), "t/y", "governed_import_origin", physical=True)
            add("material", "scrap", "input", "BOF_scrap", total("C1_BOF_scrap_input_t_h"), "t/y", "named_consumer", physical=True)
            add("material", "scrap", "input", "EAF_scrap", total("C1_EAF_scrap_input_t_h"), "t/y", "named_consumer", physical=True)
        else:
            add("material", "scrap", "input", "BOF_external_scrap", total("C0_BOF_scrap_input_t"), "t/y", "source_bound_C0_BOF_recipe", physical=True)
            add("material", "material_loss", "loss", "BOF_material_loss", total("C0_BOF_material_loss_t"), "t/y", "hot_metal_plus_scrap_minus_liquid_steel", physical=True)
            add("material", "material_balance", "accounting_residual", "C0_BOF_input_minus_output_minus_loss", total("C0_BOF_material_balance_residual_t"), "t/y", "must_equal_zero", physical=False)
            add("material", "material_loss", "loss", "DSP_material_loss", total("C0_DSP_material_loss_t"), "t/y", "DSP_input_minus_output", physical=True)

        for carrier, sinks in wag_sinks.items():
            add("WAG", carrier, "generation", f"{carrier}_generated", total(f"{carrier}_generated_mwh"), "MWh_LHV/y", "carrier_specific", physical=True)
            for sink in sinks:
                add("WAG", carrier, "use", sink.removesuffix("_mwh"), total(sink), "MWh_LHV/y", "carrier_specific_named_sink", physical=True)
            add("WAG", carrier, "flare", f"{carrier}_flared", total(f"{carrier}_flared_mwh"), "MWh_LHV/y", "carrier_specific", physical=True)
            add("WAG", carrier, "accounting_residual", f"{carrier}_balance_residual", total(f"{carrier}_balance_residual_mwh"), "MWh_LHV/y", "must_equal_zero", physical=False)

        represented_gross_before_background = (
            total("represented_gross_electricity_before_background_mwh")
            if any("represented_gross_electricity_before_background_mwh" in row for row in selected)
            else total("gross_electricity_mwh")
        )
        site_background_electricity = total("site_background_electricity_mwh")
        gross_electricity = (
            total("gross_total_electricity_mwh")
            if any("gross_total_electricity_mwh" in row for row in selected)
            else total("gross_electricity_mwh")
        )
        generator_split = _generator_electricity_reporting_split(selected)
        wag_generator_electricity = (
            generator_split["WAG_generator_electricity_mwh"] * factor
        )
        ng_generator_electricity = (
            generator_split["NG_generator_electricity_mwh"] * factor
        )
        internal_electricity = (
            generator_split["generator_internal_electricity_total_mwh"] * factor
        )
        gross_grid_import = total("gross_grid_import_mwh") or total("net_grid_import_mwh")
        gross_grid_export = total("gross_grid_export_mwh")
        net_grid = total("net_grid_exchange_mwh") or total("net_grid_import_mwh")
        electricity_residual = (
            gross_electricity - internal_electricity - gross_grid_import + gross_grid_export
        )
        add("electricity", "electricity", "demand", "represented_gross_before_background", represented_gross_before_background, "MWh_e/y", "represented_process_boundary", physical=True)
        add("electricity", "electricity", "demand_bridge", "explicit_site_background_electricity", site_background_electricity, "MWh_e/y", "opt_in_additive_full_site_bridge", physical=True, caveat="Additive; never replaces residual electricity, represented auxiliaries, or Linde N2 load.")
        add("electricity", "electricity", "demand_total", "gross_total_electricity", gross_electricity, "MWh_e/y", "represented_plus_explicit_background", physical=True)
        add("electricity", "electricity", "internal_supply", "WAG_generator_electricity", wag_generator_electricity, "MWh_e/y", "fuel_attributed_reporting_split", physical=True, caveat="WAG-attributed share of solved generator output; not an Athanasiadis calibration target.")
        add("electricity", "electricity", "internal_supply", "NG_generator_electricity", ng_generator_electricity, "MWh_e/y", "fuel_attributed_reporting_split", physical=True, caveat="Named-NG-attributed share of solved VN25 output.")
        add("electricity", "electricity", "internal_supply_total", "generator_internal_electricity_total", internal_electricity, "MWh_e/y", "no_export_internal_offset", physical=True, caveat="Total solved generator output; equals WAG plus named-NG generator electricity.")
        add("electricity", "electricity", "accounting_residual", "generator_electricity_attribution_sum_residual", generator_split["sum_identity_residual_mwh"] * factor, "MWh_e/y", "must_equal_zero", physical=False)
        add("electricity", "electricity", "gross_import", "gross_grid_import", gross_grid_import, "MWh_e/y", "represented_process_boundary", physical=True)
        add("electricity", "electricity", "gross_export", "gross_grid_export", gross_grid_export, "MWh_e/y", "zero_export_active_boundary", physical=True)
        add("electricity", "electricity", "net_exchange", "net_grid_exchange", net_grid, "MWh_e/y", "gross_import_minus_gross_export", physical=True)
        add("electricity", "electricity", "accounting_residual", "gross_total_minus_internal_minus_import_plus_export", electricity_residual, "MWh_e/y", "must_equal_zero", physical=False)
        electricity_buckets = {
            "DRP": ("DRP_electricity_mwh", "named_process_load"),
            "EAF_arc": ("EAF_arc_electricity_mwh", "named_process_load_no_secondary_overlap"),
            "HSM_rolling": ("HSM_rolling_electricity_mwh", "named_controller_load"),
            "DSP": ("DSP_electricity_mwh", "named_process_load_output_basis"),
            "ASU_oxygen": ("ASU_oxygen_electricity_mwh", "oxygen_specific_load"),
            "Linde_N2_auxiliary": ("Linde_N2_auxiliary_electricity_mwh", "separate_nonoxygen_development_load"),
            "KGF_purchased_service": ("KGF_electricity_mwh", "named_process_load"),
            "BOF_OSF": ("BOF_electricity_mwh", "named_process_load"),
            "BF": ("BF_electricity_mwh", "named_process_load"),
            "PEFA": ("PEFA_electricity_mwh", "named_controller_load"),
            "sinter": ("sinter_electricity_mwh", "named_process_load"),
            "EAF_secondary_metallurgy": ("EAF_secondary_electricity_mwh", "named_process_load"),
        }
        for component, (field, boundary) in electricity_buckets.items():
            add(
                "electricity_decomposition",
                "electricity",
                "demand_bucket",
                component,
                total(field),
                "MWh_e/y",
                boundary,
                physical=boundary != "known_not_executable_zero",
                caveat=(
                    "No accepted coefficient; zero is explicit and is not hidden in another bucket."
                    if boundary == "known_not_executable_zero"
                    else ""
                ),
            )
        add("electricity_decomposition", "electricity", "accounting_residual", "gross_minus_named_bucket_sum", total("electricity_bucket_sum_residual_mwh"), "MWh_e/y", "must_equal_zero_when_full_boundary_active", physical=False)
        add("electricity_decomposition", "electricity", "accounting_residual", "Linde_total_minus_ASU_minus_N2", total("linde_split_residual_mwh"), "MWh_e/y", "must_equal_zero", physical=False)
        add("electricity_decomposition", "electricity", "known_not_executable", "represented_boiler_steam_auxiliary_electricity", 0.0, "MWh_e/y", "no_source_accepted_auxiliary_coefficient", physical=False)
        add("electricity_decomposition", "electricity", "known_not_executable", "other_modelled_electricity_overlap_bucket", 0.0, "MWh_e/y", "no_such_active_bucket_in_quota_builder", physical=False)
        add("electricity_decomposition", "electricity", "policy_status", "exact_site_electricity_proxy_active", total("exact_site_electricity_proxy_active"), "h/y", "must_equal_zero_for_repaired_boundary", physical=False)
        full_site_electricity_gap = full_site_anchors[configuration]["electricity_pj"] - gross_electricity * PJ_PER_MWH
        add("electricity", "electricity", "boundary_gap", "full_site_anchor_minus_represented_gross", full_site_electricity_gap, "PJ/y", "partial_provenance_reporting_kpi_not_input", physical=False, caveat="Signed anchor gap; never added as dispatchable load.")

        named_ng = {
            "DRP": total("DRP_named_NG_mwh") or total("natural_gas_nm3") * 35.8 / 3600.0,
            "EAF": total("EAF_named_NG_mwh"),
            "HSM": total("NG_to_HSM_mwh"),
            "PEFA_malerij": total("NG_to_PEFA_malerij_mwh"),
            "PEFA_branderij": total("NG_to_PEFA_branderij_mwh"),
            "boiler": total("natural_gas_boiler_mwh"),
            "VN25_generator": total("generator_named_ng_mwh"),
            "fixed_full_site_component": total("full_site_fixed_ng_component_mwh"),
            "flexible_other_site_heat": total("flexible_other_site_heat_ng_mwh"),
            "source_bounded_site_baseload": total("site_baseload_ng_mwh"),
        }
        for component, amount in named_ng.items():
            add("named_NG", "NG", "use", component, amount, "MWh_LHV/y", "represented_named_consumer", physical=True, mode_b=True)
        named_ng_total = sum(named_ng.values())
        add("named_NG", "NG", "subtotal", "represented_named_NG", named_ng_total, "MWh_LHV/y", "represented_named_consumers_only", physical=True, mode_b=True)
        full_site_ng_gap = full_site_anchors[configuration]["ng_pj"] - named_ng_total * PJ_PER_MWH
        add("named_NG", "NG", "boundary_gap", "full_site_anchor_minus_named_NG", full_site_ng_gap, "PJ/y", "partial_provenance_reporting_kpi_not_input", physical=False, caveat="Signed reporting gap after all represented named NG components; it is not a dispatchable residual or calibration plug.")

        if total("aggregate_generator_technical_interface_active") > 0.0:
            aggregate_fuel = total("vattenfall_fuel_mwh") + total("generator_named_ng_mwh")
            aggregate_electricity = internal_electricity
            add("generator", "mixed_named_fuels", "input", "aggregate_C0_generator_total_fuel", aggregate_fuel, "MWh_LHV/y", "carrier_explicit_900000_Nm3_h_envelope", physical=True)
            add("generator", "electricity", "output", "aggregate_C0_generator_electricity", aggregate_electricity, "MWh_e/y", "fixed_0.345_efficiency_no_export", physical=True)
            add("generator", "conversion_loss", "loss", "aggregate_C0_generator_conversion_loss", aggregate_fuel - aggregate_electricity, "MWh/y", "fuel_minus_electricity", physical=True)
            add("generator", "volume", "unused_envelope", "aggregate_C0_generator_unused_volume", total("aggregate_generator_volume_unused_nm3_h"), "Nm3/y", "technical_envelope_not_annual_fuel_anchor", physical=False)

        if total("generator_unit_interface_active") > 0.0:
            vn25_fuel = total("VN25_total_fuel_mwh")
            vn25_electricity = total("VN25_electricity_mwh")
            vn25_loss = total("VN25_conversion_loss_mwh")
            ij01_fuel = total("IJ01_total_fuel_mwh")
            ij01_electricity = total("IJ01_electricity_mwh")
            ij01_deferred = total("IJ01_deferred_conversion_mwh")
            add("generator", "mixed_named_fuels", "input", "VN25_total_fuel", vn25_fuel, "MWh_LHV/y", "unit_specific_BFG_COG_BOFG_NG", physical=True)
            add("generator", "electricity", "output", "VN25_electricity", vn25_electricity, "MWh_e/y", "0.345_source_bounded_efficiency", physical=True)
            add("generator", "conversion_loss", "loss", "VN25_conversion_loss", vn25_loss, "MWh/y", "fuel_minus_electricity", physical=True)
            add("generator", "energy", "accounting_residual", "VN25_fuel_minus_electricity_minus_loss", vn25_fuel - vn25_electricity - vn25_loss, "MWh/y", "must_equal_zero", physical=False)
            add("generator", "WAG", "input", "IJ01_total_fuel", ij01_fuel, "MWh_LHV/y", "unit_specific_BFG_COG_BOFG_no_NG", physical=True)
            add("generator", "electricity", "output", "IJ01_electricity", ij01_electricity, "MWh_e/y", "quantitative_split_not_source_accepted", physical=True)
            add("generator", "deferred_conversion", "loss", "IJ01_deferred_conversion", ij01_deferred, "MWh/y", "conserved_unallocated_output_split", physical=True)
            add("generator", "energy", "accounting_residual", "IJ01_fuel_minus_electricity_minus_deferred", ij01_fuel - ij01_electricity - ij01_deferred, "MWh/y", "must_equal_zero", physical=False)

        steam_demand = total("steam_15bar_demand_t")
        steam_supply = total("steam_15bar_supply_t")
        steam_unserved = total("steam_15bar_unserved_t")
        add("steam", "steam_15bar", "demand", "represented_steam_demand", steam_demand, "t/y", "represented_15bar_bridge", physical=True)
        add("steam", "steam_15bar", "supply", "represented_steam_supply", steam_supply, "t/y", "represented_15bar_bridge", physical=True)
        add("steam", "steam_15bar", "unserved", "represented_steam_unserved", steam_unserved, "t/y", "must_equal_zero", physical=False)
        add("steam", "steam_15bar", "accounting_residual", "steam_demand_minus_supply_minus_unserved", steam_demand - steam_supply - steam_unserved, "t/y", "must_equal_zero", physical=False)

        wag_combustion_co2 = 0.0
        wag_flare_co2 = 0.0
        for carrier in ("BFG", "COG", "BOFG"):
            combustion = total(f"{carrier}_explicit_combustion_co2_t")
            flare = total(f"{carrier}_flare_co2_t")
            wag_combustion_co2 += combustion
            wag_flare_co2 += flare
            add("Mode_B_CO2", carrier, "combustion", f"{carrier}_represented_sink_oxidation", combustion, "tCO2/y", "point_of_oxidation_once", physical=False, mode_b=True)
            add("Mode_B_CO2", carrier, "flare", f"{carrier}_flare_oxidation", flare, "tCO2/y", "point_of_oxidation_once", physical=False, mode_b=True)
        named_ng_co2 = named_ng_total * 3.6 * ng_factor_kg_per_gj / 1000.0
        explicit_fuel_total = wag_combustion_co2 + wag_flare_co2 + named_ng_co2
        add("Mode_B_CO2", "WAG", "subtotal", "represented_WAG_combustion_and_flare", wag_combustion_co2 + wag_flare_co2, "tCO2/y", "carrier_specific_point_of_oxidation", physical=False, mode_b=True)
        add("Mode_B_CO2", "NG", "subtotal", "represented_named_NG_combustion", named_ng_co2, "tCO2/y", "named_consumers_point_of_oxidation", physical=False, mode_b=True)
        add("Mode_B_CO2", "explicit_fuel", "total", "represented_Mode_B_explicit_fuel", explicit_fuel_total, "tCO2/y", "partial_not_scope1_or_ETS", physical=False, mode_b=True)
        scope1_residual = full_site_anchors[configuration]["scope1_mt"] * 1_000_000.0 - explicit_fuel_total
        add("Mode_B_CO2", "CO2", "boundary_gap", "full_site_Scope1_anchor_minus_Mode_B", scope1_residual, "tCO2/y", "partial_provenance_reporting_kpi_not_input", physical=False, caveat="Signed coverage gap; aggregate process counters are excluded.")
    return rows_out


def _mode_comparison_rows(
    endogenous_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    *,
    endogenous_run_id: str,
    reference_run_id: str,
) -> list[dict[str, Any]]:
    """Compare two solved physical ledgers without reconstructing either run."""

    key_fields = (
        "configuration_id", "ledger_family", "carrier_or_material",
        "flow_role", "component", "unit",
    )
    def keyed(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
        return {
            tuple(str(row.get(field, "")) for field in key_fields): row
            for row in rows
        }

    endogenous = keyed(endogenous_rows)
    reference = keyed(reference_rows)
    result: list[dict[str, Any]] = []
    for key in sorted(set(endogenous) | set(reference)):
        endogenous_row = endogenous.get(key, {})
        reference_row = reference.get(key, {})
        endogenous_value = _float(endogenous_row.get("annual_value"))
        reference_value = _float(reference_row.get("annual_value"))
        delta = reference_value - endogenous_value
        family = key[1]
        role = key[3]
        if role == "accounting_residual":
            interpretation = "numerical_conservation_check"
        elif role == "boundary_gap":
            interpretation = "missing_site_boundary_reporting_residual_not_physical_input"
        elif family == "material":
            interpretation = "production_route_or_downstream_reference_choice"
        elif family == "WAG" and role == "generation":
            interpretation = "production_activity_effect_on_carrier_generation"
        elif family == "WAG":
            interpretation = "carrier_specific_sink_allocation_or_flare_effect"
        elif family == "electricity":
            interpretation = "represented_activity_intensity_or_internal_generation_effect"
        elif family in {"named_NG", "steam", "Mode_B_CO2"}:
            interpretation = "represented_route_activity_or_utility_boundary_effect"
        else:
            interpretation = "represented_boundary_difference"
        result.append(
            {
                "configuration_id": key[0],
                "ledger_family": family,
                "carrier_or_material": key[2],
                "flow_role": role,
                "component": key[4],
                "unit": key[5],
                "endogenous_feasibility_value": round(endogenous_value, 6),
                "mer_reference_validation_value": round(reference_value, 6),
                "reference_minus_endogenous": round(delta, 6),
                "reference_minus_endogenous_pct": (
                    round(100.0 * delta / endogenous_value, 6)
                    if abs(endogenous_value) > TOLERANCE_T else ""
                ),
                "difference_interpretation": interpretation,
                "endogenous_run_id": endogenous_run_id,
                "reference_run_id": reference_run_id,
                "comparison_basis": "same p_af solved seven-block annual physical ledger lineage",
            }
        )
    return result


def _annual_anchor_family_summary(anchor_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in anchor_rows:
        configuration = str(row.get("configuration") or "unclassified")
        family = str(row.get("anchor_category") or "unclassified")
        grouped.setdefault((configuration, family), []).append(row)
    summaries: list[dict[str, Any]] = []
    for (configuration, family), family_rows in sorted(grouped.items()):
        comparable: list[tuple[dict[str, Any], float]] = []
        for row in family_rows:
            if row.get("comparability_status") not in {
                "directly_comparable",
                "partially_comparable_reporting_only",
            }:
                continue
            if row.get("scenario_definition_status") != "validation_candidate":
                continue
            try:
                residual = float(row["signed_residual_pct"])
            except (KeyError, TypeError, ValueError):
                continue
            comparable.append((row, residual))
        primary = [
            (row, residual)
            for row, residual in comparable
            if row.get("comparability_status") == "directly_comparable"
            and row.get("source_rank") == "Rank 1"
            and row.get("use_in_primary_score") == "yes"
        ]
        primary_below = [(row, residual) for row, residual in primary if abs(residual) < 7.5]
        contextual_below = [(row, residual) for row, residual in comparable if abs(residual) < 7.5]
        best = min(comparable, key=lambda item: abs(item[1])) if comparable else None
        summaries.append(
            {
                "configuration": configuration,
                "independent_anchor_family": family,
                "row_count": len(family_rows),
                "comparable_row_count": len(comparable),
                "primary_comparable_row_count": len(primary),
                "primary_pair_below_7_5pct": "yes" if primary_below else "no",
                "contextual_pair_below_7_5pct": "yes" if contextual_below else "no",
                "qualifying_primary_anchor_ids": ";".join(sorted(str(row["anchor_id"]) for row, _ in primary_below)),
                "qualifying_context_anchor_ids": ";".join(sorted(str(row["anchor_id"]) for row, _ in contextual_below)),
                "best_comparable_anchor_id": str(best[0]["anchor_id"]) if best else "",
                "best_absolute_residual_pct": round(abs(best[1]), 6) if best else "",
                "coverage_status": "primary_independent_pair" if primary_below else ("context_only" if contextual_below else "coverage_gap"),
            }
        )
    return summaries


def _annual_accounting_residuals_close(rows: list[dict[str, Any]]) -> bool:
    """Accept only sub-0.01 annual-unit numerical residue after annualisation."""

    return all(
        abs(float(row["annual_value"])) <= ANNUALISED_ACCOUNTING_TOLERANCE_MWH
        for row in rows
        if row["flow_role"] == "accounting_residual"
    )


def _anchor_metric(anchor: Mapping[str, str], values: Mapping[str, Any]) -> dict[str, Any]:
    anchor_id = anchor["anchor_id"]
    metric = anchor["metric"].lower()
    def contract(
        model_metric: str,
        value: float | None,
        unit: str,
        definition: str,
        numerator: str,
        denominator: str,
        boundary: str,
        comparability: str,
        exclusion: str = "",
    ) -> dict[str, Any]:
        return {
            "model_metric": model_metric,
            "model_value": value,
            "model_unit": unit,
            "model_metric_definition": definition,
            "numerator": numerator,
            "denominator": denominator,
            "process_or_site_boundary": boundary,
            "comparability_status": comparability,
            "explicit_exclusion_reason": exclusion,
        }
    if anchor_id in {"c0_public_liquid_steel_7_2", "c1_public_liquid_steel_6_8", "active_steel_target_6_75"}:
        return contract("endogenous_liquid_steel_mt_y", values["endogenous_liquid_steel_mt_y"], "Mt/y", "BOF plus EAF endogenous liquid-steel output", "annual BOF liquid steel + annual EAF liquid steel", "t liquid steel per year", "represented endogenous steelmaking routes", "directly_comparable")
    if "hsm/wbw rolled output" in metric:
        if not values.get("hsm_output_contract_active", False):
            return contract("hsm_hrc_output_mt_y", None, "Mt/y", "HSM final HRC output after governed material conversion", "annual HSM HRC output", "t HRC per year", "C0 downstream output contract absent", "not_comparable", "C0 HSM activity is an executable final-product proxy without an independently evidenced HRC-output conversion in this mode")
        return contract("hsm_hrc_output_mt_y", values["hsm_hrc_output_mt_y"], "Mt/y", "governed final HRC output after slab-to-HRC material conversion", "annual HSM HRC output", "t HRC per year", "HSM final-product boundary", "directly_comparable")
    if "dsp output" in metric:
        if not values.get("dsp_topology_active", False):
            return contract("dsp_output_mt_y", None, "Mt/y", "DSP final coil output", "annual DSP coil output", "t DSP coil per year", "DSP boundary absent", "not_comparable", "no executable DSP route in this configuration/mode")
        return contract("dsp_output_mt_y", values["dsp_output_mt_y"], "Mt/y", "DSP final coil output after governed liquid-steel conversion", "annual DSP coil output", "t DSP coil per year", "DSP final-product boundary", "directly_comparable")
    if "imported slab" in metric:
        return contract("imported_slab_mt_y", values["imported_slab_mt_y"], "Mt/y", "origin-tagged external slab delivered only to HSM", "annual imported slab at site downstream boundary", "t slab per year", "external slab-to-HSM boundary", "directly_comparable")
    if "hsm plus dsp final-product proxy" in metric:
        return contract("final_product_proxy_mt_y", values["final_product_proxy_mt_y"], "Mt/y", "HSM HRC plus DSP coil site-final-product proxy", "annual HSM HRC + DSP coil", "t final product per year", "represented downstream site-product boundary", "directly_comparable")
    if "full-site scope 1" in metric or ("co2" in metric and "full-site" in metric):
        return contract("mode_b_explicit_fuel_co2_mt_y", values["mode_b_explicit_fuel_co2_mt_y"], "MtCO2/y", "represented point-of-oxidation WAG plus named-NG Mode-B subtotal", "represented WAG and named-NG combustion/flare CO2", "tCO2 per year", "partial represented fuel boundary", "partially_comparable_reporting_only", "full Scope-1 includes unrepresented process and fuel boundaries")
    if "co2" in metric:
        return contract("explicit_wag_co2_mt_y", values["explicit_wag_co2_mt_y"], "MtCO2/y", "represented carrier-specific WAG combustion and flare subtotal", "represented WAG sink and flare CO2", "tCO2 per year", "partial WAG point-of-oxidation boundary", "not_comparable", "anchor process/component boundary is not represented separately")
    if "asu" in metric or "oxygen" in metric or "total o2" in metric:
        return contract("oxygen_kt_y", values["oxygen_kt_y"], "kt/y", "represented process oxygen demand", "annual represented oxygen tonnes", "kt oxygen per year", "partial process-utility boundary", "not_comparable", "anchor utility boundary and unit contract are not closed")
    if "grid import" in metric:
        return contract("net_grid_import_pj_y", values["net_grid_import_pj_y"], "PJ/y", "represented gross demand less internal WAG electricity", "annual represented net grid import", "PJ electricity per year", "partial represented electricity boundary", "partially_comparable_reporting_only", "full-site grid boundary and source locator remain incomplete")
    if "electricity" in metric or "electric power" in metric:
        if "generator" in metric or "residual-gas" in metric:
            return contract("wag_power_twh_y", values["wag_power_twh_y"], "TWh/y", "electricity generated from WAG at the aggregate generator interface", "annual internal generator electricity", "TWh_e per year", "aggregate represented WAG-generator output", "partially_comparable_reporting_only", "generator unit split and source boundary are incomplete")
        if "power" in metric:
            return contract("average_power_mw", values["average_power_mw"], "MW", "represented gross electricity divided by reporting hours", "represented gross MWh", "reporting hours", "partial represented electricity boundary", "partially_comparable_reporting_only", "site-total boundary is incomplete")
        anchor_unit = anchor.get("converted_unit") or anchor.get("raw_unit")
        if anchor_unit == "PJ/y":
            return contract("gross_electricity_pj_y", values["gross_electricity_pj_y"], "PJ/y", "represented gross process demand before internal generation offset", "annual represented gross electricity demand", "PJ_e per year", "partial represented electricity boundary", "partially_comparable_reporting_only", "full-site anchor includes unknown/background loads that remain reporting-only")
        return contract("gross_electricity_twh_y", values["gross_electricity_twh_y"], "TWh/y", "represented gross process demand before internal generation offset", "annual represented gross electricity demand", "TWh_e per year", "partial represented electricity boundary", "partially_comparable_reporting_only", "full-site or proxy context is not independent represented-component validation")
    if anchor_id == "c1_drp_ng_27_72":
        return contract("drp_named_ng_pj_y", values["drp_named_ng_pj_y"], "PJ/y", "named DRP reduction plus furnace natural gas", "annual DRP named NG", "PJ_LHV per year", "DRP component boundary", "directly_comparable")
    if anchor_id == "c1_vn25_ng_4_1":
        if not values.get("generator_named_ng_available", False):
            return contract("generator_named_ng_pj_y", None, "PJ/y", "named VN25 natural gas", "annual VN25 named NG", "PJ_LHV per year", "VN25 component boundary absent", "not_comparable", "generator NG and VN25/IJ01 split are not modelled")
        return contract("generator_named_ng_pj_y", values["generator_named_ng_pj_y"], "PJ/y", "named VN25 natural gas at the unit fuel boundary", "annual VN25 named NG", "PJ_LHV per year", "VN25 source-bounded generator interface", "directly_comparable")
    if anchor_id == "c1_generator_total_with_flare_14_6":
        if not values.get("generator_named_ng_available", False):
            return contract("generator_wag_pj_y", values["generator_wag_pj_y"], "PJ/y", "actual WAG sent to aggregate generator interface", "BFG + COG + BOFG to aggregate generator", "PJ_LHV per year", "aggregate generator WAG only", "not_comparable", "anchor includes named generator NG and/or VN25/IJ01 unit split not present in model")
        return contract("generator_total_fuel_plus_flare_pj_y", values["generator_total_fuel_plus_flare_pj_y"], "PJ/y", "VN25 plus IJ01 WAG and named NG plus carrier-specific flare", "annual unit fuel plus flare", "PJ_LHV per year", "C1 unit-specific generator and flare boundary", "directly_comparable")
    if anchor_id == "c1_vn25_total_fuel_13_7":
        if not values.get("generator_named_ng_available", False):
            return contract("generator_wag_pj_y", values["generator_wag_pj_y"], "PJ/y", "actual WAG sent to aggregate generator interface", "BFG + COG + BOFG to aggregate generator", "PJ_LHV per year", "aggregate generator WAG only", "not_comparable", "VN25 unit split is not present in model")
        return contract("vn25_total_fuel_pj_y", values["vn25_total_fuel_pj_y"], "PJ/y", "VN25 BFG plus COG plus BOFG plus named NG", "annual VN25 total fuel", "PJ_LHV per year", "VN25 unit fuel boundary", "directly_comparable")
    if anchor_id == "c1_ij01_total_fuel_0_8":
        if not values.get("generator_named_ng_available", False):
            return contract("generator_wag_pj_y", values["generator_wag_pj_y"], "PJ/y", "actual WAG sent to aggregate generator interface", "BFG + COG + BOFG to aggregate generator", "PJ_LHV per year", "aggregate generator WAG only", "not_comparable", "IJ01 unit split is not present in model")
        return contract("ij01_total_fuel_pj_y", values["ij01_total_fuel_pj_y"], "PJ/y", "IJ01 BFG plus COG plus BOFG; NG prohibited", "annual IJ01 total fuel", "PJ_LHV per year", "IJ01 unit fuel boundary", "directly_comparable")
    if "natural gas" in metric or " ng " in f" {metric} ":
        return contract("represented_ng_pj_y", values["represented_ng_pj_y"], "PJ/y", "subtotal of named represented NG consumers", "DRP + EAF + HSM + PEFA + boiler + generator + fixed bridge + flexible heat bridge named NG", "PJ_LHV per year", "shared represented named-NG subtotal", "partially_comparable_reporting_only", "every represented named NG component is counted once; any remaining signed anchor gap stays reporting-only")
    if anchor_id == "c1_generator_wag_with_flare_10_6":
        return contract("generator_wag_plus_flare_pj_y", values["generator_wag_plus_flare_pj_y"], "PJ/y", "actual BFG/COG/BOFG sent to generator interface plus carrier flare", "generator WAG + WAG flare", "PJ_LHV per year", "aggregate represented generator-WAG boundary", "directly_comparable")
    if "flare" in metric:
        return contract("wag_flare_pj_y", values["wag_flare_pj_y"], "PJ/y", "carrier-specific WAG flare subtotal", "annual BFG + COG + BOFG flare", "PJ_LHV per year", "represented flare boundary", "directly_comparable")
    if "product gas reuse" in metric:
        return contract("wag_use_pj_y", values["wag_use_pj_y"], "PJ/y", "represented carrier-specific WAG use at all named sinks", "annual WAG use", "PJ_LHV per year", "represented sinks, not full site", "partially_comparable_reporting_only", "anchor is site-total context and not exact generator or represented-sink boundary")
    if "wag" in metric or "fuel" in metric:
        return contract("wag_generation_pj_y", values["wag_generation_pj_y"], "PJ/y", "carrier-specific thermal WAG generation", "annual BFG + COG + BOFG generation", "PJ_LHV per year", "represented thermal WAG generation boundary", "not_comparable", "anchor thermal/electric basis or component boundary is not compatible")
    return contract("", None, "", "no mapped represented metric", "", "", "unmapped boundary", "not_comparable", "no explicit metric and boundary contract")


def _anchor_rows(
    metrics: Mapping[str, Mapping[str, Any]],
    *,
    execution_mode: str = "endogenous_feasibility",
    additional_reference_definition_ids: Collection[str] = (),
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    reference_definition_ids = {
        "c1_public_liquid_steel_6_8", "c1_dsp_raw_output_1_5",
        "c1_hsm_wbw_raw_output_5_5", "c1_imported_slab_0_6",
        "c1_final_product_proxy_7_0",
        "c1_ij01_total_fuel_0_8",
    }
    reference_definition_ids.update(additional_reference_definition_ids)
    for anchor in _read_csv(ANCHOR_REGISTER_PATH):
        configuration = anchor["configuration"]
        configurations = (
            ("C0", "C1") if configuration == "both" and anchor["anchor_id"] == "active_steel_target_6_75" else (configuration,)
        )
        if configuration not in {"C0", "C1", "both"}:
            result.append({
                "anchor_id": anchor["anchor_id"], "configuration": configuration,
                "anchor_category": anchor.get("anchor_category", "unclassified"),
                "comparison_status": "out_of_scope_or_generic", "comparability_status": "not_comparable",
                "scenario_definition_status": "validation_candidate",
                "explicit_exclusion_reason": "generic or out-of-scope anchor has no configuration-matched metric",
                "model_metric_definition": "", "numerator": "", "denominator": "",
                "process_or_site_boundary": "out_of_scope", "signed_residual_pct": "", "absolute_residual_pct": "",
                "source_rank": anchor.get("source_trust_rank", ""), "evidence_tier": anchor.get("evidence_tier", ""),
                "anchor_role": anchor.get("anchor_role", ""), "use_in_primary_score": anchor.get("use_in_primary_score", "no"),
                "caveat": anchor["caveat"],
            })
            continue
        for configuration_key in configurations:
            model_configuration = CONFIGURATIONS[0] if configuration_key == "C0" else CONFIGURATIONS[1]
            if model_configuration not in metrics:
                result.append(
                    {
                        "anchor_id": anchor["anchor_id"],
                        "configuration": model_configuration,
                        "anchor_category": anchor["anchor_category"],
                        "anchor_metric": anchor["metric"],
                        "comparison_status": "not_evaluated_no_solved_rolling_execution",
                        "boundary_status": "no_solved_executed_blocks",
                        "caveat": anchor["caveat"],
                    }
                )
                continue
            contract = _anchor_metric(anchor, metrics[model_configuration])
            model_value = contract["model_value"]
            model_unit = contract["model_unit"]
            anchor_value = _float(anchor.get("converted_value") or anchor.get("raw_value")) if (anchor.get("converted_value") or anchor.get("raw_value")) not in {"", "not_found", "qualitative"} else None
            anchor_unit = anchor.get("converted_unit") or anchor.get("raw_unit")
            unit_match = model_value is not None and anchor_value is not None and model_unit == anchor_unit
            scenario_definition = (
                anchor["anchor_id"] == "active_steel_target_6_75"
                or anchor["anchor_id"] in additional_reference_definition_ids
                or (execution_mode == "reference_validation" and anchor["anchor_id"] in reference_definition_ids)
            )
            comparability = "scenario_definition" if scenario_definition else contract["comparability_status"]
            exclusion = (
                "production/reference volume defines this scenario and cannot validate itself"
                if scenario_definition
                else contract["explicit_exclusion_reason"]
            )
            if model_value is not None and anchor_value not in {None, 0.0} and unit_match:
                gap = model_value - anchor_value
                signed_residual_pct = 100.0 * gap / anchor_value
                absolute_residual_pct = abs(signed_residual_pct)
            else:
                gap = ""
                signed_residual_pct = ""
                absolute_residual_pct = ""
            result.append(
                {
                    "anchor_id": anchor["anchor_id"],
                    "configuration": model_configuration,
                    "anchor_category": anchor["anchor_category"],
                    "anchor_metric": anchor["metric"],
                    "anchor_value": anchor_value if anchor_value is not None else "",
                    "anchor_unit": anchor_unit,
                    "model_metric": contract["model_metric"],
                    "model_metric_definition": contract["model_metric_definition"],
                    "numerator": contract["numerator"],
                    "denominator": contract["denominator"],
                    "process_or_site_boundary": contract["process_or_site_boundary"],
                    "model_annualised_value": round(model_value, 8) if model_value is not None else "",
                    "model_unit": model_unit,
                    "gap_model_minus_anchor": round(gap, 8) if gap != "" else "",
                    "signed_residual_pct": round(signed_residual_pct, 6) if signed_residual_pct != "" else "",
                    "absolute_residual_pct": round(absolute_residual_pct, 6) if absolute_residual_pct != "" else "",
                    "comparison_status": comparability,
                    "comparability_status": comparability,
                    "scenario_definition_status": "scenario_definition" if scenario_definition else "validation_candidate",
                    "explicit_exclusion_reason": exclusion,
                    "unit_match": str(unit_match).lower(),
                    "boundary_status": contract["process_or_site_boundary"],
                    "source_rank": anchor["source_trust_rank"],
                    "evidence_tier": anchor["evidence_tier"],
                    "anchor_role": anchor.get("anchor_role", ""),
                    "use_in_primary_score": anchor.get("use_in_primary_score", "no"),
                    "caveat": anchor["caveat"],
                }
            )
    return result


def _annual_origin_ledger(
    hourly_rows: list[dict[str, Any]],
    downstream_routing: Mapping[str, Any],
    *,
    case_id: str,
) -> list[dict[str, Any]]:
    rows = [row for row in hourly_rows if row.get("configuration_id") == C1_CONFIGURATION]
    if not rows:
        return []
    factor = HOURS_PER_YEAR / len(rows)
    total = lambda field: sum(_float(row.get(field)) for row in rows)
    hsm_yield = float(downstream_routing["hsm_final_t_per_t_slab"])
    imported_slab = total("C1_imported_slab_to_HSM_t_h")
    imported_product = imported_slab * hsm_yield
    endogenous_product = (
        hsm_yield
        * (total("C1_cold_slab_draw_to_HSM_t_h") + total("C1_EAF_to_HSM_slab_t_h"))
        + total("C1_DSP_final_product_output_t")
    )
    site_product = total("final_product_output_t")
    hsm_input_residual = total("C1_retained_HSM_input_t_h") - (
        total("C1_cold_slab_draw_to_HSM_t_h")
        + total("C1_EAF_to_HSM_slab_t_h")
        + imported_slab
    )
    final_origin_residual = site_product - endogenous_product - imported_product
    hsm_row_residuals = [
        _float(row.get("C1_retained_HSM_input_t_h"))
        - _float(row.get("C1_cold_slab_draw_to_HSM_t_h"))
        - _float(row.get("C1_EAF_to_HSM_slab_t_h"))
        - _float(row.get("C1_imported_slab_to_HSM_t_h"))
        for row in rows
    ]
    final_row_residuals = [
        _float(row.get("final_product_output_t"))
        - hsm_yield
        * (
            _float(row.get("C1_cold_slab_draw_to_HSM_t_h"))
            + _float(row.get("C1_EAF_to_HSM_slab_t_h"))
            + _float(row.get("C1_imported_slab_to_HSM_t_h"))
        )
        - _float(row.get("C1_DSP_final_product_output_t"))
        for row in rows
    ]
    # Hourly dispatch is intentionally written at six decimal places. Clamp
    # only when every row closes within the corresponding rounding envelope;
    # a material imbalance in any row remains visible.
    if max(map(abs, hsm_row_residuals), default=0.0) <= 2e-6:
        hsm_input_residual = 0.0
    if max(map(abs, final_row_residuals), default=0.0) <= 2e-6:
        final_origin_residual = 0.0
    result = [
        {
            "case_id": case_id,
            "metric": "endogenous_site_final_product",
            "executed_total_t": round(endogenous_product, 6),
            "annualised_value": round(endogenous_product * factor, 6),
            "unit": "t/y",
            "origin": "BOF_and_EAF_endogenous",
            "boundary": "represented_upstream_and_downstream",
        },
        {
            "case_id": case_id,
            "metric": "imported_slab_to_HSM",
            "executed_total_t": round(imported_slab, 6),
            "annualised_value": round(imported_slab * factor, 6),
            "unit": "t/y",
            "origin": "external_imported_slab",
            "boundary": "external_supply_to_HSM_only",
        },
        {
            "case_id": case_id,
            "metric": "site_final_product_from_imported_slab",
            "executed_total_t": round(imported_product, 6),
            "annualised_value": round(imported_product * factor, 6),
            "unit": "t/y",
            "origin": "external_imported_slab",
            "boundary": "after_governed_HSM_conversion",
        },
        {
            "case_id": case_id,
            "metric": "site_final_product",
            "executed_total_t": round(site_product, 6),
            "annualised_value": round(site_product * factor, 6),
            "unit": "t/y",
            "origin": "all_origins",
            "boundary": "rolling_executed_site_product",
        },
        {
            "case_id": case_id,
            "metric": "HSM_origin_input_balance_residual",
            "executed_total_t": round(hsm_input_residual, 9),
            "annualised_value": round(hsm_input_residual * factor, 9),
            "unit": "t/y",
            "origin": "all_HSM_origins",
            "boundary": "identity_check_no_supply",
        },
        {
            "case_id": case_id,
            "metric": "site_final_product_origin_residual",
            "executed_total_t": round(final_origin_residual, 9),
            "annualised_value": round(final_origin_residual * factor, 9),
            "unit": "t/y",
            "origin": "all_product_origins",
            "boundary": "identity_check_no_supply",
        },
    ]
    for metric, unit in (
        ("imported_slab_upstream_site_electricity", "MWh/y"),
        ("imported_slab_upstream_site_WAG", "MWh_LHV/y"),
        ("imported_slab_upstream_site_NG", "MWh_LHV/y"),
        ("imported_slab_upstream_direct_fuel_CO2", "tCO2/y"),
    ):
        result.append(
            {
                "case_id": case_id,
                "metric": metric,
                "executed_total_t": 0.0,
                "annualised_value": 0.0,
                "unit": unit,
                "origin": "external_imported_slab",
                "boundary": "upstream_external_burden_excluded",
            }
        )
    return result


def _annual_c0_downstream_origin_ledger(
    hourly_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Close the endogenous C0 BOF-to-HSM/DSP origin through rolling inventory."""

    rows = [row for row in hourly_rows if row.get("configuration_id") == C0_CONFIGURATION]
    if not rows:
        return []
    factor = HOURS_PER_YEAR / len(rows)
    total = lambda field: sum(_float(row.get(field)) for row in rows)
    first = rows[0]
    inferred_initial_slab = (
        _float(first.get("cold_slab_inventory_t"))
        - _float(first.get("C0_BOF_crude_steel_output_t"))
        + _float(first.get("C0_HSM_input_t_h"))
        + _float(first.get("C0_DSP_liquid_steel_input_t"))
    )
    final_slab = _float(rows[-1].get("cold_slab_inventory_t"))
    slab_inventory_change = final_slab - inferred_initial_slab
    bof_liquid = total("C0_BOF_crude_steel_output_t")
    hsm_input = total("C0_HSM_input_t_h")
    dsp_input = total("C0_DSP_liquid_steel_input_t")
    hsm_output = total("C0_HSM_final_product_t")
    dsp_output = total("C0_DSP_final_product_t")
    final_product = total("final_product_output_t")
    route_residual = bof_liquid - hsm_input - dsp_input - slab_inventory_change
    final_residual = final_product - hsm_output - dsp_output
    previous_inventory = inferred_initial_slab
    hourly_route_residuals: list[float] = []
    hourly_final_residuals: list[float] = []
    for row in rows:
        current_inventory = _float(row.get("cold_slab_inventory_t"))
        hourly_route_residuals.append(
            previous_inventory
            + _float(row.get("C0_BOF_crude_steel_output_t"))
            - _float(row.get("C0_HSM_input_t_h"))
            - _float(row.get("C0_DSP_liquid_steel_input_t"))
            - current_inventory
        )
        hourly_final_residuals.append(
            _float(row.get("final_product_output_t"))
            - _float(row.get("C0_HSM_final_product_t"))
            - _float(row.get("C0_DSP_final_product_t"))
        )
        previous_inventory = current_inventory
    # Dispatch rows are serialized at six decimals. As in the C1 origin
    # ledger, clamp only when every hourly identity is inside that envelope.
    if max(map(abs, hourly_route_residuals), default=0.0) <= 3e-6:
        route_residual = 0.0
    if max(map(abs, hourly_final_residuals), default=0.0) <= 2e-6:
        final_residual = 0.0
    values = (
        ("BOF_liquid_steel_origin", bof_liquid, "source", "endogenous_C0_BOF"),
        ("BOF_to_HSM_slab", hsm_input, "route_input", "endogenous_C0_BOF"),
        ("BOF_to_DSP_liquid_steel", dsp_input, "route_input", "endogenous_C0_BOF"),
        ("HSM_final_product", hsm_output, "route_output", "endogenous_C0_BOF"),
        ("DSP_final_product", dsp_output, "route_output", "endogenous_C0_BOF"),
        ("cold_slab_inventory_change", slab_inventory_change, "inventory_change", "endogenous_C0_BOF"),
        ("BOF_route_origin_residual", route_residual, "accounting_residual", "all_C0_downstream"),
        ("site_final_product_origin_residual", final_residual, "accounting_residual", "all_C0_downstream"),
    )
    return [
        {
            "configuration_id": C0_CONFIGURATION,
            "metric": metric,
            "executed_total_t": round(amount, 9),
            "annualised_value_t_y": round(amount * factor, 9),
            "flow_role": role,
            "origin": origin,
            "boundary": "same_solved_rolling_hours_and_inventory_handoffs",
        }
        for metric, amount, role, origin in values
    ]


def _c1_downstream_capacity_diagnosis(
    *,
    plan: Any,
    target_multiplier: float,
    downstream_routing: Mapping[str, Any],
    source_coke_chain: Mapping[str, float],
    eaf_material_balance: Mapping[str, float] | None,
    bof_material_balance: Mapping[str, float] | None,
    scrap_supply_ledger: Mapping[str, Any] | None,
    solver_time_limit_seconds: float,
    upstream_diagnosis: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Maximise the active first-window C1 model without its quota constraints."""
    inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=plan.planning_horizon_hours,
        target_multiplier=target_multiplier,
        include_retained_bf_bof=True,
    )
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        rolling_production_deadline_targets_t=plan.cumulative_deadline_targets_t,
        fix_c1_hybrid_schedule=False,
        c1_retained_route_policy="quota_driven_topology",
        commitment_granularity="daily_binary_hourly_throughput",
        eaf_material_balance=eaf_material_balance,
        bof_material_balance=bof_material_balance,
        scrap_supply_ledger=scrap_supply_ledger,
        downstream_origin_routing=downstream_routing,
        c1_coke_chain_reconciliation=source_coke_chain,
    )
    model.final_product_fulfilment.deactivate()
    model.rolling_production_deadline.deactivate()
    model.static_price_naive_objective.deactivate()
    model.gate2_capacity_objective = Objective(
        expr=sum(model.final_product_output[t] for t in model.TIME),
        sense=maximize,
    )
    solver_name, solver = _select_solver()
    if solver is None:
        raise ClosedLoopFeasibilityError("No solver is available for the Gate 2 capacity diagnosis.")
    _apply_solver_time_limit(solver_name, solver, solver_time_limit_seconds)
    import time

    start = time.perf_counter()
    result = solver.solve(model)
    runtime = time.perf_counter() - start
    termination = str(result.solver.termination_condition)
    if termination.lower() not in {"optimal", "feasible"}:
        raise ClosedLoopFeasibilityError(f"Gate 2 capacity diagnosis did not solve: {termination}")

    total = lambda component: sum(float(value(component[t])) for t in model.TIME)
    maximum_final_product_t = total(model.final_product_output)
    imported_slab_t = total(model.imported_slab_to_hsm)
    imported_cap_t = float(downstream_routing["imported_slab_horizon_cap_t"])
    imported_final_product_t = imported_slab_t * float(downstream_routing["hsm_final_t_per_t_slab"])
    dsp_final_product_t = total(model.dsp_final_product_output)
    dsp_cap_t = float(downstream_routing["dsp_final_product_horizon_cap_t"])
    hsm_input_t = total(model.hot_strip_mill)
    bof_liquid_steel_t = float(value(model.bof_liquid_steel_total))
    eaf_liquid_steel_t = float(value(model.eaf_liquid_steel_total))
    endogenous_liquid_steel_t = float(value(model.endogenous_liquid_steel_total))
    site_scrap_t = float(value(model.site_scrap_supply_total_t))
    bof_scrap_t = total(model.bof_scrap_supply_t)
    eaf_scrap_t = total(model.eaf_scrap_supply_t) if hasattr(model, "eaf_scrap_supply_t") else total(model.scrap_t)
    retained = inputs.retained_bf_bof
    if retained is None:
        raise ClosedLoopFeasibilityError("Gate 2 C1 diagnosis requires the retained BF-BOF route.")
    hsm_capacity_t = retained.process_limits["hot_strip_mill"][1] * plan.planning_horizon_hours
    upstream_max_t = 0.0
    upstream_shortfall_t = 0.0
    if upstream_diagnosis is not None:
        upstream_max_t = float(
            upstream_diagnosis.get("component_final_product_upper_envelopes_t", {}).get(
                "combined_terminal_balanced", 0.0
            )
        )
        conflicts = list(upstream_diagnosis.get("conflicts", []))
        if conflicts:
            upstream_shortfall_t = float(conflicts[0].get("capacity_shortfall_t", 0.0))
    delivered_endogenous_t = maximum_final_product_t - imported_final_product_t
    additional_downstream_loss_t = max(0.0, upstream_max_t - delivered_endogenous_t)
    first_block_final_t = sum(float(value(model.final_product_output[t])) for t in range(plan.execution_block_hours))
    first_block_import_t = sum(float(value(model.imported_slab_to_hsm[t])) for t in range(plan.execution_block_hours))
    terminal_inventory_residuals = {
        "dri_t": float(value(model.dri_inventory[plan.planning_horizon_hours - 1])) - inputs.dri_buffer_initial_t,
        "coke_t": float(value(model.coke_inventory[plan.planning_horizon_hours - 1])) - retained.coke_store_initial_t,
        "sinter_t": float(value(model.sinter_inventory[plan.planning_horizon_hours - 1])) - retained.sinter_store_initial_t,
        "hot_iron_t": float(value(model.hot_iron_inventory[plan.planning_horizon_hours - 1])) - retained.hot_iron_store_initial_t,
        "cold_slab_t": float(value(model.cold_slab_inventory[plan.planning_horizon_hours - 1])) - retained.cold_slab_store_initial_t,
    }
    max_abs_wag_residual_mwh = max(
        abs(float(value(component[t])))
        for component in (
            model.bfg_balance_residual,
            model.cog_balance_residual,
            model.bofg_balance_residual,
        )
        for t in model.TIME
    )
    max_abs_hsm_origin_residual_t = max(
        abs(
            float(value(model.hot_strip_mill[t]))
            - float(value(model.cold_slab_draw_to_hsm[t]))
            - float(value(model.eaf_to_hsm_slab[t]))
            - float(value(model.imported_slab_to_hsm[t]))
        )
        for t in model.TIME
    )
    stats = collect_model_stats(model)
    binding_constraints: list[str] = []
    if scrap_supply_ledger is None:
        binding_constraints.append("retained_BF6_and_DRP_endogenous_capacity_envelopes")
    else:
        for key, realised in (
            ("site_total_scrap_supply_cap_t", site_scrap_t),
            ("bof_scrap_supply_cap_t", bof_scrap_t),
            ("eaf_scrap_supply_cap_t", eaf_scrap_t),
        ):
            if abs(realised - float(scrap_supply_ledger[key])) <= TOLERANCE_T:
                binding_constraints.append(key)
    if abs(dsp_final_product_t - dsp_cap_t) <= TOLERANCE_T:
        binding_constraints.append("DSP_1.5_Mt_y_horizon_cap")
    if abs(imported_slab_t - imported_cap_t) <= TOLERANCE_T:
        binding_constraints.append("imported_slab_0.6_Mt_y_horizon_cap")
    binding_constraints.append(
        f"HSM_{1.0 / float(downstream_routing['hsm_final_t_per_t_slab']):.6g}_t_slab_per_t_final_conversion"
    )
    return {
        "diagnosis_status": "focused_active_model_capacity_proof",
        "solver_name": solver_name,
        "solver_status": str(result.solver.status),
        "termination_condition": termination,
        "runtime_seconds": round(runtime, 6),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "planning_horizon_hours": plan.planning_horizon_hours,
        "quota_target_t": round(inputs.final_product_target_t, 6),
        "maximum_site_final_product_t": round(maximum_final_product_t, 6),
        "remaining_shortfall_t": round(inputs.final_product_target_t - maximum_final_product_t, 6),
        "annualised_maximum_site_final_product_mt_y": round(maximum_final_product_t * HOURS_PER_YEAR / plan.planning_horizon_hours / 1_000_000.0, 9),
        "annualised_remaining_shortfall_t_y": round((inputs.final_product_target_t - maximum_final_product_t) * HOURS_PER_YEAR / plan.planning_horizon_hours, 6),
        "original_endogenous_final_proxy_capacity_t": round(upstream_max_t, 6),
        "original_endogenous_shortfall_t": round(upstream_shortfall_t, 6),
        "imported_slab_t": round(imported_slab_t, 6),
        "imported_slab_cap_t": round(imported_cap_t, 6),
        "imported_final_product_after_hsm_yield_t": round(imported_final_product_t, 6),
        "original_shortfall_covered_after_hsm_yield": imported_final_product_t >= upstream_shortfall_t - TOLERANCE_T,
        "delivered_endogenous_product_after_downstream_conversion_t": round(delivered_endogenous_t, 6),
        "additional_downstream_conversion_loss_vs_original_proxy_t": round(additional_downstream_loss_t, 6),
        "dsp_final_product_t": round(dsp_final_product_t, 6),
        "dsp_horizon_cap_t": round(dsp_cap_t, 6),
        "hsm_input_t": round(hsm_input_t, 6),
        "hsm_input_capacity_t": round(hsm_capacity_t, 6),
        "bof_liquid_steel_t": round(bof_liquid_steel_t, 6),
        "eaf_liquid_steel_t": round(eaf_liquid_steel_t, 6),
        "endogenous_liquid_steel_t": round(endogenous_liquid_steel_t, 6),
        "site_scrap_supply_t": round(site_scrap_t, 6),
        "bof_scrap_supply_t": round(bof_scrap_t, 6),
        "eaf_scrap_supply_t": round(eaf_scrap_t, 6),
        "scrap_supply_caps_t": (
            {
                key: round(float(scrap_supply_ledger[key]), 6)
                for key in (
                    "site_total_scrap_supply_cap_t",
                    "bof_scrap_supply_cap_t",
                    "eaf_scrap_supply_cap_t",
                )
            }
            if scrap_supply_ledger is not None
            else None
        ),
        "first_execution_block_capacity_t": round(first_block_final_t, 6),
        "first_execution_block_quota_t": round(plan.quota_per_execution_block_t, 6),
        "first_execution_block_imported_slab_t": round(first_block_import_t, 6),
        "first_execution_block_import_annualised_t_y": round(first_block_import_t * HOURS_PER_YEAR / plan.execution_block_hours, 6),
        "terminal_inventory_residuals_t": {key: round(residual, 9) for key, residual in terminal_inventory_residuals.items()},
        "max_abs_carrier_wag_balance_residual_mwh": round(max_abs_wag_residual_mwh, 9),
        "max_abs_hsm_origin_input_residual_t": round(max_abs_hsm_origin_residual_t, 9),
        "binding_constraints": binding_constraints,
        "not_binding_causes": {
            "HSM_capacity": hsm_input_t < hsm_capacity_t - TOLERANCE_T,
            "import_timing_within_first_24h": first_block_final_t >= plan.quota_per_execution_block_t - TOLERANCE_T,
            "rolling_inventory_handoff": "not_causal; infeasibility is proven in the first 168-hour window with all terminal inventory equalities active",
        },
        "interpretation": "This capacity solve uses the active origin-tagged downstream model and reports the binding governed material, import, DSP and conversion boundaries. HSM nameplate, first-block timing and rolling inventory are reported separately and are not inferred from a static annual ledger.",
    }


def run_closed_loop_feasibility_anchor_reconciliation(
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    scenario_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = _config(config_file)
    if scenario_overrides:
        config = {**config, **scenario_overrides}
    forecast_price_field = str(config.get("forecast_price_field", "y_pred"))
    perfect_foresight_oracle = bool(
        config.get("perfect_foresight_oracle", False)
    )
    if (forecast_price_field == "y_true") != perfect_foresight_oracle:
        raise ClosedLoopFeasibilityError(
            "Runtime y_true use requires an explicitly labelled perfect-foresight oracle."
        )
    generator_interface_cap_mode, hsm_rolling_electricity = _source_bounded_sensitivity_levers(config)
    (
        linde_n2_mwh_h,
        eaf_secondary_electricity,
        dsp_electricity,
        site_background_electricity_mwh_h,
        site_background_electricity_mwh_h_by_configuration,
    ) = _electricity_boundary_levers(config)
    site_baseload_ng_mwh_h_by_configuration = _site_baseload_ng_levers(config)
    site_residual_steam_t_h_by_configuration = _site_residual_levers(
        config, "site_residual_steam_t_h_by_configuration"
    )
    site_residual_direct_co2_t_h_by_configuration = _site_residual_levers(
        config, "site_residual_direct_co2_t_h_by_configuration"
    )
    c1_energy_boundary = _c1_source_backed_energy_boundary(config)
    (
        wag_generation_yield_overrides,
        bf_electricity_intensity_scales,
        c1_energy_boundary,
    ) = _user_authorized_emulation_overlays(config, c1_energy_boundary)
    (
        c0_aggregate_generator_technical_interface,
        c0_full_site_energy_bridge,
    ) = _c0_real_anchor_energy_recovery_interfaces(config)
    route_boundary_contract = load_route_boundary_contract()
    future_cost_boundary_contract = load_future_cost_boundary_contract()
    external_procurement_coefficients = _external_procurement_flow_coefficients(
        config, route_boundary_contract
    )
    rolling_plans, rolling_timing_rows = _rolling_plans_from_config(config)
    plan = rolling_plans[0]
    first_plan = plan
    target_multiplier = _model_target_multiplier(config, plan)
    first_target_multiplier = target_multiplier
    run_directory = Path(output_root).resolve() / str(config["run_id"])
    if run_directory.exists():
        raise ClosedLoopFeasibilityError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)

    source_coke_chain = _source_coke_chain(config)
    c0_continuous_activities = continuous_must_run_activities(C0_CONFIGURATION)
    reference_definition_rows, c0_reference_routing, c1_reference_bands = _reference_definition(
        config, horizon_hours=plan.planning_horizon_hours
    )
    downstream_origin_routing = _downstream_origin_routing(
        config,
        horizon_hours=plan.planning_horizon_hours,
        reference_bands=c1_reference_bands,
    )
    if str(config.get("execution_mode", "")).startswith("fixed_reference"):
        reference_deadlines = sorted(plan.cumulative_deadline_targets_t)
        if c0_reference_routing is not None:
            c0_reference_routing["reference_band_deadline_hours"] = (
                reference_deadlines
            )
        downstream_origin_routing["reference_band_deadline_hours"] = (
            reference_deadlines
        )
    generator_unit_interface = _generator_unit_interface(
        config, horizon_hours=plan.planning_horizon_hours,
        deadline_hours=plan.cumulative_deadline_targets_t,
    )
    eaf_material_balance = config.get("eaf_material_balance")
    bof_material_balance = config.get("bof_material_balance")
    scrap_supply_ledger = _scrap_supply_ledger(
        config,
        horizon_hours=plan.planning_horizon_hours,
        execution_block_hours=plan.execution_block_hours,
        deadline_hours=plan.cumulative_deadline_targets_t,
    )
    supplied_metallics = (
        eaf_material_balance is not None,
        bof_material_balance is not None,
        scrap_supply_ledger is not None,
    )
    if any(supplied_metallics) and not all(supplied_metallics):
        raise ClosedLoopFeasibilityError(
            "Gate 2 named metallics require EAF, BOF and site-scrap ledgers together."
        )
    raw_initial_overrides = config.get(
        "initial_inventory_overrides_by_configuration", {}
    )
    if not isinstance(raw_initial_overrides, Mapping):
        raise ClosedLoopFeasibilityError(
            "initial_inventory_overrides_by_configuration must be a mapping."
        )
    overrides: dict[str, dict[str, float]] = {
        str(configuration): {
            str(key): float(value) for key, value in dict(values).items()
        }
        for configuration, values in raw_initial_overrides.items()
    }
    raw_initial_cumulative = config.get("initial_cumulative_production_t", {})
    if not isinstance(raw_initial_cumulative, Mapping):
        raise ClosedLoopFeasibilityError(
            "initial_cumulative_production_t must be a mapping."
        )
    initial_cumulative = {
        configuration: float(raw_initial_cumulative.get(configuration, 0.0))
        for configuration in CONFIGURATIONS
    }
    cumulative = dict(initial_cumulative)
    raw_terminal_inventory_band = config.get(
        "terminal_inventory_band_by_configuration", {}
    )
    if not isinstance(raw_terminal_inventory_band, Mapping) or any(
        not isinstance(values, Mapping)
        for values in raw_terminal_inventory_band.values()
    ):
        raise ClosedLoopFeasibilityError(
            "terminal_inventory_band_by_configuration must be a mapping of mappings."
        )
    terminal_inventory_band = {
        str(configuration): {
            str(state_id): {
                str(bound_id): float(bound_value)
                for bound_id, bound_value in dict(raw_bounds).items()
            }
            for state_id, raw_bounds in values.items()
        }
        for configuration, values in raw_terminal_inventory_band.items()
    }
    if terminal_inventory_band and config.get("terminal_executed_hours_target") in {None, ""}:
        raise ClosedLoopFeasibilityError(
            "A terminal inventory band requires terminal_executed_hours_target."
        )
    terminal_inventory_band_fingerprint = (
        exact_input_fingerprint(terminal_inventory_band)
        if terminal_inventory_band
        else "not_configured"
    )
    initial_executed_hours = int(config.get("initial_executed_hours", 0))
    if initial_executed_hours < 0:
        raise ClosedLoopFeasibilityError(
            "initial_executed_hours must be non-negative."
        )
    executed_hours_so_far = initial_executed_hours
    replan_execution_offsets: dict[int, int] = {}
    execution_rows: list[dict[str, Any]] = []
    executed_hourly_rows: list[dict[str, Any]] = []
    replan_rows: list[dict[str, Any]] = []
    production_progress_rows: list[dict[str, Any]] = []
    model_audit_rows: list[dict[str, Any]] = []
    cost_objective_reconciliation_rows: list[dict[str, Any]] = []
    cost_policies_by_replan: dict[int, dict[str, Any]] = {}
    electricity_price_series_rows: list[dict[str, Any]] = []
    first_window_cost_ledger: list[dict[str, Any]] = []
    first_report: dict[str, Any] | None = None
    reports: list[dict[str, Any]] = []
    c1_route_policy = str(config.get("c1_retained_route_policy", "quota_driven_topology"))
    if c1_route_policy not in {"bottom_up_fixed_retained_route", "quota_driven_topology", "target_share"}:
        raise ClosedLoopFeasibilityError(f"Unsupported C1 route policy: {c1_route_policy}")
    c1_route_band = config.get("c1_liquid_steel_route_band")
    continuous_activities = (
        continuous_must_run_activities(C1_CONFIGURATION)
        if bool(config.get("use_c1_component_ontology_continuous_classes", False))
        else ()
    )
    progress_state_enabled = bool(
        config.get("rolling_production_progress_state_enabled", False)
    )
    production_envelope_fraction = float(
        config.get("production_envelope_tolerance_fraction", 0.005)
    )
    variable_forecast_progress_active = (
        str(config.get("price_series_id", ""))
        == "hourly_da_dplus4_point_forecast"
        and config.get("forecast_price_override_eur_per_mwh") in {None, ""}
    )
    raw_allocation_envelope = config.get("c0_allocation_envelope_diagnostic")
    raw_sale_sensitivity = config.get("c0_electricity_sale_sensitivity")
    if raw_sale_sensitivity is not None:
        if not isinstance(raw_sale_sensitivity, Mapping):
            raise ClosedLoopFeasibilityError(
                "c0_electricity_sale_sensitivity must be a mapping."
            )
        if raw_sale_sensitivity.get("enabled") is not True:
            raw_sale_sensitivity = None
        elif (
            raw_sale_sensitivity.get("policy_id") != "athanasiadis_sale_enabled"
            or forecast_price_field != "y_pred"
            or perfect_foresight_oracle
            or str(config.get("forecast_dataset_split", "validation"))
            != "validation"
        ):
            raise ClosedLoopFeasibilityError(
                "The C0 sale sensitivity requires governed validation y_pred and forbids oracle/held-out prices."
            )
        elif (
            not raw_sale_sensitivity.get("incumbent_capture_directory")
            or not (
                isinstance(
                    raw_sale_sensitivity.get("incumbent_provenance"), Mapping
                )
                or isinstance(
                    raw_sale_sensitivity.get("incumbent_provenance_by_replan"),
                    Mapping,
                )
            )
            or not raw_sale_sensitivity.get("containment_oracle_root")
        ):
            raise ClosedLoopFeasibilityError(
                "The sale sensitivity requires captured no-export incumbent and containment-oracle paths."
            )
    raw_normal_solution_capture = config.get("normal_solution_capture")
    if raw_normal_solution_capture is not None and (
        not isinstance(raw_normal_solution_capture, Mapping)
        or raw_normal_solution_capture.get("enabled") is not True
        or not raw_normal_solution_capture.get("directory")
        or not isinstance(
            raw_normal_solution_capture.get("provenance"), Mapping
        )
    ):
        raise ClosedLoopFeasibilityError(
            "Normal-solution capture requires enabled=true, a directory, and "
            "complete provenance fingerprints."
        )
    if raw_normal_solution_capture is not None:
        _initialize_normal_solution_capture_directory(raw_normal_solution_capture)
    normal_schedule_by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    if raw_allocation_envelope is not None:
        if (
            not isinstance(raw_allocation_envelope, Mapping)
            or raw_allocation_envelope.get("enabled") is not True
            or raw_allocation_envelope.get("endpoint") not in {"min", "max"}
        ):
            raise ClosedLoopFeasibilityError(
                "C0 allocation-envelope diagnostic requires enabled=true and endpoint=min|max."
            )
        if float(raw_allocation_envelope.get("state_tolerance", 1e-6)) != 1e-6:
            raise ClosedLoopFeasibilityError(
                "C0 allocation-envelope state tolerance must remain 1e-6 model units."
            )
        if (
            raw_allocation_envelope.get("endpoint_solver_accuracy_schema")
            != "steel_endpoint_solver_accuracy_v1"
            or float(raw_allocation_envelope.get("endpoint_relative_mip_gap", -1.0))
            != 0.0
            or float(
                raw_allocation_envelope.get(
                    "endpoint_absolute_mip_gap_mwh", -1.0
                )
            )
            != 0.001
            or float(
                raw_allocation_envelope.get(
                    "endpoint_bound_comparison_epsilon_mwh", -1.0
                )
            )
            != 1e-9
            or float(
                raw_allocation_envelope.get(
                    "endpoint_annual_bound_uncertainty_limit_mwh_y", -1.0
                )
            )
            != 1.0
        ):
            raise ClosedLoopFeasibilityError(
                "C0 allocation-envelope endpoint solver-accuracy contract changed."
            )
        raw_schedule = raw_allocation_envelope.get("normal_controller_schedule")
        schedule_hash = str(
            raw_allocation_envelope.get("normal_controller_schedule_sha256", "")
        )
        if not isinstance(raw_schedule, list) or len(raw_schedule) != (
            int(config["replan_count"]) * len(CONFIGURATIONS)
        ):
            raise ClosedLoopFeasibilityError(
                "Allocation endpoints require the complete current-normal C0/C1 "
                "controller schedule."
            )
        calculated_schedule_hash = hashlib.sha256(
            json.dumps(
                raw_schedule, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if calculated_schedule_hash != schedule_hash:
            raise ClosedLoopFeasibilityError(
                "Current-normal controller schedule fingerprint mismatch."
            )
        normal_schedule_by_key = {
            (int(row["replan_index"]), str(row["configuration_id"])): row
            for row in raw_schedule
        }
        if len(normal_schedule_by_key) != len(raw_schedule):
            raise ClosedLoopFeasibilityError(
                "Current-normal controller schedule contains duplicate keys."
            )
    diagnostic_replan_index = config.get("diagnostic_replan_index")
    oracle_only = bool(
        raw_allocation_envelope is not None
        and raw_allocation_envelope.get("oracle_only", False)
    )
    if diagnostic_replan_index is not None:
        diagnostic_replan_index = int(diagnostic_replan_index)
        if not 0 <= diagnostic_replan_index < int(config["replan_count"]):
            raise ClosedLoopFeasibilityError(
                "diagnostic_replan_index lies outside the frozen replan matrix."
            )
    replan_indices = (
        (diagnostic_replan_index,)
        if diagnostic_replan_index is not None
        else range(int(config["replan_count"]))
    )
    for replan_index in replan_indices:
        if normal_schedule_by_key:
            schedule_rows = {
                configuration: normal_schedule_by_key[
                    (replan_index, configuration)
                ]
                for configuration in CONFIGURATIONS
            }
            offsets = {
                int(row["executed_hours_before"]) for row in schedule_rows.values()
            }
            if len(offsets) != 1:
                raise ClosedLoopFeasibilityError(
                    "Normal controller schedule has inconsistent execution offsets."
                )
            executed_hours_so_far = offsets.pop()
            overrides = {
                configuration: {
                    str(key): float(value)
                    for key, value in dict(
                        schedule_rows[configuration]["start_overrides"]
                    ).items()
                }
                for configuration in CONFIGURATIONS
            }
            cumulative = {
                configuration: float(
                    schedule_rows[configuration]["cumulative_executed_before_t"]
                )
                for configuration in CONFIGURATIONS
            }
        plan = rolling_plans[replan_index]
        target_multiplier = _model_target_multiplier(config, plan)
        (
            current_reference_definition_rows,
            c0_reference_routing,
            c1_reference_bands,
        ) = _reference_definition(
            config, horizon_hours=plan.planning_horizon_hours
        )
        if replan_index == 0:
            reference_definition_rows = current_reference_definition_rows
        downstream_origin_routing = _downstream_origin_routing(
            config,
            horizon_hours=plan.planning_horizon_hours,
            reference_bands=c1_reference_bands,
        )
        if str(config.get("execution_mode", "")).startswith("fixed_reference"):
            reference_deadlines = sorted(plan.cumulative_deadline_targets_t)
            if bool(
                rolling_timing_rows[replan_index].get(
                    "campaign_terminal_endpoint_active", False
                )
            ):
                c0_reference_routing = _campaign_progress_reference_routing(
                    c0_reference_routing,
                    definition_rows=current_reference_definition_rows,
                    configuration=C0_CONFIGURATION,
                    executed_rows=executed_hourly_rows,
                    executed_hours_before=executed_hours_so_far,
                    deadline_hours=reference_deadlines,
                )
                downstream_origin_routing = _campaign_progress_reference_routing(
                    downstream_origin_routing,
                    definition_rows=current_reference_definition_rows,
                    configuration=C1_CONFIGURATION,
                    executed_rows=executed_hourly_rows,
                    executed_hours_before=executed_hours_so_far,
                    deadline_hours=reference_deadlines,
                )
            if c0_reference_routing is not None:
                c0_reference_routing["reference_band_deadline_hours"] = (
                    reference_deadlines
                )
            downstream_origin_routing["reference_band_deadline_hours"] = (
                reference_deadlines
            )
        generator_unit_interface = _generator_unit_interface(
            config,
            horizon_hours=plan.planning_horizon_hours,
            deadline_hours=plan.cumulative_deadline_targets_t,
        )
        scrap_supply_ledger = _scrap_supply_ledger(
            config,
            horizon_hours=plan.planning_horizon_hours,
            execution_block_hours=plan.execution_block_hours,
            deadline_hours=plan.cumulative_deadline_targets_t,
        )
        commitment_day_lengths: list[int] = []
        previous_deadline = 0
        for deadline in sorted(plan.cumulative_deadline_targets_t):
            commitment_day_lengths.append(int(deadline) - previous_deadline)
            previous_deadline = int(deadline)
        replan_execution_offsets[replan_index] = executed_hours_so_far
        terminal_hours_target = config.get("terminal_executed_hours_target")
        if terminal_hours_target not in {None, ""}:
            remaining_terminal_hours = int(terminal_hours_target) - int(
                executed_hours_so_far
            )
            exact_deadline_hour = terminal_inventory_activation_hour(
                terminal_executed_hours_target=int(terminal_hours_target),
                executed_hours_so_far=executed_hours_so_far,
                planning_horizon_hours=plan.planning_horizon_hours,
            )
            terminal_exact = exact_deadline_hour is not None
            hard_exact_execution_target = (
                exact_deadline_hour == plan.execution_block_hours
            )
        else:
            exact_deadline_hour = None
            terminal_exact = bool(
                config.get("exact_terminal_production_quota_enabled", False)
            ) and replan_index == int(config["replan_count"]) - 1
            hard_exact_execution_target = terminal_exact
        progress_contract = _rolling_production_progress_contract(
            plan=plan,
            replan_index=replan_index,
            cumulative_before=cumulative,
            base_target_multiplier=target_multiplier,
            enabled=progress_state_enabled,
            envelope_fraction=production_envelope_fraction,
            terminal_exact=hard_exact_execution_target,
            central_target_before_t=(
                float(config["annual_reference_target_mt_y"])
                * 1_000_000.0
                * float(executed_hours_so_far)
                / HOURS_PER_YEAR
            ),
            terminal_recoverability_enabled=False,
            exact_deadline_hour=exact_deadline_hour,
        )
        exact_deadline_targets = (
            {
                configuration: (
                    float(config["annual_reference_target_mt_y"])
                    * 1_000_000.0
                    * float(terminal_hours_target)
                    / HOURS_PER_YEAR
                    - cumulative[configuration]
                )
                for configuration in CONFIGURATIONS
            }
            if exact_deadline_hour is not None
            and terminal_hours_target not in {None, ""}
            else None
        )
        if terminal_exact and exact_deadline_hour is None:
            exact_deadline_hour = plan.execution_block_hours
            exact_deadline_targets = dict(
                progress_contract["progress_target_by_configuration_t"]
            )
        deterministic_cost_policy = _deterministic_cost_policy(
            config,
            future_cost_boundary_contract,
            horizon_hours=plan.planning_horizon_hours,
            nominal_forecast_horizon_hours=int(
                rolling_timing_rows[replan_index].get(
                    "nominal_planning_horizon_hours",
                    plan.planning_horizon_hours,
                )
            ),
            replan_index=replan_index,
            execution_block_hours=plan.execution_block_hours,
        )
        resolved_sale_sensitivity: dict[str, Any] | None = None
        if raw_sale_sensitivity is not None:
            if deterministic_cost_policy is None:
                raise ClosedLoopFeasibilityError(
                    "The electricity-sale sensitivity requires represented deterministic cost."
                )
            electricity_flows = [
                row
                for row in deterministic_cost_policy["flows"]
                if row.get("configuration") in {"C0", "both"}
                and row.get("model_component_attribute") == "net_grid_import_mwh"
            ]
            if len(electricity_flows) != 1:
                raise ClosedLoopFeasibilityError(
                    "Exactly one governed C0 grid-electricity price flow is required."
                )
            resolved_sale_sensitivity = {
                **dict(raw_sale_sensitivity),
                "sale_price_eur_by_hour": list(
                    electricity_flows[0]["price_eur_by_hour"]
                ),
                "replan_index": replan_index,
                "execution_hours": plan.execution_block_hours,
            }
            raw_breakthrough = raw_sale_sensitivity.get("breakthrough_test")
            if raw_breakthrough is not None:
                if not isinstance(raw_breakthrough, Mapping) or not isinstance(
                    raw_breakthrough.get("reference_metrics_by_replan"), Mapping
                ):
                    raise ClosedLoopFeasibilityError(
                        "Sale breakthrough test requires comparator metrics by replan."
                    )
                reference_by_replan = raw_breakthrough[
                    "reference_metrics_by_replan"
                ]
                if str(replan_index) not in reference_by_replan:
                    raise ClosedLoopFeasibilityError(
                        f"Sale breakthrough comparator metrics missing for replan {replan_index}."
                    )
                resolved_sale_sensitivity["breakthrough_test"] = {
                    "mode": str(raw_breakthrough.get("mode", "")),
                    "execution_hours": plan.execution_block_hours,
                    "reference_metrics": dict(
                        reference_by_replan[str(replan_index)]
                    ),
                }
            implementation_sha256 = str(
                config.get("phase2_implementation_sha256", "")
            ).lower()
            if (
                len(implementation_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in implementation_sha256
                )
            ):
                raise ClosedLoopFeasibilityError(
                    "Sale state preservation requires the exact Phase 2 "
                    "implementation identity."
                )
            state_preservation_contract = {
                "schema_version": "steel_phase2_sale_state_preservation_v4",
                "enabled": True,
                "configuration_id": C0_CONFIGURATION,
                "replan_index": replan_index,
                "execution_hours": plan.execution_block_hours,
                "implementation_sha256": implementation_sha256,
            }
            resolved_sale_sensitivity["state_preservation"] = (
                state_preservation_contract
            )
            incumbent_path = (
                Path(str(raw_sale_sensitivity["incumbent_capture_directory"]))
                / (
                    f"normal_solution_replan_{replan_index:02d}__"
                    f"{C0_CONFIGURATION}.json.gz"
                )
            ).resolve()
            if not incumbent_path.is_file():
                raise ClosedLoopFeasibilityError(
                    f"Captured no-export incumbent is missing: {incumbent_path}"
                )
            resolved_sale_sensitivity["incumbent_containment"] = {
                "normal_solution_record_path": str(incumbent_path),
                "normal_solution_record_sha256": hashlib.sha256(
                    incumbent_path.read_bytes()
                ).hexdigest(),
                "normal_solution_expected_provenance": dict(
                    raw_sale_sensitivity.get(
                        "incumbent_provenance_by_replan", {}
                    ).get(
                        str(replan_index),
                        raw_sale_sensitivity.get("incumbent_provenance", {}),
                    )
                ),
                "oracle_directory": str(
                    Path(str(raw_sale_sensitivity["containment_oracle_root"])).resolve()
                    / f"replan_{replan_index:02d}"
                ),
                "validation_tolerance_policy": (
                    validation_tolerance_policy_contract()
                ),
                "state_preservation": state_preservation_contract,
            }
            deterministic_cost_policy = {
                **deterministic_cost_policy,
                "electricity_sale_sensitivity": resolved_sale_sensitivity,
            }
        if deterministic_cost_policy is not None:
            cost_policies_by_replan[replan_index] = deterministic_cost_policy
            electricity_price_series_rows.extend(
                deterministic_cost_policy["electricity_price_series_slice"]
            )
        report = run_s44c_unified_physical_regression(
            run_id=f"{config['run_id']}_replan_{replan_index:02d}", write_report=False,
            performance_mode=str(config.get("performance_mode", "optimized_equivalent")),
            horizon_hours_override=plan.planning_horizon_hours,
            target_multiplier=target_multiplier,
            target_multiplier_by_configuration=(
                progress_contract["target_multiplier_by_configuration"]
                if progress_state_enabled
                else None
            ),
            fix_c0_binary_schedule=False, enable_minimal_wag_layer=True,
            enable_c1_retained_bf_bof_route=True, enable_internal_wag_power=True,
            development_controller_activation=str(config.get("development_controller_activation", "full")),
            hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity,
            rolling_production_deadline_targets_t=(
                None
                if progress_state_enabled
                else plan.cumulative_deadline_targets_t
            ),
            rolling_production_deadline_targets_by_configuration_t=(
                progress_contract["deadline_targets_by_configuration_t"]
                if progress_state_enabled
                else None
            ),
            rolling_production_progress_target_by_configuration_t=(
                progress_contract["progress_target_by_configuration_t"]
                if progress_state_enabled
                else None
            ),
            rolling_production_progress_lower_bound_by_configuration_t=(
                progress_contract[
                    "progress_lower_bound_by_configuration_t"
                ]
                if progress_state_enabled
                else None
            ),
            rolling_production_progress_upper_bound_by_configuration_t=(
                progress_contract[
                    "progress_upper_bound_by_configuration_t"
                ]
                if progress_state_enabled
                else None
            ),
            rolling_production_execution_block_hours=plan.execution_block_hours,
            rolling_production_hard_exact_execution_target=hard_exact_execution_target,
            rolling_production_exact_deadline_hour=exact_deadline_hour,
            rolling_production_exact_deadline_target_by_configuration_t=exact_deadline_targets,
            initial_inventory_overrides_by_configuration=overrides or None,
            rolling_terminal_inventory_hour=(
                exact_deadline_hour
                if terminal_inventory_band and exact_deadline_hour is not None
                else None
            ),
            rolling_terminal_inventory_bounds_by_configuration=(
                terminal_inventory_band
                if terminal_inventory_band and exact_deadline_hour is not None
                else None
            ),
            fix_c1_hybrid_schedule=c1_route_policy == "bottom_up_fixed_retained_route",
            c1_retained_route_policy=c1_route_policy,
            commitment_granularity=str(config.get("commitment_granularity", "hourly_binary")),
            commitment_day_lengths=commitment_day_lengths,
            eaf_material_balance=eaf_material_balance,
            bof_material_balance=bof_material_balance,
            scrap_supply_ledger=scrap_supply_ledger,
            c1_liquid_steel_route_band=c1_route_band,
            c0_continuous_must_run_activities=c0_continuous_activities,
            c0_coke_chain_reconciliation=source_coke_chain,
            c0_downstream_reference_routing=c0_reference_routing,
            continuous_must_run_activities=continuous_activities,
            c1_coke_chain_reconciliation=source_coke_chain,
            downstream_origin_routing=downstream_origin_routing,
            generator_interface_cap_mode=generator_interface_cap_mode,
            generator_unit_interface=generator_unit_interface,
            c1_energy_boundary=c1_energy_boundary,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_mwh_h,
            site_background_electricity_mwh_h=site_background_electricity_mwh_h,
            site_background_electricity_mwh_h_by_configuration=(
                site_background_electricity_mwh_h_by_configuration
            ),
            site_baseload_ng_mwh_h_by_configuration=(
                site_baseload_ng_mwh_h_by_configuration
            ),
            site_residual_steam_t_h_by_configuration=(
                site_residual_steam_t_h_by_configuration
            ),
            site_residual_direct_co2_t_h_by_configuration=(
                site_residual_direct_co2_t_h_by_configuration
            ),
            eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity,
            dsp_electricity_mwh_per_t_coil_override=dsp_electricity,
            external_procurement_flow_coefficients=external_procurement_coefficients,
            deterministic_cost_policy=deterministic_cost_policy,
            wag_generation_yield_overrides_by_configuration=(
                wag_generation_yield_overrides
            ),
            bf_electricity_intensity_scale_by_configuration=(
                bf_electricity_intensity_scales
            ),
            c0_aggregate_generator_technical_interface=(
                c0_aggregate_generator_technical_interface
            ),
            c0_full_site_energy_bridge=c0_full_site_energy_bridge,
            hsm_source_mix_policy_by_configuration=config.get(
                "hsm_source_mix_policy_by_configuration"
            ),
            c0_electricity_sale_sensitivity=resolved_sale_sensitivity,
            c0_allocation_envelope_diagnostic=(
                {
                    **dict(raw_allocation_envelope),
                    "execution_hours": plan.execution_block_hours,
                    "replan_index": replan_index,
                    "normal_snapshot": {
                        "executed_final_product_t": float(
                            normal_schedule_by_key[
                                (replan_index, C0_CONFIGURATION)
                            ]["executed_final_product_t"]
                        ),
                        "coke_inventory_t": float(
                            normal_schedule_by_key[
                                (replan_index, C0_CONFIGURATION)
                            ]["end_overrides"]["coke_store_initial_t"]
                        ),
                        "sinter_inventory_t": float(
                            normal_schedule_by_key[
                                (replan_index, C0_CONFIGURATION)
                            ]["end_overrides"]["sinter_store_initial_t"]
                        ),
                        "hot_iron_inventory_t": float(
                            normal_schedule_by_key[
                                (replan_index, C0_CONFIGURATION)
                            ]["end_overrides"]["hot_iron_store_initial_t"]
                        ),
                        "cold_slab_inventory_t": float(
                            normal_schedule_by_key[
                                (replan_index, C0_CONFIGURATION)
                            ]["end_overrides"]["cold_slab_store_initial_t"]
                        ),
                        "wag_generator_electricity_mwh": float(
                            normal_schedule_by_key[
                                (replan_index, C0_CONFIGURATION)
                            ]["executed_wag_generator_electricity_mwh"]
                        ),
                    },
                    "normal_solution_record_path": str(
                        raw_allocation_envelope[
                            "normal_solution_records_by_replan"
                        ][str(replan_index)]["path"]
                    ),
                    "normal_solution_record_sha256": str(
                        raw_allocation_envelope[
                            "normal_solution_records_by_replan"
                        ][str(replan_index)]["sha256"]
                    ),
                    "normal_solution_expected_provenance": dict(
                        raw_allocation_envelope[
                            "normal_solution_records_by_replan"
                        ][str(replan_index)]["provenance"]
                    ),
                    "oracle_directory": str(
                        Path(
                            str(
                                raw_allocation_envelope[
                                    "failure_evidence_directory"
                                ]
                            )
                        )
                        / f"oracle_r{replan_index:02d}"
                    ),
                }
                if raw_allocation_envelope is not None
                else None
            ),
            normal_solution_capture_by_configuration=(
                {
                    configuration: {
                        "enabled": True,
                        "structural_inactive_exclusion_enabled": bool(
                            raw_normal_solution_capture.get(
                                "structural_inactive_exclusion_enabled", False
                            )
                        ),
                        "path": str(
                            Path(
                                str(raw_normal_solution_capture["directory"])
                            )
                            / (
                                f"normal_solution_replan_{replan_index:02d}__"
                                f"{configuration}.json.gz"
                            )
                        ),
                        "replan_index": replan_index,
                        "controller_state": {
                            "executed_hours_before": executed_hours_so_far,
                            "start_overrides": dict(
                                overrides.get(configuration, {})
                            ),
                            "cumulative_executed_before_t": cumulative[
                                configuration
                            ],
                            "execution_block_hours": plan.execution_block_hours,
                            "planning_horizon_hours": (
                                plan.planning_horizon_hours
                            ),
                            "production_progress_contract": dict(
                                progress_contract[
                                    "state_by_configuration"
                                ][configuration]
                            ),
                        },
                        "provenance": dict(
                            raw_normal_solution_capture["provenance"]
                        ),
                    }
                    for configuration in CONFIGURATIONS
                }
                if raw_normal_solution_capture is not None
                else None
            ),
            solver_time_limit_seconds=float(config.get("solver_time_limit_seconds", 120)),
        )
        if first_report is None:
            first_report = report
        _validate_required_solver_family(config, report["configuration_build_audit"])
        reports.append(report)
        solved_configurations = tuple(
            configuration
            for configuration in CONFIGURATIONS
            if next(
                row for row in report["configuration_build_audit"]
                if row.get("configuration_id") == configuration
            ).get("build_status") == "solved"
        )
        report_performance = dict(report.get("performance", {}))
        configuration_count = max(len(report["configuration_build_audit"]), 1)
        for row in report["configuration_build_audit"]:
            model_audit_rows.append(
                {
                    "replan_index": replan_index,
                    **row,
                    "input_resolution_seconds": float(
                        report_performance.get("input_resolution_seconds", 0.0)
                    )
                    / configuration_count,
                    "array_preparation_seconds": 0.0,
                    "model_build_seconds": float(row.get("build_runtime_seconds", 0.0)),
                    "presolve_solver_seconds": float(row.get("runtime_seconds", 0.0)),
                    "postprocessing_seconds": 0.0,
                    "dataframe_construction_seconds": 0.0,
                    "output_io_seconds": 0.0,
                    "wall_time_seconds": float(row.get("build_runtime_seconds", 0.0))
                    + float(row.get("runtime_seconds", 0.0)),
                    "peak_working_set_mb": peak_working_set_mb(),
                    "scenario_count": 1,
                    "timestep_count": int(plan.planning_horizon_hours),
                    "bid_ladder_steps": 0,
                }
            )
        if diagnostic_replan_index is not None:
            c0_oracle_audit = next(
                row
                for row in report["configuration_build_audit"]
                if row["configuration_id"] == C0_CONFIGURATION
            )
            oracle_status = c0_oracle_audit.get(
                "allocation_envelope_normal_feasibility_oracle_status"
            )
            resolved = {
                **config,
                "scenario_overrides_applied": dict(
                    scenario_overrides or {}
                ),
            }
            resolved_yaml = yaml.safe_dump(resolved, sort_keys=False)
            (run_directory / "config_resolved.yaml").write_text(
                resolved_yaml, encoding="utf-8"
            )
            (run_directory / "resolved_config.yaml").write_text(
                resolved_yaml, encoding="utf-8"
            )
            _write_json(
                run_directory / "input_manifest.json",
                _input_manifest(config_file, resolved_config=resolved),
            )
            _write_json(
                run_directory / "code_version.json",
                {
                    "git_commit": report["git_commit"],
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            _write_csv(
                run_directory / "rolling_model_metrics.csv",
                model_audit_rows,
            )
            summary = {
                "run_id": config["run_id"],
                "status": (
                    "oracle_only_pass"
                    if oracle_only and oracle_status == "pass"
                    else "oracle_only_fail_closed"
                    if oracle_only
                    else "diagnostic_endpoint_pass"
                    if c0_oracle_audit.get(
                        "allocation_envelope_termination_condition"
                    )
                    == "optimal"
                    else "diagnostic_endpoint_fail_closed"
                ),
                "diagnostic_replan_index": replan_index,
                "oracle_status": oracle_status,
                "endpoint_objective_solved": not oracle_only,
                "endpoint_termination_condition": c0_oracle_audit.get(
                    "allocation_envelope_termination_condition"
                ),
                "endpoint_objective_value_mwh": c0_oracle_audit.get(
                    "allocation_envelope_objective_value_mwh"
                ),
                "normal_solution_variable_count": c0_oracle_audit.get(
                    "allocation_envelope_normal_solution_variable_count"
                ),
                "deactivated_deadline_row": c0_oracle_audit.get(
                    "allocation_envelope_deactivated_deadline_row"
                ),
                "oracle_record_path": c0_oracle_audit.get(
                    "allocation_envelope_normal_feasibility_oracle_record_path"
                ),
                "oracle_record_sha256": c0_oracle_audit.get(
                    "allocation_envelope_normal_feasibility_oracle_record_sha256"
                ),
            }
            _write_json(run_directory / "run_summary.json", summary)
            return {
                "run_directory": run_directory,
                "summary": summary,
                "execution_rows": [],
                "executed_hourly_rows": [],
                "terminal_inventory_overrides_by_configuration": overrides,
                "terminal_cumulative_production_t": cumulative,
                "terminal_executed_hours": executed_hours_so_far,
                "rolling_timestamp_rows": [rolling_timing_rows[replan_index]],
            }
        if deterministic_cost_policy is not None:
            planned_cost_ledger = _procurement_cost_ledger(
                report["hourly_rows"],
                deterministic_cost_policy,
                run_id=str(config["run_id"]),
                replan_index=replan_index,
            )
            if replan_index == 0:
                first_window_cost_ledger = list(planned_cost_ledger)
            for configuration_id in CONFIGURATIONS:
                audit = next(
                    row
                    for row in report["configuration_build_audit"]
                    if row["configuration_id"] == configuration_id
                )
                primary = audit.get("primary_cost_objective_eur")
                tie_break_model_cost = audit.get(
                    "tie_break_cost_objective_eur"
                )
                endpoint_model_cost = audit.get(
                    "allocation_envelope_cost_eur"
                )
                executed_solution_model_cost = (
                    endpoint_model_cost
                    if endpoint_model_cost not in {None, ""}
                    else tie_break_model_cost
                )
                planned_cost = sum(
                    float(row["cost_eur"])
                    for row in planned_cost_ledger
                    if row["configuration_id"] == configuration_id
                )
                preservation_residual = (
                    float(tie_break_model_cost) - float(primary)
                    if primary not in {None, ""}
                    and tie_break_model_cost not in {None, ""}
                    else float("inf")
                )
                endpoint_preservation_residual = (
                    float(endpoint_model_cost) - float(primary)
                    if primary not in {None, ""}
                    and endpoint_model_cost not in {None, ""}
                    else preservation_residual
                )
                reporting_residual = (
                    planned_cost - float(executed_solution_model_cost)
                    if executed_solution_model_cost not in {None, ""}
                    else float("inf")
                )
                reporting_validation = (
                    trajectory_cost_record(
                        (
                            "reported_ledger_vs_executed_solution_cost"
                            f"[{configuration_id},{replan_index}]"
                        ),
                        reporting_residual,
                        comparison_scale_eur=max(
                            abs(planned_cost),
                            abs(float(executed_solution_model_cost)),
                        ),
                    )
                    if executed_solution_model_cost not in {None, ""}
                    else {
                        "status": "fail",
                        "allowed_tolerance": 0.0,
                        "raw_residual": "missing_executed_solution_model_cost",
                    }
                )
                objective_preservation_tolerance = float(
                    deterministic_cost_policy["objective_tolerance_eur"]
                )
                physical_wag_upper_bound = bool(
                    configuration_id == C0_CONFIGURATION
                    and raw_allocation_envelope is not None
                    and raw_allocation_envelope.get("breakthrough_mode")
                    == "phase5b_physical_wag_upper_bound_v1"
                )
                aggregate_preservation_validation = (
                    _planning_horizon_cost_preservation_validation(
                        primary_cost_eur=float(primary),
                        tie_break_cost_eur=float(tie_break_model_cost),
                        endpoint_cost_eur=float(
                            tie_break_model_cost
                            if physical_wag_upper_bound
                            else endpoint_model_cost
                            if endpoint_model_cost not in {None, ""}
                            else tie_break_model_cost
                        ),
                    )
                    if primary not in {None, ""}
                    and tie_break_model_cost not in {None, ""}
                    else {
                        "status": "fail",
                        "tie_break": {"allowed_tolerance": 0.0},
                        "endpoint": {"allowed_tolerance": 0.0},
                    }
                )
                cost_objective_reconciliation_rows.append(
                    {
                        "replan_index": replan_index,
                        "configuration_id": configuration_id,
                        "primary_cost_objective_eur": primary,
                        "tie_break_model_cost_eur": tie_break_model_cost,
                        "allocation_envelope_endpoint_cost_eur": endpoint_model_cost,
                        "executed_solution_model_cost_eur": executed_solution_model_cost,
                        "executed_solution_reported_cost_eur": round(planned_cost, 6),
                        "tie_break_minus_primary_cost_eur": round(
                            preservation_residual, 9
                        ),
                        "endpoint_minus_primary_cost_eur": round(
                            endpoint_preservation_residual, 9
                        ),
                        "reported_ledger_minus_executed_solution_cost_eur": round(
                            reporting_residual, 9
                        ),
                        "allowed_tolerance_eur": deterministic_cost_policy[
                            "objective_tolerance_eur"
                        ],
                        "model_cost_preservation_constraint_tolerance_eur": (
                            objective_preservation_tolerance
                        ),
                        "solver_numerical_tolerance": SOLVER_NUMERICAL_TOLERANCE,
                        "tie_break_aggregate_validation_tolerance_eur": (
                            aggregate_preservation_validation["tie_break"][
                                "allowed_tolerance"
                            ]
                        ),
                        "endpoint_aggregate_validation_tolerance_eur": (
                            aggregate_preservation_validation["endpoint"][
                                "allowed_tolerance"
                            ]
                        ),
                        "cost_preservation_validation_purpose": (
                            "economic_stage_only_physical_upper_bound_endpoint_not_applicable"
                            if physical_wag_upper_bound
                            else "trajectory_or_yearly_aggregate_cost"
                        ),
                        "cost_preservation_validation_status": (
                            aggregate_preservation_validation["status"]
                        ),
                        "reported_ledger_allowed_tolerance_eur": (
                            reporting_validation["allowed_tolerance"]
                        ),
                        "reported_ledger_validation_purpose": (
                            "trajectory_or_yearly_aggregate_cost"
                        ),
                        "validation_tolerance_policy": (
                            validation_tolerance_policy_contract()
                        ),
                        "status": (
                            "pass"
                            if aggregate_preservation_validation["status"] == "pass"
                            and reporting_validation["status"] == "pass"
                            else "fail"
                        ),
                    }
                )
        if C0_CONFIGURATION not in solved_configurations:
            c0_audit = next(
                row
                for row in report["configuration_build_audit"]
                if row.get("configuration_id") == C0_CONFIGURATION
            )
            raise ClosedLoopFeasibilityError(
                "Gate-1 C0 regressed during rolling execution; no handoff is valid: "
                f"replan_index={replan_index}, "
                f"executed_hours_before={executed_hours_so_far}, "
                f"planning_horizon_hours={plan.planning_horizon_hours}, "
                f"terminal_inventory_band_active={bool(terminal_inventory_band and exact_deadline_hour is not None)}, "
                f"terminal_hour_in_plan={exact_deadline_hour}, "
                f"build_status={c0_audit.get('build_status')}, "
                f"solver_status={c0_audit.get('solver_status')}, "
                f"termination={c0_audit.get('termination_condition')}, "
                f"caveat={c0_audit.get('caveat')}"
            )
        current_rows, next_overrides = _execution_rows(
            report, replan_index=replan_index, execution_hours=plan.execution_block_hours,
            quota_t=plan.quota_per_execution_block_t, cumulative_before=cumulative, start_overrides=overrides,
            production_progress_state=progress_contract[
                "state_by_configuration"
            ],
            configurations=solved_configurations,
        )
        for row in report["hourly_rows"]:
            if (
                row.get("configuration_id") in solved_configurations
                and int(row.get("hour_index", -1)) < plan.execution_block_hours
            ):
                executed_hourly_rows.append(
                    {
                        "replan_index": replan_index,
                        "executed_hour_index": replan_execution_offsets[
                            replan_index
                        ]
                        + int(row["hour_index"]),
                        **row,
                    }
                )
        for row in current_rows:
            if normal_schedule_by_key:
                scheduled = normal_schedule_by_key[
                    (replan_index, row["configuration_id"])
                ]
                cumulative[row["configuration_id"]] = float(
                    scheduled["cumulative_executed_after_t"]
                )
            else:
                cumulative[row["configuration_id"]] = float(
                    row["cumulative_executed_final_product_t"]
                )
            state = progress_contract["state_by_configuration"][
                row["configuration_id"]
            ]
            audit = next(
                item
                for item in report["configuration_build_audit"]
                if item["configuration_id"] == row["configuration_id"]
            )
            production_progress_rows.append(
                {
                    **state,
                    "local_deadline_targets_t": json.dumps(
                        progress_contract[
                            "deadline_targets_by_configuration_t"
                        ][row["configuration_id"]],
                        sort_keys=True,
                    ),
                    "target_multiplier": progress_contract[
                        "target_multiplier_by_configuration"
                    ][row["configuration_id"]],
                    "executed_block_t": row["executed_final_product_t"],
                    "cumulative_executed_after_t": row[
                        "cumulative_executed_final_product_t"
                    ],
                    "carried_credit_after_t": row[
                        "carried_production_credit_after_t"
                    ],
                    "execution_target_residual_t": row[
                        "execution_progress_target_residual_t"
                    ],
                    "cumulative_envelope_status": row[
                        "cumulative_envelope_status"
                    ],
                    "progress_objective_optimum_deviation_t": audit.get(
                        "production_progress_optimum_deviation_t", ""
                    ),
                    "progress_objective_runtime_seconds": audit.get(
                        "production_progress_runtime_seconds", ""
                    ),
                    "objective_hierarchy": (
                        "production_progress_then_represented_net_procurement_cost_then_physical_tie_break"
                        if resolved_sale_sensitivity is not None
                        else "production_progress_then_represented_procurement_cost_then_physical_tie_break"
                        if deterministic_cost_policy is not None
                        else "rolling_production_progress_then_physical_tie_break"
                    ),
                    "terminal_inventory_band_active": bool(
                        terminal_inventory_band
                        and exact_deadline_hour is not None
                    ),
                    "terminal_inventory_band_hour": (
                        exact_deadline_hour
                        if terminal_inventory_band
                        and exact_deadline_hour is not None
                        else ""
                    ),
                    "terminal_inventory_band_fingerprint_sha256": (
                        terminal_inventory_band_fingerprint
                    ),
                }
            )
            replan_rows.append({
                "replan_index": replan_index, "configuration_id": row["configuration_id"],
                "start_overrides": json.dumps(overrides.get(row["configuration_id"], {}), sort_keys=True),
                "next_overrides": json.dumps(next_overrides[row["configuration_id"]], sort_keys=True),
                "build_status": next(a["build_status"] for a in report["configuration_build_audit"] if a["configuration_id"] == row["configuration_id"]),
            })
        execution_rows.extend(current_rows)
        if normal_schedule_by_key:
            overrides = {
                configuration: {
                    str(key): float(value)
                    for key, value in dict(
                        normal_schedule_by_key[
                            (replan_index, configuration)
                        ]["end_overrides"]
                    ).items()
                }
                for configuration in CONFIGURATIONS
            }
            executed_hours_so_far = int(
                normal_schedule_by_key[
                    (replan_index, C0_CONFIGURATION)
                ]["executed_hours_after"]
            )
        else:
            overrides = next_overrides
            executed_hours_so_far += plan.execution_block_hours

    if first_report is None:
        raise ClosedLoopFeasibilityError("No rolling plan was solved.")
    c1_full_rolling_solved = len(
        {
            int(row["replan_index"])
            for row in executed_hourly_rows
            if row.get("configuration_id") == C1_CONFIGURATION
        }
    ) == int(config["replan_count"])
    executed_cost_ledger: list[dict[str, Any]] = []
    for replan_index, cost_policy in sorted(cost_policies_by_replan.items()):
        executed_cost_ledger.extend(
            _procurement_cost_ledger(
                [
                    row
                    for row in executed_hourly_rows
                    if int(row["replan_index"]) == replan_index
                ],
                cost_policy,
                run_id=str(config["run_id"]),
            )
        )
    if executed_cost_ledger:
        (
            procurement_cost_configuration_rows,
            procurement_cost_component_rows,
            procurement_cost_route_rows,
        ) = _procurement_cost_summaries(
            executed_cost_ledger, executed_hourly_rows
        )
    else:
        procurement_cost_configuration_rows = []
        procurement_cost_component_rows = []
        procurement_cost_route_rows = []
    if c1_full_rolling_solved:
        annual_metrics, plant_rows = _annual_model_metrics(executed_hourly_rows)
        anchor_rows = _anchor_rows(
            annual_metrics,
            execution_mode=str(config.get("execution_mode", "endogenous_feasibility")),
            additional_reference_definition_ids=(
                {
                    "c0_public_liquid_steel_7_2",
                    "c0_hsm_wbw_raw_output_5_4",
                    "c0_dsp_raw_output_1_5",
                    "c1_public_liquid_steel_6_8",
                    "c1_hsm_wbw_raw_output_5_5",
                    "c1_dsp_raw_output_1_5",
                    "c1_imported_slab_0_6",
                    "c1_final_product_proxy_7_0",
                }
                if c0_reference_routing is not None
                and isinstance(config.get("reference_validation"), Mapping)
                else ()
            ),
        )
        origin_rows = _annual_origin_ledger(
            executed_hourly_rows,
            downstream_origin_routing,
            case_id=str(config["c1_boundary_case"]),
        )
        c0_origin_rows = _annual_c0_downstream_origin_ledger(executed_hourly_rows)
        physical_boundary_rows = _annual_physical_boundary_ledger(executed_hourly_rows)
        raw_co2_constants = config.get("first_order_co2_constant_mt_y_by_configuration", {})
        if not isinstance(raw_co2_constants, Mapping):
            raise ClosedLoopFeasibilityError(
                "first_order_co2_constant_mt_y_by_configuration must be a mapping."
            )
        first_order_co2_rows = _first_order_full_site_co2_ledger(
            executed_hourly_rows,
            constant_mt_y_by_configuration={
                str(key): float(value) for key, value in raw_co2_constants.items()
            },
        )
        coverage_share_rows = _full_site_coverage_share_rows(
            executed_hourly_rows, first_order_co2_rows
        )
        raw_parameter_candidates = config.get("user_authorized_parameter_candidates", [])
        if not isinstance(raw_parameter_candidates, list):
            raise ClosedLoopFeasibilityError(
                "user_authorized_parameter_candidates must be a list."
            )
        parameter_range_exception_rows = _parameter_range_exception_report(
            raw_parameter_candidates
        )
        anchor_family_rows = _annual_anchor_family_summary(anchor_rows)
        annual_equivalent_rows = _annual_equivalent_views(
            executed_hourly_rows, list(first_report["hourly_rows"])
        )
        inventory_effect_rows = _inventory_effects(executed_hourly_rows)
    else:
        annual_metrics, plant_rows, anchor_rows, origin_rows = {}, [], [], []
        c0_origin_rows = []
        physical_boundary_rows, anchor_family_rows = [], []
        first_order_co2_rows, coverage_share_rows = [], []
        parameter_range_exception_rows = []
        annual_equivalent_rows, inventory_effect_rows = [], []
    mode_comparison_rows: list[dict[str, Any]] = []
    if config.get("execution_mode") == "reference_validation":
        comparison_run_id = str(config.get("comparison_run_id", ""))
        comparison_ledger_path = (
            Path(output_root).resolve() / comparison_run_id / "annual_physical_boundary_ledger.csv"
        )
        if not comparison_run_id or not comparison_ledger_path.exists():
            raise ClosedLoopFeasibilityError(
                "reference_validation requires an existing solved endogenous comparison ledger."
            )
        mode_comparison_rows = _mode_comparison_rows(
            _read_csv(comparison_ledger_path),
            physical_boundary_rows,
            endogenous_run_id=comparison_run_id,
            reference_run_id=str(config["run_id"]),
        )
    c1_diagnosis = _c1_capacity_diagnosis(
        report=first_report,
        planning_horizon_hours=first_plan.planning_horizon_hours,
        target_multiplier=first_target_multiplier,
        source_coke_chain=source_coke_chain,
    )
    c0_execution = [row for row in execution_rows if row["configuration_id"] == C0_CONFIGURATION]
    c1_execution = [row for row in execution_rows if row["configuration_id"] == C1_CONFIGURATION]
    c1_case = str(config["c1_boundary_case"])
    import_cap_t_y = float(config.get("imported_slab_annual_cap_mt_y", 0.0)) * 1_000_000.0
    c1_import_t = sum(float(row["imported_slab_to_hsm_t"]) for row in c1_execution)
    c1_executed_hours = sum(int(row["execution_hours"]) for row in c1_execution)
    c1_import_annualised_t_y = (
        c1_import_t * HOURS_PER_YEAR / c1_executed_hours if c1_executed_hours else 0.0
    )
    origin_residual = max(
        (
            abs(float(row.get("annualised_value", 0.0)))
            for row in origin_rows
            if row["metric"] in {"HSM_origin_input_balance_residual", "site_final_product_origin_residual"}
        ),
        default=0.0,
    )
    expected_stresscase = c1_case == "endogenous_6_75" and not c1_execution and c1_diagnosis is not None
    max_generator_identity_residual = max(
        (
            abs(_float(row.get("generator_fuel_identity_residual_mwh")))
            for row in executed_hourly_rows
            if row.get("configuration_id") == C1_CONFIGURATION
        ),
        default=0.0,
    )
    ij01_named_ng_mwh = sum(
        _float(row.get("IJ01_NG_fuel_mwh"))
        for row in executed_hourly_rows
        if row.get("configuration_id") == C1_CONFIGURATION
    )
    electricity_boundary_active = str(config.get("repair_stage", "none")) == "electricity"
    max_electricity_bucket_residual = max(
        (abs(_float(row.get("electricity_bucket_sum_residual_mwh"))) for row in executed_hourly_rows),
        default=0.0,
    )
    max_linde_split_residual = max(
        (abs(_float(row.get("linde_split_residual_mwh"))) for row in executed_hourly_rows),
        default=0.0,
    )
    exact_proxy_hours = sum(
        _float(row.get("exact_site_electricity_proxy_active")) for row in executed_hourly_rows
    )
    endogenous_reference_bands_absent = (
        config.get("execution_mode") != "endogenous_feasibility"
        or (
            "reference_validation_bands" not in (c0_reference_routing or {})
            and "reference_validation_bands" not in downstream_origin_routing
            and c1_route_band is None
        )
    )
    future_priced_flows = [
        row
        for row in future_cost_boundary_contract
        if row.get("included_in_first_deterministic_cost_layer") == "yes"
    ]
    future_priced_flows_closed = bool(future_priced_flows) and all(
        row.get("source_status")
        in {"source_backed_central", "boundary_reconciled_development", "accepted_development"}
        and row.get("physical_unit")
        and row.get("activity_driver")
        and row.get("source_locator")
        for row in future_priced_flows
    )
    residuals_excluded_from_future_cost = all(
        row.get("included_in_first_deterministic_cost_layer") == "no"
        for row in future_cost_boundary_contract
        if row.get("residual_status") != "not_residual"
    )
    wag_has_no_direct_purchase_price = all(
        row.get("future_price_unit") in {"", "not_applicable"}
        for row in future_cost_boundary_contract
        if row.get("carrier") in {"BFG", "COG", "BOFG", "WAG_and_NG"}
    )
    named_ng_use_rows = [
        row
        for row in physical_boundary_rows
        if row.get("ledger_family") == "named_NG" and row.get("flow_role") == "use"
    ]
    named_ng_subtotals = [
        row
        for row in physical_boundary_rows
        if row.get("ledger_family") == "named_NG" and row.get("flow_role") == "subtotal"
    ]
    named_ng_identity_residual = abs(
        sum(_float(row.get("annual_value")) for row in named_ng_use_rows)
        - sum(_float(row.get("annual_value")) for row in named_ng_subtotals)
    )
    electricity_identity_residual = max(
        (
            abs(_float(row.get("annual_value")))
            for row in physical_boundary_rows
            if row.get("ledger_family") == "electricity"
            and row.get("flow_role") == "accounting_residual"
        ),
        default=0.0,
    )
    steam_identity_residual = max(
        (
            abs(_float(row.get("annual_value")))
            for row in physical_boundary_rows
            if row.get("ledger_family") == "steam"
            and row.get("flow_role") == "accounting_residual"
        ),
        default=0.0,
    )
    cost_mode_active = bool(cost_policies_by_replan)
    executed_electricity_price_rows = [
        {
            **row,
            "executed_hour_index": replan_execution_offsets[
                int(row["replan_index"])
            ]
            + int(row["model_hour"]),
            "executed_block_field_status": "interface_only_not_settlement",
        }
        for row in electricity_price_series_rows
        if int(row["model_hour"])
        < rolling_plans[int(row["replan_index"])].execution_block_hours
    ]
    price_series_timing_safe = bool(electricity_price_series_rows) and all(
        datetime.fromisoformat(row["information_available_timestamp_utc"])
        <= datetime.fromisoformat(row["replan_timestamp_utc"])
        for row in electricity_price_series_rows
    )
    price_series_has_no_realised_future = all(
        "oracle" not in str(row["forecast_realised_classification"]).lower()
        and "realised" not in str(row["forecast_realised_classification"]).lower()
        for row in electricity_price_series_rows
    )
    cost_objectives_active = bool(model_audit_rows) and all(
        row.get("objective_type") == "represented_external_procurement_cost_eur"
        and row.get("primary_cost_objective_eur") not in {None, ""}
        for row in model_audit_rows
    )
    cost_objective_reconciliation_pass = bool(
        cost_objective_reconciliation_rows
    ) and all(
        row["status"] == "pass" for row in cost_objective_reconciliation_rows
    )
    cost_ledger_validation = _governed_cost_ledger_validation(
        config, executed_cost_ledger
    )
    cost_summary_total = sum(
        _float(row.get("executed_procurement_cost_eur"))
        for row in procurement_cost_configuration_rows
    )
    cost_component_total = sum(
        _float(row.get("cost_eur")) for row in procurement_cost_component_rows
    )
    cost_route_total = sum(
        _float(row.get("cost_eur")) for row in procurement_cost_route_rows
    )
    downstream_capacity_diagnosis = (
        _c1_downstream_capacity_diagnosis(
            plan=plan,
            target_multiplier=target_multiplier,
            downstream_routing=downstream_origin_routing,
            source_coke_chain=source_coke_chain,
            eaf_material_balance=eaf_material_balance,
            bof_material_balance=bof_material_balance,
            scrap_supply_ledger=scrap_supply_ledger,
            solver_time_limit_seconds=float(config.get("solver_time_limit_seconds", 300)),
            upstream_diagnosis=c1_diagnosis,
        )
        if c1_case == "mer_site_product" and not c1_execution
        else None
    )
    global_terminal_hours = config.get("terminal_executed_hours_target")
    global_terminal_reached = (
        global_terminal_hours in {None, ""}
        or executed_hours_so_far >= int(global_terminal_hours)
    )
    handoff_contract = _validate_inventory_handoff_contract(
        replan_rows,
        replan_count=int(config["replan_count"]),
        phase2_single_window_preflight=(
            config.get("phase2_single_window_preflight") is True
        ),
        tolerance=TOLERANCE_T,
    )
    validation_rows = [
        {"check_id": "c0_closed_loop_replans_completed", "status": "pass" if len(c0_execution) == int(config["replan_count"]) else "fail", "evidence": "rolling_execution.csv"},
        {"check_id": "c0_executed_quotas_pass", "status": "pass" if c0_execution and all(row["quota_status"] == "pass" for row in c0_execution) else "fail", "evidence": "rolling_execution.csv"},
        {
            "check_id": "rolling_production_progress_state",
            "status": "pass"
            if (
                not progress_state_enabled
                or (
                    len(production_progress_rows)
                    == len(CONFIGURATIONS) * int(config["replan_count"])
                    and all(
                        row["cumulative_envelope_status"] == "pass"
                        and (
                            variable_forecast_progress_active
                            or abs(
                                _float(
                                    row.get(
                                        "progress_objective_optimum_deviation_t"
                                    )
                                )
                            )
                            <= 1e-4
                        )
                        for row in production_progress_rows
                    )
                    and (
                        not global_terminal_reached
                        or all(
                            abs(
                                cumulative[configuration]
                                * HOURS_PER_YEAR
                                / executed_hours_so_far
                                - float(config["annual_reference_target_mt_y"])
                                * 1_000_000.0
                            )
                            <= 0.1
                            for configuration in CONFIGURATIONS
                        )
                    )
                )
            )
            else "fail",
            "evidence": "rolling_production_progress_state.csv;rolling_execution.csv",
        },
        {
            "check_id": "exact_terminal_production_quota",
            "status": "pass"
            if (
                not bool(config.get("exact_terminal_production_quota_enabled", False))
                or not global_terminal_reached
                or (
                    all(
                        row.get("terminal_exact_quota_active") is True
                        and abs(
                            _float(row.get("cumulative_executed_after_t"))
                            - _float(row.get("next_cumulative_central_target_t"))
                        )
                        <= 1e-4
                        for row in production_progress_rows
                        if int(row["replan_index"]) == int(config["replan_count"]) - 1
                    )
                    and len(
                        [
                            row for row in production_progress_rows
                            if int(row["replan_index"]) == int(config["replan_count"]) - 1
                        ]
                    )
                    == len(CONFIGURATIONS)
                )
            )
            else "fail",
            "evidence": "rolling_production_progress_state.csv;rolling_execution.csv",
        },
        {"check_id": "c0_continuous_operation_preserved", "status": "pass" if first_report.get("c0_continuous_must_run_activities") == sorted(c0_continuous_activities) and not first_report.get("fix_c0_binary_schedule") else "fail", "evidence": "rolling_model_metrics.csv"},
        {"check_id": "c1_case_status", "status": "pass" if (expected_stresscase or (len(c1_execution) == int(config["replan_count"]) and all(row["quota_status"] == "pass" for row in c1_execution))) else "fail", "evidence": "rolling_execution.csv and c1_capacity_diagnosis.json"},
        {"check_id": "imported_slab_cap", "status": "pass" if c1_import_annualised_t_y <= import_cap_t_y + TOLERANCE_T else "fail", "evidence": "rolling_execution.csv"},
        {"check_id": "origin_conservation", "status": "pass" if (not c1_execution or origin_residual <= TOLERANCE_T) else "fail", "evidence": "annual_origin_material_ledger.csv"},
        {"check_id": "c0_downstream_origin_conservation", "status": "pass" if c0_origin_rows and all(abs(_float(row.get("annualised_value_t_y"))) <= ANNUALISED_ACCOUNTING_TOLERANCE_MWH for row in c0_origin_rows if row.get("flow_role") == "accounting_residual") else "fail", "evidence": "annual_c0_downstream_origin_ledger.csv"},
        {"check_id": "material_conservation", "status": "pass" if all(float(row["max_abs_material_balance_residual_t"]) <= HOURLY_REPORTING_MATERIAL_TOLERANCE_T for row in execution_rows) else "fail", "evidence": "rolling_execution.csv"},
        {"check_id": "carrier_specific_wag_balance", "status": "pass" if all(float(row["max_abs_carrier_wag_balance_residual_mwh"]) <= TOLERANCE_T for row in execution_rows) else "fail", "evidence": "rolling_execution.csv"},
        {
            "check_id": "terminal_handoff_snapshot_complete",
            "status": (
                "pass"
                if handoff_contract["terminal_handoff_snapshot_complete"]
                else "fail"
            ),
            "validation_scope": handoff_contract["validation_scope"],
            "checked_transition_count": handoff_contract[
                "checked_transition_count"
            ],
            "evidence": "inventory_handoff.csv; complete finite next_overrides schema",
        },
        {
            "check_id": "inter_window_handoff_continuity",
            "status": (
                "pass"
                if handoff_contract["inter_window_handoff_continuity"]
                in {"pass", "not_applicable"}
                and handoff_contract["status"] == "pass"
                else "fail"
            ),
            "result": handoff_contract["inter_window_handoff_continuity"],
            "validation_scope": handoff_contract["validation_scope"],
            "checked_transition_count": handoff_contract[
                "checked_transition_count"
            ],
            "max_state_residual": handoff_contract["max_state_residual"],
            "evidence": (
                "not_applicable: terminal snapshot only; no propagation claim"
                if handoff_contract["inter_window_handoff_continuity"]
                == "not_applicable"
                else "inventory_handoff.csv; previous next_overrides versus next start_overrides"
            ),
        },
        {"check_id": "market_terms_disabled", "status": "pass", "evidence": "resolved config"},
        {"check_id": "annual_reporting_fail_closed_to_solved_rolling_lineage", "status": "pass", "evidence": "annual ledgers are generated only after the complete C0/C1 rolling chain solves"},
        {"check_id": "no_fixed_route_split", "status": "pass" if c1_route_policy == "quota_driven_topology" and c1_route_band is None else "fail", "evidence": "config_resolved.yaml"},
        {"check_id": "configured_rolling_replans_completed", "status": "pass" if len(c0_execution) == int(config["replan_count"]) and len(c1_execution) == int(config["replan_count"]) else "fail", "evidence": "rolling_execution.csv"},
        {"check_id": "generator_fuel_identity", "status": "pass" if max_generator_identity_residual <= TOLERANCE_T else "fail", "evidence": "executed_hourly_dispatch.csv;annual_physical_boundary_ledger.csv"},
        {"check_id": "ij01_named_ng_prohibited", "status": "pass" if abs(ij01_named_ng_mwh) <= TOLERANCE_T else "fail", "evidence": "executed_hourly_dispatch.csv"},
        {"check_id": "electricity_bucket_non_overlap", "status": "pass" if (not electricity_boundary_active or max_electricity_bucket_residual <= TOLERANCE_T) else "fail", "evidence": "executed_hourly.csv;annual_physical_boundary_ledger.csv"},
        {"check_id": "linde_n2_separate_from_asu", "status": "pass" if (not electricity_boundary_active or max_linde_split_residual <= TOLERANCE_T) else "fail", "evidence": "executed_hourly.csv;annual_physical_boundary_ledger.csv"},
        {"check_id": "exact_site_electricity_proxy_retired", "status": "pass" if (not electricity_boundary_active or abs(exact_proxy_hours) <= TOLERANCE_T) else "fail", "evidence": "executed_hourly.csv"},
        {"check_id": "route_and_denominator_contract_complete", "status": "pass" if route_boundary_contract and {row["configuration"] for row in route_boundary_contract} == {"C0", "C1"} else "fail", "evidence": "route_boundary_contract.csv"},
        {"check_id": "reference_bands_absent_in_endogenous_mode", "status": "pass" if endogenous_reference_bands_absent else "fail", "evidence": "resolved_config.yaml"},
        {"check_id": "future_priced_flows_have_unit_source_activity_basis", "status": "pass" if future_priced_flows_closed else "fail", "evidence": "future_cost_boundary_contract.csv"},
        {"check_id": "residual_energy_excluded_from_future_objective", "status": "pass" if residuals_excluded_from_future_cost else "fail", "evidence": "future_cost_boundary_contract.csv"},
        {"check_id": "wag_opportunity_value_no_direct_purchase_price", "status": "pass" if wag_has_no_direct_purchase_price else "fail", "evidence": "future_cost_boundary_contract.csv"},
        {"check_id": "named_ng_component_identity", "status": "pass" if named_ng_identity_residual <= ANNUALISED_ACCOUNTING_TOLERANCE_MWH else "fail", "evidence": "annual_physical_boundary_ledger.csv"},
        {"check_id": "gross_internal_grid_electricity_identity", "status": "pass" if electricity_identity_residual <= ANNUALISED_ACCOUNTING_TOLERANCE_MWH else "fail", "evidence": "annual_physical_boundary_ledger.csv"},
        {"check_id": "represented_steam_boundary_identity", "status": "pass" if steam_identity_residual <= ANNUALISED_ACCOUNTING_TOLERANCE_MWH else "fail", "evidence": "annual_physical_boundary_ledger.csv"},
    ]
    if cost_mode_active:
        validation_rows.extend(
            [
                {
                    "check_id": "lexicographic_procurement_cost_objective_active",
                    "status": "pass" if cost_objectives_active else "fail",
                    "evidence": "rolling_model_metrics.csv",
                },
                {
                    "check_id": "primary_cost_preserved_by_physical_tie_break",
                    "status": "pass" if cost_objective_reconciliation_pass else "fail",
                    "evidence": "cost_objective_reconciliation.csv",
                },
                {
                    "check_id": "all_governed_procurement_price_families_active",
                    "status": (
                        "pass"
                        if cost_ledger_validation["status"] == "pass"
                        else "fail"
                    ),
                    "evidence": "executed_procurement_cost_ledger.csv",
                },
                {
                    "check_id": "procurement_cost_component_and_route_identities",
                    "status": "pass"
                    if abs(cost_summary_total - cost_component_total) <= 1e-4
                    and abs(cost_summary_total - cost_route_total) <= 1e-4
                    else "fail",
                    "evidence": "procurement_cost_summary.csv;procurement_cost_by_component.csv;procurement_cost_by_route.csv",
                },
                {
                    "check_id": "fixed_reference_cumulative_route_bands_active",
                    "status": "pass"
                    if c0_reference_routing is not None
                    and "reference_validation_bands" in c0_reference_routing
                    and c1_reference_bands is not None
                    else "fail",
                    "evidence": "reference_definition.csv;resolved_config.yaml",
                },
                {
                    "check_id": "no_revenue_residual_ets_or_market_cost_terms",
                    "status": "pass"
                    if cost_ledger_validation["status"] == "pass"
                    else "fail",
                    "evidence": "resolved_config.yaml;executed_procurement_cost_ledger.csv",
                },
                {
                    "check_id": "electricity_price_series_covers_every_rolling_plan",
                    "status": "pass"
                    if len(electricity_price_series_rows)
                    == sum(item.planning_horizon_hours for item in rolling_plans)
                    and len(executed_electricity_price_rows)
                    == sum(item.execution_block_hours for item in rolling_plans)
                    else "fail",
                    "evidence": "electricity_price_series.csv;executed_electricity_price_series.csv",
                },
                {
                    "check_id": "price_information_timing_non_anticipative",
                    "status": "pass"
                    if (
                        price_series_timing_safe
                        and price_series_has_no_realised_future
                    )
                    or perfect_foresight_oracle
                    else "fail",
                    "evidence": (
                        "electricity_price_series.csv;separately_labelled_perfect_foresight_oracle"
                        if perfect_foresight_oracle
                        else "electricity_price_series.csv"
                    ),
                },
            ]
        )
    if c1_full_rolling_solved:
        forbidden_mode_b = any(
            row["included_in_mode_b_co2"] == "true"
            and row["carrier_or_material"] not in {"BFG", "COG", "BOFG", "WAG", "NG", "explicit_fuel"}
            for row in physical_boundary_rows
        )
        validation_rows.extend(
            [
                {
                    "check_id": "annual_physical_boundary_accounting",
                    "status": "pass" if _annual_accounting_residuals_close(physical_boundary_rows) else "fail",
                    "evidence": "annual_physical_boundary_ledger.csv",
                },
                {
                    "check_id": "mode_b_explicit_fuel_separation",
                    "status": "pass" if not forbidden_mode_b else "fail",
                    "evidence": "annual_physical_boundary_ledger.csv",
                },
                {
                    "check_id": "anchor_hsm_output_not_input",
                    "status": "pass" if all(
                        row.get("model_metric") == "hsm_hrc_output_mt_y"
                        for row in anchor_rows
                        if "hsm/wbw rolled output" in str(row.get("anchor_metric", "")).lower()
                    ) else "fail",
                    "evidence": "annual_anchor_reconciliation.csv",
                },
                {
                    "check_id": "unit_match_not_sufficient_for_comparability",
                    "status": "pass" if any(
                        row.get("unit_match") == "true"
                        and row.get("comparability_status") != "directly_comparable"
                        for row in anchor_rows
                    ) else "fail",
                    "evidence": "annual_anchor_reconciliation.csv",
                },
                {
                    "check_id": "generator_component_boundary_provenance",
                    "status": "pass" if (
                        (
                            generator_unit_interface is not None
                            and any(
                                row.get("anchor_id") == "c1_vn25_ng_4_1"
                                and row.get("comparability_status") == "directly_comparable"
                                for row in anchor_rows
                            )
                        )
                        or (
                            generator_unit_interface is None
                            and all(
                                row.get("comparability_status") == "not_comparable"
                                for row in anchor_rows
                                if row.get("anchor_id") in {"c1_vn25_ng_4_1", "c1_generator_total_with_flare_14_6"}
                            )
                        )
                    ) else "fail",
                    "evidence": "annual_anchor_reconciliation.csv",
                },
                {
                    "check_id": "reference_definitions_excluded_from_scoring",
                    "status": "pass" if (
                        config.get("execution_mode") != "reference_validation"
                        or all(
                            row.get("comparability_status") == "scenario_definition"
                            for row in anchor_rows
                            if row.get("scenario_definition_status") == "scenario_definition"
                        )
                    ) else "fail",
                    "evidence": "annual_anchor_reconciliation.csv;reference_definition.csv",
                },
                {
                    "check_id": "configuration_specific_family_scoring",
                    "status": "pass" if all(row.get("configuration") for row in anchor_family_rows) else "fail",
                    "evidence": "independent_anchor_family_summary.csv",
                },
                {
                    "check_id": "annual_equivalents_not_annual_truth",
                    "status": "pass" if annual_equivalent_rows and all(
                        row.get("truth_status") == "representative_deterministic_annual_equivalent_not_simulated_year"
                        for row in annual_equivalent_rows
                    ) else "fail",
                    "evidence": "annual_equivalent_views.csv",
                },
                {
                    "check_id": "reference_mode_compares_same_solved_ledger_lineage",
                    "status": "pass" if (
                        config.get("execution_mode") != "reference_validation"
                        or bool(mode_comparison_rows)
                    ) else "fail",
                    "evidence": "mode_comparison.csv",
                },
            ]
        )
    status = "pass" if all(row["status"] == "pass" for row in validation_rows) else "fail"
    primary_anchor_pairs = sum(row["primary_pair_below_7_5pct"] == "yes" for row in anchor_family_rows)
    contextual_anchor_pairs = sum(row["contextual_pair_below_7_5pct"] == "yes" for row in anchor_family_rows)
    anchor_coverage_status = "reported_not_readiness_gate"
    pre_cost_boundary_ready = (
        status == "pass"
        and c1_full_rolling_solved
        and future_priced_flows_closed
        and residuals_excluded_from_future_cost
        and wag_has_no_direct_purchase_price
    )
    cost_acceptance_ready = _cost_acceptance_readiness(
        pre_cost_boundary_ready=pre_cost_boundary_ready,
        cost_mode_active=cost_mode_active,
        cost_objectives_active=cost_objectives_active,
        cost_objective_reconciliation_pass=cost_objective_reconciliation_pass,
        cost_ledger_validation=cost_ledger_validation,
    )
    gate3_stage_gate = {
        "stage_id": (
            "fixed_reference_lexicographic_procurement_cost_acceptance"
            if cost_mode_active
            else "final_pre_economics_methodology_and_boundary_closure"
        ),
        "status": "pass" if status == "pass" else "fail",
        "physical_ledger_status": "pass" if c1_full_rolling_solved and status == "pass" else "fail_closed",
        "anchor_coverage_status": anchor_coverage_status,
        "independent_primary_configuration_family_pairs_below_7_5pct": primary_anchor_pairs,
        "contextual_configuration_family_pairs_below_7_5pct": contextual_anchor_pairs,
        "required_independent_primary_configuration_family_pairs": 0,
        "superseded_historical_operational_anchor_requirement": 4,
        "pre_cost_validation_policy": "physical_intensity_and_boundary_closure",
        "post_cost_operational_validation_policy": (
            "same_solved_rolling_lineage_physical_anchor_and_cost_reconciliation"
            if cost_mode_active
            else "deferred_until_deterministic_cost_objective_exists"
        ),
        "decision": (
            "ready_for_post_cost_reconciliation"
            if cost_mode_active and cost_acceptance_ready
            else "ready_for_deterministic_procurement_cost_design"
            if not cost_mode_active and pre_cost_boundary_ready
            else "not_ready"
        ),
        "next_permitted_gate": (
            "post_cost_physical_anchor_cost_reconciliation"
            if cost_mode_active and cost_acceptance_ready
            else "fixed_reference_deterministic_procurement_cost"
            if not cost_mode_active and pre_cost_boundary_ready
            else "physical_or_cost_boundary_repair"
        ),
        "future_cost_objective_activation_status": (
            "active_fixed_reference_only" if cost_mode_active else "prepared_not_active"
        ),
        "economics_and_markets_unlocked": False,
        "execution_mode": config.get("execution_mode", "endogenous_feasibility"),
        "lineage_run_id": config["run_id"],
        "annualisation_reporting_only": True,
    }
    resolved = dict(config)
    resolved["deadline_targets_t"] = first_plan.cumulative_deadline_targets_t
    resolved["model_target_multiplier"] = first_target_multiplier
    resolved["rolling_timestamp_contract"] = {
        "active": bool(config.get("timestamped_dplus4_rolling_enabled", False)),
        "planning_horizon_hours_min": min(
            item.planning_horizon_hours for item in rolling_plans
        ),
        "planning_horizon_hours_max": max(
            item.planning_horizon_hours for item in rolling_plans
        ),
        "execution_block_hours_min": min(
            item.execution_block_hours for item in rolling_plans
        ),
        "execution_block_hours_max": max(
            item.execution_block_hours for item in rolling_plans
        ),
        "executed_hours": executed_hours_so_far - initial_executed_hours,
    }
    resolved["c1_retained_route_policy"] = c1_route_policy
    resolved["c0_continuous_must_run_activities"] = list(c0_continuous_activities)
    resolved["c1_continuous_must_run_activities"] = list(continuous_activities)
    resolved["source_coke_chain"] = source_coke_chain
    resolved["downstream_origin_interface_active"] = True
    resolved["downstream_origin_routing"] = dict(downstream_origin_routing)
    resolved["generator_unit_interface"] = generator_unit_interface
    resolved["represented_electricity_boundary_levers"] = {
        "linde_n2_auxiliary_electricity_mwh_h": linde_n2_mwh_h,
        "eaf_secondary_electricity_mwh_per_t_ls": eaf_secondary_electricity,
        "dsp_electricity_mwh_per_t_coil": dsp_electricity,
        "site_background_electricity_mwh_h": site_background_electricity_mwh_h,
        "site_background_electricity_mwh_h_by_configuration": dict(
            site_background_electricity_mwh_h_by_configuration
        ),
    }
    resolved["site_baseload_ng_mwh_h_by_configuration"] = dict(
        site_baseload_ng_mwh_h_by_configuration
    )
    resolved["site_residual_steam_t_h_by_configuration"] = dict(
        site_residual_steam_t_h_by_configuration
    )
    resolved["site_residual_direct_co2_t_h_by_configuration"] = dict(
        site_residual_direct_co2_t_h_by_configuration
    )
    resolved["c1_source_backed_energy_boundary"] = dict(c1_energy_boundary or {})
    resolved["wag_generation_yield_overrides_by_configuration"] = (
        wag_generation_yield_overrides
    )
    resolved["named_process_electricity_intensity_scales_by_configuration"] = dict(
        config.get("named_process_electricity_intensity_scales_by_configuration", {})
    )
    resolved["future_deterministic_cost_contract"] = {
        "activation_status": (
            "active_fixed_reference_only" if cost_mode_active else "prepared_not_active"
        ),
        "objective": "minimise represented external procurement cost lexicographically before the physical tie-breaker",
        "included": [
            "represented_net_grid_electricity_purchase",
            "represented_named_natural_gas_purchase",
            "represented_coking_coal_and_PCI_purchase",
            "represented_sinter_and_PEFA_ore_purchase",
            "represented_DRP_pellet_purchase",
            "represented_scrap_purchase",
            "represented_imported_slab_purchase",
        ],
        "excluded": [
            "residual_electricity",
            "residual_natural_gas",
            "WAG_purchase_cost",
            "internal_electricity_revenue",
            "steam_revenue",
            "product_revenue",
            "ETS",
            "DA",
            "stochasticity",
            "CVaR",
            "mFRR",
        ],
        "fixed_reference_scenario_bands_active": cost_mode_active,
        "price_values_populated": cost_mode_active,
        "result_fields": list(FUTURE_DETERMINISTIC_COST_RESULT_FIELDS),
    }
    resolved["electricity_price_series_interface"] = {
        "price_series_id": config.get(
            "price_series_id", "flat_central_reference_v1"
        ),
        "contract_path": str(
            PRICE_SERIES_CONTRACT_PATH.relative_to(REPO_ROOT)
        ).replace("\\", "/"),
        "rolling_slice_policy": (
            "one governed timestamp-derived D-D+4 slice per replan"
            if bool(config.get("timestamped_dplus4_rolling_enabled", False))
            else f"one information-safe {first_plan.planning_horizon_hours}h slice per replan"
        ),
        "executed_block_fields": "first local delivery day using actual UTC hours; interface_only_not_settlement",
        "dam_bidding_active": False,
        "settlement_active": False,
    }
    resolved["c0_downstream_reference_routing"] = c0_reference_routing
    resolved["reference_definition_row_count"] = len(reference_definition_rows)
    resolved["scenario_overrides_applied"] = dict(scenario_overrides or {})
    resolved["annualisation_policy"] = "8760/actual_executed_timestamp_hours from concatenated solved first-local-day blocks; reporting only"
    resolved_yaml = yaml.safe_dump(resolved, sort_keys=False)
    (run_directory / "config_resolved.yaml").write_text(resolved_yaml, encoding="utf-8")
    (run_directory / "resolved_config.yaml").write_text(resolved_yaml, encoding="utf-8")
    _write_json(run_directory / "input_manifest.json", _input_manifest(config_file, resolved_config=resolved))
    _write_json(run_directory / "code_version.json", {"git_commit": first_report["git_commit"], "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_csv(run_directory / "rolling_execution.csv", execution_rows)
    _write_csv(run_directory / "rolling_timestamp_contract.csv", rolling_timing_rows)
    _write_csv(run_directory / "inventory_handoff.csv", replan_rows)
    _write_csv(
        run_directory / "rolling_production_progress_state.csv",
        production_progress_rows,
    )
    _write_csv(run_directory / "executed_hourly.csv", executed_hourly_rows)
    _write_csv(run_directory / "first_window_hourly.csv", first_report["hourly_rows"])
    _write_csv(run_directory / "rolling_model_metrics.csv", model_audit_rows)
    _write_csv(run_directory / "annual_plant_metrics.csv", plant_rows)
    _write_csv(run_directory / "annual_origin_material_ledger.csv", origin_rows)
    _write_csv(run_directory / "annual_c0_downstream_origin_ledger.csv", c0_origin_rows)
    _write_csv(run_directory / "annual_physical_boundary_ledger.csv", physical_boundary_rows)
    _write_csv(run_directory / "first_order_full_site_co2_ledger.csv", first_order_co2_rows)
    _write_csv(run_directory / "full_site_coverage_shares.csv", coverage_share_rows)
    _write_csv(run_directory / "parameter_range_exceptions.csv", parameter_range_exception_rows)
    _write_csv(run_directory / "annual_equivalent_views.csv", annual_equivalent_rows)
    _write_csv(run_directory / "inventory_effects.csv", inventory_effect_rows)
    _write_csv(run_directory / "reference_definition.csv", reference_definition_rows)
    _write_csv(run_directory / "route_boundary_contract.csv", route_boundary_contract)
    _write_csv(run_directory / "future_cost_boundary_contract.csv", future_cost_boundary_contract)
    cost_result_values: dict[str, Any] = {}
    if cost_mode_active:
        price_field = {
            "grid_electricity_flat_nl": "electricity_cost_eur",
            "natural_gas_ttf_proxy": "natural_gas_cost_eur",
            "coking_coal_hcc_proxy": "coking_coal_cost_eur",
            "pci_coal_proxy": "pci_cost_eur",
            "iron_ore_62fe_proxy": "iron_ore_cost_eur",
            "imported_dr_pellets_proxy": "dr_pellet_cost_eur",
            "purchased_scrap_proxy": "purchased_scrap_cost_eur",
            "imported_slab_proxy": "imported_slab_cost_eur",
        }
        for price_id, field in price_field.items():
            cost_result_values[field] = {
                configuration: round(
                    sum(
                        float(row["cost_eur"])
                        for row in executed_cost_ledger
                        if row["configuration_id"] == configuration
                        and row["price_id"] == price_id
                    ),
                    6,
                )
                for configuration in CONFIGURATIONS
            }
        cost_result_values["total_represented_procurement_cost_eur"] = {
            row["configuration_id"]: row["executed_procurement_cost_eur"]
            for row in procurement_cost_configuration_rows
        }
        cost_result_values["represented_procurement_cost_eur_per_t_final_product"] = {
            row["configuration_id"]: row[
                "procurement_cost_eur_per_t_final_product"
            ]
            for row in procurement_cost_configuration_rows
        }
        cost_result_values["cost_by_component_eur"] = procurement_cost_component_rows
        cost_result_values["cost_by_route_eur"] = procurement_cost_route_rows
    _write_csv(
        run_directory / "future_cost_result_contract.csv",
        [
            {
                "field": field,
                "activation_status": (
                    "active_fixed_reference_only"
                    if cost_mode_active
                    else "prepared_not_active"
                ),
                "value": (
                    json.dumps(cost_result_values.get(field, ""), sort_keys=True)
                    if cost_mode_active
                    else ""
                ),
                "caveat": (
                    "Fixed-reference represented procurement cost; no route-selection, revenue, ETS or market claim."
                    if cost_mode_active
                    else "No prices or deterministic cost objective are active in this physical acceptance run."
                ),
            }
            for field in FUTURE_DETERMINISTIC_COST_RESULT_FIELDS
        ],
    )
    if cost_mode_active:
        _write_csv(
            run_directory / "executed_procurement_cost_ledger.csv",
            executed_cost_ledger,
        )
        _write_csv(
            run_directory / "first_window_procurement_cost_ledger.csv",
            first_window_cost_ledger,
        )
        _write_csv(
            run_directory / "procurement_cost_summary.csv",
            procurement_cost_configuration_rows,
        )
        _write_csv(
            run_directory / "procurement_cost_by_component.csv",
            procurement_cost_component_rows,
        )
        _write_csv(
            run_directory / "procurement_cost_by_route.csv",
            procurement_cost_route_rows,
        )
        _write_csv(
            run_directory / "cost_objective_reconciliation.csv",
            cost_objective_reconciliation_rows,
        )
        _write_csv(
            run_directory / "electricity_price_series.csv",
            electricity_price_series_rows,
        )
        _write_csv(
            run_directory / "executed_electricity_price_series.csv",
            executed_electricity_price_rows,
        )
    _write_csv(run_directory / "mode_comparison.csv", mode_comparison_rows)
    _write_csv(run_directory / "annual_anchor_reconciliation.csv", anchor_rows)
    _write_csv(run_directory / "independent_anchor_family_summary.csv", anchor_family_rows)
    _write_csv(run_directory / "validation_checks.csv", validation_rows)
    # Retain the historical filename for downstream readers and publish the
    # current gate-specific stop contract alongside it.
    _write_json(run_directory / "gate3_stage_gate.json", gate3_stage_gate)
    _write_json(run_directory / "gate4_stop.json", gate3_stage_gate)
    _write_csv(run_directory / "first_window_model_metrics.csv", [
        {"configuration_id": configuration, **{key: round(value, 8) for key, value in values.items()}}
        for configuration, values in annual_metrics.items()
    ])
    if c1_diagnosis is not None:
        _write_json(run_directory / "c1_capacity_diagnosis.json", c1_diagnosis)
    if downstream_capacity_diagnosis is not None:
        _write_json(run_directory / "c1_downstream_capacity_diagnosis.json", downstream_capacity_diagnosis)
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Annualisation uses actual executed UTC timestamp hours from concatenated first-local-day blocks; incomplete support remains a comparison diagnostic, not a year simulation.\n"
        "- Full-site anchors remain reporting context. Unit equality never makes a row comparable without a matching numerator, denominator and process/site boundary.\n"
        "- Reference production bands are scenario definitions and are excluded from independent validation scoring.\n"
        "- The uniform imported-slab envelope is an annual-cap conversion for this development case, not an observed delivery calendar.\n"
        "- Imported slab enters only HSM/WBW and receives no upstream site electricity, WAG, NG or direct-fuel CO2; represented downstream burdens remain with HSM.\n"
        "- C0/C1 material inventory handoff is implemented only for represented buffers. Steam, WAG and residuals do not become stored state or supply.\n"
        "- Full-site electricity, NG and Scope-1 residuals are signed coverage KPIs only; they are not model inputs and retain partial-provenance caveats.\n"
        "- Mode-B includes only carrier-specific WAG oxidation/flaring and named represented NG combustion; aggregate process counters remain excluded.\n"
        + (
            "- Fixed-reference central procurement prices are active lexicographically; route bands remain scenario definitions and hourly dispatch remains endogenous.\n"
            if cost_mode_active
            else "- No prices, DA, revenue, ETS, residual filling or full Scope 1 claim is active.\n"
        )
        + "- DA bidding, settlement, revenue, ETS, residual filling and a full Scope 1 claim remain inactive.\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": config["run_id"], "status": status, "c1_boundary_case": c1_case,
        "execution_mode": config.get("execution_mode", "endogenous_feasibility"),
        "c1_case_role": "all_endogenous_stresscase" if c1_case == "endogenous_6_75" else "MER_site_product_boundary",
        "replan_count": int(config["replan_count"]),
        "planning_horizon_hours": first_plan.planning_horizon_hours,
        "planning_horizon_hours_min": min(item.planning_horizon_hours for item in rolling_plans),
        "planning_horizon_hours_max": max(item.planning_horizon_hours for item in rolling_plans),
        "execution_block_hours": first_plan.execution_block_hours,
        "execution_block_hours_min": min(item.execution_block_hours for item in rolling_plans),
        "execution_block_hours_max": max(item.execution_block_hours for item in rolling_plans),
        "executed_hours": executed_hours_so_far - initial_executed_hours,
        "initial_executed_hours": initial_executed_hours,
        "terminal_executed_hours": executed_hours_so_far,
        "initial_cumulative_production_t": initial_cumulative,
        "terminal_cumulative_production_t": cumulative,
        "terminal_inventory_overrides_by_configuration": overrides,
        "terminal_handoff_snapshot_complete": handoff_contract[
            "terminal_handoff_snapshot_complete"
        ],
        "inter_window_handoff_continuity": handoff_contract[
            "inter_window_handoff_continuity"
        ],
        "handoff_validation_scope": handoff_contract["validation_scope"],
        "handoff_checked_transition_count": handoff_contract[
            "checked_transition_count"
        ],
        "handoff_checked_state_value_count": handoff_contract[
            "checked_state_value_count"
        ],
        "handoff_max_state_residual": handoff_contract["max_state_residual"],
        "cumulative_execution_t": cumulative, "annualisation_reporting_only": True,
        "rolling_production_progress_state_enabled": progress_state_enabled,
        "objective_hierarchy": (
            "production_progress_then_represented_procurement_cost_then_physical_tie_break"
            if cost_mode_active
            else "rolling_production_progress_then_physical_tie_break"
        ),
        "production_envelope_tolerance_fraction": production_envelope_fraction,
        "executed_annual_equivalent_t_y": {
            configuration: round(
                (cumulative[configuration] - initial_cumulative[configuration])
                * HOURS_PER_YEAR
                / (executed_hours_so_far - initial_executed_hours),
                6,
            )
            for configuration in CONFIGURATIONS
        },
        "maximum_abs_carried_production_credit_t": round(
            max(
                (
                    abs(_float(row.get("carried_credit_after_t")))
                    for row in production_progress_rows
                ),
                default=0.0,
            ),
            6,
        ),
        "c0_rolling_status": "pass" if len(c0_execution) == int(config["replan_count"]) else "fail",
        "c1_rolling_status": (
            "expected_infeasible_stresscase" if expected_stresscase
            else "pass" if len(c1_execution) == int(config["replan_count"])
            else "infeasible"
        ),
        "imported_slab_executed_t": round(c1_import_t, 6),
        "imported_slab_annualised_t_y": round(c1_import_annualised_t_y, 6),
        "imported_slab_annual_cap_t_y": import_cap_t_y,
        "origin_conservation_max_abs_annualised_residual_t_y": round(origin_residual, 9),
        "c1_downstream_capacity_diagnosis": downstream_capacity_diagnosis,
        "model_size_by_replan": [
            {
                "replan_index": row["replan_index"],
                "configuration_id": row["configuration_id"],
                "solver_name": row.get("solver_name"),
                "solver_status": row.get("solver_status"),
                "termination_condition": row.get("termination_condition"),
                "objective_value": row.get("objective_value"),
                "objective_type": row.get("objective_type"),
                "primary_cost_objective_eur": row.get("primary_cost_objective_eur"),
                "primary_cost_best_bound_eur": row.get("primary_cost_best_bound_eur"),
                "primary_cost_runtime_seconds": row.get("primary_cost_runtime_seconds"),
                "production_progress_objective_active": row.get(
                    "production_progress_objective_active"
                ),
                "production_progress_target_t": row.get(
                    "production_progress_target_t"
                ),
                "production_progress_optimum_deviation_t": row.get(
                    "production_progress_optimum_deviation_t"
                ),
                "production_progress_runtime_seconds": row.get(
                    "production_progress_runtime_seconds"
                ),
                "tie_break_objective_value": row.get("tie_break_objective_value"),
                "tie_break_cost_objective_eur": row.get("tie_break_cost_objective_eur"),
                "tie_break_runtime_seconds": row.get("tie_break_runtime_seconds"),
                "priced_flow_count": row.get("priced_flow_count"),
                "runtime_seconds": row.get("runtime_seconds"),
                "mip_gap": row.get("mip_gap"),
                "variable_count": row.get("variable_count"),
                "binary_count": row.get("binary_count"),
                "constraint_count": row.get("constraint_count"),
            }
            for row in model_audit_rows
        ],
        "anchor_rows": len(anchor_rows),
        "directly_comparable_anchor_rows": sum(row.get("comparability_status") == "directly_comparable" for row in anchor_rows),
        "partially_comparable_reporting_rows": sum(row.get("comparability_status") == "partially_comparable_reporting_only" for row in anchor_rows),
        "not_comparable_anchor_rows": sum(row.get("comparability_status") == "not_comparable" for row in anchor_rows),
        "scenario_definition_anchor_rows": sum(row.get("comparability_status") == "scenario_definition" for row in anchor_rows),
        "mode_comparison_rows": len(mode_comparison_rows),
        "phase_decision": gate3_stage_gate["decision"],
        "future_cost_objective_activation_status": (
            "active_fixed_reference_only" if cost_mode_active else "prepared_not_active"
        ),
        "procurement_cost_results": procurement_cost_configuration_rows,
        "cost_objective_reconciliation_status": (
            "pass" if cost_mode_active and cost_objective_reconciliation_pass
            else "not_applicable"
        ),
        "price_series_id": (
            config.get("price_series_id", "flat_central_reference_v1")
            if cost_mode_active
            else None
        ),
        "price_series_interface_status": (
            "validated_operational_rolling_slices"
            if cost_mode_active
            and price_series_timing_safe
            and price_series_has_no_realised_future
            else "separately_labelled_perfect_foresight_oracle"
            if cost_mode_active and perfect_foresight_oracle
            else "not_applicable"
        ),
        "independent_primary_configuration_family_pairs_below_7_5pct": primary_anchor_pairs,
        "contextual_configuration_family_pairs_below_7_5pct": contextual_anchor_pairs,
        "anchor_coverage_status": anchor_coverage_status,
        "first_order_full_site_co2_ledger_rows": len(first_order_co2_rows),
        "full_site_coverage_share_rows": len(coverage_share_rows),
        "parameter_range_exception_rows": len(parameter_range_exception_rows),
        "market_prices_enabled": False,
    }
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": "rolling_feasibility_anchor_reconciliation", "lineage_role": config.get("lineage_role", "gate_2_rolling_physical_evidence"), "output_policy": config.get("output_policy", "minimal"), "status": status})
    (run_directory / "README.md").write_text(
        f"# {config['run_id']}\n\n"
        f"- Run class: rolling feasibility and anchor reconciliation\n"
        f"- Lineage role: {config.get('lineage_role', 'rolling_physical_evidence')}\n"
        f"- Execution mode: {config.get('execution_mode', 'endogenous_feasibility')}\n"
        f"- Status: {status}\n"
        f"- Planning/execution: {min(item.planning_horizon_hours for item in rolling_plans)}-{max(item.planning_horizon_hours for item in rolling_plans)}-hour plans, {executed_hours_so_far - initial_executed_hours} actual executed timestamp hours\n"
        f"- Output policy: {config.get('output_policy', 'minimal')}\n"
        f"- Phase decision: {gate3_stage_gate['decision']}\n"
        f"- Deterministic procurement-cost objective: {'active fixed-reference only' if cost_mode_active else 'prepared, not active'}\n\n"
        "Annualised values are deterministic reporting equivalents from the solved rolling blocks, not a simulated calendar year. "
        "Use `resolved_config.yaml`, `input_manifest.json`, `rolling_model_metrics.csv`, `validation_checks.csv` and `run_summary.json` for reproduction and interpretation.\n",
        encoding="utf-8",
    )
    return {
        "run_directory": run_directory,
        "summary": summary,
        "execution_rows": execution_rows,
        "executed_hourly_rows": executed_hourly_rows,
        "anchor_rows": anchor_rows,
        "origin_rows": origin_rows,
        "physical_boundary_rows": physical_boundary_rows,
        "first_order_full_site_co2_rows": first_order_co2_rows,
        "full_site_coverage_share_rows": coverage_share_rows,
        "parameter_range_exception_rows": parameter_range_exception_rows,
        "anchor_family_rows": anchor_family_rows,
        "procurement_cost_rows": procurement_cost_configuration_rows,
        "gate3_stage_gate": gate3_stage_gate,
        "terminal_inventory_overrides_by_configuration": overrides,
        "terminal_cumulative_production_t": cumulative,
        "terminal_executed_hours": executed_hours_so_far,
        "rolling_timestamp_rows": rolling_timing_rows,
    }


def run_source_boundary_evidence_repair_family(
    *,
    config_path: str | Path,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    repair_stage: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run endogenous and reference modes under one repair-family lineage folder."""

    config_file = Path(config_path).resolve()
    base = _config(config_file)
    if not bool(base.get("paired_execution_modes", False)):
        raise ClosedLoopFeasibilityError(
            "Source-boundary repair families require paired_execution_modes: true."
        )
    stage = str(repair_stage or base.get("repair_stage", "none"))
    if stage not in {"downstream", "generator", "electricity"}:
        raise ClosedLoopFeasibilityError(
            "A concrete downstream, generator or electricity repair stage is required."
        )
    family_run_id = str(run_id or base["run_id"])
    parent = Path(output_root).resolve() / family_run_id
    if parent.exists():
        raise ClosedLoopFeasibilityError(f"Repair-family run directory already exists: {parent}")
    parent.mkdir(parents=True)
    activation = "full_electricity_boundary" if stage == "electricity" else "full"
    common = {
        "repair_stage": stage,
        "development_controller_activation": activation,
        "lineage_role": "pre_economics_source_boundary_evidence_repair",
    }
    endogenous = run_closed_loop_feasibility_anchor_reconciliation(
        config_path=config_file,
        output_root=parent,
        scenario_overrides={
            **common,
            "run_id": "endogenous",
            "execution_mode": "endogenous_feasibility",
            "comparison_run_id": "",
        },
    )
    reference = run_closed_loop_feasibility_anchor_reconciliation(
        config_path=config_file,
        output_root=parent,
        scenario_overrides={
            **common,
            "run_id": "reference",
            "execution_mode": "reference_validation",
            "comparison_run_id": "endogenous",
        },
    )
    combined_anchor_rows = [
        {"repair_execution_mode": "endogenous_feasibility", **row}
        for row in endogenous["anchor_rows"]
    ] + [
        {"repair_execution_mode": "reference_validation", **row}
        for row in reference["anchor_rows"]
        if str(row.get("anchor_id", "")).startswith("c1_generator")
        or row.get("anchor_id")
        in {"c1_vn25_ng_4_1", "c1_vn25_total_fuel_13_7", "c1_ij01_total_fuel_0_8"}
    ]
    anchor_families = _annual_anchor_family_summary(combined_anchor_rows)
    primary_pairs = sum(
        row.get("primary_pair_below_7_5pct") == "yes" for row in anchor_families
    )
    comparison_rows = _mode_comparison_rows(
        endogenous["physical_boundary_rows"],
        reference["physical_boundary_rows"],
        endogenous_run_id=f"{family_run_id}/endogenous",
        reference_run_id=f"{family_run_id}/reference",
    )
    _write_csv(parent / "repair_mode_comparison.csv", comparison_rows)
    _write_csv(parent / "repair_anchor_reconciliation.csv", combined_anchor_rows)
    _write_csv(parent / "repair_anchor_family_summary.csv", anchor_families)
    status = (
        "pass"
        if endogenous["summary"]["status"] == "pass"
        and reference["summary"]["status"] == "pass"
        else "fail"
    )
    readiness = (
        "ready_for_deterministic_energy_cost_design"
        if status == "pass"
        and endogenous["gate3_stage_gate"]["decision"] == "ready_for_deterministic_energy_cost_design"
        and reference["gate3_stage_gate"]["decision"] == "ready_for_deterministic_energy_cost_design"
        else "not_ready"
    )
    summary = {
        "run_id": family_run_id,
        "status": status,
        "repair_stage": stage,
        "run_class": "source_boundary_evidence_repair",
        "lineage_role": "pre_economics_physical_gate",
        "endogenous_status": endogenous["summary"]["status"],
        "reference_status": reference["summary"]["status"],
        "independent_pre_cost_configuration_family_pairs_below_7_5pct": primary_pairs,
        "historical_four_operational_anchor_rule": "superseded_not_a_readiness_gate",
        "cost_design_readiness": readiness,
        "future_cost_objective_activation_status": "prepared_not_active",
        "markets_and_costs_enabled": False,
    }
    _write_json(parent / "repair_summary.json", summary)
    _write_json(
        parent / "registry_entry.json",
        {
            "run_id": family_run_id,
            "run_class": "source_boundary_evidence_repair",
            "lineage_role": "pre_economics_physical_gate",
            "output_policy": "minimal",
            "status": status,
        },
    )
    return {
        "run_directory": parent,
        "summary": summary,
        "endogenous": endogenous,
        "reference": reference,
    }
