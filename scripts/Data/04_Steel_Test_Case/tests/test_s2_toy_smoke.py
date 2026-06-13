from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from pyomo.environ import Var

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.config import load_config
from steel.input_tables import load_governed_toy_tables
from steel.model import build_model, choose_solver
from steel.runner import run_from_config


CONFIG_PATH = TEST_CASE_ROOT / "configs" / "base_s2_toy_smoke.yaml"
IMPOSSIBLE_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "impossible_production_target.yaml"
TERMINAL_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "terminal_inventory_infeasible.yaml"
FEED_CONFIG_PATH = TEST_CASE_ROOT / "configs" / "route_feed_shortage_or_buffer_bottleneck.yaml"


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

    validation_csv = (run_dir / "validation_summary.csv").read_text(encoding="utf-8")
    assert "production_target_met" in validation_csv
    assert "thesis_usable" in validation_csv


def test_governed_toy_tables_have_required_metadata():
    config = load_config(CONFIG_PATH)
    assert config.input_tables is not None
    bundle = load_governed_toy_tables(config.input_tables.table_root, config.input_tables.scenario_or_config)
    assert bundle.row_counts["carriers"] > 0
    for table_name, frame in bundle.tables.items():
        assert "source_status" in frame.columns
        assert "approval_status" in frame.columns
        assert frame["approval_status"].eq("not_approved").all(), table_name


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
