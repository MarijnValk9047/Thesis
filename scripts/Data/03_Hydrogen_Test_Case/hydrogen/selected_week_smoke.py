from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .common_support import ARTIFACT_LABELS
from .optimisation.output_policy import get_output_policy
from .optimisation.progress_reporting import ProgressReporter
from .optimisation.runtime_profiling import RuntimeProfiler
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .run_registry import save_frame_csv, save_frame_parquet, save_json, save_text
from .selected_week_policy import (
    COMMON_SUPPORT_DAYS_PATH,
    COMMON_SUPPORT_REGISTRY_PATH,
    OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH,
    OFFICIAL_TEST_SELECTED_WEEKS_PATH,
    expected_methodological_use,
    resolve_registry_rows,
    run_selected_week_input_preflight,
)
from .selected_week_suite import SelectedWeekSuiteResult, run_real_scenario_selected_week_suite

try:
    from visual_style import MODEL_COLORS, apply_visual_style
except Exception:  # noqa: BLE001
    MODEL_COLORS = {
        "LEAR Strict": "#C97941",
        "LEAR FS3 pruned candidate": "#3A7D7C",
        "XGBoost FS3 pruned candidate": "#1F4E79",
        "Price insensitive benchmark": "#333333",
    }

    def apply_visual_style() -> None:
        plt.rcParams.update(
            {
                "figure.figsize": (8, 4.5),
                "figure.dpi": 120,
                "savefig.dpi": 300,
                "axes.grid": True,
                "grid.alpha": 0.5,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "legend.frameon": False,
            }
        )


DEFAULT_WEEK_REGISTRY = COMMON_SUPPORT_REGISTRY_PATH
DEFAULT_SUPPORT_CSV = COMMON_SUPPORT_DAYS_PATH
DEFAULT_SELECTED_WEEKS_YAML = OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH
DEFAULT_ARTIFACT_IDS = (
    "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support",
    "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
    "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate",
)

TOLERANCE = 1e-6
DEFAULT_PREFLIGHT_CACHE_DIRNAME = "_selected_week_preflight_cache"
PHASE_C_BENCHMARK_SCOPE = "per_model"
PHASE_C_EXPECTED_GAMMAS = (0.0,)


@dataclass(frozen=True)
class PhaseCSmokeRunResult:
    run_dir: Path
    selected_week: pd.Series
    support_days: pd.DataFrame
    suite_result: SelectedWeekSuiteResult
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    benchmark_metrics: pd.DataFrame
    validation_checks: pd.DataFrame
    actual_settlement_results: pd.DataFrame
    scenario_settlement_results: pd.DataFrame


def _validation_row(
    *,
    check_name: str,
    status: str,
    details: str,
    severity: str = "hard_fail",
    artifact_id: str = "",
    model_label: str = "",
    week_id: str = "",
    week_label: str = "",
    delivery_day: str = "",
    forecast_origin_utc: str = "",
) -> dict[str, str]:
    return {
        "check_name": str(check_name),
        "status": str(status),
        "severity": str(severity),
        "details": str(details),
        "artifact_id": str(artifact_id),
        "model_label": str(model_label),
        "week_id": str(week_id),
        "week_label": str(week_label),
        "delivery_day": str(delivery_day),
        "forecast_origin_utc": str(forecast_origin_utc),
    }


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    if values.size == 0:
        return float("nan")
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = float(quantile) * float(sorted_weights.sum())
    index = min(int(np.searchsorted(cumulative, cutoff, side="left")), len(sorted_values) - 1)
    return float(sorted_values[index])


def _label_for_artifact(artifact_id: str) -> str:
    mapping = {
        "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support": "LEAR Strict",
        "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate": "LEAR FS3 pruned candidate",
        "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate": "XGBoost FS3 pruned candidate",
    }
    return mapping.get(str(artifact_id), ARTIFACT_LABELS.get(str(artifact_id), str(artifact_id)))


def _normalize_selected_week_split(selected_week_split: str) -> str:
    normalized = str(selected_week_split).strip().lower()
    if normalized not in {"validation", "test"}:
        raise ValueError(f"Unsupported selected-week split for Phase C smoke: {selected_week_split!r}")
    return normalized


def _support_label_for_split(selected_week_split: str) -> str:
    normalized = _normalize_selected_week_split(selected_week_split)
    if normalized == "validation":
        return "hourly selected-week development smoke on exact common validation support"
    return "hourly selected-week comparison on common partial test support"


def _resolve_output_policy_name(output_mode: str) -> str:
    normalized = str(output_mode).strip().lower()
    if normalized in {"speed", "minimal"}:
        return "minimal"
    if normalized == "audit":
        return "audit"
    if normalized == "full":
        return "full"
    raise ValueError(f"Unsupported Phase C output_mode: {output_mode!r}")


def load_and_validate_phase_c_week(
    *,
    week_registry_path: Path,
    support_csv_path: Path,
    selected_weeks_yaml_path: Path | None,
    week_id: str,
    selected_week_split: str,
) -> tuple[pd.Series, pd.DataFrame]:
    normalized_split = _normalize_selected_week_split(selected_week_split)
    if selected_weeks_yaml_path is None:
        default_path = (
            OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH
            if normalized_split == "validation"
            else OFFICIAL_TEST_SELECTED_WEEKS_PATH
        )
        raise ValueError(f"Phase C requires the official selected {normalized_split}-week config: {default_path}")
    row = resolve_registry_rows(
        registry_path=week_registry_path,
        selected_weeks_yaml_path=selected_weeks_yaml_path,
        requested_identifiers=[str(week_id)],
        expected_split=normalized_split,
    ).iloc[0].copy()
    expected_week_label = str(row["week_label"])
    expected_start_date = str(row["delivery_start_date"])
    expected_end_date = str(row["delivery_end_date"])
    expected_use = expected_methodological_use(normalized_split)

    checks = {
        "regime_label": (bool(str(row["regime_label"])), f"expected non-empty regime_label, got {row['regime_label']}"),
        "delivery_start_date": (
            str(row["delivery_start_date"]) == str(expected_start_date),
            f"expected {expected_start_date}, got {row['delivery_start_date']}",
        ),
        "delivery_end_date": (
            str(row["delivery_end_date"]) == str(expected_end_date),
            f"expected {expected_end_date}, got {row['delivery_end_date']}",
        ),
        "period_type": (str(row["period_type"]) == normalized_split, f"expected {normalized_split}, got {row['period_type']}"),
        "number_of_delivery_days": (
            int(row["number_of_delivery_days"]) == 7,
            f"expected 7, got {row['number_of_delivery_days']}",
        ),
        "complete_for_lear_strict": (bool(row["complete_for_lear_strict"]), "LEAR Strict week row is not complete."),
        "complete_for_lear_fs3": (bool(row["complete_for_lear_fs3"]), "LEAR FS3 week row is not complete."),
        "complete_for_xgboost_fs3": (bool(row["complete_for_xgboost_fs3"]), "XGBoost FS3 week row is not complete."),
        "complete_actual_prices": (bool(row["complete_actual_prices"]), "Actual prices are not complete."),
        "support_status": (
            str(row["support_status"]) == "common_complete_support_selected",
            f"expected common_complete_support_selected, got {row['support_status']}",
        ),
        "methodological_use": (
            str(row["methodological_use"]) == expected_use,
            f"expected {expected_use}, got {row['methodological_use']}",
        ),
    }
    failures = [f"{name}: {message}" for name, (ok, message) in checks.items() if not ok]
    if failures:
        raise ValueError("Phase C selected-week validation failed: " + "; ".join(failures))

    if not support_csv_path.exists():
        raise FileNotFoundError(f"Common-support day table not found: {support_csv_path}")
    support_days = pd.read_csv(support_csv_path)
    support_days["delivery_date"] = pd.to_datetime(support_days["delivery_date"], errors="raise")
    week_days = support_days.loc[
        (support_days["delivery_date"] >= pd.Timestamp(expected_start_date))
        & (support_days["delivery_date"] <= pd.Timestamp(expected_end_date))
    ].copy()
    if int(week_days.shape[0]) != 7:
        raise ValueError(
            f"Expected 7 common-support day rows for {expected_week_label}, found {int(week_days.shape[0])}."
        )
    expected_dates = pd.date_range(expected_start_date, expected_end_date, freq="D")
    actual_dates = pd.DatetimeIndex(week_days["delivery_date"]).sort_values()
    if not actual_dates.equals(expected_dates):
        raise ValueError(
            f"Selected week support rows are not exactly the requested 7 consecutive dates: {actual_dates.strftime('%Y-%m-%d').tolist()}"
        )
    required_complete = (
        week_days["period_type"].astype(str).eq(normalized_split)
        & week_days["complete_actual_prices"].astype(bool)
        & week_days["complete_for_lear_strict"].astype(bool)
        & week_days["complete_for_lear_fs3"].astype(bool)
        & week_days["complete_for_xgboost_fs3"].astype(bool)
        & week_days["common_complete_support"].astype(bool)
        & week_days["n_hours_actual"].astype(int).eq(24)
        & week_days["n_hours_lear_strict"].astype(int).eq(24)
        & week_days["n_hours_lear_fs3"].astype(int).eq(24)
        & week_days["n_hours_xgboost_fs3"].astype(int).eq(24)
        & week_days["n_scenarios_per_origin_lear_strict"].astype(int).eq(75)
        & week_days["n_scenarios_per_origin_lear_fs3"].astype(int).eq(75)
        & week_days["n_scenarios_per_origin_xgboost_fs3"].astype(int).eq(75)
    )
    if not bool(required_complete.all()):
        failing_days = week_days.loc[~required_complete, "delivery_date"].dt.strftime("%Y-%m-%d").tolist()
        raise ValueError(
            f"Selected week contains days that are not exact common complete support: {failing_days}"
        )
    return row, week_days.reset_index(drop=True)


