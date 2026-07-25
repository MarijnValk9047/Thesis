import csv
import hashlib
import math
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = (
    ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract"
)
ANCHOR_PATH = CONTRACT_ROOT / "user_authorized_emulation_anchor_overlay.csv"
PARAMETER_PATH = CONTRACT_ROOT / "user_authorized_emulation_parameter_overlay.csv"
STRICT_TARGET_PATH = CONTRACT_ROOT / "calibration_validation_target_contract.csv"
STRICT_PARAMETER_PATH = CONTRACT_ROOT / "calibratable_parameter_contract.csv"
CONFIG_PATH = (
    ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c5_user_authorized_full_site_emulation.yaml"
)

ANCHOR_FIELDS = {
    "overlay_id",
    "configuration",
    "metric",
    "target_role",
    "value_low",
    "value_central",
    "value_high",
    "unit",
    "time_basis",
    "comparison_basis",
    "accepted_interpretation",
    "tolerance_rule",
    "implementation_ledger",
    "calibration_stage",
    "user_authorised_provenance",
    "source_locator",
    "arithmetic_caveat",
}
PARAMETER_FIELDS = {
    "parameter_id",
    "parameter_family",
    "configuration",
    "baseline_central",
    "baseline_low",
    "baseline_high",
    "first_relaxed_low",
    "first_relaxed_high",
    "allowed_values",
    "unit",
    "stage",
    "may_move",
    "physical_hard_bound",
    "affected_targets",
    "affected_processes",
    "selection_rule",
    "source_locator",
    "caveat",
}
STRICT_SHA256 = {
    STRICT_TARGET_PATH: "55b828d4fe59915ffb00d86b44158aec4121f77e8f9848218c63f6d1f4cf795e",
    STRICT_PARAMETER_PATH: "968e207d4fd6166a60e782eed913e3d646d03e79c969f417a17d6ec79067bdf8",
}


def _rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _by_id(path, id_field):
    return {row[id_field]: row for row in _rows(path)}


def _float(row, field):
    return float(row[field])


def test_real_anchor_repair_extends_overlay_and_preserves_remaining_five_percent_targets():
    rows = _rows(ANCHOR_PATH)
    assert len(rows) == 28
    assert set(rows[0]) == ANCHOR_FIELDS
    assert len({row["overlay_id"] for row in rows}) == 28
    assert {row["user_authorised_provenance"] for row in rows} == {
        "user_authorized_goal_objective_20260722",
        "user_authorized_real_anchor_repair_20260723",
    }
    assert all(all(row[field].strip() for field in ANCHOR_FIELDS) for row in rows)

    by_id = {row["overlay_id"]: row for row in rows}
    five_percent = {
        "uae_c1_gross_site_electricity": 4.89,
        "uae_c1_wag_generator_electricity": 1.23,
        "uae_c1_ng_hourly": 151673.52,
        "uae_c1_first_order_co2": 9.107793,
    }
    for overlay_id, central in five_percent.items():
        row = by_id[overlay_id]
        assert _float(row, "value_central") == central
        assert math.isclose(_float(row, "value_low"), central * 0.95)
        assert math.isclose(_float(row, "value_high"), central * 1.05)
        assert row["tolerance_rule"] == "within_5_percent"

    expected_bands = {
        "uae_c0_wag_generator_electricity": (2.528, 2.528, 2.528),
        "uae_c0_figure91_wag_band": (2.74, 2.74, 2.773),
        "uae_c0_figure91_ng_band": (270.0, 270.0, 270.0),
        "uae_c0_first_order_co2": (12.24, 12.24, 12.24),
        "uae_c0_figure91_coal_band": (3.66, 3.66, 3.66),
        "uae_bad_fig69_dri_correlation": (0.159, None, 0.412),
    }
    for overlay_id, (low, central, high) in expected_bands.items():
        row = by_id[overlay_id]
        assert _float(row, "value_low") == low
        if central is not None:
            assert _float(row, "value_central") == central
        assert _float(row, "value_high") == high

    assert by_id["uae_c0_wag_generator_electricity"]["target_role"] == "primary_real_anchor"
    assert by_id["real_anchor_c0_normal_case_flexible_ng_reference"]["target_role"] == "validation_reference"


