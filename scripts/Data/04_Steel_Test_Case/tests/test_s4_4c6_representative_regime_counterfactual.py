from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from typing import Iterator
import uuid

import pandas as pd
import pytest


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (  # noqa: E402
    SteelPriceInformationBundle,
    _scenario_inputs,
)
from steel.s4_4c6_phase6d_eaf_heat_state_one_day import (  # noqa: E402
    EXPECTED_COST_INCUMBENT,
    Phase6DEmergencyRecourse,
    _split_horizon_support,
)
from steel.s4_4c6_representative_regime_counterfactual import (  # noqa: E402
    RepresentativeRegimeError,
    _assert_run_execution_authorized,
    _base_context_config,
    _completed_run_contract_metadata,
    _experiment_directory_name,
    _gate_experiment_rows,
    _representative_run_contract,
    _solver_progress_callback,
    _validate_execution_authorization,
    load_study_frames,
    load_representative_config,
    realised_cost_comparisons,
    run_selected_experiments,
    select_experiments,
)
import steel.s4_4c6_representative_regime_counterfactual as representative  # noqa: E402


@contextmanager
def _writable_scratch(prefix: str) -> Iterator[Path]:
    path = Path.cwd() / "tmp" / f"{prefix}_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_shared_qh_context_uses_48h_physics_and_24h_economics() -> None:
    config = load_representative_config()
    hourly = _base_context_config(config, market_granularity="hourly", horizon_hours=24)
    quarterhour = _base_context_config(
        config, market_granularity="quarterhour", horizon_hours=24
    )
    assert hourly.time_grid.horizon_steps == 192
    assert quarterhour.time_grid.horizon_steps == 192
    assert hourly.time_grid.execution_steps == quarterhour.time_grid.execution_steps == 96
    assert hourly.economic_horizon_hours == quarterhour.economic_horizon_hours == 24
    assert hourly.physical_feasibility_tail_active
    assert quarterhour.physical_feasibility_tail_active
    assert hourly.granularity == "hourly"
    assert quarterhour.granularity == "quarterhour"
    assert (
        hourly.config["planning_physical_tiebreak_mode"]
        == quarterhour.config["planning_physical_tiebreak_mode"]
        == EXPECTED_COST_INCUMBENT
    )
    assert hourly.config["solver_seed"] == quarterhour.config["solver_seed"] == 0
    assert hourly.config["planning_solver_execution_mode"] == "sequential_pyomo"
    assert hourly.config["gurobi_performance_options"] == {"MIPFocus": 1}
    assert hourly.config["parent_round_restricted_bridge_active"]
    assert hourly.config["solver_time_limit_seconds"] == 900
    assert hourly.config["mip_gap_limit"] == pytest.approx(0.001)
    assert hourly.config["economic_mip_gap_limit"] == pytest.approx(0.002)
    assert hourly.config["integer_feasibility_tolerance"] == pytest.approx(1e-9)
    sensitivity = _base_context_config(
        config, market_granularity="quarterhour", horizon_hours=120
    )
    assert sensitivity.config["planning_physical_tiebreak_mode"] == EXPECTED_COST_INCUMBENT
    assert sensitivity.config["solver_seed"] == 0


def test_representative_config_promotes_v1_and_keeps_redispatch_tiebreak() -> None:
    metadata = _representative_run_contract(load_representative_config())
    assert metadata["planning_physical_tiebreak_mode"] == EXPECTED_COST_INCUMBENT
    assert not metadata["planning_physical_tiebreak_solve_performed"]
    assert metadata["redispatch_physical_tiebreak_solve_performed"]
    assert metadata["imbalance_recourse_active"]
    assert metadata["imbalance_penalty_eur_per_mwh"] == pytest.approx(5000.0)
    assert metadata["e_program_compliance_claim_requires_zero_imbalance"]
    assert metadata["parent_round_restricted_bridge_active"]
    assert metadata["parent_round_bridge_fixed_scope"] == (
        "economic_scenario_binaries_only"
    )
    assert not metadata["parent_round_bridge_final_result_eligible"]
    assert not metadata["parent_round_bridge_preservation_constraint_allowed"]
    assert metadata["parent_round_bridge_requires_full_expected_cost_resolve"]
    assert metadata["feasibility_bid_selection_mode"] == "expected_cost_incumbent"
    assert metadata["path_feasibility_active"]
    assert metadata["path_feasibility_planner_scope"] == "C1_responsive_S10_only"
    assert metadata["path_feasibility_maximum_augmentation_rounds"] == 3
    assert not metadata["path_feasibility_economic_scenario_probability_allowed"]
    assert not metadata["path_feasibility_expected_cost_weight_allowed"]
    assert not metadata["path_feasibility_final_test_source_allowed"]
    assert metadata["solver_seed"] == 0
    assert metadata["solver_name"] == "gurobi"
    assert metadata["solver_version"]


