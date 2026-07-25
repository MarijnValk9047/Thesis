from __future__ import annotations

import os
import shutil
import sys
import csv
import json
from pathlib import Path


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel import s4_4c5p_bh_fixed_reference_cost_completion_audit as audit


def test_completion_audit_proves_all_seven_phases() -> None:
    output = (
        audit.REPO_ROOT
        / "data"
        / "03_Optimisation"
        / "runs"
        / f"_test_completion_audit_{os.getpid()}"
    )
    shutil.rmtree(output, ignore_errors=True)
    try:
        result = audit.run_completion_audit(output_directory=output)
        assert result["summary"]["status"] == "pass"
        assert result["summary"]["phases_completed"] == list(range(1, 8))
        assert (
            result["summary"]["completion_decision"]
            == "ready_for_future_DAM_price_integration"
        )
        assert result["summary"]["requirements_passed"] == result["summary"][
            "requirements_total"
        ]
    finally:
        shutil.rmtree(output, ignore_errors=True)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _accepted_paths() -> dict[str, Path]:
    return {key: audit.RUN_ROOT / value for key, value in audit.RUNS.items()}


def test_production_envelope_reports_every_deadline_and_causal_selector() -> None:
    paths = _accepted_paths()
    rows = audit._build_production_envelope_diagnosis(
        paths["phase4_cost"], paths["phase1_2_physical"]
    )
    route_deadlines = [
        row
        for row in rows
        if row["row_type"] == "per_replan_first_deadline_route_band"
    ]
    quota_deadlines = [
        row for row in rows if row["row_type"] == "cumulative_quota_deadline"
    ]
    assert len(route_deadlines) == 7 * (3 + 5)
    assert len(quota_deadlines) == 14
    assert all(row["status"] == "pass" for row in route_deadlines + quota_deadlines)
    conclusions = [row for row in rows if row["row_type"] == "causal_conclusion"]
    assert len(conclusions) == 2
    assert all(row["binding_side"] == "upper" for row in conclusions)
    assert all(
        row["causal_role"]
        == "governed_receding_horizon_front_loading_inside_the_fixed_reference_band"
        for row in conclusions
    )
    c0_continuous = [
        row
        for row in rows
        if row["row_type"] == "continuous_operation_rule"
        and row["configuration"] == "C0"
    ]
    c1_continuous = [
        row
        for row in rows
        if row["row_type"] == "continuous_operation_rule"
        and row["configuration"] == "C1"
    ]
    assert all(float(row["on_hours"]) == 168.0 for row in c0_continuous)
    assert all("override_disabled" in row["causal_role"] for row in c1_continuous)


def test_cost_waterfall_reconciles_and_excludes_internal_and_residual_flows() -> None:
    paths = _accepted_paths()
    rows, totals = audit._build_cost_waterfall(paths["phase4_cost"])
    included = [row for row in rows if row["row_type"] == "included_flow"]
    excluded = [row for row in rows if row["row_type"] == "excluded_flow"]
    assert len(included) == len(
        [
            row
            for row in audit.load_future_cost_boundary_contract()
            if row["objective_enabled"] == "true"
        ]
    )
    assert len({row["double_count_group"] for row in included}) == len(included)
    assert all(float(row["executed_cost_eur"]) == 0.0 for row in excluded)
    assert all(
        row["included_status"] == "excluded_zero_direct_cost"
        for row in excluded
        if "RESIDUAL" in row["flow_id"]
        or row["flow_id"].startswith("BOTH_WAG_")
        or "STEAM" in row["flow_id"]
        or "GEN_" in row["flow_id"]
    )
    imported_slab = next(row for row in included if row["flow_id"] == "C1_MAT_IMPORTED_SLAB")
    assert imported_slab["origin_status"] == "imported_origin_tagged"
    assert imported_slab["component"] == "external_slab_boundary"
    assert abs(totals["C0"]["executed_cost_eur"] - 34_154_162.09339) < 1e-5
    assert abs(totals["C1"]["executed_cost_eur"] - 61_068_468.567875) < 1e-5


