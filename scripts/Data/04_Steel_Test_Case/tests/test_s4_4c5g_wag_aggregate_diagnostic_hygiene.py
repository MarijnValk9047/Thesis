from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c5g_wag_aggregate_diagnostic_hygiene import (  # noqa: E402
    C5G_DIR,
    WAG_CARRIERS,
    WAG_TOL_MWH,
    run_s4_4c5g_wag_aggregate_diagnostic_hygiene,
)
from steel.s4_4c5f_coking_plant_minimal_parameterisation import C1  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float:
    return float(value or 0.0)


@pytest.fixture(scope="module")
def c5g_outputs() -> Path:
    run_s4_4c5g_wag_aggregate_diagnostic_hygiene()
    return C5G_DIR


def test_c5g_required_outputs_exist_and_parse(c5g_outputs: Path):
    required = [
        "s4_4c5g_stage_gate.json",
        "s4_4c5g_run_registry.csv",
        "s4_4c5g_wag_aggregate_invariant.csv",
        "s4_4c5g_compact_table_for_chat.csv",
        "s4_4c5g_compact_aggregate_reconciliation.csv",
        "s4_4c5g_wag_generation_consumption_by_plant.csv",
        "s4_4c5g_cog_wag_balance_by_plant.csv",
        "s4_4c5g_cog_self_use_surplus_dashboard.csv",
        "s4_4c5g_lhv_consistency_checks.csv",
        "s4_4c5g_kgf_split_diagnostics.csv",
    ]
    for filename in required:
        path = c5g_outputs / filename
        assert path.exists()
        if path.suffix == ".csv":
            assert _read_csv(path)

    gate = json.loads((c5g_outputs / "s4_4c5g_stage_gate.json").read_text(encoding="utf-8"))
    assert gate["decision"] == "pass_development_wag_aggregate_diagnostic_hygiene"
    assert gate["aggregate_invariant_fail_count"] == 0
    assert gate["compact_aggregate_reconciliation_fail_count"] == 0
    assert gate["lhv_consistency_fail_count"] == 0


def test_c5g_wag_aggregate_invariant_closes_raw_and_site(c5g_outputs: Path):
    rows = _read_csv(c5g_outputs / "s4_4c5g_wag_aggregate_invariant.csv")
    assert len(rows) == 8
    assert {(row["configuration"], row["horizon_hours"], row["scale_basis"]) for row in rows}

    for row in rows:
        generated = _num(row["total_WAG_generated_MWh_y"])
        direct = _num(row["total_WAG_direct_use_MWh_y"])
        boiler = _num(row["total_WAG_boiler_use_MWh_y"])
        vattenfall = _num(row["total_WAG_vattenfall_use_MWh_y"])
        flared = _num(row["total_WAG_flared_MWh_y"])
        other = _num(row["total_WAG_explicit_other_sink_or_loss_MWh_y"])
        accounted = _num(row["total_WAG_accounted_MWh_y"])
        assert generated == pytest.approx(direct + boiler + vattenfall + flared + other)
        assert accounted == pytest.approx(direct + boiler + vattenfall + flared + other)
        assert abs(_num(row["balance_error_MWh_y"])) <= WAG_TOL_MWH
        assert flared <= generated + WAG_TOL_MWH
        assert row["status"] == "pass"
        assert row["red_flags"] == ""


def test_c5g_compact_wag_rows_match_aggregate_invariant(c5g_outputs: Path):
    aggregate = _read_csv(c5g_outputs / "s4_4c5g_wag_aggregate_invariant.csv")
    compact = _read_csv(c5g_outputs / "s4_4c5g_compact_table_for_chat.csv")
    compact_by_key = {(row["configuration"], row["horizon_hours"], row["plant"]): row for row in compact}

    for raw_row in [row for row in aggregate if row["scale_basis"] == "raw"]:
        site_row = next(
            row
            for row in aggregate
            if row["configuration"] == raw_row["configuration"]
            and row["horizon_hours"] == raw_row["horizon_hours"]
            and row["scale_basis"] == "site_scaled"
        )
        key_base = (raw_row["configuration"], raw_row["horizon_hours"])
        flaring = compact_by_key[(*key_base, "flaring")]
        assert flaring["main_product"] == "WAG_flared_MWh_LHV_y_same_basis"
        assert _num(flaring["main_product_raw_t_y"]) == pytest.approx(_num(raw_row["total_WAG_flared_MWh_y"]))
        assert _num(flaring["main_product_site_t_y"]) == pytest.approx(_num(site_row["total_WAG_flared_MWh_y"]))

        total = compact_by_key[(*key_base, "WAG_TOTAL_ALL_GENERATED")]
        assert _num(total["main_product_raw_t_y"]) == pytest.approx(_num(raw_row["total_WAG_generated_MWh_y"]))
        assert _num(total["main_product_site_t_y"]) == pytest.approx(_num(site_row["total_WAG_generated_MWh_y"]))
        assert _num(flaring["main_product_raw_t_y"]) <= _num(total["main_product_raw_t_y"]) + WAG_TOL_MWH
        assert _num(flaring["main_product_site_t_y"]) <= _num(total["main_product_site_t_y"]) + WAG_TOL_MWH

        for carrier in WAG_CARRIERS:
            row = compact_by_key[(*key_base, f"WAG_TOTAL_{carrier}_GENERATED")]
            assert row["main_product"] == "WAG_generated_MWh_LHV_y_same_basis"
            assert _num(row["main_product_raw_t_y"]) == pytest.approx(_num(raw_row[f"{carrier}_generated_MWh_y"]))
            assert _num(row["main_product_site_t_y"]) == pytest.approx(_num(site_row[f"{carrier}_generated_MWh_y"]))

    reconciliation = _read_csv(c5g_outputs / "s4_4c5g_compact_aggregate_reconciliation.csv")
    assert all(row["status"] == "pass" for row in reconciliation)


def test_c5g_preserves_c1_topology_and_kgf_cog_surplus(c5g_outputs: Path):
    compact = _read_csv(c5g_outputs / "s4_4c5g_compact_table_for_chat.csv")
    c1_24 = [row for row in compact if row["configuration"] == C1 and row["horizon_hours"] == "24"]
    kgf2 = next(row for row in c1_24 if row["plant"] == "KGF2")
    bf7 = next(row for row in c1_24 if row["plant"] == "BF7")
    assert kgf2["active"] == "False"
    assert _num(kgf2["main_product_site_t_y"]) == 0.0
    assert bf7["active"] == "False"
    assert _num(bf7["main_product_site_t_y"]) == 0.0

    cog = _read_csv(c5g_outputs / "s4_4c5g_cog_wag_balance_by_plant.csv")
    kgf_rows = [row for row in cog if row["plant_id"] in {"KGF1", "KGF2"}]
    assert kgf_rows
    for row in kgf_rows:
        gross = _num(row["gross_generated_MWh_LHV_y"])
        self_use = _num(row["self_used_MWh_LHV_y"])
        surplus = _num(row["surplus_to_network_MWh_LHV_y"])
        assert gross == pytest.approx(self_use + surplus)
        assert surplus >= 0.0


def test_c5g_lhv_consistency_remains_pass(c5g_outputs: Path):
    lhv = _read_csv(c5g_outputs / "s4_4c5g_lhv_consistency_checks.csv")
    assert lhv
    assert all(row["status"] == "pass" for row in lhv)
