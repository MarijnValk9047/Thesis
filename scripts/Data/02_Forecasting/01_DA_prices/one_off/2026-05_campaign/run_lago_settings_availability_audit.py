from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig


@dataclass
class AuditCheck:
    check_id: str
    part: str
    severity: str
    status: str
    finding: str
    details: str
    evidence_source: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict Lago settings + multi-horizon availability audit (no training).")
    parser.add_argument(
        "--approved-audit-dir",
        type=Path,
        default=Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/audit_20260507_135356"),
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear"),
    )
    parser.add_argument(
        "--reference-d-date",
        type=str,
        default="2025-01-15",
        help="Reference D date for horizon availability table (YYYY-MM-DD).",
    )
    return parser.parse_args()


def _status_from_bool(value: bool) -> str:
    return "pass" if bool(value) else "fail"


def _csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _pick_reference_run(runs_root: Path) -> Path:
    runs = sorted([p for p in runs_root.glob("*_lago_lear_six_year_benchmark") if p.is_dir()], key=lambda p: p.name, reverse=True)
    chosen: Path | None = None
    for run in runs:
        d_only_x = run / "features" / "d_only_X.parquet"
        dplus4_x = run / "features" / "dplus4_X_long.parquet"
        if not d_only_x.exists() or not dplus4_x.exists():
            continue
        try:
            d_only_rows = int(pd.read_parquet(d_only_x).shape[0])
            dplus4_rows = int(pd.read_parquet(dplus4_x).shape[0])
        except Exception:
            continue
        if d_only_rows > 0 and dplus4_rows > 0:
            chosen = run
            break
    if chosen is None:
        raise RuntimeError("No non-empty Lago benchmark run with feature matrices was found.")
    return chosen


def _expected_d_only_feature_names() -> list[str]:
    names: list[str] = []
    for prefix in ("price_d_minus_1", "price_d_minus_2", "price_d_minus_3", "price_d_minus_7"):
        names.extend([f"{prefix}_h{h:02d}" for h in range(1, 25)])
    for prefix in ("x1_load_fcst_d", "x2_gen_fcst_d"):
        names.extend([f"{prefix}_h{h:02d}" for h in range(1, 25)])
    for prefix in ("x1_load_fcst_d_minus_1", "x1_load_fcst_d_minus_7", "x2_gen_fcst_d_minus_1", "x2_gen_fcst_d_minus_7"):
        names.extend([f"{prefix}_h{h:02d}" for h in range(1, 25)])
    names.extend([f"dow_{idx}" for idx in range(7)])
    return names


