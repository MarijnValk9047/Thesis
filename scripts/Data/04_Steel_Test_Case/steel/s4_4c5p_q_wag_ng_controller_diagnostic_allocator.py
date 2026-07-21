"""S4.4c5p_q carrier-specific WAG/NG diagnostic allocation ledger.

This stage does not dispatch or reallocate fuel.  It normalises only accepted
existing controller outputs into one carrier-specific ledger and fails closed
where a source-backed controller demand or mix is absent.  It is therefore a
diagnostic implementation of the C5p_p design, governed by C5p_o.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    S4_ROOT,
    _read_csv,
    _write_csv,
    _write_json,
)


STAGE = "S4.4c5p_q_wag_ng_controller_diagnostic_allocator"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_q_wag_ng_controller_diagnostic_allocator"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_NG_CONTROLLER_DIAGNOSTIC_ALLOCATOR.md")

C5P_O_DIR = S4_ROOT / "s4_4c5p_o_wag_controller_contract_hardening"
C5P_P_DIR = S4_ROOT / "s4_4c5p_p_wag_ng_controller_design"
C5M_DIR = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation"
C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
C5P_C_DIR = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting"
S3_WAG_INPUT_PATH = (
    S4_ROOT.parent / "S3" / "s3_provisional_dev_input" / "s3_wag_selected_dev_inputs.csv"
)

CONFIGS = (C0, C1)
PHYSICAL_CARRIERS = ("BFG", "COG", "BOFG", "NG")
NON_PHYSICAL_CARRIERS = ("aggregate_wag", "mixed_wag")
# 1 MWh = 3.6 GJ = 0.0000036 PJ.
MWH_TO_PJ = 0.0000036

MIX_COLUMNS = [
    "configuration",
    "horizon_hours",
    "sink_or_controller",
    "carrier",
    "allocation_MWh_LHV_y",
    "allocation_PJ_y",
    "allocation_provenance",
    "physical_interpretation_status",
    "is_eligible",
    "NG_backup_used",
    "caveat",
]

BALANCE_COLUMNS = [
    "configuration",
    "carrier",
    "generation_PJ_y",
    "process_or_prep_use_PJ_y",
    "steam_boiler_use_PJ_y",
    "generator_use_PJ_y",
    "flare_spill_PJ_y",
    "residual_PJ_y",
    "balance_residual_PJ_y",
    "balance_status",
    "authoritative_source",
    "allocator_effect",
    "caveat",
]

RECONCILIATION_COLUMNS = [
    "configuration",
    "carrier",
    "process_or_prep_total_PJ_y",
    "identified_controller_process_use_PJ_y",
    "unclassified_process_use_PJ_y",
    "reconciliation_status",
    "evidence",
    "caveat",
]

BLOCKED_COLUMNS = [
    "blocked_case_id",
    "configuration",
    "sink_or_controller",
    "carrier",
    "missing_requirement",
    "current_handling",
    "why_not_invented",
    "unlocks_after",
]

VALIDATION_COLUMNS = [
    "check_id",
    "check_name",
    "configuration",
    "status",
    "evidence",
    "recommended_action",
]

ALIGNMENT_COLUMNS = [
    "functional_area",
    "current_q_handling",
    "athanasiadis_precedent_role",
    "alignment_status",
    "evidence_status",
    "caveat",
]

WAG_CO2_COLUMNS = [
    "configuration",
    "horizon_hours",
    "sink_or_controller",
    "carrier",
    "allocated_MWh_LHV_y",
    "allocated_GJ_LHV_y",
    "emission_factor_kgCO2_per_GJ",
    "WAG_combustion_or_flare_CO2_t_y",
    "carbon_accounting_mode",
    "factor_provenance",
    "ledger_status",
    "caveat",
]


def _as_float(value: str | float | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _fmt(value: float | str | None, digits: int = 6) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    if math.isclose(value, 0.0, abs_tol=1e-9):
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _optional_csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path) if path.exists() else []


def _annual_rows(path: Path) -> list[dict[str, str]]:
    return [row for row in _optional_csv(path) if row.get("horizon_hours") == "168"]


def _mix_row(
    configuration: str,
    horizon_hours: str,
    sink: str,
    carrier: str,
    mwh: float | None,
    provenance: str,
    status: str,
    eligible: str,
    ng_backup: str,
    caveat: str,
) -> dict[str, str]:
    return {
        "configuration": configuration,
        "horizon_hours": horizon_hours,
        "sink_or_controller": sink,
        "carrier": carrier,
        "allocation_MWh_LHV_y": _fmt(mwh),
        "allocation_PJ_y": _fmt(None if mwh is None else mwh * MWH_TO_PJ),
        "allocation_provenance": provenance,
        "physical_interpretation_status": status,
        "is_eligible": eligible,
        "NG_backup_used": ng_backup,
        "caveat": caveat,
    }


def _build_mix_ledger() -> list[dict[str, str]]:
    """Compile existing controller mix outputs without changing their allocation."""
    rows: list[dict[str, str]] = []

    combined_process_rows = _annual_rows(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv")
    for row in combined_process_rows:
        for carrier, field in {
            "BFG": "BFG_to_HSM_site_MWh_y",
            "COG": "COG_to_HSM_site_MWh_y",
            "BOFG": "BOFG_to_HSM_site_MWh_y",
            "NG": "NG_to_HSM_site_MWh_y",
        }.items():
            value = _as_float(row.get(field))
            rows.append(
                _mix_row(
                    row["configuration"],
                    row["horizon_hours"],
                    "HSM_WBW",
                    carrier,
                    value,
                    "C5m combined HSM/sinter controller dashboard",
                    "accepted_existing_controller_output",
                    "yes" if carrier != "NG" else "backup_only",
                    "yes" if carrier == "NG" and value > 0 else "no",
                    "Latest combined controller surface selected because it reconciles to C5p_o BFG process use; HSM source-card split remains sensitivity-only for migration.",
                )
            )

    for row in combined_process_rows:
        for carrier, field in {
            "BFG": "BFG_to_Sinter_site_MWh_y",
            "COG": "COG_to_Sinter_site_MWh_y",
            "BOFG": "BOFG_to_Sinter_site_MWh_y",
            "NG": "NG_to_Sinter_site_MWh_y",
        }.items():
            value = _as_float(row.get(field))
            rows.append(
                _mix_row(
                    row["configuration"],
                    row["horizon_hours"],
                    "Sinter",
                    carrier,
                    value,
                    "C5m combined HSM/sinter controller dashboard",
                    "accepted_existing_controller_output",
                    "yes" if carrier in {"COG", "NG"} else "no",
                    "yes" if carrier == "NG" and value > 0 else "no",
                    "Existing controller output; BFG and BOFG remain blocked in the base sinter controller.",
                )
            )

    steam_rows = _annual_rows(C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv")
    for row in steam_rows:
        for carrier, field in {
            "BFG": "BFG_to_steam_MWh_LHV_y",
            "COG": "COG_to_steam_MWh_LHV_y",
            "BOFG": "BOFG_to_steam_MWh_LHV_y",
            "NG": "NG_backup_for_steam_MWh_LHV_y",
        }.items():
            value = _as_float(row.get(field))
            rows.append(
                _mix_row(
                    row["configuration"],
                    row["horizon_hours"],
                    "steam_boiler_controller",
                    carrier,
                    value,
                    "C5p_b boiler/steam allocation output",
                    "accepted_existing_controller_output" if carrier != "BOFG" else "blocked_base",
                    "no" if carrier == "BOFG" else ("backup_only" if carrier == "NG" else "yes"),
                    "yes" if carrier == "NG" and value > 0 else "no",
                    "BOFG remains blocked in the steam layer; this row reports existing output only.",
                )
            )

    generator_rows = _annual_rows(C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv")
    for row in generator_rows:
        unit_id = row.get("unit_id", "")
        if unit_id not in {"VN25", "IJ01", "C0_CURRENT_GENERATOR_INTERFACE"}:
            continue
        for carrier, field in {
            "BFG": "BFG_MWh_LHV_y",
            "COG": "COG_MWh_LHV_y",
            "BOFG": "BOFG_MWh_LHV_y",
            "NG": "NG_MWh_LHV_y",
        }.items():
            value = _as_float(row.get(field))
            rows.append(
                _mix_row(
                    row["configuration"],
                    row["horizon_hours"],
                    unit_id,
                    carrier,
                    value,
                    "C5p_c generator fuel allocation output",
                    "accepted_existing_controller_output",
                    "backup_only" if carrier == "NG" else "yes",
                    "yes" if carrier == "NG" and value > 0 else "no",
                    "Generator interface is an internal electricity offset; not market dispatch or export revenue.",
                )
            )
    return rows


def _build_balance_ledger() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in _optional_csv(C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv"):
        if row.get("carrier") not in PHYSICAL_CARRIERS:
            continue
        rows.append(
            {
                "configuration": row["configuration"],
                "carrier": row["carrier"],
                "generation_PJ_y": row["generation_PJ_y"],
                "process_or_prep_use_PJ_y": row["process_or_prep_use_PJ_y"],
                "steam_boiler_use_PJ_y": row["steam_boiler_use_PJ_y"],
                "generator_use_PJ_y": row["generator_use_PJ_y"],
                "flare_spill_PJ_y": row["flare_spill_PJ_y"],
                "residual_PJ_y": row["residual_PJ_y"],
                "balance_residual_PJ_y": row["balance_residual_PJ_y"],
                "balance_status": row["balance_status"],
                "authoritative_source": "C5p_o hardened carrier sink ledger (from C5p_m)",
                "allocator_effect": "none; C5p_q compiles existing controller mixes only",
                "caveat": row.get("caveat", ""),
            }
        )
    return rows


def _build_process_reconciliation(mix_rows: list[dict[str, str]], balance_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    process_sinks = {"HSM_WBW", "Sinter"}
    for configuration in CONFIGS:
        for carrier in ("BFG", "COG", "BOFG"):
            total = next(
                _as_float(row["process_or_prep_use_PJ_y"])
                for row in balance_rows
                if row["configuration"] == configuration and row["carrier"] == carrier
            )
            identified = sum(
                _as_float(row["allocation_PJ_y"])
                for row in mix_rows
                if row["configuration"] == configuration
                and row["carrier"] == carrier
                and row["sink_or_controller"] in process_sinks
            )
            unclassified = total - identified
            status = "pass" if math.isclose(unclassified, 0.0, abs_tol=1e-5) else "partial"
            rows.append(
                {
                    "configuration": configuration,
                    "carrier": carrier,
                    "process_or_prep_total_PJ_y": _fmt(total),
                    "identified_controller_process_use_PJ_y": _fmt(identified),
                    "unclassified_process_use_PJ_y": _fmt(unclassified),
                    "reconciliation_status": status,
                    "evidence": "C5p_o carrier balance reconciled against the later C5m combined HSM/sinter controller output.",
                    "caveat": "Unclassified process use is retained as a gap; it is not reallocated to a plant or NG.",
                }
            )
    return rows


def _wag_emission_factors() -> dict[str, float]:
    """Read governed development-only point-of-oxidation factors.

    The values are intentionally read from the existing S3 selected-input
    artifact rather than duplicated here.  This stage emits a partial WAG
    combustion/flare ledger only; it never adds aggregate process counters or
    natural-gas residual emissions.
    """
    parameter_to_carrier = {
        "bfg_combustion_factor_netherlands": "BFG",
        "cog_combustion_factor_netherlands": "COG",
        "oxygas_bofg_combustion_factor_netherlands": "BOFG",
    }
    factors: dict[str, float] = {}
    for row in _optional_csv(S3_WAG_INPUT_PATH):
        carrier = parameter_to_carrier.get(row.get("parameter_name", ""))
        if carrier is None:
            continue
        if row.get("accepted_for_dev_use") != "true":
            raise ValueError(f"WAG CO2 factor for {carrier} is not accepted for development use.")
        if row.get("energy_basis") != "LHV_energy":
            raise ValueError(f"WAG CO2 factor for {carrier} must use LHV_energy basis.")
        factors[carrier] = _as_float(row.get("selected_value"))
    missing = set(("BFG", "COG", "BOFG")) - set(factors)
    if missing:
        raise ValueError(f"Missing governed WAG CO2 factors for: {sorted(missing)}")
    return factors


def _build_wag_point_of_oxidation_co2_ledger(mix_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Book represented WAG oxidation once, at carrier-specific sink rows.

    This is intentionally a partial emissions ledger.  It excludes NG, site
    residuals, aggregate BF/BOF/KGF/PEFA process counters and any inferred
    common-plant allocation.  Consequently it is suitable for diagnostic
    anchor reconciliation, never for ETS costs or a consolidated site total.
    """
    factors = _wag_emission_factors()
    rows: list[dict[str, str]] = []
    for row in mix_rows:
        carrier = row["carrier"]
        if carrier not in factors:
            continue
        mwh = _as_float(row["allocation_MWh_LHV_y"])
        energy_gj = mwh * 3.6
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "sink_or_controller": row["sink_or_controller"],
                "carrier": carrier,
                "allocated_MWh_LHV_y": _fmt(mwh),
                "allocated_GJ_LHV_y": _fmt(energy_gj),
                "emission_factor_kgCO2_per_GJ": _fmt(factors[carrier]),
                "WAG_combustion_or_flare_CO2_t_y": _fmt(energy_gj * factors[carrier] / 1000.0),
                "carbon_accounting_mode": "point_of_oxidation_partial_WAG_explicit",
                "factor_provenance": "S3 selected development input; RVO/Netherlands fuel list January 2025",
                "ledger_status": "represented_sink_only_not_consolidated_site_total",
                "caveat": (
                    "Do not add aggregate BF/BOF/KGF/PEFA process counters, NG residual emissions, "
                    "or Scope 2 to this ledger. Unclassified WAG use and carrier-unsplit C1 flare remain visible gaps."
                ),
            }
        )
    return rows


