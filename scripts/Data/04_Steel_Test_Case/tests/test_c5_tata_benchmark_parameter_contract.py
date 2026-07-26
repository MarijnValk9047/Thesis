import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[4]
STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c_unified_physical_modelbuilder import S44B_INPUT_DIR, _load_tables


CONTRACT_DIR = (
    ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "c5_tata_benchmark_target_contract"
)
PARAMETER_PATH = CONTRACT_DIR / "calibratable_parameter_contract.csv"
TARGET_PATH = CONTRACT_DIR / "calibration_validation_target_contract.csv"
FREEZE_PATH = CONTRACT_DIR / "baseline_freeze.json"

REQUIRED_FIELDS = {
    "parameter_id",
    "parameter_family",
    "active_central",
    "low",
    "high",
    "unit",
    "activity_basis",
    "source_id",
    "source_locator",
    "evidence_strength",
    "affected_processes",
    "allowed_target_ids",
    "allowed_target_families",
    "may_move",
    "structurally_linked",
    "baseline_field",
    "baseline_path",
    "explicit_driver",
    "overlay_mode",
    "caveats",
    "allowed_values",
    "required_mode",
    "calibration_group",
    "co_movement_rule",
    "identifiability_role",
}
IDENTIFIABILITY_FIELDS = {
    "allowed_values",
    "required_mode",
    "calibration_group",
    "co_movement_rule",
    "identifiability_role",
}
AUDIT_FROZEN = {
    "bfg_generation_nm3_per_t_hot_metal",
    "cog_generation_m3_per_t_dry_coal",
    "bofg_generation_nm3_per_t_liquid_steel",
    "vn25_electricity_efficiency",
}
FORBIDDEN_FAMILIES = {
    "production_quotas",
    "governed_material_conversions",
    "official_capacities",
    "residual_electricity",
    "residual_ng",
    "wag_ng_ratios",
    "aggregate_mixed_wag_allocation",
    "wobbe_gas_quality",
    "arbitrary_process_co2_counters",
    "source_blocked_routes",
}


def _csv_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_parameter_contract_ranges_drivers_targets_and_forbidden_families():
    rows = _csv_rows(PARAMETER_PATH)
    assert rows
    assert set(rows[0]) == REQUIRED_FIELDS
    assert all(
        all(row[field].strip() for field in REQUIRED_FIELDS - IDENTIFIABILITY_FIELDS)
        for row in rows
    )
    assert {row["may_move"] for row in rows} <= {"true", "false"}
    assert {row["structurally_linked"] for row in rows} <= {"true", "false"}

    ids = [row["parameter_id"] for row in rows]
    assert len(ids) == len(set(ids))
    movable = {row["parameter_id"] for row in rows if row["may_move"] == "true"}
    assert movable == set()
    assert not any(
        row["may_move"] == "true" and row["parameter_family"] in FORBIDDEN_FAMILIES
        for row in rows
    )
    assert FORBIDDEN_FAMILIES <= {
        row["parameter_family"] for row in rows if row["may_move"] == "false"
    }

    for row in rows:
        if row["parameter_id"] not in AUDIT_FROZEN:
            continue
        low = float(row["low"])
        central = float(row["active_central"])
        high = float(row["high"])
        assert all(math.isfinite(value) for value in (low, central, high))
        assert low < high
        assert low <= central <= high
        assert row["source_locator"] != "not_applicable"
        assert row["baseline_field"] != "not_applicable"
        assert (ROOT / row["baseline_path"]).exists()
        assert row["explicit_driver"] != "not_applicable"
        assert row["may_move"] == "false"
        assert row["allowed_target_ids"] == "none"
        assert row["allowed_target_families"] == "none"
        assert row["overlay_mode"] == "forbidden_audit_freeze"
        assert row["required_mode"] == "source_driven_baseline_only"
        assert all(row[field].strip() for field in IDENTIFIABILITY_FIELDS)
        assert "zero comparable calibration targets" in row["caveats"]

    by_id = {row["parameter_id"]: row for row in rows}
    cog = by_id["cog_generation_m3_per_t_dry_coal"]
    assert cog["activity_basis"] == "per tonne coking dry-coal input"
    assert "STEEL-WAG-EVID-0004" in cog["source_id"]
    assert "0005" not in cog["source_id"]

    wag_rows = [row for row in rows if row["parameter_family"] == "wag_generation_coefficient"]
    assert len(wag_rows) == 3
    assert {row["calibration_group"] for row in wag_rows} == {
        "audit_frozen_no_comparable_target"
    }
    assert {row["co_movement_rule"] for row in wag_rows} == {
        "none_while_frozen"
    }
    vn25 = by_id["vn25_electricity_efficiency"]
    assert vn25["calibration_group"] == "audit_frozen_no_comparable_target"
    assert vn25["allowed_values"] == "0.34;0.345"
    assert vn25["high"] == vn25["active_central"] == "0.345"
    assert vn25["required_mode"] == "source_driven_baseline_only"

    kgf_rows = [row for row in rows if row["parameter_family"] == "kgf_annual_operating_output"]
    assert {row["parameter_id"] for row in kgf_rows} == {
        "c0_kgf1_annual_coke_output",
        "c0_kgf2_annual_coke_output",
        "c1_kgf1_annual_coke_output",
    }
    assert {row["may_move"] for row in kgf_rows} == {"false"}
    assert {row["identifiability_role"] for row in kgf_rows} == {
        "no_executable_degree_of_freedom"
    }

    pefa_rows = [row for row in rows if row["parameter_family"] == "pefa_annual_component_output"]
    assert {row["parameter_id"] for row in pefa_rows} == {
        "c0_pefa_annual_fired_pellet_output",
        "c1_pefa_annual_fired_pellet_output",
    }
    assert {row["may_move"] for row in pefa_rows} == {"false"}
    assert {row["identifiability_role"] for row in pefa_rows} == {
        "direct_target_overlap_and_missing_physical_linkage"
    }
    assert all("missing_consumption_inventory_terminal_linkage" in row["overlay_mode"] for row in pefa_rows)
    assert by_id["c0_pefa_annual_fired_pellet_output"]["active_central"] == "4.3125"
    assert by_id["c0_pefa_annual_fired_pellet_output"]["low"] == "4.6"
    assert by_id["c0_pefa_annual_fired_pellet_output"]["high"] == "4.6"
    assert by_id["c1_pefa_annual_fired_pellet_output"]["active_central"] == "4.963235294118"
    assert by_id["c1_pefa_annual_fired_pellet_output"]["low"] == "4.0"
    assert by_id["c1_pefa_annual_fired_pellet_output"]["high"] == "5.0"
    assert "source-designated central and high" in by_id["c1_pefa_annual_fired_pellet_output"]["caveats"]