def test_missing_or_unknown_representative_planning_mode_fails_closed() -> None:
    config = load_representative_config()
    del config["experiment_contract"]["planning_physical_tiebreak_mode"]
    with pytest.raises(RepresentativeRegimeError, match="requires the explicit"):
        _representative_run_contract(config)
    config["experiment_contract"]["planning_physical_tiebreak_mode"] = "epsilon"
    with pytest.raises(RepresentativeRegimeError, match="requires the explicit"):
        _representative_run_contract(config)


def test_summary_and_lineage_metadata_records_v1_optima_and_solver_version() -> None:
    result = {
        "experiment_id": "sample",
        "solver_versions": ["12.0.3"],
        "planning_production_progress_optimum_t_by_day": [0.0],
        "planning_expected_cost_optimum_eur_by_day": [9_000_000.0],
        "planning_selected_incumbent_expected_cost_eur_by_day": [9_000_000.0],
    }
    metadata = _completed_run_contract_metadata(
        load_representative_config(), [result]
    )
    assert metadata["solver_versions"] == ["12.0.3"]
    assert metadata["planning_optima_by_experiment"] == [
        {
            "experiment_id": "sample",
            "production_progress_optimum_t_by_day": [0.0],
            "expected_cost_optimum_eur_by_day": [9_000_000.0],
            "selected_incumbent_expected_cost_eur_by_day": [9_000_000.0],
        }
    ]


def test_scenario_interface_accepts_causal_d_only_support() -> None:
    timestamps = tuple(pd.date_range("2025-01-12T23:00:00Z", periods=24, freq="h"))
    bundle = SteelPriceInformationBundle(
        delivery_day=date(2025, 1, 13),
        forecast_origin_utc=pd.Timestamp("2025-01-12T07:00:00Z"),
        timestamps_utc=timestamps,
        point_prices=tuple(50.0 for _ in timestamps),
        scenario_prices={"S10_01": tuple(40.0 for _ in timestamps)},
        scenario_probabilities={"S10_01": 1.0},
        scenario_source_blocks={"S10_01": "validation_block"},
    )
    scenarios, probabilities = _scenario_inputs("H-S10", bundle, None)
    assert len(scenarios["S10_01"]) == 24
    assert probabilities == {"S10_01": 1.0}
    context = _base_context_config(
        load_representative_config(), market_granularity="hourly", horizon_hours=24
    )
    split_active, market_intervals, economic_physical_intervals = (
        _split_horizon_support(context, bundle)
    )
    assert split_active
    assert market_intervals == 24
    assert economic_physical_intervals == context.time_grid.execution_steps == 96


def test_blocked_long_horizon_row_is_fail_closed() -> None:
    manifest = pd.DataFrame(
        [
            {
                "experiment_id": "blocked",
                "experiment_class": "horizon_sensitivity",
                "economic_execution_ready": False,
                "blockers": "causal_strict_dplus1_to_dplus4_support_missing",
            }
        ]
    )
    with pytest.raises(RepresentativeRegimeError, match="Fail-closed"):
        select_experiments(manifest, ["blocked"])


def test_cost_comparison_uses_positive_equals_saving() -> None:
    results = pd.DataFrame(
        [
            {
                "experiment_id": "A",
                "realised_total_cost_eur": 100.0,
                "expected_objective_lower_bound_eur": 98.0,
                "expected_objective_upper_bound_eur": 100.0,
            },
            {
                "experiment_id": "B",
                "realised_total_cost_eur": 90.0,
                "expected_objective_lower_bound_eur": 89.0,
                "expected_objective_upper_bound_eur": 90.0,
            },
            {
                "experiment_id": "C",
                "realised_total_cost_eur": 80.0,
                "expected_objective_lower_bound_eur": 79.5,
                "expected_objective_upper_bound_eur": 80.0,
            },
        ]
    )
    manifest = pd.DataFrame(
        [
            {
                "experiment_id": experiment_id,
                "week_id": "winter",
                "configuration": "C1",
                "arm": arm,
                "benchmark": "stochastic_policy",
            }
            for experiment_id, arm in (
                ("A", "A_hourly"),
                ("B", "B_qh_flat"),
                ("C", "C_qh_shape"),
            )
        ]
    )
    row = realised_cost_comparisons(results, manifest).iloc[0]
    assert row["delta_qh_market_eur"] == 10.0
    assert row["delta_shape_eur"] == 10.0
    assert row["delta_total_eur"] == 20.0
    assert row["expected_delta_qh_market_interval_lower_eur"] == 8.0
    assert row["expected_delta_qh_market_interval_upper_eur"] == 11.0
    assert row["expected_delta_shape_interval_lower_eur"] == 9.0
    assert row["expected_delta_shape_interval_upper_eur"] == 10.5
    assert row["expected_delta_total_interval_lower_eur"] == 18.0
    assert row["expected_delta_total_interval_upper_eur"] == 20.5
    assert bool(row["positive_means_saving"])


