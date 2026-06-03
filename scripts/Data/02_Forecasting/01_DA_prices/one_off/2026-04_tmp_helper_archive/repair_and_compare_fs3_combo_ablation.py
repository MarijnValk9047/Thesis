from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.notebook_support import load_feature_family_ablation_bundle  # noqa: E402


OUTPUT_ROOT = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da"
RUNS_ROOT = OUTPUT_ROOT / "runs"
ANALYSIS_ROOT = OUTPUT_ROOT / "analysis" / "fs3_combo_ablation_comparison"
LOG_ROOT = REPO_ROOT / "tmp" / "codex_logs"
LOG_PATH = LOG_ROOT / "repair_and_compare_fs3_combo_ablation.log"

POLL_SECONDS = 300
MAX_WAIT_SECONDS = 24 * 60 * 60
TARGETS = {
    "lear": "lear_fs3_combo_promoted_benchmark",
    "xgboost": "xgboost_fs3_combo_promoted_benchmark",
}
REPORTING_LEVELS = ("d_only", "stitched_all_horizon")
REPORTING_LEVEL_LABELS = {
    "d_only": "D only",
    "stitched_all_horizon": "Full horizon",
}
SPLITS = ("validation", "test")
METRICS = ("mae", "rmae_vs_official_naive")


def log(message: str) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def active_process_count(model_family: str) -> int:
    powershell = f"""
$matches = Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -eq 'python.exe' -and
    $_.CommandLine -like '*run_fs3_ordered_benchmarks.py*' -and
    $_.CommandLine -like '*--execution-mode feature_value*' -and
    $_.CommandLine -like '*--feature-value-step all*' -and
    $_.CommandLine -like '*--stage combo*' -and
    $_.CommandLine -like '*--feature-value-model-family {model_family}*'
}}
Write-Output $matches.Count
""".strip()
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", powershell],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"Failed to inspect active process count for {model_family}.")
    return int((completed.stdout or "0").strip() or "0")


def latest_complete_aggregate_run(parent_run_label: str) -> Path | None:
    aggregate_label = f"feature_family_ablation__{parent_run_label}"
    candidates = []
    for run_dir in RUNS_ROOT.glob(f"*_{aggregate_label}"):
        if (run_dir / "run_summary.json").exists():
            candidates.append(run_dir)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def launch_or_resume_family(model_family: str) -> int:
    command = [
        sys.executable,
        "scripts/Data/02_Forecasting/01_DA_prices/run_fs3_ordered_benchmarks.py",
        "--execution-mode",
        "feature_value",
        "--feature-value-step",
        "all",
        "--stage",
        "combo",
        "--feature-value-model-family",
        model_family,
    ]
    log(f"Launching or resuming full combo ablation for {model_family}: {' '.join(command)}")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    log(f"Full combo ablation for {model_family} exited with code {completed.returncode}.")
    return int(completed.returncode)


def parent_performance_table(bundle: dict[str, object], model_family: str) -> pd.DataFrame:
    summary = pd.DataFrame(bundle["summary"]).copy()
    summary = summary[
        summary["metric"].astype(str).eq("mae")
        & summary["split"].astype(str).isin(SPLITS)
        & summary["reporting_level"].astype(str).isin(REPORTING_LEVELS)
    ].copy()
    if summary.empty:
        return pd.DataFrame()
    parent = (
        summary[
            [
                "split",
                "reporting_level",
                "reporting_level_label",
                "metric",
                "parent_value",
                "model",
                "parent_run_id",
                "aggregate_run_id",
            ]
        ]
        .drop_duplicates(subset=["split", "reporting_level", "metric"])
        .rename(
            columns={
                "parent_value": f"{model_family}_parent_mae",
                "model": f"{model_family}_model",
                "parent_run_id": f"{model_family}_parent_run_id",
                "aggregate_run_id": f"{model_family}_aggregate_run_id",
            }
        )
        .reset_index(drop=True)
    )
    return parent


def family_delta_table(bundle: dict[str, object], model_family: str) -> pd.DataFrame:
    summary = pd.DataFrame(bundle["summary"]).copy()
    summary = summary[
        summary["metric"].astype(str).isin(METRICS)
        & summary["split"].astype(str).isin(SPLITS)
        & summary["reporting_level"].astype(str).isin(REPORTING_LEVELS)
    ].copy()
    if summary.empty:
        return pd.DataFrame()
    return summary.rename(
        columns={
            "parent_value": f"{model_family}_parent_value",
            "child_value": f"{model_family}_child_value",
            "delta": f"{model_family}_delta",
            "relative_delta": f"{model_family}_relative_delta",
            "interpretation_flag": f"{model_family}_interpretation",
            "child_better_origin_rate": f"{model_family}_child_better_origin_rate",
            "mean_origin_delta": f"{model_family}_mean_origin_delta",
            "std_origin_delta": f"{model_family}_std_origin_delta",
        }
    )


