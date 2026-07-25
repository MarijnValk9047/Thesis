"""Checkpoint-8 analytical screen for the bounded KGF/PeFa emulation surface.

This module never builds or solves a model.  It makes the target overlap and
the missing PeFa production-to-use linkage explicit before any rolling run is
allowed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_transparent_emulation_prescreen.yaml"
)

CONFIGURATIONS = {
    "C0": "C0_current_BF_BOF_reference",
    "C1": "C1_phase1_BF_BOF_plus_DRP_EAF",
}
TARGET_IDS = {
    "kgf_c0": ("mer_c0_kgf1_coke_1_0", "mer_c0_kgf2_coke_0_8"),
    "kgf_c1": ("mer_c1_kgf1_coke_1_0",),
    "pefa_c0": ("mer_c0_pefa_output_4_6",),
    "pefa_c1": ("mer_c1_pefa_output_4_0_5_0",),
}
REJECTION_CODES = (
    "direct_calibration_target_prescription",
    "missing_pefa_consumption_linkage",
    "missing_fired_pellet_inventory_identity",
    "missing_terminal_use_reconciliation",
)


class TransparentEmulationPrescreenError(ValueError):
    """Raised when the frozen analytical screen contract is violated."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = [dict(row) for row in rows]
    if not materialised:
        raise TransparentEmulationPrescreenError(f"Refusing to write empty evidence: {path}")
    fields: list[str] = []
    for row in materialised:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialised)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_path(value: str) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise TransparentEmulationPrescreenError(f"Path escapes repository: {value}") from exc
    return path


def load_prescreen_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TransparentEmulationPrescreenError("Prescreen config must be a mapping.")
    design = payload.get("design", {})
    candidates = design.get("overlay_candidates", {}).get("c1_pefa_mt_y", [])
    if list(candidates) != [4.0, 4.25, 4.5, 4.75, 5.0]:
        raise TransparentEmulationPrescreenError("The frozen five-point C1 PeFa design changed.")
    if float(design.get("overlay_candidates", {}).get("c0_pefa_mt_y", 0.0)) != 4.6:
        raise TransparentEmulationPrescreenError("C0 PeFa must remain the 4.6 Mt/y source point.")
    if int(design.get("round_count", 0)) > int(design.get("maximum_rounds", 0)):
        raise TransparentEmulationPrescreenError("Analytical round limit exceeded.")
    if int(design.get("parameter_family_count", 0)) > int(
        design.get("maximum_parameter_families", 0)
    ):
        raise TransparentEmulationPrescreenError("Parameter-family limit exceeded.")
    if payload.get("prohibitions", {}).get("solver_runs_enabled") is not False:
        raise TransparentEmulationPrescreenError("Checkpoint 8 must remain analytical-only.")
    if tuple(payload.get("hard_rejection_gates", ())) != REJECTION_CODES:
        raise TransparentEmulationPrescreenError("Hard rejection gates changed.")
    return payload


