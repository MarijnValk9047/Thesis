from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5e_source_backed_anchor_closure import (
    CONFIG_PATH,
    annual_anchor_comparisons,
    carrier_coverage,
    dynamic_source_service_accounts,
    generator_balances,
    load_config,
    load_source_contract,
)
from steel.s4_4c_unified_physical_modelbuilder import REPO_ROOT


CONTRACT = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/"
    "c5_phase5e_source_backed_anchor_contract/source_backed_annual_service_contract.csv"
)


def _rows() -> list[dict[str, object]]:
    return load_source_contract(CONTRACT)


def test_phase5e_replaces_anonymous_residual_with_independent_source_categories() -> None:
    rows = _rows()
    forbidden = ("anchor_minus_model", "model_residual", "calibration_plug")

    assert not any(
        token in str(row["quantity_origin"]).lower()
        for row in rows
        for token in forbidden
    )

    coverage = carrier_coverage(rows)
    assert len(coverage) == 6
    assert all(row["status"] == "pass" for row in coverage)
    assert all(float(row["named_share_fraction"]) >= 0.60 for row in coverage)
    assert all(float(row["unallocated_share_fraction"]) < 0.40 for row in coverage)

    c0_ng = next(
        row for row in coverage
        if row["configuration"] == "C0" and row["carrier"] == "natural_gas"
    )
    c1_ng = next(
        row for row in coverage
        if row["configuration"] == "C1" and row["carrier"] == "natural_gas"
    )
    assert c0_ng["primary_total"] == pytest.approx(12.5)
    assert c0_ng["named_source_backed_value"] == pytest.approx(12.5)
    assert c1_ng["primary_total"] == pytest.approx(46.7)
    assert c1_ng["named_source_backed_value"] == pytest.approx(46.7)


def test_phase5e_all_primary_annual_accounts_close_within_five_percent() -> None:
    comparisons = annual_anchor_comparisons(_rows(), relative_tolerance=0.05)

    assert comparisons
    assert all(row["status"] == "pass" for row in comparisons)
    assert all(float(row["absolute_relative_error"]) <= 0.05 for row in comparisons)
    assert all(row["enters_dispatch"] is False for row in comparisons)
    assert all(row["enters_cost"] is False for row in comparisons)


def test_phase5e_generator_balance_recovers_wag_electricity_without_forcing_output() -> None:
    balances = generator_balances(_rows(), {"C0": 2.528, "C1": 1.23})
    by_configuration = {row["configuration"]: row for row in balances}

    assert all(row["status"] == "pass" for row in balances)
    assert by_configuration["C0"]["fuel_identity_residual_pj_y"] == pytest.approx(0.0)
    assert by_configuration["C0"]["energy_identity_residual_pj_y"] == pytest.approx(0.0)
    assert by_configuration["C0"]["fuel_proportional_wag_electricity_twh_y"] == pytest.approx(
        9.8 * (23.6 / 25.5) / 3.6
    )
    assert by_configuration["C1"]["fuel_proportional_wag_electricity_twh_y"] == pytest.approx(
        5.9 * (10.3 / 14.1) / 3.6
    )
    assert by_configuration["C0"]["attribution_role"] == (
        "derived_reporting_indicator_not_dispatch_constraint"
    )


def test_phase5e_config_keeps_source_accounts_out_of_dispatch_and_retires_phase5d_promotion() -> None:
    config = load_config(CONFIG_PATH)
    policy = config["phase5e"]["policy"]

    assert policy["annual_service_accounts_enter_dispatch"] is False
    assert policy["annual_service_accounts_enter_cost"] is False
    assert policy["external_export_allowed"] is False
    assert policy["parameter_calibration_performed"] is False
    assert policy["phase5d_policy_promoted"] is False
    assert config["phase5e"]["gates"]["primary_anchor_relative_tolerance"] == pytest.approx(0.05)


def test_phase5e_dynamic_service_accounts_are_partitions_not_additive_plugs() -> None:
    artifact = {
        "hourly": [
            {
                "configuration_id": "C0_current_BF_BOF_reference",
                "generator_named_ng_mwh": "0",
                "NG_to_HSM_mwh": "0",
                "NG_to_PEFA_malerij_mwh": "0",
                "NG_to_PEFA_branderij_mwh": "0",
            },
            {
                "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "DRP_named_NG_mwh": str(9.9 / 3.6),
                "EAF_named_NG_mwh": "0",
                "generator_named_ng_mwh": "0",
            },
        ]
    }

    accounts = dynamic_source_service_accounts("test-period", artifact, _rows())

    assert accounts
    assert all(row["quantity_role"] == "annual_account_partition_not_additive_to_optimizer" for row in accounts)
    assert all(row["enters_dispatch"] is False for row in accounts)
    assert all(row["enters_cost"] is False for row in accounts)
    c1_dri = next(
        row for row in accounts
        if row["configuration"] == "C1"
        and row["carrier"] == "natural_gas"
        and row["service_component"] == "DRI_factory"
    )
    assert c1_dri["source_backed_annual_value"] == pytest.approx(27.7)
    assert c1_dri["dynamic_overlap_annual_equivalent"] is not None


def test_phase5e_canonical_anchor_rows_have_exact_mer_locators() -> None:
    register = (
        REPO_ROOT
        / "data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/"
        "c5_model_anchor_evidence_register.csv"
    )
    with register.open(encoding="utf-8", newline="") as handle:
        rows = {row["anchor_id"]: row for row in csv.DictReader(handle)}

    expected = {
        "c0_full_site_ng_12_5pj_missing": ("12.5", "WD07 Table 4.2 report p17 / PDF p23"),
        "c1_full_site_ng_46_5pj_missing": ("46.7", "WD07 Table 6.2 report p65 / PDF p71"),
        "c0_official_scope1_12_6_missing": ("12.6", "WD07 Table 4.3 report p18 / PDF p24"),
        "c1_official_scope1_8_3_missing": ("8.3", "WD07 Table 6.1 report p63 / PDF p69"),
    }
    for anchor_id, (value, locator) in expected.items():
        row = rows[anchor_id]
        assert row["raw_value"] == value
        assert row["source_locator"] == locator
        assert row["evidence_tier"] == "Tier A"
        assert row["use_in_primary_score"] == "yes"
        assert row["review_status"] == "accepted"