def test_background_arithmetic_and_accounting_definitions_are_distinct():
    by_id = _by_id(ANCHOR_PATH, "overlay_id")
    for configuration, gross in (("c0", 3.17), ("c1", 4.89)):
        for percentage in (5, 15, 25):
            row = by_id[f"uae_{configuration}_background_{percentage:02d}"]
            expected = gross * percentage / 100.0
            assert math.isclose(_float(row, "value_low"), expected)
            assert math.isclose(_float(row, "value_central"), expected)
            assert math.isclose(_float(row, "value_high"), expected)
            assert row["implementation_ledger"] == "explicit_background_electricity"
            assert row["tolerance_rule"] == "exact_discrete_case"

    wag_rows = [
        row for row in by_id.values() if row["metric"] == "wag_only_generator_electricity"
    ]
    assert len(wag_rows) == 3
    assert {row["implementation_ledger"] for row in wag_rows} == {
        "wag_only_generator_electricity",
        "WAG_generator_electricity_mwh",
    }
    primary_wag = [row for row in wag_rows if row["target_role"] == "primary_calibration_target"]
    assert len(primary_wag) == 1
    assert all("excludes NG-generated electricity" in row["accepted_interpretation"] for row in primary_wag)
    assert all("direct process WAG use" in row["accepted_interpretation"] for row in primary_wag)

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounting"]["ng_generator_electricity_separate"] is True
    assert config["accounting"]["wag_generator_electricity_definition"] == (
        "gross_BFG_COG_BOFG_generator_output_only"
    )
    assert config["background_electricity"] == {
        "five_percent_case_mwh_h_by_configuration": {
            "C0_current_BF_BOF_reference": 18.0936073059,
            "C1_phase1_BF_BOF_plus_DRP_EAF": 27.9109589041,
        },
        "separate_from": [
            "residual_electricity",
            "represented_auxiliary_electricity",
            "linde_n2_auxiliary_load",
        ],
        "additive_to_existing_represented_auxiliaries": True,
        "may_replace_residual_electricity": False,
        "may_replace_represented_auxiliary_electricity": False,
        "may_replace_linde_n2_auxiliary_load": False,
    }
    background_parameter = _by_id(PARAMETER_PATH, "parameter_id")[
        "uae_background_electricity_share"
    ]
    assert "never a replacement for residual electricity" in background_parameter[
        "selection_rule"
    ]
    assert "Linde N2" in background_parameter["selection_rule"]


def test_gross_site_electricity_import_export_algebra_subtracts_export_once():
    exact_identity = (
        "gross_site_electricity = WAG_generator + NG_generator + "
        "gross_grid_import - gross_grid_export"
    )
    net_identity = "net_grid_exchange = gross_grid_import - gross_grid_export"
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    accounting = config["accounting"]
    assert accounting["gross_site_electricity_identity"] == exact_identity
    assert accounting["net_grid_exchange_identity"] == net_identity
    assert accounting["gross_site_electricity_via_net_exchange"] == (
        "gross_site_electricity = WAG_generator + NG_generator + net_grid_exchange"
    )
    assert accounting["gross_grid_export_subtraction_count"] == 1

    gross_rows = [
        row
        for row in _rows(ANCHOR_PATH)
        if row["metric"] == "gross_site_electricity"
    ]
    assert len(gross_rows) == 2
    for row in gross_rows:
        assert exact_identity in row["accepted_interpretation"]
        assert net_identity in row["accepted_interpretation"]
        assert "subtracted exactly once" in row["accepted_interpretation"]

    wag_generator = 2.0
    ng_generator = 0.5
    gross_grid_import = 1.25
    gross_grid_export = 0.25
    net_grid_exchange = gross_grid_import - gross_grid_export
    direct = wag_generator + ng_generator + gross_grid_import - gross_grid_export
    via_net = wag_generator + ng_generator + net_grid_exchange
    double_subtracted = via_net - gross_grid_export
    assert direct == via_net == 3.5
    assert double_subtracted == 3.25
    assert double_subtracted != direct


def test_ng_hourly_annual_caveat_and_co2_ledger_separation():
    by_id = _by_id(ANCHOR_PATH, "overlay_id")
    c0_hourly = by_id["uae_c0_ng_hourly"]
    c0_annual = by_id["uae_c0_figure91_ng_band"]
    assert c0_hourly["target_role"] == "secondary_directional_model_context"
    assert _float(c0_annual, "value_central") == 270.0
    assert c0_annual["target_role"] == "primary_real_anchor"

    co2_rows = [
        row for row in by_id.values() if row["metric"] == "first_order_full_site_co2"
    ]
    assert len(co2_rows) == 2
    assert {row["implementation_ledger"] for row in co2_rows} == {
        "first_order_full_site_co2"
    }
    assert all(
        "separate from physically explicit" in row["arithmetic_caveat"]
        or "separate from physically explicit" in row["accepted_interpretation"]
        for row in co2_rows
    )
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["accounting"]["co2_ledgers_must_not_be_summed"] is True
    assert config["accounting"]["physical_co2_ledger"] == (
        "existing_explicit_fuel_and_oxidation"
    )