def build_comparison_artifacts() -> None:
    bundles = {family: load_feature_family_ablation_bundle(OUTPUT_ROOT, run_label) for family, run_label in TARGETS.items()}
    missing = [family for family, bundle in bundles.items() if bundle is None]
    if missing:
        raise RuntimeError(f"Cannot compare results yet; missing aggregate bundle(s): {', '.join(missing)}")

    ANALYSIS_ROOT.mkdir(parents=True, exist_ok=True)

    parent_frames = [parent_performance_table(bundle, family) for family, bundle in bundles.items()]
    parent_comparison = parent_frames[0]
    for frame in parent_frames[1:]:
        parent_comparison = parent_comparison.merge(
            frame,
            on=["split", "reporting_level", "reporting_level_label", "metric"],
            how="outer",
        )
    if not parent_comparison.empty:
        parent_comparison["parent_mae_gap_lear_minus_xgboost"] = (
            parent_comparison["lear_parent_mae"] - parent_comparison["xgboost_parent_mae"]
        )
        parent_comparison = parent_comparison.sort_values(["split", "reporting_level"]).reset_index(drop=True)

    family_frames = [family_delta_table(bundle, family) for family, bundle in bundles.items()]
    family_comparison = family_frames[0]
    join_keys = ["split", "reporting_level", "reporting_level_label", "metric", "feature_family"]
    drop_overlap = [
        "model",
        "model_family",
        "fs_stage",
        "comparison_type",
        "parent_run_label",
        "child_run_id",
        "child_run_label",
        "ablation_policy",
        "rmae_reference_source",
        "origin_count",
        "validation_first",
        "parent_run_id",
        "aggregate_run_id",
    ]
    family_comparison = family_comparison.drop(columns=[column for column in drop_overlap if column in family_comparison.columns])
    for family, frame in zip(tuple(TARGETS.keys())[1:], family_frames[1:]):
        reduced = frame.drop(columns=[column for column in drop_overlap if column in frame.columns])
        family_comparison = family_comparison.merge(reduced, on=join_keys, how="outer")

    if not family_comparison.empty:
        family_comparison["delta_gap_lear_minus_xgboost"] = (
            family_comparison.get("lear_delta") - family_comparison.get("xgboost_delta")
        )
        family_comparison["relative_delta_gap_lear_minus_xgboost"] = (
            family_comparison.get("lear_relative_delta") - family_comparison.get("xgboost_relative_delta")
        )
        family_comparison = family_comparison.sort_values(join_keys).reset_index(drop=True)

    validation_rank = family_comparison[
        family_comparison["split"].astype(str).eq("validation")
        & family_comparison["metric"].astype(str).eq("mae")
        & family_comparison["reporting_level"].astype(str).isin(REPORTING_LEVELS)
    ].copy()

    rank_outputs: dict[str, pd.DataFrame] = {}
    for family in TARGETS:
        delta_col = f"{family}_delta"
        if delta_col not in validation_rank.columns:
            rank_outputs[family] = pd.DataFrame()
            continue
        ranking = validation_rank[
            ["reporting_level", "reporting_level_label", "feature_family", delta_col, f"{family}_relative_delta"]
        ].copy()
        ranking = ranking.sort_values(["reporting_level", delta_col, "feature_family"], ascending=[True, False, True])
        ranking["rank_within_reporting_level"] = ranking.groupby("reporting_level").cumcount() + 1
        rank_outputs[family] = ranking.reset_index(drop=True)

    parent_path = ANALYSIS_ROOT / "parent_mae_comparison.csv"
    family_path = ANALYSIS_ROOT / "family_delta_comparison.csv"
    lear_rank_path = ANALYSIS_ROOT / "lear_validation_mae_rank.csv"
    xgboost_rank_path = ANALYSIS_ROOT / "xgboost_validation_mae_rank.csv"
    metadata_path = ANALYSIS_ROOT / "comparison_metadata.json"
    markdown_path = ANALYSIS_ROOT / "comparison_summary.md"

    parent_comparison.to_csv(parent_path, index=False)
    family_comparison.to_csv(family_path, index=False)
    rank_outputs["lear"].to_csv(lear_rank_path, index=False)
    rank_outputs["xgboost"].to_csv(xgboost_rank_path, index=False)

    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "lear_aggregate_run_dir": str(bundles["lear"]["run_dir"]),
        "xgboost_aggregate_run_dir": str(bundles["xgboost"]["run_dir"]),
        "reporting_levels": list(REPORTING_LEVELS),
        "splits": list(SPLITS),
        "metrics": list(METRICS),
        "artifacts": {
            "parent_mae_comparison": str(parent_path),
            "family_delta_comparison": str(family_path),
            "lear_validation_mae_rank": str(lear_rank_path),
            "xgboost_validation_mae_rank": str(xgboost_rank_path),
            "comparison_summary": str(markdown_path),
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    lines = [
        "# FS3 Combo Ablation Comparison",
        "",
        f"Generated at: {metadata['generated_at']}",
        "",
        "## Parent MAE comparison",
        "",
    ]
    if parent_comparison.empty:
        lines.append("No parent MAE comparison rows were available.")
        lines.append("")
    else:
        for split in SPLITS:
            split_frame = parent_comparison[parent_comparison["split"].astype(str).eq(split)].copy()
            if split_frame.empty:
                continue
            lines.append(f"### {split.title()}")
            lines.append("")
            for reporting_level in REPORTING_LEVELS:
                row_match = split_frame[split_frame["reporting_level"].astype(str).eq(reporting_level)].copy()
                if row_match.empty:
                    continue
                row = row_match.iloc[0]
                better_family = "LEAR" if float(row["lear_parent_mae"]) < float(row["xgboost_parent_mae"]) else "XGBoost"
                lines.append(
                    f"- {REPORTING_LEVEL_LABELS[reporting_level]}: "
                    f"LEAR MAE = {float(row['lear_parent_mae']):.3f}, "
                    f"XGBoost MAE = {float(row['xgboost_parent_mae']):.3f}, "
                    f"better parent = {better_family}."
                )
            lines.append("")

    lines.extend(
        [
            "## Most harmful validation removals",
            "",
        ]
    )
    for family in TARGETS:
        ranking = rank_outputs[family]
        lines.append(f"### {family.upper() if family == 'lear' else 'XGBoost'}")
        lines.append("")
        if ranking.empty:
            lines.append("No ranking rows were available.")
            lines.append("")
            continue
        for reporting_level in REPORTING_LEVELS:
            level_frame = ranking[ranking["reporting_level"].astype(str).eq(reporting_level)].copy()
            if level_frame.empty:
                continue
            top_row = level_frame.iloc[0]
            lines.append(
                f"- {REPORTING_LEVEL_LABELS[reporting_level]}: "
                f"`{top_row['feature_family']}` is the most harmful removal "
                f"(delta = {float(top_row[f'{family}_delta']):+.3f}, "
                f"relative = {float(top_row[f'{family}_relative_delta']):+.2%})."
            )
        lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    log(f"Wrote comparison artifacts to {ANALYSIS_ROOT}.")


def ensure_full_runs_complete() -> None:
    deadline = time.time() + MAX_WAIT_SECONDS
    while time.time() < deadline:
        completed_flags: list[bool] = []
        for family, parent_run_label in TARGETS.items():
            active_count = active_process_count(family)
            aggregate_dir = latest_complete_aggregate_run(parent_run_label)
            aggregate_complete = aggregate_dir is not None
            completed_flags.append(aggregate_complete)

            if active_count == 0 and not aggregate_complete:
                log(f"{family}: no active process and no complete aggregate found; rerunning full combo ablation.")
                exit_code = launch_or_resume_family(family)
                if exit_code != 0:
                    raise RuntimeError(f"Rerun for {family} failed with exit code {exit_code}.")
                aggregate_dir = latest_complete_aggregate_run(parent_run_label)
                aggregate_complete = aggregate_dir is not None
                completed_flags[-1] = aggregate_complete

            if aggregate_complete:
                log(f"{family}: complete aggregate detected at {aggregate_dir.name}.")
            else:
                log(f"{family}: still running or incomplete; active_processes={active_count}.")

        if all(completed_flags):
            return

        time.sleep(POLL_SECONDS)

    raise TimeoutError("Timed out while waiting for full FS3 combo ablation aggregates.")


def main() -> int:
    log("Starting FS3 combo ablation repair-and-compare workflow.")
    ensure_full_runs_complete()
    build_comparison_artifacts()
    log("FS3 combo ablation repair-and-compare workflow finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
