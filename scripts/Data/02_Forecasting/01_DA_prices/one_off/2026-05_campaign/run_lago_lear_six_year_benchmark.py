from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.lago_benchmark_data import LagoDataBundle, write_data_audit_artifacts
from hourly_da.core.lago_benchmark_features import (
    LagoDailyFeatureMatrix,
    build_lago_d_only_daily_matrix,
)
from hourly_da.core.lago_comparison import build_aligned_comparison_tables, load_existing_candidate_runs
from hourly_da.core.lago_evaluation import evaluate_lago_predictions, write_evaluation_artifacts
from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig
from hourly_da.core.lago_lear_model import LagoLearFitResult, fit_predict_lago_d_only, fit_predict_lago_dplus4
from hourly_da.core.lago_multiday_features import LagoMultidayFeatureMatrix, build_lago_dplus4_direct_matrix_strict_no_future
from hourly_da.core.lago_splits import LagoSplitConfig, build_split_days, plot_split_visualization, split_summary_payload
from hourly_da.core.lago_visualization import (
    plot_abs_error_heatmap,
    plot_coefficient_heatmap,
    plot_feature_schematic,
    plot_mae_by_lead_day,
    plot_res_forecast_diagnostics,
    plot_residual_distribution,
    plot_residuals_by_hour_lead,
    plot_selected_week_overlays,
    plot_top_bottom_identification,
    plot_week_error_series,
)
from hourly_da.core.visual_weeks import WEEKLY_FEATURE_COLUMNS, select_case_weeks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staged Lago et al.-style LEAR six-year benchmark.")
    parser.add_argument("--prepare-data", action="store_true")
    parser.add_argument("--run-import", action="store_true")
    parser.add_argument("--run-res-forecast-import", action="store_true")
    parser.add_argument("--run-cleaning", action="store_true")
    parser.add_argument("--clean-res-forecast", action="store_true")
    parser.add_argument("--build-features", action="store_true")
    parser.add_argument("--run-d-only", action="store_true")
    parser.add_argument("--run-dplus4", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--plot-selected-weeks", action="store_true")
    parser.add_argument("--compare-existing", action="store_true")
    parser.add_argument("--make-notebook", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--max-origins", type=int, default=None)
    parser.add_argument("--start-local-date", type=str, default="2019-10-01")
    parser.add_argument("--end-exclusive-local-date", type=str, default="2025-10-01")
    parser.add_argument(
        "--split-policy",
        type=str,
        default="lago_104w_test",
        choices=["lago_104w_test", "thesis_official", "custom"],
    )
    parser.add_argument(
        "--dst-policy",
        type=str,
        default="skip_non_24h_local_days",
        choices=["skip_non_24h_local_days", "use_existing_project_mapping"],
    )
    parser.add_argument(
        "--x2-policy",
        type=str,
        default="res_forecast_if_available",
        choices=["aggregate_generation", "res_forecast_if_available", "no_x2", "persistence_proxy"],
    )
    parser.add_argument(
        "--x2-missing-policy",
        type=str,
        default="impute_training_median",
        choices=["impute_training_median", "fail"],
    )
    parser.add_argument(
        "--dplus4-x2-policy",
        type=str,
        default="strict_no_future_x2",
        choices=["strict_no_future_x2", "persistence_proxy"],
    )
    parser.add_argument("--allow-x2-aggregate-fallback", action="store_true")
    parser.add_argument("--allow-official-cleaned-fallback", action="store_true")
    parser.add_argument(
        "--dplus4-horizon-policy-csv",
        type=str,
        default="",
        help="Path to horizon_allowed_feature_policy.csv used by strict D..D+4 feature gate.",
    )
    parser.add_argument(
        "--dplus4-calibration-windows",
        type=str,
        default="",
        help="Comma-separated D+4 calibration windows (e.g. 1092 or 56,84,1092,1456). Empty uses config defaults.",
    )
    parser.add_argument("--no-dplus4-ensemble", action="store_true")
    parser.add_argument("--checkpoint-predictions", action="store_true")
    parser.add_argument("--dplus4-disable-full-coef-dump", action="store_true")
    parser.add_argument("--dplus4-save-full-coefs", action="store_true")
    parser.add_argument("--dplus4-checkpoint-chunk-rows", type=int, default=5000)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def _configure_logging(log_path: Path, level_name: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def _ensure_run_dirs(run_dir: Path) -> dict[str, Path]:
    paths = {
        "run": run_dir,
        "import": run_dir / "import",
        "cleaning": run_dir / "cleaning",
        "data_audit": run_dir / "data_audit",
        "features": run_dir / "features",
        "predictions": run_dir / "predictions",
        "metrics": run_dir / "metrics",
        "plots": run_dir / "plots",
        "selected_weeks": run_dir / "selected_weeks",
        "comparisons": run_dir / "comparisons",
        "notebook_support": run_dir / "notebook_support",
        "logs": run_dir / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _run_subprocess(command: list[str], *, cwd: Path, log_file: Path) -> tuple[int, str]:
    logging.info("Exec: %s", " ".join(command))
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    text = "\n".join(
        [
            f"$ {' '.join(command)}",
            "",
            proc.stdout.strip(),
            proc.stderr.strip(),
            "",
            f"exit_code={proc.returncode}",
        ]
    ).strip()
    log_file.write_text(text + "\n", encoding="utf-8")
    return proc.returncode, text


def _copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _parse_local_date(value: str) -> date:
    return pd.Timestamp(value).date()


def _build_config(args: argparse.Namespace) -> LagoLearBenchmarkConfig:
    x2_policy_map = {
        "aggregate_generation": "aggregate_generation",
        "res_forecast_if_available": "res_forecast_if_available",
        "no_x2": "no_x2",
        "persistence_proxy": "res_forecast_if_available",
    }
    return replace(
        LagoLearBenchmarkConfig(),
        benchmark_start_local_date=_parse_local_date(args.start_local_date),
        benchmark_end_exclusive_local_date=_parse_local_date(args.end_exclusive_local_date),
        dst_policy=args.dst_policy,
        x2_policy=x2_policy_map[str(args.x2_policy)],
        x2_missing_policy=str(args.x2_missing_policy),
        dplus4_x2_policy=str(args.dplus4_x2_policy),
        allow_x2_aggregate_fallback=bool(args.allow_x2_aggregate_fallback),
        allow_x2_persistence_proxy=bool(args.x2_policy == "persistence_proxy" or args.dplus4_x2_policy == "persistence_proxy"),
        allow_official_cleaned_fallback=bool(args.allow_official_cleaned_fallback),
    )


def _resolve_horizon_policy_csv(args: argparse.Namespace, config: LagoLearBenchmarkConfig) -> Path:
    value = str(getattr(args, "dplus4_horizon_policy_csv", "") or "").strip()
    if value:
        path = Path(value)
        if path.exists():
            return path
        raise FileNotFoundError(f"--dplus4-horizon-policy-csv does not exist: {path}")
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
        "Could not resolve horizon_allowed_feature_policy.csv. "
        "Provide --dplus4-horizon-policy-csv explicitly."
    )


def _resolve_dplus4_windows(args: argparse.Namespace, config: LagoLearBenchmarkConfig) -> tuple[int, ...]:
    raw = str(getattr(args, "dplus4_calibration_windows", "") or "").strip()
    if not raw:
        return tuple(int(value) for value in config.lago_windows_days)
    parsed: list[int] = []
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        parsed.append(int(value))
    if not parsed:
        raise ValueError("--dplus4-calibration-windows parsed empty after cleaning.")
    allowed = set(int(v) for v in config.lago_windows_days)
    invalid = [value for value in parsed if int(value) not in allowed]
    if invalid:
        raise ValueError(f"Unsupported D+4 calibration windows: {invalid}. Allowed: {sorted(allowed)}")
    return tuple(sorted(set(int(value) for value in parsed)))


def _default_run_toggles(args: argparse.Namespace) -> argparse.Namespace:
    if args.smoke_test:
        args.build_features = True
        args.run_d_only = True
        args.run_dplus4 = True
        args.evaluate = True
        args.plot_selected_weeks = True
        if args.max_origins is None:
            args.max_origins = 3
        if not args.allow_official_cleaned_fallback:
            args.allow_official_cleaned_fallback = True
    if args.prepare_data:
        args.build_features = True
    heavy_flags = any([args.run_d_only, args.run_dplus4, args.run_import, args.run_res_forecast_import, args.run_cleaning])
    if not heavy_flags and not args.build_features and not args.evaluate and not args.plot_selected_weeks and not args.compare_existing and not args.make_notebook:
        args.make_notebook = True
    if not args.make_notebook and not heavy_flags:
        args.make_notebook = True
    return args


def _load_naive_reference_reporting(candidate_run_paths: tuple[Path, ...]) -> pd.DataFrame:
    for run_path in candidate_run_paths:
        official_path = run_path / "official_naive_reference.json"
        reporting_path = run_path / "metrics_by_reporting_level.csv"
        if not official_path.exists() or not reporting_path.exists():
            continue
        try:
            reference = json.loads(official_path.read_text(encoding="utf-8"))
            reporting = pd.read_csv(reporting_path)
        except Exception:
            continue
        model_name = str(reference.get("model", ""))
        if not model_name:
            continue
        subset = reporting[reporting["model"].astype(str) == model_name].copy()
        if not subset.empty:
            return subset
    return pd.DataFrame()


def _weekly_feature_table_from_price(
    price_frame: pd.DataFrame,
    split_days: pd.DataFrame,
    timezone: str,
) -> pd.DataFrame:
    if price_frame.empty:
        return pd.DataFrame()
    split_lookup = {
        pd.Timestamp(local_day).date(): split
        for local_day, split in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False)
        if pd.notna(local_day) and pd.notna(split)
    }
    frame = price_frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).copy()
    frame["timestamp_local"] = frame["timestamp_utc"].dt.tz_convert(timezone)
    frame["local_delivery_date"] = frame["timestamp_local"].dt.date
    frame["dataset_split"] = frame["local_delivery_date"].map(split_lookup)
    frame = frame[frame["dataset_split"] == "test"].copy()
    if frame.empty:
        return pd.DataFrame()

    iso = frame["timestamp_local"].dt.isocalendar()
    frame["iso_year"] = iso["year"].astype(int)
    frame["iso_week"] = iso["week"].astype(int)

    rows: list[dict[str, Any]] = []
    for (iso_year, iso_week), group in frame.groupby(["iso_year", "iso_week"], dropna=False):
        week_start = date.fromisocalendar(int(iso_year), int(iso_week), 1)
        week_end = week_start + timedelta(days=6)
        values = pd.to_numeric(group["price_eur_per_mwh"], errors="coerce")
        observed = values.dropna()
        if observed.empty:
            continue
        abs_changes = observed.diff().abs().dropna()
        midpoint_month = (week_start + timedelta(days=3)).month
        if midpoint_month in (12, 1, 2):
            season = "winter"
        elif midpoint_month in (6, 7, 8):
            season = "summer"
        else:
            season = "shoulder"
        rows.append(
            {
                "iso_year": int(iso_year),
                "iso_week": int(iso_week),
                "iso_week_id": f"{int(iso_year)}-W{int(iso_week):02d}",
                "week_start_local_date": week_start.isoformat(),
                "week_end_local_date": week_end.isoformat(),
                "week_midpoint_local_date": (week_start + timedelta(days=3)).isoformat(),
                "season": season,
                "expected_hours": int(group.shape[0]),
                "observed_hours": int(observed.shape[0]),
                "observed_coverage_pct": float(observed.shape[0] / group.shape[0] * 100.0),
                "weekly_mean_price": float(observed.mean()),
                "weekly_std_price": float(observed.std(ddof=0)),
                "weekly_min_price": float(observed.min()),
                "weekly_max_price": float(observed.max()),
                "weekly_range": float(observed.max() - observed.min()),
                "negative_hours_count": int((observed < 0.0).sum()),
                "negative_hours_share": float((observed < 0.0).mean()),
                "mean_abs_hourly_change": float(abs_changes.mean()) if not abs_changes.empty else 0.0,
                "p95_abs_hourly_change": float(abs_changes.quantile(0.95)) if not abs_changes.empty else 0.0,
                "very_high_price_hours_count": int((observed >= 150.0).sum()),
            }
        )
    weekly = pd.DataFrame(rows)
    if weekly.empty:
        return weekly
    return weekly.sort_values("week_start_local_date").reset_index(drop=True)


def _build_selected_weeks(
    *,
    price_frame: pd.DataFrame,
    split_days: pd.DataFrame,
    timezone: str,
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekly = _weekly_feature_table_from_price(price_frame, split_days, timezone)
    output_dir.mkdir(parents=True, exist_ok=True)
    weekly.to_csv(output_dir / "weekly_feature_table.csv", index=False)
    if weekly.empty:
        return pd.DataFrame(), weekly
    selected_config = HourlyDAPipelineConfig()
    candidates, selected = select_case_weeks(weekly, selected_config)
    candidates.to_csv(output_dir / "selected_week_candidates.csv", index=False)
    selected.to_csv(output_dir / "selected_weeks.csv", index=False)
    return selected, weekly


def _choose_x2_frames(bundle: LagoDataBundle, policy: str) -> tuple[pd.DataFrame, pd.DataFrame | None]:
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


def _concat_fit_results(results: list[LagoLearFitResult]) -> LagoLearFitResult:
    if not results:
        empty = pd.DataFrame()
        return LagoLearFitResult(empty, empty, empty, empty, empty, empty, empty)
    return LagoLearFitResult(
        predictions_long=pd.concat([result.predictions_long for result in results if not result.predictions_long.empty], ignore_index=True)
        if any(not result.predictions_long.empty for result in results)
        else pd.DataFrame(),
        coefficients_long=pd.concat([result.coefficients_long for result in results if not result.coefficients_long.empty], ignore_index=True)
        if any(not result.coefficients_long.empty for result in results)
        else pd.DataFrame(),
        model_fit_audit=pd.concat([result.model_fit_audit for result in results if not result.model_fit_audit.empty], ignore_index=True)
        if any(not result.model_fit_audit.empty for result in results)
        else pd.DataFrame(),
        alpha_selection_audit=pd.concat([result.alpha_selection_audit for result in results if not result.alpha_selection_audit.empty], ignore_index=True)
        if any(not result.alpha_selection_audit.empty for result in results)
        else pd.DataFrame(),
        nonzero_feature_summary=pd.concat(
            [result.nonzero_feature_summary for result in results if not result.nonzero_feature_summary.empty], ignore_index=True
        )
        if any(not result.nonzero_feature_summary.empty for result in results)
        else pd.DataFrame(),
        skipped_predictions=pd.concat([result.skipped_predictions for result in results if not result.skipped_predictions.empty], ignore_index=True)
        if any(not result.skipped_predictions.empty for result in results)
        else pd.DataFrame(),
        imputation_summary=pd.concat([result.imputation_summary for result in results if not result.imputation_summary.empty], ignore_index=True)
        if any(not result.imputation_summary.empty for result in results)
        else pd.DataFrame(),
    )


def _aligned_external_predictions_for_dm(
    *,
    lago_predictions: pd.DataFrame,
    external_runs: dict[str, pd.DataFrame],
    timezone: str,
) -> pd.DataFrame:
    if lago_predictions.empty:
        return pd.DataFrame()
    key_frame = lago_predictions[
        ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true"]
    ].drop_duplicates()
    out_frames: list[pd.DataFrame] = []
    for run_name, frame in external_runs.items():
        if frame.empty:
            continue
        required = {"forecast_origin_utc", "target_timestamp_utc", "lead_day", "model", "y_pred"}
        if not required.issubset(set(frame.columns)):
            continue
        ext = frame.copy()
        ext["forecast_origin_utc"] = pd.to_datetime(ext["forecast_origin_utc"], utc=True, errors="coerce")
        ext["target_timestamp_utc"] = pd.to_datetime(ext["target_timestamp_utc"], utc=True, errors="coerce")
        if "dataset_split" not in ext.columns:
            ext["dataset_split"] = "unknown"
        ext = key_frame.merge(
            ext[
                ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "model", "y_pred"]
            ],
            on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"],
            how="inner",
        )
        if ext.empty:
            continue
        ext["model"] = ext["run_name"] = run_name + "::" + ext["model"].astype(str)
        ext["model_family"] = "external"
        ext["fs_level"] = "FS_EXTERNAL"
        ext["feature_variant"] = "aligned_existing_run"
        ext["lead_day"] = pd.to_numeric(ext["lead_day"], errors="coerce").astype("Int64")
        ext["lead_day_label"] = ext["lead_day"].map(lambda value: "D" if int(value) == 0 else f"D+{int(value)}")
        ext["forecast_origin_local"] = ext["forecast_origin_utc"].dt.tz_convert(timezone)
        ext["target_delivery_local_date"] = ext["target_timestamp_utc"].dt.tz_convert(timezone).dt.date
        ext["target_hour_local"] = ext["target_timestamp_utc"].dt.tz_convert(timezone).dt.hour.astype("Int64")
        ext["horizon_index"] = ext["lead_day"].astype(int) * 24 + ext["target_hour_local"].astype(int) + 1
        ext["target_known_at_utc"] = ext["forecast_origin_utc"]
        ext["is_observed_target"] = True
        ext["fit_time_sec"] = pd.NA
        ext["predict_time_sec"] = pd.NA
        ext["fit_time_warning"] = False
        ext["window_days"] = pd.NA
        ext["ensemble_component"] = pd.NA
        out_frames.append(ext)
    if not out_frames:
        return pd.DataFrame()
    return pd.concat(out_frames, ignore_index=True)


def _write_notebook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cells: list[dict[str, Any]] = [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# 25 Lago LEAR Six-Year Benchmark\n",
                "\n",
                "This notebook documents and runs a reproducible Lago et al. (2021)-style LEAR benchmark for Dutch hourly day-ahead prices.\n",
                "\n",
                "- **Exact Lago-style D-only** benchmark uses a daily 247-feature structure.\n",
                "- **D..D+4** benchmark is a no-leakage thesis adaptation with strict known-at filtering.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 1. Title and Purpose\n",
                "\n",
                "Goal: evaluate whether a transparent LEAR benchmark can approach or beat current complex FS2/FS3 stacks.\n",
            ],
        },
        {
            "cell_type": "code",
            "metadata": {},
            "source": [
                "from pathlib import Path\n",
                "import os\n",
                "import sys\n",
                "import json\n",
                "import pandas as pd\n",
                "\n",
                "NOTEBOOK_CWD = Path.cwd()\n",
                "REPO_ROOT = next(path for path in [NOTEBOOK_CWD, *NOTEBOOK_CWD.parents] if (path / \"scripts/Data/02_Forecasting/01_DA_prices\").exists())\n",
                "os.chdir(REPO_ROOT)\n",
                "PACKAGE_ROOT = REPO_ROOT / \"scripts/Data/02_Forecasting/01_DA_prices\"\n",
                "if str(PACKAGE_ROOT) not in sys.path:\n",
                "    sys.path.append(str(PACKAGE_ROOT))\n",
                "\n",
                "from hourly_da.core.lago_lear_config import LagoLearBenchmarkConfig\n",
                "\n",
                "config = LagoLearBenchmarkConfig()\n",
                "config\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 2. Data Scope and Provenance\n",
                "\n",
                "Inspect staged/official cleaned coverage, known-at assumptions, and missingness artifacts from run outputs.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## Importing and Constructing the Renewable Generation Forecast Variable\n",
                "\n",
                "This benchmark imports ENTSO-E A69 day-ahead RES forecasts by PSR type for NL:\n",
                "- `B16` solar\n",
                "- `B18` wind offshore\n",
                "- `B19` wind onshore\n",
                "\n",
                "The aggregate Lago `x2` variable is constructed as:\n",
                "`x2 = B16 + B18 + B19` per timestamp.\n",
                "\n",
                "The exact D-only Lago variant uses only this aggregate `x2` vector (not separate component vectors) to preserve the 247-feature structure.\n",
                "\n",
                "Known-at convention for A69 PSR imports:\n",
                "- `known_at_rule = day_ahead_local_08_assumption_a69_psr`\n",
                "- enforce `known_at_utc <= forecast_origin_utc` for feature eligibility.\n",
                "\n",
                "Feature-ready RES policy used for Lago x2:\n",
                "- strict hourly RES files are preserved as audit outputs\n",
                "- benchmark x2 prefers feature-ready hourly files\n",
                "- wind (`B18`,`B19`) is never zero-filled\n",
                "- partial hours with `3/4` native points are accepted and flagged\n",
                "- solar (`B16`) may be zero-filled only during physically dark NL hours (daylight classifier documented in cleaning diagnostics)\n",
                "- aggregate x2 row is usable only when all three components are feature-ready for that hour\n",
                "\n",
                "Missing RES forecast handling for the selected benchmark variant (`LEAR_LAGO_247_IMPUTED_X2`):\n",
                "- remaining missing `x2` feature values are imputed with rolling **training-window median** only\n",
                "- no row is dropped solely because `x2` has missing values when `--x2-missing-policy impute_training_median`\n",
                "- `y_true` values are never imputed\n",
                "- inspect: `features/missing_feature_summary.csv`, `features/imputation_summary.csv`, `features/dropped_rows_by_reason.csv`, `features/variant_feature_counts.csv`\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 3. Lago Feature Construction\n",
                "\n",
                "Expected exact D-only feature count:\n",
                "- 96 price lags\n",
                "- 48 current exogenous vectors (24 load + 24 RES)\n",
                "- 96 lagged exogenous vectors\n",
                "- 7 weekday dummies\n",
                "- **Total = 247**\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 4. D+4 Adaptation\n",
                "\n",
                "D+4 uses direct lead-day/hour models with strict known-at filtering and explicit x2 policy metadata.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 5. Model Methodology\n",
                "\n",
                "For each calibration window (56, 84, 1092, 1456 days):\n",
                "1. Standardize features\n",
                "2. Select alpha via `LassoLarsIC(criterion='aic')`\n",
                "3. Refit final coordinate-descent `Lasso`\n",
                "4. Train per-hour (and per lead-day/hour for D+4)\n",
                "5. Ensemble = arithmetic mean across available windows\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 6. Running the Pipeline\n",
                "\n",
                "### Preflight / smoke\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_six_year_benchmark.py --smoke-test --max-origins 3 --allow-official-cleaned-fallback\n",
                "```\n",
                "\n",
                "### Import dry-run\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --dry-run --start-year 2019 --end-year 2025\n",
                "```\n",
                "\n",
                "### RES A69 by-PSR import dry-run\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py --dry-run --start-year 2019 --end-year 2025 --psr-types B16 B18 B19\n",
                "```\n",
                "\n",
                "### Actual import\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --run-import --start-year 2019 --end-year 2025 --output-root data/00_raw_lago_lear_six_year\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py --run-import --start-year 2019 --end-year 2025 --output-root data/00_raw_lago_lear_six_year --psr-types B16 B18 B19\n",
                "```\n",
                "\n",
                "### Cleaning dry-run\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py --dry-run\n",
                "```\n",
                "\n",
                "### Actual cleaning\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py --run-cleaning --raw-root data/00_raw_lago_lear_six_year --output-root data/01_cleaned_lago_lear_six_year\n",
                "```\n",
                "\n",
                "### Full D-only\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_six_year_benchmark.py --build-features --run-d-only --evaluate --plot-selected-weeks --compare-existing --split-policy lago_104w_test\n",
                "```\n",
                "\n",
                "### Full D+4\n",
                "```bash\n",
                ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_six_year_benchmark.py --build-features --run-dplus4 --evaluate --plot-selected-weeks --compare-existing --split-policy lago_104w_test --dplus4-x2-policy strict_no_future_x2\n",
                "```\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 7. Evaluation Results\n",
                "Load `metrics_overall.csv`, `metrics_by_lead_day.csv`, `operational_diagnostics.csv`, and `dm_tests.csv` from a run directory.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 8. Selected-Week Visual Interpretation\n",
                "Inspect winter/summer/high-volatility/high-price/low-price/negative-price weeks and ranking diagnostics.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 9. Comparison with Current FS2/FS3\n",
                "Use aligned timestamps/origins only. Mark non-overlapping periods as not comparable.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 10. Limitations and Thesis Interpretation\n",
                "\n",
                "- D-only is the closest Lago-style replication.\n",
                "- D+4 is a no-leakage adaptation, not an exact Lago replication.\n",
                "- Known-at assumptions are conservative internal project assumptions.\n",
                "- MAPE is reported but not used for model selection under negative/near-zero prices.\n",
            ],
        },
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "## 11. Final Conclusion Template\n",
                "\n",
                "- Does Lago LEAR ensemble beat naive?\n",
                "- Does it approach FS3?\n",
                "- Which window performs best?\n",
                "- Is short-window or long-window calibration better?\n",
                "- Does D+4 degrade smoothly with lead_day?\n",
                "- Does top/bottom-hour identification support optimization needs?\n",
            ],
        },
    ]
    notebook_payload = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook_payload, indent=1), encoding="utf-8")


