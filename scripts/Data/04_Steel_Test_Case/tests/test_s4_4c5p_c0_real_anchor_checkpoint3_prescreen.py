from __future__ import annotations

from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    _config,
    _model_target_multiplier,
    _rolling_plans_from_config,
    _rolling_production_progress_contract,
)
from steel.s4_4c5p_c0_real_anchor_checkpoint3_prescreen import (
    CASE_DEFINITIONS,
    DEFAULT_CONFIG_PATH,
    _c0_progress_execution_arguments,
    dry_run_prescreen,
    gross_electricity_band_score,
    is_material_relative_error_improvement,
    load_frozen_development_week,
    resolve_candidate_manifest,
    score_and_select_checkpoint3_rows,
)


def test_checkpoint3_resolves_exactly_the_five_declared_candidates() -> None:
    rows = resolve_candidate_manifest(_config(DEFAULT_CONFIG_PATH))
    assert [row["candidate_id"] for row in rows] == [item[0] for item in CASE_DEFINITIONS]
    assert len(rows) == 5
    assert rows[0]["repair_interface_active"] is False
    assert all(row["repair_interface_active"] for row in rows[1:])
    assert all(row["solver_invoked"] is False for row in rows)
    assert all(row["planning_horizon_hours"] == 168 for row in rows)


def test_checkpoint3_background_conversions_and_stress_label_are_exact() -> None:
    rows = {row["candidate_id"]: row for row in resolve_candidate_manifest(_config(DEFAULT_CONFIG_PATH))}
    assert rows["source_driven_baseline"]["explicit_background_mwh_h"] == 0.0
    assert rows["recovery_bg00"]["explicit_background_mwh_h"] == 0.0
    assert rows["recovery_bg15"]["explicit_background_mwh_h"] == pytest.approx(
        0.4755 * 1_000_000.0 / 8760.0
    )
    assert rows["recovery_bg25"]["explicit_background_mwh_h"] == pytest.approx(
        0.7925 * 1_000_000.0 / 8760.0
    )
    assert rows["recovery_bg30_stress"]["explicit_background_mwh_h"] == pytest.approx(
        0.9510 * 1_000_000.0 / 8760.0
    )
    assert rows["recovery_bg30_stress"]["outside_prior_5_25_range"] is True
    assert "not_source_calibrated" in rows["recovery_bg30_stress"]["boundary_role"]


def test_checkpoint3_repaired_parameters_and_initial_state_are_identical() -> None:
    repaired = [
        row
        for row in resolve_candidate_manifest(_config(DEFAULT_CONFIG_PATH))
        if row["repair_interface_active"]
    ]
    fixed_fields = {
        "generator_efficiency",
        "generator_mixed_volume_cap_nm3_h",
        "generator_electrical_capacity_mw",
        "natural_gas_lhv_mj_per_nm3",
        "inferred_low_case_ng_floor_pj_y",
        "already_represented_fixed_ng_pj_y",
        "flexible_heat_service_envelope_pj_y",
        "normal_case_flexible_ng_validation_reference_pj_y",
        "production_policy",
        "initial_state_policy",
        "material_coefficients_policy",
        "wag_yields_policy",
    }
    for field in fixed_fields:
        assert len({row[field] for row in repaired}) == 1


def test_checkpoint3_week_is_frozen_development_only_and_dry_run_never_builds() -> None:
    week = load_frozen_development_week()
    assert week["period_id"] == "validation_2024-02-12"
    assert week["delivery_start_utc"] == "2024-02-11T23:00:00+00:00"
    assert week["delivery_end_exclusive_utc"] == "2024-02-18T23:00:00+00:00"
    assert week["operational_price_field"] == "y_pred"
    assert week["final_eight_held_out_selection_eligible"] is False
    assert week["selection_used_optimization_results"] is False
    result = dry_run_prescreen()
    assert result["failure_count"] == 0
    assert result["candidate_count"] == 5
    assert result["gurobi_invoked"] is False
    assert result["model_built"] is False
    assert result["candidate_scorecard_created"] is False


