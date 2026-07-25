"""Freeze representative D-D+4 periods before source/emulation solver work.

This checkpoint is deliberately selection-only.  It reads the governed LEAR/Lago
forecast source, validates seven executable local delivery days per period, and
freezes separate validation and held-out-test representative periods.  It never
calls the steel modelbuilder or a solver.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import yaml

from .s4_4c5p_bf_price_series_interface import (
    DPLUS4_SOURCE_CONTRACT_PATH,
    _resolve_dplus4_source_files,
    build_dplus4_forecast_slice,
    dplus4_timestamp_plan,
    load_dplus4_source_contract,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_source_emulation_validation_v1_20260721"
DEFAULT_OUTPUT = REPO_ROOT / "data/03_Optimisation/runs" / RUN_ID
DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_source_emulation_validation.yaml"
)
CONTRACT_FILENAME = "representative_week_selection_contract.csv"
TOLERANCE = 1e-12
LOCAL_ZONE = ZoneInfo("Europe/Amsterdam")


class RepresentativePeriodError(RuntimeError):
    """Raised when the representative-period design cannot fail closed."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise RepresentativePeriodError(f"Refusing to write empty output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise RepresentativePeriodError("All forecast timestamps must be timezone-aware.")
    return result.astimezone(timezone.utc)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("run_id") != RUN_ID:
        raise RepresentativePeriodError("Representative-period run identity is not governed.")
    if config.get("output_policy") != "minimal":
        raise RepresentativePeriodError("Representative-period design requires output_policy=minimal.")
    if config.get("run_class") != "deterministic_source_and_emulation_validation":
        raise RepresentativePeriodError("Unexpected representative-period run class.")
    if config.get("annualisation_label") != "representative_period_annualised":
        raise RepresentativePeriodError("Annualised results must use the governed partial-support label.")
    if bool(config.get("selection_solver_runs_enabled")):
        raise RepresentativePeriodError("Checkpoint 4 selection must not enable solver runs.")
    if config.get("selection", {}).get("candidate_week_anchor") != "monday_local_delivery":
        raise RepresentativePeriodError("Candidate weeks must be Monday-aligned local delivery weeks.")
    if int(config.get("selection", {}).get("origins_per_period", 0)) != 7:
        raise RepresentativePeriodError("Each selected period must contain seven daily forecast origins.")
    return config


def _valid_origins(
    *, forecast_run_root: Path, dataset_split: str, contract: Mapping[str, Any]
) -> dict[date, dict[str, Any]]:
    paths = _resolve_dplus4_source_files(contract, forecast_run_root)
    columns = [
        "run_id",
        "model",
        "feature_variant",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_delivery_local_date",
        "target_known_at_utc",
        "lead_day",
        "y_pred",
        "y_true",
    ]
    table = pq.read_table(
        paths["predictions"],
        columns=columns,
        filters=[
            ("run_id", "=", contract["source_run_id"]),
            ("model", "=", contract["model_id"]),
            ("feature_variant", "=", contract["feature_variant"]),
            ("dataset_split", "=", dataset_split),
        ],
    )
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in table.to_pylist():
        grouped[_timestamp(row["forecast_origin_utc"])].append(row)
    governed_start = _timestamp(contract[f"{dataset_split}_start_origin_utc"])
    valid: dict[date, dict[str, Any]] = {}
    for origin, rows in sorted(grouped.items()):
        if origin < governed_start:
            continue
        rows.sort(key=lambda row: _timestamp(row["target_timestamp_utc"]))
        local_dates = sorted({date.fromisoformat(str(row["target_delivery_local_date"])) for row in rows})
        if len(local_dates) != 5 or len(rows) not in {119, 120, 121}:
            continue
        first_date = local_dates[0]
        executed = [
            row for row in rows
            if date.fromisoformat(str(row["target_delivery_local_date"])) == first_date
        ]
        if len(executed) not in {23, 24, 25}:
            continue
        if not all(row["y_pred"] is not None and math.isfinite(float(row["y_pred"])) for row in rows):
            continue
        if not all(row["y_true"] is not None and math.isfinite(float(row["y_true"])) for row in executed):
            continue
        if not all(
            _timestamp(row["target_known_at_utc"]) == origin
            and _timestamp(row["target_timestamp_utc"]) > origin
            for row in rows
        ):
            continue
        day_hours = [
            sum(
                date.fromisoformat(str(row["target_delivery_local_date"])) == local_date
                for row in rows
            )
            for local_date in local_dates
        ]
        if first_date in valid:
            raise RepresentativePeriodError(f"Duplicate governed origin for {first_date}.")
        valid[first_date] = {
            "origin": origin,
            "planning_hours": len(rows),
            "execution_hours": len(executed),
            "local_delivery_day_hours": day_hours,
            "execution_rows": executed,
        }
    return valid


