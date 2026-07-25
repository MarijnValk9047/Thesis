"""Checkpoint 6 held-out representative-week orchestration and reporting.

Every optimisation delegates to the accepted p_af rolling runner. Preparation
and cache-only aggregation never call a solver.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any, Iterable, Mapping

import yaml

from .c5_source_emulation_evaluation import (
    STRATEGIES,
    _aggregate_summary_fields,
    _case_id,
    _case_ready,
    _guardrail_rows,
    _period_summary_rows,
    _solver_rows,
    _strategy_comparison_rows,
    _strategy_overrides,
    _terminal_inventory_rows,
    _weighted_rows,
)
from .c5_source_emulation_validation import (
    _select_and_weight,
    build_candidate_weeks,
)
from .s4_4c5p_bf_price_series_interface import load_dplus4_source_contract
from .s4_4c5p_c0_real_anchor_checkpoint4_behavior import (
    candidate_overrides as checkpoint4_candidate_overrides,
)
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs"
    / "steel_c5_real_anchor_energy_recovery_checkpoint6.yaml"
)
OUTPUT_LABEL = "weighted_annual_equivalent_from_representative_held_out_weeks"
EXPECTED_CANDIDATES = ("source_driven_baseline", "recovery_bg25")
EXPECTED_PERIODS = (
    "test_2025-09-08",
    "test_2024-10-21",
    "test_2024-12-09",
    "test_2025-01-13",
    "test_2024-11-04",
    "test_2025-05-12",
    "test_2025-01-06",
    "test_2025-03-03",
)
EXPECTED_WEIGHTS = (
    0.130434782609,
    0.369565217391,
    0.021739130435,
    0.065217391304,
    0.021739130435,
    0.173913043478,
    0.152173913043,
    0.065217391304,
)
SUMMARY_FIELDS = (
    "final_product_t_y",
    "bof_liquid_steel_t_y",
    "eaf_liquid_steel_t_y",
    "hsm_output_t_y",
    "dsp_output_t_y",
    "slab_import_t_y",
    "drp_dri_output_t_y",
    "gross_electricity_mwh_y",
    "internal_wag_electricity_mwh_y",
    "grid_import_mwh_y",
    "named_ng_mwh_lhv_y",
    "wag_generation_mwh_lhv_y",
    "wag_mandatory_sinks_mwh_lhv_y",
    "wag_generator_sinks_mwh_lhv_y",
    "wag_flare_mwh_lhv_y",
    "steam_15bar_t_y",
    "mode_b_explicit_fuel_co2_t_y",
    "objective_procurement_cost_eur_y",
    "forecast_evaluated_procurement_cost_eur_y",
    "realised_procurement_cost_eur_y",
)


class Checkpoint6Error(RuntimeError):
    """Raised when the frozen Checkpoint 6 contract is violated."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise Checkpoint6Error(f"Refusing to write empty output: {path.name}")
    fields: list[str] = []
    for row in materialised:
        for field in row:
            if field not in fields:
                fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialised)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _git_head() -> str:
    head = REPO_ROOT / ".git"
    if not head.exists():
        return "unknown"
    import subprocess

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def load_checkpoint6_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))


