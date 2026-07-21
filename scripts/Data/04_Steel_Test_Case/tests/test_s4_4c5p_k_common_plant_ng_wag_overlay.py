from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5f_coking_plant_minimal_parameterisation import C0, C1  # noqa: E402
from steel.s4_4c5p_k_common_plant_ng_wag_overlay import (  # noqa: E402
    ALLOCATION_COLUMNS,
    C5P_K_DIR,
    FUEL_DEMAND_COLUMNS,
    NG_SUMMARY_COLUMNS,
    REPORT_PATH,
    WARNING_COLUMNS,
    allocate_with_wag_priority,
    run_s4_4c5p_k_common_plant_ng_wag_overlay,
)


ANCHOR_REGISTER = Path(
    "data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/c5_model_anchor_evidence_register.csv"
)

REQUIRED_FILES = {
    "common_plant_fuel_demand_overlay.csv": FUEL_DEMAND_COLUMNS,
    "common_plant_wag_ng_allocation.csv": ALLOCATION_COLUMNS,
    "common_plant_ng_residual_summary.csv": NG_SUMMARY_COLUMNS,
    "common_plant_warnings.csv": WARNING_COLUMNS,
}

OFFICIAL_PATCHED_IDS = {
    "c0_official_total_site_electricity_13_7pj_missing",
    "c0_official_grid_import_3_4pj_missing",
    "c1_official_total_site_electricity_17_8pj_missing",
    "c1_official_grid_import_11_7pj_missing",
    "c0_full_site_ng_12_5pj_missing",
    "c1_full_site_ng_46_5pj_missing",
    "c0_official_scope1_12_6_missing",
    "c1_official_scope1_8_3_missing",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5p_k_outputs() -> Path:
    run_s4_4c5p_k_common_plant_ng_wag_overlay()
    return C5P_K_DIR


def test_anchor_register_patches_athanasiadis_rows_without_blocking():
    rows = {row["anchor_id"]: row for row in _read_csv(ANCHOR_REGISTER)}
    athan_rows = [row for row in rows.values() if row["anchor_id"].startswith("athan_table")]
    assert len(athan_rows) == 8
    for row in athan_rows:
        assert row["source_trust_rank"] == "Rank 3"
        assert row["evidence_tier"] == "Tier B"
        assert row["anchor_role"] == "model_precedent"
        assert row["model_use_status"] == "sensitivity_scoring"
        assert row["locator_quality"] == "partial"
        assert row["use_in_primary_score"] == "no"
        assert "value supplied by user" in row["source_locator"]
        assert "not official Tata truth" in row["caveat"]


def test_official_mer_candidate_anchors_are_open_partial_not_blocked():
    rows = {row["anchor_id"]: row for row in _read_csv(ANCHOR_REGISTER)}
    for anchor_id in OFFICIAL_PATCHED_IDS:
        row = rows[anchor_id]
        assert row["source_trust_rank"] == "Rank 1"
        assert row["evidence_tier"] == "Tier F"
        assert row["locator_quality"] == "partial"
        assert row["model_use_status"] != "blocked"
        assert row["use_in_primary_score"] == "no"
        assert row["review_status"] == "open"
        assert "Inherited from prior source-card/candidate work" in row["caveat"]


def test_c5p_k_outputs_parse_and_have_required_columns(c5p_k_outputs: Path):
    for name, columns in REQUIRED_FILES.items():
        path = c5p_k_outputs / name
        assert path.exists(), name
        rows = _read_csv(path)
        assert rows, name
        assert set(columns).issubset(rows[0].keys()), name

    summary = json.loads((c5p_k_outputs / "summary.json").read_text(encoding="utf-8"))
    gate = json.loads((c5p_k_outputs / "s4_4c5p_k_stage_gate.json").read_text(encoding="utf-8"))
    assert summary["status"] == "development_only"
    assert summary["thesis_usability"] is False
    assert summary["failure_count"] == 0
    assert gate["candidate_values_migrated_to_executable_inputs"] is False
    assert gate["model_equations_changed"] is False
    assert gate["residual_ng_load_added"] is False
    assert gate["economics_readiness"] == "NO_GO"
    assert gate["DA_readiness"] == "NO_GO"
    assert REPORT_PATH.exists()


def test_c1_only_assets_are_excluded_from_c0_common_replication(c5p_k_outputs: Path):
    fuel_rows = _read_csv(c5p_k_outputs / "common_plant_fuel_demand_overlay.csv")
    allocated_plants = {row["plant"] for row in fuel_rows if row["common_or_new_asset"] == "common_C0_C1_asset"}
    assert "DRP" not in allocated_plants
    assert "EAF" not in allocated_plants
    assert {"HSM/WBW", "KGF/coking"} <= allocated_plants

    warnings = _read_csv(c5p_k_outputs / "common_plant_warnings.csv")
    assert any(row["issue_type"] == "c1_only_asset_excluded" and row["plant"] == "DRP" for row in warnings)
    assert any(row["issue_type"] == "c1_only_asset_excluded" and row["plant"] == "EAF" for row in warnings)


def test_common_plants_use_same_candidate_intensity_basis_in_c0_and_c1(c5p_k_outputs: Path):
    fuel_rows = [
        row
        for row in _read_csv(c5p_k_outputs / "common_plant_fuel_demand_overlay.csv")
        if row["common_or_new_asset"] == "common_C0_C1_asset"
    ]
    for plant in {"HSM/WBW", "KGF/coking"}:
        rows = [row for row in fuel_rows if row["plant"] == plant]
        assert {row["configuration"] for row in rows} == {C0, C1}
        assert len({(row["intensity_value"], row["intensity_unit"]) for row in rows}) == 1


def test_wag_priority_fallback_and_explicit_ratio_helper():
    fallback = allocate_with_wag_priority(10.0, 7.0)
    assert fallback["wag_allocated_pj"] == pytest.approx(7.0)
    assert fallback["ng_residual_pj"] == pytest.approx(3.0)
    assert fallback["unmet_fuel_pj"] == pytest.approx(0.0)

    explicit = allocate_with_wag_priority(10.0, 100.0, explicit_ng_share=0.25)
    assert explicit["wag_allocated_pj"] == pytest.approx(7.5)
    assert explicit["ng_residual_pj"] == pytest.approx(2.5)
    assert explicit["unmet_fuel_pj"] == pytest.approx(0.0)

    impossible = allocate_with_wag_priority(-1.0, 0.0)
    assert "NEGATIVE_OR_IMPOSSIBLE_INPUT" in impossible["warnings"]


def test_common_ng_residual_summary_reports_partial_anchor_residuals(c5p_k_outputs: Path):
    rows = {row["configuration"]: row for row in _read_csv(c5p_k_outputs / "common_plant_ng_residual_summary.csv")}
    assert rows[C0]["full_site_ng_anchor_PJ_y"] == "12.5"
    assert rows[C1]["full_site_ng_anchor_PJ_y"] == "46.5"
    assert _num(rows[C0]["common_plant_ng_residual_PJ_y"]) == pytest.approx(0.0, abs=1e-9)
    assert _num(rows[C1]["common_plant_ng_residual_PJ_y"]) > 0.0
    assert "partial" in rows[C0]["anchor_status"]
    assert "partial" in rows[C1]["anchor_status"]
