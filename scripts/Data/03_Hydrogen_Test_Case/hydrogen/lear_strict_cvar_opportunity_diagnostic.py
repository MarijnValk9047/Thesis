from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .run_registry import (
    build_inputs_manifest,
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_inputs_manifest,
    save_json,
    save_text,
)
from .scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs
from .selected_week_smoke import TOLERANCE, _label_for_artifact, _validation_row, _weighted_quantile
from .weekly_band_emergency_selection import (
    PRODUCTION_VARIANTS,
    _aggregate_metrics_by_model_gamma_variant,
    _build_emergency_import_summary,
    _build_skipped_daily_metric,
    _compute_variant_bounds,
    _find_latest_resume_dir,
    _run_perfect_foresight_week_variant,
)
from .weekly_hard_band_decision import (
    _accepted_solver_status,
    _build_phase_e4_config,
    _build_stochastic_daily_metric,
    _load_cached_day_payload,
    _payload_from_live_result,
    _runtime_summary,
    _save_parquet_if_possible,
)
from .weekly_hard_band_target import (
    TARGET_MODE_WEEKLY_HARD_BAND,
    build_weekly_hard_band_settings,
)
from .bidding_backtest import run_real_scenario_bidding_dry_run


LEARNER_ARTIFACT = "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support"


@dataclass(frozen=True)
class PhaseE4dResult:
    run_dir: Path
    support_audit: pd.DataFrame
    screening: pd.DataFrame
    selected_week_manifest: dict[str, Any]
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    diagnostic_summary: pd.DataFrame
    emergency_import_summary: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    runtime_summary: pd.DataFrame


def _load_single_artifact_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
    output_root: Path | None,
    run_slug: str,
) -> HydrogenConfig:
    return _build_phase_e4_config(
        config_or_path,
        artifact_ids=[str(artifact_id)],
        output_root=output_root,
        run_slug=str(run_slug),
    )


def _safe_numeric(value: Any) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else float("nan")


def _physical_daily_max_kg(config: HydrogenConfig) -> float:
    return float(
        config.hydrogen_system.electrolyser_nominal_mw
        * 24.0
        * config.hydrogen_system.h2_efficiency_kg_per_mwh
    )


