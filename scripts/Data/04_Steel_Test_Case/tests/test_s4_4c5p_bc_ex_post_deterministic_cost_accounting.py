from __future__ import annotations

import ast
import csv
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path
import sys

import pytest

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel import s4_4c5p_bc_ex_post_deterministic_cost_accounting as accounting
from steel.s4_4c_component_ontology import (
    load_external_supply_costs,
    load_future_cost_boundary_contract,
)


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def accounted_run() -> Path:
    output = (
        accounting.REPO_ROOT
        / "data"
        / "03_Optimisation"
        / "runs"
        / f"_test_s2_ex_post_cost_{os.getpid()}"
    )
    if output.exists():
        shutil.rmtree(output)
    result = accounting.run_ex_post_cost_accounting(output_directory=output)
    assert result["summary"]["status"] == "pass"
    try:
        yield output
    finally:
        shutil.rmtree(output, ignore_errors=True)


def test_grid_cost_uses_net_grid_import_only(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    physical = _csv(accounting.DEFAULT_PHYSICAL_PARENT / "executed_hourly.csv")
    booked = defaultdict(float)
    solved = defaultdict(float)
    for row in ledger:
        if row["price_id"] == "grid_electricity_flat_nl":
            booked[row["configuration"]] += float(row["solved_quantity"])
    for row in physical:
        solved[row["configuration_id"]] += float(row["net_grid_import_mwh"])
    assert booked == pytest.approx(solved)


def test_gross_and_named_electricity_buckets_are_not_priced(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    electricity = [row for row in ledger if row["carrier_or_material"] == "electricity"]
    assert {row["flow_id"] for row in electricity} == {"C0_EL_GRID", "C1_EL_GRID"}


def test_named_ng_consumers_are_counted_exactly_once(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    rows = [row for row in ledger if row["price_id"] == "natural_gas_ttf_proxy"]
    keys = {
        (row["configuration"], row["timestamp_or_hour"], row["flow_id"], row["component"])
        for row in rows
    }
    assert len(keys) == len(rows)
    assert len({(row["configuration"], row["timestamp_or_hour"]) for row in rows}) == 336


def test_residual_electricity_and_ng_contribute_zero_cost(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    excluded = _csv(accounted_run / "excluded_cost_boundary.csv")
    assert not any("RESIDUAL" in row["flow_id"] for row in ledger)
    residuals = [
        row
        for row in excluded
        if "RESIDUAL" in row["flow_id"]
        or row["flow_id"] == "PHYSICAL_REPORTING_BOUNDARY_GAP"
    ]
    assert residuals and all(float(row["cost_eur"]) == 0.0 for row in residuals)


def test_internal_carriers_steam_and_generation_have_zero_direct_cost(
    accounted_run: Path,
) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    assert not {
        "BFG",
        "COG",
        "BOFG",
        "WAG",
        "WAG_and_NG",
        "steam",
    }.intersection(row["carrier_or_material"] for row in ledger)


def test_imported_slab_uses_actual_executed_quantity_not_cap(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    physical = _csv(accounting.DEFAULT_PHYSICAL_PARENT / "executed_hourly.csv")
    booked = sum(
        float(row["solved_quantity"])
        for row in ledger
        if row["price_id"] == "imported_slab_proxy"
    )
    executed = sum(
        float(row["C1_imported_slab_to_HSM_t_h"])
        for row in physical
        if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
    )
    assert booked == pytest.approx(executed)


def test_imported_slab_keeps_zero_upstream_site_burdens(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    slab = [row for row in ledger if row["price_id"] == "imported_slab_proxy"]
    assert slab
    assert {row["flow_id"] for row in slab} == {"C1_MAT_IMPORTED_SLAB"}
    assert {row["component"] for row in slab} == {"external_slab_boundary"}
    assert {row["carrier_or_material"] for row in slab} == {"imported_slab"}


def test_price_triplets_exist_and_only_central_is_active() -> None:
    rows = load_external_supply_costs()
    for price_id in accounting.ACTIVE_PROCUREMENT_PRICE_IDS:
        family = [row for row in rows if row["price_id"] == price_id]
        assert {row["scenario_id"] for row in family} == {
            "development_low",
            "development_central",
            "development_high",
        }
        assert [
            row["scenario_id"]
            for row in family
            if row["model_use_status"] == "active_fixed_reference_procurement"
        ] == ["development_central"]


def test_every_active_quantity_and_price_unit_is_compatible() -> None:
    rows = [
        row
        for row in load_future_cost_boundary_contract()
        if row["accounting_enabled"] == "true"
    ]
    prices = {
        (row["price_id"], row["scenario_id"]): row
        for row in load_external_supply_costs()
    }
    assert rows
    assert all(row["unit_compatibility_status"] == "compatible" for row in rows)
    assert all(
        row["price_unit"]
        == prices[(row["price_id"], row["price_scenario_id"])]["unit"]
        for row in rows
    )


def test_component_costs_sum_to_configuration_total(accounted_run: Path) -> None:
    components = _csv(accounted_run / "cost_summary_by_component.csv")
    summaries = _csv(accounted_run / "cost_summary_by_configuration.csv")
    component_total = defaultdict(float)
    for row in components:
        component_total[row["configuration"]] += float(row["cost_eur"])
    assert component_total == pytest.approx(
        {
            row["configuration"]: float(row["total_represented_procurement_cost_eur"])
            for row in summaries
        }
    )


def test_route_costs_sum_to_configuration_total(accounted_run: Path) -> None:
    routes = _csv(accounted_run / "cost_summary_by_route.csv")
    summaries = _csv(accounted_run / "cost_summary_by_configuration.csv")
    route_total = defaultdict(float)
    for row in routes:
        route_total[row["configuration"]] += float(row["cost_eur"])
    assert route_total == pytest.approx(
        {
            row["configuration"]: float(row["total_represented_procurement_cost_eur"])
            for row in summaries
        }
    )


def test_all_enabled_external_procurement_flows_are_booked(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    expected = {
        row["flow_id"]
        for row in load_future_cost_boundary_contract()
        if row["accounting_enabled"] == "true"
    }
    assert {row["flow_id"] for row in ledger} == expected
    assert {
        "coking_coal",
        "PCI",
        "iron_ore",
        "DR_pellets",
        "scrap",
    }.issubset({row["carrier_or_material"] for row in ledger})


def test_c0_and_c1_are_reported_separately(accounted_run: Path) -> None:
    rows = _csv(accounted_run / "cost_summary_by_configuration.csv")
    assert {row["configuration"] for row in rows} == set(accounting.EXPECTED_CONFIGURATIONS)


def test_only_executed_24_hour_blocks_are_booked(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    grid = [
        row
        for row in ledger
        if row["flow_id"] in {"C0_EL_GRID", "C1_EL_GRID"}
    ]
    counts = defaultdict(int)
    for row in grid:
        counts[(row["configuration"], int(row["execution_block"]))] += 1
    assert len(counts) == 14
    assert set(counts.values()) == {24}


def test_overlapping_planning_horizons_are_not_summed(accounted_run: Path) -> None:
    ledger = _csv(accounted_run / "cost_flow_ledger.csv")
    for configuration in accounting.EXPECTED_CONFIGURATIONS:
        hours = {
            int(row["timestamp_or_hour"])
            for row in ledger
            if row["configuration"] == configuration
            and row["flow_id"] in {"C0_EL_GRID", "C1_EL_GRID"}
        }
        assert hours == set(range(168))


def test_reference_validation_output_cannot_emit_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    original = accounting._read_json

    def reference_summary(path: Path) -> dict[str, object]:
        payload = original(path)
        if path.name == "run_summary.json":
            payload["execution_mode"] = "reference_validation"
        return payload

    monkeypatch.setattr(accounting, "_read_json", reference_summary)
    with pytest.raises(accounting.ExPostCostAccountingError, match="Reference-validation"):
        accounting._validate_parent(accounting.DEFAULT_PHYSICAL_PARENT)


def test_physical_builder_constraints_and_objective_are_unchanged(accounted_run: Path) -> None:
    manifest = json.loads((accounted_run / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["physical_builder_sha256"] == accounting._sha256(
        accounting.PHYSICAL_BUILDER_PATH
    )
    assert accounting.PHYSICAL_BUILDER_PATH.name not in Path(accounting.__file__).read_text(
        encoding="utf-8"
    ).replace(
        '"s4_4c_unified_physical_modelbuilder.py"', ""
    )


def test_prices_are_not_hardcoded_in_python() -> None:
    active_values = {
        float(row["value"])
        for row in load_external_supply_costs()
        if row["model_use_status"] == "active_fixed_reference_procurement"
    }
    tree = ast.parse(Path(accounting.__file__).read_text(encoding="utf-8"))
    numeric_constants = {
        float(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }
    assert active_values.isdisjoint(numeric_constants)


def test_accepted_physical_guardrails_and_fingerprint_are_unchanged(
    accounted_run: Path,
) -> None:
    checks = _csv(accounting.DEFAULT_PHYSICAL_PARENT / "validation_checks.csv")
    manifest = json.loads((accounted_run / "input_manifest.json").read_text(encoding="utf-8"))
    fingerprint, files = accounting._fingerprint_parent(accounting.DEFAULT_PHYSICAL_PARENT)
    assert checks and all(row["status"] == "pass" for row in checks)
    assert manifest["physical_parent_fingerprint_sha256"] == fingerprint
    assert manifest["physical_parent_files"] == files