def validate_checkpoint6_config(config: Mapping[str, Any]) -> None:
    if config.get("mode") != "c0_real_anchor_energy_recovery_checkpoint6":
        raise Checkpoint6Error("Unexpected Checkpoint 6 execution mode.")
    if config.get("output_policy") != "minimal":
        raise Checkpoint6Error("Checkpoint 6 requires output_policy=minimal.")
    if config.get("annualisation_label") != OUTPUT_LABEL:
        raise Checkpoint6Error("Checkpoint 6 annual-equivalent label changed.")
    checkpoint = config["checkpoint_6"]
    if (
        int(checkpoint["expected_candidate_week_count"]) != 46
        or int(checkpoint["selected_period_count"]) != 8
        or int(checkpoint["expected_rolling_case_count"]) != 48
        or int(checkpoint["expected_model_count"]) != 672
    ):
        raise Checkpoint6Error("Frozen Checkpoint 6 matrix counts changed.")
    if tuple(row["candidate_id"] for row in checkpoint["candidates"]) != (
        EXPECTED_CANDIDATES
    ):
        raise Checkpoint6Error("Frozen candidate pair changed.")
    if tuple(row["strategy_id"] for row in checkpoint["strategies"]) != STRATEGIES:
        raise Checkpoint6Error("Frozen strategy definitions changed.")
    for strategy in checkpoint["strategies"]:
        oracle = bool(strategy["perfect_foresight_oracle"])
        if (strategy["price_field"] == "y_true") != oracle:
            raise Checkpoint6Error("y_true is permitted only for oracle_y_true.")
    frozen = checkpoint["frozen_test_selection"]
    if tuple(row["period_id"] for row in frozen) != EXPECTED_PERIODS:
        raise Checkpoint6Error("Frozen eight-period order changed.")
    if any(
        abs(float(row["split_weight"]) - expected) > 5e-13
        for row, expected in zip(frozen, EXPECTED_WEIGHTS)
    ):
        raise Checkpoint6Error("Frozen eight-period weights changed.")
    if abs(sum(float(row["split_weight"]) for row in frozen) - 1.0) > 1e-9:
        raise Checkpoint6Error("Frozen TEST weights must sum to one.")
    recovery = checkpoint["candidates"][1]
    interface = checkpoint["recovery_interface"][
        "c0_aggregate_generator_technical_interface"
    ]
    bridge = checkpoint["recovery_interface"]["c0_full_site_energy_bridge"]
    if (
        recovery["candidate_classification"] != "emulation_sensitivity_only"
        or float(recovery["explicit_background_twh_y"]) != 0.7925
        or abs(float(recovery["explicit_background_mwh_h"]) - 90.46803652968036)
        > 1e-12
        or float(interface["electricity_efficiency"]) != 0.345
        or float(interface["total_fuel_volume_cap_nm3_h"]) != 900000.0
        or float(interface["electrical_capacity_mw"]) != 770.0
        or float(bridge["inferred_low_case_full_site_ng_floor_pj_y"]) != 8.005
        or float(bridge["flexible_other_site_heat_service_envelope_pj_y"]) != 3.07
        or interface["export_allowed"] is not False
    ):
        raise Checkpoint6Error("Reviewed recovery_bg25 definition changed.")
    if checkpoint["historical_4plus4_contract_overwrite_allowed"] is not False:
        raise Checkpoint6Error("Historical representative contract is immutable.")


