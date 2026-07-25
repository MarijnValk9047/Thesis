"""Bounded C0 electricity-boundary / NG-price mechanism experiment.

The module adds orchestration and compact diagnostics only. Every optimisation
is delegated to the accepted p_af rolling runner and the accepted physical
parameters remain unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .c5_user_authorized_emulation_checkpoint4 import (
    _artifact,
    _case_ready,
)
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_bf_price_series_interface import (
    _resolve_dplus4_source_files,
    load_dplus4_source_contract,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs"
    / "steel_c5_real_anchor_mechanism_experiment.yaml"
)
EXPECTED_CANDIDATES = (
    "source_driven_baseline",
    "recovery_bg25_ng55",
    "recovery_bg30_ng55",
    "recovery_bg31_ng55",
    "recovery_bg30_ng30",
)
EXPECTED_SCENARIOS = (
    "calm_price_insensitive",
    "volatile_negative_governed_y_pred",
    "volatile_negative_oracle_y_true",
)
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")
SPECIAL_NG_FLOWS = (
    "C0_NG_GENERATOR",
    "C0_NG_FIXED_FULL_SITE",
    "C0_NG_FLEXIBLE_OTHER_SITE_HEAT",
)
BF_CAPACITIES_T_SINTER_H = {
    "C0_BF6": 170.0,
    "C0_BF7": 261.53846154,
    "C1_BF6": 170.0,
}
ENERGY_TOLERANCE = 0.01
FINAL_DECISION = (
    "lower_ng_activates_generator_ng_in_volatile_cases_"
    "allocation_location_tiebreak_selected_stop_no_second_search"
)
TIE_BREAK_INTERPRETATION = (
    "The builder tie-break penalizes flexible-heat NG but not named generator NG. "
    "When feasible, NG-to-generator plus WAG-to-flexible-heat is economically "
    "equivalent and tie-break selected versus NG-to-flexible-heat plus "
    "WAG-to-generator. Zero flexible NG is therefore non-identifiable and is not "
    "proof that substitution is absent."
)


class MechanismExperimentError(RuntimeError):
    """Raised when the frozen experiment contract or a physical gate fails."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise MechanismExperimentError(f"Refusing to write empty output: {path.name}")
    fields: list[str] = []
    for row in materialised:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialised)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _resolved_config_sha256(payload: Mapping[str, Any]) -> str:
    encoded = yaml.safe_dump(dict(payload), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def mwh_lhv_to_pj(value_mwh_lhv: float) -> float:
    return value_mwh_lhv * 3.6e-6


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_mechanism_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))


def validate_mechanism_config(config: Mapping[str, Any]) -> None:
    if config.get("mode") != "c0_real_anchor_mechanism_experiment":
        raise MechanismExperimentError("Unexpected mechanism-experiment mode.")
    if config.get("output_policy") != "minimal":
        raise MechanismExperimentError("The experiment requires output_policy=minimal.")
    experiment = config["experiment"]
    candidates = tuple(row["candidate_id"] for row in experiment["candidates"])
    scenarios = tuple(row["scenario_id"] for row in experiment["scenarios"])
    periods = tuple(row["period_id"] for row in experiment["development_periods"])
    if candidates != EXPECTED_CANDIDATES:
        raise MechanismExperimentError(f"Frozen candidates differ: {candidates}.")
    if scenarios != EXPECTED_SCENARIOS:
        raise MechanismExperimentError(f"Frozen scenarios differ: {scenarios}.")
    if periods != EXPECTED_PERIODS:
        raise MechanismExperimentError(f"Frozen periods differ: {periods}.")
    if int(experiment["expected_rolling_case_count"]) != 15:
        raise MechanismExperimentError("Exactly 5x3=15 rolling cases are required.")
    if int(experiment["expected_model_count"]) != 210:
        raise MechanismExperimentError("Exactly 210 C0/C1 solver records are required.")
    if experiment.get("held_out_periods_used") is not False or any(
        row["dataset_split"] != "validation"
        or row["period_role"] != "development"
        or row["final_held_out_selection_eligible"] is not False
        for row in experiment["development_periods"]
    ):
        raise MechanismExperimentError("Held-out periods are prohibited.")
    y_true = [
        row["scenario_id"]
        for row in experiment["scenarios"]
        if row["price_field"] == "y_true"
    ]
    if y_true != ["volatile_negative_oracle_y_true"] or any(
        (row["price_field"] == "y_true")
        != bool(row["perfect_foresight_oracle"])
        for row in experiment["scenarios"]
    ):
        raise MechanismExperimentError("y_true is permitted only in the labelled oracle.")

    expected_candidates = (
        (False, 0.0, 0.0, "development_central", 55.0),
        (True, 0.25, 0.7925, "development_central", 55.0),
        (True, 0.30, 0.951, "development_central", 55.0),
        (True, 0.31, 0.9827, "development_central", 55.0),
        (True, 0.30, 0.951, "development_low", 30.0),
    )
    observed_candidates = tuple(
        (
            bool(row["repair_interface_active"]),
            float(row["explicit_background_share"]),
            float(row["explicit_background_twh_y"]),
            row["ng_price_scenario_id"],
            float(row["ng_price_eur_per_mwh_lhv"]),
        )
        for row in experiment["candidates"]
    )
    if observed_candidates != expected_candidates:
        raise MechanismExperimentError("The frozen candidate parameter matrix changed.")

    generator = experiment["recovery_interface"][
        "c0_aggregate_generator_technical_interface"
    ]
    bridge = experiment["recovery_interface"]["c0_full_site_energy_bridge"]
    immutable = experiment["immutable_physical_contract"]
    required = {
        "electricity_efficiency": 0.345,
        "total_fuel_volume_cap_nm3_h": 900000.0,
        "electrical_capacity_mw": 770.0,
        "natural_gas_lhv_mj_per_nm3": 35.8,
    }
    if any(abs(float(generator[key]) - value) > 1e-12 for key, value in required.items()):
        raise MechanismExperimentError("The aggregate-generator physical interface changed.")
    if generator["export_allowed"] is not False:
        raise MechanismExperimentError("Export must remain disabled.")
    if (
        abs(float(bridge["inferred_low_case_full_site_ng_floor_pj_y"]) - 8.005)
        > 1e-12
        or abs(
            float(bridge["flexible_other_site_heat_service_envelope_pj_y"]) - 3.07
        )
        > 1e-12
    ):
        raise MechanismExperimentError("The physical NG bridge changed.")
    if immutable["wag_generation_yield_overrides_by_configuration"] != {} or any(
        immutable[key] is not False
        for key in (
            "physical_ng_bridge_changed",
            "operating_rules_changed",
            "route_logic_changed",
        )
    ):
        raise MechanismExperimentError("Immutable physical parameters were reopened.")


