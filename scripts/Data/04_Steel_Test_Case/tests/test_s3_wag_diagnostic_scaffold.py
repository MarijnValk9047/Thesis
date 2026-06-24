from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_diagnostic import (  # noqa: E402
    WAGDiagnosticError,
    allocate_process_first,
    assess_wag_readiness,
    calculate_bfg_generation,
    calculate_bofg_generation,
    calculate_cog_generation,
    calculate_point_of_oxidation_emissions,
)
from steel.wag_diagnostic_inputs import (  # noqa: E402
    DEFAULT_SELECTED_WAG_INPUT_PATH,
    WAGInputError,
    load_fixed_activity_profile,
    load_selected_wag_inputs,
)


SELECTION_REVIEW_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_candidate_review"
    / "s3_wag_dev_input_selection_review.csv"
)
RUNNER_PATH = TEST_CASE_ROOT / "steel" / "wag_diagnostic_runner.py"


def _copy_selected_inputs(tmp_path: Path) -> Path:
    target = tmp_path / "s3_wag_selected_dev_inputs.csv"
    shutil.copyfile(DEFAULT_SELECTED_WAG_INPUT_PATH, target)
    return target


def _mutate_selected_input(tmp_path: Path, column: str, value: str, row_index: int = 0) -> Path:
    path = _copy_selected_inputs(tmp_path)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.loc[row_index, column] = value
    frame.to_csv(path, index=False)
    return path


def _profile_frame(source_artifact_path: str = "data/03_Optimisation/inputs/assets/steel/S3/synthetic_fixture.csv") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "profile_package_id": "fixture_profile",
                "profile_row_id": "row_001",
                "configuration_id": "C0",
                "scenario_label": "synthetic_unit_test",
                "time_index": "0",
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "timestep_hours": "1",
                "s2_activity_id": "BF",
                "s2_activity_type": "bf_hot_metal_activity",
                "activity_value": "10",
                "activity_unit": "t_per_hour",
                "activity_direction": "production",
                "source_stage": "unit_test_fixture",
                "source_artifact_id": "fixture",
                "source_artifact_path": source_artifact_path,
                "source_artifact_hash": "sha256:test",
                "profile_extraction_method": "synthetic_test_fixture",
                "review_status": "development_fixture_only",
                "thesis_usability": "false",
                "notes": "",
            }
        ]
    )


def test_selected_loader_accepts_governed_packet_and_rejects_review_surface():
    selected = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    assert len(selected) == 22
    assert all(item.input_id.startswith("S30B_WAG_DEV_") for item in selected.values())
    with pytest.raises(WAGInputError, match="selected"):
        load_selected_wag_inputs(SELECTION_REVIEW_PATH)


@pytest.mark.parametrize(
    ("column", "value", "match"),
    [
        ("thesis_usability", "true", "thesis-usable"),
        ("approval_status", "approved_model_input", "approval_status"),
        ("source_card_ids", "STEEL-SC-0019", "STEEL-SC-0019"),
        ("unit", "", "no unit"),
        ("selected_value", "", "no selected_value"),
    ],
)
def test_selected_loader_rejects_invalid_rows(tmp_path: Path, column: str, value: str, match: str):
    path = _mutate_selected_input(tmp_path, column, value)
    with pytest.raises(WAGInputError, match=match):
        load_selected_wag_inputs(path)


def test_selected_loader_rejects_duplicate_effective_keys(tmp_path: Path):
    path = _copy_selected_inputs(tmp_path)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    duplicate_cols = ["configuration_id", "carrier", "linked_activity_or_node", "parameter_name"]
    frame.loc[1, duplicate_cols] = frame.loc[0, duplicate_cols]
    frame.to_csv(path, index=False)
    with pytest.raises(WAGInputError, match="Duplicate effective"):
        load_selected_wag_inputs(path)


