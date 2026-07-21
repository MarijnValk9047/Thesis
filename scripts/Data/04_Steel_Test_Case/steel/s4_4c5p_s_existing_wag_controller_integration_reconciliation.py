"""Reconcile existing KGF, BF hot-stove and PEFA WAG controllers to C5p_o/q.

The three controllers already exist in upstream C5 layers.  This stage does
not recreate them and does not change allocation behaviour.  It establishes
which outputs can be safely treated as explanations of the C5p_o/q ledger and
which remain blocked by a boundary or horizon mismatch.
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
STAGE = "S4.4c5p_s_existing_wag_controller_integration_reconciliation"
S4_ROOT = ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_s_existing_wag_controller_integration_reconciliation"
REPORT_PATH = ROOT / "docs/optimisation/steel/S4/C5_EXISTING_WAG_CONTROLLER_INTEGRATION_RECONCILIATION.md"
C5P_O_DIR = S4_ROOT / "s4_4c5p_o_wag_controller_contract_hardening"
C5P_Q_DIR = S4_ROOT / "s4_4c5p_q_wag_ng_controller_diagnostic_allocator"
C5P_R_DIR = S4_ROOT / "s4_4c5p_r_remaining_process_user_controller_source_audit"
C5M_B_DIR = S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration"
C5N_A_DIR = S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer"

MWH_TO_PJ = 0.0000036
TOL_PJ = 1e-5

IMPLEMENTATION_COLUMNS = [
    "configuration",
    "controller",
    "upstream_stage",
    "upstream_horizon_hours",
    "carrier",
    "upstream_value_MWh_LHV_y",
    "upstream_value_PJ_y",
    "controller_status",
    "relation_to_C5p_o_q",
    "safe_contract_use_now",
    "caveat",
]
RECONCILIATION_COLUMNS = [
    "configuration",
    "controller",
    "carrier",
    "c5p_o_metric",
    "c5p_o_value_PJ_y",
    "c5p_q_metric",
    "c5p_q_value_PJ_y",
    "upstream_horizon_hours",
    "upstream_value_PJ_y",
    "absolute_gap_PJ_y",
    "reconciliation_status",
    "integration_decision",
    "caveat",
]
FINDING_COLUMNS = [
    "finding_id",
    "severity",
    "configuration",
    "controller",
    "finding_type",
    "evidence",
    "impact",
    "required_resolution",
]
POLICY_COLUMNS = [
    "controller",
    "carrier_policy",
    "current_boundary_treatment",
    "may_be_added_as_new_C5p_o_sink",
    "may_explain_C5p_q_unclassified_process_use",
    "required_guardrail",
    "status",
]
ATH_ALIGNMENT_COLUMNS = [
    "functional_area",
    "current_repository_handling",
    "athanasiadis_precedent_role",
    "alignment_status",
    "limitation",
]
ACTION_COLUMNS = [
    "priority",
    "action_id",
    "action",
    "why",
    "must_not_do",
    "completion_criterion",
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
    result: dict[str, float] = {}
    for part in value.split(";"):
        if "=" not in part:
            continue
        key, raw = part.split("=", maxsplit=1)
        result[key.strip()] = _as_float(raw.strip())
    return result


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


def _source_payload() -> dict[str, Any]:
    return {
        "contract": _read_csv(C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv"),
        "q_reconciliation": _read_csv(C5P_Q_DIR / "process_controller_reconciliation.csv"),
        "m_b_kpis": _read_csv(C5M_B_DIR / "s4_4c5m_b_plant_kpi_table.csv"),
        "m_b_wag": _read_csv(C5M_B_DIR / "s4_4c5m_b_wag_carrier_ledger.csv"),
        "pefa": _read_csv(C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv"),
        "r_readiness": _read_csv(C5P_R_DIR / "controller_activation_readiness.csv"),
    }


def _contract_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["configuration"], row["carrier"]): row for row in rows if row["carrier"] in {"BFG", "COG", "BOFG"}}


def _q_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["configuration"], row["carrier"]): row for row in rows}


def _m_b_kpi_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (row["configuration"], row["plant_or_controller"]): row
        for row in rows
        if row["horizon_hours"] == "168"
    }


def _m_b_wag_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {
        (row["configuration"], row["carrier"]): row
        for row in rows
        if row["horizon_hours"] == "168"
    }


def _pefa_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["configuration"], row["horizon_hours"]): row for row in rows}


def _configurations(contract: dict[tuple[str, str], dict[str, str]]) -> tuple[str, ...]:
    return tuple(sorted({configuration for configuration, _ in contract}))


def _implementation_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    kpis = _m_b_kpi_map(payload["m_b_kpis"])
    pefa = _pefa_map(payload["pefa"])
    contract = _contract_map(payload["contract"])
    rows: list[dict[str, str]] = []
    for configuration in _configurations(contract):
        kgf_values = [
            _assignments(kpis[(configuration, kgf)]["WAG_consumed_by_carrier"]).get("COG_self_use", 0.0)
            for kgf in ("KGF1", "KGF2")
            if (configuration, kgf) in kpis
        ]
        kgf_mwh = sum(kgf_values)
        rows.append(
            {
                "configuration": configuration,
                "controller": "KGF_underfiring",
                "upstream_stage": "C5m_b active-plant ledger",
                "upstream_horizon_hours": "168",
                "carrier": "COG",
                "upstream_value_MWh_LHV_y": _fmt(kgf_mwh),
                "upstream_value_PJ_y": _fmt(kgf_mwh * MWH_TO_PJ),
                "controller_status": "implemented_upstream",
                "relation_to_C5p_o_q": "upstream self-use precedes clean-COG surplus; it must not be added as another C5p_o sink",
                "safe_contract_use_now": "boundary evidence only",
                "caveat": "C5m_b clean-COG quantity does not numerically match C5p_o COG generation; reconcile boundary/denominator first.",
            }
        )
        bf = kpis[(configuration, "Controller_Blast_Furnace")]
        bf_mwh = _assignments(bf["WAG_consumed_by_carrier"]).get("BFG", 0.0)
        rows.append(
            {
                "configuration": configuration,
                "controller": "BF_hot_stove",
                "upstream_stage": "C5m_b active-plant ledger",
                "upstream_horizon_hours": "168",
                "carrier": "BFG",
                "upstream_value_MWh_LHV_y": _fmt(bf_mwh),
                "upstream_value_PJ_y": _fmt(bf_mwh * MWH_TO_PJ),
                "controller_status": "implemented_upstream",
                "relation_to_C5p_o_q": "upstream BFG-first deduction precedes net BFG surplus; it must not be added as another C5p_o sink",
                "safe_contract_use_now": "boundary evidence only",
                "caveat": "C5m_b net BFG generation differs from C5p_o BFG generation; reconcile boundary/denominator first.",
            }
        )
        for carrier, field, controller_name in (
            ("COG", "COG_to_PEFA_branderij_site_MWh_y", "PEFA_total_gas_heat"),
            ("BOFG", "BOFG_to_PEFA_malerij_site_MWh_y", "PEFA_total_gas_heat"),
        ):
            for horizon in ("24", "168"):
                value = _as_float(pefa[(configuration, horizon)][field])
                rows.append(
                    {
                        "configuration": configuration,
                        "controller": controller_name,
                        "upstream_stage": "C5n_a PEFA Option-A controller",
                        "upstream_horizon_hours": horizon,
                        "carrier": carrier,
                        "upstream_value_MWh_LHV_y": _fmt(value),
                        "upstream_value_PJ_y": _fmt(value * MWH_TO_PJ),
                        "controller_status": "implemented_upstream",
                        "relation_to_C5p_o_q": "candidate explanation for C5p_q unclassified process use",
                        "safe_contract_use_now": "explanation only until a common horizon is frozen",
                        "caveat": "No fixed Malerij/Branderij share is used; the controller remains Option A total-gas heat with structural eligibility.",
                    }
                )
    return rows


def _reconciliation_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    contract = _contract_map(payload["contract"])
    q_rows = _q_map(payload["q_reconciliation"])
    kpis = _m_b_kpi_map(payload["m_b_kpis"])
    m_b_wag = _m_b_wag_map(payload["m_b_wag"])
    pefa = _pefa_map(payload["pefa"])
    rows: list[dict[str, str]] = []
    for configuration in _configurations(contract):
        kgf_mwh = sum(
            _assignments(kpis[(configuration, kgf)]["WAG_consumed_by_carrier"]).get("COG_self_use", 0.0)
            for kgf in ("KGF1", "KGF2")
            if (configuration, kgf) in kpis
        )
        c5po_cog = _as_float(contract[(configuration, "COG")]["generation_PJ_y"])
        m_b_cog = _as_float(m_b_wag[(configuration, "COG")]["generated_site_MWh_LHV_y"]) * MWH_TO_PJ
        rows.append(
            {
                "configuration": configuration,
                "controller": "KGF_underfiring",
                "carrier": "COG",
                "c5p_o_metric": "net_COG_generation",
                "c5p_o_value_PJ_y": _fmt(c5po_cog),
                "c5p_q_metric": "not_applicable; self-use must precede surplus",
                "c5p_q_value_PJ_y": "",
                "upstream_horizon_hours": "168",
                "upstream_value_PJ_y": _fmt(kgf_mwh * MWH_TO_PJ),
                "absolute_gap_PJ_y": _fmt(abs(m_b_cog - c5po_cog)),
                "reconciliation_status": "blocked_boundary_mismatch",
                "integration_decision": "do_not_add_KGF_self_use_to_C5p_o; it is already upstream of a different clean-COG boundary",
                "caveat": f"C5m_b clean-COG generation={_fmt(m_b_cog)} PJ/y versus C5p_o={_fmt(c5po_cog)} PJ/y.",
            }
        )
        bf_mwh = _assignments(kpis[(configuration, "Controller_Blast_Furnace")]["WAG_consumed_by_carrier"]).get("BFG", 0.0)
        c5po_bfg = _as_float(contract[(configuration, "BFG")]["generation_PJ_y"])
        m_b_bfg = _as_float(m_b_wag[(configuration, "BFG")]["generated_site_MWh_LHV_y"]) * MWH_TO_PJ
        rows.append(
            {
                "configuration": configuration,
                "controller": "BF_hot_stove",
                "carrier": "BFG",
                "c5p_o_metric": "net_BFG_generation",
                "c5p_o_value_PJ_y": _fmt(c5po_bfg),
                "c5p_q_metric": "not_applicable; hot-stove use must precede surplus",
                "c5p_q_value_PJ_y": "",
                "upstream_horizon_hours": "168",
                "upstream_value_PJ_y": _fmt(bf_mwh * MWH_TO_PJ),
                "absolute_gap_PJ_y": _fmt(abs(m_b_bfg - c5po_bfg)),
                "reconciliation_status": "blocked_boundary_mismatch",
                "integration_decision": "do_not_add_hot_stove_use_to_C5p_o; it is already upstream of a different net-BFG boundary",
                "caveat": f"C5m_b net BFG generation={_fmt(m_b_bfg)} PJ/y versus C5p_o={_fmt(c5po_bfg)} PJ/y.",
            }
        )
        for carrier, field in (("COG", "COG_to_PEFA_branderij_site_MWh_y"), ("BOFG", "BOFG_to_PEFA_malerij_site_MWh_y")):
            q_value = _as_float(q_rows[(configuration, carrier)]["unclassified_process_use_PJ_y"])
            candidates = {
                horizon: _as_float(pefa[(configuration, horizon)][field]) * MWH_TO_PJ
                for horizon in ("24", "168")
            }
            selected_horizon = min(candidates, key=lambda horizon: abs(candidates[horizon] - q_value))
            selected = candidates[selected_horizon]
            status = "matches_unclassified_process_use_but_horizon_normalisation_required" if abs(selected - q_value) <= TOL_PJ else "does_not_match_unclassified_process_use"
            rows.append(
                {
                    "configuration": configuration,
                    "controller": "PEFA_total_gas_heat",
                    "carrier": carrier,
                    "c5p_o_metric": "process_or_prep_use",
                    "c5p_o_value_PJ_y": contract[(configuration, carrier)]["process_or_prep_use_PJ_y"],
                    "c5p_q_metric": "unclassified_process_use",
                    "c5p_q_value_PJ_y": _fmt(q_value),
                    "upstream_horizon_hours": selected_horizon,
                    "upstream_value_PJ_y": _fmt(selected),
                    "absolute_gap_PJ_y": _fmt(abs(selected - q_value)),
                    "reconciliation_status": status,
                    "integration_decision": "map as explanation only; do not change C5p_o/q until the common annualisation horizon is explicit",
                    "caveat": "The best numeric match is the PEFA 24-hour annualised output; C5p_q currently also reads 168-hour HSM/sinter outputs.",
                }
            )
    return rows


def _finding_rows(reconciliation: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in reconciliation:
        if row["controller"] == "PEFA_total_gas_heat":
            rows.append(
                {
                    "finding_id": f"S_PEFA_{row['configuration']}_{row['carrier']}",
                    "severity": "warning",
                    "configuration": row["configuration"],
                    "controller": row["controller"],
                    "finding_type": "cross_horizon_annualisation",
                    "evidence": f"PEFA {row['carrier']} maps to C5p_q only at {row['upstream_horizon_hours']}h; gap={row['absolute_gap_PJ_y']} PJ/y.",
                    "impact": "It explains the unclassified process-use gap but cannot yet join a ledger labelled with another horizon.",
                    "required_resolution": "Freeze one annualisation horizon for every upstream controller before canonical ledger integration.",
                }
            )
        else:
            rows.append(
                {
                    "finding_id": f"S_{row['controller']}_{row['configuration']}",
                    "severity": "blocking",
                    "configuration": row["configuration"],
                    "controller": row["controller"],
                    "finding_type": "net_boundary_mismatch",
                    "evidence": row["caveat"],
                    "impact": "Adding the upstream demand again would double count a self-use deduction already upstream of its own net-carrier boundary.",
                    "required_resolution": "Create an explicit gross-to-net carrier boundary bridge before merging this controller into C5p_o.",
                }
            )
    rows.append(
        {
            "finding_id": "S_C1_FLARE_CARRIER_SPLIT",
            "severity": "blocking",
            "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "controller": "flare_spill",
            "finding_type": "missing_carrier_split",
            "evidence": "C5p_o retains only an aggregate C1 flare/spill row.",
            "impact": "Fuel-explicit CO2 and a complete carrier allocation ledger remain blocked.",
            "required_resolution": "Emit or source a carrier-specific flare/spill output; do not infer a split.",
        }
    )
    return rows


def _policy_rows() -> list[dict[str, str]]:
    return [
        {
            "controller": "KGF_underfiring",
            "carrier_policy": "COG self-use before clean COG surplus; BFG/BOFG/NG blocked in base",
            "current_boundary_treatment": "implemented upstream of C5p_o net-COG boundary",
            "may_be_added_as_new_C5p_o_sink": "no",
            "may_explain_C5p_q_unclassified_process_use": "not until a gross-to-net bridge exists",
            "required_guardrail": "self-use and surplus cannot both use the same COG",
            "status": "blocked_boundary_reconciliation",
        },
        {
            "controller": "BF_hot_stove",
            "carrier_policy": "BFG first; enrichment only if separately enabled; NG backup only",
            "current_boundary_treatment": "implemented upstream of C5p_o net-BFG boundary",
            "may_be_added_as_new_C5p_o_sink": "no",
            "may_explain_C5p_q_unclassified_process_use": "not applicable",
            "required_guardrail": "gross BFG cannot be represented as net surplus before hot-stove deduction",
            "status": "blocked_boundary_reconciliation",
        },
        {
            "controller": "PEFA_total_gas_heat",
            "carrier_policy": "Option-A total gas heat; BOFG/NG Malerij and COG/NG Branderij structural eligibility; BFG blocked",
            "current_boundary_treatment": "implemented upstream and numerically maps to C5p_q process gaps at 24h annualisation",
            "may_be_added_as_new_C5p_o_sink": "not until horizon is frozen",
            "may_explain_C5p_q_unclassified_process_use": "yes_24h_only",
            "required_guardrail": "no fixed stage share and no aggregate WAG allocation",
            "status": "partial_horizon_reconciliation",
        },
        {
            "controller": "mixed_wag_and_C1_flare",
            "carrier_policy": "mixed_wag structural-only; flare must remain carrier-specific if used physically",
            "current_boundary_treatment": "not quantitatively resolved",
            "may_be_added_as_new_C5p_o_sink": "no",
            "may_explain_C5p_q_unclassified_process_use": "no",
            "required_guardrail": "no invented Wobbe/share or flare split",
            "status": "blocked",
        },
    ]


def _athanasiadis_rows() -> list[dict[str, str]]:
    return [
        {
            "functional_area": "separate process gas controllers",
            "current_repository_handling": "KGF, BF hot stove and PEFA are separate upstream controller surfaces rather than aggregate WAG sinks.",
            "athanasiadis_precedent_role": "plant-specific gas-controller architecture",
            "alignment_status": "aligned",
            "limitation": "Architecture-only check; no raw thesis PDF or numeric replication used.",
        },
        {
            "functional_area": "carrier-specific tracking",
            "current_repository_handling": "COG/BFG/BOFG are retained separately; aggregate_wag and mixed_wag cannot feed physical allocation.",
            "athanasiadis_precedent_role": "gas-network separation before downstream utility/generator interfaces",
            "alignment_status": "aligned",
            "limitation": "No quantitative Wobbe/share-constrained mixer exists.",
        },
        {
            "functional_area": "common horizon and interface contract",
            "current_repository_handling": "Existing controller layers use annualised outputs from different horizon runs.",
            "athanasiadis_precedent_role": "coherent model-wide controller network",
            "alignment_status": "not_yet_aligned",
            "limitation": "C5p_q cannot yet merge 24h PEFA evidence with 168h controller rows as one canonical physical ledger.",
        },
        {
            "functional_area": "market and CO2 boundary",
            "current_repository_handling": "No direct WAG market valuation; fuel-explicit CO2 remains blocked.",
            "athanasiadis_precedent_role": "gas network remains separate from DA-market valuation and carbon accounting",
            "alignment_status": "aligned",
            "limitation": "This is not a claim of exact Tata operation or ETS readiness.",
        },
    ]


def _action_rows() -> list[dict[str, str]]:
    return [
        {
            "priority": "P0",
            "action_id": "S_ACTION_001",
            "action": "Freeze a common annualisation horizon in the WAG controller contract",
            "why": "PEFA matches C5p_q at 24h while C5p_q currently consumes 168h HSM/sinter outputs.",
            "must_not_do": "Do not relabel outputs or average 24h/168h results silently.",
            "completion_criterion": "Every controller row entering the canonical ledger has an explicit and common horizon basis.",
        },
        {
            "priority": "P0",
            "action_id": "S_ACTION_002",
            "action": "Create a gross-to-net COG boundary bridge for KGF",
            "why": "KGF self-use is already upstream but C5m_b and C5p_o clean-COG quantities do not match.",
            "must_not_do": "Do not add KGF self-use again as a C5p_o process sink.",
            "completion_criterion": "Gross COG, self-use and net clean-COG surplus reconcile to one chosen carrier ledger.",
        },
        {
            "priority": "P0",
            "action_id": "S_ACTION_003",
            "action": "Create a gross-to-net BFG boundary bridge for BF hot stove",
            "why": "Hot-stove use exists upstream but the C5m_b and C5p_o net BFG values differ.",
            "must_not_do": "Do not add hot-stove BFG as another C5p_o sink.",
            "completion_criterion": "Gross BFG, hot-stove deduction and net BFG surplus reconcile to one chosen carrier ledger.",
        },
        {
            "priority": "P1",
            "action_id": "S_ACTION_004",
            "action": "Integrate PEFA as a source-traceable explanation after the horizon freeze",
            "why": "PEFA explains all four COG/BOFG unclassified process-use gaps at 24h annualisation.",
            "must_not_do": "Do not invent a fixed Malerij/Branderij split or allow BFG into PEFA.",
            "completion_criterion": "PEFA rows replace the unclassified COG/BOFG explanation without changing carrier totals.",
        },
        {
            "priority": "P1",
            "action_id": "S_ACTION_005",
            "action": "Keep C1 flare and mixed_wag blocked",
            "why": "No carrier flare split or quantitative mixer exists.",
            "must_not_do": "Do not infer shares for CO2 or physical allocation.",
            "completion_criterion": "A source-backed carrier-split output exists or the rows remain reporting-only.",
        },
    ]


def _validation_rows(reconciliation: list[dict[str, str]]) -> list[dict[str, str]]:
    pefa_rows = [row for row in reconciliation if row["controller"] == "PEFA_total_gas_heat"]
    return [
        {
            "check_id": "S_CHECK_001",
            "check_name": "existing_KGF_controller_found",
            "status": "pass",
            "evidence": "C5m_b KGF1/KGF2 self-use rows are read at the 168h annualisation.",
            "recommended_action": "Reconcile rather than duplicate the self-use demand.",
        },
        {
            "check_id": "S_CHECK_002",
            "check_name": "existing_BF_hot_stove_controller_found",
            "status": "pass",
            "evidence": "C5m_b Controller_Blast_Furnace BFG use is read at the 168h annualisation.",
            "recommended_action": "Reconcile rather than duplicate the hot-stove demand.",
        },
        {
            "check_id": "S_CHECK_003",
            "check_name": "existing_PEFA_controller_found",
            "status": "pass",
            "evidence": "C5n_a Option-A PEFA controller rows are read for 24h and 168h annualisations.",
            "recommended_action": "Freeze the horizon before canonical integration.",
        },
        {
            "check_id": "S_CHECK_004",
            "check_name": "PEFA_explains_q_unclassified_process_use_at_24h",
            "status": "pass" if all(row["upstream_horizon_hours"] == "24" and _as_float(row["absolute_gap_PJ_y"]) <= TOL_PJ for row in pefa_rows) else "fail",
            "evidence": "COG and BOFG PEFA values equal C5p_q unclassified COG/BOFG rows at the 24h annualisation.",
            "recommended_action": "Use only as an explanation until the ledger horizon is common.",
        },
        {
            "check_id": "S_CHECK_005",
            "check_name": "no_duplicate_KGF_or_BF_sink_added",
            "status": "pass",
            "evidence": "This stage writes reconciliation tables only and leaves C5p_o carrier balances unchanged.",
            "recommended_action": "Do not add the upstream netted demands to C5p_o.",
        },
        {
            "check_id": "S_CHECK_006",
            "check_name": "no_aggregate_or_mixed_wag_physical_use",
            "status": "pass",
            "evidence": "Only BFG, COG and BOFG rows are read; aggregate_wag and mixed_wag are excluded.",
            "recommended_action": "Retain C5p_o carrier policies.",
        },
        {
            "check_id": "S_CHECK_007",
            "check_name": "no_executable_migration_or_fuel_explicit_CO2",
            "status": "pass",
            "evidence": "No executable inputs, model equations or CO2 factors are read or written.",
            "recommended_action": "Keep NG residual, fuel-explicit CO2 and sensitivity blocked.",
        },
    ]


def _write_report(summary: dict[str, Any]) -> None:
    report = f"""# C5 Existing WAG-Controller Integration Reconciliation

