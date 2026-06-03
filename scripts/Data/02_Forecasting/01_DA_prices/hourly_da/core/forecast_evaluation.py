from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HourlyDAPipelineConfig
from .metrics import diebold_mariano_test
from .reporting import find_latest_run, load_csv, load_json, resolve_tabular_path


EVALUATION_REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "run_summary.json",
    "metrics_overall.csv",
    "metrics_by_lead_day.csv",
    "metrics_by_reporting_level.csv",
    "model_settings_summary.csv",
    "official_naive_reference.json",
    "origin_timing_summary.csv",
)

PREDICTION_ARTIFACT_OPTIONS: tuple[str, ...] = ("predictions_long.parquet", "predictions_long.csv")

THESIS_CORE_WEEK_CATEGORIES: tuple[str, ...] = ("typical_winter", "typical_summer", "high_volatility")
APPENDIX_WEEK_CATEGORIES: tuple[str, ...] = ("high_price", "low_price", "negative_price")

FS3_FINAL_CANDIDATE_CONTEXTS: tuple[dict[str, object], ...] = (
    {
        "candidate_key": "lear_fs3_promoted",
        "candidate_label": "LEAR FS3 promoted",
        "run_label": "lear_fs3_combo_promoted_benchmark",
        "model_family": "lear",
        "fs_level": "FS3",
        "variant": "promoted",
        "candidate_context": "fs3_promoted",
        "preferred_model_names": ("lear_fs3_combo_promoted",),
    },
    {
        "candidate_key": "xgboost_fs3_promoted",
        "candidate_label": "XGBoost FS3 promoted",
        "run_label": "xgboost_fs3_combo_promoted_benchmark",
        "model_family": "xgboost",
        "fs_level": "FS3",
        "variant": "promoted",
        "candidate_context": "fs3_promoted",
        "preferred_model_names": ("xgboost_fs3_combo_promoted",),
    },
    {
        "candidate_key": "lear_fs3_pruned_candidate",
        "candidate_label": "LEAR FS3 pruned candidate",
        "run_label": "lear_fs3_combo_pruned_candidate_benchmark",
        "model_family": "lear",
        "fs_level": "FS3",
        "variant": "pruned_candidate",
        "candidate_context": "fs3_pruned_candidate",
        "preferred_model_names": ("lear_fs3_combo_pruned_candidate", "lear_fs3_combo_promoted"),
    },
    {
        "candidate_key": "xgboost_fs3_pruned_candidate",
        "candidate_label": "XGBoost FS3 pruned candidate",
        "run_label": "xgboost_fs3_combo_pruned_candidate_benchmark",
        "model_family": "xgboost",
        "fs_level": "FS3",
        "variant": "pruned_candidate",
        "candidate_context": "fs3_pruned_candidate",
        "preferred_model_names": ("xgboost_fs3_combo_pruned_candidate", "xgboost_fs3_combo_promoted"),
    },
)

FS2_REFERENCE_CONTEXTS: tuple[dict[str, object], ...] = (
    {
        "candidate_key": "lear_fs2",
        "candidate_label": "LEAR FS2",
        "run_label": "lear_fs2_benchmark",
        "model_family": "lear",
        "fs_level": "FS2",
        "variant": "benchmark_parent",
        "candidate_context": "fs2",
        "preferred_model_names": ("lear_fs2",),
    },
    {
        "candidate_key": "xgboost_fs2",
        "candidate_label": "XGBoost FS2",
        "run_label": "xgboost_fs2_benchmark",
        "model_family": "xgboost",
        "fs_level": "FS2",
        "variant": "benchmark_parent",
        "candidate_context": "fs2",
        "preferred_model_names": ("xgboost_fs2",),
    },
)


def default_decision_thresholds() -> dict[str, float]:
    return {
        "validation_rmae_minimum": 1.00,
        "validation_rmae_preferred": 0.95,
        "major_horizon_rmae_maximum": 1.00,
        "large_daily_level_bias_eur_per_mwh": 5.0,
        "marginal_fs3_rmae_gain_vs_fs2": 0.01,
        "clear_test_failure_rmae": 1.02,
        "clear_test_failure_horizon_pass_share": 0.40,
    }


def _run_label_from_dir_name(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def _matching_run_dirs(output_root: Path, run_label: str) -> list[Path]:
    run_root = Path(output_root) / "runs"
    if not run_root.exists():
        return []
    return sorted(
        candidate
        for candidate in run_root.iterdir()
        if candidate.is_dir() and _run_label_from_dir_name(candidate.name) == str(run_label)
    )


def _prediction_artifact_name(run_dir: Path) -> str | None:
    for filename in PREDICTION_ARTIFACT_OPTIONS:
        if (run_dir / filename).exists():
            return filename
    return None


def _missing_evaluation_artifacts(run_dir: Path) -> list[str]:
    missing = [filename for filename in EVALUATION_REQUIRED_ARTIFACTS if not (run_dir / filename).exists()]
    if _prediction_artifact_name(run_dir) is None:
        missing.append("predictions_long.parquet|csv")
    return missing


def run_is_complete_for_decision_evaluation(run_dir: Path) -> bool:
    return not _missing_evaluation_artifacts(run_dir)


def find_latest_complete_run(
    output_root: Path,
    run_label: str,
) -> Path | None:
    candidates = _matching_run_dirs(output_root, run_label)
    for candidate in reversed(candidates):
        if run_is_complete_for_decision_evaluation(candidate):
            return candidate
    return None


def _load_run_model_catalog(run_dir: Path) -> pd.DataFrame:
    suite_models_path = run_dir / "suite_models.json"
    if suite_models_path.exists():
        suite_models = load_json(run_dir, "suite_models.json")
        rows: list[dict[str, object]] = []
        for record in suite_models.get("models", []):
            model_name = record.get("model") or record.get("name")
            if not model_name:
                continue
            rows.append(
                {
                    "model": str(model_name),
                    "model_family": str(record.get("model_family") or record.get("family") or ""),
                    "fs_level": str(record.get("fs_level") or ""),
                }
            )
        if rows:
            return pd.DataFrame(rows).drop_duplicates(subset=["model"]).reset_index(drop=True)

    metrics_overall_path = run_dir / "metrics_overall.csv"
    if metrics_overall_path.exists():
        metrics = pd.read_csv(metrics_overall_path)
        if "model" in metrics.columns:
            frame = metrics[[column for column in ("model", "model_family", "fs_level") if column in metrics.columns]].copy()
            if "model_family" not in frame.columns:
                frame["model_family"] = ""
            if "fs_level" not in frame.columns:
                frame["fs_level"] = ""
            return frame.drop_duplicates(subset=["model"]).reset_index(drop=True)

    return pd.DataFrame(columns=["model", "model_family", "fs_level"])


def _resolve_candidate_model_name(
    run_dir: Path,
    *,
    model_family: str,
    fs_level: str,
    preferred_model_names: tuple[str, ...] | None = None,
) -> str:
    catalog = _load_run_model_catalog(run_dir)
    if catalog.empty:
        raise ValueError(f"No model catalog could be resolved for {run_dir}.")

    preferred_model_names = tuple(str(value) for value in (preferred_model_names or ()))
    available_models = set(catalog["model"].astype(str).tolist())
    for model_name in preferred_model_names:
        if model_name in available_models:
            return model_name

    family_rows = catalog[catalog["model_family"].astype(str) == str(model_family)].copy()
    if not family_rows.empty:
        fs_rows = family_rows[family_rows["fs_level"].astype(str) == str(fs_level)].copy()
        if not fs_rows.empty:
            fs_rows = fs_rows.sort_values("model").reset_index(drop=True)
            return str(fs_rows.iloc[0]["model"])
        family_rows = family_rows.sort_values("model").reset_index(drop=True)
        return str(family_rows.iloc[0]["model"])

    non_naive = catalog[~catalog["model"].astype(str).str.startswith("naive_")].copy()
    if not non_naive.empty:
        non_naive = non_naive.sort_values(["fs_level", "model"], ascending=[False, True]).reset_index(drop=True)
        return str(non_naive.iloc[0]["model"])

    raise ValueError(f"Could not resolve a benchmark model for {run_dir}.")


def _resolve_context_run(
    output_root: Path,
    context: dict[str, object],
) -> dict[str, object]:
    run_label = str(context["run_label"])
    candidates = _matching_run_dirs(output_root, run_label)
    latest_any = candidates[-1] if candidates else None
    latest_complete = find_latest_complete_run(output_root, run_label)
    selected_run = latest_complete
    selected_model = None
    prediction_artifact = None
    if selected_run is not None:
        selected_model = _resolve_candidate_model_name(
            selected_run,
            model_family=str(context["model_family"]),
            fs_level=str(context["fs_level"]),
            preferred_model_names=tuple(context.get("preferred_model_names", ())),
        )
        prediction_artifact = _prediction_artifact_name(selected_run)

    if latest_any is None:
        availability_status = "missing"
        note = "No run folder exists for this exact run label."
    elif latest_complete is None:
        availability_status = "incomplete_only"
        note = f"Latest folder {latest_any.name} is incomplete for decision evaluation and was not used."
    elif latest_any != latest_complete:
        availability_status = "latest_incomplete_fallback"
        note = f"Newer incomplete folder {latest_any.name} was skipped; {latest_complete.name} is the latest complete run."
    else:
        availability_status = "complete"
        note = "Latest complete run selected."

    return {
        **context,
        "selected_run_dir": selected_run,
        "selected_run_id": selected_run.name if selected_run is not None else None,
        "selected_model": selected_model,
        "prediction_artifact": prediction_artifact,
        "latest_run_dir": latest_any,
        "latest_run_id": latest_any.name if latest_any is not None else None,
        "availability_status": availability_status,
        "missing_artifacts_latest": _missing_evaluation_artifacts(latest_any) if latest_any is not None else ["run_folder"],
        "note": note,
    }


def _select_fs2_reference_from_comparison(output_root: Path) -> tuple[pd.DataFrame, str | None, str]:
    comparison_run = find_latest_complete_run(output_root, "model_comparison")
    if comparison_run is None:
        return pd.DataFrame(), None, "No complete model_comparison artifact was available."

    metrics = load_csv(comparison_run, "metrics_by_reporting_level.csv")
    if metrics.empty:
        return pd.DataFrame(), None, "The latest complete model_comparison artifact had no metrics_by_reporting_level rows."

    candidates = metrics[
        (metrics["dataset_split"].astype(str) == "validation")
        & (metrics["reporting_level"].astype(str) == "stitched_all_horizon")
        & (metrics["model"].astype(str).isin(["lear_fs2", "xgboost_fs2"]))
    ].copy()
    if candidates.empty:
        return pd.DataFrame(), None, "The latest complete model_comparison artifact had no validation full-horizon LEAR/XGBoost FS2 rows."

    candidates["candidate_label"] = candidates["model"].map({"lear_fs2": "LEAR FS2", "xgboost_fs2": "XGBoost FS2"})
    candidates["abs_bias"] = candidates["bias"].astype(float).abs()
    candidates = candidates.sort_values(["rmae_vs_official_naive", "mae", "rmse", "abs_bias", "model"]).reset_index(drop=True)
    selected_model = str(candidates.iloc[0]["model"])
    rule = (
        f"Selected from {comparison_run.name} using validation full-horizon "
        "rMAE, then MAE, RMSE, and |bias| as tie-breakers."
    )
    return candidates, selected_model, rule


def _resolve_fs2_reference_rows(
    output_root: Path,
    resolved_contexts: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], pd.DataFrame, str]:
    comparison_candidates, selected_model, selection_rule = _select_fs2_reference_from_comparison(output_root)
    rows: list[dict[str, object]] = []

    if selected_model is not None:
        selected_context = resolved_contexts[selected_model]
        rows.append(
            {
                **selected_context,
                "candidate_key": "best_fs2_reference",
                "candidate_label": "Best FS2 reference",
                "underlying_candidate_label": str(selected_context["candidate_label"]),
                "underlying_model": str(selected_context["selected_model"]),
                "candidate_context": "fs2_reference",
                "variant": "validation_selected_reference",
                "selection_rule": selection_rule,
            }
        )
        return rows, comparison_candidates, selection_rule

    available_fs2 = [
        resolved_contexts[key]
        for key in ("lear_fs2", "xgboost_fs2")
        if resolved_contexts[key]["selected_run_dir"] is not None
    ]
    for context in available_fs2:
        rows.append(
            {
                **context,
                "underlying_candidate_label": str(context["candidate_label"]),
                "underlying_model": str(context["selected_model"]),
                "selection_rule": "No single FS2 reference could be resolved from existing metadata; both latest complete LEAR and XGBoost FS2 parents are included.",
            }
        )
    fallback_rule = (
        "No single FS2 reference could be resolved from existing metadata; "
        "both latest complete LEAR and XGBoost FS2 parents are included."
    )
    return rows, comparison_candidates, selection_rule or fallback_rule