def test_fixed_profile_loader_accepts_fixture_and_rejects_generated_runs(tmp_path: Path):
    valid_path = tmp_path / "fixed_profile.csv"
    _profile_frame().to_csv(valid_path, index=False)
    rows = load_fixed_activity_profile(valid_path)
    assert len(rows) == 1
    assert rows[0].timestamp_utc.tzinfo is not None

    run_path = tmp_path / "runs" / "fixed_profile.csv"
    run_path.parent.mkdir()
    _profile_frame().to_csv(run_path, index=False)
    with pytest.raises(WAGInputError, match="run folders"):
        load_fixed_activity_profile(run_path)

    artifact_run_path = tmp_path / "fixed_profile_runs_artifact.csv"
    _profile_frame("scripts/Data/04_Steel_Test_Case/runs/generated/profile.csv").to_csv(artifact_run_path, index=False)
    with pytest.raises(WAGInputError, match="run-folder"):
        load_fixed_activity_profile(artifact_run_path)


def test_bfg_and_bofg_generation_hand_calculations_and_basis_guard():
    bfg = calculate_bfg_generation(
        hot_metal_activity_value=10.0,
        activity_unit="t_per_hour",
        timestep_hours=2.0,
        generation_intensity_nm3_per_t_hot_metal=100.0,
        lhv_mj_per_nm3=3.0,
    )
    assert bfg.generated_volume == pytest.approx(2000.0)
    assert bfg.generated_energy_gj == pytest.approx(6.0)
    assert bfg.generated_energy_mwh_thermal == pytest.approx(6.0 / 3.6)

    bofg = calculate_bofg_generation(
        steel_activity_value=20.0,
        activity_unit="tonnes",
        timestep_hours=1.0,
        generation_intensity_nm3_per_t_steel=75.0,
        lhv_mj_per_nm3=8.0,
        activity_basis="per tonne liquid steel",
        coefficient_activity_basis="per tonne liquid steel",
    )
    assert bofg.generated_volume == pytest.approx(1500.0)
    assert bofg.generated_energy_gj == pytest.approx(12.0)

    with pytest.raises(WAGDiagnosticError, match="basis"):
        calculate_bofg_generation(
            steel_activity_value=20.0,
            activity_unit="tonnes",
            timestep_hours=1.0,
            generation_intensity_nm3_per_t_steel=75.0,
            lhv_mj_per_nm3=8.0,
            activity_basis="per tonne crude steel",
            coefficient_activity_basis="per tonne liquid steel",
        )


def test_cog_chain_calculates_when_complete_and_blocks_missing_inputs():
    result = calculate_cog_generation(
        hot_metal_activity_tonnes=100.0,
        coke_rate_per_t_hot_metal=0.5,
        onsite_coking_share=0.8,
        dry_coal_t_per_t_coke=1.2,
        cog_yield_m3_per_t_dry_coal=300.0,
        cog_lhv_mj_per_m3=18.0,
        mandatory_cog_self_use_fraction=0.25,
    )
    assert result.blocked is False
    assert result.gross_cog_volume_m3 == pytest.approx(14400.0)
    assert result.gross_cog_energy_gj == pytest.approx(259.2)
    assert result.allocatable_cog_energy_gj == pytest.approx(194.4)

    missing_coke_rate = calculate_cog_generation(
        hot_metal_activity_tonnes=100.0,
        coke_rate_per_t_hot_metal=None,
        onsite_coking_share=0.8,
        dry_coal_t_per_t_coke=1.2,
        cog_yield_m3_per_t_dry_coal=300.0,
        cog_lhv_mj_per_m3=18.0,
        mandatory_cog_self_use_fraction=0.25,
    )
    assert missing_coke_rate.blocked is True
    assert "coke_rate_per_t_hot_metal" in missing_coke_rate.missing_inputs

    missing_share = calculate_cog_generation(
        hot_metal_activity_tonnes=100.0,
        coke_rate_per_t_hot_metal=0.5,
        onsite_coking_share=None,
        dry_coal_t_per_t_coke=1.2,
        cog_yield_m3_per_t_dry_coal=300.0,
        cog_lhv_mj_per_m3=18.0,
        mandatory_cog_self_use_fraction=0.25,
    )
    assert missing_share.blocked is True
    assert "onsite_coking_share" in missing_share.missing_inputs
    assert missing_share.gross_cog_energy_gj == 0.0


