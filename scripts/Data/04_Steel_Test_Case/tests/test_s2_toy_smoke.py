from __future__ import annotations

import json
import inspect
from pathlib import Path
from shutil import copytree
import sys

import pandas as pd
import pytest
from pyomo.environ import Var
import yaml

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.config import load_config
from steel.governance import (
    dry_run_validate_input_governance,
    load_s2_candidate_mapping,
    load_s2_candidate_review,
    load_s2_schema,
    load_s2_topology_skeleton,
    validate_s2_candidate_review,
)
from steel.input_tables import load_governed_toy_tables
from steel.model import build_model, choose_solver
from steel.runner import run_from_config
from steel.topology_loader import load_topology_skeleton, validate_topology_skeleton
from steel.topology_objects import build_steel_topology, build_steel_topology_from_registry

FORBIDDEN_HORIZON_PATTERN = r"(?:^|[^a-z0-9])d-only(?:[^a-z0-9]|$)|(?:^|[^a-z0-9])d_only(?:[^a-z0-9]|$)|(?:^|[^a-z0-9])d\+4(?:[^a-z0-9]|$)|(?:^|[^a-z0-9])d_plus_4(?:[^a-z0-9]|$)"

CONFIG_PATH = TEST_CASE_ROOT / "configs" / "base_s2_toy_smoke.yaml"
CANDIDATE_REVIEW_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "candidate_review_toy_parse_only.yaml"
IMPOSSIBLE_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "impossible_production_target.yaml"
TERMINAL_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "terminal_inventory_infeasible.yaml"
FEED_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "route_feed_shortage_or_buffer_bottleneck.yaml"
SCHEMA_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_schema"
MAPPING_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_mapping"
REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"


def test_model_builds_with_zero_binaries():
    config = load_config(CONFIG_PATH)
    model = build_model(config)
    binary_count = sum(
        1
        for variable in model.component_data_objects(ctype=Var, active=True, descend_into=True)
        if variable.is_binary()
    )
    assert binary_count == 0


def test_smoke_run_outputs(tmp_path: Path):
    config = load_config(CONFIG_PATH)
    try:
        choose_solver(config)
    except RuntimeError:
        pytest.skip("No LP solver available for the steel S2.0 smoke test.")

    result = run_from_config(
        CONFIG_PATH,
        output_root_override=tmp_path,
        run_id_override="pytest_steel_s2_toy_smoke",
    )
    run_dir = Path(result["run_dir"])
    required_files = {
        "resolved_config.yaml",
        "model_stats.json",
        "solver_summary.json",
        "flows.csv",
        "inventories.csv",
        "production_summary.csv",
        "validation_summary.csv",
        "warnings_and_limitations.md",
        "stage_note.md",
        "run_manifest.json",
    }
    assert required_files.issubset({path.name for path in run_dir.iterdir()})

    model_stats = json.loads((run_dir / "model_stats.json").read_text(encoding="utf-8"))
    assert model_stats["binary_count"] == 0

    run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert run_summary["input_mode"] == "toy_scaffold"
    assert run_summary["thesis_usable"] == "no"

    validation_csv = (run_dir / "validation_summary.csv").read_text(encoding="utf-8")
    assert "production_target_met" in validation_csv
    assert "input_mode_declared" in validation_csv
    assert "thesis_usable" in validation_csv


def test_governed_toy_tables_have_required_metadata():
    config = load_config(CONFIG_PATH)
    assert config.input_tables is not None
    bundle = load_governed_toy_tables(
        config.input_tables.table_root,
        config.input_tables.scenario_or_config,
        input_mode=config.input_tables.input_mode,
    )
    assert bundle.row_counts["carriers"] > 0
    for table_name, frame in bundle.tables.items():
        assert "source_status" in frame.columns
        assert "approval_status" in frame.columns
        assert frame["approval_status"].eq("not_approved").all(), table_name


def test_s2_schema_and_mapping_files_parse():
    schema_bundle = load_s2_schema(SCHEMA_ROOT)
    mapping_bundle = load_s2_candidate_mapping(MAPPING_ROOT)
    assert len(schema_bundle.tables) >= 10
    assert len(mapping_bundle.tables) == 4


