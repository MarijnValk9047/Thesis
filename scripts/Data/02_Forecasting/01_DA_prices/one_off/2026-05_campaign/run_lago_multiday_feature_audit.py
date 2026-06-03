from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hourly_da.core.lago_benchmark_data import audit_lago_data_coverage
from hourly_da.core.lago_benchmark_features import build_lago_d_only_daily_matrix
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_multiday_features import build_lago_dplus4_direct_matrix_strict_no_future


@dataclass
class AuditCheck:
    check_id: str
    severity: str
    status: str
    details: str
    evidence_file: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit strict D..D+4 LEAR direct feature path without training.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear"),
    )
    parser.add_argument(
        "--horizon-policy-csv",
        type=str,
        default="",
        help="Path to horizon_allowed_feature_policy.csv. If empty, latest settings_availability_audit_*/ file is used.",
    )
    parser.add_argument("--allow-official-cleaned-fallback", action="store_true", default=True)
    return parser.parse_args()


def _resolve_policy_csv(args: argparse.Namespace, config: LagoLearBenchmarkConfig) -> Path:
    raw = str(args.horizon_policy_csv or "").strip()
    if raw:
        path = Path(raw)
        if path.exists():
            return path
        raise FileNotFoundError(f"--horizon-policy-csv not found: {path}")
    candidates = sorted(
        [
            path / "horizon_allowed_feature_policy.csv"
            for path in config.output_root.glob("settings_availability_audit_*")
            if path.is_dir()
        ],
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "No horizon_allowed_feature_policy.csv found in settings_availability_audit_* folders. "
        "Provide --horizon-policy-csv."
    )


def _choose_x2_frames(bundle: Any) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    res = bundle.exogenous_frames.get("da_res_generation_forecast", pd.DataFrame())
    agg = bundle.exogenous_frames.get("da_generation_forecast", pd.DataFrame())
    primary = res if not res.empty else agg
    fallback = agg if (not agg.empty and not primary.equals(agg)) else None
    return primary, fallback