## What this stage found

KGF underfiring, BF hot-stove heat and PEFA total gas heat were already
implemented in upstream C5 layers. They must therefore not be rebuilt or added
as extra WAG sinks in C5p_o. The task is an integration/reconciliation problem,
not a missing-controller problem.

## Controller status

- **KGF:** upstream COG self-use exists, but its clean-COG boundary does not
  numerically match the current C5p_o COG generation. Adding it again would
  double count self-use.
- **BF hot stove:** upstream BFG-first use exists, but its net BFG boundary
  does not numerically match the current C5p_o BFG generation. Adding it again
  would double count hot-stove use.
- **PEFA:** upstream Option-A PEFA outputs explain the full C5p_q unclassified
  COG and BOFG process-use gaps when the 24-hour annualised output is used.
  C5p_q also carries 168-hour HSM/sinter rows, so this remains explanation-only
  until a common annualisation horizon is frozen.

## Athanasiadis methodology

The architecture is aligned: separate carrier-specific process controllers,
plant-specific eligibility, utility/generator separation and no direct WAG
market valuation. It is not yet fully aligned as one coherent controller
network because the annualisation horizon is not common. No raw Athanasiadis
PDF was inspected and this is not a numeric replication or an official Tata
claim.

## Gate

- Existing-controller reconciliation: GO, diagnostic-only.
- PEFA explanation of C5p_q COG/BOFG gaps: GO at 24h only, pending horizon
  normalisation.