def test_candidate_review_files_parse_and_have_zero_approved_rows():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["candidate_review_data_files_checked"] == 10
    assert payload["candidate_review_files_checked"] == 19
    assert payload["promotion_packet_rows_checked"] == 5
    assert payload["unit_sign_endpoint_note_present"] is True
    assert payload["deepsearch_f_source_rows_checked"] == 20
    assert payload["deepsearch_f_candidate_assumption_rows_checked"] > 0
    assert payload["deepsearch_f_matrix_rows_checked"] > 0
    assert payload["configuration_rows_checked"] == 4
    assert payload["main_configuration_rows"] == 2
    assert payload["configuration_tag_mapping_rows_checked"] == 33
    assert payload["topology_skeleton_files_checked"] == 7
    assert payload["topology_configuration_rows_checked"] == 2
    assert payload["topology_route_rows_checked"] == 3
    assert payload["topology_process_unit_rows_checked"] == 17
    assert payload["topology_carrier_rows_checked"] == 11
    assert payload["topology_store_rows_checked"] == 7
    assert payload["topology_arc_rows_checked"] == 32
    assert payload["topology_inventory_policy_rows_checked"] == 4
    assert payload["topology_object_configuration_count"] == 2
    assert payload["topology_object_route_count"] == 3
    assert payload["topology_object_process_unit_count"] == 17
    assert payload["topology_object_carrier_count"] == 11
    assert payload["topology_object_store_count"] == 7
    assert payload["topology_object_arc_count"] == 32
    assert payload["topology_object_inventory_policy_count"] == 4
    assert payload["topology_object_warnings"] == []
    assert payload["approved_rows"] == 0
    assert payload["candidate_review_total_rows"] > 0
    assert payload["thesis_grade_numerical_rows"] == 0
    assert payload["candidate_review_executable_rows"] == 0
    assert payload["later_stage_s2_executable_rows"] == 0

    checklist = review_bundle.tables["s2_promotion_checklist.csv"]
    assert checklist["approval_ready"].str.lower().eq("false").all()
    assert checklist["thesis_grade_numerical_ready"].str.lower().eq("false").all()
    assert checklist["candidate_review_executable"].str.lower().eq("false").all()

    summary = review_bundle.tables["s2_review_summary.csv"]
    assert "TOTAL" in set(summary["review_table"])

    classification = review_bundle.tables["s2_structural_numerical_classification.csv"]
    assert classification["approval_status"].str.lower().isin({"candidate_not_approved", "validation_only", "postponed"}).all()
    assert classification["thesis_grade_numerical_eligibility"].str.lower().eq("false").all()
    assert classification["annual_value_status"].str.lower().ne("may_become_hourly_cap").all()

    packet_index = review_bundle.tables["s2_numerical_promotion_packet_index.csv"]
    assert set(packet_index["category"]) == {
        "process_bounds",
        "conversion_coefficients",
        "production_targets",
        "initial_inventories",
        "terminal_inventory_rules",
    }
    assert packet_index["approval_status"].str.lower().isin({"blocked", "not_approved"}).all()
    assert packet_index["thesis_grade_numerical_eligibility"].str.lower().eq("false").all()
    assert packet_index["executable_use_status"].str.lower().eq("non_executable").all()
    assert packet_index["validation_use_status"].str.lower().eq("cannot_drive_constraints").all()
    assert packet_index["annual_to_hourly_status"].str.lower().isin({"annual_public_values_not_hourly_cap", "not_annual_value"}).all()

    configuration_register = review_bundle.tables["s2_configuration_scope_register.csv"]
    assert set(configuration_register["configuration_id"]) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        "C1S_phase1_sensitivity_variants",
        "C2_exogenous_hydrogen_sensitivity_optional_later",
    }
    main_rows = configuration_register["main_case_flag"].str.lower().eq("true")
    assert set(configuration_register.loc[main_rows, "configuration_id"]) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    }
    c1s = configuration_register.loc[configuration_register["configuration_id"].eq("C1S_phase1_sensitivity_variants")].iloc[0]
    assert c1s["sensitivity_only_flag"] == "true"
    assert c1s["main_case_flag"] == "false"
    c2 = configuration_register.loc[configuration_register["configuration_id"].eq("C2_exogenous_hydrogen_sensitivity_optional_later")].iloc[0]
    assert c2["optional_later_flag"] == "true"
    assert c2["sensitivity_only_flag"] == "true"
    assert c2["main_case_flag"] == "false"
    assert configuration_register["executable_status"].isin({"non_executable", "not_implemented"}).all()
    assert configuration_register["thesis_usability"].str.lower().eq("false").all()
    assert configuration_register["approval_status"].isin({"not_approved", "scope_freeze_only"}).all()
    scan = configuration_register.astype(str).agg(" ".join, axis=1).str.lower()
    assert not scan.str.contains(FORBIDDEN_HORIZON_PATTERN, regex=True).any()

    configuration_tag_mapping = review_bundle.tables["s2_configuration_tag_mapping.csv"]
    assert set(configuration_tag_mapping["mapped_configuration_id"]).issuperset(
        {
            "C0_current_BF_BOF_reference",
            "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            "C1S_phase1_sensitivity_variants",
            "C2_exogenous_hydrogen_sensitivity_optional_later",
            "postponed_or_blocked",
        }
    )
    blocked_tags = {"Phase 2", "Phase 3", "full_hydrogen", "on_site_electrolysis", "hydrogen_production_optimisation", "hydrogen_storage", "SAF", "CCS"}
    blocked_rows = configuration_tag_mapping["legacy_tag"].isin(blocked_tags)
    assert configuration_tag_mapping.loc[blocked_rows, "mapped_configuration_id"].eq("postponed_or_blocked").all()
    assert configuration_tag_mapping["executable_status"].eq("non_executable").all()
    assert configuration_tag_mapping["thesis_usability"].str.lower().eq("false").all()
    assert configuration_tag_mapping["approval_status"].isin({"not_approved", "scope_mapping_only", "blocked"}).all()
    c1s_rows = configuration_tag_mapping["mapped_configuration_id"].eq("C1S_phase1_sensitivity_variants")
    assert configuration_tag_mapping.loc[c1s_rows, "mapped_configuration_role"].eq("sensitivity_only_within_C1").all()
    c2_rows = configuration_tag_mapping["mapped_configuration_id"].eq("C2_exogenous_hydrogen_sensitivity_optional_later")
    assert configuration_tag_mapping.loc[c2_rows, "mapped_configuration_role"].eq("optional_later_sensitivity_only").all()
    mapping_scan = configuration_tag_mapping.astype(str).agg(" ".join, axis=1).str.lower()
    assert not mapping_scan.str.contains(FORBIDDEN_HORIZON_PATTERN, regex=True).any()

    topology_bundle = load_s2_topology_skeleton(REVIEW_ROOT)
    topology_configurations = topology_bundle.tables["configurations.csv"]
    assert set(topology_configurations["configuration_id"]) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    }
    assert topology_configurations["main_case_flag"].str.lower().eq("true").all()
    assert topology_configurations["sensitivity_only_flag"].str.lower().eq("false").all()
    assert topology_configurations["optional_later_flag"].str.lower().eq("false").all()

    topology_routes = topology_bundle.tables["routes.csv"]
    assert {
        ("C0_current_BF_BOF_reference", "C0_ROUTE_BF_BOF"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_RETAINED_BF_BOF"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_NG_DRP_EAF"),
    } == {(row["configuration_id"], row["route_id"]) for row in topology_routes.to_dict(orient="records")}
    route_scan = topology_routes.astype(str).agg(" ".join, axis=1).str.lower()
    assert not route_scan.str.contains(r"phase 2|phase2|phase 3|phase3|full_hydrogen|on_site_electrolysis|hydrogen_storage|saf|ccs", regex=True).any()

    topology_carriers = topology_bundle.tables["carriers.csv"]
    boundary_rows = topology_carriers["carrier_id"].isin(
        {"coal_or_coke_input_boundary", "iron_ore_or_pellet_input_boundary", "scrap_input_boundary", "flux_input_boundary"}
    )
    assert topology_carriers.loc[boundary_rows, "external_supply_flag"].str.lower().eq("true").all()
    assert topology_carriers.loc[boundary_rows, "internal_carrier_flag"].str.lower().eq("false").all()

    topology_stores = topology_bundle.tables["stores.csv"]
    assert topology_stores["bounded_store_required"].str.lower().eq("true").all()
    assert not topology_stores["store_name"].str.lower().str.contains(r"coke|sinter|pellet", regex=True).any()

    topology_inventory_policy = topology_bundle.tables["inventory_policy.csv"]
    cyc50_rows = topology_inventory_policy["endpoint_policy"].str.contains("CYC50", case=False, regex=False)
    assert cyc50_rows.any()
    assert topology_inventory_policy.loc[cyc50_rows, "numerical_status"].eq("no_numerical_value").all()
    assert topology_inventory_policy.loc[cyc50_rows, "executable_status"].eq("non_executable").all()

    deepsearch_f_source_index = review_bundle.tables["s2_deepsearch_f_source_index.csv"]
    assert set(deepsearch_f_source_index["source_id"]) == {f"F{index:02d}" for index in range(1, 21)}
    f07 = deepsearch_f_source_index.loc[deepsearch_f_source_index["source_id"].eq("F07")].iloc[0]
    assert f07["canonical_title"] == "ENERGIRON: DRI Technology by Tenova and Danieli"
    assert f07["url_or_doi"] == "https://tenova.com/sites/default/files/files/solutions/2026/ENERGIRON_Brochure_ENG.pdf"
    assert "ENERGIRON_Brochure_ENG.pdf" in f07["local_file_reference"]

    f15 = deepsearch_f_source_index.loc[deepsearch_f_source_index["source_id"].eq("F15")].iloc[0]
    assert f15["author_or_institution"] == "Geani Kasselman"
    assert f15["year"] == "2011"
    assert "Kasselman_Operations(2011).pdf" in f15["local_file_reference"]

    deepsearch_f_register = review_bundle.tables["s2_deepsearch_f_candidate_assumption_register.csv"]
    assert deepsearch_f_register["executable_status"].eq("non_executable").all()
    assert deepsearch_f_register["thesis_usability"].str.lower().eq("false").all()
    assert not deepsearch_f_register["category"].str.lower().str.contains(r"d_only|d\+4|d_plus_4", regex=True).any()
    annual_rows = deepsearch_f_register["unit"].str.contains("per_year|/y", case=False, regex=True)
    assert annual_rows.any()
    assert deepsearch_f_register.loc[annual_rows, "recommended_status"].eq("validation_target_only").all()
    assert deepsearch_f_register.loc[annual_rows, "approval_blocker"].str.lower().str.contains("hourly").all()


