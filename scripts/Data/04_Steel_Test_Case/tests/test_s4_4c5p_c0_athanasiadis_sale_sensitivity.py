from __future__ import annotations

import inspect
import csv
import importlib.util
import json
import os
import shutil
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import sys

from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    RangeSet,
    SolverFactory,
    Var,
    minimize,
    value,
)
import pytest
import yaml

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c_unified_physical_modelbuilder import (
    S44CModelBuilderError,
    _add_rolling_production_progress_tracking,
    _build_c0_inputs,
    _build_c0_model,
    _active_variable_records,
    _audit_loaded_incumbent,
    _finalize_registered_validation_evidence,
    _install_registered_validation_relaxations,
    _finalize_sale_economic_validation_overlay,
    _install_sale_economic_validation_overlay,
    _capture_complete_normal_solution,
    _capture_sale_state_preservation_targets,
    _apply_sale_state_preservation,
    _finalize_sale_state_preservation,
    _load_tables,
    _sale_incumbent_containment_oracle,
    _solve_c1_configuration,
    _solve_with_optional_lexicographic_cost,
    _record_declared_variable_schema,
    _shared_variable_schema_diagnostics,
    _variable_structural_classification,
)
import steel.s4_4c_unified_physical_modelbuilder as modelbuilder
from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    _c0_real_anchor_energy_recovery_interfaces,
    _config as load_physical_config,
    _cost_acceptance_readiness,
    _electricity_boundary_levers,
    _governed_cost_ledger_validation,
    _initialize_normal_solution_capture_directory,
    _ledger_price_input_fingerprint,
    _validate_inventory_handoff_contract,
)
from steel.s4_4c5p_c0_real_anchor_mechanism_experiment import (
    candidate_overrides,
    load_mechanism_config,
)
from steel.s4_4c5p_phase5b_c0_export_sensitivity import (
    install_terminal_validation_extension,
)
from steel.validation_tolerance_policy import (
    CONSTRAINT_FAMILY_REGISTRY,
    SOLVER_NUMERICAL_TOLERANCE,
    constraint_family_rule,
    policy_contract,
)
from steel.s4_4c5p_c0_athanasiadis_sale_sensitivity import (
    DEFAULT_CONFIG_PATH,
    POSTHOC_REAUDIT_AUTHORIZATION_PHRASE,
    POSTHOC_REAUDIT_EXECUTION_MODE,
    POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
    POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256,
    POSTHOC_REAUDIT_SOURCE_CONFIG_SHA256,
    POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256,
    POSTHOC_REAUDIT_SOURCE_POLICY_CONTRACT,
    SUPPORTED_EXECUTION_MODES,
    SaleSensitivityError,
    authoritative_phase1_contract,
    cross_policy_state_guardrails,
    electricity_guardrails,
    executed_sale_accounting,
    execution_plan,
    frozen_case_matrix,
    handoff_continuity,
    implementation_fingerprints,
    load_config,
    _persist_failure_evidence,
    _expected_containment_replan_indices,
    _full_matrix_authorization_metadata,
    _case_ready,
    _child_failure_evidence,
    _mapping_sha256,
    _negative_price_validation_contract,
    _negative_price_validation_claimed,
    _prepare_attempt_output,
    _portable_persistent_path,
    _portableize_persistent_payload,
    _validate_containment_records,
    absent_disabled_result_equivalence,
    negative_price_export_coherence,
    policy_overrides,
    run_sale_sensitivity,
    run_posthoc_full_matrix_guardrail_reaudit,
    validate_config,
)
import steel.s4_4c5p_c0_athanasiadis_sale_sensitivity as sale_sensitivity_module


@pytest.fixture
def local_test_tmp(request: pytest.FixtureRequest):
    suffix = __import__("hashlib").sha256(request.node.nodeid.encode()).hexdigest()[:12]
    path = STEEL_ROOT.parents[2] / "tmp" / f"sale_sensitivity_test_{os.getpid()}_{suffix}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _solver():
    solver = SolverFactory("appsi_highs")
    if not solver.available(exception_flag=False):
        pytest.skip("HiGHS is unavailable for the Phase-2 unit test.")
    return solver


def _write_test_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _posthoc_source_fixture(local_test_tmp: Path) -> tuple[Path, Path]:
    governed_root = local_test_tmp / "governed"
    config = load_config()
    config["output_root"] = _portable_persistent_path(governed_root)
    config_path = local_test_tmp / "posthoc_config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    source = governed_root / "attempts" / POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID
    source.mkdir(parents=True)

    source_config = deepcopy(config)
    source_config["experiment"]["validation_tolerance_policy"] = dict(
        POSTHOC_REAUDIT_SOURCE_POLICY_CONTRACT
    )
    source_config.update(
        {
            "execution_mode": "full_matrix",
            "full_matrix_authorization_supplied": True,
            "full_matrix_reviewer_decision": "PASS",
            "attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
            "implementation_sha256": (
                POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
            ),
        }
    )
    assert _mapping_sha256(_full_matrix_authorization_metadata(source_config)) == (
        POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256
    )
    (source / "resolved_config.yaml").write_text(
        yaml.safe_dump(source_config, sort_keys=False), encoding="utf-8"
    )
    (source / "run_summary.json").write_text(
        json.dumps(
            {
                "status": "fail",
                "execution_mode": "full_matrix",
                "completed_trajectory_count": 8,
                "solver_model_count": 112,
                "guardrail_failure_count": 2,
                "held_out_periods_used": False,
                "candidate_promoted": False,
                "implementation_sha256": (
                    POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
                ),
            }
        ),
        encoding="utf-8",
    )
    (source / "run_identity.json").write_text(
        json.dumps(
            {
                "attempt_id": POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
                "execution_mode": "full_matrix",
                "diagnostic_case_id": None,
                "full_matrix_reviewer_decision": "PASS",
                "implementation_sha256": (
                    POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
                ),
                "config_sha256": POSTHOC_REAUDIT_SOURCE_CONFIG_SHA256,
                "full_matrix_authorization_metadata_sha256": (
                    POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256
                ),
            }
        ),
        encoding="utf-8",
    )
    (source / "code_version.json").write_text(
        json.dumps(
            {
                "git_commit": modelbuilder.EXPECTED_HEAD
                if hasattr(modelbuilder, "EXPECTED_HEAD")
                else "f2c4126b216707b132ca9bab43291b345e49b939",
                "implementation_sha256": (
                    POSTHOC_REAUDIT_SOURCE_IMPLEMENTATION_SHA256
                ),
                "full_matrix_authorization_metadata_sha256": (
                    POSTHOC_REAUDIT_SOURCE_AUTHORIZATION_METADATA_SHA256
                ),
            }
        ),
        encoding="utf-8",
    )
    (source / "implementation_fingerprints.json").write_text(
        json.dumps(
            {
                "current_head": "f2c4126b216707b132ca9bab43291b345e49b939",
                "expected_parent_head": (
                    "f2c4126b216707b132ca9bab43291b345e49b939"
                ),
            }
        ),
        encoding="utf-8",
    )

    case_rows = [
        {
            "case_id": f"sale__{candidate}__{scenario}__{policy}",
            "candidate_id": candidate,
            "scenario_id": scenario,
            "policy_id": policy,
            "status": "pass",
            "execution_mode": "full_matrix",
            "dataset_split": "validation",
            "price_field": "y_pred",
            "perfect_foresight_oracle": "False",
        }
        for candidate in ("recovery_bg30_ng55", "recovery_bg30_ng30")
        for scenario in (
            "calm_price_insensitive",
            "volatile_negative_governed_y_pred",
        )
        for policy in (
            "accepted_no_export_comparator",
            "athanasiadis_sale_enabled",
        )
    ]
    _write_test_csv(source / "case_status.csv", case_rows)
    solver_rows = [
        {
            "candidate_id": candidate,
            "scenario_id": scenario,
            "policy_id": policy,
            "configuration_id": configuration,
            "replan_index": replan,
            "solver_status": "ok",
            "termination_condition": "optimal",
        }
        for candidate in ("recovery_bg30_ng55", "recovery_bg30_ng30")
        for scenario in (
            "calm_price_insensitive",
            "volatile_negative_governed_y_pred",
        )
        for policy in (
            "accepted_no_export_comparator",
            "athanasiadis_sale_enabled",
        )
        for configuration in (
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        )
        for replan in range(7)
    ]
    _write_test_csv(source / "child_solver_summary.csv", solver_rows)

    target_case = (
        "sale__recovery_bg30_ng30__volatile_negative_governed_y_pred__"
        "accepted_no_export_comparator"
    )
    electricity_names = (
        "electricity_identity",
        "no_simultaneous_import_export",
        "no_grid_reexport",
        "export_bounded_by_internal_generation",
        "wag_and_ng_generation_exactly_separate",
        "accepted_comparator_export_zero",
    )
    guardrails: list[dict[str, object]] = []
    for case in case_rows:
        for name in electricity_names:
            edge = case["case_id"] == target_case and name in {
                "electricity_identity",
                "wag_and_ng_generation_exactly_separate",
            }
            guardrails.append(
                {
                    "case_id": case["case_id"],
                    "guardrail": name,
                    "max_residual": (
                        1.0000000543186616e-6 if edge else 0.0
                    ),
                    "status": "fail" if edge else "pass",
                }
            )
    other_counts = {
        "cross_policy_cumulative_progress_state": 4,
        "cross_policy_every_dynamic_handoff_state": 4,
        "cross_policy_executed_and_cumulative_production": 4,
        "cross_policy_terminal_handoff_snapshot_every_dynamic_state": 4,
        "inter_window_handoff_continuity": 8,
        "negative_price_export_coherence": 4,
        "ng_price_0_345_break_even_direction": 2,
        "real_model_containment_oracle_all_replans": 4,
        "sale_net_optimum_no_worse_than_identical_state_comparator": 4,
        "terminal_handoff_snapshot_complete": 8,
    }
    for name, count in other_counts.items():
        for index in range(count):
            row: dict[str, object] = {
                "case_id": f"preserved_{name}_{index}",
                "guardrail": name,
                "max_residual": (
                    3.637978807091713e-12
                    if name == "real_model_containment_oracle_all_replans"
                    else -1.0
                    if name == "sale_net_optimum_no_worse_than_identical_state_comparator"
                    else 0.0
                ),
                "status": "pass",
            }
            if name == "inter_window_handoff_continuity":
                row["result"] = "pass"
            if name == "ng_price_0_345_break_even_direction":
                row["allowed_tolerance"] = 1e-6
            if name == "sale_net_optimum_no_worse_than_identical_state_comparator":
                row["allowed_tolerance"] = 1.0
            guardrails.append(row)
    assert len(guardrails) == 94
    _write_test_csv(source / "physical_guardrails.csv", guardrails)
    return config_path, source


def _posthoc_fixture_source_contract(source: Path) -> dict[str, dict[str, object]]:
    return {
        path.name: {
            "size_bytes": path.stat().st_size,
            "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
        }
        for path in source.iterdir()
        if path.is_file()
    }


def _sale_model(*, demand: float = 5.0, wag_generation: float = 8.0) -> ConcreteModel:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 1)
    model.wag_generator_electricity_mwh = Var(model.TIME, bounds=(0.0, wag_generation))
    model.ng_generator_electricity_mwh = Var(model.TIME, domain=NonNegativeReals)
    model.ng_fuel_mwh = Var(model.TIME, domain=NonNegativeReals)
    model.final_product_output = Expression(
        model.TIME, rule=lambda _m, _t: 1.2345678901234567
    )
    model.bof_crude_steel_output = Expression(
        model.TIME, rule=lambda _m, _t: 1.3
    )
    model.c0_hsm_final_product_output = Expression(
        model.TIME, rule=lambda _m, _t: 0.9
    )
    model.c0_dsp_final_product_output = Expression(
        model.TIME, rule=lambda _m, _t: 0.3345678901234567
    )
    model.coke_inventory = Var(
        model.TIME, initialize={0: 11.11111111111111, 1: 12.12121212121212}
    )
    model.sinter_inventory = Var(
        model.TIME, initialize={0: 21.21212121212121, 1: 22.22222222222222}
    )
    model.hot_iron_inventory = Var(
        model.TIME, initialize={0: 31.31313131313131, 1: 32.32323232323232}
    )
    model.cold_slab_inventory = Var(
        model.TIME, initialize={0: 41.41414141414141, 1: 42.42424242424242}
    )
    model.total_generator_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.wag_generator_electricity_mwh[t]
        + m.ng_generator_electricity_mwh[t],
    )
    model.gross_total_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: demand)
    model.gross_grid_import_mwh = Var(model.TIME, domain=NonNegativeReals)
    model.gross_grid_export_mwh = Var(model.TIME, domain=NonNegativeReals)
    model.net_grid_import_mwh = Expression(
        model.TIME, rule=lambda m, t: m.gross_grid_import_mwh[t]
    )
    model.grid_import_mode = Var(model.TIME, domain=Binary)
    model.gross_site_electricity_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.total_generator_electricity_mwh[t]
        + m.gross_grid_import_mwh[t]
        == m.gross_total_electricity_mwh[t] + m.gross_grid_export_mwh[t],
    )
    model.no_grid_reexport = Constraint(
        model.TIME,
        rule=lambda m, t: m.gross_grid_import_mwh[t]
        <= m.gross_total_electricity_mwh[t],
    )
    model.export_bounded_by_internal_generation = Constraint(
        model.TIME,
        rule=lambda m, t: m.gross_grid_export_mwh[t]
        <= m.total_generator_electricity_mwh[t],
    )
    model.grid_import_capacity = Constraint(
        model.TIME,
        rule=lambda m, t: m.gross_grid_import_mwh[t] <= 770.0 * m.grid_import_mode[t],
    )
    model.grid_export_capacity = Constraint(
        model.TIME,
        rule=lambda m, t: m.gross_grid_export_mwh[t]
        <= 770.0 * (1 - m.grid_import_mode[t]),
    )
    model.boiler_scaffold_fuel_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.ng_generator_electricity_mwh[t] == 0.345 * m.ng_fuel_mwh[t],
    )
    model.electricity_sale_sensitivity_active = True
    model.grid_import_bound_audit = {
        "status": "pass",
        "constraint_aware_fbbt": True,
        "hourly_bounds": [],
    }
    model.static_price_naive_objective = Objective(
        expr=sum(model.ng_fuel_mwh[t] for t in model.TIME), sense=minimize
    )
    return model


def _cost_policy(*, electricity_price: float, ng_price: float = 55.0) -> dict[str, object]:
    return {
        "objective_tolerance_eur": 0.01,
        "flows": [
            {
                "configuration": "C0",
                "flow_id": "grid",
                "model_component_attribute": "net_grid_import_mwh",
                "price_eur_by_hour": [electricity_price, electricity_price],
            },
            {
                "configuration": "C0",
                "flow_id": "ng",
                "model_component_attribute": "ng_fuel_mwh",
                "price_eur_by_hour": [ng_price, ng_price],
            },
        ],
    }


def _state_preservation_contract() -> dict[str, object]:
    return {
        "schema_version": "steel_phase2_sale_state_preservation_v4",
        "enabled": True,
        "configuration_id": "C0_current_BF_BOF_reference",
        "replan_index": 0,
        "execution_hours": 2,
        "implementation_sha256": "a" * 64,
    }


def _sale_policy(price: float) -> dict[str, object]:
    state_preservation = _state_preservation_contract()
    return {
        "enabled": True,
        "policy_id": "athanasiadis_sale_enabled",
        "sale_price_eur_by_hour": [price, price],
        "replan_index": 0,
        "execution_hours": 2,
        "state_preservation": state_preservation,
        "incumbent_containment": {
            "validation_tolerance_policy": policy_contract(),
            "state_preservation": state_preservation,
        },
    }


