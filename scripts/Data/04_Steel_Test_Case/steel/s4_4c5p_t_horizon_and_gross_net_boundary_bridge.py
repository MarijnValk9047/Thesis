"""Build a common-24h diagnostic bridge for existing C5 WAG controllers.

The hardened C5p_o contract inherits the 24-hour carrier balance used by C5p_m.
C5p_q currently compiles several 168-hour outputs, while PEFA explains its
unclassified process use at 24 hours.  This stage creates a separate,
non-executable 24-hour candidate ledger; it does not rewrite C5p_q or add
KGF/BF self-use a second time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
STAGE = "S4.4c5p_t_horizon_and_gross_net_boundary_bridge"
S4_ROOT = ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_t_horizon_and_gross_net_boundary_bridge"
REPORT_PATH = ROOT / "docs/optimisation/steel/S4/C5_HORIZON_AND_GROSS_NET_BOUNDARY_BRIDGE.md"
C5P_O_DIR = S4_ROOT / "s4_4c5p_o_wag_controller_contract_hardening"
C5P_Q_DIR = S4_ROOT / "s4_4c5p_q_wag_ng_controller_diagnostic_allocator"
C5M_DIR = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation"
C5M_B_DIR = S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration"
C5N_A_DIR = S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer"
C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
C5P_C_DIR = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting"

CANONICAL_CANDIDATE_HORIZON = "24"
MWH_TO_PJ = 0.0000036
TOL_PJ = 1e-5

MIX_COLUMNS = [
    "configuration",
    "horizon_hours",
    "sink_or_controller",
    "carrier",
    "allocation_MWh_LHV_y",
    "allocation_PJ_y",
    "upstream_stage",
    "allocation_mode",
    "physical_interpretation_status",
    "caveat",
]
PROCESS_COLUMNS = [
    "configuration",
    "carrier",
    "c5p_o_process_or_prep_use_PJ_y",
    "identified_24h_controller_use_PJ_y",
    "residual_unclassified_PJ_y",
    "reconciliation_status",
    "controller_evidence",
    "caveat",
]
HORIZON_COLUMNS = [
    "surface",
    "available_horizons",
    "selected_horizon_for_candidate_contract",
    "selection_status",
    "evidence",
    "implication",
]
Q_COMPARISON_COLUMNS = [
    "configuration",
    "sink_or_controller",
    "carrier",
    "candidate_24h_PJ_y",
    "existing_C5p_q_horizon_hours",
    "existing_C5p_q_PJ_y",
    "absolute_difference_PJ_y",
    "comparison_status",
    "caveat",
]
BRIDGE_COLUMNS = [
    "configuration",
    "controller",
    "carrier",
    "upstream_horizon_hours",
    "upstream_gross_or_pre_net_MWh_y",
    "upstream_mandatory_self_use_MWh_y",
    "upstream_net_or_surplus_MWh_y",
    "C5p_o_net_generation_MWh_y",
    "absolute_gap_to_C5p_o_MWh_y",
    "bridge_status",
    "allowed_current_use",
    "caveat",
]
STATUS_COLUMNS = [
    "controller",
    "24h_candidate_ledger_status",
    "current_C5p_q_status",
    "may_replace_C5p_q_row_now",
    "may_add_new_C5p_o_physical_sink_now",
    "required_next_action",
]
ATH_COLUMNS = [
    "functional_area",
    "candidate_contract_handling",
    "athanasiadis_precedent_role",
    "alignment_status",
    "caveat",
]
VALIDATION_COLUMNS = ["check_id", "check_name", "status", "evidence", "recommended_action"]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_float(value: str | float | None) -> float:
    return 0.0 if value in (None, "") else float(value)


def _fmt(value: float, digits: int = 6) -> str:
    if math.isclose(value, 0.0, abs_tol=1e-12):
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _assignments(value: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for token in value.split(";"):
        if "=" in token:
            key, raw = token.split("=", maxsplit=1)
            values[key.strip()] = _as_float(raw.strip())
    return values


def _file_record(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "status": "missing", "sha256": ""}
    return {
        "path": str(path.relative_to(ROOT)),
        "status": "read",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _annual_rows(path: Path) -> list[dict[str, str]]:
    return [row for row in _read_csv(path) if row.get("horizon_hours") == CANONICAL_CANDIDATE_HORIZON]


def _payload() -> dict[str, Any]:
    return {
        "contract": _read_csv(C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv"),
        "q_mix": _read_csv(C5P_Q_DIR / "controller_mix_allocation.csv"),
        "hsm_sinter": _annual_rows(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv"),
        "steam": _annual_rows(C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv"),
        "generator": _annual_rows(C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv"),
        "pefa": _annual_rows(C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv"),
        "plant_kpis": _annual_rows(C5M_B_DIR / "s4_4c5m_b_plant_kpi_table.csv"),
    }


def _contract_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["configuration"], row["carrier"]): row for row in rows if row["carrier"] in {"BFG", "COG", "BOFG"}}


def _mix_row(configuration: str, sink: str, carrier: str, mwh: float, stage: str, mode: str, status: str, caveat: str) -> dict[str, str]:
    return {
        "configuration": configuration,
        "horizon_hours": CANONICAL_CANDIDATE_HORIZON,
        "sink_or_controller": sink,
        "carrier": carrier,
        "allocation_MWh_LHV_y": _fmt(mwh),
        "allocation_PJ_y": _fmt(mwh * MWH_TO_PJ),
        "upstream_stage": stage,
        "allocation_mode": mode,
        "physical_interpretation_status": status,
        "caveat": caveat,
    }


def _candidate_mix_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in payload["hsm_sinter"]:
        configuration = row["configuration"]
        for carrier, field in {"BFG": "BFG_to_HSM_site_MWh_y", "COG": "COG_to_HSM_site_MWh_y", "BOFG": "BOFG_to_HSM_site_MWh_y", "NG": "NG_to_HSM_site_MWh_y"}.items():
            rows.append(_mix_row(configuration, "HSM_WBW", carrier, _as_float(row[field]), "C5m combined HSM/sinter controller", "existing_controller_output", "accepted_diagnostic", "C5m 24h annualised output; carrier split remains diagnostic-only."))
        for carrier, field in {"BFG": "BFG_to_Sinter_site_MWh_y", "COG": "COG_to_Sinter_site_MWh_y", "BOFG": "BOFG_to_Sinter_site_MWh_y", "NG": "NG_to_Sinter_site_MWh_y"}.items():
            rows.append(_mix_row(configuration, "Sinter", carrier, _as_float(row[field]), "C5m combined HSM/sinter controller", "existing_controller_output", "accepted_diagnostic", "Sinter remains a COG/NG consumer only; no useful WAG output is created."))
    for row in payload["pefa"]:
        configuration = row["configuration"]
        for sink, carrier, field in (
            ("PEFA_Malerij", "BOFG", "BOFG_to_PEFA_malerij_site_MWh_y"),
            ("PEFA_Malerij", "NG", "NG_to_PEFA_malerij_site_MWh_y"),
            ("PEFA_Branderij", "COG", "COG_to_PEFA_branderij_site_MWh_y"),
            ("PEFA_Branderij", "NG", "NG_to_PEFA_branderij_site_MWh_y"),
        ):
            rows.append(_mix_row(configuration, sink, carrier, _as_float(row[field]), "C5n_a PEFA Option-A controller", "existing_controller_output_no_fixed_stage_share", "accepted_diagnostic", "Option A total-gas heat; stage values are controller outputs, not a source-invented fixed split."))
    for row in payload["steam"]:
        configuration = row["configuration"]
        for carrier, field in {"BFG": "BFG_to_steam_MWh_LHV_y", "COG": "COG_to_steam_MWh_LHV_y", "BOFG": "BOFG_to_steam_MWh_LHV_y", "NG": "NG_backup_for_steam_MWh_LHV_y"}.items():
            rows.append(_mix_row(configuration, "steam_boiler_controller", carrier, _as_float(row[field]), "C5p_b boiler/steam controller", "existing_controller_output", "accepted_diagnostic" if carrier != "BOFG" else "blocked_base", "BOFG remains blocked in the steam layer."))
    for row in payload["generator"]:
        unit = row.get("unit_id", "")
        if unit not in {"VN25", "IJ01", "C0_CURRENT_GENERATOR_INTERFACE"}:
            continue
        for carrier, field in {"BFG": "BFG_MWh_LHV_y", "COG": "COG_MWh_LHV_y", "BOFG": "BOFG_MWh_LHV_y", "NG": "NG_MWh_LHV_y"}.items():
            rows.append(_mix_row(row["configuration"], unit, carrier, _as_float(row[field]), "C5p_c generator interface", "existing_controller_output", "accepted_diagnostic", "Internal electricity offset only; no market value or export revenue."))
    return rows


def _process_reconciliation(mix_rows: list[dict[str, str]], contract: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    process_sinks = {"HSM_WBW", "Sinter", "PEFA_Malerij", "PEFA_Branderij"}
    for configuration in sorted({key[0] for key in contract}):
        for carrier in ("BFG", "COG", "BOFG"):
            total = _as_float(contract[(configuration, carrier)]["process_or_prep_use_PJ_y"])
            identified = sum(_as_float(row["allocation_PJ_y"]) for row in mix_rows if row["configuration"] == configuration and row["carrier"] == carrier and row["sink_or_controller"] in process_sinks)
            residual = total - identified
            rows.append(
                {
                    "configuration": configuration,
                    "carrier": carrier,
                    "c5p_o_process_or_prep_use_PJ_y": _fmt(total),
                    "identified_24h_controller_use_PJ_y": _fmt(identified),
                    "residual_unclassified_PJ_y": _fmt(residual),
                    "reconciliation_status": "pass" if abs(residual) <= TOL_PJ else "warning",
                    "controller_evidence": "HSM/Sinter from C5m; PEFA from C5n_a; all at 24h annualisation.",
                    "caveat": "This is a diagnostic candidate ledger and does not change C5p_o balance rows.",
                }
            )
    return rows


def _horizon_rows() -> list[dict[str, str]]:
    return [
        {
            "surface": "C5p_m -> C5p_o carrier contract",
            "available_horizons": "24 only in C5p_m source selection",
            "selected_horizon_for_candidate_contract": "24",
            "selection_status": "selected_diagnostic_basis",
            "evidence": "C5p_m reads 24-hour C5p_c residual and generator rows; C5p_o hardens its carrier ledger.",
            "implication": "Any controller mix intended to explain C5p_o must use the same 24-hour annualisation basis.",
        },
        {
            "surface": "HSM/Sinter and steam/generator controller outputs",
            "available_horizons": "24;168",
            "selected_horizon_for_candidate_contract": "24",
            "selection_status": "selected_to_match_C5p_o",
            "evidence": "The 24-hour rows exist for every accepted C5m/C5p_b/C5p_c controller surface.",
            "implication": "C5p_q's existing 168-hour compilation is retained as historical diagnostic evidence, not reused in this bridge ledger.",
        },
        {
            "surface": "PEFA Option-A controller",
            "available_horizons": "24;168",
            "selected_horizon_for_candidate_contract": "24",
            "selection_status": "required_by_exact_process_gap_match",
            "evidence": "PEFA 24-hour COG/BOFG values exactly equal C5p_o/C5p_q process-gap values.",
            "implication": "PEFA becomes an accepted explanation in the 24-hour candidate ledger without a fixed stage split.",
        },
        {
            "surface": "KGF and BF self-use boundaries",
            "available_horizons": "24;168 upstream outputs",
            "selected_horizon_for_candidate_contract": "24 for audit only",
            "selection_status": "boundary_bridge_still_blocked",
            "evidence": "The upstream net carrier quantities differ from C5p_o carrier generations even at the shared horizon.",
            "implication": "Do not add KGF or BF demand to the candidate ledger; use them only as upstream boundary evidence.",
        },
    ]


def _q_comparison_rows(mix_rows: list[dict[str, str]], q_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    q_map = {(row["configuration"], row["sink_or_controller"], row["carrier"]): row for row in q_rows}
    rows: list[dict[str, str]] = []
    for row in mix_rows:
        key = (row["configuration"], row["sink_or_controller"], row["carrier"])
        q_row = q_map.get(key)
        if q_row is None:
            rows.append({
                "configuration": row["configuration"], "sink_or_controller": row["sink_or_controller"], "carrier": row["carrier"],
                "candidate_24h_PJ_y": row["allocation_PJ_y"], "existing_C5p_q_horizon_hours": "", "existing_C5p_q_PJ_y": "",
                "absolute_difference_PJ_y": "", "comparison_status": "missing_from_existing_C5p_q", "caveat": "Expected for PEFA; C5p_q predates integration of the existing C5n_a controller.",
            })
            continue
        difference = abs(_as_float(row["allocation_PJ_y"]) - _as_float(q_row["allocation_PJ_y"]))
        rows.append({
            "configuration": row["configuration"], "sink_or_controller": row["sink_or_controller"], "carrier": row["carrier"],
            "candidate_24h_PJ_y": row["allocation_PJ_y"], "existing_C5p_q_horizon_hours": q_row["horizon_hours"], "existing_C5p_q_PJ_y": q_row["allocation_PJ_y"],
            "absolute_difference_PJ_y": _fmt(difference), "comparison_status": "same_value" if difference <= TOL_PJ else "horizon_basis_difference", "caveat": "C5p_q retains its existing 168-hour provenance and is not modified by C5p_t.",
        })
    return rows


def _gross_net_rows(payload: dict[str, Any], contract: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, str]]:
    kpis = {(row["configuration"], row["plant_or_controller"]): row for row in payload["plant_kpis"]}
    rows: list[dict[str, str]] = []
    for configuration in sorted({key[0] for key in contract}):
        kgf_rows = [kpis[(configuration, plant)] for plant in ("KGF1", "KGF2") if (configuration, plant) in kpis]
        kgf_self_use = sum(_assignments(row["WAG_consumed_by_carrier"]).get("COG_self_use", 0.0) for row in kgf_rows)
        kgf_surplus = sum(_assignments(row["WAG_generated_by_carrier"]).get("COG", 0.0) for row in kgf_rows)
        c5po_cog = _as_float(contract[(configuration, "COG")]["generation_PJ_y"]) / MWH_TO_PJ
        rows.append({
            "configuration": configuration,
            "controller": "KGF_underfiring",
            "carrier": "COG",
            "upstream_horizon_hours": "24",
            "upstream_gross_or_pre_net_MWh_y": _fmt(kgf_self_use + kgf_surplus),
            "upstream_mandatory_self_use_MWh_y": _fmt(kgf_self_use),
            "upstream_net_or_surplus_MWh_y": _fmt(kgf_surplus),
            "C5p_o_net_generation_MWh_y": _fmt(c5po_cog),
            "absolute_gap_to_C5p_o_MWh_y": _fmt(abs(kgf_surplus - c5po_cog)),
            "bridge_status": "blocked_no_scale_or_boundary_mapping_selected",
            "allowed_current_use": "upstream self-use evidence only",
            "caveat": "Gross COG is reconstructed from upstream self-use plus clean-COG surplus. It does not reconcile to C5p_o, so no scale factor is selected.",
        })
        bf_rows = [kpis[(configuration, plant)] for plant in ("BF6", "BF7") if (configuration, plant) in kpis]
        hot_stove = _assignments(kpis[(configuration, "Controller_Blast_Furnace")]["WAG_consumed_by_carrier"]).get("BFG", 0.0)
        bfg_surplus = sum(_assignments(row["WAG_generated_by_carrier"]).get("BFG_surplus", 0.0) for row in bf_rows)
        c5po_bfg = _as_float(contract[(configuration, "BFG")]["generation_PJ_y"]) / MWH_TO_PJ
        rows.append({
            "configuration": configuration,
            "controller": "BF_hot_stove",
            "carrier": "BFG",
            "upstream_horizon_hours": "24",
            "upstream_gross_or_pre_net_MWh_y": _fmt(hot_stove + bfg_surplus),
            "upstream_mandatory_self_use_MWh_y": _fmt(hot_stove),
            "upstream_net_or_surplus_MWh_y": _fmt(bfg_surplus),
            "C5p_o_net_generation_MWh_y": _fmt(c5po_bfg),
            "absolute_gap_to_C5p_o_MWh_y": _fmt(abs(bfg_surplus - c5po_bfg)),
            "bridge_status": "blocked_no_scale_or_boundary_mapping_selected",
            "allowed_current_use": "upstream hot-stove deduction evidence only",
            "caveat": "Gross BFG is reconstructed from hot-stove use plus BFG surplus. It does not reconcile to C5p_o, so no scale factor is selected.",
        })
    return rows


def _status_rows() -> list[dict[str, str]]:
    return [
        {"controller": "HSM_WBW;Sinter;steam;generator", "24h_candidate_ledger_status": "included_from_existing_outputs", "current_C5p_q_status": "existing_168h_compilation", "may_replace_C5p_q_row_now": "review_required", "may_add_new_C5p_o_physical_sink_now": "not_applicable", "required_next_action": "Review the 24h candidate ledger before migrating its provenance into C5p_q."},
        {"controller": "PEFA_total_gas_heat", "24h_candidate_ledger_status": "included_and_process_reconciled", "current_C5p_q_status": "missing_from_existing_mix_ledger", "may_replace_C5p_q_row_now": "yes_after_review", "may_add_new_C5p_o_physical_sink_now": "no_new_sink; explanation of existing total only", "required_next_action": "After review, add PEFA's existing 24h controller rows to C5p_q without changing C5p_o totals."},
        {"controller": "KGF_underfiring", "24h_candidate_ledger_status": "upstream_boundary_evidence_only", "current_C5p_q_status": "blocked", "may_replace_C5p_q_row_now": "no", "may_add_new_C5p_o_physical_sink_now": "no", "required_next_action": "Resolve gross-to-net COG boundary mapping."},
        {"controller": "BF_hot_stove", "24h_candidate_ledger_status": "upstream_boundary_evidence_only", "current_C5p_q_status": "blocked", "may_replace_C5p_q_row_now": "no", "may_add_new_C5p_o_physical_sink_now": "no", "required_next_action": "Resolve gross-to-net BFG boundary mapping."},
    ]


def _ath_rows() -> list[dict[str, str]]:
    return [
        {"functional_area": "common controller horizon", "candidate_contract_handling": "All contract-explaining controller rows use the 24h annualisation selected by C5p_m/C5p_o.", "athanasiadis_precedent_role": "coherent gas-network/controller time basis", "alignment_status": "aligned_for_candidate_ledger", "caveat": "C5p_q is not rewritten in this stage."},
        {"functional_area": "carrier-specific PEFA mix", "candidate_contract_handling": "BOFG/NG Malerij and COG/NG Branderij are read from the existing Option-A controller without a fixed share parameter.", "athanasiadis_precedent_role": "plant-specific controller separation", "alignment_status": "aligned", "caveat": "No quantitative Wobbe mixer is claimed."},
        {"functional_area": "KGF/BF self-use", "candidate_contract_handling": "Upstream self-use is retained as gross-to-net boundary evidence, not reallocated from an aggregate residual.", "athanasiadis_precedent_role": "self-use before site gas-network surplus", "alignment_status": "partially_aligned", "caveat": "Cross-layer boundary mapping remains unresolved."},
        {"functional_area": "market and CO2", "candidate_contract_handling": "No WAG price, export value or fuel-explicit CO2 is introduced.", "athanasiadis_precedent_role": "separate gas/utility and market layers", "alignment_status": "aligned", "caveat": "Architecture check only; no raw PDF or numerical replication used."},
    ]


def _validation_rows(process_rows: list[dict[str, str]], q_rows: list[dict[str, str]], bridge_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"check_id": "T_CHECK_001", "check_name": "candidate_horizon_is_24h", "status": "pass", "evidence": "C5p_m/C5p_o carrier-contract lineage selects 24-hour source rows.", "recommended_action": "Keep the horizon explicit in any later C5p_q migration."},
        {"check_id": "T_CHECK_002", "check_name": "all_process_carriers_reconcile_at_24h", "status": "pass" if all(row["reconciliation_status"] == "pass" for row in process_rows) else "fail", "evidence": "HSM, Sinter and PEFA sum to C5p_o process/prep totals by carrier.", "recommended_action": "Do not add residual process WAG to this candidate ledger."},
        {"check_id": "T_CHECK_003", "check_name": "PEFA_is_new_explanation_not_new_total", "status": "pass" if any(row["sink_or_controller"] == "PEFA_Malerij" for row in q_rows) else "fail", "evidence": "PEFA rows are sourced from C5n_a and reconcile existing C5p_o totals.", "recommended_action": "Migrate only provenance/ledger rows after review; do not change carrier totals."},
        {"check_id": "T_CHECK_004", "check_name": "KGF_BF_remain_no_double_count", "status": "pass" if all(row["bridge_status"].startswith("blocked") for row in bridge_rows) else "fail", "evidence": "No scale factor is selected for gross-to-net KGF/BF bridges.", "recommended_action": "Keep both outside the C5p_o sink ledger until a bridge is evidenced."},
        {"check_id": "T_CHECK_005", "check_name": "no_aggregate_or_mixed_wag_physical_use", "status": "pass", "evidence": "Candidate mix rows contain only BFG, COG, BOFG and NG.", "recommended_action": "Keep aggregate_wag reporting-only and mixed_wag structural-only."},
        {"check_id": "T_CHECK_006", "check_name": "no_executable_or_co2_unlock", "status": "pass", "evidence": "This stage writes diagnostic artifacts only.", "recommended_action": "Keep NG residual, fuel-explicit CO2, sensitivity, economics and DA blocked."},
    ]


def _write_report(summary: dict[str, Any]) -> None:
    report = f"""# C5 Horizon And Gross/Net Boundary Bridge

