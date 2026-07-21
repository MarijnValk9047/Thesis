from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_aw_annual_multi_anchor_reconciliation import (
    _anchor_family_summary,
    _annual_anchor_rows,
    _comparability_contract,
    _proximity,
)
import steel.s4_4c5p_aw_annual_multi_anchor_reconciliation as annual_reconciliation


def test_proximity_obeys_strict_seven_point_five_and_ten_percent_policy() -> None:
    assert _proximity(0.074999, True, 0.075, 0.10) == "within_7_5pct_target"
    assert _proximity(0.075, True, 0.075, 0.10) == "within_10pct_review"
    assert _proximity(0.101, True, 0.05, 0.10) == "outside_10pct"


def test_non_comparable_anchor_is_not_scored() -> None:
    assert _proximity(0.0, False, 0.05, 0.10) == "not_scored"


def test_generator_wag_subtotal_is_score_eligible_but_total_fuel_is_not() -> None:
    wag = _comparability_contract("c1_generator_wag_with_flare_10_6")
    total = _comparability_contract("c1_generator_total_with_flare_14_6")
    assert wag["score_eligible"] == "yes"
    assert wag["comparability_decision"] == "direct_comparable"
    assert total["score_eligible"] == "no"
    assert total["comparability_decision"] == "named_ng_boundary_missing"
    assert total["score_status"] == "not_comparable"
    assert total["exclusion_reason"] == "named_NG_hourly_driver_missing"


def test_production_target_is_a_guardrail_not_independent_anchor_validation() -> None:
    target = _comparability_contract("active_final_product_target_6_75")
    assert target["score_eligible"] == "no"
    assert target["score_status"] == "production_guardrail"
    assert target["anchor_family"] == "production_guardrail"
    assert target["independent_validation"] == "no"
    assert target["exclusion_reason"] == "achieved_by_construction_not_independent_validation"


def test_contract_exposes_explicit_boundary_and_scoring_fields() -> None:
    contract = _comparability_contract("c1_official_total_site_electricity_17_8pj_missing")
    assert contract["numerator_alignment"] == "represented model gross electricity"
    assert contract["denominator_alignment"] == "official site-total annual electricity"
    assert contract["boundary_alignment"] == "model excludes residual/background loads and some process-service boundaries"
    assert contract["scaling_status"] == "not_allowed_partial_site_boundary"
    assert contract["score_status"] == "secondary_context"
    assert contract["exclusion_reason"] == "partial_site_boundary"


def test_annual_rows_publish_explicit_boundary_contract_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        annual_reconciliation,
        "_read_csv",
        lambda _path: [{
            "anchor_id": "active_final_product_target_6_75",
            "metric": "final_product_output",
            "model_value": "6.75",
            "anchor_value": "6.75",
            "unit": "Mt/y",
            "signed_residual": "0.0",
            "signed_residual_share": "0.0",
            "comparison_class": "primary_score",
            "comparison_basis": "active_target",
            "source_rank": "active_model_target",
            "locator_quality": "exact",
            "status": "comparable_with_caveat",
            "caveat": "active target",
        }],
    )
    rows = _annual_anchor_rows(
        {"run_id": "test_run", "label": "test", "role": "test"},
        Path("unused"),
        {"target_abs_residual_share": 0.075, "review_abs_residual_share": 0.10},
    )
    row = rows[0]
    assert row["numerator_definition"] == "same final-product proxy"
    assert row["denominator_definition"] == "same 6.75-Mt/y active target"
    assert row["site_process_boundary"] == "same rolling physical boundary"
    assert row["scaling_status"] == "not_required_same_target"
    assert row["score_status"] == "production_guardrail"
    assert row["exclusion_reason"] == "achieved_by_construction_not_independent_validation"
    assert row["proximity_status"] == "not_scored"
    assert row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"


def test_anchor_family_summary_deduplicates_rows_and_counts_only_independent_validation() -> None:
    rows = [
        {
            "anchor_family": "generator_wag_interface",
            "anchor_id": "subtotal",
            "boundary_comparable": "yes_with_caveat",
            "independent_validation": "yes",
            "proximity_status": "within_7_5pct_target",
            "exclusion_reason": "",
            "currentness_status": "current",
        },
        {
            "anchor_family": "generator_wag_interface",
            "anchor_id": "flare",
            "boundary_comparable": "no",
            "independent_validation": "no",
            "proximity_status": "not_scored",
            "exclusion_reason": "boundary_mismatch",
            "currentness_status": "current",
        },
        {
            "anchor_family": "production_guardrail",
            "anchor_id": "target",
            "boundary_comparable": "no",
            "independent_validation": "no",
            "proximity_status": "not_scored",
            "exclusion_reason": "achieved_by_construction_not_independent_validation",
            "currentness_status": "current",
        },
    ]
    summaries = {row["anchor_family"]: row for row in _anchor_family_summary(rows)}
    assert summaries["generator_wag_interface"]["independent_comparable_family"] == "yes"
    assert summaries["generator_wag_interface"]["family_below_7_5pct"] == "yes"
    assert summaries["generator_wag_interface"]["independent_comparable_row_count"] == 1
    assert summaries["production_guardrail"]["independent_comparable_family"] == "no"