def _verified_preservation_fixture(
    model: ConcreteModel,
    *,
    root: Path,
    price: float,
) -> tuple[dict[str, object], dict[str, object]]:
    policy = _sale_policy(price)
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    provenance = {"implementation_sha256": "a" * 64}
    capture = _capture_sale_state_preservation_targets(
        model,
        contract=_state_preservation_contract(),
        saved_capture={
            "configuration_id": "C0_current_BF_BOF_reference",
            "replan_index": 0,
            "provenance": provenance,
        },
    )
    oracle_directory = root / "oracle"
    oracle_directory.mkdir(parents=True, exist_ok=True)
    containment_record = oracle_directory / "sale_incumbent_containment.json"
    capture_sha256 = "b" * 64
    containment.update(
        {
            "oracle_directory": str(oracle_directory),
            "normal_solution_record_sha256": capture_sha256,
            "normal_solution_expected_provenance": provenance,
        }
    )
    containment_record.write_text(
        json.dumps(
            {
                "status": "pass",
                "provenance": provenance,
                "saved_normal_solution_sha256": capture_sha256,
                "state_preservation_capture": capture,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    oracle_result = {
        "status": "pass",
        "provenance": provenance,
        "saved_normal_solution_path": "test_capture.json.gz",
        "saved_normal_solution_sha256": capture_sha256,
        "fixed_state_sha256_before": "c" * 64,
        "fixed_state_sha256_after": "c" * 64,
        "value_state_sha256_before": "d" * 64,
        "value_state_sha256_after": "d" * 64,
        "state_preservation_capture": capture,
        "record_sha256": __import__("hashlib").sha256(
            containment_record.read_bytes()
        ).hexdigest(),
    }
    return policy, oracle_result


def _install_verified_containment_stub(
    model: ConcreteModel,
    *,
    root: Path,
    price: float,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    policy, oracle_result = _verified_preservation_fixture(
        model, root=root, price=price
    )
    monkeypatch.setattr(
        modelbuilder,
        "_sale_incumbent_containment_oracle",
        lambda *args, **kwargs: oracle_result,
    )
    return policy


def _resign_containment_record(
    policy: dict[str, object], oracle_result: dict[str, object]
) -> None:
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    record_path = (
        Path(str(containment["oracle_directory"]))
        / "sale_incumbent_containment.json"
    )
    record_path.write_text(
        json.dumps(
            {
                "status": oracle_result["status"],
                "provenance": oracle_result["provenance"],
                "saved_normal_solution_sha256": oracle_result[
                    "saved_normal_solution_sha256"
                ],
                "state_preservation_capture": oracle_result[
                    "state_preservation_capture"
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    oracle_result["record_sha256"] = __import__("hashlib").sha256(
        record_path.read_bytes()
    ).hexdigest()


def _complete_handoff_rows(replan_count: int) -> list[dict[str, object]]:
    schemas = {
        "C0_current_BF_BOF_reference": (
            "coke_store_initial_t",
            "sinter_store_initial_t",
            "hot_iron_store_initial_t",
            "cold_slab_store_initial_t",
        ),
        "C1_phase1_BF_BOF_plus_DRP_EAF": (
            "coke_store_initial_t",
            "sinter_store_initial_t",
            "hot_iron_store_initial_t",
            "cold_slab_store_initial_t",
            "dri_buffer_initial_t",
        ),
    }
    rows: list[dict[str, object]] = []
    for configuration, fields in schemas.items():
        previous: dict[str, float] = {}
        for replan in range(replan_count):
            terminal = {
                field: float(index + replan + 1)
                for index, field in enumerate(fields)
            }
            rows.append(
                {
                    "configuration_id": configuration,
                    "replan_index": replan,
                    "start_overrides": json.dumps(previous, sort_keys=True),
                    "next_overrides": json.dumps(terminal, sort_keys=True),
                }
            )
            previous = terminal
    return rows


def test_absent_and_disabled_hook_leave_normal_objective_path_equivalent() -> None:
    assert policy_overrides("accepted_no_export_comparator") == {}
    assert "electricity_sale_sensitivity" not in inspect.signature(
        _solve_c1_configuration
    ).parameters
    disabled = {"enabled": False, "policy_id": "athanasiadis_sale_enabled"}
    assert not bool(disabled["enabled"])
    def model() -> ConcreteModel:
        item = ConcreteModel()
        item.TIME = RangeSet(0, 0)
        item.flow = Var(item.TIME, domain=NonNegativeReals, initialize=1.0)
        item.flow[0].fix(1.0)
        item.static_price_naive_objective = Objective(expr=item.flow[0])
        return item
    cost = {
        "objective_tolerance_eur": 0.01,
        "flows": [{"configuration": "C0", "flow_id": "x", "model_component_attribute": "flow", "price_eur_by_hour": [1.0]}],
    }
    absent, explicit = model(), model()
    _, absent_meta = _solve_with_optional_lexicographic_cost(
        absent, solver=_solver(), configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=cost,
    )
    _, explicit_meta = _solve_with_optional_lexicographic_cost(
        explicit, solver=_solver(), configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=cost, electricity_sale_sensitivity=disabled,
    )
    assert set(absent.component_map()) == set(explicit.component_map())
    without_runtime = lambda payload: {
        key: item for key, item in payload.items() if not key.endswith("_runtime_seconds")
    }
    assert without_runtime(absent_meta) == without_runtime(explicit_meta)


def test_real_absent_disabled_result_contract_compares_closed_loop_rows() -> None:
    rows = [
        {
            "configuration_id": configuration,
            "replan_index": 0,
            "solver_status": "ok",
            "termination_condition": "optimal",
            "objective_value": 1.25,
            "primary_cost_objective_eur": 2.5,
            "production_progress_actual_t": 3.75,
            "production_progress_surplus_t": 0.0,
            "production_progress_deficit_t": 0.0,
        }
        for configuration in (
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        )
    ]
    passed = absent_disabled_result_equivalence(rows, deepcopy(rows))
    assert passed["status"] == "pass"
    assert passed["checked_model_count"] == 2
    changed = deepcopy(rows)
    changed[0]["objective_value"] = 2.250001
    failed = absent_disabled_result_equivalence(rows, changed)
    assert failed["status"] == "fail"
    assert "numeric_mismatch" in failed["failure_reasons"]


def test_real_containment_oracle_fixes_shared_incumbent_and_restores_state(
    local_test_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    comparator = ConcreteModel()
    comparator.TIME = RangeSet(0, 0)
    comparator.shared = Var(comparator.TIME, domain=NonNegativeReals)
    full_precision_value = 5.123456789012345
    comparator.shared[0].set_value(full_precision_value)
    comparator.final_product_output = Expression(
        comparator.TIME, rule=lambda m, t: m.shared[t]
    )
    comparator.bof_crude_steel_output = Expression(
        comparator.TIME, rule=lambda m, t: m.shared[t]
    )
    comparator.c0_hsm_final_product_output = Expression(
        comparator.TIME, rule=lambda m, t: m.shared[t]
    )
    comparator.c0_dsp_final_product_output = Expression(
        comparator.TIME, rule=lambda _m, _t: 0.0
    )
    edge_lower_bound = full_precision_value + 1.0000003385357559e-6
    comparator.rolling_production_deadline = Constraint(
        expr=comparator.shared[0] >= edge_lower_bound
    )
    inventory_targets = {
        "coke_inventory": 11.11111111111111,
        "sinter_inventory": 22.22222222222222,
        "hot_iron_inventory": 33.33333333333333,
        "cold_slab_inventory": 44.44444444444444,
    }
    for component_name, target in inventory_targets.items():
        setattr(
            comparator,
            component_name,
            Var(comparator.TIME, initialize=target),
        )
    comparator.static_price_naive_objective = Objective(expr=comparator.shared[0])
    capture_path = (
        local_test_tmp
        / "attempts/deadbeef/normal_capture/calm/normal.json.gz"
    )
    provenance = {"case": "test", "implementation_sha256": "a" * 64}
    _capture_complete_normal_solution(
        comparator,
        metadata={},
        solver=SimpleNamespace(name="gurobi", options={}, version=lambda: (1, 0)),
        configuration_id="C0_current_BF_BOF_reference",
        policy={"enabled": True, "structural_inactive_exclusion_enabled": True, "path": str(capture_path), "replan_index": 0, "provenance": provenance},
    )
    assert capture_path.is_file()
    assert capture_path.parent.is_dir()
    sale = ConcreteModel()
    sale.TIME = RangeSet(0, 0)
    sale.shared = Var(sale.TIME, domain=NonNegativeReals)
    sale.shared[0].set_value(None)
    sale.final_product_output = Expression(
        sale.TIME, rule=lambda m, t: m.shared[t]
    )
    sale.bof_crude_steel_output = Expression(
        sale.TIME, rule=lambda m, t: m.shared[t]
    )
    sale.c0_hsm_final_product_output = Expression(
        sale.TIME, rule=lambda m, t: m.shared[t]
    )
    sale.c0_dsp_final_product_output = Expression(
        sale.TIME, rule=lambda _m, _t: 0.0
    )
    sale.rolling_production_deadline = Constraint(
        expr=sale.shared[0] >= edge_lower_bound
    )
    for component_name in inventory_targets:
        setattr(sale, component_name, Var(sale.TIME))
    sale.gross_total_electricity_mwh = Expression(sale.TIME, rule=lambda _m, _t: 5.0)
    sale.total_generator_electricity_mwh = Expression(sale.TIME, rule=lambda _m, _t: 0.0)
    sale.gross_grid_import_mwh = Var(sale.TIME, domain=NonNegativeReals, initialize=0.0)
    sale.gross_grid_export_mwh = Var(sale.TIME, domain=NonNegativeReals, initialize=0.0)
    sale.grid_import_mode = Var(sale.TIME, domain=Binary, initialize=0.0)
    sale.gross_site_electricity_balance = Constraint(
        sale.TIME,
        rule=lambda m, t: m.total_generator_electricity_mwh[t]
        + m.gross_grid_import_mwh[t]
        == m.gross_total_electricity_mwh[t] + m.gross_grid_export_mwh[t],
    )
    sale.static_price_naive_objective = Objective(expr=sale.shared[0])
    before_fixed = sale.shared[0].fixed
    before_value = sale.shared[0].value
    state_preservation = {
        **_state_preservation_contract(),
        "execution_hours": 1,
    }

    class FakeSolver:
        name = "gurobi"
        options: dict[str, object] = {}
        def solve(self, _model, load_solutions=False):
            assert _model.shared[0].fixed
            assert _model.shared[0].value == full_precision_value
            return SimpleNamespace(solver=SimpleNamespace(status="ok", termination_condition="optimal"))

    monkeypatch.setattr(
        "steel.s4_4c_unified_physical_modelbuilder._native_gurobi_zero_objective_check",
        lambda *args, **kwargs: {"status": "optimal", "iis_created": False},
    )
    oracle_policy = {
        "normal_solution_record_path": str(capture_path),
        "validation_tolerance_policy": policy_contract(),
        "normal_solution_record_sha256": __import__("hashlib").sha256(
            capture_path.read_bytes()
        ).hexdigest(),
        "normal_solution_expected_provenance": provenance,
        "oracle_directory": str(local_test_tmp / "oracle"),
        "state_preservation": state_preservation,
    }
    original_components = set(sale.component_map())
    result = _sale_incumbent_containment_oracle(
        sale,
        solver=FakeSolver(),
        policy=oracle_policy,
        tolerance=1e-6,
    )
    assert result["status"] == "pass"
    assert result["schema_version"] == "steel_sale_incumbent_containment_v2"
    assert result["normal_solver_relevant_schema_sha256"]
    assert result["sale_solver_relevant_schema_sha256"]
    assert result["normal_active_incidence_sha256"]
    assert result["sale_active_incidence_sha256"]
    assert result["original_model_fingerprint_unchanged"] is True
    assert result["original_model_structure_sha256_before"] == (
        result["original_model_structure_sha256_after"]
    )
    assert result["loaded_incumbent_audit"]["feasible"] is False
    assert result["loaded_incumbent_audit"][
        "constraint_above_tolerance_count"
    ] == 1
    assert result["loaded_incumbent_audit"][
        "exact_maximum_constraint_violations"
    ][0]["name"] == "rolling_production_deadline"
    assert result["constraint_audit_disposition"] == (
        "registered_unit_purpose_validation_model_required"
    )
    assert result["constraint_feasibility_authority"] == (
        "required_pyomo_and_native_gurobi_fixed_incumbent_registered_"
        "validation_model"
    )
    validation_rows = result["registered_validation_evidence"]["rows"]
    deadline = next(
        row
        for row in validation_rows
        if row["constraint_family"] == "rolling_production_deadline"
    )
    assert deadline["allowed_tolerance"] == 1.0
    assert deadline["used_relaxation"] == pytest.approx(
        edge_lower_bound - full_precision_value
    )
    assert deadline["status"] == "pass"
    assert result["new_exchange_variable_names"] == [
        "grid_import_mode[0]", "gross_grid_export_mwh[0]", "gross_grid_import_mwh[0]"
    ]
    assert result["state_preservation_capture"]["targets"] == {
        "executed_final_product_t": full_precision_value,
        "executed_bof_liquid_steel_t": full_precision_value,
        "executed_hsm_final_output_t": full_precision_value,
        "executed_dsp_final_output_t": 0.0,
        "coke_inventory_t": inventory_targets["coke_inventory"],
        "sinter_inventory_t": inventory_targets["sinter_inventory"],
        "hot_iron_inventory_t": inventory_targets["hot_iron_inventory"],
        "cold_slab_inventory_t": inventory_targets["cold_slab_inventory"],
    }
    assert sale.shared[0].fixed is before_fixed
    assert sale.shared[0].value is before_value
    assert all(
        getattr(sale, component_name)[0].value is None
        for component_name in inventory_targets
    )
    repeated = _sale_incumbent_containment_oracle(
        sale,
        solver=FakeSolver(),
        policy=oracle_policy,
        tolerance=1e-6,
    )
    assert repeated["status"] == "pass"
    assert repeated["original_model_fingerprint_unchanged"] is True
    assert set(sale.component_map()) == original_components


def test_electricity_identity_exclusivity_reexport_export_bound_and_split() -> None:
    rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "WAG_generator_electricity_mwh": 6.0,
            "NG_generator_electricity_mwh": 2.0,
            "total_generator_electricity_mwh": 8.0,
            "gross_grid_import_mwh": 0.0,
            "gross_grid_export_mwh": 3.0,
            "gross_total_electricity_mwh": 5.0,
        }
    ]
    guardrails = electricity_guardrails(rows, sale_enabled=True)
    assert all(
        row["status"] == "pass"
        for row in guardrails
    )
    assert all(row["allowed_tolerance"] == 1e-6 for row in guardrails)
    assert all(row["tolerance_accumulation_allowed"] is False for row in guardrails)


@pytest.mark.parametrize(
    ("residual", "expected_status"),
    (
        (1.0000000543186616e-6, "pass"),
        (1.001e-6, "fail"),
        (1e-6 + 1e-9, "fail"),
    ),
)
def test_electricity_guardrails_use_registered_threshold_comparison(
    residual: float,
    expected_status: str,
) -> None:
    rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "WAG_generator_electricity_mwh": residual,
            "NG_generator_electricity_mwh": 0.0,
            "total_generator_electricity_mwh": 0.0,
            "gross_grid_import_mwh": 0.0,
            "gross_grid_export_mwh": 0.0,
            "gross_total_electricity_mwh": 0.0,
        }
    ]
    by_name = {
        row["guardrail"]: row
        for row in electricity_guardrails(rows, sale_enabled=False)
    }
    for name in (
        "electricity_identity",
        "wag_and_ng_generation_exactly_separate",
    ):
        row = by_name[name]
        assert row["raw_residual"] == residual
        assert row["max_residual"] == residual
        assert row["allowed_tolerance"] == 1e-6
        assert row["governed_tolerance"] == 1e-6
        assert row["positive_excess"] == max(0.0, residual - 1e-6)
        assert row["normalized_residual"] == residual / 1e-6
        assert row["status"] == expected_status


def test_electricity_trajectory_max_does_not_accumulate_hourly_tolerance() -> None:
    rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "WAG_generator_electricity_mwh": 0.75e-6,
            "NG_generator_electricity_mwh": 0.0,
            "total_generator_electricity_mwh": 0.0,
            "gross_grid_import_mwh": 0.0,
            "gross_grid_export_mwh": 0.0,
            "gross_total_electricity_mwh": 0.0,
        }
        for _ in range(2)
    ]
    identity = next(
        row
        for row in electricity_guardrails(rows, sale_enabled=False)
        if row["guardrail"] == "electricity_identity"
    )
    assert identity["raw_residual"] == 0.75e-6
    assert identity["aggregation"] == "per_trajectory_max_no_hourly_accumulation"
    assert identity["tolerance_accumulation_allowed"] is False
    assert identity["status"] == "pass"

    comparator_rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "WAG_generator_electricity_mwh": 0.75e-6,
            "NG_generator_electricity_mwh": 0.0,
            "total_generator_electricity_mwh": 0.75e-6,
            "gross_grid_import_mwh": 0.0,
            "gross_grid_export_mwh": 0.75e-6,
            "gross_total_electricity_mwh": 0.0,
        }
        for _ in range(2)
    ]
    comparator_export = next(
        row
        for row in electricity_guardrails(
            comparator_rows, sale_enabled=False
        )
        if row["guardrail"] == "accepted_comparator_export_zero"
    )
    assert comparator_export["raw_residual"] == 0.75e-6
    assert comparator_export["status"] == "pass"


_EXPECTED_PROCUREMENT_PRICE_IDS = {
    "grid_electricity_flat_nl",
    "natural_gas_ttf_proxy",
    "coking_coal_hcc_proxy",
    "pci_coal_proxy",
    "iron_ore_62fe_proxy",
    "imported_dr_pellets_proxy",
    "purchased_scrap_proxy",
    "imported_slab_proxy",
}


def _cost_ledger_validation_config(*, sale_enabled: bool = False) -> dict[str, object]:
    config: dict[str, object] = {
        "market_prices_enabled": False,
        "product_revenue_enabled": False,
        "co2_ets_objective_enabled": False,
    }
    if sale_enabled:
        config["c0_electricity_sale_sensitivity"] = {
            "enabled": True,
            "policy_id": "athanasiadis_sale_enabled",
            "price_basis": "same_governed_y_pred_as_import",
            "revenue_scope": "gross_grid_export_only",
            "settlement_claim": False,
        }
    return config


def _cost_ledger_validation_rows(*, include_sale: bool = False) -> list[dict[str, object]]:
    rows = [
        {
            "price_id": price_id,
            "price_scenario_id": "fixed_reference_v1",
            "plan_hour_index": 0,
            "price_eur_per_unit": 1.0,
        }
        for price_id in sorted(_EXPECTED_PROCUREMENT_PRICE_IDS)
    ]
    if include_sale:
        rows.append(
            {
                "configuration_id": "C0_current_BF_BOF_reference",
                "flow_id": "C0_EL_EXPORT",
                "component": "gross_grid_export",
                "cost_route": "represented_electricity_sale_sensitivity",
                "physical_quantity_attribute": "gross_grid_export_mwh",
                "quantity": 2.5,
                "price_id": "governed_y_pred_sale_value",
                "price_scenario_id": "same_governed_y_pred_as_import",
                "plan_hour_index": 0,
                "price_eur_per_unit": 40.0,
                "cost_eur": -100.0,
            }
        )
    for row in rows:
        row["price_input_fingerprint_sha256"] = _ledger_price_input_fingerprint(row)
    return rows


def test_normal_cost_ledger_contract_requires_exact_frozen_eight_families() -> None:
    diagnostics = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(),
        _cost_ledger_validation_rows(),
    )
    assert diagnostics["status"] == "pass"
    assert set(diagnostics["expected_price_ids"]) == _EXPECTED_PROCUREMENT_PRICE_IDS
    assert diagnostics["sale_row_count"] == 0


def test_explicit_sale_policy_authorizes_exact_governed_export_value_family() -> None:
    diagnostics = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(sale_enabled=True),
        _cost_ledger_validation_rows(include_sale=True),
    )
    assert diagnostics["status"] == "pass"
    assert diagnostics["sale_policy_valid"] is True
    assert diagnostics["sale_rows_valid"] is True
    assert set(diagnostics["expected_price_ids"]) == {
        *_EXPECTED_PROCUREMENT_PRICE_IDS,
        "governed_y_pred_sale_value",
    }


def test_sale_value_family_without_explicit_sale_policy_fails_closed() -> None:
    diagnostics = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(),
        _cost_ledger_validation_rows(include_sale=True),
    )
    assert diagnostics["status"] == "fail"
    assert diagnostics["unauthorized_price_ids"] == [
        "governed_y_pred_sale_value"
    ]


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("policy_id", "generic_sale"),
        ("price_basis", "realised_price"),
        ("revenue_scope", "all_generation"),
        ("settlement_claim", True),
    ],
)
def test_sale_value_family_requires_complete_explicit_sale_policy_identity(
    field: str, wrong_value: object
) -> None:
    config = _cost_ledger_validation_config(sale_enabled=True)
    sale_policy = config["c0_electricity_sale_sensitivity"]
    assert isinstance(sale_policy, dict)
    sale_policy[field] = wrong_value
    diagnostics = _governed_cost_ledger_validation(
        config, _cost_ledger_validation_rows(include_sale=True)
    )
    assert diagnostics["status"] == "fail"
    assert diagnostics["sale_policy_valid"] is False


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("configuration_id", "C1_TS_new_route"),
        ("flow_id", "C0_OTHER_EXPORT"),
        ("component", "net_grid_export"),
        ("cost_route", "market_settlement"),
        ("physical_quantity_attribute", "net_grid_export_mwh"),
        ("price_scenario_id", "realised_spot_price"),
    ],
)
def test_sale_value_family_rejects_wrong_governed_row_identity(
    field: str, wrong_value: str
) -> None:
    rows = _cost_ledger_validation_rows(include_sale=True)
    rows[-1][field] = wrong_value
    diagnostics = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(sale_enabled=True), rows
    )
    assert diagnostics["status"] == "fail"
    assert f"wrong_{field}" in diagnostics["sale_row_diagnostics"][0][
        "failure_ids"
    ]


def test_second_extra_revenue_family_remains_forbidden() -> None:
    rows = _cost_ledger_validation_rows(include_sale=True)
    rows.append({"price_id": "generic_product_revenue"})
    diagnostics = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(sale_enabled=True), rows
    )
    assert diagnostics["status"] == "fail"
    assert diagnostics["unauthorized_price_ids"] == ["generic_product_revenue"]