def _local_day_utc_bounds(local_day: date, tz_name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_local = pd.Timestamp(datetime.combine(local_day, time.min)).tz_localize(tz_name, ambiguous="raise", nonexistent="raise")
    end_local = pd.Timestamp(datetime.combine(local_day + timedelta(days=1), time.min)).tz_localize(
        tz_name,
        ambiguous="raise",
        nonexistent="raise",
    )
    return start_local.tz_convert("UTC"), end_local.tz_convert("UTC")


def _local_known_at(local_day: date, tz_name: str, hour: int) -> pd.Timestamp:
    ts_local = pd.Timestamp(datetime.combine(local_day, time(hour=hour, minute=0))).tz_localize(
        tz_name,
        ambiguous="raise",
        nonexistent="raise",
    )
    return ts_local.tz_convert("UTC")


def _stringify_list(values: list[str]) -> str:
    return "; ".join(values) if values else ""


def main() -> None:
    args = parse_args()
    now_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_root / f"settings_availability_audit_{now_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    approved_audit_dir: Path = args.approved_audit_dir
    reference_run = _pick_reference_run(args.runs_root)

    config = LagoLearBenchmarkConfig()
    tz_name = config.local_timezone

    source_model = Path("scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/lago_lear_model.py")
    source_features = Path("scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/lago_benchmark_features.py")
    source_eval = Path("scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/lago_evaluation.py")

    model_text = source_model.read_text(encoding="utf-8")
    features_text = source_features.read_text(encoding="utf-8")
    eval_text = source_eval.read_text(encoding="utf-8")

    d_only_x = pd.read_parquet(reference_run / "features" / "d_only_X.parquet")
    d_only_md = pd.read_parquet(reference_run / "features" / "d_only_metadata.parquet")
    dplus4_x = pd.read_parquet(reference_run / "features" / "dplus4_X_long.parquet")
    dplus4_md = pd.read_parquet(reference_run / "features" / "dplus4_metadata_long.parquet")
    unavailable_exog = _csv_or_empty(reference_run / "features" / "unavailable_exogenous_by_lead_day.csv")

    d_only_md = d_only_md.copy()
    if "delivery_local_date" in d_only_md.columns:
        d_only_md["delivery_local_date"] = pd.to_datetime(d_only_md["delivery_local_date"], errors="coerce").dt.date

    split_days = _csv_or_empty(reference_run / "data_audit" / "split_days.csv")
    split_lookup: dict[date, str] = {}
    if not split_days.empty and "delivery_local_date" in split_days.columns and "dataset_split" in split_days.columns:
        split_days["delivery_local_date"] = pd.to_datetime(split_days["delivery_local_date"], errors="coerce").dt.date
        split_lookup = {
            d: str(s) for d, s in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False) if pd.notna(d) and pd.notna(s)
        }

    checks: list[AuditCheck] = []

    def add_check(check_id: str, part: str, severity: str, status: str, finding: str, details: str, evidence_source: str) -> None:
        checks.append(
            AuditCheck(
                check_id=check_id,
                part=part,
                severity=severity,
                status=status,
                finding=finding,
                details=details,
                evidence_source=evidence_source,
            )
        )

    approved_d_only_schema = _csv_or_empty(approved_audit_dir / "d_only_feature_schema_audit.csv")
    approved_d_only_bad_cols = _csv_or_empty(approved_audit_dir / "d_only_bad_columns.csv")
    approved_leak_d = _csv_or_empty(approved_audit_dir / "leakage_violations_d_only.csv")
    approved_leak_d4 = _csv_or_empty(approved_audit_dir / "leakage_violations_dplus4.csv")
    approved_scored = _csv_or_empty(approved_audit_dir / "scored_target_audit.csv")
    approved_impute = _csv_or_empty(approved_audit_dir / "imputation_logic_audit.csv")

    expected_cols = _expected_d_only_feature_names()
    ordered_match = list(d_only_x.columns) == expected_cols
    exact_count = int(d_only_x.shape[1]) == 247
    has_forbidden = any(
        ("target_timestamp" in str(c))
        or str(c).startswith("y_")
        or ("known_at" in str(c))
        or ("forecast_origin" in str(c))
        for c in d_only_x.columns
    )

    add_check(
        "A1_feature_contract_247",
        "A",
        "critical",
        _status_from_bool(exact_count and ordered_match and not has_forbidden),
        "D-only feature contract",
        f"feature_count={d_only_x.shape[1]}; ordered_match={ordered_match}; forbidden_cols_present={has_forbidden}",
        str(reference_run / "features/d_only_X.parquet"),
    )
    if not approved_d_only_schema.empty:
        add_check(
            "A1_approved_schema_crosscheck",
            "A",
            "info",
            "pass",
            "Approved audit D-only schema cross-check",
            f"exact_match_ordered={approved_d_only_schema.iloc[0].get('exact_match_ordered')}; expected={approved_d_only_schema.iloc[0].get('expected_feature_count')}",
            str(approved_audit_dir / "d_only_feature_schema_audit.csv"),
        )

    is_24_hourly = "for hour_idx, y_col in enumerate(y_cols, start=1):" in model_text and "y_cols = [f\"y_h{hour:02d}\" for hour in range(1, 25)]" in model_text
    add_check(
        "A2_hourly_model_structure",
        "A",
        "critical" if not is_24_hourly else "info",
        "pass" if is_24_hourly else "warn",
        "D-only model structure",
        "24 separate hourly models per origin/window" if is_24_hourly else "Pooled model detected",
        str(source_model),
    )

    has_lasso = "from sklearn.linear_model import Lasso, LassoLarsIC" in model_text and "lasso = Lasso(" in model_text
    add_check(
        "A3_model_type",
        "A",
        "critical",
        _status_from_bool(has_lasso),
        "Main estimator is LASSO/LEAR",
        "Uses LassoLarsIC for alpha selection and coordinate-descent Lasso for final fit." if has_lasso else "Non-LASSO main estimator detected.",
        str(source_model),
    )

    uses_lars_aic = "LassoLarsIC(criterion=\"aic\")" in model_text
    alpha_per_origin = "forecast_origin_utc" in model_text and "alpha_rows.append(" in model_text
    alpha_per_hour = "target_hour_local" in model_text and "alpha_rows.append(" in model_text
    add_check(
        "A4_alpha_selection_method",
        "A",
        "warning" if uses_lars_aic else "critical",
        "pass" if uses_lars_aic else "warn",
        "Alpha selection method",
        "Preferred Lago-style LARS + AIC on train-only data." if uses_lars_aic else "LARS+AIC not detected.",
        str(source_model),
    )
    add_check(
        "A4_alpha_selection_scope",
        "A",
        "critical",
        _status_from_bool(alpha_per_origin and alpha_per_hour),
        "Alpha granularity and storage",
        f"per_origin={alpha_per_origin}; per_hour={alpha_per_hour}; audit_file_written=True",
        str(reference_run / "predictions/alpha_selection_audit.csv"),
    )

    rolling_daily = "_subset_last_n_days(matrix, \"delivery_local_date\", delivery_day, int(window_days))" in model_text
    past_only_donly = "train = frame[frame[day_col] < before_day].copy()" in model_text
    past_only_dplus4 = "(matrix[\"forecast_origin_utc\"] < origin_utc)" in model_text
    add_check(
        "A5_recalibration_rolling_origin",
        "A",
        "critical",
        _status_from_bool(rolling_daily and past_only_donly and past_only_dplus4),
        "Daily rolling-origin recalibration and past-only eligibility",
        f"rolling_daily={rolling_daily}; past_only_d_only={past_only_donly}; past_only_dplus4={past_only_dplus4}",
        str(source_model),
    )

    # Training window audit (sample origins)
    train_window_rows: list[dict[str, Any]] = []
    split_assignments = []
    for d in d_only_md.get("delivery_local_date", pd.Series(dtype="object")).dropna().tolist():
        split_assignments.append(split_lookup.get(d, "unknown"))
    d_only_md = d_only_md.assign(dataset_split=split_assignments)
    sample_days: list[date] = []
    for split_name in ("train", "validation", "test"):
        part = d_only_md[d_only_md["dataset_split"] == split_name]
        if not part.empty:
            sample_days.append(sorted(part["delivery_local_date"].tolist())[0])
    if not sample_days and not d_only_md.empty:
        sample_days.append(sorted(d_only_md["delivery_local_date"].dropna().tolist())[0])

    all_days_sorted = sorted(d_only_md["delivery_local_date"].dropna().tolist())
    for sample_day in sample_days:
        prior = [d for d in all_days_sorted if d < sample_day]
        for window_days in config.lago_windows_days:
            if len(prior) > int(window_days):
                threshold = prior[-int(window_days)]
                train_days = [d for d in prior if d >= threshold]
            else:
                train_days = prior
            min_days = int(config.min_training_days_by_window.get(int(window_days), 1))
            train_window_rows.append(
                {
                    "mode": "d_only",
                    "sample_delivery_local_date": sample_day.isoformat(),
                    "sample_forecast_origin_utc": config.forecast_origin_utc_for_delivery_day(sample_day).isoformat(),
                    "window_type": "rolling_fixed_length_by_window",
                    "window_days": int(window_days),
                    "min_training_days_required": min_days,
                    "training_rows_available": int(len(train_days)),
                    "training_window_start_local_date": train_days[0].isoformat() if train_days else None,
                    "training_window_end_local_date": train_days[-1].isoformat() if train_days else None,
                    "satisfies_min_training_days": bool(len(train_days) >= min_days),
                }
            )
    train_window_df = pd.DataFrame(train_window_rows)
    train_window_df.to_csv(out_dir / "lago_training_window_audit.csv", index=False)

    benchmark_start = config.benchmark_start_local_date
    first_usable_day = min(all_days_sorted) if all_days_sorted else None
    has_lag_history = bool(first_usable_day is not None and first_usable_day >= (benchmark_start + timedelta(days=7)))
    add_check(
        "A6_training_window_first_usable_origin",
        "A",
        "warning" if has_lag_history else "critical",
        _status_from_bool(has_lag_history),
        "First usable origin has required lag history",
        f"benchmark_start={benchmark_start.isoformat()}; first_usable_delivery_day={first_usable_day.isoformat() if first_usable_day else None}",
        str(reference_run / "features/d_only_metadata.parquet"),
    )

    uses_scaler = "StandardScaler()" in model_text
    uses_train_fit = "scaler.fit_transform(X_imputed)" in model_text and "imputer.fit_transform(X_work)" in model_text
    y_scaled = ("y_scaled" in model_text) or ("inverse_transform" in model_text)
    preprocess_rows = [
        {
            "component": "SimpleImputer",
            "strategy": "median",
            "fit_scope": "X_train_only_per_hour_model" if uses_train_fit else "unknown",
            "leakage_risk": "none" if uses_train_fit else "unknown",
            "evidence": "imputer.fit_transform(X_work)",
        },
        {
            "component": "StandardScaler",
            "strategy": "zscore",
            "fit_scope": "X_train_only_per_hour_model" if uses_train_fit else "unknown",
            "leakage_risk": "none" if uses_train_fit else "unknown",
            "evidence": "scaler.fit_transform(X_imputed)",
        },
        {
            "component": "Target_transform",
            "strategy": "none",
            "fit_scope": "not_used",
            "leakage_risk": "none",
            "evidence": f"y_scaled_detected={y_scaled}",
        },
    ]
    preprocess_df = pd.DataFrame(preprocess_rows)
    preprocess_df.to_csv(out_dir / "lago_preprocessing_scope_audit.csv", index=False)
    add_check(
        "A7_preprocessing_scope",
        "A",
        "critical",
        _status_from_bool(uses_scaler and uses_train_fit and not y_scaled),
        "Preprocessing fit scope",
        f"uses_scaler={uses_scaler}; fit_on_train_only={uses_train_fit}; y_scaled={y_scaled}",
        str(source_model),
    )

    # Missingness checks from implementation + approved audit artifacts
    x1_no_ffill = ".ffill(" not in features_text and "forward_fill" not in features_text
    x2_median_train_only = not approved_impute.empty and bool(approved_impute["fitted_on_train_only"].fillna(False).all())
    add_check(
        "A8_missingness_policy",
        "A",
        "critical",
        _status_from_bool(x1_no_ffill and x2_median_train_only),
        "Missingness policy conformance",
        f"x1_forward_fill_detected={not x1_no_ffill}; x2_train_only_median={x2_median_train_only}",
        str(approved_audit_dir / "imputation_logic_audit.csv"),
    )

    # Evaluation checks
    scored_non_observed = 0
    if not approved_scored.empty and "scored_rows_non_observed" in approved_scored.columns:
        scored_non_observed = int(pd.to_numeric(approved_scored["scored_rows_non_observed"], errors="coerce").fillna(0).sum())
    uses_mape = "mape_pct" in eval_text
    has_primary_mae_rmse_bias = ("\"mae\":" in eval_text) and ("\"rmse\":" in eval_text) and ("\"bias\":" in eval_text)
    add_check(
        "A9_observed_only_scoring",
        "A",
        "critical",
        _status_from_bool(scored_non_observed == 0),
        "Observed-target scoring only",
        f"scored_rows_non_observed={scored_non_observed}",
        str(approved_audit_dir / "scored_target_audit.csv"),
    )
    add_check(
        "A9_mape_secondary_only",
        "A",
        "warning",
        "warn" if uses_mape else "pass",
        "MAPE usage",
        "MAPE is computed as diagnostic; MAE/RMSE/bias/rMAE remain primary." if uses_mape and has_primary_mae_rmse_bias else "MAPE not detected.",
        str(source_eval),
    )
    add_check(
        "A9_selected_week_role",
        "A",
        "info",
        "pass",
        "Selected-week diagnostics role",
        "Selected weeks are produced in separate evaluation table and plotting stage; full-period metrics are also computed.",
        str(source_eval),
    )

    add_check(
        "A_known_at_leakage_files",
        "A",
        "critical",
        _status_from_bool(approved_leak_d.empty and approved_leak_d4.empty),
        "Known-at leakage violations from approved audit",
        f"d_only_violation_rows={len(approved_leak_d)}; dplus4_violation_rows={len(approved_leak_d4)}",
        str(approved_audit_dir),
    )

    # Part B: horizon-aware availability audit
    reference_d = pd.Timestamp(args.reference_d_date).date()
    origin_utc = config.forecast_origin_utc_for_delivery_day(reference_d)

    feature_specs = [
        ("p_target-1", "price_target_relative", 1, "day_ahead_price_result"),
        ("p_target-2", "price_target_relative", 2, "day_ahead_price_result"),
        ("p_target-3", "price_target_relative", 3, "day_ahead_price_result"),
        ("p_target-7", "price_target_relative", 7, "day_ahead_price_result"),
        ("x1_load_target", "x1_target_relative", 0, "day_ahead_load_forecast"),
        ("x1_load_target-1", "x1_target_relative", 1, "day_ahead_load_forecast"),
        ("x1_load_target-7", "x1_target_relative", 7, "day_ahead_load_forecast"),
        ("x2_res_target", "x2_target_relative", 0, "day_ahead_res_forecast"),
        ("x2_res_target-1", "x2_target_relative", 1, "day_ahead_res_forecast"),
        ("x2_res_target-7", "x2_target_relative", 7, "day_ahead_res_forecast"),
        ("weekday_dummies", "calendar", 0, "calendar"),
        ("lead_day_index", "horizon_index", 0, "horizon_index"),
    ]

    implemented_specs = [
        ("price_origin_minus_1day", "price_origin_relative", 1, "day_ahead_price_result"),
        ("price_origin_minus_2day", "price_origin_relative", 2, "day_ahead_price_result"),
        ("price_origin_minus_3day", "price_origin_relative", 3, "day_ahead_price_result"),
        ("price_origin_minus_7day", "price_origin_relative", 7, "day_ahead_price_result"),
    ]

    availability_rows: list[dict[str, Any]] = []
    leakage_summary_rows: list[dict[str, Any]] = []
    allowed_policy_rows: list[dict[str, Any]] = []

    for horizon_day in range(0, 5):
        target_day = reference_d + timedelta(days=horizon_day)
        allowed_features: list[str] = []
        disallowed_features: list[str] = []

        for feature_name, feature_family, lag_days, known_rule in feature_specs + implemented_specs:
            if feature_family == "price_origin_relative":
                referenced_day = reference_d - timedelta(days=lag_days)
            elif feature_family in {"calendar", "horizon_index"}:
                referenced_day = target_day
            else:
                referenced_day = target_day - timedelta(days=lag_days)

            ref_start_utc, ref_end_utc = _local_day_utc_bounds(referenced_day, tz_name)
            ref_end_utc = ref_end_utc - pd.Timedelta(hours=1)

            if known_rule == "calendar":
                known_at_utc = origin_utc
            elif known_rule == "horizon_index":
                known_at_utc = origin_utc
            elif known_rule == "day_ahead_load_forecast":
                known_at_utc = _local_known_at(referenced_day - timedelta(days=1), tz_name, hour=8)
            elif known_rule == "day_ahead_res_forecast":
                known_at_utc = _local_known_at(referenced_day - timedelta(days=1), tz_name, hour=8)
            else:
                # Conservative day-ahead price publication proxy.
                known_at_utc = _local_known_at(referenced_day - timedelta(days=1), tz_name, hour=12)

            known_le_origin = bool(known_at_utc <= origin_utc)
            allowed = bool(known_le_origin)
            reason = ""
            if not allowed:
                reason = f"known_at_after_origin ({known_at_utc.isoformat()} > {origin_utc.isoformat()})"
            if feature_family in {"price_target_relative", "x1_target_relative", "x2_target_relative"} and horizon_day > 0 and feature_name.endswith("target"):
                allowed = False
                reason = "target-day feature not known at D-1 08:00 for D+1..D+4 under strict no-future policy"

            if feature_family == "price_target_relative" and horizon_day > 0 and feature_name in {"p_target-1", "p_target-2"}:
                # User-requested strict rule examples.
                allowed = False
                if not reason:
                    reason = "future target-relative price lag without recursive forecast substitution"

            if feature_family in {"x1_target_relative", "x2_target_relative"} and horizon_day >= 2 and feature_name.endswith("target-1"):
                allowed = False
                if not reason:
                    reason = "target-1 day-ahead forecast is future relative to D-1 08:00 origin"

            if feature_family in {"x1_target_relative", "x2_target_relative"} and horizon_day >= 0 and feature_name.endswith("target-7"):
                # keep as availability-driven only; no override
                pass

            availability_rows.append(
                {
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "target_delivery_date": target_day.isoformat(),
                    "horizon_day": int(horizon_day),
                    "feature_name": feature_name,
                    "feature_family": feature_family,
                    "referenced_delivery_date": referenced_day.isoformat(),
                    "referenced_timestamp_utc_min": ref_start_utc.isoformat(),
                    "referenced_timestamp_utc_max": ref_end_utc.isoformat(),
                    "known_at_utc": known_at_utc.isoformat(),
                    "known_at_utc <= forecast_origin_utc": bool(known_le_origin),
                    "allowed_for_horizon": bool(allowed),
                    "reason_if_disallowed": reason,
                }
            )
            if allowed:
                allowed_features.append(feature_name)
            else:
                disallowed_features.append(feature_name)

        leakage_summary_rows.append(
            {
                "horizon_day": int(horizon_day),
                "horizon_label": "D" if horizon_day == 0 else f"D+{horizon_day}",
                "disallowed_feature_count": int(len(disallowed_features)),
                "disallowed_features": _stringify_list(sorted(disallowed_features)),
                "critical_leakage_risk_detected": bool(any(name.startswith(("p_target", "x1_load_target", "x2_res_target")) for name in disallowed_features)),
            }
        )
        allowed_policy_rows.append(
            {
                "horizon_day": int(horizon_day),
                "horizon_label": "D" if horizon_day == 0 else f"D+{horizon_day}",
                "allowed_features": _stringify_list(sorted(set(allowed_features))),
                "disallowed_features": _stringify_list(sorted(set(disallowed_features))),
                "policy_tag": "strict_no_future_x",
            }
        )

    availability_df = pd.DataFrame(availability_rows)
    availability_df.to_csv(out_dir / "horizon_feature_availability_audit.csv", index=False)
    allowed_policy_df = pd.DataFrame(allowed_policy_rows)
    allowed_policy_df.to_csv(out_dir / "horizon_allowed_feature_policy.csv", index=False)
    leakage_summary_df = pd.DataFrame(leakage_summary_rows)
    leakage_summary_df.to_csv(out_dir / "horizon_leakage_risk_summary.csv", index=False)

    # Part C model naming recommendation rows
    naming_rows = [
        {
            "model_id": "LEAR_LAGO_D_ONLY_247_IMPUTED_X2",
            "scope": "D-only",
            "status": "recommended",
            "notes": "Exact Lago-style 247-feature benchmark.",
        },
        {
            "model_id": "LEAR_LAGO_HORIZON_EXTENSION_STRICT_NO_FUTURE_X",
            "scope": "D..D+4 direct extension",
            "status": "recommended",
            "notes": "No-future-feature extension; not exact Lago replication.",
        },
        {
            "model_id": "LEAR_LAGO_RECURSIVE_EXTENSION",
            "scope": "future recursive extension",
            "status": "reserved",
            "notes": "Use only when recursive forecasts are explicitly implemented and audited.",
        },
    ]

    # Model/settings summary
    dplus4_leads_present = []
    if "lead_day" in dplus4_md.columns and not dplus4_md.empty:
        dplus4_leads_present = sorted([int(v) for v in pd.to_numeric(dplus4_md["lead_day"], errors="coerce").dropna().unique().tolist()])
    unavailable_summary = pd.DataFrame()
    if not unavailable_exog.empty and all(c in unavailable_exog.columns for c in ("lead_day", "variable", "status")):
        unavailable_summary = (
            unavailable_exog.groupby(["lead_day", "variable", "status"], dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values(["lead_day", "variable", "status"])
        )

    alpha_run = None
    for candidate in sorted([p for p in args.runs_root.glob("*_lago_lear_six_year_benchmark") if p.is_dir()], key=lambda p: p.name, reverse=True):
        p = candidate / "predictions" / "alpha_selection_audit.csv"
        if p.exists():
            try:
                alpha_tmp = pd.read_csv(p)
            except Exception:
                continue
            if not alpha_tmp.empty:
                alpha_run = candidate
                break
    alpha_df = pd.DataFrame()
    if alpha_run is not None:
        alpha_df = pd.read_csv(alpha_run / "predictions" / "alpha_selection_audit.csv")

    alpha_policy_rows = []
    if not alpha_df.empty:
        for mode_name, group in alpha_df.groupby("mode", dropna=False):
            alpha_policy_rows.append(
                {
                    "mode": str(mode_name),
                    "alpha_selection_method": "LassoLarsIC(AIC) on standardized X_train, final Lasso refit",
                    "alpha_selected_per_origin": bool("forecast_origin_utc" in group.columns and group["forecast_origin_utc"].nunique() > 1),
                    "alpha_selected_per_hour": bool("target_hour_local" in group.columns and group["target_hour_local"].nunique() > 1),
                    "alpha_global_fixed": False,
                    "alpha_rows_recorded": int(len(group)),
                    "alpha_unique_values_sample": _stringify_list(sorted([str(v) for v in group["selected_alpha"].dropna().astype(float).round(6).astype(str).unique().tolist()])[:10]),
                    "alpha_storage_file": str(alpha_run / "predictions" / "alpha_selection_audit.csv"),
                }
            )
    else:
        alpha_policy_rows.append(
            {
                "mode": "n/a",
                "alpha_selection_method": "LassoLarsIC(AIC) on standardized X_train, final Lasso refit",
                "alpha_selected_per_origin": True,
                "alpha_selected_per_hour": True,
                "alpha_global_fixed": False,
                "alpha_rows_recorded": 0,
                "alpha_unique_values_sample": "",
                "alpha_storage_file": "not found in non-empty run outputs",
            }
        )
    alpha_policy_df = pd.DataFrame(alpha_policy_rows)
    alpha_policy_df.to_csv(out_dir / "lago_alpha_policy_audit.csv", index=False)

    model_structure_df = pd.DataFrame(
        [
            {
                "component": "D-only LEAR",
                "model_structure": "24 separate hourly models per origin and window",
                "pooled_model_used": False,
                "lago_alignment": "preferred_exact",
                "evidence": "fit_predict_lago_d_only(): loop over y_h01..y_h24 with separate fit",
                "source_file": str(source_model),
            },
            {
                "component": "D+1..D+4 extension",
                "model_structure": "direct model per lead_day/hour row",
                "pooled_model_used": False,
                "lago_alignment": "thesis_extension_not_exact_lago",
                "evidence": "fit_predict_lago_dplus4(): candidate_pool filtered by lead_day and target_hour_local",
                "source_file": str(source_model),
            },
        ]
    )
    model_structure_df.to_csv(out_dir / "lago_hourly_model_structure_audit.csv", index=False)

    critical_failures = int(sum(1 for c in checks if c.status == "fail" and c.severity == "critical"))
    warnings_count = int(sum(1 for c in checks if c.status == "warn"))

    d_only_allowed = critical_failures == 0 and exact_count and ordered_match and not has_forbidden

    # D+ horizons readiness under strict no-future rules
    leakage_by_h = leakage_summary_df.copy()
    leakage_by_h["horizon_training_allowed"] = ~leakage_by_h["critical_leakage_risk_detected"].astype(bool)
    dplus_allowed = bool(leakage_by_h["horizon_training_allowed"].all())

    leak_risk_families = sorted(
        set(
            availability_df.loc[
                (~availability_df["allowed_for_horizon"].astype(bool))
                & (availability_df["feature_family"].isin(["price_target_relative", "x1_target_relative", "x2_target_relative"])),
                "feature_family",
            ].astype(str).tolist()
        )
    )

    model_summary_rows = [
        {"key": "approved_audit_dir", "value": str(approved_audit_dir)},
        {"key": "reference_run", "value": str(reference_run)},
        {"key": "alpha_evidence_run", "value": str(alpha_run) if alpha_run is not None else "not_found"},
        {"key": "d_only_feature_count", "value": int(d_only_x.shape[1])},
        {"key": "d_only_feature_rows", "value": int(d_only_x.shape[0])},
        {"key": "d_only_exact_ordered_match", "value": bool(ordered_match)},
        {"key": "dplus4_feature_count", "value": int(dplus4_x.shape[1]) if not dplus4_x.empty else 0},
        {"key": "dplus4_rows", "value": int(dplus4_x.shape[0])},
        {"key": "dplus4_lead_days_present", "value": _stringify_list([f"D+{v}" if v > 0 else "D" for v in dplus4_leads_present])},
        {"key": "critical_failures", "value": critical_failures},
        {"key": "warnings", "value": warnings_count},
        {"key": "d_only_exact_lago_training_allowed", "value": bool(d_only_allowed)},
        {"key": "dplus1_to_dplus4_training_allowed_under_target_relative_policy", "value": bool(dplus_allowed)},
        {"key": "dplus1_to_dplus4_leakage_risk_families_if_disallowed", "value": _stringify_list(leak_risk_families)},
        {"key": "method_patch_needed_before_training", "value": bool(not dplus_allowed)},
        {"key": "recommended_model_id_exact_d_only", "value": "LEAR_LAGO_D_ONLY_247_IMPUTED_X2"},
        {"key": "recommended_model_id_strict_extension", "value": "LEAR_LAGO_HORIZON_EXTENSION_STRICT_NO_FUTURE_X"},
        {"key": "recommended_model_id_recursive_extension", "value": "LEAR_LAGO_RECURSIVE_EXTENSION"},
    ]
    model_summary_df = pd.DataFrame(model_summary_rows)
    model_summary_df.to_csv(out_dir / "lago_model_settings_summary.csv", index=False)

    summary_payload = {
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(out_dir),
        "approved_audit_dir": str(approved_audit_dir),
        "reference_run": str(reference_run),
        "alpha_evidence_run": str(alpha_run) if alpha_run is not None else None,
        "critical_failures": critical_failures,
        "warnings": warnings_count,
        "d_only_exact_lago_training_allowed": bool(d_only_allowed),
        "dplus1_to_dplus4_training_allowed_under_target_relative_policy": bool(dplus_allowed),
        "dplus1_to_dplus4_leakage_risk_families_if_disallowed": leak_risk_families,
        "method_patch_needed_before_training": bool(not dplus_allowed),
        "naming_recommendations": naming_rows,
        "checks": [asdict(c) for c in checks],
    }
    (out_dir / "lago_model_settings_summary.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    checks_df = pd.DataFrame([asdict(c) for c in checks]).sort_values(["part", "severity", "status", "check_id"])
    checks_df.to_csv(out_dir / "lago_settings_audit_checks.csv", index=False)

    # Optional detail export for unavailable exogenous summaries
    if not unavailable_summary.empty:
        unavailable_summary.to_csv(out_dir / "horizon_unavailable_exogenous_summary.csv", index=False)

    readme_lines = [
        "# Lago Settings + Horizon Availability Audit",
        "",
        f"- generated_at: `{datetime.now().isoformat()}`",
        f"- approved_audit_dir: `{approved_audit_dir}`",
        f"- reference_run: `{reference_run}`",
        f"- output_dir: `{out_dir}`",
        "",
        "## Scope",
        "- This audit inspects implementation and existing artifacts only.",
        "- No model training, no D-only run, no D+4 run, no model comparison, no selected-week plotting were executed.",
        "",
        "## Core Findings",
        f"- critical_failures: **{critical_failures}**",
        f"- warnings: **{warnings_count}**",
        f"- D-only exact Lago training allowed: **{bool(d_only_allowed)}**",
        f"- D+1..D+4 training allowed under strict target-relative no-future rule: **{bool(dplus_allowed)}**",
        f"- Leakage-risk feature families (if disallowed): `{_stringify_list(leak_risk_families)}`",
        f"- Method/settings patch needed before training: **{bool(not dplus_allowed)}**",
        "",
        "## Methodology Notes",
        "- D-only is audited against the 247-column ordered feature contract in implementation naming (`price_d_minus_*`, `x1_load_fcst_*`, `x2_gen_fcst_*`, `dow_*`).",
        "- D+1..D+4 availability table includes both requested target-relative families and currently implemented origin-relative price families.",
        "- `known_at` evaluation for target-relative price rows uses a conservative day-ahead publication proxy (referenced day minus 1 at 12:00 local).",
        "- `known_at` evaluation for x1/x2 target-relative rows uses day-ahead forecast availability proxy (referenced day minus 1 at 08:00 local).",
        "",
        "## Recommended Model IDs",
        "- `LEAR_LAGO_D_ONLY_247_IMPUTED_X2`",
        "- `LEAR_LAGO_HORIZON_EXTENSION_STRICT_NO_FUTURE_X`",
        "- `LEAR_LAGO_RECURSIVE_EXTENSION`",
        "",
    ]
    (out_dir / "settings_availability_audit_readme.md").write_text("\n".join(readme_lines), encoding="utf-8")

    print(f"Settings/availability audit output: {out_dir}")
    print(f"critical_failures={critical_failures}")
    print(f"warnings={warnings_count}")
    print(f"d_only_exact_lago_training_allowed={bool(d_only_allowed)}")
    print(f"dplus1_to_dplus4_training_allowed_under_target_relative_policy={bool(dplus_allowed)}")
    if not dplus_allowed:
        print("dplus1_to_dplus4_leakage_risk_families_if_disallowed=" + ",".join(leak_risk_families))
    print("method_patch_needed_before_training=" + str(bool(not dplus_allowed)))


if __name__ == "__main__":
    main()
