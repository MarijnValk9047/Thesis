from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from pyomo.environ import ConcreteModel, Constraint, NonNegativeReals, RangeSet, Var, value


TEST_CASE_DIR = Path(__file__).resolve().parents[1]
if str(TEST_CASE_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_DIR))

from steel.s4_4c_unified_physical_modelbuilder import (  # noqa: E402
    DEFAULT_BUILD_AUDIT_CSV_PATH,
    DEFAULT_CONSTRAINT_AUDIT_CSV_PATH,
    DEFAULT_HOURLY_CSV_PATH,
    DEFAULT_REPORT_JSON_PATH,
    DEFAULT_STAGE_GATE_JSON_PATH,
    SOLVER_PREFERENCE,
    _add_rolling_production_progress_tracking,
    _apply_solver_time_limit,
    _add_reference_cumulative_deadline_bands,
    run_s44c_unified_physical_regression,
)
from steel.s4_4c_component_ontology import continuous_must_run_activities  # noqa: E402


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _active_regression_kwargs() -> dict[str, object]:
    """Use the active quota lower bound and C0 operation-class contract."""

    return {
        "horizon_hours_override": 24,
        "rolling_production_deadline_targets_t": {24: 5905.2},
        "c0_continuous_must_run_activities": continuous_must_run_activities(
            "C0_current_BF_BOF_reference"
        ),
        "c0_coke_chain_reconciliation": {
            "dry_coal_t_per_t_coke": 1.285,
            "bf_coke_t_per_t_hot_metal": 0.359,
        },
        "solver_time_limit_seconds": 20,
    }


def test_s4_4c_prefers_gurobi_and_applies_its_time_limit():
    class SolverStub:
        def __init__(self):
            self.options: dict[str, float] = {}

    solver = SolverStub()
    _apply_solver_time_limit("gurobi", solver, 300)

    assert SOLVER_PREFERENCE[:2] == ("gurobi", "gurobi_direct")
    assert solver.options["TimeLimit"] == 300.0


def test_fixed_reference_deadlines_constrain_cumulative_quantity_not_hourly_profile():
    model = ConcreteModel()
    model.TIME = RangeSet(0, 47)
    model.route_output = Var(model.TIME, domain=NonNegativeReals)
    _add_reference_cumulative_deadline_bands(
        model,
        constraint_prefix="test_reference",
        hourly_expressions={"route": model.route_output},
        bands={"route": {"lower_t": 480.0, "upper_t": 528.0}},
        deadline_hours=[24, 48],
        horizon_hours=48,
    )
    constraints = list(model.component_data_objects(Constraint, active=True))
    assert len(constraints) == 4
    assert value(model.test_reference_route_24h_lower.lower) == 240.0
    assert value(model.test_reference_route_24h_upper.upper) == 264.0
    assert all(not variable.fixed for variable in model.route_output.values())

    progress_model = ConcreteModel()
    progress_model.TIME = RangeSet(0, 47)
    progress_model.route_output = Var(
        progress_model.TIME, domain=NonNegativeReals
    )
    _add_reference_cumulative_deadline_bands(
        progress_model,
        constraint_prefix="progress_reference",
        hourly_expressions={"route": progress_model.route_output},
        bands={"route": {"lower_t": 480.0, "upper_t": 528.0}},
        deadline_hours=[24, 48],
        horizon_hours=48,
        explicit_deadline_bands={
            "route": {
                24: {"lower_t": 210.0, "upper_t": 230.0},
                48: {"lower_t": 470.0, "upper_t": 500.0},
            }
        },
    )
    assert value(progress_model.progress_reference_route_24h_lower.lower) == 210.0
    assert value(progress_model.progress_reference_route_48h_upper.upper) == 500.0


def test_rolling_progress_is_one_block_deviation_objective_not_fixed_profile():
    model = ConcreteModel()
    model.TIME = RangeSet(0, 47)
    model.final_product_output = Var(model.TIME, domain=NonNegativeReals)

    _add_rolling_production_progress_tracking(
        model,
        execution_block_hours=24,
        next_execution_target_t=100.0,
    )

    assert len(model.rolling_production_progress_identity) == 1
    assert not model.rolling_production_progress_objective.active
    assert model.rolling_production_progress_target_t == 100.0
    assert model.rolling_production_progress_execution_hours == 24
    model.final_product_output[0].set_value(100.0)
    for hour in range(1, 48):
        model.final_product_output[hour].set_value(0.0)
    model.rolling_production_progress_surplus_t.set_value(0.0)
    model.rolling_production_progress_deficit_t.set_value(0.0)
    assert value(model.rolling_production_progress_identity.body) == 0.0