def derive_frozen_test_selection(
    *,
    forecast_run_root: str | Path,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Reproduce the independently approved TEST-only selection exactly."""

    checkpoint = config["checkpoint_6"]
    candidates = build_candidate_weeks(
        forecast_run_root=Path(forecast_run_root).resolve(),
        dataset_split="test",
        contract=load_dplus4_source_contract(),
    )
    if len(candidates) != 46:
        raise Checkpoint6Error(f"Expected 46 eligible TEST weeks, found {len(candidates)}.")
    selected, _ = _select_and_weight(
        candidates,
        target_count=8,
        feature_fields=list(checkpoint["selection_feature_fields"]),
    )
    if tuple(row["period_id"] for row in selected) != EXPECTED_PERIODS:
        raise Checkpoint6Error("Reproduced TEST selection differs from approval.")
    if any(
        abs(float(row["split_weight"]) - expected) > 5e-13
        for row, expected in zip(selected, EXPECTED_WEIGHTS)
    ):
        raise Checkpoint6Error("Reproduced TEST weights differ from approval.")
    output: list[dict[str, Any]] = []
    for row in selected:
        executed_hours = int(row["execution_hours"])
        output.append(
            {
                **row,
                "selection_contract_version": (
                    "steel_c5_checkpoint6_independent_test_eight_week_v1"
                ),
                "annualisation_label": OUTPUT_LABEL,
                "selection_scope": "independently_approved_test_only",
                "historical_4plus4_contract_unchanged": True,
                "duration_annualisation_factor": round(
                    8760.0 / executed_hours, 12
                ),
                "duration_aware_fixed_quantity_policy": (
                    "sum_exact_executed_hours_then_multiply_8760_over_"
                    "executed_hours_before_split_weight"
                ),
                "annual_backtest": False,
            }
        )
    return output


def duration_aware_annual_equivalent(
    period_total: float, executed_hours: int
) -> float:
    if executed_hours <= 0:
        raise Checkpoint6Error("Executed hours must be positive.")
    return float(period_total) * 8760.0 / int(executed_hours)


def _cp4_candidate_overrides(
    config: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    compatible = {
        "checkpoint_4": {
            "recovery_interface": config["checkpoint_6"]["recovery_interface"]
        }
    }
    return checkpoint4_candidate_overrides(compatible, candidate)


def _cache_identity_payload(
    *,
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    period: Mapping[str, Any],
    strategy: str,
) -> dict[str, Any]:
    """Return the deterministic frozen identity of one candidate-period-strategy case."""

    expected_overrides = {
        **_strategy_overrides(period, strategy),
        **_cp4_candidate_overrides(config, candidate),
        "lineage_role": "checkpoint6_held_out_case_cache",
    }
    return {
        "contract_version": "steel_c5_checkpoint6_case_cache_identity_v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_classification": candidate["candidate_classification"],
        "period_id": period["period_id"],
        "dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "execution_hours": int(period["execution_hours"]),
        "split_weight": float(period["split_weight"]),
        "strategy": strategy,
        "price_field": "y_true" if strategy == "oracle_y_true" else "y_pred",
        "flat_price_eur_per_mwh": 80.0 if strategy == "price_insensitive" else None,
        "perfect_foresight_oracle": strategy == "oracle_y_true",
        "expected_scenario_overrides": expected_overrides,
    }


def _expected_case_overrides(
    *,
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    period: Mapping[str, Any],
    strategy: str,
    forecast_root: Path,
) -> dict[str, Any]:
    identity = _cache_identity_payload(
        config=config,
        candidate=candidate,
        period=period,
        strategy=strategy,
    )
    fingerprint = _mapping_sha256(identity)
    return {
        **identity["expected_scenario_overrides"],
        "forecast_run_root": str(forecast_root.resolve()),
        "checkpoint6_cache_contract": {
            "contract_version": identity["contract_version"],
            "scenario_override_sha256": fingerprint,
            "candidate_id": identity["candidate_id"],
            "candidate_classification": identity["candidate_classification"],
            "period_id": identity["period_id"],
            "strategy": identity["strategy"],
        },
    }


def _checkpoint6_case_ready(
    directory: Path,
    *,
    expected_overrides: Mapping[str, Any],
    expected_scenario_override_sha256: str,
) -> bool:
    """Fail closed unless a passing cache is the exact expected frozen case."""

    try:
        if not _case_ready(directory):
            return False
        resolved_path = directory / "config_resolved.yaml"
        metrics_path = directory / "rolling_model_metrics.csv"
        if not resolved_path.is_file() or not metrics_path.is_file():
            return False
        resolved = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
        persisted = resolved["scenario_overrides_applied"]
        if not isinstance(persisted, Mapping):
            return False
        if _mapping_sha256(persisted) != _mapping_sha256(expected_overrides):
            return False
        contract = persisted.get("checkpoint6_cache_contract")
        if not isinstance(contract, Mapping):
            return False
        if contract.get("scenario_override_sha256") != (
            expected_scenario_override_sha256
        ):
            return False
        metrics = _read_csv(metrics_path)
    except (
        OSError,
        csv.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        yaml.YAMLError,
    ):
        return False
    if len(metrics) != 14:
        return False
    expected_model_keys = {
        (str(replan), configuration)
        for replan in range(7)
        for configuration in CONFIGURATIONS
    }
    actual_model_keys = {
        (str(row.get("replan_index", "")), row.get("configuration_id", ""))
        for row in metrics
    }
    return (
        actual_model_keys == expected_model_keys
        and all(row.get("termination_condition") == "optimal" for row in metrics)
    )


def frozen_scenario_matrix(
    config: Mapping[str, Any], periods: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in config["checkpoint_6"]["candidates"]:
        for period in periods:
            for strategy in STRATEGIES:
                identity = _cache_identity_payload(
                    config=config,
                    candidate=candidate,
                    period=period,
                    strategy=strategy,
                )
                rows.append(
                    {
                        "case_id": _case_id(period["period_id"], strategy),
                        "candidate_id": candidate["candidate_id"],
                        "candidate_classification": candidate[
                            "candidate_classification"
                        ],
                        "period_id": period["period_id"],
                        "dataset_split": "test",
                        "executed_hours": period["execution_hours"],
                        "split_weight": period["split_weight"],
                        "strategy": strategy,
                        "price_field": (
                            "y_true" if strategy == "oracle_y_true" else "y_pred"
                        ),
                        "perfect_foresight_oracle": strategy == "oracle_y_true",
                        "annualisation_label": OUTPUT_LABEL,
                        "scenario_override_sha256": _mapping_sha256(identity),
                    }
                )
    if len(rows) != 48:
        raise Checkpoint6Error("Frozen scenario matrix must contain 48 cases.")
    return rows


def _preparation_readme() -> str:
    return (
        "# C0 real-anchor energy-recovery Checkpoint 6\n\n"
        "Status: `checkpoint6_prepared_solver_not_invoked`.\n\n"
        "This distinct TEST-only snapshot freezes eight independently approved "
        "representative held-out weeks, two reviewed candidates and three strategies "
        "(48 rolling cases). The historical 4+4 representative contract is unchanged. "
        f"Every aggregate result must be labelled `{OUTPUT_LABEL}`; this is not an "
        "annual backtest. Fixed/background quantities use exact executed-hour "
        "duration before 8760-hour annual-equivalent scaling, including the 169-hour "
        "2024-10-21 DST week.\n\n"
        "`recovery_bg25` remains `emulation_sensitivity_only` and nonpromoted. "
        "`y_true` is isolated to the labelled rolling oracle. No exact Tata twin, "
        "Athanasiadis NG thermal-substitution, Badarinath BF relationship or VN25 "
        "outage validation claim is permitted.\n"
    )


def prepare_checkpoint6(
    *,
    forecast_run_root: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Persist the frozen Checkpoint 6 contract without invoking a solver."""

    config_file = Path(config_path).resolve()
    config = load_checkpoint6_config(config_file)
    validate_checkpoint6_config(config)
    periods = derive_frozen_test_selection(
        forecast_run_root=forecast_run_root, config=config
    )
    matrix = frozen_scenario_matrix(config, periods)
    output = (REPO_ROOT / config["output_root"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "held_out_eight_week_selection_contract.csv", periods)
    _write_csv(output / "strategy_definitions.csv", config["checkpoint_6"]["strategies"])
    _write_csv(output / "scenario_matrix.csv", matrix)
    _write_csv(
        output / "scenario_input_manifest.csv",
        [
            {
                **row,
                "execution_status": "frozen_not_started",
                "solver_invoked": False,
            }
            for row in matrix
        ],
    )
    repository_files = [
        config_file,
        Path(__file__).resolve(),
        REPO_ROOT / config["checkpoint_6"]["physical_config"],
        REPO_ROOT / config["checkpoint_6"]["checkpoint4_config"],
        REPO_ROOT / config["checkpoint_6"]["checkpoint4_state"],
        REPO_ROOT / config["checkpoint_6"]["checkpoint3_scorecard"],
        REPO_ROOT / config["checkpoint_6"]["historical_representative_contract"],
    ]
    _write_json(
        output / "input_manifest.json",
        {
            "run_id": config["run_id"],
            "checkpoint": 6,
            "forecast_run_root_persisted": False,
            "selection_method_reused": (
                "c5_source_emulation_validation._select_and_weight"
            ),
            "eligible_test_week_count": 46,
            "selected_test_week_count": 8,
            "candidate_count": 2,
            "strategy_count": 3,
            "rolling_case_count": 48,
            "expected_model_count": 672,
            "annualisation_label": OUTPUT_LABEL,
            "solver_invoked_by_preparation": False,
            "historical_4plus4_contract_overwritten": False,
            "repository_files": [
                {
                    "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "sha256": _sha256(path),
                }
                for path in repository_files
            ],
        },
    )
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    _write_json(
        output / "code_version.json",
        {
            "git_commit": _git_head(),
            "required_git_commit": "5e25ec0c7c356d1b8773b0a25271f9b60bbdf057",
            "required_branch": "feature/steel-next-layer",
            "checkpoint": 6,
        },
    )
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": config["run_id"],
            "status": "checkpoint6_prepared_solver_not_invoked",
            "solver_invoked": False,
            "rolling_case_count_frozen": 48,
            "held_out_test_period_count": 8,
            "historical_4plus4_contract_overwritten": False,
            "recovery_candidate_classification": "emulation_sensitivity_only",
            "annualisation_label": OUTPUT_LABEL,
            "next_action": "root_executes_checkpoint6_with_accepted_p_af_runner",
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": "minimal",
            "status": "checkpoint6_prepared_solver_not_invoked",
            "git_eligible": False,
        },
    )
    (output / "README.md").write_text(_preparation_readme(), encoding="utf-8")
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        f"- All aggregates are `{OUTPUT_LABEL}`; they are not an annual backtest.\n"
        "- Eight TEST weeks are representative held-out support, not full-year coverage.\n"
        "- `y_true` is an optimizer input only for the explicitly labelled rolling oracle.\n"
        "- Whole-period cost differences are arithmetic-only without a terminal-inventory value bridge.\n"
        "- Recovery remains an emulation sensitivity and is not promoted.\n"
        "- Residual electricity and NG remain reporting-only and excluded from dispatch/cost.\n",
        encoding="utf-8",
    )
    return {
        "status": "checkpoint6_prepared_solver_not_invoked",
        "selected_period_count": len(periods),
        "rolling_case_count": len(matrix),
        "solver_invoked": False,
        "output_root": str(output),
    }