def _read_day_run_outputs(day_run_dirs: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], list[dict[str, Any]]]:
    datasets: dict[str, list[pd.DataFrame]] = {
        "submitted_bids": [],
        "scenario_clearing": [],
        "actual_clearing": [],
        "actual_clearing_by_hour": [],
        "actual_redispatch_timeseries": [],
        "scenario_settlement_results": [],
        "actual_settlement_results": [],
        "benchmark_comparison": [],
    }
    input_manifests: list[dict[str, Any]] = []
    scenario_manifests: list[dict[str, Any]] = []

    for row in day_run_dirs.to_dict(orient="records"):
        run_dir = Path(str(row["run_dir"]))
        if not run_dir.exists():
            raise FileNotFoundError(f"Nested day-run folder does not exist: {run_dir}")

        metadata = {
            "artifact_id": str(row["artifact_id"]),
            "model_label": str(row["model_label"]),
            "week_id": str(row["week_id"]),
            "week_label": str(row["week_label"]),
            "delivery_day": str(row["delivery_day"]),
            "forecast_origin_utc": str(row["forecast_origin_utc"]),
            "day_run_dir": str(run_dir),
        }

        file_map = {
            "submitted_bids": ("submitted_bids.parquet", "parquet"),
            "scenario_clearing": ("scenario_clearing.parquet", "parquet"),
            "actual_clearing": ("actual_clearing.parquet", "parquet"),
            "actual_clearing_by_hour": ("actual_clearing_by_hour.parquet", "parquet"),
            "actual_redispatch_timeseries": ("actual_redispatch_timeseries.parquet", "parquet"),
            "scenario_settlement_results": ("scenario_settlement_results.csv", "csv"),
            "actual_settlement_results": ("actual_settlement_results.csv", "csv"),
            "benchmark_comparison": ("benchmark_comparison.csv", "csv"),
        }
        for key, (name, kind) in file_map.items():
            path = run_dir / name
            if key == "benchmark_comparison" and not path.exists():
                continue
            if not path.exists():
                raise FileNotFoundError(f"Expected day-run artifact missing: {path}")
            frame = pd.read_parquet(path) if kind == "parquet" else pd.read_csv(path)
            datasets[key].append(frame.assign(**metadata))

        input_manifest_path = run_dir / "input_manifest.json"
        scenario_manifest_path = run_dir / "scenario_manifest.json"
        input_manifests.append(json.loads(input_manifest_path.read_text(encoding="utf-8")))
        scenario_manifests.append(json.loads(scenario_manifest_path.read_text(encoding="utf-8")))

    aggregated = {
        name: (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
        for name, frames in datasets.items()
    }
    return aggregated, input_manifests, scenario_manifests


def _scenario_coverage_by_day(scenario_fan_inputs: pd.DataFrame) -> pd.DataFrame:
    if scenario_fan_inputs.empty:
        return pd.DataFrame(
            columns=[
                "artifact_id",
                "model_label",
                "delivery_day",
                "actual_price_within_scenario_minmax_share",
                "actual_price_within_p10_p90_share",
                "actual_price_within_p05_p95_share",
            ]
        )

    frame = scenario_fan_inputs.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    rows: list[dict[str, Any]] = []
    group_cols = ["artifact_id", "model_label", "delivery_day"]
    for keys, group in frame.groupby(group_cols, sort=False):
        artifact_id, model_label, delivery_day = keys
        within_minmax = 0
        within_p10_p90 = 0
        within_p05_p95 = 0
        hour_count = 0
        for _, hour_group in group.groupby("delivery_start_utc", sort=True):
            values = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
            weights = hour_group["scenario_probability"].astype(float).to_numpy()
            actual = float(hour_group["actual_price_eur_per_mwh"].iloc[0])
            if values.size == 0:
                continue
            hour_count += 1
            scenario_min = float(np.min(values))
            scenario_max = float(np.max(values))
            p10 = _weighted_quantile(values, weights, 0.10)
            p90 = _weighted_quantile(values, weights, 0.90)
            p05 = _weighted_quantile(values, weights, 0.05)
            p95 = _weighted_quantile(values, weights, 0.95)
            within_minmax += int(scenario_min - TOLERANCE <= actual <= scenario_max + TOLERANCE)
            within_p10_p90 += int(p10 - TOLERANCE <= actual <= p90 + TOLERANCE)
            within_p05_p95 += int(p05 - TOLERANCE <= actual <= p95 + TOLERANCE)
        denominator = max(hour_count, 1)
        rows.append(
            {
                "artifact_id": str(artifact_id),
                "model_label": str(model_label),
                "delivery_day": str(delivery_day),
                "actual_price_within_scenario_minmax_share": float(within_minmax / denominator),
                "actual_price_within_p10_p90_share": float(within_p10_p90 / denominator),
                "actual_price_within_p05_p95_share": float(within_p05_p95 / denominator),
            }
        )
    return pd.DataFrame(rows)


def _redispatch_energy_by_day(actual_redispatch_timeseries: pd.DataFrame) -> pd.DataFrame:
    if actual_redispatch_timeseries.empty:
        return pd.DataFrame(
            columns=[
                "artifact_id",
                "model_label",
                "delivery_day",
                "electrolyser_energy_mwh",
                "compressor_energy_mwh",
            ]
        )
    frame = actual_redispatch_timeseries.copy()
    frame["timestep_hours"] = pd.to_numeric(frame["timestep_hours"], errors="coerce").fillna(1.0)
    frame["electrolyser_energy_mwh"] = pd.to_numeric(frame["P_el_mw"], errors="coerce").fillna(0.0) * frame["timestep_hours"]
    frame["compressor_energy_mwh"] = pd.to_numeric(frame["P_comp_mw"], errors="coerce").fillna(0.0) * frame["timestep_hours"]
    return (
        frame.groupby(["artifact_id", "model_label", "delivery_day"], as_index=False)
        .agg(
            electrolyser_energy_mwh=("electrolyser_energy_mwh", "sum"),
            compressor_energy_mwh=("compressor_energy_mwh", "sum"),
        )
        .reset_index(drop=True)
    )


def _build_enhanced_daily_metrics(
    *,
    suite_result: SelectedWeekSuiteResult,
    run_id: str,
    risk_mode: str,
    coverage_by_day: pd.DataFrame,
    actual_settlement_results: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
) -> pd.DataFrame:
    daily = suite_result.daily_metrics.copy()
    actual = actual_settlement_results.copy()
    actual["forecast_origin_utc"] = pd.to_datetime(actual["forecast_origin_utc"], utc=True, errors="raise")
    actual["delivery_day"] = pd.to_datetime(actual["delivery_day"], errors="coerce").fillna(pd.to_datetime(actual["forecast_origin_utc"], utc=True).dt.tz_convert("Europe/Amsterdam").dt.tz_localize(None).dt.normalize())
    actual["delivery_day"] = pd.to_datetime(actual["delivery_day"]).dt.strftime("%Y-%m-%d")
    actual_join = actual[
        [
            "artifact_id",
            "model_label",
            "delivery_day",
            "target_hydrogen_kg",
            "terminal_inventory_start_kg",
            "terminal_inventory_end_kg",
            "ramp_boundary_hits",
            "binary_variable_count",
            "constraint_count",
            "variable_count",
            "target_fulfilment_ratio",
        ]
    ].copy()
    energy_by_day = _redispatch_energy_by_day(actual_redispatch_timeseries)
    merged = daily.merge(coverage_by_day, on=["artifact_id", "model_label", "delivery_day"], how="left")
    merged = merged.merge(actual_join, on=["artifact_id", "model_label", "delivery_day"], how="left")
    merged = merged.merge(energy_by_day, on=["artifact_id", "model_label", "delivery_day"], how="left")

    merged["run_id"] = str(run_id)
    merged["strategy"] = "stochastic_bid_risk_neutral"
    merged["risk_mode"] = str(risk_mode)
    merged["cvar_alpha"] = pd.NA
    merged["cvar_gamma"] = 0.0
    merged["benchmark_profit"] = merged["price_insensitive_realised_adjusted_profit"]
    merged["value_captured_vs_perfect_foresight"] = pd.NA
    merged["average_actual_price_paid"] = merged["weighted_average_actual_price_paid"]
    merged["hours_with_zero_clearing"] = merged["zero_clearing_hours"]
    merged["hours_with_partial_clearing"] = merged["partial_clearing_hours"]
    merged["high_bid_share"] = merged["share_bid_energy_ge_250"]
    merged["market_cap_bid_share"] = merged["share_bid_energy_at_market_cap"]
    merged["average_bid_headroom_for_accepted_blocks"] = merged["bid_price_minus_actual_price_for_accepted_blocks_weighted"]
    merged["hydrogen_sold_or_compressed_kg"] = merged["hydrogen_compressed_or_sold_kg"]
    merged["production_fulfilment_ratio"] = merged["target_fulfilment_ratio_capped_for_reliability"]
    merged["storage_start_kg"] = merged["terminal_inventory_start_kg"]
    merged["storage_end_kg"] = merged["terminal_inventory_end_kg"]
    merged["electrolyser_energy_mwh"] = merged["electrolyser_energy_mwh"].fillna(0.0)
    merged["compressor_energy_mwh"] = merged["compressor_energy_mwh"].fillna(0.0)
    merged["electrolyser_ramp_hits"] = merged["ramp_boundary_hits"].fillna(0).astype(int)
    merged["scenario_probability_check"] = merged["probability_sum_per_origin"].astype(float).sub(1.0).abs() <= 1e-6
    merged["model_label"] = merged["artifact_id"].map(_label_for_artifact).fillna(merged["model_label"])
    merged["variable_count"] = merged["variables"]
    merged["binary_variable_count"] = merged["binaries"]
    merged["constraint_count"] = merged["constraints"]
    return merged


def _build_enhanced_weekly_metrics(
    *,
    daily_metrics: pd.DataFrame,
    selected_week: pd.Series,
    run_id: str,
    risk_mode: str,
) -> pd.DataFrame:
    group_cols = ["artifact_id", "model_label", "week_id", "week_label", "period_type", "strategy", "risk_mode", "run_id"]
    frame = daily_metrics.copy()
    frame["period_type"] = str(selected_week["period_type"])
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_cols, sort=False):
        artifact_id, model_label, week_id, week_label, period_type, strategy, local_risk_mode, local_run_id = keys
        submitted = float(group["submitted_energy_mwh"].sum())
        cleared = float(group["cleared_energy_mwh"].sum())
        accepted_headroom_numerator = float(group["accepted_bid_headroom_weighted_numerator"].sum())
        accepted_energy = float(group["accepted_bid_energy_mwh"].sum())
        row = {
            "run_id": str(local_run_id),
            "artifact_id": str(artifact_id),
            "model_label": str(model_label),
            "week_id": str(week_id),
            "period_type": str(period_type),
            "week_label": str(week_label),
            "week_start": str(selected_week["delivery_start_date"]),
            "week_end": str(selected_week["delivery_end_date"]),
            "number_of_delivery_days": int(group["delivery_day"].nunique()),
            "strategy": str(strategy),
            "risk_mode": str(local_risk_mode),
            "cvar_alpha": pd.NA,
            "cvar_gamma": 0.0,
            "solver_status": "Optimal" if group["solver_status"].astype(str).eq("Optimal").all() else "mixed",
            "objective_value": float(group["objective_value"].sum()),
            "solve_time_seconds": float(group["solve_time_seconds"].sum()),
            "mip_gap": float(group["mip_gap"].max(skipna=True)) if not group["mip_gap"].dropna().empty else float("nan"),
            "variable_count": int(group["variable_count"].max()),
            "binary_variable_count": int(group["binary_variable_count"].max()),
            "constraint_count": int(group["constraint_count"].max()),
            "realised_adjusted_profit": float(group["realised_adjusted_profit"].sum()),
            "realised_operating_profit": float(
                group["hydrogen_revenue"].sum()
                - group["DA_settlement_cost"].sum()
                - group["unused_energy_penalty_eur"].sum()
                - group["shortfall_penalty_eur"].sum()
            ),
            "hydrogen_revenue": float(group["hydrogen_revenue"].sum()),
            "da_settlement_cost": float(group["DA_settlement_cost"].sum()),
            "unused_energy_penalty": float(group["unused_energy_penalty_eur"].sum()),
            "shortfall_penalty": float(group["shortfall_penalty_eur"].sum()),
            "terminal_inventory_correction": float(group["terminal_inventory_correction_eur"].sum()),
            "benchmark_profit": float(group["benchmark_profit"].sum()),
            "stochastic_minus_benchmark_profit": float(group["stochastic_minus_benchmark_profit"].sum()),
            "value_captured_vs_perfect_foresight": pd.NA,
            "average_actual_price_paid": float(group["DA_settlement_cost"].sum() / cleared) if cleared > 0.0 else float("nan"),
            "submitted_energy_mwh": submitted,
            "cleared_energy_mwh": cleared,
            "rejected_energy_mwh": float(group["rejected_energy_mwh"].sum()),
            "used_cleared_energy_mwh": float(group["used_energy_mwh"].sum()),
            "unused_cleared_energy_mwh": float(group["unused_cleared_energy_mwh"].sum()),
            "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
            "rejected_energy_share": float(group["rejected_energy_mwh"].sum() / submitted) if submitted > 0.0 else 0.0,
            "hours_with_zero_clearing": int(group["hours_with_zero_clearing"].sum()),
            "hours_with_partial_clearing": int(group["hours_with_partial_clearing"].sum()),
            "weighted_average_bid_price": float(np.average(group["weighted_average_bid_price"], weights=group["submitted_energy_mwh"])) if submitted > 0.0 else float("nan"),
            "high_bid_share": float(group["submitted_energy_mwh"].mul(group["high_bid_share"]).sum() / submitted) if submitted > 0.0 else 0.0,
            "market_cap_bid_share": float(group["submitted_energy_mwh"].mul(group["market_cap_bid_share"]).sum() / submitted) if submitted > 0.0 else 0.0,
            "average_bid_headroom_for_accepted_blocks": float(accepted_headroom_numerator / accepted_energy) if accepted_energy > 0.0 else float("nan"),
            "hydrogen_produced_kg": float(group["hydrogen_produced_kg"].sum()),
            "hydrogen_sold_or_compressed_kg": float(group["hydrogen_sold_or_compressed_kg"].sum()),
            "target_hydrogen_kg": float(group["target_hydrogen_kg"].sum()),
            "production_fulfilment_ratio": float(
                min(group["hydrogen_sold_or_compressed_kg"].sum(), group["target_hydrogen_kg"].sum()) / group["target_hydrogen_kg"].sum()
            ) if float(group["target_hydrogen_kg"].sum()) > 0.0 else float("nan"),
            "shortfall_kg": float(group["shortfall_kg"].sum()),
            "storage_start_kg": float(group["storage_start_kg"].iloc[0]),
            "storage_end_kg": float(group["storage_end_kg"].iloc[-1]),
            "storage_min_kg": float(group["storage_min_kg"].min()),
            "storage_max_kg": float(group["storage_max_kg"].max()),
            "reserve_boundary_hits": int(group["reserve_boundary_hits"].sum()),
            "electrolyser_energy_mwh": float(group["electrolyser_energy_mwh"].sum()),
            "compressor_energy_mwh": float(group["compressor_energy_mwh"].sum()),
            "electrolyser_ramp_hits": int(group["electrolyser_ramp_hits"].sum()),
            "scenario_count": int(group["scenario_count"].mode().iloc[0]),
            "scenario_probability_check": bool(group["scenario_probability_check"].all()),
            "actual_price_within_scenario_minmax_share": float(group["actual_price_within_scenario_minmax_share"].mean()),
            "actual_price_within_p10_p90_share": float(group["actual_price_within_p10_p90_share"].mean()),
            "actual_price_within_p05_p95_share": float(group["actual_price_within_p05_p95_share"].mean()),
            "expected_profit_from_optimisation": float(group["expected_adjusted_profit"].sum()),
            "realised_minus_expected_profit": float(group["realised_adjusted_profit"].sum() - group["expected_adjusted_profit"].sum()),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _build_weekly_metrics_by_model(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    if weekly_metrics.empty:
        return pd.DataFrame()
    return weekly_metrics[
        [
            "artifact_id",
            "model_label",
            "week_id",
            "week_label",
            "realised_adjusted_profit",
            "benchmark_profit",
            "stochastic_minus_benchmark_profit",
            "submitted_energy_mwh",
            "cleared_energy_mwh",
            "rejected_energy_mwh",
            "clearing_ratio",
            "unused_cleared_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "shortfall_kg",
            "average_actual_price_paid",
            "solve_time_seconds",
            "solver_status",
        ]
    ].copy()


def _build_benchmark_metrics(
    *,
    benchmark_comparison: pd.DataFrame,
    selected_week: pd.Series,
    run_id: str,
) -> pd.DataFrame:
    if benchmark_comparison.empty:
        return pd.DataFrame()
    daily = benchmark_comparison.copy()
    daily["run_id"] = str(run_id)
    daily["week_id"] = str(selected_week["week_id"])
    daily["week_label"] = str(selected_week["week_label"])
    daily["period_type"] = str(selected_week["period_type"])
    daily["aggregation_level"] = "daily"
    daily["model_label"] = daily["artifact_id"].map(_label_for_artifact).fillna(daily["model_label"])
    daily["realised_adjusted_profit"] = daily["realised_adjusted_profit_eur"]
    daily["average_actual_price_paid"] = daily["weighted_average_actual_price_paid_for_cleared_energy"]

    weekly = (
        daily.groupby(["run_id", "artifact_id", "model_label", "week_id", "week_label", "period_type"], as_index=False)
        .agg(
            realised_adjusted_profit=("realised_adjusted_profit_eur", "sum"),
            cleared_energy_mwh=("cleared_energy_mwh", "sum"),
            used_energy_mwh=("used_energy_mwh", "sum"),
            unused_cleared_energy_mwh=("unused_cleared_energy_mwh", "sum"),
            hydrogen_sold_or_compressed_kg=("hydrogen_compressed_or_sold_kg", "sum"),
            shortfall_kg=("shortfall_kg", "sum"),
            da_settlement_cost=("realised_DA_settlement_cost_eur", "sum"),
            hydrogen_revenue=("hydrogen_revenue_eur", "sum"),
            unused_energy_penalty=("unused_energy_penalty_eur", "sum"),
            shortfall_penalty=("shortfall_penalty_eur", "sum"),
            terminal_inventory_correction=("terminal_inventory_correction_eur", "sum"),
            solve_time_seconds=("solve_time_seconds", "sum"),
            solver_status=("solver_status", lambda s: "Optimal" if pd.Series(s).astype(str).eq("Optimal").all() else "mixed"),
        )
    )
    weekly["aggregation_level"] = "weekly"
    weekly["strategy"] = "price_insensitive_plan_first_market_cap"
    weekly["week_start"] = str(selected_week["delivery_start_date"])
    weekly["week_end"] = str(selected_week["delivery_end_date"])
    weekly["average_actual_price_paid"] = weekly["da_settlement_cost"] / weekly["cleared_energy_mwh"]
    return pd.concat([daily, weekly], ignore_index=True, sort=False)


def _expected_phase_c_stochastic_count(
    *,
    artifact_ids: list[str],
    support_days: pd.DataFrame,
    expected_gamma_values: list[float] | tuple[float, ...],
) -> int:
    model_count = len({str(value) for value in artifact_ids})
    day_count = int(pd.to_datetime(support_days["delivery_date"], errors="coerce").nunique())
    gamma_count = len({round(float(value), 12) for value in expected_gamma_values}) or 1
    return int(model_count * day_count * gamma_count)


def _expected_phase_c_benchmark_counts(
    *,
    benchmark_scope: str,
    include_price_insensitive_benchmark: bool,
    artifact_ids: list[str],
    support_days: pd.DataFrame,
) -> dict[str, int]:
    if not include_price_insensitive_benchmark:
        return {"daily": 0, "weekly": 0}
    model_count = len({str(value) for value in artifact_ids})
    day_count = int(pd.to_datetime(support_days["delivery_date"], errors="coerce").nunique())
    normalized_scope = str(benchmark_scope).strip().lower()
    if normalized_scope == "per_model":
        return {"daily": int(model_count * day_count), "weekly": int(model_count)}
    if normalized_scope == "shared":
        return {"daily": int(day_count), "weekly": 1}
    raise ValueError(f"Unsupported Phase C benchmark scope: {benchmark_scope!r}")


def _summarise_phase_c_runtime(
    *,
    profiler: RuntimeProfiler,
    preflight_runtime: pd.DataFrame,
    suite_runtime: pd.DataFrame,
    total_wall_seconds: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    wrapper_runtime = profiler.to_frame().copy()
    if not wrapper_runtime.empty:
        wrapper_runtime["timing_source"] = "wrapper_wall_clock"
        rows.extend(wrapper_runtime.to_dict(orient="records"))
    if not preflight_runtime.empty:
        preflight_rows = preflight_runtime.copy()
        preflight_rows["stage"] = preflight_rows["stage"].astype(str).map(lambda value: f"preflight_{value}")
        preflight_rows["timing_source"] = "selected_week_preflight_wall_clock"
        if "accounting_bucket" not in preflight_rows.columns:
            preflight_rows["accounting_bucket"] = "preflight_wall"
        rows.extend(preflight_rows.to_dict(orient="records"))
    if not suite_runtime.empty:
        suite_rows = suite_runtime.copy()
        suite_rows["timing_source"] = "selected_week_suite_runtime"
        rows.extend(suite_rows.to_dict(orient="records"))

    runtime_frame = pd.DataFrame(rows)
    if runtime_frame.empty:
        return runtime_frame
    if "accounting_bucket" not in runtime_frame.columns:
        runtime_frame["accounting_bucket"] = ""
    included_buckets = {"wrapper_wall", "preflight_wall", "wall"}
    sum_profiled_stage_seconds = float(
        pd.to_numeric(
            runtime_frame.loc[runtime_frame["accounting_bucket"].astype(str).isin(included_buckets), "wall_time_seconds"],
            errors="coerce",
        ).sum()
    )
    unprofiled_seconds = max(float(total_wall_seconds) - sum_profiled_stage_seconds, 0.0)
    unprofiled_share = float(unprofiled_seconds / total_wall_seconds) if float(total_wall_seconds) > 0.0 else float("nan")
    summary_rows = pd.DataFrame(
        [
            {
                "stage": "total_wall_seconds",
                "started_utc": pd.NA,
                "finished_utc": pd.NA,
                "wall_time_seconds": float(total_wall_seconds),
                "timing_source": "summary",
                "metric_name": "summary",
                "accounting_bucket": "summary",
            },
            {
                "stage": "sum_profiled_stage_seconds",
                "started_utc": pd.NA,
                "finished_utc": pd.NA,
                "wall_time_seconds": float(sum_profiled_stage_seconds),
                "timing_source": "summary",
                "metric_name": "summary",
                "accounting_bucket": "summary",
            },
            {
                "stage": "unprofiled_seconds",
                "started_utc": pd.NA,
                "finished_utc": pd.NA,
                "wall_time_seconds": float(unprofiled_seconds),
                "timing_source": "summary",
                "metric_name": "summary",
                "accounting_bucket": "summary",
            },
            {
                "stage": "unprofiled_share",
                "started_utc": pd.NA,
                "finished_utc": pd.NA,
                "wall_time_seconds": float(unprofiled_share),
                "timing_source": "summary",
                "metric_name": "summary_fraction",
                "accounting_bucket": "summary",
            },
        ]
    )
    runtime_frame = pd.concat([runtime_frame, summary_rows], ignore_index=True, sort=False)
    preferred_columns = [
        "stage",
        "started_utc",
        "finished_utc",
        "wall_time_seconds",
        "timing_source",
        "metric_name",
    ]
    other_columns = [column for column in runtime_frame.columns if column not in preferred_columns]
    return runtime_frame[preferred_columns + other_columns] if not runtime_frame.empty else runtime_frame


def _build_phase_c_validation_checks(
    *,
    existing_checks: pd.DataFrame,
    selected_week: pd.Series,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    expected_gamma_values: list[float] | tuple[float, ...],
    include_price_insensitive_benchmark: bool,
    benchmark_scope: str,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    suite_result: SelectedWeekSuiteResult,
    requested_week_id: str,
) -> pd.DataFrame:
    checks = existing_checks.copy()
    rows: list[dict[str, str]] = []
    week_id = str(selected_week["week_id"])
    week_label = str(selected_week["week_label"])
    day_count = int(support_days.shape[0])
    expected_artifact_ids = sorted({str(value) for value in artifact_ids})
    expected_stochastic_run_count = _expected_phase_c_stochastic_count(
        artifact_ids=artifact_ids,
        support_days=support_days,
        expected_gamma_values=expected_gamma_values,
    )
    benchmark_counts = _expected_phase_c_benchmark_counts(
        benchmark_scope=benchmark_scope,
        include_price_insensitive_benchmark=include_price_insensitive_benchmark,
        artifact_ids=artifact_ids,
        support_days=support_days,
    )
    rows.append(
        _validation_row(
            check_name="selected_week_matches_phase_c_target",
            status="pass"
            if str(requested_week_id)
            in {
                str(selected_week.get("requested_identifier", "")),
                str(selected_week.get("regime_label", "")),
                str(selected_week["week_label"]),
                str(selected_week["week_id"]),
            }
            else "fail",
            details=(
                f"requested={requested_week_id}, resolved_week_label={week_label}, "
                f"start={selected_week['delivery_start_date']}, end={selected_week['delivery_end_date']}"
            ),
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="exactly_one_selected_week_run",
            status="pass" if int(suite_result.selected_week_registry.shape[0]) == 1 else "fail",
            details=f"selected_week_count={int(suite_result.selected_week_registry.shape[0])}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="all_selected_days_inside_common_support",
            status="pass" if int(day_count) == 7 and support_days["common_complete_support"].astype(bool).all() else "fail",
            details=f"selected_day_count={day_count}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="all_selected_days_have_complete_actual_prices",
            status="pass" if support_days["complete_actual_prices"].astype(bool).all() else "fail",
            details=f"complete_actual_price_days={int(support_days['complete_actual_prices'].astype(bool).sum())}/7",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="all_selected_days_have_75_scenarios_per_origin",
            status="pass"
            if (
                support_days["n_scenarios_per_origin_lear_strict"].astype(int).eq(75).all()
                and support_days["n_scenarios_per_origin_lear_fs3"].astype(int).eq(75).all()
                and support_days["n_scenarios_per_origin_xgboost_fs3"].astype(int).eq(75).all()
            )
            else "fail",
            details="expected 75 scenarios per origin for all three artifacts on all selected days",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="selected_week_methodological_use_matches_split",
            status="pass"
            if str(selected_week["methodological_use"]) == expected_methodological_use(str(selected_week["period_type"]))
            else "fail",
            details=f"methodological_use={selected_week['methodological_use']}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="all_requested_artifacts_run_on_same_week",
            status="pass"
            if sorted(daily_metrics["artifact_id"].astype(str).unique().tolist()) == expected_artifact_ids
            else "fail",
            details=f"artifacts={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="stochastic_milp_run_count_matches_expected_matrix",
            status="pass" if int(daily_metrics.shape[0]) == expected_stochastic_run_count else "fail",
            details=(
                f"expected={expected_stochastic_run_count}, actual={int(daily_metrics.shape[0])}, "
                f"models={len(expected_artifact_ids)}, days={int(pd.to_datetime(support_days['delivery_date'], errors='coerce').nunique())}, "
                f"gammas={sorted({round(float(value), 12) for value in expected_gamma_values})}"
            ),
            week_id=week_id,
            week_label=week_label,
        )
    )
    benchmark_weekly = benchmark_metrics.loc[
        benchmark_metrics.get("aggregation_level", pd.Series(dtype=object)).astype(str) == "weekly"
    ]
    benchmark_daily = benchmark_metrics.loc[
        benchmark_metrics.get("aggregation_level", pd.Series(dtype=object)).astype(str) == "daily"
    ]
    rows.append(
        _validation_row(
            check_name="benchmark_run_count_matches_configured_policy",
            status="pass"
            if (
                int(benchmark_weekly.shape[0]) == int(benchmark_counts["weekly"])
                and int(benchmark_daily.shape[0]) == int(benchmark_counts["daily"])
            )
            else "fail",
            details=(
                f"scope={benchmark_scope}, expected_weekly={int(benchmark_counts['weekly'])}, "
                f"actual_weekly={int(benchmark_weekly.shape[0])}, expected_daily={int(benchmark_counts['daily'])}, "
                f"actual_daily={int(benchmark_daily.shape[0])}"
            ),
            week_id=week_id,
            week_label=week_label,
        )
    )
    if include_price_insensitive_benchmark and str(benchmark_scope).strip().lower() == "per_model":
        benchmark_weekly_artifacts = sorted(
            benchmark_weekly.get("artifact_id", pd.Series(dtype=object)).astype(str).unique().tolist()
        )
        rows.append(
            _validation_row(
                check_name="benchmark_artifact_support_matches_requested_models",
                status="pass"
                if benchmark_weekly_artifacts == expected_artifact_ids
                else "fail",
                details=(
                    f"expected_artifacts={expected_artifact_ids}, "
                    f"actual_artifacts={benchmark_weekly_artifacts}"
                ),
                week_id=week_id,
                week_label=week_label,
            )
        )
    rows.append(
        _validation_row(
            check_name="scenario_probabilities_sum_to_one_per_origin",
            status="pass" if daily_metrics["scenario_probability_check"].astype(bool).all() else "fail",
            details=f"pass_count={int(daily_metrics['scenario_probability_check'].astype(bool).sum())}/{int(daily_metrics.shape[0])}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="no_cvar_variables_or_gamma_sweep_activated",
            status="pass"
            if (
                scenario_settlement_results["risk_measure"].astype(str).eq("risk_neutral").all()
                and pd.to_numeric(scenario_settlement_results["cvar_gamma"], errors="coerce").fillna(0.0).abs().le(1e-12).all()
            )
            else "fail",
            details=(
                f"risk_measures={sorted(scenario_settlement_results['risk_measure'].astype(str).unique().tolist())}, "
                f"gamma_values={sorted(pd.to_numeric(scenario_settlement_results['cvar_gamma'], errors='coerce').fillna(0.0).round(9).unique().tolist())}"
            ),
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="no_quarter_hour_data_used",
            status="pass"
            if (
                actual_clearing["granularity"].astype(str).eq("hourly").all()
                and pd.to_numeric(actual_clearing["timestep_hours"], errors="coerce").fillna(0.0).eq(1.0).all()
            )
            else "fail",
            details=f"granularities={sorted(actual_clearing['granularity'].astype(str).unique().tolist())}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="no_d_plus_4_data_used",
            status="pass" if actual_clearing["horizon"].astype(str).eq("D_only").all() else "fail",
            details=f"horizons={sorted(actual_clearing['horizon'].astype(str).unique().tolist())}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="used_cleared_energy_plus_unused_equals_cleared_weekly",
            status="pass"
            if (
                actual_redispatch_timeseries.groupby(["artifact_id", "model_label", "delivery_day"])
                .apply(
                    lambda grp: abs(
                        float(grp["used_energy_mwh"].sum() + grp["unused_cleared_energy_mwh"].sum() - grp["cleared_energy_mwh"].sum())
                    )
                    <= 1e-6
                )
                .astype(bool)
                .all()
            )
            else "fail",
            details="weekly redispatch energy balance grouped by model and day",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="benchmark_uses_same_actual_prices_and_days",
            status="pass"
            if not benchmark_metrics.empty
            and benchmark_metrics["period_type"].astype(str).eq(str(selected_week["period_type"])).all()
            else "fail",
            details=f"benchmark rows present and tagged to the same selected {selected_week['period_type']} week",
            week_id=week_id,
            week_label=week_label,
        )
    )
    rows.append(
        _validation_row(
            check_name="no_selected_week_crosses_split_boundary",
            status="pass"
            if weekly_metrics["period_type"].astype(str).eq(str(selected_week["period_type"])).all()
            else "fail",
            details=f"period_types={sorted(weekly_metrics['period_type'].astype(str).unique().tolist())}",
            week_id=week_id,
            week_label=week_label,
        )
    )
    appended = pd.DataFrame(rows)
    if checks.empty:
        checks = appended
    else:
        checks = pd.concat([checks, appended], ignore_index=True)
    return checks


def _write_phase_c_readme(
    *,
    run_dir: Path,
    selected_week: pd.Series,
    artifact_ids: list[str],
    weekly_metrics: pd.DataFrame,
    validation_checks: pd.DataFrame,
) -> None:
    selected_week_split = str(selected_week["period_type"])
    support_label = _support_label_for_split(selected_week_split)
    summary = weekly_metrics[
        [
            "model_label",
            "realised_adjusted_profit",
            "benchmark_profit",
            "stochastic_minus_benchmark_profit",
            "submitted_energy_mwh",
            "cleared_energy_mwh",
            "rejected_energy_mwh",
            "clearing_ratio",
            "unused_cleared_energy_mwh",
            "hydrogen_sold_or_compressed_kg",
            "shortfall_kg",
            "average_actual_price_paid",
            "solve_time_seconds",
            "solver_status",
        ]
    ].copy()
    lines = [
        "# Phase C Selected-Week Risk-Neutral Smoke Run",
        "",
        "## Scope",
        "",
        f"- label: {support_label}",
        "- market scope: hourly, D-only, DA-only",
        f"- week scope: exactly one selected common-support {selected_week_split} week",
        "- risk mode: risk-neutral stochastic bidding only",
        "- benchmark: price-insensitive benchmark on the same actual prices and delivery days",
        "- exclusions: no CVaR, no gamma sweeps, no mFRR, no quarter-hour, no D+4, no exclusive group bids",
        "",
        "## Selected Week",
        "",
        f"- week_label: `{selected_week['week_label']}`",
        f"- week_id: `{selected_week['week_id']}`",
        f"- delivery_start_date: `{selected_week['delivery_start_date']}`",
        f"- delivery_end_date: `{selected_week['delivery_end_date']}`",
        f"- selection_reason: {selected_week['selection_reason']}",
        f"- rationale: development smoke run on one exact-common-support {selected_week_split} week.",
        "",
        "## Artifacts / Models",
        "",
    ]
    for artifact_id in artifact_ids:
        lines.append(f"- `{artifact_id}`")
    lines.extend(
        [
            "",
            "## Method",
            "",
            "Pipeline: `scenario input -> stochastic bid optimisation -> actual clearing -> deterministic redispatch -> pay-as-cleared settlement -> metrics`.",
            "",
            "Important interpretation rules:",
            "- expected optimisation profit and realised settlement profit are different quantities;",
            "- realised DA settlement uses the actual market price, not the submitted bid price;",
            "- redispatch can only use actually cleared electricity;",
            (
                "- selected validation weeks are development-stage tuning and smoke-test inputs only, not final out-of-sample test evidence."
                if selected_week_split == "validation"
                else "- selected test weeks are diagnostic reporting only, not CVaR gamma tuning data."
            ),
            "",
            "## Weekly Results",
            "",
            "```csv",
            summary.to_csv(index=False).strip(),
            "```",
        ]
    )

    hard_fail_count = int(
        validation_checks.loc[
            validation_checks["severity"].astype(str).eq("hard_fail")
            & validation_checks["status"].astype(str).eq("fail")
        ].shape[0]
    )
    lines.extend(
        [
            "",
            "## Validation Status",
            "",
            f"- hard_fail_count: {hard_fail_count}",
            f"- total_checks: {int(validation_checks.shape[0])}",
            "- benchmark and stochastic runs use the same selected delivery week and actual DA prices.",
            "",
            "## Known Limitations",
            "",
            "- this is not a full split-wide three-model comparison;",
            "- results are limited to one exact-common-support selected week;",
            "- no perfect-foresight comparator is included here, so value captured vs perfect foresight remains `NA`;",
            "- scenario undercoverage warnings still matter and should be interpreted alongside realised economics.",
            "",
            "## Acceptance",
            "",
            f"- Phase C status: {'pass' if hard_fail_count == 0 else 'fail'}",
        ]
    )
    save_text(run_dir, "README_selected_week_smoke.md", "\n".join(lines))


def _plot_time_series_by_model(
    *,
    frame: pd.DataFrame,
    value_columns: list[str],
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    if frame.empty:
        return
    apply_visual_style()
    ordered_models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in frame["model_label"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(len(ordered_models), 1, figsize=(14, max(4.0, 3.3 * len(ordered_models))), sharex=True)
    if len(ordered_models) == 1:
        axes = [axes]
    for ax, model_label in zip(axes, ordered_models, strict=True):
        model_frame = frame.loc[frame["model_label"].astype(str) == model_label].copy().sort_values("delivery_start_utc")
        color = MODEL_COLORS.get(model_label, "#1F4E79")
        for idx, column in enumerate(value_columns):
            series_color = [color, "#31a354", "#d95f0e", "#6a3d9a"][idx % 4]
            ax.step(model_frame["delivery_start_utc"], pd.to_numeric(model_frame[column], errors="coerce"), where="post", linewidth=1.6, label=column, color=series_color)
        ax.set_ylabel(ylabel)
        ax.set_title(model_label)
        ax.legend(loc="upper left", ncol=min(len(value_columns), 4))
    axes[-1].set_xlabel("Delivery hour (UTC)")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_weekly_model_comparison(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    metrics = [
        ("realised_adjusted_profit", "Realised adjusted profit"),
        ("stochastic_minus_benchmark_profit", "Stochastic - benchmark"),
        ("clearing_ratio", "Clearing ratio"),
        ("production_fulfilment_ratio", "Hydrogen fulfilment"),
        ("average_actual_price_paid", "Average actual price paid"),
        ("solve_time_seconds", "Solve time"),
    ]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(10, 16))
    if len(metrics) == 1:
        axes = [axes]
    frame = weekly_metrics.copy().sort_values("model_label").reset_index(drop=True)
    x = np.arange(frame.shape[0])
    colors = [MODEL_COLORS.get(label, "#1F4E79") for label in frame["model_label"].astype(str)]
    for ax, (column, title) in zip(axes, metrics, strict=True):
        ax.bar(x, pd.to_numeric(frame[column], errors="coerce"), color=colors)
        ax.set_xticks(x)
        ax.set_xticklabels(frame["model_label"], rotation=15, ha="right")
        ax.set_title(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_economic_decomposition(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    components = [
        "hydrogen_revenue",
        "da_settlement_cost",
        "unused_energy_penalty",
        "shortfall_penalty",
        "terminal_inventory_correction",
    ]
    frame = weekly_metrics.copy().sort_values("model_label").reset_index(drop=True)
    x = np.arange(frame.shape[0])
    fig, ax = plt.subplots(figsize=(11, 6))
    bottom_positive = np.zeros(frame.shape[0])
    bottom_negative = np.zeros(frame.shape[0])
    color_map = {
        "hydrogen_revenue": "#31a354",
        "da_settlement_cost": "#2b8cbe",
        "unused_energy_penalty": "#d95f0e",
        "shortfall_penalty": "#6a3d9a",
        "terminal_inventory_correction": "#636363",
    }
    sign_flipped = {"da_settlement_cost", "unused_energy_penalty", "shortfall_penalty"}
    for component in components:
        values = pd.to_numeric(frame[component], errors="coerce").fillna(0.0).to_numpy()
        if component in sign_flipped:
            values = -values
        positive = np.where(values >= 0.0, values, 0.0)
        negative = np.where(values < 0.0, values, 0.0)
        ax.bar(x, positive, bottom=bottom_positive, color=color_map[component], label=component)
        ax.bar(x, negative, bottom=bottom_negative, color=color_map[component])
        bottom_positive = bottom_positive + positive
        bottom_negative = bottom_negative + negative
    ax.scatter(x, pd.to_numeric(frame["realised_adjusted_profit"], errors="coerce"), color="#111111", label="realised_adjusted_profit", zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(frame["model_label"], rotation=15, ha="right")
    ax.set_ylabel("EUR")
    ax.set_title("Weekly economic decomposition")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_validation_summary(validation_checks: pd.DataFrame, output_path: Path) -> None:
    if validation_checks.empty:
        return
    apply_visual_style()
    summary = (
        validation_checks.groupby(["severity", "status"], as_index=False)
        .size()
        .sort_values(["severity", "status"])
        .reset_index(drop=True)
    )
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = summary["severity"].astype(str) + " | " + summary["status"].astype(str)
    ax.bar(labels, summary["size"], color="#4C78A8")
    ax.set_ylabel("Check count")
    ax.set_title("Validation summary")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _create_phase_c_figures(
    *,
    run_dir: Path,
    suite_result: SelectedWeekSuiteResult,
    actual_clearing_by_hour: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    validation_checks: pd.DataFrame,
) -> None:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    scenario_fan_path = suite_result.suite_dir / "notebook_inputs" / "scenario_fan_inputs.parquet"
    if scenario_fan_path.exists():
        scenario_fan_inputs = pd.read_parquet(scenario_fan_path)
        _plot_time_series_by_model(
            frame=scenario_fan_inputs.rename(columns={"actual_price_eur_per_mwh": "actual_price"}),
            value_columns=["actual_price"],
            ylabel="EUR/MWh",
            title="Actual DA price across the selected week",
            output_path=figures_dir / "scenario_fan_vs_realised_price_actual_overlay.png",
        )

    submitted_bids_path = run_dir / "submitted_bids.parquet"
    if submitted_bids_path.exists():
        submitted = pd.read_parquet(submitted_bids_path)
        representative = (
            submitted.groupby(["model_label", "delivery_start_utc"], as_index=False)["bid_quantity_mw"]
            .sum()
            .sort_values(["model_label", "bid_quantity_mw"], ascending=[True, False])
            .groupby("model_label", as_index=False)
            .head(3)
        )
        selected_hours = representative["delivery_start_utc"].drop_duplicates().tolist()
        if selected_hours:
            from .plots import plot_submitted_bid_curves_with_actual_overlays

            actual_prices = (
                actual_clearing_by_hour[["model_label", "delivery_start_utc", "actual_price_eur_per_mwh"]]
                .drop_duplicates()
                .assign(actual_path_id=lambda df: df["model_label"].astype(str))
            )
            for model_label in submitted["model_label"].astype(str).unique():
                model_bids = submitted.loc[submitted["model_label"].astype(str) == model_label].copy()
                model_prices = actual_prices.loc[actual_prices["model_label"].astype(str) == model_label].copy()
                if model_bids.empty or model_prices.empty:
                    continue
                plot_submitted_bid_curves_with_actual_overlays(
                    submitted_bids=model_bids,
                    actual_price_paths=model_prices[["delivery_start_utc", "actual_price_eur_per_mwh", "actual_path_id"]],
                    selected_hours=selected_hours[:3],
                    output_dir=figures_dir,
                    filename=f"submitted_bid_curve_{model_label.lower().replace(' ', '_')}.png",
                )

    _plot_time_series_by_model(
        frame=actual_clearing_by_hour,
        value_columns=["submitted_energy_mwh", "cleared_energy_mwh", "rejected_energy_mwh"],
        ylabel="MWh",
        title="Submitted, cleared, and rejected electricity",
        output_path=figures_dir / "submitted_cleared_rejected_electricity.png",
    )
    _plot_time_series_by_model(
        frame=actual_redispatch_timeseries,
        value_columns=["cleared_energy_mwh", "used_energy_mwh", "unused_cleared_energy_mwh"],
        ylabel="MWh",
        title="Cleared, used, and unused electricity",
        output_path=figures_dir / "cleared_used_unused_electricity.png",
    )
    _plot_time_series_by_model(
        frame=actual_redispatch_timeseries,
        value_columns=["H_prod_kg", "H_comp_kg", "H_buf_kg", "shortfall_kg"],
        ylabel="kg / state",
        title="Hydrogen operation and storage trajectory",
        output_path=figures_dir / "hydrogen_operation.png",
    )
    _plot_economic_decomposition(weekly_metrics, figures_dir / "weekly_economic_decomposition.png")
    _plot_weekly_model_comparison(weekly_metrics, figures_dir / "weekly_model_comparison.png")
    _plot_validation_summary(validation_checks, figures_dir / "validation_summary.png")


def run_selected_week_risk_neutral_smoke(
    *,
    config: HydrogenConfig | str | Path,
    week_id: str,
    artifact_ids: list[str] | tuple[str, ...],
    run_slug: str,
    risk_mode: str = "risk_neutral",
    include_price_insensitive_benchmark: bool = True,
    output_root: Path | None = None,
    week_registry_path: Path = DEFAULT_WEEK_REGISTRY,
    support_csv_path: Path = DEFAULT_SUPPORT_CSV,
    selected_weeks_yaml_path: Path | None = DEFAULT_SELECTED_WEEKS_YAML,
    selected_week_split: str = "validation",
    output_mode: str = "speed",
    progress_reporting: bool = False,
    progress_metadata: dict[str, Any] | None = None,
    external_progress_reporter: ProgressReporter | None = None,
) -> PhaseCSmokeRunResult:
    if str(risk_mode) != "risk_neutral":
        raise ValueError(f"Phase C supports risk_neutral only, got {risk_mode!r}.")
    if not include_price_insensitive_benchmark:
        raise ValueError("Phase C requires the price-insensitive benchmark to be enabled.")

    run_wall_started = perf_counter()
    resolved_config = config if isinstance(config, HydrogenConfig) else load_hydrogen_config(config)
    normalized_split = _normalize_selected_week_split(selected_week_split)
    profiler = RuntimeProfiler()
    smoke_output_policy = get_output_policy(_resolve_output_policy_name(output_mode))
    selected_weeks_path = Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None
    preflight_cache_root = (Path(output_root) if output_root is not None else resolved_config.run_output_root) / DEFAULT_PREFLIGHT_CACHE_DIRNAME
    with profiler.track(
        "selected_week_resolve",
        requested_week_id=str(week_id),
        selected_week_split=normalized_split,
        accounting_bucket="wrapper_wall",
    ):
        selected_week, support_days = load_and_validate_phase_c_week(
            week_registry_path=Path(week_registry_path),
            support_csv_path=Path(support_csv_path),
            selected_weeks_yaml_path=selected_weeks_path,
            week_id=week_id,
            selected_week_split=normalized_split,
        )
    with profiler.track(
        "selected_week_input_preflight",
        requested_week_id=str(week_id),
        artifact_count=len({str(value) for value in artifact_ids}),
        output_policy_name=smoke_output_policy.name,
        accounting_bucket="container",
    ):
        preflight = run_selected_week_input_preflight(
            config=resolved_config,
            artifact_ids=[str(value) for value in artifact_ids],
            requested_identifiers=[str(week_id)],
            selected_weeks_yaml_path=selected_weeks_path,
            expected_split=normalized_split,
            cache_root=preflight_cache_root,
            output_policy_name=smoke_output_policy.name,
        )
    preflight_fail_count = int(preflight.audit_rows.loc[preflight.audit_rows["status"].astype(str).eq("fail")].shape[0])
    if preflight_fail_count > 0:
        raise RuntimeError(
            f"Phase C selected-week input preflight failed ({preflight_fail_count}); "
            f"requested_week_id={week_id}, split={normalized_split}."
        )

    single_week_registry = pd.DataFrame([selected_week.to_dict()])
    with tempfile.TemporaryDirectory(prefix="phase_c_selected_week_") as temp_dir:
        temp_registry_path = Path(temp_dir) / "selected_week_registry_one_week.csv"
        single_week_registry.to_csv(temp_registry_path, index=False)
        with profiler.track(
            "suite_execution",
            artifact_count=len({str(value) for value in artifact_ids}),
            selected_week_label=str(selected_week["week_label"]),
            accounting_bucket="container",
        ):
            suite_result = run_real_scenario_selected_week_suite(
                config=resolved_config,
                artifact_ids=[str(value) for value in artifact_ids],
                week_registry=temp_registry_path,
                output_root=output_root,
                strategy_name="stochastic_bid_risk_neutral",
                include_price_insensitive_benchmark=True,
                risk_measure="risk_neutral",
                experiment_name=str(run_slug),
                output_policy_name=smoke_output_policy.name,
                cache_root=preflight_cache_root,
                progress_reporting=bool(progress_reporting),
                progress_metadata=progress_metadata,
                external_progress_reporter=external_progress_reporter,
            )

    run_dir = suite_result.suite_dir
    run_id = run_dir.name
    actual_settlement_results = suite_result.actual_settlement_results.copy()
    scenario_settlement_results = suite_result.scenario_settlement_results.copy()
    actual_clearing = suite_result.actual_clearing.copy()
    actual_clearing_by_hour = suite_result.actual_clearing_by_hour.copy()
    actual_redispatch_timeseries = suite_result.actual_redispatch_timeseries.copy()
    submitted_bids = suite_result.submitted_bids.copy()
    scenario_clearing = suite_result.scenario_clearing.copy()
    benchmark_comparison = suite_result.benchmark_comparison.copy()
    input_manifests = list(suite_result.input_manifests)
    scenario_manifests = list(suite_result.scenario_manifests)

    with profiler.track("metrics_reporting", run_id=str(run_id), accounting_bucket="wrapper_wall"):
        scenario_fan_inputs = suite_result.scenario_fan_inputs.copy()
        coverage_by_day = _scenario_coverage_by_day(scenario_fan_inputs)

        actual_settlement_results["artifact_id"] = actual_settlement_results["artifact_id"].astype(str)
        actual_settlement_results["model_label"] = actual_settlement_results["artifact_id"].map(_label_for_artifact)
        actual_settlement_results["delivery_day"] = pd.to_datetime(actual_settlement_results["forecast_origin_utc"], utc=True, errors="raise").dt.tz_convert("Europe/Amsterdam").dt.tz_localize(None).dt.normalize() + pd.Timedelta(days=1)
        actual_settlement_results["delivery_day"] = actual_settlement_results["delivery_day"].dt.strftime("%Y-%m-%d")

        daily_metrics = _build_enhanced_daily_metrics(
            suite_result=suite_result,
            run_id=run_id,
            risk_mode=risk_mode,
            coverage_by_day=coverage_by_day,
            actual_settlement_results=actual_settlement_results,
            actual_redispatch_timeseries=actual_redispatch_timeseries,
        )
        weekly_metrics = _build_enhanced_weekly_metrics(
            daily_metrics=daily_metrics,
            selected_week=selected_week,
            run_id=run_id,
            risk_mode=risk_mode,
        )
        benchmark_metrics = _build_benchmark_metrics(
            benchmark_comparison=benchmark_comparison,
            selected_week=selected_week,
            run_id=run_id,
        )
    with profiler.track("validation_checks", run_id=str(run_id), accounting_bucket="wrapper_wall"):
        validation_checks = _build_phase_c_validation_checks(
            existing_checks=suite_result.validation_checks_all_runs,
            selected_week=selected_week,
            support_days=support_days,
            artifact_ids=[str(value) for value in artifact_ids],
            expected_gamma_values=list(PHASE_C_EXPECTED_GAMMAS),
            include_price_insensitive_benchmark=include_price_insensitive_benchmark,
            benchmark_scope=PHASE_C_BENCHMARK_SCOPE,
            daily_metrics=daily_metrics,
            weekly_metrics=weekly_metrics,
            actual_clearing=actual_clearing,
            actual_redispatch_timeseries=actual_redispatch_timeseries,
            scenario_settlement_results=scenario_settlement_results,
            benchmark_metrics=benchmark_metrics,
            suite_result=suite_result,
            requested_week_id=str(week_id),
        )

    selected_week_manifest = {
        "week_id": str(selected_week["week_id"]),
        "week_label": str(selected_week["week_label"]),
        "period_type": str(selected_week["period_type"]),
        "delivery_start_date": str(selected_week["delivery_start_date"]),
        "delivery_end_date": str(selected_week["delivery_end_date"]),
        "support_status": str(selected_week["support_status"]),
        "methodological_use": str(selected_week["methodological_use"]),
        "selection_reason": str(selected_week["selection_reason"]),
        "selected_delivery_days": support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist(),
    }
    scenario_manifest = {
        "phase": "C",
        "support_label": _support_label_for_split(normalized_split),
        "risk_mode": str(risk_mode),
        "artifacts": scenario_manifests,
        "input_manifests": input_manifests,
    }
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    run_manifest["phase"] = "C"
    run_manifest["requested_week_id"] = str(week_id)
    run_manifest["requested_run_slug"] = str(run_slug)
    run_manifest["selected_week_manifest_path"] = str(run_dir / "selected_week_manifest.json")
    run_manifest["scenario_manifest_path"] = str(run_dir / "scenario_manifest.json")
    run_manifest["support_statement"] = _support_label_for_split(normalized_split)
    run_manifest["benchmark_scope"] = PHASE_C_BENCHMARK_SCOPE
    run_manifest["preflight_cache_root"] = str(preflight_cache_root)
    run_manifest["selected_week_input_preflight_path"] = str(run_dir / "selected_week_input_preflight.csv")
    run_manifest["selected_week_input_runtime_profile_path"] = str(run_dir / "selected_week_input_runtime_profile.csv")
    run_manifest["runtime_profile_path"] = str(run_dir / "runtime_profile.csv")
    run_manifest["runtime_profile_json_path"] = str(run_dir / "runtime_profile.json")
    run_manifest["selected_week_execution_audit_path"] = str(run_dir / "selected_week_execution_audit.csv")
    run_manifest["selected_week_slice_audit_path"] = str(run_dir / "selected_week_slice_audit.csv")
    run_manifest["smoke_output_policy_name"] = smoke_output_policy.name
    run_manifest["requested_output_mode"] = str(output_mode)

    with profiler.track("output_writing", run_id=str(run_id), accounting_bucket="wrapper_wall"):
        save_frame_csv(run_dir, "selected_week_input_preflight.csv", preflight.audit_rows)
        save_frame_csv(run_dir, "selected_week_input_runtime_profile.csv", preflight.runtime_profile)
        save_json(
            run_dir,
            "selected_week_preflight_manifest.json",
            {
                "output_policy_name": preflight.output_policy_name,
                "cache_root": str(preflight.cache_root) if preflight.cache_root is not None else "",
                "cache_status_counts": preflight.audit_rows["cache_status"].astype(str).value_counts().to_dict(),
                "requested_identifiers": [str(week_id)],
                "artifact_ids": [str(value) for value in artifact_ids],
                "expected_split": normalized_split,
            },
        )
        save_json(run_dir, "selected_week_manifest.json", selected_week_manifest)
        save_json(run_dir, "scenario_manifest.json", scenario_manifest)
        save_json(run_dir, "run_manifest.json", run_manifest)
        save_frame_csv(run_dir, "selected_week_execution_audit.csv", suite_result.execution_audit)
        save_frame_csv(run_dir, "selected_week_slice_audit.csv", suite_result.slice_audit)
        save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
        save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
        save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
        save_frame_csv(run_dir, "weekly_metrics_by_model.csv", _build_weekly_metrics_by_model(weekly_metrics))
        save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
        save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks)

    with profiler.track("readme_generation", run_id=str(run_id), accounting_bucket="wrapper_wall"):
        _write_phase_c_readme(
            run_dir=run_dir,
            selected_week=selected_week,
            artifact_ids=[str(value) for value in artifact_ids],
            weekly_metrics=weekly_metrics,
            validation_checks=validation_checks,
        )
    with profiler.track("figure_generation", run_id=str(run_id), accounting_bucket="wrapper_wall"):
        if smoke_output_policy.save_figures:
            _create_phase_c_figures(
                run_dir=run_dir,
                suite_result=suite_result,
                actual_clearing_by_hour=actual_clearing_by_hour,
                actual_redispatch_timeseries=actual_redispatch_timeseries,
                weekly_metrics=weekly_metrics,
                validation_checks=validation_checks,
            )
    runtime_profile = _summarise_phase_c_runtime(
        profiler=profiler,
        preflight_runtime=preflight.runtime_profile,
        suite_runtime=suite_result.suite_runtime_profile,
        total_wall_seconds=perf_counter() - run_wall_started,
    )
    save_frame_csv(run_dir, "runtime_profile.csv", runtime_profile)
    runtime_profile.to_json(run_dir / "runtime_profile.json", orient="records", indent=2)

    hard_fail_count = int(
        validation_checks.loc[
            validation_checks["severity"].astype(str).eq("hard_fail")
            & validation_checks["status"].astype(str).eq("fail")
        ].shape[0]
    )
    if hard_fail_count > 0:
        raise RuntimeError(
            f"Phase C smoke run completed but hard validation checks failed ({hard_fail_count}); see {run_dir / 'validation_checks_all_runs.csv'}."
        )

    return PhaseCSmokeRunResult(
        run_dir=run_dir,
        selected_week=selected_week,
        support_days=support_days,
        suite_result=suite_result,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        benchmark_metrics=benchmark_metrics,
        validation_checks=validation_checks,
        actual_settlement_results=actual_settlement_results,
        scenario_settlement_results=scenario_settlement_results,
    )
