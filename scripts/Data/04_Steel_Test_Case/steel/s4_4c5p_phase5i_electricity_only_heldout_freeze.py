"""Phase 5I electricity-only fresh-held-out represented-boundary freeze gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import HOURS_PER_YEAR, PJ_PER_MWH
from .s4_4c5p_phase5b_c0_export_sensitivity import (
    _git_head, _read_csv, _read_json, _select_solver, _sha256,
    install_terminal_validation_extension,
)
from .s4_4c5p_phase5e_source_backed_anchor_closure import load_source_contract
from .s4_4c5p_phase5g_final_deterministic_freeze import (
    BUILDER_CONFIGURATION, CONFIGURATIONS, _actual_totals, _anchor_rows,
    _dependencies, _flow_summary, _hsm_checks, _physical_checks,
    _primary_anchors, _stage_artifacts, load_config as load_phase5g_config,
    load_overlap_contract, source_service_pools, validate_overlap_against_source,
)
from .s4_4c5p_phase5h_four_residual_effect_gate import (
    held_out_contract, procurement_cost_rows, steam_and_emissions_rows,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5i_electricity_only_heldout_freeze_v1_20260728"
CONFIG_PATH = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5i_electricity_only_heldout_freeze.yaml"
CLASSIFICATION = "validation_selected_user_authorized_aggregate_electricity_baseload_abstraction"


class Phase5IFreezeError(RuntimeError):
    pass


def _resolve(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (REPO_ROOT / value).resolve()


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase5IFreezeError(f"Persistent path must be repository-relative: {path}") from exc


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields: list[str] = []
    for row in materialized:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal":
        raise Phase5IFreezeError("Phase-5I identity or output policy changed.")
    phase = payload.get("phase5i")
    if not isinstance(phase, Mapping) or float(phase.get("selected_electricity_share", -1)) != 0.1:
        raise Phase5IFreezeError("Phase-5I requires the frozen 10% electricity share.")
    policy = phase.get("policy", {})
    required_false = (
        "phase5g_failed_baseload_active", "legacy_phase5d_ng_bridges_active",
        "residual_ng_active", "residual_steam_active", "residual_direct_co2_active",
        "export_allowed", "hsm_policy_changed", "wag_yields_changed",
        "production_physics_changed", "baseload_price_responsive",
        "full_site_digital_twin_claim", "exact_annual_anchor_replication_claim",
        "ets_ready_claim",
    )
    if any(bool(policy.get(key)) for key in required_false) or not bool(policy.get("no_reselection_after_heldout")):
        raise Phase5IFreezeError("Phase-5I scope or no-reselection policy changed.")
    return payload


def load_selected_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    if len(rows) != 8:
        raise Phase5IFreezeError("Phase-5I contract must contain C0/C1 rows for four residual families.")
    for row in rows:
        for field in ("selected_share", "source_service_pool_pj_y", "annual_quantity_pj_y", "hourly_quantity_mwh_h"):
            row[field] = float(row[field])
    electricity = [row for row in rows if row["residual_family"] == "electricity"]
    if len(electricity) != 2 or {row["configuration"] for row in electricity} != {"C0", "C1"}:
        raise Phase5IFreezeError("Exactly one C0/C1 electricity row is required.")
    for row in electricity:
        if row["selected_share"] != 0.1 or row["classification"] != CLASSIFICATION:
            raise Phase5IFreezeError("Electricity-only identity or classification changed.")
        if any(row[field].lower() != "false" for field in (
            "observed_hourly_profile", "tata_approved", "complete_site_allocation", "price_responsive"
        )):
            raise Phase5IFreezeError("Electricity baseload interpretation changed.")
        expected_annual = 0.1 * row["source_service_pool_pj_y"]
        expected_hourly = expected_annual / (HOURS_PER_YEAR * PJ_PER_MWH)
        if not math.isclose(row["annual_quantity_pj_y"], expected_annual, abs_tol=1e-12):
            raise Phase5IFreezeError("Electricity annual identity failed.")
        if not math.isclose(row["hourly_quantity_mwh_h"], expected_hourly, abs_tol=1e-12):
            raise Phase5IFreezeError("Electricity hourly identity failed.")
        if row["status"] not in {"selected_validation_frozen_candidate", "heldout_validated_promoted"}:
            raise Phase5IFreezeError("Electricity contract promotion status is invalid.")
    zeros = [row for row in rows if row["residual_family"] != "electricity"]
    if any(any(row[field] != 0.0 for field in (
        "selected_share", "annual_quantity_pj_y", "hourly_quantity_mwh_h"
    )) or row["executable"].lower() != "false" for row in zeros):
        raise Phase5IFreezeError("NG, steam and direct-CO2 residuals must remain zero and non-executable.")
    return rows


def electricity_maps(rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    return {
        BUILDER_CONFIGURATION[str(row["configuration"])]: float(row["hourly_quantity_mwh_h"])
        for row in rows if row["residual_family"] == "electricity"
    }


def validate_pool_identity(
    rows: Iterable[Mapping[str, Any]], pool_path: Path, tolerance: float = 1e-12
) -> list[dict[str, Any]]:
    pools = _read_csv(pool_path)
    checks: list[dict[str, Any]] = []
    for row in rows:
        if row["residual_family"] != "electricity":
            continue
        configuration = str(row["configuration"])
        observed = sum(
            float(item["eligible_service_pool_pj_y"])
            for item in pools
            if item["carrier"] == "electricity" and item["configuration"] == configuration
        )
        residual = abs(observed - float(row["source_service_pool_pj_y"]))
        checks.append({
            "check_id": f"{configuration}_phase5h_pool_identity", "actual": residual,
            "limit": tolerance, "status": "pass" if residual <= tolerance else "fail",
        })
    return checks


def residual_zero_checks(artifacts: Mapping[str, Mapping[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    fields = (
        "site_baseload_ng_mwh", "residual_steam_15bar_demand_t",
        "residual_unmodelled_direct_co2_t", "gross_grid_export_mwh",
        "full_site_energy_bridge_named_ng_mwh",
    )
    for period_id, artifact in artifacts.items():
        for configuration in ("C0", "C1"):
            builder = BUILDER_CONFIGURATION[configuration]
            rows = [row for row in artifact["hourly"] if row["configuration_id"] == builder]
            for field in fields:
                maximum = max(abs(float(row.get(field) or 0.0)) for row in rows)
                checks.append({
                    "stage": "heldout", "period_id": period_id, "configuration": configuration,
                    "check_id": f"{field}_zero", "actual": maximum, "limit": tolerance,
                    "status": "pass" if maximum <= tolerance else "fail",
                })
    return checks


def component_checks(
    artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]],
    overlap_rows: list[dict[str, Any]], reference_path: Path, tolerance: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actual = source_service_pools(artifacts, periods, [row for row in overlap_rows if row["carrier"] == "natural_gas"])
    reference = {row["mapping_id"]: row for row in _read_csv(reference_path)}
    checks: list[dict[str, Any]] = []
    for row in actual:
        ref = reference[row["mapping_id"]]
        mapped = float(row["mapped_explicit_model_pj_y"])
        source = float(ref["source_value_pj_y"])
        validation = float(ref["phase5h_10pct_validation_mapped_pj_y"])
        limit = source if row["mapping_id"] == "P5G-C0-NG-GEN" else max(source, validation)
        passed = mapped <= limit + tolerance
        checks.append({
            "check_id": f"{row['mapping_id']}_heldout_component_compatibility",
            "configuration": row["configuration"], "actual_pj_y": mapped,
            "limit_pj_y": limit, "tolerance_pj": tolerance,
            "status": "pass" if passed else "fail",
            "notes": "C0 generator uses the absolute MER ceiling; other rows may retain but not enlarge a documented validation/source mismatch.",
        })
    return actual, checks


def promoted_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for source in rows:
        row = dict(source)
        if row["residual_family"] == "electricity":
            row["status"] = "heldout_validated_promoted"
            row["executable"] = "true"
        output.append(row)
    return output


def _persist(
    *, config_file: Path, config: Mapping[str, Any], phase: Mapping[str, Any],
    contract_path: Path, heldout_path: Path, contract_rows: list[dict[str, Any]],
    case_status: list[dict[str, Any]], checks: list[dict[str, Any]],
    component_rows: list[dict[str, Any]], component_gate: list[dict[str, Any]],
    anchor_rows: list[dict[str, Any]], flow_rows: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]], checkpoint: Mapping[str, Any], started: float,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase5IFreezeError("Phase-5I governed output root already exists.")
    output.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8")
    _write_csv(output / "contract_verification.csv", contract_rows)
    _write_csv(output / "promoted_contract_preview.csv", promoted_rows(contract_rows) if checkpoint["status"] == "pass" else contract_rows)
    _write_csv(output / "case_status.csv", case_status)
    _write_csv(output / "physical_checks.csv", checks)
    _write_csv(output / "component_overlap_checks.csv", component_gate)
    _write_csv(output / "component_overlap_waterfall.csv", component_rows)
    _write_csv(output / "heldout_anchor_generalisation.csv", anchor_rows)
    _write_csv(output / "heldout_flow_summary.csv", flow_rows)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    input_paths = [
        config_file, contract_path, heldout_path, _resolve(phase["component_reference"]),
        _resolve(phase["phase5g_overlap_contract"]), _resolve(phase["source_contract"]),
        _resolve(phase["phase5h_checkpoint"]), _resolve(phase["phase5h_source_pool"]),
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    ]
    manifest = [{"path": _portable(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size} for path in input_paths]
    _write_json(output / "input_manifest.json", {"files": manifest})
    price_fingerprints = sorted({
        row["price_input_fingerprint_sha256"]
        for artifact in artifacts.values() for row in artifact["costs"]
        if row.get("price_input_fingerprint_sha256")
    })
    fingerprints = {
        "git_head": _git_head(),
        "model_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest if row["path"].endswith(".py")}),
        "input_contract_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest if not row["path"].endswith(".py")}),
        "hsm_policy_fingerprint_sha256": _payload_sha256(load_phase5g_config(_resolve(phase["phase5g_config"]))["phase5g"]["hsm_source_mix_policy_by_configuration"]),
        "terminal_contract_source_sha256": _sha256(_resolve(load_phase5g_config(_resolve(phase["phase5g_config"]))["phase5g"]["parent_phase5b_config"])),
        "forecast_input_fingerprints_sha256": _payload_sha256(price_fingerprints),
        "electricity_baseload_contract_sha256": _sha256(contract_path),
        "heldout_period_contract_sha256": _sha256(heldout_path),
    }
    _write_json(output / "fingerprint_manifest.json", fingerprints)
    _write_json(output / "code_version.json", {"git_head": _git_head(), "model_fingerprint_sha256": fingerprints["model_fingerprint_sha256"]})
    _write_json(output / "registry_entry.json", {
        "run_id": RUN_ID, "run_class": config["run_class"], "lineage_role": config["lineage_role"],
        "output_policy": config["output_policy"], "retention_status": config["retention_status"],
        "decision": checkpoint["decision"],
    })
    summary = {**dict(checkpoint), "runtime_seconds": time.perf_counter() - started, "fingerprints": fingerprints}
    _write_json(output / "run_summary.json", summary)
    (output / "README.md").write_text(
        "# Phase 5I electricity-only held-out freeze\n\n"
        f"Decision: `{checkpoint['decision']}`. This is a represented-boundary gate, not a full-site digital-twin or exact annual-anchor claim.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\nHeld-out annual-equivalent anchor errors are generalisation evidence, not annual backtests. Whole-site NG, steam and direct-CO2 residuals remain outside dispatch and cost. The boundary is not ETS-ready.\n",
        encoding="utf-8",
    )
    return summary


def run_phase5i(config_path: str | Path = CONFIG_PATH, *, refresh_from_cache: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase5i"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase5IFreezeError("Phase-5I requires the preserved parent HEAD.")
    phase5h_checkpoint = _read_json(_resolve(phase["phase5h_checkpoint"]))
    if phase5h_checkpoint["decision"] != "four_residual_gate_failed_residual_layer_not_promoted" or phase5h_checkpoint["fresh_held_out_models"] != 0:
        raise Phase5IFreezeError("Phase-5H starting decision or held-out integrity changed.")
    contract_path = _resolve(phase["selected_contract"])
    contract_rows = load_selected_contract(contract_path)
    pool_checks = validate_pool_identity(contract_rows, _resolve(phase["phase5h_source_pool"]))
    heldout_path = _resolve(phase["held_out_contract"])
    heldout_rows, _ = held_out_contract(heldout_path)
    if len(heldout_rows) != int(phase["expected_period_count"]):
        raise Phase5IFreezeError("Fresh held-out period count changed.")
    scratch = _resolve(phase["scratch_root"])
    if scratch.exists() and not refresh_from_cache:
        raise Phase5IFreezeError("Phase-5I scratch exists; held-out may already have been opened.")
    if refresh_from_cache:
        expected_dirs = {f"phase5g__phase5i_heldout__{row['period_id'].replace('-', '_')}" for row in heldout_rows}
        actual_dirs = {path.name for path in scratch.iterdir() if path.is_dir()} if scratch.exists() else set()
        if actual_dirs != expected_dirs:
            raise Phase5IFreezeError("Cache refresh requires exactly the four completed held-out cases.")
    else:
        scratch.mkdir(parents=True)
    phase5g_config = load_phase5g_config(_resolve(phase["phase5g_config"]))
    phase5g = dict(phase5g_config["phase5g"])
    phase5g["scratch_root"] = phase["scratch_root"]
    parent, phase4, terminal_target = _dependencies(phase5g)
    if _select_solver()[1] is None:
        raise Phase5IFreezeError("Gurobi is unavailable before held-out execution.")
    install_terminal_validation_extension()
    electricity = electricity_maps(contract_rows)
    zero = {configuration: 0.0 for configuration in CONFIGURATIONS}
    artifacts, case_status = _stage_artifacts(
        "phase5i_heldout", heldout_rows, phase5g, parent, phase4, terminal_target,
        electricity, zero,
    )
    tolerance = float(phase["physical_balance_tolerance_mwh"])
    physical = _physical_checks("heldout", artifacts, electricity, zero, tolerance)
    physical += _hsm_checks("heldout", artifacts, phase5g, tolerance)
    physical += residual_zero_checks(artifacts, tolerance)
    physical += pool_checks
    source_rows = load_source_contract(_resolve(phase["source_contract"]))
    overlap_rows = load_overlap_contract(_resolve(phase["phase5g_overlap_contract"]))
    validate_overlap_against_source(overlap_rows, source_rows)
    component_rows, component_gate = component_checks(
        artifacts, heldout_rows, overlap_rows, _resolve(phase["component_reference"]),
        float(phase["component_exceedance_tolerance_pj"]),
    )
    anchors = _primary_anchors(source_rows)
    totals = _actual_totals(artifacts, heldout_rows)
    anchors_rows = [row for row in _anchor_rows("fresh_heldout", totals, anchors) if row["carrier"] == "electricity"]
    flow_rows = _flow_summary("fresh_heldout", artifacts, heldout_rows, 56.1)
    flow_rows += procurement_cost_rows("fresh_heldout", artifacts, heldout_rows)
    flow_rows += steam_and_emissions_rows("fresh_heldout", artifacts, heldout_rows)
    model_count = sum(int(row["model_count"]) for row in case_status)
    passed = (
        model_count == int(phase["expected_models"])
        and all(row["status"] == "pass" for row in case_status + physical + component_gate)
    )
    checkpoint = {
        "run_id": RUN_ID,
        "decision": phase["decision_on_pass"] if passed else phase["decision_on_fail"],
        "status": "pass" if passed else "fail",
        "heldout_models": model_count,
        "all_models_optimal": all(row["all_models_optimal"] == "True" if isinstance(row["all_models_optimal"], str) else row["all_models_optimal"] for row in case_status),
        "selected_electricity_share": 0.1,
        "contract_promoted": passed,
        "residual_ng_share": 0.0, "residual_steam_share": 0.0,
        "residual_direct_co2_share": 0.0,
        "reselection_after_heldout": False,
        "fresh_heldout_opened_once": True,
        "evidence_regenerated_from_completed_cache": refresh_from_cache,
        "phase6_authorization": "phase6a_deterministic_da_bidding_and_settlement_only" if passed else "blocked",
        "scope": "physically_and_terminally_validated_represented_boundary_not_full_site_digital_twin",
        "failure_count": 0 if passed else 1,
    }
    return _persist(
        config_file=config_file, config=config, phase=phase, contract_path=contract_path,
        heldout_path=heldout_path, contract_rows=contract_rows, case_status=case_status,
        checks=physical, component_rows=component_rows, component_gate=component_gate,
        anchor_rows=anchors_rows, flow_rows=flow_rows, artifacts=artifacts,
        checkpoint=checkpoint, started=started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--refresh-from-cache", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_phase5i(args.config, refresh_from_cache=args.refresh_from_cache), indent=2))


if __name__ == "__main__":
    main()