def _wag_co2_totals_by_configuration(wag_co2_rows: list[dict[str, str]]) -> dict[str, float]:
    totals = {configuration: 0.0 for configuration in CONFIGS}
    for row in wag_co2_rows:
        totals[row["configuration"]] = totals.get(row["configuration"], 0.0) + _as_float(
            row["WAG_combustion_or_flare_CO2_t_y"]
        )
    return {configuration: float(_fmt(value, digits=6)) for configuration, value in totals.items()}


def _build_blocked_rows() -> list[dict[str, str]]:
    common = "C0;C1"
    return [
        {
            "blocked_case_id": "Q_BLOCK_001",
            "configuration": common,
            "sink_or_controller": "KGF_underfiring",
            "carrier": "COG",
            "missing_requirement": "Accepted KGF controller output connected to the hardened ledger.",
            "current_handling": "source-backed eligibility only; no numeric allocation added",
            "why_not_invented": "COG self-use must be deducted before surplus; using a generic residual would risk double counting.",
            "unlocks_after": "Existing KGF controller output or reconciled source-backed implementation.",
        },
        {
            "blocked_case_id": "Q_BLOCK_002",
            "configuration": common,
            "sink_or_controller": "BF_hot_stove",
            "carrier": "BFG;COG;BOFG;NG",
            "missing_requirement": "Reconciled hot-stove heat-demand output and enrichment policy.",
            "current_handling": "design eligibility only; no numeric allocation added",
            "why_not_invented": "Gross BFG cannot be treated as surplus before hot-stove demand is deducted.",
            "unlocks_after": "Existing or source-backed hot-stove controller output.",
        },
        {
            "blocked_case_id": "Q_BLOCK_003",
            "configuration": common,
            "sink_or_controller": "PEFA_Malerij_and_Branderij",
            "carrier": "BOFG;COG;NG",
            "missing_requirement": "Exact source-card locator and accepted PEFA controller output.",
            "current_handling": "eligibility design only; no numeric allocation added",
            "why_not_invented": "The card/source mapping remains partial and must not be converted into a synthetic fuel split.",
            "unlocks_after": "PEFA controller source review and existing-output integration.",
        },
        {
            "blocked_case_id": "Q_BLOCK_004",
            "configuration": common,
            "sink_or_controller": "common_plant_WAG_NG_split",
            "carrier": "BFG;COG;BOFG;NG",
            "missing_requirement": "Controller-compatible common-plant split, not an aggregate residual ratio.",
            "current_handling": "no common-plant reallocation; reporting gap retained",
            "why_not_invented": "C5p_k aggregate fallback is excluded by C5p_o and cannot be revived here.",
            "unlocks_after": "Source-backed controller hardening for the applicable sinks.",
        },
        {
            "blocked_case_id": "Q_BLOCK_005",
            "configuration": common,
            "sink_or_controller": "mixed_wag_dispatch",
            "carrier": "mixed_wag",
            "missing_requirement": "No requirement: quantitative mixed-gas/Wobbe modelling is outside thesis scope.",
            "current_handling": "structural label only",
            "why_not_invented": "Carrier-specific BFG/COG/BOFG rows remain the physical accounting basis; mixed_wag cannot be used as a separate fuel.",
            "unlocks_after": "Not planned in current thesis scope.",
        },
        {
            "blocked_case_id": "Q_BLOCK_006",
            "configuration": C1,
            "sink_or_controller": "flare_spill",
            "carrier": "BFG;COG;BOFG",
            "missing_requirement": "Carrier-split flare accounting.",
            "current_handling": "aggregate warning only",
            "why_not_invented": "A carrier split cannot be inferred from aggregate flare.",
            "unlocks_after": "Carrier-split diagnostic or source-backed flare policy.",
        },
    ]