def _resolve_official_naive_reference(
    resolved_contexts: dict[str, dict[str, object]],
    fs2_rows: list[dict[str, object]],
) -> tuple[dict[str, object], Path]:
    preferred_rows = fs2_rows + [resolved_contexts[context["candidate_key"]] for context in FS3_FINAL_CANDIDATE_CONTEXTS]
    for row in preferred_rows:
        run_dir = row.get("selected_run_dir")
        if run_dir is None:
            continue
        reference = load_json(Path(run_dir), "official_naive_reference.json")
        return reference, Path(run_dir)
    raise FileNotFoundError("No complete benchmark-parent run was available to resolve official_naive_reference.json.")


def _resolve_naive_prediction_source(
    official_naive_model: str,
    candidate_rows: list[dict[str, object]],
) -> tuple[Path | None, str | None]:
    for row in candidate_rows:
        run_dir = row.get("selected_run_dir")
        if run_dir is None:
            continue
        catalog = _load_run_model_catalog(Path(run_dir))
        if official_naive_model in set(catalog["model"].astype(str).tolist()) and _prediction_artifact_name(Path(run_dir)) is not None:
            return Path(run_dir), official_naive_model
    return None, None


def discover_final_candidate_runs(output_root: Path) -> dict[str, object]:
    fs3_rows = {
        str(context["candidate_key"]): _resolve_context_run(output_root, context)
        for context in FS3_FINAL_CANDIDATE_CONTEXTS
    }
    fs2_rows = {
        str(context["candidate_key"]): _resolve_context_run(output_root, context)
        for context in FS2_REFERENCE_CONTEXTS
    }
    resolved_contexts = {**fs2_rows, **fs3_rows}
    fs2_reference_rows, fs2_selection_table, fs2_selection_rule = _resolve_fs2_reference_rows(output_root, resolved_contexts)
    official_naive_reference, rmae_reference_run_dir = _resolve_official_naive_reference(resolved_contexts, fs2_reference_rows)
    official_naive_model = str(official_naive_reference["model"])

    comparison_candidates = fs2_reference_rows + [fs3_rows[str(context["candidate_key"])] for context in FS3_FINAL_CANDIDATE_CONTEXTS]
    naive_prediction_run_dir, naive_prediction_model = _resolve_naive_prediction_source(official_naive_model, comparison_candidates)
    naive_prediction_available = naive_prediction_run_dir is not None and naive_prediction_model is not None

    main_candidate_rows: list[dict[str, object]] = []
    main_candidate_rows.append(
        {
            "candidate_key": "official_naive_benchmark",
            "candidate_label": f"Naive {official_naive_model.replace('naive_', '').replace('_', ' ')}",
            "display_group": "benchmark",
            "run_label": _run_label_from_dir_name(naive_prediction_run_dir.name) if naive_prediction_run_dir is not None else None,
            "selected_run_dir": naive_prediction_run_dir,
            "selected_run_id": naive_prediction_run_dir.name if naive_prediction_run_dir is not None else None,
            "selected_model": naive_prediction_model,
            "underlying_candidate_label": None,
            "underlying_model": official_naive_model,
            "model_family": "naive",
            "fs_level": str(official_naive_reference.get("fs_level", "FS0")),
            "variant": "official_reference",
            "candidate_context": "benchmark",
            "prediction_available": bool(naive_prediction_available),
            "selection_rule": "Validation-selected official naive benchmark from official_naive_reference.json.",
            "note": (
                f"Prediction rows are loaded from {naive_prediction_run_dir.name}."
                if naive_prediction_run_dir is not None
                else "No benchmark-parent prediction rows were available for the official naive benchmark."
            ),
        }
    )
    for row in fs2_reference_rows:
        main_candidate_rows.append(
            {
                **row,
                "display_group": "fs2",
                "prediction_available": bool(row.get("selected_run_dir") is not None and row.get("selected_model")),
            }
        )
    for context in FS3_FINAL_CANDIDATE_CONTEXTS:
        row = fs3_rows[str(context["candidate_key"])]
        main_candidate_rows.append(
            {
                **row,
                "display_group": "fs3",
                "underlying_candidate_label": str(row["candidate_label"]),
                "underlying_model": str(row["selected_model"]) if row["selected_model"] is not None else None,
                "selection_rule": "Latest complete targeted benchmark-parent run for this final FS3 context.",
                "prediction_available": bool(row.get("selected_run_dir") is not None and row.get("selected_model")),
            }
        )

    availability_rows: list[dict[str, object]] = []
    for row in [*fs2_rows.values(), *fs3_rows.values()]:
        availability_rows.append(
            {
                "candidate_label": row["candidate_label"],
                "run_label": row["run_label"],
                "latest_folder": row["latest_run_id"],
                "selected_complete_folder": row["selected_run_id"],
                "selected_model": row["selected_model"],
                "status": row["availability_status"],
                "prediction_artifact": row["prediction_artifact"] or "-",
                "missing_latest_artifacts": ", ".join(row["missing_artifacts_latest"]) if row["missing_artifacts_latest"] else "",
                "note": row["note"],
            }
        )
    availability_rows.append(
        {
            "candidate_label": "Official naive benchmark",
            "run_label": main_candidate_rows[0]["run_label"],
            "latest_folder": main_candidate_rows[0]["selected_run_id"],
            "selected_complete_folder": main_candidate_rows[0]["selected_run_id"],
            "selected_model": official_naive_model,
            "status": "prediction_ready" if naive_prediction_available else "aggregate_only",
            "prediction_artifact": _prediction_artifact_name(naive_prediction_run_dir) if naive_prediction_run_dir is not None else "-",
            "missing_latest_artifacts": "" if naive_prediction_available else "predictions_long.parquet|csv",
            "note": main_candidate_rows[0]["note"],
        }
    )
    availability_rows.append(
        {
            "candidate_label": "Frozen case weeks",
            "run_label": "case_week_selection",
            "latest_folder": latest_case_week_run_id(output_root),
            "selected_complete_folder": latest_case_week_run_id(output_root),
            "selected_model": "-",
            "status": "complete" if latest_case_week_run_id(output_root) is not None else "missing",
            "prediction_artifact": "-",
            "missing_latest_artifacts": "" if latest_case_week_run_id(output_root) is not None else "selected_weeks.csv",
            "note": "Frozen objective weeks are reused; this notebook does not reselect them.",
        }
    )

    candidate_frame = pd.DataFrame(main_candidate_rows)
    validate_unique_candidate_labels(candidate_frame)
    return {
        "availability": pd.DataFrame(availability_rows).reset_index(drop=True),
        "candidates": candidate_frame.reset_index(drop=True),
        "fs2_selection_table": fs2_selection_table.reset_index(drop=True),
        "fs2_selection_rule": fs2_selection_rule,
        "official_naive_reference": official_naive_reference,
        "official_naive_model": official_naive_model,
        "naive_prediction_available": bool(naive_prediction_available),
        "naive_prediction_run_dir": naive_prediction_run_dir,
        "rmae_reference_run_dir": rmae_reference_run_dir,
    }


