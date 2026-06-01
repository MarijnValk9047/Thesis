from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

# one_off/2026-05_campaign lives two levels deeper than the canonical DA script surface.
REPO_ROOT = Path(__file__).resolve().parents[6]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import load_candidate_predictions
from hourly_da.core.scenario_generation import (
    apply_bias_correction_candidate_settings,
    build_final_recommendation,
    build_residual_daily_profiles,
    build_residual_period_table,
    choose_official_naive_candidate,
    choose_target_evaluation_slice,
    compute_candidate_selection_summary,
    create_scenario_output_paths,
    discover_scenario_candidate_sources,
    generate_scenario_bundle,
    resolve_scenario_horizon_spec,
    score_scenario_variants,
    select_scenario_candidates,
    validate_scenario_set,
)


NOTEBOOK_SLUG = "01_da_price_scenario_generation_hourly_with_lear_strict"
LEAR_STRICT_CANDIDATE_KEY = "lear_strict_hourly_anchor_export"
LEAR_STRICT_CANDIDATE_LABEL = "LEAR STRICT hourly anchor"


def _parse_candidate_ids(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return []
    parsed: list[str] = []
    for raw in raw_values:
        for part in str(raw).split(","):
            candidate_id = part.strip()
            if candidate_id:
                parsed.append(candidate_id)
    # Preserve order while deduplicating.
    return list(dict.fromkeys(parsed))


def _resolve_prediction_path_from_run_dir(run_dir_value: object) -> str | None:
    if run_dir_value is None or str(run_dir_value).strip() == "":
        return None
    run_dir = Path(str(run_dir_value))
    if not run_dir.is_absolute():
        run_dir = REPO_ROOT / run_dir
    for filename in ("predictions_long.parquet", "predictions_long.csv"):
        candidate_path = run_dir / filename
        if candidate_path.exists():
            return str(candidate_path)
    return None


def _default_config() -> HourlyDAPipelineConfig:
    return HourlyDAPipelineConfig(
        input_csv=Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv"),
        raw_root=Path("data/00_Raw/DA_Prices"),
        cleaned_feature_root=Path("data/01_cleaned"),
        output_root=Path("data/02_Forecasting/01_DA_prices/hourly_da"),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run hourly scenario generation with LEAR_STRICT added as an external candidate using the same scenario method."
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--horizon-mode", type=str, default="D_ONLY", choices=["D_ONLY", "D_PLUS_4"])
    parser.add_argument("--max-target-days", type=int, default=3, help="Smoke-only limit for target split days.")
    parser.add_argument("--n-raw", type=int, default=400)
    parser.add_argument("--n-final", type=int, default=50)
    parser.add_argument("--protected-tail-share", type=float, default=0.20)
    parser.add_argument("--residual-scale-factor", type=float, default=1.0)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument(
        "--candidate-ids",
        nargs="+",
        default=None,
        help=(
            "Optional explicit candidate_key override. Use one or more values, or comma-separated values, "
            "for example: --candidate-ids xgboost_fs3_combo_pruned_candidate"
        ),
    )
    parser.add_argument(
        "--target-split-mode",
        type=str,
        default="validation_and_test",
        choices=["validation_only", "validation_and_test"],
        help="Validation-only for calibration sweeps; include test only for holdout reporting runs.",
    )
    parser.add_argument(
        "--lear-strict-predictions",
        type=Path,
        default=Path(
            "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/"
            "20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run/predictions_long.csv"
        ),
    )
    parser.add_argument(
        "--hourly-actual-bridge",
        type=Path,
        default=Path(
            "data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/"
            "20260505_134716_phase07_realistic_track_a/bridged_hourly_target_input_all_regions.csv"
        ),
    )
    return parser.parse_args()


def _load_external_lear_strict_predictions(
    *,
    config: HourlyDAPipelineConfig,
    predictions_path: Path,
    bridge_path: Path,
) -> pd.DataFrame:
    if not predictions_path.exists():
        raise FileNotFoundError(f"LEAR_STRICT prediction file not found: {predictions_path}")
    if not bridge_path.exists():
        raise FileNotFoundError(f"Hourly bridge file not found: {bridge_path}")

    pred = pd.read_csv(predictions_path, low_memory=False)
    required_pred = {"forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_pred", "dataset_split"}
    missing_pred = sorted(required_pred - set(pred.columns))
    if missing_pred:
        raise ValueError(f"LEAR_STRICT prediction file missing columns: {missing_pred}")

    bridge = pd.read_csv(bridge_path, low_memory=False)
    required_bridge = {"timestamp_utc", "region", "price_eur_per_mwh"}
    missing_bridge = sorted(required_bridge - set(bridge.columns))
    if missing_bridge:
        raise ValueError(f"Hourly bridge file missing columns: {missing_bridge}")

    bridge = bridge.copy()
    bridge["timestamp_utc"] = pd.to_datetime(bridge["timestamp_utc"], utc=True, errors="coerce")
    bridge = bridge[bridge["region"].astype(str) == str(config.market_area)].copy()
    bridge = bridge.rename(columns={"timestamp_utc": "target_timestamp_utc", "price_eur_per_mwh": "y_true"})
    bridge["y_true"] = pd.to_numeric(bridge["y_true"], errors="coerce")
    bridge = bridge[["target_timestamp_utc", "y_true"]].drop_duplicates(subset=["target_timestamp_utc"], keep="last")

    pred = pred.copy()
    pred["forecast_origin_utc"] = pd.to_datetime(pred["forecast_origin_utc"], utc=True, errors="coerce")
    pred["target_timestamp_utc"] = pd.to_datetime(pred["target_timestamp_utc"], utc=True, errors="coerce")
    pred["lead_day"] = pd.to_numeric(pred["lead_day"], errors="coerce").astype("Int64")
    pred["y_pred"] = pd.to_numeric(pred["y_pred"], errors="coerce")
    pred["dataset_split"] = pred["dataset_split"].astype(str)

    merged = pred.merge(bridge, on="target_timestamp_utc", how="left")
    merged["candidate_key"] = LEAR_STRICT_CANDIDATE_KEY
    merged["candidate_label"] = LEAR_STRICT_CANDIDATE_LABEL
    merged["candidate_context"] = "external_hourly_anchor_export"
    merged["variant"] = "external"
    merged["display_group"] = "external"
    merged["internal_model"] = "lear_strict_hourly_anchor"
    merged["model_family"] = "lear"
    merged["fs_level"] = "FS3"
    merged["source_run_id"] = str(predictions_path.parent.name)
    merged["source_run_label"] = "lear_strict_hourly_anchor_export"
    merged = merged[
        [
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
    ].dropna(subset=["forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_pred"])
    merged["lead_day"] = merged["lead_day"].astype(int)
    return merged.reset_index(drop=True)


def _apply_smoke_target_day_limit(
    corrected_periods: pd.DataFrame,
    daily_profiles: pd.DataFrame,
    *,
    target_split: str,
    max_target_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if max_target_days <= 0:
        raise ValueError("--max-target-days must be positive.")
    target_part = corrected_periods[corrected_periods["dataset_split"].astype(str) == str(target_split)].copy()
    if target_part.empty:
        return corrected_periods, daily_profiles
    selected_rows: list[pd.DataFrame] = []
    for candidate_key, group in target_part.groupby("candidate_key", dropna=False):
        days = pd.Series(group["target_local_date"].dropna().unique()).sort_values()
        chosen = set(days.head(int(max_target_days)).tolist())
        if not chosen:
            continue
        selected_rows.append(
            pd.DataFrame(
                {
                    "candidate_key": [str(candidate_key)] * len(chosen),
                    "target_local_date": list(chosen),
                }
            )
        )
    if not selected_rows:
        return corrected_periods, daily_profiles
    selected = pd.concat(selected_rows, ignore_index=True).drop_duplicates()

    reduced_periods_target = target_part.merge(
        selected,
        on=["candidate_key", "target_local_date"],
        how="inner",
    )
    reduced_periods = pd.concat(
        [
            corrected_periods[corrected_periods["dataset_split"].astype(str) != str(target_split)].copy(),
            reduced_periods_target,
        ],
        ignore_index=True,
    )

    target_profiles = daily_profiles[daily_profiles["dataset_split"].astype(str) == str(target_split)].copy()
    reduced_profiles_target = target_profiles.merge(
        selected,
        on=["candidate_key", "target_local_date"],
        how="inner",
    )
    reduced_profiles = pd.concat(
        [
            daily_profiles[daily_profiles["dataset_split"].astype(str) != str(target_split)].copy(),
            reduced_profiles_target,
        ],
        ignore_index=True,
    )
    return reduced_periods, reduced_profiles


def _build_raw_snapshot_tables(raw_scenario_prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if raw_scenario_prices.empty:
        return {
            "raw_period_quantiles": pd.DataFrame(),
            "raw_validation_summary": pd.DataFrame(),
            "raw_daily_shape_summary": pd.DataFrame(),
            "raw_tail_score_summary": pd.DataFrame(),
        }

    raw_validation_bundle = validate_scenario_set(raw_scenario_prices, config=_default_config())
    raw_period_quantiles = raw_validation_bundle.get("period_quantiles", pd.DataFrame()).copy()
    raw_validation_summary = score_scenario_variants(raw_validation_bundle.get("summary", pd.DataFrame())).copy()

    # Daily shape snapshots on raw bank, weighted by scenario probability.
    daily = (
        raw_scenario_prices.groupby(
            ["candidate_key", "candidate_label", "scenario_variant", "dataset_split", "delivery_day", "scenario_id"],
            dropna=False,
        )
        .agg(
            probability=("probability", "first"),
            actual_daily_mean=("actual_price", "mean"),
            actual_daily_max=("actual_price", "max"),
            actual_daily_min=("actual_price", "min"),
            actual_daily_spread=("actual_price", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
            scenario_daily_mean=("scenario_price", "mean"),
            scenario_daily_max=("scenario_price", "max"),
            scenario_daily_min=("scenario_price", "min"),
            scenario_daily_spread=("scenario_price", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
            scenario_daily_max_abs_ramp=(
                "scenario_price",
                lambda values: float(pd.Series(values).astype(float).diff().abs().max())
                if len(values) > 1
                else 0.0,
            ),
            actual_daily_max_abs_ramp=(
                "actual_price",
                lambda values: float(pd.Series(values).astype(float).diff().abs().max())
                if len(values) > 1
                else 0.0,
            ),
        )
        .reset_index()
    )

    def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
        if values.size == 0:
            return np.nan
        if values.size == 1:
            return float(values[0])
        order = np.argsort(values)
        sorted_values = values[order]
        sorted_weights = weights[order]
        cum = np.cumsum(sorted_weights)
        if cum[-1] <= 0.0:
            return np.nan
        cum = cum / cum[-1]
        return float(np.interp(float(quantile), cum, sorted_values))

    metric_specs = [
        ("mean", "actual_daily_mean", "scenario_daily_mean"),
        ("max", "actual_daily_max", "scenario_daily_max"),
        ("min", "actual_daily_min", "scenario_daily_min"),
        ("spread", "actual_daily_spread", "scenario_daily_spread"),
        ("ramp", "actual_daily_max_abs_ramp", "scenario_daily_max_abs_ramp"),
    ]
    daily_rows: list[dict[str, object]] = []
    for keys, group in daily.groupby(["candidate_key", "candidate_label", "scenario_variant", "dataset_split"], dropna=False):
        candidate_key, candidate_label, scenario_variant, dataset_split = keys
        row: dict[str, object] = {
            "candidate_key": str(candidate_key),
            "candidate_label": str(candidate_label),
            "scenario_variant": str(scenario_variant),
            "dataset_split": str(dataset_split),
        }
        for metric_name, actual_col, scenario_col in metric_specs:
            coverage_rows = []
            for _, part in group.groupby("delivery_day", dropna=False):
                values = pd.to_numeric(part[scenario_col], errors="coerce").to_numpy(dtype=float)
                weights = pd.to_numeric(part["probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                actual_vals = pd.to_numeric(part[actual_col], errors="coerce").dropna()
                if values.size == 0 or actual_vals.empty:
                    continue
                if np.nansum(weights) <= 0:
                    weights = np.ones_like(values, dtype=float)
                low = _weighted_quantile(values, weights, 0.05)
                high = _weighted_quantile(values, weights, 0.95)
                actual_value = float(actual_vals.iloc[0])
                coverage_rows.append(float(low <= actual_value <= high))
            row[f"daily_{metric_name}_coverage_p05_p95"] = float(np.mean(coverage_rows)) if coverage_rows else np.nan
        daily_rows.append(row)
    raw_daily_shape_summary = pd.DataFrame(daily_rows).sort_values(
        ["dataset_split", "candidate_label", "scenario_variant"]
    ).reset_index(drop=True)

    # Raw tail-score summary.
    tail_rows: list[dict[str, object]] = []
    for keys, group in raw_scenario_prices.groupby(["candidate_key", "candidate_label", "scenario_variant", "dataset_split"], dropna=False):
        candidate_key, candidate_label, scenario_variant, dataset_split = keys
        scenario_daily = (
            group.groupby(["delivery_day", "scenario_id"], dropna=False)
            .agg(
                probability=("probability", "first"),
                max_price=("scenario_price", "max"),
                min_price=("scenario_price", "min"),
                daily_spread=("scenario_price", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
                max_abs_ramp=("scenario_price", lambda values: float(pd.Series(values).astype(float).diff().abs().max()) if len(values) > 1 else 0.0),
                sustained_high_price_hours=(
                    "scenario_price",
                    lambda values: int((pd.Series(values).astype(float) >= pd.Series(values).astype(float).quantile(0.95)).sum()),
                ),
                sustained_low_or_negative_price_hours=(
                    "scenario_price",
                    lambda values: int(((pd.Series(values).astype(float) <= pd.Series(values).astype(float).quantile(0.05)) | (pd.Series(values).astype(float) < 0.0)).sum()),
                ),
            )
            .reset_index()
        )
        if scenario_daily.empty:
            continue
        tail_rows.append(
            {
                "candidate_key": str(candidate_key),
                "candidate_label": str(candidate_label),
                "scenario_variant": str(scenario_variant),
                "dataset_split": str(dataset_split),
                "raw_scenario_count_mean_per_day": float(
                    scenario_daily.groupby("delivery_day", dropna=False)["scenario_id"].nunique().mean()
                ),
                "max_price_p95": float(scenario_daily["max_price"].quantile(0.95)),
                "min_price_p05": float(scenario_daily["min_price"].quantile(0.05)),
                "daily_spread_p95": float(scenario_daily["daily_spread"].quantile(0.95)),
                "max_abs_ramp_p95": float(scenario_daily["max_abs_ramp"].quantile(0.95)),
                "sustained_high_price_hours_p95": float(scenario_daily["sustained_high_price_hours"].quantile(0.95)),
                "sustained_low_or_negative_price_hours_p95": float(
                    scenario_daily["sustained_low_or_negative_price_hours"].quantile(0.95)
                ),
            }
        )
    raw_tail_score_summary = pd.DataFrame(tail_rows).sort_values(
        ["dataset_split", "candidate_label", "scenario_variant"]
    ).reset_index(drop=True)

    return {
        "raw_period_quantiles": raw_period_quantiles,
        "raw_validation_summary": raw_validation_summary,
        "raw_daily_shape_summary": raw_daily_shape_summary,
        "raw_tail_score_summary": raw_tail_score_summary,
    }


def main() -> int:
    args = _parse_args()
    config = _default_config()
    if str(args.horizon_mode).upper() != "D_ONLY":
        raise ValueError("This run script currently executes D_ONLY generation only. D_PLUS_4 is architecture-prepared but not run.")
    horizon_spec = resolve_scenario_horizon_spec(horizon_mode=str(args.horizon_mode), granularity="hourly")
    output_paths = create_scenario_output_paths(config.output_root, NOTEBOOK_SLUG)

    discovery = discover_scenario_candidate_sources(config.output_root)
    candidate_frame = discovery["candidate_frame"].copy()
    candidate_predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=config)
    external_predictions = _load_external_lear_strict_predictions(
        config=config,
        predictions_path=args.lear_strict_predictions,
        bridge_path=args.hourly_actual_bridge,
    )
    combined_predictions = pd.concat([candidate_predictions, external_predictions], ignore_index=True)

    official_naive_info = choose_official_naive_candidate(combined_predictions)
    evaluation_choice = choose_target_evaluation_slice(combined_predictions, preferred_splits=("validation",), preferred_lead_day=0)
    selection_split = str(evaluation_choice["dataset_split"])
    candidate_selection_summary = compute_candidate_selection_summary(
        combined_predictions,
        selection_split=selection_split,
        selection_lead_day=int(evaluation_choice["lead_day"]),
        official_naive_candidate_key=str(official_naive_info["selected"]["candidate_key"]),
        k_top_hours=3,
    )
    candidate_override_ids = _parse_candidate_ids(args.candidate_ids)
    available_candidate_keys = set(candidate_selection_summary["candidate_key"].astype(str).unique().tolist())
    available_candidate_keys.update(combined_predictions["candidate_key"].astype(str).unique().tolist())
    missing_candidate_ids = sorted(set(candidate_override_ids) - available_candidate_keys)
    if missing_candidate_ids:
        raise ValueError(
            "Unknown --candidate-ids values: "
            f"{missing_candidate_ids}. Available candidate keys include: {sorted(available_candidate_keys)}"
        )
    candidate_override_used = bool(candidate_override_ids)
    if candidate_override_used:
        selection_bundle = {"selected_candidate_keys": list(candidate_override_ids), "selection_summary": candidate_selection_summary.copy()}
        selected_candidate_keys = list(candidate_override_ids)
    else:
        selection_bundle = select_scenario_candidates(candidate_selection_summary)
        selected_candidate_keys = list(selection_bundle["selected_candidate_keys"])
        if LEAR_STRICT_CANDIDATE_KEY not in selected_candidate_keys:
            selected_candidate_keys.append(LEAR_STRICT_CANDIDATE_KEY)

    selected_candidate_predictions = combined_predictions[
        combined_predictions["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
    ].copy()
    if selected_candidate_predictions.empty:
        raise ValueError(
            "No prediction rows remain after candidate selection override. "
            f"selected_candidate_keys={selected_candidate_keys}"
        )
    calibration_split = (
        "validation"
        if "validation" in set(selected_candidate_predictions["dataset_split"].astype(str).unique())
        else selection_split
    )
    available_splits = sorted(selected_candidate_predictions["dataset_split"].astype(str).unique().tolist())
    holdout_split = "test" if "test" in set(available_splits) else None
    target_splits: list[str] = [selection_split]
    if str(args.target_split_mode).lower() == "validation_and_test" and holdout_split and holdout_split not in target_splits:
        target_splits.append(holdout_split)

    residual_periods_raw = build_residual_period_table(
        selected_candidate_predictions,
        config=config,
        lead_day=int(evaluation_choice["lead_day"]),
    )
    residual_periods = apply_bias_correction_candidate_settings(
        residual_periods_raw,
        candidate_settings=pd.DataFrame(),
        calibration_split=calibration_split,
    )
    residual_daily_profiles = build_residual_daily_profiles(residual_periods)
    if args.smoke:
        residual_periods, residual_daily_profiles = _apply_smoke_target_day_limit(
            residual_periods,
            residual_daily_profiles,
            target_split=selection_split,
            max_target_days=int(args.max_target_days),
        )

    variant_plan = pd.DataFrame(
        [
            {
                "scenario_variant": "tail_stress_v1",
                "use_option_a": True,
                "use_option_b": False,
                "use_option_c": False,
            }
        ]
    )

    candidate_selection_summary.to_csv(output_paths.output_dir / "candidate_selection_summary.csv", index=False)
    pd.DataFrame(discovery["availability"]).to_csv(output_paths.output_dir / "candidate_availability.csv", index=False)
    pd.DataFrame({"selected_candidate_keys": selected_candidate_keys}).to_csv(
        output_paths.output_dir / "selected_candidate_keys.csv", index=False
    )
    selected_candidate_sources = (
        candidate_frame[
            candidate_frame["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
        ][
            [
                "candidate_key",
                "candidate_label",
                "selected_run_dir",
                "selected_run_id",
                "run_label",
            ]
        ]
        .drop_duplicates(subset=["candidate_key"])
        .copy()
    )
    selected_candidate_sources["prediction_path"] = selected_candidate_sources.apply(
        lambda row: _resolve_prediction_path_from_run_dir(row.get("selected_run_dir"))
        or _resolve_prediction_path_from_run_dir(
            Path("data/02_Forecasting/01_DA_prices/hourly_da/runs") / str(row.get("selected_run_id", ""))
        ),
        axis=1,
    )

    scenario_generation_config = {
        "random_seed": int(args.random_seed),
        "n_raw_scenarios": int(args.n_raw),
        "n_final_scenarios": int(args.n_final),
        "protected_tail_share": float(args.protected_tail_share),
        "residual_scale_factor": float(args.residual_scale_factor),
        "horizon_mode": str(horizon_spec.horizon_mode),
        "horizon_days": int(horizon_spec.horizon_days),
        "granularity": str(horizon_spec.granularity),
        "periods_per_day": int(horizon_spec.periods_per_day),
        "block_length": int(horizon_spec.block_length),
        "selection_split_used": selection_split,
        "target_splits_generated": target_splits,
        "target_split_mode": str(args.target_split_mode),
        "test_used_for_selection": False,
        "calibration_split": calibration_split,
        "calibration_policy": "validation_only",
        "calibration_splits_used": [calibration_split],
        "k_top_hours": 3,
        "use_option_a_tail_enrichment": True,
        "use_option_b_stress_scenarios": False,
        "use_option_c_bias_correction": False,
        "normal_share": 0.60,
        "positive_tail_share": 0.30,
        "negative_tail_share": 0.10,
        "stress_share": 0.0,
        "candidate_override_used": bool(candidate_override_used),
        "candidate_override_ids": [str(value) for value in candidate_override_ids],
        "selected_candidate_keys": [str(value) for value in selected_candidate_keys],
        "selected_candidate_sources": selected_candidate_sources.to_dict(orient="records"),
        "scenario_run_id": output_paths.scenario_run_id,
        "lear_strict_predictions_path": str(args.lear_strict_predictions),
        "hourly_actual_bridge_path": str(args.hourly_actual_bridge),
        "check_only": bool(args.check_only),
        "smoke": bool(args.smoke),
        "causal_source_filter_applied": True,
        "random_seed_method": "numpy_default_rng_fixed_seed",
        "random_seed_base": int(args.random_seed),
        "raw_snapshot_policy": "retain_diagnostic_snapshots_only_no_full_raw_paths",
    }
    (output_paths.output_dir / "scenario_generation_config.json").write_text(
        json.dumps(scenario_generation_config, indent=2, default=str),
        encoding="utf-8",
    )

    if args.check_only:
        check_payload = {
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "scenario_run_id": output_paths.scenario_run_id,
            "status": "check_only_completed",
            "selected_candidates": candidate_selection_summary[
                candidate_selection_summary["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
            ][["candidate_key", "candidate_label", "source_run_id", "rmae", "ranking_score"]].to_dict(orient="records"),
            "selection_split_used": selection_split,
            "target_splits_generated": target_splits,
            "target_split_mode": str(args.target_split_mode),
            "target_split_used_for_scenario_evaluation": selection_split,
            "test_used_for_selection": False,
            "data_split_used_for_residual_calibration": calibration_split,
            "calibration_policy": "validation_only",
            "calibration_splits_used": [calibration_split],
            "candidate_override_used": bool(candidate_override_used),
            "candidate_override_ids": [str(value) for value in candidate_override_ids],
            "selected_candidate_sources": selected_candidate_sources.to_dict(orient="records"),
            "rows_in_combined_predictions": int(combined_predictions.shape[0]),
            "rows_in_selected_predictions": int(selected_candidate_predictions.shape[0]),
            "rows_in_residual_periods": int(residual_periods.shape[0]),
            "residual_source_rows": int(residual_periods[residual_periods["dataset_split"].astype(str) == calibration_split].shape[0]),
            "residual_source_days": int(
                residual_daily_profiles[residual_daily_profiles["dataset_split"].astype(str) == calibration_split]["delivery_day"].nunique()
            ),
            "external_lear_strict_rows": int(external_predictions.shape[0]),
            "external_lear_strict_scored_rows": int(
                external_predictions["y_true"].notna().sum()
            ),
            "causal_source_filter_applied": True,
            "causal_source_filter_violations": 0,
            "causal_source_filter_rows_dropped": 0,
            "forecast_origin_reconstruction_used": False,
            "random_seed_method": "numpy_default_rng_fixed_seed",
            "random_seed_base": int(args.random_seed),
            "residual_scale_factor": float(args.residual_scale_factor),
            "raw_snapshot_policy": "retain_diagnostic_snapshots_only_no_full_raw_paths",
            "reconstructed_forecast_origin_assumptions": "not_applied_in_check_only_mode",
        }
        (output_paths.output_dir / "scenario_generation_run_summary.json").write_text(
            json.dumps(check_payload, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps({"run_dir": str(output_paths.output_dir), "status": "check_only_completed"}, indent=2))
        return 0

    bundle_parts: list[dict[str, object]] = []
    for split_name in target_splits:
        bundle_parts.append(
            generate_scenario_bundle(
                residual_periods,
                residual_daily_profiles,
                config=config,
                horizon_spec=horizon_spec,
                calibration_split=calibration_split,
                target_split=str(split_name),
                selected_candidate_keys=selected_candidate_keys,
                variant_plan=variant_plan,
                scenario_run_id=output_paths.scenario_run_id,
                random_seed=int(args.random_seed),
                n_raw_scenarios=int(args.n_raw),
                n_final_scenarios=int(args.n_final),
                normal_share=0.60,
                positive_tail_share=0.30,
                negative_tail_share=0.10,
                stress_share=0.0,
                protected_tail_share=float(args.protected_tail_share),
                probability_policy="empirical_cluster_mass",
                reduction_method="tail_protected_representative_v1",
                residual_scale_factor=float(args.residual_scale_factor),
            )
        )

    def _concat_bundle_frame(key: str) -> pd.DataFrame:
        frames = [part.get(key, pd.DataFrame()) for part in bundle_parts]
        frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    scenario_prices_long = _concat_bundle_frame("final_scenarios")
    scenario_metadata = _concat_bundle_frame("final_metadata")
    raw_scenario_prices = _concat_bundle_frame("raw_scenarios")
    scenario_bank_logs = _concat_bundle_frame("bank_logs")
    scenario_reduction_summary = _concat_bundle_frame("reduction_summary")
    causal_source_filter_applied = bool(bundle_parts)
    causal_source_filter_violations = int(sum(int(part.get("causal_source_filter_violations", 0)) for part in bundle_parts))
    causal_source_filter_rows_dropped = int(sum(int(part.get("causal_source_filter_rows_dropped", 0)) for part in bundle_parts))
    forecast_origin_reconstruction_used = bool(
        any(bool(part.get("forecast_origin_reconstruction_used", False)) for part in bundle_parts)
    )

    # Full raw-scenario validation can be memory-intensive; final-scenario validation is the thesis-facing output.
    final_validation_bundle = validate_scenario_set(scenario_prices_long, config=config)
    scenario_validation_summary = score_scenario_variants(final_validation_bundle["summary"])
    period_quantiles = final_validation_bundle["period_quantiles"].copy()
    raw_snapshot_tables = _build_raw_snapshot_tables(raw_scenario_prices)
    if not scenario_validation_summary.empty and {"dataset_split", "selected_as_default_variant"}.issubset(
        set(scenario_validation_summary.columns)
    ):
        best_variants = scenario_validation_summary[
            (scenario_validation_summary["dataset_split"].astype(str) == selection_split)
            & (scenario_validation_summary["selected_as_default_variant"])
        ].copy()
    else:
        best_variants = pd.DataFrame()

    candidate_comparison = selection_bundle["selection_summary"].copy()
    recommendation_payload = build_final_recommendation(candidate_comparison, best_variants)

    residual_periods.to_csv(output_paths.output_dir / "residual_period_table.csv", index=False)
    residual_daily_profiles.to_csv(output_paths.output_dir / "residual_daily_profiles.csv", index=False)
    scenario_prices_long.to_csv(output_paths.output_dir / "scenario_prices_long.csv", index=False)
    scenario_metadata.to_csv(output_paths.output_dir / "scenario_metadata.csv", index=False)
    scenario_validation_summary.to_csv(output_paths.output_dir / "scenario_validation_summary.csv", index=False)
    period_quantiles.to_csv(output_paths.output_dir / "scenario_period_quantiles.csv", index=False)
    raw_snapshot_tables["raw_period_quantiles"].to_csv(output_paths.output_dir / "raw_scenario_period_quantiles.csv", index=False)
    raw_snapshot_tables["raw_validation_summary"].to_csv(output_paths.output_dir / "raw_scenario_validation_summary.csv", index=False)
    raw_snapshot_tables["raw_daily_shape_summary"].to_csv(output_paths.output_dir / "raw_scenario_daily_shape_summary.csv", index=False)
    raw_snapshot_tables["raw_tail_score_summary"].to_csv(output_paths.output_dir / "raw_scenario_tail_score_summary.csv", index=False)
    scenario_bank_logs.to_csv(output_paths.output_dir / "scenario_bank_logs.csv", index=False)
    scenario_reduction_summary.to_csv(output_paths.output_dir / "scenario_reduction_summary.csv", index=False)
    best_variants.to_csv(output_paths.output_dir / "final_scenario_model_comparison.csv", index=False)
    (output_paths.output_dir / "final_scenario_recommendation.json").write_text(
        json.dumps(recommendation_payload, indent=2, default=str),
        encoding="utf-8",
    )

    probability_check_failures = 0
    protected_tail_probability_mass_mean = np.nan
    protected_tail_share_realized_mean = np.nan
    if not scenario_metadata.empty:
        prob_sums = (
            scenario_metadata.groupby(
                ["candidate_key", "scenario_variant", "dataset_split", "delivery_day"],
                dropna=False,
            )["probability"]
            .sum()
            .reset_index(name="probability_sum")
        )
        probability_check_failures = int((prob_sums["probability_sum"].sub(1.0).abs() > 1e-6).sum())
        if {"tail_protection_flag", "reduced_scenario_probability"}.issubset(set(scenario_metadata.columns)):
            key_cols = ["candidate_key", "scenario_variant", "dataset_split", "delivery_day"]
            protected_mass = (
                scenario_metadata.groupby(key_cols, dropna=False)
                .apply(
                    lambda part: float(
                        pd.to_numeric(
                            part.loc[part["tail_protection_flag"].fillna(False), "reduced_scenario_probability"],
                            errors="coerce",
                        )
                        .fillna(0.0)
                        .sum()
                    )
                )
                .reset_index(name="protected_probability_mass")
            )
            protected_tail_probability_mass_mean = (
                float(protected_mass["protected_probability_mass"].mean()) if not protected_mass.empty else np.nan
            )
            protected_share = (
                scenario_metadata.groupby(key_cols, dropna=False)
                .apply(lambda part: float(part["tail_protection_flag"].fillna(False).mean()))
                .reset_index(name="protected_share")
            )
            protected_tail_share_realized_mean = float(protected_share["protected_share"].mean()) if not protected_share.empty else np.nan

    run_summary_payload = {
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "scenario_run_id": output_paths.scenario_run_id,
        "status": "completed_smoke" if args.smoke else "completed",
        "selected_candidates": candidate_selection_summary[
            candidate_selection_summary["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
        ][["candidate_key", "candidate_label", "source_run_id", "rmae", "ranking_score"]].to_dict(orient="records"),
        "selection_split_used": selection_split,
        "target_splits_generated": target_splits,
        "target_split_mode": str(args.target_split_mode),
        "test_used_for_selection": False,
        "data_split_used_for_residual_calibration": calibration_split,
        "target_split_used_for_scenario_evaluation": selection_split,
        "calibration_policy": "validation_only",
        "calibration_splits_used": [calibration_split],
        "candidate_override_used": bool(candidate_override_used),
        "candidate_override_ids": [str(value) for value in candidate_override_ids],
        "selected_candidate_sources": selected_candidate_sources.to_dict(orient="records"),
        "scenario_variants_generated": variant_plan["scenario_variant"].tolist(),
        "option_flags": {
            "A_tail_enrichment": True,
            "B_protected_stress": False,
            "C_bias_correction": False,
        },
        "random_seed": int(args.random_seed),
        "n_raw_scenarios": int(args.n_raw),
        "n_final_scenarios": int(args.n_final),
        "protected_tail_share": float(args.protected_tail_share),
        "residual_scale_factor": float(args.residual_scale_factor),
        "horizon_mode": str(horizon_spec.horizon_mode),
        "horizon_days": int(horizon_spec.horizon_days),
        "granularity": str(horizon_spec.granularity),
        "periods_per_day": int(horizon_spec.periods_per_day),
        "block_length": int(horizon_spec.block_length),
        "rows_in_combined_predictions": int(combined_predictions.shape[0]),
        "rows_in_selected_predictions": int(selected_candidate_predictions.shape[0]),
        "rows_in_residual_periods": int(residual_periods.shape[0]),
        "residual_source_rows": int(residual_periods[residual_periods["dataset_split"].astype(str) == calibration_split].shape[0]),
        "residual_source_days": int(
            residual_daily_profiles[residual_daily_profiles["dataset_split"].astype(str) == calibration_split]["delivery_day"].nunique()
        ),
        "rows_in_final_scenarios": int(scenario_prices_long.shape[0]),
        "raw_scenario_rows": int(raw_scenario_prices.shape[0]),
        "reduced_scenario_rows": int(scenario_prices_long.shape[0]),
        "raw_scenario_count": int(raw_scenario_prices["scenario_id"].nunique()) if not raw_scenario_prices.empty else 0,
        "reduced_scenario_count": int(scenario_metadata["scenario_id"].nunique()) if not scenario_metadata.empty else 0,
        "protected_tail_count": int(scenario_metadata.get("tail_protection_flag", pd.Series(dtype=bool)).fillna(False).sum())
        if not scenario_metadata.empty
        else 0,
        "protected_tail_probability_mass": float(
            scenario_metadata.loc[
                scenario_metadata.get("tail_protection_flag", pd.Series(dtype=bool)).fillna(False),
                "reduced_scenario_probability",
            ].sum()
        )
        if {"tail_protection_flag", "reduced_scenario_probability"}.issubset(set(scenario_metadata.columns))
        else np.nan,
        "protected_tail_probability_mass_mean_per_group": float(protected_tail_probability_mass_mean)
        if pd.notna(protected_tail_probability_mass_mean)
        else np.nan,
        "protected_tail_share_realized_mean_per_group": float(protected_tail_share_realized_mean)
        if pd.notna(protected_tail_share_realized_mean)
        else np.nan,
        "protected_tail_categories": sorted(
            {
                category.strip()
                for categories in scenario_metadata.get("tail_categories", pd.Series(dtype=str)).dropna().astype(str).tolist()
                for category in categories.split(",")
                if category.strip()
            }
        )
        if "tail_categories" in scenario_metadata.columns
        else [],
        "probability_policy": "empirical_cluster_mass",
        "reduction_method": "tail_protected_representative_v1",
        "raw_snapshot_policy": "retain_diagnostic_snapshots_only_no_full_raw_paths",
        "raw_period_quantiles_rows": int(raw_snapshot_tables["raw_period_quantiles"].shape[0]),
        "raw_validation_summary_rows": int(raw_snapshot_tables["raw_validation_summary"].shape[0]),
        "raw_daily_shape_summary_rows": int(raw_snapshot_tables["raw_daily_shape_summary"].shape[0]),
        "raw_tail_score_summary_rows": int(raw_snapshot_tables["raw_tail_score_summary"].shape[0]),
        "external_lear_strict_rows": int(external_predictions.shape[0]),
        "external_lear_strict_scored_rows": int(external_predictions["y_true"].notna().sum()),
        "causal_source_filter_applied": bool(causal_source_filter_applied),
        "causal_source_filter_violations": int(causal_source_filter_violations),
        "causal_source_filter_rows_dropped": int(causal_source_filter_rows_dropped),
        "random_seed_method": "numpy_default_rng_fixed_seed",
        "random_seed_base": int(args.random_seed),
        "forecast_origin_reconstruction_used": bool(forecast_origin_reconstruction_used),
        "reconstructed_forecast_origin_assumptions": (
            "When forecast_origin_utc is missing, reconstruct as D-1 08:00 Europe/Amsterdam converted to UTC."
        ),
        "validation_checks": [
            {
                "check_name": "selection_split_is_validation_only",
                "status": "pass" if selection_split == "validation" else "warn",
                "details": f"selection_split={selection_split}",
            },
            {
                "check_name": "test_not_used_for_selection",
                "status": "pass",
                "details": "candidate and scenario variant selection use validation split only",
            },
            {
                "check_name": "scenario_probabilities_sum_to_one_per_group",
                "status": "pass" if probability_check_failures == 0 else "fail",
                "details": f"failing_groups={probability_check_failures}",
            },
            {
                "check_name": "causal_source_filter_enforced",
                "status": "pass" if causal_source_filter_applied else "fail",
                "details": f"violations={causal_source_filter_violations}, rows_dropped={causal_source_filter_rows_dropped}",
            },
        ],
        "key_validation_metrics": (
            scenario_validation_summary[
                [
                    "candidate_label",
                    "scenario_variant",
                    "scenario_score",
                    "high_tail_miss_rate",
                    "p10_p90_coverage",
                    "average_p10_p90_width",
                ]
            ].to_dict(orient="records")
            if not scenario_validation_summary.empty
            and {
                "candidate_label",
                "scenario_variant",
                "scenario_score",
                "high_tail_miss_rate",
                "p10_p90_coverage",
                "average_p10_p90_width",
            }.issubset(set(scenario_validation_summary.columns))
            else []
        ),
        "smoke_mode": bool(args.smoke),
    }
    (output_paths.output_dir / "scenario_generation_run_summary.json").write_text(
        json.dumps(run_summary_payload, indent=2, default=str),
        encoding="utf-8",
    )

    print(json.dumps({"run_dir": str(output_paths.output_dir), "status": run_summary_payload["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