def test_generator_anchor_decomposition_is_conserved_and_not_fitted() -> None:
    paths = _accepted_paths()
    decomposition = audit._build_generator_anchor_causal_decomposition(paths)
    generator_wag = next(
        row
        for row in decomposition
        if row["decomposition_step"] == "generator_WAG_plus_flare"
    )
    vn25_ng = next(
        row for row in decomposition if row["decomposition_step"] == "VN25_named_NG"
    )
    assert abs(float(generator_wag["central_cost_value"]) - 6.69607804) < 1e-8
    assert abs(float(generator_wag["central_gap_to_anchor"]) + 3.90392196) < 1e-8
    assert float(vn25_ng["central_cost_value"]) == 0.0
    assert float(vn25_ng["natural_gas_high_value"]) == 0.0
    classifications = audit._build_anchor_gap_classification(
        audit._csv(paths["phase5_reconciliation"] / "post_cost_anchor_comparison.csv")
    )
    assert all(row["implementation_defect"] == "no" for row in classifications)
    assert all(row["forced_annual_target_active"] == "no" for row in classifications)
    assert all(row["repair_implemented"] == "no_unsupported_anchor_fitting" for row in classifications)


def test_final_acceptance_audit_explains_production_and_closes_waterfalls() -> None:
    output = (
        audit.REPO_ROOT
        / "data"
        / "03_Optimisation"
        / "runs"
        / f"_test_final_acceptance_audit_{os.getpid()}"
    )
    shutil.rmtree(output, ignore_errors=True)
    try:
        result = audit.run_final_acceptance_explanation_audit(
            output_directory=output
        )
        assert result["summary"]["status"] == "pass"
        assert (
            result["summary"]["final_decision"]
            == "ready_for_governed_DAM_data_contract"
        )
        production = _read_csv(output / "production_envelope_diagnosis.csv")
        planned = [
            row
            for row in production
            if row["row_type"] == "view_comparison"
            and row["view_id"] == "first_planned_168h_horizon"
        ]
        executed = [
            row
            for row in production
            if row["row_type"] == "view_comparison"
            and row["view_id"] == "complete_executed_blocks"
        ]
        assert len(planned) == len(executed) == 2
        assert all(abs(float(row["annual_equivalent_mt_y"]) - 6.75) < 5e-9 for row in planned)
        assert all(abs(float(row["annual_equivalent_mt_y"]) - 6.78375) < 5e-9 for row in executed)
        assert all(
            row["status"] == "pass"
            for row in production
            if row["row_type"] == "continuous_operation_rule"
        )

        waterfall = _read_csv(output / "procurement_cost_waterfall.csv")
        for configuration in (
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        ):
            flow_total = sum(
                float(row["executed_cost_eur"])
                for row in waterfall
                if row["row_type"] == "included_flow"
                and row["configuration_id"] == configuration
            )
            config_total = next(
                float(row["executed_cost_eur"])
                for row in waterfall
                if row["row_type"] == "configuration_total"
                and row["configuration_id"] == configuration
            )
            assert abs(flow_total - config_total) < 1e-5
        assert all(
            float(row["executed_cost_eur"]) == 0.0
            for row in waterfall
            if row["row_type"] == "excluded_flow"
        )

        classifications = _read_csv(output / "anchor_gap_classification.csv")
        assert {row["anchor_id"] for row in classifications} == {
            "c1_vn25_ng_4_1",
            "c1_generator_wag_with_flare_10_6",
        }
        assert all(row["forced_annual_target_active"] == "no" for row in classifications)
        assert all(row["implementation_defect"] == "no" for row in classifications)
        checks = _read_csv(output / "final_acceptance_checks.csv")
        assert checks and all(row["status"] == "pass" for row in checks)
        summary = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
        assert summary["solver_reruns"] == 0
        assert summary["direct_C0_C1_EUR_per_t_comparability"] == "not_directly_comparable"
    finally:
        shutil.rmtree(output, ignore_errors=True)