def test_parameter_overlay_ranges_stages_and_sensitivity_labels():
    rows = _rows(PARAMETER_PATH)
    assert len(rows) == 23
    assert set(rows[0]) == PARAMETER_FIELDS
    assert len({row["parameter_id"] for row in rows}) == len(rows)
    assert {row["stage"] for row in rows} == {
        "analytical", "rolling", "reporting", "checkpoint_1_2", "validation"
    }
    assert {row["may_move"] for row in rows} == {"true", "false"}
    assert all(row["physical_hard_bound"].strip() for row in rows)
    assert all(row["affected_processes"].strip() for row in rows)
    assert all(row["selection_rule"].strip() for row in rows)

    by_id = {row["parameter_id"]: row for row in rows}
    endpoint_exemptions = {
        "uae_background_electricity_share",
        "uae_c0_first_order_co2_constant",
        "uae_c1_first_order_co2_constant",
    }
    assert set(by_id) - endpoint_exemptions
    for parameter_id, row in by_id.items():
        if parameter_id in endpoint_exemptions:
            continue
        if row["may_move"] == "false":
            continue
        baseline_low = _float(row, "baseline_low")
        baseline_high = _float(row, "baseline_high")
        relaxed_low = _float(row, "first_relaxed_low")
        relaxed_high = _float(row, "first_relaxed_high")
        assert relaxed_low <= baseline_low
        assert relaxed_high >= baseline_high
        assert _float(row, "first_relaxed_low") >= baseline_low * 0.75 - 1e-9
        assert _float(row, "first_relaxed_high") <= baseline_high * 1.25 + 1e-9
        assert "user_authorized_sensitivity" in row["caveat"]

    background = by_id["uae_background_electricity_share"]
    assert background["allowed_values"] == "0.05;0.15;0.25"
    assert _float(background, "first_relaxed_low") == 0.05
    assert _float(background, "first_relaxed_high") == 0.25
    assert "discrete share" in background["selection_rule"]

    eaf = by_id["uae_c1_eaf_liquid_steel_share"]
    assert eaf["stage"] == "rolling"
    assert "endogenous within existing capacity" in eaf["caveat"]
    for parameter_id in (
        "uae_c0_kgf1_band_review",
        "uae_c0_kgf2_band_review",
        "uae_c1_kgf1_band_review",
        "uae_c0_pefa_band_review",
        "uae_c1_pefa_band_review",
    ):
        assert by_id[parameter_id]["stage"] == "rolling"
        assert "Rolling-only" in by_id[parameter_id]["caveat"]
    for parameter_id in (
        "uae_c0_first_order_co2_constant",
        "uae_c1_first_order_co2_constant",
    ):
        assert by_id[parameter_id]["stage"] == "reporting"
        assert "exempt from the 25-percent endpoint extension rule" in by_id[
            parameter_id
        ]["selection_rule"]
        assert "never modify or combine" in by_id[parameter_id]["caveat"]
        assert by_id[parameter_id]["physical_hard_bound"] == (
            "0<=constant<=configured_target_minus_selected_factor_subtotal"
        )
        assert "standalone envelope only" in by_id[parameter_id]["caveat"]

    electricity_scaler = by_id[
        "uae_named_process_electricity_intensity_scaling"
    ]
    assert electricity_scaler["affected_processes"].split(";") == [
        "DRP", "EAF_arc", "HSM_rolling", "DSP", "ASU_oxygen",
        "KGF_purchased_service", "BOF_OSF", "BF", "PeFa", "sinter",
        "EAF_secondary_metallurgy",
    ]
    assert "exactly one recorded named process" in electricity_scaler["selection_rule"]
    for forbidden in ("background", "residual", "Linde N2", "multiple unrelated"):
        assert forbidden in electricity_scaler["selection_rule"]

    ng_scaler = by_id["uae_named_process_ng_requirement_scaling"]
    assert ng_scaler["affected_processes"] == "HSM;PeFa;boiler"
    assert "exactly one recorded HSM PeFa or boiler" in ng_scaler["selection_rule"]
    assert "never uniformly scale unrelated NG loads" in ng_scaler["selection_rule"]
    assert by_id["uae_coal_coking_input_scaling"]["affected_processes"] == "KGF1;KGF2"


