from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ar_c1_metallics_dri_interface_audit import (
    build_scrap_reconciliation_rows,
    load_metallics_evidence,
    run_dri_buffer_forced_shift,
)


def test_bof_and_eaf_scrap_streams_close_to_official_site_envelope() -> None:
    rows = {row["check_id"]: row for row in build_scrap_reconciliation_rows(load_metallics_evidence())}
    assert rows["separate_named_consumers"]["result"] == "pass"
    assert rows["process_streams_match_site_total_envelope"]["result"] == "pass"
    assert rows["external_plus_internal_matches_lower_site_total"]["result"] == "pass"


def test_equal_bof_eaf_scrap_ratio_is_not_promoted_without_evidence() -> None:
    rows = {row["check_id"]: row for row in build_scrap_reconciliation_rows(load_metallics_evidence())}
    assert rows["athanasiadis_equal_scrap_ratio_claim"]["result"] == "unverified"


def test_existing_dri_buffer_stores_releases_and_returns_to_initial_inventory() -> None:
    summary, trace = run_dri_buffer_forced_shift()
    assert summary["status"] == "pass"
    assert trace[0]["eaf_dri_input_t_h"] == 0.0
    assert summary["buffer_max_t"] > summary["buffer_initial_t"]
    assert summary["terminal_residual_t"] == 0.0
