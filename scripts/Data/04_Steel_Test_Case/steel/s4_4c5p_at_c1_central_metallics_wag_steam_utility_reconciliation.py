"""Integrated C1 physical utility reconciliation around the central metallics case.

This diagnostic runs the existing C1 model-builder surfaces together: the
bounded BOF/EAF metallics ledger, carrier-specific WAG controllers, boiler
scaffold and generator interface.  It deliberately does not add an allocator,
residual load, Wobbe/mixed-gas model, market term or aggregate-process CO2.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pyomo.environ import Constraint, Objective, maximize, value

from .model import collect_model_stats
from .s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from .s4_4c5p_as_c1_bof_eaf_metallics_ledger import (
    DEFAULT_CONFIG as METALLICS_CONFIG,
    _load_config as _load_metallics_config,
    _scenario_maps,
)
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    SELECTED_WAG_LHV_MJ_PER_NM3,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)
from .wag_development_controller_contract import BOILER_FUEL_PATH, BOILER_STEAM_DEMAND_PATH


STAGE = "S4.4c5p_at_c1_central_metallics_wag_steam_utility_reconciliation"
HOURS_PER_YEAR = 8760.0
DEFAULT_RUN_ID = "steel_c1_central_metallics_wag_steam_utility_reconciliation_v1"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
ANCHOR_REGISTER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "c5_model_anchor_register"
    / "c5_model_anchor_evidence_register.csv"
)
REPORT_PATH = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_C1_CENTRAL_METALLICS_WAG_STEAM_UTILITY_RECONCILIATION.md"
OVERLAY_ELECTRICITY_PATH = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4"
    / "s4_4c5p_i_source_card_candidate_overlay_reconciliation" / "c5_candidate_overlay_electricity_by_plant.csv"
)
EAF_DEVELOPMENT_INPUT_PATH = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4"
    / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff" / "s4_4c5o_b_eaf_development_input_rows.csv"
)

# Approximate visual bands transcribed from the user-supplied Badarinath
# price-insensitive boxplots.  They are deliberately context-only: the thesis
# figures redact the underlying plant data and do not expose a machine-readable
# sample, denominator or exact quantiles.
BADARINATH_C1_PRICE_INSENSITIVE_VISUAL_BANDS = (
    ("December", "Sintering Plant", 6.0, 8.0, 10.0),
    ("December", "Pelletizing Plant", 15.0, 18.0, 20.0),
    ("December", "Blast Furnace 6", 8.0, 9.0, 10.0),
    ("December", "Basic Oxygen Plant", 16.0, 19.0, 22.0),
    ("December", "Linde Plant", 85.0, 100.0, 105.0),
    ("December", "DRP", 52.0, 60.0, 68.0),
    ("December", "EAF", 235.0, 250.0, 258.0),
    ("December", "DSP Plant", 7.0, 15.0, 25.0),
    ("December", "Hot Strip Mill", 50.0, 55.0, 57.0),
    ("July", "Sintering Plant", 6.0, 8.0, 10.0),
    ("July", "Pelletizing Plant", 15.0, 18.0, 20.0),
    ("July", "Blast Furnace 6", 7.0, 9.0, 10.0),
    ("July", "Basic Oxygen Plant", 16.0, 19.0, 22.0),
    ("July", "Linde Plant", 85.0, 100.0, 106.0),
    ("July", "DRP", 52.0, 60.0, 68.0),
    ("July", "EAF", 235.0, 250.0, 258.0),
    ("July", "DSP Plant", 7.0, 15.0, 25.0),
    ("July", "Hot Strip Mill", 52.0, 55.0, 58.0),
    ("August", "Sintering Plant", 7.0, 9.0, 11.0),
    ("August", "Pelletizing Plant", 15.0, 18.0, 20.0),
    ("August", "Blast Furnace 6", 8.0, 9.0, 10.0),
    ("August", "Basic Oxygen Plant", 16.0, 18.0, 20.0),
    ("August", "Linde Plant", 85.0, 100.0, 105.0),
    ("August", "DRP", 51.0, 58.0, 68.0),
    ("August", "EAF", 235.0, 248.0, 255.0),
    ("August", "DSP Plant", 7.0, 15.0, 25.0),
    ("August", "Hot Strip Mill", 52.0, 55.0, 58.0),
)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sum(model: Any, name: str) -> float:
    component = getattr(model, name)
    return sum(float(value(component[t])) for t in model.TIME)


def _annualise(value_horizon: float, horizon_hours: int) -> float:
    return value_horizon * HOURS_PER_YEAR / float(horizon_hours)


def _mwh_to_pj(value_mwh: float) -> float:
    return value_mwh * 3.6 / 1_000_000.0


def _quantile(values: list[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise ValueError("Quantile requires values and a probability in [0, 1].")
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    lower = math.floor(location)
    upper = math.ceil(location)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (location - lower)


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _file_record(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path),
        "status": "read" if path.exists() else "missing",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "",
    }


def _anchor_map() -> dict[str, dict[str, str]]:
    return {row["anchor_id"]: row for row in _read_csv(ANCHOR_REGISTER)}


def _candidate_value(path: Path, **criteria: str) -> float:
    row = next(
        (candidate for candidate in _read_csv(path) if all(candidate.get(key) == expected for key, expected in criteria.items())),
        None,
    )
    if row is None:
        raise ValueError(f"Missing candidate row in {path.name}: {criteria}")
    for field in ("candidate_value", "base_value"):
        if row.get(field):
            return float(row[field])
    raise ValueError(f"Candidate row has no numeric value in {path.name}: {criteria}")


def _anchor_value_in_unit(anchor: dict[str, str], expected_unit: str, fallback: float) -> float:
    """Convert only transparent annual energy units used by this diagnostic."""
    if not anchor:
        return fallback
    value = float(anchor["converted_value"])
    unit = anchor.get("converted_unit", "")
    if unit == expected_unit:
        return value
    if unit == "PJ/y" and expected_unit == "TWh/y":
        return value / 3.6
    if unit == "TWh/y" and expected_unit == "PJ/y":
        return value * 3.6
    return fallback


def _scenario(config: dict[str, Any], scenario_id: str | None = None) -> dict[str, Any]:
    selected_id = scenario_id or "rounded_central_named_consumption"
    return next(row for row in config["scenarios"] if row["scenario_id"] == selected_id)


def _hsm_carrier_precedence(config: dict[str, Any]) -> tuple[str, ...] | None:
    """Read an explicit diagnostic controller order without creating a gas mix."""

    policy = config.get("wag_controller_policy", {})
    precedence = policy.get("hsm_carrier_precedence")
    return tuple(str(carrier) for carrier in precedence) if precedence is not None else None


def _hsm_eligible_carriers(config: dict[str, Any]) -> tuple[str, ...] | None:
    """Read a source-labelled eligibility set; it never creates a gas mix."""

    policy = config.get("wag_controller_policy", {})
    eligible = policy.get("hsm_eligible_carriers")
    return tuple(str(carrier) for carrier in eligible) if eligible is not None else None


def _generator_interface_cap_mode(config: dict[str, Any]) -> str:
    """Keep the inherited profile cap unless a scenario explicitly selects the volume envelope."""

    policy = config.get("wag_controller_policy", {})
    return str(policy.get("generator_interface_cap_mode", "inherited_profile"))


def _route_band(scenario: dict[str, Any]) -> dict[str, float] | None:
    raw = scenario.get("c1_liquid_steel_route_band")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("c1_liquid_steel_route_band must be a mapping when supplied.")
    return {key: float(value) for key, value in raw.items()}


def _linde_n2_auxiliary_electricity_mwh_h(config: dict[str, Any], override: float | None) -> float:
    """Use only an explicit source-context auxiliary load; never create a residual electricity bucket."""

    value = config.get("linde_n2_auxiliary_electricity_mwh_h", 0.0) if override is None else override
    value = float(value)
    if value < 0.0:
        raise ValueError("Linde N2 auxiliary electricity must be non-negative.")
    return value


def _electricity_boundary_overrides(scenario: dict[str, Any]) -> dict[str, float]:
    """Read explicit source-labelled sensitivity values; no residual electricity is created."""

    raw = scenario.get("electricity_boundary_overrides", {})
    if not isinstance(raw, dict):
        raise ValueError("electricity_boundary_overrides must be a mapping when supplied.")
    allowed = {
        "eaf_secondary_electricity_mwh_per_t_ls",
        "dsp_electricity_mwh_per_t_coil",
    }
    unknown = set(raw).difference(allowed)
    if unknown:
        raise ValueError(f"Unsupported electricity-boundary override(s): {sorted(unknown)}")
    values = {key: float(value) for key, value in raw.items()}
    if any(value < 0.0 for value in values.values()):
        raise ValueError("Electricity-boundary overrides must be non-negative.")
    return values


def _wag_lhv_source_factor_override(scenario: dict[str, Any]) -> dict[str, float] | None:
    """Read one source-labelled carrier-LHV sensitivity without changing inputs.

    This changes only the energy represented by already modelled carrier
    volumes.  Process heat demand remains in its existing energy basis, so the
    helper cannot create a WAG/NG ratio, a mixed carrier, or a residual plug.
    """

    raw = scenario.get("wag_lhv_mj_per_nm3_override")
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"BFG", "COG", "BOFG"}:
        raise ValueError("wag_lhv_mj_per_nm3_override must define exactly BFG, COG and BOFG.")
    values = {carrier: float(value) for carrier, value in raw.items()}
    if any(value <= 0.0 for value in values.values()):
        raise ValueError("WAG LHV sensitivity values must be positive.")
    return values


def _apply_wag_lhv_source_factor_override(
    inputs: Any,
    override: dict[str, float] | None,
) -> Any:
    """Return a transient C1 input copy with factor-consistent WAG generation.

    Source gas volumes are preserved.  The KGF underfiring and sinter demand
    rows are already energy-basis demands and intentionally do not change.
    """

    if override is None:
        return inputs
    retained = inputs.retained_bf_bof
    if retained is None:
        raise ValueError("Carrier-LHV sensitivity requires the retained C1 BF-BOF route.")
    return replace(
        inputs,
        retained_bf_bof=replace(
            retained,
            bfg_mwh_per_t_hot_iron=retained.bfg_nm3_per_t_hot_iron * override["BFG"] / 3600.0,
            cog_mwh_per_t_coke=retained.cog_m3_per_t_dry_coal * override["COG"] / 3600.0,
            bofg_mwh_per_t_liquid_steel=retained.bofg_nm3_per_t_liquid_steel * override["BOFG"] / 3600.0,
        ),
    )


def _build_and_solve(
    *,
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float | None = None,
    downstream_boundary_case: str = "mer_site_product",
    metallics_config_path: str | Path = METALLICS_CONFIG,
    scenario_id: str | None = None,
) -> tuple[Any, dict[str, Any], float, str, dict[str, Any]]:
    config = _load_metallics_config(Path(metallics_config_path))
    horizon_hours = int(config["horizon_hours"])
    scenario = _scenario(config, scenario_id)
    eaf, bof, ledger = _scenario_maps(config, scenario, horizon_hours)
    annual_target_mt_y = scenario.get("annual_target_mt_y")
    hsm_carrier_precedence = _hsm_carrier_precedence(config)
    hsm_eligible_carriers = _hsm_eligible_carriers(config)
    generator_interface_cap_mode = _generator_interface_cap_mode(config)
    c1_liquid_steel_route_band = _route_band(scenario)
    linde_n2_auxiliary_electricity_mwh_h = _linde_n2_auxiliary_electricity_mwh_h(
        config, linde_n2_auxiliary_electricity_mwh_h
    )
    electricity_boundary_overrides = _electricity_boundary_overrides(scenario)
    wag_lhv_override = _wag_lhv_source_factor_override(scenario)
    base_inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=horizon_hours,
        include_retained_bf_bof=True,
    )
    target_multiplier = 1.0
    target_horizon_t: float | None = None
    if annual_target_mt_y not in (None, ""):
        target_horizon_t = float(annual_target_mt_y) * 1_000_000.0 * horizon_hours / HOURS_PER_YEAR
        target_multiplier = target_horizon_t / base_inputs.final_product_target_t
    inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=horizon_hours,
        target_multiplier=target_multiplier,
        include_retained_bf_bof=True,
    )
    # The downstream-origin interface changes the final-product conversion.
    # Preserve the declared annual quota directly on the final-product
    # constraint instead of indirectly scaling a pre-origin proxy target.
    if target_horizon_t is not None:
        inputs = replace(inputs, final_product_target_t=target_horizon_t)
    inputs = _apply_wag_lhv_source_factor_override(inputs, wag_lhv_override)
    if downstream_boundary_case not in {"endogenous_6_75", "mer_site_product"}:
        raise ValueError("downstream_boundary_case must be endogenous_6_75 or mer_site_product.")
    downstream_routing = build_c1_uniform_import_routing(load_source_values(), horizon_hours=horizon_hours)
    if downstream_boundary_case == "endogenous_6_75":
        downstream_routing = {**downstream_routing, "imported_slab_max_t_h": 0.0}
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        development_controller_activation="full_electricity_boundary",
        hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity_mwh_per_t_hrc_override,
        linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
        c1_retained_route_policy="quota_driven_topology",
        commitment_granularity="daily_binary_hourly_throughput",
        downstream_origin_routing=downstream_routing,
        eaf_material_balance=eaf,
        bof_material_balance=bof,
        scrap_supply_ledger=ledger,
        c1_coke_chain_reconciliation={key: float(value) for key, value in config["source_coke_chain"].items()},
        hsm_carrier_precedence=hsm_carrier_precedence,
        hsm_eligible_carriers=hsm_eligible_carriers,
        generator_interface_cap_mode=generator_interface_cap_mode,
        c1_liquid_steel_route_band=c1_liquid_steel_route_band,
        eaf_secondary_electricity_mwh_per_t_ls_override=electricity_boundary_overrides.get("eaf_secondary_electricity_mwh_per_t_ls"),
        dsp_electricity_mwh_per_t_coil_override=electricity_boundary_overrides.get("dsp_electricity_mwh_per_t_coil"),
    )
    target_required = annual_target_mt_y not in (None, "")
    solver_name, solver = _select_solver()
    if solver_name is None or solver is None:
        raise RuntimeError("No configured solver is available.")
    _apply_solver_time_limit(solver_name, solver, float(config["solver_time_limit_seconds"]))
    start = time.perf_counter()
    if target_required:
        result = solver.solve(model)
        first_termination = str(result.solver.termination_condition).lower()
        maximum_final_product = sum(float(value(model.final_product_output[t])) for t in model.TIME)
    else:
        model.final_product_fulfilment.deactivate()
        model.static_price_naive_objective.deactivate()
        model.utility_reconciliation_capacity_objective = Objective(
            expr=sum(model.final_product_output[t] for t in model.TIME),
            sense=maximize,
        )
        result = solver.solve(model)
        first_termination = str(result.solver.termination_condition).lower()
        if first_termination not in {"optimal", "feasible"}:
            raise RuntimeError(f"Central metallics utility reconciliation has no accepted capacity solution: {first_termination}")
        maximum_final_product = sum(float(value(model.final_product_output[t])) for t in model.TIME)
        # Preserve the capacity result and then use the builder's existing
        # controller/flare tie-breaker.  This avoids treating flaring as free
        # just because a capacity diagnostic has no economic objective.
        model.utility_reconciliation_capacity_objective.deactivate()
        model.final_product_capacity_preservation = Constraint(
            expr=sum(model.final_product_output[t] for t in model.TIME)
            >= maximum_final_product - 1e-6,
        )
        model.static_price_naive_objective.activate()
        result = solver.solve(model)
    elapsed = time.perf_counter() - start
    termination = str(result.solver.termination_condition).lower()
    if termination not in {"optimal", "feasible"}:
        raise RuntimeError(f"Central metallics utility reconciliation controller solve failed: {termination}")
    return model, config, elapsed, solver_name, {
        "scenario": scenario,
        "stats": collect_model_stats(model),
        "termination": termination,
        "capacity_termination": first_termination,
        "maximum_final_product_horizon_t": maximum_final_product,
        "target_required": target_required,
        "annual_target_mt_y": float(annual_target_mt_y) if target_required else None,
        "downstream_boundary_case": downstream_boundary_case,
        "downstream_origin_routing": downstream_routing,
        "hsm_carrier_precedence": list(hsm_carrier_precedence) if hsm_carrier_precedence is not None else None,
        "hsm_eligible_carriers": list(hsm_eligible_carriers) if hsm_eligible_carriers is not None else None,
        "generator_interface_cap_mode": generator_interface_cap_mode,
        "c1_liquid_steel_route_band": c1_liquid_steel_route_band,
        "electricity_boundary_overrides": electricity_boundary_overrides,
        "wag_lhv_mj_per_nm3_override": wag_lhv_override,
    }


def _carrier_rows(
    model: Any,
    horizon_hours: int,
    lhv_mj_per_nm3: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    selected_lhv = lhv_mj_per_nm3 or SELECTED_WAG_LHV_MJ_PER_NM3
    sinks = {
        "BFG": {
            "process_or_self_use": ("bfg_to_bf_hot_stove", "bfg_to_kgf1"),
            "hsm_or_pefa": ("bfg_to_hsm",),
            "steam_boiler": ("bfg_to_boiler",),
            "generator": ("bfg_to_vattenfall",),
            "flare": ("bfg_flared",),
            "generated": "bfg_generated",
            "activity": "bf6_hot_iron_output",
            "activity_basis": "t_hot_metal/y",
        },
        "COG": {
            "process_or_self_use": ("cog_to_kgf1", "cog_to_kgf2", "cog_to_sinter"),
            "hsm_or_pefa": ("cog_to_hsm", "cog_to_pefa_branderij"),
            "steam_boiler": ("cog_to_boiler",),
            "generator": ("cog_to_vattenfall",),
            "flare": ("cog_flared",),
            "generated": "cog_generated",
            "activity": "coking_plant_1",
            "activity_basis": "t_dry_coal/y",
        },
        "BOFG": {
            "process_or_self_use": (),
            "hsm_or_pefa": ("bofg_to_hsm", "bofg_to_pefa_malerij"),
            "steam_boiler": (),
            "generator": ("bofg_to_vattenfall",),
            "flare": ("bofg_flared",),
            "generated": "bofg_generated",
            "activity": "bof_crude_steel_output",
            "activity_basis": "t_liquid_steel/y",
        },
    }
    rows: list[dict[str, Any]] = []
    for carrier, mapping in sinks.items():
        generated = _annualise(_sum(model, mapping["generated"]), horizon_hours)
        activity = _annualise(_sum(model, mapping["activity"]), horizon_hours)
        values = {
            name: sum(_annualise(_sum(model, component), horizon_hours) for component in components)
            for name, components in mapping.items()
            if name not in {"generated", "activity", "activity_basis"}
        }
        accounted = sum(values.values())
        rows.append(
            {
                "configuration": "C1",
                "carrier": carrier,
                "source_activity_t_y": round(activity, 6),
                "source_activity_basis": mapping["activity_basis"],
                "implied_generation_MWh_LHV_per_activity_t": round(generated / activity, 9) if activity else "",
                "selected_LHV_MJ_per_Nm3": selected_lhv[carrier],
                "generation_MWh_LHV_y": round(generated, 6),
                "process_or_self_use_MWh_LHV_y": round(values["process_or_self_use"], 6),
                "hsm_pefa_MWh_LHV_y": round(values["hsm_or_pefa"], 6),
                "steam_boiler_MWh_LHV_y": round(values["steam_boiler"], 6),
                "generator_MWh_LHV_y": round(values["generator"], 6),
                "flare_MWh_LHV_y": round(values["flare"], 6),
                "residual_MWh_LHV_y": round(generated - accounted, 9),
                "balance_status": "pass" if abs(generated - accounted) <= 1e-5 else "fail",
                "physical_carrier_status": "carrier_specific_accepted",
                "caveat": "Annualised representative-week diagnostic; no mixed or aggregate WAG is allocated physically.",
            }
        )
    return rows


def _sink_mix_rows(model: Any, horizon_hours: int) -> list[dict[str, Any]]:
    """Expose every represented carrier-to-sink flow without forming a mixed-gas pool."""

    flows = (
        ("BFG", "BF hot stove", "bfg_to_bf_hot_stove", "mandatory_process_self_use"),
        ("COG", "KGF1 underfiring", "cog_to_kgf1", "mandatory_process_self_use"),
        ("COG", "KGF2 underfiring", "cog_to_kgf2", "mandatory_process_self_use"),
        ("COG", "sinter", "cog_to_sinter", "mandatory_process_self_use"),
        ("BFG", "HSM reheat", "bfg_to_hsm", "HSM_controller"),
        ("COG", "HSM reheat", "cog_to_hsm", "HSM_controller"),
        ("BOFG", "HSM reheat", "bofg_to_hsm", "HSM_controller"),
        ("NG", "HSM reheat", "ng_to_hsm_mwh", "HSM_named_backup"),
        ("BOFG", "PEFA Malerij", "bofg_to_pefa_malerij", "PEFA_controller"),
        ("COG", "PEFA Branderij", "cog_to_pefa_branderij", "PEFA_controller"),
        ("NG", "PEFA Malerij", "ng_to_pefa_malerij_mwh", "PEFA_named_backup"),
        ("NG", "PEFA Branderij", "ng_to_pefa_branderij_mwh", "PEFA_named_backup"),
        ("BFG", "15-bar boiler bridge", "bfg_to_boiler", "steam_utility"),
        ("COG", "15-bar boiler bridge", "cog_to_boiler", "steam_utility"),
        ("NG", "15-bar boiler bridge", "ng_to_boiler_mwh", "steam_named_backup"),
        ("BFG", "VN25/IJ01 interface", "bfg_to_vattenfall", "generator_interface"),
        ("COG", "VN25/IJ01 interface", "cog_to_vattenfall", "generator_interface"),
        ("BOFG", "VN25/IJ01 interface", "bofg_to_vattenfall", "generator_interface"),
        ("BFG", "flare", "bfg_flared", "carrier_specific_flare"),
        ("COG", "flare", "cog_flared", "carrier_specific_flare"),
        ("BOFG", "flare", "bofg_flared", "carrier_specific_flare"),
    )
    rows: list[dict[str, Any]] = []
    hsm_precedence = ">".join(getattr(model, "hsm_carrier_precedence", ()))
    for carrier, sink, component, role in flows:
        annual_mwh = _annualise(_sum(model, component), horizon_hours)
        rows.append(
            {
                "configuration": "C1",
                "carrier": carrier,
                "sink": sink,
                "controller_role": role,
                "annual_MWh_LHV_y": round(annual_mwh, 6),
                "physical_carrier_flow": "yes",
                "hsm_precedence_if_applicable": hsm_precedence if sink == "HSM reheat" else "",
                "caveat": "Carrier-specific realised flow; no aggregate or mixed WAG carrier is created.",
            }
        )
    return rows


def _physical_flow_trace_rows(
    sink_mixes: list[dict[str, Any]],
    origin_material: list[dict[str, Any]],
    utilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Trace active C1 flows from governed input class to annual output.

    The trace is deliberately an evidence index, not a second physical ledger.
    Values remain in the dedicated material, carrier and utility ledgers.
    """
    origin_value = {str(row["metric"]): row.get("annual_value", "") for row in origin_material}
    utility_value = {str(row["metric"]): row.get("model_value", "") for row in utilities}
    material_flows = (
        ("coking_dry_coal_to_coke", "material", "process_units.csv; source_coke_chain", "coke_output", "coke_balance", "carrier activity and material continuity", "executable", "Coke output is derived from named dry-coal to coke conversion."),
        ("sinter_to_retained_bf6", "material", "process_units.csv; process_io_coefficients.csv", "blast_furnace_6", "sinter_balance", "represented retained-route material balance", "executable", "Retained BF6 sinter feed is explicit."),
        ("bf6_hot_metal_to_bof", "material", "process_io_coefficients.csv", "bf6_hot_iron_output", "hot_iron_balance", "endogenous_BOF_liquid_steel", "executable", "Hot metal remains a separate material handoff."),
        ("bof_liquid_steel_to_hsm", "material", "process_io_coefficients.csv; downstream origin routing", "bof_to_hsm_slab", "hsm_input_balance", "BOF_to_HSM_slab", "executable", "BOF slab keeps its origin tag."),
        ("drp_pellets_to_dri", "material", "process_units.csv; process_io_coefficients.csv", "drp_pellet_input", "dri_balance", "endogenous_EAF_liquid_steel", "executable", "DRP and DRI buffer are explicit C1 material layers."),
        ("dri_and_named_scrap_to_eaf", "material", "process_io_coefficients.csv; metallics scenario", "eaf_liquid_steel_output", "eaf_material_balance", "endogenous_EAF_liquid_steel", "executable", "BOF and EAF metallics remain separately labelled."),
        ("eaf_liquid_steel_to_hsm", "material", "downstream origin routing", "eaf_to_hsm_slab", "hsm_input_balance", "EAF_to_HSM_slab", "executable", "EAF slab keeps its origin tag."),
        ("imported_slab_to_hsm", "material", "downstream origin routing", "imported_slab_to_hsm", "hsm_input_balance", "imported_slab_to_HSM", "executable", "Imported slab has no upstream site energy, WAG, NG or CO2 assignment."),
        ("hsm_and_dsp_to_final_product", "material", "downstream origin routing", "final_product_output", "final_product_fulfilment", "site_final_product", "executable", "HSM and DSP remain distinct downstream routes."),
    )
    rows = [
        {
            "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "flow_id": flow_id,
            "carrier_or_material": carrier_or_material,
            "input_source": input_source,
            "activity_basis": "see named source row",
            "pyomo_component": component,
            "pyomo_constraint_or_expression": constraint,
            "annual_ledger_destination": ledger,
            "annual_value": origin_value.get(ledger, ""),
            "annual_unit": "t/y",
            "anchor_numerator_role": "final_product_output" if ledger == "site_final_product" else "supporting_material_ledger",
            "classification": classification,
            "caveat": caveat,
        }
        for flow_id, carrier_or_material, input_source, component, constraint, ledger, classification, caveat in material_flows
    ]
    for sink in sink_mixes:
        carrier = str(sink["carrier"])
        sink_name = str(sink["sink"])
        rows.append(
            {
                "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "flow_id": f"{carrier.lower()}_to_{sink_name.lower().replace(' ', '_').replace('/', '_')}",
                "carrier_or_material": carrier,
                "input_source": "wag_generation_coefficients.csv; wag_sink_eligibility.csv; C5 controller profile",
                "activity_basis": "carrier-specific MWh_LHV/y",
                "pyomo_component": sink_name,
                "pyomo_constraint_or_expression": "carrier balance or explicit controller demand",
                "annual_ledger_destination": "wag_sink_mix_ledger.csv; wag_carrier_ledger.csv",
                "annual_value": sink["annual_MWh_LHV_y"],
                "annual_unit": "MWh_LHV/y",
                "anchor_numerator_role": "generator_or_flare_WAG_anchor" if sink_name in {"VN25/IJ01 interface", "flare"} else "supporting_carrier_ledger",
                "classification": "executable",
                "caveat": str(sink["caveat"]),
            }
        )
    for metric in (
        "gross_electricity",
        "internal_WAG_generator_electricity_offset",
        "net_grid_import_after_internal_WAG_offset",
        "modelled_steam_15bar_demand",
        "modelled_steam_15bar_supply",
        "modelled_steam_15bar_unserved",
        "named_NG_HSM_PEFA_boiler_energy",
        "WAG_explicit_combustion_CO2",
    ):
        rows.append(
            {
                "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "flow_id": metric,
                "carrier_or_material": "utility_or_emissions",
                "input_source": "governed controller profile or explicit model expression",
                "activity_basis": "annualised representative-week output",
                "pyomo_component": metric,
                "pyomo_constraint_or_expression": "represented utility or Mode-B expression",
                "annual_ledger_destination": "utility_energy_co2_ledger.csv",
                "annual_value": utility_value.get(metric, ""),
                "annual_unit": "see utility ledger",
                "anchor_numerator_role": "anchor_or_visible_residual_context",
                "classification": "executable",
                "caveat": "Reported at represented boundary; it never creates a residual energy input.",
            }
        )
    rows.extend(
        [
            {
                "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "flow_id": "full_site_electricity_residual",
                "carrier_or_material": "electricity",
                "input_source": "official site context only",
                "activity_basis": "site annual context",
                "pyomo_component": "none",
                "pyomo_constraint_or_expression": "none",
                "annual_ledger_destination": "anchor_comparison.csv",
                "annual_value": "",
                "annual_unit": "TWh/y",
                "anchor_numerator_role": "reporting residual only",
                "classification": "diagnostic",
                "caveat": "Visible comparison residual; never a model load or allocation input.",
            },
            {
                "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "flow_id": "full_site_ng_and_scope1_residual",
                "carrier_or_material": "natural_gas_and_CO2",
                "input_source": "official site context only",
                "activity_basis": "site annual context",
                "pyomo_component": "none",
                "pyomo_constraint_or_expression": "none",
                "annual_ledger_destination": "anchor_comparison.csv",
                "annual_value": "",
                "annual_unit": "PJ_LHV/y; MtCO2/y",
                "anchor_numerator_role": "reporting residual only",
                "classification": "blocked",
                "caveat": "No non-overlapping source-backed process drivers exist for the missing site boundary.",
            },
        ]
    )
    return rows