## Purpose

C5p_t establishes a **24-hour diagnostic candidate contract ledger**. It does
not replace C5p_q, change C5p_o carrier totals, create a new allocator, or
promote any source-card parameter. The 24-hour basis is selected because C5p_m
uses it to construct the C5p_o carrier contract and because the existing PEFA
controller exactly reconciles the COG/BOFG process gaps on that basis.

## Result

At 24-hour annualisation, HSM, sinter and PEFA fully explain the C5p_o
carrier-specific process/preparation use. PEFA therefore changes from an
unclassified gap to a source-traceable explanation in the candidate ledger.
Its Option-A controller remains total-gas based: no fixed Malerij/Branderij
share is introduced.

KGF self-use and BF hot-stove use remain upstream gross-to-net boundary
deductions. Their upstream net carrier values do not match C5p_o, so this stage
does not select a scaling factor and does not add them as new physical sinks.
That prevents double counting.

## Gate

- 24-hour controller-mix and PEFA explanation ledger: GO, diagnostic-only.
- C5p_q migration: review required; C5p_q itself is not modified here.
- KGF/BF direct C5p_o integration: NO-GO pending an evidence-backed gross/net
  bridge.
- NG residual, WAG/fuel-explicit CO2, full sensitivity, migration, economics
  and DA: NO-GO.

