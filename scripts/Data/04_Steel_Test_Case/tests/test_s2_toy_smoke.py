from __future__ import annotations

import json
from pathlib import Path
import sys

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
    validate_s2_candidate_review,
)
from steel.input_tables import load_governed_toy_tables
from steel.model import build_model, choose_solver
from steel.runner import run_from_config


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
    assert payload["candidate_review_files_checked"] == 13
    assert payload["approved_rows"] == 0
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