def test_topology_loader_loads_current_registry():
    topology_bundle = load_topology_skeleton(REVIEW_ROOT)
    payload = validate_topology_skeleton(topology_bundle)

    assert payload["topology_skeleton_files_checked"] == 7
    assert payload["topology_configuration_rows_checked"] == 2
    assert payload["topology_route_rows_checked"] == 3
    assert payload["topology_process_unit_rows_checked"] == 17
    assert payload["topology_carrier_rows_checked"] == 11
    assert payload["topology_store_rows_checked"] == 7
    assert payload["topology_arc_rows_checked"] == 32
    assert payload["topology_inventory_policy_rows_checked"] == 4
    assert payload["topology_loader_warnings"] == []


def test_topology_loader_rejects_unbounded_internal_store(tmp_path: Path):
    source_root = REVIEW_ROOT / "s2_topology_skeleton"
    copied_root = tmp_path / "s2_topology_skeleton"
    copytree(source_root, copied_root)

    stores_path = copied_root / "stores.csv"
    stores = pd.read_csv(stores_path, dtype=str, keep_default_na=False)
    stores.loc[stores["store_id"].eq("c1_dri_hdri_buffer"), "bounded_store_required"] = "false"
    stores.to_csv(stores_path, index=False)

    topology_bundle = load_topology_skeleton(tmp_path)
    with pytest.raises(ValueError, match="bounded"):
        validate_topology_skeleton(topology_bundle)


