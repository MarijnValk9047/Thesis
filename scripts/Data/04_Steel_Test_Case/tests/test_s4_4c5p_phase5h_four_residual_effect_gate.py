from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest
from pyomo.environ import Objective, value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_phase5h_four_residual_effect_gate import (
    CONFIG_PATH,
    FAMILIES,
    OLD_OPENED_HELD_OUT,
    _best_share,
    component_exceedances,
    held_out_contract,
    load_config,
    load_four_residual_overlap,
    steam_evidence_gate,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    NG_COMBUSTION_T_CO2_PER_MWH_LHV,
    REPO_ROOT,
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _build_c0_model,
    _load_tables,
)


CONTRACT_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_phase5h_four_residual_contract"
)


def test_phase5h_config_is_bounded_and_failed_phase5g_contract_is_inactive() -> None:
    phase = load_config(CONFIG_PATH)["phase5h"]

    assert phase["percentage_grid"] == pytest.approx([index / 10 for index in range(1, 10)])
    assert phase["maximum_campaign_models"] == 1680
    assert phase["policy"]["phase5g_failed_baseload_active"] is False
    assert phase["policy"]["all_four_required_for_promotion"] is True
    assert phase["policy"]["steam_branch_fail_closed_without_maximum"] is True
    assert phase["decision_on_fail"] == "four_residual_gate_failed_residual_layer_not_promoted"


def test_overlap_contract_covers_all_families_once_per_explicit_field() -> None:
    rows = load_four_residual_overlap(CONTRACT_ROOT / "four_residual_overlap_contract.csv")

    assert {row["family"] for row in rows} == set(FAMILIES)
    fields = [
        (row["configuration"], row["family"], field)
        for row in rows for field in row["dynamic_overlap_fields"]
    ]
    assert len(fields) == len(set(fields))
    boundaries = [row for row in rows if row["overlap_classification"] == "boundary_remainder_ineligible"]
    assert {(row["configuration"], row["source_value"]) for row in boundaries} == {
        ("C0", 2.3), ("C1", 1.6)
    }
    assert all(row["residual_eligible"] is False for row in boundaries)
    assert all(row["residual_eligible"] is False for row in rows if "scope2" in row["overlap_classification"])


def test_steam_evidence_fails_closed_and_prohibited_bases_cannot_form_pool() -> None:
    result = steam_evidence_gate(CONTRACT_ROOT / "steam_residual_evidence_gate.csv")

    assert result["status"] == "fail"
    assert result["defensible_maximum_exists"] is False
    assert result["eligible_row_count"] == 0
    assert result["decision"] == "steam_branch_stopped_no_defensible_normal_operation_maximum"
    assert {"P5H-STEAM-HERACLES-START", "P5H-STEAM-RETIRED", "P5H-STEAM-CAPACITY", "P5H-STEAM-SPILL"}.issubset(
        set(result["prohibited_bases_present"])
    )


def test_fresh_heldout_is_frozen_unopened_and_excludes_old_periods() -> None:
    rows, fingerprint = held_out_contract(CONTRACT_ROOT / "fresh_held_out_period_contract.csv")

    assert len(rows) == 4
    assert not ({row["period_id"] for row in rows} & OLD_OPENED_HELD_OUT)
    assert {row["status"] for row in rows} == {"frozen_unopened"}
    assert len(fingerprint) == 64


def test_shared_selection_requires_both_configurations_and_breaks_ties_low() -> None:
    alpha, rows = _best_share(
        {"C0": 82.0, "C1": 82.0}, {"C0": 40.0, "C1": 40.0},
        {"C0": 100.0, "C1": 100.0},
    )
    assert alpha == pytest.approx(0.4)
    assert all(0.0 < row["share"] < 1.0 for row in rows)

    failed, _ = _best_share(
        {"C0": 82.0, "C1": 120.0}, {"C0": 40.0, "C1": 40.0},
        {"C0": 100.0, "C1": 100.0},
    )
    assert failed is None


def test_component_guard_rejects_generator_ng_above_source_before_residual() -> None:
    rows = [{
        "mapping_id": "C0-generator", "dynamic_overlap_fields": "generator_named_ng_mwh",
        "mapped_explicit_model_pj_y": 2.1, "source_value_pj_y": 1.9,
    }, {
        "mapping_id": "C0-unmodelled", "dynamic_overlap_fields": "",
        "mapped_explicit_model_pj_y": 9.0, "source_value_pj_y": 1.5,
    }]

    assert [row["mapping_id"] for row in component_exceedances(rows, 1e-6)] == [
        "C0-generator"
    ]
    assert component_exceedances(
        rows, 1e-6, {"C0-generator": 2.1, "C0-unmodelled": 9.0}
    ) == []
    assert [row["mapping_id"] for row in component_exceedances(
        rows, 1e-6, {"C0-generator": 1.8, "C0-unmodelled": 9.0}
    )] == ["C0-generator"]


def test_builder_residual_steam_is_constant_additive_and_co2_is_reporting_only() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR), horizon_hours_override=1, target_multiplier=1.0
    )
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        development_controller_activation="full",
        site_residual_steam_t_h=2.5,
        site_residual_direct_co2_t_h=3.5,
    )

    assert value(model.residual_steam_15bar_demand_t[0]) == pytest.approx(2.5)
    assert value(model.steam_15bar_demand_t[0]) == pytest.approx(
        value(model.steam_15bar_explicit_demand_t[0]) + 2.5
    )
    assert value(model.residual_unmodelled_direct_co2_t[0]) == pytest.approx(3.5)
    assert value(model.represented_process_counter_direct_co2_t[0]) == pytest.approx(0.0)
    assert NG_COMBUSTION_T_CO2_PER_MWH_LHV == pytest.approx(0.20196)
    objective_text = " ".join(str(component.expr) for component in model.component_objects(Objective, active=True))
    assert "residual_unmodelled_direct_co2" not in objective_text


def test_nonpromoted_contract_has_no_executable_or_selected_rows() -> None:
    with (CONTRACT_ROOT / "four_residual_candidate_contract.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 8
    assert {row["executable"] for row in rows} == {"false"}
    assert {row["selected_share"] for row in rows} == {"0"}
    assert all("selected_validation_frozen" not in row["status"] for row in rows)


def test_gate_order_keeps_selected_validation_and_heldout_after_steam_pass_only() -> None:
    module = (
        STEEL_ROOT / "steel/s4_4c5p_phase5h_four_residual_effect_gate.py"
    ).read_text(encoding="utf-8")

    evidence = module.index("steam_gate = steam_evidence_gate")
    heldout_freeze = module.index("_, heldout_sha = held_out_contract")
    benchmark = module.index("baseline_artifacts, baseline_status")
    assert evidence < heldout_freeze < benchmark
    assert "held_out_artifacts" not in module
