from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c3_static_physical_closeout import C3_DIR, run_s4_4c3_static_physical_closeout  # noqa: E402


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def test_s4_4c3_closeout_flags_fixed_schedule_and_guardrail_need() -> None:
    report = run_s4_4c3_static_physical_closeout()
    gate = report["stage_gate"]

    assert gate["decision"] == "pass_static_physical_closeout_but_daily_guardrail_required"
    assert gate["fixed_schedule_classification"] == "heuristic_not_benchmark_ready"
    assert gate["final_day_compression"] == "true"
    assert gate["daily_envelope_slack_used"] == "false"
    assert gate["free_c0_diagnostic_solved"] == "false"
    assert gate["ready_for_hot_cold_slab_and_wag_utility_equation_work"] == "true_with_guardrail_caveat"


def test_s4_4c3_outputs_parse_and_compare_variants() -> None:
    run_s4_4c3_static_physical_closeout()
    for name in [
        "s4_4c3_stage_gate.json",
        "s4_4c3_fixed_c0_binary_schedule_audit.json",
        "s4_4c3_c0_daily_envelope_diagnostic_report.json",
        "s4_4c3_free_c0_solve_diagnostic_report.json",
    ]:
        json.loads((C3_DIR / name).read_text(encoding="utf-8"))

    comparison = _rows(C3_DIR / "s4_4c3_fixed_vs_free_or_guarded_comparison.csv")
    by_variant = {row["variant_id"]: row for row in comparison}

    assert by_variant["fixed_c2_baseline"]["daily_min_t"] == "2936.4"
    assert by_variant["daily_envelope_diagnostic"]["daily_min_t"] == "4724.16"
    assert by_variant["daily_envelope_diagnostic"]["production_residual_t"] == "0.0"
    free_report = json.loads((C3_DIR / "s4_4c3_free_c0_solve_diagnostic_report.json").read_text(encoding="utf-8"))
    assert free_report["termination_condition"] == "maxTimeLimit"
    assert free_report["incumbent_available"] is True
