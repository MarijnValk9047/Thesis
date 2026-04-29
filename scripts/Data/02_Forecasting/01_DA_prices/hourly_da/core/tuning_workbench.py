from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..models.registry import build_naive_baseline_models
from .config import HourlyDAPipelineConfig
from .feature_value import instantiate_model_from_parent_context, resolve_parent_stage_run
from .schedule import generate_forecast_origins


XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL = "xgboost_fs3_combo_pruned_candidate_benchmark"
XGBOOST_FS3_PREVIOUS_PARENT_RUN_LABEL = "xgboost_fs3_combo_promoted_benchmark"
XGBOOST_FS2_PARENT_RUN_LABEL = "xgboost_fs2_benchmark"
XGBOOST_FS3_ACTIVE_MODEL_NAME = "xgboost_fs3_combo_promoted"
XGBOOST_FS3_TUNING_RUN_LABEL_PREFIX = "xgboost_fs3_tuning"
XGBOOST_FS3_TUNING_PRIMARY_SPLIT = "validation"
XGBOOST_FS3_TUNING_PRIMARY_REPORTING_LEVEL = "stitched_all_horizon"
XGBOOST_FS3_TUNING_PRIMARY_METRIC = "mae"
XGBOOST_FS3_TUNING_MIN_VALIDATION_COVERAGE_PCT = 95.0
XGBOOST_FS3_TUNING_PILOT_ORIGIN_COUNT = 48
XGBOOST_FS3_TUNING_AUTO_FULL_VALIDATION_TOP_K = 3
XGBOOST_FS3_ACTIVE_EXCLUDED_BLOCKS = (
    "short_autoregressive_price_lags",
    "neighbor_only_historical_fundamentals",
    "domestic_historical_fundamentals",
    "domestic_day_ahead_fundamentals",
)
XGBOOST_TUNABLE_SETTING_FIELDS = (
    "training_window_hours",
    "min_train_rows",
    "n_estimators",
    "max_depth",
    "learning_rate",
    "subsample",
    "colsample_bytree",
    "reg_alpha",
    "reg_lambda",
    "random_state",
    "n_jobs",
)


def default_xgboost_fs3_pilot_candidate_plan() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "candidate_id": "xgboost_fs3_tune_r1_c01",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.03,
                "max_depth": 4,
                "n_estimators": 140,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "rationale": "Lower learning rate with more trees around the current depth.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c02",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.03,
                "max_depth": 3,
                "n_estimators": 180,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "rationale": "Shallower trees with more boosting rounds for smoother generalization.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c03",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.05,
                "max_depth": 5,
                "n_estimators": 120,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "rationale": "Adds capacity while keeping the original learning rate.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c04",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.05,
                "max_depth": 3,
                "n_estimators": 100,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "rationale": "Simpler tree shape to test whether the current depth is too aggressive.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c05",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.07,
                "max_depth": 4,
                "n_estimators": 90,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "rationale": "Tests a mildly more aggressive shrinkage region with limited extra depth.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c06",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.03,
                "max_depth": 4,
                "n_estimators": 140,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.0,
                "reg_lambda": 2.0,
                "rationale": "Same conservative tree region as c01 but with stronger L2 regularization.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c07",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.03,
                "max_depth": 4,
                "n_estimators": 140,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.2,
                "reg_lambda": 1.0,
                "rationale": "Adds sparse regularization on top of the conservative c01 region.",
            },
            {
                "candidate_id": "xgboost_fs3_tune_r1_c08",
                "search_stage": "pilot_round_1",
                "learning_rate": 0.03,
                "max_depth": 4,
                "n_estimators": 140,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.0,
                "reg_lambda": 1.0,
                "rationale": "Adds stochastic row and column subsampling to reduce variance.",
            },
        ]
    )


@dataclass(frozen=True)
class SelectedSplitPipelineConfig(HourlyDAPipelineConfig):
    selected_evaluation_splits: tuple[str, ...] = ("validation", "test")

    def evaluation_splits(self) -> tuple[str, ...]:
        return tuple(str(split_name) for split_name in self.selected_evaluation_splits)


def with_selected_evaluation_splits(
    config: HourlyDAPipelineConfig,
    selected_splits: tuple[str, ...] | list[str],
) -> SelectedSplitPipelineConfig:
    normalized = tuple(dict.fromkeys(str(split_name) for split_name in selected_splits if str(split_name)))
    if not normalized:
        raise ValueError("selected_splits must contain at least one split name.")
    payload = dict(config.__dict__)
    payload["selected_evaluation_splits"] = normalized
    return SelectedSplitPipelineConfig(**payload)