def test_topology_object_builder_constructs_structural_topology():
    topology = build_steel_topology_from_registry(REVIEW_ROOT)

    assert set(topology.configurations) == {
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    }
    assert topology.summary_counts() == {
        "configurations": 2,
        "routes": 3,
        "process_units": 17,
        "carriers": 11,
        "stores": 7,
        "arcs": 32,
        "inventory_policies": 4,
    }

    assert len(topology.list_routes("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF")) == 2
    assert topology.list_process_units("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_NG_DRP_EAF")
    assert topology.list_stores("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_NG_DRP_EAF")
    assert topology.list_arcs("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_NG_DRP_EAF")
    assert topology.list_carriers_in_scope()
    assert topology.source_like_nodes("C0_current_BF_BOF_reference")
    assert topology.sink_like_nodes("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF")

    for collection in (
        topology.configurations.values(),
        topology.routes.values(),
        topology.process_units.values(),
        topology.carriers.values(),
        topology.stores.values(),
        topology.arcs.values(),
        topology.inventory_policies.values(),
    ):
        for item in collection:
            assert item.executable_status == "non_executable"
            assert item.thesis_usability is False
            assert item.approval_status in {"structural_candidate", "scope_freeze_only", "not_approved", "blocked"}


def test_topology_object_builder_keeps_structural_surface_only():
    topology_bundle = load_topology_skeleton(REVIEW_ROOT)
    topology = build_steel_topology(topology_bundle, validate=True)
    module_source = inspect.getsource(sys.modules["steel.topology_objects"]).lower()

    assert "pyomo" not in module_source
    banned_field_tokens = {"capacity", "yield", "coefficient", "cost", "emission", "tariff", "bid_quantity", "objective_value"}
    object_text = " ".join(
        str(value).lower()
        for collection in (
            topology.configurations.values(),
            topology.routes.values(),
            topology.process_units.values(),
            topology.carriers.values(),
            topology.stores.values(),
            topology.arcs.values(),
            topology.inventory_policies.values(),
        )
        for item in collection
        for value in item.__dict__.values()
    )
    assert not any(token in object_text for token in ("phase 2", "phase3", "full_hydrogen", "on_site_electrolysis", "mfrr", "cvar"))
    assert not any(token in module_source for token in banned_field_tokens)


