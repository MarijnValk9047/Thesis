from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from hourly_da.core.ablation_blocks import aggregate_run_label_for_scheme
from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.reporting import find_latest_run, load_csv
from hourly_da.notebook_support import (
    annotate_ablation_metric_slice,
    load_fs2_ablation_bundle,
    select_feature_family_metric_slice,
)


POLL_SECONDS = 60
LOG_DIR = REPO_ROOT / "tmp" / "codex_logs"
SUMMARY_PATH = LOG_DIR / "fs2_first_loop_summary.json"

BASELINE_SPECS = [
    {
        "parent_run_label": "lear_fs2_benchmark",
        "candidate_run_label": "lear_fs2_pruned_candidate_benchmark",
        "model_family": "lear",
        "model_name": "lear_fs2",
    },
    {
        "parent_run_label": "xgboost_fs2_benchmark",
        "candidate_run_label": "xgboost_fs2_pruned_candidate_benchmark",
        "model_family": "xgboost",
        "model_name": "xgboost_fs2",
    },
]
SCHEMES = ("stage_a_top_level", "layer1_mutually_exclusive")


def _print(message: str) -> None:
    print(message, flush=True)


def _write_summary(payload: dict[str, object]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _bundle_available(config: HourlyDAPipelineConfig, parent_run_label: str, model_family: str, scheme_name: str):
    return load_fs2_ablation_bundle(
        config.output_root,
        config,
        parent_run_label=parent_run_label,
        model_family=model_family,
        scheme_name=scheme_name,
    )


def wait_for_baseline_bundles(config: HourlyDAPipelineConfig) -> dict[tuple[str, str], dict[str, object]]:
    _print("Waiting for baseline FS2 staged-ablation bundles to complete.")
    bundles: dict[tuple[str, str], dict[str, object]] = {}
    while True:
        pending: list[str] = []
        for spec in BASELINE_SPECS:
            for scheme_name in SCHEMES:
                key = (spec["model_family"], scheme_name)
                bundle = _bundle_available(config, spec["parent_run_label"], spec["model_family"], scheme_name)
                if bundle is None:
                    aggregate_run_label = aggregate_run_label_for_scheme(
                        parent_run_label=spec["parent_run_label"],
                        scheme_name=scheme_name,
                        scheme_version="1",
                    )
                    pending.append(aggregate_run_label)
                    continue
                bundles[key] = bundle
        if not pending:
            _print("Baseline FS2 staged-ablation bundles are available.")
            return bundles
        _write_summary({"status": "waiting_for_baseline_bundles", "pending_aggregate_run_labels": pending})
        _print(f"Still waiting for baseline bundles: {pending}")
        time.sleep(POLL_SECONDS)


def _action_from_buckets(d_bucket: str, stitched_bucket: str) -> str:
    harmful = {"strong_harmful", "mild_harmful"}
    helpful = {"strong_helpful", "mild_helpful"}
    neutral = {"near_zero_uncertain", "insufficient_data"}
    if d_bucket in harmful and stitched_bucket in harmful:
        return "prune_candidate"
    if (d_bucket in harmful and stitched_bucket in neutral) or (stitched_bucket in harmful and d_bucket in neutral):
        return "prune_candidate"
    if (d_bucket in harmful and stitched_bucket in helpful) or (d_bucket in helpful and stitched_bucket in harmful):
        return "redesign_candidate"
    if d_bucket in neutral and stitched_bucket in neutral:
        return "ambiguous"
    return "keep_or_monitor"


def choose_candidate_blocks(bundles: dict[tuple[str, str], dict[str, object]]) -> dict[str, list[str]]:
    selections: dict[str, list[str]] = {}
    selection_rows: list[dict[str, object]] = []
    for spec in BASELINE_SPECS:
        layer1_bundle = bundles[(spec["model_family"], "layer1_mutually_exclusive")]
        summary = layer1_bundle["summary"]
        d_only = annotate_ablation_metric_slice(
            select_feature_family_metric_slice(
                summary,
                split="validation",
                reporting_level="d_only",
                metric="mae",
            )
        )[["feature_family", "effect_bucket", "relative_delta"]].rename(
            columns={
                "effect_bucket": "d_only_bucket",
                "relative_delta": "d_only_relative_delta",
            }
        )
        stitched = annotate_ablation_metric_slice(
            select_feature_family_metric_slice(
                summary,
                split="validation",
                reporting_level="stitched_all_horizon",
                metric="mae",
            )
        )[["feature_family", "effect_bucket", "relative_delta"]].rename(
            columns={
                "effect_bucket": "stitched_bucket",
                "relative_delta": "stitched_relative_delta",
            }
        )
        merged = d_only.merge(stitched, on="feature_family", how="outer")
        if merged.empty:
            selections[spec["model_family"]] = []
            continue
        merged["suggested_action"] = merged.apply(
            lambda row: _action_from_buckets(
                str(row.get("d_only_bucket", "insufficient_data")),
                str(row.get("stitched_bucket", "insufficient_data")),
            ),
            axis=1,
        )
        merged["negative_score"] = merged[
            ["d_only_relative_delta", "stitched_relative_delta"]
        ].apply(
            lambda row: float(
                pd.Series([value for value in row.tolist() if pd.notna(value)]).clip(upper=0.0).mean()
            )
            if any(pd.notna(row))
            else 0.0,
            axis=1,
        )
        merged["model_family"] = spec["model_family"]
        selection_rows.extend(merged.to_dict(orient="records"))
        candidates = merged[merged["suggested_action"] == "prune_candidate"].copy()
        if candidates.empty:
            selections[spec["model_family"]] = []
            continue
        chosen = candidates.sort_values(["negative_score", "feature_family"], ascending=[True, True]).head(1)
        selections[spec["model_family"]] = chosen["feature_family"].astype(str).tolist()
    _write_summary({"status": "candidate_blocks_selected", "selection_rows": selection_rows, "selections": selections})
    _print(f"Selected FS2 candidate blocks: {selections}")
    return selections


def _run_command(command: list[str], *, label: str) -> None:
    _print(f"Running {label}: {' '.join(command)}")
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _model_spec(model_family: str) -> dict[str, str]:
    matches = [spec for spec in BASELINE_SPECS if spec["model_family"] == model_family]
    if not matches:
        raise KeyError(model_family)
    return matches[0]


def run_candidate_parent_benchmarks(selections: dict[str, list[str]]) -> None:
    for model_family, blocks in selections.items():
        if not blocks:
            _print(f"No candidate parent rerun selected for {model_family}.")
            continue
        spec = _model_spec(model_family)
        command = [
            sys.executable,
            str(PACKAGE_ROOT / "run_revised_parent_benchmark.py"),
            "--fs-level",
            "FS2",
            "--model-family",
            model_family,
            "--parent-run-label",
            spec["parent_run_label"],
            "--run-label",
            spec["candidate_run_label"],
            "--ablation-scheme",
            "layer1_mutually_exclusive",
            "--excluded-blocks",
            *blocks,
        ]
        _run_command(command, label=f"{model_family}_candidate_parent")


def run_candidate_ablations(selections: dict[str, list[str]]) -> None:
    for model_family, blocks in selections.items():
        if not blocks:
            _print(f"No candidate staged ablation selected for {model_family}.")
            continue
        spec = _model_spec(model_family)
        command = [
            sys.executable,
            str(PACKAGE_ROOT / "run_staged_block_ablation.py"),
            "--fs-level",
            "FS2",
            "--model-family",
            model_family,
            "--parent-run-label",
            spec["candidate_run_label"],
            "--ablation-schemes",
            "stage_a_top_level",
            "layer1_mutually_exclusive",
        ]
        _run_command(command, label=f"{model_family}_candidate_ablation")


def refresh_candidate_comparison(selections: dict[str, list[str]]) -> None:
    active_run_labels = {
        spec["model_family"]: (spec["candidate_run_label"] if selections.get(spec["model_family"]) else spec["parent_run_label"])
        for spec in BASELINE_SPECS
    }
    command = [
        sys.executable,
        str(PACKAGE_ROOT / "run_model_comparison.py"),
        "--fs-level",
        "FS2",
        "--run-label",
        "model_comparison_fs2_pruned_candidate",
        "--lear-run-label",
        active_run_labels["lear"],
        "--xgboost-run-label",
        active_run_labels["xgboost"],
        "--prophet-run-label",
        "prophet_benchmark",
    ]
    _run_command(command, label="fs2_candidate_model_comparison")


def collect_parent_delta_rows(config: HourlyDAPipelineConfig, selections: dict[str, list[str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for spec in BASELINE_SPECS:
        baseline_run_dir = find_latest_run(config.output_root, spec["parent_run_label"])
        candidate_run_dir = None
        if selections.get(spec["model_family"]):
            try:
                candidate_run_dir = find_latest_run(config.output_root, spec["candidate_run_label"])
            except FileNotFoundError:
                candidate_run_dir = None
        baseline_metrics = load_csv(baseline_run_dir, "metrics_by_reporting_level.csv")
        baseline_metrics = baseline_metrics[baseline_metrics["model"].astype(str) == spec["model_name"]].copy()
        candidate_metrics = pd.DataFrame()
        if candidate_run_dir is not None:
            candidate_metrics = load_csv(candidate_run_dir, "metrics_by_reporting_level.csv")
            candidate_metrics = candidate_metrics[candidate_metrics["model"].astype(str) == spec["model_name"]].copy()
        for split_name in ("validation", "test"):
            for reporting_level in ("d_only", "stitched_all_horizon"):
                baseline_row = baseline_metrics[
                    (baseline_metrics["dataset_split"].astype(str) == split_name)
                    & (baseline_metrics["reporting_level"].astype(str) == reporting_level)
                ].head(1)
                candidate_row = candidate_metrics[
                    (candidate_metrics["dataset_split"].astype(str) == split_name)
                    & (candidate_metrics["reporting_level"].astype(str) == reporting_level)
                ].head(1)
                rows.append(
                    {
                        "model_family": spec["model_family"],
                        "selected_blocks": selections.get(spec["model_family"], []),
                        "dataset_split": split_name,
                        "reporting_level": reporting_level,
                        "baseline_mae": float(baseline_row["mae"].iloc[0]) if not baseline_row.empty else None,
                        "candidate_mae": float(candidate_row["mae"].iloc[0]) if not candidate_row.empty else None,
                        "candidate_minus_baseline_mae": (
                            float(candidate_row["mae"].iloc[0]) - float(baseline_row["mae"].iloc[0])
                            if (not baseline_row.empty and not candidate_row.empty)
                            else None
                        ),
                    }
                )
    return rows


def main() -> None:
    config = HourlyDAPipelineConfig()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    bundles = wait_for_baseline_bundles(config)
    selections = choose_candidate_blocks(bundles)
    run_candidate_parent_benchmarks(selections)
    refresh_candidate_comparison(selections)
    run_candidate_ablations(selections)
    delta_rows = collect_parent_delta_rows(config, selections)
    _write_summary(
        {
            "status": "completed",
            "selections": selections,
            "parent_delta_rows": delta_rows,
        }
    )
    _print("FS2 first loop completed.")


if __name__ == "__main__":
    main()