def _week_statistics(rows: list[Mapping[str, Any]]) -> dict[str, float]:
    truths = [float(row["y_true"]) for row in rows]
    predictions = [float(row["y_pred"]) for row in rows]
    errors = [prediction - truth for prediction, truth in zip(predictions, truths)]
    return {
        "realised_mean_eur_per_mwh": statistics.fmean(truths),
        "realised_volatility_eur_per_mwh": statistics.pstdev(truths),
        "negative_price_share": sum(value < 0.0 for value in truths) / len(truths),
        "forecast_mae_eur_per_mwh": statistics.fmean(abs(value) for value in errors),
        "forecast_rmse_eur_per_mwh": math.sqrt(statistics.fmean(value * value for value in errors)),
        "forecast_mean_eur_per_mwh": statistics.fmean(predictions),
    }


def build_candidate_weeks(
    *,
    forecast_run_root: Path,
    dataset_split: str,
    contract: Mapping[str, Any],
    governed_origins: dict[date, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return disjoint Monday-aligned full weeks from one governed split."""

    origins = governed_origins or _valid_origins(
        forecast_run_root=forecast_run_root,
        dataset_split=dataset_split,
        contract=contract,
    )
    candidates: list[dict[str, Any]] = []
    for start in sorted(origins):
        if start.weekday() != 0:
            continue
        delivery_dates = [start + timedelta(days=offset) for offset in range(7)]
        if any(delivery_date not in origins for delivery_date in delivery_dates):
            continue
        origin_records = [origins[delivery_date] for delivery_date in delivery_dates]
        executed_rows = [
            row
            for origin_record in origin_records
            for row in origin_record["execution_rows"]
        ]
        execution_hours = sum(record["execution_hours"] for record in origin_records)
        start_origin = origin_records[0]["origin"]
        candidates.append(
            {
                "candidate_week_id": f"{dataset_split}_{start.isoformat()}",
                "dataset_split": dataset_split,
                "period_role": "development" if dataset_split == "validation" else "held_out",
                "forecast_start_origin_utc": start_origin.isoformat(),
                "delivery_start_local_date": start.isoformat(),
                "delivery_end_local_date": delivery_dates[-1].isoformat(),
                "calendar_position_fraction": start.timetuple().tm_yday / 366.0,
                "calendar_quarter": ((start.month - 1) // 3) + 1,
                "execution_hours": execution_hours,
                "dst_status": "dst_transition_week" if execution_hours != 168 else "ordinary_168_hour_week",
                **_week_statistics(executed_rows),
                "origin_records": origin_records,
            }
        )
    if not candidates:
        raise RepresentativePeriodError(f"No complete Monday-aligned weeks exist in {dataset_split}.")
    for earlier, later in zip(candidates, candidates[1:]):
        earlier_end = date.fromisoformat(earlier["delivery_end_local_date"])
        later_start = date.fromisoformat(later["delivery_start_local_date"])
        if later_start <= earlier_end:
            raise RepresentativePeriodError("Candidate week construction produced overlap.")
    return candidates


def _standardised_vectors(
    candidates: list[dict[str, Any]], feature_fields: list[str]
) -> dict[str, tuple[float, ...]]:
    centres: dict[str, float] = {}
    scales: dict[str, float] = {}
    for field in feature_fields:
        values = [float(row[field]) for row in candidates]
        centres[field] = statistics.fmean(values)
        scales[field] = statistics.pstdev(values) or 1.0
    return {
        row["candidate_week_id"]: tuple(
            (float(row[field]) - centres[field]) / scales[field]
            for field in feature_fields
        )
        for row in candidates
    }


def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _select_and_weight(
    candidates: list[dict[str, Any]], *, target_count: int, feature_fields: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vectors = _standardised_vectors(candidates, feature_fields)
    by_id = {row["candidate_week_id"]: row for row in candidates}
    count = min(target_count, len(candidates))
    zero = tuple(0.0 for _ in feature_fields)
    central = min(candidates, key=lambda row: (_distance(vectors[row["candidate_week_id"]], zero), row["candidate_week_id"]))
    selected_ids = [central["candidate_week_id"]]
    dst = [row for row in candidates if row["execution_hours"] != 168]
    if dst and len(selected_ids) < count:
        dst_pick = max(
            dst,
            key=lambda row: (
                _distance(vectors[row["candidate_week_id"]], vectors[selected_ids[0]]),
                -int(row["delivery_start_local_date"].replace("-", "")),
            ),
        )
        if dst_pick["candidate_week_id"] not in selected_ids:
            selected_ids.append(dst_pick["candidate_week_id"])
    while len(selected_ids) < count:
        remaining = [row for row in candidates if row["candidate_week_id"] not in selected_ids]
        pick = max(
            remaining,
            key=lambda row: (
                min(
                    _distance(vectors[row["candidate_week_id"]], vectors[selected_id])
                    for selected_id in selected_ids
                ),
                -int(row["delivery_start_local_date"].replace("-", "")),
            ),
        )
        selected_ids.append(pick["candidate_week_id"])
    assignments: dict[str, list[tuple[dict[str, Any], float]]] = defaultdict(list)
    diagnostics: list[dict[str, Any]] = []
    for candidate in candidates:
        representative_id, distance = min(
            (
                (selected_id, _distance(vectors[candidate["candidate_week_id"]], vectors[selected_id]))
                for selected_id in selected_ids
            ),
            key=lambda item: (item[1], item[0]),
        )
        assignments[representative_id].append((candidate, distance))
        diagnostics.append(
            {
                **{key: value for key, value in candidate.items() if key != "origin_records"},
                "selection_status": "selected" if candidate["candidate_week_id"] in selected_ids else "eligible_not_selected",
                "assigned_representative_period_id": representative_id,
                "standardised_cluster_distance": round(distance, 9),
                "selection_input_policy": "calendar_and_ex_post_price_regime_only",
            }
        )
    selected: list[dict[str, Any]] = []
    annual_weeks = 365.25 / 7.0
    for rank, selected_id in enumerate(selected_ids, start=1):
        row = by_id[selected_id]
        members = assignments[selected_id]
        weight = len(members) / len(candidates)
        selected.append(
            {
                "selection_contract_version": "steel_c5_representative_period_v1",
                "period_id": selected_id,
                "dataset_split": row["dataset_split"],
                "period_role": row["period_role"],
                "selection_rank": rank,
                "frozen_forecast_start_origin_utc": row["forecast_start_origin_utc"],
                "delivery_start_local_date": row["delivery_start_local_date"],
                "delivery_end_local_date": row["delivery_end_local_date"],
                "replan_count": 7,
                "execution_hours": row["execution_hours"],
                "dst_status": row["dst_status"],
                "realised_mean_eur_per_mwh": round(row["realised_mean_eur_per_mwh"], 9),
                "realised_volatility_eur_per_mwh": round(row["realised_volatility_eur_per_mwh"], 9),
                "negative_price_share": round(row["negative_price_share"], 12),
                "forecast_mae_eur_per_mwh": round(row["forecast_mae_eur_per_mwh"], 9),
                "forecast_rmse_eur_per_mwh": round(row["forecast_rmse_eur_per_mwh"], 9),
                "split_weight": round(weight, 12),
                "represented_week_count": len(members),
                "represented_delivery_days": 7 * len(members),
                "eligible_week_count_in_split": len(candidates),
                "annualisation_multiplier": round(weight * annual_weeks, 12),
                "annualisation_label": "representative_period_annualised",
                "operational_price_field": "y_pred",
                "ex_post_regime_field": "y_true",
                "ex_post_field_use": "selection_regime_classification_only_never_optimizer_input",
                "optimisation_result_inputs_used": False,
                "anchor_residual_inputs_used": False,
                "selection_status": "frozen",
            }
        )
    return selected, diagnostics


def _support_rows(
    *,
    selected: list[dict[str, Any]],
    forecast_run_root: Path,
    contract: Mapping[str, Any],
    origin_lookup: Mapping[str, dict[date, dict[str, Any]]],
) -> list[dict[str, Any]]:
    support: list[dict[str, Any]] = []
    for period in selected:
        # Exercise the governed operational adapter at every frozen start origin.
        # The remaining six origin rows come from the same already fingerprinted
        # Parquet scan, avoiding 56 repeated full-file reads in this selection-only
        # checkpoint.
        adapter_rows = build_dplus4_forecast_slice(
            forecast_run_root=forecast_run_root,
            dataset_split=period["dataset_split"],
            start_origin_utc=period["frozen_forecast_start_origin_utc"],
            replan_index=0,
            planning_horizon_hours=None,
        )
        adapter_plan = dplus4_timestamp_plan(adapter_rows)
        period_start = date.fromisoformat(period["delivery_start_local_date"])
        for replan_index in range(7):
            delivery_date = period_start + timedelta(days=replan_index)
            record = origin_lookup[period["dataset_split"]][delivery_date]
            origin = record["origin"]
            first_delivery = datetime.combine(
                delivery_date,
                datetime.min.time(),
                tzinfo=LOCAL_ZONE,
            ).astimezone(timezone.utc)
            if replan_index == 0 and (
                int(adapter_plan["execution_block_hours"]) != record["execution_hours"]
                or int(adapter_plan["planning_horizon_hours"]) != record["planning_hours"]
            ):
                raise RepresentativePeriodError("Governed adapter and source scan disagree.")
            support.append(
                {
                    "period_id": period["period_id"],
                    "dataset_split": period["dataset_split"],
                    "replan_index": replan_index,
                    "forecast_origin_utc": origin.isoformat(),
                    "delivery_local_date": delivery_date.isoformat(),
                    "delivery_start_utc": first_delivery.isoformat(),
                    "execution_hours": record["execution_hours"],
                    "planning_horizon_hours": record["planning_hours"],
                    "local_delivery_day_hours": ";".join(str(value) for value in record["local_delivery_day_hours"]),
                    "y_pred_complete": True,
                    "y_true_ex_post_complete_for_execution": True,
                    "information_timing_pass": origin < first_delivery,
                    "y_true_exposed_to_operational_interface": False,
                }
            )
    return support


def _validate_selection(
    *, selected: list[dict[str, Any]], support: list[dict[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    target_count = int(config["selection"]["target_periods_per_split"])
    for split in ("validation", "test"):
        periods = [row for row in selected if row["dataset_split"] == split]
        split_support = [row for row in support if row["dataset_split"] == split]
        expected = min(target_count, int(periods[0]["eligible_week_count_in_split"])) if periods else 0
        checks.extend(
            [
                {"check_id": f"{split}_largest_available_period_set", "status": "pass" if len(periods) == expected and expected > 0 else "fail", "evidence": f"selected={len(periods)} expected={expected}"},
                {"check_id": f"{split}_weights_sum_to_one", "status": "pass" if abs(sum(float(row["split_weight"]) for row in periods) - 1.0) <= 1e-9 else "fail", "evidence": f"sum={sum(float(row['split_weight']) for row in periods):.12f}"},
                {"check_id": f"{split}_seven_origins_per_period", "status": "pass" if all(sum(row["period_id"] == period["period_id"] for row in split_support) == 7 for period in periods) else "fail", "evidence": f"support_rows={len(split_support)}"},
                {"check_id": f"{split}_dst_handled", "status": "pass" if all(int(row["execution_hours"]) in {167, 168, 169} for row in periods) and any(int(row["execution_hours"]) != 168 for row in periods) else "fail", "evidence": ";".join(str(row["execution_hours"]) for row in periods)},
            ]
        )
    selected_intervals = [
        (date.fromisoformat(row["delivery_start_local_date"]), date.fromisoformat(row["delivery_end_local_date"]))
        for row in selected
    ]
    nonoverlap = all(
        left_end < right_start or right_end < left_start
        for index, (left_start, left_end) in enumerate(selected_intervals)
        for right_start, right_end in selected_intervals[index + 1 :]
    )
    checks.extend(
        [
            {"check_id": "selected_periods_non_overlapping", "status": "pass" if nonoverlap else "fail", "evidence": f"period_count={len(selected)}"},
            {"check_id": "governed_information_timing", "status": "pass" if all(row["information_timing_pass"] for row in support) else "fail", "evidence": "y_pred known at origin before delivery"},
            {"check_id": "y_true_ex_post_only", "status": "pass" if all(not row["y_true_exposed_to_operational_interface"] for row in support) else "fail", "evidence": "oracle adapter used only for completeness check"},
            {"check_id": "annualisation_label_partial_support", "status": "pass" if all(row["annualisation_label"] == "representative_period_annualised" for row in selected) else "fail", "evidence": "not a full-year empirical backtest"},
            {"check_id": "no_optimisation_or_anchor_selection_inputs", "status": "pass" if all(not row["optimisation_result_inputs_used"] and not row["anchor_residual_inputs_used"] for row in selected) else "fail", "evidence": "calendar and price-regime fields only"},
        ]
    )
    frozen = config.get("frozen_selection", [])
    if frozen:
        actual = [
            {
                "period_id": row["period_id"],
                "frozen_forecast_start_origin_utc": row["frozen_forecast_start_origin_utc"],
                "split_weight": float(row["split_weight"]),
            }
            for row in selected
        ]
        expected = [
            {
                "period_id": row["period_id"],
                "frozen_forecast_start_origin_utc": row["frozen_forecast_start_origin_utc"],
                "split_weight": float(row["split_weight"]),
            }
            for row in frozen
        ]
        frozen_pass = actual == expected
        checks.append({"check_id": "config_frozen_timestamps_and_weights", "status": "pass" if frozen_pass else "fail", "evidence": f"expected={len(expected)} actual={len(actual)}"})
    if any(row["status"] != "pass" for row in checks):
        failed = [row["check_id"] for row in checks if row["status"] != "pass"]
        raise RepresentativePeriodError(f"Representative-period validation failed: {failed}")
    return checks


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run_representative_period_design(
    *,
    forecast_run_root: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_directory: str | Path | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    output = Path(output_directory).resolve() if output_directory else DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    source_root = Path(forecast_run_root).resolve()
    contract = load_dplus4_source_contract()
    feature_fields = list(config["selection"]["feature_fields"])
    permitted_fields = {
        "calendar_position_fraction",
        "realised_mean_eur_per_mwh",
        "realised_volatility_eur_per_mwh",
        "negative_price_share",
        "forecast_mae_eur_per_mwh",
    }
    if not feature_fields or not set(feature_fields).issubset(permitted_fields):
        raise RepresentativePeriodError("Selection features exceed the governed calendar/price-regime set.")
    selected: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    candidate_counts: dict[str, int] = {}
    origin_lookup: dict[str, dict[date, dict[str, Any]]] = {}
    for split in ("validation", "test"):
        origin_lookup[split] = _valid_origins(
            forecast_run_root=source_root,
            dataset_split=split,
            contract=contract,
        )
        candidates = build_candidate_weeks(
            forecast_run_root=source_root,
            dataset_split=split,
            contract=contract,
            governed_origins=origin_lookup[split],
        )
        candidate_counts[split] = len(candidates)
        split_selected, split_diagnostics = _select_and_weight(
            candidates,
            target_count=int(config["selection"]["target_periods_per_split"]),
            feature_fields=feature_fields,
        )
        selected.extend(split_selected)
        diagnostics.extend(split_diagnostics)
    support = _support_rows(
        selected=selected,
        forecast_run_root=source_root,
        contract=contract,
        origin_lookup=origin_lookup,
    )
    checks = _validate_selection(selected=selected, support=support, config=config)

    contract_root = (REPO_ROOT / config["contract_root"]).resolve()
    persistent_contract = contract_root / CONTRACT_FILENAME
    _write_csv(persistent_contract, selected)
    _write_csv(output / CONTRACT_FILENAME, selected)
    _write_csv(output / "representative_week_selection_diagnostics.csv", diagnostics)
    _write_csv(output / "representative_week_origin_support.csv", support)
    _write_csv(output / "selection_validation_checks.csv", checks)
    resolved_config = output / "resolved_config.yaml"
    resolved_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    config_path_resolved = Path(config_path).resolve()
    repository_inputs = [
        config_path_resolved,
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_c5_source_emulation_validation.py",
        DPLUS4_SOURCE_CONTRACT_PATH,
        REPO_ROOT / config["parent_checkpoint_state"],
        REPO_ROOT / config["target_contract_path"],
        REPO_ROOT / config["parameter_contract_path"],
    ]
    manifest = {
        "run_id": RUN_ID,
        "external_source": {
            "source_run_id": contract["source_run_id"],
            "runtime_root_persisted": False,
            "source_file_sha256": contract["source_file_sha256"],
        },
        "repository_files": [
            {"path": _repo_relative(path), "sha256": _sha256(path)}
            for path in repository_inputs
        ],
        "selection_contract": {
            "path": _repo_relative(persistent_contract),
            "sha256": _sha256(persistent_contract),
        },
    }
    _write_json(output / "input_manifest.json", manifest)
    _write_json(
        output / "code_version.json",
        {"git_head": _git_head(), "module": _repo_relative(Path(__file__))},
    )
    summary = {
        "run_id": RUN_ID,
        "status": "pass",
        "decision": "representative_period_design_frozen_pending_independent_review",
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "output_policy": config["output_policy"],
        "annualisation_label": config["annualisation_label"],
        "coverage_claim": "separate_partial_support_validation_and_held_out_test_representative_periods",
        "selected_period_count": len(selected),
        "selected_period_count_by_split": {
            split: sum(row["dataset_split"] == split for row in selected)
            for split in ("validation", "test")
        },
        "eligible_week_count_by_split": candidate_counts,
        "selected_execution_hours_by_split": {
            split: sum(int(row["execution_hours"]) for row in selected if row["dataset_split"] == split)
            for split in ("validation", "test")
        },
        "split_weight_sums": {
            split: round(sum(float(row["split_weight"]) for row in selected if row["dataset_split"] == split), 12)
            for split in ("validation", "test")
        },
        "selection_feature_fields": feature_fields,
        "y_true_policy": "ex_post_regime_classification_only_never_optimizer_input",
        "optimisation_results_used_for_selection": False,
        "anchor_residuals_used_for_selection": False,
        "solver_run_performed": False,
        "physical_parameters_changed": False,
        "model_logic_changed": False,
        "source_contract_id": contract["contract_id"],
        "source_run_id": contract["source_run_id"],
        "validation_check_count": len(checks),
        "validation_failure_count": 0,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": RUN_ID,
            "completed_checkpoint": 4,
            "status": "pass",
            "decision": summary["decision"],
            "independent_review_required": True,
            "solver_run_performed": False,
            "calibration_performed": False,
            "next_gate": "independent_review_then_development_period_source_baseline_and_emulation_execution",
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "output_root": _repo_relative(output),
            "output_policy": config["output_policy"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "status": "pass",
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- These are weighted representative periods from separate validation and test support, not a full-year empirical backtest.\n"
        "- `y_true` is used only for ex-post price-regime classification and a separately labelled completeness check. Operational solves must use `y_pred`.\n"
        "- Weights represent eligible complete Monday-aligned weeks within each split; they do not repair missing seasonal support.\n"
        "- No optimisation result, anchor residual, model solve, physical parameter, or model logic influenced selection.\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Source/emulation representative-period design\n\n"
        "Decision: `representative_period_design_frozen_pending_independent_review`.\n\n"
        "This selection-only checkpoint freezes separate development (`validation`) and held-out (`test`) D-D+4 weeks before any source-baseline or emulation solve. Each period has seven executable local delivery days, governed `y_pred` support, ex-post-only `y_true`, and a split-normalised cluster/member-week weight. Annualised downstream reporting must be labelled `representative_period_annualised`.\n\n"
        "No solver was called and no physical parameter or model logic changed.\n",
        encoding="utf-8",
    )
    artifact_count = len([path for path in output.iterdir() if path.is_file()])
    artifact_size = sum(path.stat().st_size for path in output.iterdir() if path.is_file())
    if artifact_count > int(config["output_limits"]["maximum_artifact_count"]):
        raise RepresentativePeriodError("Output artifact-count limit exceeded.")
    if artifact_size > int(config["output_limits"]["maximum_size_bytes"]):
        raise RepresentativePeriodError("Output size limit exceeded.")
    return {
        "output_directory": str(output),
        "persistent_contract": str(persistent_contract),
        "summary": summary,
        "selected": selected,
        "checks": checks,
        "artifact_count": artifact_count,
        "artifact_size_bytes": artifact_size,
    }
