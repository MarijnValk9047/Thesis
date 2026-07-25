"""Frozen Checkpoint 4 behavioural validation for the retained C0 pair.

This module contains orchestration and compact reporting only. Every rolling
optimisation is delegated to the accepted p_af runner.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any, Mapping

import yaml

from .c5_user_authorized_emulation_checkpoint4 import (
    _annual_component,
    _artifact,
    _case_ready,
    _git_head,
    _guardrail_rows,
    _number,
    _scenario_overrides,
    _solver_rows,
    _write_csv,
    _write_json,
)
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_bl_deterministic_price_response_anchor_diagnostics import (
    _first_window_price_vector,
    _first_window_schedule_costs,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs"
    / "steel_c5_real_anchor_energy_recovery_checkpoint4.yaml"
)
EXPECTED_CANDIDATES = ("source_driven_baseline", "recovery_bg25")
EXPECTED_SCENARIOS = (
    "calm_price_insensitive",
    "calm_flat_low",
    "calm_flat_high",
    "calm_governed_y_pred",
    "volatile_negative_governed_y_pred",
    "volatile_negative_oracle_y_true",
)
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")
TOLERANCE = 1e-4


class Checkpoint4BehaviorError(RuntimeError):
    """Raised when the frozen Checkpoint 4 contract is violated."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_checkpoint4_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))


def validate_checkpoint4_config(config: Mapping[str, Any]) -> None:
    if config.get("mode") != "c0_real_anchor_energy_recovery_checkpoint4":
        raise Checkpoint4BehaviorError("Unexpected Checkpoint 4 execution mode.")
    if config.get("output_policy") != "minimal":
        raise Checkpoint4BehaviorError("Checkpoint 4 requires output_policy=minimal.")
    checkpoint = config["checkpoint_4"]
    candidates = tuple(row["candidate_id"] for row in checkpoint["candidates"])
    scenarios = tuple(row["scenario_id"] for row in checkpoint["scenarios"])
    periods = tuple(row["period_id"] for row in checkpoint["development_periods"])
    if candidates != EXPECTED_CANDIDATES:
        raise Checkpoint4BehaviorError(f"Frozen candidates differ: {candidates}.")
    if scenarios != EXPECTED_SCENARIOS:
        raise Checkpoint4BehaviorError(f"Frozen scenarios differ: {scenarios}.")
    if periods != EXPECTED_PERIODS:
        raise Checkpoint4BehaviorError(f"Frozen periods differ: {periods}.")
    if int(checkpoint["expected_rolling_case_count"]) != 12:
        raise Checkpoint4BehaviorError("Exactly 2x6=12 rolling cases are required.")
    if int(checkpoint["expected_model_count"]) != 168:
        raise Checkpoint4BehaviorError("Exactly 168 inherited C0/C1 model solves are expected.")
    if checkpoint.get("held_out_periods_used") is not False or any(
        row["dataset_split"] != "validation"
        or row["period_role"] != "development"
        or row["final_held_out_selection_eligible"] is not False
        for row in checkpoint["development_periods"]
    ):
        raise Checkpoint4BehaviorError("Held-out periods are prohibited.")
    for scenario in checkpoint["scenarios"]:
        is_oracle = bool(scenario["perfect_foresight_oracle"])
        if (scenario["price_field"] == "y_true") != is_oracle:
            raise Checkpoint4BehaviorError(
                "y_true is permitted only in the explicitly labelled oracle."
            )
    recovery = checkpoint["candidates"][1]
    if (
        recovery["candidate_classification"] != "emulation_sensitivity_only"
        or float(recovery["explicit_background_twh_y"]) != 0.7925
        or abs(float(recovery["explicit_background_mwh_h"]) - 90.46803652968036)
        > 1e-12
    ):
        raise Checkpoint4BehaviorError("The retained recovery_bg25 definition changed.")
    interface = checkpoint["recovery_interface"][
        "c0_aggregate_generator_technical_interface"
    ]
    if (
        float(interface["electricity_efficiency"]) != 0.345
        or float(interface["total_fuel_volume_cap_nm3_h"]) != 900000.0
        or float(interface["electrical_capacity_mw"]) != 770.0
        or float(interface["natural_gas_lhv_mj_per_nm3"]) != 35.8
        or interface["export_allowed"] is not False
    ):
        raise Checkpoint4BehaviorError("The reviewed recovery interface changed.")
    stress = checkpoint["physical_stress_contract"]
    if (
        stress["stress_id"] != "aggregate_vn25_off_proxy"
        or stress["execution_availability"] != "structurally_unavailable"
        or float(stress["proposed_electrical_capacity_mw"]) != 420.0
        or float(stress["proposed_total_fuel_volume_cap_nm3_h"]) != 300000.0
        or stress["safeguard_bypass_allowed"] is not False
    ):
        raise Checkpoint4BehaviorError("The frozen synthetic stress contract changed.")
    scorecard = _read_csv(REPO_ROOT / checkpoint["checkpoint3_scorecard"])
    selected = {
        row["candidate_id"]
        for row in scorecard
        if row["selected_for_checkpoint4"].lower() == "true"
    }
    if selected != set(EXPECTED_CANDIDATES):
        raise Checkpoint4BehaviorError(
            "Checkpoint 4 candidates differ from the reviewed Checkpoint 3 pair."
        )


