"""Phase 5J corrected WAG-electricity closure and fresh-held-out freeze gate."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

import yaml

from .s4_4c5p_phase5b_c0_export_sensitivity import (
    _git_head,
    _read_csv,
    _select_solver,
    _sha256,
    install_terminal_validation_extension,
)
from .s4_4c5p_phase5e_source_backed_anchor_closure import load_source_contract
from .s4_4c5p_phase5g_final_deterministic_freeze import (
    BUILDER_CONFIGURATION,
    CONFIGURATIONS,
    _actual_totals,
    _anchor_rows,
    _dependencies,
    _flow_summary,
    _hsm_checks,
    _physical_checks,
    _primary_anchors,
    _stage_artifacts,
    load_config as load_phase5g_config,
    load_overlap_contract,
    validate_overlap_against_source,
)
from .s4_4c5p_phase5h_four_residual_effect_gate import (
    held_out_contract,
    procurement_cost_rows,
    steam_and_emissions_rows,
)
from .s4_4c5p_phase5i_electricity_only_heldout_freeze import (
    _payload_sha256,
    _portable,
    _resolve,
    _write_csv,
    _write_json,
    component_checks,
    electricity_maps,
    promoted_rows,
    residual_zero_checks,
    validate_pool_identity,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5j_wag_electricity_closure_v1_20260728"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5j_wag_electricity_closure.yaml"
)
CLASSIFICATION = (
    "validation_selected_user_authorized_aggregate_electricity_baseload_abstraction"
)


class Phase5JGateError(RuntimeError):
    pass


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    phase = payload.get("phase5j")
    if (
        payload.get("run_id") != RUN_ID
        or payload.get("output_policy") != "minimal"
        or not isinstance(phase, Mapping)
        or float(phase.get("selected_electricity_share", -1.0)) != 0.9
    ):
        raise Phase5JGateError("Phase-5J identity, output policy or selected share changed.")
    policy = phase.get("policy", {})
    required_true = (
        "no_reselection_after_heldout",
        "generator_ng_cost_active_without_legacy_bridge",
    )
    required_false = (
        "legacy_phase5d_ng_bridges_active",
        "residual_ng_active",
        "residual_steam_active",
        "residual_direct_co2_active",
        "export_allowed",
        "hsm_policy_changed",
        "wag_yields_changed",
        "production_physics_changed",
        "baseload_price_responsive",
        "exact_anchor_closure_required",
    )
    if not all(bool(policy.get(key)) for key in required_true) or any(
        bool(policy.get(key)) for key in required_false
    ):
        raise Phase5JGateError("Phase-5J bounded correction policy changed.")
    return payload


def load_selected_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    if len(rows) != 8:
        raise Phase5JGateError("Phase-5J requires C0/C1 rows for four residual families.")
    numeric = (
        "selected_share",
        "source_service_pool_pj_y",
        "annual_quantity_pj_y",
        "hourly_quantity_mwh_h",
    )
    for row in rows:
        for field in numeric:
            row[field] = float(row[field])
    electricity = [row for row in rows if row["residual_family"] == "electricity"]
    if {row["configuration"] for row in electricity} != {"C0", "C1"}:
        raise Phase5JGateError("Exactly one C0/C1 electricity row is required.")
    for row in electricity:
        annual = 0.9 * row["source_service_pool_pj_y"]
        hourly = annual / (8760.0 * 3.6e-6)
        if (
            row["selected_share"] != 0.9
            or row["classification"] != CLASSIFICATION
            or row["status"] != "selected_validation_frozen_candidate"
            or not math.isclose(row["annual_quantity_pj_y"], annual, abs_tol=1e-12)
            or not math.isclose(row["hourly_quantity_mwh_h"], hourly, abs_tol=1e-12)
        ):
            raise Phase5JGateError("Phase-5J electricity contract identity failed.")
        if any(
            row[field].lower() != "false"
            for field in (
                "observed_hourly_profile",
                "tata_approved",
                "complete_site_allocation",
                "price_responsive",
            )
        ):
            raise Phase5JGateError("Phase-5J baseload interpretation changed.")
    zeros = [row for row in rows if row["residual_family"] != "electricity"]
    if any(
        any(row[field] != 0.0 for field in numeric)
        or row["executable"].lower() != "false"
        for row in zeros
    ):
        raise Phase5JGateError("NG, steam and direct-CO2 residuals must remain zero.")
    return rows


def _generator_cost_checks(
    artifacts: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for period_id, artifact in artifacts.items():
        rows = [row for row in artifact["costs"] if row.get("flow_id") == "C0_NG_GENERATOR"]
        passed = bool(rows) and all(float(row["price_eur_per_unit"]) > 0.0 for row in rows)
        checks.append(
            {
                "stage": "fresh_heldout",
                "period_id": period_id,
                "configuration": "C0",
                "check_id": "generator_ng_cost_active_without_legacy_bridge",
                "actual": len(rows),
                "limit": ">0 priced rows",
                "status": "pass" if passed else "fail",
            }
        )
    return checks


def _external_validity_checks(
    totals: Mapping[tuple[str, str], float],
    anchors: Mapping[tuple[str, str], float],
    flow_rows: list[dict[str, Any]],
    phase: Mapping[str, Any],
) -> list[dict[str, Any]]:
    flow = {
        (str(row["configuration"]), str(row["metric"])): float(row["value"])
        for row in flow_rows
    }
    checks: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        error = abs(
            totals[(configuration, "electricity")]
            / anchors[(configuration, "electricity")]
            - 1.0
        )
        error_limit = float(phase["heldout_electricity_error_limit"][configuration])
        flare = flow[(configuration, "WAG_flared")]
        flare_limit = float(phase["heldout_flare_limit_pj_y"][configuration])
        checks.extend(
            [
                {
                    "stage": "fresh_heldout",
                    "configuration": configuration,
                    "check_id": "electricity_anchor_error_bounded",
                    "actual": error,
                    "limit": error_limit,
                    "status": "pass" if error <= error_limit else "fail",
                },
                {
                    "stage": "fresh_heldout",
                    "configuration": configuration,
                    "check_id": "wag_flare_absolute_boundary_bounded",
                    "actual": flare,
                    "limit": flare_limit,
                    "status": "pass" if flare <= flare_limit else "fail",
                    "notes": "Absolute robustness gate; the approximately 0.1-PJ/y source value remains the reported comparison.",
                },
            ]
        )
    return checks


def _persist(
    *,
    config_file: Path,
    config: Mapping[str, Any],
    phase: Mapping[str, Any],
    contract_path: Path,
    heldout_path: Path,
    contract_rows: list[dict[str, Any]],
    case_status: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    component_rows: list[dict[str, Any]],
    component_gate: list[dict[str, Any]],
    anchor_rows: list[dict[str, Any]],
    flow_rows: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    checkpoint: Mapping[str, Any],
    started: float,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase5JGateError("Phase-5J governed output root already exists.")
    output.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8"
    )
    _write_csv(output / "contract_verification.csv", contract_rows)
    _write_csv(
        output / "promoted_contract_preview.csv",
        promoted_rows(contract_rows) if checkpoint["status"] == "pass" else contract_rows,
    )
    _write_csv(output / "case_status.csv", case_status)
    _write_csv(output / "physical_and_external_validity_checks.csv", checks)
    _write_csv(output / "component_overlap_checks.csv", component_gate)
    _write_csv(output / "component_overlap_waterfall.csv", component_rows)
    _write_csv(output / "heldout_anchor_generalisation.csv", anchor_rows)
    _write_csv(output / "heldout_flow_summary.csv", flow_rows)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    inputs = [
        config_file,
        contract_path,
        heldout_path,
        _resolve(phase["component_reference"]),
        _resolve(phase["phase5g_overlap_contract"]),
        _resolve(phase["source_contract"]),
        _resolve(phase["phase5h_source_pool"]),
        Path(__file__).resolve(),
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT
        / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    ]
    manifest = [
        {"path": _portable(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}
        for path in inputs
    ]
    _write_json(output / "input_manifest.json", {"files": manifest})
    price_fingerprints = sorted(
        {
            row["price_input_fingerprint_sha256"]
            for artifact in artifacts.values()
            for row in artifact["costs"]
            if row.get("price_input_fingerprint_sha256")
        }
    )
    fingerprints = {
        "git_head": _git_head(),
        "model_fingerprint_sha256": _payload_sha256(
            {row["path"]: row["sha256"] for row in manifest if row["path"].endswith(".py")}
        ),
        "input_contract_fingerprint_sha256": _payload_sha256(
            {row["path"]: row["sha256"] for row in manifest if not row["path"].endswith(".py")}
        ),
        "forecast_input_fingerprints_sha256": _payload_sha256(price_fingerprints),
        "electricity_baseload_contract_sha256": _sha256(contract_path),
        "heldout_period_contract_sha256": _sha256(heldout_path),
    }
    _write_json(output / "fingerprint_manifest.json", fingerprints)
    _write_json(
        output / "code_version.json",
        {"git_head": _git_head(), "model_fingerprint_sha256": fingerprints["model_fingerprint_sha256"]},
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": config["output_policy"],
            "retention_status": config["retention_status"],
            "decision": checkpoint["decision"],
        },
    )
    summary = {
        **dict(checkpoint),
        "runtime_seconds": time.perf_counter() - started,
        "fingerprints": fingerprints,
    }
    _write_json(output / "run_summary.json", summary)
    (output / "README.md").write_text(
        "# Phase 5J corrected WAG-electricity closure\n\n"
        f"Decision: `{checkpoint['decision']}`. Generator NG is priced independently of the retired legacy bridge; central WAG yields remain unchanged.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\nThe 90% electricity term is a validation-selected aggregate baseload, not an observed profile. The approximately 54-PJ/y WAG value is recovery context rather than a gross-production cap. Remaining flare is carrier- and hour-specific and is not hidden by a fitted WAG-yield reduction.\n",
        encoding="utf-8",
    )
    return summary


def run_phase5j(
    config_path: str | Path = CONFIG_PATH, *, resume_from_complete_cache: bool = False
) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase5j"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase5JGateError("Phase-5J requires the preserved parent HEAD.")
    contract_path = _resolve(phase["selected_contract"])
    contract_rows = load_selected_contract(contract_path)
    pool_checks = validate_pool_identity(
        contract_rows, _resolve(phase["phase5h_source_pool"])
    )
    heldout_path = _resolve(phase["held_out_contract"])
    heldout_rows, _ = held_out_contract(heldout_path)
    if len(heldout_rows) != int(phase["expected_period_count"]):
        raise Phase5JGateError("Fresh held-out period count changed.")
    scratch = _resolve(phase["scratch_root"])
    expected_dirs = {
        f"phase5g__phase5j_heldout__{row['period_id'].replace('-', '_')}"
        for row in heldout_rows
    }
    if scratch.exists():
        if not resume_from_complete_cache:
            raise Phase5JGateError("Phase-5J scratch already exists; fresh evidence cannot reopen.")
        actual = {path.name for path in scratch.iterdir() if path.is_dir()}
        if not actual.issubset(expected_dirs) or any(
            not (scratch / name / "run_summary.json").exists() for name in actual
        ):
            raise Phase5JGateError(
                "A structural-input recovery may reuse only complete expected cases."
            )
    else:
        scratch.mkdir(parents=True)
    phase5g = dict(load_phase5g_config(_resolve(phase["phase5g_config"]))["phase5g"])
    phase5g["scratch_root"] = phase["scratch_root"]
    parent, phase4, terminal_target = _dependencies(phase5g)
    if _select_solver()[1] is None:
        raise Phase5JGateError("Gurobi is unavailable before held-out execution.")
    install_terminal_validation_extension()
    electricity = electricity_maps(contract_rows)
    zero = {configuration: 0.0 for configuration in CONFIGURATIONS}
    artifacts, case_status = _stage_artifacts(
        "phase5j_heldout",
        heldout_rows,
        phase5g,
        parent,
        phase4,
        terminal_target,
        electricity,
        zero,
    )
    tolerance = float(phase["physical_balance_tolerance_mwh"])
    physical = _physical_checks("fresh_heldout", artifacts, electricity, zero, tolerance)
    physical += _hsm_checks("fresh_heldout", artifacts, phase5g, tolerance)
    physical += residual_zero_checks(artifacts, tolerance)
    physical += pool_checks
    physical += _generator_cost_checks(artifacts)
    source_rows = load_source_contract(_resolve(phase["source_contract"]))
    overlap_rows = load_overlap_contract(_resolve(phase["phase5g_overlap_contract"]))
    validate_overlap_against_source(overlap_rows, source_rows)
    component_rows, component_gate = component_checks(
        artifacts,
        heldout_rows,
        overlap_rows,
        _resolve(phase["component_reference"]),
        float(phase["component_exceedance_tolerance_pj"]),
    )
    anchors = _primary_anchors(source_rows)
    totals = _actual_totals(artifacts, heldout_rows)
    anchor_rows = [
        row
        for row in _anchor_rows("fresh_heldout", totals, anchors)
        if row["carrier"] == "electricity"
    ]
    flow_rows = _flow_summary("fresh_heldout", artifacts, heldout_rows, 56.1)
    flow_rows += procurement_cost_rows("fresh_heldout", artifacts, heldout_rows)
    flow_rows += steam_and_emissions_rows("fresh_heldout", artifacts, heldout_rows)
    physical += _external_validity_checks(totals, anchors, flow_rows, phase)
    model_count = sum(int(row["model_count"]) for row in case_status)
    passed = model_count == int(phase["expected_models"]) and all(
        row["status"] == "pass" for row in case_status + physical + component_gate
    )
    checkpoint = {
        "run_id": RUN_ID,
        "decision": phase["decision_on_pass"] if passed else phase["decision_on_fail"],
        "status": "pass" if passed else "fail",
        "heldout_models": model_count,
        "selected_electricity_share": 0.9,
        "generator_ng_cost_active_without_legacy_bridge": True,
        "wag_yields_changed": False,
        "contract_promoted": passed,
        "reselection_after_heldout": False,
        "fresh_heldout_opened_once": True,
        "structural_input_recovery_from_complete_cache": resume_from_complete_cache,
        "phase6_authorization": "rerun_phase6a_before_phase6b" if passed else "blocked",
        "scope": "corrected_represented_boundary_not_full_site_digital_twin",
        "failure_count": 0 if passed else 1,
    }
    return _persist(
        config_file=config_file,
        config=config,
        phase=phase,
        contract_path=contract_path,
        heldout_path=heldout_path,
        contract_rows=contract_rows,
        case_status=case_status,
        checks=physical,
        component_rows=component_rows,
        component_gate=component_gate,
        anchor_rows=anchor_rows,
        flow_rows=flow_rows,
        artifacts=artifacts,
        checkpoint=checkpoint,
        started=started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--resume-from-complete-cache", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_phase5j(
                args.config,
                resume_from_complete_cache=args.resume_from_complete_cache,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