def _weighted_summary_rows(
    source_rows: list[dict[str, Any]], candidate: Mapping[str, Any]
) -> list[dict[str, Any]]:
    aggregated = _aggregate_summary_fields(source_rows, list(SUMMARY_FIELDS))
    output: list[dict[str, Any]] = []
    for row in aggregated:
        final_product = float(row["final_product_t_y"])
        grid = float(row["grid_import_mwh_y"])
        realised = float(row["realised_procurement_cost_eur_y"])
        grid_cost_proxy = sum(
            float(source["split_weight"])
            * float(source["average_realised_electricity_price_paid_eur_per_mwh"])
            * float(source["grid_import_mwh_y"])
            for source in source_rows
            if source["strategy"] == row["strategy"]
            and source["configuration_id"] == row["configuration_id"]
            and source["average_realised_electricity_price_paid_eur_per_mwh"]
            not in {"", None}
        )
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_classification": candidate["candidate_classification"],
                **row,
                "annualisation_label": OUTPUT_LABEL,
                "represented_procurement_cost_eur_per_t": (
                    realised / final_product if final_product else ""
                ),
                "average_realised_electricity_price_paid_eur_per_mwh": (
                    grid_cost_proxy / grid if grid else ""
                ),
                "annual_backtest": False,
                "candidate_promoted": False,
            }
        )
    return output