def candidate_overrides(
    config: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    background = float(candidate["explicit_background_mwh_h"])
    overrides: dict[str, Any] = {
        "site_background_electricity_mwh_h_by_configuration": {
            C0_CONFIGURATION: background,
            C1_CONFIGURATION: 0.0,
        },
        "checkpoint4_candidate_id": candidate["candidate_id"],
        "checkpoint4_candidate_classification": candidate[
            "candidate_classification"
        ],
    }
    if bool(candidate["repair_interface_active"]):
        recovery = config["checkpoint_4"]["recovery_interface"]
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


def frozen_scenario_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    checkpoint = config["checkpoint_4"]
    periods = {
        row["period_id"]: row for row in checkpoint["development_periods"]
    }
    rows: list[dict[str, Any]] = []
    for candidate in checkpoint["candidates"]:
        for scenario in checkpoint["scenarios"]:
            resolved = {
                **_scenario_overrides(scenario, periods),
                **candidate_overrides(config, candidate),
            }
            rows.append(
                {
                    "case_id": _case_id(
                        str(candidate["candidate_id"]), str(scenario["scenario_id"])
                    ),
                    "candidate_id": candidate["candidate_id"],
                    "candidate_classification": candidate[
                        "candidate_classification"
                    ],
                    "scenario_id": scenario["scenario_id"],
                    "period_id": scenario["period_id"],
                    "price_field": scenario["price_field"],
                    "flat_price_eur_per_mwh": scenario.get(
                        "flat_price_eur_per_mwh"
                    ),
                    "perfect_foresight_oracle": scenario[
                        "perfect_foresight_oracle"
                    ],
                    "final_held_out_selection_eligible": False,
                    "scenario_override_sha256": _mapping_sha256(resolved),
                }
            )
    return rows


def scenario_response_contract_rows(
    config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "frozen_before_solver_execution": True,
            "uses_realised_future_information_operationally": (
                row["expectation_id"]
                == "oracle_first_window_realised_cost_dominance"
            ),
        }
        for row in config["checkpoint_4"]["expectations"]
    ]


def _case_id(candidate_id: str, scenario_id: str) -> str:
    return f"cp4__{candidate_id}__{scenario_id}".replace("-", "_")


def _preparation_readme() -> str:
    return (
        "# C0 real-anchor energy-recovery Checkpoint 4\n\n"
        "Status: `checkpoint4_prepared_reviewed_checkpoint3`; no Checkpoint 4 "
        "solver has been invoked by the preparation step.\n\n"
        "The frozen matrix contains exactly two reviewed candidates and six price "
        "profiles over two pre-existing validation/development weeks. Operational "
        "profiles use `y_pred`; `y_true` is isolated to the explicitly labelled "
        "oracle. Both weeks remain excluded from final held-out selection.\n\n"
        "`recovery_bg25` remains `emulation_sensitivity_only` and cannot be promoted "
        "centrally here. The 420 MW/300,000 Nm3/h aggregate VN25-off proxy is frozen "
        "as a synthetic stress contract but is structurally unavailable because the "
        "accepted runner validates the reviewed 770 MW/900,000 Nm3/h interface. No "
        "safeguard is bypassed. C1 is solved naturally by the accepted runner but is "
        "unchanged by the C0 repair and is not recalibrated.\n"
    )