def test_s4_4c_attempts_c0_and_c1_through_same_runner():
    report = run_s44c_unified_physical_regression(
        run_id="pytest_s44c_no_write", write_report=False, **_active_regression_kwargs()
    )
    audits = {row["configuration_id"]: row for row in report["configuration_build_audit"]}

    assert set(audits) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
    }
    assert audits["C0_current_BF_BOF_reference"]["build_status"] == "solved"
    assert audits["C1_phase1_BF_BOF_plus_DRP_EAF"]["build_status"] == "solved"
    assert report["stage_gate"]["decision"] == "pass_to_s4_4d"


def test_s4_4c_c1_physical_regression_enforces_target_and_terminal_rule():
    report = run_s44c_unified_physical_regression(
        run_id="pytest_s44c_physical", write_report=False, **_active_regression_kwargs()
    )
    c1 = next(
        row
        for row in report["configuration_build_audit"]
        if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
    )

    assert c1["solver_status"] == "ok"
    assert c1["termination_condition"] == "optimal"
    assert c1["binary_count"] > 0
    assert float(c1["final_product_residual_t"]) >= -1e-6
    assert float(c1["final_product_fulfilled_t"]) >= float(c1["final_product_target_t"])
    assert abs(float(c1["dri_terminal_residual_t"])) <= 1e-6
    assert float(c1["electricity_mwh"]) > 0.0
    assert float(c1["natural_gas_nm3"]) > 0.0


def test_s4_4c_public_builder_forwards_named_bof_eaf_metallics_and_scrap_caps():
    horizon_hours = 24
    report = run_s44c_unified_physical_regression(
        run_id="pytest_s44c_named_metallics",
        write_report=False,
        **_active_regression_kwargs(),
        enable_c1_retained_bf_bof_route=True,
        c1_retained_route_policy="quota_driven_topology",
        commitment_granularity="daily_binary_hourly_throughput",
        eaf_material_balance={
            "hdri_t_per_t_liquid_steel": 0.8484848485,
            "scrap_t_per_t_liquid_steel": 0.3030303030,
        },
        bof_material_balance={
            "hot_metal_t_per_t_liquid_steel": 0.824,
            "scrap_t_per_t_liquid_steel": 0.294,
        },
        scrap_supply_ledger={
            "site_total_scrap_supply_cap_t": 2_000_000.0 * horizon_hours / 8760.0,
            "bof_scrap_supply_cap_t": 1_000_000.0 * horizon_hours / 8760.0,
            "eaf_scrap_supply_cap_t": 1_000_000.0 * horizon_hours / 8760.0,
        },
    )
    c1 = next(
        row
        for row in report["configuration_build_audit"]
        if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
    )
    assert c1["termination_condition"] == "optimal"
    assert c1["named_bof_eaf_metallics_active"] == "true"
    assert float(c1["scrap_t"]) > 0.0
    assert float(c1["site_total_scrap_t"]) >= float(c1["bof_scrap_t"])


def test_s4_4c_constraint_audit_includes_implemented_and_blocked_families():
    report = run_s44c_unified_physical_regression(
        run_id="pytest_s44c_constraints", write_report=False, **_active_regression_kwargs()
    )
    rows = report["constraint_audit"]
    implemented = {
        (row["configuration_id"], row["constraint_family"])
        for row in rows
        if row["implemented"] == "yes"
    }
    blocked = {
        (row["configuration_id"], row["constraint_family"])
        for row in rows
        if row["implemented"] == "no"
    }

    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "capacity_bounds") in implemented
    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "DRI_buffer_balance") in implemented
    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "final_product_fulfilment") in implemented
    assert ("C0_current_BF_BOF_reference", "process_activity_variables") in implemented
    assert ("C1_phase1_BF_BOF_plus_DRP_EAF", "WAG_steam_grid_balance") in blocked


def test_s4_4c_writes_parseable_reports():
    run_s44c_unified_physical_regression(
        run_id="pytest_s44c_write", write_report=True, **_active_regression_kwargs()
    )

    report = json.loads(DEFAULT_REPORT_JSON_PATH.read_text(encoding="utf-8"))
    gate = json.loads(DEFAULT_STAGE_GATE_JSON_PATH.read_text(encoding="utf-8"))
    build_rows = _read_csv(DEFAULT_BUILD_AUDIT_CSV_PATH)
    constraint_rows = _read_csv(DEFAULT_CONSTRAINT_AUDIT_CSV_PATH)
    hourly_rows = _read_csv(DEFAULT_HOURLY_CSV_PATH)

    assert report["hourly_da_price_taking_active"] is False
    assert gate["product_revenue_active"] is False
    assert gate["export_revenue_active"] is False
    assert gate["grid_tariff_objective_active"] is False
    assert gate["direct_wag_market_valuation_active"] is False
    assert gate["co2_ets_objective_active"] is False
    assert gate["invalid_input_rows_used_count"] == 0
    assert len(build_rows) == 2
    assert constraint_rows
    assert len(hourly_rows) == 48