def _per_ton_rows(weighted_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numerators = {
        field: field
        for field in SUMMARY_FIELDS
        if field.endswith("_t_y")
        or field.endswith("_mwh_y")
        or field.endswith("_mwh_lhv_y")
        or field.endswith("_co2_t_y")
        or field.endswith("_cost_eur_y")
    }
    output: list[dict[str, Any]] = []
    for row in weighted_summary:
        denominator = float(row["final_product_t_y"])
        for metric, field in numerators.items():
            output.append(
                {
                    "candidate_id": row["candidate_id"],
                    "candidate_classification": row["candidate_classification"],
                    "strategy": row["strategy"],
                    "configuration_id": row["configuration_id"],
                    "metric": metric,
                    "weighted_annual_equivalent_value": row[field],
                    "per_t_final_product": (
                        float(row[field]) / denominator if denominator else ""
                    ),
                    "denominator": "weighted_site_final_product_t",
                    "annualisation_label": OUTPUT_LABEL,
                }
            )
    return output


def _summary_dispersion_rows(
    source_rows: list[dict[str, Any]], candidate: Mapping[str, Any]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        for configuration in CONFIGURATIONS:
            selected = [
                row
                for row in source_rows
                if row["strategy"] == strategy
                and row["configuration_id"] == configuration
            ]
            for field in SUMMARY_FIELDS:
                values = [
                    (float(row["split_weight"]), float(row[field]))
                    for row in selected
                ]
                mean = sum(weight * value for weight, value in values)
                std = math.sqrt(
                    sum(weight * (value - mean) ** 2 for weight, value in values)
                )
                output.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "candidate_classification": candidate[
                            "candidate_classification"
                        ],
                        "strategy": strategy,
                        "configuration_id": configuration,
                        "metric": field,
                        "period_count": len(values),
                        "minimum": min(value for _, value in values),
                        "maximum": max(value for _, value in values),
                        "weighted_mean": mean,
                        "weighted_standard_deviation": std,
                        "annualisation_label": OUTPUT_LABEL,
                    }
                )
    return output