@pytest.mark.parametrize(
    "flag",
    [
        "market_prices_enabled",
        "product_revenue_enabled",
        "co2_ets_objective_enabled",
    ],
)
def test_sale_policy_does_not_enable_forbidden_economic_flags(flag: str) -> None:
    config = _cost_ledger_validation_config(sale_enabled=True)
    config[flag] = True
    diagnostics = _governed_cost_ledger_validation(
        config, _cost_ledger_validation_rows(include_sale=True)
    )
    assert diagnostics["status"] == "fail"
    assert diagnostics["forbidden_economic_flags_absent"] is False


@pytest.mark.parametrize(
    ("field", "bad_value", "failure_id"),
    [
        ("cost_eur", 100.0, "sale_cost_not_negative_quantity_times_price"),
        ("quantity", -1.0, "negative_quantity"),
        ("quantity", float("nan"), "nonfinite_quantity"),
        ("price_eur_per_unit", float("inf"), "nonfinite_price"),
        ("cost_eur", float("nan"), "nonfinite_cost"),
    ],
)
def test_sale_value_family_rejects_wrong_cost_identity_and_nonfinite_values(
    field: str, bad_value: float, failure_id: str
) -> None:
    rows = _cost_ledger_validation_rows(include_sale=True)
    rows[-1][field] = bad_value
    diagnostics = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(sale_enabled=True), rows
    )
    assert diagnostics["status"] == "fail"
    assert failure_id in diagnostics["sale_row_diagnostics"][0]["failure_ids"]


def test_cost_acceptance_readiness_uses_governed_ledger_contract() -> None:
    valid = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(sale_enabled=True),
        _cost_ledger_validation_rows(include_sale=True),
    )
    invalid = _governed_cost_ledger_validation(
        _cost_ledger_validation_config(),
        _cost_ledger_validation_rows(include_sale=True),
    )
    common = {
        "pre_cost_boundary_ready": True,
        "cost_mode_active": True,
        "cost_objectives_active": True,
        "cost_objective_reconciliation_pass": True,
    }
    assert _cost_acceptance_readiness(
        **common, cost_ledger_validation=valid
    ) is True
    assert _cost_acceptance_readiness(
        **common, cost_ledger_validation=invalid
    ) is False


def _classification_model(
    *,
    required_value: float | None = 1.0,
    required_ub: float | None = None,
) -> ConcreteModel:
    model = ConcreteModel()
    model.required = Var(
        domain=NonNegativeReals,
        bounds=(0.0, required_ub),
        initialize=required_value,
    )
    if required_value is None:
        model.required.set_value(None)
    model.inactive = Var(domain=NonNegativeReals)
    model.required_floor = Constraint(expr=model.required >= 0.0)
    model.objective = Objective(expr=model.required)
    return model


def test_structurally_inactive_variable_requires_zero_active_or_governed_incidence() -> None:
    classification = _variable_structural_classification(_classification_model())
    inactive = next(row for row in classification["variables"] if row["name"] == "inactive")
    assert inactive["structurally_inactive_exclusion"] is True
    assert inactive["active_constraint_families"] == []
    assert inactive["active_objective_families"] == []
    assert inactive["active_expression_families"] == []


def test_capture_excludes_only_classified_undefined_inactive_variable(
    local_test_tmp: Path,
) -> None:
    path = local_test_tmp / "capture/normal.json.gz"
    _capture_complete_normal_solution(
        _classification_model(),
        metadata={},
        solver=SimpleNamespace(name="test", options={}, version=lambda: (1, 0)),
        configuration_id="C0_current_BF_BOF_reference",
        policy={
            "enabled": True,
            "structural_inactive_exclusion_enabled": True,
            "path": str(path),
            "replan_index": 0,
            "provenance": {"test": "inactive"},
        },
    )
    import gzip
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert [row["name"] for row in payload["variables"]] == ["required"]
    assert [row["name"] for row in payload["variable_classification"]["inactive_exclusions"]] == ["inactive"]


def test_capture_fails_exactly_for_undefined_solver_relevant_variable(
    local_test_tmp: Path,
) -> None:
    path = local_test_tmp / "capture/normal.json.gz"
    with pytest.raises(S44CModelBuilderError, match="undefined solver/governed-relevant") as exc:
        _capture_complete_normal_solution(
            _classification_model(required_value=None),
            metadata={},
            solver=SimpleNamespace(name="test", options={}, version=lambda: (1, 0)),
            configuration_id="C0_current_BF_BOF_reference",
            policy={
                "enabled": True,
                "structural_inactive_exclusion_enabled": True,
                "path": str(path),
                "replan_index": 0,
                "provenance": {"test": "undefined"},
            },
        )
    evidence = Path(exc.value.variable_classification_evidence_path)
    record = json.loads(evidence.read_text())
    undefined = record["undefined_variables"][0]
    assert undefined["name"] == "required"
    assert undefined["solver_relevant"] is True
    assert undefined["value"] is None
    assert undefined["stale"] is True


def test_classification_records_required_domain_bounds_fixed_and_roles() -> None:
    required = next(
        row
        for row in _variable_structural_classification(_classification_model())["variables"]
        if row["name"] == "required"
    )
    assert required["domain"] == "NonNegativeReals"
    assert required["lb"] == pytest.approx(0.0)
    assert required["ub"] is None
    assert required["declared_domain"] == "NonNegativeReals"
    assert required["current_domain"] == "NonNegativeReals"
    assert required["current_schema_differs_from_declared"] is False
    assert required["fixed"] is False
    assert required["solver_representation"] == "active_constraint_or_objective"
    assert required["classification_reason"] == "required_active_solver_incidence"


def test_complete_structure_hash_is_value_independent() -> None:
    first = _classification_model(required_value=1.0)
    second = _classification_model(required_value=1.23456789012345)
    assert _variable_structural_classification(first)["complete_structure_sha256"] == _variable_structural_classification(second)["complete_structure_sha256"]


def test_solver_relevant_schema_hash_is_value_independent() -> None:
    first = _classification_model(required_value=1.0)
    second = _classification_model(required_value=9.0)
    assert _variable_structural_classification(first)["solver_relevant_schema_sha256"] == _variable_structural_classification(second)["solver_relevant_schema_sha256"]


def test_inactive_exclusion_hash_is_deterministic_across_undefined_state() -> None:
    first = _classification_model()
    second = _classification_model()
    second.inactive.set_value(7.0)
    assert _variable_structural_classification(first)["inactive_exclusion_sha256"] == _variable_structural_classification(second)["inactive_exclusion_sha256"]


def test_fixed_values_hash_changes_with_full_precision_fixed_value() -> None:
    first = _classification_model()
    first.required.fix(1.000000000000001)
    second = _classification_model()
    second.required.fix(1.000000000000002)
    assert _variable_structural_classification(first)["fixed_values_sha256"] != _variable_structural_classification(second)["fixed_values_sha256"]


def test_active_incidence_hash_changes_when_constraint_family_changes() -> None:
    first = _classification_model()
    second = _classification_model()
    second.extra_required_cap = Constraint(expr=second.required <= 2.0)
    assert _variable_structural_classification(first)["active_incidence_sha256"] != _variable_structural_classification(second)["active_incidence_sha256"]


def test_active_variable_records_can_snapshot_and_restore_original_none_state() -> None:
    model = _classification_model()
    records = _active_variable_records(model, allow_undefined=True)
    inactive = next(row for row in records if row["name"] == "inactive")
    assert inactive["value"] is None
    assert inactive["stale"] is True


def _capture_classification_fixture(path: Path) -> dict[str, object]:
    provenance = {"test": "classification_fixture"}
    _capture_complete_normal_solution(
        _classification_model(),
        metadata={},
        solver=SimpleNamespace(name="test", options={}, version=lambda: (1, 0)),
        configuration_id="C0_current_BF_BOF_reference",
        policy={
            "enabled": True,
            "structural_inactive_exclusion_enabled": True,
            "path": str(path),
            "replan_index": 0,
            "provenance": provenance,
        },
    )
    return provenance


def test_containment_rejects_unauthorized_new_solver_variable(
    local_test_tmp: Path,
) -> None:
    capture = local_test_tmp / "normal.json.gz"
    provenance = _capture_classification_fixture(capture)
    sale = _classification_model()
    sale.required.set_value(None)
    sale.rogue = Var(domain=NonNegativeReals)
    sale.rogue_floor = Constraint(expr=sale.rogue >= 0.0)
    with pytest.raises(S44CModelBuilderError, match="required_not_captured") as exc:
        _sale_incumbent_containment_oracle(
            sale,
            solver=SimpleNamespace(name="gurobi", options={}),
            policy={
                "normal_solution_record_path": str(capture),
                "validation_tolerance_policy": policy_contract(),
                "normal_solution_record_sha256": __import__("hashlib").sha256(capture.read_bytes()).hexdigest(),
                "normal_solution_expected_provenance": provenance,
                "oracle_directory": str(local_test_tmp / "oracle"),
            },
            tolerance=1e-6,
        )
    assert Path(exc.value.containment_evidence_path).is_file()


def test_containment_rejects_normal_sale_inactive_classification_mismatch(
    local_test_tmp: Path,
) -> None:
    capture = local_test_tmp / "normal.json.gz"
    provenance = _capture_classification_fixture(capture)
    sale = _classification_model()
    sale.inactive_floor = Constraint(expr=sale.inactive >= 0.0)
    with pytest.raises(S44CModelBuilderError, match="exclusion_names"):
        _sale_incumbent_containment_oracle(
            sale,
            solver=SimpleNamespace(name="gurobi", options={}),
            policy={
                "normal_solution_record_path": str(capture),
                "validation_tolerance_policy": policy_contract(),
                "normal_solution_record_sha256": __import__("hashlib").sha256(capture.read_bytes()).hexdigest(),
                "normal_solution_expected_provenance": provenance,
                "oracle_directory": str(local_test_tmp / "oracle"),
            },
            tolerance=1e-6,
        )


def test_containment_rejects_genuine_declared_shared_schema_change(
    local_test_tmp: Path,
) -> None:
    capture = local_test_tmp / "normal.json.gz"
    provenance = {"test": "declared_schema_change"}
    normal = _classification_model(required_ub=1.0)
    _record_declared_variable_schema(normal)
    _capture_complete_normal_solution(
        normal,
        metadata={},
        solver=SimpleNamespace(name="test", options={}, version=lambda: (1, 0)),
        configuration_id="C0_current_BF_BOF_reference",
        policy={
            "enabled": True,
            "structural_inactive_exclusion_enabled": True,
            "path": str(capture),
            "replan_index": 0,
            "provenance": provenance,
        },
    )
    sale = _classification_model(required_ub=2.0)
    _record_declared_variable_schema(sale)
    with pytest.raises(S44CModelBuilderError, match="shared_schema") as exc:
        _sale_incumbent_containment_oracle(
            sale,
            solver=SimpleNamespace(name="gurobi", options={}),
            policy={
                "normal_solution_record_path": str(capture),
                "validation_tolerance_policy": policy_contract(),
                "normal_solution_record_sha256": __import__("hashlib").sha256(capture.read_bytes()).hexdigest(),
                "normal_solution_expected_provenance": provenance,
                "oracle_directory": str(local_test_tmp / "oracle"),
            },
            tolerance=1e-6,
        )
    precheck = json.loads(Path(exc.value.containment_evidence_path).read_text())
    assert precheck["shared_schema_mismatches"] == ["required"]
    detail = precheck["shared_declared_schema_mismatch_details"][0]
    assert detail["normal_declared_schema"]["ub"] == pytest.approx(1.0)
    assert detail["sale_declared_schema"]["ub"] == pytest.approx(2.0)


def test_hourly_fbbt_bound_audit_is_written_before_containment(
    local_test_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _sale_model()
    model.grid_import_bound_audit = {
        "schema_version": "steel_c0_hourly_import_bound_audit_v1",
        "status": "pass",
        "constraint_aware_fbbt": True,
        "derivation_method": "fbbt(model)",
        "active_constraint_families_sha256": "a" * 64,
        "hourly_bounds": [
            {
                "hour_index": hour,
                "gross_consumption_upper_bound_mwh": 5.0,
                "gross_grid_import_upper_bound_mwh": 5.0,
                "status": "finite",
            }
            for hour in range(2)
        ],
    }
    policy = _install_verified_containment_stub(
        model, root=local_test_tmp, price=100.0, monkeypatch=monkeypatch
    )
    _solve_with_optional_lexicographic_cost(
        model,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(electricity_price=100.0),
        electricity_sale_sensitivity=policy,
    )
    audit_path = local_test_tmp / "oracle/grid_import_hourly_bound_audit.json"
    audit = json.loads(audit_path.read_text())
    assert audit["status"] == "pass"
    assert len(audit["hourly_bounds"]) == 2


def test_full_precision_required_value_survives_capture_round_trip(
    local_test_tmp: Path,
) -> None:
    model = _classification_model(required_value=1.2345678901234567)
    path = local_test_tmp / "normal.json.gz"
    _capture_complete_normal_solution(
        model,
        metadata={},
        solver=SimpleNamespace(name="test", options={}, version=lambda: (1, 0)),
        configuration_id="C0_current_BF_BOF_reference",
        policy={
            "enabled": True,
            "structural_inactive_exclusion_enabled": True,
            "path": str(path),
            "replan_index": 0,
            "provenance": {"test": "precision"},
        },
    )
    import gzip
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["variables"][0]["value"] == 1.2345678901234567


def test_sale_state_targets_use_full_precision_verified_incumbent_values() -> None:
    model = _sale_model()
    capture = _capture_sale_state_preservation_targets(
        model,
        contract=_state_preservation_contract(),
        saved_capture={
            "configuration_id": "C0_current_BF_BOF_reference",
            "replan_index": 0,
            "provenance": {"implementation_sha256": "a" * 64},
        },
    )
    assert capture["target_schema"] == [
        "executed_final_product_t",
        "executed_bof_liquid_steel_t",
        "executed_hsm_final_output_t",
        "executed_dsp_final_output_t",
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
    ]
    assert capture["targets"] == {
        "executed_final_product_t": 2 * 1.2345678901234567,
        "executed_bof_liquid_steel_t": 2.6,
        "executed_hsm_final_output_t": 1.8,
        "executed_dsp_final_output_t": 2 * 0.3345678901234567,
        "coke_inventory_t": 12.12121212121212,
        "sinter_inventory_t": 22.22222222222222,
        "hot_iron_inventory_t": 32.32323232323232,
        "cold_slab_inventory_t": 42.42424242424242,
    }


def test_sale_state_apply_adds_exact_progress_and_inventory_constraints(
    local_test_tmp: Path,
) -> None:
    model = _sale_model()
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    deadline_target_t = 18_493.150684931505
    deadline_residual_t = 1.0000003385357559e-6
    model.deadline_probe = Var(
        initialize=deadline_target_t - deadline_residual_t
    )
    model.deadline_probe.fix()
    model.rolling_production_deadline = Constraint(
        expr=model.deadline_probe >= deadline_target_t
    )
    validation_context = _install_sale_economic_validation_overlay(model)
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    context = _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    constraint_names = oracle_result["state_preservation_capture"][
        "constraint_names"
    ]
    expected_names = set(constraint_names.values())
    assert expected_names == {
        "sale_state_executed_final_product_preservation_exact",
        "sale_state_executed_bof_liquid_steel_preservation_exact",
        "sale_state_executed_hsm_final_output_preservation_exact",
        "sale_state_executed_dsp_final_output_preservation_exact",
        "sale_state_coke_inventory_preservation_exact",
        "sale_state_sinter_inventory_preservation_exact",
        "sale_state_hot_iron_inventory_preservation_exact",
        "sale_state_cold_slab_inventory_preservation_exact",
    }
    assert len(expected_names) == len(constraint_names) == 8
    assert all(hasattr(model, name) for name in expected_names)
    for target_id, name in constraint_names.items():
        constraint = getattr(model, name)
        assert value(constraint.lower) == context["targets"][target_id]
        assert value(constraint.upper) == context["targets"][target_id]
    evidence = json.loads(Path(context["evidence_path"]).read_text())
    assert evidence["status"] == "targets_applied_pending_economic_solve"
    assert evidence["targets"] == context["targets"]
    assert evidence["target_bounds"] == context["target_bounds"]
    assert all(
        bounds == {
            "lower_bound_t": context["targets"][target_id] - 1.0,
            "upper_bound_t": context["targets"][target_id] + 1.0,
        }
        for target_id, bounds in context["target_bounds"].items()
    )
    assert evidence["containment_record_sha256"] == oracle_result["record_sha256"]
    validation = _finalize_sale_economic_validation_overlay(
        model, validation_context
    )
    deadline_row = next(
        row
        for row in validation["rows"]
        if row["constraint_family"] == "rolling_production_deadline"
    )
    assert validation["status"] == "pass"
    assert deadline_row["raw_residual"] == pytest.approx(deadline_residual_t)


@pytest.mark.parametrize("residual_t", [0.0, 0.001, 1.0])
def test_sale_state_final_audit_accepts_independent_boundary_residuals(
    local_test_tmp: Path,
    residual_t: float,
) -> None:
    model = _sale_model()
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    context = _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    model.coke_inventory[1].set_value(
        context["targets"]["coke_inventory_t"] + residual_t
    )
    exact = model.sale_state_coke_inventory_preservation_exact
    if residual_t:
        assert value(exact.body) != value(exact.lower)
    finalized = _finalize_sale_state_preservation(
        model,
        context=context,
        termination_condition="optimal",
        tolerance=1.0,
    )
    assert finalized["status"] == "pass"
    assert finalized["signed_residuals"]["coke_inventory_t"] == pytest.approx(
        residual_t
    )
    assert finalized["absolute_residuals"]["coke_inventory_t"] == pytest.approx(
        residual_t
    )
    assert finalized["normalized_residuals"]["coke_inventory_t"] == pytest.approx(
        residual_t
    )
    assert finalized["per_state_validation"]["coke_inventory_t"][
        "aggregation"
    ] == "independent_state_no_accumulation"


def test_sale_state_overlay_does_not_modify_original_constraints(
    local_test_tmp: Path,
) -> None:
    model = _sale_model()
    before = {
        constraint.name: str(constraint.expr)
        for constraint in model.component_data_objects(Constraint, active=True)
    }
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    after = {
        constraint.name: str(constraint.expr)
        for constraint in model.component_data_objects(Constraint, active=True)
        if constraint.name in before
    }
    assert after == before


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_target",
        "extra_target",
        "nonfinite_target",
        "wrong_target_hash",
        "wrong_capture_contract",
        "wrong_provenance",
        "wrong_restoration_hash",
        "wrong_containment_hash",
    ],
)
def test_sale_state_preservation_rejects_corrupt_capture_or_identity(
    local_test_tmp: Path, corruption: str
) -> None:
    model = _sale_model()
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp / corruption, price=100.0
    )
    capture = deepcopy(oracle_result["state_preservation_capture"])
    oracle_result["state_preservation_capture"] = capture
    if corruption == "missing_target":
        capture["targets"].pop("coke_inventory_t")
        capture["targets_sha256"] = modelbuilder._canonical_payload_sha256(
            capture["targets"]
        )
    elif corruption == "extra_target":
        capture["targets"]["dri_inventory_t"] = 1.0
        capture["targets_sha256"] = modelbuilder._canonical_payload_sha256(
            capture["targets"]
        )
    elif corruption == "nonfinite_target":
        capture["targets"]["coke_inventory_t"] = float("inf")
    elif corruption == "wrong_target_hash":
        capture["targets_sha256"] = "0" * 64
    elif corruption == "wrong_capture_contract":
        capture["contract"]["implementation_sha256"] = "f" * 64
    elif corruption == "wrong_provenance":
        oracle_result["provenance"] = {"implementation_sha256": "f" * 64}
    elif corruption == "wrong_restoration_hash":
        oracle_result["value_state_sha256_after"] = "e" * 64
    elif corruption == "wrong_containment_hash":
        oracle_result["record_sha256"] = "0" * 64
    if corruption != "wrong_containment_hash":
        _resign_containment_record(policy, oracle_result)
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    with pytest.raises(S44CModelBuilderError):
        _apply_sale_state_preservation(
            model,
            containment_result=oracle_result,
            containment_policy=containment,
            contract=policy["state_preservation"],
            tolerance=1e-6,
        )


