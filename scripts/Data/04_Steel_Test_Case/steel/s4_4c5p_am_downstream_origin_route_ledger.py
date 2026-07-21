"""Compile a source-backed annual downstream-origin ledger without changing dispatch."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_downstream_origin_route_ledger_v1"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
DSP_CARD = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "source_cards" / "DSP_Parameters.md"
HSM_CARD = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "source_cards" / "HSM_Parameters.md"
POLICY = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_PRODUCT_DENOMINATOR_AND_SLAB_IMPORT_BOUNDARY_POLICY.md"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _card_value(text: str, parameter_id: str) -> float:
    match = re.search(rf"\|\s*`{re.escape(parameter_id)}`\s*\|\s*(?:approx\.\s*)?([0-9.]+)", text)
    if match is None:
        raise ValueError(f"Could not read {parameter_id} from source card.")
    return float(match.group(1))


def _policy_context(text: str) -> dict[str, float]:
    pattern = re.compile(
        r"\|\s*`(?P<measure>[^`]+)`\s*\|.*?\|\s*(?P<c0>[0-9.]+)\s*Mt/y\s*\|\s*(?P<c1>[0-9.]+)\s*Mt/y\s*\|"
    )
    rows = {match.group("measure"): match.groupdict() for match in pattern.finditer(text)}
    required = {"endogenous_liquid_steel_t", "imported_slab_t", "site_final_product_t"}
    if not required.issubset(rows):
        raise ValueError("The product-boundary policy does not expose all required annual context values.")
    return {
        "c0_liquid_steel": float(rows["endogenous_liquid_steel_t"]["c0"]),
        "c1_liquid_steel": float(rows["endogenous_liquid_steel_t"]["c1"]),
        "c0_imported_slab": float(rows["imported_slab_t"]["c0"]),
        "c1_imported_slab": float(rows["imported_slab_t"]["c1"]),
        "c0_final_product": float(rows["site_final_product_t"]["c0"]),
        "c1_final_product": float(rows["site_final_product_t"]["c1"]),
    }


def load_source_values() -> dict[str, float]:
    dsp_text = DSP_CARD.read_text(encoding="utf-8")
    hsm_text = HSM_CARD.read_text(encoding="utf-8")
    values = _policy_context(POLICY.read_text(encoding="utf-8"))
    values.update(
        {
            "c0_dsp_output": _card_value(dsp_text, "DSP_C0_OUTPUT_ANNUAL_MT_Y"),
            "c1_dsp_output": _card_value(dsp_text, "DSP_C1_OUTPUT_ANNUAL_MT_Y"),
            "c0_dsp_share": _card_value(dsp_text, "DSP_C0_SHARE_OF_OSF_TO_DSP"),
            "c1_dsp_eaf_share": _card_value(dsp_text, "DSP_C1_EAF_ROUTE_SHARE_OF_DSP"),
            "dsp_input_per_coil": _card_value(dsp_text, "DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL_BASE"),
            "hsm_input_per_hrc": _card_value(
                hsm_text, "HSM_SLAB_INPUT_T_PER_T_HRC_GATE2_CENTRAL"
            ),
        }
    )
    values["c0_hsm_output"] = values["c0_final_product"] - values["c0_dsp_output"]
    values["c1_hsm_output"] = values["c1_final_product"] - values["c1_dsp_output"]
    return values


def build_annual_ledger(values: dict[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in ("C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_NG_DRP_EAF"):
        prefix = "c0" if configuration.startswith("C0") else "c1"
        dsp_input = values[f"{prefix}_dsp_output"] * values["dsp_input_per_coil"]
        hsm_required = values[f"{prefix}_hsm_output"] * values["hsm_input_per_hrc"]
        endogenous_after_dsp = values[f"{prefix}_liquid_steel"] - dsp_input
        imported_hsm = values[f"{prefix}_imported_slab"] if prefix == "c1" else 0.0
        hsm_gap = endogenous_after_dsp + imported_hsm - hsm_required
        rows.extend(
            [
                {
                    "configuration": configuration,
                    "origin": "BOF_endogenous_liquid_steel" if prefix == "c0" else "EAF_and_BOF_combined_endogenous_liquid_steel",
                    "sink": "DSP",
                    "annual_mt_y": round(dsp_input, 6),
                    "basis": "DSP output anchor multiplied by development candidate liquid-steel input",
                    "status": "diagnostic_only",
                    "caveat": "This is a source-card conversion check, not a dispatch constraint.",
                },
                {
                    "configuration": configuration,
                    "origin": "EAF_endogenous_liquid_steel" if prefix == "c1" else "not_applicable",
                    "sink": "DSP",
                    "annual_mt_y": round(dsp_input * values["c1_dsp_eaf_share"], 6) if prefix == "c1" else 0.0,
                    "basis": "C1 MER route-share anchor applied only for annual origin reconciliation",
                    "status": "diagnostic_only",
                    "caveat": "The approximately 90% EAF share remains a validation anchor, not a dispatch constraint.",
                },
                {
                    "configuration": configuration,
                    "origin": "imported_slab",
                    "sink": "HSM_WBW",
                    "annual_mt_y": round(imported_hsm, 6),
                    "basis": "C1 MER/source-card annual HSM-boundary context" if prefix == "c1" else "C0 import is not source-mapped in this ledger",
                    "status": "reporting_only_inactive_supply",
                    "caveat": "No external supply is activated in the physical optimiser.",
                },
                {
                    "configuration": configuration,
                    "origin": "combined_available_material_after_DSP",
                    "sink": "HSM_WBW",
                    "annual_mt_y": round(endogenous_after_dsp + imported_hsm, 6),
                    "basis": "endogenous liquid-steel anchor less DSP input plus source-mapped C1 imported slab",
                    "status": "diagnostic_only",
                    "caveat": "C1 BOF/EAF split to HSM remains unresolved; this is deliberately combined.",
                },
                {
                    "configuration": configuration,
                    "origin": "HSM_WBW_requirement",
                    "sink": "HSM_WBW",
                    "annual_mt_y": round(hsm_required, 6),
                    "basis": "HSM product anchor multiplied by development candidate slab input",
                    "status": "diagnostic_only",
                    "caveat": "The HSM input coefficient is development-only and must not be tuned to close this balance.",
                },
                {
                    "configuration": configuration,
                    "origin": "material_balance_residual",
                    "sink": "HSM_WBW",
                    "annual_mt_y": round(hsm_gap, 6),
                    "basis": "available material after DSP minus HSM slab requirement",
                    "status": "visible_residual",
                    "caveat": "Negative means the annual public/product anchors and candidate yields do not close on this simplified boundary; it is not a plug.",
                },
            ]
        )
    return rows


def build_reconciliation_rows(values: dict[str, float]) -> list[dict[str, Any]]:
    c0_implied = values["c0_dsp_output"] * values["dsp_input_per_coil"] / values["c0_liquid_steel"]
    return [
        {
            "check_id": "C0_DSP_ROUTE_SHARE",
            "configuration": "C0_current_BF_BOF_reference",
            "model_or_derived_value": round(c0_implied, 6),
            "anchor_value": values["c0_dsp_share"],
            "comparison": "derived DSP liquid-steel input share versus MER 20% routing anchor",
            "status": "warning_boundary_or_yield_mismatch",
            "caveat": "Do not tune the DSP yield or route share solely to remove this gap.",
        },
        {
            "check_id": "C1_DSP_EAF_ORIGIN",
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "model_or_derived_value": values["c1_dsp_eaf_share"],
            "anchor_value": values["c1_dsp_eaf_share"],
            "comparison": "annual ledger preserves the MER approximate EAF-origin DSP share",
            "status": "reported_not_constrained",
            "caveat": "The active builder still lacks origin-tagged EAF/BOF routing.",
        },
        {
            "check_id": "C1_IMPORTED_SLAB_DESTINATION",
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "model_or_derived_value": values["c1_imported_slab"],
            "anchor_value": values["c1_imported_slab"],
            "comparison": "C1 annual imported slab is source-mapped to HSM/WBW",
            "status": "source_mapped_but_inactive",
            "caveat": "No hourly profile or physical external-supply interface has been approved.",
        },
    ]


def build_gate_rows() -> list[dict[str, str]]:
    return [
        {
            "gate": "BOF_EAF_to_DSP_origin_tags",
            "status": "design_ready_not_implemented",
            "reason": "The DSP card provides eligible inputs and annual route anchors, but the unified builder retains pooled/direct final-product expressions.",
            "next_action": "Add origin-tag variables and route balances without constraining the 90% anchor.",
        },
        {
            "gate": "imported_slab_to_HSM",
            "status": "source_mapped_not_implemented",
            "reason": "The source card maps C1 imported slab to HSM/WBW, but no separate annual-cap-to-rolling-profile interface exists.",
            "next_action": "Propose a bounded external-to-HSM input that is separate from cold-slab inventory.",
        },
        {
            "gate": "annual_product_anchor_comparison",
            "status": "not_comparable_as_physical_run",
            "reason": "The annual ledger shows yield/boundary residuals and the builder has no origin-tagged downstream balances.",
            "next_action": "Run an opt-in tagged-interface feasibility case only after the interface design passes review.",
        },
    ]


def build_c1_uniform_import_routing(
    values: dict[str, float],
    *,
    horizon_hours: int,
    imported_slab_annual_cap_mt_y: float | None = None,
    minimize_imported_slab: bool = False,
) -> dict[str, float | bool]:
    """Return an explicit development scenario, not a measured hourly import profile.

    The annual supply bound is converted both to a uniform hourly delivery
    envelope and to an exact horizon-total cap.  The latter keeps the annual
    boundary visible when this interface is reused by a rolling optimiser.
    """
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive.")
    annual_cap_mt_y = (
        values["c1_imported_slab"]
        if imported_slab_annual_cap_mt_y is None
        else float(imported_slab_annual_cap_mt_y)
    )
    if annual_cap_mt_y < 0.0:
        raise ValueError("imported_slab_annual_cap_mt_y must be non-negative.")
    annual_cap_t_y = annual_cap_mt_y * 1_000_000.0
    return {
        "hsm_final_t_per_t_slab": 1.0 / values["hsm_input_per_hrc"],
        "dsp_liquid_steel_input_t_per_t_coil": values["dsp_input_per_coil"],
        "dsp_final_product_horizon_cap_t": values["c1_dsp_output"] * 1_000_000.0 * horizon_hours / 8760.0,
        "imported_slab_max_t_h": annual_cap_t_y / 8760.0,
        "imported_slab_horizon_cap_t": annual_cap_t_y * horizon_hours / 8760.0,
        "minimize_imported_slab": bool(minimize_imported_slab),
    }


def run_downstream_origin_route_ledger(*, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    run_directory = Path(output_root).resolve() / RUN_ID
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    values = load_source_values()
    ledger_rows = build_annual_ledger(values)
    reconciliation_rows = build_reconciliation_rows(values)
    gate_rows = build_gate_rows()
    residuals = [row for row in ledger_rows if row["origin"] == "material_balance_residual"]
    summary = {
        "run_id": RUN_ID,
        "status": "pass_with_visible_boundary_residuals",
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "imported_slab_active_physical_supply": False,
        "c1_imported_slab_destination": "HSM_WBW_source_mapped",
        "c1_dsp_eaf_share_constraint_active": False,
        "hsm_balance_residual_mt_y": {row["configuration"]: row["annual_mt_y"] for row in residuals},
        "next_gate": "review an opt-in origin-tagged material-interface design; do not tune development yields to remove residuals",
    }
    _write_csv(run_directory / "annual_origin_routing_ledger.csv", ledger_rows)
    _write_csv(run_directory / "route_anchor_reconciliation.csv", reconciliation_rows)
    _write_csv(run_directory / "route_implementation_gate.csv", gate_rows)
    (run_directory / "resolved_config.yaml").write_text(
        "run_id: steel_downstream_origin_route_ledger_v1\noutput_policy: minimal\nrun_class: diagnostic\nlineage_role: diagnostic\n",
        encoding="utf-8",
    )
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (DSP_CARD, HSM_CARD, POLICY)}
    _write_json(run_directory / "input_manifest.json", manifest)
    _write_json(run_directory / "code_version.json", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": RUN_ID, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Limitations\n\n- This is an annual source-card ledger, not a solve or dispatch rule.\n- DSP and HSM yield values are development candidates, not values tuned to anchors.\n- Imported slab remains inactive in the physical optimiser.\n- C1 EAF-to-DSP share is reported but not constrained.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "summary": summary, "ledger_rows": ledger_rows, "gate_rows": gate_rows}