def _anchor_comparison_rows(
    weighted_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lookup = {
        (row["candidate_id"], row["strategy"], row["configuration_id"]): row
        for row in weighted_summary
    }
    baseline_c0 = lookup[
        ("source_driven_baseline", "price_insensitive", C0_CONFIGURATION)
    ]
    recovery_c0 = lookup[("recovery_bg25", "price_insensitive", C0_CONFIGURATION)]
    baseline_c1 = lookup[
        ("source_driven_baseline", "price_insensitive", C1_CONFIGURATION)
    ]
    recovery_c1 = lookup[("recovery_bg25", "price_insensitive", C1_CONFIGURATION)]

    def band_residual(value: float, low: float, high: float) -> float:
        return low - value if value < low else value - high if value > high else 0.0

    definitions = (
        (
            "real_c0_gross_electricity_band",
            float(baseline_c0["gross_electricity_mwh_y"]) / 1e6,
            float(recovery_c0["gross_electricity_mwh_y"]) / 1e6,
            "3.00-3.17",
            3.0,
            3.17,
            "TWh/y",
            "full_site_gross_represented_electricity",
            "annual_represented_full_site_gross_electricity_boundary",
            "screening_calibration_observation_not_independent_validation",
        ),
        (
            "real_c0_wag_generator_electricity",
            float(baseline_c0["internal_wag_electricity_mwh_y"]) / 1e6,
            float(recovery_c0["internal_wag_electricity_mwh_y"]) / 1e6,
            "2.528",
            2.528,
            2.528,
            "TWh/y",
            "WAG_attributed_generator_electricity",
            "annual_WAG_only_gross_generator_electricity_output_boundary",
            "screening_calibration_observation_not_independent_validation",
        ),
        (
            "real_c0_named_ng",
            float(baseline_c0["named_ng_mwh_lhv_y"]) * 3.6e-6,
            float(recovery_c0["named_ng_mwh_lhv_y"]) * 3.6e-6,
            "9.666",
            9.666,
            9.666,
            "PJ_LHV/y",
            "represented_named_NG_only_residual_excluded",
            "calendar_year_named_NG_LHV_energy_boundary_excluding_residual_NG",
            "screening_calibration_observation_not_independent_validation",
        ),
        (
            "mer_c1_dri_output_context",
            float(baseline_c1["drp_dri_output_t_y"]) / 1e6,
            float(recovery_c1["drp_dri_output_t_y"]) / 1e6,
            "2.8",
            2.8,
            2.8,
            "Mt_DRI/y",
            "MER_route_consistency_denominator",
            "annual_C1_DRP_DRI_output_boundary",
            "scenario_definition_overlap_not_independent_validation",
        ),
    )
    output: list[dict[str, Any]] = []
    for (
        anchor_id,
        baseline,
        recovery,
        source,
        low,
        high,
        unit,
        boundary,
        denominator,
        classification,
    ) in definitions:
        output.append(
            {
                "anchor_id": anchor_id,
                "real_first_source_value_or_band": source,
                "unit": unit,
                "source_driven_baseline_value": baseline,
                "recovery_bg25_value": recovery,
                "baseline_signed_or_band_residual": band_residual(
                    baseline, low, high
                ),
                "recovery_signed_or_band_residual": band_residual(
                    recovery, low, high
                ),
                "denominator": denominator,
                "boundary": boundary,
                "classification": classification,
                "calibration_use": False,
                "exact_tata_twin_claim": False,
                "annualisation_label": OUTPUT_LABEL,
            }
        )
    for anchor_id, context, denominator, reason in (
        (
            "athanasiadis_ng_thermal_substitution",
            "Athanasiadis model context",
            "unresolved_annual_thermal_service_and_named_NG_boundary",
            "not_validated_boundary_and_denominator_not_comparable",
        ),
        (
            "badarinath_bf_relationships",
            "Badarinath behavioural context",
            "unresolved_annual_BF_capacity_and_output_denominator",
            "not_validated_no_exact_BF_capacity_denominator",
        ),
        (
            "vn25_outage",
            "synthetic aggregate capacity context",
            "unresolved_named_asset_capacity_and_outage_duration_denominator",
            "not_validated_no_historical_outage_case",
        ),
    ):
        output.append(
            {
                "anchor_id": anchor_id,
                "real_first_source_value_or_band": context,
                "unit": "not_comparable",
                "source_driven_baseline_value": "",
                "recovery_bg25_value": "",
                "baseline_signed_or_band_residual": "",
                "recovery_signed_or_band_residual": "",
                "denominator": denominator,
                "boundary": reason,
                "classification": "not_validated",
                "calibration_use": False,
                "exact_tata_twin_claim": False,
                "annualisation_label": OUTPUT_LABEL,
            }
        )
    if any(
        not row["denominator"]
        or row["denominator"] == row["real_first_source_value_or_band"]
        for row in output
    ):
        raise Checkpoint6Error(
            "Anchor denominator must be an explicit boundary definition."
        )
    return output


def _duration_guardrails(
    *,
    candidate: Mapping[str, Any],
    periods: list[dict[str, Any]],
    scratch: Path,
) -> list[dict[str, Any]]:
    expected_background = (
        float(candidate["explicit_background_mwh_h"]) * 8760.0
    )
    expected_fixed_ng = 8.005 / 3.6e-6 if candidate["repair_interface_active"] else 0.0
    output: list[dict[str, Any]] = []
    for period in periods:
        for strategy in STRATEGIES:
            artifact = _read_csv(
                scratch
                / _case_id(period["period_id"], strategy)
                / "executed_hourly.csv"
            )
            rows = [
                row
                for row in artifact
                if row["configuration_id"] == C0_CONFIGURATION
            ]
            hours = len(rows)
            background = duration_aware_annual_equivalent(
                sum(float(row["site_background_electricity_mwh"]) for row in rows),
                hours,
            )
            fixed_ng = duration_aware_annual_equivalent(
                sum(float(row["full_site_fixed_ng_component_mwh"]) for row in rows),
                hours,
            )
            for check_id, value, expected, unit in (
                (
                    "duration_aware_fixed_background",
                    background,
                    expected_background,
                    "MWh_e/y",
                ),
                (
                    "duration_aware_fixed_ng",
                    fixed_ng,
                    expected_fixed_ng,
                    "MWh_LHV/y",
                ),
            ):
                residual = value - expected
                output.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "period_id": period["period_id"],
                        "strategy": strategy,
                        "configuration_id": C0_CONFIGURATION,
                        "check_id": check_id,
                        "status": "pass" if abs(residual) <= 1e-4 else "fail",
                        "maximum_abs_residual": abs(residual),
                        "evidence": (
                            f"{hours} exact executed hours; 8760/{hours} duration scaling; {unit}"
                        ),
                    }
                )
    return output


