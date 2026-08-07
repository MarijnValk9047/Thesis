from __future__ import annotations

from datetime import date
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from pyomo.environ import (
    Binary,
    Block,
    ConcreteModel,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))


from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (  # noqa: E402
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (  # noqa: E402
    SteelActualPriceBundle,
    SteelRollingState,
    _build_physical_model,
    clear_hourly_da_bids,
)
from steel.s4_4c6_phase6d_eaf_heat_state_one_day import (  # noqa: E402
    DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH,
    ECONOMIC_MIP_GAP_LIMIT,
    EXPECTED_COST_INCUMBENT,
    EXPECTED_DELIVERY_DAY,
    FEASIBILITY_BID_EXPECTED_COST_INCUMBENT,
    FEASIBILITY_BID_FIXED_ECONOMIC_BINARY,
    FEASIBILITY_BID_FULL_MILP,
    FULL_PHYSICAL_TIEBREAK,
    IMBALANCE_ZERO_TOLERANCE_MWH,
    PHASE6D_CONFIG,
    PLANNING_SOLVER_NATIVE_TWO_OBJECTIVE,
    PLANNING_SOLVER_SEQUENTIAL,
    REDISPATCH_PHYSICAL_TIEBREAK_TIER,
    STEEL_BID_GRID,
    Phase6DEmergencyRecourse,
    Phase6DError,
    Phase6DPathFeasibilityIncomplete,
    Phase6DPerformanceIncomplete,
    _acceptance_mask_thresholds,
    _apply_bid_acceptance_signature_symmetry_breaking,
    _canonical_eaf_start_expression,
    _context_for_market,
    _economic_mip_acceptance_record,
    _expand_market_values,
    _feasibility_bid_canonical_solve_required,
    _feasibility_bid_selection_mode,
    _fix_economic_scenario_binary_incumbent,
    _gurobi_performance_options,
    _native_multiobjective_log_tiers,
    _parse_gurobi_performance_log,
    _physical_group_size,
    _planning_physical_tiebreak_mode,
    _planning_physical_tiebreak_solve_required,
    _planning_solver_execution_mode,
    _reconstruct_cleared_da_settlement,
    _reconstruct_imbalance_state,
    _solve_conditional_minimum_imbalance_gate,
    _solve_optimal,
    _solve_grouped_redispatch_model,
    actual_bundle_from_feasibility_pattern,
    build_validation_feasibility_clearing_pattern,
    canonical_bid_volumes_from_scenario_requirements,
    load_phase6d_config,
    run_limited_path_feasibility_constraint_generation,
    select_worst_feasibility_path_violation,
    solve_grouped_da_bid_plan,
    validate_feasibility_clearing_pattern,
    validate_flat_price_physics_identity,
)
import steel.s4_4c6_phase6d_eaf_heat_state_one_day as phase6d  # noqa: E402
from steel.s4_4c_unified_physical_modelbuilder import (  # noqa: E402
    EAFHeatStateParameters,
)


@pytest.fixture(scope="module")
def phase6d_config() -> dict:
    return load_phase6d_config(PHASE6D_CONFIG)


@pytest.fixture(scope="module")
def c1_model(phase6d_config: dict):
    context = _context_for_market(phase6d_config, "hourly")
    state = SteelRollingState("phase6d_test", C1_CONFIGURATION)
    model = _build_physical_model(
        context,
        C1_CONFIGURATION,
        state,
        terminal_day=False,
        planning_horizon_hours=120,
        terminal_hour_in_horizon=None,
    )
    for q in model.TIME:
        if not model.eaf_heat_start[q].fixed:
            model.eaf_heat_start[q].set_value(0.0)
        model.drp_pellet_input[q].set_value(0.0)
        model.basic_oxygen_furnace[q].set_value(0.0)
        model.blast_furnace_6[q].set_value(0.0)
    return context, model


def _set_single_heat(model, start_q: int) -> None:
    for q in model.TIME:
        if not model.eaf_heat_start[q].fixed:
            model.eaf_heat_start[q].set_value(0.0)
    model.eaf_heat_start[start_q].set_value(1.0)


def test_phase6d_config_freezes_one_day_and_heat_parameters(
    phase6d_config: dict,
) -> None:
    phase = phase6d_config["phase6d"]
    assert phase["delivery_date"] == "2026-04-27"
    assert phase["time_step_hours"] == 0.25
    assert (
        phase["c1_non_eaf_availability_policy"]
        == "inherit_phase6b_phase6c_endogenous_commitment"
    )
    assert phase["eaf_heat_state"]["heat_size_t_liquid_steel"] == 325.0
    assert phase["eaf_heat_state"]["maintenance_intervals"] == []
    assert phase["mip_gap_limit"] == pytest.approx(0.001)
    assert phase["economic_mip_gap_limit"] == pytest.approx(0.002)
    assert (
        phase["planning_physical_tiebreak_mode"]
        == FULL_PHYSICAL_TIEBREAK
    )


def test_planning_physical_tiebreak_mode_defaults_to_frozen_v0() -> None:
    assert (
        _planning_physical_tiebreak_mode(SimpleNamespace(config={}))
        == FULL_PHYSICAL_TIEBREAK
    )
    assert (
        _planning_physical_tiebreak_mode(
            SimpleNamespace(
                config={
                    "planning_physical_tiebreak_mode": EXPECTED_COST_INCUMBENT
                }
            )
        )
        == EXPECTED_COST_INCUMBENT
    )


def test_planning_physical_tiebreak_mode_rejects_unknown_variant() -> None:
    with pytest.raises(Phase6DError, match="Unsupported planning_physical_tiebreak_mode"):
        _planning_physical_tiebreak_mode(
            SimpleNamespace(config={"planning_physical_tiebreak_mode": "epsilon"})
        )


def test_planning_solver_execution_mode_defaults_and_fails_closed() -> None:
    assert (
        _planning_solver_execution_mode(SimpleNamespace(config={}))
        == PLANNING_SOLVER_SEQUENTIAL
    )
    assert (
        _planning_solver_execution_mode(
            SimpleNamespace(
                config={
                    "planning_solver_execution_mode": (
                        PLANNING_SOLVER_NATIVE_TWO_OBJECTIVE
                    )
                }
            )
        )
        == PLANNING_SOLVER_NATIVE_TWO_OBJECTIVE
    )
    with pytest.raises(Phase6DError, match="planning_solver_execution_mode"):
        _planning_solver_execution_mode(
            SimpleNamespace(config={"planning_solver_execution_mode": "unsafe"})
        )


def test_gurobi_performance_options_are_bounded_and_whitelisted() -> None:
    assert _gurobi_performance_options(SimpleNamespace(config={})) == {}
    assert _gurobi_performance_options(
        SimpleNamespace(config={"gurobi_performance_options": {"MIPFocus": 3}})
    ) == {"MIPFocus": 3}
    with pytest.raises(Phase6DError, match="Unsupported Gurobi"):
        _gurobi_performance_options(
            SimpleNamespace(config={"gurobi_performance_options": {"MIPGap": 0.5}})
        )
    with pytest.raises(Phase6DError, match="outside its safe range"):
        _gurobi_performance_options(
            SimpleNamespace(config={"gurobi_performance_options": {"MIPFocus": 4}})
        )


def test_time_limit_economic_incumbent_is_epsilon_optimal_at_fixed_gap() -> None:
    record = _economic_mip_acceptance_record(
        tier="expected_represented_cost",
        termination="maxtimelimit",
        objective_value=9_694_749.389854,
        best_incumbent=9_694_749.389854,
        best_bound=9_684_082.199056,
        accepted_relative_gap=ECONOMIC_MIP_GAP_LIMIT,
    )
    assert record["epsilon_optimal_accepted"] is True
    assert record["optimality_class"] == "epsilon_optimal"
    assert record["objective_lower_bound_eur"] == pytest.approx(9_684_082.199056)
    assert record["objective_upper_bound_eur"] == pytest.approx(9_694_749.389854)
    assert record["absolute_objective_band_eur"] == pytest.approx(10_667.190798)
    assert record["certified_relative_gap"] == pytest.approx(0.001100305987)


@pytest.mark.parametrize(
    ("termination", "incumbent", "bound"),
    [
        ("maxtimelimit", 100.0, None),
        ("maxtimelimit", None, 99.9),
        ("maxtimelimit", 100.0, 99.7),
        ("infeasible", 100.0, 99.9),
    ],
)
def test_economic_epsilon_acceptance_fails_closed(
    termination: str, incumbent: float | None, bound: float | None
) -> None:
    record = _economic_mip_acceptance_record(
        tier="expected_represented_cost",
        termination=termination,
        objective_value=incumbent,
        best_incumbent=incumbent,
        best_bound=bound,
        accepted_relative_gap=ECONOMIC_MIP_GAP_LIMIT,
    )
    assert record["epsilon_optimal_accepted"] is False


def test_economic_gap_policy_cannot_accept_a_physical_tier() -> None:
    with pytest.raises(Phase6DError, match="physical tier"):
        _economic_mip_acceptance_record(
            tier="production_progress",
            termination="optimal",
            objective_value=0.0,
            best_incumbent=0.0,
            best_bound=0.0,
            accepted_relative_gap=ECONOMIC_MIP_GAP_LIMIT,
        )


class _FakeTimeLimitSolver:
    def __init__(self, *, incumbent: float, bound: float) -> None:
        self.options: dict[str, float] = {"MIPGap": 0.001}
        self.incumbent = incumbent
        self.bound = bound

    def solve(self, model, warmstart=False):
        del model, warmstart
        solver = SimpleNamespace(
            status="aborted",
            termination_condition="maxTimeLimit",
            statistics=None,
            get=lambda key: (
                (self.incumbent - self.bound) / abs(self.incumbent)
                if key == "gap"
                else None
            ),
        )
        return SimpleNamespace(
            solver=solver,
            problem=SimpleNamespace(
                upper_bound=self.incumbent,
                lower_bound=self.bound,
            ),
        )


def test_solve_optimal_accepts_only_certified_economic_time_limit() -> None:
    model = ConcreteModel()
    model.objective = Objective(expr=100.0, sense=minimize)
    solver = _FakeTimeLimitSolver(incumbent=100.0, bound=99.9)
    _, record = _solve_optimal(
        model,
        solver,
        "expected_represented_cost",
        warmstart=False,
        economic_mip_gap_limit=ECONOMIC_MIP_GAP_LIMIT,
    )
    assert record["epsilon_optimal_accepted"] is True
    assert record["termination_condition"] == "maxTimeLimit"
    assert solver.options["MIPGap"] == pytest.approx(0.001)

    blocked_solver = _FakeTimeLimitSolver(incumbent=100.0, bound=99.7)
    with pytest.raises(Phase6DPerformanceIncomplete):
        _solve_optimal(
            model,
            blocked_solver,
            "expected_represented_cost",
            warmstart=False,
            economic_mip_gap_limit=ECONOMIC_MIP_GAP_LIMIT,
        )


def test_feasibility_bid_selection_mode_is_explicit_and_fail_closed() -> None:
    assert (
        _feasibility_bid_selection_mode(SimpleNamespace(config={}))
        == FEASIBILITY_BID_FULL_MILP
    )
    assert (
        _feasibility_bid_selection_mode(
            SimpleNamespace(
                config={
                    "feasibility_bid_selection_mode": (
                        FEASIBILITY_BID_EXPECTED_COST_INCUMBENT
                    )
                }
            )
        )
        == FEASIBILITY_BID_EXPECTED_COST_INCUMBENT
    )
    with pytest.raises(Phase6DError, match="feasibility_bid_selection_mode"):
        _feasibility_bid_selection_mode(
            SimpleNamespace(config={"feasibility_bid_selection_mode": "unsafe"})
        )


def test_feasibility_expected_cost_incumbent_skips_only_secondary_bid_solve() -> None:
    assert not _feasibility_bid_canonical_solve_required(
        FEASIBILITY_BID_EXPECTED_COST_INCUMBENT, feasibility_path_count=1
    )
    assert _feasibility_bid_canonical_solve_required(
        FEASIBILITY_BID_FULL_MILP, feasibility_path_count=1
    )
    assert _feasibility_bid_canonical_solve_required(
        FEASIBILITY_BID_FIXED_ECONOMIC_BINARY, feasibility_path_count=1
    )
    assert not _feasibility_bid_canonical_solve_required(
        FEASIBILITY_BID_FULL_MILP, feasibility_path_count=0
    )
    source = inspect.getsource(solve_grouped_da_bid_plan)
    block_build = source.index("feasibility_masks:")
    secondary_objective = source.index(
        "feasibility_canonical_bid_solve_performed = False"
    )
    assert "if validated_feasibility_paths:" in source[
        block_build:secondary_objective
    ]
    assert "_feasibility_bid_canonical_solve_required(" in source[
        secondary_objective:
    ]


def test_parent_round_bridge_is_warm_start_only_and_restores_full_milp() -> None:
    source = inspect.getsource(solve_grouped_da_bid_plan)
    bridge = source.index("parent_round_restricted_expected_cost_bridge")
    unfix = source.index("variable.unfix()", bridge)
    final_objective = source.index("root.expected_cost_objective = Objective", unfix)
    final_solve = source.index('"expected_represented_cost"', final_objective)
    assert bridge < unfix < final_objective < final_solve
    assert '"parent_round_bridge_final_result_eligible": False' in source
    assert "root.cost_preservation" not in source[bridge:final_objective]


def test_reduced_canonicalisation_fixes_only_economic_scenario_binaries() -> None:
    root = ConcreteModel()
    root.SCENARIO = Set(initialize=("a", "b"), ordered=True)
    root.scenario = Block(root.SCENARIO)
    for scenario_id in root.SCENARIO:
        root.scenario[scenario_id].binary = Var((0, 1), domain=Binary)
        root.scenario[scenario_id].continuous = Var(domain=NonNegativeReals)
        root.scenario[scenario_id].binary[0].set_value(0.0)
        root.scenario[scenario_id].binary[1].set_value(1.0)
        root.scenario[scenario_id].continuous.set_value(2.0)
    fixed = _fix_economic_scenario_binary_incumbent(root)
    assert fixed == 4
    assert all(
        variable.fixed
        for scenario_id in root.SCENARIO
        for variable in root.scenario[scenario_id].binary.values()
    )
    assert all(
        not root.scenario[scenario_id].continuous.fixed
        for scenario_id in root.SCENARIO
    )


def test_bid_signature_symmetry_break_preserves_one_equivalent_step() -> None:
    root = ConcreteModel()
    root.MARKET_TIME = Set(initialize=(0,), ordered=True)
    root.BID = Set(initialize=STEEL_BID_GRID, ordered=True)
    root.bid_volume_mwh = Var(root.MARKET_TIME, root.BID, domain=NonNegativeReals)
    stats = _apply_bid_acceptance_signature_symmetry_breaking(
        root,
        scenario_ids=("low", "high"),
        scenario_prices={"low": (50.0,), "high": (150.0,)},
        feasibility_masks={},
    )
    unfixed_by_signature: dict[tuple[bool, bool], list[float]] = {}
    for bid_price in STEEL_BID_GRID:
        signature = (bid_price >= 50.0, bid_price >= 150.0)
        if not root.bid_volume_mwh[0, bid_price].fixed:
            unfixed_by_signature.setdefault(signature, []).append(bid_price)
    assert (False, False) not in unfixed_by_signature
    assert all(len(prices) == 1 for prices in unfixed_by_signature.values())
    assert stats["fixed_bid_step_count"] + stats["retained_bid_step_count"] == len(
        STEEL_BID_GRID
    )


def test_gurobi_performance_log_parser_captures_runtime_diagnosis() -> None:
    parsed = _parse_gurobi_performance_log(
        """
Presolve removed 123 rows and 456 columns
Presolve time: 1.25s
Presolved: 1000 rows, 800 columns, 5000 nonzeros
Detected 7 symmetries
Found heuristic solution: objective 9.900000e+06
Loaded user MIP start with objective 1.010000e+07
Root relaxation: objective 9.100000e+06, 250 iterations, 0.75 seconds (1.25 work units)
Explored 42 nodes (100 simplex iterations) in 12.50 seconds (3.75 work units)
Best objective 9.200000e+06, best bound 9.199000e+06, gap 0.0109%
"""
    )
    assert parsed == {
        "presolve_removed_rows": 123,
        "presolve_removed_columns": 456,
        "presolved_rows": 1000,
        "presolved_columns": 800,
        "presolved_nonzeros": 5000,
        "presolve_seconds": pytest.approx(1.25),
        "root_relaxation_objective": pytest.approx(9_100_000.0),
        "root_relaxation_seconds": pytest.approx(0.75),
        "root_relaxation_work_units": pytest.approx(1.25),
        "loaded_mip_start_objective": pytest.approx(10_100_000.0),
        "first_heuristic_incumbent": pytest.approx(9_900_000.0),
        "best_incumbent": pytest.approx(9_200_000.0),
        "best_bound": pytest.approx(9_199_000.0),
        "final_mip_gap": pytest.approx(0.000109),
        "branch_and_bound_nodes": 42,
        "solver_reported_time_seconds": pytest.approx(12.5),
        "work_units": pytest.approx(3.75),
        "detected_symmetry_count": 7,
    }


def test_v1_skips_planning_tiebreak_and_v0_remains_supported() -> None:
    assert not _planning_physical_tiebreak_solve_required(EXPECTED_COST_INCUMBENT)
    assert _planning_physical_tiebreak_solve_required(FULL_PHYSICAL_TIEBREAK)
    assert "_planning_physical_tiebreak_solve_required" in inspect.getsource(
        solve_grouped_da_bid_plan
    )
    assert REDISPATCH_PHYSICAL_TIEBREAK_TIER == "redispatch_physical_tiebreak"
    assert "REDISPATCH_PHYSICAL_TIEBREAK_TIER" in inspect.getsource(
        _solve_grouped_redispatch_model
    )


@pytest.mark.parametrize(
    "penalty", [0.0, -1.0, 2500.0, 10000.0, float("inf"), float("nan")]
)
def test_execution_recourse_rejects_every_non_frozen_penalty(
    penalty: float,
) -> None:
    with pytest.raises(Phase6DError, match="exactly one fixed"):
        _solve_grouped_redispatch_model(
            None,
            C1_CONFIGURATION,
            None,
            None,
            (),
            oracle_execute_D_cost_only=False,
            imbalance_penalty_eur_per_mwh=penalty,
        )


def _qh_validation_actual(delivery_day: date = date(2025, 3, 2)):
    timestamps = tuple(
        pd.date_range(
            f"{delivery_day.isoformat()} 00:00",
            periods=96,
            freq="15min",
            tz="Europe/Amsterdam",
        ).tz_convert("UTC")
    )
    return SteelActualPriceBundle(
        delivery_day=delivery_day,
        timestamps_utc=timestamps,
        prices=tuple(float((index % 9) * 40 - 100) for index in range(96)),
        granularity="quarterhour",
        time_step_hours=0.25,
    )


def test_validation_pattern_is_deterministic_probability_free_and_grid_correct() -> None:
    actual = _qh_validation_actual()
    kwargs = {
        "source_shadow_id": "shadow__typical_calm__2025-03-02",
        "bid_grid_id": "steel_phase6d_qh_shared_qh_eaf_bid_grid_v1",
        "forbidden_final_periods": ((date(2025, 1, 13), date(2025, 1, 19)),),
    }
    left = build_validation_feasibility_clearing_pattern(actual, **kwargs)
    right = build_validation_feasibility_clearing_pattern(actual, **kwargs)
    assert left == right
    assert left["lead_positions"] == list(range(96))
    assert len(left["acceptance_mask_by_lead_position"]) == 96
    assert not {
        "probability",
        "scenario_probability",
        "expected_cost_weight",
        "raw_prices_eur_per_mwh",
    }.intersection(left)
    assert len(_acceptance_mask_thresholds(left)) == 96


def test_controlled_synthetic_validation_pattern_has_distinct_non_final_lineage() -> None:
    actual = _qh_validation_actual(date(2025, 3, 3))
    pattern = build_validation_feasibility_clearing_pattern(
        actual,
        source_validation_case_id="synthetic_validation__S0_flat_reference",
        source_profile_id="S0_flat_reference",
        source_lineage_sha256="a" * 64,
        bid_grid_id="steel_phase6d_qh_shared_qh_eaf_bid_grid_v1",
        forbidden_final_periods=((date(2025, 1, 13), date(2025, 1, 19)),),
    )
    assert pattern["source_class"] == "controlled_synthetic_validation"
    assert pattern["development_validation_case"]
    assert not pattern["development_shadow_case"]
    assert not pattern["final_test_case"]
    assert pattern["cutoff_status"] == (
        "pre_final_validation_only_not_origin_information"
    )
    assert "source_shadow_id" not in pattern


def test_controlled_synthetic_pattern_requires_complete_lineage() -> None:
    with pytest.raises(Phase6DError, match="complete lineage"):
        build_validation_feasibility_clearing_pattern(
            _qh_validation_actual(),
            source_validation_case_id="synthetic_validation__S0_flat_reference",
            source_profile_id="S0_flat_reference",
            source_lineage_sha256="short",
            bid_grid_id="steel_phase6d_qh_shared_qh_eaf_bid_grid_v1",
            forbidden_final_periods=(),
        )


def test_final_week_cannot_be_a_feasibility_pattern_source() -> None:
    actual = _qh_validation_actual(date(2025, 1, 15))
    with pytest.raises(Phase6DError, match="final-week"):
        build_validation_feasibility_clearing_pattern(
            actual,
            source_shadow_id="shadow__forbidden__2025-01-15",
            bid_grid_id="steel_phase6d_qh_shared_qh_eaf_bid_grid_v1",
            forbidden_final_periods=((date(2025, 1, 13), date(2025, 1, 19)),),
        )


def test_hourly_and_qh_feasibility_patterns_cannot_mix() -> None:
    actual = _qh_validation_actual()
    pattern = build_validation_feasibility_clearing_pattern(
        actual,
        source_shadow_id="shadow__typical_calm__2025-03-02",
        bid_grid_id="steel_phase6d_qh_shared_qh_eaf_bid_grid_v1",
        forbidden_final_periods=((date(2025, 1, 13), date(2025, 1, 19)),),
    )
    with pytest.raises(Phase6DError, match="cannot mix"):
        validate_feasibility_clearing_pattern(
            pattern,
            market_granularity="hourly",
            market_intervals=96,
            bid_grid_id="steel_phase6d_hourly_shared_qh_eaf_bid_grid_v1",
        )
    with pytest.raises(Phase6DError, match="cannot mix"):
        actual_bundle_from_feasibility_pattern(
            pattern,
            delivery_day=date(2025, 4, 1),
            timestamps_utc=actual.timestamps_utc,
            market_granularity="hourly",
            market_time_step_hours=1.0,
            bid_grid_id="steel_phase6d_hourly_shared_qh_eaf_bid_grid_v1",
        )


def test_feasibility_block_contract_shares_bid_variables_and_has_no_cost_weight() -> None:
    source = inspect.getsource(solve_grouped_da_bid_plan)
    assert "root.bid_volume_mwh" in source
    assert "root.feasibility_path_clearing" in source
    assert "m.feasibility_path[path_id].net_grid_import_mwh" in source
    assert "feasibility_path_progress_preservation" in source
    cost_section = source[source.index("cost_expr = sum(") : source.index("tie_expr = sum(")]
    assert "feasibility_path" not in cost_section
    assert '"feasibility_path_expected_cost_contribution_eur": 0.0' in source


def test_worst_path_selection_is_deterministic() -> None:
    diagnostics = [
        {"path_id": "b", "minimum_imbalance_mwh": 2.0},
        {"path_id": "a", "minimum_imbalance_mwh": 2.0},
        {"path_id": "c", "minimum_imbalance_mwh": 1.0},
    ]
    assert select_worst_feasibility_path_violation(diagnostics)["path_id"] == "a"


def test_constraint_generation_adds_one_path_per_round_and_then_passes() -> None:
    paths = ({"path_id": "a"}, {"path_id": "b"})
    solve_calls: list[tuple[int, tuple[str, ...]]] = []

    def solve(selected, round_index):
        solve_calls.append((round_index, tuple(row["path_id"] for row in selected)))
        return SimpleNamespace(
            solver={
                "variable_count": 10 + len(selected),
                "binary_count": len(selected),
                "constraint_count": 20 + len(selected),
                "total_solver_seconds": 1.0,
            }
        )

    def assess(plan, candidates, round_index):
        del plan, round_index
        selected = set(solve_calls[-1][1])
        return [
            {
                "path_id": row["path_id"],
                "minimum_imbalance_mwh": (
                    0.0 if row["path_id"] in selected else 2.0
                ),
            }
            for row in candidates
        ]

    result = run_limited_path_feasibility_constraint_generation(
        paths,
        solve_plan=solve,
        assess_plan=assess,
        max_augmentation_rounds=3,
    )
    assert result["status"] == "pass"
    assert [len(ids) for _, ids in solve_calls] == [0, 1, 2]
    assert all(row["added_path_count"] <= 1 for row in result["rounds"])


def test_constraint_generation_fails_closed_after_three_rounds() -> None:
    paths = tuple({"path_id": chr(97 + index)} for index in range(4))

    def solve(selected, round_index):
        del round_index
        return SimpleNamespace(
            solver={
                "variable_count": len(selected),
                "binary_count": len(selected),
                "constraint_count": len(selected),
                "total_solver_seconds": 0.0,
            }
        )

    def assess(plan, candidates, round_index):
        del round_index
        selected_count = int(plan.solver["variable_count"])
        return [
            {
                "path_id": row["path_id"],
                "minimum_imbalance_mwh": (
                    0.0 if index < selected_count else 1.0
                ),
            }
            for index, row in enumerate(candidates)
        ]

    with pytest.raises(Phase6DPathFeasibilityIncomplete) as caught:
        run_limited_path_feasibility_constraint_generation(
            paths,
            solve_plan=solve,
            assess_plan=assess,
            max_augmentation_rounds=3,
        )
    assert (
        caught.value.diagnostic["status"]
        == "path_feasibility_augmentation_incomplete"
    )
    assert caught.value.diagnostic["reason"] == "maximum_augmentation_rounds_reached"
    assert len(caught.value.diagnostic["selected_path_ids"]) == 3


def test_constraint_generation_propagates_unproven_optimality() -> None:
    def solve(selected, round_index):
        del selected, round_index
        raise Phase6DPerformanceIncomplete("time limit")

    with pytest.raises(Phase6DPerformanceIncomplete):
        run_limited_path_feasibility_constraint_generation(
            ({"path_id": "a"},),
            solve_plan=solve,
            assess_plan=lambda *_: (),
            max_augmentation_rounds=3,
        )


def _conditional_gate_model() -> tuple[ConcreteModel, object, object]:
    model = ConcreteModel()
    model.PHASE6D_EXECUTION_MARKET = Set(initialize=(0,), ordered=True)
    model.PHYSICAL_TIME = Set(initialize=(0,), ordered=True)
    model.phase6d_imbalance_positive_mwh = Var(
        model.PHASE6D_EXECUTION_MARKET, domain=NonNegativeReals
    )
    model.phase6d_imbalance_negative_mwh = Var(
        model.PHASE6D_EXECUTION_MARKET, domain=NonNegativeReals
    )
    model.net_grid_import_mwh = Var(model.PHYSICAL_TIME, domain=NonNegativeReals)
    imbalance = sum(
        model.phase6d_imbalance_positive_mwh[t]
        + model.phase6d_imbalance_negative_mwh[t]
        for t in model.PHASE6D_EXECUTION_MARKET
    )
    penalty = DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH * imbalance
    return model, 100.0 + penalty, penalty


def _fake_gate_solver(
    monkeypatch: pytest.MonkeyPatch,
    tier_values: dict[str, float],
    calls: list[str],
) -> None:
    def fake_solve(
        model,
        solver,
        tier,
        *,
        warmstart,
        economic_mip_gap_limit=None,
        progress_callback=None,
    ):
        del solver, warmstart, economic_mip_gap_limit
        calls.append(tier)
        amount = float(tier_values[tier])
        model.phase6d_imbalance_positive_mwh[0].set_value(amount)
        model.phase6d_imbalance_negative_mwh[0].set_value(0.0)
        model.net_grid_import_mwh[0].set_value(10.0 + amount)
        if progress_callback is not None:
            progress_callback({"event": "solver_tier_started", "tier": tier})
            progress_callback(
                {
                    "event": "solver_tier_finished",
                    "tier": tier,
                    "solver_status": "ok",
                    "termination_condition": "optimal",
                    "mip_gap": 0.0,
                }
            )
        return SimpleNamespace(
            solver=SimpleNamespace(status="ok", termination_condition="optimal")
        ), {
            "tier": tier,
            "solver_status": "ok",
            "termination_condition": "optimal",
            "mip_gap": 0.0,
            "runtime_seconds": 0.01,
            "variable_count": 3,
            "binary_count": 0,
            "constraint_count": 0,
        }

    monkeypatch.setattr(phase6d, "_solve_optimal", fake_solve)


def _run_fake_gate(model, cost_expr, penalty_expr):
    return _solve_conditional_minimum_imbalance_gate(
        model,
        object(),
        cost_expr=cost_expr,
        imbalance_volume_expr=(
            model.phase6d_imbalance_positive_mwh[0]
            + model.phase6d_imbalance_negative_mwh[0]
        ),
        imbalance_penalty_expr=penalty_expr,
        imbalance_recourse_active=True,
        imbalance_penalty_eur_per_mwh=DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH,
        cleared_energy_mwh=(10.0,),
        group_size=1,
        cost_tolerance_eur=1e-4,
        economic_mip_gap_limit=ECONOMIC_MIP_GAP_LIMIT,
        tiers=[],
        progress_callback=None,
    )


def test_zero_economic_imbalance_skips_minimum_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, cost_expr, penalty_expr = _conditional_gate_model()
    calls: list[str] = []
    _fake_gate_solver(
        monkeypatch, {"redispatch_represented_cost": 0.0}, calls
    )
    _, _, gate = _run_fake_gate(model, cost_expr, penalty_expr)
    assert calls == ["redispatch_represented_cost"]
    assert not gate["conditional_minimum_imbalance_solve_performed"]
    assert gate["status"] == "zero_imbalance_from_economic_solve"


def test_avoidable_economic_imbalance_gets_minimum_and_hard_zero_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, cost_expr, penalty_expr = _conditional_gate_model()
    calls: list[str] = []
    _fake_gate_solver(
        monkeypatch,
        {
            "redispatch_represented_cost": 1.0,
            "redispatch_minimum_absolute_imbalance": 0.0,
            "redispatch_represented_cost_hard_zero_imbalance": 0.0,
        },
        calls,
    )
    _, _, gate = _run_fake_gate(model, cost_expr, penalty_expr)
    assert calls == [
        "redispatch_represented_cost",
        "redispatch_minimum_absolute_imbalance",
        "redispatch_represented_cost_hard_zero_imbalance",
    ]
    assert gate["conditional_minimum_imbalance_solve_performed"]
    assert gate["hard_zero_economic_resolve_performed"]
    assert model.phase6d_imbalance_positive_mwh[0].fixed
    assert value(model.phase6d_imbalance_positive_mwh[0]) == 0.0


def test_unavoidable_imbalance_is_emergency_recourse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, cost_expr, penalty_expr = _conditional_gate_model()
    calls: list[str] = []
    _fake_gate_solver(
        monkeypatch,
        {
            "redispatch_represented_cost": 2.0,
            "redispatch_minimum_absolute_imbalance": 0.25,
        },
        calls,
    )
    with pytest.raises(Phase6DEmergencyRecourse) as caught:
        _run_fake_gate(model, cost_expr, penalty_expr)
    assert calls == [
        "redispatch_represented_cost",
        "redispatch_minimum_absolute_imbalance",
    ]
    assert caught.value.diagnostic["status"] == "emergency_recourse"
    assert caught.value.diagnostic["absolute_imbalance_mwh"] == pytest.approx(0.25)
    assert caught.value.diagnostic["imbalance_penalty_eur"] == pytest.approx(1250.0)
    assert not caught.value.diagnostic["abc_comparison_eligible"]


def test_minimum_imbalance_time_limit_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, cost_expr, penalty_expr = _conditional_gate_model()
    calls: list[str] = []

    def fake_solve(
        model,
        solver,
        tier,
        *,
        warmstart,
        economic_mip_gap_limit=None,
        progress_callback=None,
    ):
        del solver, warmstart, economic_mip_gap_limit, progress_callback
        calls.append(tier)
        if tier == "redispatch_represented_cost":
            model.phase6d_imbalance_positive_mwh[0].set_value(1.0)
            model.phase6d_imbalance_negative_mwh[0].set_value(0.0)
            model.net_grid_import_mwh[0].set_value(11.0)
            return SimpleNamespace(
                solver=SimpleNamespace(status="ok", termination_condition="optimal")
            ), {"tier": tier}
        raise Phase6DPerformanceIncomplete(
            "time limit", diagnostic={"tier": {"tier": tier, "mip_gap": 0.1}}
        )

    monkeypatch.setattr(phase6d, "_solve_optimal", fake_solve)
    with pytest.raises(Phase6DPerformanceIncomplete) as caught:
        _run_fake_gate(model, cost_expr, penalty_expr)
    assert calls[-1] == "redispatch_minimum_absolute_imbalance"
    assert (
        caught.value.diagnostic["status"]
        == "minimum_imbalance_optimality_unproven"
    )


def test_penalty_and_cleared_settlement_are_reconstructed_once() -> None:
    model, _, penalty_expr = _conditional_gate_model()
    model.phase6d_imbalance_positive_mwh[0].set_value(0.4)
    model.phase6d_imbalance_negative_mwh[0].set_value(0.1)
    model.net_grid_import_mwh[0].set_value(10.3)
    state = _reconstruct_imbalance_state(
        model,
        model.phase6d_imbalance_positive_mwh[0]
        + model.phase6d_imbalance_negative_mwh[0],
        penalty_expr,
        (10.0,),
        1,
        DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH,
    )
    assert state["absolute_imbalance_mwh"] == pytest.approx(0.5)
    assert state["imbalance_penalty_eur"] == pytest.approx(2500.0)
    assert state["maximum_cleared_physical_identity_error_mwh"] <= (
        IMBALANCE_ZERO_TOLERANCE_MWH
    )
    clearing = SimpleNamespace(
        hourly=[
            {"cleared_energy_mwh": 2.0, "realised_price_eur_per_mwh": 50.0},
            {"cleared_energy_mwh": 3.0, "realised_price_eur_per_mwh": -10.0},
        ]
    )
    assert _reconstruct_cleared_da_settlement(clearing) == pytest.approx(70.0)


def test_native_multiobjective_log_parser_uses_order_when_names_are_truncated() -> None:
    log = Path(__file__).resolve().parents[4] / "tmp" / "phase6d_native_parser_test.log"
    blocks = []
    for index, name in enumerate(
        ("production_progres", "expected_represent", "physical_tiebreak"),
        start=1,
    ):
        blocks.append(
            f"Multi-objectives: optimize objective {index} ({name}) ...\n"
            f"Explored {index} nodes (10 simplex iterations) in {index}.00 seconds ({index}.50 work units)\n"
            f"Best objective {index}.0, best bound {index}.0, gap 0.0000%\n"
        )
    log.write_text("".join(blocks), encoding="utf-8")
    try:
        records = _native_multiobjective_log_tiers(
            log,
            model_stats=SimpleNamespace(variables=3, binaries=2, constraints=1),
            fallback_status="ok",
            fallback_termination="optimal",
        )
        assert [record["tier"] for record in records] == [
            "production_progress",
            "expected_represented_cost",
            "physical_tiebreak",
        ]
        assert [record["objective_value"] for record in records] == [1.0, 2.0, 3.0]
    finally:
        log.unlink(missing_ok=True)


def test_heat_sequence_q0_q1_q2_and_no_overlap(c1_model) -> None:
    _, model = c1_model
    _set_single_heat(model, 4)
    assert value(model.eaf_melt[4]) == pytest.approx(1.0)
    assert value(model.eaf_melt[5]) == pytest.approx(1.0)
    assert value(model.eaf_tap[6]) == pytest.approx(1.0)
    assert value(model.eaf_melt[6]) == pytest.approx(0.0)
    assert max(
        value(model.eaf_melt[q] + model.eaf_tap[q]) for q in model.TIME
    ) <= 1.0


def test_only_one_start_binary_per_possible_heat_start(c1_model) -> None:
    _, model = c1_model
    assert model.eaf_heat_start[0].domain is Binary
    assert not hasattr(model, "eaf_melt_binary")
    assert not hasattr(model, "eaf_tap_binary")
    assert not hasattr(model, "eaf_day_on")
    assert model.eaf_heat_start[478].fixed
    assert model.eaf_heat_start[479].fixed


def test_325_t_per_tap_and_integer_heat_output(c1_model) -> None:
    _, model = c1_model
    _set_single_heat(model, 10)
    outputs = [value(model.eaf_liquid_steel_output[q]) for q in model.TIME]
    assert outputs[12] == pytest.approx(325.0)
    assert sum(outputs) == pytest.approx(325.0)


def test_arc_energy_is_137_2222222_mwh_per_heat_and_zero_at_tap_idle(
    c1_model,
) -> None:
    _, model = c1_model
    _set_single_heat(model, 20)
    arc = [value(model.eaf_arc_electricity_mwh[q]) for q in model.TIME]
    assert arc[20] == pytest.approx(68.6111111075)
    assert arc[21] == pytest.approx(68.6111111075)
    assert arc[22] == pytest.approx(0.0)
    assert sum(arc) == pytest.approx(137.222222215)
    assert model.eaf_arc_on_power_mw == pytest.approx(274.44444443)


def test_eaf_material_ng_o2_and_secondary_totals_follow_heat_phases(
    c1_model,
) -> None:
    context, model = c1_model
    _set_single_heat(model, 30)
    hdri = sum(value(model.eaf_dri_input[q]) for q in model.TIME)
    scrap = sum(value(model.eaf_scrap_supply_t[q]) for q in model.TIME)
    ng = sum(value(model.eaf_named_ng_mwh[q]) for q in model.TIME)
    oxygen = sum(value(model.oxygen_t[q]) for q in model.TIME)
    secondary = sum(
        value(model.eaf_secondary_electricity_mwh[q]) for q in model.TIME
    )
    assert hdri == pytest.approx(
        325.0 * context.config["eaf_material_balance"]["hdri_t_per_t_liquid_steel"]
    )
    assert scrap == pytest.approx(
        325.0 * context.config["eaf_material_balance"]["scrap_t_per_t_liquid_steel"]
    )
    assert ng == pytest.approx(325.0 * 0.05 / 3.6)
    assert oxygen == pytest.approx(hdri * 0.05)
    assert secondary == pytest.approx(10.075)


def test_rolling_handoff_completes_heat_across_execution_boundary(
    phase6d_config: dict,
) -> None:
    context = _context_for_market(phase6d_config, "hourly")
    state = SteelRollingState(
        "phase6d_handoff",
        C1_CONFIGURATION,
        eaf_start_lag1=1,
        eaf_start_lag2=0,
    )
    model = _build_physical_model(
        context,
        C1_CONFIGURATION,
        state,
        terminal_day=False,
        planning_horizon_hours=120,
        terminal_hour_in_horizon=None,
    )
    for q in model.TIME:
        if not model.eaf_heat_start[q].fixed:
            model.eaf_heat_start[q].set_value(0.0)
    assert value(model.eaf_melt[0]) == pytest.approx(1.0)
    assert value(model.eaf_tap[0]) == pytest.approx(0.0)
    assert value(model.eaf_tap[1]) == pytest.approx(1.0)
    assert value(model.eaf_liquid_steel_output[1]) == pytest.approx(325.0)


def test_terminal_state_has_no_unfinished_heat(c1_model) -> None:
    _, model = c1_model
    assert model.eaf_heat_start[478].fixed
    assert model.eaf_heat_start[478].value == pytest.approx(0.0)
    assert model.eaf_heat_start[479].fixed
    assert model.eaf_heat_start[479].value == pytest.approx(0.0)


def test_quantization_aware_daily_and_weekly_route_bands(c1_model) -> None:
    context, model = c1_model
    assert model.c1_reference_eaf_liquid_steel_quantization_allowance_t == 162.5
    assert model.c1_reference_eaf_liquid_steel_effective_lower_t == pytest.approx(
        model.c1_reference_eaf_liquid_steel_original_lower_t - 162.5
    )
    assert model.c1_reference_eaf_liquid_steel_effective_upper_t == pytest.approx(
        model.c1_reference_eaf_liquid_steel_original_upper_t + 162.5
    )
    # The original 168-hour cumulative band is retained in reporting.
    original_week_lower = 3.215852199 * 1_000_000 * 168 / 8760
    original_week_upper = 3.248172321 * 1_000_000 * 168 / 8760
    assert original_week_lower == pytest.approx(61674.4268, abs=1.0)
    assert original_week_upper == pytest.approx(62293.7157, abs=1.0)
    assert original_week_lower <= 190 * 325 <= original_week_upper
    # The effective band adds half a heat on each side.
    assert original_week_lower - 162.5 <= 190 * 325
    assert 190 * 325 <= original_week_upper + 162.5


def test_hourly_market_groups_four_internal_qh_intervals() -> None:
    assert _physical_group_size("hourly") == 4
    assert _physical_group_size("quarterhour") == 1
    assert _expand_market_values((10.0, 20.0), "hourly") == (
        10.0,
        10.0,
        10.0,
        10.0,
        20.0,
        20.0,
        20.0,
        20.0,
    )


def test_analytical_canonical_bid_uses_highest_admissible_grid_step() -> None:
    volumes = canonical_bid_volumes_from_scenario_requirements(
        {
            "low": (50.0,),
            "high": (150.0,),
        },
        {
            "low": (10.0,),
            "high": (4.0,),
        },
        bid_grid=(-500.0, 0.0, 100.0, 200.0, 3000.0),
    )
    assert volumes[(0, 100.0)] == pytest.approx(6.0)
    assert volumes[(0, 3000.0)] == pytest.approx(4.0)
    assert sum(
        quantity for (_, price), quantity in volumes.items() if price >= 50.0
    ) == pytest.approx(10.0)
    assert sum(
        quantity for (_, price), quantity in volumes.items() if price >= 150.0
    ) == pytest.approx(4.0)
    assert sum(
        quantity for (_, price), quantity in volumes.items() if price >= 250.0
    ) == pytest.approx(4.0)


def test_analytical_canonical_bid_rejects_inconsistent_acceptance_set() -> None:
    with pytest.raises(Phase6DError, match="same bid-grid acceptance set"):
        canonical_bid_volumes_from_scenario_requirements(
            {"left": (51.0,), "right": (99.0,)},
            {"left": (3.0,), "right": (4.0,)},
            bid_grid=(0.0, 100.0, 200.0),
        )


def test_legacy_canonical_eaf_tiebreak_is_algebraic_zero_under_temporal_v2(
    c1_model,
) -> None:
    _, model = c1_model
    _set_single_heat(model, 4)
    assert value(_canonical_eaf_start_expression(model)) == pytest.approx(0.0)


def test_flat_price_hourly_qh_validator_uses_same_eaf_fields() -> None:
    rows = [
        {
            "eaf_heat_start": 1.0,
            "eaf_melt": 1.0,
            "eaf_tap": 0.0,
            "eaf_arc_electricity_mwh": 68.6111111075,
            "eaf_liquid_steel_output_t": 0.0,
        }
    ]
    trajectories = [
        {
            "market_granularity": "hourly",
            "configuration_id": C1_CONFIGURATION,
            "policy": "price-insensitive",
            "physical_dispatch": rows,
        },
        {
            "market_granularity": "quarterhour",
            "configuration_id": C1_CONFIGURATION,
            "policy": "price-insensitive",
            "physical_dispatch": [dict(rows[0])],
        },
    ]
    assert validate_flat_price_physics_identity(trajectories)["status"] == "pass"


def test_c1_uses_ontology_must_run_and_scaled_drp_ramp_is_active(
    c1_model,
) -> None:
    context, model = c1_model
    assert context.c1_continuous_activities == (
        "coking_plant_1",
        "sintering_plant",
        "blast_furnace_6",
        "drp_pellet_input",
    )
    for name in (
        "coking_plant_1_on",
        "sintering_plant_on",
        "blast_furnace_6_on",
        "drp_on",
    ):
        variable = getattr(model, name)
        assert all(variable[q].fixed for q in model.TIME)
        assert all(value(variable[q]) == pytest.approx(1.0) for q in model.TIME)
    assert len(model.drp_ramp_up) == 479
    assert len(model.drp_ramp_down) == 479


def test_c0_builder_does_not_gain_eaf_discreteness(
    phase6d_config: dict,
) -> None:
    context = _context_for_market(phase6d_config, "quarterhour")
    model = _build_physical_model(
        context,
        C0_CONFIGURATION,
        SteelRollingState("c0_regression", C0_CONFIGURATION),
        terminal_day=False,
        planning_horizon_hours=120,
        terminal_hour_in_horizon=None,
    )
    assert not hasattr(model, "eaf_heat_start")
    assert not hasattr(model, "eaf_melt")
    assert not hasattr(model, "eaf_tap")


def test_pay_as_cleared_uses_realised_price_not_bid_tier() -> None:
    timestamp = pd.Timestamp("2026-04-26T22:00:00Z")
    bids = [
        {
            "policy": "H-point",
            "configuration_id": C1_CONFIGURATION,
            "target_timestamp_utc": timestamp.isoformat(),
            "bid_price_eur_per_mwh": 90.0,
            "incremental_bid_volume_mwh": 2.0,
        },
        {
            "policy": "H-point",
            "configuration_id": C1_CONFIGURATION,
            "target_timestamp_utc": timestamp.isoformat(),
            "bid_price_eur_per_mwh": 50.0,
            "incremental_bid_volume_mwh": 3.0,
        },
    ]
    actual = SteelActualPriceBundle(
        delivery_day=EXPECTED_DELIVERY_DAY,
        timestamps_utc=(timestamp,),
        prices=(80.0,),
        granularity="hourly",
        time_step_hours=1.0,
    )
    result = clear_hourly_da_bids(bids, actual)
    assert result.hourly[0]["cleared_energy_mwh"] == pytest.approx(2.0)
    assert result.hourly[0]["settlement_cost_eur"] == pytest.approx(160.0)


def test_state_reporting_contains_eaf_phase_and_drp_boundary_state() -> None:
    state = SteelRollingState(
        "reporting",
        C1_CONFIGURATION,
        eaf_start_lag1=1,
        eaf_start_lag2=0,
        drp_last_pellet_input_t=100.0,
    ).snapshot()
    assert state["eaf_start_lag1"] == 1
    assert state["eaf_start_lag2"] == 0
    assert state["drp_last_pellet_input_t"] == pytest.approx(100.0)


def test_design_basis_is_45_minute_rounding_not_measured_minimum() -> None:
    parameters = EAFHeatStateParameters()
    assert parameters.derived_design_cycle_minutes == pytest.approx(42.5764)
    assert parameters.total_qh_steps * 15 == 45
    assert parameters.arc_energy_mwh_per_heat == pytest.approx(137.222222215)
    assert parameters.secondary_energy_mwh_per_heat == pytest.approx(10.075)
