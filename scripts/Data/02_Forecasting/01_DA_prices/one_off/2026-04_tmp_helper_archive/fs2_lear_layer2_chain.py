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

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.notebook_support import (
    annotate_ablation_metric_slice,
    load_fs2_ablation_bundle,
    select_feature_family_metric_slice,
    supported_fs2_layer2_target_blocks,
)

POLL_SECONDS = 60
PARENT_RUN_LABEL = "lear_fs2_pruned_candidate_benchmark"
MODEL_FAMILY = "lear"
PID_PATH = REPO_ROOT / "tmp" / "codex_logs" / "fs2_lear_candidate_ablation.pid"
STATUS_JSON = REPO_ROOT / "tmp" / "codex_logs" / "fs2_lear_layer2_chain_status.json"
STATUS_MD = REPO_ROOT / "tmp" / "codex_logs" / "fs2_lear_layer2_chain_status.md"


def _write_status(payload: dict[str, object]) -> None:
    STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_lines = ["# FS2 LEAR Layer2 Chain", ""]
    for key, value in payload.items():
        md_lines.append(f"- {key}: {value}")
    STATUS_MD.write_text("\n".join(md_lines), encoding="utf-8")


def _layer1_process_running() -> bool:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*run_staged_block_ablation.py*lear_fs2_pruned_candidate_benchmark*layer1_mutually_exclusive*' } | "
            "Select-Object -First 1 ProcessId | ConvertTo-Json -Depth 2",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return bool((result.stdout or "").strip())


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


def _select_layer2_targets(bundle: dict[str, object]) -> tuple[list[str], pd.DataFrame]:
    summary = bundle["summary"].copy()
    d_only = annotate_ablation_metric_slice(
        select_feature_family_metric_slice(
            summary,
            split="validation",
            reporting_level="d_only",
            metric="mae",
        )
    )[["feature_family", "effect_bucket", "relative_delta"]].rename(
        columns={"effect_bucket": "d_only_bucket", "relative_delta": "d_only_relative_delta"}
    )
    stitched = annotate_ablation_metric_slice(
        select_feature_family_metric_slice(
            summary,
            split="validation",
            reporting_level="stitched_all_horizon",
            metric="mae",
        )
    )[["feature_family", "effect_bucket", "relative_delta"]].rename(
        columns={"effect_bucket": "stitched_bucket", "relative_delta": "stitched_relative_delta"}
    )
    merged = d_only.merge(stitched, on="feature_family", how="outer")
    if merged.empty:
        return [], merged
    merged["suggested_action"] = merged.apply(
        lambda row: _action_from_buckets(
            str(row.get("d_only_bucket", "insufficient_data")),
            str(row.get("stitched_bucket", "insufficient_data")),
        ),
        axis=1,
    )
    merged["negative_score"] = merged[["d_only_relative_delta", "stitched_relative_delta"]].apply(
        lambda row: float(pd.Series([value for value in row.tolist() if pd.notna(value)]).clip(upper=0.0).mean())
        if any(pd.notna(row))
        else 0.0,
        axis=1,
    )
    supported = set(supported_fs2_layer2_target_blocks())
    merged = merged[merged["feature_family"].astype(str).isin(supported)].copy()
    if merged.empty:
        return [], merged
    priority = {"prune_candidate": 0, "redesign_candidate": 1, "ambiguous": 2, "keep_or_monitor": 3}
    candidates = merged[merged["suggested_action"].isin({"prune_candidate", "redesign_candidate", "ambiguous"})].copy()
    if candidates.empty:
        return [], merged
    candidates["priority"] = candidates["suggested_action"].map(priority).fillna(9)
    selected = (
        candidates.sort_values(["priority", "negative_score", "feature_family"], ascending=[True, True, True])
        .head(2)["feature_family"]
        .astype(str)
        .tolist()
    )
    return selected, merged.sort_values(["suggested_action", "negative_score", "feature_family"]).reset_index(drop=True)


def _launch_layer2(targets: list[str]) -> int:
    command = [
        str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
        str(PACKAGE_ROOT / "run_staged_block_ablation.py"),
        "--fs-level",
        "FS2",
        "--model-family",
        MODEL_FAMILY,
        "--parent-run-label",
        PARENT_RUN_LABEL,
        "--ablation-schemes",
        "layer2_subgroups",
        "--layer2-target-block",
        *targets,
    ]
    process = subprocess.Popen(command, cwd=REPO_ROOT)
    PID_PATH.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def main() -> None:
    config = HourlyDAPipelineConfig()
    _write_status({"status": "waiting_for_layer1_completion", "parent_run_label": PARENT_RUN_LABEL})
    while True:
        bundle = load_fs2_ablation_bundle(
            config.output_root,
            config,
            parent_run_label=PARENT_RUN_LABEL,
            model_family=MODEL_FAMILY,
            scheme_name="layer1_mutually_exclusive",
        )
        if bundle is not None:
            run_summary = bundle.get("run_summary", {})
            if str(run_summary.get("aggregate_status", "")) == "complete":
                break
        if not _layer1_process_running():
            _write_status({"status": "layer1_stopped_before_completion", "parent_run_label": PARENT_RUN_LABEL})
            return
        time.sleep(POLL_SECONDS)

    targets, decision_frame = _select_layer2_targets(bundle)
    decision_path = REPO_ROOT / "tmp" / "codex_logs" / "fs2_lear_layer2_target_selection.csv"
    decision_frame.to_csv(decision_path, index=False)
    if not targets:
        _write_status(
            {
                "status": "layer2_skipped_no_targets",
                "parent_run_label": PARENT_RUN_LABEL,
                "decision_table": str(decision_path),
            }
        )
        return

    pid = _launch_layer2(targets)
    _write_status(
        {
            "status": "layer2_running",
            "parent_run_label": PARENT_RUN_LABEL,
            "selected_targets": targets,
            "decision_table": str(decision_path),
            "pid": pid,
        }
    )


if __name__ == "__main__":
    main()
