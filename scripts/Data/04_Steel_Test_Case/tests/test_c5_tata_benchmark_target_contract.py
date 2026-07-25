import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CONTRACT_DIR = (
    ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "c5_tata_benchmark_target_contract"
)
CSV_PATH = CONTRACT_DIR / "calibration_validation_target_contract.csv"
SUMMARY_PATH = CONTRACT_DIR / "summary.json"

REQUIRED_FIELDS = {
    "target_id",
    "evidence_family",
    "metric",
    "value_low",
    "value_central",
    "value_high",
    "unit",
    "configuration",
    "denominator",
    "boundary",
    "source_id",
    "source_title",
    "exact_locator",
    "source_rank",
    "evidence_tier",
    "uncertainty",
    "classification",
    "allowed_use",
    "score_family",
    "calibration_use",
    "validation_use",
    "caveat",
    "canonical_anchor_id",
    "route",
    "numerator",
    "source_production_quantity",
    "denominator_type",
    "boundary_scope",
    "electricity_accounting_basis",
    "temporal_basis",
    "physical_basis",
    "co2_accounting_mode",
    "co2_included_sources",
    "raw_value",
    "raw_unit",
    "normalised_value",
    "normalised_unit",
    "scaled_value_to_6_75",
    "scaled_unit",
    "scaling_status_to_6_75",
    "locator_quality",
    "overlap_double_counting_risk",
    "comparison_status",
    "allowed_evidential_role",
    "role_freeze_status",
}
ALLOWED_CLASSIFICATIONS = {
    "scenario_definition",
    "calibration_target",
    "behavioural_calibration_target",
    "held_out_validation",
    "directional_validation",
    "reporting_context",
    "not_comparable",
    "blocked",
}
REQUIRED_EVIDENCE_FAMILIES = {
    "production_and_denominators",
    "hot_metal_liquid_steel_dri_final_product",
    "hsm_dsp_route_output",
    "slab_import",
    "plant_electricity_intensity",
    "full_site_gross_electricity",
    "internal_generation",
    "grid_import",
    "bfg_generation_and_use",
    "cog_generation_and_use",
    "bofg_generation_and_use",
    "wag_sink_allocation",
    "named_ng",
    "full_site_ng",
    "coal_and_coke",
    "ore_sinter_bf_pellets_dr_pellets",
    "bof_eaf_scrap",
    "steam_and_oxygen",
    "mode_b_explicit_fuel_co2",
    "full_site_scope_1",
    "represented_procurement_cost",
    "price_insensitive_operating_behaviour",
    "price_responsive_operating_behaviour",
    "buffers_and_inventory_response",
}
CANONICAL_PATH = (
    ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/"
    "c5_model_anchor_evidence_register.csv"
)
RUN_SNAPSHOT_PATH = (
    ROOT
    / "data/03_Optimisation/runs/steel_c5_tata_benchmark_v1_20260721/"
    "calibration_validation_target_contract.csv"
)
CALIBRATION_TARGET_IDS = {
    "mer_c0_kgf1_coke_1_0",
    "mer_c0_kgf2_coke_0_8",
    "mer_c1_kgf1_coke_1_0",
    "mer_c0_pefa_output_4_6",
    "mer_c1_pefa_output_4_0_5_0",
}
HELD_OUT_VALIDATION_TARGET_IDS = set()