def latest_case_week_run_id(output_root: Path) -> str | None:
    try:
        return find_latest_run(Path(output_root), "case_week_selection").name
    except FileNotFoundError:
        return None


def validate_unique_candidate_labels(candidate_frame: pd.DataFrame) -> None:
    if candidate_frame.empty:
        return
    duplicated = candidate_frame["candidate_label"].astype(str).duplicated(keep=False)
    if duplicated.any():
        labels = sorted(candidate_frame.loc[duplicated, "candidate_label"].astype(str).unique().tolist())
        raise ValueError(f"Candidate labels must be unique. Duplicates: {labels}")


def normalize_prediction_schema(
    predictions: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
) -> pd.DataFrame:
    if predictions.empty:
        return predictions.copy()

    frame = predictions.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True, errors="coerce")
    if "target_known_at_utc" in frame.columns:
        frame["target_known_at_utc"] = pd.to_datetime(frame["target_known_at_utc"], utc=True, errors="coerce")
    frame["lead_day"] = frame["lead_day"].astype(int)
    frame["lead_day_label"] = frame.get("lead_day_label", frame["lead_day"].map(lambda value: "D" if int(value) == 0 else f"D+{int(value)}"))
    timezone = config.resolved_business_timezone()
    frame["forecast_origin_local"] = frame["forecast_origin_utc"].dt.tz_convert(timezone)
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert(timezone)
    frame["target_local_date"] = frame["target_timestamp_local"].dt.date
    frame["target_local_hour"] = frame["target_timestamp_local"].dt.hour
    frame["target_local_dayofweek"] = frame["target_timestamp_local"].dt.dayofweek
    frame["error"] = frame["y_pred"] - frame["y_true"]
    frame["abs_error"] = frame["error"].abs()
    frame["squared_error"] = frame["error"] ** 2
    denom_smape = (frame["y_true"].abs() + frame["y_pred"].abs()).replace(0.0, np.nan)
    frame["smape_component"] = (2.0 * frame["abs_error"] / denom_smape) * 100.0
    return frame.sort_values(["candidate_label", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)


def load_candidate_predictions(
    *,
    candidate_frame: pd.DataFrame,
    config: HourlyDAPipelineConfig,
) -> pd.DataFrame:
    if candidate_frame.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    needed_columns = {
        "model",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "lead_day_label",
        "y_true",
        "y_pred",
    }
    for row in candidate_frame.to_dict(orient="records"):
        if not bool(row.get("prediction_available")):
            continue
        run_dir = row.get("selected_run_dir")
        model_name = row.get("selected_model")
        if run_dir is None or model_name is None:
            continue

        prediction_path = resolve_tabular_path(Path(run_dir), "predictions_long.csv")
        if prediction_path.suffix.lower() == ".parquet":
            try:
                prediction_frame = pd.read_parquet(prediction_path, columns=list(needed_columns))
            except Exception:
                prediction_frame = pd.read_parquet(prediction_path)
        else:
            prediction_frame = pd.read_csv(
                prediction_path,
                usecols=lambda name: str(name) in needed_columns,
                low_memory=False,
            )
        if prediction_frame.empty:
            continue
        if "model" not in prediction_frame.columns:
            continue
        mask = prediction_frame["model"].astype(str).to_numpy(dtype=str) == str(model_name)
        prediction_frame = prediction_frame.loc[mask].copy()
        if prediction_frame.empty:
            continue

        prediction_frame["candidate_key"] = str(row["candidate_key"])
        prediction_frame["candidate_label"] = str(row["candidate_label"])
        prediction_frame["candidate_context"] = str(row["candidate_context"])
        prediction_frame["variant"] = str(row["variant"])
        prediction_frame["display_group"] = str(row["display_group"])
        prediction_frame["internal_model"] = str(model_name)
        prediction_frame["model_family"] = str(row["model_family"])
        prediction_frame["fs_level"] = str(row["fs_level"])
        prediction_frame["source_run_id"] = str(row["selected_run_id"])
        prediction_frame["source_run_label"] = str(row["run_label"])
        frames.append(prediction_frame)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    required_columns = [
        "candidate_key",
        "candidate_label",
        "candidate_context",
        "variant",
        "display_group",
        "internal_model",
        "model_family",
        "fs_level",
        "source_run_id",
        "source_run_label",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "y_true",
        "y_pred",
    ]
    missing_columns = [column for column in required_columns if column not in combined.columns]
    if missing_columns:
        raise ValueError(f"Candidate prediction bundle is missing required columns: {missing_columns}")
    return normalize_prediction_schema(combined, config=config)


def load_candidate_runtime_summary(candidate_frame: pd.DataFrame) -> pd.DataFrame:
    if candidate_frame.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for row in candidate_frame.to_dict(orient="records"):
        run_dir = row.get("selected_run_dir")
        model_name = row.get("selected_model")
        if run_dir is None or model_name is None:
            continue
        timing = load_csv(Path(run_dir), "origin_timing_summary.csv")
        if timing.empty:
            continue
        timing = timing[timing["model"].astype(str) == str(model_name)].copy()
        if timing.empty:
            continue
        timing["candidate_key"] = str(row["candidate_key"])
        timing["candidate_label"] = str(row["candidate_label"])
        timing["candidate_context"] = str(row["candidate_context"])
        timing["internal_model"] = str(model_name)
        timing["source_run_id"] = str(row["selected_run_id"])
        timing["source_run_label"] = str(row["run_label"])
        frames.append(timing)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["candidate_label", "dataset_split"]).reset_index(drop=True)


def load_candidate_model_settings(candidate_frame: pd.DataFrame) -> pd.DataFrame:
    if candidate_frame.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for row in candidate_frame.to_dict(orient="records"):
        run_dir = row.get("selected_run_dir")
        model_name = row.get("selected_model")
        if run_dir is None or model_name is None:
            continue
        settings = load_csv(Path(run_dir), "model_settings_summary.csv")
        if settings.empty:
            continue
        settings = settings[settings["model"].astype(str) == str(model_name)].copy()
        if settings.empty:
            continue
        settings["candidate_key"] = str(row["candidate_key"])
        settings["candidate_label"] = str(row["candidate_label"])
        settings["candidate_context"] = str(row["candidate_context"])
        settings["source_run_id"] = str(row["selected_run_id"])
        settings["source_run_label"] = str(row["run_label"])
        frames.append(settings)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["candidate_label"]).reset_index(drop=True)


def load_official_naive_denominators(
    *,
    run_dir: Path,
    official_naive_model: str,
) -> dict[str, pd.DataFrame]:
    overall = load_csv(run_dir, "metrics_overall.csv")
    by_lead = load_csv(run_dir, "metrics_by_lead_day.csv")
    by_reporting = load_csv(run_dir, "metrics_by_reporting_level.csv")

    overall = (
        overall[overall["model"].astype(str) == str(official_naive_model)][["dataset_split", "mae"]]
        .rename(columns={"mae": "naive_mae"})
        .drop_duplicates(subset=["dataset_split"])
        .reset_index(drop=True)
    )
    by_lead = (
        by_lead[by_lead["model"].astype(str) == str(official_naive_model)][["dataset_split", "lead_day", "lead_day_label", "mae"]]
        .rename(columns={"mae": "naive_mae"})
        .drop_duplicates(subset=["dataset_split", "lead_day"])
        .reset_index(drop=True)
    )
    by_reporting = (
        by_reporting[
            by_reporting["model"].astype(str) == str(official_naive_model)
        ][["dataset_split", "reporting_level", "reporting_level_label", "mae"]]
        .rename(columns={"mae": "naive_mae"})
        .drop_duplicates(subset=["dataset_split", "reporting_level"])
        .reset_index(drop=True)
    )
    if overall.empty:
        raise ValueError("The official naive denominator could not be loaded from metrics_overall.csv.")
    return {"overall": overall, "by_lead_day": by_lead, "by_reporting_level": by_reporting}


