from __future__ import annotations

import sys
from pathlib import Path


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import _config
from steel.s4_4c5p_be_fixed_reference_cost_sensitivities import (
    CONFIG_PATH,
    PRICE_FAMILIES,
    _case_definitions,
    _run_metrics,
)


def test_bounded_sensitivity_set_has_only_required_one_family_cases() -> None:
    cases = _case_definitions(_config(CONFIG_PATH))
    assert len(cases) == 15
    ids = {case["case_id"] for case in cases}
    for family in PRICE_FAMILIES:
        assert {f"{family}_low", f"{family}_high"}.issubset(ids)
    assert {"all_low", "all_high", "vn25_efficiency_low_0_34"}.issubset(ids)


def test_accepted_central_metrics_are_complete_and_guarded() -> None:
    from steel.s4_4c5p_be_fixed_reference_cost_sensitivities import CENTRAL_PARENT

    metrics = _run_metrics(CENTRAL_PARENT)
    assert len(metrics) == 2
    assert all(row["physical_guardrails_pass"] for row in metrics.values())
    assert all(row["executed_procurement_cost_eur"] > 0.0 for row in metrics.values())
