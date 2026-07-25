from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5p_ad_representative_process_profile_test import (  # noqa: E402
    HORIZON_HOURS,
    OUTPUT_DIR,
    run_s4_4c5p_ad_representative_process_profile_test,
)


def test_representative_profile_preserves_daily_pefa_component_energy_and_keeps_fixed_schedule():
    summary = run_s4_4c5p_ad_representative_process_profile_test()
    assert summary["status"] == "pass"
    assert summary["free_c0_binary_planning_used"] is False
    assert summary["annual_anchor_test"] == "NOT_RUN"

    with (OUTPUT_DIR / "profile_hour_weights.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["configuration"], row["controller_component"]), []).append(row)
    assert len(grouped) == 4
    for component_rows in grouped.values():
        assert len(component_rows) == HORIZON_HOURS
        assert abs(sum(float(row["timing_weight"]) for row in component_rows) - HORIZON_HOURS) <= 1e-8
        fixed = float(component_rows[0]["fixed_daily_component_demand_mwh"])
        weighted = sum(float(row["weighted_component_demand_mwh"]) for row in component_rows)
        assert abs(fixed - weighted) <= 1e-8


def test_representative_profile_keeps_boiler_and_anchor_claims_out_of_scope():
    summary = json.loads((OUTPUT_DIR / "summary.json").read_text(encoding="utf-8"))
    assert summary["boiler_timing_policy"] == "continuous_accepted_profile_unchanged"
    assert summary["go_no_go"]["annual_anchor_interpretation"] == "NO_GO"
    assert summary["go_no_go"]["NG_residual_allocation"] == "NO_GO"