def sample_origin_schedule(origin_schedule: pd.DataFrame, max_origins: int | None = None) -> pd.DataFrame:
    schedule = origin_schedule.reset_index(drop=True).copy()
    if max_origins is None:
        return schedule

    limit = int(max_origins)
    if limit <= 0:
        raise ValueError("max_origins must be positive when provided.")
    if schedule.shape[0] <= limit:
        return schedule

    positions = np.linspace(0, schedule.shape[0] - 1, num=limit, dtype=int)
    positions = np.unique(positions)
    return schedule.iloc[positions].reset_index(drop=True)


def build_origin_schedule_by_split(
    config: HourlyDAPipelineConfig,
    split_names: tuple[str, ...] | list[str] = ("validation",),
    max_origins_by_split: dict[str, int] | None = None,
) -> dict[str, pd.DataFrame]:
    schedules: dict[str, pd.DataFrame] = {}
    for split_name in split_names:
        full_schedule = generate_forecast_origins(config, str(split_name))
        max_origins = None if max_origins_by_split is None else max_origins_by_split.get(str(split_name))
        schedules[str(split_name)] = sample_origin_schedule(full_schedule, max_origins=max_origins)
    return schedules


def origin_schedule_summary_frame(
    config: HourlyDAPipelineConfig,
    *,
    split_name: str,
    sampled_schedule: pd.DataFrame,
) -> pd.DataFrame:
    full_schedule = generate_forecast_origins(config, split_name)
    sampled = sampled_schedule.reset_index(drop=True).copy()

    def _edge_value(frame: pd.DataFrame, column: str, position: int) -> str:
        if frame.empty or column not in frame.columns:
            return ""
        values = frame[column].astype(str)
        return str(values.iloc[position])

    full_count = int(full_schedule.shape[0])
    sampled_count = int(sampled.shape[0])
    return pd.DataFrame(
        [
            {
                "dataset_split": str(split_name),
                "full_origin_count": full_count,
                "sample_origin_count": sampled_count,
                "sample_share_pct": (100.0 * sampled_count / full_count) if full_count else np.nan,
                "full_first_delivery_start_local_date": _edge_value(full_schedule, "delivery_start_local_date", 0),
                "full_last_delivery_start_local_date": _edge_value(full_schedule, "delivery_start_local_date", -1),
                "sample_first_delivery_start_local_date": _edge_value(sampled, "delivery_start_local_date", 0),
                "sample_last_delivery_start_local_date": _edge_value(sampled, "delivery_start_local_date", -1),
                "full_first_origin_utc": _edge_value(full_schedule, "forecast_origin_utc", 0),
                "full_last_origin_utc": _edge_value(full_schedule, "forecast_origin_utc", -1),
                "sample_first_origin_utc": _edge_value(sampled, "forecast_origin_utc", 0),
                "sample_last_origin_utc": _edge_value(sampled, "forecast_origin_utc", -1),
            }
        ]
    )


@lru_cache(maxsize=None)
def _cached_parent_context(
    config: HourlyDAPipelineConfig,
    *,
    model_family: str,
    fs_level: str,
    parent_run_label: str,
):
    return resolve_parent_stage_run(
        config,
        model_family=str(model_family),
        fs_level=str(fs_level),
        parent_run_label=str(parent_run_label),
    )


def resolve_xgboost_fs3_tuning_parent(
    config: HourlyDAPipelineConfig,
    parent_run_label: str = XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL,
):
    return _cached_parent_context(
        config,
        model_family="xgboost",
        fs_level="FS3",
        parent_run_label=str(parent_run_label),
    )


def resolve_xgboost_fs2_reference_parent(
    config: HourlyDAPipelineConfig,
    parent_run_label: str = XGBOOST_FS2_PARENT_RUN_LABEL,
):
    return _cached_parent_context(
        config,
        model_family="xgboost",
        fs_level="FS2",
        parent_run_label=str(parent_run_label),
    )