def test_sale_state_capture_rejects_missing_extra_and_nonfinite_model_state() -> None:
    missing = _sale_model()
    missing.del_component("cold_slab_inventory")
    with pytest.raises(S44CModelBuilderError, match="schema mismatch"):
        _capture_sale_state_preservation_targets(
            missing,
            contract=_state_preservation_contract(),
            saved_capture={
                "configuration_id": "C0_current_BF_BOF_reference",
                "replan_index": 0,
                "provenance": {"implementation_sha256": "a" * 64},
            },
        )
    extra = _sale_model()
    extra.dri_inventory = Var(extra.TIME, initialize=0.0)
    with pytest.raises(S44CModelBuilderError, match="schema mismatch"):
        _capture_sale_state_preservation_targets(
            extra,
            contract=_state_preservation_contract(),
            saved_capture={
                "configuration_id": "C0_current_BF_BOF_reference",
                "replan_index": 0,
                "provenance": {"implementation_sha256": "a" * 64},
            },
        )
    nonfinite = _sale_model()
    nonfinite.coke_inventory[1].set_value(float("nan"))
    with pytest.raises(S44CModelBuilderError, match="nonfinite"):
        _capture_sale_state_preservation_targets(
            nonfinite,
            contract=_state_preservation_contract(),
            saved_capture={
                "configuration_id": "C0_current_BF_BOF_reference",
                "replan_index": 0,
                "provenance": {"implementation_sha256": "a" * 64},
            },
        )


def test_sale_state_constraints_preserve_degenerate_terminal_state(
    local_test_tmp: Path,
) -> None:
    model = _sale_model()
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    context = _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    model.static_price_naive_objective.deactivate()
    model.depleting_tie_break = Objective(
        expr=model.coke_inventory[1]
        + model.sinter_inventory[1]
        + model.hot_iron_inventory[1]
        + model.cold_slab_inventory[1],
        sense=minimize,
    )
    result = _solver().solve(model)
    finalized = _finalize_sale_state_preservation(
        model,
        context=context,
        termination_condition=str(result.solver.termination_condition),
        tolerance=1.0,
    )
    assert finalized["status"] == "pass"
    assert finalized["max_residual"] == pytest.approx(0.0)
    assert json.loads(Path(context["evidence_path"]).read_text())["status"] == (
        "targets_applied_pending_economic_solve"
    )
    assert Path(finalized["evidence_path"]).name == (
        "sale_state_preservation_final.json"
    )
    assert finalized["pre_solve_evidence_sha256"]


def test_sale_state_final_audit_catches_terminal_residual(
    local_test_tmp: Path,
) -> None:
    model = _sale_model()
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    context = _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    model.coke_inventory[1].set_value(
        context["targets"]["coke_inventory_t"] - 1.000001
    )
    finalized = _finalize_sale_state_preservation(
        model,
        context=context,
        termination_condition="optimal",
        tolerance=1.0,
    )
    assert finalized["status"] == "fail_closed"
    assert finalized["absolute_residuals"]["coke_inventory_t"] == pytest.approx(
        1.000001
    )
    assert value(model.sale_state_coke_inventory_preservation_exact.body) < value(
        model.sale_state_coke_inventory_preservation_exact.lower
    )


def test_sale_state_final_audit_fails_on_nonfinite_or_band_schema_mismatch(
    local_test_tmp: Path,
) -> None:
    model = _sale_model()
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    context = _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    model.del_component("sale_state_coke_inventory_preservation_exact")
    model.coke_inventory[1].set_value(float("nan"))
    finalized = _finalize_sale_state_preservation(
        model,
        context=context,
        termination_condition="optimal",
        tolerance=1.0,
    )
    assert finalized["status"] == "fail_closed"
    assert finalized["absolute_residuals"]["coke_inventory_t"] is None
    assert "constraint_name_schema_mismatch" in finalized[
        "schema_failure_reasons"
    ]


def test_sale_state_preservation_is_c0_only_and_adds_nothing_before_rejection() -> None:
    model = _sale_model()
    with pytest.raises(S44CModelBuilderError, match="available for C0 only"):
        _solve_with_optional_lexicographic_cost(
            model,
            solver=_solver(),
            configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF",
            deterministic_cost_policy=_cost_policy(electricity_price=100.0),
            electricity_sale_sensitivity=_sale_policy(100.0),
        )
    assert not any(
        name.startswith("sale_state_") for name in model.component_map()
    )


def test_executed_hours_only_revenue_and_no_double_count() -> None:
    rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "replan_index": 0,
            "hour_index": 0,
            "gross_grid_import_mwh": 0.0,
            "gross_grid_export_mwh": 2.0,
            "total_generator_electricity_mwh": 7.0,
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "replan_index": 1,
            "hour_index": 0,
            "gross_grid_import_mwh": 3.0,
            "gross_grid_export_mwh": 0.0,
            "total_generator_electricity_mwh": 2.0,
        },
    ]
    result = executed_sale_accounting(rows, {(0, 0): 100.0, (1, 0): -20.0})
    assert result["executed_import_cost_eur"] == pytest.approx(-60.0)
    assert result["executed_export_revenue_eur"] == pytest.approx(200.0)
    assert result["executed_net_electricity_cost_eur"] == pytest.approx(-260.0)
    assert not any(
        min(float(row["gross_grid_import_mwh"]), float(row["gross_grid_export_mwh"]))
        for row in rows
    )


def _negative_guardrail_row(
    *, replan: object = 4, price: object = -10.0, exported: object = 0.0
) -> dict[str, object]:
    return {
        "configuration_id": "C0_current_BF_BOF_reference",
        "replan_index": replan,
        "electricity_sale_price_eur_per_mwh": price,
        "gross_grid_export_mwh": exported,
    }


def test_negative_price_guardrail_rejects_vacuous_required_scope() -> None:
    result = negative_price_export_coherence(
        [_negative_guardrail_row(price=1.0)],
        require_negative_hour=True,
        target_replan=4,
        validation_scope="volatile_prefix",
    )
    assert result["status"] == "fail"
    assert result["negative_hour_count"] == 0
    assert "required_negative_executed_hour_absent" in result["failure_reasons"]
    assert "target_replan_has_no_negative_executed_hour" in result[
        "failure_reasons"
    ]


def test_negative_price_guardrail_requires_designated_replan_four() -> None:
    result = negative_price_export_coherence(
        [_negative_guardrail_row(replan=2)],
        require_negative_hour=True,
        target_replan=4,
        validation_scope="volatile_prefix",
    )
    assert result["status"] == "fail"
    assert result["negative_replan_indices"] == "2"
    assert "target_replan_has_no_negative_executed_hour" in result[
        "failure_reasons"
    ]


def test_negative_price_guardrail_checks_export_at_every_negative_hour() -> None:
    result = negative_price_export_coherence(
        [
            _negative_guardrail_row(replan=4, price=-1.0, exported=0.0),
            _negative_guardrail_row(replan=4, price=-2.0, exported=2e-6),
        ],
        require_negative_hour=True,
        target_replan=4,
        validation_scope="volatile_prefix",
    )
    assert result["status"] == "fail"
    assert result["negative_hour_count"] == 2
    assert result["min_executed_price"] == pytest.approx(-2.0)
    assert result["max_negative_hour_export"] == pytest.approx(2e-6)
    assert "export_above_tolerance_at_negative_price" in result[
        "failure_reasons"
    ]


@pytest.mark.parametrize(
    "row",
    [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "replan_index": 4,
            "gross_grid_export_mwh": 0.0,
        },
        _negative_guardrail_row(exported=""),
        _negative_guardrail_row(replan="bad"),
        _negative_guardrail_row(price=float("nan")),
        _negative_guardrail_row(exported=float("inf")),
    ],
)
def test_negative_price_guardrail_rejects_malformed_rows(
    row: dict[str, object],
) -> None:
    result = negative_price_export_coherence(
        [row],
        require_negative_hour=True,
        target_replan=4,
        validation_scope="volatile_prefix",
    )
    assert result["status"] == "fail"
    assert "malformed_c0_executed_row" in result["failure_reasons"]


def test_calm_negative_guardrail_allows_empty_set_but_checks_any_present() -> None:
    empty = negative_price_export_coherence(
        [_negative_guardrail_row(price=10.0)],
        require_negative_hour=False,
        target_replan=None,
        validation_scope="calm",
    )
    assert empty["status"] == "pass"
    assert empty["negative_hour_count"] == 0
    present = negative_price_export_coherence(
        [_negative_guardrail_row(price=-1.0, exported=1e-5)],
        require_negative_hour=False,
        target_replan=None,
        validation_scope="calm",
    )
    assert present["status"] == "fail"


