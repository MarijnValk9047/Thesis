from __future__ import annotations

from datetime import datetime, UTC
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import load_candidate_predictions
from hourly_da.core.scenario_generation import (
    BIAS_CORRECTION_LEVEL_PROFILES,
    apply_bias_correction,
    build_bias_correction_maps_from_frame,
    build_residual_period_table,
    choose_official_naive_candidate,
    choose_target_evaluation_slice,
    compute_candidate_selection_summary,
    discover_scenario_candidate_sources,
    select_scenario_candidates,
)


TUNING_CALIBRATION_START = pd.Timestamp("2023-10-01")
TUNING_CALIBRATION_END = pd.Timestamp("2024-03-31")
TUNING_SELECTION_START = pd.Timestamp("2024-04-01")
TUNING_SELECTION_END = pd.Timestamp("2024-09-30")

WINDOW_DAYS_OPTIONS: tuple[int | None, ...] = (None, 180, 90)
STATISTIC_OPTIONS: tuple[str, ...] = ("mean", "median")
LEVEL_PROFILE_OPTIONS: tuple[str, ...] = (
    "sdth_sh_dh_h_global",
    "sdth_h_global",
    "sh_dh_h_global",
    "dh_h_global",
    "hour_global",
    "global_only",
)
MIN_OBSERVATION_OPTIONS: tuple[int, ...] = (20, 50, 100)
SHRINKAGE_OPTIONS: tuple[float, ...] = (0.25, 0.50, 0.75, 1.00)
CAP_OPTIONS: tuple[float | None, ...] = (None, 20.0, 10.0, 5.0)


