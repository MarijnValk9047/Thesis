from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from hydrogen.selected_week_policy import (  # noqa: E402
    COMMON_SUPPORT_DAYS_PATH,
    COMMON_SUPPORT_REGISTRY_PATH,
    COMMON_SUPPORT_SELECTED_WEEKS_PATH,
    DEPRECATED_SELECTED_WEEKS_PATH,
    OFFICIAL_TEST_SELECTED_WEEKS_PATH,
    OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH,
    TEST_SELECTED_REGIME_LABELS,
    VALIDATION_SELECTED_REGIME_LABELS,
    load_selected_week_entries,
)


@dataclass(frozen=True)
class DoctorCheck:
    check_name: str
    status: str
    details: str


def _result(check_name: str, status: str, details: str) -> DoctorCheck:
    return DoctorCheck(check_name=check_name, status=status, details=details)


def _runner_source_uses_preflight(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    return "run_selected_week_input_preflight(" in content


def main() -> int:
    checks: list[DoctorCheck] = []

    validation_entries = load_selected_week_entries(
        OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH,
        expected_split="validation",
    )
    test_entries = load_selected_week_entries(
        OFFICIAL_TEST_SELECTED_WEEKS_PATH,
        expected_split="test",
    )
    registry = pd.read_csv(COMMON_SUPPORT_REGISTRY_PATH)
    support_days = pd.read_csv(COMMON_SUPPORT_DAYS_PATH)
    support_days["delivery_date"] = pd.to_datetime(support_days["delivery_date"], errors="raise")
    deprecated_payload = DEPRECATED_SELECTED_WEEKS_PATH.read_text(encoding="utf-8")

    checks.append(
        _result(
            "selected_week_config_split_present",
            "pass" if OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH.exists() and OFFICIAL_TEST_SELECTED_WEEKS_PATH.exists() else "fail",
            f"validation={OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH.exists()}; test={OFFICIAL_TEST_SELECTED_WEEKS_PATH.exists()}",
        )
    )
    checks.append(
        _result(
            "validation_regime_labels_exact",
            "pass"
            if validation_entries["label"].astype(str).tolist() == list(VALIDATION_SELECTED_REGIME_LABELS)
            else "fail",
            f"labels={validation_entries['label'].astype(str).tolist()}",
        )
    )
    checks.append(
        _result(
            "test_regime_labels_exact",
            "pass" if test_entries["label"].astype(str).tolist() == list(TEST_SELECTED_REGIME_LABELS) else "fail",
            f"labels={test_entries['label'].astype(str).tolist()}",
        )
    )
    checks.append(
        _result(
            "deprecated_selected_weeks_file_remains_deprecated",
            "pass" if "status: deprecated" in deprecated_payload else "fail",
            f"path={DEPRECATED_SELECTED_WEEKS_PATH}",
        )
    )

    selected_registry_rows = registry.loc[
        registry["week_label"].astype(str).isin(validation_entries["week_label"].astype(str).tolist() + test_entries["week_label"].astype(str).tolist())
    ].copy()
    strict_fs3_ok = (
        selected_registry_rows["complete_for_lear_strict"].astype(bool).all()
        and selected_registry_rows["complete_for_lear_fs3"].astype(bool).all()
    )
    checks.append(
        _result(
            "lear_strict_and_lear_fs3_common_support_for_selected_weeks",
            "pass" if strict_fs3_ok else "fail",
            "all selected registry rows are complete for LEAR Strict and LEAR FS3",
        )
    )

    support_status_ok = (
        selected_registry_rows["support_status"].astype(str).eq("common_complete_support_selected").all()
        and selected_registry_rows["complete_actual_prices"].astype(bool).all()
    )
    checks.append(
        _result(
            "selected_registry_rows_complete",
            "pass" if support_status_ok else "fail",
            f"selected_row_count={int(selected_registry_rows.shape[0])}",
        )
    )

    probability_checks_path = SCRIPT_ROOT / "docs" / "selected_week_support_checks.csv"
    probability_checks = pd.read_csv(probability_checks_path)
    probability_failures = probability_checks.loc[
        probability_checks["check_name"].astype(str).str.contains("probabilities_sum_to_one_per_origin|scenario_count_per_origin_is_75")
        & probability_checks["status"].astype(str).ne("pass")
    ].copy()
    checks.append(
        _result(
            "selected_week_probability_checks_pass",
            "pass" if probability_failures.empty else "fail",
            f"failing_rows={int(probability_failures.shape[0])}",
        )
    )

    support_rows: list[pd.DataFrame] = []
    for entry in pd.concat([validation_entries, test_entries], ignore_index=True).to_dict(orient="records"):
        rows = support_days.loc[
            (support_days["delivery_date"] >= pd.Timestamp(entry["start_local_date"]))
            & (support_days["delivery_date"] <= pd.Timestamp(entry["end_local_date"]))
        ].copy()
        rows["regime_label"] = str(entry["regime_label"])
        rows["week_label"] = str(entry["week_label"])
        support_rows.append(rows)
    selected_support = pd.concat(support_rows, ignore_index=True)
    completeness_ok = (
        selected_support["complete_actual_prices"].astype(bool).all()
        and selected_support["common_complete_support"].astype(bool).all()
        and selected_support["n_hours_actual"].astype(int).eq(24).all()
    )
    checks.append(
        _result(
            "actual_price_completeness_for_selected_days",
            "pass" if completeness_ok else "fail",
            f"selected_day_count={int(selected_support.shape[0])}",
        )
    )

    runner_checks = [
        (
            "phase_c_runner_defaults_official_validation_split",
            SCRIPT_ROOT / "hydrogen" / "selected_week_smoke.py",
            "DEFAULT_SELECTED_WEEKS_YAML = OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH",
        ),
        (
            "phase_d_runner_preflight_present",
            SCRIPT_ROOT / "hydrogen" / "validation_cvar_sweep.py",
            "run_selected_week_input_preflight(",
        ),
        (
            "phase_d2_runner_preflight_present",
            SCRIPT_ROOT / "hydrogen" / "validation_cvar_expanded_sweep.py",
            "run_selected_week_input_preflight(",
        ),
        (
            "phase_d3_runner_preflight_present",
            SCRIPT_ROOT / "hydrogen" / "validation_cvar_fine_gamma_diagnostic.py",
            "run_selected_week_input_preflight(",
        ),
        (
            "phase_e2_runner_preflight_present",
            SCRIPT_ROOT / "hydrogen" / "selected_test_weeks_cvar_policy_eval.py",
            "run_selected_week_input_preflight(",
        ),
    ]
    for check_name, path, token in runner_checks:
        content = path.read_text(encoding="utf-8")
        checks.append(
            _result(
                check_name,
                "pass" if token in content else "fail",
                f"path={path.name}",
            )
        )

    checks.append(
        _result(
            "official_runners_do_not_default_to_deprecated_or_common_support_yaml",
            "pass"
            if all(
                bad_token not in (
                    (SCRIPT_ROOT / "hydrogen" / name).read_text(encoding="utf-8")
                )
                for name in [
                    "validation_cvar_sweep.py",
                    "validation_cvar_expanded_sweep.py",
                    "validation_cvar_fine_gamma_diagnostic.py",
                    "selected_test_weeks_cvar_policy_eval.py",
                ]
                for bad_token in (
                    "selected_weeks_common_support.yaml",
                    "selected_weeks.yaml",
                )
            )
            else "fail",
            "checked official validation/test runner source defaults",
        )
    )

    checks.append(
        _result(
            "phase_c_cli_requires_or_defaults_safe_split",
            "pass"
            if "--selected-week-split"
            in (SCRIPT_ROOT / "run_selected_week_risk_neutral_smoke.py").read_text(encoding="utf-8")
            else "fail",
            "checked generic smoke CLI for explicit split handling",
        )
    )

    validation_winter_row = validation_entries.loc[validation_entries["label"].astype(str).eq("winter_proxy")].iloc[0]
    checks.append(
        _result(
            "validation_winter_proxy_is_explicitly_restricted",
            "pass"
            if (
                str(validation_winter_row["week_label"]) == "validation_winter_proxy_week"
                and not bool(validation_winter_row["seasonal_claims_valid"])
                and str(validation_winter_row["proxy_for_regime_label"]) == "typical_winter"
                and str(validation_winter_row["allowed_use_restriction"])
                == "runtime_debug_common_support_only_unless_justified"
            )
            else "fail",
            (
                f"week_label={validation_winter_row['week_label']}; "
                f"proxy_for={validation_winter_row['proxy_for_regime_label']}; "
                f"seasonal_claims_valid={validation_winter_row['seasonal_claims_valid']}"
            ),
        )
    )

    validation_high_price_row = validation_entries.loc[validation_entries["label"].astype(str).eq("high_price")].iloc[0]
    checks.append(
        _result(
            "validation_high_price_week_exists",
            "pass" if bool(validation_high_price_row["dedicated_regime_candidate"]) else "warn",
            f"week_label={validation_high_price_row['week_label']}; selection_status={validation_high_price_row['selection_status']}",
        )
    )

    overall_status = "pass"
    if any(check.status == "fail" for check in checks):
        overall_status = "fail"
    elif any(check.status == "warn" for check in checks):
        overall_status = "warn"

    payload = {
        "overall_status": overall_status,
        "checks": [asdict(check) for check in checks],
        "official_paths": {
            "validation": str(OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH),
            "test": str(OFFICIAL_TEST_SELECTED_WEEKS_PATH),
            "deprecated": str(DEPRECATED_SELECTED_WEEKS_PATH),
            "common_support": str(COMMON_SUPPORT_SELECTED_WEEKS_PATH),
        },
    }
    print(json.dumps(payload, indent=2))
    return 1 if overall_status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
