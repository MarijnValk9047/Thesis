from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

STEEL_ROOT = Path(__file__).resolve().parent
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_c0_athanasiadis_sale_sensitivity import (
    DEFAULT_CONFIG_PATH,
    POSTHOC_REAUDIT_EXECUTION_MODE,
    SUPPORTED_EXECUTION_MODES,
    run_posthoc_full_matrix_guardrail_reaudit,
    run_sale_sensitivity,
)
from steel.validation_tolerance_policy import (
    POLICY_FINGERPRINT as VALIDATION_TOLERANCE_POLICY_FINGERPRINT,
    POLICY_ID as VALIDATION_TOLERANCE_POLICY_ID,
    POLICY_VERSION as VALIDATION_TOLERANCE_POLICY_VERSION,
)


VALIDATION_TOLERANCE_POLICY_REQUIRED = {
    "policy_id": VALIDATION_TOLERANCE_POLICY_ID,
    "policy_version": VALIDATION_TOLERANCE_POLICY_VERSION,
    "policy_fingerprint_sha256": VALIDATION_TOLERANCE_POLICY_FINGERPRINT,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded C0 Athanasiadis-style electricity-sale sensitivity."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument(
        "--forecast-run-root", default=os.environ.get("STEEL_DA_FORECAST_RUN_ROOT")
    )
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--diagnostic-case-id", default=None)
    parser.add_argument(
        "--execution-mode",
        choices=(*SUPPORTED_EXECUTION_MODES, POSTHOC_REAUDIT_EXECUTION_MODE),
        default="aggregate_only",
    )
    parser.add_argument("--full-matrix-authorization", default=None)
    parser.add_argument(
        "--full-matrix-reviewer-decision",
        choices=("PASS", "FAIL"),
        default=None,
    )
    parser.add_argument("--posthoc-source-attempt", default=None)
    parser.add_argument("--posthoc-reaudit-authorization", default=None)
    parser.add_argument(
        "--posthoc-reaudit-reviewer-decision",
        choices=("PASS", "FAIL"),
        default=None,
    )
    args = parser.parse_args()
    if args.execution_mode == POSTHOC_REAUDIT_EXECUTION_MODE:
        if not args.posthoc_source_attempt:
            parser.error("--posthoc-source-attempt is required for posthoc re-audit")
        if not args.posthoc_reaudit_authorization:
            parser.error(
                "--posthoc-reaudit-authorization is required for posthoc re-audit"
            )
        if args.posthoc_reaudit_reviewer_decision is None:
            parser.error(
                "--posthoc-reaudit-reviewer-decision is required for posthoc re-audit"
            )
        if any(
            (
                args.aggregate_only,
                args.diagnostic_case_id is not None,
                args.scratch_root is not None,
                args.full_matrix_authorization is not None,
                args.full_matrix_reviewer_decision is not None,
            )
        ):
            parser.error("solve-mode arguments are forbidden for posthoc re-audit")
        summary = run_posthoc_full_matrix_guardrail_reaudit(
            args.config,
            source_attempt=args.posthoc_source_attempt,
            posthoc_reaudit_authorization=args.posthoc_reaudit_authorization,
            posthoc_reaudit_reviewer_decision=(
                args.posthoc_reaudit_reviewer_decision
            ),
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["status"] == "pass" else 1
    if not args.forecast_run_root:
        parser.error("--forecast-run-root or STEEL_DA_FORECAST_RUN_ROOT is required")
    summary = run_sale_sensitivity(
        args.config,
        forecast_run_root=args.forecast_run_root,
        scratch_root=args.scratch_root,
        aggregate_only=args.aggregate_only,
        diagnostic_case_id=args.diagnostic_case_id,
        execution_mode=args.execution_mode,
        full_matrix_authorization=args.full_matrix_authorization,
        full_matrix_reviewer_decision=args.full_matrix_reviewer_decision,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] in {"pass", "diagnostic_pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
