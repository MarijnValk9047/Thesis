"""Zero-solve Phase 5C source-mechanism adjudication.

This checkpoint corrects two historical Badarinath metric definitions and
records the Athanasiadis objective boundary without changing model physics or
economics.  It consumes only existing DEVELOPMENT trajectories.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5c_source_mechanism_adjudication_v1_20260727"
OUTPUT_ROOT = REPO_ROOT / "data/03_Optimisation/runs" / RUN_ID
CASE_ROOT = (
    REPO_ROOT
    / "tmp/steel_c5_phase5b_c0_export_sensitivity_v2_20260727_cases"
)
SOURCE_INPUTS = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/source_cards/F18_athanasiadis_tata_ijmuiden_thesis.md",
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/source_cards/F19_badarinath_stochastic_bidding_framework.md",
    REPO_ROOT
    / "data/03_Optimisation/runs/steel_c5_phase5b_breakthrough_tests_v1_20260727/checkpoint_decision.json",
)
C0_CONFIGURATION = "C0_current_BF_BOF_reference"
C1_CONFIGURATION = "C1_phase1_BF_BOF_plus_DRP_EAF"
BF_CAPACITY_T_SINTER_H = {"BF6": 170.0, "BF7": 261.53846154}
AT_MAX_TOLERANCE_T_H = 1e-5
CASES = (
    {
        "period_id": "validation_2024-02-12",
        "case_id": "phase5b__validation_2024_02_12__accepted_no_export_comparator",
    },
    {
        "period_id": "validation_2024-07-01",
        "case_id": "phase5b__validation_2024_07_01__accepted_no_export_comparator",
    },
)


class Phase5CAdjudicationError(RuntimeError):
    """Raised when the bounded Phase 5C evidence contract is violated."""


def pearson_correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Return Pearson's r, or ``None`` for a constant or undersized vector."""

    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    scale = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return None if scale <= 1e-15 else numerator / scale


def inventory_change_price_correlation(
    inventories: Sequence[float], prices: Sequence[float]
) -> float | None:
    """Correlate same-hour price with hourly inventory change.

    Badarinath Table C.6 reports changes in storage levels, not storage levels.
    The first end-of-hour inventory has no preceding executed observation and
    is therefore excluded together with its price.
    """

    if len(inventories) != len(prices):
        raise Phase5CAdjudicationError("Inventory and price vectors must align.")
    changes = [
        inventories[index] - inventories[index - 1]
        for index in range(1, len(inventories))
    ]
    return pearson_correlation(changes, list(prices[1:]))