def _scenario_overrides(
    scenario: Mapping[str, Any],
    periods: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    period = periods[str(scenario["period_id"])]
    return {
        "replan_count": 7,
        "price_series_id": "hourly_da_dplus4_point_forecast",
        "generator_operating_mode": "development_price_responsive",
        "forecast_dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "timestamped_dplus4_rolling_enabled": True,
        "forecast_price_override_eur_per_mwh": scenario.get(
            "flat_price_eur_per_mwh"
        ),
        "forecast_price_field": scenario["price_field"],
        "perfect_foresight_oracle": bool(scenario["perfect_foresight_oracle"]),
    }


def candidate_overrides(
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    background_mwh_h = (
        float(candidate["explicit_background_twh_y"]) * 1_000_000.0 / 8760.0
    )
    overrides: dict[str, Any] = {
        "site_background_electricity_mwh_h_by_configuration": {
            C0_CONFIGURATION: background_mwh_h,
            C1_CONFIGURATION: 0.0,
        },
        "price_scenario_overrides": {
            "natural_gas_ttf_proxy": candidate["ng_price_scenario_id"]
        },
        "wag_generation_yield_overrides_by_configuration": {},
        "mechanism_candidate_id": candidate["candidate_id"],
        "mechanism_ng_price_eur_per_mwh_lhv": float(
            candidate["ng_price_eur_per_mwh_lhv"]
        ),
    }
    if bool(candidate["repair_interface_active"]):
        recovery = config["experiment"]["recovery_interface"]
        overrides.update(
            {
                "c0_aggregate_generator_technical_interface": dict(
                    recovery["c0_aggregate_generator_technical_interface"]
                ),
                "c0_full_site_energy_bridge": dict(
                    recovery["c0_full_site_energy_bridge"]
                ),
            }
        )
    return overrides


def structural_parameter_invariance_rows(
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Prove invariance from the frozen candidate inputs, not realised dispatch."""

    experiment = config["experiment"]
    immutable = experiment["immutable_physical_contract"]
    recovery = experiment["recovery_interface"]
    expected_keys = {
        "site_background_electricity_mwh_h_by_configuration",
        "price_scenario_overrides",
        "wag_generation_yield_overrides_by_configuration",
        "mechanism_candidate_id",
        "mechanism_ng_price_eur_per_mwh_lhv",
        "c0_aggregate_generator_technical_interface",
        "c0_full_site_energy_bridge",
    }
    output: list[dict[str, Any]] = []
    for candidate in experiment["candidates"]:
        if not bool(candidate["repair_interface_active"]):
            continue
        overrides = candidate_overrides(config, candidate)
        generator = overrides.get("c0_aggregate_generator_technical_interface", {})
        bridge = overrides.get("c0_full_site_energy_bridge", {})
        invariant = (
            set(overrides) == expected_keys
            and overrides["wag_generation_yield_overrides_by_configuration"]
            == immutable["wag_generation_yield_overrides_by_configuration"]
            == {}
            and generator
            == recovery["c0_aggregate_generator_technical_interface"]
            and bridge == recovery["c0_full_site_energy_bridge"]
            and float(generator["electricity_efficiency"]) == 0.345
            and float(generator["electrical_capacity_mw"]) == 770.0
            and float(generator["total_fuel_volume_cap_nm3_h"]) == 900000.0
            and generator["export_allowed"] is False
            and float(bridge["inferred_low_case_full_site_ng_floor_pj_y"])
            == 8.005
            and float(
                bridge["flexible_other_site_heat_service_envelope_pj_y"]
            )
            == 3.07
            and all(
                immutable[key] is False
                for key in (
                    "physical_ng_bridge_changed",
                    "operating_rules_changed",
                    "route_logic_changed",
                )
            )
        )
        output.append(
            {
                "scenario_id": "structural_contract",
                "candidate_id": candidate["candidate_id"],
                "comparison_id": "frozen_physical_parameter_invariance",
                "status": "pass" if invariant else "fail",
                "bg25_value": "",
                "bg30_ng55_value": "",
                "bg31_value": "",
                "bg30_ng30_value": "",
                "difference_ng30_minus_ng55": "",
                "wag_yield_overrides_sha256": _mapping_sha256(
                    overrides["wag_generation_yield_overrides_by_configuration"]
                ),
                "generator_interface_sha256": _mapping_sha256(generator),
                "full_site_bridge_sha256": _mapping_sha256(bridge),
                "interpretation": (
                    "empty identical WAG-yield overrides; unchanged routes/rules; "
                    "eta=0.345, capacity=770 MW, fuel-volume cap=900000 Nm3/h, "
                    "no export, fixed NG=8.005 PJ/y and flexible envelope=3.07 PJ/y"
                ),
            }
        )
    return output


def frozen_scenario_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_mechanism_config(config)
    experiment = config["experiment"]
    periods = {row["period_id"]: row for row in experiment["development_periods"]}
    rows: list[dict[str, Any]] = []
    for candidate in experiment["candidates"]:
        for scenario in experiment["scenarios"]:
            resolved = {
                **_scenario_overrides(scenario, periods),
                **candidate_overrides(config, candidate),
            }
            rows.append(
                {
                    "case_id": _case_id(
                        candidate["candidate_id"], scenario["scenario_id"]
                    ),
                    "candidate_id": candidate["candidate_id"],
                    "scenario_id": scenario["scenario_id"],
                    "period_id": scenario["period_id"],
                    "dataset_split": periods[scenario["period_id"]]["dataset_split"],
                    "price_field": scenario["price_field"],
                    "perfect_foresight_oracle": scenario[
                        "perfect_foresight_oracle"
                    ],
                    "flat_price_eur_per_mwh": scenario.get(
                        "flat_price_eur_per_mwh"
                    ),
                    "ng_price_eur_per_mwh_lhv": candidate[
                        "ng_price_eur_per_mwh_lhv"
                    ],
                    "explicit_background_twh_y": candidate[
                        "explicit_background_twh_y"
                    ],
                    "final_held_out_selection_eligible": False,
                    "resolved_override_sha256": _mapping_sha256(resolved),
                }
            )
    return rows


def _case_id(candidate_id: str, scenario_id: str) -> str:
    return f"mech__{candidate_id}__{scenario_id}".replace("-", "_")


def delta_inventory_price_correlation(
    inventory: Sequence[float], prices: Sequence[float]
) -> float | None:
    """Badarinath diagnostic: corr(inventory[t]-inventory[t-1], price[t])."""

    if len(inventory) != len(prices) or len(inventory) < 3:
        return None
    deltas = [inventory[index] - inventory[index - 1] for index in range(1, len(inventory))]
    aligned_prices = list(prices[1:])
    left_mean = statistics.fmean(deltas)
    right_mean = statistics.fmean(aligned_prices)
    numerator = sum(
        (left - left_mean) * (right - right_mean)
        for left, right in zip(deltas, aligned_prices, strict=True)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in deltas)
        * sum((value - right_mean) ** 2 for value in aligned_prices)
    )
    return numerator / denominator if denominator else None


def bf_utilization_metrics(
    throughput: Sequence[float],
    capacity_t_h: float,
    *,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    if capacity_t_h <= 0.0 or not throughput:
        raise MechanismExperimentError("BF utilization requires a positive capacity and data.")
    return {
        "mean_utilization": statistics.fmean(throughput) / capacity_t_h,
        "share_hours_at_max": sum(
            abs(value - capacity_t_h) <= tolerance for value in throughput
        )
        / len(throughput),
    }


def validate_unique_named_ng_pricing(
    cost_rows: Sequence[Mapping[str, Any]],
    *,
    expected_price_eur_per_mwh_lhv: float,
    executed_hours: int,
) -> list[dict[str, Any]]:
    """Check the three opt-in named-NG flows occur once per executed timestamp."""

    results: list[dict[str, Any]] = []
    for flow_id in SPECIAL_NG_FLOWS:
        rows = [row for row in cost_rows if row.get("flow_id") == flow_id]
        keys = {
            (
                row.get("configuration_id"),
                int(row["replan_index"]),
                int(row["executed_hour_index"]),
            )
            for row in rows
        }
        prices = {_number(row.get("price_eur_per_unit")) for row in rows}
        passed = (
            len(rows) == executed_hours
            and len(keys) == executed_hours
            and prices == {expected_price_eur_per_mwh_lhv}
            and all(row.get("price_id") == "natural_gas_ttf_proxy" for row in rows)
        )
        results.append(
            {
                "check_id": f"unique_pricing::{flow_id}",
                "status": "pass" if passed else "fail",
                "row_count": len(rows),
                "unique_timestamp_count": len(keys),
                "observed_prices": ";".join(str(value) for value in sorted(prices)),
            }
        )
    residual = [
        row
        for row in cost_rows
        if "RESIDUAL" in str(row.get("flow_id", "")).upper()
        or "residual" in str(row.get("cost_route", "")).lower()
    ]
    results.append(
        {
            "check_id": "residual_ng_never_priced",
            "status": "pass" if not residual else "fail",
            "row_count": len(residual),
            "unique_timestamp_count": "",
            "observed_prices": "",
        }
    )
    return results


def _annual_component(
    physical: Sequence[Mapping[str, Any]], configuration: str, component: str
) -> float:
    rows = [
        row
        for row in physical
        if row["configuration_id"] == configuration
        and row["component"] == component
    ]
    return _number(rows[0]["annual_value"]) if rows else 0.0


def basic_ledger_guardrails(
    physical: Sequence[Mapping[str, Any]],
    cost_rows: Sequence[Mapping[str, Any]],
    *,
    configuration: str,
    reported_cost_eur: float,
) -> list[dict[str, Any]]:
    residual = max(
        (
            abs(_number(row["annual_value"]))
            for row in physical
            if row["flow_role"] == "accounting_residual"
        ),
        default=0.0,
    )
    export = abs(_annual_component(physical, configuration, "gross_grid_export"))
    mixed = [
        row
        for row in physical
        if row["ledger_family"] == "WAG"
        and row["carrier_or_material"] not in {"BFG", "COG", "BOFG"}
    ]
    recomputed_cost = sum(_number(row["cost_eur"]) for row in cost_rows)
    return [
        {
            "check_id": "all_accounting_residuals",
            "status": "pass" if residual <= ENERGY_TOLERANCE else "fail",
            "maximum_abs_residual": residual,
            "evidence": "annual physical ledger",
        },
        {
            "check_id": "no_export",
            "status": "pass" if export <= ENERGY_TOLERANCE else "fail",
            "maximum_abs_residual": export,
            "evidence": "gross grid export",
        },
        {
            "check_id": "no_mixed_WAG",
            "status": "pass" if not mixed else "fail",
            "maximum_abs_residual": float(len(mixed)),
            "evidence": "BFG/COG/BOFG carrier rows only",
        },
        {
            "check_id": "cost_ledger_identity",
            "status": (
                "pass"
                if abs(recomputed_cost - reported_cost_eur) <= ENERGY_TOLERANCE
                else "fail"
            ),
            "maximum_abs_residual": abs(recomputed_cost - reported_cost_eur),
            "evidence": "executed cost ledger minus procurement summary",
        },
    ]


def _prices_for_hourly(
    price_rows: Sequence[Mapping[str, Any]],
    hourly_rows: Sequence[Mapping[str, Any]],
) -> list[float]:
    price_by_key = {
        (int(row["replan_index"]), int(row["model_hour"])): _number(
            row["price_eur_per_mwh_e"]
        )
        for row in price_rows
    }
    return [
        price_by_key[(int(row["replan_index"]), int(row["hour_index"]))]
        for row in hourly_rows
    ]


def _metric_rows(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    matrix: Sequence[Mapping[str, Any]],
    annual_label: str,
) -> list[dict[str, Any]]:
    matrix_by_key = {
        (row["candidate_id"], row["scenario_id"]): row for row in matrix
    }
    output: list[dict[str, Any]] = []
    for (candidate, scenario), artifact in sorted(artifacts.items()):
        physical = artifact["physical"]
        procurement = _read_csv(Path(artifact["directory"]) / "procurement_cost_summary.csv")
        procurement_by_configuration = {
            row["configuration_id"]: row for row in procurement
        }
        for configuration in CONFIGURATIONS:
            hourly = sorted(
                (
                    row
                    for row in artifact["hourly"]
                    if row["configuration_id"] == configuration
                ),
                key=lambda row: int(row["executed_hour_index"]),
            )
            wag_generated = sum(
                _annual_component(physical, configuration, f"{carrier}_generated")
                for carrier in ("BFG", "COG", "BOFG")
            )
            wag_to_generator = sum(
                _annual_component(physical, configuration, f"{carrier}_to_vattenfall")
                for carrier in ("BFG", "COG", "BOFG")
            )
            wag_to_flexible = sum(
                _annual_component(
                    physical, configuration, f"{carrier}_to_flexible_other_site_heat"
                )
                for carrier in ("BFG", "COG", "BOFG")
            )
            flare = sum(
                _annual_component(physical, configuration, f"{carrier}_flared")
                for carrier in ("BFG", "COG", "BOFG")
            )
            prices = _prices_for_hourly(artifact["prices"], hourly)
            median_price = statistics.median(prices)
            eaf = [_number(row.get("C1_EAF_liquid_steel_output_t_h")) for row in hourly]
            eaf_high = [
                value for value, price in zip(eaf, prices, strict=True) if price > median_price
            ]
            eaf_low = [
                value for value, price in zip(eaf, prices, strict=True) if price <= median_price
            ]
            no_export_binding_hours = sum(
                abs(_number(row.get("gross_grid_import_mwh"))) <= 1e-6
                for row in hourly
            )
            cost_row = procurement_by_configuration[configuration]
            output.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "period_id": matrix_by_key[(candidate, scenario)]["period_id"],
                    "configuration_id": configuration,
                    "annual_equivalent_basis": annual_label,
                    "executed_hours": len(hourly),
                    "represented_gross_electricity_mwh_y": _annual_component(
                        physical, configuration, "gross_total_electricity"
                    ),
                    "explicit_background_load_mwh_y": _annual_component(
                        physical,
                        configuration,
                        "explicit_site_background_electricity",
                    ),
                    "wag_carrier_generation_mwh_lhv_y": wag_generated,
                    "wag_to_mandatory_process_heat_mwh_lhv_y": (
                        wag_generated - wag_to_generator - wag_to_flexible - flare
                    ),
                    "wag_to_flexible_heat_mwh_lhv_y": wag_to_flexible,
                    "wag_to_generators_mwh_lhv_y": wag_to_generator,
                    "actual_wag_only_generator_electricity_mwh_y": _annual_component(
                        physical, configuration, "WAG_generator_electricity"
                    ),
                    "ng_generated_electricity_mwh_y": _annual_component(
                        physical, configuration, "NG_generator_electricity"
                    ),
                    "grid_import_mwh_y": _annual_component(
                        physical, configuration, "gross_grid_import"
                    ),
                    "fixed_named_ng_mwh_lhv_y": _annual_component(
                        physical, configuration, "fixed_full_site_component"
                    ),
                    "flexible_named_ng_mwh_lhv_y": _annual_component(
                        physical, configuration, "flexible_other_site_heat"
                    ),
                    "generator_named_ng_mwh_lhv_y": _annual_component(
                        physical, configuration, "VN25_generator"
                    ),
                    "total_named_ng_mwh_lhv_y": _annual_component(
                        physical, configuration, "represented_named_NG"
                    ),
                    "flare_curtailment_mwh_lhv_y": flare,
                    "no_export_binding_hours": no_export_binding_hours,
                    "procurement_cost_eur_for_development_week": _number(
                        cost_row["executed_procurement_cost_eur"]
                    ),
                    "procurement_cost_annual_equivalent_eur_y": _number(
                        cost_row["annualised_procurement_cost_eur_y"]
                    ),
                    "mean_price_eur_per_mwh": statistics.fmean(prices),
                    "negative_price_share": sum(value < 0.0 for value in prices)
                    / len(prices),
                    "eaf_high_price_mean_t_h": (
                        statistics.fmean(eaf_high) if eaf_high else ""
                    ),
                    "eaf_low_price_mean_t_h": (
                        statistics.fmean(eaf_low) if eaf_low else ""
                    ),
                }
            )
    return output


def _behavior_rows(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for (candidate, scenario), artifact in sorted(artifacts.items()):
        for configuration in CONFIGURATIONS:
            hourly = sorted(
                (
                    row
                    for row in artifact["hourly"]
                    if row["configuration_id"] == configuration
                ),
                key=lambda row: int(row["executed_hour_index"]),
            )
            prices = _prices_for_hourly(artifact["prices"], hourly)
            hsm_field = (
                "C0_HSM_final_product_t"
                if configuration == C0_CONFIGURATION
                else "C1_HSM_final_product_output_t"
            )
            dsp_field = (
                "C0_DSP_final_product_t"
                if configuration == C0_CONFIGURATION
                else "C1_DSP_final_product_output_t"
            )
            hsm = sum(_number(row.get(hsm_field)) for row in hourly)
            dsp = sum(_number(row.get(dsp_field)) for row in hourly)
            output.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "configuration_id": configuration,
                    "diagnostic_id": "hsm_output_exceeds_dsp_output",
                    "metric_value": hsm - dsp,
                    "status": "pass" if hsm > dsp else "fail",
                    "definition": "executed HSM output minus executed DSP output",
                }
            )
            if configuration == C0_CONFIGURATION:
                bf_series = (
                    ("C0_BF6", "C0_BF6_sinter_input_t_h"),
                    ("C0_BF7", "C0_BF7_sinter_input_t_h"),
                )
            else:
                bf_series = (("C1_BF6", "C1_retained_BF6_sinter_input_t_h"),)
            for asset, field in bf_series:
                values = [_number(row.get(field)) for row in hourly]
                metrics = bf_utilization_metrics(
                    values, BF_CAPACITIES_T_SINTER_H[asset]
                )
                for metric, value in metrics.items():
                    output.append(
                        {
                            "candidate_id": candidate,
                            "scenario_id": scenario,
                            "configuration_id": configuration,
                            "diagnostic_id": f"{asset.lower()}_{metric}",
                            "metric_value": value,
                            "status": "reported",
                            "definition": (
                                "throughput/nameplate capacity"
                                if metric == "mean_utilization"
                                else "share of executed hours at nameplate maximum"
                            ),
                        }
                    )
            if configuration == C1_CONFIGURATION:
                inventory = [_number(row.get("DRI_inventory_t")) for row in hourly]
                correlation = delta_inventory_price_correlation(inventory, prices)
                output.append(
                    {
                        "candidate_id": candidate,
                        "scenario_id": scenario,
                        "configuration_id": configuration,
                        "diagnostic_id": "badarinath_delta_dri_inventory_price_correlation",
                        "metric_value": "" if correlation is None else correlation,
                        "status": "reported",
                        "definition": "corr(DRI_inventory[t]-DRI_inventory[t-1], price[t])",
                    }
                )
                median_price = statistics.median(prices)
                eaf = [
                    _number(row.get("C1_EAF_liquid_steel_output_t_h"))
                    for row in hourly
                ]
                high = [
                    value
                    for value, price in zip(eaf, prices, strict=True)
                    if price > median_price
                ]
                low = [
                    value
                    for value, price in zip(eaf, prices, strict=True)
                    if price <= median_price
                ]
                response = (
                    statistics.fmean(low) - statistics.fmean(high)
                    if high and low
                    else 0.0
                )
                output.append(
                    {
                        "candidate_id": candidate,
                        "scenario_id": scenario,
                        "configuration_id": configuration,
                        "diagnostic_id": "eaf_low_minus_high_price_mean_throughput",
                        "metric_value": response,
                        "status": "reported",
                        "definition": "mean EAF throughput at/below median price minus above median price",
                    }
                )
    return output


def _guardrail_rows(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    candidates: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    required_validation = {
        "c0_executed_quotas_pass": "production",
        "material_conservation": "material",
        "origin_conservation": "origin",
        "carrier_specific_wag_balance": "WAG",
        "gross_internal_grid_electricity_identity": "electricity",
        "named_ng_component_identity": "named_NG",
        "represented_steam_boundary_identity": "steam",
        "mode_b_explicit_fuel_separation": "Mode_B",
        "residual_energy_excluded_from_future_objective": "no_residual_input",
    }
    output: list[dict[str, Any]] = []
    for (candidate, scenario), artifact in sorted(artifacts.items()):
        validation = {row["check_id"]: row for row in artifact["validation"]}
        for check_id, category in required_validation.items():
            present = check_id in validation
            status = validation.get(check_id, {}).get("status")
            output.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "configuration_id": "contract_scope",
                    "guardrail": category,
                    "check_id": check_id,
                    "status": "pass" if present and status == "pass" else "fail",
                    "maximum_abs_residual": "",
                    "evidence": validation.get(check_id, {}).get("evidence", "missing"),
                }
            )
        for configuration in CONFIGURATIONS:
            physical = [
                row
                for row in artifact["physical"]
                if row["configuration_id"] == configuration
            ]
            cost_rows = [
                row
                for row in artifact["costs"]
                if row["configuration_id"] == configuration
            ]
            summary = _read_csv(
                Path(artifact["directory"]) / "procurement_cost_summary.csv"
            )
            reported_cost = _number(
                next(
                    row["executed_procurement_cost_eur"]
                    for row in summary
                    if row["configuration_id"] == configuration
                )
            )
            for check in basic_ledger_guardrails(
                physical,
                cost_rows,
                configuration=configuration,
                reported_cost_eur=reported_cost,
            ):
                output.append(
                    {
                        "candidate_id": candidate,
                        "scenario_id": scenario,
                        "configuration_id": configuration,
                        "guardrail": check["check_id"],
                        **check,
                    }
                )
        candidate_payload = candidates[candidate]
        if bool(candidate_payload["repair_interface_active"]):
            pricing = validate_unique_named_ng_pricing(
                [
                    row
                    for row in artifact["costs"]
                    if row["configuration_id"] == C0_CONFIGURATION
                ],
                expected_price_eur_per_mwh_lhv=float(
                    candidate_payload["ng_price_eur_per_mwh_lhv"]
                ),
                executed_hours=168,
            )
            for row in pricing:
                output.append(
                    {
                        "candidate_id": candidate,
                        "scenario_id": scenario,
                        "configuration_id": C0_CONFIGURATION,
                        "guardrail": "unique_named_NG_pricing",
                        "check_id": row["check_id"],
                        "status": row["status"],
                        "maximum_abs_residual": "",
                        "evidence": (
                            f"rows={row['row_count']};"
                            f"unique_timestamps={row['unique_timestamp_count']};"
                            f"prices={row['observed_prices']}"
                        ),
                    }
                )
        else:
            special = [
                row for row in artifact["costs"] if row.get("flow_id") in SPECIAL_NG_FLOWS
            ]
            output.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "configuration_id": C0_CONFIGURATION,
                    "guardrail": "unique_named_NG_pricing",
                    "check_id": "baseline_special_bridge_flows_absent",
                    "status": "pass" if not special else "fail",
                    "maximum_abs_residual": len(special),
                    "evidence": "source baseline has no repair interface",
                }
            )
    return output


def _anchor_rows(
    metrics: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    anchors = config["experiment"]["anchors"]
    output: list[dict[str, Any]] = []
    for row in metrics:
        if row["configuration_id"] != C0_CONFIGURATION:
            continue
        gross_twh = float(row["represented_gross_electricity_mwh_y"]) / 1e6
        wag_twh = float(row["actual_wag_only_generator_electricity_mwh_y"]) / 1e6
        named_ng_pj = mwh_lhv_to_pj(
            float(row["total_named_ng_mwh_lhv_y"])
        )
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "scenario_id": row["scenario_id"],
                "period_id": row["period_id"],
                "annual_equivalent_basis": row["annual_equivalent_basis"],
                "gross_electricity_twh_y": gross_twh,
                "gross_anchor_lower_twh_y": anchors[
                    "c0_gross_electricity_twh_y_lower"
                ],
                "gross_anchor_upper_twh_y": anchors[
                    "c0_gross_electricity_twh_y_upper"
                ],
                "gross_anchor_in_range": (
                    float(anchors["c0_gross_electricity_twh_y_lower"])
                    <= gross_twh
                    <= float(anchors["c0_gross_electricity_twh_y_upper"])
                ),
                "actual_wag_only_electricity_twh_y": wag_twh,
                "real_wag_electricity_anchor_twh_y": anchors[
                    "c0_real_wag_generator_electricity_twh_y"
                ],
                "wag_anchor_gap_twh_y": wag_twh
                - float(anchors["c0_real_wag_generator_electricity_twh_y"]),
                "named_ng_pj_y": named_ng_pj,
                "real_named_ng_anchor_pj_y": anchors["c0_real_named_ng_pj_y"],
                "named_ng_anchor_gap_pj_y": named_ng_pj
                - float(anchors["c0_real_named_ng_pj_y"]),
            }
        )
    return output


def _mechanism_rows(
    metrics: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    by_key = {
        (row["candidate_id"], row["scenario_id"], row["configuration_id"]): row
        for row in metrics
    }
    tolerance = float(config["experiment"]["material_switch_tolerance_mwh_y"])
    structural_rows = structural_parameter_invariance_rows(config)
    output: list[dict[str, Any]] = list(structural_rows)
    structural_invariance_pass = all(
        row["status"] == "pass" for row in structural_rows
    )
    gross_monotonic_pass = True
    generator_ng_activation: dict[str, bool] = {}
    for scenario in EXPECTED_SCENARIOS:
        background_rows = [
            by_key[(candidate, scenario, C0_CONFIGURATION)]
            for candidate in (
                "recovery_bg25_ng55",
                "recovery_bg30_ng55",
                "recovery_bg31_ng55",
            )
        ]
        backgrounds = [
            float(row["explicit_background_load_mwh_y"]) for row in background_rows
        ]
        gross = [
            float(row["represented_gross_electricity_mwh_y"])
            for row in background_rows
        ]
        realised_wag_generation = [
            float(row["wag_carrier_generation_mwh_lhv_y"])
            for row in background_rows
        ]
        monotonic = (
            backgrounds[0] < backgrounds[1] < backgrounds[2]
            and gross[0] < gross[1] < gross[2]
        )
        wag_spread = max(realised_wag_generation) - min(realised_wag_generation)
        wag_spread_percent = (
            100.0 * wag_spread / statistics.fmean(realised_wag_generation)
        )
        gross_monotonic_pass = gross_monotonic_pass and monotonic
        output.append(
            {
                "scenario_id": scenario,
                "comparison_id": "bg25_bg30_bg31_monotonic_explicit_gross_boundary",
                "status": "pass" if monotonic else "fail",
                "bg25_value": gross[0],
                "bg30_ng55_value": gross[1],
                "bg31_value": gross[2],
                "bg30_ng30_value": "",
                "difference_ng30_minus_ng55": "",
                "interpretation": (
                    "explicit background and represented gross boundary rise monotonically"
                ),
            }
        )
        output.append(
            {
                "scenario_id": scenario,
                "comparison_id": (
                    "bg25_bg30_bg31_realised_wag_generation_spread_diagnostic"
                ),
                "status": "reported_diagnostic_not_gate",
                "bg25_value": realised_wag_generation[0],
                "bg30_ng55_value": realised_wag_generation[1],
                "bg31_value": realised_wag_generation[2],
                "bg30_ng30_value": "",
                "difference_ng30_minus_ng55": "",
                "spread_mwh_lhv_y": wag_spread,
                "spread_percent_of_mean": wag_spread_percent,
                "interpretation": (
                    "Realised annual-equivalent WAG generation varies through "
                    "endogenous dispatch, not parameter drift; this is diagnostic "
                    "only and is not a physical or promotion gate."
                ),
            }
        )
        high = by_key[("recovery_bg30_ng55", scenario, C0_CONFIGURATION)]
        low = by_key[("recovery_bg30_ng30", scenario, C0_CONFIGURATION)]
        fields = (
            ("flexible_named_ng_mwh_lhv_y", "flexible NG"),
            ("wag_to_flexible_heat_mwh_lhv_y", "WAG to flexible heat"),
            ("wag_to_generators_mwh_lhv_y", "WAG fuel to generators"),
            (
                "actual_wag_only_generator_electricity_mwh_y",
                "actual WAG-only generator electricity",
            ),
            ("ng_generated_electricity_mwh_y", "NG-generated electricity"),
            ("grid_import_mwh_y", "grid import"),
            ("flare_curtailment_mwh_lhv_y", "flare/curtailment"),
            ("no_export_binding_hours", "no-export binding hours"),
        )
        differences: dict[str, float] = {}
        for field, label in fields:
            difference = float(low[field]) - float(high[field])
            differences[field] = difference
            output.append(
                {
                    "scenario_id": scenario,
                    "comparison_id": f"ng30_vs_ng55::{field}",
                    "status": "reported",
                    "bg25_value": "",
                    "bg30_ng55_value": high[field],
                    "bg31_value": "",
                    "bg30_ng30_value": low[field],
                    "difference_ng30_minus_ng55": difference,
                    "interpretation": label,
                }
            )
        generator_ng_activation[scenario] = (
            float(low["ng_generated_electricity_mwh_y"])
            - float(high["ng_generated_electricity_mwh_y"])
            > tolerance
        )
    output.append(
        {
            "scenario_id": "cross_scenario_classification",
            "comparison_id": "allocation_location_tiebreak_interpretation",
            "status": "reported_non_identifiable",
            "bg25_value": "",
            "bg30_ng55_value": "",
            "bg31_value": "",
            "bg30_ng30_value": "",
            "difference_ng30_minus_ng55": "",
            "interpretation": TIE_BREAK_INTERPRETATION,
        }
    )
    volatile_activation = all(
        generator_ng_activation[scenario]
        for scenario in (
            "volatile_negative_governed_y_pred",
            "volatile_negative_oracle_y_true",
        )
    )
    calm_activation = generator_ng_activation["calm_price_insensitive"]
    if not structural_invariance_pass:
        decision = "structural_parameter_invariance_failed_no_promotion"
    elif not gross_monotonic_pass:
        decision = "explicit_gross_boundary_monotonic_gate_failed_no_promotion"
    elif volatile_activation and not calm_activation:
        decision = FINAL_DECISION
    else:
        decision = (
            "lower_ng_generator_activation_pattern_not_observed_"
            "stop_no_second_search"
        )
    return output, decision


def _solver_rows(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {"candidate_id": candidate, "scenario_id": scenario, **row}
        for (candidate, scenario), artifact in sorted(artifacts.items())
        for row in artifact["models"]
    ]


def _expected_case_overrides(
    *,
    case_id: str,
    forecast_root: Path,
    scenario: Mapping[str, Any],
    periods: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": case_id,
        "lineage_role": "bounded_mechanism_experiment_case_cache",
        "forecast_run_root": str(forecast_root),
        **_scenario_overrides(scenario, periods),
        **candidate_overrides(config, candidate),
    }


def _manifest_paths_match(manifest: Mapping[str, Any]) -> bool:
    fingerprint_rows = list(manifest.get("active_model_input_files", []))
    fingerprint_rows.extend(manifest.get("direct_source_evidence_files", []))
    anchor_path = manifest.get("anchor_register")
    anchor_sha = manifest.get("anchor_register_sha256")
    if anchor_path and anchor_sha:
        fingerprint_rows.append({"path": anchor_path, "sha256": anchor_sha})
    if not fingerprint_rows:
        return False
    for row in fingerprint_rows:
        path = REPO_ROOT / str(row.get("path", ""))
        if (
            not path.is_file()
            or not row.get("sha256")
            or _sha256(path) != row["sha256"]
        ):
            return False
    return True


def _mechanism_case_ready(
    directory: Path,
    *,
    expected_overrides: Mapping[str, Any],
    physical_config_sha256: str,
    git_head: str,
) -> bool:
    """Fail-closed cache identity check using only evidence persisted per case."""

    required = (
        "config_resolved.yaml",
        "rolling_model_metrics.csv",
        "input_manifest.json",
        "code_version.json",
    )
    if not _case_ready(directory) or not all(
        (directory / name).is_file() for name in required
    ):
        return False
    try:
        resolved_path = directory / "config_resolved.yaml"
        resolved = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
        observed_overrides = resolved["scenario_overrides_applied"]
        manifest = json.loads(
            (directory / "input_manifest.json").read_text(encoding="utf-8")
        )
        code_version = json.loads(
            (directory / "code_version.json").read_text(encoding="utf-8")
        )
        models = _read_csv(directory / "rolling_model_metrics.csv")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError):
        return False
    expected_model_keys = {
        (configuration, str(replan))
        for configuration in CONFIGURATIONS
        for replan in range(7)
    }
    observed_model_keys = {
        (row.get("configuration_id"), row.get("replan_index")) for row in models
    }
    return (
        _mapping_sha256(observed_overrides)
        == _mapping_sha256(expected_overrides)
        and manifest.get("config_sha256") == physical_config_sha256
        and manifest.get("resolved_config_sha256")
        == _resolved_config_sha256(resolved)
        and code_version.get("git_commit") == git_head
        and len(models) == 14
        and observed_model_keys == expected_model_keys
        and all(row.get("termination_condition") == "optimal" for row in models)
        and _manifest_paths_match(manifest)
    )


def solver_invoked_this_invocation(
    statuses: Sequence[Mapping[str, Any]],
) -> bool:
    return any(row.get("source") == "new_solve" for row in statuses)


def prepare_mechanism_experiment(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    forecast_run_root: str | Path,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = load_mechanism_config(config_file)
    validate_mechanism_config(config)
    experiment = config["experiment"]
    output = (REPO_ROOT / config["output_root"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    matrix = frozen_scenario_matrix(config)
    _write_csv(output / "scenario_matrix.csv", matrix)
    physical_config = (REPO_ROOT / experiment["physical_config"]).resolve()
    forecast_contract_path = (REPO_ROOT / experiment["forecast_contract"]).resolve()
    period_contract = (REPO_ROOT / experiment["period_contract"]).resolve()
    forecast_contract = load_dplus4_source_contract(forecast_contract_path)
    forecast_files = _resolve_dplus4_source_files(
        forecast_contract, Path(forecast_run_root).resolve()
    )
    repository_files = (
        config_file,
        physical_config,
        forecast_contract_path,
        period_contract,
        Path(__file__).resolve(),
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_c0_real_anchor_mechanism_experiment.py",
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT
        / "data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_future_cost_boundary_contract.csv",
        REPO_ROOT
        / "data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_external_supply_costs.csv",
    )
    _write_json(
        output / "input_manifest.json",
        {
            "run_id": config["run_id"],
            "candidate_count": 5,
            "scenario_count": 3,
            "rolling_case_count": 15,
            "expected_model_count": 210,
            "held_out_periods_used": False,
            "forecast_run_root_persisted": False,
            "forecast_source_run_id": forecast_contract["source_run_id"],
            "repository_files": [
                {
                    "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "sha256": _sha256(path),
                }
                for path in repository_files
            ],
            "forecast_source_files": [
                {
                    "logical_name": key,
                    "relative_path": forecast_contract["source_run_relative_files"][key],
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
                for key, path in sorted(forecast_files.items())
            ],
            "current_experiment_cache_identity_contract": {
                "verified": (
                    "exact scenario overrides; physical config SHA-256; resolved "
                    "config SHA-256; current source-input file SHA-256 values; Git "
                    "commit; and 14 exact optimal configuration/replan model keys"
                ),
                "per_case_dirty_source_fingerprint_status": (
                    "unavailable_not_claimed"
                ),
            },
        },
    )
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    _write_json(
        output / "code_version.json",
        {"git_commit": _git_head(), "working_tree_fingerprinted": True},
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": "minimal",
            "status": "prepared",
            "git_eligible": False,
        },
    )
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": config["run_id"],
            "status": "prepared_not_started",
            "rolling_case_count_frozen": 15,
            "held_out_periods_used": False,
            "solver_invoked": False,
        },
    )
    (output / "README.md").write_text(
        "# C0 real-anchor mechanism experiment\n\n"
        "Prepared five frozen candidates over the two existing DEVELOPMENT "
        "validation weeks. Annual-equivalent values are representative-week "
        "scalings, not empirical annual results. The experiment changes only "
        "the authorized electricity-boundary background and governed named-NG "
        "price scenario; physical WAG/NG parameters, routes, operating rules "
        "and the no-export boundary remain fixed.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a bounded deterministic development-mechanism experiment, not calibration or a digital twin.\n"
        "- The two validation weeks are not an annual backtest; all annual equivalents are labelled accordingly.\n"
        "- `y_true` is used only by the explicitly labelled oracle.\n"
        "- Gross-boundary fit alone cannot promote a candidate.\n"
        "- Realised annual-equivalent WAG-generation spreads are diagnostic endogenous-dispatch outcomes, not parameter drift or a physical/promotion gate: calm 17,213.386 MWh-LHV/y (0.10785%), governed y_pred 19,420.107 MWh-LHV/y (0.12187%), and oracle 2,965.919 MWh-LHV/y (0.01859%).\n"
        "- The builder tie-break penalizes flexible-heat NG but not generator NG; zero flexible NG is non-identifiable and does not prove absence of substitution.\n"
        "- The source-driven baseline remains central; repair candidates are nonpromoted, held-out weeks are untouched, and no second search is authorized.\n"
        "- Export, CO2 pricing, BF changes, residual plugs, bidding, settlement, stochasticity, CVaR and mFRR remain excluded.\n",
        encoding="utf-8",
    )
    return {"output_root": str(output), "matrix": matrix, "config": config}


def run_mechanism_experiment(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    forecast_run_root: str | Path,
    scratch_root: str | Path | None = None,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    preparation = prepare_mechanism_experiment(
        config_path, forecast_run_root=forecast_run_root
    )
    config = preparation["config"]
    experiment = config["experiment"]
    output = Path(preparation["output_root"])
    matrix = preparation["matrix"]
    physical_config = (REPO_ROOT / experiment["physical_config"]).resolve()
    physical_config_sha256 = _sha256(physical_config)
    current_git_head = _git_head()
    scratch = (
        Path(scratch_root).resolve()
        if scratch_root
        else (REPO_ROOT / experiment["scratch_root"]).resolve()
    )
    scratch.mkdir(parents=True, exist_ok=True)
    forecast_root = Path(forecast_run_root).resolve()
    periods = {row["period_id"]: row for row in experiment["development_periods"]}
    candidates = {row["candidate_id"]: row for row in experiment["candidates"]}
    scenarios = {row["scenario_id"]: row for row in experiment["scenarios"]}
    statuses: list[dict[str, Any]] = []
    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(matrix, start=1):
        candidate_id = row["candidate_id"]
        scenario_id = row["scenario_id"]
        case_id = row["case_id"]
        directory = scratch / case_id
        overrides = _expected_case_overrides(
            case_id=case_id,
            forecast_root=forecast_root,
            scenario=scenarios[scenario_id],
            periods=periods,
            config=config,
            candidate=candidates[candidate_id],
        )
        cached = _mechanism_case_ready(
            directory,
            expected_overrides=overrides,
            physical_config_sha256=physical_config_sha256,
            git_head=current_git_head,
        )
        source = "reused_current_experiment_cache" if cached else "new_solve"
        status = "pass"
        error = ""
        case_started = time.perf_counter()
        if not cached and not aggregate_only:
            if directory.exists():
                raise MechanismExperimentError(
                    f"Incomplete existing case preserved for inspection: {directory}"
                )
            try:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                status = "fail"
                error = f"{type(exc).__name__}: {exc}"
            cached = _mechanism_case_ready(
                directory,
                expected_overrides=overrides,
                physical_config_sha256=physical_config_sha256,
                git_head=current_git_head,
            )
            if not cached:
                status = "fail"
                error = error or "p_af returned without a complete passing case"
        elif not cached:
            status = "fail"
            source = "aggregate_only_cache_check"
            error = "complete case cache missing"
        statuses.append(
            {
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
                "period_id": row["period_id"],
                "case_id": case_id,
                "status": status,
                "source": source,
                "runtime_seconds_this_invocation": time.perf_counter() - case_started,
                "error": error,
            }
        )
        _write_csv(output / "case_status.csv", statuses)
        _write_json(
            output / "checkpoint_state.json",
            {
                "run_id": config["run_id"],
                "status": (
                    "in_progress"
                    if status == "pass" and index < len(matrix)
                    else status
                ),
                "completed_case_count": sum(
                    item["status"] == "pass" for item in statuses
                ),
                "failed_case_count": sum(
                    item["status"] != "pass" for item in statuses
                ),
                "latest_case_id": case_id,
                "held_out_periods_used": False,
                "solver_invoked": solver_invoked_this_invocation(statuses),
            },
        )
        print(
            f"[{index}/{len(matrix)}] {case_id}: {status} ({source})",
            flush=True,
        )
        if status != "pass":
            raise MechanismExperimentError(
                f"Mechanism experiment stopped on {case_id}: {error}"
            )
        artifact = _artifact(directory)
        artifact["physical"] = _read_csv(
            directory / "annual_physical_boundary_ledger.csv"
        )
        artifact["directory"] = str(directory)
        artifacts[(candidate_id, scenario_id)] = artifact

    metrics = _metric_rows(
        artifacts, matrix, experiment["annual_equivalent_label"]
    )
    behavior = _behavior_rows(artifacts)
    guardrails = _guardrail_rows(artifacts, candidates)
    solver = _solver_rows(artifacts)
    anchors = _anchor_rows(metrics, config)
    mechanism, decision = _mechanism_rows(metrics, config)
    if len(solver) != int(experiment["expected_model_count"]):
        raise MechanismExperimentError(
            f"Expected 210 solver records, found {len(solver)}."
        )
    nonoptimal = [
        row for row in solver if row.get("termination_condition") != "optimal"
    ]
    failures = [row for row in guardrails if row["status"] != "pass"]
    if nonoptimal or failures:
        raise MechanismExperimentError(
            f"Acceptance failed: nonoptimal={len(nonoptimal)}, guardrails={len(failures)}."
        )
    _write_csv(output / "candidate_scenario_metrics.csv", metrics)
    _write_csv(output / "behavioral_diagnostics.csv", behavior)
    _write_csv(output / "physical_guardrails.csv", guardrails)
    _write_csv(output / "solver_runtime_metrics.csv", solver)
    _write_csv(output / "anchor_mechanism_comparison.csv", anchors)
    _write_csv(output / "mechanism_comparison.csv", mechanism)
    summary = {
        "run_id": config["run_id"],
        "status": "pass",
        "decision": decision,
        "candidate_count": 5,
        "scenario_count": 3,
        "development_period_count": 2,
        "rolling_case_count": len(artifacts),
        "model_count": len(solver),
        "optimal_model_count": len(solver),
        "physical_guardrail_failure_count": 0,
        "held_out_periods_used": False,
        "solver_invoked_this_invocation": solver_invoked_this_invocation(statuses),
        "current_invocation_new_solve_case_count": sum(
            row["source"] == "new_solve" for row in statuses
        ),
        "current_invocation_reused_current_experiment_cache_count": sum(
            row["source"] == "reused_current_experiment_cache"
            for row in statuses
        ),
        "experiment_solver_result_case_count": len(artifacts),
        "checkpoint4_case_reuse_count": 0,
        "wall_runtime_seconds_this_invocation": time.perf_counter() - started,
        "solver_runtime_seconds_sum": sum(
            _number(row.get("runtime_seconds")) for row in solver
        ),
        "maximum_variable_count": max(int(float(row["variable_count"])) for row in solver),
        "maximum_binary_count": max(int(float(row["binary_count"])) for row in solver),
        "maximum_constraint_count": max(
            int(float(row["constraint_count"])) for row in solver
        ),
        "candidate_promotion_status": "not_promoted_development_sensitivity_only",
        "second_search_authorized": False,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": config["run_id"],
            "status": "complete",
            "decision": decision,
            "rolling_case_count": len(artifacts),
            "model_count": len(solver),
            "held_out_periods_used": False,
            "candidate_promotion_status": "not_promoted",
            "second_search_authorized": False,
            "solver_invoked_this_invocation": solver_invoked_this_invocation(
                statuses
            ),
            "reused_current_experiment_cache_count": sum(
                row["source"] == "reused_current_experiment_cache"
                for row in statuses
            ),
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": "minimal",
            "status": "pass",
            "decision": decision,
            "git_eligible": False,
        },
    )
    (output / "README.md").write_text(
        "# C0 real-anchor mechanism experiment\n\n"
        f"Decision: `{decision}`.\n\n"
        "Five frozen candidates were evaluated over the two existing DEVELOPMENT "
        "validation weeks using a flat price-insensitive benchmark, governed "
        "`y_pred`, and a separately labelled `y_true` oracle. All solves and "
        "physical/accounting guardrails pass. Annual-equivalent values are "
        "representative-development-week scalings, not empirical annual results. "
        "NG-generated electricity is reported separately and never counted as "
        "WAG electricity. Lower NG prices activate named generator NG in the two "
        "volatile cases, while the calm case does not. The builder tie-break "
        "penalizes flexible-heat NG but not generator NG, so zero flexible NG is "
        "non-identifiable rather than proof of no substitution. Realised WAG "
        "generation spreads are diagnostic endogenous-dispatch results, not "
        "parameter drift. Structural invariance is established from the frozen "
        "candidate inputs. Gross-boundary fit alone does not promote a candidate; "
        "the source-driven baseline remains central, all repair candidates remain "
        "nonpromoted, held-out periods remain untouched, and no second parameter "
        "search is authorized by this run.\n",
        encoding="utf-8",
    )
    return summary