def _normalized_setting_overrides(settings_overrides: dict[str, object] | None = None) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for field_name in XGBOOST_TUNABLE_SETTING_FIELDS:
        if settings_overrides is None or field_name not in settings_overrides:
            continue
        value = settings_overrides[field_name]
        if pd.isna(value):
            continue
        if hasattr(value, "item"):
            try:
                value = value.item()
            except Exception:
                pass
        normalized[str(field_name)] = value
    return normalized


def build_xgboost_fs3_tuning_model(
    config: HourlyDAPipelineConfig,
    *,
    model_name: str,
    settings_overrides: dict[str, object] | None = None,
    parent_run_label: str = XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL,
):
    parent = resolve_xgboost_fs3_tuning_parent(config, parent_run_label=parent_run_label)
    return instantiate_model_from_parent_context(
        parent,
        settings_overrides=_normalized_setting_overrides(settings_overrides),
        name_override=str(model_name),
    )


def build_xgboost_fs2_anchor_model(
    config: HourlyDAPipelineConfig,
    *,
    model_name: str = "xgboost_fs2_anchor",
    parent_run_label: str = XGBOOST_FS2_PARENT_RUN_LABEL,
):
    parent = resolve_xgboost_fs2_reference_parent(config, parent_run_label=parent_run_label)
    return instantiate_model_from_parent_context(parent, name_override=str(model_name))


def build_xgboost_fs3_tuning_baselines(
    config: HourlyDAPipelineConfig,
    *,
    include_naives: bool = True,
    include_fs2_anchor: bool = True,
    current_baseline_name: str = "xgboost_fs3_current_baseline",
    parent_run_label: str = XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL,
) -> list:
    models: list = []
    if include_naives:
        models.extend(build_naive_baseline_models())
    if include_fs2_anchor:
        models.append(build_xgboost_fs2_anchor_model(config))
    models.append(
        build_xgboost_fs3_tuning_model(
            config,
            model_name=str(current_baseline_name),
            parent_run_label=str(parent_run_label),
        )
    )
    return models


def build_xgboost_fs3_tuning_candidate_models(
    config: HourlyDAPipelineConfig,
    candidate_specs: pd.DataFrame | list[dict[str, object]],
    *,
    model_name_col: str = "candidate_id",
    parent_run_label: str = XGBOOST_FS3_ACTIVE_PARENT_RUN_LABEL,
) -> list:
    frame = pd.DataFrame(candidate_specs).copy()
    if frame.empty:
        return []

    models: list = []
    for spec in frame.to_dict(orient="records"):
        model_name = str(spec.get(model_name_col) or spec.get("model_name") or "").strip()
        if not model_name:
            raise ValueError("Each candidate spec must define a candidate_id or model_name.")
        models.append(
            build_xgboost_fs3_tuning_model(
                config,
                model_name=model_name,
                settings_overrides=spec,
                parent_run_label=str(parent_run_label),
            )
        )
    return models


