"""Canonical unit- and purpose-aware validation tolerances for steel models.

This module governs validation and reporting comparisons only.  It must never
be used to alter physical constraints, objectives, input values, or solver
numeric settings.  Fixed input prices are identity-checked by fingerprint;
they are not assigned a numeric tolerance.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


POLICY_ID = "steel_unit_purpose_validation_tolerance"
POLICY_VERSION = "v2_20260727"
SOLVER_NUMERICAL_TOLERANCE = 1e-6
CUMULATIVE_PRODUCTION_TOLERANCE_T = 1.0
TERMINAL_STATE_TOLERANCE_T = 1.0
HOURLY_MONEY_IDENTITY_TOLERANCE_EUR = 0.01
TRAJECTORY_COST_ABSOLUTE_FLOOR_EUR = 1.0
TRAJECTORY_COST_RELATIVE_TOLERANCE = 1e-8
ELECTRICITY_BALANCE_TOLERANCE_MWH = 1e-6
MATERIAL_BALANCE_TOLERANCE_T = 1e-6
ENERGY_BALANCE_TOLERANCE_MWH = 1e-6
THRESHOLD_COMPARISON_ROUNDOFF_ULPS = 256


class ValidationTolerancePolicyError(ValueError):
    """Raised when validation has no registered policy or changes identity."""


@dataclass(frozen=True)
class ValidationRule:
    purpose: str
    unit: str
    tolerance: float
    aggregation: str
    relaxation_allowed: bool


@dataclass(frozen=True)
class ThresholdComparisonRule:
    unit: str
    governed_tolerance: float
    aggregation: str
    comparison_roundoff_ulps: int
    comparison_roundoff_method: str


_C0_REFERENCE_PRODUCTION_FAMILIES = frozenset(
    {
        f"c0_reference_{metric}_{side}"
        for metric in (
            "bof_liquid_steel",
            "dsp_final_output",
            "hsm_final_output",
        )
        for side in ("lower", "upper")
    }
    | {
        f"c0_reference_deadline_{metric}_{hour}h_{side}"
        for metric in (
            "bof_liquid_steel",
            "dsp_final_output",
            "hsm_final_output",
        )
        for hour in (24, 48, 72, 96, 120)
        for side in ("lower", "upper")
    }
)

CUMULATIVE_PRODUCTION_FAMILIES = frozenset(
    {
        "final_product_fulfilment",
        "rolling_production_deadline",
        "rolling_production_future_terminal_quota_equality",
        "rolling_production_terminal_quota_equality",
    }
    | _C0_REFERENCE_PRODUCTION_FAMILIES
)
TERMINAL_STATE_FAMILIES = frozenset(
    {
        "coke_terminal",
        "sinter_terminal",
        "hot_iron_terminal",
        "cold_slab_terminal",
    }
)
ELECTRICITY_BALANCE_FAMILIES = frozenset({"gross_site_electricity_balance"})
MATERIAL_BALANCE_FAMILIES = frozenset(
    {
        "c0_dsp_from_current_bof",
        "coke_balance",
        "cold_slab_balance",
        "hot_iron_balance",
        "rolling_production_progress_identity",
        "sinter_balance",
    }
)
ENERGY_BALANCE_FAMILIES = frozenset(
    {
        "bfg_balance",
        "bofg_balance",
        "boiler_scaffold_fuel_balance",
        "cog_balance",
        "flexible_other_site_heat_balance",
        "hsm_reheat_balance",
        "pefa_branderij_heat_balance",
        "pefa_malerij_heat_balance",
        "steam_15bar_existing_demand_balance",
    }
)
STRICT_PHYSICAL_FAMILIES = frozenset(
    {
        "aggregate_generator_electrical_capacity",
        "basic_oxygen_furnace_daily_minimum_activity",
        "basic_oxygen_furnace_hourly_within_day",
        "blast_furnace_6_daily_minimum_activity",
        "blast_furnace_6_hourly_within_day",
        "blast_furnace_7_daily_minimum_activity",
        "blast_furnace_7_hourly_within_day",
        "c0_bof_hourly_scrap_cap",
        "c0_bof_total_scrap_cap",
        "c0_dsp_final_product_horizon_cap",
        "c0_dsp_final_product_hourly_cap",
        "coke_capacity",
        "coking_plant_1_daily_minimum_activity",
        "coking_plant_1_hourly_within_day",
        "coking_plant_2_daily_minimum_activity",
        "coking_plant_2_hourly_within_day",
        "cold_slab_capacity",
        "export_bounded_by_internal_generation",
        "flexible_other_site_heat_ng_envelope",
        "grid_export_capacity",
        "grid_import_capacity",
        "hot_iron_capacity",
        "hot_strip_mill_daily_minimum_activity",
        "hot_strip_mill_hourly_within_day",
        "no_grid_reexport",
        "process_max",
        "process_min",
        "sinter_capacity",
        "sintering_plant_daily_minimum_activity",
        "sintering_plant_hourly_within_day",
        "vattenfall_total_volume_cap",
    }
)


def _build_constraint_family_registry() -> dict[str, ValidationRule]:
    registry: dict[str, ValidationRule] = {}
    for family in CUMULATIVE_PRODUCTION_FAMILIES:
        registry[family] = ValidationRule(
            purpose="cumulative_production_acceptance",
            unit="t",
            tolerance=CUMULATIVE_PRODUCTION_TOLERANCE_T,
            aggregation="row_specific_cumulative_not_hourly_accumulated",
            relaxation_allowed=True,
        )
    for family in TERMINAL_STATE_FAMILIES:
        registry[family] = ValidationRule(
            purpose="terminal_or_carried_material_state",
            unit="t",
            tolerance=TERMINAL_STATE_TOLERANCE_T,
            aggregation="terminal_snapshot",
            relaxation_allowed=True,
        )
    for family in ELECTRICITY_BALANCE_FAMILIES:
        registry[family] = ValidationRule(
            purpose="hourly_electricity_balance_identity",
            unit="MWh_e",
            tolerance=ELECTRICITY_BALANCE_TOLERANCE_MWH,
            aggregation="per_hour_no_accumulation",
            relaxation_allowed=False,
        )
    for family in MATERIAL_BALANCE_FAMILIES:
        registry[family] = ValidationRule(
            purpose="hourly_material_balance_identity",
            unit="t",
            tolerance=MATERIAL_BALANCE_TOLERANCE_T,
            aggregation="per_row_no_accumulation",
            relaxation_allowed=False,
        )
    for family in ENERGY_BALANCE_FAMILIES:
        registry[family] = ValidationRule(
            purpose="hourly_energy_balance_identity",
            unit="MWh_LHV",
            tolerance=ENERGY_BALANCE_TOLERANCE_MWH,
            aggregation="per_row_no_accumulation",
            relaxation_allowed=False,
        )
    for family in STRICT_PHYSICAL_FAMILIES:
        registry[family] = ValidationRule(
            purpose="physical_bound_capacity_or_operating_rule",
            unit="model_unit",
            tolerance=SOLVER_NUMERICAL_TOLERANCE,
            aggregation="per_row_solver_numeric",
            relaxation_allowed=False,
        )
    return registry


CONSTRAINT_FAMILY_REGISTRY = _build_constraint_family_registry()


ELECTRICITY_TRAJECTORY_MAX_PURPOSES = (
    "electricity_identity",
    "no_simultaneous_import_export",
    "no_grid_reexport",
    "export_bounded_by_internal_generation",
    "wag_and_ng_generation_exactly_separate",
    "accepted_comparator_export_zero",
)
THRESHOLD_COMPARISON_REGISTRY = {
    purpose: ThresholdComparisonRule(
        unit="MWh_e",
        governed_tolerance=ELECTRICITY_BALANCE_TOLERANCE_MWH,
        aggregation="per_trajectory_max_no_hourly_accumulation",
        comparison_roundoff_ulps=THRESHOLD_COMPARISON_ROUNDOFF_ULPS,
        comparison_roundoff_method=(
            "binary64_ulps_at_max_of_one_raw_residual_and_governed_tolerance"
        ),
    )
    for purpose in ELECTRICITY_TRAJECTORY_MAX_PURPOSES
}


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def exact_input_fingerprint(payload: Any) -> str:
    """Fingerprint frozen inputs without numeric coercion or tolerance."""

    return canonical_json_sha256(payload)


def require_exact_input_fingerprint(
    observed: Any,
    *,
    expected_fingerprint: str,
    purpose: str,
) -> str:
    observed_fingerprint = exact_input_fingerprint(observed)
    if observed_fingerprint != expected_fingerprint:
        raise ValidationTolerancePolicyError(
            f"Exact frozen-input fingerprint mismatch for {purpose}: "
            f"expected {expected_fingerprint}, observed {observed_fingerprint}."
        )
    return observed_fingerprint


def constraint_family_rule(family: str) -> ValidationRule:
    try:
        return CONSTRAINT_FAMILY_REGISTRY[str(family)]
    except KeyError as exc:
        raise ValidationTolerancePolicyError(
            f"Unregistered active steel validation constraint family: {family}."
        ) from exc


def threshold_comparison_rule(purpose: str) -> ThresholdComparisonRule:
    try:
        return THRESHOLD_COMPARISON_REGISTRY[str(purpose)]
    except KeyError as exc:
        raise ValidationTolerancePolicyError(
            f"Unregistered steel threshold-comparison purpose: {purpose}."
        ) from exc


def threshold_comparison_record(
    *,
    validation_id: str,
    purpose: str,
    raw_residual: float,
) -> dict[str, Any]:
    rule = threshold_comparison_rule(purpose)
    residual = abs(float(raw_residual))
    governed_tolerance = float(rule.governed_tolerance)
    if not all(math.isfinite(value) for value in (residual, governed_tolerance)):
        raise ValidationTolerancePolicyError(
            f"Nonfinite threshold-comparison evidence for {validation_id}."
        )
    positive_excess = max(0.0, residual - governed_tolerance)
    comparison_scale = max(1.0, residual, governed_tolerance)
    comparison_roundoff_allowance = (
        int(rule.comparison_roundoff_ulps) * math.ulp(comparison_scale)
    )
    normalized_residual = (
        residual / governed_tolerance
        if governed_tolerance > 0.0
        else (0.0 if residual == 0.0 else math.inf)
    )
    return {
        "validation_id": str(validation_id),
        "validation_purpose": str(purpose),
        "unit": rule.unit,
        "aggregation": rule.aggregation,
        "raw_residual": residual,
        "allowed_tolerance": governed_tolerance,
        "governed_tolerance": governed_tolerance,
        "positive_excess": positive_excess,
        "comparison_roundoff_allowance": comparison_roundoff_allowance,
        "comparison_roundoff_ulps": int(rule.comparison_roundoff_ulps),
        "comparison_roundoff_method": rule.comparison_roundoff_method,
        "normalized_residual": normalized_residual,
        "tolerance_accumulation_allowed": False,
        "status": (
            "pass"
            if positive_excess <= comparison_roundoff_allowance
            else "fail"
        ),
    }


def trajectory_cost_tolerance_eur(comparison_scale_eur: float) -> float:
    scale = abs(float(comparison_scale_eur))
    if not math.isfinite(scale):
        raise ValidationTolerancePolicyError(
            "Trajectory cost comparison scale must be finite."
        )
    return max(
        TRAJECTORY_COST_ABSOLUTE_FLOOR_EUR,
        TRAJECTORY_COST_RELATIVE_TOLERANCE * scale,
    )


def validation_record(
    *,
    validation_id: str,
    purpose: str,
    unit: str,
    raw_residual: float,
    allowed_tolerance: float,
    aggregation: str,
    used_relaxation: float = 0.0,
) -> dict[str, Any]:
    residual = abs(float(raw_residual))
    tolerance = float(allowed_tolerance)
    used = abs(float(used_relaxation))
    if not all(math.isfinite(item) for item in (residual, tolerance, used)):
        raise ValidationTolerancePolicyError(
            f"Nonfinite validation evidence for {validation_id}."
        )
    normalized = residual / tolerance if tolerance > 0.0 else (
        0.0 if residual == 0.0 else math.inf
    )
    return {
        "validation_id": validation_id,
        "purpose": purpose,
        "unit": unit,
        "aggregation": aggregation,
        "raw_residual": residual,
        "allowed_tolerance": tolerance,
        "used_relaxation": used,
        "normalized_residual": normalized,
        "status": "pass" if residual <= tolerance and used <= tolerance else "fail",
    }


def hourly_money_identity_record(
    validation_id: str, residual_eur: float
) -> dict[str, Any]:
    return validation_record(
        validation_id=validation_id,
        purpose="hourly_money_identity",
        unit="EUR",
        raw_residual=residual_eur,
        allowed_tolerance=HOURLY_MONEY_IDENTITY_TOLERANCE_EUR,
        aggregation="per_hour_no_accumulation",
    )


def trajectory_cost_record(
    validation_id: str,
    residual_eur: float,
    *,
    comparison_scale_eur: float,
) -> dict[str, Any]:
    return validation_record(
        validation_id=validation_id,
        purpose="trajectory_or_yearly_aggregate_cost",
        unit="EUR",
        raw_residual=residual_eur,
        allowed_tolerance=trajectory_cost_tolerance_eur(comparison_scale_eur),
        aggregation="trajectory_total_independent_of_hourly_tolerances",
    )


def validate_hourly_and_trajectory_costs(
    hourly_residuals_eur: Sequence[float],
    *,
    trajectory_residual_eur: float,
    comparison_scale_eur: float,
) -> dict[str, Any]:
    hourly = [
        hourly_money_identity_record(f"hourly_cost[{index}]", residual)
        for index, residual in enumerate(hourly_residuals_eur)
    ]
    trajectory = trajectory_cost_record(
        "trajectory_cost",
        trajectory_residual_eur,
        comparison_scale_eur=comparison_scale_eur,
    )
    return {
        "hourly": hourly,
        "trajectory": trajectory,
        "status": (
            "pass"
            if all(row["status"] == "pass" for row in hourly)
            and trajectory["status"] == "pass"
            else "fail"
        ),
        "tolerance_accumulation_allowed": False,
    }


def presentation_value(
    value: float,
    *,
    unit: str,
    purpose: str,
    tolerance: float | None = None,
    status: str | None = None,
) -> str:
    """Format a human-facing value; never use this for machine evidence."""

    numeric = float(value)
    if tolerance is not None and abs(numeric) < 0.001 and unit == "t":
        suffix = f": {status.upper()}" if status else ""
        return f"<0.001 t (tol {float(tolerance):.1f} t){suffix}"
    if unit == "t":
        return f"{numeric:.1f} t" if purpose.endswith("state") else f"{numeric:.0f} t"
    if unit.startswith("MWh"):
        return f"{numeric:.3f} {unit}"
    if unit == "EUR" and purpose == "hourly_money_identity":
        return f"EUR {numeric:.2f}"
    if unit == "EUR":
        return f"EUR {numeric:.0f}"
    return f"{numeric:g} {unit}".strip()


def policy_definition() -> dict[str, Any]:
    return {
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "solver_numerical_tolerance": SOLVER_NUMERICAL_TOLERANCE,
        "hourly_money_identity_tolerance_eur": (
            HOURLY_MONEY_IDENTITY_TOLERANCE_EUR
        ),
        "trajectory_cost_absolute_floor_eur": (
            TRAJECTORY_COST_ABSOLUTE_FLOOR_EUR
        ),
        "trajectory_cost_relative_tolerance": (
            TRAJECTORY_COST_RELATIVE_TOLERANCE
        ),
        "input_price_comparison": "exact_fingerprint_no_numeric_tolerance",
        "threshold_comparison_registry": {
            purpose: asdict(rule)
            for purpose, rule in sorted(THRESHOLD_COMPARISON_REGISTRY.items())
        },
        "constraint_family_registry": {
            family: asdict(rule)
            for family, rule in sorted(CONSTRAINT_FAMILY_REGISTRY.items())
        },
        "tolerance_accumulation_allowed": False,
    }


POLICY_FINGERPRINT = canonical_json_sha256(policy_definition())


def policy_contract() -> dict[str, str]:
    return {
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "policy_fingerprint_sha256": POLICY_FINGERPRINT,
    }


def resolve_policy_contract(payload: Mapping[str, Any]) -> dict[str, str]:
    expected = policy_contract()
    observed = {
        key: str(payload.get(key, ""))
        for key in expected
    }
    if observed != expected:
        raise ValidationTolerancePolicyError(
            f"Steel validation-tolerance policy identity mismatch: {observed}."
        )
    return expected


# Existing runners and tolerance-bearing validation modules remain explicit
# legacy exemptions.  Their filename inventories are hashed so a new relevant
# file must deliberately import/register this policy rather than silently
# inheriting a blanket numeric comparison.
POLICY_ENFORCED_RUNNERS = frozenset(
    {"run_s4_4c5p_c0_athanasiadis_sale_sensitivity.py"}
)
LEGACY_RUNNER_INVENTORY_COUNT = 109
LEGACY_RUNNER_INVENTORY_SHA256 = (
    "e42748ae28138c21725afcb32e73cda9a671b5e50782b0f73939f4c50f783127"
)
POLICY_ENFORCED_STEEL_MODULES = frozenset(
    {
        "s4_4c5p_c0_athanasiadis_sale_sensitivity.py",
        "s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        "s4_4c_unified_physical_modelbuilder.py",
    }
)
LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_COUNT = 17
LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_SHA256 = (
    "2176ea057f92fc3df15aee34139e8cd4ba324c7006e72addbb1783df463bae99"
)
_POLICY_RELEVANT_SEMANTIC_TOKENS = (
    "validate",
    "validation",
    "guardrail",
    "containment",
    "oracle",
    "evidence",
)


def _source_imports_validation_tolerance_policy(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and str(node.module or "").endswith("validation_tolerance_policy")
        for node in ast.walk(tree)
    )


def tolerance_bearing_validation_module_source(
    filename: str, source: str
) -> bool:
    """Recognize policy-relevant modules without scanning numeric constants."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    semantic = any(
        token in Path(filename).stem.lower()
        for token in _POLICY_RELEVANT_SEMANTIC_TOKENS
    ) or any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and any(
            token in node.name.lower()
            for token in _POLICY_RELEVANT_SEMANTIC_TOKENS
        )
        for node in ast.walk(tree)
    )
    tolerance_bearing = any(
        (
            isinstance(node, ast.Name)
            and "tolerance" in node.id.lower()
        )
        or (
            isinstance(node, ast.arg)
            and "tolerance" in node.arg.lower()
        )
        for node in ast.walk(tree)
    )
    return bool(semantic and tolerance_bearing)