def _write_docs(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Lago LEAR Six-Year Benchmark",
        "",
        "## Goal",
        "Implement a reproducible Lago et al. (2021)-style LEAR benchmark for Dutch hourly day-ahead prices, plus a no-leakage D..D+4 thesis adaptation.",
        "",
        "## Data Period",
        "- Local delivery start: 2019-10-01",
        "- Local delivery end (inclusive): 2025-09-30",
        "- End exclusive: 2025-10-01",
        "- Internal timestamp storage: UTC",
        "",
        "## Import and Cleaning",
        "Staged roots only:",
        "- raw: `data/00_raw_lago_lear_six_year`",
        "- cleaned: `data/01_cleaned_lago_lear_six_year`",
        "",
        "Base ENTSO-E import:",
        "```bash",
        ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py --dry-run --start-year 2019 --end-year 2025",
        "```",
        "",
        "A69 RES-by-PSR import:",
        "```bash",
        ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py --dry-run --start-year 2019 --end-year 2025 --psr-types B16 B18 B19",
        "```",
        "",
        "Cleaning:",
        "```bash",
        ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py --run-cleaning --raw-root data/00_raw_lago_lear_six_year --output-root data/01_cleaned_lago_lear_six_year",
        "```",
        "",
        "## Feature Definitions",
        "Exact D-only structure (247 features):",
        "- price lags: `p_(d-1), p_(d-2), p_(d-3), p_(d-7)` (96)",
        "- current exogenous: `x1_d` load + `x2_d` RES forecast (48)",
        "- lagged exogenous: `x1_(d-1), x1_(d-7), x2_(d-1), x2_(d-7)` (96)",
        "- weekday dummies (7)",
        "",
        "x2 mapping:",
        "- preferred: A69 by-PSR sum `B16 + B18 + B19`",
        "- fallback: aggregate DA generation forecast only when explicitly allowed",
        "",
        "## D+4 Adaptation",
        "Direct lead-day/hour models with strict known-at checks (`known_at_utc <= forecast_origin_utc`).",
        "",
        "## Model Specification",
        "- LEAR windows: 56, 84, 1092, 1456 days",
        "- alpha selection: `LassoLarsIC(criterion='aic')`",
        "- final fit: coordinate-descent `Lasso` on standardized features",
        "- ensemble: arithmetic mean over available windows",
        "",
        "## Runner",
        "```bash",
        ".venv\\Scripts\\python.exe scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_six_year_benchmark.py --smoke-test --max-origins 3 --allow-official-cleaned-fallback",
        "```",
        "",
        "Heavy runs require explicit flags:",
        "- `--run-d-only`",
        "- `--run-dplus4`",
        "",
        "## Outputs",
        "Runs are written under:",
        "- `data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/<timestamp>_lago_lear_six_year_benchmark/`",
        "",
        "Key artifacts include:",
        "- `run_summary.json`",
        "- `config_resolved.json`",
        "- `data_sources.json`",
        "- feature schemas and known-at audits",
        "- predictions (`predictions_long.parquet`)",
        "- coefficients (`coefficients_long.parquet`)",
        "- metrics and diagnostics",
        "- aligned comparison reports",
        "",
        "## Limitations",
        "- D+4 is an adaptation, not exact Lago.",
        "- known_at assumptions are project-internal conservative assumptions.",
        "- MAPE is reported but not a robust selection criterion for negative/near-zero prices.",
        "- comparisons are valid only on aligned overlap timestamps and observed targets.",
        "",
        "## Thesis Usage",
        "Use this benchmark as a transparent reference model and clearly separate it from official FS-stage outputs and official split reporting.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = _default_run_toggles(parse_args())
    config = _build_config(args)
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_lago_lear_six_year_benchmark"
    run_dir = config.output_root / run_id
    paths = _ensure_run_dirs(run_dir)
    _configure_logging(paths["logs"] / "run.log", args.log_level)

    logging.info("Run directory: %s", run_dir)
    (paths["run"] / "config_resolved.json").write_text(json.dumps(config.to_json_dict(), indent=2), encoding="utf-8")

    status: dict[str, Any] = {
        "run_id": run_id,
        "started_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "smoke_test": bool(args.smoke_test),
        "split_policy": str(args.split_policy),
        "requested_flags": {
            "build_features": bool(args.build_features),
            "run_d_only": bool(args.run_d_only),
            "run_dplus4": bool(args.run_dplus4),
            "evaluate": bool(args.evaluate),
            "plot_selected_weeks": bool(args.plot_selected_weeks),
            "compare_existing": bool(args.compare_existing),
            "make_notebook": bool(args.make_notebook),
            "checkpoint_predictions": bool(args.checkpoint_predictions),
        },
        "stages": {},
        "notes": [],
    }

    repo_root = Path.cwd()
    python_exe = Path(sys.executable)

    if args.run_import:
        cmd = [
            str(python_exe),
            "scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_data_import.py",
            "--run-import",
            "--start-year",
            "2019",
            "--end-year",
            "2025",
            "--output-root",
            str(config.staged_raw_root),
            "--max-pages-per-year",
            "250",
            "--datasets",
            "all",
            "--log-level",
            args.log_level,
        ]
        if args.force:
            cmd.append("--force")
        else:
            cmd.append("--skip-existing")
        code, _ = _run_subprocess(cmd, cwd=repo_root, log_file=paths["import"] / "base_import_command.log")
        status["stages"]["base_import"] = "completed" if code == 0 else f"failed_exit_{code}"
    else:
        status["stages"]["base_import"] = "not_requested"

    if args.run_res_forecast_import:
        cmd = [
            str(python_exe),
            "scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_res_forecast_import.py",
            "--run-import",
            "--start-year",
            "2019",
            "--end-year",
            "2025",
            "--output-root",
            str(config.staged_raw_root),
            "--psr-types",
            "B16",
            "B18",
            "B19",
            "--log-level",
            args.log_level,
        ]
        if args.force:
            cmd.append("--force")
        else:
            cmd.append("--skip-existing")
        code, _ = _run_subprocess(cmd, cwd=repo_root, log_file=paths["import"] / "res_import_command.log")
        status["stages"]["res_import"] = "completed" if code == 0 else f"failed_exit_{code}"
    else:
        status["stages"]["res_import"] = "not_requested"

    if args.run_cleaning or args.clean_res_forecast:
        cmd = [
            str(python_exe),
            "scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_cleaning.py",
            "--run-cleaning",
            "--raw-root",
            str(config.staged_raw_root),
            "--output-root",
            str(config.staged_cleaned_root),
            "--start-local-date",
            config.benchmark_start_local_date.isoformat(),
            "--end-exclusive-local-date",
            config.benchmark_end_exclusive_local_date.isoformat(),
            "--local-timezone",
            config.local_timezone,
            "--regions",
            config.target_region,
            "--log-level",
            args.log_level,
        ]
        code, _ = _run_subprocess(cmd, cwd=repo_root, log_file=paths["cleaning"] / "cleaning_command.log")
        status["stages"]["cleaning"] = "completed" if code == 0 else f"failed_exit_{code}"
    else:
        status["stages"]["cleaning"] = "not_requested"

    # Copy known staged import/cleaning audits into this run folder when present.
    base_import_status = config.staged_raw_root / "lago_import_audit" / "import_status.csv"
    res_import_status = (
        config.staged_raw_root
        / "RES_Generation_Forecast/NL/A69_DA_Wind_Solar_Forecast_By_PSR/res_forecast_import_status.csv"
    )
    cleaning_status = config.staged_cleaned_root / "lago_cleaning_audit" / "cleaning_status.csv"
    _copy_if_exists(base_import_status, paths["import"] / "import_status.csv")
    _copy_if_exists(res_import_status, paths["import"] / "res_forecast_import_status.csv")
    _copy_if_exists(cleaning_status, paths["cleaning"] / "cleaning_status.csv")

    needs_data = any(
        [
            args.prepare_data,
            args.build_features,
            args.run_d_only,
            args.run_dplus4,
            args.evaluate,
            args.plot_selected_weeks,
            args.compare_existing,
        ]
    )

    bundle: LagoDataBundle | None = None
    split_days = pd.DataFrame()
    selected_weeks = pd.DataFrame()
    weekly_features = pd.DataFrame()
    d_only_features: LagoDailyFeatureMatrix | None = None
    dplus4_features: LagoMultidayFeatureMatrix | None = None
    predictions = pd.DataFrame()
    coefficients = pd.DataFrame()
    skipped_predictions = pd.DataFrame()
    external_aligned_predictions = pd.DataFrame()

    if needs_data:
        bundle = write_data_audit_artifacts(config, paths["data_audit"])
        status["stages"]["data_audit"] = "completed"
        split_cfg = LagoSplitConfig(split_policy=args.split_policy)
        split_days = build_split_days(config, split_cfg)
        split_days.to_csv(paths["data_audit"] / "split_days.csv", index=False)
        split_summary = split_summary_payload(split_days, args.split_policy)
        (paths["data_audit"] / "split_summary.json").write_text(json.dumps(split_summary, indent=2), encoding="utf-8")
        plot_split_visualization(split_days, paths["data_audit"] / "split_visualization.png")
        selected_weeks, weekly_features = _build_selected_weeks(
            price_frame=bundle.price_frame,
            split_days=split_days,
            timezone=config.local_timezone,
            output_dir=paths["selected_weeks"],
        )
        status["stages"]["split_selection"] = "completed"
    else:
        status["stages"]["data_audit"] = "not_requested"
        status["stages"]["split_selection"] = "not_requested"

    if args.build_features and bundle is not None:
        x1_da = bundle.exogenous_frames.get("da_total_load_forecast", pd.DataFrame())
        x1_wa = bundle.exogenous_frames.get("week_ahead_total_load_forecast", pd.DataFrame())
        x2_primary, x2_fallback = _choose_x2_frames(bundle, args.x2_policy)

        d_only_features = build_lago_d_only_daily_matrix(
            price_df=bundle.price_frame,
            load_forecast_df=x1_da,
            generation_forecast_df=x2_primary,
            generation_forecast_fallback_df=x2_fallback,
            config=config,
        )
        if d_only_features.feature_schema.get("total_feature_count") != 247:
            raise RuntimeError("D-only feature matrix failed validation: expected 247 features.")
        expected_counts = {
            "price_lag_count": 96,
            "current_exogenous_count": 48,
            "lagged_exogenous_count": 96,
            "weekday_count": 7,
        }
        for key, expected in expected_counts.items():
            if int(d_only_features.feature_schema.get(key, -1)) != int(expected):
                raise RuntimeError(f"D-only feature schema count mismatch for {key}: expected {expected}.")
        if not d_only_features.X.empty:
            bad_cols = [col for col in d_only_features.X.columns if "target_timestamp" in str(col) or str(col).startswith("y_")]
            if bad_cols:
                raise RuntimeError(f"Leakage validation failed in D-only features: {bad_cols[:5]}")
        horizon_policy_csv = _resolve_horizon_policy_csv(args, config)
        dplus4_features = build_lago_dplus4_direct_matrix_strict_no_future(
            price_df=bundle.price_frame,
            load_forecast_df=x1_da,
            week_ahead_load_forecast_df=x1_wa,
            generation_forecast_df=x2_primary,
            config=config,
            horizon_policy_csv=horizon_policy_csv,
            hard_fail_on_policy_violation=True,
        )
        if not dplus4_features.X_long.empty:
            bad_cols = [col for col in dplus4_features.X_long.columns if "target_timestamp" in str(col)]
            if bad_cols:
                raise RuntimeError(f"Leakage validation failed in D+4 features: {bad_cols[:5]}")

        d_only_features.X.to_parquet(paths["features"] / "d_only_X.parquet", index=False)
        d_only_features.Y.to_parquet(paths["features"] / "d_only_Y.parquet", index=False)
        d_only_features.metadata.to_parquet(paths["features"] / "d_only_metadata.parquet", index=False)
        d_only_features.skipped_rows.to_csv(paths["features"] / "d_only_skipped_rows.csv", index=False)
        d_only_features.known_at_violations.to_csv(paths["features"] / "known_at_violations_d_only.csv", index=False)
        (paths["features"] / "feature_schema_d_only.json").write_text(
            json.dumps(d_only_features.feature_schema, indent=2),
            encoding="utf-8",
        )

        dplus4_features.X_long.to_parquet(paths["features"] / "dplus4_X_long.parquet", index=False)
        dplus4_features.y_long.to_parquet(paths["features"] / "dplus4_y_long.parquet", index=False)
        dplus4_features.metadata_long.to_parquet(paths["features"] / "dplus4_metadata_long.parquet", index=False)
        dplus4_features.skipped_rows.to_csv(paths["features"] / "dplus4_skipped_rows.csv", index=False)
        dplus4_features.known_at_violations.to_csv(paths["features"] / "known_at_violations_dplus4.csv", index=False)
        dplus4_features.unavailable_exogenous_by_lead_day.to_csv(
            paths["features"] / "unavailable_exogenous_by_lead_day.csv",
            index=False,
        )
        dplus4_features.disallowed_feature_attempts.to_csv(
            paths["features"] / "dplus4_disallowed_feature_attempts.csv",
            index=False,
        )
        dplus4_features.forbidden_columns_audit.to_csv(
            paths["features"] / "dplus4_forbidden_columns_audit.csv",
            index=False,
        )
        dplus4_features.feature_availability_by_horizon.to_csv(
            paths["features"] / "dplus4_feature_availability_by_horizon.csv",
            index=False,
        )
        missing_feature_parts = []
        if hasattr(d_only_features, "missing_feature_summary") and not d_only_features.missing_feature_summary.empty:
            d_only_missing = d_only_features.missing_feature_summary.copy()
            if not split_days.empty and not d_only_features.metadata.empty:
                split_lookup = {
                    pd.Timestamp(value).date(): split
                    for value, split in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False)
                    if pd.notna(value) and pd.notna(split)
                }
                d_only_dates = pd.to_datetime(d_only_features.metadata["delivery_local_date"], errors="coerce").dt.date
                d_only_split = d_only_dates.map(split_lookup)
                # summarize by split using per-row masks from X.
                split_rows = []
                for split_name in sorted(set([str(v) for v in d_only_split.dropna().unique().tolist()])):
                    idx = d_only_split == split_name
                    if not idx.any():
                        continue
                    Xs = d_only_features.X.loc[idx.values].copy()
                    for col in Xs.columns:
                        s = pd.to_numeric(Xs[col], errors="coerce")
                        split_rows.append(
                            {
                                "feature_name": col,
                                "feature_family": "x2_res" if str(col).startswith("x2_") else ("x1_load" if str(col).startswith("x1_") else ("price_lag" if str(col).startswith("price_") else ("weekday" if str(col).startswith("dow_") else "other"))),
                                "total_rows": int(s.shape[0]),
                                "missing_count": int(s.isna().sum()),
                                "missing_share": float(s.isna().mean()),
                                "split": split_name,
                                "lead_day": "D",
                            }
                        )
                d_only_missing = pd.DataFrame(split_rows) if split_rows else d_only_missing
            missing_feature_parts.append(d_only_missing)
        if hasattr(dplus4_features, "missing_feature_summary") and not dplus4_features.missing_feature_summary.empty:
            dplus4_missing = []
            for lead_day, group in dplus4_features.X_long.join(dplus4_features.metadata_long[["lead_day", "target_delivery_local_date"]]).groupby("lead_day"):
                for col in dplus4_features.X_long.columns:
                    s = pd.to_numeric(group[col], errors="coerce")
                    dplus4_missing.append(
                        {
                            "feature_name": col,
                            "feature_family": "x2_res" if str(col).startswith("x2_") else ("x1_load" if str(col).startswith("x1_") else ("price_lag" if str(col).startswith("price_") else "other")),
                            "total_rows": int(s.shape[0]),
                            "missing_count": int(s.isna().sum()),
                            "missing_share": float(s.isna().mean()),
                            "split": "all",
                            "lead_day": f"D+{int(lead_day)}" if int(lead_day) > 0 else "D",
                        }
                    )
            if dplus4_missing:
                missing_feature_parts.append(pd.DataFrame(dplus4_missing))
        missing_feature_summary = pd.concat(missing_feature_parts, ignore_index=True) if missing_feature_parts else pd.DataFrame()
        missing_feature_summary.to_csv(paths["features"] / "missing_feature_summary.csv", index=False)
        d_only_features.variant_feature_counts.to_csv(paths["features"] / "variant_feature_counts.csv", index=False)
        d_only_features.dropped_rows_by_reason.to_csv(paths["features"] / "dropped_rows_by_reason.csv", index=False)
        if str(args.x2_missing_policy) == "impute_training_median" and not d_only_features.dropped_rows_by_reason.empty:
            dropped_x2 = d_only_features.dropped_rows_by_reason["reason"].astype(str).str.contains("missing_x2", na=False).sum()
            if int(dropped_x2) != 0:
                raise RuntimeError("Validation failed: rows dropped due to x2 missing while x2_missing_policy=impute_training_median.")
        (paths["features"] / "feature_schema_dplus4.json").write_text(
            json.dumps(dplus4_features.feature_schema, indent=2),
            encoding="utf-8",
        )
        status["feature_variants"] = {
            "d_only": "LEAR_LAGO_247_IMPUTED_X2",
            "dplus4": "LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE",
        }
        status["feature_build_paths"] = {
            "d_only_builder": "hourly_da.core.lago_benchmark_features.build_lago_d_only_daily_matrix",
            "dplus4_builder": "hourly_da.core.lago_multiday_features.build_lago_dplus4_direct_matrix_strict_no_future",
            "dplus4_horizon_policy_csv": str(horizon_policy_csv),
        }

        known_violations = pd.concat(
            [d_only_features.known_at_violations, dplus4_features.known_at_violations],
            ignore_index=True,
        )
        if known_violations.empty:
            known_violations = pd.DataFrame(
                columns=[
                    "delivery_local_date",
                    "delivery_start_local_date",
                    "lead_day",
                    "frame",
                    "violation_count",
                ]
            )
        known_violations.to_csv(paths["features"] / "known_at_violations.csv", index=False)
        known_violations.to_csv(paths["data_audit"] / "known_at_violations.csv", index=False)
        if config.strict_known_at and not known_violations.empty:
            raise RuntimeError("Known-at violations found. See features/known_at_violations.csv")

        skipped_days = d_only_features.skipped_rows[
            d_only_features.skipped_rows.get("reason", pd.Series(dtype=str)).astype(str).str.contains("dst_non_24h_day")
        ].copy()
        skipped_days.to_csv(paths["data_audit"] / "skipped_days.csv", index=False)
        status["stages"]["feature_build"] = "completed"
    else:
        status["stages"]["feature_build"] = "not_requested"

    fit_results: list[LagoLearFitResult] = []
    max_origins = args.max_origins
    if args.run_d_only:
        if d_only_features is None:
            raise RuntimeError("D-only run requested but features were not built. Use --build-features.")
        fit_results.append(
            fit_predict_lago_d_only(
                X=d_only_features.X,
                Y=d_only_features.Y,
                metadata=d_only_features.metadata,
                split_days=split_days,
                config=config,
                max_origins=max_origins,
            )
        )
        status["stages"]["run_d_only"] = "completed"
    else:
        status["stages"]["run_d_only"] = "not_requested"

    if args.run_dplus4:
        if dplus4_features is None:
            raise RuntimeError("D+4 run requested but features were not built. Use --build-features.")
        dplus4_windows = _resolve_dplus4_windows(args, config)
        dplus4_use_ensemble = not bool(args.no_dplus4_ensemble)
        dplus4_save_full_coefs = bool(args.dplus4_save_full_coefs) and (not bool(args.dplus4_disable_full_coef_dump))
        checkpoint_dir = paths["predictions"] / "checkpoints" if bool(args.checkpoint_predictions) else None
        progress_path = paths["run"] / "run_progress_dplus4.json"
        fit_results.append(
            fit_predict_lago_dplus4(
                X_long=dplus4_features.X_long,
                y_long=dplus4_features.y_long,
                metadata_long=dplus4_features.metadata_long,
                split_days=split_days,
                config=config,
                max_origins=max_origins,
                dplus4_windows=dplus4_windows,
                dplus4_use_ensemble=dplus4_use_ensemble,
                checkpoint_predictions=bool(args.checkpoint_predictions),
                checkpoint_dir=checkpoint_dir,
                checkpoint_chunk_rows=int(args.dplus4_checkpoint_chunk_rows),
                dplus4_save_full_coefs=dplus4_save_full_coefs,
                progress_path=progress_path,
            )
        )
        status["dplus4_runtime_options"] = {
            "calibration_windows": [int(value) for value in dplus4_windows],
            "ensemble_enabled": bool(dplus4_use_ensemble),
            "checkpoint_predictions": bool(args.checkpoint_predictions),
            "checkpoint_dir": str(checkpoint_dir) if checkpoint_dir is not None else None,
            "checkpoint_chunk_rows": int(args.dplus4_checkpoint_chunk_rows),
            "save_full_coefs": bool(dplus4_save_full_coefs),
            "progress_path": str(progress_path),
        }
        status["stages"]["run_dplus4"] = "completed"
    else:
        status["stages"]["run_dplus4"] = "not_requested"

    fit_result = _concat_fit_results(fit_results)
    predictions = fit_result.predictions_long.copy()
    coefficients = fit_result.coefficients_long.copy()
    skipped_predictions = fit_result.skipped_predictions.copy()

    if not predictions.empty:
        predictions.insert(0, "run_id", run_id)
        if "window_days" in predictions.columns:
            predictions["window_days"] = predictions["window_days"].astype(str)
        required_prediction_cols = [
            "run_id",
            "model",
            "model_family",
            "fs_level",
            "dataset_split",
            "forecast_origin_utc",
            "target_timestamp_utc",
            "lead_day",
            "y_true",
            "y_pred",
            "fit_time_sec",
            "predict_time_sec",
        ]
        missing_cols = [column for column in required_prediction_cols if column not in predictions.columns]
        if missing_cols:
            raise RuntimeError(f"Prediction schema validation failed, missing columns: {missing_cols}")
        predictions.to_parquet(paths["predictions"] / "predictions_long.parquet", index=False)
        predictions.to_csv(paths["predictions"] / "predictions_long.csv", index=False)
    else:
        pd.DataFrame().to_csv(paths["predictions"] / "predictions_long.csv", index=False)
    if not coefficients.empty:
        coefficients.to_parquet(paths["predictions"] / "coefficients_long.parquet", index=False)
        coefficients.to_csv(paths["predictions"] / "coefficients_long.csv", index=False)
    else:
        pd.DataFrame().to_csv(paths["predictions"] / "coefficients_long.csv", index=False)
    fit_result.model_fit_audit.to_csv(paths["predictions"] / "model_fit_audit.csv", index=False)
    fit_result.alpha_selection_audit.to_csv(paths["predictions"] / "alpha_selection_audit.csv", index=False)
    fit_result.nonzero_feature_summary.to_csv(paths["predictions"] / "nonzero_feature_summary.csv", index=False)
    fit_result.imputation_summary.to_csv(paths["features"] / "imputation_summary.csv", index=False)
    skipped_predictions.to_csv(paths["predictions"] / "skipped_predictions.csv", index=False)

    if args.smoke_test:
        if predictions.empty or "lead_day" not in predictions.columns:
            raise RuntimeError("Smoke test failed: no predictions were generated.")
        if args.run_d_only and predictions[predictions["lead_day"] == 0].empty:
            raise RuntimeError("Smoke test failed: no D-only predictions.")
        if args.run_dplus4 and predictions[predictions["lead_day"] > 0].empty:
            raise RuntimeError("Smoke test failed: no D+4 predictions.")

    comparison_alignment = pd.DataFrame()
    comparison_metrics = pd.DataFrame()
    comparison_weeks = pd.DataFrame()
    if args.compare_existing and not predictions.empty:
        external_runs = load_existing_candidate_runs(config)
        comparison_alignment, comparison_metrics, comparison_weeks = build_aligned_comparison_tables(
            predictions,
            external_runs,
            selected_weeks=selected_weeks,
        )
        comparison_alignment.to_csv(paths["comparisons"] / "comparison_alignment_report.csv", index=False)
        comparison_metrics.to_csv(paths["comparisons"] / "comparison_metrics_aligned.csv", index=False)
        comparison_weeks.to_csv(paths["comparisons"] / "comparison_selected_weeks_aligned.csv", index=False)
        external_aligned_predictions = _aligned_external_predictions_for_dm(
            lago_predictions=predictions,
            external_runs=external_runs,
            timezone=config.local_timezone,
        )
        status["stages"]["comparison"] = "completed"
    else:
        status["stages"]["comparison"] = "not_requested"

    if args.evaluate and not predictions.empty:
        naive_reporting = _load_naive_reference_reporting(config.fs_candidate_run_paths)
        evaluation_tables = evaluate_lago_predictions(
            predictions,
            naive_reference_reporting=naive_reporting,
            selected_weeks=selected_weeks,
            external_aligned_predictions=external_aligned_predictions,
        )
        write_evaluation_artifacts(paths["metrics"], evaluation_tables)
        summary = {
            "models": sorted(predictions["model"].astype(str).unique().tolist()),
            "rows_predictions": int(predictions.shape[0]),
            "rows_scored": int(predictions["y_true"].notna().sum()),
            "selected_weeks_count": int(selected_weeks.shape[0]),
            "naive_reference_available": bool(not naive_reporting.empty),
        }
        (paths["metrics"] / "evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        status["stages"]["evaluation"] = "completed"
    elif args.evaluate and predictions.empty:
        status["stages"]["evaluation"] = "requested_but_no_predictions"
        status["notes"].append("Evaluation requested but predictions table was empty.")
        evaluation_tables = {}
    else:
        status["stages"]["evaluation"] = "not_requested"
        evaluation_tables = {}

    if args.plot_selected_weeks and not predictions.empty:
        prediction_for_plots = predictions.copy()
        if not external_aligned_predictions.empty:
            prediction_for_plots = pd.concat([prediction_for_plots, external_aligned_predictions], ignore_index=True)
        plot_selected_week_overlays(prediction_for_plots, selected_weeks, paths["plots"])
        plot_week_error_series(prediction_for_plots, selected_weeks, paths["plots"])
        plot_abs_error_heatmap(predictions, paths["plots"])
        plot_residual_distribution(predictions, paths["plots"])
        plot_residuals_by_hour_lead(predictions, paths["plots"])
        plot_top_bottom_identification(prediction_for_plots, selected_weeks, paths["plots"])
        metrics_by_lead = evaluation_tables.get("metrics_by_lead_day", pd.DataFrame())
        plot_mae_by_lead_day(metrics_by_lead, paths["plots"])
        plot_coefficient_heatmap(coefficients, paths["plots"])
        plot_feature_schematic(paths["plots"])
        if bundle is not None:
            plot_res_forecast_diagnostics(
                bundle.exogenous_frames.get("da_res_generation_forecast_by_psr", pd.DataFrame()),
                bundle.exogenous_frames.get("da_res_generation_forecast", pd.DataFrame()),
                paths["plots"],
            )
        status["stages"]["plotting"] = "completed"
    else:
        status["stages"]["plotting"] = "not_requested"

    if args.make_notebook:
        _write_notebook(config.notebook_path)
        _write_docs(Path("docs/forecasting/lago_lear_six_year_benchmark.md"))
        status["stages"]["notebook_docs"] = "completed"
    else:
        status["stages"]["notebook_docs"] = "not_requested"

    # Copy primary artifacts to run root for easier lookup.
    for source_path, target_name in [
        (paths["import"] / "import_status.csv", "import_status.csv"),
        (paths["cleaning"] / "cleaning_status.csv", "cleaning_status.csv"),
        (paths["data_audit"] / "data_coverage_summary.csv", "data_coverage_summary.csv"),
        (paths["data_audit"] / "split_summary.json", "split_summary.json"),
        (paths["features"] / "feature_schema_d_only.json", "feature_schema_d_only.json"),
        (paths["features"] / "feature_schema_dplus4.json", "feature_schema_dplus4.json"),
        (paths["data_audit"] / "known_at_violations.csv", "known_at_violations.csv"),
        (paths["data_audit"] / "skipped_days.csv", "skipped_days.csv"),
        (paths["predictions"] / "skipped_predictions.csv", "skipped_predictions.csv"),
        (paths["predictions"] / "predictions_long.parquet", "predictions_long.parquet"),
        (paths["predictions"] / "coefficients_long.parquet", "coefficients_long.parquet"),
        (paths["metrics"] / "metrics_overall.csv", "metrics_overall.csv"),
        (paths["metrics"] / "metrics_by_lead_day.csv", "metrics_by_lead_day.csv"),
        (paths["metrics"] / "metrics_by_reporting_level.csv", "metrics_by_reporting_level.csv"),
        (paths["metrics"] / "metrics_by_selected_week.csv", "metrics_by_selected_week.csv"),
        (paths["metrics"] / "operational_diagnostics.csv", "operational_diagnostics.csv"),
        (paths["metrics"] / "dm_tests.csv", "dm_tests.csv"),
        (paths["comparisons"] / "comparison_alignment_report.csv", "comparison_alignment_report.csv"),
        (paths["comparisons"] / "comparison_metrics_aligned.csv", "comparison_metrics_aligned.csv"),
    ]:
        _copy_if_exists(source_path, paths["run"] / target_name)

    data_sources_payload = {
        "source_root_used": bundle.source_root_used if bundle is not None else None,
        "allow_official_cleaned_fallback": bool(config.allow_official_cleaned_fallback),
        "x2_policy": args.x2_policy,
        "dplus4_x2_policy": args.dplus4_x2_policy,
    }
    (paths["run"] / "data_sources.json").write_text(json.dumps(data_sources_payload, indent=2), encoding="utf-8")

    status["finished_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    status["run_dir"] = str(run_dir)
    status["notebook_path"] = str(config.notebook_path)
    (paths["run"] / "run_summary.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    print(f"Lago LEAR benchmark run completed: {run_id}")
    print(f"Run artifacts: {run_dir}")


if __name__ == "__main__":
    main()