def _utility_rows(model: Any, horizon_hours: int) -> list[dict[str, Any]]:
    annual = lambda component: _annualise(_sum(model, component), horizon_hours)
    controller_ng_mwh = sum(annual(component) for component in (
        "ng_to_hsm_mwh", "ng_to_pefa_malerij_mwh", "ng_to_pefa_branderij_mwh", "ng_to_boiler_mwh",
    ))
    named_ng_nm3 = annual("natural_gas_nm3")
    rows = [
        {
            "metric": "final_product_output",
            "model_value": round(annual("final_product_output") / 1_000_000.0, 6),
            "unit": "Mt/y",
            "boundary_status": "active_final_product_proxy",
            "caveat": "Central bounded BOF/EAF metallics capacity diagnostic, not an exact 6.75-Mt quota solve.",
        },
        {
            "metric": "gross_electricity",
            "model_value": round(annual("gross_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "represented_process_plus_HSM_PEFA_gross_load",
            "caveat": "Not a complete site electricity boundary; residual electricity remains visible.",
        },
        {
            "metric": "BOF_electricity_development",
            "model_value": round(annual("bof_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "source_traceable_development_BOF_load",
            "caveat": "Development-only BOF electricity candidate; it is throughput-linked and separate from residual site electricity.",
        },
        {
            "metric": "BF_electricity_development",
            "model_value": round(annual("bf_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "source_traceable_development_BF_load",
            "caveat": "Source-backed BF electricity on active BF6 hot-metal throughput; it does not imply a full-site auxiliary-electricity claim.",
        },
        {
            "metric": "KGF_electricity_development",
            "model_value": round(annual("kgf_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "source_traceable_development_KGF_load",
            "caveat": "Development-only purchased KGF electricity candidate on coke-output basis; no generic other-electricity bucket is used.",
        },
        {
            "metric": "DSP_electricity_development",
            "model_value": round(annual("dsp_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "source_traceable_development_DSP_load",
            "caveat": "Development-only DSP rolling/casting electricity on final-coil output; tunnel-furnace fuel remains inactive.",
        },
        {
            "metric": "EAF_secondary_electricity_sensitivity",
            "model_value": round(annual("eaf_secondary_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "explicit_source_labelled_sensitivity_load",
            "caveat": "Separate throughput-linked secondary-metallurgy electricity; active only when the scenario explicitly supplies its source-labelled intensity.",
        },
        {
            "metric": "ASU_electricity_development",
            "model_value": round(annual("asu_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "source_traceable_development_ASU_load",
            "caveat": "Development-only gaseous-O2 electricity on represented DRP/EAF plus BOF O2 demand; it does not cover unmodelled O2 uses or other air gases.",
        },
        {
            "metric": "Linde_N2_auxiliary_electricity_context",
            "model_value": round(annual("linde_n2_auxiliary_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "explicit_nonsteel_site_context_load",
            "caveat": "Athanasiadis-style N2/auxiliary Linde electricity context. It is separate from O2 intensity, material demand, residual electricity and flexibility.",
        },
        {
            "metric": "Linde_total_meter_electricity_context",
            "model_value": round(annual("linde_total_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "O2_process_plus_N2_auxiliary_context",
            "caveat": "Comparable to a Linde plant-meter context only; it is not an official Tata meter claim or a steel-process intensity.",
        },
        {
            "metric": "sinter_electricity_development",
            "model_value": round(annual("sinter_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "source_traceable_development_sinter_load",
            "caveat": "Development utility proxy on active sinter throughput; its COG heat use remains a separate carrier-specific WAG sink.",
        },
        {
            "metric": "BOF_oxygen_development",
            "model_value": round(annual("bof_oxygen_development_t") / 1_000.0, 6),
            "unit": "kt_O2/y",
            "boundary_status": "source_traceable_development_BOF_O2",
            "caveat": "Added only to the represented ASU electricity driver; no residual site O2 demand is inferred.",
        },
        {
            "metric": "BF_oxygen_development",
            "model_value": round(annual("bf_oxygen_development_t") / 1_000.0, 6),
            "unit": "kt_O2/y",
            "boundary_status": "source_traceable_development_BF_O2",
            "caveat": "Added only to the represented ASU electricity driver; BF and other process/utility oxygen uses remain an explicit partial boundary.",
        },
        {
            "metric": "represented_oxygen_for_ASU",
            "model_value": round(annual("represented_oxygen_t") / 1_000.0, 6),
            "unit": "kt_O2/y",
            "boundary_status": "DRP_EAF_plus_BOF_represented_O2",
            "caveat": "Not a full-site oxygen balance: BF and other utility/process uses remain outside this source-linked subtotal.",
        },
        {
            "metric": "internal_WAG_generator_electricity_offset",
            "model_value": round(annual("wag_electricity_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "internal_offset_not_market_revenue",
            "caveat": "Generator interface is not DA dispatch or export revenue.",
        },
        {
            "metric": "net_grid_import_after_internal_WAG_offset",
            "model_value": round(annual("net_grid_import_mwh") / 1_000_000.0, 6),
            "unit": "TWh/y",
            "boundary_status": "represented_net_import_only",
            "caveat": "Not a complete full-site import claim; compare as secondary residual KPI only.",
        },
        {
            "metric": "steam_production_proxy",
            "model_value": round(annual("steam_production_mwh") / 1_000_000.0, 6),
            "unit": "TWh_th/y",
            "boundary_status": "boiler_fuel_energy_proxy",
            "caveat": "Energy proxy only. The source-stage C5p_b mass-flow bridge below is the accepted represented-demand check.",
        },
        {
            "metric": "modelled_steam_15bar_demand",
            "model_value": round(annual("steam_15bar_demand_t") / 1_000.0, 6),
            "unit": "kt_steam/y",
            "boundary_status": "C5p_b_existing_modelled_demand_only",
            "caveat": "All existing mapped demand is represented at 15 bar; unmodelled site steam residual remains excluded rather than filled.",
        },
        {
            "metric": "modelled_steam_15bar_supply",
            "model_value": round(annual("steam_15bar_supply_t") / 1_000.0, 6),
            "unit": "kt_steam/y",
            "boundary_status": "C5p_b_fuel_to_steam_mass_bridge",
            "caveat": "Derived from the same accepted C5p_b annual boiler fuel and mass-flow rows; not a detailed enthalpy or pressure-dispatch model.",
        },
        {
            "metric": "modelled_steam_15bar_unserved",
            "model_value": round(annual("steam_15bar_unserved_t") / 1_000.0, 6),
            "unit": "kt_steam/y",
            "boundary_status": "represented_existing_demand_only",
            "caveat": "Zero only for the C5p_b mapped existing demand; it is not a claim that the full-site steam residual is zero.",
        },
        {
            "metric": "named_NG_DRP_EAF_volume",
            "model_value": round(named_ng_nm3 / 1_000_000.0, 6),
            "unit": "million Nm3/y",
            "boundary_status": "named_process_NG_volume",
            "caveat": "Reported separately because this builder surface has no governed LHV conversion for a consolidated NG-energy total.",
        },
        {
            "metric": "named_NG_HSM_PEFA_boiler_energy",
            "model_value": round(_mwh_to_pj(controller_ng_mwh), 6),
            "unit": "PJ_LHV/y",
            "boundary_status": "named_controller_NG_energy",
            "caveat": "Separate from DRP/EAF volume and from unallocated full-site NG residual.",
        },
        {
            "metric": "WAG_explicit_combustion_CO2",
            "model_value": round(annual("wag_explicit_combustion_co2_t") / 1_000_000.0, 6),
            "unit": "MtCO2/y",
            "boundary_status": "Mode_B_represented_oxidation_sinks_only",
            "caveat": "Excludes aggregate process counters, named NG combustion, residual NG, Scope 2 and unrepresented site sources.",
        },
        {
            "metric": "WAG_flare_CO2",
            "model_value": round(annual("flaring_co2_t") / 1_000_000.0, 6),
            "unit": "MtCO2/y",
            "boundary_status": "carrier_specific_flare_only",
            "caveat": "Included within WAG explicit combustion; do not add again.",
        },
    ]
    return rows


def _origin_material_rows(model: Any, horizon_hours: int) -> list[dict[str, Any]]:
    """Export origin-tagged downstream accounting without assigning import upstream impacts."""
    annual = lambda component: _annualise(_sum(model, component), horizon_hours)
    bof_to_hsm = annual("bof_to_hsm_slab")
    eaf_to_hsm = annual("eaf_to_hsm_slab")
    imported_to_hsm = annual("imported_slab_to_hsm")
    hsm_input = annual("hot_strip_mill")
    rows = [
        ("endogenous_BOF_liquid_steel", annual("bof_crude_steel_output"), "t/y", "represented_upstream_route", "BOF output remains endogenous liquid steel."),
        ("endogenous_EAF_liquid_steel", annual("eaf_liquid_steel_output"), "t/y", "represented_upstream_route", "EAF output remains endogenous liquid steel."),
        ("BOF_to_HSM_slab", bof_to_hsm, "t/y", "origin_tagged_downstream", "Explicit BOF-origin slab routed to HSM."),
        ("EAF_to_HSM_slab", eaf_to_hsm, "t/y", "origin_tagged_downstream", "Explicit EAF-origin slab routed to HSM."),
        ("imported_slab_to_HSM", imported_to_hsm, "t/y", "external_downstream_boundary", "Imported slab is external and never receives upstream site energy, WAG, NG or direct-fuel CO2."),
        ("HSM_input", hsm_input, "t/y", "origin_tagged_downstream", "Must equal BOF-to-HSM plus EAF-to-HSM plus imported slab."),
        ("DSP_final_product", annual("dsp_final_product_output"), "t/y", "represented_downstream", "DSP output remains separate from HSM product."),
        ("site_final_product", annual("final_product_output"), "t/y", "site_product_boundary", "Scenario output measure; not silently substituted for liquid steel."),
    ]
    output = [
        {
            "metric": metric,
            "annual_value": round(value, 6),
            "unit": unit,
            "boundary": boundary,
            "status": "reported",
            "caveat": caveat,
        }
        for metric, value, unit, boundary, caveat in rows
    ]
    hsm_residual = hsm_input - bof_to_hsm - eaf_to_hsm - imported_to_hsm
    output.append({
        "metric": "HSM_origin_input_balance_residual",
        "annual_value": round(hsm_residual, 6),
        "unit": "t/y",
        "boundary": "origin_tagged_downstream",
        "status": "pass" if abs(hsm_residual) <= 1e-6 else "fail",
        "caveat": "Identity check only; no material residual is added.",
    })
    for metric, unit in (
        ("imported_slab_upstream_electricity", "TWh/y"),
        ("imported_slab_upstream_WAG", "PJ_LHV/y"),
        ("imported_slab_upstream_NG", "PJ_LHV/y"),
        ("imported_slab_upstream_direct_fuel_CO2", "MtCO2/y"),
    ):
        output.append({
            "metric": metric,
            "annual_value": 0.0,
            "unit": unit,
            "boundary": "external_supply_excluded",
            "status": "pass",
            "caveat": "External slab upstream impacts are outside the site physical boundary.",
        })
    return output


def _representation_gap_rows(model: Any, horizon_hours: int) -> list[dict[str, Any]]:
    """Expose source-backed next levers without silently activating them.

    A row is either active in the physical model, a bounded sensitivity
    candidate, or deliberately deferred.  It is not a residual-load budget.
    """

    annual = lambda component: _annualise(_sum(model, component), horizon_hours)
    hsm_output_t_y = annual("hot_strip_mill")
    eaf_ls_t_y = annual("eaf_liquid_steel_output")
    coke_t_y = annual("coke_output")
    hsm_high = _candidate_value(
        OVERLAY_ELECTRICITY_PATH,
        configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
        candidate_parameter_id="HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID",
    )
    kgf_gross = _candidate_value(
        OVERLAY_ELECTRICITY_PATH,
        configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
        candidate_parameter_id="KGF_ELECTRICITY_GROSS_SERVICE_GJ_PER_T_COKE",
    )
    dsp_high = _candidate_value(
        OVERLAY_ELECTRICITY_PATH,
        configuration="C1_phase1_BF_BOF_plus_DRP_EAF",
        candidate_parameter_id="DSP_ELECTRICITY_MWH_PER_T_DSP_COIL_SENS_HIGH",
    )
    eaf_secondary = _candidate_value(
        EAF_DEVELOPMENT_INPUT_PATH,
        parameter_id="EAF_SECONDARY_MET_ELECTRICITY_MWH_PER_T_LS",
    )
    active_hsm = annual("hsm_rolling_electricity_mwh")
    active_kgf = annual("kgf_electricity_mwh")
    active_dsp = annual("dsp_electricity_mwh")
    return [
        {
            "process_or_interface": "BF6 electricity and oxygen",
            "activity_driver": "bf6_hot_iron_output",
            "annual_activity_t_y": round(annual("bf6_hot_iron_output"), 3),
            "status": "active_source_traceable_development",
            "current_model_value_TWh_y": round(annual("bf_electricity_mwh") / 1_000_000.0, 6),
            "potential_increment_TWh_y": 0.0,
            "why_not_more": "BF electricity and O2 are represented; remaining BF auxiliaries and steam have no accepted site-level demand/controller bridge.",
            "next_action": "Compare the per-t HM intensity before any BF auxiliary expansion.",
        },
        {
            "process_or_interface": "HSM rolling electricity high literature bound",
            "activity_driver": "hot_strip_mill",
            "annual_activity_t_y": round(hsm_output_t_y, 3),
            "status": "sensitivity_only_pending_locator",
            "current_model_value_TWh_y": round(active_hsm / 1_000_000.0, 6),
            "potential_increment_TWh_y": round(max(hsm_high * hsm_output_t_y - active_hsm, 0.0) / 1_000_000.0, 6),
            "why_not_more": "0.104 MWh/t is a non-Tata literature candidate with repository locator still pending; it must be a bounded sensitivity, not a base correction.",
            "next_action": "Run alone only after this representation audit is accepted.",
        },
        {
            "process_or_interface": "KGF gross-service electricity",
            "activity_driver": "coke_output",
            "annual_activity_t_y": round(coke_t_y, 3),
            "status": "sensitivity_only_recovery_boundary_unresolved",
            "current_model_value_TWh_y": round(active_kgf / 1_000_000.0, 6),
            "potential_increment_TWh_y": round(max(kgf_gross * coke_t_y - active_kgf, 0.0) / 1_000_000.0, 6),
            "why_not_more": "Gross service demand contains internally produced electricity in a CDQ/recovery context that is not represented here; activating it now risks double counting.",
            "next_action": "Keep purchased-electricity base; only test gross service with explicit recovery-boundary reconciliation.",
        },
        {
            "process_or_interface": "DSP high electricity proxy",
            "activity_driver": "dsp_final_product_output",
            "annual_activity_t_y": round(annual("dsp_final_product_output"), 3),
            "status": "sensitivity_only_proxy_not_DSP_specific",
            "current_model_value_TWh_y": round(active_dsp / 1_000_000.0, 6),
            "potential_increment_TWh_y": round(max(dsp_high * annual("dsp_final_product_output") - active_dsp, 0.0) / 1_000_000.0, 6),
            "why_not_more": "The high value is an HSM proxy, not a DSP-specific measured coefficient.",
            "next_action": "Do not activate before a DSP boundary/source review.",
        },
        {
            "process_or_interface": "EAF secondary metallurgy electricity",
            "activity_driver": "eaf_liquid_steel_output",
            "annual_activity_t_y": round(eaf_ls_t_y, 3),
            "status": "deferred_accounting_only",
            "current_model_value_TWh_y": 0.0,
            "potential_increment_TWh_y": round(eaf_secondary * eaf_ls_t_y / 1_000_000.0, 6),
            "why_not_more": "Source stage explicitly classifies 0.031 MWh/t LS as secondary-metallurgy deferred and separate from arc electricity.",
            "next_action": "Add only with an explicit secondary-metallurgy process boundary and no overlap with the EAF arc coefficient.",
        },
        {
            "process_or_interface": "C1 generator named-NG interface",
            "activity_driver": "generator fuel interface",
            "annual_activity_t_y": "",
            "status": "reporting_only_missing_driver",
            "current_model_value_TWh_y": 0.0,
            "potential_increment_TWh_y": "",
            "why_not_more": "The 4.1-PJ/y named-NG context is an annual validation anchor, not a source-backed hourly generator demand driver.",
            "next_action": "Keep it as an unresolved named-NG residual/interface context; do not inject it into the generator.",
        },
    ]


def _plant_load_distribution_rows(model: Any, horizon_hours: int) -> list[dict[str, Any]]:
    """Summarise price-free hourly load distributions by physical plant layer."""

    mappings = (
        ("Sintering Plant", "sinter_electricity_mwh", "sintering_plant", "active source-traceable development utility proxy"),
        ("Pelletizing Plant", "pefa_electricity_mwh", None, "fixed source-stage PEFA utility profile"),
        ("Blast Furnace 6", "bf_electricity_mwh", "bf6_hot_iron_output", "active source-traceable development electricity"),
        ("Basic Oxygen Plant", "bof_electricity_mwh", "bof_crude_steel_output", "BOF auxiliary electricity only; not BOF-plus-ASU"),
        ("Linde Plant", "linde_total_electricity_mwh", None, "O2-process electricity plus separately reported N2/auxiliary site-context load; not full Linde/site air-gas demand"),
        ("DRP", "drp_electricity_mwh", "drp_pellet_input", "existing DRP route electricity"),
        ("EAF", "eaf_total_electricity_mwh", "eaf_liquid_steel_output", "arc electricity plus an explicitly scenario-labelled secondary-metallurgy load, if active"),
        ("DSP Plant", "dsp_electricity_mwh", "dsp_final_product_output", "base DSP development electricity or an explicitly scenario-labelled sensitivity"),
        ("Hot Strip Mill", "hsm_rolling_electricity_mwh", "hot_strip_mill", "rolling electricity only; reheating fuel is separate"),
    )
    rows: list[dict[str, Any]] = []
    for plant, component, driver, caveat in mappings:
        values = [float(value(getattr(model, component)[t])) for t in model.TIME]
        active_driver_t = (
            _annualise(sum(float(value(getattr(model, driver)[t])) for t in model.TIME), horizon_hours)
            if driver is not None
            else ""
        )
        annual_mwh = _annualise(sum(values), horizon_hours)
        intensity = annual_mwh / active_driver_t if isinstance(active_driver_t, float) and active_driver_t > 0 else ""
        rows.append(
            {
                "configuration": "C1",
                "plant": plant,
                "electricity_component": component,
                "hourly_mean_MWh": round(sum(values) / len(values), 6),
                "hourly_p10_MWh": round(_quantile(values, 0.10), 6),
                "hourly_p25_MWh": round(_quantile(values, 0.25), 6),
                "hourly_p50_MWh": round(_quantile(values, 0.50), 6),
                "hourly_p75_MWh": round(_quantile(values, 0.75), 6),
                "hourly_p90_MWh": round(_quantile(values, 0.90), 6),
                "zero_share": round(sum(1 for item in values if abs(item) <= 1e-9) / len(values), 6),
                "annualised_electricity_TWh_y": round(annual_mwh / 1_000_000.0, 6),
                "annual_activity_t_y": round(active_driver_t, 3) if isinstance(active_driver_t, float) else "",
                "electricity_MWh_per_t_driver": round(intensity, 9) if isinstance(intensity, float) else "",
                "comparison_status": "diagnostic_only_price_free_profile",
                "caveat": caveat,
            }
        )
    return rows


def _badarinath_price_insensitive_rows(plant_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare only hour-distribution shape against redacted visual context."""

    by_plant = {str(row["plant"]): row for row in plant_rows}
    rows: list[dict[str, Any]] = []
    for month, plant, visual_p25, visual_p50, visual_p75 in BADARINATH_C1_PRICE_INSENSITIVE_VISUAL_BANDS:
        model_row = by_plant[plant]
        model_p50 = float(model_row["hourly_p50_MWh"])
        rows.append(
            {
                "configuration": "C1_DRP_EAF_phase",
                "month": month,
                "plant": plant,
                "badarinath_strategy": "price_insensitive",
                "badarinath_visual_p25_MWh": visual_p25,
                "badarinath_visual_p50_MWh": visual_p50,
                "badarinath_visual_p75_MWh": visual_p75,
                "model_hourly_mean_MWh": model_row["hourly_mean_MWh"],
                "model_hourly_p25_MWh": model_row["hourly_p25_MWh"],
                "model_hourly_p50_MWh": model_p50,
                "model_hourly_p75_MWh": model_row["hourly_p75_MWh"],
                "model_zero_share": model_row["zero_share"],
                "median_relation": (
                    "within_visual_IQR" if visual_p25 <= model_p50 <= visual_p75
                    else "below_visual_IQR" if model_p50 < visual_p25
                    else "above_visual_IQR"
                ),
                "comparison_class": "secondary_context_visual_approximation_not_scored",
                "caveat": (
                    "Bands are approximate readings of user-supplied redacted Badarinath figures. "
                    "They are not digitised raw observations, annual anchors, constraints or calibration targets."
                ),
            }
        )
    return rows


def _anchor_comparisons(utility_rows: list[dict[str, Any]], carrier_rows: list[dict[str, Any]], anchors: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    by_metric = {row["metric"]: float(row["model_value"]) for row in utility_rows if isinstance(row["model_value"], (int, float))}
    generation_plus_flare_pj = _mwh_to_pj(sum(float(row["generator_MWh_LHV_y"]) + float(row["flare_MWh_LHV_y"]) for row in carrier_rows))
    comparisons = [
        ("active_final_product_target_6_75", "final_product_output", 6.75, "Mt/y", "primary_score", "active_target", "comparable"),
        ("c1_official_total_site_electricity_17_8pj_missing", "gross_electricity", 17.8 / 3.6, "TWh/y", "secondary_context", "partial_site_boundary", "not_comparable"),
        ("athan_table9_phase1_electricity_4_89", "gross_electricity", 4.89, "TWh/y", "secondary_context", "unscaled_model_precedent", "not_comparable"),
        ("c1_official_grid_import_11_7pj_missing", "net_grid_import_after_internal_WAG_offset", 11.7 / 3.6, "TWh/y", "secondary_context", "partial_site_boundary", "not_comparable"),
        # MER Table 5.5 reports 14.6 PJ/y as *total* generator fuel plus
        # flare.  It includes 4.1 PJ/y named VN25 NG, which this physical
        # boundary deliberately does not allocate.  The source-comparable
        # WAG-only quantity is therefore BFG 9.1 + BOFG 1.3 + COG 0.1 +
        # flare 0.1 = 10.6 PJ/y.
        ("c1_generator_wag_with_flare_10_6", "generator_plus_flare_WAG_fuel", 10.6, "PJ/y", "boundary_comparable", "annual_wag_interface_anchor", "comparable"),
        ("c1_generator_total_with_flare_14_6", "generator_plus_flare_total_fuel", 14.6, "PJ/y", "not_comparable", "total_fuel_includes_unmodelled_named_ng", "not_comparable"),
        ("c1_generator_flare_0_1", "flare_WAG_fuel", 0.1, "PJ/y", "secondary_context", "annual_interface_anchor", "not_comparable"),
        # Table 9 reports WAG generation in TWh.  The only dimensionally
        # coherent model counterpart is internal WAG-to-electricity output,
        # not the upstream carrier-energy total in PJ_LHV/y.
        ("athan_table9_phase1_wag_1_23", "internal_WAG_generator_electricity_offset", 1.23, "TWh/y", "secondary_context", "model_precedent_generator_electricity_context", "not_comparable"),
        ("c1_official_scope1_8_3_missing", "WAG_explicit_combustion_CO2", 8.3, "MtCO2/y", "reporting_only", "partial_mode_B_subtotal", "reporting_only"),
        ("athan_table9_phase1_co2_9_108", "WAG_explicit_combustion_CO2", 9.10779317, "MtCO2/y", "reporting_only", "partial_mode_B_subtotal", "reporting_only"),
    ]
    rows: list[dict[str, Any]] = []
    for anchor_id, metric, fallback, unit, classification, comparison_basis, comparability_status in comparisons:
        if metric == "generator_plus_flare_WAG_fuel":
            model_value = generation_plus_flare_pj
        elif metric == "generator_plus_flare_total_fuel":
            # Keep the official total visible, but do not manufacture the
            # unrepresented 4.1-PJ/y VN25 NG component merely to compare it.
            model_value = None
        elif metric == "flare_WAG_fuel":
            model_value = _mwh_to_pj(sum(float(row["flare_MWh_LHV_y"]) for row in carrier_rows))
        else:
            model_value = by_metric[metric]
        anchor = anchors.get(anchor_id, {})
        anchor_value = _anchor_value_in_unit(anchor, unit, fallback) if anchor_id != "active_final_product_target_6_75" else fallback
        residual = model_value - anchor_value if model_value is not None else None
        if comparability_status == "not_comparable":
            comparison_status = "not_comparable"
        elif comparability_status == "reporting_only":
            comparison_status = "partial_not_scored"
        else:
            comparison_status = "comparable_with_caveat"
        caveat = anchor.get("caveat", "Active 6.75-Mt/y final-product proxy target.")
        if anchor_id == "athan_table9_phase1_wag_1_23":
            caveat = (
                "Table 9 is reported in TWh, so it is compared only with the represented internal WAG-to-electricity offset. "
                "Athanasiadis remains a model-precedent context anchor: its denominator and generator boundary are unresolved, "
                "so this row must not drive a correction or be treated as official Tata truth."
            )
        elif anchor_id == "c1_generator_wag_with_flare_10_6":
            caveat = (
                "Derived from Rank-1 MER Table 5.5 carrier components: BFG 9.1 + BOFG 1.3 + COG 0.1 "
                "+ generator flare 0.1 PJ/y.  It is the comparable WAG-only subtotal; it is not an hourly constraint."
            )
        elif anchor_id == "c1_generator_total_with_flare_14_6":
            caveat = (
                "MER Table 5.5 total includes 4.1 PJ/y named VN25 NG, which is intentionally reporting-only in the current "
                "physical boundary.  No model residual, allocation or signed gap is reported for this non-comparable total."
            )
        rows.append(
            {
                "anchor_id": anchor_id,
                "metric": metric,
                "model_value": round(model_value, 6) if model_value is not None else "",
                "anchor_value": round(anchor_value, 6),
                "unit": unit,
                "signed_residual": round(residual, 6) if residual is not None else "",
                "signed_residual_share": round(residual / anchor_value, 8) if residual is not None and anchor_value else "",
                "comparison_class": classification,
                "comparison_basis": comparison_basis,
                "comparability_status": comparability_status,
                "comparability_reason": caveat,
                "source_rank": anchor.get("source_trust_rank", "active_model_target"),
                "locator_quality": anchor.get("locator_quality", "exact"),
                "status": comparison_status,
                "caveat": caveat,
            }
        )
    return rows


def _guardrails(carrier_rows: list[dict[str, Any]], utility_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_metric = {row["metric"]: row for row in utility_rows}
    steam_demand = float(by_metric["modelled_steam_15bar_demand"]["model_value"])
    steam_supply = float(by_metric["modelled_steam_15bar_supply"]["model_value"])
    steam_unserved = float(by_metric["modelled_steam_15bar_unserved"]["model_value"])
    return [
        {"check_id": "AT_001", "check_name": "carrier_specific_WAG_balance", "status": "pass" if all(row["balance_status"] == "pass" for row in carrier_rows) else "fail", "evidence": "BFG, COG and BOFG balance rows close independently.", "action": "Do not substitute aggregate WAG."},
        {"check_id": "AT_002", "check_name": "aggregate_or_mixed_WAG_not_physical", "status": "pass", "evidence": "Only BFG, COG and BOFG are written as physical ledger carriers.", "action": "Keep aggregate/mixed WAG reporting-only."},
        {"check_id": "AT_003", "check_name": "no_residual_energy_input", "status": "pass", "evidence": "Electricity and NG residuals are not model variables in this run.", "action": "Retain gaps only in reporting."},
        {"check_id": "AT_004", "check_name": "Mode_B_CO2_separate_from_process_counters", "status": "pass", "evidence": by_metric["WAG_explicit_combustion_CO2"]["caveat"], "action": "Do not consolidate to Scope 1."},
        {"check_id": "AT_005", "check_name": "no_market_or_ETS_terms", "status": "pass", "evidence": "Capacity objective only; no price, revenue or ETS term is created.", "action": "Keep economics and DA out of scope."},
        {"check_id": "AT_005b", "check_name": "electricity_boundary_loads_are_explicit", "status": "pass", "evidence": "BF, BOF, KGF, DSP, ASU and sinter development loads are throughput-linked expressions, not a residual site-load input.", "action": "Keep every added electricity bucket source-traceable and separately reported."},
        {"check_id": "AT_006", "check_name": "C5p_b_mapped_steam_15bar_bridge", "status": "pass" if abs(steam_supply - steam_demand) <= 1e-6 and abs(steam_unserved) <= 1e-6 else "fail", "evidence": by_metric["modelled_steam_15bar_supply"]["caveat"], "action": "Keep the source-stage fuel-to-mass bridge explicit and do not fill unmodelled steam residual."},
        {"check_id": "AT_007", "check_name": "full_site_steam_residual_not_claimed", "status": "warning", "evidence": by_metric["modelled_steam_15bar_demand"]["caveat"], "action": "Do not extrapolate mapped existing demand to a full-site steam claim."},
    ]


def _write_report() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        """# C1 Central Metallics WAG, Steam and Utility Reconciliation

## Purpose

This run combines the existing C1 central BOF/EAF metallics diagnostic with
the existing carrier-specific WAG, HSM/PEFA, boiler and generator surfaces.
It is an annualised representative-week reconciliation diagnostic, not an
economic optimisation or a whole-site annual claim.

## Included layers

- bounded BOF/EAF scrap and metallics ledger;
- BFG, COG and BOFG carrier balances only;
- existing HSM and PEFA fuel controllers;
- existing boiler-scaffold and generator-interface terms;
- source-traceable BF, BOF, KGF, DSP, ASU and sinter electricity boundary rows;
- a source-status representation-gap register for the next electricity layers;
- gross electricity, internal WAG generation offset and represented net import;
- named NG reported separately from the unresolved full-site NG residual;
- Mode-B WAG point-of-oxidation CO2 subtotal only.

## Boundary rules

- Aggregate and mixed WAG never feed a physical sink.
- C5p_k does not feed allocation.
- No WAG/NG ratio or Wobbe-quality rule is invented.
- No electricity or NG residual becomes a load, allocation or cost.
- BF, BOF, KGF, DSP, ASU and sinter electricity are activity-linked development rows,
  separately reported rather than hidden inside a generic site-electricity gap.
- WAG-explicit CO2 is not combined with aggregate BF/BOF/KGF/PEFA/sinter
  process counters and is not called Scope 1 or ETS-ready.
- The integrated boiler fuel balance now carries the C5p_b mapped existing
  demand as an explicit 15-bar mass-flow bridge.  It does not fill or claim
  unmodelled full-site steam demand, and it is not a detailed enthalpy model.

## Anchor policy

Official/MER records are secondary validation context where their existing
locator or boundary remains partial. Athanasiadis Table 9 is unscaled
model-precedent context, not official Tata truth. No anchor is a constraint.

When a labelled carrier-LHV sensitivity is active, it changes only the energy
represented by fixed BFG/COG/BOFG volumes. Table 9's WAG value is reported in
TWh and is therefore compared only with internal WAG-to-electricity output,
not with upstream WAG fuel energy in PJ. Neither comparison is a reason to
silently migrate a factor set into the base inputs.

## Result interpretation

Use `anchor_comparison.csv` only after first checking `guardrail_checks.csv`
and `wag_carrier_ledger.csv`. A closer value is never accepted if it results
from a guardrail failure, a boundary mismatch or a hidden residual.

`representation_gap_register.csv` is deliberately not a residual-load budget.
It distinguishes active source-traceable rows from bounded sensitivities and
deferred process layers, so that an annual anchor gap cannot silently activate
unrepresented electricity, NG or WAG use.

## Badarinath price-insensitive context

`plant_load_distribution.csv` reports the model's hourly price-free load
distribution by physical plant layer. `badarinath_price_insensitive_comparison.csv`
uses approximate visual bands transcribed from the user-supplied redacted
Badarinath figures. Those rows assess relative plant-load shape only: they are
not annual anchors, exact observations, constraints or calibration targets.
""",
        encoding="utf-8",
    )


def run_c1_central_metallics_wag_steam_utility_reconciliation(
    *,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    run_id: str = DEFAULT_RUN_ID,
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float | None = None,
    downstream_boundary_case: str = "mer_site_product",
    metallics_config_path: str | Path = METALLICS_CONFIG,
    scenario_id: str | None = None,
    output_policy: str = "diagnostics",
    run_class: str = "physical_anchor_reconciliation",
    lineage_role: str = "diagnostic",
    retention: str = "local_run_artifact_not_git_eligible_by_default",
) -> dict[str, Any]:
    if output_policy not in {"minimal", "diagnostics", "full", "thesis_report"}:
        raise ValueError(f"Unsupported output policy: {output_policy}")
    if not run_class.strip() or not lineage_role.strip() or not retention.strip():
        raise ValueError("Run metadata values must be non-empty strings.")
    run_directory = Path(output_root).resolve() / run_id
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    try:
        model, config, runtime_seconds, solver_name, metadata = _build_and_solve(
            hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity_mwh_per_t_hrc_override,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
            downstream_boundary_case=downstream_boundary_case,
            metallics_config_path=metallics_config_path,
            scenario_id=scenario_id,
        )
    except RuntimeError as error:
        message = str(error)
        if "feasible solution was not found" not in message.lower():
            raise
        summary = {
            "run_id": run_id,
            "stage": STAGE,
            "status": "no_accepted_solution",
            "output_policy": output_policy,
            "run_class": run_class,
            "lineage_role": lineage_role,
            "retention": retention,
            "downstream_boundary_case": downstream_boundary_case,
            "termination_condition": "infeasible_or_no_solution_loaded",
            "reason": message,
            "go_no_go": {"annual_anchor_comparison": "NO_GO", "economics_and_DA": "NO_GO"},
        }
        _write_json(run_directory / "run_summary.json", summary)
        _write_json(run_directory / "registry_entry.json", {"run_id": run_id, "run_class": run_class, "lineage_role": lineage_role, "output_policy": output_policy, "git_eligible": False})
        _write_json(run_directory / "code_version.json", {"git_revision": _git_revision(), "timestamp_utc": datetime.now(timezone.utc).isoformat(), "module": __file__})
        _write_json(run_directory / "input_manifest.json", {"source_metallics_config": str(metallics_config_path), "scenario_id": scenario_id, "downstream_boundary_case": downstream_boundary_case})
        (run_directory / "warnings_and_limitations.md").write_text(
            "# No accepted solution\n\nThe model could not meet the declared physical case. No dispatch, annual anchor comparison, or parameter change is inferred from this result.\n",
            encoding="utf-8",
        )
        return {"run_directory": run_directory, "summary": summary, "carrier_rows": [], "comparisons": []}
    horizon_hours = int(config["horizon_hours"])
    lhv_override = metadata["wag_lhv_mj_per_nm3_override"]
    carriers = _carrier_rows(model, horizon_hours, lhv_override)
    sink_mixes = _sink_mix_rows(model, horizon_hours)
    utilities = _utility_rows(model, horizon_hours)
    origin_material = _origin_material_rows(model, horizon_hours)
    flow_trace = _physical_flow_trace_rows(sink_mixes, origin_material, utilities)
    anchors = _anchor_map()
    comparisons = _anchor_comparisons(utilities, carriers, anchors)
    checks = _guardrails(carriers, utilities)
    final_product_value = float(next(row for row in utilities if row["metric"] == "final_product_output")["model_value"])
    if metadata["annual_target_mt_y"] is not None:
        target = float(metadata["annual_target_mt_y"])
        checks.append({
            "check_id": "AT_008",
            "check_name": "declared_annual_final_product_quota",
            "status": "pass" if abs(final_product_value - target) <= 1e-6 else "fail",
            "evidence": f"annualised final product {final_product_value:.6f} Mt/y versus declared target {target:.6f} Mt/y",
            "action": "Do not call a capacity result an exact-quota run unless this identity passes.",
        })
    representation_gaps = _representation_gap_rows(model, horizon_hours)
    plant_loads = _plant_load_distribution_rows(model, horizon_hours)
    badarinath_comparison = _badarinath_price_insensitive_rows(plant_loads)
    counts: dict[str, int] = {}
    for row in checks:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    final_product = next(row for row in utilities if row["metric"] == "final_product_output")
    summary = {
        "run_id": run_id,
        "stage": STAGE,
        "status": "pass_with_caveats" if all(row["status"] != "fail" for row in checks) else "fail",
        "output_policy": output_policy,
        "run_class": run_class,
        "lineage_role": lineage_role,
        "retention": retention,
        "solver_name": solver_name,
        "termination_condition": metadata["termination"],
        "runtime_seconds": round(runtime_seconds, 6),
        "variable_count": metadata["stats"].variables,
        "binary_count": metadata["stats"].binaries,
        "constraint_count": metadata["stats"].constraints,
        "annualised_final_product_mt_y": final_product["model_value"],
        "downstream_boundary_case": metadata["downstream_boundary_case"],
        "origin_material_guardrail_pass": all(row["status"] != "fail" for row in origin_material),
        "carrier_sink_mix_rows": len(sink_mixes),
        "physical_flow_trace_rows": len(flow_trace),
        "guardrail_counts": counts,
        "representation_gap_counts": {
            status: sum(1 for row in representation_gaps if row["status"] == status)
            for status in sorted({str(row["status"]) for row in representation_gaps})
        },
        "badarinath_price_insensitive_context": {
            "rows": len(badarinath_comparison),
            "within_visual_IQR": sum(1 for row in badarinath_comparison if row["median_relation"] == "within_visual_IQR"),
            "below_visual_IQR": sum(1 for row in badarinath_comparison if row["median_relation"] == "below_visual_IQR"),
            "above_visual_IQR": sum(1 for row in badarinath_comparison if row["median_relation"] == "above_visual_IQR"),
            "policy": "secondary_context_visual_approximation_not_scored",
        },
        "go_no_go": {
            "carrier_specific_WAG_utility_reconciliation": "GO_DIAGNOSTIC_ONLY",
            "annual_anchor_comparison": "GO_WITH_BOUNDARY_CAVEATS",
            "C5p_b_mapped_steam_15bar_bridge": "GO_DIAGNOSTIC_ONLY",
            "full_site_steam_bus_closure": "NO_GO",
            "full_site_NG_or_electricity_claim": "NO_GO",
            "whole_site_Scope1_or_ETS_claim": "NO_GO",
            "economics_and_DA": "NO_GO",
        },
    }
    resolved = {
        "source_metallics_config": Path(metallics_config_path).resolve().relative_to(REPO_ROOT).as_posix(),
        "scenario_id": metadata["scenario"]["scenario_id"],
        "horizon_hours": horizon_hours,
        "objective": (
            "exact_annual_target_physical_feasibility_with_existing_static_controller_tiebreaker"
            if metadata["target_required"]
            else "maximise_final_product_capacity_for_central_source_bounded_metallics_case"
        ),
        "secondary_objective": "existing_static_controller_and_flare_tiebreaker_at_preserved_capacity" if not metadata["target_required"] else "not_applicable",
        "development_controller_activation": "full_electricity_boundary",
        "hsm_carrier_precedence": metadata["hsm_carrier_precedence"],
        "hsm_eligible_carriers": metadata["hsm_eligible_carriers"],
        "generator_interface_cap_mode": metadata["generator_interface_cap_mode"],
        "c1_liquid_steel_route_band": metadata["c1_liquid_steel_route_band"],
        "electricity_boundary_overrides": metadata["electricity_boundary_overrides"],
        "wag_lhv_mj_per_nm3_override": lhv_override,
        "downstream_boundary_case": metadata["downstream_boundary_case"],
        "downstream_origin_routing": metadata["downstream_origin_routing"],
        "hsm_rolling_electricity_mwh_per_t_hrc_override": hsm_rolling_electricity_mwh_per_t_hrc_override,
        "linde_n2_auxiliary_electricity_mwh_h": linde_n2_auxiliary_electricity_mwh_h,
        "economic_terms_enabled": False,
        "market_prices_enabled": False,
        "ETS_enabled": False,
    }
    (run_directory / "resolved_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    _write_json(
        run_directory / "input_manifest.json",
        {"inputs": [_file_record(path) for path in (
            Path(metallics_config_path).resolve(), ANCHOR_REGISTER, BOILER_FUEL_PATH, BOILER_STEAM_DEMAND_PATH,
            OVERLAY_ELECTRICITY_PATH, EAF_DEVELOPMENT_INPUT_PATH,
        )]},
    )
    _write_json(run_directory / "code_version.json", {"git_revision": _git_revision(), "timestamp_utc": datetime.now(timezone.utc).isoformat(), "module": __file__})
    _write_csv(run_directory / "wag_carrier_ledger.csv", carriers)
    _write_csv(run_directory / "wag_sink_mix_ledger.csv", sink_mixes)
    _write_csv(run_directory / "utility_energy_co2_ledger.csv", utilities)
    _write_csv(run_directory / "origin_material_ledger.csv", origin_material)
    _write_csv(run_directory / "physical_flow_trace.csv", flow_trace)
    _write_csv(run_directory / "anchor_comparison.csv", comparisons)
    _write_csv(run_directory / "guardrail_checks.csv", checks)
    _write_csv(run_directory / "representation_gap_register.csv", representation_gaps)
    _write_csv(run_directory / "plant_load_distribution.csv", plant_loads)
    _write_csv(run_directory / "badarinath_price_insensitive_comparison.csv", badarinath_comparison)
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": run_id, "run_class": run_class, "lineage_role": lineage_role, "output_policy": output_policy, "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The run is either a capacity diagnostic or an exact quota-feasibility case; see resolved_config.yaml.\n"
        "- The 15-bar steam bridge closes only C5p_b mapped existing demand; full-site residual steam demand and detailed pressure/enthalpy dispatch remain out of scope.\n"
        "- Full-site electricity and NG anchors retain partial locator/boundary provenance.\n"
        "- Mode-B WAG CO2 is a represented-sink subtotal only, not Scope 1 or ETS-ready.\n"
        "- A carrier-LHV sensitivity changes the energy represented by fixed source gas volumes; combustion factors remain the selected reporting factors and its CO2 subtotal is not used for cross-factor scoring.\n",
        encoding="utf-8",
    )
    _write_report()
    return {"run_directory": run_directory, "summary": summary, "carrier_rows": carriers, "comparisons": comparisons}