def test_process_first_allocation_balances_no_export_or_revenue():
    allocation = allocate_process_first(
        available_energy_gj_by_carrier={"BFG": 100.0, "COG": 50.0, "BOFG_LD_gas": 50.0},
        mandatory_process_demand_gj_by_carrier={"BFG": 20.0},
        steam_boiler_useful_demand_gj=45.0,
        boiler_efficiency=0.9,
        residual_site_electricity_demand_mwh=10.0,
        wag_to_power_efficiency=0.4,
        timestep_hours=1.0,
    )
    assert allocation.process_use_gj["BFG"] == pytest.approx(20.0)
    assert sum(allocation.boiler_use_gj.values()) == pytest.approx(50.0)
    assert allocation.potential_net_import_offset_mwh <= 10.0
    assert allocation.residual_grid_import_mwh >= 0.0
    assert all(abs(value) <= 1e-6 for value in allocation.balance_residual_gj.values())
    output_fields = set(asdict(allocation))
    assert "export" not in output_fields
    assert "revenue" not in output_fields


def test_point_of_oxidation_emissions_no_generation_count_and_partial_ets_block():
    allocation = allocate_process_first(
        available_energy_gj_by_carrier={"BFG": 10.0},
        mandatory_process_demand_gj_by_carrier={"BFG": 4.0},
        steam_boiler_useful_demand_gj=0.0,
        boiler_efficiency=0.9,
        residual_site_electricity_demand_mwh=1.0,
        wag_to_power_efficiency=0.5,
        timestep_hours=1.0,
    )
    emissions = calculate_point_of_oxidation_emissions(
        allocation=allocation,
        emission_factors_kg_per_gj={"BFG": 260.0},
        natural_gas_energy_gj=2.0,
        natural_gas_factor_kg_per_gj=56.0,
    )
    assert emissions.wag_co2_tonnes_by_carrier_sink["BFG"]["process_use"] == pytest.approx(1.04)
    assert "generation" not in emissions.wag_co2_tonnes_by_carrier_sink["BFG"]
    assert emissions.natural_gas_co2_tonnes == pytest.approx(0.112)
    assert emissions.direct_emissions_ledger_complete is False
    assert emissions.gross_ets_cost_eligible is False
    assert emissions.double_counting_validation_passed is True


def test_current_readiness_is_scaffold_only_with_explicit_blockers():
    selected = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    readiness = assess_wag_readiness(selected)
    assert readiness.implementation_ready is True
    assert readiness.runtime_ready is False
    assert readiness.bfg_generation_ready.ready is True
    assert readiness.bofg_generation_ready.ready is True
    assert readiness.cog_generation_ready.ready is True
    assert readiness.mandatory_process_use_ready.ready is False
    assert readiness.steam_boiler_allocation_ready.ready is False
    assert readiness.power_import_offset_ready.ready is False
    assert readiness.emissions_ready.ready is True
    assert "mandatory_process_use_profile" in readiness.mandatory_process_use_ready.missing_inputs
    assert "steam_boiler_useful_demand_profile" in readiness.steam_boiler_allocation_ready.missing_inputs
    assert "site_electricity_demand_profile" in readiness.power_import_offset_ready.missing_inputs


def test_runner_validation_only_succeeds_on_temp_selected_fixture(tmp_path: Path):
    selected_path = _copy_selected_inputs(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--validate-inputs-only",
            "--selected-input-path",
            str(selected_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert '"runtime_ready": false' in result.stdout


def test_wag_modules_do_not_hardcode_selected_coefficients():
    module_paths = [
        TEST_CASE_ROOT / "steel" / "wag_diagnostic.py",
        TEST_CASE_ROOT / "steel" / "wag_diagnostic_inputs.py",
        TEST_CASE_ROOT / "steel" / "wag_diagnostic_runner.py",
        TEST_CASE_ROOT / "steel" / "wag_fixed_profile_builder.py",
    ]
    selected_values = {"1600", "37.15", "260.0", "56.1", "1500000", "479.2", "3.55"}
    combined = "\n".join(path.read_text(encoding="utf-8") for path in module_paths)
    for value in selected_values:
        assert value not in combined
