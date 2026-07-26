from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

from pyomo.environ import (
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    RangeSet,
    SolverFactory,
    Var,
    maximize,
    minimize,
    value,
)
import pytest
from pyomo.opt import TerminationCondition
import yaml

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c_unified_physical_modelbuilder import (
    S44CModelBuilderError,
    _solve_with_optional_lexicographic_cost,
)
import steel.s4_4c_unified_physical_modelbuilder as modelbuilder
from steel.s4_4c5p_c0_wag_ng_allocation_envelope import (
    AllocationEnvelopeError,
    DEFAULT_CONFIG_PATH,
    _endpoint_ready,
    _execution_output_directory,
    _normal_case_id,
    _persist_failure_bundle,
    _persist_normal_control_evidence,
    _trajectory_endpoint_bound_uncertainty,
    annual_equivalent,
    frozen_case_matrix,
    load_config,
    min_normal_max_status,
)


def _solver():
    solver = SolverFactory("appsi_highs")
    if not solver.available(exception_flag=False):
        pytest.skip("HiGHS is unavailable for the allocation-envelope unit test.")
    return solver


@pytest.fixture
def local_test_tmp(request: pytest.FixtureRequest):
    suffix = hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:12]
    path = (
        STEEL_ROOT.parents[2]
        / "tmp"
        / f"allocation_envelope_v6_test_{os.getpid()}_{suffix}"
    )
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _tiny_c0_model() -> ConcreteModel:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 2)
    model.final_product_output = Var(model.TIME, domain=NonNegativeReals)
    model.priced_flow = Var(model.TIME, domain=NonNegativeReals)
    model.wag_generator_electricity_mwh = Var(
        model.TIME, bounds=(0.0, 10.0)
    )
    model.ng_generator_electricity_mwh = Var(
        model.TIME, bounds=(0.0, 10.0)
    )
    model.coke_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.sinter_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.hot_iron_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.cold_slab_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.generator_split = Constraint(
        model.TIME,
        rule=lambda m, t: (
            m.wag_generator_electricity_mwh[t]
            + m.ng_generator_electricity_mwh[t]
            == 10.0
        ),
    )
    model.rolling_production_deadline = Constraint(
        [2],
        rule=lambda m, hour: sum(
            m.final_product_output[t] for t in range(hour)
        )
        >= 2.0,
    )
    for hour in model.TIME:
        model.final_product_output[hour].fix(1.0)
        model.priced_flow[hour].fix(1.0)
        model.coke_inventory[hour].fix(2.0)
        model.sinter_inventory[hour].fix(3.0)
        model.hot_iron_inventory[hour].fix(4.0)
        model.cold_slab_inventory[hour].fix(5.0)
    model.static_price_naive_objective = Objective(
        expr=sum(
            model.wag_generator_electricity_mwh[t] for t in model.TIME
        ),
        sense=minimize,
    )
    return model


def _cost_policy() -> dict[str, object]:
    return {
        "objective_tolerance_eur": 0.01,
        "flows": [
            {
                "configuration": "C0",
                "flow_id": "test_fixed_cost",
                "model_component_attribute": "priced_flow",
                "price_eur_by_hour": [1.0, 1.0, 1.0],
            }
        ],
    }


def _native_optimal_record(variable_count: int) -> dict[str, object]:
    return {
        "status": "optimal",
        "status_code": 2,
        "solution_count": 1,
        "objective_sense": "minimise",
        "objective_term_count": 0,
        "max_primal_violation": 0.0,
        "constraint_violation": 0.0,
        "bound_violation": 0.0,
        "integrality_violation": None,
        "model_fingerprint": "0x00000000",
        "row_count": 1,
        "column_count": variable_count,
        "binary_count": 0,
        "iis_created": False,
        "iis_path": None,
    }


def _normal_capture_and_matching_endpoint(
    directory: Path,
) -> tuple[Path, dict[str, object], ConcreteModel]:
    capture_path = directory / "complete_normal.json.gz"
    provenance = {
        "expected_parent_head": "test",
        "normal_controller_schedule_sha256": "1" * 64,
        "controller_schedule_row_sha256": "2" * 64,
        "record_finalized": True,
    }
    normal_model = _tiny_c0_model()
    _solve_with_optional_lexicographic_cost(
        normal_model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
        normal_solution_capture={
            "enabled": True,
            "path": str(capture_path),
            "replan_index": 0,
            "controller_state": {"executed_hours_before": 0},
            "provenance": provenance,
        },
    )
    endpoint_model = _tiny_c0_model()
    _solve_with_optional_lexicographic_cost(
        endpoint_model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
    )
    return capture_path, provenance, endpoint_model


def test_absent_hook_leaves_normal_objective_path_unchanged() -> None:
    model = _tiny_c0_model()
    _, metadata = _solve_with_optional_lexicographic_cost(
        model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
    )
    assert "allocation_envelope_active" not in metadata
    assert not hasattr(model, "allocation_envelope_objective")
    assert model.static_price_naive_objective.active
    assert sum(
        value(model.wag_generator_electricity_mwh[t]) for t in model.TIME
    ) == pytest.approx(0.0)


def test_warm_start_loads_only_free_values_and_preserves_prefixed_state(
    local_test_tmp: Path,
) -> None:
    capture_path, _, endpoint_model = _normal_capture_and_matching_endpoint(
        local_test_tmp
    )
    with gzip.open(capture_path, "rt", encoding="utf-8") as handle:
        capture = json.load(handle)
    saved_by_name = {row["name"]: row for row in capture["variables"]}
    free_variable = endpoint_model.wag_generator_electricity_mwh[0]
    fixed_variable = endpoint_model.final_product_output[0]
    fixed_value_before = value(fixed_variable)
    free_variable.set_value(7.0)
    record_hash = hashlib.sha256(capture_path.read_bytes()).hexdigest()
    audit = modelbuilder._prepare_allocation_endpoint_warm_start(
        endpoint_model,
        diagnostic={
            "case_id": "warm_start_values",
            "replan_index": 0,
            "normal_solution_record_path": str(capture_path),
            "normal_solution_record_sha256": record_hash,
            "oracle_directory": str(local_test_tmp / "warm_start_audit"),
        },
        normal_oracle={"saved_normal_solution_sha256": record_hash},
        tolerance=1e-6,
    )
    assert audit["status"] == "pass"
    assert audit["assignment_count"] == sum(
        not row["fixed"] for row in capture["variables"]
    )
    assert audit["endpoint_fixed_overwrite_count"] == 0
    assert audit["endpoint_fixed_state_unchanged"]
    assert audit["loaded_start_audit"]["feasible"]
    assert not free_variable.fixed
    assert value(free_variable) == pytest.approx(
        saved_by_name[free_variable.name]["value"]
    )
    assert fixed_variable.fixed
    assert value(fixed_variable) == fixed_value_before
    assert Path(audit["audit_path"]).is_file() or (
        STEEL_ROOT.parents[2] / audit["audit_path"]
    ).is_file()


