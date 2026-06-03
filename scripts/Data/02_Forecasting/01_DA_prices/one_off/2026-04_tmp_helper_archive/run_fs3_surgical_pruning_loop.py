from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
RUN_ROOT = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da" / "runs"
PYTHON_EXE = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = REPO_ROOT / "tmp" / "codex_logs"
STATUS_JSON = LOG_DIR / "fs3_pruning_candidate_status.json"
STATUS_MD = LOG_DIR / "fs3_pruning_candidate_status.md"
VALIDATION_DELTA_CSV = LOG_DIR / "fs3_pruning_candidate_validation_deltas.csv"

FS_LEVEL = "FS3"
PRIMARY_REPORTING_LEVEL = "stitched_all_horizon"
MAX_D_ONLY_DEGRADATION_ABS = 0.25
MAX_D_ONLY_DEGRADATION_REL = 0.015
MAX_COVERAGE_DROP_PCT = 0.50

RUN_REQUIRED_FILES = (
    "run_summary.json",
    "metrics_by_reporting_level.csv",
)

AGGREGATE_REQUIRED_FILES = (
    "run_summary.json",
    "feature_family_value_summary.csv",
    "feature_family_value_by_reporting_level.csv",
    "feature_family_parent_child_map.csv",
)

SCHEME_SEQUENCE = (
    {"scheme_name": "stage_a_top_level", "status_key": "stage_a", "label": "Stage A"},
    {"scheme_name": "layer1_mutually_exclusive", "status_key": "layer1", "label": "Layer 1"},
)