def _output_dir(output_root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = Path(output_root) / "option_c_sweeps" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _filter_delivery_range(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    delivery_day = pd.to_datetime(frame["delivery_day"], errors="coerce")
    return frame[(delivery_day >= start) & (delivery_day <= end)].copy()


def _tail_window(frame: pd.DataFrame, window_days: int | None) -> pd.DataFrame:
    if frame.empty or window_days is None:
        return frame.copy()
    delivery_day = pd.to_datetime(frame["delivery_day"], errors="coerce")
    cutoff = delivery_day.max() - pd.Timedelta(days=int(window_days) - 1)
    return frame[delivery_day >= cutoff].copy()


def _error_metrics(frame: pd.DataFrame, *, forecast_col: str) -> dict[str, float]:
    valid = frame[frame["y_true"].notna() & frame[forecast_col].notna()].copy()
    if valid.empty:
        return {
            "bias": np.nan,
            "mae": np.nan,
            "rmse": np.nan,
            "coverage_pct": 0.0,
            "observations_scored": 0,
            "observations_total": int(frame.shape[0]),
        }
    error = valid[forecast_col].astype(float) - valid["y_true"].astype(float)
    return {
        "bias": float(error.mean()),
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "coverage_pct": float(valid.shape[0] / frame.shape[0] * 100.0),
        "observations_scored": int(valid.shape[0]),
        "observations_total": int(frame.shape[0]),
    }


def _setting_id(
    *,
    statistic: str,
    level_profile_name: str,
    min_observations: int,
    shrinkage: float,
    cap_abs: float | None,
    window_days: int | None,
) -> str:
    cap_label = "none" if cap_abs is None else f"{int(cap_abs)}"
    window_label = "full" if window_days is None else f"{int(window_days)}d"
    shrinkage_label = str(shrinkage).replace(".", "p")
    return f"{statistic}__{level_profile_name}__min{min_observations}__shr{shrinkage_label}__cap{cap_label}__{window_label}"


def _evaluate_setting(
    candidate_frame: pd.DataFrame,
    calibration_frame: pd.DataFrame,
    *,
    candidate_key: str,
    candidate_label: str,
    statistic: str,
    level_profile_name: str,
    min_observations: int,
    shrinkage: float,
    cap_abs: float | None,
    window_days: int | None,
) -> dict[str, Any]:
    calibration_slice = _tail_window(calibration_frame, window_days)
    maps = build_bias_correction_maps_from_frame(calibration_slice, statistic=statistic)
    corrected = apply_bias_correction(
        candidate_frame,
        maps,
        min_observations=int(min_observations),
        level_priority=BIAS_CORRECTION_LEVEL_PROFILES[level_profile_name],
        shrinkage=float(shrinkage),
        cap_abs=cap_abs,
        setting_id=_setting_id(
            statistic=statistic,
            level_profile_name=level_profile_name,
            min_observations=min_observations,
            shrinkage=shrinkage,
            cap_abs=cap_abs,
            window_days=window_days,
        ),
        statistic_label=statistic,
    )
    raw = _error_metrics(corrected, forecast_col="y_pred")
    corrected_metrics = _error_metrics(corrected, forecast_col="bias_corrected_forecast")
    return {
        "candidate_key": candidate_key,
        "candidate_label": candidate_label,
        "setting_id": corrected["bias_correction_setting_id"].iloc[0],
        "statistic": statistic,
        "level_profile_name": level_profile_name,
        "level_priority": "|".join(BIAS_CORRECTION_LEVEL_PROFILES[level_profile_name]),
        "min_observations": int(min_observations),
        "shrinkage": float(shrinkage),
        "cap_abs": np.nan if cap_abs is None else float(cap_abs),
        "window_days": np.nan if window_days is None else int(window_days),
        "calibration_days_used": int(pd.Series(calibration_slice["delivery_day"]).nunique()),
        "raw_bias": raw["bias"],
        "corrected_bias": corrected_metrics["bias"],
        "raw_mae": raw["mae"],
        "corrected_mae": corrected_metrics["mae"],
        "raw_rmse": raw["rmse"],
        "corrected_rmse": corrected_metrics["rmse"],
        "mae_improvement": float(raw["mae"] - corrected_metrics["mae"]),
        "rmse_improvement": float(raw["rmse"] - corrected_metrics["rmse"]),
        "abs_bias_improvement": float(abs(raw["bias"]) - abs(corrected_metrics["bias"])),
        "coverage_pct": corrected_metrics["coverage_pct"],
        "observations_scored": corrected_metrics["observations_scored"],
        "observations_total": corrected_metrics["observations_total"],
    }


def _baseline_row(candidate_frame: pd.DataFrame, *, candidate_key: str, candidate_label: str) -> dict[str, Any]:
    raw = _error_metrics(candidate_frame, forecast_col="y_pred")
    return {
        "candidate_key": candidate_key,
        "candidate_label": candidate_label,
        "setting_id": "none",
        "statistic": "none",
        "level_profile_name": "none",
        "level_priority": "none",
        "min_observations": 0,
        "shrinkage": 0.0,
        "cap_abs": np.nan,
        "window_days": np.nan,
        "calibration_days_used": 0,
        "raw_bias": raw["bias"],
        "corrected_bias": raw["bias"],
        "raw_mae": raw["mae"],
        "corrected_mae": raw["mae"],
        "raw_rmse": raw["rmse"],
        "corrected_rmse": raw["rmse"],
        "mae_improvement": 0.0,
        "rmse_improvement": 0.0,
        "abs_bias_improvement": 0.0,
        "coverage_pct": raw["coverage_pct"],
        "observations_scored": raw["observations_scored"],
        "observations_total": raw["observations_total"],
    }


def _sort_selection_results(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["abs_corrected_bias"] = work["corrected_bias"].abs()
    work["cap_abs_sort"] = work["cap_abs"].fillna(9999.0)
    work["window_days_sort"] = work["window_days"].fillna(9999.0)
    return work.sort_values(
        [
            "corrected_mae",
            "corrected_rmse",
            "abs_corrected_bias",
            "shrinkage",
            "cap_abs_sort",
            "window_days_sort",
            "level_profile_name",
            "statistic",
        ],
        ascending=[True, True, True, True, True, True, True, True],
    ).reset_index(drop=True)


def _refit_and_evaluate(
    candidate_frame: pd.DataFrame,
    validation_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    setting: pd.Series,
) -> pd.DataFrame:
    if str(setting["setting_id"]) == "none":
        evaluation = pd.concat([validation_frame, test_frame], ignore_index=True).copy()
        evaluation["bias_correction"] = 0.0
        evaluation["bias_correction_level"] = "none"
        evaluation["bias_correction_observations"] = 0
        evaluation["bias_correction_setting_id"] = "none"
        evaluation["bias_correction_statistic"] = "none"
        evaluation["bias_correction_shrinkage"] = 0.0
        evaluation["bias_correction_cap_abs"] = np.nan
        evaluation["bias_correction_level_profile"] = "none"
        evaluation["bias_corrected_forecast"] = evaluation["y_pred"].astype(float)
        evaluation["bias_corrected_residual"] = evaluation["y_true"].astype(float) - evaluation["bias_corrected_forecast"].astype(float)
        corrected = evaluation
    else:
        refit_calibration = _tail_window(validation_frame, None if pd.isna(setting["window_days"]) else int(setting["window_days"]))
        maps = build_bias_correction_maps_from_frame(refit_calibration, statistic=str(setting["statistic"]))
        corrected = apply_bias_correction(
            pd.concat([validation_frame, test_frame], ignore_index=True),
            maps,
            min_observations=int(setting["min_observations"]),
            level_priority=BIAS_CORRECTION_LEVEL_PROFILES[str(setting["level_profile_name"])],
            shrinkage=float(setting["shrinkage"]),
            cap_abs=None if pd.isna(setting["cap_abs"]) else float(setting["cap_abs"]),
            setting_id=str(setting["setting_id"]),
            statistic_label=str(setting["statistic"]),
        )

    rows: list[dict[str, Any]] = []
    for dataset_split, split_frame in corrected.groupby("dataset_split", dropna=False):
        raw = _error_metrics(split_frame, forecast_col="y_pred")
        corrected_metrics = _error_metrics(split_frame, forecast_col="bias_corrected_forecast")
        rows.append(
            {
                "candidate_key": str(setting["candidate_key"]),
                "candidate_label": str(setting["candidate_label"]),
                "setting_id": str(setting["setting_id"]),
                "dataset_split": str(dataset_split),
                "raw_bias": raw["bias"],
                "corrected_bias": corrected_metrics["bias"],
                "raw_mae": raw["mae"],
                "corrected_mae": corrected_metrics["mae"],
                "raw_rmse": raw["rmse"],
                "corrected_rmse": corrected_metrics["rmse"],
                "mae_improvement": float(raw["mae"] - corrected_metrics["mae"]),
                "rmse_improvement": float(raw["rmse"] - corrected_metrics["rmse"]),
                "abs_bias_improvement": float(abs(raw["bias"]) - abs(corrected_metrics["bias"])),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    config = HourlyDAPipelineConfig(
        input_csv=REPO_ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv",
        raw_root=REPO_ROOT / "data/00_Raw/DA_Prices",
        cleaned_feature_root=REPO_ROOT / "data/01_cleaned",
        output_root=REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da",
    )
    out_dir = _output_dir(config.output_root)

    discovery = discover_scenario_candidate_sources(config.output_root)
    candidate_frame = discovery["candidate_frame"].copy()
    candidate_predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=config)

    official_naive_info = choose_official_naive_candidate(candidate_predictions)
    evaluation_choice = choose_target_evaluation_slice(candidate_predictions, preferred_splits=("test", "validation"), preferred_lead_day=0)
    candidate_selection_summary = compute_candidate_selection_summary(
        candidate_predictions,
        selection_split=str(evaluation_choice["dataset_split"]),
        selection_lead_day=int(evaluation_choice["lead_day"]),
        official_naive_candidate_key=str(official_naive_info["selected"]["candidate_key"]),
        k_top_hours=3,
    )
    selection_bundle = select_scenario_candidates(candidate_selection_summary)
    selected_candidate_keys = [str(value) for value in selection_bundle["selected_candidate_keys"]]

    residual_periods = build_residual_period_table(candidate_predictions, config=config, lead_day=0)
    residual_periods = residual_periods[
        residual_periods["candidate_key"].astype(str).isin(selected_candidate_keys)
    ].copy()

    validation_frame = residual_periods[residual_periods["dataset_split"].astype(str) == "validation"].copy()
    test_frame = residual_periods[residual_periods["dataset_split"].astype(str) == "test"].copy()
    tuning_calibration = _filter_delivery_range(validation_frame, TUNING_CALIBRATION_START, TUNING_CALIBRATION_END)
    tuning_selection = _filter_delivery_range(validation_frame, TUNING_SELECTION_START, TUNING_SELECTION_END)

    selection_rows: list[dict[str, Any]] = []
    chosen_rows: list[dict[str, Any]] = []
    test_rows: list[pd.DataFrame] = []
    notebook_setting_rows: list[dict[str, Any]] = []

    for candidate_key in selected_candidate_keys:
        candidate_label = str(
            residual_periods.loc[residual_periods["candidate_key"].astype(str) == candidate_key, "candidate_label"].iloc[0]
        )
        candidate_calibration = tuning_calibration[tuning_calibration["candidate_key"].astype(str) == candidate_key].copy()
        candidate_selection = tuning_selection[tuning_selection["candidate_key"].astype(str) == candidate_key].copy()
        candidate_validation = validation_frame[validation_frame["candidate_key"].astype(str) == candidate_key].copy()
        candidate_test = test_frame[test_frame["candidate_key"].astype(str) == candidate_key].copy()

        selection_rows.append(_baseline_row(candidate_selection, candidate_key=candidate_key, candidate_label=candidate_label))

        for window_days in WINDOW_DAYS_OPTIONS:
            calibration_window = _tail_window(candidate_calibration, window_days)
            if calibration_window.empty:
                continue
            for statistic in STATISTIC_OPTIONS:
                for level_profile_name in LEVEL_PROFILE_OPTIONS:
                    for min_observations in MIN_OBSERVATION_OPTIONS:
                        for shrinkage in SHRINKAGE_OPTIONS:
                            for cap_abs in CAP_OPTIONS:
                                selection_rows.append(
                                    _evaluate_setting(
                                        candidate_selection,
                                        calibration_window,
                                        candidate_key=candidate_key,
                                        candidate_label=candidate_label,
                                        statistic=statistic,
                                        level_profile_name=level_profile_name,
                                        min_observations=min_observations,
                                        shrinkage=shrinkage,
                                        cap_abs=cap_abs,
                                        window_days=window_days,
                                    )
                                )

        candidate_results = pd.DataFrame([row for row in selection_rows if row["candidate_key"] == candidate_key]).reset_index(drop=True)
        overall_best = _sort_selection_results(candidate_results).iloc[0]
        non_none = candidate_results[candidate_results["setting_id"].astype(str) != "none"].copy()
        best_non_none = _sort_selection_results(non_none).iloc[0]

        chosen_rows.append(
            {
                "candidate_key": candidate_key,
                "candidate_label": candidate_label,
                "overall_best_setting_id": str(overall_best["setting_id"]),
                "overall_best_is_none": bool(str(overall_best["setting_id"]) == "none"),
                "validation_selected_setting_id": str(best_non_none["setting_id"]),
                "validation_selected_statistic": str(best_non_none["statistic"]),
                "validation_selected_level_profile_name": str(best_non_none["level_profile_name"]),
                "validation_selected_min_observations": int(best_non_none["min_observations"]),
                "validation_selected_shrinkage": float(best_non_none["shrinkage"]),
                "validation_selected_cap_abs": np.nan if pd.isna(best_non_none["cap_abs"]) else float(best_non_none["cap_abs"]),
                "validation_selected_window_days": np.nan if pd.isna(best_non_none["window_days"]) else int(best_non_none["window_days"]),
                "validation_selected_corrected_mae": float(best_non_none["corrected_mae"]),
                "validation_selected_corrected_rmse": float(best_non_none["corrected_rmse"]),
                "validation_selected_corrected_bias": float(best_non_none["corrected_bias"]),
            }
        )

        test_evaluation = _refit_and_evaluate(candidate_selection, candidate_validation, candidate_test, best_non_none)
        test_rows.append(test_evaluation)
        test_only = test_evaluation[test_evaluation["dataset_split"].astype(str) == "test"].iloc[0]
        accepted = bool(
            float(test_only["corrected_mae"]) < float(test_only["raw_mae"])
            and float(test_only["corrected_rmse"]) <= float(test_only["raw_rmse"])
        )
        notebook_row = best_non_none.to_dict()
        notebook_row["test_decision"] = "accepted" if accepted else "refused"
        notebook_row["apply_in_notebook"] = accepted
        if not accepted:
            notebook_row.update(
                {
                    "setting_id": "none",
                    "statistic": "none",
                    "level_profile_name": "none",
                    "level_priority": "none",
                    "min_observations": 0,
                    "shrinkage": 0.0,
                    "cap_abs": np.nan,
                    "window_days": np.nan,
                }
            )
        notebook_setting_rows.append(notebook_row)

    selection_results = pd.DataFrame(selection_rows).sort_values(
        ["candidate_label", "corrected_mae", "corrected_rmse", "setting_id"]
    ).reset_index(drop=True)
    chosen_settings = pd.DataFrame(chosen_rows).sort_values("candidate_label").reset_index(drop=True)
    test_evaluations = pd.concat(test_rows, ignore_index=True).sort_values(["candidate_label", "dataset_split"]).reset_index(drop=True)
    notebook_settings = pd.DataFrame(notebook_setting_rows).sort_values("candidate_label").reset_index(drop=True)

    recommendation_payload = {
        "timestamp": pd.Timestamp.utcnow().isoformat(),
        "tuning_calibration_window": {
            "start": str(TUNING_CALIBRATION_START.date()),
            "end": str(TUNING_CALIBRATION_END.date()),
        },
        "tuning_selection_window": {
            "start": str(TUNING_SELECTION_START.date()),
            "end": str(TUNING_SELECTION_END.date()),
        },
        "selection_rule": {
            "validation_primary": "lowest corrected_mae",
            "validation_tiebreakers": ["lowest corrected_rmse", "lowest absolute corrected_bias"],
            "test_acceptance_rule": "accept only if test corrected_mae improves and test corrected_rmse does not worsen",
        },
        "selected_candidates": selected_candidate_keys,
        "notebook_applied_settings": notebook_settings[
            [
                "candidate_key",
                "candidate_label",
                "setting_id",
                "statistic",
                "level_profile_name",
                "min_observations",
                "shrinkage",
                "cap_abs",
                "window_days",
                "test_decision",
                "apply_in_notebook",
            ]
        ].to_dict(orient="records"),
    }

    selection_results.to_csv(out_dir / "option_c_validation_sweep_results.csv", index=False)
    chosen_settings.to_csv(out_dir / "option_c_validation_selected_settings.csv", index=False)
    test_evaluations.to_csv(out_dir / "option_c_test_evaluation.csv", index=False)
    notebook_settings.to_csv(out_dir / "option_c_notebook_applied_settings.csv", index=False)
    (out_dir / "option_c_sweep_recommendation.json").write_text(
        json.dumps(recommendation_payload, indent=2, default=str),
        encoding="utf-8",
    )

    print(out_dir)


if __name__ == "__main__":
    main()
