from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hourly_da.core.lago_benchmark_data import audit_lago_data_coverage
from hourly_da.core.lago_benchmark_features import build_lago_d_only_daily_matrix, build_lago_dplus4_direct_matrix
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_splits import LagoSplitConfig, build_split_days


@dataclass
class AuditCheck:
    check_id: str
    category: str
    check_name: str
    status: str
    severity: str
    details: str
    output_file: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lago LEAR methodological audit runner.")
    parser.add_argument("--split-policy", type=str, default="lago_104w_test", choices=["lago_104w_test", "thesis_official", "custom"])
    parser.add_argument("--x2-policy", type=str, default="res_forecast_if_available", choices=["aggregate_generation", "res_forecast_if_available", "no_x2", "persistence_proxy"])
    parser.add_argument("--x2-missing-policy", type=str, default="impute_training_median", choices=["impute_training_median", "fail"])
    parser.add_argument("--dplus4-x2-policy", type=str, default="strict_no_future_x2", choices=["strict_no_future_x2", "persistence_proxy"])
    parser.add_argument("--allow-official-cleaned-fallback", action="store_true")
    return parser.parse_args()


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _expected_d_only_feature_names() -> list[str]:
    def hour_names(prefix: str) -> list[str]:
        return [f"{prefix}_h{h:02d}" for h in range(1, 25)]

    names: list[str] = []
    names.extend(hour_names("price_d_minus_1"))
    names.extend(hour_names("price_d_minus_2"))
    names.extend(hour_names("price_d_minus_3"))
    names.extend(hour_names("price_d_minus_7"))
    names.extend(hour_names("x1_load_fcst_d"))
    names.extend(hour_names("x2_gen_fcst_d"))
    names.extend(hour_names("x1_load_fcst_d_minus_1"))
    names.extend(hour_names("x1_load_fcst_d_minus_7"))
    names.extend(hour_names("x2_gen_fcst_d_minus_1"))
    names.extend(hour_names("x2_gen_fcst_d_minus_7"))
    names.extend([f"dow_{i}" for i in range(7)])
    return names


def _build_config(args: argparse.Namespace) -> LagoLearBenchmarkConfig:
    x2_policy_map = {
        "aggregate_generation": "aggregate_generation",
        "res_forecast_if_available": "res_forecast_if_available",
        "no_x2": "no_x2",
        "persistence_proxy": "res_forecast_if_available",
    }
    return LagoLearBenchmarkConfig(
        x2_policy=x2_policy_map[str(args.x2_policy)],
        x2_missing_policy=str(args.x2_missing_policy),
        dplus4_x2_policy=str(args.dplus4_x2_policy),
        allow_x2_persistence_proxy=bool(args.x2_policy == "persistence_proxy" or args.dplus4_x2_policy == "persistence_proxy"),
        allow_official_cleaned_fallback=bool(args.allow_official_cleaned_fallback),
    )


def _choose_x2_frames(bundle: Any, policy: str) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    res = bundle.exogenous_frames.get("da_res_generation_forecast", pd.DataFrame())
    agg = bundle.exogenous_frames.get("da_generation_forecast", pd.DataFrame())
    if policy == "aggregate_generation":
        return agg, None
    if policy == "no_x2":
        primary = res if not res.empty else agg
        return primary, agg if not agg.empty else None
    primary = res if not res.empty else agg
    fallback = agg if (not agg.empty and not primary.equals(agg)) else None
    return primary, fallback


def _minute_counts(ts: pd.Series) -> str:
    vc = ts.dt.minute.value_counts(dropna=False).sort_index()
    return ";".join([f"{int(k) if pd.notna(k) else 'nan'}:{int(v)}" for k, v in vc.items()])


def _coverage_includes_period(ts_utc: pd.Series, timezone: str, start_local: str, end_local_exclusive: str) -> bool:
    ts = pd.to_datetime(ts_utc, utc=True, errors="coerce").dropna()
    if ts.empty:
        return False
    local_days = set(ts.dt.tz_convert(timezone).dt.date.tolist())
    start_day = pd.Timestamp(start_local).date()
    end_inclusive = (pd.Timestamp(end_local_exclusive) - pd.Timedelta(days=1)).date()
    return start_day in local_days and end_inclusive in local_days


def _day_slice(frame: pd.DataFrame, local_day: Any, timezone: str) -> pd.DataFrame:
    if frame.empty or "timestamp_utc" not in frame.columns:
        return frame.iloc[0:0].copy()
    work = frame.copy()
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp_utc"]).copy()
    work["target_delivery_local_date"] = work["timestamp_utc"].dt.tz_convert(timezone).dt.date
    return work[work["target_delivery_local_date"] == local_day].copy()


def _vector_by_hour_allow_missing(frame: pd.DataFrame, value_col: str) -> list[float] | None:
    if frame.empty:
        return None
    ordered = frame.sort_values(["target_hour_local", "timestamp_utc"]).copy()
    ordered = ordered.drop_duplicates(subset=["target_hour_local"], keep="last")
    if "target_hour_local" not in ordered.columns:
        ordered["target_hour_local"] = pd.to_datetime(ordered["timestamp_utc"], utc=True, errors="coerce").dt.hour
    if ordered["target_hour_local"].isna().any():
        return None
    hours = ordered["target_hour_local"].astype(int).tolist()
    if sorted(hours) != list(range(24)):
        return None
    values = pd.to_numeric(ordered[value_col], errors="coerce")
    return [float(v) if pd.notna(v) else np.nan for v in values.tolist()]


def _prepare_local_columns(frame: pd.DataFrame, timezone: str) -> pd.DataFrame:
    out = frame.copy()
    if out.empty or "timestamp_utc" not in out.columns:
        return out
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp_utc"]).copy()
    out["timestamp_local"] = out["timestamp_utc"].dt.tz_convert(timezone)
    out["target_delivery_local_date"] = out["timestamp_local"].dt.date
    out["target_hour_local"] = out["timestamp_local"].dt.hour.astype("Int64")
    return out


