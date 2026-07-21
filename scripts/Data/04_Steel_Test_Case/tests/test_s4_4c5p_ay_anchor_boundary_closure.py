from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_ay_anchor_boundary_closure import _anchor_contract_rows, _identity_rows, _utility_map, _wag_activity_basis_rows


def _anchor(anchor_id: str, share: str = "-0.07") -> dict[str, str]:
    return {
        "anchor_id": anchor_id,
        "metric": "example",
        "model_value": "1.0",
        "anchor_value": "1.0",
        "unit": "PJ/y",
        "signed_residual": share,
        "signed_residual_share": share,
        "status": "comparable_with_caveat",
        "caveat": "test",
    }


def _utilities() -> dict[str, dict[str, str]]:
    return _utility_map([
        {"metric": "gross_electricity", "model_value": "4.0"},
        {"metric": "internal_WAG_generator_electricity_offset", "model_value": "1.0"},
        {"metric": "net_grid_import_after_internal_WAG_offset", "model_value": "3.0"},
        {"metric": "modelled_steam_15bar_demand", "model_value": "10.0"},
        {"metric": "modelled_steam_15bar_supply", "model_value": "10.0"},
        {"metric": "modelled_steam_15bar_unserved", "model_value": "0.0"},
        {"metric": "WAG_explicit_combustion_CO2", "model_value": "1.0"},
    ])


def test_anchor_contract_uses_strict_less_than_7_5_percent() -> None:
    pass_row = _anchor_contract_rows("case", [_anchor("c1_generator_wag_with_flare_10_6", "-0.0749")])[0]
    review_row = _anchor_contract_rows("case", [_anchor("c1_generator_wag_with_flare_10_6", "-0.075")])[0]
    assert pass_row["within_7_5pct"] == "yes"
    assert review_row["within_7_5pct"] == "no"


def test_partial_site_electricity_remains_reporting_only() -> None:
    row = _anchor_contract_rows("case", [_anchor("c1_official_total_site_electricity_17_8pj_missing")])[0]
    assert row["score_status"] == "reporting_only"
    assert row["comparability_status"] == "not_comparable_or_reporting_only"


def test_physical_identities_close_without_creating_residual_input() -> None:
    rows = _identity_rows("case", _utilities())
    assert all(row["status"] == "pass" for row in rows)


def test_wag_activity_difference_is_not_coefficient_target() -> None:
    current = [
        {"carrier": "BFG", "generation_MWh_LHV_y": str(2_000_000 / 3.6)},
        {"carrier": "COG", "generation_MWh_LHV_y": str(1_000_000 / 3.6)},
        {"carrier": "BOFG", "generation_MWh_LHV_y": str(500_000 / 3.6)},
    ]
    historical = [
        {"configuration": "C1_phase1", "carrier": "BFG", "generation_PJ_y": "1.0"},
        {"configuration": "C1_phase1", "carrier": "COG", "generation_PJ_y": "1.0"},
        {"configuration": "C1_phase1", "carrier": "BOFG", "generation_PJ_y": "0.5"},
    ]
    rows = _wag_activity_basis_rows("case", current, historical)
    assert rows[0]["comparison_status"] == "boundary_mismatch_not_a_coefficient_target"