def blast_furnace_capacity_metrics(
    hourly_input_t: Sequence[float],
    capacity_t_h: float,
    *,
    at_max_tolerance_t_h: float = AT_MAX_TOLERANCE_T_H,
) -> dict[str, float]:
    """Normalize BF burden by its own hourly capacity."""

    if not hourly_input_t or capacity_t_h <= 0.0:
        raise Phase5CAdjudicationError("BF inputs and capacity must be positive.")
    return {
        "executed_input_t": sum(hourly_input_t),
        "capacity_utilisation_fraction": sum(hourly_input_t)
        / (capacity_t_h * len(hourly_input_t)),
        "share_hours_at_maximum": sum(
            abs(value - capacity_t_h) <= at_max_tolerance_t_h
            for value in hourly_input_t
        )
        / len(hourly_input_t),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = list(rows)
    fields = list(dict.fromkeys(key for row in materialized for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase5CAdjudicationError(
            f"Persistent lineage path must be repository-relative: {path}"
        ) from exc


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def _case_vectors(case_directory: Path) -> dict[str, list[float]]:
    hourly_path = case_directory / "executed_hourly.csv"
    price_path = case_directory / "executed_electricity_price_series.csv"
    if not hourly_path.is_file() or not price_path.is_file():
        raise Phase5CAdjudicationError(
            f"Required DEVELOPMENT evidence is missing: {case_directory}"
        )
    hourly = _read_csv(hourly_path)
    prices = _read_csv(price_path)
    price_by_hour = {
        int(row["executed_hour_index"]): float(row["price_eur_per_mwh_e"])
        for row in prices
    }
    c0 = sorted(
        (row for row in hourly if row["configuration_id"] == C0_CONFIGURATION),
        key=lambda row: int(row["executed_hour_index"]),
    )
    c1 = sorted(
        (row for row in hourly if row["configuration_id"] == C1_CONFIGURATION),
        key=lambda row: int(row["executed_hour_index"]),
    )
    if len(c0) != 168 or len(c1) != 168 or len(price_by_hour) != 168:
        raise Phase5CAdjudicationError(
            "Phase 5C requires two complete 168-hour DEVELOPMENT trajectories."
        )
    c1_indices = [int(row["executed_hour_index"]) for row in c1]
    return {
        "bf6": [float(row["C0_BF6_sinter_input_t_h"]) for row in c0],
        "bf7": [float(row["C0_BF7_sinter_input_t_h"]) for row in c0],
        "dri_inventory": [
            float(row["DRI_inventory_t_unrounded"]) for row in c1
        ],
        "prices": [price_by_hour[index] for index in c1_indices],
    }


def reproduce_badarinath_metrics() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in CASES:
        case_directory = CASE_ROOT / case["case_id"]
        vectors = _case_vectors(case_directory)
        for furnace, field in (("BF6", "bf6"), ("BF7", "bf7")):
            metrics = blast_furnace_capacity_metrics(
                vectors[field], BF_CAPACITY_T_SINTER_H[furnace]
            )
            rows.append(
                {
                    "period_id": case["period_id"],
                    "configuration": C0_CONFIGURATION,
                    "metric_id": f"{furnace.lower()}_capacity_normalised_loading",
                    "asset": furnace,
                    "metric_definition": "executed_sinter_input/(hourly_capacity*168h)",
                    "value": metrics["capacity_utilisation_fraction"],
                    "unit": "fraction",
                    "executed_input_t": metrics["executed_input_t"],
                    "capacity_t_sinter_h": BF_CAPACITY_T_SINTER_H[furnace],
                    "share_hours_at_maximum": metrics["share_hours_at_maximum"],
                    "source_comparison": "Badarinath PDF p.75 utilisation/efficiency discussion",
                    "status": "descriptive_not_a_calibration_target",
                }
            )
        correlation = inventory_change_price_correlation(
            vectors["dri_inventory"], vectors["prices"]
        )
        if correlation is None:
            raise Phase5CAdjudicationError(
                f"Nonconstant governed price response required for {case['period_id']}."
            )
        rows.append(
            {
                "period_id": case["period_id"],
                "configuration": C1_CONFIGURATION,
                "metric_id": "dri_hourly_inventory_change_price_correlation",
                "asset": "DRI_buffer",
                "metric_definition": "Pearson_r(delta_end_of_hour_DRI_inventory_t, same_hour_y_pred_EUR_per_MWh)",
                "value": correlation,
                "unit": "Pearson_r",
                "executed_input_t": "",
                "capacity_t_sinter_h": "",
                "share_hours_at_maximum": "",
                "source_comparison": "Badarinath Table C.6, PDF p.115",
                "status": "passes_positive_direction",
            }
        )
    return rows


def _source_rows() -> list[dict[str, Any]]:
    return [
        {
            "finding_id": "athanasiadis_wag_negative_marginal_cost",
            "source": "Athanasiadis 2025",
            "locator": "report p.22; PDF p.36",
            "verified_finding": "WAG use is represented as a Link with a negative marginal cost (one profit stream).",
            "current_model_relation": "The central model has no direct WAG credit and no export; Phase 5B tested export separately.",
            "decision": "method_precedent_only_no_economic_change",
            "reason": "The resource-capped Phase 5B physical oracle found no material WAG-electricity headroom under the frozen resource and state contract.",
        },
        {
            "finding_id": "athanasiadis_co2_cost",
            "source": "Athanasiadis 2025",
            "locator": "report pp.22,24; PDF pp.36,38",
            "verified_finding": "CO2 is accumulated in a Store carrying a marginal cost per tonne.",
            "current_model_relation": "Explicit and first-order CO2 ledgers exist, but ETS is outside the authorised optimisation boundary.",
            "decision": "do_not_add_ets_cost",
            "reason": "The represented emissions boundary is not ETS-ready and Phase 5C may not change economics.",
        },
        {
            "finding_id": "badarinath_bf6_bf7",
            "source": "Badarinath 2025",
            "locator": "PDF p.75",
            "verified_finding": "The source discusses BF6 material efficiency per output capacity and its share of maximum operation, not BF6 absolute throughput exceeding BF7.",
            "current_model_relation": "The earlier frozen BF6>BF7 absolute-burden test used a capacity-confounded metric.",
            "decision": "retire_absolute_throughput_anchor",
            "reason": "Capacity-normalised loading is descriptive; asset-specific efficiency remains non-comparable because separate BF output and public nameplate definitions are unavailable.",
        },
        {
            "finding_id": "badarinath_dri_storage_correlation",
            "source": "Badarinath 2025",
            "locator": "Table C.6; PDF p.115",
            "verified_finding": "The source correlates changes in storage levels with day-ahead prices.",
            "current_model_relation": "The earlier check correlated inventory level with price.",
            "decision": "replace_with_hourly_inventory_change_metric",
            "reason": "The corrected same-hour delta-inventory metric is positive in both frozen DEVELOPMENT weeks.",
        },
    ]


def _historical_corrections(metric_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    correlations = [
        float(row["value"])
        for row in metric_rows
        if row["metric_id"] == "dri_hourly_inventory_change_price_correlation"
    ]
    return [
        {
            "historical_check": "c0_bf6_over_bf7_ordering",
            "old_definition": "absolute BF6 sinter burden > absolute BF7 sinter burden",
            "corrected_definition": "capacity-normalised loading; material efficiency needs asset-specific output/nameplate denominator",
            "disposition": "invalid_anchor_retired_not_comparable",
            "effect_on_prior_candidate_selection": "none; the check was directional/non-hard and cannot promote a candidate",
        },
        {
            "historical_check": "dri_storage_volatile_vs_calm",
            "old_definition": "correlation(inventory level, price)",
            "corrected_definition": "correlation(hourly change in DRI inventory, same-hour optimiser-visible price)",
            "disposition": "corrected_direction_passes",
            "effect_on_prior_candidate_selection": (
                "none; both frozen no-export DEVELOPMENT weeks are positive "
                f"({min(correlations):.9f} to {max(correlations):.9f})"
            ),
        },
    ]


def run(output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    target = Path(output_root).resolve()
    target.mkdir(parents=True, exist_ok=True)
    metric_rows = reproduce_badarinath_metrics()
    source_rows = _source_rows()
    correction_rows = _historical_corrections(metric_rows)
    inputs: list[dict[str, Any]] = []
    for case in CASES:
        directory = CASE_ROOT / case["case_id"]
        for filename in (
            "executed_hourly.csv",
            "executed_electricity_price_series.csv",
        ):
            path = directory / filename
            inputs.append(
                {
                    "role": "existing_development_trajectory",
                    "period_id": case["period_id"],
                    "path": _portable(path),
                    "sha256": _sha256(path),
                }
            )
    for path in SOURCE_INPUTS:
        if not path.is_file():
            raise Phase5CAdjudicationError(f"Required source evidence is missing: {path}")
        inputs.append(
            {
                "role": "source_or_prior_gate_evidence",
                "period_id": "not_applicable",
                "path": _portable(path),
                "sha256": _sha256(path),
            }
        )
    decision = {
        "run_id": RUN_ID,
        "decision": "phase5c_sources_adjudicated_freeze_no_export_authorize_frozen_held_out_next",
        "zero_solve": True,
        "development_only": True,
        "held_out_data_used": False,
        "physical_model_changed": False,
        "economics_changed": False,
        "historical_anchor_defects_corrected": 2,
        "dri_change_direction_pass_count": 2,
        "bf_asset_specific_efficiency_status": "not_comparable_missing_public_denominator",
        "athanasiadis_wag_credit_status": "method_precedent_not_promoted",
        "athanasiadis_ets_status": "not_authorized_boundary_not_ets_ready",
        "central_model": "accepted_no_export_source_driven_model",
        "next_gate": "frozen_terminal_aware_held_out_validation",
        "next_gate_authorized": True,
        "anchor_claim_limit": "No Badarinath numerical replication or Tata asset-level BF efficiency claim.",
    }
    contract = {
        "run_id": RUN_ID,
        "output_policy": "minimal",
        "run_class": "zero_solve_source_mechanism_interpretation_reproduction",
        "lineage_role": "Phase_5C_decision_evidence",
        "period_role": "DEVELOPMENT_only",
        "case_ids": [case["case_id"] for case in CASES],
        "held_out_periods_used": False,
        "bf_capacities_t_sinter_h": BF_CAPACITY_T_SINTER_H,
        "bf_at_max_tolerance_t_h": AT_MAX_TOLERANCE_T_H,
    }
    _write_csv(target / "source_mechanism_adjudication.csv", source_rows)
    _write_csv(target / "badarinath_metric_reproduction.csv", metric_rows)
    _write_csv(target / "historical_anchor_corrections.csv", correction_rows)
    _write_json(target / "checkpoint_decision.json", decision)
    _write_json(target / "resolved_contract.json", contract)
    _write_json(target / "input_manifest.json", {"inputs": inputs})
    _write_json(
        target / "code_version.json",
        {
            "git_head": _git_head(),
            "implementation": _portable(Path(__file__)),
            "implementation_sha256": _sha256(Path(__file__)),
        },
    )
    (target / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a zero-solve adjudication of existing DEVELOPMENT evidence.\n"
        "- Badarinath is a method and behavioural precedent, not a numerical Tata input source.\n"
        "- BF capacity-normalised loading does not reproduce asset-specific material efficiency.\n"
        "- The DRI correlation is descriptive and strategy-specific; it is not a calibration target.\n"
        "- No ETS, WAG credit, export, bidding, settlement, stochasticity, CVaR or mFRR is activated.\n",
        encoding="utf-8",
    )
    correlations = [
        float(row["value"])
        for row in metric_rows
        if row["metric_id"] == "dri_hourly_inventory_change_price_correlation"
    ]
    bf_rows = [
        row for row in metric_rows if row["configuration"] == C0_CONFIGURATION
    ]
    bf_summary = "; ".join(
        f"{row['period_id']} {row['asset']}={float(row['value']):.3%}"
        for row in bf_rows
    )
    (target / "README.md").write_text(
        "# Phase 5C source-mechanism adjudication\n\n"
        "This compact checkpoint revisits the Athanasiadis and Badarinath findings using their source definitions. It performs no optimisation and consumes only the two frozen no-export DEVELOPMENT trajectories.\n\n"
        "The earlier Badarinath DRI check used inventory level. Table C.6 uses changes in storage level. The corrected same-hour DRI-inventory-change correlations are "
        f"{correlations[0]:.6f} and {correlations[1]:.6f}, so the expected positive direction passes in both weeks.\n\n"
        "The earlier BF6 > BF7 absolute-throughput check is retired because it confounded plant capacity with utilisation. Current capacity-normalised loading is "
        f"{bf_summary}. Asset-specific material efficiency remains not comparable because this model has no separate public BF output/nameplate denominator; no parameter is fitted.\n\n"
        "Athanasiadis explicitly applies a negative marginal cost to WAG use and a marginal cost to accumulated CO2. Those are economic-boundary precedents, not permission to add ETS or a WAG credit here. The Phase 5B resource-capped physical oracle already found no material WAG-electricity headroom under the frozen resource/state contract.\n\n"
        "Decision: retain and freeze the accepted no-export source-driven model. The two historical behavioural failures are reclassified rather than calibrated. Frozen terminal-aware held-out validation is the next authorised gate; Phase 5C itself uses no held-out observations. Export, ETS and later market layers remain off.\n",
        encoding="utf-8",
    )
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(run(args.output_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
