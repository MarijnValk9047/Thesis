from __future__ import annotations

from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5c_source_mechanism_adjudication import (
    blast_furnace_capacity_metrics,
    inventory_change_price_correlation,
    pearson_correlation,
)


def test_dri_source_metric_uses_hourly_inventory_change_not_level() -> None:
    inventories = [0.0, 3.0, 4.0, 8.0, 10.0]
    prices = [99.0, 30.0, 10.0, 40.0, 20.0]

    corrected = inventory_change_price_correlation(inventories, prices)
    incorrect_level_metric = pearson_correlation(inventories, prices)

    assert corrected == pytest.approx(1.0)
    assert incorrect_level_metric != pytest.approx(corrected)


def test_bf_comparison_normalises_each_furnace_by_its_own_capacity() -> None:
    bf6 = blast_furnace_capacity_metrics([50.0, 100.0], 100.0)
    bf7 = blast_furnace_capacity_metrics([100.0, 200.0], 200.0)

    assert bf6["executed_input_t"] < bf7["executed_input_t"]
    assert bf6["capacity_utilisation_fraction"] == pytest.approx(0.75)
    assert bf7["capacity_utilisation_fraction"] == pytest.approx(0.75)
    assert bf6["share_hours_at_maximum"] == pytest.approx(0.5)
    assert bf7["share_hours_at_maximum"] == pytest.approx(0.5)