def summarize_candidate_coverage(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    grouped = (
        predictions.groupby(["candidate_label", "dataset_split", "lead_day", "lead_day_label"], dropna=False)
        .agg(
            rows=("target_timestamp_utc", "size"),
            forecast_origins=("forecast_origin_utc", "nunique"),
            unique_targets=("target_timestamp_utc", "nunique"),
        )
        .reset_index()
        .sort_values(["candidate_label", "dataset_split", "lead_day"])
        .reset_index(drop=True)
    )
    return grouped


def summarize_missingness(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in predictions.groupby(["candidate_label", "dataset_split"], dropna=False):
        candidate_label, dataset_split = keys
        rows.append(
            {
                "candidate_label": candidate_label,
                "dataset_split": dataset_split,
                "rows": int(group.shape[0]),
                "missing_actuals": int(group["y_true"].isna().sum()),
                "missing_predictions": int(group["y_pred"].isna().sum()),
                "missing_either": int((group["y_true"].isna() | group["y_pred"].isna()).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["candidate_label", "dataset_split"]).reset_index(drop=True)


def summarize_duplicate_origin_targets(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    duplicate_counts = (
        predictions.groupby(
            ["candidate_label", "dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"],
            dropna=False,
        )
        .size()
        .rename("duplicate_count")
        .reset_index()
    )
    duplicate_counts = duplicate_counts[duplicate_counts["duplicate_count"] > 1].copy()
    if duplicate_counts.empty:
        return pd.DataFrame(
            [
                {
                    "candidate_label": candidate_label,
                    "dataset_split": dataset_split,
                    "duplicate_origin_target_rows": 0,
                }
                for candidate_label, dataset_split in predictions[["candidate_label", "dataset_split"]].drop_duplicates().itertuples(index=False)
            ]
        )
    summary = (
        duplicate_counts.groupby(["candidate_label", "dataset_split"], dropna=False)
        .agg(duplicate_origin_target_rows=("duplicate_count", "sum"))
        .reset_index()
        .sort_values(["candidate_label", "dataset_split"])
        .reset_index(drop=True)
    )
    return summary


def summarize_local_day_lengths(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    base = (
        predictions[["dataset_split", "target_timestamp_utc", "target_local_date"]]
        .drop_duplicates(subset=["dataset_split", "target_timestamp_utc"])
        .copy()
    )
    day_lengths = (
        base.groupby(["dataset_split", "target_local_date"], dropna=False)
        .size()
        .rename("hours_in_local_day")
        .reset_index()
    )
    summary = (
        day_lengths.groupby(["dataset_split", "hours_in_local_day"], dropna=False)
        .size()
        .rename("days")
        .reset_index()
        .sort_values(["dataset_split", "hours_in_local_day"])
        .reset_index(drop=True)
    )
    return summary


def build_stitched_d_only_predictions(
    predictions: pd.DataFrame,
    *,
    split_name: str | None = None,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    stitched = predictions[predictions["lead_day"].astype(int) == 0].copy()
    if split_name is not None:
        stitched = stitched[stitched["dataset_split"].astype(str) == str(split_name)].copy()
    if stitched.empty:
        return stitched
    stitched = stitched.sort_values(["candidate_label", "dataset_split", "target_timestamp_utc", "forecast_origin_utc"])
    stitched = stitched.drop_duplicates(subset=["candidate_key", "dataset_split", "target_timestamp_utc"], keep="last")
    return stitched.reset_index(drop=True)


def summarize_stitched_overlap_check(stitched_predictions: pd.DataFrame) -> pd.DataFrame:
    if stitched_predictions.empty:
        return pd.DataFrame()
    overlap = (
        stitched_predictions.groupby(["candidate_label", "dataset_split", "target_timestamp_utc"], dropna=False)
        .size()
        .rename("row_count")
        .reset_index()
    )
    summary = (
        overlap.groupby(["candidate_label", "dataset_split"], dropna=False)
        .agg(overlap_rows=("row_count", lambda values: int((pd.Series(values) > 1).sum())))
        .reset_index()
        .sort_values(["candidate_label", "dataset_split"])
        .reset_index(drop=True)
    )
    return summary


def _metric_row(group: pd.DataFrame) -> dict[str, object]:
    valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
    if valid.empty:
        return {
            "observations_total": int(group.shape[0]),
            "observations_scored": 0,
            "coverage_pct": 0.0,
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
            "smape_pct": np.nan,
            "median_ae": np.nan,
            "p90_ae": np.nan,
            "p95_ae": np.nan,
        }
    return {
        "observations_total": int(group.shape[0]),
        "observations_scored": int(valid.shape[0]),
        "coverage_pct": float(valid.shape[0] / group.shape[0] * 100.0),
        "mae": float(valid["abs_error"].mean()),
        "rmse": float(math.sqrt(valid["squared_error"].mean())),
        "bias": float(valid["error"].mean()),
        "smape_pct": float(valid["smape_component"].mean(skipna=True)),
        "median_ae": float(valid["abs_error"].median()),
        "p90_ae": float(valid["abs_error"].quantile(0.90)),
        "p95_ae": float(valid["abs_error"].quantile(0.95)),
    }


def _attach_rmae_from_lookup(
    metrics: pd.DataFrame,
    denominator_frame: pd.DataFrame,
    *,
    join_keys: list[str],
    output_col: str = "rmae_vs_official_naive",
) -> pd.DataFrame:
    if denominator_frame.empty:
        raise ValueError("The rMAE denominator lookup is empty.")
    merged = metrics.merge(denominator_frame, on=join_keys, how="left")
    if merged["naive_mae"].isna().any():
        missing = merged.loc[merged["naive_mae"].isna(), join_keys].drop_duplicates().to_dict(orient="records")
        raise ValueError(f"Missing rMAE denominator rows for {missing}.")
    merged[output_col] = merged["mae"] / merged["naive_mae"]
    merged.loc[merged["naive_mae"] == 0.0, output_col] = np.nan
    merged["rmae"] = merged[output_col]
    return merged.drop(columns=["naive_mae"])


def compute_classical_metrics(
    predictions: pd.DataFrame,
    naive_denominators: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    rows = []
    group_cols = ["candidate_key", "candidate_label", "candidate_context", "display_group", "model_family", "fs_level", "dataset_split"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_metric_row(group))
        row["forecast_origins"] = int(group["forecast_origin_utc"].nunique())
        row["unique_targets"] = int(group["target_timestamp_utc"].nunique())
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values(["dataset_split", "mae", "candidate_label"]).reset_index(drop=True)
    return _attach_rmae_from_lookup(frame, naive_denominators["overall"], join_keys=["dataset_split"])


def compute_horizon_metrics(
    predictions: pd.DataFrame,
    naive_denominators: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    rows = []
    group_cols = [
        "candidate_key",
        "candidate_label",
        "candidate_context",
        "display_group",
        "model_family",
        "fs_level",
        "dataset_split",
        "lead_day",
        "lead_day_label",
    ]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_metric_row(group))
        row["forecast_origins"] = int(group["forecast_origin_utc"].nunique())
        row["unique_targets"] = int(group["target_timestamp_utc"].nunique())
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values(["dataset_split", "lead_day", "mae", "candidate_label"]).reset_index(drop=True)
    return _attach_rmae_from_lookup(frame, naive_denominators["by_lead_day"], join_keys=["dataset_split", "lead_day", "lead_day_label"])


def compute_daily_level_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label", "target_local_date"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row = dict(zip(group_cols, keys, strict=True))
        row["hours_total"] = int(group.shape[0])
        row["hours_scored"] = int(valid.shape[0])
        row["coverage_pct"] = float(valid.shape[0] / group.shape[0] * 100.0) if group.shape[0] else 0.0
        if valid.empty:
            row.update(
                {
                    "actual_daily_mean": np.nan,
                    "forecast_daily_mean": np.nan,
                    "daily_level_abs_error": np.nan,
                    "daily_level_bias": np.nan,
                    "actual_daily_std": np.nan,
                    "forecast_daily_std": np.nan,
                    "daily_std_error": np.nan,
                    "actual_daily_range": np.nan,
                    "forecast_daily_range": np.nan,
                    "daily_range_error": np.nan,
                }
            )
        else:
            actual_mean = float(valid["y_true"].mean())
            forecast_mean = float(valid["y_pred"].mean())
            actual_std = float(valid["y_true"].std(ddof=0))
            forecast_std = float(valid["y_pred"].std(ddof=0))
            actual_range = float(valid["y_true"].max() - valid["y_true"].min())
            forecast_range = float(valid["y_pred"].max() - valid["y_pred"].min())
            row.update(
                {
                    "actual_daily_mean": actual_mean,
                    "forecast_daily_mean": forecast_mean,
                    "daily_level_abs_error": abs(forecast_mean - actual_mean),
                    "daily_level_bias": forecast_mean - actual_mean,
                    "actual_daily_std": actual_std,
                    "forecast_daily_std": forecast_std,
                    "daily_std_error": forecast_std - actual_std,
                    "actual_daily_range": actual_range,
                    "forecast_daily_range": forecast_range,
                    "daily_range_error": forecast_range - actual_range,
                }
            )
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["candidate_label", "dataset_split", "lead_day", "target_local_date"]).reset_index(drop=True)
    summary = (
        daily.groupby(["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label"], dropna=False)
        .agg(
            days=("target_local_date", "nunique"),
            valid_days=("daily_level_abs_error", lambda values: int(pd.Series(values).notna().sum())),
            mean_daily_level_mae=("daily_level_abs_error", "mean"),
            mean_daily_level_bias=("daily_level_bias", "mean"),
            mean_daily_volatility_error=("daily_std_error", "mean"),
            mean_daily_range_error=("daily_range_error", "mean"),
            mean_abs_daily_level_bias=("daily_level_bias", lambda values: float(pd.Series(values).abs().mean())),
            mean_abs_daily_volatility_error=("daily_std_error", lambda values: float(pd.Series(values).abs().mean())),
            mean_abs_daily_range_error=("daily_range_error", lambda values: float(pd.Series(values).abs().mean())),
        )
        .reset_index()
        .sort_values(["dataset_split", "lead_day", "mean_daily_level_mae", "candidate_label"])
        .reset_index(drop=True)
    )
    return daily, summary


def _timing_error_hours(actual_ts: pd.Timestamp | None, predicted_ts: pd.Timestamp | None) -> float:
    if actual_ts is None or predicted_ts is None or pd.isna(actual_ts) or pd.isna(predicted_ts):
        return np.nan
    return abs((pd.Timestamp(predicted_ts) - pd.Timestamp(actual_ts)).total_seconds()) / 3600.0


def _extreme_timestamp(group: pd.DataFrame, value_col: str, *, ascending: bool) -> pd.Timestamp | None:
    if group.empty:
        return None
    ordered = group.sort_values([value_col, "target_timestamp_utc"], ascending=[ascending, True]).reset_index(drop=True)
    return pd.Timestamp(ordered.iloc[0]["target_timestamp_utc"])


def compute_daily_shape_metrics(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label", "target_local_date"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row = dict(zip(group_cols, keys, strict=True))
        row["hours_scored"] = int(valid.shape[0])
        row["flat_actual_day"] = False
        if valid.shape[0] < 2:
            row.update(
                {
                    "pearson_corr": np.nan,
                    "spearman_corr": np.nan,
                    "demeaned_shape_mae": np.nan,
                    "peak_hour_timing_error": np.nan,
                    "trough_hour_timing_error": np.nan,
                }
            )
        else:
            actual_std = float(valid["y_true"].std(ddof=0))
            predicted_std = float(valid["y_pred"].std(ddof=0))
            if actual_std <= 1e-12:
                pearson_corr = np.nan
                spearman_corr = np.nan
                row["flat_actual_day"] = True
            else:
                pearson_corr = float(valid["y_true"].corr(valid["y_pred"], method="pearson")) if predicted_std > 1e-12 else np.nan
                spearman_corr = float(valid["y_true"].corr(valid["y_pred"], method="spearman")) if predicted_std > 1e-12 else np.nan
            actual_demeaned = valid["y_true"] - float(valid["y_true"].mean())
            pred_demeaned = valid["y_pred"] - float(valid["y_pred"].mean())
            row.update(
                {
                    "pearson_corr": pearson_corr,
                    "spearman_corr": spearman_corr,
                    "demeaned_shape_mae": float((pred_demeaned - actual_demeaned).abs().mean()),
                    "peak_hour_timing_error": _timing_error_hours(
                        _extreme_timestamp(valid, "y_true", ascending=False),
                        _extreme_timestamp(valid, "y_pred", ascending=False),
                    ),
                    "trough_hour_timing_error": _timing_error_hours(
                        _extreme_timestamp(valid, "y_true", ascending=True),
                        _extreme_timestamp(valid, "y_pred", ascending=True),
                    ),
                }
            )
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["candidate_label", "dataset_split", "lead_day", "target_local_date"]).reset_index(drop=True)
    summary = (
        daily.groupby(["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label"], dropna=False)
        .agg(
            days=("target_local_date", "nunique"),
            valid_pearson_days=("pearson_corr", lambda values: int(pd.Series(values).notna().sum())),
            valid_spearman_days=("spearman_corr", lambda values: int(pd.Series(values).notna().sum())),
            flat_actual_days=("flat_actual_day", lambda values: int(pd.Series(values).fillna(False).sum())),
            mean_pearson_corr=("pearson_corr", "mean"),
            mean_spearman_corr=("spearman_corr", "mean"),
            mean_demeaned_shape_mae=("demeaned_shape_mae", "mean"),
            mean_peak_hour_timing_error=("peak_hour_timing_error", "mean"),
            mean_trough_hour_timing_error=("trough_hour_timing_error", "mean"),
        )
        .reset_index()
        .sort_values(["dataset_split", "lead_day", "mean_demeaned_shape_mae", "candidate_label"])
        .reset_index(drop=True)
    )
    return daily, summary


def compute_topk_hour_metrics(
    predictions: pd.DataFrame,
    *,
    ks: tuple[int, ...] = (3, 6),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label", "target_local_date"]
    for keys, group in predictions.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].sort_values("target_timestamp_utc").copy()
        row["hours_scored"] = int(valid.shape[0])
        actual_expensive = valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[False, True]) if not valid.empty else valid
        actual_cheap = valid.sort_values(["y_true", "target_timestamp_utc"], ascending=[True, True]) if not valid.empty else valid
        pred_expensive = valid.sort_values(["y_pred", "target_timestamp_utc"], ascending=[False, True]) if not valid.empty else valid
        pred_cheap = valid.sort_values(["y_pred", "target_timestamp_utc"], ascending=[True, True]) if not valid.empty else valid
        for k in ks:
            if valid.shape[0] < k:
                row[f"top{k}_expensive_recall"] = np.nan
                row[f"top{k}_cheap_recall"] = np.nan
                continue
            actual_expensive_set = set(pd.to_datetime(actual_expensive.head(k)["target_timestamp_utc"], utc=True).tolist())
            pred_expensive_set = set(pd.to_datetime(pred_expensive.head(k)["target_timestamp_utc"], utc=True).tolist())
            actual_cheap_set = set(pd.to_datetime(actual_cheap.head(k)["target_timestamp_utc"], utc=True).tolist())
            pred_cheap_set = set(pd.to_datetime(pred_cheap.head(k)["target_timestamp_utc"], utc=True).tolist())
            row[f"top{k}_expensive_recall"] = float(len(actual_expensive_set & pred_expensive_set) / k)
            row[f"top{k}_cheap_recall"] = float(len(actual_cheap_set & pred_cheap_set) / k)
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values(["candidate_label", "dataset_split", "lead_day", "target_local_date"]).reset_index(drop=True)
    agg_map: dict[str, tuple[str, object]] = {"days": ("target_local_date", "nunique")}
    for k in ks:
        agg_map[f"valid_top{k}_expensive_days"] = (f"top{k}_expensive_recall", lambda values: int(pd.Series(values).notna().sum()))
        agg_map[f"valid_top{k}_cheap_days"] = (f"top{k}_cheap_recall", lambda values: int(pd.Series(values).notna().sum()))
        agg_map[f"mean_top{k}_expensive_recall"] = (f"top{k}_expensive_recall", "mean")
        agg_map[f"mean_top{k}_cheap_recall"] = (f"top{k}_cheap_recall", "mean")
    summary = (
        daily.groupby(["candidate_key", "candidate_label", "dataset_split", "lead_day", "lead_day_label"], dropna=False)
        .agg(**agg_map)
        .reset_index()
        .sort_values(["dataset_split", "lead_day", "candidate_label"])
        .reset_index(drop=True)
    )
    return daily, summary


def _actual_split_quantiles(predictions: pd.DataFrame) -> pd.DataFrame:
    unique_actuals = predictions[["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true"]].drop_duplicates().copy()
    return (
        unique_actuals.groupby("dataset_split", dropna=False)["y_true"]
        .agg(top_10_threshold=lambda values: float(pd.Series(values).quantile(0.90)), bottom_10_threshold=lambda values: float(pd.Series(values).quantile(0.10)))
        .reset_index()
    )


def _high_volatility_day_flags(predictions: pd.DataFrame) -> pd.DataFrame:
    unique_actuals = (
        predictions[["dataset_split", "target_timestamp_utc", "target_local_date", "y_true"]]
        .drop_duplicates(subset=["dataset_split", "target_timestamp_utc"])
        .copy()
    )
    daily_ranges = (
        unique_actuals.groupby(["dataset_split", "target_local_date"], dropna=False)["y_true"]
        .agg(actual_daily_range=lambda values: float(pd.Series(values).max() - pd.Series(values).min()))
        .reset_index()
    )
    thresholds = (
        daily_ranges.groupby("dataset_split", dropna=False)["actual_daily_range"]
        .quantile(0.90)
        .rename("high_volatility_threshold")
        .reset_index()
    )
    flagged = daily_ranges.merge(thresholds, on="dataset_split", how="left")
    flagged["is_high_volatility_day"] = flagged["actual_daily_range"] >= flagged["high_volatility_threshold"]
    return flagged[["dataset_split", "target_local_date", "actual_daily_range", "high_volatility_threshold", "is_high_volatility_day"]]


def compute_tail_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    quantiles = _actual_split_quantiles(predictions)
    volatility_flags = _high_volatility_day_flags(predictions)
    work = predictions.merge(quantiles, on="dataset_split", how="left").merge(
        volatility_flags[["dataset_split", "target_local_date", "is_high_volatility_day"]],
        on=["dataset_split", "target_local_date"],
        how="left",
    )
    work["is_top_10_actual"] = work["y_true"] > work["top_10_threshold"]
    work["is_bottom_10_actual"] = work["y_true"] < work["bottom_10_threshold"]
    work["is_negative_actual"] = work["y_true"] < 0.0
    rows = []
    group_cols = ["candidate_key", "candidate_label", "dataset_split"]
    for keys, group in work.groupby(group_cols, dropna=False):
        valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
        row = dict(zip(group_cols, keys, strict=True))
        row["top10_mae"] = float(valid.loc[valid["is_top_10_actual"], "abs_error"].mean()) if valid["is_top_10_actual"].any() else np.nan
        row["top10_bias"] = float(valid.loc[valid["is_top_10_actual"], "error"].mean()) if valid["is_top_10_actual"].any() else np.nan
        row["bottom10_mae"] = float(valid.loc[valid["is_bottom_10_actual"], "abs_error"].mean()) if valid["is_bottom_10_actual"].any() else np.nan
        row["bottom10_bias"] = float(valid.loc[valid["is_bottom_10_actual"], "error"].mean()) if valid["is_bottom_10_actual"].any() else np.nan
        row["negative_mae"] = float(valid.loc[valid["is_negative_actual"], "abs_error"].mean()) if valid["is_negative_actual"].any() else np.nan
        row["negative_bias"] = float(valid.loc[valid["is_negative_actual"], "error"].mean()) if valid["is_negative_actual"].any() else np.nan
        row["p90_ae"] = float(valid["abs_error"].quantile(0.90)) if not valid.empty else np.nan
        row["p95_ae"] = float(valid["abs_error"].quantile(0.95)) if not valid.empty else np.nan
        row["high_volatility_day_mae"] = (
            float(valid.loc[valid["is_high_volatility_day"].fillna(False), "abs_error"].mean())
            if valid["is_high_volatility_day"].fillna(False).any()
            else np.nan
        )
        row["high_volatility_day_bias"] = (
            float(valid.loc[valid["is_high_volatility_day"].fillna(False), "error"].mean())
            if valid["is_high_volatility_day"].fillna(False).any()
            else np.nan
        )
        row["top10_rows"] = int(valid["is_top_10_actual"].sum())
        row["bottom10_rows"] = int(valid["is_bottom_10_actual"].sum())
        row["negative_rows"] = int(valid["is_negative_actual"].sum())
        row["high_volatility_rows"] = int(valid["is_high_volatility_day"].fillna(False).sum())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "candidate_label"]).reset_index(drop=True)


def compute_diebold_mariano_table(
    predictions: pd.DataFrame,
    *,
    benchmark_candidate_key: str,
    challenger_candidate_keys: list[str],
    reporting_views: tuple[str, ...] = ("stitched_all_horizon", "d_only"),
    loss: str = "absolute",
    hac_lag: int = 24,
) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    benchmark_all = predictions[predictions["candidate_key"].astype(str) == str(benchmark_candidate_key)].copy()
    if benchmark_all.empty:
        return pd.DataFrame()
    benchmark_label = str(benchmark_all["candidate_label"].iloc[0])

    for reporting_view in reporting_views:
        if reporting_view == "d_only":
            benchmark = build_stitched_d_only_predictions(benchmark_all)
            merge_keys = ["dataset_split", "target_timestamp_utc", "y_true"]
        else:
            benchmark = benchmark_all.copy()
            merge_keys = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true"]

        benchmark = benchmark.rename(columns={"y_pred": "y_pred_benchmark"})
        for challenger_key in challenger_candidate_keys:
            challenger_all = predictions[predictions["candidate_key"].astype(str) == str(challenger_key)].copy()
            if challenger_all.empty:
                continue
            challenger_label = str(challenger_all["candidate_label"].iloc[0])
            challenger = build_stitched_d_only_predictions(challenger_all) if reporting_view == "d_only" else challenger_all.copy()
            challenger = challenger.rename(columns={"y_pred": "y_pred_challenger"})
            merged = benchmark.merge(challenger, on=merge_keys, how="inner")
            if merged.empty:
                continue
            for split_name, split_group in merged.groupby("dataset_split", dropna=False):
                dm_result = diebold_mariano_test(
                    actual=split_group["y_true"],
                    forecast_a=split_group["y_pred_challenger"],
                    forecast_b=split_group["y_pred_benchmark"],
                    loss=loss,
                    hac_lag=hac_lag,
                )
                dm_result.update(
                    {
                        "dataset_split": split_name,
                        "reporting_view": reporting_view,
                        "benchmark_candidate_key": benchmark_candidate_key,
                        "benchmark_candidate_label": benchmark_label,
                        "challenger_candidate_key": challenger_key,
                        "challenger_candidate_label": challenger_label,
                    }
                )
                rows.append(dm_result)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["dataset_split", "reporting_view", "challenger_candidate_label"]).reset_index(drop=True)


def load_frozen_selected_weeks(
    output_root: Path,
    *,
    categories: tuple[str, ...] | None = None,
) -> tuple[Path, pd.DataFrame]:
    run_dir = find_latest_run(Path(output_root), "case_week_selection")
    selected_weeks = load_csv(run_dir, "selected_weeks.csv")
    if categories is not None and "category" in selected_weeks.columns:
        selected_weeks = selected_weeks[selected_weeks["category"].astype(str).isin([str(value) for value in categories])].copy()
    return run_dir, selected_weeks.reset_index(drop=True)


def build_week_metric_summary(
    stitched_predictions: pd.DataFrame,
    selected_weeks: pd.DataFrame,
    *,
    benchmark_candidate_key: str | None = None,
) -> pd.DataFrame:
    if stitched_predictions.empty or selected_weeks.empty:
        return pd.DataFrame()

    rows = []
    for week in selected_weeks.to_dict(orient="records"):
        week_start = pd.Timestamp(week["week_start_local_date"]).date()
        week_end = pd.Timestamp(week["week_end_local_date"]).date()
        week_frame = stitched_predictions[
            (stitched_predictions["target_local_date"] >= week_start)
            & (stitched_predictions["target_local_date"] <= week_end)
        ].copy()
        if week_frame.empty:
            continue

        shape_daily, shape_summary = compute_daily_shape_metrics(week_frame)
        _, topk_summary = compute_topk_hour_metrics(week_frame, ks=(3,))
        for keys, group in week_frame.groupby(["candidate_key", "candidate_label"], dropna=False):
            candidate_key, candidate_label = keys
            valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
            mae = float(valid["abs_error"].mean()) if not valid.empty else np.nan
            bias = float(valid["error"].mean()) if not valid.empty else np.nan
            row = {
                "category": str(week["category"]),
                "iso_week_id": str(week["iso_week_id"]),
                "week_start_local_date": str(week["week_start_local_date"]),
                "week_end_local_date": str(week["week_end_local_date"]),
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "mae": mae,
                "bias": bias,
                "rmae": np.nan,
            }
            if benchmark_candidate_key is not None:
                benchmark_part = week_frame[week_frame["candidate_key"].astype(str) == str(benchmark_candidate_key)].copy()
                benchmark_valid = benchmark_part[benchmark_part["y_true"].notna() & benchmark_part["y_pred"].notna()].copy()
                benchmark_mae = float(benchmark_valid["abs_error"].mean()) if not benchmark_valid.empty else np.nan
                row["rmae"] = mae / benchmark_mae if pd.notna(benchmark_mae) and benchmark_mae != 0.0 and pd.notna(mae) else np.nan

            shape_row = shape_summary[shape_summary["candidate_key"].astype(str) == str(candidate_key)].copy()
            topk_row = topk_summary[topk_summary["candidate_key"].astype(str) == str(candidate_key)].copy()
            if not shape_row.empty:
                row["mean_pearson_corr"] = float(shape_row.iloc[0]["mean_pearson_corr"])
                row["mean_spearman_corr"] = float(shape_row.iloc[0]["mean_spearman_corr"])
                row["mean_demeaned_shape_mae"] = float(shape_row.iloc[0]["mean_demeaned_shape_mae"])
            else:
                row["mean_pearson_corr"] = np.nan
                row["mean_spearman_corr"] = np.nan
                row["mean_demeaned_shape_mae"] = np.nan
            if not topk_row.empty:
                row["mean_top3_expensive_recall"] = float(topk_row.iloc[0]["mean_top3_expensive_recall"])
                row["mean_top3_cheap_recall"] = float(topk_row.iloc[0]["mean_top3_cheap_recall"])
            else:
                row["mean_top3_expensive_recall"] = np.nan
                row["mean_top3_cheap_recall"] = np.nan
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["category", "candidate_label"]).reset_index(drop=True)


def build_candidate_style_map(candidate_frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if candidate_frame.empty:
        return {}
    palette = {
        "official_naive_benchmark": {"color": "#244f7a", "linestyle": "--", "linewidth": 2.7},
        "best_fs2_reference": {"color": "#2e7d5b", "linestyle": "-", "linewidth": 2.3},
        "lear_fs2": {"color": "#2e7d5b", "linestyle": "-", "linewidth": 2.0},
        "xgboost_fs2": {"color": "#4b7f2b", "linestyle": "-", "linewidth": 2.0},
        "lear_fs3_promoted": {"color": "#2f8f9d", "linestyle": "-", "linewidth": 2.2},
        "xgboost_fs3_promoted": {"color": "#cf6a32", "linestyle": "-", "linewidth": 2.2},
        "lear_fs3_pruned_candidate": {"color": "#2f8f9d", "linestyle": ":", "linewidth": 2.2},
        "xgboost_fs3_pruned_candidate": {"color": "#cf6a32", "linestyle": ":", "linewidth": 2.2},
    }
    styles: dict[str, dict[str, object]] = {}
    for _, row in candidate_frame.iterrows():
        candidate_key = str(row["candidate_key"])
        base = palette.get(candidate_key, {"color": "#6b7c8b", "linestyle": "-", "linewidth": 2.0})
        styles[candidate_key] = {
            **base,
            "label": str(row["candidate_label"]),
            "alpha": 0.95,
        }
    return styles


def build_recommendation_inputs(
    classical_metrics: pd.DataFrame,
    horizon_metrics: pd.DataFrame,
    level_summary: pd.DataFrame,
    shape_summary: pd.DataFrame,
    topk_summary: pd.DataFrame,
    tail_metrics: pd.DataFrame,
    runtime_summary: pd.DataFrame,
) -> pd.DataFrame:
    if classical_metrics.empty:
        return pd.DataFrame()

    def _safe_split_filter(frame: pd.DataFrame, split_name: str) -> pd.DataFrame:
        if frame.empty or "dataset_split" not in frame.columns:
            return pd.DataFrame(columns=frame.columns)
        return frame[frame["dataset_split"].astype(str) == str(split_name)].copy()

    def _safe_candidate_filter(frame: pd.DataFrame, candidate_key: str) -> pd.DataFrame:
        if frame.empty or "candidate_key" not in frame.columns:
            return pd.DataFrame(columns=frame.columns)
        return frame[frame["candidate_key"].astype(str) == str(candidate_key)].copy()

    validation_classical = classical_metrics[classical_metrics["dataset_split"].astype(str) == "validation"].copy()
    test_classical = classical_metrics[classical_metrics["dataset_split"].astype(str) == "test"].copy()
    validation_horizons = _safe_split_filter(horizon_metrics, "validation")
    test_horizons = _safe_split_filter(horizon_metrics, "test")
    validation_level = _safe_split_filter(level_summary, "validation")
    validation_shape = _safe_split_filter(shape_summary, "validation")
    validation_topk = _safe_split_filter(topk_summary, "validation")
    validation_tail = _safe_split_filter(tail_metrics, "validation")
    validation_runtime = _safe_split_filter(runtime_summary, "validation")

    rows = []
    for _, row in validation_classical.iterrows():
        candidate_key = str(row["candidate_key"])
        summary_row = row.to_dict()
        test_row = _safe_candidate_filter(test_classical, candidate_key)
        horizon_part = _safe_candidate_filter(validation_horizons, candidate_key)
        test_horizon_part = _safe_candidate_filter(test_horizons, candidate_key)
        level_part = _safe_candidate_filter(validation_level, candidate_key)
        shape_part = _safe_candidate_filter(validation_shape, candidate_key)
        topk_part = _safe_candidate_filter(validation_topk, candidate_key)
        tail_part = _safe_candidate_filter(validation_tail, candidate_key)
        runtime_part = _safe_candidate_filter(validation_runtime, candidate_key)

        summary_row["validation_horizon_pass_share"] = float((horizon_part["rmae"] < 1.0).mean()) if not horizon_part.empty else np.nan
        summary_row["test_horizon_pass_share"] = float((test_horizon_part["rmae"] < 1.0).mean()) if not test_horizon_part.empty else np.nan

        if not test_row.empty:
            test_record = test_row.iloc[0]
            summary_row["test_mae"] = float(test_record["mae"])
            summary_row["test_rmae"] = float(test_record["rmae"])
            summary_row["test_rmse"] = float(test_record["rmse"])
            summary_row["test_bias"] = float(test_record["bias"])
        else:
            summary_row["test_mae"] = np.nan
            summary_row["test_rmae"] = np.nan
            summary_row["test_rmse"] = np.nan
            summary_row["test_bias"] = np.nan

        if not level_part.empty:
            summary_row["validation_mean_daily_level_mae"] = float(level_part.iloc[0]["mean_daily_level_mae"])
            summary_row["validation_mean_daily_level_bias"] = float(level_part.iloc[0]["mean_daily_level_bias"])
            summary_row["validation_mean_abs_daily_level_bias"] = float(level_part.iloc[0]["mean_abs_daily_level_bias"])
            summary_row["validation_mean_abs_daily_range_error"] = float(level_part.iloc[0]["mean_abs_daily_range_error"])
        else:
            summary_row["validation_mean_daily_level_mae"] = np.nan
            summary_row["validation_mean_daily_level_bias"] = np.nan
            summary_row["validation_mean_abs_daily_level_bias"] = np.nan
            summary_row["validation_mean_abs_daily_range_error"] = np.nan

        if not shape_part.empty:
            summary_row["validation_mean_pearson_corr"] = float(shape_part.iloc[0]["mean_pearson_corr"])
            summary_row["validation_mean_spearman_corr"] = float(shape_part.iloc[0]["mean_spearman_corr"])
            summary_row["validation_mean_demeaned_shape_mae"] = float(shape_part.iloc[0]["mean_demeaned_shape_mae"])
        else:
            summary_row["validation_mean_pearson_corr"] = np.nan
            summary_row["validation_mean_spearman_corr"] = np.nan
            summary_row["validation_mean_demeaned_shape_mae"] = np.nan

        if not topk_part.empty:
            summary_row["validation_top3_expensive_recall"] = float(topk_part.iloc[0]["mean_top3_expensive_recall"])
            summary_row["validation_top3_cheap_recall"] = float(topk_part.iloc[0]["mean_top3_cheap_recall"])
        else:
            summary_row["validation_top3_expensive_recall"] = np.nan
            summary_row["validation_top3_cheap_recall"] = np.nan

        if not tail_part.empty:
            summary_row["validation_top10_mae"] = float(tail_part.iloc[0]["top10_mae"])
            summary_row["validation_negative_mae"] = float(tail_part.iloc[0]["negative_mae"])
            summary_row["validation_high_volatility_day_mae"] = float(tail_part.iloc[0]["high_volatility_day_mae"])
            summary_row["validation_p95_ae"] = float(tail_part.iloc[0]["p95_ae"])
        else:
            summary_row["validation_top10_mae"] = np.nan
            summary_row["validation_negative_mae"] = np.nan
            summary_row["validation_high_volatility_day_mae"] = np.nan
            summary_row["validation_p95_ae"] = np.nan

        if not runtime_part.empty:
            summary_row["validation_fit_time_mean_sec"] = float(runtime_part.iloc[0]["fit_time_mean_sec"])
            summary_row["validation_predict_time_mean_sec"] = float(runtime_part.iloc[0]["predict_time_mean_sec"])
            summary_row["validation_fit_time_warning_count"] = int(runtime_part.iloc[0]["fit_time_warning_count"])
        else:
            summary_row["validation_fit_time_mean_sec"] = np.nan
            summary_row["validation_predict_time_mean_sec"] = np.nan
            summary_row["validation_fit_time_warning_count"] = np.nan

        rows.append(summary_row)
    return pd.DataFrame(rows).sort_values(["rmae", "mae", "candidate_label"]).reset_index(drop=True)


def implementation_note(candidate_label: str, candidate_context: str, model_family: str) -> str:
    label = str(candidate_label)
    if candidate_context == "benchmark":
        return "Minimal implementation cost and maximum transparency, but operational realism may be too weak."
    if "FS2" in label and model_family == "lear":
        return "Frozen linear structure. Easier to explain in the thesis than XGBoost, with moderate implementation complexity."
    if "FS2" in label and model_family == "xgboost":
        return "Operationally practical nonlinear model, but less interpretable than LEAR and harder to justify if gains are marginal."
    if "promoted" in label and model_family == "lear":
        return "Full FS3 causal stack on a linear base. More explainable than XGBoost FS3, but feature breadth still adds maintenance cost."
    if "promoted" in label and model_family == "xgboost":
        return "Highest complexity among current candidates because nonlinear interactions sit on top of the full FS3 exogenous stack."
    if "pruned candidate" in label and model_family == "lear":
        return "Reduced FS3 linear candidate. Keeps some FS3 benefit while trimming thesis explanation burden."
    if "pruned candidate" in label and model_family == "xgboost":
        return "Reduced FS3 tree candidate. Still less interpretable than LEAR, but lighter than the promoted XGBoost parent."
    return "Implementation note unavailable."


def recommend_candidate(
    selection_inputs: pd.DataFrame,
    *,
    thresholds: dict[str, float] | None = None,
) -> dict[str, object]:
    thresholds = thresholds or default_decision_thresholds()
    non_benchmark = selection_inputs[selection_inputs["candidate_context"].astype(str) != "benchmark"].copy()
    if non_benchmark.empty:
        return {
            "recommended_candidate_key": None,
            "recommended_candidate_label": None,
            "decision_reason": "No non-benchmark candidate was available.",
            "stop_da_here": False,
            "move_to_mfrr": False,
        }

    best_fs2 = non_benchmark[non_benchmark["display_group"].astype(str) == "fs2"].sort_values(["rmae", "mae"]).head(1)
    fs3_candidates = non_benchmark[non_benchmark["display_group"].astype(str) == "fs3"].sort_values(["rmae", "mae"]).copy()

    baseline_row = best_fs2.iloc[0] if not best_fs2.empty else None
    provisional_row = baseline_row
    decision_reason = "No FS3 candidate was available, so the best FS2 reference remains the thesis candidate."

    if not fs3_candidates.empty:
        best_fs3 = fs3_candidates.iloc[0]
        provisional_row = best_fs3
        decision_reason = "The best validation FS3 candidate is provisionally selected before the FS2 simplicity check."
        if baseline_row is not None:
            fs3_gain = float(baseline_row["rmae"] - best_fs3["rmae"])
            fs3_clear_improvement = fs3_gain >= float(thresholds["marginal_fs3_rmae_gain_vs_fs2"])
            baseline_level_bias = float(baseline_row["validation_mean_abs_daily_level_bias"]) if pd.notna(baseline_row["validation_mean_abs_daily_level_bias"]) else np.nan
            fs3_level_bias = float(best_fs3["validation_mean_abs_daily_level_bias"]) if pd.notna(best_fs3["validation_mean_abs_daily_level_bias"]) else np.nan
            fs3_level_ok = (
                pd.isna(fs3_level_bias)
                or fs3_level_bias <= float(thresholds["large_daily_level_bias_eur_per_mwh"])
                or (pd.notna(baseline_level_bias) and fs3_level_bias <= baseline_level_bias)
            )
            fs3_test_failure = (
                pd.notna(best_fs3["test_rmae"]) and float(best_fs3["test_rmae"]) > float(thresholds["clear_test_failure_rmae"])
            ) or (
                pd.notna(best_fs3["test_horizon_pass_share"]) and float(best_fs3["test_horizon_pass_share"]) < float(thresholds["clear_test_failure_horizon_pass_share"])
            )
            if (not fs3_clear_improvement or not fs3_level_ok or fs3_test_failure) and baseline_row is not None:
                provisional_row = baseline_row
                reason_parts = []
                if not fs3_clear_improvement:
                    reason_parts.append("FS3 improves validation rMAE only marginally versus FS2.")
                if not fs3_level_ok:
                    reason_parts.append("FS3 worsens daily level retention relative to the FS2 reference.")
                if fs3_test_failure:
                    reason_parts.append("The validation-selected FS3 candidate shows a clear robustness failure on test.")
                reason_parts.append("The simpler FS2 reference is therefore retained.")
                decision_reason = " ".join(reason_parts)
            else:
                decision_reason = (
                    f"{best_fs3['candidate_label']} improves validation rMAE enough over the best FS2 reference "
                    "without triggering the configured simplicity fallback."
                )

    if provisional_row is None:
        return {
            "recommended_candidate_key": None,
            "recommended_candidate_label": None,
            "decision_reason": "No candidate could be recommended.",
            "stop_da_here": False,
            "move_to_mfrr": False,
        }

    recommended_label = str(provisional_row["candidate_label"])
    validation_pass = pd.notna(provisional_row["rmae"]) and float(provisional_row["rmae"]) < float(thresholds["validation_rmae_minimum"])
    stop_da_here = bool(validation_pass)
    return {
        "recommended_candidate_key": str(provisional_row["candidate_key"]),
        "recommended_candidate_label": recommended_label,
        "decision_reason": decision_reason,
        "stop_da_here": stop_da_here,
        "move_to_mfrr": stop_da_here,
        "implementation_note": implementation_note(
            recommended_label,
            str(provisional_row["candidate_context"]),
            str(provisional_row["model_family"]),
        ),
    }


def build_model_selection_summary(
    selection_inputs: pd.DataFrame,
    recommendation: dict[str, object],
) -> pd.DataFrame:
    if selection_inputs.empty:
        return pd.DataFrame()
    frame = selection_inputs.copy()
    recommended_key = recommendation.get("recommended_candidate_key")
    frame["runtime_note"] = frame.apply(
        lambda row: (
            f"fit {float(row['validation_fit_time_mean_sec']):.2f}s, predict {float(row['validation_predict_time_mean_sec']):.2f}s"
            if pd.notna(row["validation_fit_time_mean_sec"]) and pd.notna(row["validation_predict_time_mean_sec"])
            else "Runtime summary unavailable"
        ),
        axis=1,
    )
    frame["implementability_note"] = frame.apply(
        lambda row: implementation_note(str(row["candidate_label"]), str(row["candidate_context"]), str(row["model_family"])),
        axis=1,
    )
    frame["classical_metrics_summary"] = frame.apply(
        lambda row: (
            f"val rMAE {float(row['rmae']):.3f}, val MAE {float(row['mae']):.2f}, "
            f"test rMAE {float(row['test_rmae']):.3f}" if pd.notna(row["test_rmae"]) else f"val rMAE {float(row['rmae']):.3f}, val MAE {float(row['mae']):.2f}"
        ),
        axis=1,
    )
    frame["horizon_robustness_summary"] = frame["validation_horizon_pass_share"].map(
        lambda value: "Unavailable" if pd.isna(value) else f"{float(value) * 100.0:.0f}% of validation horizons below rMAE 1.00"
    )
    frame["level_retention_summary"] = frame.apply(
        lambda row: (
            "Unavailable"
            if pd.isna(row["validation_mean_daily_level_mae"])
            else f"mean daily level MAE {float(row['validation_mean_daily_level_mae']):.2f}, mean daily bias {float(row['validation_mean_daily_level_bias']):+.2f}"
        ),
        axis=1,
    )
    frame["shape_retention_summary"] = frame.apply(
        lambda row: (
            "Unavailable"
            if pd.isna(row["validation_mean_pearson_corr"])
            else f"Pearson {float(row['validation_mean_pearson_corr']):.2f}, Spearman {float(row['validation_mean_spearman_corr']):.2f}, de-meaned shape MAE {float(row['validation_mean_demeaned_shape_mae']):.2f}"
        ),
        axis=1,
    )
    frame["expensive_hour_recall_summary"] = frame["validation_top3_expensive_recall"].map(
        lambda value: "Unavailable" if pd.isna(value) else f"Top-3 expensive recall {float(value):.2f}"
    )
    frame["cheap_hour_recall_summary"] = frame["validation_top3_cheap_recall"].map(
        lambda value: "Unavailable" if pd.isna(value) else f"Top-3 cheap recall {float(value):.2f}"
    )
    frame["tail_stress_note"] = frame.apply(
        lambda row: (
            "Unavailable"
            if pd.isna(row["validation_top10_mae"])
            else f"Top-10% MAE {float(row['validation_top10_mae']):.2f}, high-volatility-day MAE {float(row['validation_high_volatility_day_mae']):.2f}, p95 AE {float(row['validation_p95_ae']):.2f}"
        ),
        axis=1,
    )
    frame["recommended_yes_no"] = frame["candidate_key"].astype(str) == str(recommended_key)
    frame["thesis_use_limitations"] = frame.apply(
        lambda row: (
            "Baseline only; use only if stronger models fail realism or robustness."
            if str(row["candidate_context"]) == "benchmark"
            else "Document deterministic-only limitations and residual tail risk."
        ),
        axis=1,
    )
    frame["notes"] = np.where(
        frame["recommended_yes_no"],
        str(recommendation.get("decision_reason", "")),
        "",
    )
    columns = [
        "candidate_context",
        "candidate_label",
        "classical_metrics_summary",
        "horizon_robustness_summary",
        "level_retention_summary",
        "shape_retention_summary",
        "expensive_hour_recall_summary",
        "cheap_hour_recall_summary",
        "tail_stress_note",
        "runtime_note",
        "implementability_note",
        "recommended_yes_no",
        "thesis_use_limitations",
        "notes",
    ]
    return frame[columns].sort_values(["recommended_yes_no", "candidate_label"], ascending=[False, True]).reset_index(drop=True)


def run_metric_smoke_checks(config: HourlyDAPipelineConfig) -> pd.DataFrame:
    timezone = config.resolved_business_timezone()
    local_ranges = [
        pd.date_range("2025-03-30 00:00", periods=23, freq="h", tz=timezone),
        pd.date_range("2025-10-26 00:00", periods=25, freq="h", tz=timezone),
        pd.date_range("2025-01-15 00:00", periods=24, freq="h", tz=timezone),
    ]
    timestamps_local = local_ranges[0].append(local_ranges[1]).append(local_ranges[2])
    timestamps_utc = timestamps_local.tz_convert("UTC")

    actual = np.linspace(10.0, 40.0, len(timestamps_utc))
    actual[-24:] = 25.0
    benchmark_pred = actual.copy()
    candidate_pred = actual + np.sin(np.arange(len(actual))) * 2.0
    origin_map = [timestamp.floor("D") - pd.Timedelta(hours=16) for timestamp in timestamps_utc]

    rows = []
    for candidate_key, candidate_label, y_pred in [
        ("official_naive_benchmark", "Naive previous week", benchmark_pred),
        ("candidate", "Synthetic candidate", candidate_pred),
    ]:
        for timestamp_utc, forecast_origin_utc, y_true, prediction in zip(timestamps_utc, origin_map, actual, y_pred, strict=True):
            rows.append(
                {
                    "candidate_key": candidate_key,
                    "candidate_label": candidate_label,
                    "candidate_context": "benchmark" if candidate_key == "official_naive_benchmark" else "fs2_reference",
                    "variant": "smoke",
                    "display_group": "benchmark" if candidate_key == "official_naive_benchmark" else "fs2",
                    "internal_model": candidate_key,
                    "model_family": "naive" if candidate_key == "official_naive_benchmark" else "lear",
                    "fs_level": "FS0" if candidate_key == "official_naive_benchmark" else "FS2",
                    "source_run_id": "synthetic",
                    "source_run_label": "synthetic",
                    "dataset_split": "test",
                    "forecast_origin_utc": forecast_origin_utc,
                    "target_timestamp_utc": timestamp_utc,
                    "lead_day": 0,
                    "lead_day_label": "D",
                    "y_true": float(y_true),
                    "y_pred": float(prediction),
                }
            )
    predictions = normalize_prediction_schema(pd.DataFrame(rows), config=config)
    stitched = build_stitched_d_only_predictions(predictions, split_name="test")
    _, topk_summary = compute_topk_hour_metrics(predictions, ks=(3,))
    _, shape_summary = compute_daily_shape_metrics(predictions)

    checks = [
        {
            "check": "candidate_labels_unique",
            "passed": predictions["candidate_label"].astype(str).nunique() == 2,
            "details": "Two synthetic candidates are present and labels remain distinguishable after loading.",
        },
        {
            "check": "day_length_23_present",
            "passed": 23 in summarize_local_day_lengths(predictions)["hours_in_local_day"].tolist(),
            "details": "Spring DST day is preserved.",
        },
        {
            "check": "day_length_25_present",
            "passed": 25 in summarize_local_day_lengths(predictions)["hours_in_local_day"].tolist(),
            "details": "Autumn DST day is preserved.",
        },
        {
            "check": "topk_handles_short_days",
            "passed": not topk_summary.empty,
            "details": "Top-k summary returns a table for 23/24/25-hour local days.",
        },
        {
            "check": "flat_day_correlation_nan",
            "passed": bool(shape_summary["flat_actual_days"].max() >= 1),
            "details": "At least one flat actual day is counted instead of being silently forced to zero correlation.",
        },
        {
            "check": "stitched_targets_unique",
            "passed": int(summarize_stitched_overlap_check(stitched)["overlap_rows"].sum()) == 0,
            "details": "Stitched D-only forecasts contain no overlapping target duplicates.",
        },
    ]
    return pd.DataFrame(checks)