def test_runtime_wag_table_remains_source_driven_and_unchanged():
    active_dir = (
        ROOT
        / "data/03_Optimisation/inputs/assets/steel/S4/"
        "s4_4b5a_asymmetric_c0_c1_correction/corrected_dev_inputs"
    ).resolve()
    assert S44B_INPUT_DIR == active_dir
    runtime_path = active_dir / "wag_generation_coefficients.csv"
    frozen_hash = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    runtime_rows = _csv_rows(runtime_path)

    expected = {
        "BFG": (1600.0, "Nm3/t_hot_metal", "per tonne BF hot metal"),
        "COG": (365.0, "m3/t_dry_coal", "per tonne dry coal"),
        "BOFG": (75.0, "Nm3/t_liquid_steel", "per tonne BOF liquid steel"),
    }
    for carrier, (central, unit, basis) in expected.items():
        selected = [row for row in runtime_rows if row["wag_carrier"] == carrier]
        assert selected
        assert {float(row["coefficient"]) for row in selected} == {central}
        assert {row["coefficient_unit"] for row in selected} == {unit}
        assert {row["basis"] for row in selected} == {basis}
        assert {row["configuration_id"] for row in selected} <= {
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        }

    loaded = _load_tables(input_dir=active_dir)
    loaded_wag = loaded.tables["wag_generation_coefficients.csv"]
    for carrier, (central, _, _) in expected.items():
        assert {
            float(row["coefficient"])
            for row in loaded_wag
            if row["wag_carrier"] == carrier
        } == {central}
    assert hashlib.sha256(runtime_path.read_bytes()).hexdigest() == frozen_hash