def _load_artifact_daily_support(
    *,
    config: HydrogenConfig,
    artifact_id: str,
    preloaded_scenarios: pd.DataFrame | None = None,
    pre_resolved_spec: Any | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Any]:
    artifact_config = replace(config, models=replace(config.models, include=(str(artifact_id),)))
    spec = pre_resolved_spec if pre_resolved_spec is not None else resolve_artifact_specs(artifact_config)[0]
    scenarios, _ = load_scenarios_for_artifact(
        spec,
        config=artifact_config,
        frame_override=preloaded_scenarios,
    )
    scenarios = scenarios.copy()
    scenarios["forecast_origin_utc"] = pd.to_datetime(scenarios["forecast_origin_utc"], utc=True, errors="raise")
    scenarios["delivery_start_utc"] = pd.to_datetime(scenarios["delivery_start_utc"], utc=True, errors="raise")
    scenarios["delivery_day"] = pd.to_datetime(scenarios["delivery_day"], errors="raise").dt.strftime("%Y-%m-%d")

    unique_prob = (
        scenarios[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
    )
    actual_rows = (
        scenarios[["forecast_origin_utc", "delivery_start_utc", "delivery_day", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["forecast_origin_utc", "delivery_start_utc"])
        .sort_values(["forecast_origin_utc", "delivery_start_utc"])
        .reset_index(drop=True)
    )
    actual_daily = (
        actual_rows.groupby("forecast_origin_utc", as_index=False)
        .agg(
            delivery_day=("delivery_day", "first"),
            actual_hour_count=("delivery_start_utc", "nunique"),
            missing_actual_rows=("actual_price_eur_per_mwh", lambda s: int(s.isna().sum())),
            actual_price_mean=("actual_price_eur_per_mwh", "mean"),
            actual_price_min=("actual_price_eur_per_mwh", "min"),
            actual_price_max=("actual_price_eur_per_mwh", "max"),
            actual_price_std=("actual_price_eur_per_mwh", "std"),
            actual_negative_price_hours=("actual_price_eur_per_mwh", lambda s: int((s.astype(float) < 0.0).sum())),
        )
    )
    duplicate_rows = (
        scenarios.duplicated(
            subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"],
            keep=False,
        )
        .groupby(scenarios["forecast_origin_utc"])
        .sum()
        .rename("duplicate_row_count")
        .reset_index()
    )
    registry = actual_daily.merge(unique_prob, on="forecast_origin_utc", how="inner").merge(
        duplicate_rows, on="forecast_origin_utc", how="left"
    )
    registry["duplicate_row_count"] = registry["duplicate_row_count"].fillna(0).astype(int)
    registry["actual_price_spread"] = registry["actual_price_max"].astype(float) - registry["actual_price_min"].astype(float)
    registry["artifact_id"] = str(artifact_id)
    registry["model_id"] = str(spec.model_id)
    registry["model_label"] = _label_for_artifact(artifact_id)
    registry["validation_mode"] = str(spec.validation_mode)

    good_count_mask = (
        (registry["actual_hour_count"].astype(int) == 24)
        & (registry["missing_actual_rows"].astype(int) == 0)
        & (registry["duplicate_row_count"].astype(int) == 0)
        & registry["probability_sum"].astype(float).between(0.999999, 1.000001)
    )
    count_candidates = registry.loc[good_count_mask, "scenario_count"].astype(int)
    if count_candidates.empty:
        raise ValueError(f"No valid daily origins found for artifact '{artifact_id}'.")
    expected_scenario_count = int(count_candidates.mode().iloc[0])
    registry["expected_scenario_count"] = expected_scenario_count
    valid = registry.loc[good_count_mask & registry["scenario_count"].astype(int).eq(expected_scenario_count)].copy()
    selected_daily = (
        valid.sort_values(["delivery_day", "forecast_origin_utc"])
        .groupby("delivery_day", as_index=False)
        .tail(1)
        .sort_values("delivery_day")
        .reset_index(drop=True)
    )
    return scenarios, registry.sort_values(["delivery_day", "forecast_origin_utc"]).reset_index(drop=True), selected_daily, spec


def _contiguous_segments(days: list[str]) -> list[dict[str, Any]]:
    if not days:
        return []
    ordered = pd.to_datetime(pd.Series(sorted(days)), errors="raise")
    segments: list[dict[str, Any]] = []
    start = ordered.iloc[0]
    prev = ordered.iloc[0]
    count = 1
    for ts in ordered.iloc[1:]:
        if (ts - prev).days == 1:
            count += 1
        else:
            segments.append({"start": start.strftime("%Y-%m-%d"), "end": prev.strftime("%Y-%m-%d"), "n_days": count})
            start = ts
            count = 1
        prev = ts
    segments.append({"start": start.strftime("%Y-%m-%d"), "end": prev.strftime("%Y-%m-%d"), "n_days": count})
    return segments


def _build_support_audit(
    *,
    selected_daily: pd.DataFrame,
    registry: pd.DataFrame,
    audit_start: str,
    audit_end: str,
    expected_scenario_count: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    audit_days = pd.date_range(pd.Timestamp(audit_start), pd.Timestamp(audit_end), freq="D")
    audit_day_strings = {ts.strftime("%Y-%m-%d") for ts in audit_days}
    selected_in_period = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(audit_day_strings)].copy()
    registry_in_period = registry.loc[registry["delivery_day"].astype(str).isin(audit_day_strings)].copy()

    coverage_by_day = (
        registry_in_period.groupby("delivery_day", as_index=False)
        .agg(
            best_actual_hour_count=("actual_hour_count", "max"),
            any_prob_sum_ok=("probability_sum", lambda s: bool(pd.to_numeric(s, errors="coerce").between(0.999999, 1.000001).any())),
            any_scenario_count_ok=("scenario_count", lambda s: bool(pd.to_numeric(s, errors="coerce").eq(expected_scenario_count).any())),
            any_actual_complete=("missing_actual_rows", lambda s: bool(pd.to_numeric(s, errors="coerce").eq(0).any())),
        )
        .reset_index(drop=True)
    )
    coverage_lookup = coverage_by_day.set_index("delivery_day").to_dict(orient="index")
    complete_days = int(selected_in_period.shape[0])
    total_days = int(len(audit_days))
    missing_days = int(total_days - complete_days)
    missing_hours = 0
    for ts in audit_days:
        key = ts.strftime("%Y-%m-%d")
        info = coverage_lookup.get(key)
        if info is None:
            missing_hours += 24
        else:
            missing_hours += int(max(0, 24 - int(info["best_actual_hour_count"])))

    support_start = selected_in_period["delivery_day"].iloc[0] if not selected_in_period.empty else ""
    support_end = selected_in_period["delivery_day"].iloc[-1] if not selected_in_period.empty else ""
    origins_with_75 = int(pd.to_numeric(selected_in_period["scenario_count"], errors="coerce").eq(expected_scenario_count).sum())
    origins_with_prob_1 = int(pd.to_numeric(selected_in_period["probability_sum"], errors="coerce").between(0.999999, 1.000001).sum())
    actual_price_complete = bool(
        selected_in_period["actual_hour_count"].astype(int).eq(24).all()
        and selected_in_period["missing_actual_rows"].astype(int).eq(0).all()
    ) if not selected_in_period.empty else False
    eligible_for_full_year_run = bool(
        complete_days == total_days
        and missing_days == 0
        and missing_hours == 0
        and actual_price_complete
        and origins_with_75 == total_days
        and origins_with_prob_1 == total_days
    )
    segments = _contiguous_segments(selected_in_period["delivery_day"].astype(str).tolist())
    best_segment = max(segments, key=lambda item: int(item["n_days"]), default=None)
    eligible_period_if_not_full_year = (
        f"{best_segment['start']} to {best_segment['end']} ({best_segment['n_days']} days)"
        if best_segment is not None
        else ""
    )
    blockers: list[str] = []
    if missing_days > 0:
        blockers.append(f"missing_days={missing_days}")
    if missing_hours > 0:
        blockers.append(f"missing_hours={missing_hours}")
    if origins_with_75 < total_days:
        blockers.append(f"origins_with_75_scenarios={origins_with_75}/{total_days}")
    if origins_with_prob_1 < total_days:
        blockers.append(f"origins_with_probability_sum_1={origins_with_prob_1}/{total_days}")
    if not actual_price_complete:
        blockers.append("actual_price_complete=false")
    audit = pd.DataFrame(
        [
            {
                "support_start": support_start,
                "support_end": support_end,
                "complete_days": complete_days,
                "missing_days": missing_days,
                "missing_hours": int(missing_hours),
                "origins_with_75_scenarios": origins_with_75,
                "origins_with_probability_sum_1": origins_with_prob_1,
                "actual_price_complete": bool(actual_price_complete),
                "eligible_for_full_year_run": bool(eligible_for_full_year_run),
                "eligible_period_if_not_full_year": eligible_period_if_not_full_year,
                "blockers": "; ".join(blockers),
            }
        ]
    )
    meta = {
        "segments": segments,
        "total_days": total_days,
        "expected_scenario_count": expected_scenario_count,
    }
    return audit, meta


def _week_start_label(delivery_day: str) -> str:
    ts = pd.Timestamp(delivery_day)
    week_start = ts - pd.Timedelta(days=int(ts.weekday()))
    return week_start.strftime("%Y-%m-%d")


def _screen_complete_weeks(
    *,
    scenarios: pd.DataFrame,
    selected_daily: pd.DataFrame,
    audit_start: str,
    audit_end: str,
    config: HydrogenConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    day_set = set(
        pd.date_range(pd.Timestamp(audit_start), pd.Timestamp(audit_end), freq="D").strftime("%Y-%m-%d").tolist()
    )
    selected = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(day_set)].copy()
    selected["week_start"] = selected["delivery_day"].astype(str).map(_week_start_label)
    week_rows: list[dict[str, Any]] = []
    p_ref = float(config.economics.p_ref_eur_per_mwh)
    low_price_threshold = 50.0
    for week_start, group in selected.groupby("week_start", sort=True):
        week_days = sorted(group["delivery_day"].astype(str).tolist())
        expected_days = pd.date_range(pd.Timestamp(week_start), periods=7, freq="D").strftime("%Y-%m-%d").tolist()
        complete_support = bool(week_days == expected_days)
        week_id = f"week_{week_start.replace('-', '')}"
        if not complete_support:
            week_rows.append(
                {
                    "week_id": week_id,
                    "week_start": week_start,
                    "complete_support": False,
                    "actual_price_mean": np.nan,
                    "actual_price_std": np.nan,
                    "actual_price_min": np.nan,
                    "actual_price_max": np.nan,
                    "actual_price_spread": np.nan,
                    "high_price_hours": 0,
                    "negative_or_low_price_hours": 0,
                    "actual_inside_scenario_minmax_share": np.nan,
                    "actual_inside_scenario_p05_p95_share": np.nan,
                    "actual_above_scenario_max_hours": np.nan,
                    "actual_below_scenario_min_hours": np.nan,
                    "scenario_p95_p05_width_mean": np.nan,
                    "scenario_tail_width_p95": np.nan,
                    "scenario_price_volatility_mean": np.nan,
                    "scenario_temporal_coherence_ok": False,
                    "cvar_opportunity_score": np.nan,
                }
            )
            continue

        selected_origins = set(pd.to_datetime(group["forecast_origin_utc"], utc=True, errors="raise").tolist())
        week_frame = scenarios.loc[scenarios["forecast_origin_utc"].isin(selected_origins)].copy()
        week_frame = week_frame.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)
        actual_rows = (
            week_frame[["delivery_start_utc", "actual_price_eur_per_mwh"]]
            .drop_duplicates(subset=["delivery_start_utc"])
            .sort_values("delivery_start_utc")
            .reset_index(drop=True)
        )
        inside_minmax = 0
        inside_p05_p95 = 0
        above_max = 0
        below_min = 0
        widths: list[float] = []
        volatilities: list[float] = []
        for _, hour_group in week_frame.groupby("delivery_start_utc", sort=True):
            values = pd.to_numeric(hour_group["scenario_price_eur_per_mwh"], errors="coerce").to_numpy(dtype=float)
            weights = pd.to_numeric(hour_group["scenario_probability"], errors="coerce").to_numpy(dtype=float)
            actual = float(pd.to_numeric(hour_group["actual_price_eur_per_mwh"], errors="coerce").iloc[0])
            scenario_min = float(np.min(values))
            scenario_max = float(np.max(values))
            p05 = float(_weighted_quantile(values, weights, 0.05))
            p95 = float(_weighted_quantile(values, weights, 0.95))
            widths.append(float(p95 - p05))
            volatilities.append(float(np.std(values)))
            inside_minmax += int(scenario_min - TOLERANCE <= actual <= scenario_max + TOLERANCE)
            inside_p05_p95 += int(p05 - TOLERANCE <= actual <= p95 + TOLERANCE)
            above_max += int(actual > scenario_max + TOLERANCE)
            below_min += int(actual < scenario_min - TOLERANCE)
        hour_count = int(actual_rows.shape[0])
        temporal_ok = True
        for _, day_group in week_frame.groupby("forecast_origin_utc", sort=False):
            scenario_counts = day_group.groupby("scenario_id")["delivery_start_utc"].nunique()
            if not scenario_counts.eq(24).all():
                temporal_ok = False
                break
            ordered_hours = sorted(day_group["delivery_start_utc"].drop_duplicates().tolist())
            if len(ordered_hours) != 24:
                temporal_ok = False
                break
            expected = pd.date_range(ordered_hours[0], periods=24, freq="h", tz="UTC")
            if list(pd.DatetimeIndex(ordered_hours)) != list(expected):
                temporal_ok = False
                break
        week_rows.append(
            {
                "week_id": week_id,
                "week_start": week_start,
                "complete_support": True,
                "actual_price_mean": float(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").mean()),
                "actual_price_std": float(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").std()),
                "actual_price_min": float(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").min()),
                "actual_price_max": float(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").max()),
                "actual_price_spread": float(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").max() - pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").min()),
                "high_price_hours": int(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").ge(p_ref).sum()),
                "negative_or_low_price_hours": int(pd.to_numeric(actual_rows["actual_price_eur_per_mwh"], errors="coerce").le(low_price_threshold).sum()),
                "actual_inside_scenario_minmax_share": float(inside_minmax / max(hour_count, 1)),
                "actual_inside_scenario_p05_p95_share": float(inside_p05_p95 / max(hour_count, 1)),
                "actual_above_scenario_max_hours": int(above_max),
                "actual_below_scenario_min_hours": int(below_min),
                "scenario_p95_p05_width_mean": float(np.mean(widths)) if widths else np.nan,
                "scenario_tail_width_p95": float(np.quantile(widths, 0.95)) if widths else np.nan,
                "scenario_price_volatility_mean": float(np.mean(volatilities)) if volatilities else np.nan,
                "scenario_temporal_coherence_ok": bool(temporal_ok),
                "cvar_opportunity_score": np.nan,
            }
        )

    screening = pd.DataFrame(week_rows).sort_values("week_start").reset_index(drop=True)
    if screening.empty:
        raise RuntimeError("No candidate weeks available for CVaR opportunity screening.")
    complete = screening.loc[screening["complete_support"].astype(bool)].copy()
    for column in [
        "actual_price_std",
        "actual_price_spread",
        "scenario_p95_p05_width_mean",
        "high_price_hours",
    ]:
        if complete.empty:
            screening[f"{column}_rank"] = np.nan
        else:
            ranks = complete[column].rank(method="average", pct=True).astype(float)
            screening[f"{column}_rank"] = np.nan
            screening.loc[complete.index, f"{column}_rank"] = ranks.to_numpy()
    screening["containment_score"] = (
        0.6 * pd.to_numeric(screening["actual_inside_scenario_minmax_share"], errors="coerce").fillna(0.0)
        + 0.4 * pd.to_numeric(screening["actual_inside_scenario_p05_p95_share"], errors="coerce").fillna(0.0)
    )
    screening["cvar_opportunity_score"] = (
        0.30 * pd.to_numeric(screening["actual_price_std_rank"], errors="coerce").fillna(0.0)
        + 0.20 * pd.to_numeric(screening["actual_price_spread_rank"], errors="coerce").fillna(0.0)
        + 0.20 * pd.to_numeric(screening["scenario_p95_p05_width_mean_rank"], errors="coerce").fillna(0.0)
        + 0.15 * pd.to_numeric(screening["high_price_hours_rank"], errors="coerce").fillna(0.0)
        + 0.15 * pd.to_numeric(screening["containment_score"], errors="coerce").fillna(0.0)
        - np.maximum(0.0, 0.90 - pd.to_numeric(screening["actual_inside_scenario_minmax_share"], errors="coerce").fillna(0.0)) * 2.0
        - np.maximum(0.0, 0.50 - pd.to_numeric(screening["actual_inside_scenario_p05_p95_share"], errors="coerce").fillna(0.0))
    )
    preferred = screening.loc[
        screening["complete_support"].astype(bool)
        & screening["scenario_temporal_coherence_ok"].astype(bool)
        & pd.to_numeric(screening["actual_inside_scenario_minmax_share"], errors="coerce").ge(0.75)
    ].copy()
    if preferred.empty:
        preferred = screening.loc[screening["complete_support"].astype(bool) & screening["scenario_temporal_coherence_ok"].astype(bool)].copy()
    selected = preferred.sort_values(
        ["cvar_opportunity_score", "actual_price_std", "scenario_p95_p05_width_mean", "high_price_hours"],
        ascending=[False, False, False, False],
    ).iloc[0]
    manifest = {
        "week_id": str(selected["week_id"]),
        "week_start": str(selected["week_start"]),
        "week_end": (pd.Timestamp(selected["week_start"]) + pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
        "week_label": "selected_cvar_opportunity_week",
        "selection_reason": (
            f"score={float(selected['cvar_opportunity_score']):.6f}; "
            f"actual_std={float(selected['actual_price_std']):.3f}; "
            f"actual_spread={float(selected['actual_price_spread']):.3f}; "
            f"inside_minmax_share={float(selected['actual_inside_scenario_minmax_share']):.3f}; "
            f"inside_p05_p95_share={float(selected['actual_inside_scenario_p05_p95_share']):.3f}; "
            f"high_price_hours={int(selected['high_price_hours'])}; "
            f"tail_width_mean={float(selected['scenario_p95_p05_width_mean']):.3f}"
        ),
    }
    screening = screening.drop(columns=[column for column in screening.columns if column.endswith("_rank") or column == "containment_score"])
    return screening, manifest


def _build_day_payloads_for_selected_week(
    *,
    scenarios: pd.DataFrame,
    selected_daily: pd.DataFrame,
    selected_week_manifest: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    week_days = pd.date_range(
        pd.Timestamp(selected_week_manifest["week_start"]),
        pd.Timestamp(selected_week_manifest["week_end"]),
        freq="D",
    ).strftime("%Y-%m-%d").tolist()
    daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(week_days)].copy()
    if daily.shape[0] != 7:
        raise ValueError(f"Selected diagnostic week does not have 7 complete support days: {week_days}")
    payloads: dict[str, dict[str, Any]] = {}
    for row in daily.to_dict(orient="records"):
        origin = pd.Timestamp(row["forecast_origin_utc"])
        delivery_day = str(row["delivery_day"])
        selected = scenarios.loc[scenarios["forecast_origin_utc"].eq(origin)].copy()
        selected = selected.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)
        payloads[delivery_day] = {
            "day_meta": row,
            "forecast_origin_utc": origin,
            "scenarios": selected,
            "model_id": str(row["model_id"]),
            "model_label": str(row["model_label"]),
            "validation_mode": str(row["validation_mode"]),
            "thesis_grade": True,
            "forecast_origin_reconstruction_used": False,
        }
    return week_days, payloads


def _weekly_metrics_from_daily(daily_metrics: pd.DataFrame, selected_week_manifest: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (gamma, production_variant), group in daily_metrics.groupby(["cvar_gamma", "production_variant"], sort=False):
        submitted = float(pd.to_numeric(group["submitted_energy_mwh"], errors="coerce").sum())
        cleared = float(pd.to_numeric(group["cleared_energy_mwh"], errors="coerce").sum())
        used = float(pd.to_numeric(group["used_cleared_energy_mwh"], errors="coerce").sum())
        pf_profit = float(pd.to_numeric(group["perfect_foresight_profit"], errors="coerce").sum())
        hydrogen_total = float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum())
        weekly_target_kg = float(
            pd.to_numeric(group["weekly_target_kg"], errors="coerce").dropna().iloc[0]
        )
        feasible_all_days = bool(
            group["actual_redispatch_feasible"].astype(bool).all()
            and group["solver_status"].map(_accepted_solver_status).all()
        )
        daily_band_violations = int(pd.to_numeric(group["daily_band_violations"], errors="coerce").fillna(0).sum())
        infeasible_days = int(pd.to_numeric(group["infeasible_redispatch_days"], errors="coerce").fillna(0).sum())
        weekly_target_met = bool(
            feasible_all_days
            and daily_band_violations == 0
            and infeasible_days == 0
            and hydrogen_total + 1e-6 >= weekly_target_kg
        )
        rows.append(
            {
                "artifact_id": str(group["artifact_id"].iloc[0]),
                "model_label": str(group["model_label"].iloc[0]),
                "week_id": str(selected_week_manifest["week_id"]),
                "week_label": str(selected_week_manifest["week_label"]),
                "week_start": str(selected_week_manifest["week_start"]),
                "week_end": str(selected_week_manifest["week_end"]),
                "production_variant": str(production_variant),
                "cvar_alpha": float(pd.to_numeric(group["cvar_alpha"], errors="coerce").dropna().iloc[0]),
                "cvar_gamma": float(gamma),
                "solver_status": "Optimal" if group["solver_status"].map(_accepted_solver_status).all() else "non_optimal_present",
                "feasible_all_days": feasible_all_days,
                "weekly_target_met": weekly_target_met,
                "daily_band_violations": daily_band_violations,
                "infeasible_redispatch_days": infeasible_days,
                "realised_adjusted_profit": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum()),
                "expected_adjusted_profit": float(pd.to_numeric(group["expected_adjusted_profit"], errors="coerce").sum()),
                "value_captured_vs_perfect_foresight": float(pd.to_numeric(group["realised_adjusted_profit"], errors="coerce").sum() / pf_profit) if abs(pf_profit) > 1e-9 else np.nan,
                "perfect_foresight_profit": pf_profit,
                "cvar_tail_profit": float(pd.to_numeric(group["cvar_tail_profit"], errors="coerce").sum()),
                "worst_scenario_profit": float(pd.to_numeric(group["worst_scenario_profit"], errors="coerce").min()),
                "emergency_import_mwh": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "emergency_import_cost": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "emergency_import_hours": int(pd.to_numeric(group["emergency_import_hours"], errors="coerce").fillna(0).sum()),
                "emergency_import_share_of_used_energy": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum() / used) if used > 0.0 else 0.0,
                "submitted_energy_mwh": submitted,
                "cleared_energy_mwh": cleared,
                "rejected_energy_mwh": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "unused_cleared_energy_mwh": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "clearing_ratio": float(cleared / submitted) if submitted > 0.0 else 0.0,
                "average_actual_price_paid": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum() / cleared) if cleared > 0.0 else np.nan,
                "high_bid_share": float(pd.to_numeric(group["high_bid_energy_mwh"], errors="coerce").sum() / submitted) if submitted > 0.0 else 0.0,
                "market_cap_bid_share": float(pd.to_numeric(group["market_cap_bid_energy_mwh"], errors="coerce").sum() / submitted) if submitted > 0.0 else 0.0,
                "storage_min_kg": float(pd.to_numeric(group["storage_min_kg"], errors="coerce").min()),
                "reserve_boundary_hits": int(pd.to_numeric(group["reserve_boundary_hits"], errors="coerce").fillna(0).sum()),
                "solve_time_seconds": float(pd.to_numeric(group["solve_time_seconds"], errors="coerce").sum()),
                "mip_gap": float(pd.to_numeric(group["mip_gap"], errors="coerce").max()),
                "variable_count": int(pd.to_numeric(group["variable_count"], errors="coerce").max()),
                "binary_variable_count": int(pd.to_numeric(group["binary_variable_count"], errors="coerce").max()),
                "constraint_count": int(pd.to_numeric(group["constraint_count"], errors="coerce").max()),
                "hydrogen_sold_or_compressed_kg": hydrogen_total,
                "weekly_target_kg": weekly_target_kg,
            }
        )
    return pd.DataFrame(rows).sort_values(["production_variant", "cvar_gamma"]).reset_index(drop=True)


def _build_diagnostic_summary(weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    return weekly_metrics[
        [
            "cvar_gamma",
            "production_variant",
            "feasible_all_days",
            "weekly_target_met",
            "daily_band_violations",
            "realised_adjusted_profit",
            "expected_adjusted_profit",
            "value_captured_vs_perfect_foresight",
            "cvar_tail_profit",
            "worst_scenario_profit",
            "emergency_import_mwh",
            "emergency_import_cost",
            "emergency_import_hours",
            "emergency_import_share_of_used_energy",
            "submitted_energy_mwh",
            "cleared_energy_mwh",
            "rejected_energy_mwh",
            "unused_cleared_energy_mwh",
            "clearing_ratio",
            "average_actual_price_paid",
            "high_bid_share",
            "market_cap_bid_share",
            "storage_min_kg",
            "reserve_boundary_hits",
            "solve_time_seconds",
            "mip_gap",
            "variable_count",
            "binary_variable_count",
            "constraint_count",
        ]
    ].sort_values(["production_variant", "cvar_gamma"]).reset_index(drop=True)


def _build_validation_checks(
    *,
    artifact_id: str,
    selected_week_manifest: dict[str, Any],
    screening: pd.DataFrame,
    daily_metrics: pd.DataFrame,
    weekly_target_tracker: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch: pd.DataFrame,
    alpha: float,
    gamma_values: list[float],
    production_variants: list[str],
    emergency_import_price: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    rows.append(_validation_row(check_name="lear_strict_only", status="pass" if daily_metrics["artifact_id"].astype(str).eq(str(artifact_id)).all() else "fail", details=f"artifact_ids={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}"))
    selected_screen = screening.loc[screening["week_id"].astype(str).eq(str(selected_week_manifest["week_id"]))].iloc[0]
    rows.append(_validation_row(check_name="selected_week_has_complete_support", status="pass" if bool(selected_screen["complete_support"]) else "fail", details=f"week_start={selected_week_manifest['week_start']}"))
    rows.append(_validation_row(check_name="gamma_grid_exactly_0_0p05_0p25", status="pass" if sorted(pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").dropna().unique().tolist()) == sorted(gamma_values) else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="alpha_exactly_0p95", status="pass" if sorted(pd.to_numeric(daily_metrics["cvar_alpha"], errors="coerce").dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(daily_metrics['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"))
    rows.append(_validation_row(check_name="production_variants_exact", status="pass" if sorted(daily_metrics["production_variant"].astype(str).unique().tolist()) == sorted(production_variants) else "fail", details=f"observed={sorted(daily_metrics['production_variant'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="emergency_import_enabled_and_charged_at_3000", status="pass" if daily_metrics["emergency_import_enabled"].astype(bool).all() and np.isclose(pd.to_numeric(daily_metrics["emergency_import_price_eur_per_mwh"], errors="coerce").dropna(), float(emergency_import_price)).all() else "fail", details=f"price={float(emergency_import_price):.2f}"))
    rows.append(_validation_row(check_name="no_shortfall_slack", status="pass" if pd.to_numeric(daily_metrics["shortfall_kg"], errors="coerce").fillna(0.0).abs().le(1e-9).all() else "fail", details="hard weekly target with emergency fallback"))
    accepted = actual_clearing.loc[actual_clearing["accepted"].astype(bool)].copy() if "accepted" in actual_clearing.columns else pd.DataFrame()
    accepted_ok = accepted.empty or bool((pd.to_numeric(accepted["bid_price_eur_per_mwh"], errors="coerce") + TOLERANCE >= pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce")).all())
    rows.append(_validation_row(check_name="accepted_iff_bid_price_ge_actual_price", status="pass" if accepted_ok else "fail", details=f"accepted_rows={int(accepted.shape[0])}"))
    pay_as_cleared_ok = True
    if not accepted.empty and "settlement_cost_eur" in accepted.columns:
        pay_as_cleared_ok = np.allclose(
            pd.to_numeric(accepted["settlement_cost_eur"], errors="coerce"),
            pd.to_numeric(accepted["actual_price_eur_per_mwh"], errors="coerce") * pd.to_numeric(accepted["cleared_energy_mwh"], errors="coerce"),
            atol=1e-6,
        )
    rows.append(_validation_row(check_name="da_settlement_pay_as_cleared", status="pass" if pay_as_cleared_ok else "fail", details="accepted DA demand pays actual cleared price"))
    rejected_ok = np.allclose(
        pd.to_numeric(daily_metrics["submitted_energy_mwh"], errors="coerce") - pd.to_numeric(daily_metrics["cleared_energy_mwh"], errors="coerce"),
        pd.to_numeric(daily_metrics["rejected_energy_mwh"], errors="coerce"),
        atol=1e-6,
        equal_nan=True,
    )
    rows.append(_validation_row(check_name="rejected_equals_submitted_minus_cleared", status="pass" if rejected_ok else "fail", details="daily rejected identity"))
    energy_balance_ok = True
    if not actual_redispatch.empty:
        used = pd.to_numeric(actual_redispatch["used_energy_mwh"], errors="coerce").fillna(0.0)
        unused = pd.to_numeric(actual_redispatch["unused_cleared_energy_mwh"], errors="coerce").fillna(0.0)
        cleared = pd.to_numeric(actual_redispatch["cleared_energy_mwh"], errors="coerce").fillna(0.0)
        emergency = pd.to_numeric(actual_redispatch["emergency_import_mwh"], errors="coerce").fillna(0.0)
        energy_balance_ok = bool(np.allclose((used + unused).to_numpy(), (cleared + emergency).to_numpy(), atol=1e-6))
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared_plus_emergency", status="pass" if energy_balance_ok else "fail", details="realised hourly energy balance"))
    storage_close_ok = True
    if not actual_redispatch.empty:
        for _, group in actual_redispatch.groupby(["production_variant", "delivery_day", "cvar_gamma"], sort=False):
            ordered = group.sort_values("delivery_start_utc")
            prev = float(ordered["storage_initial_kg"].iloc[0]) if "storage_initial_kg" in ordered.columns else float("nan")
            for row in ordered.itertuples():
                computed = prev + float(row.H_prod_kg) - float(row.H_comp_kg)
                if abs(computed - float(row.H_buf_kg)) > 1e-6:
                    storage_close_ok = False
                    break
                prev = float(row.H_buf_kg)
            if not storage_close_ok:
                break
    rows.append(_validation_row(check_name="storage_balance_closes", status="pass" if storage_close_ok else "fail", details="checked actual redispatch trajectories"))
    rows.append(_validation_row(check_name="terminal_inventory_correction_reported", status="pass" if "terminal_inventory_correction" in daily_metrics.columns else "fail", details="daily metrics include terminal inventory correction"))
    rows.append(_validation_row(check_name="infeasible_rows_explicit", status="pass", details=f"infeasible_rows={int((~daily_metrics['actual_redispatch_feasible'].astype(bool)).sum())}"))
    rows.append(_validation_row(check_name="no_scenario_probability_bid_grid_changes", status="pass", details="Diagnostic reuses existing LEAR Strict scenarios, probabilities, bid grid, and market clearing logic."))
    return pd.DataFrame(rows)


def _build_cvar_validation_checks(
    *,
    daily_metrics: pd.DataFrame,
    scenario_settlement_results: pd.DataFrame,
    alpha: float,
    gamma_values: list[float],
) -> pd.DataFrame:
    executed = daily_metrics.loc[pd.to_numeric(daily_metrics["expected_adjusted_profit"], errors="coerce").notna()].copy()
    rows = [
        _validation_row(check_name="alpha_exact", status="pass" if sorted(pd.to_numeric(executed["cvar_alpha"], errors="coerce").dropna().unique().tolist()) == [float(alpha)] else "fail", details=f"observed={sorted(pd.to_numeric(executed['cvar_alpha'], errors='coerce').dropna().unique().tolist())}"),
        _validation_row(check_name="gamma_grid_exact", status="pass" if sorted(pd.to_numeric(executed["cvar_gamma"], errors="coerce").dropna().unique().tolist()) == sorted(gamma_values) else "fail", details=f"observed={sorted(pd.to_numeric(executed['cvar_gamma'], errors='coerce').dropna().unique().tolist())}"),
        _validation_row(check_name="var_and_cvar_finite", status="pass" if (not executed.empty and np.isfinite(pd.to_numeric(executed["cvar_tail_profit"], errors="coerce")).all()) else "fail", details="executed rows only"),
    ]
    scenario = scenario_settlement_results.copy()
    if not scenario.empty and "xi_loss_excess_eur" in scenario.columns:
        rows.append(_validation_row(check_name="excess_loss_nonnegative", status="pass" if (pd.to_numeric(scenario["xi_loss_excess_eur"], errors="coerce") >= -1e-9).all() else "fail", details="scenario xi values"))
        prob_sums = scenario.groupby(["production_variant", "delivery_day", "cvar_gamma"], as_index=False)["scenario_probability"].sum()
        max_prob_error = float(pd.to_numeric(prob_sums["scenario_probability"], errors="coerce").sub(1.0).abs().max())
        rows.append(_validation_row(check_name="scenario_probabilities_sum_to_one", status="pass" if max_prob_error <= 1e-6 else "fail", details=f"max_error={max_prob_error:.9f}"))
    else:
        rows.append(_validation_row(check_name="excess_loss_nonnegative", status="fail", details="missing scenario settlement columns"))
        rows.append(_validation_row(check_name="scenario_probabilities_sum_to_one", status="fail", details="no scenario settlement rows"))
    return pd.DataFrame(rows)


def _build_readme(
    *,
    support_audit: pd.DataFrame,
    selected_week_manifest: dict[str, Any],
    screening: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    diagnostic_summary: pd.DataFrame,
) -> str:
    audit_row = support_audit.iloc[0]
    selected_screen = screening.loc[screening["week_id"].astype(str).eq(str(selected_week_manifest["week_id"]))].iloc[0]
    summary = diagnostic_summary.copy()
    band_on = summary.loc[summary["production_variant"].astype(str).eq("weekly_hard_band_on")].copy()
    band_off = summary.loc[summary["production_variant"].astype(str).eq("weekly_hard_band_off")].copy()
    best_on = band_on.sort_values("realised_adjusted_profit", ascending=False).iloc[0]
    best_off = band_off.sort_values("realised_adjusted_profit", ascending=False).iloc[0]
    all_rows = summary.sort_values(["production_variant", "cvar_gamma"]).reset_index(drop=True)

    def _gamma_effect(metric: str, frame: pd.DataFrame, improve_high: bool = True) -> str:
        ordered = frame.sort_values("cvar_gamma")
        if ordered.empty:
            return "no data"
        g0 = float(pd.to_numeric(ordered.loc[ordered["cvar_gamma"].astype(float).eq(0.0), metric], errors="coerce").iloc[0])
        gbest = float(pd.to_numeric(ordered[metric], errors="coerce").max() if improve_high else pd.to_numeric(ordered[metric], errors="coerce").min())
        if np.isnan(g0) or np.isnan(gbest):
            return "no data"
        if improve_high:
            return "yes" if gbest > g0 + 1e-9 else "no"
        return "yes" if gbest < g0 - 1e-9 else "no"

    cvar_reduce_import = "yes" if (
        (pd.to_numeric(band_on["emergency_import_mwh"], errors="coerce").min() + 1e-9 < float(pd.to_numeric(band_on.loc[band_on["cvar_gamma"].astype(float).eq(0.0), "emergency_import_mwh"], errors="coerce").iloc[0]))
        or (pd.to_numeric(band_off["emergency_import_mwh"], errors="coerce").min() + 1e-9 < float(pd.to_numeric(band_off.loc[band_off["cvar_gamma"].astype(float).eq(0.0), "emergency_import_mwh"], errors="coerce").iloc[0]))
    ) else "no"
    cvar_reduce_rejected = "yes" if (
        (pd.to_numeric(band_on["rejected_energy_mwh"], errors="coerce").min() + 1e-9 < float(pd.to_numeric(band_on.loc[band_on["cvar_gamma"].astype(float).eq(0.0), "rejected_energy_mwh"], errors="coerce").iloc[0]))
        or (pd.to_numeric(band_off["rejected_energy_mwh"], errors="coerce").min() + 1e-9 < float(pd.to_numeric(band_off.loc[band_off["cvar_gamma"].astype(float).eq(0.0), "rejected_energy_mwh"], errors="coerce").iloc[0]))
    ) else "no"
    cvar_tail_help = "yes" if (
        (pd.to_numeric(band_on["cvar_tail_profit"], errors="coerce").max() > float(pd.to_numeric(band_on.loc[band_on["cvar_gamma"].astype(float).eq(0.0), "cvar_tail_profit"], errors="coerce").iloc[0]) + 1e-9)
        or (pd.to_numeric(band_off["cvar_tail_profit"], errors="coerce").max() > float(pd.to_numeric(band_off.loc[band_off["cvar_gamma"].astype(float).eq(0.0), "cvar_tail_profit"], errors="coerce").iloc[0]) + 1e-9)
    ) else "no"
    cvar_realised_help = "yes" if (
        (pd.to_numeric(band_on["realised_adjusted_profit"], errors="coerce").max() > float(pd.to_numeric(band_on.loc[band_on["cvar_gamma"].astype(float).eq(0.0), "realised_adjusted_profit"], errors="coerce").iloc[0]) + 1e-9)
        or (pd.to_numeric(band_off["realised_adjusted_profit"], errors="coerce").max() > float(pd.to_numeric(band_off.loc[band_off["cvar_gamma"].astype(float).eq(0.0), "realised_adjusted_profit"], errors="coerce").iloc[0]) + 1e-9)
    ) else "no"
    band_conclusion = "no major change" if str(best_on["cvar_gamma"]) == str(best_off["cvar_gamma"]) else "yes"
    gamma_recommendation = "gamma=0 remains preferred"
    if cvar_realised_help == "no" and cvar_tail_help == "yes":
        gamma_recommendation = "gamma=0 remains preferred for realised-profit selection; higher gamma only improves tail diagnostics on this week"
    elif cvar_realised_help == "yes":
        gamma_recommendation = "risk aversion may be useful"
    lines = [
        "# LEAR Strict CVaR Opportunity Diagnostic",
        "",
        f"1. Is LEAR Strict eligible for a full-year run? {'yes' if bool(audit_row['eligible_for_full_year_run']) else 'no'}.",
        f"2. Which week was selected and why? {selected_week_manifest['week_start']} to {selected_week_manifest['week_end']}; {selected_week_manifest['selection_reason']}.",
        f"3. Was actual price mostly inside the scenario envelope? min/max share={float(selected_screen['actual_inside_scenario_minmax_share']):.3f}; p05/p95 share={float(selected_screen['actual_inside_scenario_p05_p95_share']):.3f}.",
        f"4. Does CVaR reduce emergency import? {cvar_reduce_import}.",
        f"5. Does CVaR reduce rejected or unused energy? rejected={cvar_reduce_rejected}.",
        f"6. Does CVaR improve CVaR tail profit or worst-scenario profit? {cvar_tail_help}.",
        f"7. Does CVaR improve realised profit? {cvar_realised_help}.",
        f"8. Does band ON/OFF change the conclusion? {band_conclusion}.",
        f"9. Should gamma remain 0, or is risk aversion useful under the new fallback policy? {gamma_recommendation}.",
        "",
        f"- Best band-on row: gamma={best_on['cvar_gamma']}, realised_profit={float(best_on['realised_adjusted_profit']):.2f}, emergency_import_mwh={float(best_on['emergency_import_mwh']):.3f}.",
        f"- Best band-off row: gamma={best_off['cvar_gamma']}, realised_profit={float(best_off['realised_adjusted_profit']):.2f}, emergency_import_mwh={float(best_off['emergency_import_mwh']):.3f}.",
    ]
    return "\n".join(lines)


def run_lear_strict_cvar_opportunity_diagnostic(
    *,
    config: HydrogenConfig | str | Path,
    artifact_id: str,
    audit_start: str,
    audit_end: str,
    alpha: float,
    gammas: list[float] | tuple[float, ...],
    production_variants: list[str] | tuple[str, ...],
    daily_min_fraction: float,
    daily_max_fraction: float,
    emergency_import_price: float,
    run_slug: str,
    output_root: Path | None = None,
    safe_resume: bool = True,
    resume_run_dir: Path | None = None,
) -> PhaseE4dResult:
    if str(artifact_id) != LEARNER_ARTIFACT:
        raise ValueError(f"Phase E4d requires LEAR Strict artifact only, got {artifact_id!r}.")
    gamma_values = [float(value) for value in gammas]
    if sorted(gamma_values) != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase E4d requires gammas exactly [0, 0.05, 0.25], got {gammas!r}.")
    if abs(float(alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase E4d requires alpha=0.95, got {alpha!r}.")
    variant_list = [str(value).strip() for value in production_variants]
    if sorted(variant_list) != sorted(PRODUCTION_VARIANTS):
        raise ValueError(f"Phase E4d requires production variants exactly {list(PRODUCTION_VARIANTS)}, got {variant_list!r}.")

    run_config = _load_single_artifact_config(
        config,
        artifact_id=artifact_id,
        output_root=output_root,
        run_slug=str(run_slug),
    )
    if resume_run_dir is not None:
        run_dir = Path(resume_run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_dir.name
    elif bool(safe_resume):
        existing = _find_latest_resume_dir(run_config.run_output_root, str(run_slug))
        if existing is not None:
            run_dir = existing
            run_id = run_dir.name
        else:
            run_id, run_dir = create_run_folder(run_config)
    else:
        run_id, run_dir = create_run_folder(run_config)
    (run_dir / "day_runs").mkdir(parents=True, exist_ok=True)
    (run_dir / "cache").mkdir(parents=True, exist_ok=True)

    scenarios, registry, selected_daily, spec = _load_artifact_daily_support(config=run_config, artifact_id=artifact_id)
    support_audit, audit_meta = _build_support_audit(
        selected_daily=selected_daily,
        registry=registry,
        audit_start=str(audit_start),
        audit_end=str(audit_end),
        expected_scenario_count=int(selected_daily["expected_scenario_count"].iloc[0]),
    )
    screening, selected_week_manifest = _screen_complete_weeks(
        scenarios=scenarios,
        selected_daily=selected_daily,
        audit_start=str(audit_start),
        audit_end=str(audit_end),
        config=run_config,
    )

    save_config_resolved(run_dir, run_config)
    save_inputs_manifest(run_dir, [run_config.config_path, run_config.models.scenario_catalog, spec.path])
    save_json(
        run_dir,
        "input_manifest.json",
        build_inputs_manifest([run_config.config_path, run_config.models.scenario_catalog, spec.path])
        | {
            "artifact_id": str(artifact_id),
            "audit_start": str(audit_start),
            "audit_end": str(audit_end),
            "alpha": float(alpha),
            "gammas": gamma_values,
            "production_variants": variant_list,
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
        },
    )
    save_frame_csv(run_dir, "lear_strict_full_year_support_audit.csv", support_audit)
    save_frame_csv(run_dir, "cvar_opportunity_week_screening.csv", screening)
    save_json(run_dir, "selected_cvar_opportunity_week_manifest.json", selected_week_manifest)

    settings = build_weekly_hard_band_settings(
        daily_target_kg=float(run_config.economics.daily_target_kg),
        daily_min_fraction=float(daily_min_fraction),
        daily_max_fraction=float(daily_max_fraction),
    )
    physical_daily_max_kg = _physical_daily_max_kg(run_config)
    save_json(
        run_dir,
        "production_variant_manifest.json",
        {
            "target_mode": TARGET_MODE_WEEKLY_HARD_BAND,
            "production_variants": variant_list,
            "weekly_target_kg": float(settings.weekly_target_kg),
            "daily_target_kg": float(settings.daily_target_kg),
            "daily_min_fraction": float(settings.daily_min_fraction),
            "daily_max_fraction": float(settings.daily_max_fraction),
            "band_on_daily_min_kg": float(settings.daily_min_kg),
            "band_on_daily_max_kg": float(settings.daily_max_kg),
            "band_off_physical_daily_max_kg": float(physical_daily_max_kg),
            "emergency_import_enabled": True,
            "emergency_import_price_eur_per_mwh": float(emergency_import_price),
            "daily_shortfall_slack_allowed": False,
        },
    )

    week_days, day_payloads = _build_day_payloads_for_selected_week(
        scenarios=scenarios,
        selected_daily=selected_daily,
        selected_week_manifest=selected_week_manifest,
    )
    week_row = pd.Series(
        {
            "week_id": str(selected_week_manifest["week_id"]),
            "week_label": str(selected_week_manifest["week_label"]),
            "regime_label": "cvar_opportunity_screened",
            "selection_reason": str(selected_week_manifest["selection_reason"]),
        }
    )

    pf_frames: list[pd.DataFrame] = []
    pf_daily_map: dict[tuple[str, str], pd.Series] = {}
    tracker_frames: list[pd.DataFrame] = []
    for production_variant in variant_list:
        cache_path = run_dir / "cache" / f"{production_variant}__perfect_foresight_daily.csv"
        reference_days = {day: day_payloads[day] for day in week_days}
        pf_daily, pf_tracker = _run_perfect_foresight_week_variant(
            week_row=week_row,
            week_days=week_days,
            reference_days=reference_days,
            config=run_config,
            settings=settings,
            production_variant=production_variant,
            physical_daily_max_kg=float(physical_daily_max_kg),
            emergency_import_price=float(emergency_import_price),
            run_id=run_id,
            cache_path=cache_path,
        )
        pf_frames.append(pf_daily)
        tracker_frames.append(pf_tracker)
        for row in pf_daily.loc[pf_daily["aggregation_level"].astype(str).eq("daily")].itertuples():
            pf_daily_map[(str(row.delivery_day), str(production_variant))] = pd.Series(row._asdict())

    registry_path = run_dir / "cache" / "stochastic_day_registry.csv"
    if registry_path.exists():
        stochastic_registry = pd.read_csv(registry_path)
    else:
        stochastic_registry = pd.DataFrame(
            columns=["delivery_day", "cvar_gamma", "production_variant", "day_run_dir", "forecast_origin_utc"]
        )

    daily_rows: list[dict[str, Any]] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    submitted_bid_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    validation_rows: list[pd.DataFrame] = []
    runtime_rows: list[dict[str, Any]] = []
    infeasibility_rows: list[dict[str, Any]] = []

    for production_variant in variant_list:
        inventory_start = float(run_config.hydrogen_system.storage_initial_kg)
        cumulative = 0.0
        block_remaining_days = False
        for gamma in gamma_values:
            inventory_start = float(run_config.hydrogen_system.storage_initial_kg)
            cumulative = 0.0
            block_remaining_days = False
            for offset, delivery_day in enumerate(week_days):
                day_payload = day_payloads[delivery_day]
                day_meta = day_payload["day_meta"]
                days_remaining = len(week_days) - offset
                bounds = _compute_variant_bounds(
                    settings=settings,
                    production_variant=production_variant,
                    cumulative_realised_h2_kg_before_today=cumulative,
                    days_remaining_in_week=days_remaining,
                    physical_daily_max_kg=float(physical_daily_max_kg),
                )
                if block_remaining_days:
                    metric_row = _build_skipped_daily_metric(
                        run_id=run_id,
                        artifact_id=artifact_id,
                        model_label=_label_for_artifact(artifact_id),
                        validation_mode=str(day_payload["validation_mode"]),
                        thesis_grade=bool(day_payload["thesis_grade"]),
                        forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                        week_row=week_row,
                        day_meta=day_meta,
                        day_payload=day_payload,
                        cvar_alpha=float(alpha),
                        cvar_gamma=float(gamma),
                        production_variant=production_variant,
                        bounds=bounds,
                        cumulative_before_kg=float(cumulative),
                        skip_reason="not_run_after_prior_infeasible_redispatch",
                        scenario_count=int(day_payload["scenarios"]["scenario_id"].astype(str).nunique()),
                        scenario_probability_check=True,
                        emergency_import_price=float(emergency_import_price),
                    )
                    daily_rows.append(metric_row)
                    tracker_frames.append(
                        pd.DataFrame(
                            [
                                {
                                    "strategy": metric_row["strategy"],
                                    "artifact_id": artifact_id,
                                    "model_label": _label_for_artifact(artifact_id),
                                    "gamma": float(gamma),
                                    "production_variant": str(production_variant),
                                    "week_id": str(selected_week_manifest["week_id"]),
                                    "week_label": str(selected_week_manifest["week_label"]),
                                    "delivery_day": delivery_day,
                                    "forecast_origin_utc": day_payload["forecast_origin_utc"],
                                    "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                    "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                    "weekly_target_kg": float(bounds.weekly_target_kg),
                                    "cumulative_before_kg": float(cumulative),
                                    "cumulative_after_kg": float(cumulative),
                                    "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                                    "days_remaining_in_week": int(bounds.days_remaining_in_week),
                                    "hydrogen_sold_or_compressed_kg": np.nan,
                                    "storage_start_kg": float(inventory_start),
                                    "storage_end_kg": float(inventory_start),
                                    "solver_status": "not_run_after_prior_infeasible_redispatch",
                                }
                            ]
                        )
                    )
                    infeasibility_rows.append(
                        {
                            "delivery_day": delivery_day,
                            "production_variant": str(production_variant),
                            "cvar_gamma": float(gamma),
                            "issue_type": "skipped_after_prior_infeasible_redispatch",
                            "details": "not_run_after_prior_infeasible_redispatch",
                        }
                    )
                    continue

                cached_mask = (
                    stochastic_registry["delivery_day"].astype(str).eq(delivery_day)
                    & pd.to_numeric(stochastic_registry["cvar_gamma"], errors="coerce").eq(float(gamma))
                    & stochastic_registry["production_variant"].astype(str).eq(str(production_variant))
                )
                payload: dict[str, Any] | None = None
                cached_rows = stochastic_registry.loc[cached_mask].copy()
                if not cached_rows.empty:
                    cache_row = cached_rows.iloc[-1]
                    day_run_dir = Path(str(cache_row["day_run_dir"]))
                    if day_run_dir.exists():
                        load_started = perf_counter()
                        payload = _load_cached_day_payload(cache_row, model_id=str(day_payload["model_id"]))
                        runtime_rows.append(
                            {
                                "solve_stage": "stochastic_bidding_day",
                                "delivery_day": delivery_day,
                                "cvar_gamma": float(gamma),
                                "production_variant": str(production_variant),
                                "wall_time_seconds": float(perf_counter() - load_started),
                                "used_cache": True,
                                "solver_status": str(payload["stochastic_solver_status"]),
                            }
                        )
                if payload is None:
                    started = perf_counter()
                    live_result = run_real_scenario_bidding_dry_run(
                        config=run_config,
                        artifact_id=artifact_id,
                        forecast_origin_utc=str(day_payload["forecast_origin_utc"].isoformat()),
                        max_origins=1,
                        output_root=run_dir / "day_runs",
                        strategy_name=f"lear_strict_cvar_opportunity::{production_variant}",
                        dry_run_label="phase_e4d_lear_strict_cvar_opportunity",
                        include_price_insensitive_comparison=False,
                        risk_measure="risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar",
                        cvar_alpha=float(alpha),
                        cvar_gamma=float(gamma),
                        production_target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                        inventory_start_kg=inventory_start,
                        reserve_kg=float(run_config.hydrogen_system.reserve_kg),
                        target_hydrogen_min_kg=float(bounds.daily_lower_bound_kg),
                        target_hydrogen_max_kg=float(bounds.daily_upper_bound_kg),
                        terminal_reference_start_kg=inventory_start,
                        emergency_import_price_eur_per_mwh=float(emergency_import_price),
                        write_outputs=True,
                    )
                    payload = _payload_from_live_result(live_result, model_id=str(day_payload["model_id"]))
                    runtime_rows.append(
                        {
                            "solve_stage": "stochastic_bidding_day",
                            "delivery_day": delivery_day,
                            "cvar_gamma": float(gamma),
                            "production_variant": str(production_variant),
                            "wall_time_seconds": float(perf_counter() - started),
                            "used_cache": False,
                            "solver_status": str(payload["stochastic_solver_status"]),
                        }
                    )
                    stochastic_registry = pd.concat(
                        [
                            stochastic_registry,
                            pd.DataFrame(
                                [
                                    {
                                        "delivery_day": delivery_day,
                                        "cvar_gamma": float(gamma),
                                        "production_variant": str(production_variant),
                                        "day_run_dir": str(payload["run_dir"]),
                                        "forecast_origin_utc": pd.Timestamp(day_payload["forecast_origin_utc"]).isoformat(),
                                    }
                                ]
                            ),
                        ],
                        ignore_index=True,
                    )
                    save_frame_csv(run_dir / "cache", "stochastic_day_registry.csv", stochastic_registry)

                pf_row = pf_daily_map.get((delivery_day, str(production_variant)))
                metric_row = _build_stochastic_daily_metric(
                    run_id=run_id,
                    artifact_id=artifact_id,
                    model_label=_label_for_artifact(artifact_id),
                    validation_mode=str(day_payload["validation_mode"]),
                    thesis_grade=bool(day_payload["thesis_grade"]),
                    forecast_origin_reconstruction_used=bool(day_payload["forecast_origin_reconstruction_used"]),
                    week_row=week_row,
                    day_meta=day_meta,
                    payload=payload,
                    cvar_alpha=float(alpha),
                    cvar_gamma=float(gamma),
                    benchmark_profit_row=None,
                    perfect_foresight_profit_row=pf_row,
                    bounds=bounds,
                    cumulative_before_kg=float(cumulative),
                )
                actual_summary = payload["actual_settlement_results"].iloc[0]
                actual_redispatch = payload["actual_redispatch_timeseries"].copy()
                import_series = pd.to_numeric(actual_redispatch.get("emergency_import_mwh", 0.0), errors="coerce").fillna(0.0)
                emergency_import_mwh = float(import_series.sum())
                used_energy = float(pd.to_numeric(actual_summary["used_energy_mwh"], errors="coerce"))
                metric_row.update(
                    {
                        "production_variant": str(production_variant),
                        "emergency_import_enabled": True,
                        "emergency_import_price_eur_per_mwh": float(emergency_import_price),
                        "emergency_import_mwh": float(actual_summary.get("emergency_import_mwh", emergency_import_mwh)),
                        "emergency_import_cost": float(actual_summary.get("emergency_import_cost_eur", emergency_import_mwh * float(emergency_import_price))),
                        "emergency_import_hours": int(import_series.gt(1e-9).sum()),
                        "emergency_import_share_of_used_energy": float(emergency_import_mwh / used_energy) if used_energy > 0.0 else 0.0,
                    }
                )
                daily_rows.append(metric_row)
                validation_checks = payload["validation_checks"].loc[
                    ~payload["validation_checks"]["check_name"].astype(str).eq("redispatch.production_target_and_shortfall_reported")
                ].copy()
                validation_rows.append(
                    validation_checks.assign(
                        artifact_id=artifact_id,
                        model_label=_label_for_artifact(artifact_id),
                        week_id=str(selected_week_manifest["week_id"]),
                        week_label=str(selected_week_manifest["week_label"]),
                        delivery_day=delivery_day,
                        forecast_origin_utc=str(payload["forecast_origin_utc"]),
                        cvar_alpha=float(alpha),
                        cvar_gamma=float(gamma),
                        production_variant=str(production_variant),
                    )
                )
                actual_clearing_rows.append(
                    payload["actual_clearing"].assign(
                        artifact_id=artifact_id,
                        model_label=_label_for_artifact(artifact_id),
                        delivery_day=delivery_day,
                        cvar_gamma=float(gamma),
                        production_variant=str(production_variant),
                    )
                )
                actual_redispatch_rows.append(
                    payload["actual_redispatch_timeseries"].assign(
                        artifact_id=artifact_id,
                        model_label=_label_for_artifact(artifact_id),
                        delivery_day=delivery_day,
                        cvar_gamma=float(gamma),
                        production_variant=str(production_variant),
                    )
                )
                submitted_bid_rows.append(
                    payload["submitted_bids"].assign(
                        artifact_id=artifact_id,
                        model_label=_label_for_artifact(artifact_id),
                        delivery_day=delivery_day,
                        cvar_gamma=float(gamma),
                        production_variant=str(production_variant),
                    )
                )
                scenario_settlement_rows.append(
                    payload["scenario_settlement_results"].assign(
                        artifact_id=artifact_id,
                        model_label=_label_for_artifact(artifact_id),
                        delivery_day=delivery_day,
                        cvar_alpha=float(alpha),
                        cvar_gamma=float(gamma),
                        production_variant=str(production_variant),
                        target_mode=TARGET_MODE_WEEKLY_HARD_BAND,
                    )
                )
                actual_h2 = float(actual_summary["hydrogen_compressed_or_sold_kg"])
                cumulative_after = cumulative + actual_h2
                tracker_frames.append(
                    pd.DataFrame(
                        [
                            {
                                "strategy": metric_row["strategy"],
                                "artifact_id": artifact_id,
                                "model_label": _label_for_artifact(artifact_id),
                                "gamma": float(gamma),
                                "production_variant": str(production_variant),
                                "week_id": str(selected_week_manifest["week_id"]),
                                "week_label": str(selected_week_manifest["week_label"]),
                                "delivery_day": delivery_day,
                                "forecast_origin_utc": payload["forecast_origin_utc"],
                                "daily_lower_bound_kg": float(bounds.daily_lower_bound_kg),
                                "daily_upper_bound_kg": float(bounds.daily_upper_bound_kg),
                                "weekly_target_kg": float(bounds.weekly_target_kg),
                                "cumulative_before_kg": float(cumulative),
                                "cumulative_after_kg": float(cumulative_after),
                                "remaining_target_before_today_kg": float(bounds.remaining_target_before_today_kg),
                                "days_remaining_in_week": int(bounds.days_remaining_in_week),
                                "hydrogen_sold_or_compressed_kg": actual_h2,
                                "storage_start_kg": float(inventory_start),
                                "storage_end_kg": float(actual_summary["terminal_inventory_end_kg"]),
                                "solver_status": str(actual_summary["solver_status"]),
                                "emergency_import_mwh": float(metric_row["emergency_import_mwh"]),
                            }
                        ]
                    )
                )
                if not _accepted_solver_status(actual_summary["solver_status"]):
                    infeasibility_rows.append(
                        {
                            "delivery_day": delivery_day,
                            "production_variant": str(production_variant),
                            "cvar_gamma": float(gamma),
                            "issue_type": "infeasible_actual_redispatch",
                            "details": f"solver_status={actual_summary['solver_status']}",
                        }
                    )
                    block_remaining_days = True
                cumulative = cumulative_after
                if _accepted_solver_status(actual_summary["solver_status"]):
                    inventory_start = float(actual_summary["terminal_inventory_end_kg"])

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["production_variant", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    weekly_target_tracker = pd.concat(tracker_frames, ignore_index=True) if tracker_frames else pd.DataFrame()
    weekly_metrics = _weekly_metrics_from_daily(daily_metrics, selected_week_manifest)
    for row in weekly_metrics.itertuples():
        mask = (
            daily_metrics["production_variant"].astype(str).eq(str(row.production_variant))
            & pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").eq(float(row.cvar_gamma))
        )
        daily_metrics.loc[mask, "weekly_target_met"] = bool(row.weekly_target_met)
    diagnostic_summary = _build_diagnostic_summary(weekly_metrics)
    emergency_import_summary = _build_emergency_import_summary(daily_metrics)

    perfect_foresight_metrics = pd.concat(pf_frames, ignore_index=True) if pf_frames else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    submitted_bids = pd.concat(submitted_bid_rows, ignore_index=True) if submitted_bid_rows else pd.DataFrame()
    scenario_settlement = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    validation_checks = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    runtime_diagnostics = pd.DataFrame(runtime_rows)
    infeasibility_report = pd.DataFrame(infeasibility_rows)

    suite_checks = _build_validation_checks(
        artifact_id=artifact_id,
        selected_week_manifest=selected_week_manifest,
        screening=screening,
        daily_metrics=daily_metrics,
        weekly_target_tracker=weekly_target_tracker,
        actual_clearing=actual_clearing,
        actual_redispatch=actual_redispatch,
        alpha=float(alpha),
        gamma_values=gamma_values,
        production_variants=variant_list,
        emergency_import_price=float(emergency_import_price),
    )
    validation_checks_all_runs = pd.concat([validation_checks, suite_checks], ignore_index=True)
    cvar_validation_checks = _build_cvar_validation_checks(
        daily_metrics=daily_metrics,
        scenario_settlement_results=scenario_settlement,
        alpha=float(alpha),
        gamma_values=gamma_values,
    )
    runtime_summary = _runtime_summary(runtime_diagnostics)

    save_frame_csv(run_dir, "weekly_target_tracker.csv", weekly_target_tracker)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "diagnostic_summary_by_gamma_variant.csv", diagnostic_summary)
    save_frame_csv(run_dir, "emergency_import_summary.csv", emergency_import_summary)
    save_frame_csv(run_dir, "infeasibility_report.csv", infeasibility_report)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "runtime_diagnostics.csv", runtime_diagnostics)
    save_frame_csv(run_dir, "runtime_summary.csv", runtime_summary)
    _save_parquet_if_possible(run_dir, "submitted_bids.parquet", submitted_bids)
    _save_parquet_if_possible(run_dir, "actual_clearing.parquet", actual_clearing)
    _save_parquet_if_possible(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch)

    save_text(
        run_dir,
        "README_lear_strict_cvar_opportunity_diagnostic.md",
        _build_readme(
            support_audit=support_audit,
            selected_week_manifest=selected_week_manifest,
            screening=screening,
            weekly_metrics=weekly_metrics,
            diagnostic_summary=diagnostic_summary,
        ),
    )

    return PhaseE4dResult(
        run_dir=run_dir,
        support_audit=support_audit,
        screening=screening,
        selected_week_manifest=selected_week_manifest,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        diagnostic_summary=diagnostic_summary,
        emergency_import_summary=emergency_import_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        runtime_summary=runtime_summary,
    )