def test_experiment_directory_key_is_stable_and_windows_safe() -> None:
    experiment_id = "typical_winter__2024-12-02__central__A_hourly__C0__h24__s10__stochastic_policy"
    key = _experiment_directory_name(experiment_id)
    assert len(key) == 16
    assert key == _experiment_directory_name(experiment_id)


def test_split_horizon_gate_matrix_is_bounded_and_maintenance_free() -> None:
    config = load_representative_config()
    rows = _gate_experiment_rows(load_study_frames(config))
    assert len(rows) == 6
    assert set(rows["configuration"]) == {"C0", "C1"}
    assert set(rows["horizon_hours"]) == {24}
    assert set(rows["scenario_count"]) == {10}
    assert not rows["weekly_eaf_maintenance_active"].any()
    assert not rows["annual_outage_active"].any()


def test_all_central_ready_selection_does_not_mix_sensitivities() -> None:
    frames = load_study_frames(load_representative_config())
    selected = select_experiments(
        frames.experiment_manifest,
        [],
        all_ready=True,
        ready_scope="central",
    )
    assert len(selected) == 56
    assert set(selected["experiment_class"]) == {"central", "central_benchmark"}
    assert selected["economic_execution_ready"].all()


def test_four_week_matrix_is_blocked_by_execution_authorization() -> None:
    config = load_representative_config()
    frames = load_study_frames(config)
    selected = frames.experiment_manifest.loc[
        frames.experiment_manifest["experiment_id"].isin(
            [
                f"high_prices__2025-01-13__central__{arm}__C1__h24__s10__stochastic_policy"
                for arm in ("A_hourly", "B_qh_flat", "C_qh_shape")
            ]
        )
    ]
    _validate_execution_authorization(config, selected, all_ready=False)
    with pytest.raises(RepresentativeRegimeError, match="four-week matrix"):
        _validate_execution_authorization(config, selected, all_ready=True)


def test_explicit_receipt_authorizes_only_exact_frozen_56_row_matrix() -> None:
    config = deepcopy(load_representative_config())
    frames = load_study_frames(config)
    selected = select_experiments(
        frames.experiment_manifest,
        [],
        all_ready=True,
        ready_scope="central",
    )
    authorization = config["execution_authorization"]
    authorization["full_four_week_matrix_authorized"] = True
    authorization["authorization_receipt"] = "user_authorized_test_receipt"
    authorization["authorization_timestamp_utc"] = "2026-08-02T15:00:00Z"
    _validate_execution_authorization(config, selected, all_ready=True)
    with pytest.raises(RepresentativeRegimeError, match="exact all-central-ready"):
        _validate_execution_authorization(config, selected.iloc[:3], all_ready=False)
    with pytest.raises(RepresentativeRegimeError, match="frozen 56-row"):
        _validate_execution_authorization(config, selected.iloc[:-1], all_ready=True)


def test_full_matrix_authorization_requires_receipt_and_aware_timestamp() -> None:
    config = deepcopy(load_representative_config())
    frames = load_study_frames(config)
    selected = select_experiments(
        frames.experiment_manifest,
        [],
        all_ready=True,
        ready_scope="central",
    )
    authorization = config["execution_authorization"]
    authorization["full_four_week_matrix_authorized"] = True
    with pytest.raises(RepresentativeRegimeError, match="receipt and timestamp"):
        _validate_execution_authorization(config, selected, all_ready=True)
    authorization["authorization_receipt"] = "user_authorized_test_receipt"
    authorization["authorization_timestamp_utc"] = "2026-08-02T15:00:00"
    with pytest.raises(RepresentativeRegimeError, match="timezone-aware"):
        _validate_execution_authorization(config, selected, all_ready=True)