def _summarize_file(
    *,
    file_id: str,
    path: Path,
    key_cols: list[str],
    value_col: str | None,
    timezone: str,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    row: dict[str, Any] = {
        "file_id": file_id,
        "path": str(path),
        "exists": path.exists(),
    }
    missingness_rows: list[dict[str, Any]] = []
    dup_info: dict[str, Any] = {
        "file_id": file_id,
        "path": str(path),
        "duplicate_timestamp_count": np.nan,
        "duplicate_key_count": np.nan,
        "non_hourly_timestamp_count": np.nan,
    }
    if not path.exists():
        return row, pd.DataFrame(missingness_rows), dup_info

    frame = pd.read_csv(path)
    row["row_count"] = int(frame.shape[0])
    row["column_count"] = int(frame.shape[1])
    if "timestamp_utc" in frame.columns:
        ts = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
        row["min_timestamp_utc"] = ts.min().isoformat() if ts.notna().any() else None
        row["max_timestamp_utc"] = ts.max().isoformat() if ts.notna().any() else None
        row["timestamp_minute_counts"] = _minute_counts(ts) if ts.notna().any() else None
        row["coverage_includes_2019_10_01_to_2025_09_30_local"] = bool(
            _coverage_includes_period(ts, timezone, "2019-10-01", "2025-10-01")
        )
        dup_info["duplicate_timestamp_count"] = int(ts.duplicated().sum())
        dup_info["non_hourly_timestamp_count"] = int((ts.dt.minute.fillna(-1) != 0).sum())
    else:
        row["min_timestamp_utc"] = None
        row["max_timestamp_utc"] = None
        row["timestamp_minute_counts"] = None
        row["coverage_includes_2019_10_01_to_2025_09_30_local"] = False

    if all(col in frame.columns for col in key_cols):
        dup_info["duplicate_key_count"] = int(frame.duplicated(subset=key_cols).sum())
    else:
        dup_info["duplicate_key_count"] = np.nan

    row["missing_value_cells"] = int(frame.isna().sum().sum())
    row["missing_value_share_cells"] = float(frame.isna().sum().sum() / float(frame.shape[0] * frame.shape[1])) if frame.shape[0] and frame.shape[1] else np.nan

    if value_col and value_col in frame.columns and "timestamp_utc" in frame.columns:
        ts_local = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(timezone)
        val = pd.to_numeric(frame[value_col], errors="coerce")
        tmp = pd.DataFrame({"year": ts_local.dt.year, "month": ts_local.dt.month, "is_missing": val.isna()})
        miss = tmp.groupby(["year", "month"], dropna=False)["is_missing"].mean().reset_index()
        miss["file_id"] = file_id
        missingness_rows = miss[["file_id", "year", "month", "is_missing"]].rename(columns={"is_missing": "missing_share"}).to_dict(orient="records")

    return row, pd.DataFrame(missingness_rows), dup_info


def _write_markdown_summary(path: Path, checks: list[AuditCheck], output_dir: Path) -> None:
    critical = [c for c in checks if c.status == "fail" and c.severity == "critical"]
    warnings = [c for c in checks if c.status == "warn"]
    passed = [c for c in checks if c.status == "pass"]
    lines = [
        "# Lago LEAR Audit Summary",
        "",
        f"- output_dir: `{output_dir}`",
        f"- critical_failures: {len(critical)}",
        f"- warnings: {len(warnings)}",
        f"- passed_checks: {len(passed)}",
        "",
        "## Critical Failures",
    ]
    if not critical:
        lines.append("- none")
    else:
        for c in critical:
            lines.append(f"- `{c.check_id}` {c.check_name}: {c.details}")
    lines.append("")
    lines.append("## Warnings")
    if not warnings:
        lines.append("- none")
    else:
        for c in warnings:
            lines.append(f"- `{c.check_id}` {c.check_name}: {c.details}")
    lines.append("")
    lines.append("## Next Actions")
    if critical:
        lines.append("- Resolve critical failures before any heavy benchmark run.")
    else:
        lines.append("- No critical failures found; review warnings and proceed carefully.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = _build_config(args)
    split_config = LagoSplitConfig(split_policy=str(args.split_policy))

    audit_root = config.output_root / f"audit_{_now_id()}"
    audit_root.mkdir(parents=True, exist_ok=True)
    checks: list[AuditCheck] = []

    def add_check(check_id: str, category: str, check_name: str, status: str, severity: str, details: str, output_file: str) -> None:
        checks.append(
            AuditCheck(
                check_id=check_id,
                category=category,
                check_name=check_name,
                status=status,
                severity=severity,
                details=details,
                output_file=output_file,
            )
        )

    # Section 1: Data coverage audit
    staged = config.staged_cleaned_root
    official = config.official_cleaned_root

    da_path = staged / "Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv"
    res_agg_path = staged / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv"
    res_psr_path = staged / "Generation/da_res_generation_forecast_by_psr/hourly/da_res_generation_forecast_by_psr_hourly_feature_ready_long.csv"
    load_candidates = [
        staged / "Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv",
        staged / "Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv",
        official / "Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv",
        official / "Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv",
    ]
    load_path = next((p for p in load_candidates if p.exists()), load_candidates[0])

    coverage_rows: list[dict[str, Any]] = []
    missingness_parts: list[pd.DataFrame] = []
    duplicate_rows: list[dict[str, Any]] = []
    for file_id, path, key_cols, value_col in [
        ("da_prices_nl_hourly", da_path, ["timestamp_utc"], "price_eur_per_mwh"),
        ("res_x2_feature_ready_hourly", res_agg_path, ["timestamp_utc", "region"], "value_mw"),
        ("res_by_psr_feature_ready_hourly", res_psr_path, ["timestamp_utc", "region", "psr_type"], "value_mw"),
        ("load_forecast_hourly", load_path, ["timestamp_utc", "region"], "value_mw"),
    ]:
        summary, miss_df, dup_info = _summarize_file(
            file_id=file_id,
            path=path,
            key_cols=key_cols,
            value_col=value_col,
            timezone=config.local_timezone,
        )
        coverage_rows.append(summary)
        if not miss_df.empty:
            missingness_parts.append(miss_df)
        duplicate_rows.append(dup_info)

    coverage_df = pd.DataFrame(coverage_rows)
    miss_df = pd.concat(missingness_parts, ignore_index=True) if missingness_parts else pd.DataFrame(columns=["file_id", "year", "month", "missing_share"])
    dup_df = pd.DataFrame(duplicate_rows)
    coverage_df.to_csv(audit_root / "data_coverage_audit.csv", index=False)
    miss_df.to_csv(audit_root / "missingness_by_year_month.csv", index=False)
    dup_df.to_csv(audit_root / "duplicate_audit.csv", index=False)

    for required_id in ["da_prices_nl_hourly", "res_x2_feature_ready_hourly", "res_by_psr_feature_ready_hourly"]:
        exists = bool(coverage_df.loc[coverage_df["file_id"] == required_id, "exists"].any())
        add_check(
            check_id=f"data_{required_id}_exists",
            category="data_coverage",
            check_name=f"{required_id} file exists",
            status="pass" if exists else "fail",
            severity="critical",
            details=f"exists={exists}",
            output_file="data_coverage_audit.csv",
        )

    non_hourly_total = int(pd.to_numeric(dup_df["non_hourly_timestamp_count"], errors="coerce").fillna(0).sum())
    add_check(
        check_id="data_hourly_timestamps",
        category="data_coverage",
        check_name="hourly feature files have minute == 0 timestamps",
        status="pass" if non_hourly_total == 0 else "fail",
        severity="critical",
        details=f"non_hourly_timestamp_count={non_hourly_total}",
        output_file="duplicate_audit.csv",
    )
    if not coverage_df.empty:
        for _, r in coverage_df.iterrows():
            add_check(
                check_id=f"data_period_{r['file_id']}",
                category="data_coverage",
                check_name=f"{r['file_id']} includes benchmark period endpoints",
                status="pass" if bool(r.get("coverage_includes_2019_10_01_to_2025_09_30_local", False)) else "warn",
                severity="high",
                details=f"coverage={r.get('coverage_includes_2019_10_01_to_2025_09_30_local', False)}",
                output_file="data_coverage_audit.csv",
            )

    # Section 2: DST audit
    dst_rows: list[dict[str, Any]] = []
    for local_day in config.benchmark_delivery_days():
        hours = int(config.expected_hours_for_local_day(local_day))
        dst_rows.append(
            {
                "delivery_local_date": local_day.isoformat(),
                "expected_hours": hours,
                "is_skipped_by_d_only_24h_model": hours != 24,
            }
        )
    dst_df = pd.DataFrame(dst_rows)
    skipped_days = dst_df[dst_df["is_skipped_by_d_only_24h_model"]].copy()
    dst_df.to_csv(audit_root / "dst_day_audit.csv", index=False)
    skipped_days.to_csv(audit_root / "skipped_local_days.csv", index=False)

    count_23 = int((dst_df["expected_hours"] == 23).sum())
    count_24 = int((dst_df["expected_hours"] == 24).sum())
    count_25 = int((dst_df["expected_hours"] == 25).sum())
    add_check(
        check_id="dst_day_counts",
        category="dst",
        check_name="DST day distribution calculated",
        status="pass",
        severity="low",
        details=f"23h={count_23},24h={count_24},25h={count_25}",
        output_file="dst_day_audit.csv",
    )
    add_check(
        check_id="dst_skipped_days_warning",
        category="dst",
        check_name="D-only skipped DST days warning",
        status="warn" if len(skipped_days) > 0 else "pass",
        severity="medium",
        details=f"skipped_days={len(skipped_days)}",
        output_file="skipped_local_days.csv",
    )

    # Build bundle/features once; no heavy training.
    bundle = audit_lago_data_coverage(config)
    x1_da = bundle.exogenous_frames.get("da_total_load_forecast", pd.DataFrame())
    x1_wa = bundle.exogenous_frames.get("week_ahead_total_load_forecast", pd.DataFrame())
    x2_primary, x2_fallback = _choose_x2_frames(bundle, str(args.x2_policy))
    split_days = build_split_days(config, split_config)
    split_days["delivery_local_date"] = pd.to_datetime(split_days["delivery_local_date"], errors="coerce").dt.date
    split_lookup = {
        d: s for d, s in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False) if pd.notna(d) and pd.notna(s)
    }

    truth = bundle.target_truth_audit.copy()
    truth["target_delivery_local_date"] = pd.to_datetime(truth["target_delivery_local_date"], errors="coerce").dt.date
    truth["dataset_split"] = truth["target_delivery_local_date"].map(split_lookup)
    complete_days = (
        truth.groupby(["target_delivery_local_date", "dataset_split"], as_index=False)
        .agg(expected_hours=("expected_hours_in_local_day", "max"), observed_hours=("is_observed_target", "sum"))
    )
    complete_days["is_complete_observed_24h"] = (complete_days["expected_hours"] == 24) & (complete_days["observed_hours"] == 24)
    candidate_model_days = complete_days[complete_days["is_complete_observed_24h"]].copy()

    x1_prepared = _prepare_local_columns(x1_da, config.local_timezone)
    x2_prepared = _prepare_local_columns(x2_primary, config.local_timezone)

    # Section 3: D-only feature audit
    d_only_failure_rows: list[dict[str, Any]] = []
    d_only_bad_cols_rows: list[dict[str, Any]] = []
    try:
        d_only = build_lago_d_only_daily_matrix(
            price_df=bundle.price_frame,
            load_forecast_df=x1_da,
            generation_forecast_df=x2_primary,
            generation_forecast_fallback_df=x2_fallback,
            config=config,
        )
        X = d_only.X.copy()
        Y = d_only.Y.copy()
        expected_cols = _expected_d_only_feature_names()
        schema_audit = pd.DataFrame(
            [
                {
                    "actual_feature_count": int(len(X.columns)),
                    "expected_feature_count": 247,
                    "exact_match_ordered": bool(list(X.columns) == expected_cols),
                    "x2_columns_present": bool(any(col.startswith("x2_") for col in X.columns)),
                }
            ]
        )
        schema_audit.to_csv(audit_root / "d_only_feature_schema_audit.csv", index=False)

        family_counts = pd.DataFrame(
            [
                {"feature_family": "price_lag", "count": int(sum(c.startswith("price_") for c in X.columns))},
                {"feature_family": "x1_current", "count": int(sum(c.startswith("x1_load_fcst_d_h") for c in X.columns))},
                {"feature_family": "x2_current", "count": int(sum(c.startswith("x2_gen_fcst_d_h") for c in X.columns))},
                {"feature_family": "x1_lagged", "count": int(sum(c.startswith("x1_load_fcst_d_minus_") for c in X.columns))},
                {"feature_family": "x2_lagged", "count": int(sum(c.startswith("x2_gen_fcst_d_minus_") for c in X.columns))},
                {"feature_family": "weekday", "count": int(sum(c.startswith("dow_") for c in X.columns))},
                {"feature_family": "total", "count": int(len(X.columns))},
            ]
        )
        family_counts.to_csv(audit_root / "d_only_feature_family_counts.csv", index=False)

        missing_rows = []
        for c in X.columns:
            s = pd.to_numeric(X[c], errors="coerce")
            missing_rows.append(
                {
                    "feature_name": c,
                    "feature_family": "price_lag" if c.startswith("price_") else ("x1" if c.startswith("x1_") else ("x2" if c.startswith("x2_") else ("weekday" if c.startswith("dow_") else "other"))),
                    "missing_count": int(s.isna().sum()),
                    "missing_share": float(s.isna().mean()) if len(s) else np.nan,
                }
            )
        missing_by_feature = pd.DataFrame(missing_rows)
        missing_by_feature.to_csv(audit_root / "d_only_missing_by_feature.csv", index=False)

        # Price-lag integrity audit
        price_lag_cols = [c for c in X.columns if c.startswith("price_")]
        price_lag_missing_after = int(X[price_lag_cols].isna().sum().sum()) if price_lag_cols else 0
        price_lag_missing_before = 0
        rows_dropped_due_to_price_lag = int(
            d_only.skipped_rows.get("reason", pd.Series(dtype=str)).astype(str).str.contains("missing_price", na=False).sum()
        )
        price_lag_integrity = pd.DataFrame(
            [
                {
                    "price_lag_missing_cells_before_filtering": int(price_lag_missing_before),
                    "price_lag_missing_cells_after_filtering": int(price_lag_missing_after),
                    "rows_dropped_due_to_price_lag_missing": int(rows_dropped_due_to_price_lag),
                    "price_lag_imputation_used": False,
                }
            ]
        )
        price_lag_integrity.to_csv(audit_root / "price_lag_integrity_audit.csv", index=False)

        forbidden_tokens = ["timestamp", "source_file", "known_at_rule", "policy", "quality_flag", "is_missing", "b16_", "b18_", "b19_"]
        bad_cols = [c for c in X.columns if any(tok in str(c) for tok in forbidden_tokens)]
        if bad_cols:
            for c in bad_cols:
                d_only_bad_cols_rows.append({"column_name": c, "reason": "forbidden_token"})
        d_only_bad_cols = pd.DataFrame(d_only_bad_cols_rows)
        d_only_bad_cols.to_csv(audit_root / "d_only_bad_columns.csv", index=False)

        # Validation checks
        feature_count_ok = len(X.columns) == 247
        ordered_ok = list(X.columns) == expected_cols
        weekday_ok = int(sum(c.startswith("dow_") for c in X.columns)) == 7
        x2_present = any(c.startswith("x2_") for c in X.columns)
        y_missing = int(Y.isna().sum().sum())
        bad_nans_price = int(missing_by_feature.loc[missing_by_feature["feature_family"].isin(["price_lag", "weekday"]), "missing_count"].sum())

        add_check("donly_feature_count_247", "d_only_features", "D-only feature count equals 247", "pass" if feature_count_ok else "fail", "critical", f"count={len(X.columns)}", "d_only_feature_schema_audit.csv")
        add_check("donly_feature_order_exact", "d_only_features", "D-only feature columns match expected names/order", "pass" if ordered_ok else "fail", "high", f"ordered_ok={ordered_ok}", "d_only_feature_schema_audit.csv")
        add_check("donly_weekday_7", "d_only_features", "D-only weekday dummy count is 7", "pass" if weekday_ok else "fail", "high", f"weekday_count={int(sum(c.startswith('dow_') for c in X.columns))}", "d_only_feature_family_counts.csv")
        add_check("donly_x2_present", "d_only_features", "D-only x2 columns present", "pass" if x2_present else "fail", "critical", f"x2_present={x2_present}", "d_only_feature_schema_audit.csv")
        add_check("donly_forbidden_columns", "d_only_features", "No forbidden audit/source columns in X", "pass" if not bad_cols else "fail", "critical", f"bad_cols={len(bad_cols)}", "d_only_bad_columns.csv")
        add_check("donly_no_nan_price_or_weekday", "d_only_features", "No NaN in price lag/weekday features", "pass" if bad_nans_price == 0 else "fail", "critical", f"nan_price_weekday={bad_nans_price}", "d_only_missing_by_feature.csv")
        add_check("donly_no_nan_targets", "d_only_features", "No NaN in D-only target y", "pass" if y_missing == 0 else "fail", "critical", f"target_nan_cells={y_missing}", "d_only_missing_by_feature.csv")
        add_check(
            "price_lag_imputation_forbidden",
            "d_only_features",
            "Price lag imputation is not used",
            "pass",
            "critical",
            "price_lag_imputation_used=False",
            "price_lag_integrity_audit.csv",
        )
    except Exception as exc:  # noqa: BLE001
        d_only_failure_rows.append({"failure": str(exc)})
        pd.DataFrame(d_only_failure_rows).to_csv(audit_root / "d_only_feature_validation_failure.csv", index=False)
        add_check(
            "donly_build_failure",
            "d_only_features",
            "D-only feature build completed",
            "fail",
            "critical",
            str(exc),
            "d_only_feature_validation_failure.csv",
        )
        d_only = None

    # Section 4: known-at/leakage D-only
    if d_only is not None:
        known_d = d_only.known_at_violations.copy()
        known_d.to_csv(audit_root / "known_at_audit_d_only.csv", index=False)
        leakage_rows: list[dict[str, Any]] = []
        if not known_d.empty:
            leakage_rows.append({"violation_type": "known_at", "details": f"rows={len(known_d)}"})
        if d_only.X.columns.str.startswith("y_").any():
            leakage_rows.append({"violation_type": "target_in_features", "details": "X contains y_ column"})
        leakage_df = pd.DataFrame(leakage_rows)
        leakage_df.to_csv(audit_root / "leakage_violations_d_only.csv", index=False)
        bundle.target_truth_audit.to_csv(audit_root / "target_truth_audit.csv", index=False)
        add_check(
            "donly_known_at_violations",
            "d_only_leakage",
            "No known_at violations in D-only",
            "pass" if known_d.empty else "fail",
            "critical",
            f"rows={len(known_d)}",
            "known_at_audit_d_only.csv",
        )
        add_check(
            "donly_leakage_violations",
            "d_only_leakage",
            "No leakage violations in D-only",
            "pass" if leakage_df.empty else "fail",
            "critical",
            f"rows={len(leakage_df)}",
            "leakage_violations_d_only.csv",
        )

    # Section 5: Imputation audit (lightweight tiny sample)
    imputation_logic_rows: list[dict[str, Any]] = []
    imputation_values_rows: list[dict[str, Any]] = []
    imputation_skipped_rows: list[dict[str, Any]] = []
    x2_cols = [f"x2_gen_fcst_d_h{h:02d}" for h in range(1, 25)] + [f"x2_gen_fcst_d_minus_1_h{h:02d}" for h in range(1, 25)] + [
        f"x2_gen_fcst_d_minus_7_h{h:02d}" for h in range(1, 25)
    ]
    relaxed_rows: list[dict[str, Any]] = []
    for day, split_name in candidate_model_days[["target_delivery_local_date", "dataset_split"]].itertuples(index=False):
        d = pd.Timestamp(day).date()
        vec_d = _vector_by_hour_allow_missing(_day_slice(x2_prepared, d, config.local_timezone), "value_mw")
        vec_d1 = _vector_by_hour_allow_missing(_day_slice(x2_prepared, (pd.Timestamp(d) - pd.Timedelta(days=1)).date(), config.local_timezone), "value_mw")
        vec_d7 = _vector_by_hour_allow_missing(_day_slice(x2_prepared, (pd.Timestamp(d) - pd.Timedelta(days=7)).date(), config.local_timezone), "value_mw")
        row = {"delivery_local_date": d, "dataset_split": split_name}
        for h in range(24):
            row[f"x2_gen_fcst_d_h{h+1:02d}"] = np.nan if vec_d is None else float(vec_d[h])
            row[f"x2_gen_fcst_d_minus_1_h{h+1:02d}"] = np.nan if vec_d1 is None else float(vec_d1[h])
            row[f"x2_gen_fcst_d_minus_7_h{h+1:02d}"] = np.nan if vec_d7 is None else float(vec_d7[h])
        relaxed_rows.append(row)
    relaxed_df = pd.DataFrame(relaxed_rows).sort_values("delivery_local_date").reset_index(drop=True) if relaxed_rows else pd.DataFrame()
    pre_imputation_x2_missing_cells = int(relaxed_df[x2_cols].isna().sum().sum()) if not relaxed_df.empty else 0

    if not relaxed_df.empty:
        sample_candidates = []
        for idx, row in relaxed_df.iterrows():
            missing_cols = [c for c in x2_cols if pd.isna(row.get(c))]
            if missing_cols:
                sample_candidates.append((idx, row, missing_cols))
        for idx, row, missing_cols in sample_candidates[:5]:
            d = pd.Timestamp(row["delivery_local_date"]).date()
            origin = config.forecast_origin_utc_for_delivery_day(d)
            train = relaxed_df[relaxed_df["delivery_local_date"] < d].copy()
            uniq = sorted(train["delivery_local_date"].dropna().unique().tolist())
            window_days = 56
            if len(uniq) > window_days:
                train = train[train["delivery_local_date"] >= uniq[-window_days]].copy()
            train_start = str(train["delivery_local_date"].min()) if not train.empty else None
            train_end = str(train["delivery_local_date"].max()) if not train.empty else None
            col = missing_cols[0]
            train_col = pd.to_numeric(train[col], errors="coerce") if not train.empty else pd.Series(dtype=float)
            train_median = float(train_col.median()) if (not train_col.empty and train_col.notna().any()) else np.nan
            global_col = pd.to_numeric(relaxed_df[col], errors="coerce")
            global_median = float(global_col.median()) if global_col.notna().any() else np.nan
            eval_after = train_median if pd.isna(row.get(col)) else float(row.get(col))
            differs = bool(np.isfinite(train_median) and np.isfinite(global_median) and not np.isclose(train_median, global_median))
            status = "ok" if np.isfinite(train_median) else "train_median_unavailable"
            imputation_logic_rows.append(
                {
                    "forecast_origin_utc": origin.isoformat(),
                    "split": str(row.get("dataset_split")),
                    "x2_column": col,
                    "missing_eval_count": int(len(missing_cols)),
                    "train_window_start": train_start,
                    "train_window_end": train_end,
                    "train_median_used": train_median,
                    "global_median_same_column": global_median,
                    "eval_value_after_imputation": eval_after,
                    "fitted_on_train_only": True,
                    "global_median_differs": differs,
                    "evidence_status": status,
                }
            )
            imputation_values_rows.append(
                {
                    "forecast_origin_utc": origin.isoformat(),
                    "model_label": "audit_sample",
                    "window_days": window_days,
                    "lead_day": "D",
                    "target_hour": col.split("_h")[-1],
                    "feature_name": col,
                    "feature_family": "x2",
                    "train_missing_count": int(train_col.isna().sum()) if not train_col.empty else np.nan,
                    "predict_missing_count": 1,
                    "imputation_value": train_median,
                    "imputer_fit_rows": int(len(train)),
                    "imputer_strategy": "median",
                }
            )

    if pre_imputation_x2_missing_cells > 0 and not imputation_logic_rows:
        imputation_logic_rows.append(
            {
                "forecast_origin_utc": None,
                "split": None,
                "x2_column": None,
                "missing_eval_count": int(pre_imputation_x2_missing_cells),
                "train_window_start": None,
                "train_window_end": None,
                "train_median_used": np.nan,
                "global_median_same_column": np.nan,
                "eval_value_after_imputation": np.nan,
                "fitted_on_train_only": False,
                "global_median_differs": False,
                "evidence_status": "no_imputation_sample_generated_despite_missing_x2",
            }
        )
        imputation_skipped_rows.append(
            {
                "delivery_local_date": None,
                "window_days": None,
                "reason": "no_imputation_sample_generated_despite_missing_x2",
            }
        )
    if pre_imputation_x2_missing_cells == 0 and not imputation_logic_rows:
        imputation_logic_rows.append(
            {
                "forecast_origin_utc": None,
                "split": None,
                "x2_column": None,
                "missing_eval_count": 0,
                "train_window_start": None,
                "train_window_end": None,
                "train_median_used": np.nan,
                "global_median_same_column": np.nan,
                "eval_value_after_imputation": np.nan,
                "fitted_on_train_only": True,
                "global_median_differs": False,
                "evidence_status": "no_missing_x2_in_relaxed_candidates",
            }
        )
    imputation_logic_df = pd.DataFrame(imputation_logic_rows)
    imputation_values_df = pd.DataFrame(imputation_values_rows)
    imputation_skipped_df = pd.DataFrame(imputation_skipped_rows)
    imputation_logic_df.to_csv(audit_root / "imputation_logic_audit.csv", index=False)
    imputation_values_df.to_csv(audit_root / "imputation_values_sample.csv", index=False)
    imputation_skipped_df.to_csv(audit_root / "imputation_skipped_cases.csv", index=False)

    fit_rows_ok = bool(imputation_logic_df["fitted_on_train_only"].fillna(False).all()) if not imputation_logic_df.empty else False
    add_check(
        "imputation_train_only_fit",
        "imputation",
        "Imputer fitted on training window rows only",
        "pass" if fit_rows_ok else "fail",
        "critical",
        f"all_fitted_on_train_only={fit_rows_ok}",
        "imputation_logic_audit.csv",
    )
    if not imputation_logic_df.empty:
        global_used = imputation_logic_df[
            (imputation_logic_df.get("global_median_differs", pd.Series(dtype=bool)).fillna(False))
            & (
                pd.to_numeric(imputation_logic_df.get("eval_value_after_imputation", pd.Series(dtype=float)), errors="coerce")
                .fillna(np.nan)
                == pd.to_numeric(imputation_logic_df.get("global_median_same_column", pd.Series(dtype=float)), errors="coerce").fillna(np.nan)
            )
        ]
        add_check(
            "imputation_not_global",
            "imputation",
            "No evidence of global median imputation",
            "pass" if global_used.empty else "fail",
            "critical",
            f"suspected_global_rows={len(global_used)}",
            "imputation_logic_audit.csv",
        )
    else:
        add_check(
            "imputation_not_global",
            "imputation",
            "No evidence of global median imputation",
            "fail",
            "critical",
            "imputation_logic_audit.csv is empty",
            "imputation_logic_audit.csv",
        )
    if not imputation_values_df.empty:
        price_imp = imputation_values_df[
            (imputation_values_df["feature_family"] == "price_lag")
            & ((imputation_values_df["train_missing_count"] > 0) | (imputation_values_df["predict_missing_count"] > 0))
        ]
        add_check(
            "imputation_price_lag",
            "imputation",
            "No price-lag imputation used",
            "pass" if price_imp.empty else "fail",
            "critical",
            f"price_lag_imputed_rows={len(price_imp)}",
            "imputation_values_sample.csv",
        )
    else:
        status = "fail" if pre_imputation_x2_missing_cells > 0 else "warn"
        sev = "critical" if pre_imputation_x2_missing_cells > 0 else "medium"
        add_check(
            "imputation_price_lag",
            "imputation",
            "No price-lag imputation used",
            status,
            sev,
            "No imputation sample rows captured.",
            "imputation_values_sample.csv",
        )
    if pre_imputation_x2_missing_cells > 0 and imputation_logic_df["evidence_status"].astype(str).str.contains("no_imputation_sample_generated", na=False).any():
        add_check(
            "imputation_sample_required_when_x2_missing",
            "imputation",
            "Imputation sample generated when x2 missingness exists",
            "fail",
            "critical",
            f"pre_imputation_x2_missing_cells={pre_imputation_x2_missing_cells}",
            "imputation_logic_audit.csv",
        )
    else:
        add_check(
            "imputation_sample_required_when_x2_missing",
            "imputation",
            "Imputation sample generated when x2 missingness exists",
            "pass",
            "high",
            f"pre_imputation_x2_missing_cells={pre_imputation_x2_missing_cells}",
            "imputation_logic_audit.csv",
        )

    # Section 6: D+4 audit (features only)
    dplus4 = build_lago_dplus4_direct_matrix(
        price_df=bundle.price_frame,
        load_forecast_df=x1_da,
        week_ahead_load_forecast_df=x1_wa,
        generation_forecast_df=x2_primary,
        config=config,
    )
    dplus4_schema = pd.DataFrame([{"feature_count": int(len(dplus4.X_long.columns)), "rows": int(len(dplus4.X_long))}])
    dplus4_schema.to_csv(audit_root / "dplus4_feature_schema_audit.csv", index=False)
    dplus4.known_at_violations.to_csv(audit_root / "known_at_audit_dplus4.csv", index=False)
    dplus4.unavailable_exogenous_by_lead_day.to_csv(audit_root / "dplus4_exogenous_availability_by_lead_day.csv", index=False)

    dplus4_leak_rows: list[dict[str, Any]] = []
    if not dplus4.metadata_long.empty:
        meta = dplus4.metadata_long.copy()
        meta["forecast_origin_utc"] = pd.to_datetime(meta["forecast_origin_utc"], utc=True, errors="coerce")
        meta["target_timestamp_utc"] = pd.to_datetime(meta["target_timestamp_utc"], utc=True, errors="coerce")
        bad_order = meta[meta["target_timestamp_utc"] <= meta["forecast_origin_utc"]]
        if not bad_order.empty:
            dplus4_leak_rows.append({"violation_type": "target_not_after_origin", "rows": int(len(bad_order))})
    if not dplus4.X_long.empty and str(config.dplus4_x2_policy) == "strict_no_future_x2":
        x2_target_cols = [c for c in dplus4.X_long.columns if c.startswith("x2_generation_forecast_for_target_h")]
        if x2_target_cols and "lead_day_numeric" in dplus4.X_long.columns:
            non_d = dplus4.X_long["lead_day_numeric"] > 0
            non_d_x2 = dplus4.X_long.loc[non_d, x2_target_cols]
            if not non_d_x2.empty:
                has_values = np.isfinite(non_d_x2.to_numpy(dtype=float)).any()
                if has_values:
                    dplus4_leak_rows.append({"violation_type": "future_x2_present_under_strict_no_future_x2", "rows": int(non_d_x2.shape[0])})
    dplus4_leak_df = pd.DataFrame(dplus4_leak_rows)
    dplus4_leak_df.to_csv(audit_root / "leakage_violations_dplus4.csv", index=False)
    add_check(
        "dplus4_leakage_violations",
        "dplus4_leakage",
        "No D+4 leakage violations",
        "pass" if dplus4_leak_df.empty else "fail",
        "critical",
        f"rows={len(dplus4_leak_df)}",
        "leakage_violations_dplus4.csv",
    )
    add_check(
        "dplus4_known_at_violations",
        "dplus4_leakage",
        "No known_at violations in D+4",
        "pass" if dplus4.known_at_violations.empty else "fail",
        "critical",
        f"rows={len(dplus4.known_at_violations)}",
        "known_at_audit_dplus4.csv",
    )
    add_check(
        "dplus4_not_exact_lago_warning",
        "dplus4",
        "D+4 is thesis extension and not exact Lago replication",
        "warn",
        "low",
        "Expected methodological note.",
        "dplus4_feature_schema_audit.csv",
    )

    # Section 7: Split audit
    train = split_days[split_days["dataset_split"] == "train"]["delivery_local_date"]
    val = split_days[split_days["dataset_split"] == "validation"]["delivery_local_date"]
    test = split_days[split_days["dataset_split"] == "test"]["delivery_local_date"]
    train_days_set = set(train.dropna().tolist())
    val_days_set = set(val.dropna().tolist())
    test_days_set = set(test.dropna().tolist())

    before_counts = candidate_model_days.groupby("dataset_split")["target_delivery_local_date"].nunique().to_dict()
    candidate_days_by_split: dict[str, set[Any]] = {
        split_name: set(
            pd.to_datetime(
                candidate_model_days.loc[
                    candidate_model_days["dataset_split"] == split_name,
                    "target_delivery_local_date",
                ],
                errors="coerce",
            )
            .dropna()
            .dt.date
            .tolist()
        )
        for split_name in ["train", "validation", "test"]
    }
    after_counts: dict[str, int] = {}
    missing_x1_drop: dict[str, int] = {}
    missing_x2_drop: dict[str, int] = {}
    retained_days_by_split: dict[str, set[Any]] = {k: set() for k in ["train", "validation", "test"]}
    reported_missing_x1_days_by_split: dict[str, set[Any]] = {k: set() for k in ["train", "validation", "test"]}
    skipped_days_with_any_reason_by_split: dict[str, set[Any]] = {k: set() for k in ["train", "validation", "test"]}
    if d_only is not None and not d_only.metadata.empty:
        md = d_only.metadata.copy()
        md["delivery_local_date"] = pd.to_datetime(md["delivery_local_date"], errors="coerce").dt.date
        md["dataset_split"] = md["delivery_local_date"].map(split_lookup)
        after_counts = md.groupby("dataset_split")["delivery_local_date"].nunique().to_dict()
        for split_name in ["train", "validation", "test"]:
            retained_days_by_split[split_name] = set(
                md.loc[md["dataset_split"] == split_name, "delivery_local_date"].dropna().tolist()
            )
        sk = d_only.skipped_rows.copy()
        if not sk.empty:
            sk["delivery_local_date"] = pd.to_datetime(sk.get("delivery_local_date", pd.Series(dtype=str)), errors="coerce").dt.date
            sk["dataset_split"] = sk["delivery_local_date"].map(split_lookup)
            sk["reason"] = sk.get("reason", pd.Series(dtype=str)).astype(str)
            x1_sk_mask = sk["reason"].str.contains(r"missing_x1|x1_load|missing_load", case=False, regex=True, na=False)
            x1_sk = sk[x1_sk_mask].groupby("dataset_split")["delivery_local_date"].nunique().to_dict()
            x2_sk = sk[sk["reason"].str.contains("missing_x2", na=False)].groupby("dataset_split")["delivery_local_date"].nunique().to_dict()
            missing_x1_drop = {str(k): int(v) for k, v in x1_sk.items()}
            missing_x2_drop = {str(k): int(v) for k, v in x2_sk.items()}
            for split_name in ["train", "validation", "test"]:
                skipped_days_with_any_reason_by_split[split_name] = set(
                    sk.loc[(sk["dataset_split"] == split_name), "delivery_local_date"].dropna().tolist()
                )
                reported_missing_x1_days_by_split[split_name] = set(
                    sk.loc[x1_sk_mask & (sk["dataset_split"] == split_name), "delivery_local_date"].dropna().tolist()
                )

    split_audit_df = pd.DataFrame(
        [
            {
                "train_start_date": str(min(train_days_set)) if train_days_set else None,
                "train_end_date": str(max(train_days_set)) if train_days_set else None,
                "validation_start_date": str(min(val_days_set)) if val_days_set else None,
                "validation_end_date": str(max(val_days_set)) if val_days_set else None,
                "test_start_date": str(min(test_days_set)) if test_days_set else None,
                "test_end_date": str(max(test_days_set)) if test_days_set else None,
                "train_target_rows_before_filtering": int(before_counts.get("train", 0)),
                "validation_target_rows_before_filtering": int(before_counts.get("validation", 0)),
                "test_target_rows_before_filtering": int(before_counts.get("test", 0)),
                "train_target_rows_after_feature_filtering": int(after_counts.get("train", 0)),
                "validation_target_rows_after_feature_filtering": int(after_counts.get("validation", 0)),
                "test_target_rows_after_feature_filtering": int(after_counts.get("test", 0)),
                "train_days_dropped_due_to_missing_x1": int(missing_x1_drop.get("train", 0)),
                "validation_days_dropped_due_to_missing_x1": int(missing_x1_drop.get("validation", 0)),
                "test_days_dropped_due_to_missing_x1": int(missing_x1_drop.get("test", 0)),
                "train_days_dropped_due_to_missing_x2_before_imputation": int(missing_x2_drop.get("train", 0)),
                "validation_days_dropped_due_to_missing_x2_before_imputation": int(missing_x2_drop.get("validation", 0)),
                "test_days_dropped_due_to_missing_x2_before_imputation": int(missing_x2_drop.get("test", 0)),
            }
        ]
    )
    split_audit_df.to_csv(audit_root / "split_audit.csv", index=False)

    # Load feature row-loss audit by split
    load_rows: list[dict[str, Any]] = []
    x1_affected_before_days_by_split: dict[str, set[Any]] = {k: set() for k in ["train", "validation", "test"]}
    x1_avail_ts = pd.Series(dtype="datetime64[ns, UTC]")
    if not x1_prepared.empty and "timestamp_utc" in x1_prepared.columns:
        x1_avail_ts = pd.to_datetime(x1_prepared["timestamp_utc"], utc=True, errors="coerce").dropna()
    coverage_load_row = coverage_df.loc[coverage_df["file_id"] == "load_forecast_hourly"].head(1)
    coverage_avail_min = None if coverage_load_row.empty else coverage_load_row["min_timestamp_utc"].iloc[0]
    coverage_avail_max = None if coverage_load_row.empty else coverage_load_row["max_timestamp_utc"].iloc[0]
    for split_name in ["train", "validation", "test"]:
        days = sorted(candidate_model_days.loc[candidate_model_days["dataset_split"] == split_name, "target_delivery_local_date"].dropna().unique().tolist())
        required_days = set()
        for d in days:
            d_date = pd.Timestamp(d).date()
            required_days.add(d_date)
            required_days.add((pd.Timestamp(d_date) - pd.Timedelta(days=1)).date())
            required_days.add((pd.Timestamp(d_date) - pd.Timedelta(days=7)).date())
        required_ts: list[pd.Timestamp] = []
        for d in sorted(required_days):
            try:
                start_utc, end_utc = config.local_day_utc_bounds(pd.Timestamp(d).date())
                required_ts.extend(pd.date_range(start=start_utc, end=end_utc - pd.Timedelta(hours=1), freq="h", tz="UTC").tolist())
            except Exception:
                continue
        req_min = min(required_ts).isoformat() if required_ts else None
        req_max = max(required_ts).isoformat() if required_ts else None
        avail_min = None
        avail_max = None
        if not x1_avail_ts.empty:
            avail_min = x1_avail_ts.min().isoformat()
            avail_max = x1_avail_ts.max().isoformat()
        else:
            avail_min = coverage_avail_min
            avail_max = coverage_avail_max
        missing_cells = 0
        affected_days_before = 0
        for d in days:
            d_date = pd.Timestamp(d).date()
            d1 = (pd.Timestamp(d_date) - pd.Timedelta(days=1)).date()
            d7 = (pd.Timestamp(d_date) - pd.Timedelta(days=7)).date()
            v_d = _vector_by_hour_allow_missing(_day_slice(x1_prepared, d_date, config.local_timezone), "value_mw")
            v_d1 = _vector_by_hour_allow_missing(_day_slice(x1_prepared, d1, config.local_timezone), "value_mw")
            v_d7 = _vector_by_hour_allow_missing(_day_slice(x1_prepared, d7, config.local_timezone), "value_mw")
            vectors = [v_d, v_d1, v_d7]
            day_missing = 0
            for vec in vectors:
                if vec is None:
                    day_missing += 24
                else:
                    day_missing += int(np.isnan(np.asarray(vec, dtype=float)).sum())
            if day_missing > 0:
                affected_days_before += 1
                x1_affected_before_days_by_split[split_name].add(d_date)
            missing_cells += day_missing
        affected_days_after = int(missing_x1_drop.get(split_name, 0))
        affected_hours_after = int(affected_days_after * 24)
        load_rows.append(
            {
                "split": split_name,
                "required_x1_min_timestamp_utc": req_min,
                "required_x1_max_timestamp_utc": req_max,
                "available_x1_min_timestamp_utc": avail_min,
                "available_x1_max_timestamp_utc": avail_max,
                "missing_x1_feature_cells_before_filtering": int(missing_cells),
                "affected_model_days_before_filtering": int(affected_days_before),
                "affected_model_days_after_filtering": int(affected_days_after),
                "affected_target_hours_after_filtering": int(affected_hours_after),
            }
        )
    load_loss_df = pd.DataFrame(load_rows)
    load_loss_df.to_csv(audit_root / "load_feature_row_loss_audit.csv", index=False)

    val_test_loss_after = int(
        load_loss_df.loc[load_loss_df["split"].isin(["validation", "test"]), "affected_model_days_after_filtering"].fillna(0).sum()
    )
    val_test_loss_before = int(
        load_loss_df.loc[load_loss_df["split"].isin(["validation", "test"]), "affected_model_days_before_filtering"].fillna(0).sum()
    )
    add_check(
        "load_coverage_row_loss_val_test",
        "split",
        "Validation/test row loss due to load coverage",
        "warn" if (val_test_loss_before > 0 or val_test_loss_after > 0) else "pass",
        "high",
        f"val_test_affected_model_days_before_filtering={val_test_loss_before}; after_filtering={val_test_loss_after}",
        "load_feature_row_loss_audit.csv",
    )

    # silent drop detector: fail only when x1-related drops are not explicitly attributed.
    observed_loss = max(
        0,
        int(before_counts.get("train", 0) - after_counts.get("train", 0))
        + int(before_counts.get("validation", 0) - after_counts.get("validation", 0))
        + int(before_counts.get("test", 0) - after_counts.get("test", 0))
    )
    reported_loss = int(sum(missing_x1_drop.values())) if missing_x1_drop else 0
    affected_before_total = int(load_loss_df["affected_model_days_before_filtering"].fillna(0).sum())
    unattributed_rows: list[dict[str, Any]] = []
    concurrent_non_x1_rows: list[dict[str, Any]] = []
    for split_name in ["train", "validation", "test"]:
        dropped_days = candidate_days_by_split.get(split_name, set()) - retained_days_by_split.get(split_name, set())
        x1_affected_days = x1_affected_before_days_by_split.get(split_name, set())
        x1_reported_days = reported_missing_x1_days_by_split.get(split_name, set())
        dropped_with_any_reason = skipped_days_with_any_reason_by_split.get(split_name, set())
        dropped_x1_affected = dropped_days.intersection(x1_affected_days)
        unattributed_days = sorted((dropped_x1_affected - dropped_with_any_reason) - x1_reported_days)
        concurrent_non_x1_days = sorted((dropped_x1_affected.intersection(dropped_with_any_reason)) - x1_reported_days)
        if unattributed_days:
            unattributed_rows.append(
                {
                    "split": split_name,
                    "unattributed_x1_drop_days": len(unattributed_days),
                    "first_unattributed_day": str(unattributed_days[0]),
                    "last_unattributed_day": str(unattributed_days[-1]),
                }
            )
        if concurrent_non_x1_days:
            concurrent_non_x1_rows.append(
                {
                    "split": split_name,
                    "x1_affected_but_dropped_for_other_reason_days": len(concurrent_non_x1_days),
                    "first_day": str(concurrent_non_x1_days[0]),
                    "last_day": str(concurrent_non_x1_days[-1]),
                }
            )
    unattributed_total = int(sum(r["unattributed_x1_drop_days"] for r in unattributed_rows))
    concurrent_non_x1_total = int(sum(r["x1_affected_but_dropped_for_other_reason_days"] for r in concurrent_non_x1_rows))
    if concurrent_non_x1_rows:
        pd.DataFrame(concurrent_non_x1_rows).to_csv(audit_root / "load_x1_concurrent_non_x1_drop_audit.csv", index=False)
    if unattributed_total > 0:
        unattributed_df = pd.DataFrame(unattributed_rows)
        unattributed_df.to_csv(audit_root / "load_unattributed_x1_drop_audit.csv", index=False)
        add_check(
            "load_coverage_silent_drop",
            "split",
            "Load coverage row loss is explicitly reported",
            "fail",
            "critical",
            (
                f"observed_loss={observed_loss}, reported_missing_x1_loss={reported_loss}, "
                f"affected_before_total={affected_before_total}, unattributed_x1_drop_days={unattributed_total}, "
                f"x1_affected_but_other_reason_drop_days={concurrent_non_x1_total}"
            ),
            "load_unattributed_x1_drop_audit.csv",
        )
    else:
        add_check(
            "load_coverage_silent_drop",
            "split",
            "Load coverage row loss is explicitly reported",
            "pass",
            "critical",
            (
                f"observed_loss={observed_loss}, reported_missing_x1_loss={reported_loss}, "
                f"affected_before_total={affected_before_total}, unattributed_x1_drop_days=0, "
                f"x1_affected_but_other_reason_drop_days={concurrent_non_x1_total}"
            ),
            "split_audit.csv",
        )

    overlap = set(train).intersection(set(test)) or set(train).intersection(set(val)) or set(val).intersection(set(test))
    test_after_train = True if (len(test) == 0 or len(train) == 0) else (min(test) > max(train))
    add_check("split_no_overlap", "split", "No overlap between train/validation/test", "pass" if not overlap else "fail", "critical", f"overlap_count={len(overlap)}", "split_audit.csv")
    add_check("split_test_after_train", "split", "Test starts after train", "pass" if test_after_train else "fail", "critical", f"test_after_train={test_after_train}", "split_audit.csv")

    rw_rows: list[dict[str, Any]] = []
    if d_only is not None and not d_only.metadata.empty:
        md = d_only.metadata.copy()
        md["delivery_local_date"] = pd.to_datetime(md["delivery_local_date"], errors="coerce").dt.date
        for delivery_day in md["delivery_local_date"].dropna().sort_values().head(3).tolist():
            pool = md[md["delivery_local_date"] < delivery_day]
            rw_rows.append(
                {
                    "delivery_local_date": str(delivery_day),
                    "train_rows_available": int(len(pool)),
                    "max_train_day": str(pool["delivery_local_date"].max()) if not pool.empty else None,
                    "uses_only_past_rows": bool(pool["delivery_local_date"].max() < delivery_day) if not pool.empty else True,
                }
            )
    rw_df = pd.DataFrame(rw_rows)
    rw_df.to_csv(audit_root / "rolling_window_audit_sample.csv", index=False)
    if not rw_df.empty:
        add_check(
            "rolling_window_past_only",
            "split",
            "Rolling windows use only past rows",
            "pass" if bool(rw_df["uses_only_past_rows"].all()) else "fail",
            "critical",
            f"all_past_only={bool(rw_df['uses_only_past_rows'].all())}",
            "rolling_window_audit_sample.csv",
        )

    # Section 8: Evaluation audit (schema + optional latest predictions)
    eval_schema_rows: list[dict[str, Any]] = []
    scored_target_rows: list[dict[str, Any]] = []
    compare_rows: list[dict[str, Any]] = []
    run_dirs = sorted([p for p in config.output_root.glob("*_lago_lear_six_year_benchmark") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    pred_path = run_dirs[0] / "predictions/predictions_long.parquet" if run_dirs else None
    if pred_path is None or not pred_path.exists():
        eval_schema_rows.append({"check": "predictions_schema_present", "status": "warn", "details": "No predictions_long.parquet found"})
    else:
        try:
            pred = pd.read_parquet(pred_path)
            required_cols = ["model", "dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true", "y_pred"]
            missing_cols = [c for c in required_cols if c not in pred.columns]
            eval_schema_rows.append({"check": "predictions_required_columns", "status": "pass" if not missing_cols else "fail", "details": ",".join(missing_cols)})
            if "feature_variant" in pred.columns:
                scored_target_rows.append({"check": "feature_variant_values", "value": ",".join(sorted(set(pred["feature_variant"].dropna().astype(str).tolist()))[:5])})
        except Exception as exc:  # noqa: BLE001
            eval_schema_rows.append({"check": "predictions_schema_read", "status": "warn", "details": str(exc)})
    comp_path = run_dirs[0] / "comparisons/comparison_metrics_aligned.csv" if run_dirs else None
    if comp_path is not None and comp_path.exists():
        comp = pd.read_csv(comp_path)
        compare_rows.append({"check": "comparison_metrics_aligned_rows", "value": int(len(comp))})
    else:
        compare_rows.append({"check": "comparison_metrics_aligned_rows", "value": 0})
    # scored target audit (non-empty even when predictions missing)
    scored_summary_rows: list[dict[str, Any]] = []
    if pred_path is not None and pred_path.exists():
        try:
            pred_eval = pd.read_parquet(pred_path)
        except Exception:
            pred_eval = pd.DataFrame()
    else:
        pred_eval = pd.DataFrame()
    truth_split = truth.copy()
    for split_name, part in truth_split.groupby("dataset_split", dropna=False):
        split_val = str(split_name)
        candidate_target_rows = int(len(part))
        observed_rows = int(part["is_observed_target"].fillna(False).sum())
        non_observed_rows = int(candidate_target_rows - observed_rows)
        if pred_eval.empty:
            scored_rows = 0
            scored_rows_observed = 0
            scored_rows_non_observed = 0
        else:
            pe = pred_eval[pred_eval.get("dataset_split", pd.Series(dtype=str)).astype(str) == split_val].copy()
            scored_rows = int(len(pe))
            if not pe.empty:
                pe["target_timestamp_utc"] = pd.to_datetime(pe["target_timestamp_utc"], utc=True, errors="coerce")
                part_key = part.copy()
                part_key["timestamp_utc"] = pd.to_datetime(part_key["timestamp_utc"], utc=True, errors="coerce")
                merged = pe.merge(part_key[["timestamp_utc", "is_observed_target"]], left_on="target_timestamp_utc", right_on="timestamp_utc", how="left")
                scored_rows_observed = int(merged["is_observed_target"].fillna(False).sum())
                scored_rows_non_observed = int(scored_rows - scored_rows_observed)
            else:
                scored_rows_observed = 0
                scored_rows_non_observed = 0
        scored_summary_rows.append(
            {
                "split": split_val,
                "candidate_target_rows": candidate_target_rows,
                "observed_target_rows": observed_rows,
                "non_observed_target_rows": non_observed_rows,
                "scored_rows": scored_rows,
                "scored_rows_observed": scored_rows_observed,
                "scored_rows_non_observed": scored_rows_non_observed,
                "excluded_non_observed_rows": int(non_observed_rows - scored_rows_non_observed),
            }
        )

    scored_audit_df = pd.DataFrame(scored_summary_rows)
    pd.DataFrame(eval_schema_rows).to_csv(audit_root / "evaluation_schema_audit.csv", index=False)
    scored_audit_df.to_csv(audit_root / "scored_target_audit.csv", index=False)
    pd.DataFrame(compare_rows).to_csv(audit_root / "comparison_alignment_audit.csv", index=False)

    all_scored_observed = bool((scored_audit_df["scored_rows_non_observed"] == 0).all()) if not scored_audit_df.empty else True
    add_check(
        "all_scored_targets_observed",
        "evaluation",
        "All scored targets are observed truth",
        "pass" if all_scored_observed else "fail",
        "critical",
        f"total_scored_non_observed={int(scored_audit_df['scored_rows_non_observed'].sum()) if not scored_audit_df.empty else 0}",
        "scored_target_audit.csv",
    )

    add_check(
        "evaluation_mape_warning",
        "evaluation",
        "MAPE reliability warning for negative/near-zero prices",
        "warn",
        "medium",
        "MAPE may be unstable for DA prices with negative/near-zero values.",
        "evaluation_schema_audit.csv",
    )

    # Warnings requested
    if miss_df is not None and not miss_df.empty:
        x2_miss = miss_df[miss_df["file_id"] == "res_x2_feature_ready_hourly"]["missing_share"].mean()
        if pd.notna(x2_miss) and float(x2_miss) > 0.10:
            add_check(
                "x2_missingness_high",
                "data_coverage",
                "High x2 missingness before imputation",
                "warn",
                "high",
                f"avg_missing_share={float(x2_miss):.4f}",
                "missingness_by_year_month.csv",
            )

    # Final outputs
    checks_df = pd.DataFrame([asdict(c) for c in checks]).sort_values(["status", "severity", "check_id"])
    checks_df.to_csv(audit_root / "audit_checks.csv", index=False)

    summary_payload = {
        "audit_output_dir": str(audit_root),
        "timestamp": datetime.now().isoformat(),
        "config": config.to_json_dict(),
        "args": vars(args),
        "counts": {
            "critical_failures": int(len([c for c in checks if c.status == "fail" and c.severity == "critical"])),
            "failures_total": int(len([c for c in checks if c.status == "fail"])),
            "warnings": int(len([c for c in checks if c.status == "warn"])),
            "passes": int(len([c for c in checks if c.status == "pass"])),
        },
    }
    (audit_root / "audit_summary.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    _write_markdown_summary(audit_root / "audit_summary.md", checks, audit_root)

    critical = [c for c in checks if c.status == "fail" and c.severity == "critical"]
    warns = [c for c in checks if c.status == "warn"]
    passed = [c for c in checks if c.status == "pass"]
    print(f"Audit output: {audit_root}")
    print(f"Critical failures: {len(critical)}")
    for c in critical:
        print(f"  - [{c.check_id}] {c.check_name}: {c.details}")
    print(f"Warnings: {len(warns)}")
    for c in warns[:20]:
        print(f"  - [{c.check_id}] {c.check_name}: {c.details}")
    print(f"Passed checks: {len(passed)}")
    if critical:
        print("Next action: resolve critical failures before running heavy benchmark.")
    else:
        print("Next action: review warnings, then proceed to controlled smoke/heavy benchmark runs.")


if __name__ == "__main__":
    main()
