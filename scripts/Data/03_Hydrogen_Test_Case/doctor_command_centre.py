from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hydrogen.command_centre import (  # noqa: E402
    DEFAULT_COMMAND_CENTRE_CONFIG,
    DEFAULT_SUPPORTED_OPTIONS,
    load_command_centre_config,
    load_supported_options,
    validate_command_centre_config,
)


def main() -> None:
    config_path = ROOT / DEFAULT_COMMAND_CENTRE_CONFIG
    supported_path = ROOT / DEFAULT_SUPPORTED_OPTIONS
    checks: list[dict[str, str]] = []
    try:
        supported = load_supported_options(supported_path)
        checks.append(
            {
                "check_name": "supported_options_registry_present",
                "status": "pass",
                "details": str(supported_path),
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "check_name": "supported_options_registry_present",
                "status": "fail",
                "details": str(exc),
            }
        )
        print(json.dumps({"overall_status": "fail", "checks": checks}, indent=2))
        raise SystemExit(1)

    try:
        payload = load_command_centre_config(config_path)
        checks.append(
            {
                "check_name": "command_centre_config_present",
                "status": "pass",
                "details": str(config_path),
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "check_name": "command_centre_config_present",
                "status": "fail",
                "details": str(exc),
            }
        )
        print(json.dumps({"overall_status": "fail", "checks": checks}, indent=2))
        raise SystemExit(1)

    try:
        resolved = validate_command_centre_config(payload, supported_options=supported)
        checks.append(
            {
                "check_name": "command_centre_config_validates",
                "status": "pass",
                "details": (
                    f"backend={resolved['backend']}; split={resolved['scope']['split']}; "
                    f"period_mode={resolved['scope']['period_mode']}; "
                    f"selected_regimes={resolved['scope']['selected_regimes']}"
                ),
            }
        )
        checks.append(
            {
                "check_name": "deprecated_selected_weeks_not_used",
                "status": "pass",
                "details": str(resolved["selected_week_config_path"]),
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "check_name": "command_centre_config_validates",
                "status": "fail",
                "details": str(exc),
            }
        )
        print(json.dumps({"overall_status": "fail", "checks": checks}, indent=2))
        raise SystemExit(1)

    print(
        json.dumps(
            {
                "overall_status": "pass",
                "checks": checks,
                "supported_options_version": str(supported.get("registry_version", "")),
                "config_path": str(config_path),
                "supported_options_path": str(supported_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