def test_candidate_review_mode_is_non_thesis_usable():
    config = load_config(CANDIDATE_REVIEW_CONFIG_PATH)
    schema_bundle = load_s2_schema(SCHEMA_ROOT)
    mapping_bundle = load_s2_candidate_mapping(MAPPING_ROOT)
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = dry_run_validate_input_governance(
        config=config,
        schema_bundle=schema_bundle,
        mapping_bundle=mapping_bundle,
        review_bundle=review_bundle,
    )
    assert payload["input_mode"] == "candidate_review"
    assert payload["thesis_usable"] is False
    assert payload["schema_files_checked"] >= 10
    assert payload["mapping_files_checked"] == 4
    assert payload["candidate_review_files_checked"] == 19
    assert payload["approved_rows"] == 0
    assert payload["promotion_packet_rows_checked"] == 5
    assert payload["unit_sign_endpoint_note_present"] is True
    assert payload["deepsearch_f_source_rows_checked"] == 20
    assert payload["deepsearch_f_candidate_assumption_rows_checked"] > 0
    assert payload["configuration_rows_checked"] == 4
    assert payload["main_configuration_rows"] == 2
    assert payload["configuration_tag_mapping_rows_checked"] == 33
    assert payload["topology_skeleton_files_checked"] == 7
    assert payload["topology_configuration_rows_checked"] == 2
    assert payload["topology_route_rows_checked"] == 3
    assert payload["topology_process_unit_rows_checked"] == 17
    assert payload["topology_carrier_rows_checked"] == 11
    assert payload["topology_store_rows_checked"] == 7
    assert payload["topology_arc_rows_checked"] == 32
    assert payload["topology_inventory_policy_rows_checked"] == 4
    assert payload["topology_object_configuration_count"] == 2
    assert payload["topology_object_route_count"] == 3
    assert payload["topology_object_process_unit_count"] == 17
    assert payload["topology_object_carrier_count"] == 11
    assert payload["topology_object_store_count"] == 7
    assert payload["topology_object_arc_count"] == 32
    assert payload["topology_object_inventory_policy_count"] == 4
    assert payload["topology_object_warnings"] == []
    assert payload["thesis_grade_numerical_rows"] == 0
    assert payload["candidate_review_executable_rows"] == 0


def test_approved_model_input_mode_rejects_toy_rows(tmp_path: Path):
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["input_tables"]["input_mode"] = "approved_model_input"
    raw["input_tables"]["table_root"] = str(
        (TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_toy_scaffold").resolve()
    )
    config_path = tmp_path / "approved_mode_should_fail.yaml"
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="approved_model_input mode requires every executable row"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("config_path", "expected_class"),
    [
        (IMPOSSIBLE_CONFIG_PATH, "capacity_bottleneck"),
        (TERMINAL_CONFIG_PATH, "terminal_inventory_violation"),
        (FEED_CONFIG_PATH, "feed_shortage"),
    ],
)
def test_infeasible_smoke_cases_are_classified(tmp_path: Path, config_path: Path, expected_class: str):
    config = load_config(config_path)
    try:
        choose_solver(config)
    except RuntimeError:
        pytest.skip("No LP solver available for the steel S2.2 smoke tests.")

    result = run_from_config(
        config_path,
        output_root_override=tmp_path,
        run_id_override=f"pytest_{expected_class}",
    )
    run_dir = Path(result["run_dir"])
    assert result["infeasibility_class"] == expected_class
    assert (run_dir / "infeasibility_summary.json").exists()
    validation_csv = (run_dir / "validation_summary.csv").read_text(encoding="utf-8")
    assert "thesis_usable" in validation_csv
    assert "no_forbidden_stage_features_active" in validation_csv