def _completion_readme(*, aggregate_only: bool, response_failure_count: int) -> str:
    return (
        "# C0 real-anchor energy-recovery Checkpoint 4\n\n"
        "Status: `checkpoint4_complete_review_pending`.\n\n"
        "All twelve frozen rolling cases are present and aggregated; 168 inherited "
        "C0/C1 model records are optimal and all physical/accounting guardrails pass. "
        + (
            "This invocation reused all completed precision12 case caches and did not "
            "invoke a solver. "
            if aggregate_only
            else "The rolling cases were executed through the accepted p_af runner. "
        )
        + f"Hard scenario-response failures: {response_failure_count}.\n\n"
        "`recovery_bg25` remains `emulation_sensitivity_only` and is not promoted. "
        "The synthetic aggregate VN25-off proxy remains structurally unavailable; no "
        "validator safeguard was bypassed. Operational profiles use `y_pred`, while "
        "`y_true` is isolated to the explicitly labelled identical-state first-window "
        "oracle. Both periods remain development/validation weeks and no held-out "
        "period was used. C1 results are reported without a recalibration claim.\n"
    )


def prepare_checkpoint4(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Persist the frozen pre-solve contract without invoking the solver."""

    config_file = Path(config_path).resolve()
    config = load_checkpoint4_config(config_file)
    validate_checkpoint4_config(config)
    output = (REPO_ROOT / config["output_root"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    matrix = frozen_scenario_matrix(config)
    contract = scenario_response_contract_rows(config)
    _write_csv(output / "scenario_response_contract.csv", contract)
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
    physical_config = (REPO_ROOT / config["checkpoint_4"]["physical_config"]).resolve()
    checkpoint3_config = (
        REPO_ROOT / config["checkpoint_4"]["checkpoint3_config"]
    ).resolve()
    period_contract = (
        REPO_ROOT / config["checkpoint_4"]["period_contract"]
    ).resolve()
    scorecard = (REPO_ROOT / config["checkpoint_4"]["checkpoint3_scorecard"]).resolve()
    repository_files = (
        config_file,
        physical_config,
        checkpoint3_config,
        period_contract,
        scorecard,
        Path(__file__).resolve(),
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel"
        / "c5_user_authorized_emulation_checkpoint4.py",
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel"
        / "s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    )
    _write_json(
        output / "input_manifest.json",
        {
            "run_id": config["run_id"],
            "checkpoint": 4,
            "candidate_count": 2,
            "scenario_profile_count": 6,
            "rolling_case_count": 12,
            "expected_model_count": 168,
            "held_out_periods_used": False,
            "solver_invoked_by_preparation": False,
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
        {"git_commit": _git_head(), "checkpoint": 4},
    )
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": config["run_id"],
            "status": "checkpoint4_prepared_reviewed_checkpoint3",
            "solver_invoked": False,
            "rolling_case_count_frozen": 12,
            "held_out_periods_used": False,
            "stress_execution_availability": "structurally_unavailable",
            "next_action": "root_invokes_checkpoint4_after_dry_run_validation",
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": "minimal",
            "status": "checkpoint4_prepared_reviewed_checkpoint3",
            "git_eligible": False,
        },
    )
    (output / "README.md").write_text(_preparation_readme(), encoding="utf-8")
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Two validation/development weeks are not an empirical annual backtest.\n"
        "- `y_true` is operational input only for the explicitly labelled oracle.\n"
        "- Oracle dominance is limited to the identical-state first planning window.\n"
        "- The aggregate VN25-off proxy is structurally unavailable and is not a historical Tata event.\n"
        "- C1 is unchanged by the C0 repair; no C1 recalibration is claimed.\n"
        "- Bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR remain excluded.\n",
        encoding="utf-8",
    )
    return {
        "status": "checkpoint4_prepared_reviewed_checkpoint3",
        "candidate_count": 2,
        "scenario_count": 6,
        "rolling_case_count": len(matrix),
        "solver_invoked": False,
        "output_root": str(output),
    }


def _strategy_price_summary(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for (candidate_id, scenario_id), artifact in sorted(artifacts.items()):
        physical = artifact["physical"]
        for configuration in CONFIGURATIONS:
            hourly = [
                row
                for row in artifact["hourly"]
                if row["configuration_id"] == configuration
            ]
            prices = executed_prices_for_hourly(artifact["prices"], hourly)
            median_price = statistics.median(prices)
            factor = 8760.0 / len(hourly)
            total = lambda field: sum(_number(row.get(field)) for row in hourly)
            generator = [
                _number(
                    row.get(
                        "total_generator_electricity_mwh",
                        row.get("generator_electricity_mwh"),
                    )
                )
                for row in hourly
            ]
            grid = [
                _number(row.get("gross_grid_import_mwh", row.get("net_grid_import_mwh")))
                for row in hourly
            ]
            high_generator = [
                value for value, price in zip(generator, prices) if price > median_price
            ]
            low_generator = [
                value for value, price in zip(generator, prices) if price <= median_price
            ]
            high_grid = [
                value for value, price in zip(grid, prices) if price > median_price
            ]
            low_grid = [
                value for value, price in zip(grid, prices) if price <= median_price
            ]
            output.append(
                {
                    "candidate_id": candidate_id,
                    "scenario_id": scenario_id,
                    "configuration_id": configuration,
                    "executed_hours": len(hourly),
                    "mean_price_eur_per_mwh": statistics.fmean(prices),
                    "price_volatility_eur_per_mwh": statistics.pstdev(prices),
                    "negative_price_share": sum(value < 0 for value in prices)
                    / len(prices),
                    "wag_generator_electricity_mwh_y": _annual_component(
                        physical, configuration, "WAG_generator_electricity"
                    ),
                    "ng_generator_electricity_mwh_y": _annual_component(
                        physical, configuration, "NG_generator_electricity"
                    ),
                    "gross_grid_import_mwh_y": _annual_component(
                        physical, configuration, "gross_grid_import"
                    ),
                    "wag_to_flexible_heat_mwh_y": sum(
                        total(field)
                        for field in (
                            "BFG_to_flexible_other_site_heat_mwh",
                            "COG_to_flexible_other_site_heat_mwh",
                            "BOFG_to_flexible_other_site_heat_mwh",
                        )
                    )
                    * factor,
                    "flexible_ng_mwh_lhv_y": _annual_component(
                        physical, configuration, "flexible_other_site_heat"
                    ),
                    "fixed_ng_mwh_lhv_y": _annual_component(
                        physical, configuration, "fixed_full_site_component"
                    ),
                    "wag_flare_mwh_lhv_y": sum(
                        total(field)
                        for field in ("BFG_flare_mwh", "COG_flare_mwh", "BOFG_flare_mwh")
                    )
                    * factor,
                    "high_price_generator_mean_mwh_h": (
                        statistics.fmean(high_generator) if high_generator else ""
                    ),
                    "low_price_generator_mean_mwh_h": (
                        statistics.fmean(low_generator) if low_generator else ""
                    ),
                    "high_price_grid_import_mean_mwh_h": (
                        statistics.fmean(high_grid) if high_grid else ""
                    ),
                    "low_price_grid_import_mean_mwh_h": (
                        statistics.fmean(low_grid) if low_grid else ""
                    ),
                    "c1_recalibration_claim": False,
                }
            )
    return output


def executed_prices_for_hourly(
    price_rows: list[Mapping[str, Any]],
    hourly_rows: list[Mapping[str, Any]],
) -> list[float]:
    """Join executed prices to executed hourly rows on the governed global index."""

    required_price = {
        "replan_index",
        "executed_hour_index",
        "price_eur_per_mwh_e",
    }
    required_hourly = {"replan_index", "executed_hour_index"}
    if not price_rows or any(
        not required_price.issubset(row) for row in price_rows
    ):
        raise Checkpoint4BehaviorError(
            "Executed price rows must contain replan_index, executed_hour_index, "
            "and price_eur_per_mwh_e."
        )
    if not hourly_rows or any(
        not required_hourly.issubset(row) for row in hourly_rows
    ):
        raise Checkpoint4BehaviorError(
            "Executed hourly rows must contain replan_index and executed_hour_index."
        )
    price_by_key: dict[tuple[int, int], float] = {}
    for row in price_rows:
        key = (int(row["replan_index"]), int(row["executed_hour_index"]))
        if key in price_by_key:
            raise Checkpoint4BehaviorError(
                f"Duplicate executed price key: {key}."
            )
        price_by_key[key] = _number(row["price_eur_per_mwh_e"])
    hourly_keys = [
        (int(row["replan_index"]), int(row["executed_hour_index"]))
        for row in hourly_rows
    ]
    missing = [key for key in hourly_keys if key not in price_by_key]
    if missing:
        raise Checkpoint4BehaviorError(
            f"Executed hourly rows have no matching executed price keys: {missing[:3]}."
        )
    return [price_by_key[key] for key in hourly_keys]


def _scenario_response_checks(
    config: Mapping[str, Any],
    summary: list[dict[str, Any]],
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    forecast_root: Path,
) -> list[dict[str, Any]]:
    by_key = {
        (row["candidate_id"], row["scenario_id"], row["configuration_id"]): row
        for row in summary
    }
    output: list[dict[str, Any]] = []

    def add(
        candidate: str,
        check_id: str,
        status: str,
        observed: str,
        basis: str,
    ) -> None:
        output.append(
            {
                "candidate_id": candidate,
                "check_id": check_id,
                "status": status,
                "observed": observed,
                "assessment_basis": basis,
            }
        )

    baseline = "source_driven_baseline"
    add(
        baseline,
        "baseline_flexible_bridge_response",
        "not_applicable",
        "source baseline has no flexible full-site bridge",
        "must not be counted as failure",
    )
    low = by_key[("recovery_bg25", "calm_flat_low", C0_CONFIGURATION)]
    high = by_key[("recovery_bg25", "calm_flat_high", C0_CONFIGURATION)]
    directional = (
        (
            "wag_generator_low_non_increasing",
            float(low["wag_generator_electricity_mwh_y"])
            <= float(high["wag_generator_electricity_mwh_y"]) + TOLERANCE,
        ),
        (
            "wag_flexible_heat_low_non_decreasing",
            float(low["wag_to_flexible_heat_mwh_y"])
            >= float(high["wag_to_flexible_heat_mwh_y"]) - TOLERANCE,
        ),
        (
            "flexible_ng_low_non_increasing",
            float(low["flexible_ng_mwh_lhv_y"])
            <= float(high["flexible_ng_mwh_lhv_y"]) + TOLERANCE,
        ),
        (
            "fixed_ng_invariant",
            abs(
                float(low["fixed_ng_mwh_lhv_y"])
                - float(high["fixed_ng_mwh_lhv_y"])
            )
            <= TOLERANCE,
        ),
    )
    for check_id, passed in directional:
        add(
            "recovery_bg25",
            check_id,
            "pass" if passed else "fail",
            f"low={low};high={high}",
            "calm flat 40 versus 120 directional comparison; no exact magnitude",
        )
    for candidate in EXPECTED_CANDIDATES:
        for configuration in CONFIGURATIONS:
            row = by_key[
                (
                    candidate,
                    "volatile_negative_governed_y_pred",
                    configuration,
                )
            ]
            high_generator = row["high_price_generator_mean_mwh_h"]
            high_grid = row["high_price_grid_import_mean_mwh_h"]
            evidence = (
                high_generator != ""
                and float(high_generator)
                >= float(row["low_price_generator_mean_mwh_h"]) - TOLERANCE
            ) or (
                high_grid != ""
                and float(high_grid)
                <= float(row["low_price_grid_import_mean_mwh_h"]) + TOLERANCE
            )
            add(
                candidate,
                f"volatile_predicted_response::{configuration}",
                "pass" if evidence else "fail",
                (
                    f"high_generator={high_generator};"
                    f"low_generator={row['low_price_generator_mean_mwh_h']};"
                    f"high_grid={high_grid};"
                    f"low_grid={row['low_price_grid_import_mean_mwh_h']}"
                ),
                "optimizer-visible y_pred above-median versus lower-price hours",
            )
            for scenario_id in (
                "volatile_negative_governed_y_pred",
                "volatile_negative_oracle_y_true",
            ):
                negative = by_key[(candidate, scenario_id, configuration)]
                add(
                    candidate,
                    f"negative_price_redistribution::{scenario_id}::{configuration}",
                    "reported",
                    (
                        f"negative_share={negative['negative_price_share']};"
                        f"wag_generator={negative['wag_generator_electricity_mwh_y']};"
                        f"grid_import={negative['gross_grid_import_mwh_y']};"
                        f"flare={negative['wag_flare_mwh_lhv_y']}"
                    ),
                    "descriptive only; no forced exact response",
                )
    volatile = next(
        row
        for row in config["checkpoint_4"]["development_periods"]
        if row["period_id"] == "validation_2024-07-01"
    )
    vector = _first_window_price_vector(
        forecast_root=forecast_root,
        dataset_split="validation",
        start_origin_utc=volatile["frozen_forecast_start_origin_utc"],
    )
    for candidate in EXPECTED_CANDIDATES:
        forecast = artifacts[
            (candidate, "volatile_negative_governed_y_pred")
        ]
        oracle = artifacts[(candidate, "volatile_negative_oracle_y_true")]
        forecast_cost = _first_window_schedule_costs(
            forecast, vector, price_field="y_true_eur_per_mwh"
        )
        oracle_cost = _first_window_schedule_costs(
            oracle, vector, price_field="y_true_eur_per_mwh"
        )
        for configuration in CONFIGURATIONS:
            left = oracle_cost[configuration]["total_represented_cost_eur"]
            right = forecast_cost[configuration]["total_represented_cost_eur"]
            add(
                candidate,
                f"oracle_first_window_dominance::{configuration}",
                "pass" if left <= right + 0.01 else "fail",
                f"oracle_y_true_cost={left};forecast_schedule_y_true_cost={right}",
                "identical-state first planning window only",
            )
    stress = config["checkpoint_4"]["physical_stress_contract"]
    add(
        "recovery_bg25",
        stress["stress_id"],
        "structurally_unavailable",
        stress["unavailability_reason"],
        "accepted validator is not bypassed",
    )
    add(
        "both",
        "c1_unchanged_by_c0_repair",
        "reported",
        "C1 outputs included for all 12 cases",
        "no C1 recalibration claim",
    )
    return output


def run_checkpoint4_behavior(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    forecast_run_root: str | Path,
    scratch_root: str | Path | None = None,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    """Execute the frozen matrix solely through the accepted p_af runner."""

    started = time.perf_counter()
    preparation = prepare_checkpoint4(config_path)
    config = load_checkpoint4_config(config_path)
    checkpoint = config["checkpoint_4"]
    output = Path(preparation["output_root"])
    scratch = (
        Path(scratch_root).resolve()
        if scratch_root
        else (REPO_ROOT / checkpoint["scratch_root"]).resolve()
    )
    scratch.mkdir(parents=True, exist_ok=True)
    forecast_root = Path(forecast_run_root).resolve()
    physical_config = (REPO_ROOT / checkpoint["physical_config"]).resolve()
    periods = {
        row["period_id"]: row for row in checkpoint["development_periods"]
    }
    statuses: list[dict[str, Any]] = []
    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    matrix = [
        (candidate, scenario)
        for candidate in checkpoint["candidates"]
        for scenario in checkpoint["scenarios"]
    ]
    for index, (candidate, scenario) in enumerate(matrix, start=1):
        candidate_id = str(candidate["candidate_id"])
        scenario_id = str(scenario["scenario_id"])
        case_id = _case_id(candidate_id, scenario_id)
        directory = scratch / case_id
        cached = _case_ready(directory)
        source = "reused_completed_case" if cached else "new_solve"
        error = ""
        status = "pass"
        case_started = time.perf_counter()
        if not cached and not aggregate_only:
            if directory.exists():
                raise Checkpoint4BehaviorError(
                    f"Incomplete existing case preserved for inspection: {directory}"
                )
            overrides = {
                "run_id": case_id,
                "lineage_role": "checkpoint4_real_anchor_behavior_case_cache",
                "forecast_run_root": str(forecast_root),
                **_scenario_overrides(scenario, periods),
                **candidate_overrides(config, candidate),
            }
            try:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                status = "fail"
                error = f"{type(exc).__name__}: {exc}"
            cached = _case_ready(directory)
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
                "case_id": case_id,
                "status": status,
                "source": source,
                "runtime_seconds_this_invocation": time.perf_counter() - case_started,
                "error": error,
            }
        )
        _write_csv(output / "checkpoint4_case_status.csv", statuses)
        print(f"[{index}/{len(matrix)}] {case_id}: {status} ({source})", flush=True)
        if status != "pass":
            raise Checkpoint4BehaviorError(
                f"Checkpoint 4 stopped on {case_id}: {error}"
            )
        artifact = _artifact(directory)
        artifact["physical"] = _read_csv(
            directory / "annual_physical_boundary_ledger.csv"
        )
        artifact["directory"] = str(directory)
        artifacts[(candidate_id, scenario_id)] = artifact

    status_by_case = {row["case_id"]: row for row in statuses}
    _write_csv(
        output / "scenario_input_manifest.csv",
        [
            {
                **row,
                "execution_status": status_by_case[row["case_id"]]["status"],
                "execution_source": status_by_case[row["case_id"]]["source"],
                "solver_invoked_this_invocation": (
                    status_by_case[row["case_id"]]["source"] == "new_solve"
                ),
            }
            for row in frozen_scenario_matrix(config)
        ],
    )
    summary = _strategy_price_summary(artifacts)
    guardrails = _guardrail_rows(artifacts)
    solver = _solver_rows(artifacts)
    if len(solver) != 168:
        raise Checkpoint4BehaviorError(
            f"Expected 168 inherited solver records, found {len(solver)}."
        )
    failures = [row for row in guardrails if row["status"] != "pass"]
    if failures:
        raise Checkpoint4BehaviorError(
            f"Physical/accounting guardrails failed: {len(failures)}."
        )
    response = _scenario_response_checks(
        config, summary, artifacts, forecast_root=forecast_root
    )
    hard_failures = [row for row in response if row["status"] == "fail"]
    _write_csv(output / "strategy_price_summary.csv", summary)
    _write_csv(output / "scenario_response_checks.csv", response)
    _write_csv(output / "physical_guardrails.csv", guardrails)
    _write_csv(output / "solver_runtime_metrics.csv", solver)
    _write_json(
        output / "run_summary.json",
        {
            "run_id": config["run_id"],
            "status": "pass" if not hard_failures else "review_required",
            "checkpoint": 4,
            "candidate_count": 2,
            "scenario_profile_count": 6,
            "rolling_case_count": 12,
            "model_count": len(solver),
            "optimal_model_count": sum(
                row.get("termination_condition") == "optimal" for row in solver
            ),
            "physical_guardrail_failure_count": 0,
            "scenario_response_failure_count": len(hard_failures),
            "solver_invoked_this_invocation": not aggregate_only,
            "reused_completed_case_count": sum(
                row["source"] == "reused_completed_case" for row in statuses
            ),
            "new_solve_case_count": sum(
                row["source"] == "new_solve" for row in statuses
            ),
            "stress_execution_availability": "structurally_unavailable",
            "candidate_promotion_status": "not_promoted_development_sensitivity_only",
            "wall_runtime_seconds_this_invocation": time.perf_counter() - started,
        },
    )
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": config["run_id"],
            "status": (
                "checkpoint4_complete_review_pending"
                if not hard_failures
                else "checkpoint4_complete_response_review_required"
            ),
            "solver_invoked": True,
            "solver_results_present": True,
            "solver_invoked_this_invocation": not aggregate_only,
            "reused_completed_case_count": sum(
                row["source"] == "reused_completed_case" for row in statuses
            ),
            "rolling_case_count": 12,
            "held_out_periods_used": False,
            "recovery_candidate_classification": "emulation_sensitivity_only",
            "candidate_promotion_status": "not_promoted",
            "c1_recalibration_claim": False,
            "stress_execution_availability": "structurally_unavailable",
        },
    )
    (output / "README.md").write_text(
        _completion_readme(
            aggregate_only=aggregate_only,
            response_failure_count=len(hard_failures),
        ),
        encoding="utf-8",
    )
    return json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
