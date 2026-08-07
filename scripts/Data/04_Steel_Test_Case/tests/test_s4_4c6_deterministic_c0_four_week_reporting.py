from __future__ import annotations

import pandas as pd
import pytest

from steel.s4_4c6_deterministic_c0_four_week_reporting import (
    CENTRAL_PRICES,
    _economic_record,
)
from steel.s4_4c6_deterministic_c0_temporal_validation import (
    load_c0_validation_config,
)


def test_four_week_contract_is_explicit_and_market_matrix_stays_closed():
    contract = load_c0_validation_config()["four_week_run_contract"]
    assert contract["regimes"] == [
        "typical_winter",
        "high_prices",
        "high_volatility",
        "typical_summer",
    ]
    assert contract["four_example_weeks_authorized"] is True
    assert contract["full_four_week_market_matrix_authorized"] is False


def test_economic_reporting_uses_explicit_denominators():
    rows = []
    for strategy in ("price_insensitive", "perfect_foresight_D"):
        rows.append(
            {
                "configuration": "C0",
                "strategy_id": strategy,
                "net_grid_import_mwh": 2.0,
                "internal_generation_mwh": 1.0,
                "electricity_price_eur_per_mwh": 100.0,
                "imported_pellets_t": 1.0,
                "external_bf_pellets_to_bf_t": 1.0,
                "external_dr_pellets_to_drp_t": 0.0,
                "drp_pellet_input_t": 0.0,
                "final_product_t": 2.0,
                "total_named_ng_procurement_mwh": 1.0,
                "coking_coal_input_t": 1.0,
                "pci_input_t": 1.0,
                "direct_co2_reporting_t": 1.0,
            }
        )
    result = _economic_record(
        pd.DataFrame(rows),
        configuration="C0",
        strategy="perfect_foresight_D",
        regime="typical_winter",
        represented_objective=1_000.0,
    )
    assert result["total_production_cost_eur"] == pytest.approx(1_000.0)
    assert result["total_imported_pellets_cost_eur"] == pytest.approx(
        2.0 * CENTRAL_PRICES["imported_bf_pellets_eur_per_t"]
    )
    assert result["average_electricity_price_paid_eur_per_mwh"] == pytest.approx(
        100.0
    )
    assert result["average_price_denominator"] == "purchased_grid_MWh"