def test_vn25_choices_match_active_config_and_generator_modes():
    config_path = (
        ROOT
        / "scripts/Data/04_Steel_Test_Case/configs/"
        "steel_hourly_da_dplus4_point_forecast_integration.yaml"
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["c1_generator_boundary"]["vn25_electricity_efficiency"] == 0.345

    mode_path = (
        ROOT
        / "data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/"
        "c5_generator_operating_mode_contract.csv"
    )
    modes = {row["mode_id"]: row for row in _csv_rows(mode_path)}
    bounded = {
        float(value)
        for value in modes["bounded_generator_sensitivity"]["allowed_efficiencies"].split(";")
    }
    assert bounded == {0.34, 0.345}
    assert modes["development_price_responsive"]["allowed_efficiencies"] == "0.345"
    assert modes["price_insensitive_reference"]["allowed_efficiencies"] == "0.345"
    assert 0.35 not in bounded


def test_baseline_freeze_hashes_and_overlay_policy():
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    assert freeze["baseline_status"] == "immutable"
    assert freeze["checkpoint"] == 8
    reconciliation = freeze["post_freeze_reconciliation"]
    assert (
        reconciliation["accepted_diagnostic_lineage"]
        == "steel_c5_wag_ng_allocation_envelope_v6_20260726"
    )
    assert reconciliation["absent_hook_baseline_behaviour_changed"] is False
    assert reconciliation["physical_parameters_changed"] is False
    assert reconciliation["candidate_promoted"] is False
    assert "remain may_move=false" in freeze["candidate_policy"]
    assert freeze["identifiability"]["effective_degrees_of_freedom"] == 0
    assert freeze["identifiability"]["calibration_observations"] == 0
    assert freeze["identifiability"]["observation_ids"] == []
    assert freeze["identifiability"]["qualified_but_unlinked_calibration_observations"] == 5
    assert set(freeze["identifiability"]["qualified_but_unlinked_observation_ids"]) == {
        "mer_c0_kgf1_coke_1_0",
        "mer_c0_kgf2_coke_0_8",
        "mer_c1_kgf1_coke_1_0",
        "mer_c0_pefa_output_4_6",
        "mer_c1_pefa_output_4_0_5_0",
    }
    wag_group = freeze["identifiability"]["groups"]["wag_generation_range_position"]
    assert wag_group["independent_coefficient_fitting_allowed"] is False
    assert wag_group["rule"] == (
        "no movement because checkpoint-3B KGF/PeFa output targets do not identify "
        "WAG-generation coefficients"
    )
    kgf_group = freeze["identifiability"]["groups"]["kgf_annual_output"]
    assert kgf_group["executable_degree_of_freedom"] is False
    pefa_group = freeze["identifiability"]["groups"]["pefa_annual_output"]
    assert pefa_group["source_ranges_mt_y"] == {"C0": [4.6, 4.6], "C1": [4.0, 5.0]}
    assert pefa_group["source_central_mt_y"]["C1"] == pefa_group["source_ranges_mt_y"]["C1"][1] == 5.0
    assert pefa_group["executable_degree_of_freedom"] is False
    independent = freeze["identifiability"]["independent_quantitative_validation"]
    assert independent["family_count"] == 0
    assert independent["target_ids"] == []
    assert independent["reclassified_target_id"] == "mer_c1_dri_output_2_8"
    assert independent["reclassified_role"] == "scenario_definition_consistency_check"
    assert "0.8484848485" in independent["overlap_evidence"]
    screen = freeze["identifiability"]["checkpoint_8_analytical_screen"]
    assert screen["overlay_candidate_count"] == 5
    assert screen["retained_rolling_candidate_count"] == 0
    assert screen["solver_runs_performed"] is False
    assert screen["held_out_targets_used"] is False
    assert screen["held_out_periods_used"] is False
    assert screen["decision"] == "source_valid_emulation_rejected"
    assert freeze["files"]
    for item in freeze["files"] + freeze["active_input_files"]:
        path = ROOT / item["path"]
        assert path.is_file()
        payload = path.read_bytes()
        if item.get("hash_policy") == "semantic_json_excluding_volatile_fields":
            assert item["volatile_fields"] == ["timestamp_utc"]
            semantic_payload = json.loads(payload.decode("utf-8"))
            for field in item["volatile_fields"]:
                assert field in semantic_payload
                del semantic_payload[field]
            canonical = json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            assert hashlib.sha256(canonical).hexdigest() == item["semantic_sha256"]
            continue
        assert len(payload) == item["bytes"]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]

    active_dir = ROOT / freeze["active_input_directory"]
    actual_paths = {
        path.relative_to(ROOT).as_posix()
        for path in active_dir.iterdir()
        if path.is_file()
    }
    frozen_paths = {item["path"] for item in freeze["active_input_files"]}
    assert frozen_paths == actual_paths
