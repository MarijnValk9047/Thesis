from __future__ import annotations

import argparse
import json
from pathlib import Path

from hydrogen.command_centre import (
    DEFAULT_COMMAND_CENTRE_CONFIG,
    DEFAULT_SUPPORTED_OPTIONS,
    run_from_command_centre,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optimisation from the project-wide command-centre config.",
    )
    parser.add_argument(
        "--command-centre-config",
        default=str(DEFAULT_COMMAND_CENTRE_CONFIG),
        help="Path to optimisation_command_centre.yaml.",
    )
    parser.add_argument(
        "--supported-options",
        default=str(DEFAULT_SUPPORTED_OPTIONS),
        help="Path to optimisation_supported_options.yaml.",
    )
    parser.add_argument(
        "--base-hydrogen-config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
        help="Base hydrogen config used by the currently implemented selected-week hydrogen backend.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    results = run_from_command_centre(
        command_centre_config_path=Path(args.command_centre_config),
        supported_options_path=Path(args.supported_options),
        base_hydrogen_config_path=Path(args.base_hydrogen_config),
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
