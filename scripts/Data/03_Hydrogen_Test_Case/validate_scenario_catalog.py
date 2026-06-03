from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs


def _artifact_row(spec: Any, status: str, message: str, findings: list[str] | None = None) -> dict[str, Any]:
    return {
        "artifact_key": spec.artifact_key,
        "validation_mode": spec.validation_mode,
        "path": str(spec.path),
        "status": status,
        "message": message,
        "findings": findings or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate scenario catalog inputs before optimisation runs.")
    parser.add_argument(
        "--config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
        help="Path to hydrogen config YAML.",
    )
    parser.add_argument(
        "--artifacts",
        nargs="*",
        default=None,
        help="Optional artifact keys to validate. Defaults to config models.include (or catalog default).",
    )
    parser.add_argument(
        "--strict-smoke",
        action="store_true",
        help="Return nonzero if smoke-test warnings are present.",
    )
    args = parser.parse_args()

    config = load_hydrogen_config(args.config)
    if args.artifacts:
        config = replace(
            config,
            models=replace(config.models, include=tuple(args.artifacts)),
        )

    specs = resolve_artifact_specs(config)
    results: list[dict[str, Any]] = []
    hard_fail = False
    smoke_warn = False

    for spec in specs:
        try:
            _, findings = load_scenarios_for_artifact(spec, config=config)
        except Exception as exc:  # noqa: BLE001
            hard_fail = True
            results.append(_artifact_row(spec, "hard_fail", f"{type(exc).__name__}: {exc}"))
            continue

        smoke_messages = [item for item in findings if item.startswith("SMOKE_WARNING:")]
        info_messages = [item for item in findings if not item.startswith("SMOKE_WARNING:")]
        if smoke_messages:
            smoke_warn = True
            results.append(_artifact_row(spec, "smoke_warning", "Artifact loaded with smoke-test warnings.", smoke_messages + info_messages))
        else:
            results.append(_artifact_row(spec, "pass", "Artifact passed catalog validation.", info_messages))

    print(json.dumps({"results": results}, indent=2))

    if hard_fail:
        return 2
    if smoke_warn and args.strict_smoke:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
