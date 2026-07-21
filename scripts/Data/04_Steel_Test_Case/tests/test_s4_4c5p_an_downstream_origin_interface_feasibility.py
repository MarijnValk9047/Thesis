from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from steel.s4_4c_unified_physical_modelbuilder import _build_c1_inputs, _build_c1_model, _load_tables


def test_source_backed_route_mapping_has_no_eaf_share_constraint() -> None:
    routing = build_c1_uniform_import_routing(load_source_values(), horizon_hours=24)
    assert routing["hsm_final_t_per_t_slab"] > 0.0
    assert routing["dsp_liquid_steel_input_t_per_t_coil"] > 0.0
    assert routing["dsp_final_product_horizon_cap_t"] > 0.0
    assert routing["imported_slab_max_t_h"] > 0.0
    assert abs(routing["imported_slab_horizon_cap_t"] - routing["imported_slab_max_t_h"] * 24) < 1e-9
    assert "eaf_dsp_share" not in routing


def test_origin_interface_has_separate_origin_balances_and_import_cap() -> None:
    tables = _load_tables()
    inputs = _build_c1_inputs(tables, horizon_hours_override=2, include_retained_bf_bof=True)
    model = _build_c1_model(
        inputs,
        enable_c1_retained_bf_bof_route=True,
        c1_retained_route_policy="quota_driven_topology",
        downstream_origin_routing=build_c1_uniform_import_routing(load_source_values(), horizon_hours=2),
    )
    assert hasattr(model, "bof_origin_route_balance")
    assert hasattr(model, "eaf_origin_route_balance")
    assert hasattr(model, "imported_slab_hourly_cap")
    assert hasattr(model, "imported_slab_horizon_cap")
    assert hasattr(model, "dsp_final_product_horizon_cap")
    assert hasattr(model, "hsm_origin_input_balance")
    assert not hasattr(model, "eaf_dsp_share_constraint")


def test_default_interface_remains_off() -> None:
    tables = _load_tables()
    inputs = _build_c1_inputs(tables, horizon_hours_override=2, include_retained_bf_bof=True)
    model = _build_c1_model(
        inputs,
        enable_c1_retained_bf_bof_route=True,
        c1_retained_route_policy="quota_driven_topology",
    )
    assert not hasattr(model, "bof_origin_route_balance")