def aggregate_checkpoint6(
    *,
    config: Mapping[str, Any],
    periods: list[dict[str, Any]],
    forecast_root: Path,
    scratch_root: Path,
    output: Path,
    statuses: list[dict[str, Any]],
    aggregate_only: bool,
) -> dict[str, Any]:
    period_summaries: list[dict[str, Any]] = []
    weighted_summaries: list[dict[str, Any]] = []
    weighted_ledger: list[dict[str, Any]] = []
    dispersion: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    guardrails: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    for candidate in config["checkpoint_6"]["candidates"]:
        candidate_root = scratch_root / candidate["candidate_id"]
        summary, artifacts, vectors = _period_summary_rows(
            periods=periods,
            scratch=candidate_root,
            forecast_root=forecast_root,
        )
        if len(artifacts) != 24:
            raise Checkpoint6Error(
                f"{candidate['candidate_id']} has {len(artifacts)}/24 complete cases."
            )
        for row in summary:
            row.update(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_classification": candidate[
                        "candidate_classification"
                    ],
                    "annualisation_label": OUTPUT_LABEL,
                }
            )
        period_summaries.extend(summary)
        weighted_summaries.extend(_weighted_summary_rows(summary, candidate))
        ledger, physical_dispersion = _weighted_rows(
            periods=periods,
            scratch=candidate_root,
            summary_rows=summary,
        )
        for rows in (ledger, physical_dispersion):
            for row in rows:
                row.update(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "candidate_classification": candidate[
                            "candidate_classification"
                        ],
                        "annualisation_label": OUTPUT_LABEL,
                        "duration_aware_time_weighting": (
                            config["checkpoint_6"][
                                "duration_aware_time_weighting"
                            ]
                        ),
                    }
                )
        weighted_ledger.extend(ledger)
        dispersion.extend(physical_dispersion)
        dispersion.extend(_summary_dispersion_rows(summary, candidate))
        terminal = _terminal_inventory_rows(summary, artifacts)
        candidate_comparisons = _strategy_comparison_rows(
            summary,
            artifacts,
            vectors,
            forecast_root,
            terminal,
        )
        for row in candidate_comparisons:
            row.update(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_classification": candidate[
                        "candidate_classification"
                    ],
                    "annualisation_label": OUTPUT_LABEL,
                }
            )
        comparisons.extend(candidate_comparisons)
        candidate_guardrails = _guardrail_rows(
            periods=periods,
            scratch=candidate_root,
            artifacts=artifacts,
        )
        for row in candidate_guardrails:
            row["candidate_id"] = candidate["candidate_id"]
        candidate_guardrails.extend(
            _duration_guardrails(
                candidate=candidate,
                periods=periods,
                scratch=candidate_root,
            )
        )
        guardrails.extend(candidate_guardrails)
        candidate_solver = _solver_rows(candidate_root, artifacts)
        for row in candidate_solver:
            row["candidate_id"] = candidate["candidate_id"]
        solver_rows.extend(candidate_solver)

    if len(solver_rows) != 672:
        raise Checkpoint6Error(f"Expected 672 model records, found {len(solver_rows)}.")
    failures = [row for row in guardrails if row["status"] != "pass"]
    _write_csv(output / "case_status.csv", statuses)
    _write_csv(output / "period_strategy_summary.csv", period_summaries)
    _write_csv(output / "strategy_comparison.csv", comparisons)
    _write_csv(output / "weighted_strategy_summary.csv", weighted_summaries)
    _write_csv(
        output / "per_ton_comparison.csv", _per_ton_rows(weighted_summaries)
    )
    _write_csv(output / "weighted_annual_equivalent_ledger.csv", weighted_ledger)
    _write_csv(output / "weekly_dispersion.csv", dispersion)
    _write_csv(
        output / "anchor_comparison.csv",
        _anchor_comparison_rows(weighted_summaries),
    )
    _write_csv(output / "physical_guardrails.csv", guardrails)
    _write_csv(output / "solver_runtime_model_metrics.csv", solver_rows)
    summary = {
        "run_id": config["run_id"],
        "status": "pass" if not failures else "review_required",
        "checkpoint": 6,
        "annualisation_label": OUTPUT_LABEL,
        "annual_backtest": False,
        "held_out_test_period_count": 8,
        "candidate_count": 2,
        "strategy_count": 3,
        "rolling_case_count": 48,
        "model_count": 672,
        "optimal_model_count": sum(
            row["termination_condition"] == "optimal" for row in solver_rows
        ),
        "physical_guardrail_failure_count": len(failures),
        "solver_invoked_this_invocation": not aggregate_only,
        "reused_completed_case_count": sum(
            row["source"] == "reused_completed_case" for row in statuses
        ),
        "new_solve_case_count": sum(
            row["source"] == "new_solve" for row in statuses
        ),
        "candidate_promotion_status": "recovery_bg25_not_promoted",
        "exact_tata_twin_claim": False,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "checkpoint_state.json",
        {
            **summary,
            "status": (
                "checkpoint6_complete_review_pending"
                if not failures
                else "checkpoint6_guardrail_review_required"
            ),
            "historical_4plus4_contract_overwritten": False,
            "residual_energy_policy": "reporting_only",
        },
    )
    (output / "README.md").write_text(
        "# C0 real-anchor energy-recovery Checkpoint 6\n\n"
        f"Status: `{summary['status']}`; review pending.\n\n"
        f"All aggregate results are `{OUTPUT_LABEL}` and are not an annual backtest. "
        "The eight independently selected TEST weeks retain their week, candidate, "
        "strategy and C0/C1 dimensions; the 169-hour DST week is duration-aware. "
        f"Physical guardrail failures: {len(failures)}. "
        f"Solver invoked in this invocation: {not aggregate_only}. "
        "`recovery_bg25` remains `emulation_sensitivity_only` and is not promoted. "
        "No exact Tata twin, Athanasiadis NG thermal-substitution, Badarinath BF "
        "relationship or VN25 outage validation is claimed.\n",
        encoding="utf-8",
    )
    return summary


