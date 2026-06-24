from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from steel.wag_diagnostic import assess_wag_readiness, readiness_to_dict, run_c0_wag_diagnostic, run_c1_component_energy_diagnostic
    from steel.wag_diagnostic_inputs import (
        DEFAULT_SELECTED_WAG_INPUT_PATH,
        DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
        load_fixed_activity_profile,
        load_selected_wag_inputs,
        load_wag_demand_coefficients,
    )
else:
    from .wag_diagnostic import assess_wag_readiness, readiness_to_dict, run_c0_wag_diagnostic, run_c1_component_energy_diagnostic
    from .wag_diagnostic_inputs import (
        DEFAULT_SELECTED_WAG_INPUT_PATH,
        DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
        load_fixed_activity_profile,
        load_selected_wag_inputs,
        load_wag_demand_coefficients,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and gate the fixed-profile S3.0b WAG diagnostic scaffold.")
    parser.add_argument("--validate-inputs-only", action="store_true", help="Validate governed inputs without running a diagnostic.")
    parser.add_argument("--profile-path", type=Path, default=None, help="Governed fixed activity-profile CSV path.")
    parser.add_argument("--configuration-id", type=str, default=None, help="Configuration ID for a guarded diagnostic run.")
    parser.add_argument(
        "--selected-input-path",
        type=Path,
        default=DEFAULT_SELECTED_WAG_INPUT_PATH,
        help="Governed provisional selected WAG input CSV path.",
    )
    parser.add_argument(
        "--demand-coefficient-path",
        type=Path,
        default=DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
        help="Governed provisional WAG demand coefficient CSV path.",
    )
    parser.add_argument("--output-path", type=Path, default=None, help="Optional explicit JSON readiness output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    selected_inputs = load_selected_wag_inputs(args.selected_input_path)
    demand_coefficients = load_wag_demand_coefficients(args.demand_coefficient_path)
    profile_rows = load_fixed_activity_profile(args.profile_path) if args.profile_path else None
    readiness = assess_wag_readiness(selected_inputs, profile_rows, demand_coefficients)
    payload = {
        "selected_input_rows_loaded": len(selected_inputs),
        "demand_coefficient_rows_loaded": len(demand_coefficients),
        "profile_rows_loaded": len(profile_rows or ()),
        "readiness": readiness_to_dict(readiness),
    }
    if not args.validate_inputs_only and args.configuration_id:
        if args.configuration_id not in {"C0_current_BF_BOF_reference", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"}:
            payload["diagnostic_error"] = "Unsupported steel WAG diagnostic configuration."
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        if profile_rows is None:
            payload["diagnostic_error"] = "--profile-path is required for a guarded diagnostic run."
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        if args.configuration_id == "C0_current_BF_BOF_reference" and not readiness.runtime_ready:
            payload["diagnostic_error"] = "Runtime readiness is false; central diagnostic not run."
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        if args.configuration_id == "C0_current_BF_BOF_reference":
            payload["diagnostic"] = run_c0_wag_diagnostic(
                selected_inputs=selected_inputs,
                demand_coefficients=demand_coefficients,
                profile_rows=profile_rows,
            )
        else:
            payload["diagnostic"] = run_c1_component_energy_diagnostic(
                selected_inputs=selected_inputs,
                profile_rows=profile_rows,
            )
    summary = json.dumps(payload, indent=2, sort_keys=True)
    print(summary)
    if args.output_path:
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(summary + "\n", encoding="utf-8")
    if args.validate_inputs_only or args.configuration_id:
        return 0
    return 0 if readiness.runtime_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
