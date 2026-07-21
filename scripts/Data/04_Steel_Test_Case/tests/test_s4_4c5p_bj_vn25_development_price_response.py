from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    ClosedLoopFeasibilityError,
    _generator_unit_interface,
)
from steel.s4_4c5p_bj_vn25_development_price_response import (
    CONFIG_PATH,
    _case_definitions,
)
from steel.s4_4c_component_ontology import (
    load_generator_operating_mode_contract,
)


def test_generator_mode_contract_is_fail_closed_and_omits_unknown_features() -> None:
    modes = load_generator_operating_mode_contract()
    assert set(modes) == {
        "price_insensitive_reference",
        "development_price_responsive",
        "bounded_generator_sensitivity",
    }
    assert modes["development_price_responsive"]["vn25_electric_capacity_mw"] == "350"
    assert modes["development_price_responsive"]["hourly_price_response"] == "true"
    assert modes["price_insensitive_reference"]["hourly_price_response"] == "false"
    assert all(row["ij01_price_response"] == "false" for row in modes.values())
    assert all(row["export_allowed"] == "false" for row in modes.values())
    for row in modes.values():
        assert {
            row["minimum_load"],
            row["startup_shutdown"],
            row["ramp"],
            row["outage_schedule"],
            row["chp_steam_obligation"],
        } == {"omitted_not_zero"}


def test_four_cases_preserve_reference_then_add_only_governed_response_and_efficiency() -> None:
    base = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    cases = _case_definitions(base)
    assert [case["case_id"] for case in cases] == [
        "price_insensitive_reference",
        "development_price_responsive_flat",
        "development_price_responsive_step_price",
        "development_price_responsive_efficiency_0_34",
    ]
    assert cases[0]["overrides"]["price_series_id"] == "flat_central_reference_v1"
    assert cases[2]["overrides"]["price_series_id"] == "synthetic_vn25_break_even_step_v1"
    assert cases[3]["overrides"]["c1_generator_boundary"]["vn25_electricity_efficiency"] == 0.34


def test_generator_interface_adds_350_mw_cap_and_keeps_ij01_controlled() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config.update(
        {
            "generator_operating_mode": "development_price_responsive",
            "price_series_id": "synthetic_vn25_break_even_step_v1",
        }
    )
    interface = _generator_unit_interface(config, horizon_hours=168)
    assert interface is not None
    assert interface["vn25_electric_capacity_mw"] == 350.0
    assert interface["vn25_electricity_efficiency"] == 0.345
    assert interface["hourly_price_response"] is True
    assert interface["ij01_price_response"] is False
    assert interface["export_allowed"] is False
    assert interface["omitted_operational_features"] == (
        "minimum_load",
        "startup_shutdown",
        "ramp",
        "outage_schedule",
        "chp_steam_obligation",
    )


def test_price_insensitive_reference_rejects_an_hourly_step_series() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config["price_series_id"] = "synthetic_vn25_break_even_step_v1"
    with pytest.raises(ClosedLoopFeasibilityError, match="flat price series"):
        _generator_unit_interface(config, horizon_hours=168)