def run_checkpoint6(
    *,
    forecast_run_root: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    scratch_root: str | Path | None = None,
    prepare_only: bool = False,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    """Prepare, execute, resume, or cache-aggregate the frozen 48-case matrix."""

    started = time.perf_counter()
    preparation = prepare_checkpoint6(
        forecast_run_root=forecast_run_root, config_path=config_path
    )
    if prepare_only:
        return preparation
    config = load_checkpoint6_config(config_path)
    periods = derive_frozen_test_selection(
        forecast_run_root=forecast_run_root, config=config
    )
    output = Path(preparation["output_root"])
    scratch = (
        Path(scratch_root).resolve()
        if scratch_root
        else (REPO_ROOT / config["checkpoint_6"]["scratch_root"]).resolve()
    )
    scratch.mkdir(parents=True, exist_ok=True)
    forecast_root = Path(forecast_run_root).resolve()
    physical_config = (
        REPO_ROOT / config["checkpoint_6"]["physical_config"]
    ).resolve()
    statuses: list[dict[str, Any]] = []
    matrix = [
        (candidate, period, strategy)
        for candidate in config["checkpoint_6"]["candidates"]
        for period in periods
        for strategy in STRATEGIES
    ]
    for index, (candidate, period, strategy) in enumerate(matrix, start=1):
        candidate_id = str(candidate["candidate_id"])
        case_id = _case_id(str(period["period_id"]), strategy)
        candidate_root = scratch / candidate_id
        directory = candidate_root / case_id
        identity = _cache_identity_payload(
            config=config,
            candidate=candidate,
            period=period,
            strategy=strategy,
        )
        expected_scenario_override_sha256 = _mapping_sha256(identity)
        overrides = _expected_case_overrides(
            config=config,
            candidate=candidate,
            period=period,
            strategy=strategy,
            forecast_root=forecast_root,
        )
        cached = _checkpoint6_case_ready(
            directory,
            expected_overrides=overrides,
            expected_scenario_override_sha256=(
                expected_scenario_override_sha256
            ),
        )
        source = "reused_completed_case" if cached else "new_solve"
        error = ""
        status = "pass"
        case_started = time.perf_counter()
        if not cached and not aggregate_only:
            if directory.exists():
                raise Checkpoint6Error(
                    "Incomplete, stale, or identity-mismatched case preserved "
                    f"for inspection: {directory}"
                )
            try:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=candidate_root,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                status = "fail"
                error = f"{type(exc).__name__}: {exc}"
            cached = _checkpoint6_case_ready(
                directory,
                expected_overrides=overrides,
                expected_scenario_override_sha256=(
                    expected_scenario_override_sha256
                ),
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
                "candidate_classification": candidate[
                    "candidate_classification"
                ],
                "period_id": period["period_id"],
                "strategy": strategy,
                "case_id": case_id,
                "status": status,
                "source": source,
                "runtime_seconds_this_invocation": (
                    time.perf_counter() - case_started
                ),
                "error": error,
            }
        )
        _write_csv(output / "case_status.csv", statuses)
        print(
            f"[{index}/{len(matrix)}] {candidate_id}/{case_id}: "
            f"{status} ({source})",
            flush=True,
        )
        if status != "pass":
            raise Checkpoint6Error(
                f"Checkpoint 6 stopped on {candidate_id}/{case_id}: {error}"
            )
    summary = aggregate_checkpoint6(
        config=config,
        periods=periods,
        forecast_root=forecast_root,
        scratch_root=scratch,
        output=output,
        statuses=statuses,
        aggregate_only=aggregate_only,
    )
    summary["wall_runtime_seconds_this_invocation"] = (
        time.perf_counter() - started
    )
    _write_json(output / "run_summary.json", summary)
    return summary