def _rows():
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_target_contract_schema_ids_and_role_separation():
    rows = _rows()
    assert rows
    assert set(rows[0]) == REQUIRED_FIELDS
    assert all(all(row[field].strip() for field in REQUIRED_FIELDS) for row in rows)

    target_ids = [row["target_id"] for row in rows]
    assert len(target_ids) == len(set(target_ids))
    assert {row["classification"] for row in rows} <= ALLOWED_CLASSIFICATIONS
    assert REQUIRED_EVIDENCE_FAMILIES == {row["evidence_family"] for row in rows}
    assert {row["calibration_use"] for row in rows} <= {"true", "false"}
    assert {row["validation_use"] for row in rows} <= {"true", "false"}
    assert not any(
        row["calibration_use"] == "true" and row["validation_use"] == "true"
        for row in rows
    )

    for row in rows:
        assert row["allowed_evidential_role"] == row["classification"]
        assert row["role_freeze_status"] in {
            "frozen_checkpoint_3b_20260721",
            "reclassified_checkpoint8_overlap_audit_20260722",
        }
        if row["classification"] in {
            "calibration_target",
            "behavioural_calibration_target",
        }:
            assert row["calibration_use"] == "true"
            assert row["validation_use"] == "false"
            calibration_boundary_text = " ".join(
                row[field].lower() for field in ("denominator", "metric", "boundary")
            )
            assert not any(
                marker in calibration_boundary_text
                for marker in ("unresolved", "unknown", "suspected")
            )
        if row["classification"] in {"held_out_validation", "directional_validation"}:
            assert row["calibration_use"] == "false"
            assert row["validation_use"] == "true"

    by_id = {row["target_id"]: row for row in rows}
    assert by_id["athan_c0_ng_average_blocked"]["classification"] == "blocked"
    assert by_id["athan_c1_ng_average_blocked"]["classification"] == "blocked"
    for target_id in (
        "athan_c0_aggregate_wag_2_74",
        "athan_c1_aggregate_wag_1_23",
    ):
        assert by_id[target_id]["classification"] == "reporting_context"
        assert by_id[target_id]["evidence_family"] == "internal_generation"
        assert by_id[target_id]["boundary"] == "comparable_only_after_boundary_bridge"
        assert by_id[target_id]["allowed_use"] == "boundary_bridge_context_only"
        assert by_id[target_id]["score_family"] == "excluded"
        assert by_id[target_id]["calibration_use"] == "false"
        assert by_id[target_id]["validation_use"] == "false"
    for target_id in (
        "athan_c0_gross_electricity_3_17",
        "athan_c1_gross_electricity_4_89",
    ):
        assert by_id[target_id]["classification"] == "blocked"
        assert by_id[target_id]["calibration_use"] == "false"
    assert by_id["mer_c1_vn25_ng_4_1"]["classification"] == "scenario_definition"
    assert by_id["mer_c1_generator_wag_flare_10_6"]["classification"] == "scenario_definition"
    for target_id in (
        "mer_c1_vn25_hours_7519",
        "mer_c1_vn25_load_50pct",
        "mer_c1_ij01_hours_conflict",
    ):
        assert by_id[target_id]["classification"] == "reporting_context"
        assert by_id[target_id]["validation_use"] == "false"

    assert {
        row["target_id"] for row in rows if row["classification"] == "calibration_target"
    } == CALIBRATION_TARGET_IDS
    assert {
        row["score_family"]
        for row in rows
        if row["classification"] == "calibration_target"
    } == {"mer_kgf_coke_output", "mer_pefa_fired_pellet_output"}
    assert {
        row["target_id"]
        for row in rows
        if row["classification"] == "held_out_validation"
    } == HELD_OUT_VALIDATION_TARGET_IDS
    assert by_id["mer_c1_kgf2_coke_0"]["classification"] == "scenario_definition"
    assert by_id["mer_c1_kgf2_coke_0"]["calibration_use"] == "false"
    dri = by_id["mer_c1_dri_output_2_8"]
    assert dri["classification"] == "scenario_definition"
    assert dri["allowed_use"] == "scenario_definition_consistency_check"
    assert dri["calibration_use"] == dri["validation_use"] == "false"
    assert dri["score_family"] == "excluded"
    assert dri["overlap_double_counting_risk"] == "high_direct_parameter_overlap"
    assert dri["comparison_status"] == "scenario_definition_consistency_check"
    assert dri["role_freeze_status"] == "reclassified_checkpoint8_overlap_audit_20260722"
    assert "0.8484848485" in dri["caveat"]
    assert "about 117 t dry coal/h" in by_id["mer_c0_kgf2_coke_0_8"]["caveat"]


def test_canonical_register_is_qualified_exactly_once_and_snapshot_matches():
    rows = _rows()
    with CANONICAL_PATH.open(encoding="utf-8", newline="") as handle:
        canonical_rows = list(csv.DictReader(handle))
    qualified_ids = [
        row["canonical_anchor_id"]
        for row in rows
        if row["canonical_anchor_id"] != "not_applicable"
    ]
    canonical_ids = {row["anchor_id"] for row in canonical_rows}
    assert len(qualified_ids) == len(set(qualified_ids)) == len(canonical_ids) == 53
    assert set(qualified_ids) == canonical_ids
    assert CSV_PATH.read_bytes() == RUN_SNAPSHOT_PATH.read_bytes()


def test_checkpoint_8_summary_reconciles_partial_emulation_roles():
    rows = _rows()

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    expected_counts = dict(sorted(Counter(row["classification"] for row in rows).items()))
    expected_counts["held_out_validation"] = 0
    assert summary["row_count"] == len(rows)
    assert summary["classification_counts"] == expected_counts
    assert set(summary["calibration_target_ids"]) == CALIBRATION_TARGET_IDS
    assert summary["calibration_family_ids"] == [
        "mer_kgf_coke_output",
        "mer_pefa_fired_pellet_output",
    ]
    assert summary["quantitative_calibration_family_count"] == 2
    assert summary["strict_independent_held_out_family_count"] == 0
    assert set(summary["held_out_validation_target_ids"]) == (
        HELD_OUT_VALIDATION_TARGET_IDS
    )
    assert summary["coverage_classification"] == "partial_emulation"
    assert summary["checks"]["strict_independent_held_out_family_count_zero"] is True
    assert summary["checks"]["c1_dri_output_is_scenario_definition_consistency_check"] is True
    assert summary["required_family_count"] == 24
    assert summary["canonical_anchor_count"] == 53
    assert summary["missing_required_families"] == []
    assert all(summary["checks"].values())
