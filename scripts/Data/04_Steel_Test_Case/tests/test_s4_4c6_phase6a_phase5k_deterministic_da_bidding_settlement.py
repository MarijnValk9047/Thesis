from __future__ import annotations

from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_phase6a_phase5k_deterministic_da_bidding_settlement import (
    load_config,
    load_phase5k_realised_price_gap_supplement,
)
from steel.s4_4c6_phase6a_deterministic_da_bidding_settlement import settle_hour


def test_phase6a_phase5k_scope_keeps_residuals_fixed_and_non_ets() -> None:
    policy = load_config()["phase6a_phase5k"]["policy"]
    assert policy["electricity_baseload_fixed"] is True
    assert policy["common_ng_site_service_fixed"] is True
    assert policy["residual_co2_reporting_only"] is True
    assert policy["residual_co2_in_cost_or_ets"] is False
    assert policy["stochastic_scenarios_allowed"] is False


def test_phase6a_phase5k_settlement_identity() -> None:
    result = settle_hour(bid_quantity_mwh=125.0, realised_price_eur_per_mwh=82.5)
    assert result["settled_quantity_mwh"] == 125.0
    assert result["electricity_procurement_cost_eur"] == 10312.5
    assert result["imbalance_mwh"] == 0.0


def test_phase6a_phase5k_realised_gap_supplement_is_settlement_only() -> None:
    phase = load_config()["phase6a_phase5k"]
    patch = load_phase5k_realised_price_gap_supplement(STEEL_ROOT.parents[2] / phase["realised_price_gap_supplement"])
    assert set(patch.values()) == {95.6}
    assert len(patch) == 3