def build_tuning_candidate_summary(
    metrics_by_reporting_level: pd.DataFrame,
    timing_summary: pd.DataFrame,
    *,
    split_name: str,
    baseline_model: str,
    model_order: list[str] | None = None,
) -> pd.DataFrame:
    if metrics_by_reporting_level.empty:
        return pd.DataFrame()

    metric_frame = metrics_by_reporting_level[
        metrics_by_reporting_level["dataset_split"].astype(str) == str(split_name)
    ].copy()
    if metric_frame.empty:
        return pd.DataFrame()
    if "display_name" not in metric_frame.columns:
        metric_frame["display_name"] = metric_frame["model"].astype(str)

    metric_cols = [
        "model",
        "display_name",
        "reporting_level",
        "mae",
        "coverage_pct",
        "rmae_vs_official_naive",
    ]
    metric_frame = metric_frame[[column for column in metric_cols if column in metric_frame.columns]].copy()

    mae_pivot = metric_frame.pivot_table(
        index=["model", "display_name"],
        columns="reporting_level",
        values="mae",
        aggfunc="first",
    )
    coverage_pivot = metric_frame.pivot_table(
        index=["model", "display_name"],
        columns="reporting_level",
        values="coverage_pct",
        aggfunc="first",
    )
    rmae_pivot = metric_frame.pivot_table(
        index=["model", "display_name"],
        columns="reporting_level",
        values="rmae_vs_official_naive",
        aggfunc="first",
    )

    summary = (
        mae_pivot.rename(
            columns={
                "d_only": "mae_d_only",
                "guidance_only": "mae_guidance_only",
                "stitched_all_horizon": "mae_stitched_all_horizon",
            }
        )
        .reset_index()
    )

    if not coverage_pivot.empty:
        coverage_view = coverage_pivot.rename(
            columns={
                "d_only": "coverage_d_only_pct",
                "guidance_only": "coverage_guidance_only_pct",
                "stitched_all_horizon": "coverage_stitched_all_horizon_pct",
            }
        ).reset_index()
        summary = summary.merge(coverage_view, on=["model", "display_name"], how="left")

    if not rmae_pivot.empty:
        rmae_view = rmae_pivot.rename(
            columns={
                "d_only": "rmae_d_only",
                "guidance_only": "rmae_guidance_only",
                "stitched_all_horizon": "rmae_stitched_all_horizon",
            }
        ).reset_index()
        summary = summary.merge(rmae_view, on=["model", "display_name"], how="left")

    baseline_rows = summary[summary["model"].astype(str) == str(baseline_model)].copy()
    if baseline_rows.empty:
        raise ValueError(f"Baseline model '{baseline_model}' is not present in the metric summary.")

    baseline_mae = float(baseline_rows.iloc[0]["mae_stitched_all_horizon"])
    summary["delta_vs_baseline_stitched_mae"] = summary["mae_stitched_all_horizon"].astype(float) - baseline_mae

    if not timing_summary.empty:
        timing_view = timing_summary[
            timing_summary["dataset_split"].astype(str) == str(split_name)
        ][
            [
                "model",
                "fit_time_mean_sec",
                "predict_time_mean_sec",
                "fit_time_max_sec",
                "fit_time_warning_count",
            ]
        ].copy()
        summary = summary.merge(timing_view, on="model", how="left")

    if model_order:
        order_map = {str(model_name): index for index, model_name in enumerate(model_order)}
        summary["_model_order"] = summary["model"].astype(str).map(order_map).fillna(len(order_map))
        summary = summary.sort_values(["_model_order", "display_name"]).drop(columns=["_model_order"])
    else:
        summary = summary.sort_values(["mae_stitched_all_horizon", "mae_d_only", "display_name"])

    return summary.reset_index(drop=True)


def build_tuning_candidate_detail(
    candidate_plan: pd.DataFrame | list[dict[str, object]],
    tuning_summary: pd.DataFrame,
    *,
    candidate_id_col: str = "candidate_id",
) -> pd.DataFrame:
    summary = tuning_summary.copy()
    if summary.empty:
        return summary

    plan = pd.DataFrame(candidate_plan).copy()
    if plan.empty:
        return summary
    if candidate_id_col not in plan.columns:
        raise ValueError(f"candidate_plan must include '{candidate_id_col}'.")

    plan[candidate_id_col] = plan[candidate_id_col].astype(str)
    merged = summary.merge(
        plan,
        left_on="model",
        right_on=candidate_id_col,
        how="left",
    )
    return merged.reset_index(drop=True)


