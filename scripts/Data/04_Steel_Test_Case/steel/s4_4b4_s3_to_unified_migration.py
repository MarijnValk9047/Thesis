"""Create the S4.4b4 S2/S3-to-unified development input package.

This module is intentionally a migration generator, not an optimiser runner.
It reads already-governed S2/S3/S4.4 evidence artifacts and writes a new
S4.4b4 input package without modifying the original S4.4b inputs.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .s4_4b_unified_input_validator import validate_unified_dev_inputs, write_validation_outputs


REPO_ROOT = Path(__file__).resolve().parents[4]
STEEL_INPUT_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel"
S2_ROOT = STEEL_INPUT_ROOT / "S2"
S3_REVIEW_ROOT = STEEL_INPUT_ROOT / "S3/s3_candidate_review"
S4_ROOT = STEEL_INPUT_ROOT / "S4"
BASE_INPUT_DIR = S4_ROOT / "s4_4b_unified_dev_inputs"
S44B2_COMPILED_REVIEW = S4_ROOT / "s4_4b2_physical_master_workbook/compiled_review"
S44B3_DIR = S4_ROOT / "s4_4b3_figure_parameter_enrichment"

OUTPUT_DIR = S4_ROOT / "s4_4b4_s3_to_unified_migration"
MIGRATED_INPUT_DIR = OUTPUT_DIR / "migrated_dev_inputs"
PYPSA_REVIEW_DIR = OUTPUT_DIR / "pypsa_style_review"

C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"

TABLES_16 = [
    "configuration_assets.csv",
    "process_units.csv",
    "process_io_coefficients.csv",
    "process_energy_intensities.csv",
    "process_emission_factors.csv",
    "buffers_and_stores.csv",
    "wag_generation_coefficients.csv",
    "wag_sink_eligibility.csv",
    "utility_demands.csv",
    "utility_conversion_assets.csv",
    "external_supply_costs.csv",
    "market_price_inputs.csv",
    "production_targets.csv",
    "validation_anchors.csv",
    "policy_modes.csv",
    "solver_and_horizon_config.csv",
]

PYPSA_REVIEW_TABLES = [
    "carriers.csv",
    "buses.csv",
    "config_components.csv",
    "links.csv",
    "link_ports.csv",
    "stores.csv",
    "loads.csv",
    "generators.csv",
    "mixing_rules.csv",
    "system_constraints.csv",
]

MIGRATION_COLUMNS = [
    "migration_stage",
    "migration_source_artifacts",
    "migration_notes",
    "executable_input",
]

FIGURE_SOURCE_CARDS = {
    "coking_plant_1": "S4B3-ATH-FIG58-COK1-OPERATING-LIMITS",
    "sintering_plant": "S4B3-ATH-FIG59-SINTER-OPERATING-LIMITS",
    "pelletizing_plant": "S4B3-ATH-FIG60-PELLETIZING-OPERATING-LIMITS",
    "blast_furnace_6": "S4B3-ATH-FIG61-BF6-OPERATING-LIMITS",
    "basic_oxygen_furnace": "S4B3-ATH-FIG62-BOF-OPERATING-LIMITS",
    "hot_strip_mill": "S4B3-ATH-FIG63-HSM-OPERATING-LIMITS",
    "hot_iron_store": "S4B3-ATH-FIG65-HOT-IRON-STORE-CAPACITY",
    "slab_store": "S4B3-ATH-FIG66-STEEL-SLAB-STORE-CAPACITY",
    "oxygen_store": "S4B3-ATH-FIG67-OXYGEN-STORE-CAPACITY",
}

FIGURE_LIMITS = {
    "coking_plant_1": {
        "min": "150",
        "max": "180",
        "unit": "t_coal/h",
        "basis": "coal consumption",
        "candidate_id": "CAND_S44B3_FIG58_COK1_LIMITS_TCOAL_H",
    },
    "sintering_plant": {
        "min": "160",
        "max": "320",
        "unit": "t_iron_ore/h",
        "basis": "iron ore consumption",
        "candidate_id": "CAND_S44B3_FIG59_SINTER_LIMITS_T_H",
    },
    "pelletizing_plant": {
        "min": "300",
        "max": "565",
        "unit": "t_iron_ore/h",
        "basis": "iron ore consumption",
        "candidate_id": "CAND_S44B3_FIG60_PELLET_LIMITS_TIRONORE_H",
    },
    "blast_furnace_6": {
        "min": "120",
        "max": "170",
        "unit": "t_sinter/h",
        "basis": "sinter consumption",
        "candidate_id": "CAND_S44B3_FIG61_BF6_LIMITS_TSINTER_H",
    },
    "basic_oxygen_furnace": {
        "min": "505",
        "max": "830",
        "unit": "t_hot_iron/h",
        "basis": "hot iron consumption",
        "candidate_id": "CAND_S44B3_FIG62_BOF_LIMITS_THOTIRON_H",
    },
    "hot_strip_mill": {
        "min": "145",
        "max": "800",
        "unit": "t_crude_steel/h",
        "basis": "crude steel consumption",
        "candidate_id": "CAND_S44B3_FIG63_HSM_LIMITS_TCRUDESTEEL_H",
    },
}

S3_GUARDRAIL_VALUES = {
    "DRP_capacity": {
        "central": "500",
        "unit": "t_pellets/h",
        "source": "data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review/s3_4_eaf_drp_guardrail_dev_inputs.csv",
    },
    "DRP_min_pu": {"central": "0.7", "unit": "pu_of_capacity"},
    "DRP_max_pu": {"central": "1.1", "unit": "pu_of_capacity"},
    "DRP_ramp_pu_per_h": {"central": "0.1", "unit": "pu/h"},
    "DRP_pellets_to_DRI": {"central": "0.74", "unit": "t_DRI/t_pellets"},
    "DRP_electricity": {"central": "0.1", "unit": "MWh/t_pellets"},
    "DRP_NG": {"central": "195", "unit": "Nm3/t_pellets"},
    "DRP_oxygen": {"central": "0.1", "unit": "t_O2/t_pellets"},
    "EAF_capacity": {"central": "400", "unit": "t_DRI/h"},
    "EAF_min_pu": {"central": "0.9", "unit": "pu_of_capacity"},
    "EAF_max_pu": {"central": "1.1", "unit": "pu_of_capacity"},
    "EAF_DRI_to_steel": {"central": "0.95", "unit": "t_liquid_steel/t_DRI"},
    "EAF_electricity": {"central": "0.5", "unit": "MWh/t_DRI"},
    "EAF_scrap": {"central": "0.2", "unit": "t_scrap/t_DRI"},
    "EAF_oxygen": {"central": "0.05", "unit": "t_O2/t_DRI"},
    "DRI_buffer_capacity": {"central": "17760", "unit": "t_DRI"},
}

S3_SELECTED_VALUES = {
    "bfg_generation_nm3_per_t_hot_metal": {
        "central": "1600.0",
        "lower": "1200.0",
        "upper": "2000.0",
        "unit": "Nm3/t_hot_metal",
        "basis": "per tonne BF hot metal",
    },
    "cog_generation_m3_per_t_dry_coal": {
        "central": "365.0",
        "lower": "280.0",
        "upper": "450.0",
        "unit": "m3/t_dry_coal",
        "basis": "per tonne dry coal",
    },
    "bofg_generation_nm3_per_t_liquid_steel": {
        "central": "75.0",
        "lower": "50.0",
        "upper": "100.0",
        "unit": "Nm3/t_liquid_steel",
        "basis": "per tonne BOF liquid steel",
    },
    "wag_to_power_efficiency_fraction": {
        "central": "0.3715",
        "lower": "0.321",
        "upper": "0.422",
        "unit": "fraction",
        "basis": "per GJ WAG fuel input",
    },
    "bf_bof_aggregate_direct_co2_t_per_t_bof": {
        "central": "2.15568",
        "lower": "1.6",
        "upper": "2.5",
        "unit": "tCO2/t_BOF_liquid_steel",
        "basis": "per tonne BOF liquid steel",
    },
}


@dataclass(frozen=True)
class CsvTable:
    rows: list[dict[str, str]]
    fieldnames: list[str]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_csv(path: Path) -> CsvTable:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return CsvTable(rows=rows, fieldnames=list(reader.fieldnames or []))


def _write_csv(path: Path, rows: Iterable[dict[str, str]], fieldnames: Iterable[str] | None = None) -> None:
    rows = [dict(row) for row in rows]
    columns = list(fieldnames or [])
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_bool_text(value: bool) -> str:
    return "true" if value else "false"


def _governance(
    *,
    source_card_ids: str,
    candidate_id: str,
    input_status: str,
    evidence_strength: str = "development_candidate",
    human_review_required: bool = False,
    caveat: str,
    migration_source: str,
    executable_input: bool = True,
    migration_notes: str = "",
) -> dict[str, str]:
    return {
        "source_card_ids": source_card_ids,
        "candidate_id": candidate_id,
        "evidence_strength": evidence_strength,
        "input_status": input_status,
        "thesis_usability": "false",
        "codex_may_decide": "false",
        "human_review_required": _as_bool_text(human_review_required),
        "caveat": caveat,
        "migration_stage": "S4.4b4",
        "migration_source_artifacts": migration_source,
        "migration_notes": migration_notes,
        "executable_input": _as_bool_text(executable_input),
    }


def _row_with_base(columns: list[str], values: dict[str, str]) -> dict[str, str]:
    row = {column: "" for column in columns}
    row.update(values)
    return row


def _dedupe(rows: Iterable[dict[str, str]], primary_key: list[str]) -> list[dict[str, str]]:
    seen: dict[tuple[str, ...], dict[str, str]] = {}
    order: list[tuple[str, ...]] = []
    for row in rows:
        key = tuple(row.get(column, "") for column in primary_key)
        if key not in seen:
            order.append(key)
        seen[key] = row
    return [seen[key] for key in order]


def _table_columns(base_tables: dict[str, CsvTable], table_name: str) -> list[str]:
    columns = list(base_tables[table_name].fieldnames)
    for extra in MIGRATION_COLUMNS:
        if extra not in columns:
            columns.append(extra)
    return columns


def _load_base_tables() -> dict[str, CsvTable]:
    return {name: _read_csv(BASE_INPUT_DIR / name) for name in TABLES_16}


def _manifest_rows() -> list[dict[str, str]]:
    manifest = BASE_INPUT_DIR / "s4_4b_unified_dev_inputs_manifest.csv"
    if not manifest.exists():
        return []
    rows = _read_csv(manifest).rows
    for row in rows:
        row["input_layer_status"] = "s4_4b4_migrated_package"
        row["caveat"] = (
            row.get("caveat", "")
            + " S4.4b4 preserves the S4.4b contract while migrating S2/S3 development inputs."
        ).strip()
    return rows


def build_source_inventory() -> list[dict[str, str]]:
    artifacts = [
        (
            S2_ROOT / "s2_13_downstream_scheduling_assumptions.csv",
            "S2.13",
            "downstream scheduling assumptions",
            "yes",
            "downstream routes; store policy",
            "Used only where already represented in S4.4b2 review and S3 guardrails.",
        ),
        (
            S2_ROOT / "s2_to_s3/s3_wag_accounting_boundary_register.csv",
            "S3.0b",
            "WAG boundary register",
            "yes",
            "BFG;COG;BOFG;WAG sinks;flaring",
            "Keeps WAG carriers separate and blocks WAG export revenue.",
        ),
        (
            S2_ROOT / "s2_to_s3/s3_wag_allocation_mode_register.csv",
            "S3.0b",
            "WAG allocation assumptions",
            "yes",
            "process-first WAG hierarchy;spillage",
            "Hierarchy migrated as eligibility/priority review rows, not market valuation.",
        ),
        (
            S2_ROOT / "s2_to_s3/s3_energy_accounting_asset_eligibility_register.csv",
            "S3.1",
            "energy accounting eligibility",
            "yes",
            "utility boundary;residual loads;Vattenfall interface",
            "Vattenfall retained as interface, not dispatch plant.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3j_final_case_assumption_register.csv",
            "S3.3j",
            "final assumption register",
            "yes",
            "C1 utility boundary;BF-BOF share;HSM heat caveats",
            "Used as final/frozen S3 assumption source where applicable.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3j_final_metric_summary.csv",
            "S3.3j",
            "final metric summary",
            "yes",
            "validation anchors;calibration diagnostics",
            "Migrated to validation anchors and report only, not executable coefficients.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3j_final_c0_regression_results.csv",
            "S3.3j",
            "C0 regression result",
            "yes",
            "C0 anchors;S33H_B_004 final case",
            "Used for validation/reporting anchors only.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3j_final_c1_boundary_aligned_results.csv",
            "S3.3j",
            "C1 boundary-aligned result",
            "yes",
            "C1 anchors;S33H_B_004 final case",
            "Used for validation/reporting anchors only.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3j_remaining_limitations.csv",
            "S3.3j",
            "remaining limitations",
            "yes",
            "utility caveats;Vattenfall caveats;pelletizing caveats",
            "Migrated into caveats and unresolved-input reporting.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3_selected_calibrated_inputs.csv",
            "S3.3",
            "selected calibrated inputs",
            "yes",
            "WAG coefficients;CO2 factor;energy scales",
            "Selected central set and existing ranges migrated as development candidates.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3_selected_parameter_ensemble.csv",
            "S3.3",
            "selected parameter ensemble",
            "yes",
            "sensitivity envelope selection",
            "Supports selected central values and existing lower/upper ranges.",
        ),
        (
            S3_REVIEW_ROOT / "s3_3h_best_case_comparison.csv",
            "S3.3h",
            "best case comparison",
            "yes",
            "best accepted case S33H_B_004",
            "Used to select S33H_B_004 where later S3.3j files reference it.",
        ),
        (
            S3_REVIEW_ROOT / "s3_4_eaf_drp_guardrail_dev_inputs.csv",
            "S3.4",
            "EAF/DRP guardrail dev inputs",
            "yes",
            "DRP;EAF;DRI buffer",
            "Migrated as development executable C1 guardrails.",
        ),
        (
            S3_REVIEW_ROOT / "s3_4_eaf_drp_guardrail_dev_input_promotion_shortlist.csv",
            "S3.4",
            "guardrail promotion shortlist",
            "yes",
            "DRP/EAF selected values and existing ranges",
            "Used where rows were promoted in S3.4 guardrail package.",
        ),
        (
            S3_REVIEW_ROOT / "s4_0b_guardrail_regression_report.csv",
            "S4.0b",
            "guardrail regression report",
            "yes",
            "C1 guardrail regression pass",
            "Supports C1 partial rerun readiness only.",
        ),
        (
            S44B2_COMPILED_REVIEW / "links.csv",
            "S4.4b2",
            "compiled physical links",
            "yes",
            "process topology;ports;interfaces",
            "Used for PyPSA-style review snapshots and structural mapping.",
        ),
        (
            S44B2_COMPILED_REVIEW / "stores.csv",
            "S4.4b2",
            "compiled physical stores",
            "yes",
            "stores;buffers;terminal policies",
            "Patched with human-confirmed figure capacities and hot/cold design.",
        ),
        (
            S44B2_COMPILED_REVIEW / "validation_anchors.csv",
            "S4.4b2",
            "compiled validation anchors",
            "yes",
            "anchors",
            "Validation-only migration context.",
        ),
        (
            S44B3_DIR / "s4_4b3_figure_parameter_patch.csv",
            "S4.4b3",
            "figure parameter patch",
            "yes",
            "Athanasiadis figure operating limits and store capacities",
            "Human-confirmed in S4.4b4 prompt; migrated as development inputs.",
        ),
        (
            S44B3_DIR / "s4_4b3_topology_decision_patch.csv",
            "S4.4b3",
            "topology decision patch",
            "yes",
            "C1 BF7/KGF2 closure",
            "Human-selected closure decision applied.",
        ),
        (
            S44B3_DIR / "s4_4b3_hot_cold_slab_design.csv",
            "S4.4b3",
            "hot/cold slab design",
            "yes",
            "hot slab;cold slab;reheating",
            "Migrated as design/deferred modelbuilder rows.",
        ),
    ]
    rows = []
    for artifact_path, stage, artifact_type, relevant, families, caveat in artifacts:
        rows.append(
            {
                "artifact_path": _rel(artifact_path),
                "stage": stage,
                "artifact_type": artifact_type,
                "relevant_for_migration": relevant,
                "extracted_families": families,
                "artifact_exists": _as_bool_text(artifact_path.exists()),
                "caveat": caveat,
            }
        )
    return rows


def build_sensitivity_selection() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    source_selected = _rel(S3_REVIEW_ROOT / "s3_3_selected_calibrated_inputs.csv")
    source_best = _rel(S3_REVIEW_ROOT / "s3_3h_best_case_comparison.csv")
    source_guardrail = _rel(S3_REVIEW_ROOT / "s3_4_eaf_drp_guardrail_dev_inputs.csv")

    for parameter_name, data in S3_SELECTED_VALUES.items():
        rows.append(
            {
                "parameter_family": "S3_selected_calibration",
                "parameter_name": parameter_name,
                "configuration_scope": "C0_C1_development_context",
                "asset_or_carrier": "WAG_or_BF_BOF",
                "selected_central_value": data["central"],
                "lower_value": data["lower"],
                "upper_value": data["upper"],
                "unit": data["unit"],
                "basis": data["basis"],
                "selection_method": "S3 selected central calibrated set; best accepted case S33H_B_004 preserved",
                "source_artifact": f"{source_selected};{source_best}",
                "sensitivity_case_id": "S33_CAND_001_CALIBRATION_ANCHOR;S33H_B_004",
                "validation_metric_used": "S3 selected ensemble plus S33H Block B weighted C1 alignment score",
                "caveat": "Development calibration value, not measured Tata truth.",
            }
        )

    guardrail_rows = {
        "DRP_nominal_capacity": ("C1", "NG_DRP", "500", "", "", "t_pellets/h", "DRP pellet input nominal rate"),
        "DRP_min_operating_fraction": ("C1", "NG_DRP", "0.7", "", "", "pu", "DRP on-state lower fraction"),
        "DRP_max_operating_fraction": ("C1", "NG_DRP", "1.1", "", "", "pu", "DRP on-state upper fraction"),
        "DRP_ramp_rate": ("C1", "NG_DRP", "0.1", "", "", "pu/h", "DRP ramp candidate"),
        "DRP_pellets_to_DRI_yield": ("C1", "NG_DRP", "0.74", "", "", "t_DRI/t_pellets", "DRP material yield"),
        "DRP_electricity_intensity": ("C1", "NG_DRP", "0.1", "", "", "MWh/t_pellets", "DRP electricity intensity"),
        "DRP_NG_intensity": ("C1", "NG_DRP", "195", "", "", "Nm3/t_pellets", "DRP natural gas intensity"),
        "DRP_oxygen_intensity": ("C1", "NG_DRP", "0.1", "", "", "t_O2/t_pellets", "DRP oxygen input"),
        "EAF_DRI_input_nominal_capacity": ("C1", "EAF", "400", "", "", "t_DRI/h", "EAF DRI input nominal rate"),
        "EAF_min_operating_fraction": ("C1", "EAF", "0.9", "", "", "pu", "EAF on-state lower fraction"),
        "EAF_max_operating_fraction": ("C1", "EAF", "1.1", "", "", "pu", "EAF on-state upper fraction"),
        "EAF_DRI_to_liquid_steel_yield": ("C1", "EAF", "0.95", "", "", "t_liquid_steel/t_DRI", "EAF material yield"),
        "EAF_electricity_intensity": ("C1", "EAF", "0.5", "", "", "MWh/t_DRI", "EAF electricity intensity"),
        "EAF_scrap_ratio": ("C1", "EAF", "0.2", "", "", "t_scrap/t_DRI", "EAF scrap diagnostic ratio"),
        "EAF_oxygen_ratio": ("C1", "EAF", "0.05", "", "", "t_O2/t_DRI", "EAF oxygen diagnostic ratio"),
        "DRI_buffer_capacity": ("C1", "DRI_buffer", "17760", "", "", "t_DRI", "48h derived guardrail buffer"),
    }
    for parameter_name, (scope, asset, central, lower, upper, unit, basis) in guardrail_rows.items():
        rows.append(
            {
                "parameter_family": "S3_4_EAF_DRP_guardrail",
                "parameter_name": parameter_name,
                "configuration_scope": scope,
                "asset_or_carrier": asset,
                "selected_central_value": central,
                "lower_value": lower,
                "upper_value": upper,
                "unit": unit,
                "basis": basis,
                "selection_method": "final S3.4 guardrail development input",
                "source_artifact": source_guardrail,
                "sensitivity_case_id": "S3_4_GUARDRAIL",
                "validation_metric_used": "S4.0b guardrail regression pass",
                "caveat": "Development guardrail value; not Tata-measured truth.",
            }
        )

    figure_source = _rel(S44B3_DIR / "s4_4b3_figure_parameter_patch.csv")
    for asset_id, data in FIGURE_LIMITS.items():
        rows.append(
            {
                "parameter_family": "S4_4b3_human_confirmed_figure",
                "parameter_name": "operating_limits",
                "configuration_scope": "C0_C1_if_asset_active",
                "asset_or_carrier": asset_id,
                "selected_central_value": "",
                "lower_value": data["min"],
                "upper_value": data["max"],
                "unit": data["unit"],
                "basis": data["basis"],
                "selection_method": "human-confirmed figure-derived development input",
                "source_artifact": figure_source,
                "sensitivity_case_id": data["candidate_id"],
                "validation_metric_used": "not_a_sensitivity_result",
                "caveat": "Figure-derived human-confirmed development input; not measured Tata truth.",
            }
        )
    return rows


def build_configuration_assets(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "configuration_assets.csv")

    assets = [
        ("coking_plant_1", True, True, "KGF1 retained in C1"),
        ("coking_plant_2", True, False, "KGF2 closed in C1"),
        ("sintering_plant", True, True, "retained raw material route"),
        ("pelletizing_plant", True, True, "retained pellet route plus DRP feed route"),
        ("blast_furnace_6", True, True, "BF6 retained in C1"),
        ("blast_furnace_7", True, False, "BF7 closed in C1"),
        ("basic_oxygen_furnace", True, True, "retained BF-BOF route where active"),
        ("continuous_caster_or_slab_conversion", True, True, "downstream slab conversion retained"),
        ("hot_strip_mill", True, True, "downstream route retained"),
        ("direct_sheet_plant", True, True, "DSP retained structurally where in workbook topology"),
        ("linde_asu", True, True, "ASU/Linde oxygen active if present"),
        ("NG_DRP", False, True, "C1 added DRP guardrail process"),
        ("EAF", False, True, "C1 added EAF guardrail process"),
        ("DRI_buffer", False, True, "C1 DRI decoupling buffer"),
        ("hot_iron_store", True, True, "figure-derived hot iron transfer store"),
        ("hot_slab_store", True, True, "hot slab design store deferred for modelbuilder"),
        ("cold_slab_store", True, True, "cold slab design store deferred for modelbuilder"),
        ("oxygen_store", True, True, "figure-derived oxygen store"),
        ("WAG_BFG_network", True, True, "BFG carrier retained separately"),
        ("WAG_COG_network", True, True, "COG carrier retained separately"),
        ("WAG_BOFG_network", True, True, "BOFG carrier retained separately"),
        ("WAG_BOILERS_15_16_23_24_mixer", True, True, "boiler/steam utility sink retained"),
        ("Vattenfall_WAG_interface", True, True, "interface only, not full dispatch plant"),
        ("WAG_flare_spillage", True, True, "explicit spillage route if sinks insufficient"),
        ("residual_site_loads", True, True, "S3 residual loads retained as loads"),
    ]

    rows: list[dict[str, str]] = []
    for asset_id, c0_active, c1_active, note in assets:
        for config_id, active in [(C0, c0_active), (C1, c1_active)]:
            status = "development_only" if active else "inactive_human_selected_default"
            caveat = (
                "Migrated topology development input; not Tata-measured truth."
                if active
                else "Human-selected C1 closure decision applied while preserving conflict history in reports."
            )
            rows.append(
                _row_with_base(
                    columns,
                    {
                        "configuration_id": config_id,
                        "asset_id": asset_id,
                        "active": _as_bool_text(active),
                        "capacity_status": "bounded_or_candidate" if active else "inactive",
                        "controllability_status": "limited_or_structural" if active else "not_active",
                        "notes": note,
                        **_governance(
                            source_card_ids="REPO-S4-4B3-TOPOLOGY;REPO-S3-3J-FINAL",
                            candidate_id=f"S44B4_TOPOLOGY_{config_id}_{asset_id}",
                            input_status=status,
                            human_review_required=False,
                            caveat=caveat,
                            migration_source=(
                                f"{_rel(S44B3_DIR / 's4_4b3_topology_decision_patch.csv')};"
                                f"{_rel(S44B2_COMPILED_REVIEW / 'config_components.csv')}"
                            ),
                            executable_input=active,
                            migration_notes=note,
                        ),
                    },
                )
            )
    return _dedupe(rows, ["configuration_id", "asset_id"])


def _process_unit_row(
    columns: list[str],
    *,
    process_id: str,
    asset_id: str,
    configuration_id: str,
    min_rate: str,
    max_rate: str,
    rate_unit: str,
    source_card_ids: str,
    candidate_id: str,
    input_status: str,
    caveat: str,
    migration_source: str,
    executable_input: bool,
    ramp_up: str = "",
    ramp_down: str = "",
    commitment_type: str = "continuous",
    human_review_required: bool = False,
) -> dict[str, str]:
    return _row_with_base(
        columns,
        {
            "process_id": process_id,
            "asset_id": asset_id,
            "configuration_id": configuration_id,
            "min_rate": min_rate,
            "max_rate": max_rate,
            "rate_unit": rate_unit,
            "ramp_up": ramp_up,
            "ramp_down": ramp_down,
            "commitment_type": commitment_type,
            **_governance(
                source_card_ids=source_card_ids,
                candidate_id=candidate_id,
                input_status=input_status,
                human_review_required=human_review_required,
                caveat=caveat,
                migration_source=migration_source,
                executable_input=executable_input,
            ),
        },
    )


def build_process_units(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "process_units.csv")
    rows: list[dict[str, str]] = []
    figure_source = _rel(S44B3_DIR / "s4_4b3_figure_parameter_patch.csv")
    for config_id in [C0, C1]:
        for asset_id, data in FIGURE_LIMITS.items():
            rows.append(
                _process_unit_row(
                    columns,
                    process_id=f"{config_id}__{asset_id}",
                    asset_id=asset_id,
                    configuration_id=config_id,
                    min_rate=data["min"],
                    max_rate=data["max"],
                    rate_unit=data["unit"],
                    source_card_ids=FIGURE_SOURCE_CARDS[asset_id],
                    candidate_id=data["candidate_id"],
                    input_status="development_only",
                    caveat=(
                        "Figure-derived human-confirmed development operating limits; "
                        "not measured Tata truth."
                    ),
                    migration_source=figure_source,
                    executable_input=True,
                )
            )

    rows.extend(
        [
            _process_unit_row(
                columns,
                process_id="C0__coking_plant_2",
                asset_id="coking_plant_2",
                configuration_id=C0,
                min_rate="",
                max_rate="",
                rate_unit="t_coal/h",
                source_card_ids="REPO-S4-4B2-WORKBOOK",
                candidate_id="S44B4_C0_COKING_PLANT_2_STRUCTURE",
                input_status="missing_blocker",
                caveat="Coking Plant 2 is active in C0 topology, but no human-confirmed operating range was migrated.",
                migration_source=_rel(S44B2_COMPILED_REVIEW / "config_components.csv"),
                executable_input=False,
                human_review_required=True,
            ),
            _process_unit_row(
                columns,
                process_id="C0__blast_furnace_7",
                asset_id="blast_furnace_7",
                configuration_id=C0,
                min_rate="",
                max_rate="",
                rate_unit="t_sinter/h",
                source_card_ids="REPO-S4-4B2-WORKBOOK",
                candidate_id="S44B4_C0_BF7_STRUCTURE",
                input_status="missing_blocker",
                caveat="BF7 is active in C0 topology, but no BF7-specific operating range was migrated.",
                migration_source=_rel(S44B2_COMPILED_REVIEW / "config_components.csv"),
                executable_input=False,
                human_review_required=True,
            ),
            _process_unit_row(
                columns,
                process_id="C1_DRP",
                asset_id="NG_DRP",
                configuration_id=C1,
                min_rate="0.7",
                max_rate="1.1",
                rate_unit="pu_of_500_t_pellets_per_h",
                ramp_up="0.1",
                ramp_down="0.1",
                commitment_type="continuous_guardrail",
                source_card_ids="S3_4_GUARDRAIL_BADARINATH_2025;REPO-S4-4B-DEV-INPUTS",
                candidate_id="S44B4_S34_DRP_OPERATING_RANGE",
                input_status="development_only",
                caveat="S3.4 selected DRP guardrail; development-only and not Tata-measured truth.",
                migration_source=_rel(S3_REVIEW_ROOT / "s3_4_eaf_drp_guardrail_dev_inputs.csv"),
                executable_input=True,
            ),
            _process_unit_row(
                columns,
                process_id="C1_EAF",
                asset_id="EAF",
                configuration_id=C1,
                min_rate="0.9",
                max_rate="1.1",
                rate_unit="pu_of_400_t_DRI_per_h",
                commitment_type="semi_continuous_binary_candidate",
                source_card_ids="S3_4_GUARDRAIL_BADARINATH_2025;REPO-S4-4B-DEV-INPUTS",
                candidate_id="S44B4_S34_EAF_OPERATING_RANGE",
                input_status="development_only",
                caveat="S3.4 selected EAF guardrail; development-only and not Tata-measured truth.",
                migration_source=_rel(S3_REVIEW_ROOT / "s3_4_eaf_drp_guardrail_dev_inputs.csv"),
                executable_input=True,
            ),
            _process_unit_row(
                columns,
                process_id="HOT_SLAB_COOLING_DESIGN",
                asset_id="hot_slab_store",
                configuration_id=C1,
                min_rate="",
                max_rate="",
                rate_unit="t_slab/h",
                source_card_ids="REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                candidate_id="S44B4_HOT_TO_COLD_SLAB_DESIGN",
                input_status="deferred_for_modelbuilder",
                caveat="Hot-to-cold slab design migrated for review; S4.4c equations are not changed in this task.",
                migration_source=_rel(S44B3_DIR / "s4_4b3_hot_cold_slab_design.csv"),
                executable_input=False,
            ),
            _process_unit_row(
                columns,
                process_id="HSM_COLD_SLAB_REHEAT_DESIGN",
                asset_id="hot_strip_mill",
                configuration_id=C1,
                min_rate="",
                max_rate="",
                rate_unit="t_slab/h",
                source_card_ids="REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                candidate_id="S44B4_COLD_SLAB_REHEAT_DESIGN",
                input_status="deferred_for_modelbuilder",
                caveat="Cold slab reheating design migrated for review; S4.4c equations are not changed in this task.",
                migration_source=_rel(S44B3_DIR / "s4_4b3_hot_cold_slab_design.csv"),
                executable_input=False,
            ),
        ]
    )
    return _dedupe(rows, ["process_id"])


def build_process_io_coefficients(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "process_io_coefficients.csv")
    rows: list[dict[str, str]] = []

    def add(process_id: str, input_material: str, output_material: str, coefficient: str, unit: str, basis: str, status: str, candidate_id: str, executable: bool) -> None:
        rows.append(
            _row_with_base(
                columns,
                {
                    "process_id": process_id,
                    "input_material": input_material,
                    "output_material": output_material,
                    "coefficient": coefficient,
                    "coefficient_unit": unit,
                    "basis": basis,
                    **_governance(
                        source_card_ids="REPO-S4-4B2-WORKBOOK;REPO-S3-4-GUARDRAIL",
                        candidate_id=candidate_id,
                        input_status=status,
                        human_review_required=status == "missing_blocker",
                        caveat=(
                            "Migrated process coefficient or structural port. "
                            "Validation anchors are not used as coefficients."
                        ),
                        migration_source=(
                            f"{_rel(S44B2_COMPILED_REVIEW / 'link_ports.csv')};"
                            f"{_rel(S3_REVIEW_ROOT / 's3_4_eaf_drp_guardrail_dev_inputs.csv')}"
                        ),
                        executable_input=executable,
                    ),
                },
            )
        )

    structural = [
        ("coking_plant_1", "dry_coal", "coke"),
        ("coking_plant_2", "dry_coal", "coke"),
        ("sintering_plant", "iron_ore", "sinter"),
        ("pelletizing_plant", "iron_ore", "pellets"),
        ("blast_furnace_6", "sinter", "hot_iron"),
        ("blast_furnace_7", "sinter", "hot_iron"),
        ("basic_oxygen_furnace", "hot_iron", "crude_steel"),
        ("continuous_caster_or_slab_conversion", "crude_steel", "slab"),
        ("hot_strip_mill", "slab", "hot_rolled_coil"),
        ("direct_sheet_plant", "hot_rolled_coil", "final_product"),
        ("linde_asu", "electricity", "oxygen"),
        ("WAG_BOILERS_15_16_23_24_mixer", "WAG_blend", "steam"),
        ("Vattenfall_WAG_interface", "WAG_blend", "electricity_interface"),
        ("WAG_flare_spillage", "WAG_blend", "flared_WAG"),
    ]
    for process_id, input_material, output_material in structural:
        add(
            process_id=process_id,
            input_material=input_material,
            output_material=output_material,
            coefficient="",
            unit="",
            basis="structural port from S4.4b2 compiled review; coefficient remains unresolved",
            status="missing_blocker",
            candidate_id=f"S44B4_STRUCTURAL_PORT_{process_id}".upper(),
            executable=False,
        )

    add("C1_DRP", "pellets", "DRI", "0.74", "t_DRI/t_pellets", "S3.4 guardrail DRP yield", "development_only", "S44B4_S34_DRP_PELLETS_TO_DRI", True)
    add("C1_EAF", "DRI", "liquid_steel", "0.95", "t_liquid_steel/t_DRI", "S3.4 guardrail EAF yield", "development_only", "S44B4_S34_EAF_DRI_TO_LIQUID_STEEL", True)
    add("C1_EAF", "scrap", "liquid_steel", "0.2", "t_scrap/t_DRI", "S3.4 diagnostic scrap ratio", "development_only", "S44B4_S34_EAF_SCRAP_RATIO", True)
    add("HOT_SLAB_COOLING_DESIGN", "hot_slab", "cold_slab", "0.50", "fraction_per_hour", "S4.4b4 initial hot-to-cold slab decay design assumption", "deferred_for_modelbuilder", "S44B4_HOT_TO_COLD_DECAY", False)
    add("HSM_COLD_SLAB_REHEAT_DESIGN", "cold_slab", "HSM_slab_feed", "1.0", "t/t", "Cold slabs can feed HSM after reheating", "deferred_for_modelbuilder", "S44B4_COLD_SLAB_REHEAT_PORT", False)
    add("HSM_HOT_SLAB_DIRECT_CHARGE_DESIGN", "hot_slab", "HSM_slab_feed", "1.0", "t/t", "Hot slabs can directly feed HSM", "deferred_for_modelbuilder", "S44B4_HOT_SLAB_DIRECT_CHARGE_PORT", False)
    return _dedupe(rows, ["process_id", "input_material", "output_material"])


def build_process_energy_intensities(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "process_energy_intensities.csv")
    rows = [dict(row) for row in base_tables["process_energy_intensities.csv"].rows]
    for row in rows:
        for column in MIGRATION_COLUMNS:
            row.setdefault(column, "")
        if row.get("input_status") in {"development_only", "selected_development_input_candidate"}:
            row["thesis_usability"] = "false"
            row["codex_may_decide"] = "false"

    def add(process_id: str, carrier: str, direction: str, intensity: str, unit: str, basis: str, status: str, candidate_id: str, executable: bool) -> None:
        rows.append(
            _row_with_base(
                columns,
                {
                    "process_id": process_id,
                    "carrier": carrier,
                    "direction": direction,
                    "intensity": intensity,
                    "intensity_unit": unit,
                    "basis": basis,
                    **_governance(
                        source_card_ids="S3_4_GUARDRAIL_BADARINATH_2025;REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                        candidate_id=candidate_id,
                        input_status=status,
                        caveat="Migrated development energy intensity; not thesis-approved or Tata-measured.",
                        migration_source=(
                            f"{_rel(S3_REVIEW_ROOT / 's3_4_eaf_drp_guardrail_dev_inputs.csv')};"
                            f"{_rel(S44B3_DIR / 's4_4b3_hot_cold_slab_design.csv')}"
                        ),
                        executable_input=executable,
                    ),
                },
            )
        )

    add("C1_DRP", "electricity", "input", "0.1", "MWh/t_pellets", "S3.4 DRP electricity intensity", "development_only", "S44B4_S34_DRP_ELECTRICITY", True)
    add("C1_DRP", "natural_gas", "input", "195", "Nm3/t_pellets", "S3.4 DRP natural gas intensity", "development_only", "S44B4_S34_DRP_NG", True)
    add("C1_DRP", "oxygen", "input", "0.1", "t_O2/t_pellets", "S3.4 DRP oxygen intensity", "development_only", "S44B4_S34_DRP_OXYGEN", True)
    add("C1_EAF", "electricity", "input", "0.5", "MWh/t_DRI", "S3.4 EAF electricity intensity", "development_only", "S44B4_S34_EAF_ELECTRICITY", True)
    add("C1_EAF", "oxygen", "input", "0.05", "t_O2/t_DRI", "S3.4 EAF oxygen ratio", "development_only", "S44B4_S34_EAF_OXYGEN", True)
    add("HSM_COLD_SLAB_REHEAT_DESIGN", "HSM_fuel_gas_blend", "input", "1.20", "GJ/t_cold_slab", "S4.4b4 initial cold slab reheating design assumption", "deferred_for_modelbuilder", "S44B4_COLD_SLAB_REHEAT_ENERGY", False)
    add("HSM_HOT_SLAB_DIRECT_CHARGE_DESIGN", "HSM_fuel_gas_blend", "input", "0.48", "GJ/t_hot_slab", "S4.4b4 hot-slab reheating energy fraction 0.40 of cold slab reheating", "deferred_for_modelbuilder", "S44B4_HOT_SLAB_REHEAT_FRACTION", False)
    return _dedupe(rows, ["process_id", "carrier", "direction"])


def build_process_emission_factors(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "process_emission_factors.csv")
    rows = [dict(row) for row in base_tables["process_emission_factors.csv"].rows]
    for row in rows:
        for column in MIGRATION_COLUMNS:
            row.setdefault(column, "")

    for process_id in ["C0__basic_oxygen_furnace", "C1__basic_oxygen_furnace"]:
        rows.append(
            _row_with_base(
                columns,
                {
                    "process_id": process_id,
                    "emission_scope": "direct_CO2",
                    "factor": "2.15568",
                    "factor_unit": "tCO2/t_BOF_liquid_steel",
                    "basis": "S3 selected calibrated BF-BOF aggregate direct CO2 factor",
                    **_governance(
                        source_card_ids="S33_CAND_001_CALIBRATION_ANCHOR",
                        candidate_id="S44B4_S33_BF_BOF_DIRECT_CO2",
                        input_status="development_only",
                        caveat="S3 calibrated aggregate development factor; not a process-measured Tata emission factor.",
                        migration_source=_rel(S3_REVIEW_ROOT / "s3_3_selected_calibrated_inputs.csv"),
                        executable_input=True,
                    ),
                },
            )
        )
    return _dedupe(rows, ["process_id", "emission_scope"])


def build_buffers_and_stores(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "buffers_and_stores.csv")
    extra_columns = [
        "initial_inventory_value",
        "terminal_inventory_value",
        "terminal_rule_detail",
        "no_free_buffer_battery",
        "shared_capacity_group",
    ]
    for column in extra_columns:
        if column not in columns:
            columns.append(column)
    rows: list[dict[str, str]] = []

    def add(
        *,
        buffer_id: str,
        material: str,
        configuration_id: str,
        capacity: str,
        capacity_unit: str,
        initial: str,
        terminal: str,
        status: str,
        source_card_ids: str,
        candidate_id: str,
        caveat: str,
        migration_source: str,
        executable: bool,
        human_review: bool = False,
        shared_capacity_group: str = "",
        loss_rate: str = "0",
    ) -> None:
        rows.append(
            _row_with_base(
                columns,
                {
                    "buffer_id": buffer_id,
                    "material": material,
                    "configuration_id": configuration_id,
                    "capacity": capacity,
                    "capacity_unit": capacity_unit,
                    "initial_rule": f"fixed_initial_{initial}" if initial not in {"", "zero_for_smoke"} else initial,
                    "terminal_rule": f"terminal_equality_{terminal}" if terminal else "terminal_equality",
                    "loss_rate": loss_rate,
                    "initial_inventory_value": initial if initial != "zero_for_smoke" else "0",
                    "terminal_inventory_value": terminal,
                    "terminal_rule_detail": "terminal_equality",
                    "no_free_buffer_battery": "true",
                    "shared_capacity_group": shared_capacity_group,
                    **_governance(
                        source_card_ids=source_card_ids,
                        candidate_id=candidate_id,
                        input_status=status,
                        human_review_required=human_review,
                        caveat=caveat,
                        migration_source=migration_source,
                        executable_input=executable,
                    ),
                },
            )
        )

    figure_source = _rel(S44B3_DIR / "s4_4b3_figure_parameter_patch.csv")
    for config_id in [C0, C1]:
        add(
            buffer_id=f"{config_id}__hot_iron_store",
            material="hot_iron",
            configuration_id=config_id,
            capacity="500",
            capacity_unit="t_hot_iron",
            initial="250",
            terminal="250",
            status="development_only",
            source_card_ids=FIGURE_SOURCE_CARDS["hot_iron_store"],
            candidate_id="CAND_S44B3_FIG65_HOT_IRON_STORE_CAP_T",
            caveat="Figure-derived human-confirmed development store capacity with 50/50 terminal policy; not Tata-measured truth.",
            migration_source=figure_source,
            executable=True,
        )
        add(
            buffer_id=f"{config_id}__oxygen_store",
            material="oxygen",
            configuration_id=config_id,
            capacity="100",
            capacity_unit="t_O2",
            initial="50",
            terminal="50",
            status="development_only",
            source_card_ids=FIGURE_SOURCE_CARDS["oxygen_store"],
            candidate_id="CAND_S44B3_FIG67_OXYGEN_STORE_CAP_T",
            caveat="Figure-derived human-confirmed development oxygen capacity with 50/50 terminal policy; not Tata-measured truth.",
            migration_source=figure_source,
            executable=True,
        )
        add(
            buffer_id=f"{config_id}__hot_slab_store",
            material="hot_slab",
            configuration_id=config_id,
            capacity="25000",
            capacity_unit="t_slab_shared_total",
            initial="0",
            terminal="0",
            status="deferred_for_modelbuilder",
            source_card_ids=FIGURE_SOURCE_CARDS["slab_store"],
            candidate_id="S44B4_HOT_SLAB_STORE_DESIGN",
            caveat=(
                "Hot slab design store shares total 25000 t slab capacity with cold slab store; "
                "initial and terminal hot inventory are zero to avoid free initial thermal energy."
            ),
            migration_source=f"{figure_source};{_rel(S44B3_DIR / 's4_4b3_hot_cold_slab_design.csv')}",
            executable=False,
            shared_capacity_group=f"{config_id}__total_slab_capacity_25000",
        )
        add(
            buffer_id=f"{config_id}__cold_slab_store",
            material="cold_slab",
            configuration_id=config_id,
            capacity="25000",
            capacity_unit="t_slab_shared_total",
            initial="12500",
            terminal="12500",
            status="deferred_for_modelbuilder",
            source_card_ids=FIGURE_SOURCE_CARDS["slab_store"],
            candidate_id="S44B4_COLD_SLAB_STORE_DESIGN",
            caveat=(
                "Cold slab design store shares total 25000 t slab capacity with hot slab store; "
                "initial and terminal inventory preserve total 50 percent slab storage policy."
            ),
            migration_source=f"{figure_source};{_rel(S44B3_DIR / 's4_4b3_hot_cold_slab_design.csv')}",
            executable=False,
            shared_capacity_group=f"{config_id}__total_slab_capacity_25000",
        )

    add(
        buffer_id="C1_DRI_BUFFER",
        material="DRI",
        configuration_id=C1,
        capacity="17760",
        capacity_unit="t_DRI",
        initial="zero_for_smoke",
        terminal="0",
        status="development_only",
        source_card_ids="STEEL-SC-0021;S3_4_GUARDRAIL_BADARINATH_2025;REPO-S4-4B-DEV-INPUTS",
        candidate_id="S44B4_S34_DRI_BUFFER_17760T",
        caveat=(
            "S3.4 solved DRI buffer policy retained despite 50/50 default conflict; "
            "zero initial inventory is required by the existing S4.4c smoke/regression setup."
        ),
        migration_source=_rel(S3_REVIEW_ROOT / "s3_4_eaf_drp_guardrail_dev_inputs.csv"),
        executable=True,
    )

    for config_id in [C0, C1]:
        for material, buffer_id in [
            ("coke", "coke_store"),
            ("sinter", "sinter_store"),
            ("pellets", "pellets_store"),
        ]:
            add(
                buffer_id=f"{config_id}__{buffer_id}",
                material=material,
                configuration_id=config_id,
                capacity="",
                capacity_unit="t",
                initial="",
                terminal="",
                status="missing_blocker",
                source_card_ids="REPO-S4-4B2-WORKBOOK",
                candidate_id=f"S44B4_{config_id}_{buffer_id.upper()}_STRUCTURE",
                caveat=f"{material} store structure migrated, but no governed capacity exists; not executable.",
                migration_source=_rel(S44B2_COMPILED_REVIEW / "stores.csv"),
                executable=False,
                human_review=True,
            )
    return _dedupe(rows, ["buffer_id"])


def build_wag_generation_coefficients(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "wag_generation_coefficients.csv")
    rows: list[dict[str, str]] = []
    definitions = [
        ("blast_furnace_6", "BFG", "bfg_generation_nm3_per_t_hot_metal", C0),
        ("blast_furnace_7", "BFG", "bfg_generation_nm3_per_t_hot_metal", C0),
        ("coking_plant_1", "COG", "cog_generation_m3_per_t_dry_coal", C0),
        ("coking_plant_2", "COG", "cog_generation_m3_per_t_dry_coal", C0),
        ("basic_oxygen_furnace", "BOFG", "bofg_generation_nm3_per_t_liquid_steel", C0),
        ("blast_furnace_6", "BFG", "bfg_generation_nm3_per_t_hot_metal", C1),
        ("coking_plant_1", "COG", "cog_generation_m3_per_t_dry_coal", C1),
        ("basic_oxygen_furnace", "BOFG", "bofg_generation_nm3_per_t_liquid_steel", C1),
    ]
    for process_id, carrier, key, config_id in definitions:
        value = S3_SELECTED_VALUES[key]
        rows.append(
            _row_with_base(
                columns,
                {
                    "process_id": process_id,
                    "wag_carrier": carrier,
                    "coefficient": value["central"],
                    "coefficient_unit": value["unit"],
                    "basis": value["basis"],
                    "configuration_id": config_id,
                    **_governance(
                        source_card_ids="S33_CAND_001_CALIBRATION_ANCHOR;REPO-S3-WAG-BOUNDARY",
                        candidate_id=f"S44B4_{config_id}_{process_id}_{carrier}_GEN",
                        input_status="development_only",
                        caveat="S3 selected calibrated WAG coefficient; development-only and not Tata-measured truth.",
                        migration_source=(
                            f"{_rel(S3_REVIEW_ROOT / 's3_3_selected_calibrated_inputs.csv')};"
                            f"{_rel(S2_ROOT / 's2_to_s3/s3_wag_accounting_boundary_register.csv')}"
                        ),
                        executable_input=True,
                    ),
                },
            )
        )
    return _dedupe(rows, ["process_id", "wag_carrier", "configuration_id"])


def build_wag_sink_eligibility(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "wag_sink_eligibility.csv")
    rows: list[dict[str, str]] = []
    sinks = [
        ("WAG_COK1_mixer", "1_process_first", "none"),
        ("WAG_HSM_mixer", "1_process_first", "none"),
        ("WAG_BOILERS_15_16_23_24_mixer", "2_steam_utility", "annual_allocation_context_only"),
        ("WAG_BOILER_41_mixer", "2_steam_utility", "annual_allocation_context_only"),
        ("Vattenfall_WAG_interface", "3_power_interface", "interface_only_no_dispatch_truth"),
        ("WAG_flare_spillage", "4_spillage", "explicit_spillage_no_value"),
    ]
    for config_id in [C0, C1]:
        for carrier in ["BFG", "COG", "BOFG"]:
            for sink, priority, treatment in sinks:
                rows.append(
                    _row_with_base(
                        columns,
                        {
                            "configuration_id": config_id,
                            "wag_carrier": carrier,
                            "sink_asset": sink,
                            "eligible": "true",
                            "priority": priority,
                            "flaring_allowed": _as_bool_text(sink == "WAG_flare_spillage"),
                            "cost_treatment": treatment,
                            **_governance(
                                source_card_ids="REPO-S3-WAG-BOUNDARY;REPO-S3-WAG-ALLOCATION",
                                candidate_id=f"S44B4_{config_id}_{carrier}_{sink}_ELIGIBILITY",
                                input_status="development_only",
                                caveat="S3 process-first WAG hierarchy migrated; no direct WAG market valuation.",
                                migration_source=(
                                    f"{_rel(S2_ROOT / 's2_to_s3/s3_wag_accounting_boundary_register.csv')};"
                                    f"{_rel(S2_ROOT / 's2_to_s3/s3_wag_allocation_mode_register.csv')}"
                                ),
                                executable_input=True,
                            ),
                        },
                    )
                )
    return _dedupe(rows, ["configuration_id", "wag_carrier", "sink_asset"])


def build_utility_demands(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "utility_demands.csv")
    rows: list[dict[str, str]] = []
    utility_rows = [
        ("combined_boiler_steam_utility_sink", "steam_utility", "annual_context", "6.0", "PJ/y", "S3.3j governed combined boiler/steam utility sink"),
        ("boiler_steam_ng_placeholder", "natural_gas", "annual_allocation_placeholder", "3.0", "PJ/y", "S3.3j placeholder internal split"),
        ("boiler_steam_wag_placeholder", "WAG_blend", "annual_allocation_placeholder", "3.0", "PJ/y", "S3.3j placeholder internal split"),
    ]
    for config_id in [C0, C1]:
        for asset_id, carrier, demand_type, value, unit, basis in utility_rows:
            rows.append(
                _row_with_base(
                    columns,
                    {
                        "configuration_id": config_id,
                        "asset_id": asset_id,
                        "utility_carrier": carrier,
                        "demand_type": demand_type,
                        "value": value,
                        "unit": unit,
                        "allocation_basis": basis,
                        **_governance(
                            source_card_ids="S33J-ASSUMP-003;S33J-ASSUMP-004;S33J-ASSUMP-005",
                            candidate_id=f"S44B4_{config_id}_{asset_id}",
                            input_status="reporting_only",
                            caveat="S3.3j annual utility allocation context only; not hidden hourly dispatch truth.",
                            migration_source=_rel(S3_REVIEW_ROOT / "s3_3j_final_case_assumption_register.csv"),
                            executable_input=False,
                        ),
                    },
                )
            )
    return _dedupe(rows, ["configuration_id", "asset_id", "utility_carrier"])


def build_utility_conversion_assets(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "utility_conversion_assets.csv")
    rows: list[dict[str, str]] = []
    assets = [
        ("boiler_steam_ng_placeholder", "natural_gas", "steam", "", "", "PJ/y_context", "false"),
        ("boiler_steam_wag_placeholder", "WAG_blend", "steam", "", "", "PJ/y_context", "false"),
        ("Vattenfall_WAG_interface", "WAG_blend", "electricity_interface", "0.3715", "", "fraction", "false"),
        ("WAG_flare_spillage", "WAG_blend", "flared_WAG", "", "", "GJ", "false"),
    ]
    for asset_id, input_carrier, output_carrier, efficiency, capacity, unit, dispatchable in assets:
        rows.append(
            _row_with_base(
                columns,
                {
                    "asset_id": asset_id,
                    "input_carrier": input_carrier,
                    "output_carrier": output_carrier,
                    "efficiency": efficiency,
                    "capacity": capacity,
                    "unit": unit,
                    "dispatchable": dispatchable,
                    **_governance(
                        source_card_ids="REPO-S3-WAG-BOUNDARY;S33_CAND_001_CALIBRATION_ANCHOR",
                        candidate_id=f"S44B4_UTILITY_{asset_id}",
                        input_status="development_only" if asset_id == "Vattenfall_WAG_interface" else "reporting_only",
                        caveat="Utility structure migrated from S3; Vattenfall is an interface only and no WAG market value is assigned.",
                        migration_source=(
                            f"{_rel(S2_ROOT / 's2_to_s3/s3_energy_accounting_asset_eligibility_register.csv')};"
                            f"{_rel(S3_REVIEW_ROOT / 's3_3_selected_calibrated_inputs.csv')}"
                        ),
                        executable_input=asset_id == "Vattenfall_WAG_interface",
                    ),
                },
            )
        )
    return _dedupe(rows, ["asset_id"])


def build_external_supply_costs(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "external_supply_costs.csv")
    rows = []
    for row in base_tables["external_supply_costs.csv"].rows:
        new_row = _row_with_base(columns, row)
        new_row.update(
            _governance(
                source_card_ids=row.get("source_card_ids", "REPO-S4-4B-DEV-INPUTS"),
                candidate_id=row.get("candidate_id", f"S44B4_COST_{row.get('carrier_or_material', 'UNKNOWN')}"),
                input_status="deferred_for_s4_4d",
                evidence_strength=row.get("evidence_strength", "development_candidate"),
                human_review_required=row.get("human_review_required", "false").lower() == "true",
                caveat=(
                    row.get("caveat", "")
                    + " S4.4b4 carries cost context only; no DA price-taking objective or economics migration is activated."
                ).strip(),
                migration_source=_rel(BASE_INPUT_DIR / "external_supply_costs.csv"),
                executable_input=False,
            )
        )
        new_row["active_in_objective"] = "false"
        rows.append(new_row)
    return _dedupe(rows, ["carrier_or_material"])


def build_market_price_inputs(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "market_price_inputs.csv")
    rows = []
    for row in base_tables["market_price_inputs.csv"].rows:
        new_row = _row_with_base(columns, row)
        new_row.update(
            _governance(
                source_card_ids=row.get("source_card_ids", "REPO-S4-4B-DEV-INPUTS"),
                candidate_id=row.get("candidate_id", f"S44B4_MARKET_{row.get('market', 'UNKNOWN')}"),
                input_status="deferred_for_later_market_stage",
                evidence_strength=row.get("evidence_strength", "governed_reference"),
                caveat=(
                    row.get("caveat", "")
                    + " Price file retained only to satisfy input contract checks; S4.4b4 does not activate DA optimisation."
                ).strip(),
                migration_source=_rel(BASE_INPUT_DIR / "market_price_inputs.csv"),
                executable_input=False,
            )
        )
        rows.append(new_row)
    return _dedupe(rows, ["market"])


def build_production_targets(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "production_targets.csv")
    rows = []
    for row in base_tables["production_targets.csv"].rows:
        if row.get("configuration_id") not in {C0, C1}:
            continue
        new_row = _row_with_base(columns, row)
        new_row.update(
            _governance(
                source_card_ids=row.get("source_card_ids", "REPO-S4-4B-DEV-INPUTS"),
                candidate_id=row.get("candidate_id", f"S44B4_TARGET_{row.get('configuration_id')}"),
                input_status="development_only",
                evidence_strength=row.get("evidence_strength", "development_candidate"),
                caveat=(
                    row.get("caveat", "")
                    + " Hard physical target retained for static physical regression only; not an economic product-revenue term."
                ).strip(),
                migration_source=_rel(BASE_INPUT_DIR / "production_targets.csv"),
                executable_input=True,
            )
        )
        new_row["hard_target"] = "true"
        rows.append(new_row)
    return _dedupe(rows, ["configuration_id", "target_id"])


def build_validation_anchors(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "validation_anchors.csv")
    rows = [dict(row) for row in base_tables["validation_anchors.csv"].rows]
    for row in rows:
        for column in MIGRATION_COLUMNS:
            row.setdefault(column, "")
        row["executable_input"] = "false"
        row["input_status"] = "validation_target" if row.get("input_status") == "validation_target" else "reporting_only"
        row["thesis_usability"] = "false"

    anchors = [
        (C0, "S3_3j_c0_mean_abs_error_pct", "1.430975422496251", "pct", "S3.3j final metric summary"),
        (C0, "gross_electricity", "3.056762062201403", "TWh/y", "S3.3j final C0 regression result"),
        (C0, "wag_electricity", "2.8366844204337047", "TWh/y", "S3.3j final C0 regression result"),
        (C1, "gross_electricity", "5.189065138677267", "TWh/y", "S3.3j final C1 boundary-aligned result"),
        (C1, "wag_electricity", "1.2047979890321883", "TWh/y", "S3.3j final C1 boundary-aligned result"),
        (C1, "bf_bof_share", "0.5033645161290325", "fraction", "S3.3j final C1 boundary-aligned result"),
        (C1, "combined_boiler_steam_utility_sink", "6.0", "PJ/y", "S3.3j final assumption register"),
    ]
    for config_id, metric, value, unit, locator in anchors:
        rows.append(
            _row_with_base(
                columns,
                {
                    "configuration_id": config_id,
                    "metric": metric,
                    "anchor_value": value,
                    "anchor_unit": unit,
                    "time_basis": "annual" if unit.endswith("/y") or unit in {"TWh/y", "PJ/y"} else "case",
                    "comparison_role": "validation_only",
                    "locator": locator,
                    **_governance(
                        source_card_ids="REPO-S3-3J-FINAL",
                        candidate_id=f"S44B4_ANCHOR_{config_id}_{metric}",
                        input_status="validation_target",
                        evidence_strength="validation_anchor",
                        caveat="S3.3j final validation anchor migrated for comparison only; not an executable model coefficient.",
                        migration_source=(
                            f"{_rel(S3_REVIEW_ROOT / 's3_3j_final_metric_summary.csv')};"
                            f"{_rel(S3_REVIEW_ROOT / 's3_3j_final_c0_regression_results.csv')};"
                            f"{_rel(S3_REVIEW_ROOT / 's3_3j_final_c1_boundary_aligned_results.csv')}"
                        ),
                        executable_input=False,
                    ),
                },
            )
        )
    return _dedupe(rows, ["configuration_id", "metric"])


def build_policy_modes(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "policy_modes.csv")
    rows = []
    for row in base_tables["policy_modes.csv"].rows:
        new_row = _row_with_base(columns, row)
        mode = row.get("policy_mode", "")
        status = "development_only" if mode == "price_naive_static_physical_regression" else "deferred_for_later_market_stage"
        new_row.update(
            _governance(
                source_card_ids=row.get("source_card_ids", "REPO-S4-4B-DEV-INPUTS"),
                candidate_id=row.get("candidate_id", f"S44B4_POLICY_{row.get('policy_id')}"),
                input_status=status,
                evidence_strength=row.get("evidence_strength", "policy_guardrail"),
                caveat=(
                    row.get("caveat", "")
                    + " S4.4b4 does not activate bidding, stochasticity, CVaR, DA economics, or product revenue."
                ).strip(),
                migration_source=_rel(BASE_INPUT_DIR / "policy_modes.csv"),
                executable_input=mode == "price_naive_static_physical_regression",
            )
        )
        rows.append(new_row)
    return _dedupe(rows, ["policy_id"])


def build_solver_and_horizon_config(base_tables: dict[str, CsvTable]) -> list[dict[str, str]]:
    columns = _table_columns(base_tables, "solver_and_horizon_config.csv")
    rows = []
    for row in base_tables["solver_and_horizon_config.csv"].rows:
        new_row = _row_with_base(columns, row)
        new_row.update(
            _governance(
                source_card_ids=row.get("source_card_ids", "REPO-S4-4B-DEV-INPUTS"),
                candidate_id=row.get("candidate_id", f"S44B4_SOLVER_{row.get('run_profile_id')}"),
                input_status="development_only",
                evidence_strength=row.get("evidence_strength", "policy_guardrail"),
                caveat=(
                    row.get("caveat", "")
                    + " S4.4b4 keeps static physical profile only; no market/stochastic run is introduced."
                ).strip(),
                migration_source=_rel(BASE_INPUT_DIR / "solver_and_horizon_config.csv"),
                executable_input=True,
            )
        )
        rows.append(new_row)
    return _dedupe(rows, ["run_profile_id"])


def build_migrated_tables(base_tables: dict[str, CsvTable]) -> dict[str, list[dict[str, str]]]:
    return {
        "configuration_assets.csv": build_configuration_assets(base_tables),
        "process_units.csv": build_process_units(base_tables),
        "process_io_coefficients.csv": build_process_io_coefficients(base_tables),
        "process_energy_intensities.csv": build_process_energy_intensities(base_tables),
        "process_emission_factors.csv": build_process_emission_factors(base_tables),
        "buffers_and_stores.csv": build_buffers_and_stores(base_tables),
        "wag_generation_coefficients.csv": build_wag_generation_coefficients(base_tables),
        "wag_sink_eligibility.csv": build_wag_sink_eligibility(base_tables),
        "utility_demands.csv": build_utility_demands(base_tables),
        "utility_conversion_assets.csv": build_utility_conversion_assets(base_tables),
        "external_supply_costs.csv": build_external_supply_costs(base_tables),
        "market_price_inputs.csv": build_market_price_inputs(base_tables),
        "production_targets.csv": build_production_targets(base_tables),
        "validation_anchors.csv": build_validation_anchors(base_tables),
        "policy_modes.csv": build_policy_modes(base_tables),
        "solver_and_horizon_config.csv": build_solver_and_horizon_config(base_tables),
    }


def _patch_pypsa_review_table(name: str, table: CsvTable) -> CsvTable:
    rows = [dict(row) for row in table.rows]
    columns = list(table.fieldnames)
    if name == "config_components.csv":
        for row in rows:
            if row.get("configuration_id") in {
                "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
                "C1_phase1_BF_BOF_plus_DRP_EAF",
            }:
                row["configuration_id"] = C1
                component = row.get("component_id", "")
                if component in {"blast_furnace_7", "coking_plant_2"}:
                    row["active"] = "false"
                    row["retained_added_closed"] = "closed"
                    row["selected_model_status"] = "inactive_human_selected_default"
                    row["human_review_required"] = "false"
                    row["caveat"] = "S4.4b4 applies human-selected C1 closure: BF7 and KGF2 inactive."
                if component in {"blast_furnace_6", "coking_plant_1"}:
                    row["active"] = "true"
                    row["retained_added_closed"] = "retained"
                    row["human_review_required"] = "false"
                    row["caveat"] = "S4.4b4 applies human-selected C1 retention: BF6 and KGF1 active."
    elif name == "stores.csv":
        for row in rows:
            store_id = row.get("store_id", "")
            if store_id == "hot_metal_buffer":
                row.update(
                    {
                        "capacity_central": "500",
                        "capacity_unit": "t_hot_iron",
                        "initial_inventory_rule": "250",
                        "terminal_inventory_rule": "terminal_equality_250",
                        "selected_model_capacity_treatment": "finite_candidate_bound",
                        "executable_status": "development_review",
                        "source_card_ids": FIGURE_SOURCE_CARDS["hot_iron_store"],
                        "source_locator": "Athanasiadis Figure 65",
                        "value_status": "candidate",
                        "human_review_required": "false",
                        "caveat": "Figure-derived human-confirmed development capacity; not Tata-measured truth.",
                    }
                )
            if store_id == "oxygen_buffer":
                row.update(
                    {
                        "capacity_central": "100",
                        "capacity_unit": "t_O2",
                        "initial_inventory_rule": "50",
                        "terminal_inventory_rule": "terminal_equality_50",
                        "selected_model_capacity_treatment": "finite_candidate_bound",
                        "executable_status": "development_review",
                        "source_card_ids": FIGURE_SOURCE_CARDS["oxygen_store"],
                        "source_locator": "Athanasiadis Figure 67",
                        "value_status": "candidate",
                        "human_review_required": "false",
                        "caveat": "Figure-derived human-confirmed development capacity; not Tata-measured truth.",
                    }
                )
        template = {column: "" for column in columns}
        rows.extend(
            [
                {
                    **template,
                    "store_id": "hot_slab_store",
                    "bus_id": "hot_slabs_bus",
                    "store_class": "thermal_state_buffer",
                    "physical_asset_exists": "true",
                    "selected_hourly_store": "deferred",
                    "capacity_central": "25000",
                    "capacity_unit": "t_slab_shared_total",
                    "initial_inventory_rule": "0",
                    "terminal_inventory_rule": "terminal_equality_0",
                    "cyclic": "false",
                    "standing_loss": "0.50_per_hour_design_decay",
                    "max_residence_time": "2",
                    "hot_cold_state_relevance": "yes",
                    "flexibility_role": "design-only hot slab state",
                    "executable_status": "deferred_for_modelbuilder",
                    "source_card_ids": FIGURE_SOURCE_CARDS["slab_store"],
                    "source_locator": "Athanasiadis Figure 66; S4.4b4 hot/cold design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Hot slab starts and ends at zero; shared total slab capacity must be enforced later.",
                },
                {
                    **template,
                    "store_id": "cold_slab_store",
                    "bus_id": "cold_slabs_bus",
                    "store_class": "physical_inventory_buffer",
                    "physical_asset_exists": "true",
                    "selected_hourly_store": "deferred",
                    "capacity_central": "25000",
                    "capacity_unit": "t_slab_shared_total",
                    "initial_inventory_rule": "12500",
                    "terminal_inventory_rule": "terminal_equality_12500",
                    "cyclic": "false",
                    "standing_loss": "0",
                    "hot_cold_state_relevance": "yes",
                    "flexibility_role": "design-only cold slab state",
                    "executable_status": "deferred_for_modelbuilder",
                    "source_card_ids": FIGURE_SOURCE_CARDS["slab_store"],
                    "source_locator": "Athanasiadis Figure 66; S4.4b4 hot/cold design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Cold slab starts and ends at 12500 t; shared total slab capacity must be enforced later.",
                },
            ]
        )
        rows = _dedupe(rows, ["store_id"])
    elif name == "links.csv":
        template = {column: "" for column in columns}
        rows.extend(
            [
                {
                    **template,
                    "link_id": "hot_slab_cooling_design",
                    "display_name": "Hot slab cooling design",
                    "process_family": "hot_cold_slab_design",
                    "physical_or_interface": "physical_design",
                    "selected_component_type": "Link",
                    "throughput_basis_bus": "hot_slabs_bus",
                    "throughput_basis_unit": "t_slab/h",
                    "continuous_batch_or_semi_continuous": "continuous_design",
                    "controllable": "false",
                    "committable_candidate": "false",
                    "physical_asset_exists": "true",
                    "source_model_representation": "S4.4b4 design-only",
                    "selected_hourly_model_representation": "deferred",
                    "component_control_class": "thermal_state_transition",
                    "executable_status": "deferred_for_modelbuilder",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only; S4.4c equations are not changed.",
                },
                {
                    **template,
                    "link_id": "cold_slab_reheating_design",
                    "display_name": "Cold slab reheating design",
                    "process_family": "hot_cold_slab_design",
                    "physical_or_interface": "physical_design",
                    "selected_component_type": "Link",
                    "throughput_basis_bus": "cold_slabs_bus",
                    "throughput_basis_unit": "t_slab/h",
                    "continuous_batch_or_semi_continuous": "continuous_design",
                    "controllable": "true",
                    "committable_candidate": "false",
                    "physical_asset_exists": "true",
                    "source_model_representation": "S4.4b4 design-only",
                    "selected_hourly_model_representation": "deferred",
                    "component_control_class": "thermal_state_transition",
                    "executable_status": "deferred_for_modelbuilder",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only; S4.4c equations are not changed.",
                },
            ]
        )
        rows = _dedupe(rows, ["link_id"])
    elif name == "link_ports.csv":
        template = {column: "" for column in columns}
        rows.extend(
            [
                {
                    **template,
                    "port_id": "hot_slab_cooling_design__in_hot_slab",
                    "link_id": "hot_slab_cooling_design",
                    "port_order": "0",
                    "bus_id": "hot_slabs_bus",
                    "direction": "input",
                    "coefficient_central": "1.0",
                    "coefficient_unit": "t/t",
                    "coefficient_basis": "hot slab thermal state transition input",
                    "sign_convention": "positive_input_consumption",
                    "required_or_optional": "required",
                    "physical_material_or_energy": "material",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only.",
                },
                {
                    **template,
                    "port_id": "hot_slab_cooling_design__out_cold_slab",
                    "link_id": "hot_slab_cooling_design",
                    "port_order": "1",
                    "bus_id": "cold_slabs_bus",
                    "direction": "output",
                    "coefficient_central": "1.0",
                    "coefficient_unit": "t/t",
                    "coefficient_basis": "mass-preserving cooled slab output",
                    "sign_convention": "positive_output_production",
                    "required_or_optional": "required",
                    "physical_material_or_energy": "material",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only.",
                },
                {
                    **template,
                    "port_id": "cold_slab_reheating_design__in_cold_slab",
                    "link_id": "cold_slab_reheating_design",
                    "port_order": "0",
                    "bus_id": "cold_slabs_bus",
                    "direction": "input",
                    "coefficient_central": "1.0",
                    "coefficient_unit": "t/t",
                    "coefficient_basis": "cold slab reheating input",
                    "sign_convention": "positive_input_consumption",
                    "required_or_optional": "required",
                    "physical_material_or_energy": "material",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only.",
                },
                {
                    **template,
                    "port_id": "cold_slab_reheating_design__in_fuel",
                    "link_id": "cold_slab_reheating_design",
                    "port_order": "1",
                    "bus_id": "HSM_fuel_gas_blend_bus",
                    "direction": "input",
                    "coefficient_central": "1.20",
                    "coefficient_unit": "GJ/t_cold_slab",
                    "coefficient_basis": "S4.4b4 cold slab reheating design assumption",
                    "sign_convention": "positive_input_consumption",
                    "required_or_optional": "required",
                    "physical_material_or_energy": "energy",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only.",
                },
                {
                    **template,
                    "port_id": "cold_slab_reheating_design__out_hsm_feed",
                    "link_id": "cold_slab_reheating_design",
                    "port_order": "2",
                    "bus_id": "HSM_slab_feed_bus",
                    "direction": "output",
                    "coefficient_central": "1.0",
                    "coefficient_unit": "t/t",
                    "coefficient_basis": "reheated HSM slab feed output",
                    "sign_convention": "positive_output_production",
                    "required_or_optional": "required",
                    "physical_material_or_energy": "material",
                    "source_card_ids": "REPO-S4-4B3-HOT-COLD-SLAB-DESIGN",
                    "source_locator": "S4.4b4 initial hot/cold slab design",
                    "value_status": "candidate",
                    "source_status": "candidate",
                    "human_review_required": "false",
                    "caveat": "Design snapshot only.",
                },
            ]
        )
        rows = _dedupe(rows, ["port_id"])
    return CsvTable(rows=rows, fieldnames=columns)


def write_pypsa_review_snapshots() -> None:
    PYPSA_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for name in PYPSA_REVIEW_TABLES:
        source = S44B2_COMPILED_REVIEW / name
        table = _read_csv(source)
        patched = _patch_pypsa_review_table(name, table)
        _write_csv(PYPSA_REVIEW_DIR / name, patched.rows, patched.fieldnames)


def build_mapping_rows(migrated_tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = []
    for table_name, rows_in_table in migrated_tables.items():
        for row in rows_in_table:
            identifier = (
                row.get("process_id")
                or row.get("buffer_id")
                or row.get("asset_id")
                or row.get("carrier_or_material")
                or row.get("metric")
                or row.get("policy_id")
                or row.get("run_profile_id")
                or row.get("target_id")
                or row.get("market")
            )
            rows.append(
                {
                    "target_table": table_name,
                    "target_row_id": identifier,
                    "configuration_id": row.get("configuration_id", ""),
                    "source_card_ids": row.get("source_card_ids", ""),
                    "candidate_id": row.get("candidate_id", ""),
                    "input_status": row.get("input_status", ""),
                    "executable_input": row.get("executable_input", ""),
                    "migration_source_artifacts": row.get("migration_source_artifacts", ""),
                    "caveat": row.get("caveat", ""),
                }
            )
    return rows


def build_manifest_rows(migrated_tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = []
    for table_name, table_rows in migrated_tables.items():
        for idx, row in enumerate(table_rows, start=1):
            rows.append(
                {
                    "table_name": table_name,
                    "row_number": str(idx),
                    "row_id": (
                        row.get("process_id")
                        or row.get("buffer_id")
                        or row.get("asset_id")
                        or row.get("carrier_or_material")
                        or row.get("metric")
                        or row.get("policy_id")
                        or row.get("run_profile_id")
                        or row.get("target_id")
                        or row.get("market")
                        or str(idx)
                    ),
                    "configuration_id": row.get("configuration_id", ""),
                    "input_status": row.get("input_status", ""),
                    "executable_input": row.get("executable_input", ""),
                    "thesis_usability": row.get("thesis_usability", ""),
                    "human_review_required": row.get("human_review_required", ""),
                    "source_card_ids": row.get("source_card_ids", ""),
                    "candidate_id": row.get("candidate_id", ""),
                    "migration_source_artifacts": row.get("migration_source_artifacts", ""),
                    "caveat": row.get("caveat", ""),
                }
            )
    return rows


def build_not_migrated_rows() -> list[dict[str, str]]:
    return [
        {
            "item": "Coking Plant 2 operating limits",
            "reason": "No human-confirmed CP2 figure value or selected S3 tested value found.",
            "status": "missing_blocker",
            "next_action": "Human review or source-card-backed candidate required before C0 full execution.",
        },
        {
            "item": "BF7 operating limits",
            "reason": "No BF7-specific migrated operating range; BF7 inactive in C1 but active in C0.",
            "status": "missing_blocker",
            "next_action": "Human review or source-card-backed candidate required before C0 full execution.",
        },
        {
            "item": "Coke/sinter/pellet store capacities",
            "reason": "Store structures exist, but governed capacities are not available.",
            "status": "missing_blocker",
            "next_action": "Add source-card-backed capacities or disable as non-flexible transfer states.",
        },
        {
            "item": "Full C0 material conversion chain",
            "reason": "S4.4b4 does not invent missing conversion coefficients; validation anchors are not used as coefficients.",
            "status": "deferred",
            "next_action": "Source-backed coefficients or explicit calibrated development assumptions are needed.",
        },
        {
            "item": "Hot/cold slab equations",
            "reason": "Design rows are migrated, but S4.4c modelbuilder is not changed in this task.",
            "status": "deferred_for_modelbuilder",
            "next_action": "Implement and test linear hot/cold slab equations in S4.4c later.",
        },
        {
            "item": "DA economics and price-taking objective",
            "reason": "Forbidden for S4.4b4 physical migration.",
            "status": "not_migrated",
            "next_action": "Reopen only in S4.4d/economic layer after physical rerun.",
        },
    ]


def build_unresolved_inputs() -> list[dict[str, str]]:
    return [
        {
            "unresolved_input": "C0 full executable BF-BOF route",
            "severity": "limits_full_C0_rerun",
            "details": "C0 topology is migrated, but CP2/BF7 limits and several conversion coefficients remain missing.",
        },
        {
            "unresolved_input": "Coke, sinter, pellet finite store capacities",
            "severity": "prevents_unbounded_storage_execution",
            "details": "Rows are present as physical structure with missing_blocker capacity.",
        },
        {
            "unresolved_input": "Hot/cold slab coupled capacity equation",
            "severity": "deferred_for_modelbuilder",
            "details": "S4.4b4 records total capacity and initial/terminal design; S4.4c equations remain disabled.",
        },
        {
            "unresolved_input": "S3.3j utility sink hourly representation",
            "severity": "reporting_only",
            "details": "6 PJ/y combined utility sink and 3/3 split are annual allocation context, not hourly dispatch truth.",
        },
    ]


def build_component_coverage() -> list[dict[str, str]]:
    return [
        {"component_family": "carriers", "coverage_status": "migrated_review_snapshot", "details": "BFG, COG, BOFG retained separately."},
        {"component_family": "buses", "coverage_status": "migrated_review_snapshot", "details": "S4.4b2 compiled buses copied to S4.4b4 review."},
        {"component_family": "links", "coverage_status": "migrated_with_deferred_hot_cold_additions", "details": "Process links copied; hot/cold design links added as deferred."},
        {"component_family": "link_ports", "coverage_status": "migrated_with_deferred_hot_cold_additions", "details": "Ports copied; hot/cold ports added."},
        {"component_family": "stores", "coverage_status": "migrated_and_patched", "details": "Hot iron, slab, oxygen, DRI buffer policies patched."},
        {"component_family": "loads", "coverage_status": "migrated_review_snapshot", "details": "Residual loads retained as review snapshot."},
        {"component_family": "generators", "coverage_status": "migrated_review_snapshot", "details": "Vattenfall/interface retained as interface only."},
        {"component_family": "mixing_rules", "coverage_status": "migrated_review_snapshot", "details": "WAG mixing remains a review snapshot; no WAG valuation."},
        {"component_family": "system_constraints", "coverage_status": "migrated_review_snapshot", "details": "Forbidden economics and governance constraints preserved."},
    ]


def build_report_payload(
    migrated_tables: dict[str, list[dict[str, str]]],
    validator_failures: int,
    validator_warnings: int,
) -> dict:
    total_rows = sum(len(rows) for rows in migrated_tables.values())
    missing_rows = sum(1 for rows in migrated_tables.values() for row in rows if row.get("input_status") == "missing_blocker")
    deferred_rows = sum(1 for rows in migrated_tables.values() for row in rows if "deferred" in row.get("input_status", ""))
    development_rows = sum(1 for rows in migrated_tables.values() for row in rows if row.get("input_status") in {"development_only", "selected_development_input_candidate"})
    return {
        "stage": "S4.4b4",
        "migration_goal": "controlled S2/S3/S3.3j migration into unified C0/C1 development input layer",
        "raw_pdfs_inspected": False,
        "original_s4_4b_inputs_modified": False,
        "migrated_dev_input_dir": _rel(MIGRATED_INPUT_DIR),
        "pypsa_style_review_dir": _rel(PYPSA_REVIEW_DIR),
        "table_count": len(migrated_tables),
        "total_rows": total_rows,
        "development_rows": development_rows,
        "missing_blocker_rows": missing_rows,
        "deferred_rows": deferred_rows,
        "validator_failure_count": validator_failures,
        "validator_warning_count": validator_warnings,
        "c1_closure_decision": {
            "BF7": "inactive",
            "KGF2_Coking_Plant_2": "inactive",
            "BF6": "active",
            "KGF1_Coking_Plant_1": "active",
            "decision_status": "human_selected_default",
        },
        "hot_cold_slab_design": {
            "total_slab_capacity_t": 25000,
            "hot_slab_initial_t": 0,
            "hot_slab_terminal_t": 0,
            "cold_slab_initial_t": 12500,
            "cold_slab_terminal_t": 12500,
            "hot_to_cold_decay_fraction_per_hour": 0.50,
            "maximum_hot_residence_time_h": 2,
            "cold_slab_reheating_energy_GJ_per_t": 1.20,
            "hot_slab_reheating_energy_fraction": 0.40,
            "executable_in_s4_4c": False,
        },
        "stage_gate_decision": "pass_with_limitations_to_s4_4c_partial_scope",
        "caveat": (
            "C1 guardrail inputs and human-confirmed figure values are migrated as development inputs. "
            "C0 remains partially blocked by missing BF7/CP2 limits and conversion coefficients. "
            "No economics, DA bidding, stochasticity, CVaR, or thesis-approved claims are introduced."
        ),
    }


def write_reports(
    migrated_tables: dict[str, list[dict[str, str]]],
    validation_result: dict,
) -> dict:
    inventory = build_source_inventory()
    selection = build_sensitivity_selection()
    mapping = build_mapping_rows(migrated_tables)
    manifest = build_manifest_rows(migrated_tables)
    not_migrated = build_not_migrated_rows()
    unresolved = build_unresolved_inputs()
    coverage = build_component_coverage()
    report = build_report_payload(
        migrated_tables,
        validator_failures=validation_result["failure_count"],
        validator_warnings=validation_result["warning_count"],
    )

    _write_csv(OUTPUT_DIR / "s4_4b4_s3_source_inventory.csv", inventory)
    _write_csv(OUTPUT_DIR / "s4_4b4_s3_sensitivity_selection.csv", selection)
    _write_csv(OUTPUT_DIR / "s4_4b4_s3_to_unified_mapping.csv", mapping)
    _write_csv(OUTPUT_DIR / "s4_4b4_migrated_rows_manifest.csv", manifest)
    _write_csv(OUTPUT_DIR / "s4_4b4_not_migrated_rows.csv", not_migrated)
    _write_csv(OUTPUT_DIR / "s4_4b4_unresolved_inputs.csv", unresolved)
    _write_csv(OUTPUT_DIR / "s4_4b4_pypsa_component_coverage.csv", coverage)
    _write_json(OUTPUT_DIR / "s4_4b4_s3_migration_report.json", report)
    _write_csv(OUTPUT_DIR / "s4_4b4_s3_migration_report.csv", [report])

    stage_gate = {
        "stage": "S4.4b4",
        "decision": "pass_with_limitations_to_s4_4c_partial_scope",
        "may_proceed_to_s4_4c_partial_scope": "true",
        "may_proceed_to_full_C0_C1_execution": "false",
        "ready_for_DA_optimisation": "false",
        "ready_for_bidding": "false",
        "ready_for_stochastic": "false",
        "thesis_usable": "false",
        "Tata_validated": "false",
        "validator_failure_count": str(validation_result["failure_count"]),
        "validator_warning_count": str(validation_result["warning_count"]),
        "caveat": report["caveat"],
    }
    _write_json(OUTPUT_DIR / "s4_4b4_stage_gate.json", stage_gate)
    _write_csv(OUTPUT_DIR / "s4_4b4_stage_gate.csv", [stage_gate])
    return report


def run_migration() -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MIGRATED_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PYPSA_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    base_tables = _load_base_tables()
    migrated_tables = build_migrated_tables(base_tables)
    for table_name, rows in migrated_tables.items():
        _write_csv(MIGRATED_INPUT_DIR / table_name, rows, _table_columns(base_tables, table_name))

    manifest_rows = _manifest_rows()
    if manifest_rows:
        _write_csv(MIGRATED_INPUT_DIR / "s4_4b_unified_dev_inputs_manifest.csv", manifest_rows)

    write_pypsa_review_snapshots()

    validation_result = validate_unified_dev_inputs(MIGRATED_INPUT_DIR)
    write_validation_outputs(validation_result, input_dir=MIGRATED_INPUT_DIR)
    report = write_reports(migrated_tables, validation_result)
    return report


def main() -> None:
    report = run_migration()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
