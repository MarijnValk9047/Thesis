from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path

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
from steel.s4_4c5p_c0_wag_ng_allocation_envelope import (
    DEFAULT_CONFIG_PATH,
    _endpoint_ready,
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


@pytest.mark.parametrize(
    ("endpoint", "sense", "expected_wag_mwh"),
    (("min", minimize, 0.0), ("max", maximize, 20.0)),
)
def test_endpoint_is_executed_hours_only_wag_only_and_preserves_state_and_cost(
    endpoint: str, sense, expected_wag_mwh: float
) -> None:
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
        metadata["allocation_envelope_normal_handoff_hash"]
        == metadata["allocation_envelope_endpoint_handoff_hash"]
    )


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


def test_endpoint_cache_fails_closed_when_fingerprints_are_missing() -> None:
    assert not _endpoint_ready(
        DEFAULT_CONFIG_PATH.parent / "__missing_allocation_envelope_cache__",
        expected_overrides={"run_id": "missing"},
        physical_config_sha256="0" * 64,
    )


def test_endpoint_cache_requires_exact_input_and_model_fingerprints() -> None:
    tmp_path = (
        STEEL_ROOT.parents[2]
        / "tmp"
        / f"allocation_envelope_cache_fingerprint_test_{os.getpid()}"
    )
    tmp_path.mkdir(parents=True, exist_ok=False)
    expected_overrides = {"run_id": "fingerprinted"}
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
            {"git_commit": "5e25ec0c7c356d1b8773b0a25271f9b60bbdf057"}
        ),
        encoding="utf-8",
    )
    fields = [
        "configuration_id",
        "termination_condition",
        "primary_cost_termination_condition",
        "primary_cost_best_bound_availability",
        "allocation_envelope_termination_condition",
        "allocation_envelope_cost_minus_primary_eur",
        "allocation_envelope_primary_objective_audit_status",
        "allocation_envelope_best_bound_audit_status",
        "allocation_envelope_normal_incumbent_min_formulation_feasible",
        "allocation_envelope_normal_incumbent_max_formulation_feasible",
    ]
    with (tmp_path / "rolling_model_metrics.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for _ in range(7):
            writer.writerow(
                {
                    "configuration_id": "C0_current_BF_BOF_reference",
                    "termination_condition": "optimal",
                    "primary_cost_termination_condition": "optimal",
                    "primary_cost_best_bound_availability": "available",
                    "allocation_envelope_termination_condition": "optimal",
                    "allocation_envelope_cost_minus_primary_eur": 0.01,
                    "allocation_envelope_primary_objective_audit_status": "pass",
                    "allocation_envelope_best_bound_audit_status": "pass",
                    "allocation_envelope_normal_incumbent_min_formulation_feasible": True,
                    "allocation_envelope_normal_incumbent_max_formulation_feasible": True,
                }
            )
    for name in ("executed_hourly.csv", "validation_checks.csv"):
        (tmp_path / name).write_text("status\npass\n", encoding="utf-8")
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