def _to_python_value(value):
    if isinstance(value, dict):
        return {str(key): _to_python_value(subvalue) for key, subvalue in value.items()}
    if isinstance(value, list):
        return [_to_python_value(item) for item in value]
    if isinstance(value, tuple):
        return [_to_python_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def build_tuning_recommendation(
    candidate_plan: pd.DataFrame | list[dict[str, object]],
    tuning_summary: pd.DataFrame,
    *,
    finalist_candidate_ids: list[str] | tuple[str, ...],
    baseline_model: str,
    min_coverage_pct: float,
    candidate_id_col: str = "candidate_id",
) -> dict[str, object]:
    detail = build_tuning_candidate_detail(
        candidate_plan,
        tuning_summary,
        candidate_id_col=candidate_id_col,
    )
    if detail.empty:
        return {
            "status": "no_summary",
            "decision": "no_recommendation",
            "manual_freeze_required": True,
            "freeze_note": "Freezing remains manual. No recommendation can be written until a full-validation summary exists.",
            "recommendation": {},
            "recommended_settings": {},
            "finalist_ranking": [],
        }

    baseline_rows = detail[detail["model"].astype(str) == str(baseline_model)].copy()
    if baseline_rows.empty:
        raise ValueError(f"Baseline model '{baseline_model}' is not present in the tuning summary.")
    baseline_row = baseline_rows.iloc[0].to_dict()

    finalist_ids = [str(candidate_id) for candidate_id in finalist_candidate_ids if str(candidate_id)]
    finalists = detail[detail["model"].astype(str).isin(finalist_ids)].copy()
    if finalists.empty:
        return {
            "status": "no_finalists",
            "decision": "no_recommendation",
            "manual_freeze_required": True,
            "freeze_note": "Freezing remains manual. No finalist candidates were available for recommendation.",
            "recommendation": {},
            "recommended_settings": {},
            "finalist_ranking": [],
        }

    finalists["coverage_gate_pass"] = finalists["coverage_stitched_all_horizon_pct"].astype(float) >= float(min_coverage_pct)
    finalists["fit_warning_gate_pass"] = finalists["fit_time_warning_count"].fillna(0).astype(float) == 0.0
    finalists["eligible_for_promotion"] = finalists["coverage_gate_pass"] & finalists["fit_warning_gate_pass"]
    finalists = finalists.sort_values(
        ["eligible_for_promotion", "mae_stitched_all_horizon", "mae_d_only", "fit_time_mean_sec"],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)

    eligible = finalists[finalists["eligible_for_promotion"]].copy()
    if eligible.empty:
        best_finalist = finalists.iloc[0].to_dict()
        return {
            "status": "no_eligible_finalist",
            "decision": "keep_current_baseline",
            "manual_freeze_required": True,
            "freeze_note": "Freezing remains manual. The current FS3 baseline stays preferred because no finalist passed the coverage/runtime gates.",
            "recommendation": {
                "recommended_model": str(baseline_model),
                "recommended_candidate_id": None,
                "decision_reason": "No finalist passed the minimum coverage and fit-warning gates.",
                "baseline_validation_stitched_mae": _to_python_value(baseline_row.get("mae_stitched_all_horizon")),
                "best_finalist_under_consideration": _to_python_value(best_finalist.get("model")),
            },
            "recommended_settings": {},
            "finalist_ranking": [
                _to_python_value(record)
                for record in finalists[
                    [
                        "model",
                        "mae_stitched_all_horizon",
                        "delta_vs_baseline_stitched_mae",
                        "mae_d_only",
                        "mae_guidance_only",
                        "coverage_stitched_all_horizon_pct",
                        "fit_time_mean_sec",
                        "fit_time_warning_count",
                        "eligible_for_promotion",
                        "rationale",
                    ]
                ].to_dict(orient="records")
            ],
        }

    best_candidate = eligible.iloc[0].to_dict()
    stitched_delta = float(best_candidate["delta_vs_baseline_stitched_mae"])
    baseline_stitched_mae = float(baseline_row["mae_stitched_all_horizon"])
    candidate_stitched_mae = float(best_candidate["mae_stitched_all_horizon"])

    if stitched_delta < 0.0:
        decision = "promote_candidate"
        recommended_model = str(best_candidate["model"])
        recommended_candidate_id = str(best_candidate.get(candidate_id_col) or best_candidate["model"])
        decision_reason = (
            f"Candidate improved validation stitched_all_horizon MAE from {baseline_stitched_mae:.3f} "
            f"to {candidate_stitched_mae:.3f} ({stitched_delta:+.3f})."
        )
        recommended_settings = {
            field_name: _to_python_value(best_candidate.get(field_name))
            for field_name in XGBOOST_TUNABLE_SETTING_FIELDS
            if field_name in best_candidate and pd.notna(best_candidate.get(field_name))
        }
    else:
        decision = "keep_current_baseline"
        recommended_model = str(baseline_model)
        recommended_candidate_id = None
        decision_reason = (
            f"No finalist improved validation stitched_all_horizon MAE versus the current baseline "
            f"({baseline_stitched_mae:.3f})."
        )
        recommended_settings = {}

    recommendation = {
        "recommended_model": recommended_model,
        "recommended_candidate_id": recommended_candidate_id,
        "decision_reason": decision_reason,
        "baseline_validation_stitched_mae": baseline_stitched_mae,
        "recommended_validation_stitched_mae": candidate_stitched_mae if decision == "promote_candidate" else baseline_stitched_mae,
        "delta_vs_current_baseline_stitched_mae": stitched_delta if decision == "promote_candidate" else 0.0,
        "recommended_validation_d_only_mae": _to_python_value(best_candidate.get("mae_d_only")) if decision == "promote_candidate" else _to_python_value(baseline_row.get("mae_d_only")),
        "recommended_validation_guidance_only_mae": _to_python_value(best_candidate.get("mae_guidance_only")) if decision == "promote_candidate" else _to_python_value(baseline_row.get("mae_guidance_only")),
        "recommended_validation_coverage_pct": _to_python_value(best_candidate.get("coverage_stitched_all_horizon_pct")) if decision == "promote_candidate" else _to_python_value(baseline_row.get("coverage_stitched_all_horizon_pct")),
        "recommended_fit_time_mean_sec": _to_python_value(best_candidate.get("fit_time_mean_sec")) if decision == "promote_candidate" else _to_python_value(baseline_row.get("fit_time_mean_sec")),
        "rationale": _to_python_value(best_candidate.get("rationale")) if decision == "promote_candidate" else "Keep the current validated FS3 baseline.",
    }

    finalist_ranking = finalists[
        [
            "model",
            "mae_stitched_all_horizon",
            "delta_vs_baseline_stitched_mae",
            "mae_d_only",
            "mae_guidance_only",
            "coverage_stitched_all_horizon_pct",
            "fit_time_mean_sec",
            "fit_time_warning_count",
            "eligible_for_promotion",
            "rationale",
        ]
    ].to_dict(orient="records")

    return {
        "status": "ok",
        "decision": decision,
        "manual_freeze_required": True,
        "freeze_note": (
            "Freezing remains manual. If you accept this recommendation, copy the recommended settings into the official "
            "FS3 XGBoost benchmark definition and rerun the benchmark context."
        ),
        "recommendation": _to_python_value(recommendation),
        "recommended_settings": _to_python_value(recommended_settings),
        "finalist_ranking": _to_python_value(finalist_ranking),
    }


def auto_select_full_validation_candidates(
    tuning_summary: pd.DataFrame,
    candidate_plan: pd.DataFrame | list[dict[str, object]],
    *,
    top_k: int = XGBOOST_FS3_TUNING_AUTO_FULL_VALIDATION_TOP_K,
    min_coverage_pct: float = XGBOOST_FS3_TUNING_MIN_VALIDATION_COVERAGE_PCT,
) -> list[str]:
    summary = tuning_summary.copy()
    if summary.empty:
        return []

    plan = pd.DataFrame(candidate_plan).copy()
    if plan.empty or "candidate_id" not in plan.columns:
        return []

    candidate_ids = plan["candidate_id"].astype(str).tolist()
    candidate_only = summary[summary["model"].astype(str).isin(candidate_ids)].copy()
    if candidate_only.empty:
        return []

    auto_promotions = candidate_only[
        (candidate_only["delta_vs_baseline_stitched_mae"].astype(float) < 0.0)
        & (candidate_only["coverage_stitched_all_horizon_pct"].astype(float) >= float(min_coverage_pct))
        & (candidate_only["fit_time_warning_count"].fillna(0).astype(float) == 0.0)
    ].sort_values(
        ["delta_vs_baseline_stitched_mae", "mae_d_only", "fit_time_mean_sec"],
        ascending=[True, True, True],
    )
    return auto_promotions.head(int(top_k))["model"].astype(str).tolist()


def build_pilot_sequence_frame(
    tuning_detail: pd.DataFrame,
    candidate_plan: pd.DataFrame | list[dict[str, object]],
) -> pd.DataFrame:
    detail = tuning_detail.copy()
    if detail.empty:
        return pd.DataFrame()

    plan = pd.DataFrame(candidate_plan).copy()
    if plan.empty or "candidate_id" not in plan.columns:
        return pd.DataFrame()

    plan = plan.reset_index(drop=True).copy()
    plan["candidate_id"] = plan["candidate_id"].astype(str)
    plan["sequence_order"] = np.arange(1, plan.shape[0] + 1, dtype=int)

    sequence = plan.merge(detail, left_on="candidate_id", right_on="model", how="left", suffixes=("", "_detail"))
    return sequence.reset_index(drop=True)


def save_xgboost_fs3_pilot_plots(
    tuning_detail: pd.DataFrame,
    candidate_plan: pd.DataFrame | list[dict[str, object]],
    output_dir: Path,
    *,
    baseline_model: str = "xgboost_fs3_current_baseline",
    fs2_anchor_model: str = "xgboost_fs2_anchor",
) -> dict[str, str]:
    detail = tuning_detail.copy()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if detail.empty:
        return {}

    from matplotlib import pyplot as plt

    from ..notebook_support import apply_standard_matplotlib_style

    apply_standard_matplotlib_style()
    saved_paths: dict[str, str] = {}

    baseline_rows = detail[detail["model"].astype(str) == str(baseline_model)].copy()
    fs2_rows = detail[detail["model"].astype(str) == str(fs2_anchor_model)].copy()
    baseline_stitched = float(baseline_rows.iloc[0]["mae_stitched_all_horizon"]) if not baseline_rows.empty else np.nan
    fs2_stitched = float(fs2_rows.iloc[0]["mae_stitched_all_horizon"]) if not fs2_rows.empty else np.nan

    candidate_ids = pd.DataFrame(candidate_plan).get("candidate_id", pd.Series(dtype=str)).astype(str).tolist()
    candidate_rows = detail[detail["model"].astype(str).isin(candidate_ids)].copy()
    if candidate_rows.empty:
        return {}

    sequence = build_pilot_sequence_frame(detail, candidate_plan)
    if not sequence.empty:
        fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True)
        metric_specs = [
            ("mae_stitched_all_horizon", "Full-horizon MAE", "tab:blue"),
            ("mae_d_only", "D-only MAE", "tab:orange"),
            ("mae_guidance_only", "Guidance-only MAE", "tab:green"),
        ]
        for column_name, label, color in metric_specs:
            axes[0].plot(
                sequence["sequence_order"],
                sequence[column_name],
                marker="o",
                linewidth=2,
                color=color,
                label=label,
            )
        if np.isfinite(baseline_stitched):
            axes[0].axhline(
                baseline_stitched,
                color="tab:red",
                linestyle="--",
                linewidth=1.5,
                label="Current FS3 baseline stitched MAE",
            )
        axes[0].set_ylabel("MAE (EUR/MWh)")
        axes[0].set_title("Pilot candidate sequence: MAE by candidate order")
        axes[0].legend(loc="best")

        rmae_specs = [
            ("rmae_stitched_all_horizon", "Full-horizon rMAE", "tab:blue"),
            ("rmae_d_only", "D-only rMAE", "tab:orange"),
            ("rmae_guidance_only", "Guidance-only rMAE", "tab:green"),
        ]
        for column_name, label, color in rmae_specs:
            axes[1].plot(
                sequence["sequence_order"],
                sequence[column_name],
                marker="o",
                linewidth=2,
                color=color,
                label=label,
            )
        axes[1].axhline(1.0, color="black", linestyle=":", linewidth=1.2, label="Official naive parity")
        axes[1].set_xlabel("Pilot candidate order")
        axes[1].set_ylabel("rMAE")
        axes[1].set_title("Pilot candidate sequence: rMAE by candidate order")
        axes[1].legend(loc="best")
        label_column = "candidate_id" if "candidate_id" in sequence.columns else "model"
        axes[1].set_xticks(sequence["sequence_order"])
        axes[1].set_xticklabels(sequence[label_column].astype(str), rotation=45, ha="right")
        fig.tight_layout()

        path = output_dir / "pilot_candidate_sequence_metrics.png"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(fig)
        saved_paths["candidate_sequence_metrics"] = str(path)

    ranked = candidate_rows.sort_values(
        ["mae_stitched_all_horizon", "mae_d_only", "fit_time_mean_sec", "model"],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    colors = ["tab:green" if float(value) < 0.0 else "tab:gray" for value in ranked["delta_vs_baseline_stitched_mae"]]
    ax.barh(
        ranked["model"],
        ranked["delta_vs_baseline_stitched_mae"],
        color=colors,
    )
    ax.axvline(0.0, color="black", linewidth=1.2)
    ax.set_xlabel("Delta vs current FS3 baseline stitched MAE (EUR/MWh)")
    ax.set_ylabel("Candidate")
    ax.set_title("Pilot candidate ranking by stitched MAE improvement")
    fig.tight_layout()
    path = output_dir / "pilot_ranked_delta_vs_baseline.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    saved_paths["ranked_delta_vs_baseline"] = str(path)

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(
        candidate_rows["fit_time_mean_sec"],
        candidate_rows["mae_stitched_all_horizon"],
        c=candidate_rows["delta_vs_baseline_stitched_mae"],
        cmap="RdYlGn_r",
        s=90,
        edgecolor="black",
        linewidth=0.5,
    )
    for row in candidate_rows.itertuples(index=False):
        ax.annotate(
            str(getattr(row, "model")),
            (float(getattr(row, "fit_time_mean_sec")), float(getattr(row, "mae_stitched_all_horizon"))),
            textcoords="offset points",
            xytext=(5, 5),
            fontsize=8,
        )
    if np.isfinite(baseline_stitched):
        ax.axhline(baseline_stitched, color="tab:red", linestyle="--", linewidth=1.2, label="Current FS3 baseline")
    if np.isfinite(fs2_stitched):
        ax.axhline(fs2_stitched, color="tab:purple", linestyle=":", linewidth=1.2, label="FS2 anchor")
    ax.set_xlabel("Mean fit time per origin (sec)")
    ax.set_ylabel("Validation stitched MAE (EUR/MWh)")
    ax.set_title("Pilot candidates: runtime vs validation MAE")
    ax.legend(loc="best")
    colorbar = fig.colorbar(scatter, ax=ax)
    colorbar.set_label("Delta vs current FS3 baseline stitched MAE")
    fig.tight_layout()
    path = output_dir / "pilot_runtime_vs_mae.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    saved_paths["runtime_vs_mae"] = str(path)

    return saved_paths


def render_tuning_recommendation_markdown(recommendation_payload: dict[str, object]) -> str:
    payload = dict(recommendation_payload or {})
    status = str(payload.get("status", "unknown"))
    decision = str(payload.get("decision", "no_recommendation"))
    recommendation = dict(payload.get("recommendation") or {})
    settings = dict(payload.get("recommended_settings") or {})

    lines = ["# XGBoost FS3 tuning recommendation", ""]
    lines.append(f"Status: `{status}`")
    lines.append(f"Decision: `{decision}`")
    lines.append("")

    if recommendation:
        recommended_model = recommendation.get("recommended_model")
        candidate_id = recommendation.get("recommended_candidate_id")
        lines.append(f"Recommended model: `{recommended_model}`")
        if candidate_id:
            lines.append(f"Recommended candidate id: `{candidate_id}`")
        lines.append(
            "Primary validation result: "
            f"`stitched_all_horizon` MAE {recommendation.get('recommended_validation_stitched_mae')} "
            f"vs baseline {recommendation.get('baseline_validation_stitched_mae')} "
            f"(delta {recommendation.get('delta_vs_current_baseline_stitched_mae')})."
        )
        lines.append(
            "Diagnostics: "
            f"`d_only` MAE {recommendation.get('recommended_validation_d_only_mae')}, "
            f"`guidance_only` MAE {recommendation.get('recommended_validation_guidance_only_mae')}, "
            f"coverage {recommendation.get('recommended_validation_coverage_pct')}%, "
            f"fit mean {recommendation.get('recommended_fit_time_mean_sec')} sec."
        )
        lines.append(f"Decision reason: {recommendation.get('decision_reason')}")
        lines.append(f"Interpretive note: {recommendation.get('rationale')}")
        lines.append("")

    if settings:
        lines.append("Recommended settings to freeze manually:")
        for key in XGBOOST_TUNABLE_SETTING_FIELDS:
            if key in settings:
                lines.append(f"- `{key}`: `{settings[key]}`")
        lines.append("")

    lines.append(str(payload.get("freeze_note", "Freezing remains manual.")))
    return "\n".join(lines)


def list_saved_run_dirs(output_root: Path, run_label_prefix: str) -> pd.DataFrame:
    run_root = Path(output_root) / "runs"
    if not run_root.exists():
        return pd.DataFrame(columns=["run_id", "run_label", "timestamp"])

    rows: list[dict[str, object]] = []
    for candidate in sorted(run_root.iterdir()):
        if not candidate.is_dir():
            continue
        parts = candidate.name.split("_", 2)
        if len(parts) != 3:
            continue
        run_label = str(parts[2])
        if not run_label.startswith(str(run_label_prefix)):
            continue
        timestamp = pd.to_datetime(f"{parts[0]}_{parts[1]}", format="%Y%m%d_%H%M%S", errors="coerce")
        rows.append(
            {
                "run_id": str(candidate.name),
                "run_label": run_label,
                "timestamp": timestamp,
            }
        )
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True) if rows else pd.DataFrame(columns=["run_id", "run_label", "timestamp"])
