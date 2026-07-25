"""Normalise current steel outputs against site, plant and model-precedent anchors.

This is a diagnostic-only comparison layer.  It never changes a coefficient,
target, controller or objective and refuses to turn denominator-mismatched
annual anchors into an optimisation score.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import (
    KGF_UNDERFIRING_MWH_PER_T_COKE,
    REPO_ROOT,
    SINTER_COG_MWH_PER_T_SINTER,
    WAG_TO_POWER_EFFICIENCY,
    load_governed_wag_factor_maps,
)
from .wag_development_controller_contract import bf_hot_stove_mwh_per_t_hot_metal, hsm_reheat_mwh_per_t_hrc


RUN_ID = "steel_intensity_anchor_diagnostic_v1"
INPUT_RUN_ID = "steel_closed_loop_feasibility_anchor_reconciliation_v1"
RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
INPUT_DIR = RUN_ROOT / INPUT_RUN_ID
OUTPUT_DIR = RUN_ROOT / RUN_ID
ANCHOR_REGISTER = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "c5_model_anchor_register" / "c5_model_anchor_evidence_register.csv"
WAG_COEFFICIENTS = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "s4_4b5a_asymmetric_c0_c1_correction" / "corrected_dev_inputs" / "wag_generation_coefficients.csv"
CONFIGS = {"C0": "C0_current_BF_BOF_reference", "C1": "C1_phase1_BF_BOF_plus_DRP_EAF"}
PJ_PER_MWH = 3.6e-6


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _num(value: Any) -> float:
    return 0.0 if value in (None, "") else float(value)


def _sum(rows: list[dict[str, str]], key: str) -> float:
    return sum(_num(row.get(key)) for row in rows)


def _model_totals() -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    rows = _read_csv(INPUT_DIR / "first_window_hourly.csv")
    output: dict[str, dict[str, float]] = {}
    plant_rows: list[dict[str, Any]] = []
    activity_fields = {
        "C0": {
            "blast_furnace_hot_metal_proxy": "C0_BOF_hot_iron_input_t_h",
            "coking_dry_coal_input": "C0_coking_input_t_h",
            "basic_oxygen_liquid_steel_proxy": "C0_BOF_hot_iron_input_t_h",
            "hsm_wbw_throughput": "C0_HSM_input_t_h",
        },
        "C1": {
            "blast_furnace_hot_metal_proxy": "C1_retained_BOF_hot_iron_input_t_h",
            "coking_dry_coal_input": "C1_retained_coking_input_t_h",
            "basic_oxygen_liquid_steel_proxy": "C1_retained_BOF_hot_iron_input_t_h",
            "hsm_wbw_retained_throughput": "C1_retained_HSM_input_t_h",
            "drp_pellet_input": "C1_DRP_activity_t_pellets_h",
            "eaf_dri_input": "C1_EAF_activity_t_DRI_h",
        },
    }
    for short, configuration in CONFIGS.items():
        scoped = [row for row in rows if row["configuration_id"] == configuration]
        final = _sum(scoped, "final_product_output_t")
        totals = {
            "final_product_t": final,
            "gross_electricity_mwh": _sum(scoped, "gross_electricity_mwh"),
            "net_grid_import_mwh": _sum(scoped, "net_grid_import_mwh"),
            "wag_generation_mwh": _sum(scoped, "WAG_generated"),
            "wag_use_mwh": _sum(scoped, "WAG_used"),
            "wag_power_mwh": _sum(scoped, "wag_electricity_mwh"),
            "generator_fuel_mwh": _sum(scoped, "vattenfall_fuel_mwh"),
            "wag_flare_mwh": _sum(scoped, "WAG_flared"),
            "represented_ng_mwh": _sum(scoped, "natural_gas_nm3") * 35.8 / 3600.0 + _sum(scoped, "natural_gas_boiler_mwh"),
            "explicit_wag_co2_t": _sum(scoped, "WAG_explicit_combustion_co2_t"),
            "oxygen_t": _sum(scoped, "oxygen_t"),
            "bfg_generation_mwh": _sum(scoped, "BFG_generated_mwh"),
            "cog_generation_mwh": _sum(scoped, "COG_generated_mwh"),
            "bofg_generation_mwh": _sum(scoped, "BOFG_generated_mwh"),
        }
        for activity_id, field in activity_fields[short].items():
            totals[activity_id] = _sum(scoped, field)
            plant_rows.append({
                "configuration": configuration,
                "metric_id": activity_id,
                "model_field": field,
                "value": round(totals[activity_id], 8),
                "unit": "t per 168h planning window",
                "interpretation": "represented model activity; not automatically an official plant output denominator",
            })
        output[short] = totals
    return output, plant_rows


def _ratio(numerator: float, denominator: float, factor: float = 1.0) -> float | None:
    return None if denominator == 0.0 else numerator * factor / denominator


def _model_intensity_rows(totals: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for short, values in totals.items():
        config = CONFIGS[short]
        base = values["final_product_t"]
        for metric_id, numerator, unit, caveat in (
            ("gross_electricity", values["gross_electricity_mwh"], "MWh/t_final_product_proxy", "gross electricity includes current represented/proxy boundary only"),
            ("net_grid_import", values["net_grid_import_mwh"], "MWh/t_final_product_proxy", "internal generator offset is not full-site grid import"),
            ("wag_generation", values["wag_generation_mwh"], "MWh/t_final_product_proxy", "carrier-specific model total; final-product-proxy denominator"),
            ("wag_use", values["wag_use_mwh"], "MWh/t_final_product_proxy", "represented WAG sinks only"),
            ("generator_electricity", values["wag_power_mwh"], "MWh/t_final_product_proxy", "internal offset only; not market export"),
            ("represented_NG", values["represented_ng_mwh"] * 3.6, "GJ/t_final_product_proxy", "named consumers only; residual NG excluded"),
            ("explicit_WAG_CO2", values["explicit_wag_co2_t"], "tCO2/t_final_product_proxy", "point-of-oxidation WAG only, not Scope 1"),
        ):
            rows.append({
                "configuration": config, "metric_id": metric_id, "numerator_value": round(numerator, 8),
                "numerator_unit": "MWh" if "CO2" not in metric_id and "NG" not in metric_id else ("tCO2" if "CO2" in metric_id else "GJ"),
                "denominator_value": round(base, 8), "denominator_unit": "t final-product proxy",
                "intensity": "" if _ratio(numerator, base) is None else round(_ratio(numerator, base), 8),
                "intensity_unit": unit, "comparability": "conditional", "caveat": caveat,
            })
        generator_efficiency = _ratio(values["wag_power_mwh"], values["generator_fuel_mwh"])
        rows.append({
            "configuration": config, "metric_id": "generator_conversion_efficiency", "numerator_value": round(values["wag_power_mwh"], 8),
            "numerator_unit": "MWh_e", "denominator_value": round(values["generator_fuel_mwh"], 8), "denominator_unit": "MWh_LHV",
            "intensity": "" if generator_efficiency is None else round(generator_efficiency, 8), "intensity_unit": "MWh_e/MWh_LHV",
            "comparability": "wiring_check", "caveat": "Checks existing fixed conversion rule rather than independently validating turbine performance.",
        })
    return rows


def _carrier_rows(totals: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    lhv, _ = load_governed_wag_factor_maps()
    coefficient_rows = _read_csv(WAG_COEFFICIENTS)
    result: list[dict[str, Any]] = []
    field_map = {"BFG": ("bfg_generation_mwh", "blast_furnace_hot_metal_proxy"), "COG": ("cog_generation_mwh", "coking_dry_coal_input"), "BOFG": ("bofg_generation_mwh", "basic_oxygen_liquid_steel_proxy")}
    for short, values in totals.items():
        configuration = CONFIGS[short]
        for carrier, (generation_field, activity_field) in field_map.items():
            source = next((row for row in coefficient_rows if row["configuration_id"] == configuration and row["wag_carrier"] == carrier), None)
            actual = _ratio(values[generation_field], values[activity_field])
            expected = None
            if source is not None:
                expected = float(source["coefficient"]) * float(lhv[carrier]) / 3600.0
            result.append({
                "configuration": configuration, "carrier": carrier,
                "activity_proxy_t": round(values[activity_field], 8), "model_generation_mwh": round(values[generation_field], 8),
                "model_intensity_mwh_per_t_activity": "" if actual is None else round(actual, 8),
                "governed_coefficient_intensity_mwh_per_t_activity": "" if expected is None else round(expected, 8),
                "wiring_delta": "" if actual is None or expected is None else round(actual - expected, 10),
                "status": "pass_wiring" if actual is not None and expected is not None and abs(actual - expected) < 1e-6 else "warning_or_missing",
                "caveat": "Agreement verifies model wiring to the selected development coefficient; it is not independent Tata validation.",
            })
    return result


def _controller_sink_rows() -> list[dict[str, Any]]:
    rows = _read_csv(INPUT_DIR / "first_window_hourly.csv")
    output: list[dict[str, Any]] = []
    definitions = {
        "C0": [
            ("KGF_underfiring", "COG", "COG_to_KGF1_mwh;COG_to_KGF2_mwh", "C0_coking_input_t_h", KGF_UNDERFIRING_MWH_PER_T_COKE, "selected development underfiring intensity"),
            ("sinter_fuel", "COG", "COG_to_sinter_mwh", "C0_sintering_input_t_h", SINTER_COG_MWH_PER_T_SINTER, "selected development sinter intensity"),
            ("BF_hot_stove", "BFG", "BFG_to_BF_hot_stove_mwh", "C0_BOF_hot_iron_input_t_h", bf_hot_stove_mwh_per_t_hot_metal(), "BOF hot-metal input is a full-window proxy for BF output"),
            ("HSM_reheat_demand", "eligible WAG + NG", "", "C0_HSM_input_t_h", hsm_reheat_mwh_per_t_hrc(), "demand formula check; individual HSM carrier rows are not emitted in this compact hourly report"),
        ],
        "C1": [
            ("KGF_underfiring", "COG", "COG_to_KGF1_mwh", "C1_retained_coking_input_t_h", KGF_UNDERFIRING_MWH_PER_T_COKE, "selected development underfiring intensity"),
            ("sinter_fuel", "COG", "COG_to_sinter_mwh", "C1_retained_sintering_input_t_h", SINTER_COG_MWH_PER_T_SINTER, "selected development sinter intensity"),
            ("BF_hot_stove", "BFG", "BFG_to_BF_hot_stove_mwh", "C1_retained_BOF_hot_iron_input_t_h", bf_hot_stove_mwh_per_t_hot_metal(), "BOF hot-metal input is a full-window proxy for BF output"),
            ("HSM_reheat_demand", "eligible WAG + NG", "", "C1_retained_HSM_input_t_h", hsm_reheat_mwh_per_t_hrc(), "demand formula check; individual HSM carrier rows are not emitted in this compact hourly report"),
        ],
    }
    for short, configuration in CONFIGS.items():
        scoped = [row for row in rows if row["configuration_id"] == configuration]
        for sink, carrier, energy_field, activity_field, expected, caveat in definitions[short]:
            activity = _sum(scoped, activity_field)
            energy = sum(_sum(scoped, field) for field in energy_field.split(";")) if energy_field else activity * expected
            actual = _ratio(energy, activity)
            output.append({
                "configuration": configuration, "sink_or_controller": sink, "carrier": carrier,
                "activity_value_t": round(activity, 8), "energy_mwh_lhv": round(energy, 8),
                "model_intensity_mwh_per_t": "" if actual is None else round(actual, 8),
                "governed_intensity_mwh_per_t": round(expected, 8),
                "delta": "" if actual is None else round(actual - expected, 10),
                "status": "pass_wiring" if actual is not None and abs(actual - expected) < 1e-6 else "warning_or_missing",
                "caveat": caveat,
            })
        generator_fuel = _sum(scoped, "vattenfall_fuel_mwh")
        generator_electricity = _sum(scoped, "wag_electricity_mwh")
        actual_efficiency = _ratio(generator_electricity, generator_fuel)
        output.append({
            "configuration": configuration, "sink_or_controller": "generator_interface", "carrier": "BFG/COG/BOFG",
            "activity_value_t": "", "energy_mwh_lhv": round(generator_fuel, 8),
            "model_intensity_mwh_per_t": "" if actual_efficiency is None else round(actual_efficiency, 8),
            "governed_intensity_mwh_per_t": WAG_TO_POWER_EFFICIENCY,
            "delta": "" if actual_efficiency is None else round(actual_efficiency - WAG_TO_POWER_EFFICIENCY, 10),
            "status": "pass_wiring" if actual_efficiency is not None and abs(actual_efficiency - WAG_TO_POWER_EFFICIENCY) < 1e-6 else "warning_or_missing",
            "caveat": "Fixed generator interface conversion; it is not an independently validated plant-performance value.",
        })
    return output


def _anchor_intensity_rows(totals: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    anchors = {row["anchor_id"]: row for row in _read_csv(ANCHOR_REGISTER)}
    mapping = [
        ("C0", "c0_public_liquid_steel_7_2", "production_context", "final_product_t", 1.0, "t/t", "denominator mismatch"),
        ("C1", "c1_public_liquid_steel_6_8", "production_context", "final_product_t", 1.0, "t/t", "denominator mismatch"),
        ("C0", "c0_total_site_electricity_3twh_context", "electricity", "gross_electricity_mwh", 1.0, "MWh/t", "partial site boundary"),
        ("C1", "c1_official_total_site_electricity_17_8pj_missing", "electricity", "gross_electricity_mwh", 1.0, "MWh/t", "partial site boundary"),
        ("C0", "athan_table8_current_electricity_3_17", "electricity", "gross_electricity_mwh", 1.0, "MWh/t", "Athanasiadis denominator conditional at 6.2 Mt/y"),
        ("C1", "athan_table9_phase1_electricity_4_89", "electricity", "gross_electricity_mwh", 1.0, "MWh/t", "Athanasiadis denominator conditional at 6.2 Mt/y"),
        ("C0", "c0_residual_gas_electricity_2twh", "generator_electricity", "wag_power_mwh", 1.0, "MWh/t", "internal generator offset boundary"),
        ("C1", "c1_generator_offset_0_935277", "generator_electricity", "wag_power_mwh", 1.0, "MWh/t", "internal generator offset boundary"),
        ("C0", "c0_product_gas_reuse_54pj", "wag_use", "wag_use_mwh", 3.6, "GJ/t", "product gas reuse may have different sink boundary"),
        ("C0", "athan_table8_current_wag_2_74", "wag_generation", "wag_generation_mwh", 1.0, "MWh/t", "Athanasiadis denominator conditional at 6.2 Mt/y"),
        ("C1", "athan_table9_phase1_wag_1_23", "wag_generation", "wag_generation_mwh", 1.0, "MWh/t", "Athanasiadis denominator conditional at 6.2 Mt/y"),
        ("C0", "c0_full_site_ng_12_5pj_missing", "represented_ng", "represented_ng_mwh", 3.6, "GJ/t", "model excludes full-site residual NG"),
        ("C1", "c1_full_site_ng_46_5pj_missing", "represented_ng", "represented_ng_mwh", 3.6, "GJ/t", "model excludes full-site residual NG"),
        ("C0", "c0_official_scope1_12_6_missing", "explicit_WAG_CO2", "explicit_wag_co2_t", 1.0, "tCO2/t", "explicit WAG-only CO2 is not full Scope 1"),
        ("C1", "c1_official_scope1_8_3_missing", "explicit_WAG_CO2", "explicit_wag_co2_t", 1.0, "tCO2/t", "explicit WAG-only CO2 is not full Scope 1"),
    ]
    rows: list[dict[str, Any]] = []
    for short, anchor_id, metric, model_field, multiplier, unit, caveat in mapping:
        anchor = anchors[anchor_id]
        config = CONFIGS[short]
        model_denominator = totals[short]["final_product_t"]
        model_intensity = _ratio(totals[short][model_field] * multiplier, model_denominator)
        anchor_value = float(anchor["converted_value"] or anchor["raw_value"])
        if anchor_id.startswith("athan_table"):
            anchor_denom_mt = 6.2
            denominator_status = "conditional_user_supplied_6_2Mt_y_to_verify"
        elif short == "C0":
            anchor_denom_mt = 7.2
            denominator_status = "official_raw_liquid_steel_anchor"
        else:
            anchor_denom_mt = 6.8
            denominator_status = "official_raw_liquid_steel_anchor"
        if anchor["converted_unit"] == "TWh/y":
            anchor_numerator = anchor_value * 1_000_000.0
        elif anchor["converted_unit"] == "PJ/y":
            anchor_numerator = anchor_value * 1_000_000.0 / 3.6
        elif anchor["converted_unit"] == "MtCO2/y":
            anchor_numerator = anchor_value * 1_000_000.0
        else:
            anchor_numerator = anchor_value * 1_000_000.0
        anchor_intensity = _ratio(anchor_numerator * multiplier, anchor_denom_mt * 1_000_000.0)
        rows.append({
            "configuration": config, "anchor_id": anchor_id, "metric": metric,
            "model_intensity": "" if model_intensity is None else round(model_intensity, 8), "anchor_intensity": "" if anchor_intensity is None else round(anchor_intensity, 8),
            "intensity_unit": unit, "ratio_model_to_anchor": "" if not anchor_intensity or model_intensity is None else round(model_intensity / anchor_intensity, 8),
            "model_denominator": round(model_denominator, 8), "model_denominator_type": "final_product_proxy",
            "anchor_denominator_mt_y": anchor_denom_mt, "anchor_denominator_type": anchor["denominator_type"],
            "denominator_status": denominator_status, "comparison_status": "conditional_not_a_score",
            "source_rank": anchor["source_trust_rank"], "caveat": caveat + "; " + anchor["caveat"],
        })
    return rows


def run_normalised_anchor_diagnostics(*, input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    if not (input_dir / "first_window_hourly.csv").exists():
        raise FileNotFoundError("Closed-loop first-window hourly output is required before intensity diagnostics.")
    if output_dir.exists():
        raise FileExistsError(f"Diagnostic output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    totals, plant_rows = _model_totals()
    model_rows = _model_intensity_rows(totals)
    carrier_rows = _carrier_rows(totals)
    controller_rows = _controller_sink_rows()
    anchor_rows = _anchor_intensity_rows(totals)
    hypotheses = [
        {"hypothesis_id": "H1", "issue": "C0 WAG generation versus Athanasiadis", "evidence": "C0 WAG per final-product proxy is materially above conditional Athanasiadis intensity, while C0 WAG use per output is near the product-gas-reuse context intensity.", "interpretation": "Possible boundary/definition mismatch between Athanasiadis total WAG and the model carrier-energy total; do not tune coefficients yet.", "next_check": "Verify Athanasiadis WAG definition/denominator and split C0 WAG generation, process use and generator fuel by carrier."},
        {"hypothesis_id": "H2", "issue": "C0 generator electricity gap", "evidence": "Generator electricity per output remains below the C0 residual-gas electricity context anchor despite high represented WAG generation.", "interpretation": "Likely sink-priority, generator-interface capacity or boundary issue rather than automatically excessive WAG generation.", "next_check": "Audit carrier-specific generator capacity/interface versus process and boiler sinks."},
        {"hypothesis_id": "H3", "issue": "C1 electricity and downstream gap", "evidence": "C1 gross electricity and retained HSM throughput are well below C1 site/model-precedent anchors.", "interpretation": "The current C1 physical boundary omits downstream/site loads and treats only the retained HSM route explicitly.", "next_check": "Complete electricity boundary decomposition before modifying WAG generation factors."},
        {"hypothesis_id": "H4", "issue": "NG residual gap", "evidence": "Represented NG per output is below full-site NG anchors, especially in C0.", "interpretation": "Expected partial-boundary residual; it is not evidence that NG should be injected into the model.", "next_check": "Keep signed residual KPI and add only source-backed named consumers."},
        {"hypothesis_id": "H5", "issue": "CO2 comparisons", "evidence": "Explicit WAG-only CO2 is lower than full-site Scope 1 anchors but may have plausible intensity order of magnitude.", "interpretation": "No conclusion on emissions accuracy is valid until non-WAG process carbon and residual boundaries are reconciled.", "next_check": "Maintain point-of-oxidation ledger and do not sum aggregate counters."},
    ]
    _write_csv(output_dir / "model_intensity_ledger.csv", model_rows)
    _write_csv(output_dir / "carrier_generation_wiring_intensity.csv", carrier_rows)
    _write_csv(output_dir / "controller_sink_wiring_intensity.csv", controller_rows)
    _write_csv(output_dir / "plant_activity_intensity_context.csv", plant_rows)
    _write_csv(output_dir / "normalised_anchor_comparison.csv", anchor_rows)
    _write_csv(output_dir / "boundary_hypotheses.csv", hypotheses)
    summary = {
        "run_id": RUN_ID, "input_run_id": INPUT_RUN_ID, "status": "diagnostic_complete",
        "anchor_intensity_rows": len(anchor_rows), "carrier_wiring_pass_rows": sum(row["status"] == "pass_wiring" for row in carrier_rows),
        "controller_wiring_pass_rows": sum(row["status"] == "pass_wiring" for row in controller_rows),
        "conditional_comparisons_only": True,
        "key_warning": "No denominator-mismatched anchor is used as an optimisation target or score.",
    }
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "input_manifest.json", {
        "closed_loop_input": str(input_dir.relative_to(REPO_ROOT)), "anchor_register": str(ANCHOR_REGISTER.relative_to(REPO_ROOT)),
        "wag_generation_coefficients": str(WAG_COEFFICIENTS.relative_to(REPO_ROOT)),
        "sha256_first_window_hourly": hashlib.sha256((input_dir / "first_window_hourly.csv").read_bytes()).hexdigest(),
    })
    (output_dir / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- All normalised comparisons are conditional: model denominator is final-product proxy while most anchors use liquid steel or an unresolved basis.\n"
        "- Athanasiadis values use the user-supplied 6.2 Mt/y denominator only as a flagged conditional calculation.\n"
        "- Carrier coefficient agreement validates wiring to selected development inputs, not Tata-specific empirical accuracy.\n"
        "- No coefficient, controller priority, residual load or objective was changed.\n",
        encoding="utf-8",
    )
    return {"output_dir": output_dir, "summary": summary, "anchor_rows": anchor_rows}
