"""Fail-closed audit of downstream product-origin coverage in the unified C5 model."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_downstream_origin_tag_audit_v1"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
BUILDER_PATH = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "s4_4c_unified_physical_modelbuilder.py"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_origin_tag_rows(builder_text: str) -> list[dict[str, str]]:
    """Describe only interfaces that the current builder visibly preserves."""
    has_import_interface = "imported_slab" in builder_text or "slab_import" in builder_text
    return [
        {
            "configuration": "C0_current_BF_BOF_reference",
            "origin_tag": "BOF_endogenous_liquid_steel",
            "downstream_destination": "HSM_final_product_proxy",
            "current_builder_status": "partially_represented",
            "evidence": "C0 final_product_output is linked to hot_strip_mill; no route-origin tag survives in the product expression.",
            "physical_use_allowed": "no",
            "required_next_interface": "tag BOF slab through HSM and DSP separately",
        },
        {
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "origin_tag": "BOF_endogenous_liquid_steel",
            "downstream_destination": "retained_HSM_final_product_proxy",
            "current_builder_status": "partially_represented",
            "evidence": "retained_bf_bof_final_product_output is explicit, but it is not tagged at HSM/DSP product level.",
            "physical_use_allowed": "no",
            "required_next_interface": "tag retained BOF slab through HSM and DSP separately",
        },
        {
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "origin_tag": "EAF_endogenous_liquid_steel",
            "downstream_destination": "direct_final_product_proxy",
            "current_builder_status": "missing_downstream_interface",
            "evidence": "eaf_final_product_output enters final_product_output directly; no explicit EAF-to-HSM or EAF-to-DSP material route exists.",
            "physical_use_allowed": "no",
            "required_next_interface": "introduce EAF liquid-steel routing to HSM/DSP with yields and origin tags",
        },
        {
            "configuration": "C0_current_BF_BOF_reference",
            "origin_tag": "imported_slab",
            "downstream_destination": "unassigned",
            "current_builder_status": "absent" if not has_import_interface else "requires_manual_review",
            "evidence": "No approved imported-slab interface may be inferred from cold-slab inventory or final-product accounting.",
            "physical_use_allowed": "no",
            "required_next_interface": "source-map eligible downstream destination before any activation",
        },
        {
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "origin_tag": "imported_slab",
            "downstream_destination": "HSM_WBW_source_mapped_but_inactive",
            "current_builder_status": "absent" if not has_import_interface else "requires_manual_review",
            "evidence": "The DSP source card records C1 imported slabs to HSM; the 0.6 Mt/y MER context remains an external annual boundary, not a current model supply or store.",
            "physical_use_allowed": "no",
            "required_next_interface": "add a separately capped external-to-HSM route and an explicit rolling-profile policy",
        },
    ]


def build_anchor_rows() -> list[dict[str, str]]:
    return [
        {
            "configuration": "C0_current_BF_BOF_reference",
            "metric": "endogenous_liquid_steel",
            "annual_value_mt_y": "7.2",
            "role": "primary_validation",
            "source": "MER Heracless Deel B section 4.3",
            "comparison_status": "not_currently_route_complete",
        },
        {
            "configuration": "C0_current_BF_BOF_reference",
            "metric": "imported_slab",
            "annual_value_mt_y": "0.016",
            "role": "reporting_context",
            "source": "MER Heracless Deel B section 4.3",
            "comparison_status": "not_active_model_supply",
        },
        {
            "configuration": "C0_current_BF_BOF_reference",
            "metric": "site_final_product",
            "annual_value_mt_y": "6.9",
            "role": "primary_validation",
            "source": "MER Heracless Deel B section 4.3",
            "comparison_status": "not_currently_origin_tagged",
        },
        {
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "metric": "endogenous_liquid_steel",
            "annual_value_mt_y": "6.8",
            "role": "primary_validation",
            "source": "MER Heracless Deel B section 5.4/5.5",
            "comparison_status": "partially_represented",
        },
        {
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "metric": "imported_slab",
            "annual_value_mt_y": "0.6",
            "role": "primary_boundary_context",
            "source": "MER Heracless Deel B section 5.5",
            "comparison_status": "not_active_model_supply",
        },
        {
            "configuration": "C1_phase1_BF_BOF_NG_DRP_EAF",
            "metric": "site_final_product",
            "annual_value_mt_y": "7.0",
            "role": "primary_validation",
            "source": "MER Heracless Deel B section 5.5",
            "comparison_status": "not_currently_origin_tagged",
        },
    ]


def build_gap_rows(origin_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "gap_id": "DOWNSTREAM_ORIGIN_TAGS_MISSING",
            "severity": "blocking",
            "issue": "Final-product output does not retain BOF/EAF/imported-slab origin through HSM/DSP.",
            "consequence": "Site-final-product anchors cannot be compared to endogenous liquid-steel anchors without boundary leakage.",
            "allowed_fix": "Add origin-tagged downstream material balances; preserve existing yields and capacities initially.",
        },
        {
            "gap_id": "EAF_DIRECT_TO_FINAL_PROXY",
            "severity": "blocking",
            "issue": "C1 EAF output currently enters final-product proxy directly.",
            "consequence": "EAF-to-DSP and EAF-to-HSM route shares cannot be validated.",
            "allowed_fix": "Route EAF liquid steel explicitly to downstream sinks before testing the 90% EAF-to-DSP context.",
        },
        {
            "gap_id": "IMPORTED_SLAB_INTERFACE_NOT_IMPLEMENTED",
            "severity": "high",
            "issue": "The source card maps C1 imported slabs to HSM/WBW, but no separately capped external-material route or rolling-profile policy exists in the builder.",
            "consequence": "Activating the 0.6 Mt/y supply now would create an ungoverned hourly supply and risk treating cold-slab inventory as external material.",
            "allowed_fix": "Add a source-backed annual-cap-to-rolling-profile policy with a separate external-to-HSM interface; do not use cold-slab inventory as supply.",
        },
        {
            "gap_id": "COLD_SLAB_STORE_NOT_IMPORT_SUPPLY",
            "severity": "blocking",
            "issue": "Existing cold_slab_inventory is a balance/store scaffold, not evidence of imported material.",
            "consequence": "Treating initial inventory as import would create hidden supply.",
            "allowed_fix": "Keep inventory and external supply separate with independent terminal and annual-cap rules.",
        },
    ]


def run_downstream_origin_tag_audit(*, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    run_directory = Path(output_root).resolve() / RUN_ID
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    builder_text = BUILDER_PATH.read_text(encoding="utf-8")
    origin_rows = build_origin_tag_rows(builder_text)
    anchor_rows = build_anchor_rows()
    gap_rows = build_gap_rows(origin_rows)
    summary = {
        "run_id": RUN_ID,
        "status": "pass_with_blocking_model_interface_gaps",
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "origin_tags_required": ["BOF_endogenous_liquid_steel", "EAF_endogenous_liquid_steel", "imported_slab"],
        "imported_slab_active_physical_supply": False,
        "downstream_origin_tagged": False,
        "c1_eaf_direct_to_final_proxy": True,
        "next_gate": "origin-tagged HSM/DSP material interface design before imported-slab or site-final-product feasibility run",
    }
    _write_csv(run_directory / "origin_tag_matrix.csv", origin_rows)
    _write_csv(run_directory / "annual_boundary_anchor_matrix.csv", anchor_rows)
    _write_csv(run_directory / "model_interface_gap_register.csv", gap_rows)
    (run_directory / "resolved_config.yaml").write_text(
        "run_id: steel_downstream_origin_tag_audit_v1\noutput_policy: minimal\nrun_class: diagnostic\nlineage_role: diagnostic\n",
        encoding="utf-8",
    )
    _write_json(run_directory / "input_manifest.json", {"builder_path": str(BUILDER_PATH.relative_to(REPO_ROOT)), "builder_sha256": hashlib.sha256(builder_text.encode()).hexdigest()})
    _write_json(run_directory / "code_version.json", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": RUN_ID, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Limitations\n\n- This audit does not solve the model.\n- No imported slab supply, capacity, yield, source-card value or energy/emissions factor is changed.\n- The MER annual import is a boundary anchor, not an authorised route split.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "summary": summary, "origin_rows": origin_rows, "gap_rows": gap_rows}