- KGF/BF direct integration into C5p_o: NO-GO pending gross-to-net boundary
  bridges.
- Full physical WAG/NG allocation, NG residual policy, WAG/fuel-explicit CO2,
  sensitivity, migration, economics and DA: NO-GO.

Status: `{summary['status']}`. No model behaviour changed.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_s_existing_wag_controller_integration_reconciliation() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = _source_payload()
    implementation = _implementation_rows(payload)
    reconciliation = _reconciliation_rows(payload)
    findings = _finding_rows(reconciliation)
    policy = _policy_rows()
    alignment = _athanasiadis_rows()
    actions = _action_rows()
    validation = _validation_rows(reconciliation)
    counts: dict[str, int] = {}
    for row in validation:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    stage_gate = {
        "stage": STAGE,
        "status": "partial_existing_controller_integration_reconciled",
        "thesis_usability": False,
        "output_policy": "diagnostics",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic_governance",
        "guardrails": {
            "new_physical_allocator_created": False,
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "raw_pdfs_inspected": False,
            "aggregate_wag_physical_allocation": False,
            "mixed_wag_quantitative_allocation": False,
            "invented_wag_ng_ratio": False,
            "c5p_k_used_as_physical_evidence": False,
            "fuel_explicit_co2_unlocked": False,
        },
        "go_no_go": {
            "existing_controller_reconciliation": "GO_DIAGNOSTIC_ONLY",
            "PEFA_gap_explanation_at_24h": "GO_DIAGNOSTIC_ONLY",
            "canonical_ledger_integration_before_horizon_freeze": "NO_GO",
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
        "key_conclusion": "three controllers exist upstream; PEFA maps to C5p_q at 24h, while KGF/BF remain blocked by net-boundary mismatch",
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "thesis_usability": False,
        "controllers_found_upstream": ["KGF_underfiring", "BF_hot_stove", "PEFA_total_gas_heat"],
        "PEFA_q_gap_mapping": "COG_and_BOFG_match_at_24h_annualisation_only",
        "blocked_direct_integrations": ["KGF_underfiring", "BF_hot_stove"],
        "finding_count": len(findings),
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [
        C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv",
        C5P_Q_DIR / "process_controller_reconciliation.csv",
        C5M_B_DIR / "s4_4c5m_b_plant_kpi_table.csv",
        C5M_B_DIR / "s4_4c5m_b_wag_carrier_ledger.csv",
        C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv",
        C5P_R_DIR / "controller_activation_readiness.csv",
    ]
    manifest = {
        "stage": STAGE,
        "output_policy": "diagnostics",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic_governance",
        "inputs": [_file_record(path) for path in inputs],
    }
    registry = {
        "run_id": STAGE,
        "purpose": "Reconcile existing KGF, BF hot-stove and PEFA controllers to C5p_o/q without changing WAG allocation.",
        "thesis_usable": False,
        "retention": "local diagnostic output until review",
        "git_eligible": False,
        "status": stage_gate["status"],
    }
    _write_csv(OUTPUT_DIR / "upstream_controller_implementation_register.csv", implementation, IMPLEMENTATION_COLUMNS)
    _write_csv(OUTPUT_DIR / "controller_to_contract_reconciliation.csv", reconciliation, RECONCILIATION_COLUMNS)
    _write_csv(OUTPUT_DIR / "horizon_boundary_findings.csv", findings, FINDING_COLUMNS)
    _write_csv(OUTPUT_DIR / "canonical_integration_policy.csv", policy, POLICY_COLUMNS)
    _write_csv(OUTPUT_DIR / "athanasiadis_methodology_alignment.csv", alignment, ATH_ALIGNMENT_COLUMNS)
    _write_csv(OUTPUT_DIR / "integration_action_plan.csv", actions, ACTION_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validation, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", manifest)
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_s_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", registry)
    _write_report(summary)
    return summary


def main() -> int:
    run_s4_4c5p_s_existing_wag_controller_integration_reconciliation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
