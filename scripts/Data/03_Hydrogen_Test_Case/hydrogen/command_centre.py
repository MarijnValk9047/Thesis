from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import pandas as pd
import yaml

from .optimisation.fingerprinting import (
    build_experiment_fingerprint,
    fingerprint_file,
    fingerprint_payload,
)
from .optimisation.progress_reporting import ProgressPaths, ProgressReporter
from .plant_parameters import load_hydrogen_config
from .run_registry import build_inputs_manifest, make_run_id
from .scenario_loader import load_scenario_catalog
from .selected_week_policy import (
    OFFICIAL_TEST_SELECTED_WEEKS_PATH,
    OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH,
    resolve_selected_entries,
)
from .selected_week_smoke import run_selected_week_risk_neutral_smoke

DEFAULT_COMMAND_CENTRE_CONFIG = Path("scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_command_centre.yaml")
DEFAULT_SUPPORTED_OPTIONS = Path("scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml")
DEPRECATED_SELECTED_WEEKS_PATH = Path("scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks.yaml")

TUNING_KEYWORDS = (
    "tuning",
    "development",
    "calibration",
    "cvar selection",
    "scenario reduction selection",
    "solver approximation selection",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML payload in {path}.")
    return payload


def _normalise_text_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        return [str(value) for value in values if str(value).strip()]
    if str(values).strip():
        return [str(values)]
    return []


def _supported_entry(registry: dict[str, Any], section: str, key: str) -> dict[str, Any]:
    options = registry.get(section)
    if not isinstance(options, dict) or key not in options:
        raise ValueError(f"Unsupported {section} option: {key!r}")
    entry = options[key]
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid registry entry for {section}.{key}")
    return entry


def _assert_registry_option(
    *,
    registry: dict[str, Any],
    section: str,
    key: str,
    require_implemented: bool = True,
) -> dict[str, Any]:
    entry = _supported_entry(registry, section, key)
    if not bool(entry.get("allowed", False)):
        raise ValueError(f"{section}.{key} is not allowed.")
    if require_implemented and not bool(entry.get("implemented", False)):
        raise ValueError(
            f"{section}.{key} is planned but not implemented. Restrictions: {entry.get('restrictions', '')}"
        )
    return entry


def _command_centre_hash(payload: dict[str, Any]) -> str:
    return fingerprint_payload(payload, length=24)


def load_command_centre_config(config_path: Path | str = DEFAULT_COMMAND_CENTRE_CONFIG) -> dict[str, Any]:
    return _load_yaml(Path(config_path))


def load_supported_options(supported_path: Path | str = DEFAULT_SUPPORTED_OPTIONS) -> dict[str, Any]:
    return _load_yaml(Path(supported_path))


def validate_command_centre_config(
    payload: dict[str, Any],
    *,
    supported_options: dict[str, Any],
) -> dict[str, Any]:
    method_version = str(payload.get("method_version", "")).strip()
    if not method_version:
        raise ValueError("method_version is required.")
    _assert_registry_option(registry=supported_options, section="method_versions", key=method_version)

    general = {
        "method_version": method_version,
        "run_purpose": str(payload.get("run_purpose", "")).strip(),
        "run_label": str(payload.get("run_label", "")).strip(),
        "notes": str(payload.get("notes", "")).strip(),
    }
    if not general["run_label"]:
        raise ValueError("run_label is required.")

    scope = {
        "asset_case": str(payload.get("asset_case", "")).strip(),
        "market_scope": str(payload.get("market_scope", "")).strip(),
        "granularity": str(payload.get("granularity", "")).strip(),
        "horizon": str(payload.get("horizon", "")).strip(),
        "split": str(payload.get("split", "")).strip(),
        "period_mode": str(payload.get("period_mode", "")).strip(),
        "selected_regimes": _normalise_text_list(payload.get("selected_regimes")),
        "custom_start_date": payload.get("custom_start_date"),
        "custom_end_date": payload.get("custom_end_date"),
    }
    for section_name, key in (
        ("asset_cases", scope["asset_case"]),
        ("market_scopes", scope["market_scope"]),
        ("granularities", scope["granularity"]),
        ("horizons", scope["horizon"]),
        ("splits", scope["split"]),
        ("period_modes", scope["period_mode"]),
    ):
        _assert_registry_option(registry=supported_options, section=section_name, key=key)
    for regime in scope["selected_regimes"]:
        _assert_registry_option(registry=supported_options, section="selected_regimes", key=regime)

    inputs = {
        "scenario_models": _normalise_text_list(payload.get("scenario_models")),
        "artifact_ids": _normalise_text_list(payload.get("artifact_ids")),
        "scenario_count_policy": str(payload.get("scenario_count_policy", "")).strip(),
        "actual_price_source": str(payload.get("actual_price_source", "")).strip(),
        "selected_week_config_validation": str(payload.get("selected_week_config_validation", "")).strip(),
        "selected_week_config_test": str(payload.get("selected_week_config_test", "")).strip(),
    }
    _assert_registry_option(registry=supported_options, section="scenario_count_policies", key=inputs["scenario_count_policy"])
    _assert_registry_option(registry=supported_options, section="actual_price_sources", key=inputs["actual_price_source"])
    for model in inputs["scenario_models"]:
        _assert_registry_option(registry=supported_options, section="scenario_models", key=model)
    for artifact_id in inputs["artifact_ids"]:
        _assert_registry_option(registry=supported_options, section="artifact_ids", key=artifact_id)

    if not inputs["artifact_ids"] and inputs["scenario_models"]:
        mapped_artifacts: list[str] = []
        for model in inputs["scenario_models"]:
            entry = _supported_entry(supported_options, "scenario_models", model)
            default_artifact = str(entry.get("default_artifact_id", "")).strip()
            if not default_artifact:
                raise ValueError(f"scenario_models.{model} does not define a default_artifact_id.")
            mapped_artifacts.append(default_artifact)
        inputs["artifact_ids"] = mapped_artifacts

    if not inputs["artifact_ids"]:
        raise ValueError("At least one artifact_id or scenario_model must be configured.")

    risk = {
        "gamma_values": [float(value) for value in payload.get("gamma_values", [])],
        "cvar_alpha": float(payload.get("cvar_alpha", 0.95)),
        "risk_mode": str(payload.get("risk_mode", "")).strip(),
    }
    _assert_registry_option(registry=supported_options, section="risk_modes", key=risk["risk_mode"])
    if risk["risk_mode"] == "risk_neutral" and any(abs(value) > 1e-12 for value in risk["gamma_values"]):
        raise ValueError("risk_mode=risk_neutral requires gamma_values to be [0.0] or empty.")
    if risk["risk_mode"] == "cvar":
        raise ValueError("risk_mode=cvar is planned but not implemented in the command-centre backend yet.")

    execution = {
        "output_mode": str(payload.get("output_mode", "")).strip(),
        "audit_days": _normalise_text_list(payload.get("audit_days")),
        "run_figures": bool(payload.get("run_figures", False)),
        "write_solver_logs": bool(payload.get("write_solver_logs", False)),
        "use_cache": bool(payload.get("use_cache", True)),
        "use_benchmark_cache": bool(payload.get("use_benchmark_cache", True)),
        "progress_reporting": bool(payload.get("progress_reporting", True)),
        "max_workers": int(payload.get("max_workers", 1)),
        "gurobi_threads": int(payload.get("gurobi_threads", 1)),
    }
    _assert_registry_option(registry=supported_options, section="output_modes", key=execution["output_mode"])
    if execution["audit_days"]:
        raise ValueError("audit_days are not implemented yet for the command-centre selected-week backend.")
    if execution["max_workers"] != 1:
        raise ValueError("max_workers other than 1 are planned but not implemented.")
    if execution["gurobi_threads"] != 1:
        raise ValueError("gurobi_threads other than 1 are planned but not implemented.")
    if not execution["use_cache"]:
        raise ValueError("use_cache=false is planned but not implemented in the current command-centre backend.")
    if not execution["use_benchmark_cache"]:
        raise ValueError("use_benchmark_cache=false is planned but not implemented in the current command-centre backend.")
    if execution["run_figures"] and execution["output_mode"] in {"speed", "minimal", "audit"}:
        raise ValueError("run_figures=true is only supported with output_mode=full in the current backend.")
    if execution["write_solver_logs"]:
        raise ValueError(
            "write_solver_logs=true is not implemented as an independent command-centre override. "
            "Solver-log persistence is currently controlled by output_mode plus failure/audit policy."
        )

    governance = {
        "allow_test_for_tuning": bool(payload.get("allow_test_for_tuning", False)),
        "methodological_approximation": bool(payload.get("methodological_approximation", False)),
        "methodological_approximation_type": str(payload.get("methodological_approximation_type", "")).strip(),
        "require_common_support": bool(payload.get("require_common_support", True)),
        "require_doctor_pass": bool(payload.get("require_doctor_pass", True)),
    }
    if governance["methodological_approximation"]:
        raise ValueError(
            "methodological_approximation=true is not implemented in the command-centre backend. "
            "Planned approximation modes must be explicitly added first."
        )

    if scope["period_mode"] != "selected_regimes":
        raise ValueError(
            f"period_mode={scope['period_mode']!r} is planned but not implemented in the command-centre backend."
        )
    if scope["split"] == "custom":
        raise ValueError("split='custom' is planned but not implemented.")
    if scope["period_mode"] == "selected_regimes" and not scope["selected_regimes"]:
        raise ValueError("selected_regimes must be populated when period_mode='selected_regimes'.")

    validation_cfg = Path(inputs["selected_week_config_validation"])
    test_cfg = Path(inputs["selected_week_config_test"])
    if validation_cfg == DEPRECATED_SELECTED_WEEKS_PATH or test_cfg == DEPRECATED_SELECTED_WEEKS_PATH:
        raise ValueError("Deprecated selected_weeks.yaml is not allowed for official command-centre runs.")

    selected_week_config_path = validation_cfg if scope["split"] == "validation" else test_cfg
    if selected_week_config_path == DEPRECATED_SELECTED_WEEKS_PATH:
        raise ValueError("Deprecated selected_weeks.yaml is not allowed for official runs.")

    lower_purpose = " ".join([general["run_purpose"], general["notes"]]).lower()
    if (
        scope["split"] == "test"
        and not governance["allow_test_for_tuning"]
        and any(keyword in lower_purpose for keyword in TUNING_KEYWORDS)
    ):
        raise ValueError(
            "Test split is forbidden for tuning/development/calibration/CVaR-selection/approximation-selection runs."
        )

    selected_entries = resolve_selected_entries(
        selected_week_config_path,
        requested_identifiers=scope["selected_regimes"],
        expected_split=scope["split"],
    )
    selected_week_payload = _load_yaml(selected_week_config_path)
    if scope["split"] == "validation" and "winter_proxy" in scope["selected_regimes"]:
        winter_proxy = selected_entries.loc[selected_entries["label"].astype(str).eq("winter_proxy")]
        if not winter_proxy.empty and bool(winter_proxy["seasonal_claims_valid"].iloc[0]):
            raise ValueError("winter_proxy must remain invalid for seasonal winter claims.")

    resolved = {
        "general": general,
        "scope": scope,
        "inputs": inputs,
        "risk": risk,
        "execution": execution,
        "governance": governance,
        "selected_week_config_path": selected_week_config_path,
        "selected_entries": selected_entries,
        "command_centre_hash": _command_centre_hash(payload),
        "supported_options_version": str(supported_options.get("registry_version", "")),
        "selected_week_policy_version": str(selected_week_payload.get("selection_policy_version", "")),
    }
    backend = determine_backend(resolved)
    _assert_registry_option(registry=supported_options, section="backends", key=backend)
    resolved["backend"] = backend
    return resolved


def determine_backend(resolved: dict[str, Any]) -> str:
    scope = resolved["scope"]
    risk = resolved["risk"]
    if (
        scope["asset_case"] == "hydrogen"
        and scope["market_scope"] == "DA_only"
        and scope["granularity"] == "hourly"
        and scope["horizon"] == "D_only"
        and scope["period_mode"] == "selected_regimes"
        and risk["risk_mode"] == "risk_neutral"
    ):
        return "selected_week_hydrogen_fastpath_v1"
    raise ValueError(
        "No implemented command-centre backend matches the requested combination. "
        "Current implementation supports only hourly D_only hydrogen DA_only selected_regimes risk_neutral runs."
    )


def command_centre_output_mode_to_policy(output_mode: str) -> str:
    normalized = str(output_mode).strip().lower()
    if normalized in {"speed", "minimal"}:
        return "minimal"
    if normalized == "audit":
        return "audit"
    if normalized == "full":
        return "full"
    raise ValueError(f"Unsupported command-centre output mode: {output_mode!r}")


def _build_command_centre_snapshot(
    *,
    raw_payload: dict[str, Any],
    resolved: dict[str, Any],
) -> dict[str, Any]:
    selected_entries = resolved["selected_entries"].copy()
    entries = selected_entries[
        [
            "label",
            "week_label",
            "week_id",
            "regime_label",
            "start_local_date",
            "end_local_date",
            "selection_status",
            "proxy_for_regime_label",
            "seasonal_claims_valid",
            "allowed_use_restriction",
        ]
    ].to_dict(orient="records")
    return {
        "raw_config": raw_payload,
        "resolved": {
            "backend": resolved["backend"],
            "command_centre_hash": resolved["command_centre_hash"],
            "supported_options_version": resolved["supported_options_version"],
            "selected_week_policy_version": resolved["selected_week_policy_version"],
            "selected_week_config_path": str(resolved["selected_week_config_path"]),
            "selected_entries": entries,
            "effective_artifact_ids": list(resolved["inputs"]["artifact_ids"]),
            "effective_output_policy": command_centre_output_mode_to_policy(resolved["execution"]["output_mode"]),
        },
    }


def _collect_artifact_fingerprints(*, base_config_path: Path, artifact_ids: list[str]) -> list[dict[str, Any]]:
    config = load_hydrogen_config(base_config_path)
    catalog = load_scenario_catalog(config.models.scenario_catalog)
    fingerprints: list[dict[str, Any]] = []
    for artifact_id in artifact_ids:
        artifacts = catalog.get("artifacts", {})
        if not isinstance(artifacts, dict) or artifact_id not in artifacts:
            raise KeyError(f"Scenario artifact {artifact_id!r} is missing in {config.models.scenario_catalog}.")
        artifact_entry = artifacts[artifact_id]
        spec_path = Path(artifact_entry["path"])
        if not spec_path.is_absolute():
            spec_path = (config.repo_root / spec_path).resolve()
        record = fingerprint_file(spec_path, include_sha256=False).to_dict()
        record["artifact_id"] = str(artifact_id)
        record["model_id"] = str(artifact_entry.get("model_id", ""))
        record["granularity"] = str(artifact_entry.get("granularity", ""))
        record["validation_mode"] = str(artifact_entry.get("validation_mode", ""))
        fingerprints.append(record)
    return fingerprints


def _expected_solves_for_resolved_config(resolved: dict[str, Any]) -> int:
    if resolved["backend"] == "selected_week_hydrogen_fastpath_v1":
        return int(
            len(resolved["inputs"]["artifact_ids"])
            * len(resolved["selected_entries"])
            * 7
            * max(len(resolved["risk"]["gamma_values"]), 1)
        )
    raise ValueError(f"Unsupported backend for expected solve counting: {resolved['backend']}")


def _build_parent_config_resolved(
    *,
    raw_payload: dict[str, Any],
    resolved: dict[str, Any],
    base_config_path: Path,
) -> dict[str, Any]:
    return {
        "command_centre_raw": raw_payload,
        "command_centre_resolved": {
            "backend": resolved["backend"],
            "method_version": resolved["general"]["method_version"],
            "command_centre_hash": resolved["command_centre_hash"],
            "supported_options_version": resolved["supported_options_version"],
            "selected_week_policy_version": resolved["selected_week_policy_version"],
            "selected_week_config_path": str(resolved["selected_week_config_path"]),
            "effective_artifact_ids": list(resolved["inputs"]["artifact_ids"]),
            "effective_output_policy": command_centre_output_mode_to_policy(resolved["execution"]["output_mode"]),
            "selected_entries": resolved["selected_entries"].to_dict(orient="records"),
        },
        "base_hydrogen_config_path": str(base_config_path),
    }


def _create_parent_run_folder(
    *,
    resolved: dict[str, Any],
    base_config_path: Path,
    raw_payload: dict[str, Any],
    supported_options: dict[str, Any],
) -> tuple[str, Path, ProgressReporter]:
    base_config = load_hydrogen_config(base_config_path)
    parent_run_id = make_run_id(str(resolved["general"]["run_label"]))
    parent_dir = base_config.run_output_root / parent_run_id
    parent_dir.mkdir(parents=True, exist_ok=False)
    (parent_dir / "child_runs").mkdir(parents=True, exist_ok=True)
    (parent_dir / "figures").mkdir(parents=True, exist_ok=True)
    snapshot_payload = _build_command_centre_snapshot(raw_payload=raw_payload, resolved=resolved)
    (parent_dir / "command_centre_snapshot.yaml").write_text(
        yaml.safe_dump(snapshot_payload, sort_keys=False),
        encoding="utf-8",
    )
    (parent_dir / "config_resolved.yaml").write_text(
        yaml.safe_dump(
            _build_parent_config_resolved(
                raw_payload=raw_payload,
                resolved=resolved,
                base_config_path=base_config_path,
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (parent_dir / "supported_options_snapshot.yaml").write_text(
        yaml.safe_dump(supported_options, sort_keys=False),
        encoding="utf-8",
    )
    artifact_fingerprints = _collect_artifact_fingerprints(
        base_config_path=base_config_path,
        artifact_ids=list(resolved["inputs"]["artifact_ids"]),
    )
    manifest_payload = build_inputs_manifest(
        [
            base_config_path,
            (base_config.repo_root / Path(DEFAULT_COMMAND_CENTRE_CONFIG)).resolve(),
            (base_config.repo_root / Path(DEFAULT_SUPPORTED_OPTIONS)).resolve(),
            (base_config.repo_root / Path(resolved["selected_week_config_path"])).resolve(),
            base_config.models.scenario_catalog,
            *[
                Path(record["path"]) if Path(record["path"]).is_absolute() else (base_config.repo_root / record["path"]).resolve()
                for record in artifact_fingerprints
            ],
        ]
    )
    (parent_dir / "input_manifest.json").write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    progress_reporter = ProgressReporter(
        run_id=parent_run_id,
        run_folder=parent_dir,
        split=str(resolved["scope"]["split"]),
        period_mode=str(resolved["scope"]["period_mode"]),
        total_solves=_expected_solves_for_resolved_config(resolved),
        progress_paths=ProgressPaths(
            log_csv=parent_dir / "aggregate_progress_log.csv",
            current_json=parent_dir / "progress_current.json",
        ),
    )
    return parent_run_id, parent_dir, progress_reporter


def _finalise_run_folder(
    *,
    run_dir: Path,
    raw_payload: dict[str, Any],
    resolved: dict[str, Any],
    base_config_path: Path,
) -> None:
    snapshot_payload = _build_command_centre_snapshot(raw_payload=raw_payload, resolved=resolved)
    snapshot_path = run_dir / "command_centre_snapshot.yaml"
    snapshot_path.write_text(yaml.safe_dump(snapshot_payload, sort_keys=False), encoding="utf-8")

    slice_audit = pd.read_csv(run_dir / "selected_week_slice_audit.csv")
    artifact_fingerprints = _collect_artifact_fingerprints(
        base_config_path=base_config_path,
        artifact_ids=list(resolved["inputs"]["artifact_ids"]),
    )
    config = load_hydrogen_config(base_config_path)
    input_slice_fingerprint = fingerprint_payload(
        {
            "slice_fingerprints": slice_audit["slice_fingerprint"].astype(str).tolist(),
            "backend": resolved["backend"],
        }
    )
    experiment = build_experiment_fingerprint(
        config=config,
        input_slice_fingerprint=input_slice_fingerprint,
        output_policy_name=command_centre_output_mode_to_policy(resolved["execution"]["output_mode"]),
        methodological_approximations=(),
        extra={
            "command_centre_hash": resolved["command_centre_hash"],
            "backend": resolved["backend"],
            "split": resolved["scope"]["split"],
            "period_mode": resolved["scope"]["period_mode"],
            "selected_regimes": list(resolved["scope"]["selected_regimes"]),
            "artifact_ids": list(resolved["inputs"]["artifact_ids"]),
        },
    )
    run_fingerprint_payload = {
        "command_centre_hash": resolved["command_centre_hash"],
        "experiment_fingerprint": experiment.digest,
        "experiment_payload": experiment.payload,
        "artifact_fingerprints": artifact_fingerprints,
        "selected_week_policy_version": resolved["selected_week_policy_version"],
        "supported_options_version": resolved["supported_options_version"],
    }
    (run_dir / "run_fingerprint.json").write_text(
        json.dumps(run_fingerprint_payload, indent=2),
        encoding="utf-8",
    )

    run_manifest_path = run_dir / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest.update(
        {
            "method_version": resolved["general"]["method_version"],
            "supported_options_version": resolved["supported_options_version"],
            "selected_week_policy_version": resolved["selected_week_policy_version"],
            "command_centre_hash": resolved["command_centre_hash"],
            "command_centre_snapshot_path": str(snapshot_path),
            "run_fingerprint_path": str(run_dir / "run_fingerprint.json"),
            "split": resolved["scope"]["split"],
            "period_mode": resolved["scope"]["period_mode"],
            "selected_regimes": list(resolved["scope"]["selected_regimes"]),
            "model_list": list(resolved["inputs"]["artifact_ids"]),
            "output_mode": resolved["execution"]["output_mode"],
            "output_policy_name": command_centre_output_mode_to_policy(resolved["execution"]["output_mode"]),
            "cache_policy": {
                "use_cache": bool(resolved["execution"]["use_cache"]),
                "use_benchmark_cache": bool(resolved["execution"]["use_benchmark_cache"]),
            },
            "scenario_artifact_fingerprints": artifact_fingerprints,
            "supported_options_path": str(DEFAULT_SUPPORTED_OPTIONS),
            "progress_log_path": str(run_dir / "progress_log.csv"),
            "progress_current_path": str(run_dir / "progress_current.json"),
        }
    )
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    readme = (
        "# README_run\n\n"
        f"- method_version: `{resolved['general']['method_version']}`\n"
        f"- backend: `{resolved['backend']}`\n"
        f"- split: `{resolved['scope']['split']}`\n"
        f"- period_mode: `{resolved['scope']['period_mode']}`\n"
        f"- selected_regimes: `{', '.join(resolved['scope']['selected_regimes'])}`\n"
        f"- output_mode: `{resolved['execution']['output_mode']}`\n"
        f"- output_policy: `{command_centre_output_mode_to_policy(resolved['execution']['output_mode'])}`\n"
        f"- command_centre_snapshot: `{snapshot_path.name}`\n"
        f"- run_fingerprint: `run_fingerprint.json`\n"
    )
    (run_dir / "README_run.md").write_text(readme, encoding="utf-8")


def _metrics_complete_from_weekly_metrics(weekly_metrics: pd.DataFrame) -> bool:
    required = [
        "realised_adjusted_profit",
        "da_settlement_cost",
        "hydrogen_produced_kg",
        "shortfall_kg",
        "cleared_energy_mwh",
        "unused_cleared_energy_mwh",
        "average_actual_price_paid",
        "storage_end_kg",
        "benchmark_profit",
    ]
    return bool(weekly_metrics[required].notna().all(axis=1).all())


def _aggregate_child_outputs(
    *,
    parent_run_id: str,
    parent_dir: Path,
    child_rows: list[dict[str, Any]],
    raw_payload: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    child_runs_frame = pd.DataFrame(child_rows)
    child_runs_frame.to_csv(parent_dir / "child_runs.csv", index=False)

    runtime_rows: list[pd.DataFrame] = []
    metrics_rows: list[pd.DataFrame] = []
    validation_rows: list[dict[str, Any]] = []
    aggregate_progress_rows: list[pd.DataFrame] = []

    for child in child_rows:
        child_dir = Path(child["child_run_folder"])
        runtime = pd.read_csv(child_dir / "runtime_profile.csv")
        runtime["parent_run_id"] = parent_run_id
        runtime["child_run_id"] = str(child["child_run_id"])
        runtime["child_run_folder"] = str(child_dir)
        runtime["regime"] = str(child["regime_or_period_label"])
        runtime_rows.append(runtime)

        progress = pd.read_csv(child_dir / "progress_log.csv")
        progress["parent_run_id"] = parent_run_id
        progress["child_run_id"] = str(child["child_run_id"])
        progress["child_run_folder"] = str(child_dir)
        aggregate_progress_rows.append(progress)

        daily = pd.read_csv(child_dir / "daily_metrics.csv")
        daily["aggregation_level"] = "daily"
        daily["parent_run_id"] = parent_run_id
        daily["child_run_id"] = str(child["child_run_id"])
        daily["child_run_folder"] = str(child_dir)
        metrics_rows.append(daily)

        weekly = pd.read_csv(child_dir / "weekly_metrics.csv")
        weekly["aggregation_level"] = "weekly"
        weekly["parent_run_id"] = parent_run_id
        weekly["child_run_id"] = str(child["child_run_id"])
        weekly["child_run_folder"] = str(child_dir)
        metrics_rows.append(weekly)

        checks = pd.read_csv(child_dir / "validation_checks_all_runs.csv")
        validation_rows.append(
            {
                "parent_run_id": parent_run_id,
                "child_run_id": str(child["child_run_id"]),
                "child_run_folder": str(child_dir),
                "regime": str(child["regime_or_period_label"]),
                "total_checks": int(checks.shape[0]),
                "pass_checks": int(checks["status"].astype(str).eq("pass").sum()),
                "fail_checks": int(checks["status"].astype(str).eq("fail").sum()),
                "hard_fail_checks": int(
                    (
                        checks["status"].astype(str).eq("fail")
                        & checks["severity"].astype(str).eq("hard_fail")
                    ).sum()
                ),
                "status": "pass"
                if not bool(
                    (
                        checks["status"].astype(str).eq("fail")
                        & checks["severity"].astype(str).eq("hard_fail")
                    ).any()
                )
                else "fail",
            }
        )

    aggregate_runtime = pd.concat(runtime_rows, ignore_index=True) if runtime_rows else pd.DataFrame()
    if not aggregate_runtime.empty:
        group_cols = ["parent_run_id", "regime", "model_label", "stage", "accounting_bucket"]
        existing_group_cols = [column for column in group_cols if column in aggregate_runtime.columns]
        aggregate_runtime_profile = (
            aggregate_runtime.groupby(existing_group_cols, dropna=False)["wall_time_seconds"]
            .sum()
            .reset_index()
            .sort_values(existing_group_cols)
            .reset_index(drop=True)
        )
    else:
        aggregate_runtime_profile = pd.DataFrame()
    aggregate_runtime_profile.to_csv(parent_dir / "aggregate_runtime_profile.csv", index=False)

    aggregate_progress = pd.concat(aggregate_progress_rows, ignore_index=True) if aggregate_progress_rows else pd.DataFrame()
    aggregate_progress.to_csv(parent_dir / "aggregate_progress_log.csv", index=False)

    aggregate_metrics = pd.concat(metrics_rows, ignore_index=True) if metrics_rows else pd.DataFrame()
    aggregate_metrics.to_csv(parent_dir / "aggregate_metrics_summary.csv", index=False)

    validation_summary = pd.DataFrame(validation_rows)
    validation_summary.to_csv(parent_dir / "validation_summary.csv", index=False)

    limitations = []
    if "winter_proxy" in resolved["scope"]["selected_regimes"]:
        limitations.append("winter_proxy remains a proxy and is not valid for winter seasonal claims.")
    limitations.append("Current command-centre backend supports only hourly D_only hydrogen DA_only risk_neutral selected-regime runs.")
    child_folders_text = (
        "; ".join(child_runs_frame["child_run_folder"].astype(str).tolist())
        if "child_run_folder" in child_runs_frame.columns
        else ""
    )
    validation_pass = bool(validation_summary["status"].eq("pass").all()) if not validation_summary.empty else False
    readme = (
        "# README_run\n\n"
        f"- command-centre run_label: `{resolved['general']['run_label']}`\n"
        f"- split: `{resolved['scope']['split']}`\n"
        f"- period_mode: `{resolved['scope']['period_mode']}`\n"
        f"- regimes: `{', '.join(resolved['scope']['selected_regimes'])}`\n"
        f"- models/artifacts: `{', '.join(resolved['inputs']['artifact_ids'])}`\n"
        f"- output_mode: `{resolved['execution']['output_mode']}`\n"
        f"- method_version: `{resolved['general']['method_version']}`\n"
        f"- supported-options version: `{resolved['supported_options_version']}`\n"
        f"- child run folders: `{child_folders_text}`\n"
        f"- validation status: `{'pass' if validation_pass else 'fail'}`\n"
        f"- limitations: `{' | '.join(limitations)}`\n"
    )
    (parent_dir / "README_run.md").write_text(readme, encoding="utf-8")

    run_fingerprint_payload = {
        "parent_run_id": parent_run_id,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "command_centre_hash": resolved["command_centre_hash"],
        "supported_options_version": resolved["supported_options_version"],
        "selected_week_policy_version": resolved["selected_week_policy_version"],
        "child_runs": child_runs_frame["child_run_id"].astype(str).tolist() if "child_run_id" in child_runs_frame.columns else [],
    }
    (parent_dir / "run_fingerprint.json").write_text(json.dumps(run_fingerprint_payload, indent=2), encoding="utf-8")


def run_from_command_centre(
    *,
    command_centre_config_path: Path | str = DEFAULT_COMMAND_CENTRE_CONFIG,
    supported_options_path: Path | str = DEFAULT_SUPPORTED_OPTIONS,
    base_hydrogen_config_path: Path | str = Path("scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml"),
) -> list[dict[str, Any]]:
    config_path = Path(command_centre_config_path)
    supported_path = Path(supported_options_path)
    base_config_path = Path(base_hydrogen_config_path)
    raw_payload = load_command_centre_config(config_path)
    supported_options = load_supported_options(supported_path)
    resolved = validate_command_centre_config(raw_payload, supported_options=supported_options)
    if bool(resolved["governance"]["require_doctor_pass"]):
        doctor_script = Path("scripts/Data/03_Hydrogen_Test_Case/doctor_selected_week_pipeline.py")
        subprocess.run(
            [sys.executable, str(doctor_script)],
            cwd=load_hydrogen_config(base_config_path).repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    backend = resolved["backend"]
    if backend != "selected_week_hydrogen_fastpath_v1":
        raise ValueError(f"Unsupported backend dispatch: {backend}")

    output_mode = str(resolved["execution"]["output_mode"])
    selected_entries = resolved["selected_entries"]
    parent_run_id, parent_dir, parent_progress_reporter = _create_parent_run_folder(
        resolved=resolved,
        base_config_path=base_config_path,
        raw_payload=raw_payload,
        supported_options=supported_options,
    )
    results: list[dict[str, Any]] = []
    run_error: Exception | None = None
    try:
        for entry in selected_entries.to_dict(orient="records"):
            progress_metadata = {
                "split": resolved["scope"]["split"],
                "period_mode": resolved["scope"]["period_mode"],
                "gamma": float(resolved["risk"]["gamma_values"][0] if resolved["risk"]["gamma_values"] else 0.0),
            }
            warning_text = ""
            if str(entry.get("allowed_use_restriction", "")).strip() not in {"", "none"}:
                warning_text = str(entry.get("allowed_use_restriction", ""))
            try:
                child_run_slug = f"cc_{resolved['scope']['split']}_{entry['label']}"
                result = run_selected_week_risk_neutral_smoke(
                    config=base_config_path,
                    week_id=str(entry["label"]),
                    artifact_ids=list(resolved["inputs"]["artifact_ids"]),
                    run_slug=str(child_run_slug),
                    risk_mode=str(resolved["risk"]["risk_mode"]),
                    include_price_insensitive_benchmark=True,
                    output_root=parent_dir / "child_runs",
                    selected_weeks_yaml_path=resolved["selected_week_config_path"],
                    selected_week_split=str(resolved["scope"]["split"]),
                    output_mode=output_mode,
                    progress_reporting=bool(resolved["execution"]["progress_reporting"]),
                    progress_metadata=progress_metadata,
                    external_progress_reporter=parent_progress_reporter,
                )
            except Exception as exc:  # noqa: BLE001
                parent_progress_reporter.mark_failed(
                    regime=str(entry["label"]),
                    model="",
                    delivery_day="",
                    warning=str(exc),
                )
                run_error = exc
                break
            _finalise_run_folder(
                run_dir=result.run_dir,
                raw_payload=raw_payload,
                resolved=resolved,
                base_config_path=base_config_path,
            )
            runtime_profile = pd.read_csv(result.run_dir / "runtime_profile.csv")
            total_wall = float(runtime_profile.loc[runtime_profile["stage"].eq("total_wall_seconds"), "wall_time_seconds"].iloc[0])
            weekly_metrics = pd.read_csv(result.run_dir / "weekly_metrics.csv")
            metrics_complete = _metrics_complete_from_weekly_metrics(weekly_metrics)
            results.append(
                {
                    "parent_run_id": str(parent_run_id),
                    "child_run_id": str(result.run_dir.name),
                    "child_run_folder": str(result.run_dir),
                    "split": str(resolved["scope"]["split"]),
                    "period_mode": str(resolved["scope"]["period_mode"]),
                    "regime_or_period_label": str(entry["label"]),
                    "model_list": json.dumps(list(resolved["inputs"]["artifact_ids"])),
                    "gamma_values": json.dumps(list(resolved["risk"]["gamma_values"])),
                    "status": "pass",
                    "runtime_seconds": float(total_wall),
                    "metrics_complete": bool(metrics_complete),
                    "warnings": warning_text,
                    "week_id": str(result.selected_week["week_id"]),
                    "week_label": str(result.selected_week["week_label"]),
                    "run_dir": str(result.run_dir),
                }
            )
    finally:
        _aggregate_child_outputs(
            parent_run_id=parent_run_id,
            parent_dir=parent_dir,
            child_rows=results,
            raw_payload=raw_payload,
            resolved=resolved,
        )
    if run_error is not None:
        raise run_error
    return {
        "parent_run_id": str(parent_run_id),
        "parent_run_dir": str(parent_dir),
        "child_runs": results,
    }
