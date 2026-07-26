import csv
import hashlib
import math
from pathlib import Path

import pytest
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
V6_ROOT = (
    ROOT
    / "data/03_Optimisation/runs/"
    "steel_c5_wag_ng_allocation_envelope_v6_20260726"
)
V6_COVERAGE_PATH = V6_ROOT / "anchor_coverage.csv"

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
    assert len(rows) == 42
    assert set(rows[0]) == ANCHOR_FIELDS
    assert len({row["overlay_id"] for row in rows}) == 42
    assert {row["user_authorised_provenance"] for row in rows} == {
        "user_authorized_goal_objective_20260722",
        "user_authorized_real_anchor_repair_20260723",
        "user_authorized_phase1_boundary_freeze_20260726",
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
        "uae_c0_figure91_wag_band": (2.74, 2.74, 2.74),
        "uae_c0_figure91_ng_band": (9.666, 9.666, 9.666),
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
            assert row["target_role"] == (
                "historical_analytical_screen_case_superseded"
            )
            assert row["tolerance_rule"] == "historical_provenance_only"

    wag_rows = [
        row for row in by_id.values() if row["metric"] == "wag_only_generator_electricity"
    ]
    assert len(wag_rows) == 4
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
        and row["comparison_basis"] == "full_site_gross_consumption"
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
    assert c0_hourly["target_role"] == (
        "historical_source_volume_superseded_by_phase1_lhv_calendar_convention"
    )
    assert _float(c0_annual, "value_central") == 9.666
    assert c0_annual["target_role"] == "primary_real_anchor"
    assert c0_annual["unit"] == "PJ_LHV/y"
    assert c0_annual["time_basis"] == "annual_calendar"

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


def test_phase1_background_classes_supersede_but_preserve_historical_screen():
    rows = _rows(ANCHOR_PATH)
    historical = [
        row
        for row in rows
        if row["target_role"] == "historical_analytical_screen_case_superseded"
    ]
    assert len(historical) == 6
    assert {row["calibration_stage"] for row in historical} == {
        "historical_provenance"
    }
    active = {
        row["overlay_id"]: row
        for row in rows
        if row["metric"] == "explicit_background_electricity_share"
        and row["calibration_stage"] == "boundary_freeze"
    }
    assert {
        overlay_id: _float(row, "value_central")
        for overlay_id, row in active.items()
    } == {
        "phase1_c0_background_low": 0.25,
        "phase1_c0_background_central": 0.30,
        "phase1_c0_background_high": 0.31,
        "phase1_c0_background_excluded": 0.375,
    }
    assert active["phase1_c0_background_excluded"]["value_low"] == "0.35"
    assert active["phase1_c0_background_excluded"]["value_high"] == "0.40"
    assert active["phase1_c0_background_excluded"]["tolerance_rule"] == (
        "hard_exclusion"
    )
    assert "new Tata evidence" in active[
        "phase1_c0_background_excluded"
    ]["accepted_interpretation"]
    assert not any(
        row["target_role"] == "explicit_background_case" for row in rows
    )


def test_phase1_primary_and_context_anchor_hierarchy_is_explicit():
    by_id = _by_id(ANCHOR_PATH, "overlay_id")
    gross = by_id["uae_c0_gross_site_electricity"]
    assert gross["target_role"] == "primary_real_anchor"
    assert (_float(gross, "value_low"), _float(gross, "value_high")) == (
        3.154,
        3.170,
    )
    assert _float(gross, "value_central") == 3.162
    assert "authoritative accepted values" in gross["accepted_interpretation"]
    assert "arithmetic midpoint" in gross["accepted_interpretation"]
    assert "not an independently accepted anchor" in gross[
        "accepted_interpretation"
    ]
    assert "calibration target or precedence value" in gross[
        "accepted_interpretation"
    ]
    assert "low/high band has authority" in gross["arithmetic_caveat"]
    gross_context = by_id["phase1_c0_gross_electricity_table8_context"]
    assert gross_context["target_role"] == "supporting_model_context_table8"
    assert _float(gross_context, "value_central") == 3.17

    wag_primary = by_id["uae_c0_wag_generator_electricity"]
    assert wag_primary["target_role"] == "primary_real_anchor"
    assert _float(wag_primary, "value_central") == 2.528
    assert wag_primary["implementation_ledger"] == "WAG_generator_electricity_mwh"
    assert "excludes NG-generated electricity" in wag_primary[
        "accepted_interpretation"
    ]
    wag_context = {
        "uae_c0_figure91_wag_band": (2.74, "supporting_model_context_table8"),
        "phase1_c0_wag_generator_electricity_figure91_context": (
            2.773,
            "supporting_model_context_figure91",
        ),
    }
    for overlay_id, (value, role) in wag_context.items():
        assert _float(by_id[overlay_id], "value_central") == value
        assert by_id[overlay_id]["target_role"] == role
        assert "NG-generated electricity" in by_id[overlay_id][
            "accepted_interpretation"
        ]


def test_phase1_ng_uses_one_lhv_calendar_convention_without_plug():
    by_id = _by_id(ANCHOR_PATH, "overlay_id")
    active_ng_ids = (
        "real_anchor_c0_inferred_low_case_ng_floor",
        "phase1_c0_flexible_heat_ng_allocation_envelope",
        "uae_c0_figure91_ng_band",
        "phase1_c0_ng_figure91_context",
        "phase1_c0_ng_table8_context",
    )
    for overlay_id in active_ng_ids:
        row = by_id[overlay_id]
        assert row["unit"] == "PJ_LHV/y"
        assert row["time_basis"] == "annual_calendar"
        combined = " ".join(
            (row["accepted_interpretation"], row["arithmetic_caveat"])
        ).lower()
        assert row["target_role"] not in {"residual", "plug", "calibration_plug"}
        if "residual" in combined or "plug" in combined:
            assert "no" in combined or "not a residual" in combined
    assert _float(
        by_id["real_anchor_c0_inferred_low_case_ng_floor"], "value_central"
    ) == 8.005
    assert (
        _float(by_id["uae_c0_figure91_ng_band"], "value_central") == 9.666
    )
    assert _float(
        by_id["phase1_c0_ng_figure91_context"], "value_central"
    ) == 10.35
    assert _float(by_id["phase1_c0_ng_table8_context"], "value_central") == 10.425
    allocation = by_id["phase1_c0_flexible_heat_ng_allocation_envelope"]
    assert allocation["value_low"] == "0"
    assert allocation["value_central"] == "not_prescribed"
    assert allocation["value_high"] == "3.07"
    service = by_id["real_anchor_c0_flexible_heat_service_envelope"]
    assert service["comparison_basis"] == "WAG_plus_NG_energy_service"
    assert service["implementation_ledger"] == (
        "flexible_other_site_heat_service_envelope_mwh"
    )
    assert "not an NG dispatch target" in service["arithmetic_caveat"]
    assert by_id["uae_c0_ng_hourly"]["target_role"] == (
        "historical_source_volume_superseded_by_phase1_lhv_calendar_convention"
    )


def test_phase1_total_wag_co2_bridge_and_yield_freeze():
    anchors = _by_id(ANCHOR_PATH, "overlay_id")
    current_wag = anchors["phase1_c0_total_wag_current"]
    assert (_float(current_wag, "value_low"), _float(current_wag, "value_high")) == (
        57.3,
        57.5,
    )
    assert _float(
        anchors["phase1_c0_total_wag_mer_tata_context"], "value_central"
    ) == 54.0
    assert "approximately 6 percent" in current_wag["arithmetic_caveat"].lower()

    bridge = anchors["phase1_c0_co2_site_boundary_bridge"]
    assert (_float(bridge, "value_low"), _float(bridge, "value_high")) == (
        1.7,
        2.0,
    )
    assert bridge["target_role"] == "reporting_sensitivity"
    forbidden = " ".join(
        (bridge["accepted_interpretation"], bridge["arithmetic_caveat"])
    )
    for term in ("dispatch", "optimization", "procurement cost", "marginal"):
        assert term in forbidden
    assert _float(anchors["uae_c0_first_order_co2"], "value_central") == 12.24

    parameters = _by_id(PARAMETER_PATH, "parameter_id")
    unchanged_yields = {
        "uae_bfg_generation_yield": (1600.0, 1200.0, 2000.0, 900.0, 2500.0),
        "uae_cog_generation_yield": (365.0, 280.0, 450.0, 210.0, 562.5),
        "uae_bofg_generation_yield": (75.0, 50.0, 100.0, 37.5, 125.0),
    }
    for parameter_id, expected in unchanged_yields.items():
        row = parameters[parameter_id]
        assert tuple(
            _float(row, field)
            for field in (
                "baseline_central",
                "baseline_low",
                "baseline_high",
                "first_relaxed_low",
                "first_relaxed_high",
            )
        ) == expected
        assert row["may_move"] == "false"
        assert "no WAG-yield calibration is authorized" in row["caveat"]


def test_phase1_tolerance_and_v6_boundary_finding_are_not_calibration():
    by_id = _by_id(ANCHOR_PATH, "overlay_id")
    policy = by_id["phase1_anchor_tolerance_policy"]
    assert policy["value_low"] == "within_5_percent"
    assert policy["value_central"] == (
        "5_to_10_percent_if_physically_and_methodologically_credible"
    )
    assert policy["value_high"] == (
        "above_10_percent_requires_explicit_boundary_or_configuration_explanation"
    )
    assert "materially worsening several others" in policy[
        "accepted_interpretation"
    ]
    finding = by_id["phase1_c0_wag_envelope_v6_finding"]
    assert finding["target_role"] == "development_boundary_finding"
    assert finding["value_central"] == "above_maximum_all_four_cases"
    assert "steel_c5_wag_ng_allocation_envelope_v6_20260726" in finding[
        "source_locator"
    ]
    assert "no candidate is promoted" in finding["accepted_interpretation"]
    assert "not calibration" in finding["arithmetic_caveat"]


@pytest.mark.skipif(
    not V6_COVERAGE_PATH.is_file(),
    reason="governed ignored v6 local evidence is absent in a clean clone",
)
def test_local_v6_certified_coverage_evidence_matches_frozen_classification():
    coverage = _rows(V6_COVERAGE_PATH)
    expected = {
        ("recovery_bg30_ng55", "calm_price_insensitive"): (
            2229430.707022833,
            298569.292977167,
        ),
        ("recovery_bg30_ng55", "volatile_negative_governed_y_pred"): (
            1935250.6946325423,
            592749.3053674577,
        ),
        ("recovery_bg30_ng30", "calm_price_insensitive"): (
            2230098.7855618005,
            297901.2144381995,
        ),
        ("recovery_bg30_ng30", "volatile_negative_governed_y_pred"): (
            2056504.6139837499,
            471495.3860162501,
        ),
    }
    assert len(coverage) == 4
    for row in coverage:
        outer, gap = expected[(row["candidate_id"], row["scenario_id"])]
        assert _float(row, "certified_maximum_outer_bound_mwh_y") == outer
        assert _float(row, "conservative_gap_above_certified_maximum_mwh_y") == gap
        assert row["status"] == "above_maximum"
        assert row["certified_classification_basis"] == (
            "certified_solver_bound_outer_range"
        )


def test_parameter_overlay_ranges_stages_and_sensitivity_labels():
    rows = _rows(PARAMETER_PATH)
    assert len(rows) == 23
    assert set(rows[0]) == PARAMETER_FIELDS
    assert len({row["parameter_id"] for row in rows}) == len(rows)
    assert {row["stage"] for row in rows} == {
        "analytical", "rolling", "reporting", "checkpoint_1_2", "validation",
        "boundary_freeze",
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
    assert background["allowed_values"] == "0.25;0.30;0.31"
    assert _float(background, "baseline_low") == 0.25
    assert _float(background, "baseline_central") == 0.30
    assert _float(background, "baseline_high") == 0.31
    assert background["may_move"] == "false"
    assert "35" in background["physical_hard_bound"]
    assert "40" in background["physical_hard_bound"]

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
    c0_co2 = by_id["uae_c0_first_order_co2_constant"]
    assert c0_co2["stage"] == "boundary_freeze"
    assert c0_co2["may_move"] == "false"
    assert c0_co2["physical_hard_bound"] == "1.7<=reporting_bridge<=2.0"
    assert "never enter dispatch" in c0_co2["selection_rule"]
    c1_co2 = by_id["uae_c1_first_order_co2_constant"]
    assert c1_co2["stage"] == "reporting"
    assert "exempt from the 25-percent endpoint extension rule" in c1_co2[
        "selection_rule"
    ]
    assert "never modify or combine" in c1_co2["caveat"]
    assert c1_co2["physical_hard_bound"] == (
        "0<=constant<=configured_target_minus_selected_factor_subtotal"
    )
    assert "standalone envelope only" in c1_co2["caveat"]

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
    assert background_values == [0.25, 0.30, 0.31]
    assert all(0 < value <= 0.31 for value in background_values)

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

    c0_bridge = by_id["uae_c0_first_order_co2_constant"]
    assert _float(c0_bridge, "first_relaxed_low") == 1.7
    assert _float(c0_bridge, "first_relaxed_high") == 2.0
    assert c0_bridge["may_move"] == "false"
    c1_bridge = by_id["uae_c1_first_order_co2_constant"]
    assert _float(c1_bridge, "first_relaxed_low") == 0
    assert _float(c1_bridge, "first_relaxed_high") == 9.56318265


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
        "analytical_prescreen_enabled": False,
        "solver_runs_enabled": True,
        "calibration_candidates_run": True,
        "unsupported_code_execution_enabled": False,
        "execution_scope": "frozen_development_week_rolling_evaluation_only",
        "next_checkpoint_required": (
            "independent_review_before_held_out_final_evaluation"
        ),
    }
    assert config["mode"] == "user_authorized_full_site_emulation_checkpoint4"
    assert config["checkpoint_id"] == (
        "checkpoint_4_frozen_development_week_behavioural_evaluation"
    )
    assert config["prescreen"]["score_families_kept_separate"] is True
    assert config["claims"]["exact_digital_twin"] is False
    assert config["claims"]["tata_questionnaire_separate"] is True

    for path, expected_sha256 in STRICT_SHA256.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
    strict_parameters = _rows(STRICT_PARAMETER_PATH)
    assert {row["may_move"] for row in strict_parameters} == {"false"}
    assert ANCHOR_PATH != STRICT_TARGET_PATH
    assert PARAMETER_PATH != STRICT_PARAMETER_PATH