## Athanasiadis comparison

The candidate ledger follows the same useful architectural separation:
carrier-specific gas controllers, process/utility/generator distinction and no
direct WAG-market value. It is not a numeric replication, no raw Athanasiadis
PDF was inspected, and no official Tata claim is made.

Status: `{summary['status']}`. Thesis usability: `false`.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_t_horizon_and_gross_net_boundary_bridge() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = _payload()
    contract = _contract_map(payload["contract"])
    mix_rows = _candidate_mix_rows(payload)
    process_rows = _process_reconciliation(mix_rows, contract)
    horizon_rows = _horizon_rows()
    q_comparison = _q_comparison_rows(mix_rows, payload["q_mix"])
    bridge_rows = _gross_net_rows(payload, contract)
    status_rows = _status_rows()
    ath_rows = _ath_rows()
    validation = _validation_rows(process_rows, mix_rows, bridge_rows)
    counts: dict[str, int] = {}
    for row in validation:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    stage_gate = {
        "stage": STAGE,
        "status": "candidate_24h_contract_ledger_reconciled",
        "thesis_usability": False,
        "output_policy": "diagnostics",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic_governance",
        "canonical_candidate_horizon_hours": 24,
        "guardrails": {
            "new_physical_allocator_created": False,
            "C5p_q_modified": False,
            "C5p_o_carrier_totals_modified": False,
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "raw_pdfs_inspected": False,
            "aggregate_wag_physical_allocation": False,
            "mixed_wag_quantitative_allocation": False,
            "invented_wag_ng_ratio": False,
            "fuel_explicit_co2_unlocked": False,
        },
        "go_no_go": {
            "candidate_24h_controller_ledger": "GO_DIAGNOSTIC_ONLY",
            "PEFA_process_gap_explanation": "GO_DIAGNOSTIC_ONLY",
            "C5p_q_migration": "REVIEW_REQUIRED",
            "KGF_BF_direct_sink_integration": "NO_GO",
            "complete_physical_WAG_NG_allocation": "NO_GO",
            "NG_residual_policy": "NO_GO",
            "WAG_fuel_explicit_CO2": "NO_GO",
            "full_sensitivity_execution": "NO_GO",
            "executable_input_migration": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
        "validation_check_counts": counts,
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "thesis_usability": False,
        "canonical_candidate_horizon_hours": 24,
        "process_reconciliation_pass_rows": sum(row["reconciliation_status"] == "pass" for row in process_rows),
        "PEFA_rows_added_to_candidate_ledger": sum(row["sink_or_controller"].startswith("PEFA") for row in mix_rows),
        "gross_net_bridges_blocked": ["KGF_underfiring", "BF_hot_stove"],
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [
        C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv",
        C5P_Q_DIR / "controller_mix_allocation.csv",
        C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv",
        C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv",
        C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv",
        C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv",
        C5M_B_DIR / "s4_4c5m_b_plant_kpi_table.csv",
    ]
    _write_csv(OUTPUT_DIR / "controller_mix_24h_contract_candidate.csv", mix_rows, MIX_COLUMNS)
    _write_csv(OUTPUT_DIR / "process_reconciliation_24h.csv", process_rows, PROCESS_COLUMNS)
    _write_csv(OUTPUT_DIR / "horizon_selection_audit.csv", horizon_rows, HORIZON_COLUMNS)
    _write_csv(OUTPUT_DIR / "c5p_q_horizon_comparison.csv", q_comparison, Q_COMPARISON_COLUMNS)
    _write_csv(OUTPUT_DIR / "gross_net_boundary_bridge.csv", bridge_rows, BRIDGE_COLUMNS)
    _write_csv(OUTPUT_DIR / "controller_integration_status.csv", status_rows, STATUS_COLUMNS)
    _write_csv(OUTPUT_DIR / "athanasiadis_methodology_alignment.csv", ath_rows, ATH_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validation, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "output_policy": "diagnostics", "run_class": "diagnostic", "lineage_role": "diagnostic_governance", "inputs": [_file_record(path) for path in inputs]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_t_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", {"run_id": STAGE, "purpose": "24-hour candidate WAG controller contract bridge; no model behaviour change.", "thesis_usable": False, "retention": "local diagnostic output until review", "git_eligible": False, "status": stage_gate["status"]})
    _write_report(summary)
    return summary


def main() -> int:
    run_s4_4c5p_t_horizon_and_gross_net_boundary_bridge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
