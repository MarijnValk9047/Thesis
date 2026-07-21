from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_am_downstream_origin_route_ledger import (
    build_annual_ledger,
    build_gate_rows,
    load_source_values,
)


def test_c1_imported_slab_is_source_mapped_to_hsm_but_not_active() -> None:
    rows = build_annual_ledger(load_source_values())
    imported = next(
        row
        for row in rows
        if row["configuration"].startswith("C1") and row["origin"] == "imported_slab"
    )
    assert imported["sink"] == "HSM_WBW"
    assert imported["status"] == "reporting_only_inactive_supply"


def test_c1_eaf_dsp_share_is_preserved_only_for_diagnostic_reconciliation() -> None:
    rows = build_annual_ledger(load_source_values())
    eaf_dsp = next(
        row
        for row in rows
        if row["configuration"].startswith("C1") and row["origin"] == "EAF_endogenous_liquid_steel"
    )
    assert eaf_dsp["status"] == "diagnostic_only"
    assert "not a dispatch constraint" in eaf_dsp["caveat"]


def test_material_residuals_remain_visible() -> None:
    rows = build_annual_ledger(load_source_values())
    residuals = [row for row in rows if row["origin"] == "material_balance_residual"]
    assert len(residuals) == 2
    assert all(row["status"] == "visible_residual" for row in residuals)


def test_gate_blocks_physical_import_activation() -> None:
    imported_gate = next(row for row in build_gate_rows() if row["gate"] == "imported_slab_to_HSM")
    assert imported_gate["status"] == "source_mapped_not_implemented"
