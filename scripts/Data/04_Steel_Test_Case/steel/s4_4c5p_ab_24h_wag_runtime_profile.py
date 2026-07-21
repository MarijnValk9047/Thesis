"""Time-boxed 24-hour C1 WAG regression and computational profile.

The subprocess boundary is intentional: it guarantees a wall-clock maximum
even when a solver-specific time-limit setting is ignored by a local wrapper.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .model import collect_model_stats
from .s4_4c_unified_physical_modelbuilder import (
    S44B_INPUT_DIR,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
)


STAGE = "S4.4c5p_ab_24h_wag_runtime_profile"
OUTPUT_DIR = Path("data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_ab_24h_wag_runtime_profile")
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_24H_WAG_RUNTIME_PROFILE.md")
CASE_COLUMNS = ["case_id", "wall_time_limit_seconds", "outcome", "wall_runtime_seconds", "solver_status", "termination_condition", "build_runtime_seconds", "solve_runtime_seconds", "variable_count", "binary_count", "constraint_count", "mip_gap", "caveat"]
BUILD_COLUMNS = ["case_id", "build_runtime_seconds", "variable_count", "binary_count", "constraint_count", "minimal_wag_layer", "retained_route", "fixed_schedule"]


def _build_profile(case_id: str, *, wag: bool, retained: bool, fixed_schedule: bool) -> dict[str, str]:
    tables = _load_tables(S44B_INPUT_DIR)
    start = time.perf_counter()
    inputs = _build_c1_inputs(tables, horizon_hours_override=24, target_multiplier=1.0, include_retained_bf_bof=retained)
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=wag,
        enable_c1_retained_bf_bof_route=retained,
        fix_c1_hybrid_schedule=fixed_schedule,
        c1_retained_route_policy="bottom_up_fixed_retained_route",
    )
    stats = collect_model_stats(model)
    return {
        "case_id": case_id,
        "build_runtime_seconds": f"{time.perf_counter() - start:.6f}",
        "variable_count": str(stats.variables),
        "binary_count": str(stats.binaries),
        "constraint_count": str(stats.constraints),
        "minimal_wag_layer": str(wag).lower(),
        "retained_route": str(retained).lower(),
        "fixed_schedule": str(fixed_schedule).lower(),
    }


def _child_command(kwargs: dict[str, Any]) -> list[str]:
    code = """
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'scripts' / 'Data' / '04_Steel_Test_Case'))
from steel.s4_4c_unified_physical_modelbuilder import S44B_INPUT_DIR, _load_tables, _solve_c0_configuration, _solve_c1_configuration
kwargs = json.loads(sys.argv[1])
configuration = kwargs.pop('configuration')
tables = _load_tables(S44B_INPUT_DIR)
if configuration == 'C0':
    audit, _, _ = _solve_c0_configuration(tables, **kwargs)
else:
    audit, _, _ = _solve_c1_configuration(tables, **kwargs)