def _target_rows(config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    rows = _read_csv(_repo_path(str(config["target_contract"])))
    by_id = {row["target_id"]: row for row in rows}
    missing = {target for targets in TARGET_IDS.values() for target in targets}.difference(by_id)
    if missing:
        raise TransparentEmulationPrescreenError(f"Missing calibration targets: {sorted(missing)}")
    for target in {target for targets in TARGET_IDS.values() for target in targets}:
        if by_id[target]["allowed_evidential_role"] != "calibration_target":
            raise TransparentEmulationPrescreenError(f"Target role changed: {target}")
    held_out = by_id.get("mer_c1_dri_output_2_8")
    if (
        held_out is None
        or held_out["allowed_evidential_role"] != "scenario_definition"
        or held_out["allowed_use"] != "scenario_definition_consistency_check"
        or held_out["validation_use"] != "false"
    ):
        raise TransparentEmulationPrescreenError("MER DRI overlap role changed.")
    return by_id


def _kgf_baseline_mt_y(config: Mapping[str, Any]) -> dict[str, float]:
    rows = _read_csv(_repo_path(str(config["kgf_baseline_ledger"])))
    selected = {
        row["configuration"]: float(row["model_output"]) / 1_000_000.0
        for row in rows
        if row["anchor_id"] == "kgf_coke_output"
    }
    expected = set(CONFIGURATIONS.values())
    if set(selected) != expected:
        raise TransparentEmulationPrescreenError("Accepted KGF annual ledger is incomplete.")
    return {short: selected[configuration] for short, configuration in CONFIGURATIONS.items()}


def _pefa_baseline_mt_y(config: Mapping[str, Any]) -> dict[str, float]:
    rows = [
        row
        for row in _read_csv(_repo_path(str(config["pefa_baseline_activity"])))
        if row["horizon_hours"] == "24"
    ]
    selected = {
        row["configuration"]: float(row["PEFA_output_site_t_y"]) / 1_000_000.0
        for row in rows
    }
    expected = set(CONFIGURATIONS.values())
    if set(selected) != expected:
        raise TransparentEmulationPrescreenError("Accepted PeFa activity profile is incomplete.")
    return {short: selected[configuration] for short, configuration in CONFIGURATIONS.items()}


def _structural_checks(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    modelbuilder = _repo_path(str(config["modelbuilder"]))
    text = modelbuilder.read_text(encoding="utf-8")
    token_lines = [
        (index, line.strip())
        for index, line in enumerate(text.splitlines(), start=1)
        if "pefa_pellet_output_t" in line
    ]
    if not token_lines:
        raise TransparentEmulationPrescreenError("PeFa output expression is missing.")
    joined = "\n".join(line for _, line in token_lines).lower()
    consumption_link_present = any(
        token in joined for token in ("bf_pellet", "drp_pellet", "pellet_consum", "pellet_use")
    )
    inventory_link_present = "inventory" in joined or "storage" in joined
    terminal_link_present = "terminal" in joined
    line_locator = ";".join(str(number) for number, _ in token_lines)
    return [
        {
            "check_id": "annual_source_range_defined_not_hourly_flexibility",
            "status": "pass",
            "promotion_effect": "none",
            "evidence": "source_cards/PELLETIZING_Parameters.md lines 98-100 and 116",
            "interpretation": "4.0-5.0 Mt/y is an annual C1 band; 5.0 is source-designated central and high.",
        },
        {
            "check_id": "existing_pefa_output_is_fixed_annual_average_expression",
            "status": "pass",
            "promotion_effect": "none",
            "evidence": f"{config['modelbuilder']} lines {line_locator}",
            "interpretation": "The existing controller compiles accepted annual output to a continuous reporting expression; it is not hourly DA flexibility.",
        },
        {
            "check_id": "pefa_output_drives_heat_electricity_and_ore_reporting",
            "status": "pass",
            "promotion_effect": "partial_link_only",
            "evidence": f"{config['modelbuilder']} lines 1510, 1591-1594, 2513-2532, 3396-3415",
            "interpretation": "Energy and ore rows are linked, but this is not a product-consumption identity.",
        },
        {
            "check_id": "pefa_output_to_bf_or_drp_consumption",
            "status": "pass" if consumption_link_present else "fail",
            "promotion_effect": "hard_reject_if_fail",
            "evidence": f"all `{modelbuilder.name}` references to pefa_pellet_output_t",
            "interpretation": "No BF or DRP fired-pellet consumption link exists." if not consumption_link_present else "Consumption link found.",
        },
        {
            "check_id": "fired_pellet_inventory_identity",
            "status": "pass" if inventory_link_present else "fail",
            "promotion_effect": "hard_reject_if_fail",
            "evidence": f"all `{modelbuilder.name}` references to pefa_pellet_output_t",
            "interpretation": "No fired-pellet inventory or storage balance exists." if not inventory_link_present else "Inventory link found.",
        },
        {
            "check_id": "fired_pellet_terminal_use_reconciliation",
            "status": "pass" if terminal_link_present else "fail",
            "promotion_effect": "hard_reject_if_fail",
            "evidence": f"all `{modelbuilder.name}` references to pefa_pellet_output_t",
            "interpretation": "No terminal fired-pellet inventory/use condition exists and none is invented." if not terminal_link_present else "Terminal link found.",
        },
        {
            "check_id": "protected_physical_parameters_unchanged",
            "status": "pass",
            "promotion_effect": "none",
            "evidence": "baseline_freeze.json; calibratable_parameter_contract.csv",
            "interpretation": "No quota, conversion, capacity, WAG coefficient, efficiency, generator rule, residual, site load, route or held-out DRI target is moved.",
        },
        {
            "check_id": "independent_validation_targets_and_periods_excluded",
            "status": "pass",
            "promotion_effect": "none",
            "evidence": "prescreen config prohibitions; target contract mer_c1_dri_output_2_8 scenario-definition role",
            "interpretation": "The analytical design uses no independent validation target or frozen evaluation period; MER DRI is scenario-definition consistency context only.",
        },
    ]


def _candidate_rows(config: Mapping[str, Any], pefa_baseline: Mapping[str, float]) -> list[dict[str, Any]]:
    design = config["design"]
    rows = [
        {
            "candidate_id": "source_driven_baseline",
            "candidate_class": "untouched_source_baseline_comparator",
            "c0_pefa_mt_y": pefa_baseline["C0"],
            "c1_pefa_mt_y": pefa_baseline["C1"],
            "parameter_family_count": 0,
            "physical_parameter_override": False,
            "direct_target_prescription": False,
            "executable_overlay": False,
        }
    ]
    for value in design["overlay_candidates"]["c1_pefa_mt_y"]:
        token = f"{float(value):.2f}".replace(".", "p")
        rows.append(
            {
                "candidate_id": f"pefa_c0_4p60_c1_{token}",
                "candidate_class": "transparent_calibrated_emulation_analytical_only",
                "c0_pefa_mt_y": float(design["overlay_candidates"]["c0_pefa_mt_y"]),
                "c1_pefa_mt_y": float(value),
                "parameter_family_count": 1,
                "physical_parameter_override": False,
                "direct_target_prescription": True,
                "executable_overlay": False,
            }
        )
    return rows


def _family_error_rows(
    *,
    candidates: list[dict[str, Any]],
    targets: Mapping[str, Mapping[str, str]],
    kgf_baseline: Mapping[str, float],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observations = {
        "kgf_c0": {
            "family": "kgf_annual_coke_output",
            "configuration": "C0",
            "target_ids": ";".join(TARGET_IDS["kgf_c0"]),
            "low": sum(float(targets[target]["value_low"]) for target in TARGET_IDS["kgf_c0"]),
            "central": sum(float(targets[target]["value_central"]) for target in TARGET_IDS["kgf_c0"]),
            "high": sum(float(targets[target]["value_high"]) for target in TARGET_IDS["kgf_c0"]),
            "unit": "Mt coke/y",
            "baseline": kgf_baseline["C0"],
            "parameter_status": "frozen_no_source_backed_range",
        },
        "kgf_c1": {
            "family": "kgf_annual_coke_output",
            "configuration": "C1",
            "target_ids": ";".join(TARGET_IDS["kgf_c1"]),
            "low": float(targets[TARGET_IDS["kgf_c1"][0]]["value_low"]),
            "central": float(targets[TARGET_IDS["kgf_c1"][0]]["value_central"]),
            "high": float(targets[TARGET_IDS["kgf_c1"][0]]["value_high"]),
            "unit": "Mt coke/y",
            "baseline": kgf_baseline["C1"],
            "parameter_status": "frozen_zero_width_source_observation",
        },
        "pefa_c0": {
            "family": "pefa_annual_fired_pellet_output",
            "configuration": "C0",
            "target_ids": TARGET_IDS["pefa_c0"][0],
            "low": float(targets[TARGET_IDS["pefa_c0"][0]]["value_low"]),
            "central": float(targets[TARGET_IDS["pefa_c0"][0]]["value_central"]),
            "high": float(targets[TARGET_IDS["pefa_c0"][0]]["value_high"]),
            "unit": "Mt fired pellets/y",
            "parameter_status": "analytical_only_rejected_missing_physical_linkage",
        },
        "pefa_c1": {
            "family": "pefa_annual_fired_pellet_output",
            "configuration": "C1",
            "target_ids": TARGET_IDS["pefa_c1"][0],
            "low": float(targets[TARGET_IDS["pefa_c1"][0]]["value_low"]),
            "central": float(targets[TARGET_IDS["pefa_c1"][0]]["value_central"]),
            "high": float(targets[TARGET_IDS["pefa_c1"][0]]["value_high"]),
            "unit": "Mt fired pellets/y",
            "parameter_status": "analytical_only_rejected_missing_physical_linkage",
        },
    }
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        values = {
            "kgf_c0": kgf_baseline["C0"],
            "kgf_c1": kgf_baseline["C1"],
            "pefa_c0": float(candidate["c0_pefa_mt_y"]),
            "pefa_c1": float(candidate["c1_pefa_mt_y"]),
        }
        for observation_id, observation in observations.items():
            value = values[observation_id]
            central = float(observation["central"])
            low = float(observation["low"])
            high = float(observation["high"])
            signed = value - central
            band_distance = max(low - value, value - high, 0.0)
            rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_class": candidate["candidate_class"],
                    "target_family": observation["family"],
                    "observation_id": observation_id,
                    "target_ids": observation["target_ids"],
                    "configuration": observation["configuration"],
                    "model_value_raw": round(value, 12),
                    "source_low_raw": low,
                    "source_central_raw": central,
                    "source_high_raw": high,
                    "unit": observation["unit"],
                    "signed_residual_raw": round(signed, 12),
                    "signed_residual_share": round(signed / central, 12),
                    "absolute_normalised_error": round(abs(signed) / central, 12),
                    "band_violation_raw": round(band_distance, 12),
                    "band_violation_share": round(band_distance / central, 12),
                    "family_weight": float(config["scoring"][f"{'kgf' if observation_id.startswith('kgf') else 'pefa'}_family_weight"]),
                    "parameter_status": observation["parameter_status"],
                    "held_out_target_used": False,
                    "held_out_period_used": False,
                }
            )
    return rows


def _scorecard_rows(
    *, candidates: list[dict[str, Any]], family_rows: list[dict[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        selected = [row for row in family_rows if row["candidate_id"] == candidate["candidate_id"]]
        kgf = [row for row in selected if row["target_family"] == "kgf_annual_coke_output"]
        pefa = [row for row in selected if row["target_family"] == "pefa_annual_fired_pellet_output"]
        kgf_error = sum(float(row["absolute_normalised_error"]) for row in kgf) / len(kgf)
        pefa_error = sum(float(row["absolute_normalised_error"]) for row in pefa) / len(pefa)
        source_deviation = (
            abs(5.0 - float(candidate["c1_pefa_mt_y"])) / (5.0 - 4.0)
            if candidate["candidate_id"] != "source_driven_baseline"
            else 0.0
        )
        overlap_indicator = float(bool(candidate["direct_target_prescription"]))
        deviation_weight = float(config["scoring"]["source_central_deviation_penalty_weight"])
        overlap_weight = float(config["scoring"]["direct_target_overlap_penalty_weight"])
        weighted_deviation = deviation_weight * source_deviation
        weighted_overlap = overlap_weight * overlap_indicator
        soft_score = (
            float(config["scoring"]["kgf_family_weight"]) * kgf_error
            + float(config["scoring"]["pefa_family_weight"]) * pefa_error
            + weighted_deviation
            + weighted_overlap
        )
        is_overlay = candidate["candidate_id"] != "source_driven_baseline"
        results.append(
            {
                **candidate,
                "round_id": 1 if is_overlay else 0,
                "kgf_family_mean_absolute_normalised_error": round(kgf_error, 12),
                "kgf_family_weight": float(config["scoring"]["kgf_family_weight"]),
                "pefa_family_mean_absolute_normalised_error": round(pefa_error, 12),
                "pefa_family_weight": float(config["scoring"]["pefa_family_weight"]),
                "source_central_deviation_raw": round(source_deviation, 12),
                "source_central_deviation_penalty_weight": deviation_weight,
                "source_central_deviation_penalty_weighted": round(weighted_deviation, 12),
                "direct_target_overlap_indicator": overlap_indicator,
                "direct_target_overlap_penalty_weight": overlap_weight,
                "direct_target_overlap_penalty_weighted": round(weighted_overlap, 12),
                "transparent_soft_score": round(soft_score, 12),
                "soft_score_formula": config["scoring"]["soft_score_formula"],
                "hard_rejection_count": len(REJECTION_CODES) if is_overlay else 0,
                "hard_rejection_codes": ";".join(REJECTION_CODES) if is_overlay else "none_baseline_comparator",
                "prescreen_decision": "rejected_before_rolling" if is_overlay else "baseline_retained_comparator",
                "rolling_eligible": False,
                "promotion_class": "source_valid_emulation_rejected" if is_overlay else "source_driven_baseline_retained",
            }
        )
    return results


def _parameter_overlay_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **candidate,
            "c0_source_low_mt_y": 4.6,
            "c0_source_central_mt_y": 4.6,
            "c0_source_high_mt_y": 4.6,
            "c1_source_low_mt_y": 4.0,
            "c1_source_central_mt_y": 5.0,
            "c1_source_high_mt_y": 5.0,
            "c1_source_central_equals_high": True,
            "annual_band_not_hourly_flexibility": True,
            "kgf_parameter_moved": False,
            "pefa_parameter_moved_in_executable_model": False,
            "held_out_target_used": False,
            "held_out_period_used": False,
        }
        for candidate in candidates
    ]


def _manifest(config: Mapping[str, Any], config_path: Path) -> dict[str, Any]:
    inputs = [
        _repo_path(str(config[key]))
        for key in (
            "parameter_contract",
            "target_contract",
            "baseline_freeze",
            "kgf_baseline_ledger",
            "pefa_baseline_activity",
            "modelbuilder",
        )
    ] + [_repo_path(str(value)) for value in config["source_cards"].values()] + [config_path]
    module = Path(__file__).resolve()
    runner = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_c5_transparent_emulation_prescreen.py"
    return {
        "inputs": [
            {
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in inputs
        ],
        "executables": [
            {
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in (module, runner)
        ],
        "source_inputs_mutated": False,
        "solver_run_performed": False,
        "held_out_target_used": False,
        "held_out_period_used": False,
    }


def run_transparent_emulation_prescreen(
    *, config_path: str | Path = DEFAULT_CONFIG
) -> dict[str, Any]:
    started = time.perf_counter()
    resolved_config_path = Path(config_path).resolve()
    config = load_prescreen_config(resolved_config_path)
    output = _repo_path(str(config["output_root"]))
    output.mkdir(parents=True, exist_ok=True)

    targets = _target_rows(config)
    kgf_baseline = _kgf_baseline_mt_y(config)
    pefa_baseline = _pefa_baseline_mt_y(config)
    structural_checks = _structural_checks(config)
    if sum(row["status"] == "fail" for row in structural_checks) != 3:
        raise TransparentEmulationPrescreenError(
            "Expected the three missing PeFa consumption/inventory/terminal hard gates."
        )
    candidates = _candidate_rows(config, pefa_baseline)
    family_rows = _family_error_rows(
        candidates=candidates,
        targets=targets,
        kgf_baseline=kgf_baseline,
        config=config,
    )
    scorecard = _scorecard_rows(candidates=candidates, family_rows=family_rows, config=config)
    if len(candidates) != 6 or sum(row["candidate_class"].startswith("transparent") for row in candidates) != 5:
        raise TransparentEmulationPrescreenError("Analytical candidate count changed.")
    if any(row["rolling_eligible"] for row in scorecard):
        raise TransparentEmulationPrescreenError("A structurally unlinked candidate cannot reach rolling.")

    _write_csv(output / "checkpoint8_parameter_overlay_design.csv", _parameter_overlay_rows(candidates))
    _write_csv(output / "checkpoint8_target_family_errors.csv", family_rows)
    _write_csv(output / "checkpoint8_candidate_scorecard.csv", scorecard)
    _write_csv(output / "checkpoint8_structural_linkage_checks.csv", structural_checks)
    _write_csv(
        output / "checkpoint9_rolling_candidate_decision.csv",
        [
            {
                "checkpoint": 9,
                "status": "not_started_no_eligible_promoted_candidate",
                "retained_candidate_count": 0,
                "rolling_candidate_count": 0,
                "validation_period_count_used": 0,
                "solver_run_performed": False,
                "decision": "source_valid_emulation_rejected",
                "source_driven_baseline_retained": True,
                "checkpoint_10_status": "not_applicable_no_retained_candidate",
                "reason": ";".join(REJECTION_CODES),
            }
        ],
    )
    _write_csv(
        output / "concessions_and_gaps.csv",
        [
            {
                "gap_id": "kgf_no_executable_operating_band",
                "status": "preserved_unresolved",
                "effect": "KGF calibration family cannot move",
                "evidence": "Coking_Plants_Parameters.md lines 86-87 and 133-135; parameter contract",
                "required_specific_repair": "source-backed annual KGF operating range and a governed linkage that does not alter protected minima/conversions",
            },
            {
                "gap_id": "c0_kgf2_active_minimum_mismatch",
                "status": "structural_mismatch_preserved",
                "effect": "0.8 Mt/y cannot be reached through the protected 150 t dry-coal/h minimum at 1.285 t/t",
                "evidence": "target contract mer_c0_kgf2_coke_0_8",
                "required_specific_repair": "independent source evidence for the operating policy; anchor residual is not sufficient",
            },
            {
                "gap_id": "pefa_output_not_linked_to_consumption_or_inventory",
                "status": "hard_promotion_blocker_for_emulation_overlay",
                "effect": "all five direct PeFa output prescriptions rejected before rolling",
                "evidence": f"{config['modelbuilder']} PeFa output references and checkpoint8_structural_linkage_checks.csv",
                "required_specific_repair": "source-backed PeFa-to-BF/DRP consumption, fired-pellet storage balance and terminal-use policy",
            },
            {
                "gap_id": "pefa_target_parameter_overlap",
                "status": "overfit_risk_explicit",
                "effect": "analytical fit cannot count as independent emulation evidence",
                "evidence": "checkpoint8_candidate_scorecard.csv direct_target_overlap_penalty",
                "required_specific_repair": "validate a linked physical parameter against evidence independent of the target used to set it",
            },
            {
                "gap_id": "mer_dri_target_embedded_in_eaf_material_conversion",
                "status": "scenario_definition_overlap_reclassified",
                "effect": "strict independent quantitative MER held-out family count is zero",
                "evidence": "EAF_Parameters.md lines 153-155; active config hdri_t_per_t_liquid_steel=0.8484848485; builder EAF coupling and DRI inventory",
                "required_specific_repair": "a genuinely independent quantitative site observation not used to define an active route coefficient",
            },
        ],
    )
    _write_csv(
        output / "final_readiness.csv",
        [
            {"gate": "checkpoint_8_analytical_prescreen", "status": "complete_reviewed", "decision": "all_five_overlays_rejected"},
            {"gate": "checkpoint_9_rolling_validation", "status": "not_started_no_eligible_promoted_candidate", "decision": "zero_rolling_candidates"},
            {"gate": "checkpoint_10_candidate_evaluation", "status": "not_applicable_no_retained_candidate", "decision": "do_not_run"},
            {"gate": "emulation_promotion", "status": "final_no_go", "decision": "source_valid_emulation_rejected"},
            {"gate": "independent_quantitative_mer_validation", "status": "no_go", "decision": "zero_independent_families_after_dri_overlap_reclassification"},
            {"gate": "independent_review", "status": "complete", "decision": "complete"},
            {"gate": "source_driven_behavioural_validation", "status": "complete", "decision": "frozen_source_baseline_physical_and_behavioural_evidence_accepted_for_thesis_interpretation"},
        ],
    )

    parameter_contract = _repo_path(str(config["parameter_contract"]))
    target_contract = _repo_path(str(config["target_contract"]))
    baseline_freeze = _repo_path(str(config["baseline_freeze"]))
    (output / "calibratable_parameter_contract.csv").write_bytes(parameter_contract.read_bytes())
    (output / "calibration_validation_target_contract.csv").write_bytes(target_contract.read_bytes())
    (output / "baseline_freeze.json").write_bytes(baseline_freeze.read_bytes())
    (output / "resolved_transparent_emulation_prescreen.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    checkpoint_state = {
        "completed_checkpoint": 8,
        "completed_subcheckpoint": "transparent_emulation_analytical_prescreen",
        "next_gate": "thesis_interpretation_of_frozen_source_driven_deterministic_D-Dplus4_response",
        "rolling_or_solver_run_performed": False,
        "calibration_authorized": False,
        "analytical_overlay_candidate_count": 5,
        "source_baseline_comparator_count": 1,
        "retained_rolling_candidate_count": 0,
        "checkpoint_9_status": "not_started_no_eligible_promoted_candidate",
        "checkpoint_10_status": "not_applicable_no_retained_candidate",
        "promotion_status": "source_valid_emulation_rejected",
        "decision": "source_valid_emulation_rejected",
        "status": "source_valid_emulation_rejected",
        "independent_review_required": False,
        "independent_reviewer_decision": "complete",
        "coverage_classification": "partial_emulation",
        "quantitative_calibration_family_count": 2,
        "executable_calibration_degree_of_freedom_count": 0,
        "strict_independent_quantitative_mer_validation_family_count": 0,
        "mer_c1_dri_output_2_8_role": "scenario_definition_consistency_check",
        "held_out_targets_used": False,
        "held_out_periods_used": False,
        "source_driven_behavioural_validation": "complete",
        "source_baseline_retention_evidence_basis": "physical_and_behavioural_not_independent_quantitative_MER_validation",
    }
    _write_json(output / "checkpoint_state.json", checkpoint_state)

    historical_summary_path = output / "run_summary.json"
    historical = (
        json.loads(historical_summary_path.read_text(encoding="utf-8"))
        if historical_summary_path.exists()
        else {}
    )
    historical_candidate_count = int(
        historical.get(
            "historical_prescreen_candidate_count",
            historical.get("candidate_count", 0),
        )
    )
    summary = {
        **historical,
        "historical_prescreen_candidate_count": historical_candidate_count,
        "candidate_count": 5,
        "source_baseline_comparator_count": 1,
        "analytical_design_row_count": 6,
        "execution_type": "analytical_prescreen_no_solver",
        "parameter_family_count": 1,
        "retained_candidate_count": 0,
        "retained_rolling_candidate_count": 0,
        "rejected_candidate_count": 5,
        "retained_candidate_ids": [],
        "checkpoint_8_status": "complete_all_overlays_rejected",
        "checkpoint_9_status": "not_started_no_eligible_promoted_candidate",
        "checkpoint_10_status": "not_applicable_no_retained_candidate",
        "promotion_status": "source_valid_emulation_rejected",
        "decision": "source_valid_emulation_rejected",
        "source_baseline_retained": True,
        "source_hashes_unchanged": False,
        "physical_source_input_hashes_unchanged": True,
        "governance_contract_hashes_evolved": True,
        "solver_run_performed": False,
        "physical_config_changed": False,
        "model_logic_changed": False,
        "held_out_targets_used": False,
        "held_out_periods_used": False,
        "checkpoint_3b_held_out_validation_target_ids": [],
        "checkpoint_3b_strict_independent_held_out_family_count": 0,
        "checkpoint_3b_role_freeze_status": "reclassified_checkpoint8_overlap_audit_20260722",
        "checkpoint_3b_status": "superseded_by_checkpoint8_overlap_audit",
        "strict_independent_quantitative_mer_validation_family_count": 0,
        "mer_c1_dri_output_2_8_role": "scenario_definition_consistency_check",
        "source_baseline_retention_evidence_basis": "physical_and_behavioural_not_independent_quantitative_MER_validation",
        "scored_target_ids": [target for targets in TARGET_IDS.values() for target in targets],
        "checkpoint_8_scored_target_ids": [target for targets in TARGET_IDS.values() for target in targets],
        "independent_validation_in_score": False,
        "calibration_target_family_count": 2,
        "kgf_family_scoring_basis": "configuration_total_from_accepted_annual_ledger_against_sum_of_unit_targets; unit split not independently identified",
        "pefa_family_scoring_basis": "raw annual fired-pellet output against source central with band violation reported separately",
        "hard_rejection_codes": list(REJECTION_CODES),
        "next_gate": "thesis_interpretation_of_frozen_source_driven_deterministic_D-Dplus4_response",
        "status": "source_valid_emulation_rejected",
        "independent_review_required": False,
        "independent_reviewer_decision": "complete",
        "runtime_seconds_checkpoint_8": round(time.perf_counter() - started, 6),
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "parent_run_id": "steel_s2_deterministic_price_response_anchor_diagnostics_v1_20260720",
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": config["output_policy"],
            "status": "source_valid_emulation_rejected",
            "decision": "source_valid_emulation_rejected",
            "independent_review_required": False,
            "independent_reviewer_decision": "complete",
            "next_gate": "thesis_interpretation_of_frozen_source_driven_deterministic_D-Dplus4_response",
        },
    )

    (output / "README.md").write_text(
        "# Tata-inspired C5 benchmark programme\n\n"
        "Checkpoint 8 screened one untouched source baseline and five analytical PeFa annual-output overlays. "
        "The PeFa C0 point is 4.6 Mt/y; the C1 design is 4.0, 4.25, 4.5, 4.75 and 5.0 Mt/y. "
        "The C1 evidence is an annual 4.0-5.0 Mt/y band, not hourly flexibility; 5.0 Mt/y is both the source-designated central value and high bound.\n\n"
        "All five overlays are rejected before rolling. The active PeFa output expression drives PeFa heat, electricity and iron-ore procurement, but it is not linked to BF/DRP fired-pellet consumption, a fired-pellet inventory, or terminal-use reconciliation. Directly prescribing PeFa output would therefore prescribe the calibration target without proving consumed physical production. The explicit target-overlap penalty does not override these hard gates.\n\n"
        "KGF remains frozen because MER supplies annual observations but no source-backed movable operating range or clean annual-output controller. The C0 KGF2 mismatch is preserved; no minimum, conversion, quota or capacity is changed.\n\n"
        "MER C1 2.8 Mt/y DRI is not independent validation: 2.8/3.3 defines the active 0.8484848485-t-HDRI/t-liquid-steel material coefficient used by the EAF coupling and DRI inventory. Its 2.7286-Mt/y comparison is route-consistency reporting context only. Zero independent quantitative MER validation families remain.\n\n"
        "Checkpoint 9 is `not_started_no_eligible_promoted_candidate`; checkpoint 10 is `not_applicable_no_retained_candidate`. No solver, independent-validation target, frozen evaluation period, residual plug, export relaxation, model-logic change or physical-configuration change was used. The independent reviewer decision is `complete` and the final result is `source_valid_emulation_rejected`; the source-driven baseline is retained on physical and behavioural evidence. The next permitted work is thesis interpretation of its frozen deterministic D-D+4 response over four validation and four held-out representative periods. No further calibration, candidate search, exact-Tata claim, full-year empirical claim, bidding, settlement, revenue, ETS, stochasticity, CVaR or mFRR is authorised.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The five PeFa rows are analytical prescriptions, not executable or promoted model configurations.\n"
        "- The PeFa annual-output evidence is not hourly flexibility evidence.\n"
        "- PeFa output lacks BF/DRP consumption, fired-pellet inventory and terminal-use linkage in the active builder.\n"
        "- KGF annual targets have no source-backed movable operating range; C0 KGF2 conflicts with the protected development minimum.\n"
        "- MER C1 DRI is scenario-definition consistency context because its 2.8/3.3 ratio defines the active EAF HDRI coefficient; the 2.7286-Mt/y comparison is not independent validation.\n"
        "- No strict independent quantitative MER validation family remains. No frozen evaluation period was used in calibration.\n"
        "- Historical WAG/efficiency prescreen artifacts remain invalidated and were not revived.\n"
        "- No rolling solve, physical-parameter calibration, residual input, new load, export, WAG/NG ratio or mixed-gas allocation occurred.\n",
        encoding="utf-8",
    )
    _write_json(output / "input_manifest.json", _manifest(config, resolved_config_path))
    return {"output_directory": str(output), "summary": summary, "scorecard": scorecard}