def test_checkpoint3_prepared_arguments_omit_terminal_recoverability_bounds() -> None:
    config = _config(DEFAULT_CONFIG_PATH)
    plan = _rolling_plans_from_config(config)[0][0]
    progress = _rolling_production_progress_contract(
        plan=plan,
        replan_index=0,
        cumulative_before={C0_CONFIGURATION: 0.0},
        base_target_multiplier=_model_target_multiplier(config, plan),
        enabled=True,
        envelope_fraction=0.005,
        central_target_before_t=0.0,
        terminal_exact=False,
    )

    arguments = _c0_progress_execution_arguments(progress)

    assert arguments["progress_lower"] is None
    assert arguments["progress_upper"] is None


def _solved_score_rows() -> list[dict[str, object]]:
    values = (
        (
            "source_driven_baseline",
            2.188994699792857,
            0.13410019786674957,
            1.0,
            0.22320226133977356,
            0.06728385155228755,
            0.0,
        ),
        (
            "recovery_bg00",
            2.188994697342143,
            0.1341001988361777,
            0.17183943664804477,
            0.22320226133977356,
            0.06728385171568625,
            0.0,
        ),
        (
            "recovery_bg15",
            2.6643109843328574,
            0.1162622413050971,
            0.17183943664804477,
            0.22318877543032792,
            0.06726830130718958,
            0.4755 / 3.17,
        ),
        (
            "recovery_bg25",
            2.9813109825707147,
            0.1162622412844712,
            0.17183943664804477,
            0.22318877543032792,
            0.06726830130718958,
            0.7925 / 3.17,
        ),
        (
            "recovery_bg30_stress",
            3.139810984844286,
            0.11626224380085878,
            0.17183943664804477,
            0.22318877543032792,
            0.06726830130718958,
            0.951 / 3.17,
        ),
    )
    return [
        {
            "candidate_id": candidate_id,
            "guardrail_status": "pass",
            "gross_electricity_twh_y": gross,
            "wag_only_electricity_relative_error": wag_error,
            "named_ng_relative_error": ng_error,
            "coal_relative_error": coal_error,
            "first_order_co2_relative_error": co2_error,
            "source_deviation_background_share_of_3p17": source_deviation,
        }
        for (
            candidate_id,
            gross,
            wag_error,
            ng_error,
            coal_error,
            co2_error,
            source_deviation,
        ) in values
    ]


def test_checkpoint3_gross_band_score_keeps_central_and_band_views() -> None:
    score = gross_electricity_band_score(2.9813109825707147)

    assert score["gross_electricity_central_signed_residual_twh_y"] == pytest.approx(
        2.9813109825707147 - 3.17
    )
    assert score["gross_electricity_band_distance_twh_y"] == pytest.approx(
        0.018689017429285304
    )
    assert score["gross_electricity_band_relative_error"] == pytest.approx(
        0.006229672476428435
    )
    assert score["gross_electricity_band_relative_error_denominator_twh_y"] == 3.0
    assert is_material_relative_error_improvement(0.2, 0.199)
    assert not is_material_relative_error_improvement(0.2, 0.1990000001)


def test_checkpoint3_solved_score_selection_is_material_and_sensitivity_only() -> None:
    scored = {
        row["candidate_id"]: row
        for row in score_and_select_checkpoint3_rows(_solved_score_rows())
    }

    assert scored["recovery_bg15"]["improved_energy_family_count_vs_baseline"] == 3
    assert scored["recovery_bg25"]["improved_energy_family_count_vs_baseline"] == 3
    assert (
        scored["recovery_bg30_stress"][
            "improved_energy_family_count_vs_baseline"
        ]
        == 3
    )
    assert scored["recovery_bg25"][
        "improved_independent_validation_family_count_vs_baseline"
    ] == 0
    assert {
        candidate_id
        for candidate_id, row in scored.items()
        if row["selected_for_checkpoint4"]
    } == {"source_driven_baseline", "recovery_bg25"}
    assert (
        scored["recovery_bg25"]["candidate_classification"]
        == "emulation_sensitivity_only"
    )
    assert scored["recovery_bg25"]["promotable_central_from_checkpoint3"] is False
    assert "gross_band_fit" in scored["recovery_bg25"]["selection_reason"]
    assert scored["recovery_bg30_stress"]["selected_for_checkpoint4"] is False
    assert "stress_boundary_fit" in scored["recovery_bg30_stress"]["selection_reason"]
