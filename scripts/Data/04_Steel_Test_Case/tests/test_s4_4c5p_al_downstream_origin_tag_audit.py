from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_al_downstream_origin_tag_audit import (
    build_anchor_rows,
    build_gap_rows,
    build_origin_tag_rows,
)


def test_origin_audit_keeps_imported_slab_out_of_physical_use() -> None:
    rows = build_origin_tag_rows("model.final_product_output = Expression()")
    imported = [row for row in rows if row["origin_tag"] == "imported_slab"]
    assert len(imported) == 2
    assert all(row["current_builder_status"] == "absent" for row in imported)
    assert all(row["physical_use_allowed"] == "no" for row in imported)


def test_anchor_matrix_preserves_separate_c1_boundaries() -> None:
    rows = [row for row in build_anchor_rows() if row["configuration"].startswith("C1")]
    values = {row["metric"]: row["annual_value_mt_y"] for row in rows}
    assert values == {"endogenous_liquid_steel": "6.8", "imported_slab": "0.6", "site_final_product": "7.0"}


def test_gap_register_forbids_cold_slab_as_hidden_import_supply() -> None:
    gaps = build_gap_rows(build_origin_tag_rows(""))
    cold_slab_gap = next(row for row in gaps if row["gap_id"] == "COLD_SLAB_STORE_NOT_IMPORT_SUPPLY")
    assert cold_slab_gap["severity"] == "blocking"
    assert "hidden supply" in cold_slab_gap["consequence"]
