from __future__ import annotations

from pathlib import Path
import sys

from pyomo.environ import ConcreteModel, NonNegativeReals, RangeSet, Var


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c_unified_physical_modelbuilder import (
    _SALE_BREAKTHROUGH_NG_COMPONENTS,
    _install_sale_breakthrough_test,
    _sale_breakthrough_test_record,
)
from steel.s4_4c5p_phase5b_breakthrough_tests import (
    C0_CONFIGURATION,
    NG_FIELDS,
    _reference_metrics_by_replan,
)


def test_breakthrough_caps_bind_import_and_named_ng_without_capping_wag() -> None:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 1)
    model.gross_grid_import_mwh = Var(model.TIME, within=NonNegativeReals)
    model.wag_generator_electricity_mwh = Var(model.TIME, within=NonNegativeReals)
    for attribute in _SALE_BREAKTHROUGH_NG_COMPONENTS:
        setattr(model, attribute, Var(model.TIME, within=NonNegativeReals))
    for t in model.TIME:
        model.gross_grid_import_mwh[t].set_value(4.0)
        model.wag_generator_electricity_mwh[t].set_value(9.0)
        for attribute in _SALE_BREAKTHROUGH_NG_COMPONENTS:
            getattr(model, attribute)[t].set_value(1.0)

    context = _install_sale_breakthrough_test(
        model,
        {
            "mode": "phase5b_physical_wag_upper_bound_v1",
            "execution_hours": 2,
            "reference_metrics": {
                "gross_grid_import_mwh": 8.0,
                "named_ng_mwh_lhv": 12.0,
                "wag_generator_electricity_mwh": 10.0,
            },
        },
    )
    record = _sale_breakthrough_test_record(context)

    assert record["resource_caps_status"] == "pass"
    assert record["actual_metrics"]["wag_generator_electricity_mwh"] == 18.0
    assert model.phase5b_breakthrough_gross_import_cap.upper == 8.0
    assert model.phase5b_breakthrough_named_ng_cap.upper == 12.0


def test_comparator_reference_metrics_are_exactly_block_specific() -> None:
    rows = []
    for replan in range(7):
        row = {
            "configuration_id": C0_CONFIGURATION,
            "replan_index": replan,
            "gross_grid_import_mwh": str(replan + 1),
            "WAG_generator_electricity_mwh": "999",
            "WAG_generator_electricity_mwh_unrounded": str(replan + 2),
        }
        row.update({field: "1" for field in NG_FIELDS})
        rows.append(row)

    result = _reference_metrics_by_replan(rows)

    assert set(result) == {str(index) for index in range(7)}
    assert result["3"] == {
        "gross_grid_import_mwh": 4.0,
        "named_ng_mwh_lhv": float(len(NG_FIELDS)),
        "wag_generator_electricity_mwh": 5.0,
    }