print(json.dumps({'audit': audit}))
"""
    return [sys.executable, "-c", code, json.dumps(kwargs)]


def _run_case(case_id: str, timeout_seconds: int, kwargs: dict[str, Any]) -> dict[str, str]:
    started = time.perf_counter()
    environment = {**os.environ, "PYTHONUTF8": "1"}
    try:
        completed = subprocess.run(
            _child_command(kwargs),
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "case_id": case_id,
            "wall_time_limit_seconds": str(timeout_seconds),
            "outcome": "terminated_by_wall_clock_guard",
            "wall_runtime_seconds": f"{time.perf_counter() - started:.6f}",
            "solver_status": "not_available",
            "termination_condition": "not_available",
            "build_runtime_seconds": "not_available",
            "solve_runtime_seconds": "not_available",
            "variable_count": "not_available",
            "binary_count": "not_available",
            "constraint_count": "not_available",
            "mip_gap": "not_available",
            "caveat": "Child process was terminated by the external wall-clock guard; no dispatch is interpreted.",
        }
    if completed.returncode != 0:
        return {
            "case_id": case_id,
            "wall_time_limit_seconds": str(timeout_seconds),
            "outcome": "child_failed",
            "wall_runtime_seconds": f"{time.perf_counter() - started:.6f}",
            "solver_status": "not_available",
            "termination_condition": "not_available",
            "build_runtime_seconds": "not_available",
            "solve_runtime_seconds": "not_available",
            "variable_count": "not_available",
            "binary_count": "not_available",
            "constraint_count": "not_available",
            "mip_gap": "not_available",
            "caveat": completed.stderr.strip()[-800:] or "Child regression process failed without diagnostic output.",
        }
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    audit = payload["audit"]
    return {
        "case_id": case_id,
        "wall_time_limit_seconds": str(timeout_seconds),
        "outcome": "completed",
        "wall_runtime_seconds": f"{time.perf_counter() - started:.6f}",
        "solver_status": str(audit.get("solver_status", "")),
        "termination_condition": str(audit.get("termination_condition", "")),
        "build_runtime_seconds": str(audit.get("build_runtime_seconds", "")),
        "solve_runtime_seconds": str(audit.get("runtime_seconds", "")),
        "variable_count": str(audit.get("variable_count", "")),
        "binary_count": str(audit.get("binary_count", "")),
        "constraint_count": str(audit.get("constraint_count", "")),
        "mip_gap": str(audit.get("mip_gap", "")),
        "caveat": str(audit.get("caveat", "")),
    }


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run_s4_4c5p_ab_24h_wag_runtime_profile(*, full_case_timeout_seconds: int = 300) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = [
        ("c1_drp_eaf_only", 30, {"configuration": "C1", "horizon_hours_override": 24, "solver_time_limit_seconds": 25}),
        ("c1_retained_route_no_wag", 30, {"configuration": "C1", "horizon_hours_override": 24, "enable_c1_retained_bf_bof_route": True, "fix_c1_hybrid_schedule": True, "c1_retained_route_policy": "bottom_up_fixed_retained_route", "solver_time_limit_seconds": 25}),
        ("c1_retained_route_with_wag", 30, {"configuration": "C1", "horizon_hours_override": 24, "enable_minimal_wag_layer": True, "enable_c1_retained_bf_bof_route": True, "fix_c1_hybrid_schedule": True, "c1_retained_route_policy": "bottom_up_fixed_retained_route", "solver_time_limit_seconds": 25}),
        ("c0_wag_fixed_schedule", 30, {"configuration": "C0", "horizon_hours_override": 24, "enable_minimal_wag_layer": True, "fix_binary_schedule": True, "solver_time_limit_seconds": 25}),
        ("c0_wag_flexible_schedule", full_case_timeout_seconds, {"configuration": "C0", "horizon_hours_override": 24, "enable_minimal_wag_layer": True, "fix_binary_schedule": False, "solver_time_limit_seconds": full_case_timeout_seconds}),
    ]
    build_profiles = [
        _build_profile(case_id, wag=kwargs.get("enable_minimal_wag_layer", False), retained=kwargs.get("enable_c1_retained_bf_bof_route", False), fixed_schedule=kwargs.get("fix_c1_hybrid_schedule", False))
        for case_id, _, kwargs in cases
        if kwargs["configuration"] == "C1"
    ]
    results = [_run_case(case_id, timeout, kwargs) for case_id, timeout, kwargs in cases]
    summary = {
        "stage": STAGE,
        "full_case_timeout_seconds": full_case_timeout_seconds,
        "build_profiles": build_profiles,
        "case_results": results,
        "interpretation_rule": "Only completed cases with feasible or optimal termination may be interpreted physically. Wall-clock terminations identify a computational bottleneck, not a physical result.",
    }
    _write_csv(OUTPUT_DIR / "model_build_profile.csv", build_profiles, BUILD_COLUMNS)
    _write_csv(OUTPUT_DIR / "runtime_case_results.csv", results, CASE_COLUMNS)
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        """# C5 24-hour WAG Runtime Profile

This stage separates model-build time from solve time and enforces an external
wall-clock guard around each solve. The full retained-route WAG case has a
maximum of 300 seconds. A timeout is a computational diagnostic only: no
dispatch, residual or anchor result may be inferred from it.

The profile separates C1-only solves from C0-only solves. It compares the
simple C1 DRP/EAF case, the retained BF-BOF route with and without WAG, and
the C0 WAG layer with fixed versus flexible binary schedules. This isolates
whether runtime comes from the retained physical route, WAG balances, or the
unfixed C0 binary schedule.
""",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    run_s4_4c5p_ab_24h_wag_runtime_profile()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
