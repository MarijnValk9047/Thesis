from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_phase6a_deterministic_da_bidding_settlement import (
    CONFIG_PATH,
    Phase6AGateError,
    load_config,
    load_da_contract,
    load_realised_price_gap_supplement,
    settle_hour,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


CONTRACT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c6_phase6a_deterministic_da_contract/deterministic_da_bid_settlement_contract.csv"
PRICE_GAP = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c6_phase6a_deterministic_da_contract/realised_price_gap_supplement.csv"
ELECTRICITY = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_phase5i_electricity_only_contract/electricity_only_baseload_contract.csv"


def test_phase6a_contract_separates_timing_and_oracle() -> None:
    rows = load_da_contract(CONTRACT)
    assert rows[0]["information_set"] == "forecast_origin_information_only"
    assert rows[0]["settlement_price_basis"] == "realised_DA_y_true"
    assert rows[1]["physical_price_basis"] == "flat_80_EUR_per_MWh"
    assert rows[2]["oracle"] == "true"
    assert rows[2]["bid_type"] == "not_submitted_counterfactual"


def test_settlement_identity_and_zero_deterministic_imbalance() -> None:
    result = settle_hour(bid_quantity_mwh=12.5, realised_price_eur_per_mwh=64.0)
    assert result["cleared_quantity_mwh"] == 12.5
    assert result["settled_quantity_mwh"] == 12.5
    assert result["imbalance_mwh"] == 0.0
    assert result["electricity_procurement_cost_eur"] == 800.0


def test_purchase_bid_cannot_be_export() -> None:
    with pytest.raises(Phase6AGateError, match="cannot be negative"):
        settle_hour(bid_quantity_mwh=-0.1, realised_price_eur_per_mwh=40.0)


def test_solver_noise_is_clamped_without_authorising_export() -> None:
    result = settle_hour(
        bid_quantity_mwh=-8.0477e-8,
        realised_price_eur_per_mwh=40.0,
        negative_tolerance_mwh=1e-4,
    )
    assert result["settled_quantity_mwh"] == 0.0
    assert result["electricity_procurement_cost_eur"] == 0.0


def test_baseload_is_fixed_and_promoted() -> None:
    with ELECTRICITY.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    electricity = [row for row in rows if row["residual_family"] == "electricity"]
    assert {row["selected_share"] for row in electricity} == {"0.1"}
    assert {row["price_responsive"] for row in electricity} == {"false"}
    assert {row["status"] for row in electricity} == {"heldout_validated_promoted"}
    assert {row["executable"] for row in electricity} == {"true"}


def test_phase6a_scope_excludes_later_market_layers() -> None:
    config = load_config(CONFIG_PATH)
    policy = config["phase6a"]["policy"]
    for key in ("stochastic_scenarios_allowed", "cvar_allowed", "mfrr_allowed", "ets_allowed", "product_revenue_allowed", "export_allowed"):
        assert policy[key] is False
    assert policy["realised_price_use"] == "settlement_and_isolated_oracle_only"
    assert policy["electricity_baseload_price_responsive"] is False


def test_realised_price_gap_supplement_is_exact_and_oracle_only() -> None:
    patch = load_realised_price_gap_supplement(PRICE_GAP)
    assert patch == {
        "2025-07-13T11:00:00+00:00": 0.0,
        "2025-07-13T12:00:00+00:00": 0.0,
        "2025-07-13T13:00:00+00:00": 0.0,
    }


def test_phase6a_reuses_frozen_period_contract_and_phase5i_gate() -> None:
    config = load_config(CONFIG_PATH)["phase6a"]
    assert config["expected_period_count"] == 4
    assert config["expected_phase5i_models_reused"] == 56
    assert config["expected_new_benchmark_models"] == 112
    assert config["expected_evaluated_models"] == 168
    assert "phase5h_four_residual_contract/fresh_held_out_period_contract.csv" in config["held_out_contract"]
    assert "phase5i_electricity_only_heldout_freeze" in config["phase5i_checkpoint"]