MODEL_SPECS = (
    {
        "model_family": "lear",
        "baseline_parent_run_label": "lear_fs3_combo_promoted_benchmark",
        "candidate_parent_run_label": "lear_fs3_combo_pruned_candidate_benchmark",
        "excluded_blocks": [
            "calendar",
            "neighbor_only_week_ahead_fundamentals",
            "neighbor_price_proxy",
            "domestic_historical_fundamentals",
        ],
    },
    {
        "model_family": "xgboost",
        "baseline_parent_run_label": "xgboost_fs3_combo_promoted_benchmark",
        "candidate_parent_run_label": "xgboost_fs3_combo_pruned_candidate_benchmark",
        "excluded_blocks": [
            "short_autoregressive_price_lags",
            "neighbor_only_historical_fundamentals",
            "domestic_historical_fundamentals",
            "domestic_day_ahead_fundamentals",
        ],
    },
)


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run_label_from_run_dir_name(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def _latest_run_dir(run_label: str) -> Path | None:
    if not RUN_ROOT.exists():
        return None
    matches = sorted(
        path for path in RUN_ROOT.iterdir() if path.is_dir() and _run_label_from_run_dir_name(path.name) == str(run_label)
    )
    return matches[-1] if matches else None


def _run_has_required_artifacts(run_dir: Path, required_files: tuple[str, ...]) -> bool:
    return all((run_dir / filename).exists() for filename in required_files)


def _latest_complete_run_dir(run_label: str, required_files: tuple[str, ...]) -> Path | None:
    if not RUN_ROOT.exists():
        return None
    matches = sorted(
        path for path in RUN_ROOT.iterdir() if path.is_dir() and _run_label_from_run_dir_name(path.name) == str(run_label)
    )
    for run_dir in reversed(matches):
        if _run_has_required_artifacts(run_dir, required_files):
            return run_dir
    return None


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _estimate_run_seconds_from_dir(run_dir: Path | None) -> float | None:
    if run_dir is None:
        return None
    timing_path = run_dir / "origin_timing_summary.csv"
    if not timing_path.exists():
        return None
    frame = pd.read_csv(timing_path)
    required_cols = {"origins", "fit_time_mean_sec", "predict_time_mean_sec"}
    if frame.empty or not required_cols.issubset(frame.columns):
        return None
    return float(
        (
            frame["origins"].astype(float)
            * (frame["fit_time_mean_sec"].astype(float) + frame["predict_time_mean_sec"].astype(float))
        ).sum()
    )


def _estimate_run_seconds_by_label(run_label: str) -> float | None:
    return _estimate_run_seconds_from_dir(_latest_complete_run_dir(run_label, RUN_REQUIRED_FILES))


def _estimate_aggregate_seconds_by_label(run_label: str) -> float | None:
    aggregate_dir = _latest_complete_run_dir(run_label, AGGREGATE_REQUIRED_FILES)
    if aggregate_dir is None:
        return None
    summary = _load_json(aggregate_dir / "run_summary.json")
    child_run_ids = [str(value) for value in summary.get("child_run_ids", [])]
    total = 0.0
    found_any = False
    for child_run_id in child_run_ids:
        child_dir = RUN_ROOT / child_run_id
        value = _estimate_run_seconds_from_dir(child_dir)
        if value is None:
            continue
        found_any = True
        total += float(value)
    return total if found_any else None


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total_seconds = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _aggregate_run_label(parent_run_label: str, scheme_name: str) -> str:
    return f"feature_family_ablation__{parent_run_label}__{scheme_name}_v1"


def _latest_complete_aggregate_run_dir(parent_run_label: str, scheme_name: str) -> Path | None:
    aggregate_label = _aggregate_run_label(parent_run_label, scheme_name)
    run_dir = _latest_complete_run_dir(aggregate_label, AGGREGATE_REQUIRED_FILES)
    if run_dir is None:
        return None
    summary = _load_json(run_dir / "run_summary.json")
    if str(summary.get("aggregate_status", "")) != "complete":
        return None
    if str(summary.get("execution_status", "")) not in {"success", ""}:
        return None
    return run_dir


def _metrics_frame(run_dir: Path) -> pd.DataFrame:
    return pd.read_csv(run_dir / "metrics_by_reporting_level.csv")


def _metric_row(run_dir: Path, *, model_family: str, split: str, reporting_level: str) -> pd.Series:
    frame = _metrics_frame(run_dir)
    view = frame[
        (frame["model_family"].astype(str) == str(model_family))
        & (frame["dataset_split"].astype(str) == str(split))
        & (frame["reporting_level"].astype(str) == str(reporting_level))
    ].copy()
    if view.empty:
        raise RuntimeError(
            f"Missing metric row in {run_dir.name} for model_family={model_family}, split={split}, reporting_level={reporting_level}."
        )
    return view.iloc[0]


def _validation_delta_rows(*, model_family: str, baseline_run_dir: Path, candidate_run_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for reporting_level in ("d_only", "guidance_only", "stitched_all_horizon"):
        baseline = _metric_row(
            baseline_run_dir,
            model_family=model_family,
            split="validation",
            reporting_level=reporting_level,
        )
        candidate = _metric_row(
            candidate_run_dir,
            model_family=model_family,
            split="validation",
            reporting_level=reporting_level,
        )
        baseline_mae = float(baseline["mae"])
        candidate_mae = float(candidate["mae"])
        delta = candidate_mae - baseline_mae
        rows.append(
            {
                "model_family": str(model_family),
                "reporting_level": str(reporting_level),
                "baseline_run_id": baseline_run_dir.name,
                "candidate_run_id": candidate_run_dir.name,
                "baseline_mae": baseline_mae,
                "candidate_mae": candidate_mae,
                "delta_mae": delta,
                "relative_delta_mae": (delta / baseline_mae) if baseline_mae else None,
                "baseline_coverage_pct": float(baseline["coverage_pct"]),
                "candidate_coverage_pct": float(candidate["coverage_pct"]),
                "coverage_drop_pct": float(baseline["coverage_pct"]) - float(candidate["coverage_pct"]),
            }
        )
    return rows


def _gate_decision(delta_rows: list[dict[str, object]]) -> dict[str, object]:
    by_level = {str(row["reporting_level"]): row for row in delta_rows}
    d_only = by_level["d_only"]
    stitched = by_level[PRIMARY_REPORTING_LEVEL]
    stitched_improved = float(stitched["delta_mae"]) < 0.0
    d_only_abs_guard = float(d_only["delta_mae"]) <= MAX_D_ONLY_DEGRADATION_ABS
    d_only_rel_guard = float(d_only["relative_delta_mae"] or 0.0) <= MAX_D_ONLY_DEGRADATION_REL
    coverage_guard = (
        float(d_only["coverage_drop_pct"]) <= MAX_COVERAGE_DROP_PCT
        and float(stitched["coverage_drop_pct"]) <= MAX_COVERAGE_DROP_PCT
    )
    passed = stitched_improved and d_only_abs_guard and d_only_rel_guard and coverage_guard
    reasons = []
    if stitched_improved:
        reasons.append("validation stitched_all_horizon MAE improved")
    else:
        reasons.append("validation stitched_all_horizon MAE did not improve")
    if d_only_abs_guard and d_only_rel_guard:
        reasons.append("validation D-only guardrail held")
    else:
        reasons.append("validation D-only guardrail failed")
    if coverage_guard:
        reasons.append("coverage guardrail held")
    else:
        reasons.append("coverage guardrail failed")
    return {
        "passed": bool(passed),
        "reasons": reasons,
        "primary_reporting_level": PRIMARY_REPORTING_LEVEL,
        "max_d_only_degradation_abs": MAX_D_ONLY_DEGRADATION_ABS,
        "max_d_only_degradation_rel": MAX_D_ONLY_DEGRADATION_REL,
        "max_coverage_drop_pct": MAX_COVERAGE_DROP_PCT,
    }


def _write_validation_delta_csv(status: dict[str, object]) -> None:
    rows = status.get("validation_delta_rows") or []
    if not rows:
        if VALIDATION_DELTA_CSV.exists():
            VALIDATION_DELTA_CSV.unlink()
        return
    pd.DataFrame(rows).to_csv(VALIDATION_DELTA_CSV, index=False)


def _render_markdown(status: dict[str, object]) -> str:
    lines = [
        "# FS3 Surgical Pruning Loop",
        "",
        f"- observed_at: {status['observed_at']}",
        f"- overall_status: {status['overall_status']}",
        f"- active_phase: {status['active_phase']}",
        f"- active_model_family: {status['active_model_family'] or ''}",
        f"- current_subprocess_pid: {status['current_subprocess'].get('pid') or ''}",
        f"- current_subprocess_label: {status['current_subprocess'].get('label') or ''}",
        f"- current_subprocess_started_at: {status['current_subprocess'].get('started_at') or ''}",
        "",
        "## Estimated Runtime",
        f"- candidate_parent_reruns: {status['estimates']['candidate_parent_reruns_text']}",
        f"- candidate_ablation_if_all_pass: {status['estimates']['candidate_ablation_if_all_pass_text']}",
        f"- all_in_if_all_pass: {status['estimates']['all_in_if_all_pass_text']}",
        "",
    ]
    for family in ("lear", "xgboost"):
        model_status = status["models"][family]
        lines.extend(
            [
                f"## {family.title()}",
                f"- baseline_parent_run_label: {model_status['baseline_parent_run_label']}",
                f"- candidate_parent_run_label: {model_status['candidate_parent_run_label']}",
                f"- excluded_blocks: {', '.join(model_status['excluded_blocks'])}",
                f"- candidate_parent_status: {model_status['candidate_parent']['status']}",
                f"- candidate_parent_run_dir: {model_status['candidate_parent']['run_dir']}",
                f"- validation_gate_status: {model_status['validation_gate']['status']}",
                f"- validation_gate_passed: {model_status['validation_gate']['passed']}",
            ]
        )
        if model_status["validation_gate"]["status"] == "evaluated":
            gate = model_status["validation_gate"]
            lines.extend(
                [
                    f"- validation_stitched_delta_mae: {gate['stitched_delta_mae']:+.4f}",
                    f"- validation_d_only_delta_mae: {gate['d_only_delta_mae']:+.4f}",
                    f"- validation_guidance_delta_mae: {gate['guidance_delta_mae']:+.4f}",
                    f"- validation_gate_reason: {'; '.join(gate['reasons'])}",
                ]
            )
        lines.extend(
            [
                f"- stage_a_status: {model_status['stage_a']['status']}",
                f"- stage_a_run_dir: {model_status['stage_a']['run_dir']}",
                f"- layer1_status: {model_status['layer1']['status']}",
                f"- layer1_run_dir: {model_status['layer1']['run_dir']}",
                "",
            ]
        )
    if status.get("error_message"):
        lines.extend(["## Error", status["error_message"], ""])
    return "\n".join(lines).rstrip() + "\n"


def _write_status(status: dict[str, object]) -> None:
    status["observed_at"] = _now_text()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps(status, indent=2), encoding="utf-8")
    STATUS_MD.write_text(_render_markdown(status), encoding="utf-8")
    _write_validation_delta_csv(status)


def _initial_status() -> dict[str, object]:
    candidate_parent_estimate_total = 0.0
    candidate_parent_known = False
    candidate_ablation_estimate_total = 0.0
    candidate_ablation_known = False
    model_payload: dict[str, object] = {}

    for spec in MODEL_SPECS:
        family = str(spec["model_family"])
        baseline_parent = str(spec["baseline_parent_run_label"])
        parent_estimate = _estimate_run_seconds_by_label(baseline_parent)
        stage_a_estimate = _estimate_aggregate_seconds_by_label(_aggregate_run_label(baseline_parent, "stage_a_top_level"))
        layer1_estimate = _estimate_aggregate_seconds_by_label(
            _aggregate_run_label(baseline_parent, "layer1_mutually_exclusive")
        )
        if parent_estimate is not None:
            candidate_parent_estimate_total += float(parent_estimate)
            candidate_parent_known = True
        if stage_a_estimate is not None:
            candidate_ablation_estimate_total += float(stage_a_estimate)
            candidate_ablation_known = True
        if layer1_estimate is not None:
            candidate_ablation_estimate_total += float(layer1_estimate)
            candidate_ablation_known = True
        model_payload[family] = {
            "baseline_parent_run_label": baseline_parent,
            "candidate_parent_run_label": str(spec["candidate_parent_run_label"]),
            "excluded_blocks": list(spec["excluded_blocks"]),
            "estimated_candidate_parent_seconds": parent_estimate,
            "estimated_stage_a_seconds": stage_a_estimate,
            "estimated_layer1_seconds": layer1_estimate,
            "candidate_parent": {
                "status": "not_started",
                "run_dir": "",
            },
            "validation_gate": {
                "status": "pending",
                "passed": False,
                "reasons": [],
                "stitched_delta_mae": None,
                "d_only_delta_mae": None,
                "guidance_delta_mae": None,
            },
            "stage_a": {
                "status": "not_started",
                "run_dir": "",
            },
            "layer1": {
                "status": "not_started",
                "run_dir": "",
            },
        }

    all_in = None
    if candidate_parent_known or candidate_ablation_known:
        all_in = candidate_parent_estimate_total + candidate_ablation_estimate_total

    return {
        "observed_at": _now_text(),
        "overall_status": "not_started",
        "active_phase": "initializing",
        "active_model_family": "",
        "current_subprocess": {
            "pid": None,
            "label": "",
            "command": [],
            "started_at": "",
        },
        "gate_config": {
            "primary_reporting_level": PRIMARY_REPORTING_LEVEL,
            "max_d_only_degradation_abs": MAX_D_ONLY_DEGRADATION_ABS,
            "max_d_only_degradation_rel": MAX_D_ONLY_DEGRADATION_REL,
            "max_coverage_drop_pct": MAX_COVERAGE_DROP_PCT,
        },
        "estimates": {
            "candidate_parent_reruns_seconds": candidate_parent_estimate_total if candidate_parent_known else None,
            "candidate_parent_reruns_text": _format_duration(candidate_parent_estimate_total)
            if candidate_parent_known
            else "unknown",
            "candidate_ablation_if_all_pass_seconds": candidate_ablation_estimate_total if candidate_ablation_known else None,
            "candidate_ablation_if_all_pass_text": _format_duration(candidate_ablation_estimate_total)
            if candidate_ablation_known
            else "unknown",
            "all_in_if_all_pass_seconds": all_in,
            "all_in_if_all_pass_text": _format_duration(all_in) if all_in is not None else "unknown",
        },
        "models": model_payload,
        "validation_delta_rows": [],
        "error_message": "",
    }


def _run_step(
    status: dict[str, object],
    *,
    model_family: str,
    phase_label: str,
    step_label: str,
    command: list[str],
) -> None:
    status["overall_status"] = "running"
    status["active_phase"] = phase_label
    status["active_model_family"] = str(model_family)
    process = subprocess.Popen(command, cwd=REPO_ROOT)
    status["current_subprocess"] = {
        "pid": int(process.pid),
        "label": step_label,
        "command": [str(part) for part in command],
        "started_at": _now_text(),
    }
    _write_status(status)
    return_code = process.wait()
    status["current_subprocess"] = {
        "pid": None,
        "label": "",
        "command": [],
        "started_at": "",
    }
    if return_code != 0:
        raise RuntimeError(f"Step failed with exit code {return_code}: {step_label}")
    _write_status(status)


def _ensure_candidate_parent(status: dict[str, object], spec: dict[str, object]) -> Path:
    family = str(spec["model_family"])
    candidate_label = str(spec["candidate_parent_run_label"])
    existing = _latest_complete_run_dir(candidate_label, RUN_REQUIRED_FILES)
    if existing is not None:
        status["models"][family]["candidate_parent"]["status"] = "reused_complete"
        status["models"][family]["candidate_parent"]["run_dir"] = existing.name
        _write_status(status)
        return existing

    status["models"][family]["candidate_parent"]["status"] = "running"
    _write_status(status)
    command = [
        str(PYTHON_EXE),
        str(PACKAGE_ROOT / "run_revised_parent_benchmark.py"),
        "--fs-level",
        FS_LEVEL,
        "--model-family",
        family,
        "--parent-run-label",
        str(spec["baseline_parent_run_label"]),
        "--run-label",
        candidate_label,
        "--ablation-scheme",
        "layer1_mutually_exclusive",
        "--excluded-blocks",
        *[str(value) for value in spec["excluded_blocks"]],
        "--show-progress",
    ]
    _run_step(
        status,
        model_family=family,
        phase_label="candidate_parent_benchmark",
        step_label=f"{family} candidate parent benchmark",
        command=command,
    )
    run_dir = _latest_complete_run_dir(candidate_label, RUN_REQUIRED_FILES)
    if run_dir is None:
        raise RuntimeError(f"Candidate parent run '{candidate_label}' completed without the required artifacts.")
    status["models"][family]["candidate_parent"]["status"] = "complete"
    status["models"][family]["candidate_parent"]["run_dir"] = run_dir.name
    _write_status(status)
    return run_dir


def _evaluate_candidate_parent(status: dict[str, object], spec: dict[str, object], candidate_run_dir: Path) -> None:
    family = str(spec["model_family"])
    baseline_label = str(spec["baseline_parent_run_label"])
    baseline_run_dir = _latest_complete_run_dir(baseline_label, RUN_REQUIRED_FILES)
    if baseline_run_dir is None:
        raise RuntimeError(f"Baseline parent run '{baseline_label}' is missing required artifacts.")
    delta_rows = _validation_delta_rows(
        model_family=family,
        baseline_run_dir=baseline_run_dir,
        candidate_run_dir=candidate_run_dir,
    )
    gate = _gate_decision(delta_rows)
    status["validation_delta_rows"] = [
        row for row in status["validation_delta_rows"] if str(row.get("model_family")) != family
    ] + delta_rows
    by_level = {str(row["reporting_level"]): row for row in delta_rows}
    validation_gate = status["models"][family]["validation_gate"]
    validation_gate["status"] = "evaluated"
    validation_gate["passed"] = bool(gate["passed"])
    validation_gate["reasons"] = list(gate["reasons"])
    validation_gate["stitched_delta_mae"] = float(by_level["stitched_all_horizon"]["delta_mae"])
    validation_gate["d_only_delta_mae"] = float(by_level["d_only"]["delta_mae"])
    validation_gate["guidance_delta_mae"] = float(by_level["guidance_only"]["delta_mae"])
    _write_status(status)


def _ensure_candidate_aggregate(status: dict[str, object], spec: dict[str, object], scheme: dict[str, str]) -> Path:
    family = str(spec["model_family"])
    status_key = str(scheme["status_key"])
    scheme_name = str(scheme["scheme_name"])
    candidate_label = str(spec["candidate_parent_run_label"])
    existing = _latest_complete_aggregate_run_dir(candidate_label, scheme_name)
    if existing is not None:
        status["models"][family][status_key]["status"] = "reused_complete"
        status["models"][family][status_key]["run_dir"] = existing.name
        _write_status(status)
        return existing

    status["models"][family][status_key]["status"] = "running"
    _write_status(status)
    command = [
        str(PYTHON_EXE),
        str(PACKAGE_ROOT / "run_staged_block_ablation.py"),
        "--fs-level",
        FS_LEVEL,
        "--model-family",
        family,
        "--parent-run-label",
        candidate_label,
        "--ablation-schemes",
        scheme_name,
        "--show-progress",
    ]
    _run_step(
        status,
        model_family=family,
        phase_label=f"candidate_{status_key}_ablation",
        step_label=f"{family} candidate {scheme['label']}",
        command=command,
    )
    run_dir = _latest_complete_aggregate_run_dir(candidate_label, scheme_name)
    if run_dir is None:
        raise RuntimeError(
            f"Candidate aggregate '{_aggregate_run_label(candidate_label, scheme_name)}' completed without the required artifacts."
        )
    status["models"][family][status_key]["status"] = "complete"
    status["models"][family][status_key]["run_dir"] = run_dir.name
    _write_status(status)
    return run_dir


def _mark_skipped_ablation(status: dict[str, object], family: str) -> None:
    for status_key in ("stage_a", "layer1"):
        status["models"][family][status_key]["status"] = "skipped_gate_fail"
        status["models"][family][status_key]["run_dir"] = ""
    _write_status(status)


def main() -> None:
    if not PYTHON_EXE.exists():
        raise FileNotFoundError(f"Missing virtualenv interpreter: {PYTHON_EXE}")

    status = _initial_status()
    _write_status(status)

    try:
        for spec in MODEL_SPECS:
            candidate_run_dir = _ensure_candidate_parent(status, spec)
            _evaluate_candidate_parent(status, spec, candidate_run_dir)

        for spec in MODEL_SPECS:
            family = str(spec["model_family"])
            gate = status["models"][family]["validation_gate"]
            if not bool(gate["passed"]):
                _mark_skipped_ablation(status, family)
                continue
            for scheme in SCHEME_SEQUENCE:
                _ensure_candidate_aggregate(status, spec, scheme)

        status["overall_status"] = "complete"
        status["active_phase"] = "finished"
        status["active_model_family"] = ""
        _write_status(status)
    except Exception as exc:
        status["overall_status"] = "failed"
        status["active_phase"] = "failed"
        status["active_model_family"] = ""
        status["current_subprocess"] = {
            "pid": None,
            "label": "",
            "command": [],
            "started_at": "",
        }
        status["error_message"] = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        _write_status(status)
        raise


if __name__ == "__main__":
    main()