def require_new_file_policy_registration(
    relative_path: str, source: str
) -> None:
    """Fail closed for a new runner or policy-relevant steel module."""

    path = Path(relative_path)
    is_runner = path.name.startswith("run_") and path.suffix == ".py"
    is_validation_module = (
        path.parent.name == "steel"
        and tolerance_bearing_validation_module_source(path.name, source)
    )
    if not (is_runner or is_validation_module):
        return
    if not _source_imports_validation_tolerance_policy(source):
        raise ValidationTolerancePolicyError(
            f"New policy-relevant file must import the shared validation "
            f"tolerance policy: {relative_path}."
        )
    if "VALIDATION_TOLERANCE_POLICY_REQUIRED" not in source:
        raise ValidationTolerancePolicyError(
            f"New policy-relevant file must declare policy registration: "
            f"{relative_path}."
        )


def repository_policy_registration_diagnostics(
    steel_test_case_root: Path,
) -> dict[str, Any]:
    """Validate frozen legacy inventories and explicit canonical registrations."""

    root = Path(steel_test_case_root)
    failures: list[str] = []
    runners = sorted(root.glob("run_*.py"))
    enforced_runners = [
        path for path in runners if path.name in POLICY_ENFORCED_RUNNERS
    ]
    legacy_runners = [
        path for path in runners if path.name not in POLICY_ENFORCED_RUNNERS
    ]
    runner_payload = "".join(path.name + "\n" for path in legacy_runners)
    runner_hash = hashlib.sha256(runner_payload.encode("utf-8")).hexdigest()
    if len(legacy_runners) != LEGACY_RUNNER_INVENTORY_COUNT:
        failures.append("legacy_runner_inventory_count")
    if runner_hash != LEGACY_RUNNER_INVENTORY_SHA256:
        failures.append("legacy_runner_inventory_sha256")
    if {path.name for path in enforced_runners} != POLICY_ENFORCED_RUNNERS:
        failures.append("enforced_runner_inventory")
    for path in enforced_runners:
        source = path.read_text(encoding="utf-8")
        if not _source_imports_validation_tolerance_policy(source):
            failures.append(f"enforced_runner_missing_policy_import:{path.name}")
        if "VALIDATION_TOLERANCE_POLICY_REQUIRED" not in source:
            failures.append(f"enforced_runner_missing_registration:{path.name}")

    module_root = root / "steel"
    relevant_modules: list[Path] = []
    for path in sorted(module_root.glob("*.py")):
        if path.name == "validation_tolerance_policy.py":
            continue
        source = path.read_text(encoding="utf-8")
        if tolerance_bearing_validation_module_source(path.name, source):
            relevant_modules.append(path)
    enforced_modules = [
        path
        for path in relevant_modules
        if path.name in POLICY_ENFORCED_STEEL_MODULES
    ]
    legacy_modules = [
        path
        for path in relevant_modules
        if path.name not in POLICY_ENFORCED_STEEL_MODULES
    ]
    module_payload = "".join(path.name + "\n" for path in legacy_modules)
    module_hash = hashlib.sha256(module_payload.encode("utf-8")).hexdigest()
    if len(legacy_modules) != LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_COUNT:
        failures.append("legacy_policy_module_inventory_count")
    if module_hash != LEGACY_POLICY_RELEVANT_MODULE_INVENTORY_SHA256:
        failures.append("legacy_policy_module_inventory_sha256")
    if {path.name for path in enforced_modules} != POLICY_ENFORCED_STEEL_MODULES:
        failures.append("enforced_policy_module_inventory")
    for path in enforced_modules:
        if not _source_imports_validation_tolerance_policy(
            path.read_text(encoding="utf-8")
        ):
            failures.append(f"enforced_module_missing_policy_import:{path.name}")
    return {
        "status": "pass" if not failures else "fail",
        "failure_ids": failures,
        "runner_count": len(runners),
        "legacy_runner_count": len(legacy_runners),
        "legacy_runner_inventory_sha256": runner_hash,
        "policy_relevant_module_count": len(relevant_modules),
        "legacy_policy_relevant_module_count": len(legacy_modules),
        "legacy_policy_relevant_module_inventory_sha256": module_hash,
    }


def constraint_registry_fingerprint(families: Iterable[str]) -> str:
    resolved = {
        str(family): asdict(constraint_family_rule(str(family)))
        for family in sorted(set(families))
    }
    return canonical_json_sha256(resolved)
