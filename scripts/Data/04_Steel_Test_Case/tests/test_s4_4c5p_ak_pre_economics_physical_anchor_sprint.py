from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ak_pre_economics_physical_anchor_sprint import (
    THRESHOLD,
    build_guardrail_rows,
    build_readiness_ledger,
    classify_anchor_role,
    evaluate_anchor_stop_condition,
)


def test_rank1_partial_anchor_is_primary_score() -> None:
    row = {"comparison_status": "partial_comparable", "source_rank": "Rank 1"}
    assert classify_anchor_role(row) == "primary_score"


def test_secondary_context_can_help_stop_rule_without_being_primary() -> None:
    row = {"comparison_status": "partial_comparable", "source_rank": "Rank 3"}
    assert classify_anchor_role(row) == "secondary_context"


def test_anchor_stop_requires_four_families_inside_threshold() -> None:
    rows = [
        {"scoring_role": "primary_score", "anchor_family": f"family_{index}", "within_15pct": "true"}
        for index in range(4)
    ]
    result = evaluate_anchor_stop_condition(rows)
    assert result["early_stop_ready"] is True
    assert result["threshold"] == THRESHOLD


def test_anchor_stop_fails_when_one_family_is_outside_threshold() -> None:
    rows = [
        {"scoring_role": "primary_score", "anchor_family": "a", "within_15pct": "true"},
        {"scoring_role": "primary_score", "anchor_family": "b", "within_15pct": "true"},
        {"scoring_role": "primary_score", "anchor_family": "c", "within_15pct": "true"},
        {"scoring_role": "secondary_context", "anchor_family": "d", "within_15pct": "false"},
    ]
    result = evaluate_anchor_stop_condition(rows)
    assert result["early_stop_ready"] is False


def test_readiness_keeps_economics_out_of_scope() -> None:
    rows = build_readiness_ledger()
    economics = next(row for row in rows if row["area"] == "economics")
    assert economics["sprint_status"] == "not_in_scope"
    assert economics["allowed_in_sprint"] == "no"


def test_guardrails_keep_market_terms_disabled() -> None:
    rows = build_readiness_ledger()
    guardrails = build_guardrail_rows({"status": "pass", "market_prices_enabled": False, "cumulative_execution_t": {"C1": 1.0}}, rows)
    checks = {row["check_id"]: row["status"] for row in guardrails}
    assert checks["market_and_economic_terms_disabled"] == "pass"
    assert checks["sprint_stops_before_economics"] == "pass"
