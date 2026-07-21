from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_bi_pre_dam_operational_boundary_closure import (
    CONFIG_PATH,
    CONFIGURATIONS,
    _case_overrides,
    build_wag_anchor_reconciliation,
    build_wag_source_to_sink_ledger,
)


def _hour(configuration: str) -> dict[str, object]:
    row: dict[str, object] = {
        "configuration_id": configuration,
        "BFG_generated_mwh": 10.0,
        "COG_generated_mwh": 5.0,
        "BOFG_generated_mwh": 3.0,
        "BFG_to_BF_hot_stove_mwh": 2.0,
        "BFG_to_KGF1_mwh": 0.0,
        "BFG_to_HSM_mwh": 1.0,
        "BFG_to_boiler_mwh": 1.0,
        "COG_to_KGF1_mwh": 1.0,
        "COG_to_KGF2_mwh": 1.0,
        "COG_to_sinter_mwh": 0.5,
        "COG_to_HSM_mwh": 0.5,
        "COG_to_PEFA_branderij_mwh": 0.5,
        "COG_to_boiler_mwh": 0.5,
        "BOFG_to_HSM_mwh": 0.5,
        "BOFG_to_PEFA_malerij_mwh": 0.5,
        "BOFG_to_boiler_mwh": 0.5,
        "BFG_flared_mwh": 0.0,
        "COG_flared_mwh": 0.0,
        "BOFG_flared_mwh": 0.0,
        "BFG_balance_residual_mwh": 0.0,
        "COG_balance_residual_mwh": 0.0,
        "BOFG_balance_residual_mwh": 0.0,
    }
    if configuration.startswith("C1_"):
        row.update(
            {
                "BFG_to_VN25_mwh": 6.0,
                "BFG_to_IJ01_mwh": 0.0,
                "COG_to_VN25_mwh": 1.0,
                "COG_to_IJ01_mwh": 0.0,
                "BOFG_to_VN25_mwh": 1.5,
                "BOFG_to_IJ01_mwh": 0.0,
            }
        )
    else:
        row.update(
            {
                "BFG_to_vattenfall_mwh": 6.0,
                "COG_to_vattenfall_mwh": 1.0,
                "BOFG_to_vattenfall_mwh": 1.5,
            }
        )
    return row


def test_same_run_wag_ledger_preserves_carriers_and_signed_identity() -> None:
    hourly = [
        _hour(configuration)
        for configuration in CONFIGURATIONS
        for _ in range(168)
    ]
    ledger = build_wag_source_to_sink_ledger(hourly)

    assert {row["carrier"] for row in ledger} == {"BFG", "COG", "BOFG"}
    assert not any(
        token in str(row).lower()
        for row in ledger
        for token in ("aggregate_wag", "mixed_wag", "c5p_k")
    )
    for configuration in CONFIGURATIONS:
        for carrier in ("BFG", "COG", "BOFG"):
            rows = [
                row
                for row in ledger
                if row["configuration_id"] == configuration
                and row["carrier"] == carrier
            ]
            source = sum(
                float(row["executed_mwh_lhv"])
                for row in rows
                if row["flow_role"] == "source"
            )
            use = sum(
                float(row["executed_mwh_lhv"])
                for row in rows
                if row["flow_role"] in {"sink", "flare"}
            )
            residual = sum(
                float(row["executed_mwh_lhv"])
                for row in rows
                if row["flow_role"] == "accounting_residual"
            )
            assert source - use - residual == pytest.approx(0.0)

    anchors = build_wag_anchor_reconciliation(ledger)
    assert any(
        row["anchor_id"] == "c1_generator_wag_with_flare_10_6"
        and row["forced_dispatch_target_active"] == "no"
        for row in anchors
    )


def test_pre_dam_run_budget_is_one_central_plus_two_focused_diagnostics() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    cases = _case_overrides(config)

    assert [case["case_id"] for case in cases] == [
        "corrected_central",
        "electricity_high",
        "vn25_efficiency_low_0_34",
    ]
    assert cases[2]["overrides"]["c1_generator_boundary"][
        "vn25_electricity_efficiency"
    ] == 0.34
    assert config["rolling_production_progress_state_enabled"] is True
    assert config["production_envelope_tolerance_fraction"] == 0.005