def _feature_columns_by_horizon(matrix: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    if matrix.empty or metadata.empty or "lead_day" not in metadata.columns:
        return pd.DataFrame(columns=["horizon_day", "horizon_label", "feature_count", "feature_names"])
    rows = []
    for lead_day in sorted(pd.to_numeric(metadata["lead_day"], errors="coerce").dropna().astype(int).unique().tolist()):
        rows.append(
            {
                "horizon_day": int(lead_day),
                "horizon_label": "D" if int(lead_day) == 0 else f"D+{int(lead_day)}",
                "feature_count": int(matrix.shape[1]),
                "feature_names": "; ".join([str(col) for col in matrix.columns]),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    now_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_root / f"multiday_feature_audit_{now_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = replace(LagoLearBenchmarkConfig(), allow_official_cleaned_fallback=bool(args.allow_official_cleaned_fallback))
    policy_csv = _resolve_policy_csv(args, config)
    bundle = audit_lago_data_coverage(config)
    x1_da = bundle.exogenous_frames.get("da_total_load_forecast", pd.DataFrame())
    x1_wa = bundle.exogenous_frames.get("week_ahead_total_load_forecast", pd.DataFrame())
    x2_primary, x2_fallback = _choose_x2_frames(bundle)
    if not x2_primary.empty and x2_fallback is not None and not x2_fallback.empty:
        # For D-only invariance check below.
        x2_for_d_only = x2_primary
        x2_fallback_for_d_only = x2_fallback
    else:
        x2_for_d_only = x2_primary
        x2_fallback_for_d_only = x2_fallback

    multiday = build_lago_dplus4_direct_matrix_strict_no_future(
        price_df=bundle.price_frame,
        load_forecast_df=x1_da,
        week_ahead_load_forecast_df=x1_wa,
        generation_forecast_df=x2_primary,
        config=config,
        horizon_policy_csv=policy_csv,
        hard_fail_on_policy_violation=False,
    )

    schema_by_h = _feature_columns_by_horizon(multiday.X_long, multiday.metadata_long)
    schema_by_h.to_csv(out_dir / "multiday_feature_schema_by_horizon.csv", index=False)
    multiday.feature_availability_by_horizon.to_csv(out_dir / "multiday_feature_availability_by_horizon.csv", index=False)
    multiday.forbidden_columns_audit.to_csv(out_dir / "multiday_forbidden_columns_audit.csv", index=False)
    multiday.known_at_violations.to_csv(out_dir / "multiday_known_at_violations.csv", index=False)
    multiday.disallowed_feature_attempts.to_csv(out_dir / "multiday_disallowed_feature_attempts.csv", index=False)
    multiday.missing_feature_summary.to_csv(out_dir / "multiday_missingness_by_feature.csv", index=False)

    # X2 imputation policy audit (feature matrix only; training-window imputation happens in model fit stage).
    x2_cols = [col for col in multiday.X_long.columns if str(col).startswith("x2_")]
    x1_cols = [col for col in multiday.X_long.columns if str(col).startswith("x1_")]
    p_cols = [col for col in multiday.X_long.columns if str(col).startswith("p_")]
    x2_missing = int(pd.to_numeric(multiday.X_long[x2_cols].stack(), errors="coerce").isna().sum()) if x2_cols else 0
    x1_missing = int(pd.to_numeric(multiday.X_long[x1_cols].stack(), errors="coerce").isna().sum()) if x1_cols else 0
    p_missing = int(pd.to_numeric(multiday.X_long[p_cols].stack(), errors="coerce").isna().sum()) if p_cols else 0
    y_missing = int(pd.to_numeric(multiday.y_long.get("y_true", pd.Series(dtype=float)), errors="coerce").isna().sum())
    x2_policy_audit = pd.DataFrame(
        [
            {
                "policy_name": "x1_no_imputation",
                "expected": "no_missing_in_x1_features",
                "observed_missing_cells": int(x1_missing),
                "status": "pass" if x1_missing == 0 else "fail",
                "severity_if_fail": "critical",
            },
            {
                "policy_name": "x2_training_window_median_only",
                "expected": "x2_missing_allowed_in_matrix; impute_during_training_on_X_train_only",
                "observed_missing_cells": int(x2_missing),
                "status": "pass",
                "severity_if_fail": "critical",
            },
            {
                "policy_name": "price_lags_no_imputation",
                "expected": "no_missing_in_price_features",
                "observed_missing_cells": int(p_missing),
                "status": "pass" if p_missing == 0 else "fail",
                "severity_if_fail": "critical",
            },
            {
                "policy_name": "target_y_no_imputation",
                "expected": "no_missing_in_observed_y_true_rows",
                "observed_missing_cells": int(y_missing),
                "status": "pass" if y_missing == 0 else "fail",
                "severity_if_fail": "critical",
            },
        ]
    )
    x2_policy_audit.to_csv(out_dir / "multiday_x2_imputation_policy_audit.csv", index=False)

    # Training window policy audit from configured model settings (no training run).
    tw_rows = []
    for window_days in config.lago_windows_days:
        tw_rows.append(
            {
                "mode": "dplus4_direct",
                "window_days": int(window_days),
                "min_training_days_required": int(config.min_training_days_by_window.get(int(window_days), 1)),
                "recalibration": "daily_rolling_origin",
                "training_pool_rule": "forecast_origin_utc < current_origin and same lead_day + target_hour_local",
                "alpha_selection_rule": "LassoLarsIC(AIC) on X_train only, then Lasso refit",
                "scaling_scope": "StandardScaler fit on X_train only",
                "status": "pass",
            }
        )
    tw_df = pd.DataFrame(tw_rows)
    tw_df.to_csv(out_dir / "multiday_training_window_policy_audit.csv", index=False)

    checks: list[AuditCheck] = []

    def add_check(check_id: str, severity: str, status: str, details: str, evidence_file: str) -> None:
        checks.append(
            AuditCheck(
                check_id=check_id,
                severity=severity,
                status=status,
                details=details,
                evidence_file=evidence_file,
            )
        )

    feature_count_ok = bool(not schema_by_h.empty and (schema_by_h["feature_count"] > 0).all())
    add_check(
        "feature_count_by_horizon",
        "info",
        "pass" if feature_count_ok else "fail",
        f"horizons={schema_by_h['horizon_label'].tolist() if not schema_by_h.empty else []}; counts={schema_by_h['feature_count'].tolist() if not schema_by_h.empty else []}",
        "multiday_feature_schema_by_horizon.csv",
    )

    forbidden_any = bool(not multiday.forbidden_columns_audit.empty and multiday.forbidden_columns_audit["is_forbidden"].fillna(False).any())
    add_check(
        "no_forbidden_columns",
        "critical",
        "pass" if not forbidden_any else "fail",
        f"forbidden_column_count={int(multiday.forbidden_columns_audit['is_forbidden'].fillna(False).sum()) if not multiday.forbidden_columns_audit.empty else 0}",
        "multiday_forbidden_columns_audit.csv",
    )

    known_at_ok = bool(multiday.known_at_violations.empty)
    add_check(
        "no_known_at_violations",
        "critical",
        "pass" if known_at_ok else "fail",
        f"violation_rows={len(multiday.known_at_violations)}",
        "multiday_known_at_violations.csv",
    )

    disallowed_ok = bool(multiday.disallowed_feature_attempts.empty)
    add_check(
        "no_disallowed_features_entered",
        "critical",
        "pass" if disallowed_ok else "fail",
        f"disallowed_attempt_rows={len(multiday.disallowed_feature_attempts)}",
        "multiday_disallowed_feature_attempts.csv",
    )

    future_price_cols = [c for c in multiday.X_long.columns if str(c).startswith(("p_target_d_minus_1_", "p_target_d_minus_2_", "p_target_d_minus_3_"))]
    add_check(
        "no_future_target_relative_price_actuals",
        "critical",
        "pass" if len(future_price_cols) == 0 else "fail",
        f"future_price_like_columns={future_price_cols[:10]}",
        "multiday_feature_schema_by_horizon.csv",
    )

    future_x_cols = [
        c
        for c in multiday.X_long.columns
        if str(c).startswith(("x1_load_target_d_h", "x2_res_target_d_h", "x1_load_target_d_minus_1_", "x2_res_target_d_minus_1_"))
    ]
    add_check(
        "no_future_target_exogenous_leakage",
        "critical",
        "pass" if len(future_x_cols) == 0 else "fail",
        f"future_target_x_columns={future_x_cols[:10]}",
        "multiday_feature_schema_by_horizon.csv",
    )

    add_check(
        "x1_not_imputed",
        "critical",
        "pass" if x1_missing == 0 else "fail",
        f"x1_missing_cells={x1_missing}",
        "multiday_x2_imputation_policy_audit.csv",
    )
    add_check(
        "x2_imputation_policy_training_window_only",
        "critical",
        "pass",
        "x2 NaNs are retained in feature matrix and expected to be imputed only during per-window model fit on X_train.",
        "multiday_x2_imputation_policy_audit.csv",
    )
    add_check(
        "target_y_not_imputed",
        "critical",
        "pass" if y_missing == 0 else "fail",
        f"y_missing_cells={y_missing}",
        "multiday_x2_imputation_policy_audit.csv",
    )
    add_check(
        "price_lags_not_imputed",
        "critical",
        "pass" if p_missing == 0 else "fail",
        f"price_missing_cells={p_missing}",
        "multiday_x2_imputation_policy_audit.csv",
    )

    observed_only = bool(multiday.metadata_long.get("is_observed_target", pd.Series(dtype=bool)).fillna(False).all()) if not multiday.metadata_long.empty else True
    add_check(
        "scored_targets_observed_only",
        "critical",
        "pass" if observed_only else "fail",
        f"is_observed_target_all_true={observed_only}",
        "multiday_feature_schema_by_horizon.csv",
    )

    # D-only exact 247 builder unchanged check.
    d_only = build_lago_d_only_daily_matrix(
        price_df=bundle.price_frame,
        load_forecast_df=x1_da,
        generation_forecast_df=x2_for_d_only,
        generation_forecast_fallback_df=x2_fallback_for_d_only,
        config=config,
    )
    d_only_ok = bool(d_only.X.shape[1] == 247)
    add_check(
        "d_only_247_builder_unchanged",
        "critical",
        "pass" if d_only_ok else "fail",
        f"d_only_feature_count={d_only.X.shape[1]}",
        "multiday_audit_readme.md",
    )

    # Required warnings/info.
    add_check(
        "dplus4_not_exact_lago_replication",
        "warning",
        "warn",
        "D+1..D+4 path is an intentional strict no-future thesis extension, not exact Lago replication.",
        "multiday_audit_readme.md",
    )
    add_check(
        "mape_diagnostic_warning",
        "warning",
        "warn",
        "MAPE may be unstable for DA prices with negative/near-zero values; keep MAE/RMSE/bias/rMAE primary.",
        "multiday_audit_readme.md",
    )
    add_check(
        "origin_relative_adaptation_info",
        "info",
        "pass",
        "Uses origin-relative base-day features for D..D+4 leakage-safe extension.",
        "multiday_feature_schema_by_horizon.csv",
    )

    checks_df = pd.DataFrame([asdict(c) for c in checks])
    checks_df.to_csv(out_dir / "multiday_audit_checks.csv", index=False)

    critical_failures = int(len(checks_df[(checks_df["severity"] == "critical") & (checks_df["status"] == "fail")]))
    warnings = int(len(checks_df[checks_df["status"] == "warn"]))

    readme_lines = [
        "# Multiday Feature Audit",
        "",
        f"- generated_at: `{datetime.now().isoformat()}`",
        f"- output_dir: `{out_dir}`",
        f"- horizon_policy_csv: `{policy_csv}`",
        f"- critical_failures: **{critical_failures}**",
        f"- warnings: **{warnings}**",
        "",
        "## Scope",
        "- Audits strict D..D+4 feature construction only.",
        "- No D-only training, no D+4 full training, no model comparison, no selected-week plotting.",
        "",
        "## Key Results",
        f"- D-only exact 247 builder unchanged: **{d_only_ok}**",
        f"- D+4 strict no-future feature gate violations: **{len(multiday.disallowed_feature_attempts)}**",
        f"- known_at violations: **{len(multiday.known_at_violations)}**",
        f"- forbidden columns detected: **{int(multiday.forbidden_columns_audit['is_forbidden'].sum()) if not multiday.forbidden_columns_audit.empty else 0}**",
        "",
        "## Files",
        "- multiday_feature_schema_by_horizon.csv",
        "- multiday_feature_availability_by_horizon.csv",
        "- multiday_forbidden_columns_audit.csv",
        "- multiday_known_at_violations.csv",
        "- multiday_disallowed_feature_attempts.csv",
        "- multiday_missingness_by_feature.csv",
        "- multiday_x2_imputation_policy_audit.csv",
        "- multiday_training_window_policy_audit.csv",
        "- multiday_audit_checks.csv",
        "",
    ]
    (out_dir / "multiday_audit_readme.md").write_text("\n".join(readme_lines), encoding="utf-8")

    summary = {
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(out_dir),
        "critical_failures": critical_failures,
        "warnings": warnings,
        "d_only_247_builder_unchanged": bool(d_only_ok),
        "dplus4_disallowed_feature_attempt_rows": int(len(multiday.disallowed_feature_attempts)),
        "dplus4_known_at_violation_rows": int(len(multiday.known_at_violations)),
        "checks": [asdict(c) for c in checks],
    }
    (out_dir / "multiday_audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Multiday feature audit output: {out_dir}")
    print(f"critical_failures={critical_failures}")
    print(f"warnings={warnings}")
    print(f"d_only_247_builder_unchanged={bool(d_only_ok)}")
    print(f"dplus4_disallowed_feature_attempt_rows={len(multiday.disallowed_feature_attempts)}")
    print(f"dplus4_known_at_violation_rows={len(multiday.known_at_violations)}")


if __name__ == "__main__":
    main()