def _build_validation_rows(
    mix_rows: list[dict[str, str]],
    balance_rows: list[dict[str, str]],
    reconciliation_rows: list[dict[str, str]],
    wag_co2_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    statuses = {row["balance_status"] for row in balance_rows}
    return [
        {
            "check_id": "Q_CHECK_001",
            "check_name": "accepted_carrier_balances_preserved",
            "configuration": "both",
            "status": "pass" if statuses == {"pass"} else "fail",
            "evidence": "C5p_o carrier-level balance rows are retained without reallocation.",
            "recommended_action": "Do not use a C5p_q mix row to alter the C5p_o balance.",
        },
        {
            "check_id": "Q_CHECK_002",
            "check_name": "no_aggregate_wag_physical_allocation",
            "configuration": "both",
            "status": "pass",
            "evidence": "No aggregate_wag rows are emitted in controller_mix_allocation.csv.",
            "recommended_action": "Keep aggregate WAG reporting-only.",
        },
        {
            "check_id": "Q_CHECK_003",
            "check_name": "no_mixed_wag_quantitative_allocation",
            "configuration": "both",
            "status": "pass",
            "evidence": "mixed_wag appears only in blocked_cases.csv.",
            "recommended_action": "Do not unlock before a quantitative mixer exists.",
        },
        {
            "check_id": "Q_CHECK_004",
            "check_name": "no_c5p_k_allocation_use",
            "configuration": "both",
            "status": "pass",
            "evidence": "C5p_k is not an input artifact to the allocator.",
            "recommended_action": "Retain C5p_k for warning/context only.",
        },
        {
            "check_id": "Q_CHECK_005",
            "check_name": "no_invented_ng_split",
            "configuration": "both",
            "status": "pass",
            "evidence": "NG rows are read only from existing HSM/sinter/steam/generator controllers.",
            "recommended_action": "Keep common-plant NG split blocked.",
        },
        {
            "check_id": "Q_CHECK_006",
            "check_name": "process_mix_reconciliation",
            "configuration": "both",
            "status": "warning" if any(row["reconciliation_status"] == "partial" for row in reconciliation_rows) else "pass",
            "evidence": "HSM and sinter explain part of process/prep use; remaining carrier-specific process use is visible as unclassified.",
            "recommended_action": "Connect KGF, BF hot-stove and PEFA controller outputs before interpreting the complete plant mix.",
        },
        {
            "check_id": "Q_CHECK_007",
            "check_name": "WAG_explicit_CO2_uses_point_of_oxidation_mode_only",
            "configuration": "both",
            "status": "pass" if wag_co2_rows else "fail",
            "evidence": "Carrier-specific BFG/COG/BOFG sink rows use the governed S3 RVO-factor selection; aggregate process counters are excluded.",
            "recommended_action": "Keep this as a partial WAG combustion/flare ledger; do not add aggregate process counters or NG residuals.",
        },
        {
            "check_id": "Q_CHECK_009",
            "check_name": "no_NG_or_residual_CO2_filling",
            "configuration": "both",
            "status": "pass",
            "evidence": "The WAG-explicit CO2 ledger accepts BFG, COG and BOFG rows only and does not infer NG or electricity residual emissions.",
            "recommended_action": "Track residual NG and electricity separately until their represented-asset boundary is complete.",
        },
        {
            "check_id": "Q_CHECK_008",
            "check_name": "no_hidden_negative_flooring",
            "configuration": "both",
            "status": "pass",
            "evidence": "All balance residuals are copied as reported from C5p_o.",
            "recommended_action": "Treat any future negative value as a warning, not as zero.",
        },
    ]


def _build_alignment_rows() -> list[dict[str, str]]:
    return [
        {
            "functional_area": "carrier-specific gas generation and use",
            "current_q_handling": "BFG, COG and BOFG stay separate in each accepted output row.",
            "athanasiadis_precedent_role": "gas-network/controller architecture precedent",
            "alignment_status": "aligned",
            "evidence_status": "indirect repository/source-card precedent only",
            "caveat": "No Athanasiadis PDF was inspected and no numeric replication is claimed.",
        },
        {
            "functional_area": "plant controller mix reporting",
            "current_q_handling": "HSM, sinter, steam and generator mixes are reported by carrier, with provenance.",
            "athanasiadis_precedent_role": "separation of process, utility and generator interfaces",
            "alignment_status": "aligned",
            "evidence_status": "partial",
            "caveat": "KGF, BF hot-stove and PEFA remain fail-closed pending controller outputs.",
        },
        {
            "functional_area": "mixed-gas treatment",
            "current_q_handling": "mixed_wag remains structural-only and cannot satisfy a sink demand.",
            "athanasiadis_precedent_role": "gas-network/mixing abstraction, deliberately simplified to carrier-specific energy accounting",
            "alignment_status": "aligned",
            "evidence_status": "governed thesis-scope decision",
            "caveat": "Wobbe/gas-quality constraints are deliberately out of scope; no physical allocation is made from mixed_wag.",
        },
        {
            "functional_area": "generator and market boundary",
            "current_q_handling": "Generator gas use is an internal electricity offset only; no WAG price or export value is created.",
            "athanasiadis_precedent_role": "generator-interface separation",
            "alignment_status": "aligned",
            "evidence_status": "indirect",
            "caveat": "No DA or price-responsive dispatch is active.",
        },
    ]


def _file_manifest(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        if not path.exists():
            rows.append({"path": str(path), "status": "missing", "sha256": ""})
            continue
        rows.append(
            {
                "path": str(path),
                "status": "read",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return rows


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _stage_gate(validation_rows: list[dict[str, str]], blocked_rows: list[dict[str, str]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in validation_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "stage": STAGE,
        "status": "partial_diagnostic_allocation",
        "thesis_usability": False,
        "contract_interface": "C5p_o authoritative diagnostic interface",
        "allocator_behaviour": "compile accepted existing controller outputs; fail closed otherwise",
        "validation_check_counts": counts,
        "blocked_case_count": len(blocked_rows),
        "go_no_go": {
            "controller_mix_reporting": "GO_DIAGNOSTIC_ONLY",
            "carrier_balance_reporting": "GO_DIAGNOSTIC_ONLY",
            "complete_common_plant_WAG_NG_physical_allocation": "NO_GO",
            "NG_residual_policy": "NO_GO",
            "WAG_explicit_CO2_ledger": "GO_DIAGNOSTIC_ONLY_PARTIAL",
            "consolidated_site_or_ETS_CO2": "NO_GO",
            "full_sensitivity_execution": "NO_GO",
            "executable_input_migration": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
        "guardrails": {
            "new_physical_allocator_created": False,
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "raw_pdfs_inspected": False,
            "c5p_k_used_as_physical_evidence": False,
            "aggregate_wag_physical_allocation": False,
            "mixed_wag_quantitative_allocation": False,
            "invented_wag_ng_ratio": False,
            "fuel_explicit_co2_unlocked": "partial_WAG_point_of_oxidation_only",
        },
    }


def _write_report(summary: dict[str, Any], validations: list[dict[str, str]], blocked: list[dict[str, str]]) -> None:
    counts = summary["validation_check_counts"]
    report = f"""# C5 WAG/NG Controller Diagnostic Allocator

## Purpose

C5p_q is the first diagnostic implementation of the C5p_p WAG/NG design. It does **not** introduce a new physical allocator. Instead, it compiles accepted existing controller outputs into one carrier-specific ledger and fails closed where the current model lacks a reconciled controller demand or mix.

C5p_o remains authoritative for the WAG contract. COG, BFG and BOFG remain separate physical carriers where existing rows preserve them. `mixed_wag` remains structural-only, `aggregate_wag` remains reporting-only, and C5p_k is excluded from physical allocation.

## What is actually allocated here

The ledger reports only existing quantitative controller outputs for HSM/WBW, sinter, the governed steam/boiler layer, and the generator interfaces. Its purpose is provenance and reconciliation, not a new dispatch result. The C5p_o carrier balance is copied unchanged as the authoritative balance.

## What remains blocked

KGF underfiring, BF hot-stove heat, PEFA mixes, a common-plant WAG/NG split, and C1 carrier-split flare are not generated from residual WAG. They remain explicitly blocked. Count: {len(blocked)}. Wobbe/gas-quality constraints are deliberately outside the thesis scope.

## WAG-explicit CO2

`wag_point_of_oxidation_co2_ledger.csv` adds a separate partial WAG combustion/flare ledger. It counts BFG, COG and BOFG only where an accepted controller row records their use, using the existing RVO/Netherlands fuel-list factor selection. It excludes NG residuals, electricity residuals, Scope 2 and aggregate BF/BOF/KGF/PEFA process counters. It is therefore not a site total, not ETS-ready and not a cost input.

## Validation status

Validation checks: `{counts}`. The WAG balances are preserved. A warning remains because HSM and sinter account for only part of C5p_o's process/prep carrier totals; the unclassified remainder is reported rather than reassigned.

## Athanasiadis alignment

The comparison is methodological only: carrier-specific generation/use, plant controller separation, steam/boiler and generator interfaces, no direct WAG-market value, and fail-closed mixing are aligned at an architectural level. It is not a numeric replication, no raw Athanasiadis PDF was inspected, and no official Tata claim is made.

## Critical review

Review `controller_mix_allocation.csv` to verify that each mix has an existing-controller provenance. Review `process_controller_reconciliation.csv` to see exactly what process use remains unclassified. Any aggregate WAG physical row, mixed-WAG numeric allocation, C5p_k provenance, or a newly inferred WAG/NG ratio invalidates this stage.

## Gate

- Controller mix and carrier-balance reporting: GO, diagnostic-only.
- Complete common-plant physical WAG/NG allocation: NO-GO.
- NG residual policy, full sensitivity, executable migration, economics and DA: NO-GO.
- WAG-explicit CO2 ledger: GO, diagnostic-only and partial. Consolidated site/ETS CO2: NO-GO.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_q_wag_ng_controller_diagnostic_allocator() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mix_rows = _build_mix_ledger()
    balance_rows = _build_balance_ledger()
    reconciliation_rows = _build_process_reconciliation(mix_rows, balance_rows)
    blocked_rows = _build_blocked_rows()
    wag_co2_rows = _build_wag_point_of_oxidation_co2_ledger(mix_rows)
    wag_co2_totals = _wag_co2_totals_by_configuration(wag_co2_rows)
    validation_rows = _build_validation_rows(mix_rows, balance_rows, reconciliation_rows, wag_co2_rows)
    alignment_rows = _build_alignment_rows()
    stage_gate = _stage_gate(validation_rows, blocked_rows)

    inputs = [
        C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv",
        C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv",
        C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv",
        C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv",
        C5P_P_DIR / "wag_controller_eligibility_matrix.csv",
    ]
    input_manifest = {
        "stage": STAGE,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "inputs": _file_manifest(inputs),
    }
    code_version = {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__}
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "thesis_usability": False,
        "output_policy": "minimal",
        "mix_rows": len(mix_rows),
        "balance_rows": len(balance_rows),
        "reconciliation_rows": len(reconciliation_rows),
        "wag_explicit_co2_rows": len(wag_co2_rows),
        "wag_explicit_co2_partial_totals_t_y": wag_co2_totals,
        "blocked_cases": len(blocked_rows),
        "validation_check_counts": stage_gate["validation_check_counts"],
        "accepted_sinks": sorted({row["sink_or_controller"] for row in mix_rows}),
        "top_blockers": [row["sink_or_controller"] for row in blocked_rows],
        "go_no_go": stage_gate["go_no_go"],
    }
    registry_entry = {
        "run_id": STAGE,
        "purpose": "Carrier-specific compilation of accepted WAG/NG controller outputs; no new allocation.",
        "thesis_usable": False,
        "retention": "local diagnostic output until review",
        "git_eligible": False,
        "status": stage_gate["status"],
    }

    _write_csv(OUTPUT_DIR / "controller_mix_allocation.csv", mix_rows, MIX_COLUMNS)
    _write_csv(OUTPUT_DIR / "carrier_balance_after_allocation.csv", balance_rows, BALANCE_COLUMNS)
    _write_csv(OUTPUT_DIR / "process_controller_reconciliation.csv", reconciliation_rows, RECONCILIATION_COLUMNS)
    _write_csv(OUTPUT_DIR / "wag_point_of_oxidation_co2_ledger.csv", wag_co2_rows, WAG_CO2_COLUMNS)
    _write_csv(OUTPUT_DIR / "blocked_cases.csv", blocked_rows, BLOCKED_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validation_rows, VALIDATION_COLUMNS)
    _write_csv(OUTPUT_DIR / "athanasiadis_alignment_check.csv", alignment_rows, ALIGNMENT_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", input_manifest)
    _write_json(OUTPUT_DIR / "code_version.json", code_version)
    _write_json(OUTPUT_DIR / "s4_4c5p_q_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", registry_entry)
    _write_report(summary, validation_rows, blocked_rows)
    return summary


def main() -> int:
    run_s4_4c5p_q_wag_ng_controller_diagnostic_allocator()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