def test_resume_authorized_false_is_a_real_stop_sentinel() -> None:
    with _writable_scratch("c6_resume_sentinel") as run_root:
        (run_root / "run_control.json").write_text(
            json.dumps(
                {
                    "status": "emergency_recourse",
                    "resume_authorized": False,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(RepresentativeRegimeError, match="stop sentinel"):
            _assert_run_execution_authorized(run_root, resume=True)


def test_solver_progress_is_flushed_before_and_after_tier() -> None:
    with _writable_scratch("c6_solver_progress") as run_root:
        (run_root / "run_control.json").write_text(
            json.dumps({"status": "running", "resume_authorized": True}),
            encoding="utf-8",
        )
        callback = _solver_progress_callback(
            run_root,
            experiment_id="sample",
            delivery_day=date(2025, 1, 15),
            solve_stage="redispatch",
        )
        callback(
            {
                "event": "solver_tier_started",
                "tier": "redispatch_production_progress",
                "started_at_utc": "2026-08-01T20:00:00+00:00",
            }
        )
        callback(
            {
                "event": "solver_tier_finished",
                "tier": "redispatch_production_progress",
                "started_at_utc": "2026-08-01T20:00:00+00:00",
                "ended_at_utc": "2026-08-01T20:00:01+00:00",
                "runtime_seconds": 1.0,
                "solver_status": "ok",
                "termination_condition": "optimal",
                "mip_gap": 0.0,
            }
        )
        ledger = json.loads(
            (run_root / "solver_tier_progress.json").read_text(encoding="utf-8")
        )
        assert [event["event"] for event in ledger["events"]] == [
            "solver_tier_started",
            "solver_tier_finished",
        ]
        assert ledger["latest"]["mip_gap"] == 0.0


def test_emergency_recourse_stops_before_next_experiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _writable_scratch("c6_emergency_stop") as tmp_path:
        config = load_representative_config()
        config["outputs"]["central"]["root"] = str(tmp_path / "runs")
        frames_real = load_study_frames(config)
        selected = frames_real.experiment_manifest.loc[
            frames_real.experiment_manifest["experiment_id"].isin(
                [
                    f"high_prices__2025-01-13__central__{arm}__C1__h24__s10__stochastic_policy"
                    for arm in ("A_hourly", "B_qh_flat")
                ]
            )
        ].copy()
        frames = SimpleNamespace(
            experiment_manifest=selected,
            study_root=tmp_path / "study",
            family_root=tmp_path / "family",
        )
        calls: list[str] = []

        def fail_first(config, frames, row, run_root, *, resume):
            del config, frames, run_root, resume
            calls.append(str(row["experiment_id"]))
            raise Phase6DEmergencyRecourse(
                "positive minimum",
                {
                    "status": "emergency_recourse",
                    "absolute_imbalance_mwh": 0.25,
                },
            )

        monkeypatch.setattr(
            representative, "load_representative_config", lambda _: config
        )
        monkeypatch.setattr(representative, "load_study_frames", lambda _: frames)
        monkeypatch.setattr(
            representative,
            "select_experiments",
            lambda *args, **kwargs: selected,
        )
        monkeypatch.setattr(representative, "_sha256", lambda _: "sha256")
        monkeypatch.setattr(representative, "_git_head", lambda: "head")
        monkeypatch.setattr(
            representative,
            "_representative_run_contract",
            lambda _: {"imbalance_penalty_eur_per_mwh": 5000.0},
        )
        monkeypatch.setattr(
            representative,
            "_load_frozen_path_feasibility_patterns",
            lambda _: ([], tmp_path / "patterns.json"),
        )
        monkeypatch.setattr(
            representative, "_completed_run_contract_metadata", lambda *args: {}
        )
        monkeypatch.setattr(representative, "run_experiment", fail_first)
        outcome = run_selected_experiments(
            "ignored.yaml",
            list(selected["experiment_id"]),
            all_ready=False,
            ready_scope=None,
            run_id="emergency_stop_test",
            resume=False,
        )
        assert len(calls) == 1
        assert outcome["summary"]["status"] == "emergency_recourse"
        run_control = json.loads(
            (
                tmp_path
                / "runs"
                / "emergency_stop_test"
                / "run_control.json"
            ).read_text(encoding="utf-8")
        )
        assert not run_control["resume_authorized"]


def test_frozen_final_pattern_pool_has_no_economic_or_final_weight() -> None:
    config = load_representative_config()
    patterns, manifest_path = representative._load_frozen_path_feasibility_patterns(
        config
    )
    contract = config["experiment_contract"]["path_feasibility_augmentation"]
    assert representative._sha256(manifest_path) == contract[
        "frozen_pattern_manifest_sha256"
    ]
    assert patterns
    assert {str(item["market_grid"]) for item in patterns} == {
        "hourly",
        "quarterhour",
    }
    assert all(item["economic_scenario"] is False for item in patterns)
    assert all(item["settlement_eligible"] is False for item in patterns)
    assert all(item["forecast_metric_eligible"] is False for item in patterns)
    assert all(item["final_test_case"] is False for item in patterns)
    assert all("probability" not in item for item in patterns)
    assert all("expected_cost_weight" not in item for item in patterns)


def test_final_c1_path_planner_preserves_s10_and_shared_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import steel.s4_4c6_behavioural_validation as behavioural

    config = load_representative_config()
    timestamps = tuple(pd.date_range("2025-07-13T22:00:00Z", periods=24, freq="h"))
    probabilities = {f"s{index}": 0.1 for index in range(10)}
    scenarios = {
        scenario_id: tuple(100.0 + index for _ in timestamps)
        for index, scenario_id in enumerate(probabilities)
    }
    bundle = SteelPriceInformationBundle(
        delivery_day=date(2025, 7, 14),
        forecast_origin_utc=pd.Timestamp("2025-07-13T06:00:00Z"),
        timestamps_utc=timestamps,
        point_prices=tuple(100.0 for _ in timestamps),
        scenario_prices=scenarios,
        scenario_probabilities=probabilities,
        scenario_source_blocks={key: "frozen" for key in probabilities},
    )
    scenario_prices, normalized_probabilities = _scenario_inputs(
        "H-S10", bundle, None
    )
    contract_sha256 = representative._canonical_payload_sha256(
        {
            "scenario_ids": tuple(sorted(scenario_prices)),
            "scenario_prices": scenario_prices,
            "scenario_probabilities": normalized_probabilities,
        }
    )
    plan = SimpleNamespace(
        policy="H-S10",
        solver={"economic_s10_contract_sha256": contract_sha256},
    )
    patterns = [
        {"path_id": "hourly", "market_grid": "hourly", "final_test_case": False},
        {
            "path_id": "quarterhour",
            "market_grid": "quarterhour",
            "final_test_case": False,
        },
    ]
    captured: dict[str, object] = {}

    def fake_constraint_generation(prepared, case, candidate_patterns, state):
        captured.update(
            {
                "prepared": prepared,
                "case": case,
                "candidate_patterns": candidate_patterns,
                "state": state,
            }
        )
        return {
            "status": "pass",
            "plan": plan,
            "selected_paths": [candidate_patterns[0]],
            "rounds": [{"round_index": 0}, {"round_index": 1}],
        }

    monkeypatch.setattr(
        representative,
        "_load_frozen_path_feasibility_patterns",
        lambda _: (patterns, representative.REPRESENTATIVE_CONFIG),
    )
    monkeypatch.setattr(
        behavioural,
        "load_behavioural_config",
        lambda _: {
            "frozen_contract": {
                "path_feasibility_augmentation": {
                    "maximum_augmentation_rounds": 3,
                    "maximum_patterns_added_per_round": 1,
                }
            }
        },
    )
    monkeypatch.setattr(
        behavioural,
        "solve_constraint_generated_bid_plan",
        fake_constraint_generation,
    )
    state = representative.SteelRollingState(
        episode_id="final", configuration_id=representative.C1_CONFIGURATION
    )
    returned, metadata = representative._solve_final_c1_path_feasible_plan(
        config,
        SimpleNamespace(),
        {
            "experiment_id": "final__C1__A",
            "week_id": "typical_summer__2025-07-14",
            "regime_role": "typical_summer",
            "arm": "A_hourly",
        },
        delivery_day=date(2025, 7, 14),
        state=state,
        experiment_root=Path.cwd() / "tmp",
        bundle=bundle,
    )
    assert returned is plan
    assert captured["state"] is state
    assert captured["case"]["final_test_case"] is True
    assert captured["candidate_patterns"] is patterns
    assert metadata["selected_pattern_count"] == 1
    assert metadata["economic_s10_contract_sha256"] == contract_sha256
    assert not metadata["probability_assigned_to_feasibility_paths"]
    assert not metadata["expected_cost_weight_assigned_to_feasibility_paths"]