def test_invalid_warm_start_fails_before_endpoint_solve(
    local_test_tmp: Path,
) -> None:
    capture_path, _, endpoint_model = _normal_capture_and_matching_endpoint(
        local_test_tmp
    )
    with gzip.open(capture_path, "rt", encoding="utf-8") as handle:
        capture = json.load(handle)
    target = next(
        row
        for row in capture["variables"]
        if row["name"] == "wag_generator_electricity_mwh[0]"
    )
    target["value"] = 99.0
    with gzip.open(capture_path, "wt", encoding="utf-8") as handle:
        json.dump(capture, handle, sort_keys=True)
    record_hash = hashlib.sha256(capture_path.read_bytes()).hexdigest()
    audit_directory = local_test_tmp / "invalid_warm_start"
    with pytest.raises(
        S44CModelBuilderError,
        match="warm-start values failed",
    ):
        modelbuilder._prepare_allocation_endpoint_warm_start(
            endpoint_model,
            diagnostic={
                "case_id": "invalid_warm_start",
                "replan_index": 0,
                "normal_solution_record_path": str(capture_path),
                "normal_solution_record_sha256": record_hash,
                "oracle_directory": str(audit_directory),
            },
            normal_oracle={"saved_normal_solution_sha256": record_hash},
            tolerance=1e-6,
        )
    audit = json.loads(
        (audit_directory / "endpoint_warm_start_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["status"] == "fail_closed"
    assert audit["failure_stage"] == "loaded_start_feasibility_audit"
    assert not audit["loaded_start_audit"]["feasible"]


def test_gurobi_hook_uses_warmstart_only_for_endpoint_solve(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_path = local_test_tmp / "warmstart_capture.json.gz"
    provenance = {"expected_parent_head": "test"}
    normal_model = _tiny_c0_model()
    _solve_with_optional_lexicographic_cost(
        normal_model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
        normal_solution_capture={
            "enabled": True,
            "path": str(capture_path),
            "replan_index": 0,
            "controller_state": {},
            "provenance": provenance,
        },
    )
    with gzip.open(capture_path, "rt", encoding="utf-8") as handle:
        variable_count = int(json.load(handle)["variable_count"])
    monkeypatch.setattr(
        modelbuilder,
        "_native_gurobi_zero_objective_check",
        lambda *args, **kwargs: _native_optimal_record(variable_count),
    )

    delegate = _solver()

    class RecordingGurobiSolver:
        name = "gurobi"

        def __init__(self) -> None:
            self.options: dict[str, object] = {}
            self.calls: list[dict[str, object]] = []
            self.option_snapshots: list[dict[str, object]] = []

        def solve(self, model, **kwargs):
            self.calls.append(dict(kwargs))
            self.option_snapshots.append(dict(self.options))
            delegated = dict(kwargs)
            delegated.pop("warmstart", None)
            return delegate.solve(model, **delegated)

    solver = RecordingGurobiSolver()
    endpoint_model = _tiny_c0_model()
    _, metadata = _solve_with_optional_lexicographic_cost(
        endpoint_model,
        solver=solver,
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
        allocation_envelope_diagnostic={
            "endpoint": "max",
            "execution_hours": 2,
            "state_tolerance": 1e-6,
            "normal_solution_record_path": str(capture_path),
            "normal_solution_record_sha256": hashlib.sha256(
                capture_path.read_bytes()
            ).hexdigest(),
            "normal_solution_expected_provenance": provenance,
            "oracle_directory": str(local_test_tmp / "recording_oracle"),
            "iis_evidence_sha256": "6" * 64,
            "endpoint_solver_accuracy_schema": "steel_endpoint_solver_accuracy_v1",
            "endpoint_relative_mip_gap": 0.0,
            "endpoint_absolute_mip_gap_mwh": 0.001,
            "endpoint_bound_comparison_epsilon_mwh": 1e-9,
            "endpoint_annual_bound_uncertainty_limit_mwh_y": 1.0,
        },
    )
    warmstart_calls = [
        call for call in solver.calls if call.get("warmstart") is True
    ]
    assert len(warmstart_calls) == 1
    assert solver.calls[-1].get("warmstart") is True
    assert all("warmstart" not in call for call in solver.calls[:-1])
    assert solver.option_snapshots[-1]["MIPGap"] == 0.0
    assert solver.option_snapshots[-1]["MIPGapAbs"] == 0.001
    assert all(
        "MIPGap" not in options and "MIPGapAbs" not in options
        for options in solver.option_snapshots[:-1]
    )
    assert all(
        name not in solver.options
        for name in (
            "DualReductions",
            "InfUnbdInfo",
            "FeasibilityTol",
            "MIPGap",
            "MIPGapAbs",
            "LogFile",
        )
    )
    assert metadata["allocation_envelope_warmstart_solver_argument"]
    assert metadata["allocation_envelope_warm_start_status"] == "pass"
    expected_evidence_directory = (local_test_tmp / "recording_oracle").resolve()
    assert Path(
        metadata["allocation_envelope_warm_start_audit_path"]
    ).resolve().parent == expected_evidence_directory
    assert Path(
        metadata["allocation_envelope_endpoint_solver_log_path"]
    ).resolve().parent == expected_evidence_directory
    assert metadata["allocation_envelope_endpoint_accuracy_schema"] == (
        "steel_endpoint_solver_accuracy_v1"
    )
    assert metadata["allocation_envelope_endpoint_relative_mip_gap_target"] == 0.0
    assert metadata[
        "allocation_envelope_endpoint_absolute_mip_gap_target_mwh"
    ] == 0.001
    assert metadata[
        "allocation_envelope_endpoint_objective_bound_audit_status"
    ] == "pass"


@pytest.mark.parametrize(
    ("endpoint", "sense", "expected_wag_mwh"),
    (("min", minimize, 0.0), ("max", maximize, 20.0)),
)
def test_endpoint_is_executed_hours_only_wag_only_and_preserves_state_and_cost(
    endpoint: str,
    sense,
    expected_wag_mwh: float,
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_path = local_test_tmp / "complete_normal.json.gz"
    capture_provenance = {
        "expected_parent_head": "test",
        "config_sha256": "1" * 64,
        "schedule_sha256": "2" * 64,
        "controller_sha256": "3" * 64,
        "source_sha256": "4" * 64,
        "git_diff_sha256": "5" * 64,
    }
    normal_model = _tiny_c0_model()
    _solve_with_optional_lexicographic_cost(
        normal_model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
        normal_solution_capture={
            "enabled": True,
            "path": str(capture_path),
            "replan_index": 0,
            "controller_state": {"executed_hours_before": 0},
            "provenance": capture_provenance,
        },
    )
    with gzip.open(capture_path, "rt", encoding="utf-8") as handle:
        capture = json.load(handle)
    assert capture["variable_count"] == len(capture["variables"])
    assert capture["schema_version"] == "steel_complete_normal_solution_v2"
    assert all(
        {
            "name",
            "value",
            "fixed",
            "fixed_value",
            "domain",
            "lb",
            "ub",
        }
        <= set(row)
        for row in capture["variables"]
    )
    assert len(capture["variable_name_sha256"]) == 64
    assert len(capture["variable_schema_sha256"]) == 64
    assert len(capture["variable_fixed_schema_sha256"]) == 64
    assert len(capture["model_structure_sha256"]) == 64

    monkeypatch.setattr(
        modelbuilder,
        "_native_gurobi_zero_objective_check",
        lambda *args, **kwargs: {
            "status": "optimal",
            "status_code": 2,
            "solution_count": 1,
            "objective_sense": "minimise",
            "objective_term_count": 0,
            "max_primal_violation": 0.0,
            "constraint_violation": 0.0,
            "bound_violation": 0.0,
            "integrality_violation": 0.0,
            "model_fingerprint": "0x00000000",
            "row_count": 1,
            "column_count": capture["variable_count"],
            "binary_count": 0,
            "iis_created": False,
            "iis_path": None,
        },
    )
    model = _tiny_c0_model()
    _, metadata = _solve_with_optional_lexicographic_cost(
        model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
        allocation_envelope_diagnostic={
            "endpoint": endpoint,
            "execution_hours": 2,
            "state_tolerance": 1e-6,
            "normal_solution_record_path": str(capture_path),
            "normal_solution_record_sha256": hashlib.sha256(
                capture_path.read_bytes()
            ).hexdigest(),
            "normal_solution_expected_provenance": capture_provenance,
            "oracle_directory": str(local_test_tmp / f"oracle_{endpoint}"),
            "iis_evidence_sha256": "6" * 64,
        },
    )
    assert model.allocation_envelope_objective.sense == sense
    objective_text = str(model.allocation_envelope_objective.expr)
    assert "wag_generator_electricity_mwh[0]" in objective_text
    assert "wag_generator_electricity_mwh[1]" in objective_text
    assert "wag_generator_electricity_mwh[2]" not in objective_text
    assert "ng_generator_electricity_mwh" not in objective_text
    assert not hasattr(model, "procurement_cost_optimum_lower_audit")
    assert hasattr(model, "procurement_cost_optimum_preservation")
    assert metadata["allocation_envelope_objective_value_mwh"] == pytest.approx(
        expected_wag_mwh
    )
    assert sum(
        value(model.ng_generator_electricity_mwh[t]) for t in range(2)
    ) == pytest.approx(20.0 - expected_wag_mwh)
    assert metadata["allocation_envelope_termination_condition"].lower() == "optimal"
    assert metadata["primary_cost_termination_condition"].lower() == "optimal"
    assert metadata["primary_cost_best_bound_availability"] == "available"
    assert metadata["allocation_envelope_primary_objective_audit_status"] == "pass"
    assert metadata["allocation_envelope_best_bound_audit_status"] == "pass"
    assert metadata[
        "allocation_envelope_normal_incumbent_min_formulation_feasible"
    ]
    assert metadata[
        "allocation_envelope_normal_incumbent_max_formulation_feasible"
    ]
    assert metadata["allocation_envelope_cost_minus_primary_eur"] == pytest.approx(
        0.0
    )
    assert metadata["allocation_envelope_max_state_residual"] <= 1e-6
    assert (
        metadata["allocation_envelope_endpoint_handoff_hash"]
        == metadata["allocation_envelope_raw_endpoint_handoff_hash"]
    )
    incumbent_audit = metadata[
        "allocation_envelope_normal_incumbent_feasibility_audit"
    ]
    assert incumbent_audit["feasible"]
    assert incumbent_audit["constraint_count"] > 0
    assert incumbent_audit["variable_count"] > 0
    assert incumbent_audit["cost_cap_present"]
    assert incumbent_audit["production_and_state_preservation_present"]
    assert incumbent_audit["objective_definition_valid"]
    assert incumbent_audit["single_absolute_tolerance"] == 1e-6
    assert (
        metadata["allocation_envelope_effective_state_tolerance"] == 1e-6
    )
    assert (
        metadata["allocation_envelope_deactivated_deadline_row"]
        == "rolling_production_deadline[2]"
    )
    assert not model.rolling_production_deadline[2].active
    assert hasattr(
        model, "allocation_envelope_executed_final_product_preservation"
    )
    assert hasattr(model, "allocation_envelope_cold_slab_inventory_preservation")
    assert metadata["allocation_envelope_normal_feasibility_oracle_status"] == "pass"
    assert metadata["allocation_envelope_endpoint_prefixed_overwrite_count"] == 0
    assert metadata["allocation_envelope_warm_start_status"] == "pass"
    assert metadata["allocation_envelope_warm_start_fixed_overwrite_count"] == 0
    assert metadata[
        "allocation_envelope_warm_start_max_constraint_violation"
    ] <= 1e-6
    assert (
        metadata["allocation_envelope_endpoint_fixed_state_sha256_before"]
        == metadata["allocation_envelope_endpoint_fixed_state_sha256_after"]
    )


@pytest.mark.parametrize(
    ("endpoint", "lower_bound", "upper_bound", "expected_bound"),
    (
        ("min", 9.9995, 12.0, 9.9995),
        ("max", 8.0, 10.0005, 10.0005),
    ),
)
def test_endpoint_bound_audit_uses_sense_correct_solver_bound(
    endpoint: str,
    lower_bound: float,
    upper_bound: float,
    expected_bound: float,
) -> None:
    audit = modelbuilder._allocation_endpoint_objective_bound_audit(
        SimpleNamespace(
            problem=SimpleNamespace(
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )
        ),
        endpoint=endpoint,
        incumbent_mwh=10.0,
    )
    assert audit["status"] == "pass"
    assert audit["best_bound_mwh"] == pytest.approx(expected_bound)
    assert audit["best_bound_attribute"] == (
        "lower_bound" if endpoint == "min" else "upper_bound"
    )


@pytest.mark.parametrize("raw_bound", (None, float("nan"), float("inf")))
def test_endpoint_bound_audit_fails_closed_for_missing_or_nonfinite_bound(
    raw_bound: float | None,
) -> None:
    audit = modelbuilder._allocation_endpoint_objective_bound_audit(
        SimpleNamespace(
            problem=SimpleNamespace(lower_bound=raw_bound, upper_bound=raw_bound)
        ),
        endpoint="max",
        incumbent_mwh=10.0,
    )
    assert audit["status"] == "fail"
    assert audit["best_bound_availability"] == "unavailable"


def test_endpoint_bound_audit_rejects_large_or_sense_inconsistent_gap() -> None:
    too_large = modelbuilder._allocation_endpoint_objective_bound_audit(
        SimpleNamespace(problem=SimpleNamespace(lower_bound=9.998, upper_bound=12.0)),
        endpoint="min",
        incumbent_mwh=10.0,
    )
    inconsistent = modelbuilder._allocation_endpoint_objective_bound_audit(
        SimpleNamespace(problem=SimpleNamespace(lower_bound=8.0, upper_bound=9.99)),
        endpoint="max",
        incumbent_mwh=10.0,
    )
    assert too_large["failure_reason"] == (
        "absolute_objective_bound_gap_exceeds_limit"
    )
    assert inconsistent["failure_reason"] == "sense_inconsistent_best_bound"


def _endpoint_bound_rows(
    *, endpoint: str, gap_mwh: float = 0.001
) -> list[dict[str, object]]:
    incumbent = 10.0
    bound = incumbent - gap_mwh if endpoint == "min" else incumbent + gap_mwh
    return [
        {
            "allocation_envelope_execution_hours": 24,
            "allocation_envelope_objective_value_mwh": incumbent,
            "allocation_envelope_endpoint_best_bound_mwh": bound,
            "allocation_envelope_endpoint_objective_bound_abs_gap_mwh": gap_mwh,
            "allocation_envelope_endpoint_accuracy_schema": (
                "steel_endpoint_solver_accuracy_v1"
            ),
            "allocation_envelope_endpoint_best_bound_availability": "available",
            "allocation_envelope_endpoint_objective_bound_audit_status": "pass",
            "allocation_envelope_endpoint_bound_sense_status": "pass",
            "allocation_envelope_endpoint_relative_mip_gap_target": 0.0,
            "allocation_envelope_endpoint_absolute_mip_gap_target_mwh": 0.001,
        }
        for _ in range(7)
    ]


def test_trajectory_bound_uncertainty_is_separate_and_annualized() -> None:
    audit = _trajectory_endpoint_bound_uncertainty(
        _endpoint_bound_rows(endpoint="max"), endpoint="max"
    )
    assert audit["endpoint_objective_bound_uncertainty_mwh_y"] == pytest.approx(
        0.365
    )
    assert audit["reported_endpoint_value_basis"] == (
        "feasible_incumbent_executed_hours"
    )


def test_trajectory_bound_uncertainty_over_limit_fails_closed() -> None:
    with pytest.raises(AllocationEnvelopeError, match="annualized"):
        _trajectory_endpoint_bound_uncertainty(
            _endpoint_bound_rows(endpoint="min"),
            endpoint="min",
            annual_uncertainty_limit_mwh_y=0.3,
        )


def test_oracle_rejects_prefixed_saved_value_mismatch_without_mutation(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_path, provenance, endpoint_model = (
        _normal_capture_and_matching_endpoint(local_test_tmp)
    )
    endpoint_model.final_product_output[0].fix(1.01)
    before_value = value(endpoint_model.final_product_output[0])
    before_active_objectives = {
        objective.name
        for objective in endpoint_model.component_data_objects(
            Objective, active=True
        )
    }
    native_called = False

    def _unexpected_native(*args, **kwargs):
        nonlocal native_called
        native_called = True
        raise AssertionError("native oracle must not run after a fixed mismatch")

    monkeypatch.setattr(
        modelbuilder, "_native_gurobi_zero_objective_check", _unexpected_native
    )
    oracle_directory = local_test_tmp / "oracle_mismatch"
    with pytest.raises(
        S44CModelBuilderError,
        match="fixed-variable compatibility failed before mutation",
    ):
        modelbuilder._complete_normal_feasibility_oracle(
            endpoint_model,
            solver=_solver(),
            diagnostic={
                "case_id": "fixed_mismatch",
                "replan_index": 0,
                "normal_solution_record_path": str(capture_path),
                "normal_solution_record_sha256": hashlib.sha256(
                    capture_path.read_bytes()
                ).hexdigest(),
                "normal_solution_expected_provenance": provenance,
                "oracle_directory": str(oracle_directory),
            },
            tolerance=1e-6,
            base_model_structure_sha256=(
                modelbuilder._model_structure_sha256(endpoint_model)
            ),
        )
    assert not native_called
    assert endpoint_model.final_product_output[0].fixed
    assert value(endpoint_model.final_product_output[0]) == before_value
    assert {
        objective.name
        for objective in endpoint_model.component_data_objects(
            Objective, active=True
        )
    } == before_active_objectives
    assert not hasattr(
        endpoint_model, "allocation_envelope_normal_oracle_objective"
    )
    record = json.loads(
        (oracle_directory / "normal_feasibility_oracle.json").read_text(
            encoding="utf-8"
        )
    )
    audit = record["fixed_variable_compatibility_audit"]
    assert record["status"] == "fail_closed"
    assert audit["fixed_status_or_value_mismatch_count"] == 1
    assert audit["endpoint_prefixed_overwrite_count"] == 0


def test_oracle_leaves_matching_prefixed_values_and_restores_only_free_values(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_path, provenance, endpoint_model = (
        _normal_capture_and_matching_endpoint(local_test_tmp)
    )
    fixed_value_before = value(endpoint_model.final_product_output[0])
    free_variable = endpoint_model.wag_generator_electricity_mwh[0]
    assert not free_variable.fixed
    free_variable.set_value(7.0)
    free_value_before = value(free_variable)
    options_solver = _solver()
    options_before = dict(options_solver.options)
    with gzip.open(capture_path, "rt", encoding="utf-8") as handle:
        variable_count = int(json.load(handle)["variable_count"])
    monkeypatch.setattr(
        modelbuilder,
        "_native_gurobi_zero_objective_check",
        lambda *args, **kwargs: _native_optimal_record(variable_count),
    )
    result = modelbuilder._complete_normal_feasibility_oracle(
        endpoint_model,
        solver=options_solver,
        diagnostic={
            "case_id": "fixed_match",
            "replan_index": 0,
            "normal_solution_record_path": str(capture_path),
            "normal_solution_record_sha256": hashlib.sha256(
                capture_path.read_bytes()
            ).hexdigest(),
            "normal_solution_expected_provenance": provenance,
            "oracle_directory": str(local_test_tmp / "oracle_match"),
        },
        tolerance=1e-6,
        base_model_structure_sha256=(
            modelbuilder._model_structure_sha256(endpoint_model)
        ),
    )
    audit = result["fixed_variable_compatibility_audit"]
    assert result["status"] == "pass"
    assert audit["endpoint_prefixed_checked_count"] > 0
    assert audit["endpoint_prefixed_overwrite_count"] == 0
    assert audit["temporarily_fixed_count"] > 0
    assert audit["fixed_status_or_value_mismatch_count"] == 0
    assert audit["endpoint_fixed_state_sha256_before"] == audit[
        "endpoint_fixed_state_sha256_after"
    ]
    assert audit["endpoint_variable_state_sha256_before"] == audit[
        "endpoint_variable_state_sha256_after"
    ]
    assert endpoint_model.final_product_output[0].fixed
    assert value(endpoint_model.final_product_output[0]) == fixed_value_before
    assert not free_variable.fixed
    assert value(free_variable) == free_value_before
    assert not hasattr(
        endpoint_model, "allocation_envelope_normal_oracle_objective"
    )
    assert dict(options_solver.options) == options_before


def test_oracle_restores_free_values_objectives_and_options_when_write_fails(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_path, provenance, endpoint_model = (
        _normal_capture_and_matching_endpoint(local_test_tmp)
    )
    free_variable = endpoint_model.wag_generator_electricity_mwh[0]
    free_variable.set_value(7.0)
    free_value_before = value(free_variable)
    active_before = {
        objective.name
        for objective in endpoint_model.component_data_objects(
            Objective, active=True
        )
    }
    oracle_solver = _solver()
    oracle_solver.options["sentinel"] = "unchanged"
    options_before = dict(oracle_solver.options)

    def _fail_write(*args, **kwargs):
        raise RuntimeError("synthetic LP writer failure")

    monkeypatch.setattr(endpoint_model, "write", _fail_write)
    with pytest.raises(S44CModelBuilderError, match="pre_solve_lp_write"):
        modelbuilder._complete_normal_feasibility_oracle(
            endpoint_model,
            solver=oracle_solver,
            diagnostic={
                "case_id": "writer_failure",
                "replan_index": 0,
                "normal_solution_record_path": str(capture_path),
                "normal_solution_record_sha256": hashlib.sha256(
                    capture_path.read_bytes()
                ).hexdigest(),
                "normal_solution_expected_provenance": provenance,
                "oracle_directory": str(local_test_tmp / "oracle_write_fail"),
            },
            tolerance=1e-6,
            base_model_structure_sha256=(
                modelbuilder._model_structure_sha256(endpoint_model)
            ),
        )
    assert not free_variable.fixed
    assert value(free_variable) == free_value_before
    assert {
        objective.name
        for objective in endpoint_model.component_data_objects(
            Objective, active=True
        )
    } == active_before
    assert not hasattr(
        endpoint_model, "allocation_envelope_normal_oracle_objective"
    )
    assert dict(oracle_solver.options) == options_before


def test_oracle_solver_exception_persists_fail_closed_and_restores_state(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_path, provenance, endpoint_model = (
        _normal_capture_and_matching_endpoint(local_test_tmp)
    )
    free_variable = endpoint_model.wag_generator_electricity_mwh[0]
    free_variable.set_value(7.0)
    free_value_before = value(free_variable)
    active_before = {
        objective.name
        for objective in endpoint_model.component_data_objects(
            Objective, active=True
        )
    }

    class ExplodingSolver:
        name = "fake_non_gurobi"

        def __init__(self) -> None:
            self.options = {"sentinel": "unchanged"}

        def solve(self, model, load_solutions=False):
            raise RuntimeError("synthetic solver exception")

    solver = ExplodingSolver()
    options_before = dict(solver.options)
    native_called = False

    def _unexpected_native(*args, **kwargs):
        nonlocal native_called
        native_called = True
        raise AssertionError("native reread must not run after Pyomo failure")

    monkeypatch.setattr(
        modelbuilder, "_native_gurobi_zero_objective_check", _unexpected_native
    )
    oracle_directory = local_test_tmp / "oracle_solver_fail"
    with pytest.raises(
        S44CModelBuilderError, match="pyomo_zero_objective_solve"
    ):
        modelbuilder._complete_normal_feasibility_oracle(
            endpoint_model,
            solver=solver,
            diagnostic={
                "case_id": "solver_failure",
                "replan_index": 0,
                "normal_solution_record_path": str(capture_path),
                "normal_solution_record_sha256": hashlib.sha256(
                    capture_path.read_bytes()
                ).hexdigest(),
                "normal_solution_expected_provenance": provenance,
                "oracle_directory": str(oracle_directory),
            },
            tolerance=1e-6,
            base_model_structure_sha256=(
                modelbuilder._model_structure_sha256(endpoint_model)
            ),
        )
    assert not native_called
    assert not free_variable.fixed
    assert value(free_variable) == free_value_before
    assert {
        objective.name
        for objective in endpoint_model.component_data_objects(
            Objective, active=True
        )
    } == active_before
    assert not hasattr(
        endpoint_model, "allocation_envelope_normal_oracle_objective"
    )
    assert solver.options == options_before
    record = json.loads(
        (oracle_directory / "normal_feasibility_oracle.json").read_text(
            encoding="utf-8"
        )
    )
    assert record["status"] == "fail_closed"
    assert record["failure_stage"] == "pyomo_zero_objective_solve"
    assert record["exception"]["type"] == "RuntimeError"
    assert record["pyomo_solve"]["termination_condition"] == "not_run"
    assert record["native_gurobi_reread_solve"]["status"] == "not_run"
    audit = record["fixed_variable_compatibility_audit"]
    assert audit["endpoint_variable_state_sha256_before"] == audit[
        "endpoint_variable_state_sha256_after"
    ]


def test_fixed_status_and_value_change_the_fixed_schema_hash() -> None:
    model = _tiny_c0_model()
    _solve_with_optional_lexicographic_cost(
        model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
    )
    records = modelbuilder._active_variable_records(model)
    _, structural_hash, fixed_hash = (
        modelbuilder._variable_name_and_schema_hashes(records)
    )
    model.final_product_output[0].fix(1.0001)
    changed_records = modelbuilder._active_variable_records(model)
    _, changed_structural_hash, changed_fixed_hash = (
        modelbuilder._variable_name_and_schema_hashes(changed_records)
    )
    assert structural_hash == changed_structural_hash
    assert fixed_hash != changed_fixed_hash


def test_envelope_rejects_primary_cost_feasible_without_optimality() -> None:
    class FeasibleOnlyPrimarySolver:
        def __init__(self) -> None:
            self.inner = _solver()

        def solve(self, model):
            result = self.inner.solve(model)
            result.solver.termination_condition = TerminationCondition.feasible
            return result

    with pytest.raises(
        S44CModelBuilderError,
        match="primary procurement-cost stage must terminate optimal",
    ):
        _solve_with_optional_lexicographic_cost(
            _tiny_c0_model(),
            solver=FeasibleOnlyPrimarySolver(),
            configuration_id="C0_current_BF_BOF_reference",
            deterministic_cost_policy=_cost_policy(),
            allocation_envelope_diagnostic={
                "endpoint": "max",
                "execution_hours": 2,
                "state_tolerance": 1e-6,
            },
        )


def test_envelope_rejects_any_extra_state_or_solver_allowance() -> None:
    with pytest.raises(
        S44CModelBuilderError,
        match="absolute feasibility tolerance is not exactly 1e-6",
    ):
        _solve_with_optional_lexicographic_cost(
            _tiny_c0_model(),
            solver=_solver(),
            configuration_id="C0_current_BF_BOF_reference",
            deterministic_cost_policy=_cost_policy(),
            allocation_envelope_diagnostic={
                "endpoint": "max",
                "execution_hours": 2,
                "state_tolerance": 2e-6,
            },
        )


def test_frozen_matrix_is_two_candidates_two_validation_cases_two_endpoints() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    matrix = frozen_case_matrix(config)
    assert len(matrix) == 8
    assert {row["candidate_id"] for row in matrix} == {
        "recovery_bg30_ng55",
        "recovery_bg30_ng30",
    }
    assert {row["scenario_id"] for row in matrix} == {
        "calm_price_insensitive",
        "volatile_negative_governed_y_pred",
    }
    assert {row["period_id"] for row in matrix} == {
        "validation_2024-02-12",
        "validation_2024-07-01",
    }
    assert {row["endpoint"] for row in matrix} == {"min", "max"}
    assert all(row["dataset_split"] == "validation" for row in matrix)
    assert all(row["price_field"] == "y_pred" for row in matrix)
    assert not any(row["perfect_foresight_oracle"] for row in matrix)
    assert "lower_cost_audit_tolerance_eur" not in config["experiment"]
    assert config["run_id"] == "steel_c5_wag_ng_allocation_envelope_v6_20260726"
    assert (
        config["experiment"]["scratch_root"]
        == "tmp/steel_c5_envelope_v6_cases"
    )
    assert config["experiment"]["endpoint_solver_accuracy_schema"] == (
        "steel_endpoint_solver_accuracy_v1"
    )
    assert config["experiment"]["endpoint_relative_mip_gap"] == 0.0
    assert config["experiment"]["endpoint_absolute_mip_gap_mwh"] == 0.001
    assert config["experiment"]["endpoint_bound_comparison_epsilon_mwh"] == 1e-9
    assert config["experiment"][
        "endpoint_annual_bound_uncertainty_limit_mwh_y"
    ] == 1.0
    longest_oracle_path = (
        STEEL_ROOT.parents[2]
        / config["experiment"]["scratch_root"]
        / "alloc__recovery_bg30_ng55__volatile_negative_governed_y_pred__max"
        / "first_failure_evidence"
        / "oracle_r03"
        / "normal_feasibility_oracle.lp"
    )
    assert len(str(longest_oracle_path)) < 240
    assert config["experiment"]["immutable_physical_contract"] == {
        "electricity_background_percent": 30.0,
        "wag_generation_yield_overrides_by_configuration": {},
        "generator_electricity_efficiency": 0.345,
        "generator_electrical_capacity_mw": 770.0,
        "generator_total_fuel_volume_cap_nm3_h": 900000.0,
        "export_allowed": False,
        "fixed_full_site_ng_pj_y": 8.005,
        "flexible_other_site_heat_service_envelope_pj_y": 3.07,
        "physical_ng_bridge_changed": False,
        "operating_rules_changed": False,
        "route_logic_changed": False,
    }


def test_metric_conversion_and_min_normal_max_logic() -> None:
    assert annual_equivalent(168.0, 168) == pytest.approx(8760.0)
    assert min_normal_max_status(1.0, 2.0, 3.0, 1e-6) == "pass"
    assert min_normal_max_status(2.1, 2.0, 3.0, 1e-6) == "fail"
    assert min_normal_max_status(1.0, 3.1, 3.0, 1e-6) == "fail"


def test_four_current_normal_control_ids_are_distinct_from_endpoints() -> None:
    ids = {
        _normal_case_id(candidate, scenario)
        for candidate in ("recovery_bg30_ng55", "recovery_bg30_ng30")
        for scenario in (
            "calm_price_insensitive",
            "volatile_negative_governed_y_pred",
        )
    }
    assert len(ids) == 4
    assert all(value.startswith("normal__") for value in ids)
    assert not any("__min" in value or "__max" in value for value in ids)


def test_targeted_outputs_cannot_overwrite_the_full_run_root(
    local_test_tmp: Path,
) -> None:
    primary = local_test_tmp / "full_run"
    assert _execution_output_directory(
        primary,
        diagnostic_case_id=None,
        diagnostic_replan_index=None,
        oracle_only=False,
    ) == primary
    oracle_path = _execution_output_directory(
        primary,
        diagnostic_case_id=(
            "alloc__recovery_bg30_ng30__"
            "volatile_negative_governed_y_pred__max"
        ),
        diagnostic_replan_index=4,
        oracle_only=True,
    )
    endpoint_path = _execution_output_directory(
        primary,
        diagnostic_case_id=(
            "alloc__recovery_bg30_ng30__"
            "volatile_negative_governed_y_pred__max"
        ),
        diagnostic_replan_index=4,
        oracle_only=False,
    )
    assert oracle_path != primary
    assert endpoint_path != primary
    assert oracle_path != endpoint_path
    assert primary in oracle_path.parents
    assert primary in endpoint_path.parents


def test_all_governed_targeted_output_paths_leave_windows_path_margin() -> None:
    primary = (
        STEEL_ROOT.parents[2]
        / "data"
        / "03_Optimisation"
        / "runs"
        / "steel_c5_wag_ng_allocation_envelope_v6_20260726"
    ).resolve()
    governed_filenames = (
        "normal_solution_record_manifest.csv",
        "normal_solution_records/normal_13.json.gz",
        "first_failure_evidence/oracle_r06/normal_feasibility_oracle.json",
        "first_failure_evidence/oracle_r06/normal_feasibility_oracle.lp",
    )
    for candidate in ("recovery_bg30_ng55", "recovery_bg30_ng30"):
        for scenario in (
            "calm_price_insensitive",
            "volatile_negative_governed_y_pred",
        ):
            for endpoint in ("min", "max"):
                case_id = f"alloc__{candidate}__{scenario}__{endpoint}"
                for oracle_only in (False, True):
                    output = _execution_output_directory(
                        primary,
                        diagnostic_case_id=case_id,
                        diagnostic_replan_index=6,
                        oracle_only=oracle_only,
                    )
                    for filename in governed_filenames:
                        assert len(str(output / filename)) < 240


def test_endpoint_cache_fails_closed_when_fingerprints_are_missing() -> None:
    assert not _endpoint_ready(
        DEFAULT_CONFIG_PATH.parent / "__missing_allocation_envelope_cache__",
        expected_overrides={"run_id": "missing"},
        physical_config_sha256="0" * 64,
    )


def test_endpoint_cache_requires_exact_input_and_model_fingerprints(
    local_test_tmp: Path,
) -> None:
    tmp_path = local_test_tmp
    schedule_hash = "2" * 64
    normal_records: dict[str, dict[str, object]] = {}
    expected_overrides = {
        "run_id": "fingerprinted",
        "c0_allocation_envelope_diagnostic": {
            "endpoint": "max",
            "normal_controller_schedule_sha256": schedule_hash,
            "normal_solution_records_by_replan": normal_records,
            "endpoint_solver_accuracy_schema": "steel_endpoint_solver_accuracy_v1",
            "endpoint_relative_mip_gap": 0.0,
            "endpoint_absolute_mip_gap_mwh": 0.001,
            "endpoint_bound_comparison_epsilon_mwh": 1e-9,
            "endpoint_annual_bound_uncertainty_limit_mwh_y": 1.0,
        },
    }
    physical_hash = "1" * 64
    source_path = STEEL_ROOT.parents[2] / "AGENTS.md"
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    (tmp_path / "run_summary.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8"
    )
    (tmp_path / "config_resolved.yaml").write_text(
        yaml.safe_dump({"scenario_overrides_applied": expected_overrides}),
        encoding="utf-8",
    )
    (tmp_path / "input_manifest.json").write_text(
        json.dumps(
            {
                "config_sha256": physical_hash,
                "active_model_input_files": [
                    {"path": "AGENTS.md", "sha256": source_hash}
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "code_version.json").write_text(
        json.dumps(
            {"git_commit": "373d0bbde6ae76466ce8ee76afdc4aa5b93f2e51"}
        ),
        encoding="utf-8",
    )
    fields = [
        "configuration_id",
        "replan_index",
        "termination_condition",
        "primary_cost_termination_condition",
        "primary_cost_best_bound_availability",
        "allocation_envelope_termination_condition",
        "allocation_envelope_cost_minus_primary_eur",
        "allocation_envelope_primary_objective_audit_status",
            "allocation_envelope_best_bound_audit_status",
            "allocation_envelope_normal_feasibility_oracle_status",
            "allocation_envelope_effective_state_tolerance",
            "allocation_envelope_max_state_residual",
            "allocation_envelope_deactivated_deadline_row",
            "allocation_envelope_normal_incumbent_min_formulation_feasible",
        "allocation_envelope_normal_incumbent_max_formulation_feasible",
        "allocation_envelope_normal_feasibility_oracle_record_path",
        "allocation_envelope_normal_feasibility_oracle_record_sha256",
        "allocation_envelope_warm_start_status",
        "allocation_envelope_warm_start_assignment_count",
        "allocation_envelope_warm_start_source_record_sha256",
        "allocation_envelope_warmstart_solver_argument",
        "allocation_envelope_warm_start_audit_path",
        "allocation_envelope_warm_start_audit_sha256",
        "allocation_envelope_endpoint_solver_log_path",
        "allocation_envelope_endpoint_solver_log_sha256",
        "allocation_envelope_execution_hours",
        "allocation_envelope_objective_value_mwh",
        "allocation_envelope_endpoint_accuracy_schema",
        "allocation_envelope_endpoint_incumbent_basis",
        "allocation_envelope_endpoint_best_bound_availability",
        "allocation_envelope_endpoint_best_bound_mwh",
        "allocation_envelope_endpoint_objective_bound_abs_gap_mwh",
        "allocation_envelope_endpoint_objective_bound_audit_status",
        "allocation_envelope_endpoint_bound_sense_status",
        "allocation_envelope_endpoint_relative_mip_gap_target",
        "allocation_envelope_endpoint_absolute_mip_gap_target_mwh",
        "allocation_envelope_endpoint_bound_comparison_epsilon_mwh",
        "allocation_envelope_endpoint_solver_options_sha256",
        "allocation_envelope_endpoint_pre_solve_model_path",
        "allocation_envelope_endpoint_pre_solve_model_sha256",
    ]
    metrics_rows = []
    oracle_paths = []
    warm_paths = []
    for replan in range(7):
        normal_path = tmp_path / f"normal_{replan}.json.gz"
        normal_path.write_bytes(f"normal-{replan}".encode("utf-8"))
        normal_sha = hashlib.sha256(normal_path.read_bytes()).hexdigest()
        row_sha = hashlib.sha256(f"row-{replan}".encode()).hexdigest()
        normal_records[str(replan)] = {
            "path": str(normal_path),
            "sha256": normal_sha,
            "variable_name_sha256": "3" * 64,
            "variable_schema_sha256": "4" * 64,
            "variable_fixed_schema_sha256": "5" * 64,
            "provenance": {
                "controller_schedule_row_sha256": row_sha,
            },
        }
        oracle_path = tmp_path / f"oracle_{replan}.json"
        oracle = {
            "schema_version": "steel_normal_feasibility_oracle_v2",
            "status": "pass",
            "failure_stage": None,
            "dual_path_agreement": True,
            "pyomo_solve": {"optimal": True},
            "native_gurobi_reread_solve": {"status": "optimal"},
            "pre_solve_loaded_value_audit": {"feasible": True},
            "fixed_variable_compatibility_audit": {
                "fixed_status_or_value_mismatch_count": 0,
                "endpoint_prefixed_overwrite_count": 0,
                "unchanged_endpoint_fixed_state": True,
                "unchanged_endpoint_variable_state": True,
            },
            "saved_normal_solution_sha256": normal_sha,
            "variable_name_sha256": "3" * 64,
            "variable_schema_sha256": "4" * 64,
            "variable_fixed_schema_sha256": "5" * 64,
            "provenance": {
                "normal_controller_schedule_sha256": schedule_hash,
                "controller_schedule_row_sha256": row_sha,
            },
        }
        oracle_path.write_text(json.dumps(oracle), encoding="utf-8")
        oracle_paths.append((oracle_path, oracle))
        warm_start_path = tmp_path / f"warm_start_{replan}.json"
        warm_start = {
            "schema_version": "steel_endpoint_warm_start_v1",
            "status": "pass",
            "failure_stage": None,
            "source_normal_solution_sha256": normal_sha,
            "source_variable_name_sha256": "3" * 64,
            "source_variable_schema_sha256": "4" * 64,
            "source_variable_fixed_schema_sha256": "5" * 64,
            "assignment_count": 4357,
            "endpoint_fixed_overwrite_count": 0,
            "endpoint_fixed_state_unchanged": True,
            "loaded_start_audit": {
                "feasible": True,
                "tolerance": 1e-6,
            },
        }
        warm_start_path.write_text(
            json.dumps(warm_start), encoding="utf-8"
        )
        warm_paths.append((warm_start_path, warm_start))
        endpoint_log_path = tmp_path / f"endpoint_{replan}.log"
        endpoint_log_path.write_text(
            "Loaded user MIP start with objective 10\nOptimal solution found\n",
            encoding="utf-8",
        )
        endpoint_lp_path = tmp_path / f"endpoint_{replan}.lp"
        endpoint_lp_path.write_text("portable endpoint model", encoding="utf-8")
        solver_options_hash = hashlib.sha256(
            json.dumps(
                {"MIPGap": 0.0, "MIPGapAbs": 0.001, "warmstart": True},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        metrics_rows.append(
            {
                "configuration_id": "C0_current_BF_BOF_reference",
                "replan_index": replan,
                "termination_condition": "optimal",
                "primary_cost_termination_condition": "optimal",
                "primary_cost_best_bound_availability": "available",
                "allocation_envelope_termination_condition": "optimal",
                "allocation_envelope_cost_minus_primary_eur": 0.01,
                "allocation_envelope_primary_objective_audit_status": "pass",
                "allocation_envelope_best_bound_audit_status": "pass",
                "allocation_envelope_normal_feasibility_oracle_status": "pass",
                "allocation_envelope_effective_state_tolerance": 1e-6,
                "allocation_envelope_max_state_residual": 1e-6,
                "allocation_envelope_deactivated_deadline_row": "rolling_production_deadline[24]",
                "allocation_envelope_normal_incumbent_min_formulation_feasible": True,
                "allocation_envelope_normal_incumbent_max_formulation_feasible": True,
                "allocation_envelope_normal_feasibility_oracle_record_path": str(
                    oracle_path
                ),
                "allocation_envelope_normal_feasibility_oracle_record_sha256": hashlib.sha256(
                    oracle_path.read_bytes()
                ).hexdigest(),
                "allocation_envelope_warm_start_status": "pass",
                "allocation_envelope_warm_start_assignment_count": 4357,
                "allocation_envelope_warm_start_source_record_sha256": normal_sha,
                "allocation_envelope_warmstart_solver_argument": True,
                "allocation_envelope_warm_start_audit_path": str(
                    warm_start_path
                ),
                "allocation_envelope_warm_start_audit_sha256": hashlib.sha256(
                    warm_start_path.read_bytes()
                ).hexdigest(),
                "allocation_envelope_endpoint_solver_log_path": str(
                    endpoint_log_path
                ),
                "allocation_envelope_endpoint_solver_log_sha256": hashlib.sha256(
                    endpoint_log_path.read_bytes()
                ).hexdigest(),
                "allocation_envelope_execution_hours": 24,
                "allocation_envelope_objective_value_mwh": 10.0,
                "allocation_envelope_endpoint_accuracy_schema": (
                    "steel_endpoint_solver_accuracy_v1"
                ),
                "allocation_envelope_endpoint_incumbent_basis": "feasible_solution",
                "allocation_envelope_endpoint_best_bound_availability": "available",
                "allocation_envelope_endpoint_best_bound_mwh": 10.0005,
                "allocation_envelope_endpoint_objective_bound_abs_gap_mwh": 0.0005,
                "allocation_envelope_endpoint_objective_bound_audit_status": "pass",
                "allocation_envelope_endpoint_bound_sense_status": "pass",
                "allocation_envelope_endpoint_relative_mip_gap_target": 0.0,
                "allocation_envelope_endpoint_absolute_mip_gap_target_mwh": 0.001,
                "allocation_envelope_endpoint_bound_comparison_epsilon_mwh": 1e-9,
                "allocation_envelope_endpoint_solver_options_sha256": (
                    solver_options_hash
                ),
                "allocation_envelope_endpoint_pre_solve_model_path": str(
                    endpoint_lp_path
                ),
                "allocation_envelope_endpoint_pre_solve_model_sha256": hashlib.sha256(
                    endpoint_lp_path.read_bytes()
                ).hexdigest(),
            }
        )
    (tmp_path / "config_resolved.yaml").write_text(
        yaml.safe_dump({"scenario_overrides_applied": expected_overrides}),
        encoding="utf-8",
    )
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    for name in ("executed_hourly.csv", "validation_checks.csv"):
        (tmp_path / name).write_text("status\npass\n", encoding="utf-8")
    assert _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    missing_path, missing_payload = oracle_paths[0]
    missing_path.unlink()
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    missing_path.write_text(json.dumps(missing_payload), encoding="utf-8")
    metrics_rows[0][
        "allocation_envelope_normal_feasibility_oracle_record_sha256"
    ] = hashlib.sha256(missing_path.read_bytes()).hexdigest()
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    missing_path.write_text("tampered", encoding="utf-8")
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    missing_path.write_text(json.dumps(missing_payload), encoding="utf-8")
    warm_path, warm_payload = warm_paths[0]
    warm_path.write_text("tampered", encoding="utf-8")
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    warm_path.write_text(json.dumps(warm_payload), encoding="utf-8")
    metrics_rows[0][
        "allocation_envelope_warm_start_audit_sha256"
    ] = hashlib.sha256(warm_path.read_bytes()).hexdigest()
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    metrics_rows[0][
        "allocation_envelope_endpoint_objective_bound_abs_gap_mwh"
    ] = 0.002
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    metrics_rows[0][
        "allocation_envelope_endpoint_objective_bound_abs_gap_mwh"
    ] = 0.0005
    metrics_rows[0]["allocation_envelope_endpoint_solver_options_sha256"] = (
        "0" * 64
    )
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    metrics_rows[0]["allocation_envelope_endpoint_solver_options_sha256"] = (
        solver_options_hash
    )
    endpoint_lp_path = Path(
        str(metrics_rows[0]["allocation_envelope_endpoint_pre_solve_model_path"])
    )
    endpoint_lp_original = endpoint_lp_path.read_text(encoding="utf-8")
    endpoint_lp_path.write_text("tampered", encoding="utf-8")
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    endpoint_lp_path.write_text(endpoint_lp_original, encoding="utf-8")
    endpoint_log_path = Path(
        str(metrics_rows[0]["allocation_envelope_endpoint_solver_log_path"])
    )
    endpoint_log_original = endpoint_log_path.read_text(encoding="utf-8")
    endpoint_log_path.write_text("Optimal solution found\n", encoding="utf-8")
    metrics_rows[0]["allocation_envelope_endpoint_solver_log_sha256"] = (
        hashlib.sha256(endpoint_log_path.read_bytes()).hexdigest()
    )
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    endpoint_log_path.write_text(endpoint_log_original, encoding="utf-8")
    metrics_rows[0]["allocation_envelope_endpoint_solver_log_sha256"] = (
        hashlib.sha256(endpoint_log_path.read_bytes()).hexdigest()
    )
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics_rows)
    assert _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )
    manifest = json.loads(
        (tmp_path / "input_manifest.json").read_text(encoding="utf-8")
    )
    manifest["active_model_input_files"][0]["sha256"] = "0" * 64
    (tmp_path / "input_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assert not _endpoint_ready(
        tmp_path,
        expected_overrides=expected_overrides,
        physical_config_sha256=physical_hash,
    )


def test_full_normal_evidence_is_persisted_before_endpoint_work(
    local_test_tmp: Path,
) -> None:
    output = local_test_tmp / "persistent"
    provenance = [
        {"candidate_id": f"candidate_{index}", "status": "pass"}
        for index in range(4)
    ]
    schedules = [
        {
            "candidate_id": f"candidate_{index // 14}",
            "replan_index": index % 7,
            "configuration_id": (
                "C0_current_BF_BOF_reference"
                if index % 2 == 0
                else "C1_phase1_BF_BOF_plus_DRP_EAF"
            ),
        }
        for index in range(56)
    ]
    source_root = local_test_tmp / "scratch_normal_records"
    source_root.mkdir()
    records = []
    for index in range(56):
        source = source_root / f"normal_{index:02d}.json.gz"
        source.write_bytes(f"complete-normal-{index}".encode("utf-8"))
        records.append(
            {
                "candidate_id": f"candidate_{index // 14}",
                "scenario_id": "validation_scenario",
                "replan_index": index % 7,
                "configuration_id": (
                    "C0_current_BF_BOF_reference"
                    if index % 2 == 0
                    else "C1_phase1_BF_BOF_plus_DRP_EAF"
                ),
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    _persist_normal_control_evidence(
        output,
        provenance=provenance,
        normal_schedule_rows=schedules,
        normal_record_rows=records,
        require_full_matrix=True,
    )
    assert len(list(csv.DictReader((output / "primary_control_provenance.csv").open()))) == 4
    assert len(list(csv.DictReader((output / "normal_controller_schedule.csv").open()))) == 56
    manifest_path = output / "normal_solution_record_manifest.csv"
    manifest = list(csv.DictReader(manifest_path.open()))
    assert len(manifest) == 56
    shutil.rmtree(source_root)
    for row in manifest:
        bundled = STEEL_ROOT.parents[2] / row["path"]
        assert bundled.is_file()
        assert len(str(bundled.resolve())) < 240
        assert hashlib.sha256(bundled.read_bytes()).hexdigest() == row["sha256"]
        assert row["bundled_under_persistent_root"] == "True"


def test_failure_bundle_is_recursive_portable_and_hash_complete(
    local_test_tmp: Path,
) -> None:
    case_directory = local_test_tmp / "case"
    source = case_directory / "first_failure_evidence"
    oracle = source / "oracle_r04"
    oracle.mkdir(parents=True)
    (source / "endpoint_pre_solve_model.lp").write_text(
        "endpoint model", encoding="utf-8"
    )
    (source / "endpoint_solver.log").write_text(
        "infeasible", encoding="utf-8"
    )
    (source / "saved_normal_solution.json.gz").write_bytes(b"normal")
    saved_normal_hash = hashlib.sha256(
        (source / "saved_normal_solution.json.gz").read_bytes()
    ).hexdigest()
    (oracle / "normal_feasibility_oracle.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8"
    )
    (oracle / "normal_feasibility_oracle.lp").write_text(
        "oracle model", encoding="utf-8"
    )
    (source / "first_failure.json").write_text(
        json.dumps(
            {
                "replan_index": 4,
                "normal_controller_schedule_sha256": "1" * 64,
                "controller_schedule_row_sha256": "2" * 64,
                "controller_state": {"executed_hours_before": 96},
                "authoritative_schedule_row": {
                    "start_overrides": {"coke_store_initial_t": 1.0}
                },
                "start_state": {"coke_store_initial_t": 1.0},
                "deactivated_constraint_row": "rolling_production_deadline[24]",
                "cost_cap_rhs_eur": 10.01,
                "loaded_normal_cost_minus_cap_rhs_eur": 0.0,
                "bundled_saved_normal_solution": {
                    "path": "stale/source/path.json.gz",
                    "sha256": saved_normal_hash,
                    "source_sha256": saved_normal_hash,
                    "hash_matches_source": True,
                },
            }
        ),
        encoding="utf-8",
    )
    output = local_test_tmp / "output"
    manifest = _persist_failure_bundle(
        output,
        case_id="failed_case",
        source_directory=case_directory,
    )
    assert manifest["failed_replan_index"] == 4
    assert manifest["file_count"] == 6
    assert all(not Path(path).is_absolute() for path in manifest["files_sha256"])
    for relative, expected_hash in manifest["files_sha256"].items():
        path = output / relative
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
    persisted = json.loads(
        (output / "failure_evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert persisted["failed_replan_index"] == 4
    assert persisted["oracle_saved_normal_schedule_controller_linkage"][
        "normal_controller_schedule_sha256"
    ] == "1" * 64
    bundled = persisted["oracle_saved_normal_schedule_controller_linkage"][
        "bundled_saved_normal_solution"
    ]
    assert bundled["path"].startswith("failure_evidence/failed_case/")
    assert bundled["sha256"] == saved_normal_hash
    assert bundled["source_sha256"] == saved_normal_hash
    assert bundled["hash_matches_source"]


def test_endpoint_failure_json_binds_oracle_cost_state_and_file_hashes(
    local_test_tmp: Path,
) -> None:
    model = _tiny_c0_model()
    _solve_with_optional_lexicographic_cost(
        model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(),
    )
    evidence = local_test_tmp / "failure"
    evidence.mkdir()
    saved_normal = local_test_tmp / "normal.json.gz"
    saved_normal.write_bytes(b"normal-record")
    endpoint_lp = evidence / "endpoint_pre_solve_model.lp"
    endpoint_lp.write_text("endpoint-lp", encoding="utf-8")
    endpoint_log = evidence / "endpoint_solver.log"
    endpoint_log.write_text("infeasible", encoding="utf-8")
    saved_hash = hashlib.sha256(saved_normal.read_bytes()).hexdigest()
    oracle = {
        "oracle_record_path": "tmp/oracle.json",
        "oracle_record_sha256": "1" * 64,
        "status": "pass",
        "saved_normal_solution_path": "tmp/normal.json.gz",
        "saved_normal_solution_sha256": saved_hash,
        "variable_count": 1,
        "variable_name_sha256": "2" * 64,
        "variable_schema_sha256": "3" * 64,
        "variable_fixed_schema_sha256": "4" * 64,
        "fixed_variable_compatibility_audit": {
            "endpoint_prefixed_overwrite_count": 0
        },
        "pre_solve_loaded_value_audit": {
            "feasible": True,
            "max_constraint_violation": 0.0,
        },
        "pre_solve_symbolic_lp": "tmp/oracle.lp",
        "pre_solve_symbolic_lp_sha256": "5" * 64,
        "controller_state": {
            "authoritative_schedule_row": {
                "start_overrides": {"coke_store_initial_t": 1.0}
            }
        },
        "provenance": {
            "normal_controller_schedule_sha256": "6" * 64,
            "controller_schedule_row_sha256": "7" * 64,
        },
    }
    modelbuilder._preserve_allocation_endpoint_failure(
        model,
        SimpleNamespace(
            solver=SimpleNamespace(
                status="warning", termination_condition="infeasible"
            ),
            problem=SimpleNamespace(lower_bound=None),
        ),
        {
            "case_id": "case",
            "replan_index": 4,
            "failure_evidence_directory": str(evidence),
            "normal_solution_record_path": str(saved_normal),
        },
        endpoint="max",
        normal_snapshot={"executed_final_product_t": 1.0},
        primary_cost=10.0,
        primary_best_bound=9.999999,
        normal_cost=10.01,
        cost_tolerance=0.01,
        normal_oracle=oracle,
        warm_start_audit={
            "schema_version": "steel_endpoint_warm_start_v1",
            "status": "pass",
            "assignment_count": 4357,
            "assignment_variable_name_sha256": "8" * 64,
            "assignment_variable_schema_sha256": "9" * 64,
            "assignment_value_state_sha256": "a" * 64,
            "full_start_value_state_sha256": "b" * 64,
            "source_normal_solution_sha256": saved_hash,
            "endpoint_fixed_overwrite_count": 0,
            "loaded_start_audit": {
                "feasible": True,
                "max_constraint_violation": 0.0,
                "max_variable_bound_violation": 0.0,
                "max_integrality_violation": 0.0,
            },
            "audit_path": "tmp/endpoint_warm_start_audit.json",
            "audit_sha256": "c" * 64,
        },
        deactivated_deadline_name="rolling_production_deadline[24]",
        endpoint_pre_solve_model_path=endpoint_lp,
        endpoint_pre_solve_model_sha256=hashlib.sha256(
            endpoint_lp.read_bytes()
        ).hexdigest(),
        endpoint_solver_log_path=endpoint_log,
    )
    record = json.loads(
        (evidence / "first_failure.json").read_text(encoding="utf-8")
    )
    assert record["normal_feasibility_oracle"]["status"] == "pass"
    assert record["endpoint_warm_start"]["status"] == "pass"
    assert record["endpoint_warm_start"]["assignment_count"] == 4357
    assert record["endpoint_warm_start"][
        "source_normal_solution_sha256"
    ] == saved_hash
    assert record["normal_feasibility_oracle"][
        "variable_fixed_schema_sha256"
    ] == "4" * 64
    assert record["bundled_saved_normal_solution"]["hash_matches_source"]
    assert record["cost_cap_rhs_eur"] == pytest.approx(10.01)
    assert record["loaded_normal_cost_minus_cap_rhs_eur"] == pytest.approx(0.0)
    assert record["deactivated_constraint_row"] == "rolling_production_deadline[24]"
    assert record["endpoint_pre_solve_model_sha256"] == hashlib.sha256(
        endpoint_lp.read_bytes()
    ).hexdigest()
    assert record["endpoint_solver_log_sha256"] == hashlib.sha256(
        endpoint_log.read_bytes()
    ).hexdigest()