def test_parameter_overlay_numeric_physical_bounds():
    by_id = _by_id(PARAMETER_PATH, "parameter_id")
    for parameter_id in (
        "uae_bfg_generation_yield",
        "uae_cog_generation_yield",
        "uae_bofg_generation_yield",
    ):
        assert _float(by_id[parameter_id], "first_relaxed_low") > 0
        assert _float(by_id[parameter_id], "first_relaxed_high") > 0

    for parameter_id in (
        "uae_c0_generator_efficiency",
        "uae_vn25_generator_efficiency",
    ):
        low = _float(by_id[parameter_id], "first_relaxed_low")
        high = _float(by_id[parameter_id], "first_relaxed_high")
        assert 0 < low <= high < 1

    eaf = by_id["uae_c1_eaf_liquid_steel_share"]
    assert 0 <= _float(eaf, "first_relaxed_low")
    assert _float(eaf, "first_relaxed_high") <= 1
    background = by_id["uae_background_electricity_share"]
    background_values = [float(value) for value in background["allowed_values"].split(";")]
    assert background_values == [0.05, 0.15, 0.25]
    assert all(0 < value <= 0.25 for value in background_values)

    for parameter_id in (
        "uae_c0_kgf1_band_review",
        "uae_c0_kgf2_band_review",
        "uae_c1_kgf1_band_review",
        "uae_c0_pefa_band_review",
        "uae_c1_pefa_band_review",
    ):
        row = by_id[parameter_id]
        assert _float(row, "first_relaxed_low") > 0
        assert _float(row, "first_relaxed_high") > 0

    for parameter_id in (
        "uae_named_process_electricity_intensity_scaling",
        "uae_named_process_ng_requirement_scaling",
        "uae_coal_coking_input_scaling",
    ):
        row = by_id[parameter_id]
        assert _float(row, "first_relaxed_low") > 0
        assert _float(row, "first_relaxed_high") > 0

    co2_caps = {
        "uae_c0_first_order_co2_constant": 13.365216,
        "uae_c1_first_order_co2_constant": 9.56318265,
    }
    for parameter_id, cap in co2_caps.items():
        row = by_id[parameter_id]
        assert _float(row, "first_relaxed_low") == 0
        assert _float(row, "first_relaxed_high") == cap


def test_design_limits_no_execution_and_strict_contracts_untouched():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    design = config["design"]
    shares = design["background_electricity_shares"]
    recipes = design["perturbation_recipes"]
    structured_count = len(shares) * len(recipes)
    assert structured_count == config["design"]["structured_candidate_count"] == 27
    assert config["design"]["total_design_row_count"] == structured_count + 1 == 28
    assert config["design"]["maximum_candidates"] <= 30
    assert config["design"]["maximum_retained_candidates"] <= 5
    assert config["design"]["source_baseline"]["immutable"] is True
    assert shares == [0.05, 0.15, 0.25]
    assert len(recipes) == 9
    assert len({recipe["recipe_id"] for recipe in recipes}) == 9
    assert {recipe["recipe_id"] for recipe in recipes} == {
        "central_no_movement",
        "bfg_yield_low",
        "bfg_yield_high",
        "cog_yield_low",
        "cog_yield_high",
        "bofg_yield_low",
        "bofg_yield_high",
        "single_process_electricity_low",
        "single_process_electricity_high",
    }
    assert [recipe for recipe in recipes if recipe["parameter_family"] == "none"] == [
        {
            "recipe_id": "central_no_movement",
            "parameter_family": "none",
            "direction": "central",
        }
    ]
    carrier_families = {"BFG_yield", "COG_yield", "BOFG_yield"}
    assert {
        recipe["parameter_family"]
        for recipe in recipes
        if recipe["parameter_family"] in carrier_families
    } == carrier_families
    assert all(
        recipe["parameter_family"] in carrier_families
        or recipe["parameter_family"] in {"none", "named_process_electricity_intensity"}
        for recipe in recipes
    )
    assert design["recipe_policy"] == {
        "one_family_at_a_time": True,
        "carrier_yields_never_co_move": True,
        "named_process_selection_required": True,
        "selected_process_recorded_per_candidate": True,
    }
    assert "structured_axes" not in design
    assert "wag_yield_range_position" not in design
    assert config["execution"] == {
        "enabled": True,
        "analytical_prescreen_enabled": True,
        "solver_runs_enabled": False,
        "calibration_candidates_run": True,
        "unsupported_code_execution_enabled": False,
        "execution_scope": "analytical_annual_ledger_projection_only",
        "next_checkpoint_required": "checkpoint_4_independent_review",
    }
    assert config["mode"] == "user_authorized_full_site_emulation_prescreen"
    assert config["checkpoint_id"] == "checkpoint_3_bounded_analytical_annual_prescreen"
    assert config["prescreen"]["score_families_kept_separate"] is True
    assert config["claims"]["exact_digital_twin"] is False
    assert config["claims"]["tata_questionnaire_separate"] is True

    for path, expected_sha256 in STRICT_SHA256.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
    strict_parameters = _rows(STRICT_PARAMETER_PATH)
    assert {row["may_move"] for row in strict_parameters} == {"false"}
    assert ANCHOR_PATH != STRICT_TARGET_PATH
    assert PARAMETER_PATH != STRICT_PARAMETER_PATH
