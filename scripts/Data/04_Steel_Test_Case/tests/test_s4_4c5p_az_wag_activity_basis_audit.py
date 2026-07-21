from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_az_wag_activity_basis_audit import build_activity_reconciliation


def test_historical_activity_is_back_calculated_without_factor_tuning() -> None:
    active = [
        {"carrier": "BFG", "source_activity_basis": "t_hot_metal/y", "source_activity_t_y": "100", "generation_MWh_LHV_y": "200", "implied_generation_MWh_LHV_per_activity_t": "2"},
        {"carrier": "COG", "source_activity_basis": "t_dry_coal/y", "source_activity_t_y": "100", "generation_MWh_LHV_y": "300", "implied_generation_MWh_LHV_per_activity_t": "3"},
        {"carrier": "BOFG", "source_activity_basis": "t_liquid_steel/y", "source_activity_t_y": "100", "generation_MWh_LHV_y": "400", "implied_generation_MWh_LHV_per_activity_t": "4"},
    ]
    old = [
        {"configuration": "C1_phase1_BF_BOF_plus_DRP_EAF", "carrier": "BFG", "generation_PJ_y": "0.00036"},
        {"configuration": "C1_phase1_BF_BOF_plus_DRP_EAF", "carrier": "COG", "generation_PJ_y": "0.00036"},
        {"configuration": "C1_phase1_BF_BOF_plus_DRP_EAF", "carrier": "BOFG", "generation_PJ_y": "0.00036"},
    ]
    drivers = {
        "BFG": (100.0, "t_hot_metal/y", "test"),
        "COG": (100.0, "t_dry_coal/y", "test"),
        "BOFG": (100.0, "t_liquid_steel/y", "test"),
    }
    rows = build_activity_reconciliation(active, old, drivers)
    assert {row["coefficient_action"] for row in rows} == {"do_not_tune"}
    assert all(row["comparison_status"] == "not_comparable_different_ledger_point" for row in rows)
    assert all(row["driver_comparison"] == "within_5pct" for row in rows)
