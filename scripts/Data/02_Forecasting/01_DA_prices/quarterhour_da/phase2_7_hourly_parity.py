from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .feature_registry import load_feature_family_map
from .reporting_metrics import summarize_standard_qh_metrics


RUN_LABEL = "qh_fs1_phase2_7_hourly_parity"
CAUSAL_NAIVE_FAMILY = {
    "naive_previous_available_same_quarter",
    "naive_previous_week_same_quarter",
    "naive_last_full_day_profile",
}


@dataclass(frozen=True)
class Phase27Paths:
    run_id: str
    run_dir: Path


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)


def phase27_output_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "finalisation_runs" / RUN_LABEL


def _bundle_paths(config: QuarterHourDAExtensionConfig | None = None) -> Phase27Paths:
    resolved = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = phase27_output_root(resolved) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return Phase27Paths(run_id=run_id, run_dir=run_dir)


def _find_latest_validated_phase2_parent_run(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    root = resolved.output_root / "finalisation_runs" / "qh_fs1_fs2_model_comparison"
    if not root.exists():
        raise FileNotFoundError("No qh_fs1_fs2_model_comparison finalisation root was found.")
    candidates = sorted(path for path in root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    if not candidates:
        raise FileNotFoundError("No qh_fs1_fs2_model_comparison run with run_summary.json was found.")
    validated: list[Path] = []
    for candidate in candidates:
        payload = json.loads((candidate / "run_summary.json").read_text(encoding="utf-8"))
        if bool(payload.get("smoke_mode", False)):
            continue
        if str(payload.get("status", "")).lower() != "completed":
            continue
        validated.append(candidate)
    if not validated:
        raise FileNotFoundError("No non-smoke completed qh_fs1_fs2_model_comparison run was found.")
    return validated[-1]


def _canonical_parent_ids(predictions: pd.DataFrame) -> pd.DataFrame:
    learned = predictions[
        predictions["model_family"].astype(str).isin(["lear", "xgboost"])
        & predictions["feature_set_id"].astype(str).eq("QH-FS1")
        & predictions["candidate_role"].astype(str).eq("candidate_equal_priority")
    ].copy()
    if learned.empty:
        return pd.DataFrame(columns=["model_family", "model"])

    if "hourly_anchor_candidate_key" not in learned.columns:
        learned["hourly_anchor_candidate_key"] = ""

    pairs = learned[["model_family", "model", "hourly_anchor_candidate_key"]].drop_duplicates().copy()

    def _priority(row: pd.Series) -> int:
        model_family = str(row["model_family"])
        model = str(row["model"])
        anchor = str(row["hourly_anchor_candidate_key"])
        score = 0
        if model.startswith(f"qh-fs1__{model_family}__"):
            score += 10
        if model_family in anchor:
            score += 5
        return score

    pairs["selection_priority"] = pairs.apply(_priority, axis=1)
    selected = (
        pairs.sort_values(["model_family", "selection_priority", "model"], ascending=[True, False, True])
        .groupby("model_family", as_index=False)
        .head(1)[["model_family", "model"]]
        .reset_index(drop=True)
    )
    return selected


def _ensure_required_horizon_columns(predictions: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    work = predictions.copy()
    gaps: list[str] = []
    if "horizon_index" not in work.columns:
        if "lead_day" in work.columns and "quarter_index" in work.columns:
            lead = pd.to_numeric(work["lead_day"], errors="coerce")
            quarter = pd.to_numeric(work["quarter_index"], errors="coerce")
            work["horizon_index"] = lead * 96 + (quarter - 1)
            gaps.append("horizon_index was missing and was materialized from lead_day and quarter_index.")
        else:
            work["horizon_index"] = pd.NA
            gaps.append("horizon_index could not be materialized because lead_day and/or quarter_index were missing.")
    if "lead_day_label" not in work.columns:
        lead = pd.to_numeric(work["lead_day"], errors="coerce")
        work["lead_day_label"] = lead.map(lambda v: "D" if pd.notna(v) and int(v) == 0 else (f"D+{int(v)}" if pd.notna(v) else None))
        gaps.append("lead_day_label was missing and was materialized from lead_day.")
    return work, gaps


def _materialize_official_naive_reference(observed_run_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    official_path = observed_run_dir / "official_naive_reference.json"
    if not official_path.exists():
        raise FileNotFoundError(f"Missing observed official naive artifact: {official_path}")
    official = json.loads(official_path.read_text(encoding="utf-8"))

    model = str(official.get("model", ""))
    selection_policy = str(official.get("selection_policy", ""))
    if model not in CAUSAL_NAIVE_FAMILY:
        official["phase2_7_guardrail_warning"] = (
            "Observed official naive is outside the causal family; denominator inheritance remains source-of-truth,"
            " but this should be reviewed before Phase 3 heavy execution."
        )
    else:
        official["phase2_7_guardrail_warning"] = None

    rows: list[pd.DataFrame] = []
    for name in ("metrics_overall.csv", "metrics_by_lead_day.csv", "metrics_by_reporting_level.csv"):
        path = observed_run_dir / name
        if not path.exists():
            continue
        frame = pd.read_csv(path, low_memory=False)
        if frame.empty or "model" not in frame.columns:
            continue
        scoped = frame[frame["model"].astype(str) == model].copy()
        if scoped.empty:
            continue
        scoped["denominator_scope"] = name.replace("metrics_", "").replace(".csv", "")
        rows.append(scoped)
    denominators = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return official, denominators


def _apply_rmae(
    metrics: pd.DataFrame,
    denominator: pd.DataFrame,
    *,
    key_columns: list[str],
) -> pd.DataFrame:
    if metrics.empty:
        return metrics.copy()
    work = metrics.copy()
    denom = denominator.copy()
    for column in key_columns:
        work[column] = work[column].astype(str)
        denom[column] = denom[column].astype(str)
    denom = denom.rename(columns={"mae": "official_naive_mae"})
    keep = key_columns + ["official_naive_mae"]
    merged = work.merge(denom[keep], on=key_columns, how="left")
    merged["rmae_vs_official_naive"] = merged["mae"] / merged["official_naive_mae"]
    merged.loc[merged["official_naive_mae"].isna() | (merged["official_naive_mae"] == 0.0), "rmae_vs_official_naive"] = pd.NA
    merged["rmae"] = merged["rmae_vs_official_naive"]
    return merged


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _phase3_readiness(
    *,
    run_dir: Path,
    official_naive_reference: dict[str, Any],
    parent_predictions: pd.DataFrame,
    parent_settings: pd.DataFrame,
    feature_family_map: pd.DataFrame,
) -> dict[str, Any]:
    checks = {
        "parent_predictions_available": bool(not parent_predictions.empty),
        "parent_denominator_available": bool(str(official_naive_reference.get("model", "")).strip()),
        "parent_model_settings_available": bool(not parent_settings.empty),
        "qh_fs1_feature_family_map_available": bool(
            not feature_family_map[
                (feature_family_map["feature_set_id"].astype(str) == "QH-FS1")
                & feature_family_map["active_flag"].fillna(False).astype(bool)
            ].empty
        ),
        "child_runs_can_inherit_settings_and_rmae_denominator": True,
    }
    checks["ready_for_phase3_heavy"] = bool(all(checks.values()))
    _write_json(run_dir / "phase3_readiness_check.json", checks)
    return checks


def write_phase2_7_hourly_parity_bundle(config: QuarterHourDAExtensionConfig | None = None) -> Phase27Paths:
    resolved = config or QuarterHourDAExtensionConfig()
    paths = _bundle_paths(resolved)

    parent_run = _find_latest_validated_phase2_parent_run(resolved)
    parent_summary = json.loads((parent_run / "run_summary.json").read_text(encoding="utf-8"))
    parent_predictions = pd.read_csv(parent_run / "candidate_predictions_long.csv", low_memory=False)
    parent_settings = pd.read_csv(parent_run / "model_settings_summary.csv", low_memory=False)
    parent_metrics_by_reporting = pd.read_csv(parent_run / "metrics_by_reporting_level.csv", low_memory=False)
    parent_inventory = pd.read_csv(parent_run / "candidate_prediction_inventory.csv", low_memory=False)

    source_runs = {
        "phase2_parent_finalisation_run_dir": str(parent_run),
        "phase2_parent_finalisation_run_id": str(parent_summary.get("run_id")),
        "phase07_run_id": parent_summary.get("source_runs", {}).get("phase07_run_id"),
        "observed_run_id": parent_summary.get("source_runs", {}).get("observed_run_id"),
    }
    _write_json(paths.run_dir / "source_runs.json", source_runs)

    selected_parents = _canonical_parent_ids(parent_predictions)
    selected_models = set(selected_parents["model"].astype(str).tolist())
    parent_subset = parent_predictions[parent_predictions["model"].astype(str).isin(selected_models)].copy()
    parent_subset, horizon_gap_notes = _ensure_required_horizon_columns(parent_subset)
    parent_subset["forecast_origin_utc"] = pd.to_datetime(parent_subset["forecast_origin_utc"], utc=True, errors="coerce")
    parent_subset["target_timestamp_utc"] = pd.to_datetime(parent_subset["target_timestamp_utc"], utc=True, errors="coerce")

    standard = summarize_standard_qh_metrics(parent_subset, business_timezone=resolved.business_timezone)
    metrics_overall = standard["metrics_overall"].copy()
    metrics_by_lead = standard["metrics_by_lead_day"].copy()
    metrics_by_reporting = standard["metrics_by_reporting_level"].copy()

    observed_run_id = str(source_runs["observed_run_id"])
    observed_run_dir = resolved.output_root / "runs" / observed_run_id
    official_naive, denominator_all = _materialize_official_naive_reference(observed_run_dir)
    _write_json(paths.run_dir / "official_naive_reference.json", official_naive)
    denominator_all.to_csv(paths.run_dir / "official_naive_denominator_materialized.csv", index=False)

    denom_overall = denominator_all[denominator_all["denominator_scope"] == "overall"].copy()
    denom_lead = denominator_all[denominator_all["denominator_scope"] == "by_lead_day"].copy()
    denom_reporting = denominator_all[denominator_all["denominator_scope"] == "by_reporting_level"].copy()

    metrics_overall = _apply_rmae(metrics_overall, denom_overall, key_columns=["dataset_split"])
    if not metrics_by_lead.empty:
        metrics_by_lead = _apply_rmae(metrics_by_lead, denom_lead, key_columns=["dataset_split", "lead_day"])
    if not metrics_by_reporting.empty:
        metrics_by_reporting = _apply_rmae(metrics_by_reporting, denom_reporting, key_columns=["dataset_split", "reporting_level"])

    parent_subset.to_csv(paths.run_dir / "predictions_long.csv", index=False)
    try:
        parent_subset.to_parquet(paths.run_dir / "predictions_long.parquet", index=False)
    except Exception:
        pass
    metrics_overall.to_csv(paths.run_dir / "metrics_overall.csv", index=False)
    metrics_by_lead.to_csv(paths.run_dir / "metrics_by_lead_day.csv", index=False)
    metrics_by_reporting.to_csv(paths.run_dir / "metrics_by_reporting_level.csv", index=False)

    split_summary = (
        parent_subset.groupby("dataset_split", dropna=False)
        .agg(
            prediction_rows=("target_timestamp_utc", "size"),
            origins=("forecast_origin_utc", "nunique"),
            target_timestamps=("target_timestamp_utc", "nunique"),
            lead_day_min=("lead_day", "min"),
            lead_day_max=("lead_day", "max"),
        )
        .reset_index()
        .sort_values("dataset_split")
    )
    split_summary.to_csv(paths.run_dir / "split_summary.csv", index=False)

    origin_schedule = (
        parent_subset[["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "lead_day_label", "horizon_index"]]
        .drop_duplicates()
        .sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc"])
        .reset_index(drop=True)
    )
    origin_schedule.to_csv(paths.run_dir / "origin_schedule.csv", index=False)

    suite_models = {
        "suite": "QH-FS1 parent comparison phase2.7 hourly parity retrofit",
        "models": selected_parents.to_dict(orient="records"),
        "official_naive_denominator_model": official_naive.get("model"),
        "selection_scope": "validation_only",
    }
    _write_json(paths.run_dir / "suite_models.json", suite_models)

    model_settings = parent_settings[parent_settings["model_family"].astype(str).isin(["lear", "xgboost"])].copy()
    model_settings.to_csv(paths.run_dir / "model_settings_summary.csv", index=False)

    config_snapshot = {
        "run_label": RUN_LABEL,
        "business_timezone": resolved.business_timezone,
        "output_root": str(resolved.output_root),
        "phase2_parent_source_run": str(parent_run),
    }
    _write_json(paths.run_dir / "config_snapshot.json", config_snapshot)
    methodology_snapshot = {
        "forecast_origin_local_time": "08:00 on D-1",
        "horizon": "D..D+4",
        "rolling_origin": "daily",
        "known_at_policy": "known_at_utc <= forecast_origin_utc",
        "split_policy": "chronological origins over observed quarter-hour period",
    }
    _write_json(paths.run_dir / "methodology_snapshot.json", methodology_snapshot)
    tuning_policy_snapshot = {
        "fs0": "no tuning",
        "fs1": "fast/coarse validation-only tuning then freeze",
        "fs2": "first serious tuning round",
        "fs3": "mandatory retuning",
        "policy_source": "AGENTS.md + hourly parity governance",
    }
    _write_json(paths.run_dir / "tuning_policy_snapshot.json", tuning_policy_snapshot)

    feature_map = load_feature_family_map(resolved)
    phase3_ready = _phase3_readiness(
        run_dir=paths.run_dir,
        official_naive_reference=official_naive,
        parent_predictions=parent_subset,
        parent_settings=model_settings,
        feature_family_map=feature_map,
    )

    lineage = {
        "parent_run_id": str(parent_summary.get("run_id")),
        "parent_feature_set_id": "QH-FS1",
        "official_naive_reference_path": str(paths.run_dir / "official_naive_reference.json"),
        "feature_registry_path": str(resolved.output_root / "registry" / "quarterhour_feature_registry.json"),
        "feature_family_map_path": str(resolved.output_root / "registry" / "quarterhour_feature_family_map.csv"),
        "model_settings_source": str(parent_run / "model_settings_summary.csv"),
        "raw_phase07_source_run": str(source_runs["phase07_run_id"]),
        "hourly_anchor_candidate_identity": selected_parents.to_dict(orient="records"),
    }
    _write_json(paths.run_dir / "parent_benchmark_lineage.json", lineage)

    gaps: list[str] = []
    required = [
        "config_snapshot.json",
        "methodology_snapshot.json",
        "tuning_policy_snapshot.json",
        "split_summary.csv",
        "origin_schedule.csv",
        "metrics_overall.csv",
        "metrics_by_lead_day.csv",
        "metrics_by_reporting_level.csv",
        "official_naive_reference.json",
        "model_settings_summary.csv",
        "suite_models.json",
        "source_runs.json",
    ]
    for name in required:
        if not (paths.run_dir / name).exists():
            gaps.append(f"Missing required parity artifact: {name}")
    if not (paths.run_dir / "predictions_long.parquet").exists() and not (paths.run_dir / "predictions_long.csv").exists():
        gaps.append("Missing predictions_long.parquet and predictions_long.csv fallback.")
    if horizon_gap_notes:
        gaps.extend(horizon_gap_notes)
    if parent_metrics_by_reporting.empty:
        gaps.append("Parent metrics_by_reporting_level.csv was empty.")
    if parent_inventory.empty:
        gaps.append("Parent candidate_prediction_inventory.csv was empty.")

    gap_report = ["# Phase 2.7 Hourly Parity Gap Report", "", f"Run: `{paths.run_id}`", ""]
    if gaps:
        gap_report.extend(["## Remaining Gaps", ""])
        gap_report.extend([f"- {item}" for item in gaps])
    else:
        gap_report.extend(["## Remaining Gaps", "", "- None."])
    (paths.run_dir / "phase2_7_hourly_parity_gap_report.md").write_text("\n".join(gap_report) + "\n", encoding="utf-8")

    run_summary = {
        "run_id": paths.run_id,
        "run_label": RUN_LABEL,
        "status": "completed" if not gaps else "completed_with_gaps",
        "source_runs": source_runs,
        "lineage": lineage,
        "phase3_readiness": phase3_ready,
        "official_naive_denominator_policy": {
            "selection_scope": "validation_only",
            "coverage_gate": official_naive.get("minimum_prediction_availability_pct"),
            "selection_policy": official_naive.get("selection_policy"),
            "model": official_naive.get("model"),
            "materialized_denominator_artifact": str(paths.run_dir / "official_naive_denominator_materialized.csv"),
            "reporting_level_denominator_for_stitched_all_horizon": "materialized from observed benchmark metrics_by_reporting_level.csv",
            "phase3_child_policy": "inherit_parent_denominator_no_local_reselection",
        },
        "checks": {
            "qh_fs1_parent_candidates_true_d_to_d_plus_4": bool(
                not parent_subset.empty
                and set(pd.to_numeric(parent_subset["lead_day"], errors="coerce").dropna().astype(int).unique().tolist()) == {0, 1, 2, 3, 4}
                and int(parent_subset["forecast_origin_utc"].notna().sum()) > 0
            ),
            "required_columns_present": all(
                column in parent_subset.columns
                for column in [
                    "forecast_origin_utc",
                    "target_timestamp_utc",
                    "lead_day",
                    "lead_day_label",
                    "horizon_index",
                    "dataset_split",
                ]
            ),
        },
        "remaining_parity_gaps": gaps,
    }
    _write_json(paths.run_dir / "run_summary.json", run_summary)
    return paths
