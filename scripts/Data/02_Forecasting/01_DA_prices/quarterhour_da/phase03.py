from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import (
    load_candidate_model_settings,
    load_candidate_runtime_summary,
    summarize_candidate_coverage,
    summarize_missingness,
)

from .anchor_selection import build_dynamic_hourly_anchor_selection, selection_contract_frame
from .config import QuarterHourDAExtensionConfig
from .phase02 import find_latest_phase02_run


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase03_anchor_selection")


def find_latest_phase03_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase03_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _build_hourly_config(config: QuarterHourDAExtensionConfig) -> HourlyDAPipelineConfig:
    return HourlyDAPipelineConfig(output_root=config.hourly_da_output_root)


def _ensure_frame_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    working = frame.copy()
    for column in columns:
        if column not in working.columns:
            working[column] = pd.Series(dtype="object")
    return working[columns]


def _stringify_paths(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    for column in working.columns:
        working[column] = working[column].map(lambda value: str(value) if isinstance(value, Path) else value)
    return working


def _build_evaluation_slice_summary(evaluation_choice: dict[str, Any], predictions: pd.DataFrame) -> pd.DataFrame:
    target_slice = evaluation_choice["predictions"].copy()
    return pd.DataFrame(
        [
            {
                "selection_split": str(evaluation_choice["dataset_split"]),
                "selection_lead_day": int(evaluation_choice["lead_day"]),
                "selection_lead_day_label": str(evaluation_choice["lead_day_label"]),
                "candidate_count_in_slice": int(target_slice["candidate_key"].nunique()),
                "rows_in_slice": int(target_slice.shape[0]),
                "unique_targets_in_slice": int(target_slice["target_timestamp_utc"].nunique()),
                "forecast_origins_in_slice": int(target_slice["forecast_origin_utc"].nunique()),
                "selection_rule": "Inherited from hourly scenario-generation pipeline: prefer test D-only; fall back to validation if needed.",
                "notes": "The downstream 15-minute extension uses the hourly scenario-selection slice without hardcoding candidate names.",
            }
        ]
    )


def _build_official_naive_selected_frame(official_naive: dict[str, Any]) -> pd.DataFrame:
    selected = dict(official_naive["selected"])
    return pd.DataFrame([selected])


def _build_selected_anchor_models(
    *,
    role_rows: pd.DataFrame,
    selection_summary: pd.DataFrame,
    candidate_frame: pd.DataFrame,
    evaluation_choice: dict[str, Any],
) -> pd.DataFrame:
    if role_rows.empty:
        return pd.DataFrame()

    candidate_cols = [
        "candidate_key",
        "candidate_label",
        "selected_model",
        "selected_run_dir",
        "selected_run_id",
        "run_label",
        "model_family",
        "fs_level",
        "candidate_context",
        "display_group",
        "variant",
        "run_role",
        "discovery_rule",
    ]
    merged = (
        role_rows.merge(selection_summary, on="candidate_key", how="left", suffixes=("", "_selection"))
        .merge(candidate_frame[candidate_cols], on="candidate_key", how="left", suffixes=("", "_candidate"))
        .copy()
    )

    rows: list[dict[str, Any]] = []
    selection_split = str(evaluation_choice["dataset_split"])
    selection_lead_day = int(evaluation_choice["lead_day"])
    selection_lead_day_label = str(evaluation_choice["lead_day_label"])

    for row in merged.to_dict(orient="records"):
        role = str(row["selection_role"])
        if role == "deterministic_winner":
            role_description = "best_all_round"
            primary_metric = "rmae"
            primary_value = row.get("rmae")
            secondary_metric = ""
            secondary_value = None
            reason = "Lowest rMAE on the inherited hourly scenario-selection slice."
        elif role == "hour_ranking_winner":
            role_description = "best_hour_ranking"
            primary_metric = "ranking_score"
            primary_value = row.get("ranking_score")
            secondary_metric = ""
            secondary_value = None
            reason = "Highest hour-ranking score on the inherited hourly scenario-selection slice."
        else:
            role_description = "best_all_round_and_best_hour_ranking"
            primary_metric = "rmae"
            primary_value = row.get("rmae")
            secondary_metric = "ranking_score"
            secondary_value = row.get("ranking_score")
            reason = "The same hourly candidate won both the deterministic and hour-ranking roles under the existing scenario-selection logic."

        rows.append(
            {
                "role": role,
                "role_description": role_description,
                "candidate_key": str(row["candidate_key"]),
                "candidate_label": str(row.get("candidate_label") or row.get("candidate_label_selection") or ""),
                "model_family": str(row.get("model_family") or row.get("model_family_selection") or ""),
                "fs_level": str(row.get("fs_level") or row.get("fs_level_selection") or ""),
                "candidate_context": str(row.get("candidate_context") or ""),
                "source_run_id": str(row.get("selected_run_id") or row.get("source_run_id") or ""),
                "source_run_label": str(row.get("run_label") or row.get("source_run_label") or ""),
                "source_run_dir": str(row.get("selected_run_dir") or ""),
                "internal_model_name": str(row.get("selected_model") or ""),
                "selection_metric_primary": primary_metric,
                "selection_metric_primary_value": primary_value,
                "selection_metric_secondary": secondary_metric,
                "selection_metric_secondary_value": secondary_value,
                "selection_split": selection_split,
                "selection_lead_day": selection_lead_day,
                "selection_lead_day_label": selection_lead_day_label,
                "mae": row.get("mae"),
                "rmse": row.get("rmse"),
                "bias": row.get("bias"),
                "rmae": row.get("rmae"),
                "ranking_score": row.get("ranking_score"),
                "risk_weighted_ranking_score": row.get("risk_weighted_ranking_score"),
                "topk_expensive_recall": row.get("topk_expensive_recall"),
                "topk_cheap_recall": row.get("topk_cheap_recall"),
                "reason_selected": reason,
                "notes": (
                    "Roles and selection metrics are inherited directly from the hourly scenario-generation pipeline. "
                    "No hourly candidate names were hardcoded in the quarter-hour extension."
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_selected_runtime_summary(runtime_summary: pd.DataFrame, selected_anchor_models: pd.DataFrame) -> pd.DataFrame:
    if runtime_summary.empty or selected_anchor_models.empty:
        return pd.DataFrame()
    role_lookup = selected_anchor_models[["candidate_key", "role", "role_description"]].drop_duplicates()
    return (
        runtime_summary.merge(role_lookup, on="candidate_key", how="left")
        .sort_values(["role", "dataset_split"])
        .reset_index(drop=True)
    )


def _build_selected_model_settings_summary(model_settings: pd.DataFrame, selected_anchor_models: pd.DataFrame) -> pd.DataFrame:
    if model_settings.empty or selected_anchor_models.empty:
        return pd.DataFrame()
    role_lookup = selected_anchor_models[["candidate_key", "role", "role_description"]].drop_duplicates()
    working = model_settings.merge(role_lookup, on="candidate_key", how="left")
    preferred_columns = [
        "role",
        "role_description",
        "candidate_key",
        "candidate_label",
        "model",
        "model_family",
        "fs_level",
        "settings_source",
        "strategy",
        "fs3_experiment",
        "ablation_scheme_name",
        "ablation_target_block",
        "training_window_hours",
        "min_train_rows",
        "alpha",
        "max_iter",
        "n_estimators",
        "max_depth",
        "learning_rate",
        "subsample",
        "colsample_bytree",
        "reg_alpha",
        "reg_lambda",
        "branch_mode",
        "d_only_model_name",
        "guidance_model_name",
        "source_run_id",
        "source_run_label",
    ]
    available_columns = [column for column in preferred_columns if column in working.columns]
    return working[available_columns].sort_values(["role", "candidate_label"]).reset_index(drop=True)


def run_phase03_anchor_selection(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = config.phase03_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    hourly_config = _build_hourly_config(config)
    selection_bundle = build_dynamic_hourly_anchor_selection(output_root=hourly_config.output_root, config=hourly_config)

    selection_contract = selection_contract_frame()
    selection_contract.to_csv(run_dir / "selection_contract.csv", index=False)

    candidate_availability = _ensure_frame_columns(
        selection_bundle["discovery"]["availability"].copy(),
        [
            "candidate_id",
            "candidate_label",
            "fs_level",
            "model_family",
            "source_run_label",
            "source_run_id",
            "internal_model_name",
            "discovery_context",
            "source_run_role",
            "older_versions_found",
        ],
    )
    candidate_availability.to_csv(run_dir / "candidate_availability.csv", index=False)

    ignored_runs = _ensure_frame_columns(
        selection_bundle["discovery"]["ignored_runs"].copy(),
        ["run_id", "run_label", "status", "reason"],
    )
    ignored_runs.to_csv(run_dir / "ignored_runs.csv", index=False)

    candidate_frame = _stringify_paths(selection_bundle["candidate_frame"].copy())
    candidate_frame.to_csv(run_dir / "candidate_frame_latest.csv", index=False)

    evaluation_slice_summary = _build_evaluation_slice_summary(
        selection_bundle["evaluation_choice"],
        selection_bundle["predictions"],
    )
    evaluation_slice_summary.to_csv(run_dir / "evaluation_slice_summary.csv", index=False)

    official_naive_summary = pd.DataFrame(selection_bundle["official_naive"]["summary"]).copy()
    official_naive_selected = _build_official_naive_selected_frame(selection_bundle["official_naive"])
    official_naive_summary.to_csv(run_dir / "official_naive_summary.csv", index=False)
    official_naive_selected.to_csv(run_dir / "official_naive_selected.csv", index=False)

    prediction_coverage = summarize_candidate_coverage(selection_bundle["predictions"])
    prediction_missingness = summarize_missingness(selection_bundle["predictions"])
    prediction_coverage.to_csv(run_dir / "prediction_coverage_summary.csv", index=False)
    prediction_missingness.to_csv(run_dir / "prediction_missingness_summary.csv", index=False)

    selection_summary = selection_bundle["selection_summary"].copy()
    selection_summary.to_csv(run_dir / "candidate_selection_summary.csv", index=False)

    role_rows = _ensure_frame_columns(
        selection_bundle["role_rows"].copy(),
        ["candidate_key", "selection_role"],
    )
    role_rows.to_csv(run_dir / "selected_role_rows.csv", index=False)

    selected_anchor_models = _build_selected_anchor_models(
        role_rows=role_rows,
        selection_summary=selection_summary,
        candidate_frame=candidate_frame,
        evaluation_choice=selection_bundle["evaluation_choice"],
    )
    selected_anchor_models.to_csv(run_dir / "selected_anchor_models.csv", index=False)

    selected_candidate_frame = candidate_frame[
        candidate_frame["candidate_key"].astype(str).isin(selected_anchor_models["candidate_key"].astype(str))
    ].copy()
    runtime_summary = load_candidate_runtime_summary(selected_candidate_frame)
    runtime_summary = _build_selected_runtime_summary(runtime_summary, selected_anchor_models)
    runtime_summary = _ensure_frame_columns(
        runtime_summary,
        [
            "role",
            "role_description",
            "dataset_split",
            "model",
            "model_family",
            "fs_level",
            "origins",
            "fit_time_mean_sec",
            "fit_time_median_sec",
            "fit_time_max_sec",
            "fit_time_warning_count",
            "predict_time_mean_sec",
            "predict_time_median_sec",
            "candidate_key",
            "candidate_label",
            "candidate_context",
            "internal_model",
            "source_run_id",
            "source_run_label",
        ],
    )
    runtime_summary.to_csv(run_dir / "selected_candidate_runtime_summary.csv", index=False)

    model_settings = load_candidate_model_settings(selected_candidate_frame)
    model_settings_summary = _build_selected_model_settings_summary(model_settings, selected_anchor_models)
    model_settings_summary = _ensure_frame_columns(
        model_settings_summary,
        [
            "role",
            "role_description",
            "candidate_key",
            "candidate_label",
            "model",
            "model_family",
            "fs_level",
            "settings_source",
            "strategy",
            "fs3_experiment",
            "ablation_scheme_name",
            "ablation_target_block",
            "training_window_hours",
            "min_train_rows",
            "alpha",
            "max_iter",
            "n_estimators",
            "max_depth",
            "learning_rate",
            "subsample",
            "colsample_bytree",
            "reg_alpha",
            "reg_lambda",
            "branch_mode",
            "d_only_model_name",
            "guidance_model_name",
            "source_run_id",
            "source_run_label",
        ],
    )
    model_settings_summary.to_csv(run_dir / "selected_candidate_model_settings_summary.csv", index=False)

    latest_phase02 = find_latest_phase02_run(config)
    run_summary = {
        "run_id": run_id,
        "phase": "phase03_dynamic_hourly_anchor_selection",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "hourly_output_root": str(hourly_config.output_root),
        "phase02_run_dir": str(latest_phase02) if latest_phase02 is not None else None,
        "selection_contract_authority": selection_contract.iloc[0].to_dict(),
        "candidate_count_discovered": int(candidate_frame.shape[0]),
        "selected_candidate_keys": [str(value) for value in selection_bundle["selected_candidate_keys"]],
        "deterministic_candidate_key": str(selection_bundle["deterministic_candidate_key"]),
        "ranking_candidate_key": str(selection_bundle["ranking_candidate_key"]),
        "ranking_runner_up_key": (
            str(selection_bundle["ranking_runner_up_key"]) if selection_bundle["ranking_runner_up_key"] is not None else None
        ),
        "evaluation_choice": {
            "dataset_split": str(selection_bundle["evaluation_choice"]["dataset_split"]),
            "lead_day": int(selection_bundle["evaluation_choice"]["lead_day"]),
            "lead_day_label": str(selection_bundle["evaluation_choice"]["lead_day_label"]),
        },
        "official_naive_selected": official_naive_selected.iloc[0].to_dict() if not official_naive_selected.empty else {},
        "selected_anchor_models": selected_anchor_models.to_dict(orient="records"),
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