def test_objective_hierarchy_sale_value_and_negative_price_behavior(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    positive = _sale_model()
    positive_policy = _install_verified_containment_stub(
        positive,
        root=local_test_tmp / "positive",
        price=100.0,
        monkeypatch=monkeypatch,
    )
    _, positive_meta = _solve_with_optional_lexicographic_cost(
        positive,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(electricity_price=100.0),
        electricity_sale_sensitivity=positive_policy,
    )
    assert positive_meta["primary_electricity_export_revenue_eur"] > 0.0
    assert positive_meta["sale_economic_validation_overlay"]["status"] == "pass"
    assert positive_meta["sale_economic_validation_overlay"][
        "underlying_core_unchanged"
    ] is True
    assert Path(
        positive_meta["sale_economic_validation_overlay"]["evidence_path"]
    ).is_file()
    assert positive_meta["sale_state_preservation"]["status"] == "pass"
    assert sum(value(positive.gross_grid_export_mwh[t]) for t in positive.TIME) > 0.0

    negative = _sale_model()
    negative_policy = _install_verified_containment_stub(
        negative,
        root=local_test_tmp / "negative",
        price=-20.0,
        monkeypatch=monkeypatch,
    )
    _, negative_meta = _solve_with_optional_lexicographic_cost(
        negative,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(electricity_price=-20.0),
        electricity_sale_sensitivity=negative_policy,
    )
    assert negative_meta["primary_electricity_export_revenue_eur"] == pytest.approx(0.0)
    assert sum(value(negative.gross_grid_export_mwh[t]) for t in negative.TIME) == pytest.approx(0.0)
    assert positive.static_price_naive_objective.active
    assert hasattr(positive, "procurement_cost_optimum_preservation")


def test_ng_price_efficiency_break_even_direction(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    low_ng = _sale_model(wag_generation=0.0)
    low_policy = _install_verified_containment_stub(
        low_ng,
        root=local_test_tmp / "low",
        price=100.0,
        monkeypatch=monkeypatch,
    )
    _solve_with_optional_lexicographic_cost(
        low_ng,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(electricity_price=100.0, ng_price=30.0),
        electricity_sale_sensitivity=low_policy,
    )
    high_ng = _sale_model(wag_generation=0.0)
    high_policy = _install_verified_containment_stub(
        high_ng,
        root=local_test_tmp / "high",
        price=100.0,
        monkeypatch=monkeypatch,
    )
    _solve_with_optional_lexicographic_cost(
        high_ng,
        solver=_solver(),
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy=_cost_policy(electricity_price=100.0, ng_price=55.0),
        electricity_sale_sensitivity=high_policy,
    )
    assert sum(value(low_ng.ng_fuel_mwh[t]) for t in low_ng.TIME) >= sum(
        value(high_ng.ng_fuel_mwh[t]) for t in high_ng.TIME
    )


def test_complete_handoff_state_and_cumulative_progress_preserved() -> None:
    handoff = _complete_handoff_rows(1)
    continuity = handoff_continuity(
        handoff,
        phase2_single_window_preflight=True,
        expected_replan_count=1,
    )
    assert continuity["status"] == "pass"
    assert continuity["inter_window_handoff_continuity"] == "not_applicable"
    execution = [
        {
            "configuration_id": row["configuration_id"],
            "replan_index": 0,
            "executed_final_product_t": 10.0,
            "cumulative_executed_final_product_t": 10.0,
        }
        for row in handoff
    ]
    progress = [
        {
            "configuration_id": row["configuration_id"],
            "replan_index": 0,
            "executed_before_t": 0.0,
            "cumulative_executed_after_t": 10.0,
            "carried_credit_before_t": 0.0,
            "carried_credit_after_t": 0.0,
            "executed_block_t": 10.0,
        }
        for row in handoff
    ]
    assert all(
        row["status"] == "pass"
        for row in cross_policy_state_guardrails(
            execution, execution, handoff, handoff, progress, progress
        )
    )


def test_volatile_prefix_checks_all_four_transitions_for_both_configurations() -> None:
    result = handoff_continuity(
        _complete_handoff_rows(5),
        phase2_single_window_preflight=False,
        expected_replan_count=5,
    )
    assert result["status"] == "pass"
    assert result["validation_scope"] == "complete_multi_window_handoff_chain"
    assert result["checked_transition_count"] == 8
    assert result["inter_window_handoff_continuity"] == "pass"


def _cross_policy_progress_check(
    comparator_progress: list[dict[str, object]],
    sale_progress: list[dict[str, object]],
) -> list[dict[str, object]]:
    replan_count = len(comparator_progress) // 2
    handoff = _complete_handoff_rows(replan_count)
    execution = [
        {
            "configuration_id": row["configuration_id"],
            "replan_index": row["replan_index"],
            "executed_final_product_t": 10.0,
            "cumulative_executed_final_product_t": 10.0,
        }
        for row in handoff
    ]
    return cross_policy_state_guardrails(
        execution,
        execution,
        handoff,
        handoff,
        comparator_progress,
        sale_progress,
        tolerance=1e-6,
    )


def _governed_progress_rows(replan_count: int) -> list[dict[str, object]]:
    return [
        {
            "configuration_id": configuration,
            "replan_index": replan,
            "executed_before_t": 123456.789012345 + replan,
            "cumulative_executed_after_t": 124456.789012345 + replan,
            "carried_credit_before_t": 0.125 + replan,
            "carried_credit_after_t": 0.25 + replan,
            "executed_block_t": 1000.0,
        }
        for replan in range(replan_count)
        for configuration in (
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        )
    ]


def test_actual_governed_progress_schema_compares_full_precision_state() -> None:
    rows = _governed_progress_rows(2)
    progress = next(
        row
        for row in _cross_policy_progress_check(rows, [dict(row) for row in rows])
        if row["guardrail"] == "cross_policy_cumulative_progress_state"
    )
    assert progress["status"] == "pass"
    assert progress["max_residual"] == pytest.approx(0.0)


def test_progress_schema_requires_executed_before_t_without_alias_fallback() -> None:
    comparator = _governed_progress_rows(1)
    sale = [dict(row) for row in comparator]
    sale[0].pop("executed_before_t")
    checks = _cross_policy_progress_check(comparator, sale)
    assert checks == [
        {
            "guardrail": "cross_policy_cumulative_progress_schema",
            "status": "fail",
            "max_residual": "missing_field",
        }
    ]


def test_progress_mismatch_in_last_replan_fails_governed_tolerance() -> None:
    comparator = _governed_progress_rows(2)
    sale = [dict(row) for row in comparator]
    sale[-1]["executed_before_t"] = (
        float(sale[-1]["executed_before_t"]) + 2e-6
    )
    progress = next(
        row
        for row in _cross_policy_progress_check(comparator, sale)
        if row["guardrail"] == "cross_policy_cumulative_progress_state"
    )
    assert progress["status"] == "fail"
    assert progress["max_residual"] == pytest.approx(2e-6)


def _write_containment_record(
    root: Path,
    directory: str,
    payload: object = None,
) -> None:
    target = root / directory / "sale_incumbent_containment.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if payload == "malformed":
        target.write_text("{", encoding="utf-8")
    else:
        target.write_text(
            json.dumps({"status": "pass"} if payload is None else payload),
            encoding="utf-8",
        )
    suffix = directory.removeprefix("replan_")
    replan_index = int(suffix) if suffix.isdigit() else 0
    target_schema = [
        "executed_final_product_t",
        "executed_bof_liquid_steel_t",
        "executed_hsm_final_output_t",
        "executed_dsp_final_output_t",
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
    ]
    targets = {
        "executed_final_product_t": 18_493.150684931505,
        "executed_bof_liquid_steel_t": 19_466.47440519106,
        "executed_hsm_final_output_t": 14_000.0,
        "executed_dsp_final_output_t": 4_493.150684931505,
        "coke_inventory_t": 245.38021409043836,
        "sinter_inventory_t": 0.0,
        "hot_iron_inventory_t": 500.0,
        "cold_slab_inventory_t": 12_456.801578003515,
    }
    cumulative_components = {
        "executed_final_product_t": "final_product_output",
        "executed_bof_liquid_steel_t": "bof_crude_steel_output",
        "executed_hsm_final_output_t": "c0_hsm_final_product_output",
        "executed_dsp_final_output_t": "c0_dsp_final_product_output",
    }
    state_schema = [
        {
            "target_id": key,
            "model_component": cumulative_components.get(
                key, key.removesuffix("_t")
            ),
            "selection": (
                "sum_executed_hours"
                if key in cumulative_components
                else "handoff_hour"
            ),
            "unit": "t",
            "operational_constraint": "full_precision_exact_equality",
            "final_validation": "independent_state_acceptance",
            "allowed_tolerance_t": 1.0,
        }
        for key in target_schema
    ]
    constraint_names = {
        key: f"sale_state_{stem}_preservation_exact"
        for key, stem in {
            "executed_final_product_t": "executed_final_product",
            "executed_bof_liquid_steel_t": "executed_bof_liquid_steel",
            "executed_hsm_final_output_t": "executed_hsm_final_output",
            "executed_dsp_final_output_t": "executed_dsp_final_output",
            "coke_inventory_t": "coke_inventory",
            "sinter_inventory_t": "sinter_inventory",
            "hot_iron_inventory_t": "hot_iron_inventory",
            "cold_slab_inventory_t": "cold_slab_inventory",
        }.items()
    }
    target_bounds = {
        key: {
            "lower_bound_t": target - 1.0,
            "upper_bound_t": target + 1.0,
        }
        for key, target in targets.items()
    }
    implementation_sha = "a" * 64
    pre = {
        "schema_version": "steel_phase2_sale_state_preservation_v4",
        "status": "targets_applied_pending_economic_solve",
        "configuration_id": "C0_current_BF_BOF_reference",
        "replan_index": replan_index,
        "implementation_sha256": implementation_sha,
        "source_capture_sha256": "b" * 64,
        "source_capture_provenance": {
            "implementation_sha256": implementation_sha
        },
        "containment_record_sha256": __import__("hashlib").sha256(
            target.read_bytes()
        ).hexdigest(),
        "target_schema": target_schema,
        "targets": targets,
        "targets_sha256": modelbuilder._canonical_payload_sha256(targets),
        "target_bounds": target_bounds,
        "target_bounds_sha256": modelbuilder._canonical_payload_sha256(
            target_bounds
        ),
        "state_schema": state_schema,
        "state_schema_sha256": modelbuilder._canonical_payload_sha256(
            state_schema
        ),
        "constraint_names": constraint_names,
        "constraint_names_sha256": modelbuilder._canonical_payload_sha256(
            constraint_names
        ),
    }
    pre_path = target.parent / "sale_state_preservation_pre_solve.json"
    pre_path.write_text(
        json.dumps(pre, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    actual_values = dict(targets)
    actual_values["executed_final_product_t"] = 18_493.15068493151
    signed_residuals = {
        key: actual_values[key] - targets[key] for key in target_schema
    }
    absolute_residuals = {
        key: abs(signed_residuals[key]) for key in target_schema
    }
    normalized_residuals = {
        key: absolute_residuals[key] for key in target_schema
    }
    final = {
        **pre,
        "status": "pass",
        "actual_values": actual_values,
        "signed_residuals": signed_residuals,
        "absolute_residuals": absolute_residuals,
        "normalized_residuals": normalized_residuals,
        "per_state_validation": {
            key: {
                "status": "pass",
                "aggregation": "independent_state_no_accumulation",
                "allowed_tolerance": 1.0,
                "allowed_tolerance_t": 1.0,
                "signed_residual_t": signed_residuals[key],
                "absolute_residual_t": absolute_residuals[key],
                "normalized_residual": normalized_residuals[key],
                "raw_residual": absolute_residuals[key],
                "used_relaxation": 0.0,
                "purpose": "cumulative_production_or_carried_state",
                "unit": "t",
                "validation_id": f"sale_state_preservation[{key}]",
                "target_value_t": targets[key],
                "lower_bound_t": target_bounds[key]["lower_bound_t"],
                "upper_bound_t": target_bounds[key]["upper_bound_t"],
            }
            for key in target_schema
        },
        "max_residual": max(absolute_residuals.values()),
        "pre_solve_evidence_sha256": __import__("hashlib").sha256(
            pre_path.read_bytes()
        ).hexdigest(),
    }
    (target.parent / "sale_state_preservation_final.json").write_text(
        json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runtime_edges = (
        (
            "c0_reference_deadline_bof_liquid_steel_48h_lower",
            1.000000000014552,
            1.4551915228366852e-11,
        ),
        (
            "c0_reference_deadline_hsm_final_output_48h_upper",
            1.000000000003638,
            3.637978807091713e-12,
        ),
    )
    economic_rows: list[dict[str, object]] = []
    for row_index in range(48):
        if row_index < len(runtime_edges):
            name, raw_residual, excess = runtime_edges[row_index]
        else:
            name = f"registered_runtime_validation_row_{row_index:02d}"
            raw_residual = 0.0
            excess = 0.0
        economic_rows.append(
            {
                "constraint_name": name,
                "validation_id": name,
                "constraint_family": name,
                "constraint_index": "None",
                "relaxation_allowed": True,
                "status": "pass",
                "purpose": "cumulative_production_acceptance",
                "unit": "t",
                "aggregation": "row_specific_cumulative_not_hourly_accumulated",
                "raw_residual": raw_residual,
                "allowed_tolerance": 1.0,
                "governed_tolerance": 1.0,
                "excess_beyond_governed_tolerance": excess,
                "solver_numerical_allowance": SOLVER_NUMERICAL_TOLERANCE,
                "overlay_raw_residual": excess,
                "overlay_residual": excess,
                "normalized_residual": raw_residual,
                "used_relaxation": 0.0,
                "original_expression": f"original {name}",
                "overlay_expression": f"overlay {name}",
            }
        )
    economic_overlay = {
        "schema_version": "steel_sale_economic_validation_overlay_v2",
        "status": "pass",
        "policy": policy_contract(),
        "underlying_core_unchanged": True,
        "underlying_core_sha256_before": "c" * 64,
        "underlying_core_sha256_after_install": "c" * 64,
        "registered_acceptance_row_count": 48,
        "failed_validation_row_count": 0,
        "rows_sha256": modelbuilder._canonical_payload_sha256(economic_rows),
        "rows": economic_rows,
    }
    (
        target.parent / "sale_economic_validation_overlay.json"
    ).write_text(
        json.dumps(economic_overlay, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_containment_scope_is_explicit_and_full_matrix_remains_seven() -> None:
    experiment = {"replan_count": 7}
    assert _expected_containment_replan_indices(experiment, {}) == tuple(range(7))
    assert _expected_containment_replan_indices(
        experiment,
        {
            "replan_count": 1,
            "phase2_single_window_preflight": True,
            "phase2_single_window_preflight_mode": (
                "preflight_volatile_containment"
            ),
        },
    ) == (0,)
    assert _expected_containment_replan_indices(
        experiment,
        {
            "replan_count": 5,
            "phase2_bounded_prefix_preflight": True,
            "phase2_bounded_prefix_target_replan": 4,
            "phase2_bounded_prefix_preflight_mode": "preflight_volatile",
        },
    ) == tuple(range(5))
    with pytest.raises(SaleSensitivityError, match="contradictory"):
        _expected_containment_replan_indices(
            experiment,
            {"replan_count": 1, "phase2_single_window_preflight": False},
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"replan_count": 5},
        {
            "replan_count": 5,
            "phase2_single_window_preflight": True,
            "phase2_bounded_prefix_preflight": True,
        },
        {
            "replan_count": 4,
            "phase2_bounded_prefix_preflight": True,
            "phase2_bounded_prefix_target_replan": 4,
            "phase2_bounded_prefix_preflight_mode": "preflight_volatile",
        },
        {
            "replan_count": 5,
            "phase2_bounded_prefix_preflight": True,
            "phase2_bounded_prefix_target_replan": 3,
            "phase2_bounded_prefix_preflight_mode": "preflight_volatile",
        },
    ],
)
def test_containment_scope_rejects_contradictory_or_unflagged_shortening(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(SaleSensitivityError, match="contradictory"):
        _expected_containment_replan_indices(
            {"replan_count": 7}, overrides
        )


def test_flagged_single_window_containment_requires_exact_replan_zero(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    expected = _expected_containment_replan_indices(
        {"replan_count": 7},
        {
            "replan_count": 1,
            "phase2_single_window_preflight": True,
            "phase2_single_window_preflight_mode": "preflight_containment",
        },
    )
    result = _validate_containment_records(
        root, expected_replan_indices=expected
    )
    assert result["status"] == "pass"
    assert result["expected_record_count"] == 1
    assert result["checked_record_count"] == 1
    assert result["checked_replan_indices"] == "0"


def test_real_runtime_evidence_schema_with_48_overlay_rows_passes_parent_verifier(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    directory = root / "replan_00"
    pre = json.loads(
        (directory / "sale_state_preservation_pre_solve.json").read_text(
            encoding="utf-8"
        )
    )
    final = json.loads(
        (directory / "sale_state_preservation_final.json").read_text(
            encoding="utf-8"
        )
    )
    overlay = json.loads(
        (directory / "sale_economic_validation_overlay.json").read_text(
            encoding="utf-8"
        )
    )

    assert pre["status"] == "targets_applied_pending_economic_solve"
    assert pre["targets"]["executed_final_product_t"] == 18_493.150684931505
    assert final["status"] == "pass"
    assert final["actual_values"]["executed_final_product_t"] == 18_493.15068493151
    assert final["max_residual"] == 3.637978807091713e-12
    assert overlay["schema_version"] == "steel_sale_economic_validation_overlay_v2"
    assert overlay["status"] == "pass"
    assert overlay["policy"] == policy_contract()
    assert overlay["registered_acceptance_row_count"] == 48
    assert overlay["failed_validation_row_count"] == 0
    assert len(overlay["rows"]) == 48

    result = _validate_containment_records(
        root, expected_replan_indices=(0,)
    )

    assert result["status"] == "pass"
    assert result["state_preservation_passed_record_count"] == 1
    assert result["max_residual"] == 3.637978807091713e-12


def test_unflagged_single_record_fails_against_full_seven_replans(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    with pytest.raises(SaleSensitivityError, match="contradictory"):
        _expected_containment_replan_indices(
            {"replan_count": 7},
            {"replan_count": 1, "phase2_single_window_preflight": False},
        )


def test_multi_window_containment_checks_every_replan_zero_through_six(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    for index in range(7):
        _write_containment_record(root, f"replan_{index:02d}")
    result = _validate_containment_records(
        root, expected_replan_indices=tuple(range(7))
    )
    assert result["status"] == "pass"
    assert result["passed_record_count"] == 7
    assert result["checked_replan_indices"] == "0;1;2;3;4;5;6"
    assert result["max_residual"] == 3.637978807091713e-12


def test_volatile_prefix_containment_checks_exact_replans_zero_through_four(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    for index in range(5):
        _write_containment_record(root, f"replan_{index:02d}")
    expected = _expected_containment_replan_indices(
        {"replan_count": 7},
        {
            "replan_count": 5,
            "phase2_bounded_prefix_preflight": True,
            "phase2_bounded_prefix_target_replan": 4,
            "phase2_bounded_prefix_preflight_mode": "preflight_volatile",
        },
    )
    result = _validate_containment_records(
        root, expected_replan_indices=expected
    )
    assert result["status"] == "pass"
    assert result["expected_replan_indices"] == "0;1;2;3;4"
    assert result["state_preservation_passed_record_count"] == 5


def test_containment_missing_expected_record_fails(local_test_tmp: Path) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    result = _validate_containment_records(root, expected_replan_indices=(0, 1))
    assert result["status"] == "fail"
    assert result["missing_record_paths"] == (
        "replan_01/sale_incumbent_containment.json"
    )


def test_containment_duplicate_equivalent_directory_fails(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    _write_containment_record(root, "replan_0")
    result = _validate_containment_records(root, expected_replan_indices=(0,))
    assert result["status"] == "fail"
    assert result["duplicate_replan_indices"] == "0"
    assert "replan_0/sale_incumbent_containment.json" in result[
        "extra_record_paths"
    ]


def test_containment_wrong_replan_index_fails(local_test_tmp: Path) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_01")
    result = _validate_containment_records(root, expected_replan_indices=(0,))
    assert result["status"] == "fail"
    assert result["checked_replan_indices"] == "1"
    assert result["missing_record_paths"]
    assert result["extra_record_paths"]


@pytest.mark.parametrize(
    "payload",
    [{"status": "fail"}, "malformed"],
)
def test_containment_failed_or_malformed_record_fails(
    local_test_tmp: Path, payload: object
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00", payload)
    result = _validate_containment_records(root, expected_replan_indices=(0,))
    assert result["status"] == "fail"
    assert result["failed_or_malformed_record_paths"] == (
        "replan_00/sale_incumbent_containment.json"
    )


def test_containment_requires_durable_pre_and_final_preservation_evidence(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    (root / "replan_00/sale_state_preservation_final.json").unlink()
    result = _validate_containment_records(root, expected_replan_indices=(0,))
    assert result["status"] == "fail"
    assert "missing_state_preservation_evidence" in result["failure_reasons"]


def test_containment_rejects_preservation_residual_mismatch(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    final_path = root / "replan_00/sale_state_preservation_final.json"
    final = json.loads(final_path.read_text())
    final["actual_values"]["coke_inventory_t"] += 1.0
    final_path.write_text(json.dumps(final), encoding="utf-8")
    result = _validate_containment_records(root, expected_replan_indices=(0,))
    assert result["status"] == "fail"
    assert "failed_state_preservation_evidence" in result["failure_reasons"]


def test_containment_accepts_solver_numerical_excess_after_governed_tolerance(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    overlay_path = root / "replan_00/sale_economic_validation_overlay.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    exact_residuals = (
        (
            "c0_reference_deadline_bof_liquid_steel_48h_lower",
            1.000000000014552,
            1.4551915228366852e-11,
        ),
        (
            "c0_reference_deadline_hsm_final_output_48h_upper",
            1.000000000003638,
            3.637978807091713e-12,
        ),
    )
    rows = [
        {
            "constraint_name": name,
            "relaxation_allowed": True,
            "status": "pass",
            "raw_residual": raw_residual,
            "allowed_tolerance": 1.0,
            "governed_tolerance": 1.0,
            "excess_beyond_governed_tolerance": excess,
            "solver_numerical_allowance": SOLVER_NUMERICAL_TOLERANCE,
            "overlay_raw_residual": excess,
            "overlay_residual": excess,
            "normalized_residual": raw_residual,
            "original_expression": f"original {name}",
            "overlay_expression": f"overlay {name}",
        }
        for name, raw_residual, excess in exact_residuals
    ]
    overlay["registered_acceptance_row_count"] = len(rows)
    overlay["rows"] = rows
    overlay["rows_sha256"] = modelbuilder._canonical_payload_sha256(rows)
    overlay_path.write_text(
        json.dumps(overlay, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = _validate_containment_records(root, expected_replan_indices=(0,))

    assert result["status"] == "pass"
    assert result["state_preservation_passed_record_count"] == 1


def test_containment_rejects_excess_above_solver_numerical_allowance(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "containment"
    _write_containment_record(root, "replan_00")
    overlay_path = root / "replan_00/sale_economic_validation_overlay.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    excess = 2.0 * SOLVER_NUMERICAL_TOLERANCE
    row = {
        "constraint_name": "c0_reference_deadline_bof_liquid_steel_48h_lower",
        "relaxation_allowed": True,
        "status": "pass",
        "raw_residual": 1.0 + excess,
        "allowed_tolerance": 1.0,
        "governed_tolerance": 1.0,
        "excess_beyond_governed_tolerance": excess,
        "solver_numerical_allowance": SOLVER_NUMERICAL_TOLERANCE,
        "overlay_raw_residual": excess,
        "overlay_residual": excess,
        "normalized_residual": 1.0 + excess,
        "original_expression": "original lower deadline",
        "overlay_expression": "expanded lower deadline",
    }
    overlay["registered_acceptance_row_count"] = 1
    overlay["rows"] = [row]
    overlay["rows_sha256"] = modelbuilder._canonical_payload_sha256([row])
    overlay_path.write_text(
        json.dumps(overlay, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = _validate_containment_records(root, expected_replan_indices=(0,))

    assert result["status"] == "fail"
    assert "failed_state_preservation_evidence" in result["failure_reasons"]


def test_single_window_requires_exact_c0_and_c1_replan_zero_rows() -> None:
    rows = _complete_handoff_rows(1)
    assert _validate_inventory_handoff_contract(
        rows, replan_count=1, phase2_single_window_preflight=True
    )["status"] == "pass"
    missing = _validate_inventory_handoff_contract(
        rows[:-1], replan_count=1, phase2_single_window_preflight=True
    )
    assert missing["status"] == "fail"
    assert any("missing_rows" in reason for reason in missing["failure_reasons"])


def test_single_window_rejects_nonzero_replan_row() -> None:
    rows = _complete_handoff_rows(1)
    rows[0]["replan_index"] = 1
    result = _validate_inventory_handoff_contract(
        rows, replan_count=1, phase2_single_window_preflight=True
    )
    assert result["status"] == "fail"
    assert result["terminal_handoff_snapshot_complete"] is False


def test_single_window_rejects_empty_terminal_snapshot() -> None:
    rows = _complete_handoff_rows(1)
    rows[0]["next_overrides"] = "{}"
    result = _validate_inventory_handoff_contract(
        rows, replan_count=1, phase2_single_window_preflight=True
    )
    assert result["status"] == "fail"
    assert any("incomplete_next_schema" in reason for reason in result["failure_reasons"])


def test_single_window_requires_complete_c0_terminal_schema() -> None:
    rows = _complete_handoff_rows(1)
    payload = json.loads(str(rows[0]["next_overrides"]))
    payload.pop("coke_store_initial_t")
    rows[0]["next_overrides"] = json.dumps(payload)
    result = _validate_inventory_handoff_contract(
        rows, replan_count=1, phase2_single_window_preflight=True
    )
    assert result["terminal_handoff_snapshot_complete"] is False


def test_single_window_requires_complete_c1_terminal_schema() -> None:
    rows = _complete_handoff_rows(1)
    payload = json.loads(str(rows[1]["next_overrides"]))
    payload.pop("dri_buffer_initial_t")
    rows[1]["next_overrides"] = json.dumps(payload)
    result = _validate_inventory_handoff_contract(
        rows, replan_count=1, phase2_single_window_preflight=True
    )
    assert result["terminal_handoff_snapshot_complete"] is False


def test_single_window_rejects_nonfinite_terminal_state() -> None:
    rows = _complete_handoff_rows(1)
    payload = json.loads(str(rows[0]["next_overrides"]))
    payload["coke_store_initial_t"] = float("nan")
    rows[0]["next_overrides"] = json.dumps(payload)
    result = _validate_inventory_handoff_contract(
        rows, replan_count=1, phase2_single_window_preflight=True
    )
    assert result["status"] == "fail"
    assert any("nonfinite_terminal_state" in reason for reason in result["failure_reasons"])


def test_single_window_reports_neutral_na_without_propagation_claim() -> None:
    result = _validate_inventory_handoff_contract(
        _complete_handoff_rows(1),
        replan_count=1,
        phase2_single_window_preflight=True,
    )
    assert result["validation_scope"] == "phase2_single_window_terminal_snapshot_only"
    assert result["inter_window_handoff_continuity"] == "not_applicable"
    assert result["checked_transition_count"] == 0


def test_unflagged_one_replan_fails_closed() -> None:
    result = _validate_inventory_handoff_contract(
        _complete_handoff_rows(1),
        replan_count=1,
        phase2_single_window_preflight=False,
    )
    assert result["status"] == "fail"
    assert result["validation_scope"] == "invalid_unflagged_single_window"


def test_multi_window_checks_every_configuration_and_transition() -> None:
    result = _validate_inventory_handoff_contract(
        _complete_handoff_rows(3),
        replan_count=3,
        phase2_single_window_preflight=False,
    )
    assert result["status"] == "pass"
    assert result["inter_window_handoff_continuity"] == "pass"
    assert result["checked_transition_count"] == 4
    assert result["checked_state_value_count"] == 18


def test_multi_window_missing_configuration_replan_row_fails() -> None:
    rows = _complete_handoff_rows(3)
    rows = [
        row
        for row in rows
        if not (
            row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
            and row["replan_index"] == 1
        )
    ]
    result = _validate_inventory_handoff_contract(
        rows, replan_count=3, phase2_single_window_preflight=False
    )
    assert result["status"] == "fail"
    assert result["checked_transition_count"] < 4


def test_multi_window_incomplete_carried_start_schema_fails() -> None:
    rows = _complete_handoff_rows(2)
    row = next(
        item
        for item in rows
        if item["configuration_id"] == "C0_current_BF_BOF_reference"
        and item["replan_index"] == 1
    )
    payload = json.loads(str(row["start_overrides"]))
    payload.pop("hot_iron_store_initial_t")
    row["start_overrides"] = json.dumps(payload)
    result = _validate_inventory_handoff_contract(
        rows, replan_count=2, phase2_single_window_preflight=False
    )
    assert result["status"] == "fail"
    assert any("incomplete_start_schema" in reason for reason in result["failure_reasons"])


def test_multi_window_state_mismatch_fails_at_governed_tolerance() -> None:
    rows = _complete_handoff_rows(2)
    row = next(
        item
        for item in rows
        if item["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
        and item["replan_index"] == 1
    )
    payload = json.loads(str(row["start_overrides"]))
    payload["dri_buffer_initial_t"] += 2e-6
    row["start_overrides"] = json.dumps(payload)
    result = _validate_inventory_handoff_contract(
        rows,
        replan_count=2,
        phase2_single_window_preflight=False,
        tolerance=1e-6,
    )
    assert result["status"] == "fail"
    assert result["max_state_residual"] == pytest.approx(2e-6)


def test_cross_policy_terminal_equality_covers_every_dynamic_state() -> None:
    handoff = _complete_handoff_rows(1)
    altered = [dict(row) for row in handoff]
    payload = json.loads(str(altered[1]["next_overrides"]))
    payload["dri_buffer_initial_t"] += 1.000001
    altered[1]["next_overrides"] = json.dumps(payload)
    execution = [
        {
            "configuration_id": row["configuration_id"],
            "replan_index": 0,
            "executed_final_product_t": 1.0,
            "cumulative_executed_final_product_t": 1.0,
        }
        for row in handoff
    ]
    progress = [
        {
            "configuration_id": row["configuration_id"],
            "replan_index": 0,
            "executed_before_t": 0.0,
            "cumulative_executed_after_t": 1.0,
            "carried_credit_before_t": 0.0,
            "carried_credit_after_t": 0.0,
            "executed_block_t": 1.0,
        }
        for row in handoff
    ]
    checks = cross_policy_state_guardrails(
        execution, execution, handoff, altered, progress, progress
    )
    terminal = next(
        row
        for row in checks
        if row["guardrail"]
        == "cross_policy_terminal_handoff_snapshot_every_dynamic_state"
    )
    assert terminal["status"] == "fail"


def test_exact_matrix_no_held_out_guardrails_fingerprints_and_phase1_values() -> None:
    config = load_config()
    validate_config(config)
    assert config["full_matrix_execution_authorized"] is True
    assert config["full_matrix_post_review_token_sha256"] == (
        "0b6cbf5feb712535d6130fafb211b5f5d914d69ccaba6b88aeeada88455bb50c"
    )
    matrix = frozen_case_matrix(config)
    assert len(matrix) == 8
    assert {row["candidate_id"] for row in matrix} == {
        "recovery_bg30_ng55",
        "recovery_bg30_ng30",
    }
    assert {row["policy_id"] for row in matrix} == {
        "accepted_no_export_comparator",
        "athanasiadis_sale_enabled",
    }
    assert all(row["dataset_split"] == "validation" for row in matrix)
    assert all(row["price_field"] == "y_pred" for row in matrix)
    assert not any(row["perfect_foresight_oracle"] for row in matrix)
    immutable = config["experiment"]["immutable_phase1_contract"]
    authoritative = authoritative_phase1_contract(config)
    assert immutable["c0_background_percent"] == pytest.approx(30.0)
    assert immutable["generator_electricity_efficiency"] == pytest.approx(0.345)
    assert immutable["generator_electrical_capacity_mw"] == pytest.approx(770.0)
    assert immutable["generator_total_fuel_volume_cap_nm3_h"] == pytest.approx(900000.0)
    assert immutable["fixed_full_site_ng_pj_y"] == pytest.approx(8.005)
    assert immutable["flexible_other_site_heat_service_max_pj_y"] == pytest.approx(3.07)
    assert authoritative["total_wag_low_pj_y"] == pytest.approx(57.3)
    assert authoritative["total_wag_high_pj_y"] == pytest.approx(57.5)
    fingerprints = implementation_fingerprints(DEFAULT_CONFIG_PATH)
    assert fingerprints["expected_parent_head"]
    assert fingerprints["working_tree_diff_sha256"]
    assert fingerprints["supported_execution_modes"] == list(
        SUPPORTED_EXECUTION_MODES
    )
    assert "preflight_volatile_containment" in SUPPORTED_EXECUTION_MODES
    assert all(row["sha256"] for row in fingerprints["files"])
    exclusion = fingerprints["semantic_config_fingerprint"][
        "authorization_exclusion_contract"
    ]
    assert exclusion["excluded_fields"] == [
        "full_matrix_execution_authorized",
        "full_matrix_post_review_token_sha256",
    ]
    assert exclusion["all_other_config_fields_semantic"] is True


def test_semantic_and_authorization_fingerprints_are_strictly_separated(
    local_test_tmp: Path,
) -> None:
    base = load_config()
    base_path = local_test_tmp / "base.yaml"
    base_path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    token = "reviewed-token"
    authorized = deepcopy(base)
    authorized["full_matrix_execution_authorized"] = True
    authorized["full_matrix_post_review_token_sha256"] = __import__(
        "hashlib"
    ).sha256(token.encode("utf-8")).hexdigest()
    authorized_path = local_test_tmp / "authorized.yaml"
    authorized_path.write_text(
        yaml.safe_dump(authorized, sort_keys=False), encoding="utf-8"
    )
    base_fingerprints = implementation_fingerprints(base_path)
    authorized_fingerprints = implementation_fingerprints(authorized_path)
    base_implementation = _mapping_sha256(base_fingerprints)
    authorized_implementation = _mapping_sha256(authorized_fingerprints)
    assert base_implementation == authorized_implementation
    assert _mapping_sha256(
        {
            **base_fingerprints["sale_state_preservation_specification"],
            "implementation_sha256": base_implementation,
        }
    ) == _mapping_sha256(
        {
            **authorized_fingerprints[
                "sale_state_preservation_specification"
            ],
            "implementation_sha256": authorized_implementation,
        }
    )
    base_auth_sha = _mapping_sha256(
        _full_matrix_authorization_metadata(base)
    )
    authorized_auth_sha = _mapping_sha256(
        _full_matrix_authorization_metadata(authorized)
    )
    assert base_auth_sha != authorized_auth_sha
    assert __import__("hashlib").sha256(base_path.read_bytes()).hexdigest() != (
        __import__("hashlib").sha256(authorized_path.read_bytes()).hexdigest()
    )
    root = local_test_tmp / "attempts"
    base_attempt, _ = _prepare_attempt_output(
        root,
        run_identity={
            "implementation_sha256": base_implementation,
            "config_sha256": __import__("hashlib").sha256(
                base_path.read_bytes()
            ).hexdigest(),
            "full_matrix_authorization_metadata_sha256": base_auth_sha,
        },
        execution_mode="full_matrix",
        diagnostic_case_id=None,
    )
    authorized_attempt, _ = _prepare_attempt_output(
        root,
        run_identity={
            "implementation_sha256": authorized_implementation,
            "config_sha256": __import__("hashlib").sha256(
                authorized_path.read_bytes()
            ).hexdigest(),
            "full_matrix_authorization_metadata_sha256": authorized_auth_sha,
        },
        execution_mode="full_matrix",
        diagnostic_case_id=None,
    )
    assert base_attempt != authorized_attempt


def test_any_non_authorization_config_change_changes_implementation_identity(
    local_test_tmp: Path,
) -> None:
    base = load_config()
    changed = deepcopy(base)
    changed["run_class"] = str(changed["run_class"]) + " changed"
    base_path = local_test_tmp / "base.yaml"
    changed_path = local_test_tmp / "changed.yaml"
    base_path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    changed_path.write_text(
        yaml.safe_dump(changed, sort_keys=False), encoding="utf-8"
    )
    assert _mapping_sha256(implementation_fingerprints(base_path)) != (
        _mapping_sha256(implementation_fingerprints(changed_path))
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_flag",
        "missing_hash",
        "nonstrict_flag",
        "false_with_hash",
        "true_without_hash",
        "uppercase_hash",
    ],
)
@pytest.mark.parametrize("base_authorized", [False, True])
def test_authorization_metadata_missing_or_malformed_fails_closed(
    mutation: str,
    base_authorized: bool,
) -> None:
    config = load_config()
    config["full_matrix_execution_authorized"] = base_authorized
    config["full_matrix_post_review_token_sha256"] = (
        "b" * 64 if base_authorized else None
    )
    if mutation == "missing_flag":
        config.pop("full_matrix_execution_authorized")
    elif mutation == "missing_hash":
        config.pop("full_matrix_post_review_token_sha256")
    elif mutation == "nonstrict_flag":
        config["full_matrix_execution_authorized"] = 1
    elif mutation == "false_with_hash":
        config["full_matrix_execution_authorized"] = False
        config["full_matrix_post_review_token_sha256"] = "a" * 64
    elif mutation == "true_without_hash":
        config["full_matrix_execution_authorized"] = True
        config["full_matrix_post_review_token_sha256"] = None
    elif mutation == "uppercase_hash":
        config["full_matrix_execution_authorized"] = True
        config["full_matrix_post_review_token_sha256"] = "A" * 64
    with pytest.raises(SaleSensitivityError, match="authorization"):
        validate_config(config)


def test_preflight_scopes_and_full_matrix_remain_exactly_frozen() -> None:
    config = load_config()
    for mode, scenario in (
        ("preflight_containment", "calm_price_insensitive"),
        ("preflight_calm", "calm_price_insensitive"),
    ):
        cases, overrides = execution_plan(config, mode)
        assert len(cases) == 2
        assert {row["scenario_id"] for row in cases} == {scenario}
        assert {row["policy_id"] for row in cases} == {
            "accepted_no_export_comparator",
            "athanasiadis_sale_enabled",
        }
        assert overrides == {
            "replan_count": 1,
            "phase2_single_window_preflight": True,
            "phase2_single_window_preflight_mode": mode,
        }
    volatile_containment, volatile_containment_overrides = execution_plan(
        config, "preflight_volatile_containment"
    )
    assert len(volatile_containment) == 2
    assert {row["scenario_id"] for row in volatile_containment} == {
        "volatile_negative_governed_y_pred"
    }
    assert {row["policy_id"] for row in volatile_containment} == {
        "accepted_no_export_comparator",
        "athanasiadis_sale_enabled",
    }
    assert volatile_containment_overrides == {
        "replan_count": 1,
        "phase2_single_window_preflight": True,
        "phase2_single_window_preflight_mode": (
            "preflight_volatile_containment"
        ),
    }
    volatile_containment_handoff = handoff_continuity(
        _complete_handoff_rows(1),
        phase2_single_window_preflight=True,
        expected_replan_count=1,
    )
    assert volatile_containment_handoff["status"] == "pass"
    assert volatile_containment_handoff["validation_scope"] == (
        "phase2_single_window_terminal_snapshot_only"
    )
    assert volatile_containment_handoff["inter_window_handoff_continuity"] == (
        "not_applicable"
    )
    volatile, volatile_overrides = execution_plan(
        config, "preflight_volatile"
    )
    assert len(volatile) == 2
    assert {row["scenario_id"] for row in volatile} == {
        "volatile_negative_governed_y_pred"
    }
    assert {row["policy_id"] for row in volatile} == {
        "accepted_no_export_comparator",
        "athanasiadis_sale_enabled",
    }
    assert volatile_overrides == {
        "replan_count": 5,
        "phase2_bounded_prefix_preflight": True,
        "phase2_bounded_prefix_target_replan": 4,
        "phase2_bounded_prefix_preflight_mode": "preflight_volatile",
    }
    assert "phase2_single_window_preflight" not in volatile_overrides
    absent, absent_overrides = execution_plan(
        config, "preflight_absent_disabled"
    )
    assert {row["policy_id"] for row in absent} == {
        "accepted_no_export_comparator",
        "explicit_disabled_preflight",
    }
    assert absent_overrides["phase2_single_window_preflight"] is True
    full, overrides = execution_plan(config, "full_matrix")
    assert len(full) == 8
    assert overrides == {}
    assert config["experiment"]["replan_count"] == 7
    assert config["experiment"]["solver_model_count"] == 112
    assert len(full) * config["experiment"]["replan_count"] * 2 == 112


@pytest.mark.parametrize(
    ("execution_mode", "evaluated", "claim_eligible"),
    [
        ("aggregate_only", False, False),
        ("preflight_absent_disabled", False, False),
        ("preflight_containment", True, False),
        ("preflight_calm", True, False),
        ("preflight_volatile_containment", False, False),
        ("preflight_volatile", True, True),
        ("full_matrix", True, True),
    ],
)
def test_negative_price_contract_is_explicit_for_every_supported_mode(
    execution_mode: str,
    evaluated: bool,
    claim_eligible: bool,
) -> None:
    contract = _negative_price_validation_contract(
        execution_mode,
        volatile=(
            "volatile" in execution_mode or execution_mode == "full_matrix"
        ),
    )
    assert execution_mode in SUPPORTED_EXECUTION_MODES
    assert contract["evaluate"] is evaluated
    assert contract["claimed"] is claim_eligible
    if execution_mode == "preflight_volatile":
        assert contract["require_negative_hour"] is True
        assert contract["target_replan"] == 4
        assert contract["validation_scope"] == (
            "volatile_bounded_prefix_replans_0_through_4"
        )


def _claim_guardrail(*, required: bool, negative_hours: int) -> dict[str, object]:
    return {
        "guardrail": "negative_price_export_coherence",
        "status": "pass",
        "negative_hour_required": required,
        "negative_hour_count": negative_hours,
    }


@pytest.mark.parametrize("execution_mode", SUPPORTED_EXECUTION_MODES)
def test_negative_price_claim_is_fail_closed_across_every_supported_mode(
    execution_mode: str,
) -> None:
    if execution_mode == "preflight_volatile":
        complete = [_claim_guardrail(required=True, negative_hours=1)]
    elif execution_mode == "full_matrix":
        complete = [
            _claim_guardrail(required=False, negative_hours=0),
            _claim_guardrail(required=True, negative_hours=2),
            _claim_guardrail(required=False, negative_hours=0),
            _claim_guardrail(required=True, negative_hours=2),
        ]
    else:
        complete = [_claim_guardrail(required=True, negative_hours=1)]
    assert _negative_price_validation_claimed(
        execution_mode, complete
    ) is (execution_mode in {"preflight_volatile", "full_matrix"})

    empty_required = [dict(row) for row in complete]
    for row in empty_required:
        if row["negative_hour_required"] is True:
            row["negative_hour_count"] = 0
    assert not _negative_price_validation_claimed(execution_mode, empty_required)


def test_negative_price_claim_rejects_missing_or_failed_full_guardrails() -> None:
    complete = [
        _claim_guardrail(required=False, negative_hours=0),
        _claim_guardrail(required=True, negative_hours=1),
        _claim_guardrail(required=False, negative_hours=0),
        _claim_guardrail(required=True, negative_hours=1),
    ]
    assert _negative_price_validation_claimed("full_matrix", complete)
    assert not _negative_price_validation_claimed("full_matrix", complete[:-1])
    failed = [dict(row) for row in complete]
    failed[-1]["status"] = "fail"
    assert not _negative_price_validation_claimed("full_matrix", failed)


def test_wrapper_uses_the_canonical_execution_mode_inventory() -> None:
    wrapper = STEEL_ROOT / "run_s4_4c5p_c0_athanasiadis_sale_sensitivity.py"
    source = wrapper.read_text(encoding="utf-8")
    assert "SUPPORTED_EXECUTION_MODES" in source
    assert "POSTHOC_REAUDIT_EXECUTION_MODE" in source
    assert "choices=(*SUPPORTED_EXECUTION_MODES, POSTHOC_REAUDIT_EXECUTION_MODE)" in source


def test_posthoc_full_matrix_reaudit_is_no_solve_and_preserves_source(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, source = _posthoc_source_fixture(local_test_tmp)
    monkeypatch.setattr(
        sale_sensitivity_module,
        "POSTHOC_REAUDIT_SOURCE_FILE_CONTRACT",
        _posthoc_fixture_source_contract(source),
    )
    source_before = {
        path.relative_to(source).as_posix(): __import__("hashlib").sha256(
            path.read_bytes()
        ).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    solver_calls = 0

    def forbidden_solver_call(*_args: object, **_kwargs: object) -> None:
        nonlocal solver_calls
        solver_calls += 1
        raise AssertionError("posthoc re-audit must not invoke a child solver")

    monkeypatch.setattr(
        "steel.s4_4c5p_c0_athanasiadis_sale_sensitivity.subprocess.run",
        forbidden_solver_call,
    )
    monkeypatch.setattr(
        "steel.s4_4c5p_c0_athanasiadis_sale_sensitivity._git_head",
        lambda: "f2c4126b216707b132ca9bab43291b345e49b939",
    )
    monkeypatch.setattr(
        "steel.s4_4c5p_c0_athanasiadis_sale_sensitivity._git_diff_sha256",
        lambda: "d" * 64,
    )
    monkeypatch.setattr(
        "steel.s4_4c5p_c0_athanasiadis_sale_sensitivity.run_closed_loop_feasibility_anchor_reconciliation",
        forbidden_solver_call,
    )

    summary = run_posthoc_full_matrix_guardrail_reaudit(
        config_path,
        source_attempt=source,
        posthoc_reaudit_authorization=POSTHOC_REAUDIT_AUTHORIZATION_PHRASE,
        posthoc_reaudit_reviewer_decision="PASS",
    )

    assert solver_calls == 0
    assert summary["status"] == "pass"
    assert summary["execution_mode"] == POSTHOC_REAUDIT_EXECUTION_MODE
    assert summary["source_run_status"] == "fail"
    assert summary["solver_model_count"] == 0
    assert summary["source_solver_model_count"] == 112
    assert summary["source_artifacts_modified"] is False
    source_after = {
        path.relative_to(source).as_posix(): __import__("hashlib").sha256(
            path.read_bytes()
        ).hexdigest()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert source_after == source_before
    output = STEEL_ROOT.parents[2] / summary["attempt_output_root"]
    supersession = json.loads(
        (output / "supersession_manifest.json").read_text(encoding="utf-8")
    )
    assert supersession["source_run_status"] == "fail"
    assert supersession["source_artifacts_modified"] is False
    assert supersession["solver_model_count"] == 0
    assert supersession["source_solver_model_count"] == 112
    assert supersession["reaudited_guardrail_row_count"] == 94
    assert supersession["reaudited_guardrail_failure_count"] == 0
    assert {
        row["guardrail"] for row in supersession["superseded_guardrail_rows"]
    } == {
        "electricity_identity",
        "wag_and_ng_generation_exactly_separate",
    }
    reaudited = list(
        csv.DictReader(
            (output / "physical_guardrails_reaudited.csv").open(
                newline="", encoding="utf-8"
            )
        )
    )
    assert len(reaudited) == 94
    assert all(row["status"] == "pass" for row in reaudited)


@pytest.mark.parametrize(
    "mutation",
    ("case_status", "solver_status", "guardrail_count"),
)
def test_posthoc_reaudit_fails_closed_on_source_schema_or_status_mismatch(
    local_test_tmp: Path,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, source = _posthoc_source_fixture(local_test_tmp)
    monkeypatch.setattr(
        sale_sensitivity_module,
        "POSTHOC_REAUDIT_SOURCE_FILE_CONTRACT",
        _posthoc_fixture_source_contract(source),
    )
    if mutation == "case_status":
        rows = list(
            csv.DictReader(
                (source / "case_status.csv").open(newline="", encoding="utf-8")
            )
        )
        rows[0]["status"] = "fail"
        _write_test_csv(source / "case_status.csv", rows)
    elif mutation == "solver_status":
        rows = list(
            csv.DictReader(
                (source / "child_solver_summary.csv").open(
                    newline="", encoding="utf-8"
                )
            )
        )
        rows[0]["termination_condition"] = "infeasible"
        _write_test_csv(source / "child_solver_summary.csv", rows)
    else:
        rows = list(
            csv.DictReader(
                (source / "physical_guardrails.csv").open(
                    newline="", encoding="utf-8"
                )
            )
        )
        _write_test_csv(source / "physical_guardrails.csv", rows[:-1])

    with pytest.raises(SaleSensitivityError, match="failed closed"):
        run_posthoc_full_matrix_guardrail_reaudit(
            config_path,
            source_attempt=source,
            posthoc_reaudit_authorization=POSTHOC_REAUDIT_AUTHORIZATION_PHRASE,
            posthoc_reaudit_reviewer_decision="PASS",
        )
    assert not (local_test_tmp / "governed/posthoc_reaudits").exists()


def test_posthoc_reaudit_rejects_wrong_authorization_before_output(
    local_test_tmp: Path,
) -> None:
    config_path, source = _posthoc_source_fixture(local_test_tmp)
    with pytest.raises(SaleSensitivityError, match="authorization phrase"):
        run_posthoc_full_matrix_guardrail_reaudit(
            config_path,
            source_attempt=source,
            posthoc_reaudit_authorization="wrong",
            posthoc_reaudit_reviewer_decision="PASS",
        )
    assert not (local_test_tmp / "governed/posthoc_reaudits").exists()


def test_posthoc_cli_dispatch_never_calls_solve_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wrapper_path = STEEL_ROOT / "run_s4_4c5p_c0_athanasiadis_sale_sensitivity.py"
    spec = importlib.util.spec_from_file_location("posthoc_wrapper_test", wrapper_path)
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    solve_calls = 0
    posthoc_calls = 0

    def forbidden_solve(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal solve_calls
        solve_calls += 1
        raise AssertionError("solve runner must not be called")

    def posthoc_stub(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal posthoc_calls
        posthoc_calls += 1
        return {"status": "pass", "solver_model_count": 0}

    monkeypatch.setattr(wrapper, "run_sale_sensitivity", forbidden_solve)
    monkeypatch.setattr(
        wrapper, "run_posthoc_full_matrix_guardrail_reaudit", posthoc_stub
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(wrapper_path),
            "--execution-mode",
            POSTHOC_REAUDIT_EXECUTION_MODE,
            "--posthoc-source-attempt",
            POSTHOC_REAUDIT_SOURCE_ATTEMPT_ID,
            "--posthoc-reaudit-authorization",
            POSTHOC_REAUDIT_AUTHORIZATION_PHRASE,
            "--posthoc-reaudit-reviewer-decision",
            "PASS",
        ],
    )

    assert wrapper.main() == 0
    assert solve_calls == 0
    assert posthoc_calls == 1
    assert '"solver_model_count": 0' in capsys.readouterr().out


def test_volatile_containment_has_distinct_attempt_identity(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "attempt_identity"
    identity = {
        "run_id": "steel_c5_athanasiadis_sale_sensitivity_v1_20260726",
        "config_sha256": "a" * 64,
        "implementation_sha256": "b" * 64,
    }
    one_window, one_identity = _prepare_attempt_output(
        root,
        run_identity=identity,
        execution_mode="preflight_volatile_containment",
        diagnostic_case_id=None,
    )
    prefix, prefix_identity = _prepare_attempt_output(
        root,
        run_identity=identity,
        execution_mode="preflight_volatile",
        diagnostic_case_id=None,
    )
    assert one_window != prefix
    assert one_identity["attempt_id"] != prefix_identity["attempt_id"]
    assert one_identity["execution_mode"] == "preflight_volatile_containment"
    assert prefix_identity["execution_mode"] == "preflight_volatile"


def test_attempt_lineage_preserves_prior_root_identity_byte_for_byte(
    local_test_tmp: Path,
) -> None:
    root = local_test_tmp / "governed_output"
    root.mkdir()
    prior_identity = b'{"implementation_sha256":"superseded"}\n'
    prior_summary = b'{"status":"diagnostic_pass"}\n'
    (root / "run_identity.json").write_bytes(prior_identity)
    (root / "run_summary.json").write_bytes(prior_summary)
    attempt, identity = _prepare_attempt_output(
        root,
        run_identity={
            "run_id": "steel_c5_athanasiadis_sale_sensitivity_v1_20260726",
            "config_sha256": "a" * 64,
            "implementation_sha256": "b" * 64,
        },
        execution_mode="preflight_calm",
        diagnostic_case_id=None,
    )
    assert (root / "run_identity.json").read_bytes() == prior_identity
    assert (root / "run_summary.json").read_bytes() == prior_summary
    assert attempt.parent == root / "attempts"
    assert attempt != root
    assert json.loads((attempt / "run_identity.json").read_text()) == identity
    assert identity["execution_mode"] == "preflight_calm"


def test_case_cache_rejects_old_implementation_or_authorization_identity(
    local_test_tmp: Path,
) -> None:
    directory = local_test_tmp / "case"
    directory.mkdir()
    forecast_root = local_test_tmp / "forecast"
    forecast_root.mkdir()
    expected_overrides = {"forecast_run_root": str(forecast_root.resolve())}
    portable_overrides = _portableize_persistent_payload(
        expected_overrides, forecast_root=forecast_root
    )
    (directory / "run_summary.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8"
    )
    (directory / "config_resolved.yaml").write_text(
        yaml.safe_dump({"scenario_overrides_applied": portable_overrides}),
        encoding="utf-8",
    )
    (directory / "code_version.json").write_text(
        json.dumps({"git_commit": sale_sensitivity_module._git_head()}),
        encoding="utf-8",
    )
    source = (
        STEEL_ROOT.parents[2]
        / "data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md"
    )
    (directory / "input_manifest.json").write_text(
        json.dumps(
            {
                "active_model_input_files": [
                    {
                        "path": str(
                            source.relative_to(STEEL_ROOT.parents[2])
                        ).replace("\\", "/"),
                        "sha256": __import__("hashlib").sha256(
                            source.read_bytes()
                        ).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    for name in (
        "executed_hourly.csv",
        "inventory_handoff.csv",
        "rolling_model_metrics.csv",
    ):
        (directory / name).write_text("x\n", encoding="utf-8")
    old_implementation = "a" * 64
    preservation = "b" * 64
    authorization = "c" * 64
    (directory / "case_cache_manifest.json").write_text(
        json.dumps(
            {
                "implementation_sha256": old_implementation,
                "sale_state_preservation_sha256": preservation,
                "full_matrix_authorization_metadata_sha256": authorization,
                "scenario_overrides_sha256": _mapping_sha256(
                    portable_overrides
                ),
                "files": [
                    {
                        "path": "executed_hourly.csv",
                        "sha256": __import__("hashlib").sha256(
                            (directory / "executed_hourly.csv").read_bytes()
                        ).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert _case_ready(
        directory,
        expected_overrides=expected_overrides,
        implementation_sha256=old_implementation,
        preservation_sha256=preservation,
        authorization_metadata_sha256=authorization,
    )
    assert not _case_ready(
        directory,
        expected_overrides=expected_overrides,
        implementation_sha256="d" * 64,
        preservation_sha256=preservation,
        authorization_metadata_sha256=authorization,
    )
    assert not _case_ready(
        directory,
        expected_overrides=expected_overrides,
        implementation_sha256=old_implementation,
        preservation_sha256=preservation,
        authorization_metadata_sha256="e" * 64,
    )


def test_nested_attempt_capture_directory_is_initialized_before_model_work(
    local_test_tmp: Path,
) -> None:
    nested = local_test_tmp / "scratch/attempts/new/capture/calm"
    assert not nested.exists()
    resolved = _initialize_normal_solution_capture_directory(
        {"directory": str(nested)}
    )
    assert resolved == nested.resolve()
    assert nested.is_dir()


def test_real_volatile_active_c0_deadline_reports_exact_machine_edge() -> None:
    """Pin the preserved volatile replan-0 arithmetic in the real C0 builder."""

    tables = _load_tables(modelbuilder.CORRECTED_INPUT_DIR)
    inputs = _build_c0_inputs(
        tables,
        horizon_hours_override=120,
        target_multiplier=15.658361008036568,
    )
    target_24 = 18493.150684931505
    routing = {
        "hsm_final_t_per_t_slab": 0.9600000000000002,
        "hsm_slab_input_t_per_t_hrc": 1.0416666666666665,
        "dsp_liquid_steel_input_t_per_t_coil": 1.05,
        "dsp_final_product_horizon_cap_t": 20547.945205479453,
        "dsp_final_product_max_t_h": 171.23287671232876,
        "bof_hot_metal_t_per_t_liquid_steel": 0.875,
        "bof_scrap_t_per_t_liquid_steel": 0.208,
        "bof_total_scrap_horizon_cap_t": 20547.945205479453,
        "bof_total_scrap_max_t_h": 171.23287671232876,
    }
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        c0_downstream_reference_routing=routing,
        rolling_production_deadline_targets_t={
            24: target_24,
            120: inputs.final_product_target_t,
        },
    )
    for variable in model.component_data_objects(Var, active=True):
        variable.set_value(0.0, skip_validation=False)
    hot_strip_mill = [
        800.0, 800.0, 800.0, 800.0, 800.0, 800.0,
        394.75285257077985, 394.7528525707813, 336.7547270659937,
        800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0, 800.0,
        800.0, 479.3471959620631, 358.68778297001626,
        394.75285257077985, 110.59312756646592, 416.75609178601997,
        168.60177103241156,
    ]
    dsp_liquid_steel = [179.7945205479452] * 22 + [
        107.0949973972629,
        179.7945205479452,
    ]
    for hour, incumbent_value in enumerate(hot_strip_mill):
        model.hot_strip_mill[hour].set_value(incumbent_value)
    for hour, incumbent_value in enumerate(dsp_liquid_steel):
        model.c0_dsp_liquid_steel_input[hour].set_value(incumbent_value)
    deadline = model.rolling_production_deadline[24]
    for constraint in model.component_data_objects(Constraint, active=True):
        if constraint is not deadline:
            constraint.deactivate()

    audit = _audit_loaded_incumbent(model, tolerance=1e-6)
    exact = audit["exact_maximum_constraint_violations"]
    assert audit["constraint_count"] == 1
    assert audit["constraint_above_tolerance_count"] == 1
    assert audit["max_constraint_violation"] == pytest.approx(
        1.0000003385357559e-6, rel=0.0, abs=1e-15
    )
    assert exact == audit["constraints_above_tolerance"]
    assert exact[0]["name"] == "rolling_production_deadline[24]"
    assert exact[0]["component_name"] == "rolling_production_deadline"
    assert exact[0]["index"] == "24"
    assert exact[0]["violated_side"] == "lower"
    assert exact[0]["body"] == pytest.approx(18493.150683931504)
    assert exact[0]["lower"] == target_24
    assert "0.9600000000000002*hot_strip_mill[0]" in exact[0]["expression"]
    assert "0.9523809523809523*c0_dsp_liquid_steel_input[23]" in exact[0][
        "expression"
    ]
    assert audit["evaluation_contract"]["rounding_or_secondary_margin"] is False
    validation_context = _install_registered_validation_relaxations(model)
    validation = _finalize_registered_validation_evidence(
        model, validation_context
    )
    row = validation["rows"][0]
    assert validation["status"] == "pass"
    assert row["constraint_family"] == "rolling_production_deadline"
    assert row["raw_residual"] == pytest.approx(1.0000003385357559e-6)
    assert row["allowed_tolerance"] == 1.0
    assert row["normalized_residual"] == pytest.approx(
        1.0000003385357559e-6
    )


def test_real_active_volatile_c0_exact_quota_families_resolve_and_fail_above_one_tonne(
    request: pytest.FixtureRequest,
) -> None:
    """Use the real C0 builder plus the single-window volatile terminal contract."""

    original_registry = dict(CONSTRAINT_FAMILY_REGISTRY)
    request.addfinalizer(
        lambda: (
            CONSTRAINT_FAMILY_REGISTRY.clear(),
            CONSTRAINT_FAMILY_REGISTRY.update(original_registry),
        )
    )
    install_terminal_validation_extension()
    tables = _load_tables(modelbuilder.CORRECTED_INPUT_DIR)
    inputs = _build_c0_inputs(
        tables,
        horizon_hours_override=120,
        target_multiplier=15.658361008036568,
    )
    physical_path = (
        STEEL_ROOT
        / "configs/steel_hourly_da_dplus4_point_forecast_integration.yaml"
    )
    mechanism_path = (
        STEEL_ROOT / "configs/steel_c5_real_anchor_mechanism_experiment.yaml"
    )
    physical = load_physical_config(physical_path)
    mechanism = load_mechanism_config(mechanism_path)
    candidate = next(
        row
        for row in mechanism["experiment"]["candidates"]
        if row["candidate_id"] == "recovery_bg30_ng55"
    )
    physical = {**physical, **candidate_overrides(mechanism, candidate)}
    generator, bridge = _c0_real_anchor_energy_recovery_interfaces(physical)
    electricity = _electricity_boundary_levers(physical)
    assert generator is not None
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        site_background_electricity_mwh_h=electricity[3],
        aggregate_generator_technical_interface=generator,
        full_site_energy_bridge=bridge,
        electricity_sale_sensitivity={
            "enabled": True,
            "policy_id": "athanasiadis_sale_enabled",
        },
    )
    target_24 = 18493.150684931505
    _add_rolling_production_progress_tracking(
        model,
        execution_block_hours=24,
        next_execution_target_t=target_24,
        hard_exact_execution_target=True,
        exact_deadline_hour=24,
        exact_deadline_target_t=target_24,
    )
    for variable in model.component_data_objects(Var, active=True):
        variable.set_value(0.0, skip_validation=False)

    active_families = sorted(
        {
            constraint.parent_component().name
            for constraint in model.component_data_objects(
                Constraint, active=True
            )
        }
    )
    assert "rolling_production_terminal_quota_equality" in active_families
    assert (
        "rolling_production_future_terminal_quota_equality"
        in active_families
    )
    unregistered_families = sorted(
        set(active_families) - set(CONSTRAINT_FAMILY_REGISTRY)
    )
    assert not unregistered_families
    resolved_active_families = {
        family: constraint_family_rule(family) for family in active_families
    }
    assert set(resolved_active_families) == set(active_families)

    context = _install_registered_validation_relaxations(model)
    assert context["active_constraint_family_count"] == len(active_families)
    exact_families = {
        "rolling_production_terminal_quota_equality",
        "rolling_production_future_terminal_quota_equality",
    }
    exact_contexts = [
        row_context
        for row_context in context["row_contexts"]
        if row_context["evidence"]["constraint_family"] in exact_families
    ]
    assert {
        row_context["evidence"]["constraint_family"]
        for row_context in exact_contexts
    } == exact_families
    for row_context in exact_contexts:
        evidence = row_context["evidence"]
        assert evidence["purpose"] == "cumulative_production_acceptance"
        assert evidence["unit"] == "t"
        assert evidence["allowed_tolerance"] == 1.0
        assert evidence["relaxation_allowed"] is True
        assert len(evidence["relaxation_side_indices"]) == 2

    validation = _finalize_registered_validation_evidence(model, context)
    exact_rows = [
        row
        for row in validation["rows"]
        if row["constraint_family"] in exact_families
    ]
    exact_lower_sides = [
        row
        for row in validation["relaxation_sides"]
        if row["constraint_family"] in exact_families
        and row["side"] == "lower"
    ]
    assert {row["constraint_family"] for row in exact_rows} == exact_families
    assert {
        row["constraint_family"] for row in exact_lower_sides
    } == exact_families
    for row in exact_rows:
        assert row["raw_residual"] == pytest.approx(target_24)
        assert row["status"] == "fail"
    for side in exact_lower_sides:
        assert side["raw_required_relaxation"] == pytest.approx(target_24)
        assert side["solved_used_relaxation"] == pytest.approx(1.0)
        assert side["required_within_allowed_tolerance"] is False
        assert side["status"] == "fail"


def test_registered_production_relaxation_fails_above_one_tonne() -> None:
    model = ConcreteModel()
    model.production = Var(initialize=8.999999)
    model.production.fix()
    model.rolling_production_deadline = Constraint(
        expr=model.production >= 10.0
    )
    context = _install_registered_validation_relaxations(model)
    validation = _finalize_registered_validation_evidence(model, context)
    assert validation["status"] == "fail"
    assert validation["rows"][0]["raw_residual"] > 1.0
    assert validation["rows"][0]["allowed_tolerance"] == 1.0


def test_sale_economic_overlay_accepts_machine_edge_and_fails_above_one_tonne() -> None:
    target = 18_493.150684931505
    machine_edge = 1.0000003385357559e-6
    accepted = ConcreteModel()
    accepted.production = Var(initialize=target - machine_edge)
    accepted.production.fix()
    accepted.rolling_production_deadline = Constraint(
        expr=accepted.production >= target
    )
    accepted_context = _install_sale_economic_validation_overlay(accepted)
    accepted_evidence = _finalize_sale_economic_validation_overlay(
        accepted, accepted_context
    )
    accepted_row = accepted_evidence["rows"][0]
    assert accepted_evidence["status"] == "pass"
    assert accepted_evidence["underlying_core_unchanged"] is True
    assert accepted_row["raw_residual"] == pytest.approx(machine_edge)
    assert accepted_row["allowed_tolerance"] == 1.0
    assert accepted_row["governed_tolerance"] == 1.0
    assert accepted_row["excess_beyond_governed_tolerance"] == 0.0
    assert (
        accepted_row["solver_numerical_allowance"]
        == SOLVER_NUMERICAL_TOLERANCE
    )
    assert accepted_row["normalized_residual"] == pytest.approx(machine_edge)
    assert accepted_row["overlay_lower"] == pytest.approx(target - 1.0)
    assert accepted_row["overlay_raw_residual"] == pytest.approx(0.0)
    assert accepted_row["overlay_residual"] == pytest.approx(0.0)

    rejected = ConcreteModel()
    rejected.production = Var(initialize=target - 1.000002)
    rejected.production.fix()
    rejected.rolling_production_deadline = Constraint(
        expr=rejected.production >= target
    )
    rejected_context = _install_sale_economic_validation_overlay(rejected)
    rejected_evidence = _finalize_sale_economic_validation_overlay(
        rejected, rejected_context
    )
    assert rejected_evidence["status"] == "fail"
    assert rejected_evidence["rows"][0]["raw_residual"] > 1.0
    assert rejected_evidence["rows"][0]["overlay_raw_residual"] > 0.0


@pytest.mark.parametrize(
    ("constraint_name", "raw_residual", "expected_overlay_residual"),
    (
        (
            "c0_reference_deadline_bof_liquid_steel_48h_lower",
            1.000000000014552,
            1.4551915228366852e-11,
        ),
        (
            "c0_reference_deadline_hsm_final_output_48h_upper",
            1.000000000003638,
            3.637978807091713e-12,
        ),
    ),
)
def test_sale_economic_overlay_accepts_actual_solver_numerical_edge(
    constraint_name: str,
    raw_residual: float,
    expected_overlay_residual: float,
) -> None:
    model = ConcreteModel()
    if constraint_name.endswith("_lower"):
        model.production = Var(initialize=0.0)
        model.production.fix()
        constraint = Constraint(expr=model.production >= raw_residual)
    else:
        model.production = Var(initialize=raw_residual)
        model.production.fix()
        constraint = Constraint(expr=model.production <= 0.0)
    setattr(model, constraint_name, constraint)

    context = _install_sale_economic_validation_overlay(model)
    evidence = _finalize_sale_economic_validation_overlay(model, context)
    row = evidence["rows"][0]

    assert evidence["schema_version"] == "steel_sale_economic_validation_overlay_v2"
    assert evidence["status"] == "pass"
    assert row["raw_residual"] == raw_residual
    assert row["allowed_tolerance"] == 1.0
    assert row["governed_tolerance"] == 1.0
    assert row["excess_beyond_governed_tolerance"] == expected_overlay_residual
    assert row["solver_numerical_allowance"] == SOLVER_NUMERICAL_TOLERANCE
    assert row["overlay_raw_residual"] == expected_overlay_residual
    assert row["overlay_residual"] == expected_overlay_residual
    assert row["normalized_residual"] == raw_residual
    assert row["status"] == "pass"


def test_sale_economic_overlay_never_widens_physical_balance() -> None:
    model = ConcreteModel()
    model.flow = Var(initialize=0.0)
    model.coke_balance = Constraint(expr=model.flow == 0.0)
    original_expression = str(model.coke_balance.expr)
    context = _install_sale_economic_validation_overlay(model)
    assert context["registered_acceptance_row_count"] == 0
    assert model.coke_balance.active
    assert str(model.coke_balance.expr) == original_expression
    assert len(model.sale_economic_validation_overlay_rows) == 0


def test_sale_economic_overlay_fails_closed_before_unknown_family_mutation() -> None:
    model = ConcreteModel()
    model.production = Var(initialize=10.0)
    model.rolling_production_deadline = Constraint(
        expr=model.production >= 10.0
    )
    model.unknown_future_family = Constraint(expr=model.production <= 11.0)
    with pytest.raises(
        S44CModelBuilderError,
        match="Unregistered active steel validation constraint family",
    ):
        _install_sale_economic_validation_overlay(model)
    assert model.rolling_production_deadline.active
    assert model.unknown_future_family.active
    assert not hasattr(model, "sale_economic_validation_overlay_rows")


def test_exact_state_propagation_prevents_prior_coke_iis_drift(
    local_test_tmp: Path,
) -> None:
    comparator_terminal_coke_t = 12.0
    prior_sale_terminal_coke_t = comparator_terminal_coke_t - (
        0.7783634228536016
    )
    iis_coke_balance_rhs_t = 0.7783634228535732
    assert comparator_terminal_coke_t - prior_sale_terminal_coke_t == pytest.approx(
        iis_coke_balance_rhs_t, abs=1e-12
    )
    model = _sale_model()
    model.coke_inventory[1].set_value(comparator_terminal_coke_t)
    policy, oracle_result = _verified_preservation_fixture(
        model, root=local_test_tmp, price=100.0
    )
    containment = policy["incumbent_containment"]
    assert isinstance(containment, dict)
    context = _apply_sale_state_preservation(
        model,
        containment_result=oracle_result,
        containment_policy=containment,
        contract=policy["state_preservation"],
        tolerance=1e-6,
    )
    exact = model.sale_state_coke_inventory_preservation_exact
    assert value(exact.lower) == comparator_terminal_coke_t
    assert value(exact.upper) == comparator_terminal_coke_t
    model.coke_inventory[1].set_value(prior_sale_terminal_coke_t)
    assert value(exact.body) != value(exact.lower)


def _two_sided_registered_validation_fixture():
    model = ConcreteModel()
    model.production = Var(initialize=9.5)
    model.production.fix()
    model.rolling_production_deadline = Constraint(
        expr=model.production == 10.0
    )
    context = _install_registered_validation_relaxations(model)
    return model, context


def test_two_sided_validation_row_records_every_installed_slack() -> None:
    model, context = _two_sided_registered_validation_fixture()
    validation = _finalize_registered_validation_evidence(model, context)
    sides = validation["relaxation_sides"]
    assert validation["schema_version"] == "steel_registered_validation_rows_v2"
    assert validation["status"] == "pass"
    assert validation["relaxation_side_count"] == 2
    assert [row["side"] for row in sides] == ["lower", "upper"]
    assert all(
        row["constraint_name"] == "rolling_production_deadline"
        and row["constraint_family"] == "rolling_production_deadline"
        and row["constraint_index"] == "None"
        for row in sides
    )
    assert sides[0]["raw_required_relaxation"] == pytest.approx(0.5)
    assert sides[0]["solved_used_relaxation"] == pytest.approx(0.5)
    assert sides[0]["normalized_raw_residual"] == pytest.approx(0.5)
    assert sides[0]["normalized_used_residual"] == pytest.approx(0.5)
    assert sides[0]["solved_used_slack_covers_required"] is True
    assert sides[1]["raw_required_relaxation"] == pytest.approx(0.0)
    assert sides[1]["solved_used_relaxation"] == pytest.approx(0.0)


def test_two_sided_validation_fails_when_used_slack_is_insufficient() -> None:
    model, context = _two_sided_registered_validation_fixture()
    lower_index = next(
        index
        for index, side in enumerate(context["relaxation_sides"])
        if side["side"] == "lower"
    )
    model.sale_validation_relaxation[lower_index].set_value(0.4)
    validation = _finalize_registered_validation_evidence(model, context)
    lower = next(
        row for row in validation["relaxation_sides"] if row["side"] == "lower"
    )
    assert validation["status"] == "fail"
    assert validation["failed_relaxation_side_count"] == 1
    assert lower["required_within_allowed_tolerance"] is True
    assert lower["used_within_allowed_tolerance"] is True
    assert lower["solved_used_slack_covers_required"] is False
    assert lower["status"] == "fail"
    assert validation["rows"][0]["relaxation_side_status"] == "fail"


def test_two_sided_validation_side_manifest_and_hash_are_deterministic() -> None:
    model, context = _two_sided_registered_validation_fixture()
    first = _finalize_registered_validation_evidence(model, context)
    second = _finalize_registered_validation_evidence(model, context)
    assert first["relaxation_sides"] == second["relaxation_sides"]
    assert first["relaxation_sides_sha256"] == second[
        "relaxation_sides_sha256"
    ]
    assert first["rows_sha256"] == second["rows_sha256"]
    assert first["evidence_manifest_sha256"] == second[
        "evidence_manifest_sha256"
    ]


def test_unregistered_active_constraint_family_fails_closed() -> None:
    model = ConcreteModel()
    model.x = Var(initialize=0.0)
    model.unregistered_future_validation = Constraint(expr=model.x >= 0.0)
    with pytest.raises(
        S44CModelBuilderError,
        match="Unregistered active steel validation constraint family",
    ):
        _install_registered_validation_relaxations(model)


def test_real_active_c0_model_uses_constraint_aware_hourly_import_bounds(
    local_test_tmp: Path,
) -> None:
    physical_path = (
        STEEL_ROOT / "configs/steel_hourly_da_dplus4_point_forecast_integration.yaml"
    )
    mechanism_path = (
        STEEL_ROOT / "configs/steel_c5_real_anchor_mechanism_experiment.yaml"
    )
    physical = load_physical_config(physical_path)
    mechanism = load_mechanism_config(mechanism_path)
    candidate = next(
        row
        for row in mechanism["experiment"]["candidates"]
        if row["candidate_id"] == "recovery_bg30_ng55"
    )
    physical = {**physical, **candidate_overrides(mechanism, candidate)}
    generator, bridge = _c0_real_anchor_energy_recovery_interfaces(physical)
    electricity = _electricity_boundary_levers(physical)
    assert generator is not None
    tables = _load_tables(modelbuilder.CORRECTED_INPUT_DIR)
    inputs = _build_c0_inputs(
        tables, horizon_hours_override=2, target_multiplier=0.01
    )
    common_build_kwargs = {
        "enable_minimal_wag_layer": True,
        "enable_internal_wag_power": True,
        "development_controller_activation": "full",
        "site_background_electricity_mwh_h": electricity[3],
        "aggregate_generator_technical_interface": generator,
        "full_site_energy_bridge": bridge,
    }
    normal_model = _build_c0_model(inputs, **common_build_kwargs)
    model = _build_c0_model(
        inputs,
        **common_build_kwargs,
        electricity_sale_sensitivity={
            "enabled": True,
            "policy_id": "athanasiadis_sale_enabled",
        },
    )
    audit = model.grid_import_bound_audit
    assert audit["status"] == "pass"
    assert audit["constraint_aware_fbbt"] is True
    assert "fbbt(model)" in audit["derivation_method"]
    assert len(audit["hourly_bounds"]) == 2
    assert all(row["status"] == "finite" for row in audit["hourly_bounds"])
    bounds = {
        row["hour_index"]: row["gross_grid_import_upper_bound_mwh"]
        for row in audit["hourly_bounds"]
    }
    assert all(bound > 0.0 and bound != pytest.approx(770.0) for bound in bounds.values())
    for hour in model.TIME:
        model.gross_grid_import_mwh[hour].set_value(0.0)
        model.grid_import_mode[hour].set_value(1.0)
        assert value(model.grid_import_capacity[hour].body) == pytest.approx(
            -bounds[int(hour)]
        )
    assert "770.0" in str(model.grid_export_capacity[0].expr)
    classification = _variable_structural_classification(model)
    normal_classification = _variable_structural_classification(normal_model)
    normal_names = {
        row["name"] for row in normal_classification["required_variables"]
    }
    stable_schema = _shared_variable_schema_diagnostics(
        normal_classification,
        classification,
        normal_names,
    )
    assert stable_schema["declared_schema_mismatch_count"] == 0
    assert stable_schema["current_or_derived_bound_difference_count"] > 0
    assert any(
        "coking_plant_1[0]" in row["variable_names"]
        for row in stable_schema["current_or_derived_bound_pair_categories"]
    )
    for hour in model.TIME:
        model.basic_oxygen_furnace[hour].set_value(1.0)
        model.hot_strip_mill[hour].set_value(1.0)
        model.c0_dsp_liquid_steel_input[hour].set_value(0.0)
    for component_name, endpoint_value in {
        "coke_inventory": 10.0,
        "sinter_inventory": 20.0,
        "hot_iron_inventory": 30.0,
        "cold_slab_inventory": 40.0,
    }.items():
        getattr(model, component_name)[1].set_value(endpoint_value)
    preservation_policy, preservation_oracle = (
        _verified_preservation_fixture(
            model,
            root=local_test_tmp / "real_c0_preservation",
            price=100.0,
        )
    )
    preservation_containment = preservation_policy["incumbent_containment"]
    assert isinstance(preservation_containment, dict)
    preservation_context = _apply_sale_state_preservation(
        model,
        containment_result=preservation_oracle,
        containment_policy=preservation_containment,
        contract=preservation_policy["state_preservation"],
        tolerance=1e-6,
    )
    assert set(preservation_context["targets"]) == {
        "executed_final_product_t",
        "executed_bof_liquid_steel_t",
        "executed_hsm_final_output_t",
        "executed_dsp_final_output_t",
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
    }
    real_band_names = {
        name
        for name in preservation_oracle["state_preservation_capture"][
            "constraint_names"
        ].values()
    }
    assert len(real_band_names) == 8
    assert all(hasattr(model, name) for name in real_band_names)
    for target_id, name in preservation_oracle[
        "state_preservation_capture"
    ]["constraint_names"].items():
        constraint = getattr(model, name)
        assert value(constraint.lower) == preservation_context["targets"][
            target_id
        ]
        assert value(constraint.upper) == preservation_context["targets"][
            target_id
        ]
    coking = next(
        row
        for row in classification["variables"]
        if row["name"] == "coking_plant_1[0]"
    )
    assert coking["solver_relevant"] is True
    assert coking["structurally_inactive_exclusion"] is False
    assert set(coking["active_constraint_families"]) >= {
        "process_min",
        "process_max",
        "cog_balance",
        "coke_balance",
    }
    assert "report_result_expression" in coking["governed_role_categories"]
    assert coking["declared_ub"] is None
    assert coking["current_ub"] == pytest.approx(180.0)
    assert coking["current_schema_differs_from_declared"] is True


def test_failure_evidence_is_durable_portable_and_has_stage_runtimes(
    local_test_tmp: Path,
) -> None:
    output = local_test_tmp / "failure_output"
    workstation_path = local_test_tmp / "nested/attempt/capture.json.gz"
    error = S44CModelBuilderError(
        f"nonfinite hourly bound at {workstation_path}"
    )
    error.phase2_stage = "model_construction.constraint_aware_fbbt"
    error.bound_audit = {
        "status": "fail_nonfinite",
        "unbounded_variables": [{"name": "process[0]"}],
        "missing_constraint_families": ["process_capacity"],
    }
    status = {
        "case_id": "case",
        "status": "fail",
        "cache_directory": _portable_persistent_path(local_test_tmp / "case"),
        "exception_stage": error.phase2_stage,
        "exception_type": type(error).__name__,
        "exception_message": str(error),
        "load_runtime_seconds": 0.1,
        "build_runtime_seconds": 0.2,
        "solve_runtime_seconds": 0.0,
        "write_runtime_seconds": 0.0,
    }
    _persist_failure_evidence(
        output,
        statuses=[status],
        exc=error,
        stage=error.phase2_stage,
        started=__import__("time").perf_counter(),
        load_runtime_seconds=0.1,
        build_runtime_seconds=0.2,
    )
    summary = json.loads((output / "run_summary.json").read_text())
    status_text = (output / "case_status.csv").read_text()
    assert summary["status"] == "fail"
    assert summary["exception_stage"] == error.phase2_stage
    assert summary["exception_type"] == "S44CModelBuilderError"
    assert str(workstation_path) in str(error)
    assert str(workstation_path) not in summary["exception_message"]
    assert summary["bound_audit_present"] is True
    assert all(
        key in summary
        for key in (
            "load_runtime_seconds",
            "build_runtime_seconds",
            "solve_runtime_seconds",
            "write_runtime_seconds",
        )
    )
    assert "C:\\Users" not in status_text
    assert str(workstation_path) not in status_text
    assert (output / "grid_import_bound_failure_audit.json").is_file()


def test_completed_child_failure_is_persisted_before_parent_raises(
    local_test_tmp: Path,
) -> None:
    child = local_test_tmp / "child_case"
    child.mkdir()
    (child / "run_summary.json").write_text(
        json.dumps({"status": "fail"}), encoding="utf-8"
    )
    (child / "validation_checks.csv").write_text(
        "check_id,status\n"
        "primary_cost_preserved_by_physical_tie_break,fail\n"
        "material_balance,pass\n",
        encoding="utf-8",
    )
    (child / "rolling_model_metrics.csv").write_text(
        "build_runtime_seconds,runtime_seconds\n1.25,2.5\n0.75,3.5\n",
        encoding="utf-8",
    )
    evidence = _child_failure_evidence(child)
    assert evidence["child_run_status"] == "fail"
    assert evidence["child_failure_checks"] == (
        "primary_cost_preserved_by_physical_tie_break"
    )
    assert evidence["build_runtime_seconds"] == pytest.approx(2.0)
    assert evidence["solve_runtime_seconds"] == pytest.approx(6.0)

    output = local_test_tmp / "parent_failure"
    status = {
        "case_id": "child_case",
        "status": "fail",
        "execution_mode": "preflight_volatile_containment",
        "cache_directory": _portable_persistent_path(child),
        "exception_stage": "child_validation_status",
        "exception_type": "ChildRunStatusFailure",
        "exception_message": "completed child returned status=fail",
        "load_runtime_seconds": 0.1,
        "write_runtime_seconds": 0.2,
        **evidence,
    }
    error = SaleSensitivityError(status["exception_message"])
    _persist_failure_evidence(
        output,
        statuses=[status],
        exc=error,
        stage="child_validation_status",
        started=__import__("time").perf_counter(),
        load_runtime_seconds=0.1,
        build_runtime_seconds=evidence["build_runtime_seconds"],
        solve_runtime_seconds=evidence["solve_runtime_seconds"],
        write_runtime_seconds=0.2,
        execution_mode="preflight_volatile_containment",
    )
    summary = json.loads((output / "run_summary.json").read_text())
    case_status = (output / "case_status.csv").read_text()
    assert summary["execution_mode"] == "preflight_volatile_containment"
    assert summary["failed_case_ids"] == ["child_case"]
    assert summary["child_failure_checks"] == [
        "primary_cost_preserved_by_physical_tie_break"
    ]
    assert summary["failed_child_artifacts"] == [
        {
            "case_id": "child_case",
            "cache_directory": status["cache_directory"],
            "run_summary_path": evidence["child_run_summary_path"],
            "validation_checks_path": evidence[
                "child_validation_checks_path"
            ],
        }
    ]
    assert summary["build_runtime_seconds"] == pytest.approx(2.0)
    assert summary["solve_runtime_seconds"] == pytest.approx(6.0)
    assert "primary_cost_preserved_by_physical_tie_break" in case_status
    assert "preflight_volatile_containment" in case_status
    assert str(local_test_tmp) not in case_status


def test_persistent_payload_paths_are_repository_or_governed_root_relative(
    local_test_tmp: Path,
) -> None:
    forecast_root = Path("C:/governed/forecast")
    portable = _portableize_persistent_payload(
        {
            "cache": str(local_test_tmp / "case"),
            "forecast": str(forecast_root / "validation"),
        },
        forecast_root=forecast_root,
    )
    assert not Path(portable["cache"]).is_absolute()
    assert portable["forecast"] == "governed_forecast_root:validation"
    assert "C:\\Users" not in json.dumps(portable)


def test_full_matrix_requires_yaml_flag_hash_and_root_value(
    local_test_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sale_sensitivity_module,
        "_git_head",
        lambda: sale_sensitivity_module.EXPECTED_HEAD,
    )
    config = load_config()
    with pytest.raises(SaleSensitivityError, match="YAML authorization"):
        run_sale_sensitivity(
            DEFAULT_CONFIG_PATH,
            forecast_run_root=local_test_tmp,
            execution_mode="full_matrix",
            full_matrix_authorization=(
                f"{config['run_id']}:post_review_authorized"
            ),
            full_matrix_reviewer_decision="PASS",
        )
    token = "root-final-authorization"
    config["full_matrix_execution_authorized"] = True
    config["full_matrix_post_review_token_sha256"] = __import__("hashlib").sha256(
        token.encode("utf-8")
    ).hexdigest()
    config["output_root"] = _portable_persistent_path(local_test_tmp / "never_created")
    config_path = local_test_tmp / "authorized_config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(SaleSensitivityError, match="matching root-provided"):
        run_sale_sensitivity(
            config_path,
            forecast_run_root=local_test_tmp,
            execution_mode="full_matrix",
            full_matrix_authorization="wrong-root-value",
            full_matrix_reviewer_decision="PASS",
        )
    with pytest.raises(SaleSensitivityError, match="reviewer decision PASS"):
        run_sale_sensitivity(
            config_path,
            forecast_run_root=local_test_tmp,
            execution_mode="full_matrix",
            full_matrix_authorization=token,
            full_matrix_reviewer_decision="FAIL",
        )
