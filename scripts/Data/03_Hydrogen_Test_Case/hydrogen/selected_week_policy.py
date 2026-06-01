from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .optimisation.input_resolver import InputSliceRequest, resolve_input_slice
from .optimisation.output_policy import get_output_policy
from .optimisation.runtime_profiling import RuntimeProfiler
from .plant_parameters import HydrogenConfig, load_hydrogen_config


OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH = Path(
    "scripts/Data/03_Hydrogen_Test_Case/configs/selected_validation_weeks.yaml"
)
OFFICIAL_TEST_SELECTED_WEEKS_PATH = Path(
    "scripts/Data/03_Hydrogen_Test_Case/configs/selected_test_weeks.yaml"
)
DEPRECATED_SELECTED_WEEKS_PATH = Path(
    "scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks.yaml"
)
COMMON_SUPPORT_SELECTED_WEEKS_PATH = Path(
    "scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks_common_support.yaml"
)
COMMON_SUPPORT_REGISTRY_PATH = Path(
    "scripts/Data/03_Hydrogen_Test_Case/docs/selected_week_registry_common_support.csv"
)
COMMON_SUPPORT_DAYS_PATH = Path(
    "scripts/Data/03_Hydrogen_Test_Case/docs/common_support_three_model_hourly.csv"
)

INTENDED_REGIME_LABELS = (
    "typical_summer",
    "typical_winter",
    "high_volatility",
    "high_price",
)
OFFICIAL_REGIME_LABELS = INTENDED_REGIME_LABELS
VALIDATION_SELECTED_REGIME_LABELS = (
    "typical_summer",
    "winter_proxy",
    "high_volatility",
    "high_price",
)
TEST_SELECTED_REGIME_LABELS = INTENDED_REGIME_LABELS
KNOWN_REGIME_LABELS = tuple(
    dict.fromkeys(
        list(INTENDED_REGIME_LABELS)
        + list(VALIDATION_SELECTED_REGIME_LABELS)
        + list(TEST_SELECTED_REGIME_LABELS)
    )
)
OFFICIAL_VALIDATION_WEEK_LABELS = tuple(
    f"validation_{regime}_week" for regime in VALIDATION_SELECTED_REGIME_LABELS
)
OFFICIAL_TEST_WEEK_LABELS = tuple(
    f"test_{regime}_week" for regime in TEST_SELECTED_REGIME_LABELS
)

OFFICIAL_LEAR_STRICT_ARTIFACT_ID = (
    "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support"
)
OFFICIAL_LEAR_FS3_ARTIFACT_ID = (
    "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate"
)
OFFICIAL_XGBOOST_FS3_ARTIFACT_ID = (
    "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate"
)


@dataclass(frozen=True)
class SelectedWeekPreflightResult:
    selected_entries: pd.DataFrame
    registry_rows: pd.DataFrame
    audit_rows: pd.DataFrame
    runtime_profile: pd.DataFrame
    output_policy_name: str
    cache_root: Path | None


def _normalize_path(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    return Path(path).resolve()


def official_selected_weeks_path(expected_split: str) -> Path:
    normalized = str(expected_split).strip().lower()
    if normalized == "validation":
        return OFFICIAL_VALIDATION_SELECTED_WEEKS_PATH
    if normalized == "test":
        return OFFICIAL_TEST_SELECTED_WEEKS_PATH
    raise ValueError(f"Unsupported selected-week split: {expected_split!r}")


def allowed_regime_labels(expected_split: str) -> tuple[str, ...]:
    normalized = str(expected_split).strip().lower()
    if normalized == "validation":
        return VALIDATION_SELECTED_REGIME_LABELS
    if normalized == "test":
        return TEST_SELECTED_REGIME_LABELS
    raise ValueError(f"Unsupported selected-week split: {expected_split!r}")


def expected_methodological_use(expected_split: str) -> str:
    normalized = str(expected_split).strip().lower()
    if normalized == "validation":
        return "cvar_selection"
    if normalized == "test":
        return "diagnostic_reporting"
    raise ValueError(f"Unsupported selected-week split: {expected_split!r}")


def ensure_official_selected_weeks_path(
    path: Path | str | None,
    *,
    expected_split: str,
) -> Path:
    if path is None:
        raise ValueError(f"Official {expected_split} selected-week runs require an explicit split config path.")
    resolved = _normalize_path(path)
    assert resolved is not None
    deprecated = _normalize_path(DEPRECATED_SELECTED_WEEKS_PATH)
    common_support = _normalize_path(COMMON_SUPPORT_SELECTED_WEEKS_PATH)
    official = _normalize_path(official_selected_weeks_path(expected_split))
    if resolved == deprecated:
        raise ValueError(
            "Official selected-week runs must not use deprecated selected_weeks.yaml. "
            f"Use {official_selected_weeks_path(expected_split)} instead."
        )
    if resolved == common_support:
        raise ValueError(
            "Official selected-week runs must not use audit-only selected_weeks_common_support.yaml. "
            f"Use {official_selected_weeks_path(expected_split)} instead."
        )
    return Path(path)


def _load_yaml_payload(path: Path | str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Selected-week YAML must contain a mapping: {path}")
    return payload


def _derive_regime_label(label: str, week_label: str) -> str:
    if label in KNOWN_REGIME_LABELS:
        return str(label)
    for prefix in ("validation_", "test_"):
        if week_label.startswith(prefix) and week_label.endswith("_week"):
            candidate = week_label[len(prefix) : -len("_week")]
            if candidate in KNOWN_REGIME_LABELS:
                return candidate
    if week_label in KNOWN_REGIME_LABELS:
        return week_label
    return str(label)


def load_selected_week_entries(
    path: Path | str,
    *,
    expected_split: str | None = None,
) -> pd.DataFrame:
    payload = _load_yaml_payload(path)
    rows = payload.get("selected_weeks", [])
    frame = pd.DataFrame(rows)
    required = {"label", "start_local_date", "end_local_date"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Selected-week YAML is missing required fields {sorted(missing)}: {path}")
    split_value = str(payload.get("split", expected_split or "")).strip().lower()
    if expected_split is not None and split_value and split_value != str(expected_split).strip().lower():
        raise ValueError(
            f"Selected-week YAML split mismatch for {path}: expected {expected_split!r}, got {split_value!r}."
        )
    frame["period_type"] = split_value if split_value else str(expected_split or "")
    frame["label"] = frame["label"].astype(str)
    if "week_label" not in frame.columns:
        frame["week_label"] = frame["label"]
    frame["week_label"] = frame["week_label"].astype(str)
    if "week_id" not in frame.columns:
        frame["week_id"] = ""
    frame["week_id"] = frame["week_id"].astype(str)
    if "regime_label" not in frame.columns:
        frame["regime_label"] = [
            _derive_regime_label(str(label), str(week_label))
            for label, week_label in zip(frame["label"], frame["week_label"], strict=False)
        ]
    frame["regime_label"] = frame["regime_label"].astype(str)
    frame["start_local_date"] = pd.to_datetime(frame["start_local_date"], errors="raise").dt.strftime("%Y-%m-%d")
    frame["end_local_date"] = pd.to_datetime(frame["end_local_date"], errors="raise").dt.strftime("%Y-%m-%d")
    if "selection_status" not in frame.columns:
        frame["selection_status"] = "selected_dedicated"
    if "dedicated_regime_candidate" not in frame.columns:
        frame["dedicated_regime_candidate"] = True
    frame["dedicated_regime_candidate"] = frame["dedicated_regime_candidate"].fillna(False).astype(bool)
    if "selection_reason" not in frame.columns:
        frame["selection_reason"] = ""
    if "fallback_reason" not in frame.columns:
        frame["fallback_reason"] = ""
    if "proxy_for_regime_label" not in frame.columns:
        frame["proxy_for_regime_label"] = ""
    if "seasonal_claims_valid" not in frame.columns:
        frame["seasonal_claims_valid"] = True
    frame["seasonal_claims_valid"] = frame["seasonal_claims_valid"].fillna(True).astype(bool)
    if "allowed_use_restriction" not in frame.columns:
        frame["allowed_use_restriction"] = ""
    return frame.reset_index(drop=True)


def resolve_selected_entries(
    path: Path | str,
    *,
    requested_identifiers: list[str] | tuple[str, ...],
    expected_split: str,
) -> pd.DataFrame:
    official_path = ensure_official_selected_weeks_path(path, expected_split=expected_split)
    entries = load_selected_week_entries(official_path, expected_split=expected_split)
    selected_rows: list[pd.Series] = []
    for requested in [str(value) for value in requested_identifiers]:
        match = entries.loc[
            entries["label"].astype(str).eq(requested)
            | entries["week_label"].astype(str).eq(requested)
            | entries["week_id"].astype(str).eq(requested)
            | entries["regime_label"].astype(str).eq(requested)
        ].copy()
        if match.empty:
            raise ValueError(
                f"Selected-week identifier {requested!r} not found in official {expected_split} config {official_path}."
            )
        if int(match.shape[0]) != 1:
            raise ValueError(
                f"Selected-week identifier {requested!r} is ambiguous in {official_path}; "
                f"matches={match[['label', 'week_label', 'week_id']].to_dict(orient='records')}"
            )
        selected_rows.append(match.iloc[0].copy())
    resolved = pd.DataFrame(selected_rows).reset_index(drop=True)
    duplicate_regimes = resolved["regime_label"].astype(str).duplicated(keep=False)
    if bool(duplicate_regimes.any()):
        raise ValueError(
            "Official selected-week request contains duplicate regime labels: "
            f"{resolved.loc[duplicate_regimes, 'regime_label'].astype(str).tolist()}"
        )
    return resolved


def resolve_registry_rows(
    *,
    registry_path: Path | str,
    selected_weeks_yaml_path: Path | str,
    requested_identifiers: list[str] | tuple[str, ...],
    expected_split: str,
) -> pd.DataFrame:
    entries = resolve_selected_entries(
        selected_weeks_yaml_path,
        requested_identifiers=requested_identifiers,
        expected_split=expected_split,
    )
    registry = pd.read_csv(registry_path)
    rows: list[pd.Series] = []
    for entry in entries.to_dict(orient="records"):
        match = registry.loc[
            registry["period_type"].astype(str).eq(expected_split)
            & (
                registry["week_id"].astype(str).eq(str(entry["week_id"]))
                | registry["week_label"].astype(str).eq(str(entry["week_label"]))
            )
        ].copy()
        if int(match.shape[0]) != 1:
            raise ValueError(
                f"Expected exactly one registry row for {entry['label']!r} in {registry_path}, "
                f"found {int(match.shape[0])}."
            )
        row = match.iloc[0].copy()
        row["requested_identifier"] = str(entry["label"])
        row["regime_label"] = str(entry["regime_label"])
        row["selection_status"] = str(entry.get("selection_status", "selected_dedicated"))
        row["dedicated_regime_candidate"] = bool(entry.get("dedicated_regime_candidate", True))
        row["fallback_reason"] = str(entry.get("fallback_reason", ""))
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)


def run_selected_week_input_preflight(
    *,
    config: HydrogenConfig | str | Path,
    artifact_ids: list[str] | tuple[str, ...],
    requested_identifiers: list[str] | tuple[str, ...],
    selected_weeks_yaml_path: Path | str,
    expected_split: str,
    cache_root: Path | None = None,
    output_policy_name: str = "minimal",
) -> SelectedWeekPreflightResult:
    resolved_config = config if isinstance(config, HydrogenConfig) else load_hydrogen_config(config)
    selected_entries = resolve_selected_entries(
        selected_weeks_yaml_path,
        requested_identifiers=requested_identifiers,
        expected_split=expected_split,
    )
    registry_rows = resolve_registry_rows(
        registry_path=COMMON_SUPPORT_REGISTRY_PATH,
        selected_weeks_yaml_path=selected_weeks_yaml_path,
        requested_identifiers=requested_identifiers,
        expected_split=expected_split,
    )
    policy = get_output_policy(output_policy_name)
    profiler = RuntimeProfiler()
    audit_rows: list[dict[str, Any]] = []
    for artifact_id in [str(value) for value in artifact_ids]:
        for entry in selected_entries.to_dict(orient="records"):
            with profiler.track(
                "load",
                artifact_id=artifact_id,
                expected_split=expected_split,
                regime_label=str(entry["regime_label"]),
                requested_identifier=str(entry["label"]),
            ):
                resolved_slice = resolve_input_slice(
                    resolved_config,
                    request=InputSliceRequest(
                        artifact_id=artifact_id,
                        start_local_date=str(entry["start_local_date"]),
                        end_local_date=str(entry["end_local_date"]),
                        period_mode="selected_weeks",
                        period_labels=(str(entry["label"]),),
                        dataset_split=expected_split,
                    ),
                    output_policy_name=policy.name,
                    cache_root=cache_root,
                )
            origin_registry = resolved_slice.origin_registry.copy()
            market_actuals = resolved_slice.market_actuals.copy()
            scenario_frame = resolved_slice.scenarios.copy()
            delivery_days = pd.to_datetime(scenario_frame["delivery_day"], errors="coerce").dt.normalize()
            actual_missing_rows = int(pd.to_numeric(market_actuals["actual_price_eur_per_mwh"], errors="coerce").isna().sum())
            probability_sum_min = float(origin_registry["probability_sum"].min()) if not origin_registry.empty else float("nan")
            probability_sum_max = float(origin_registry["probability_sum"].max()) if not origin_registry.empty else float("nan")
            scenario_count_min = int(origin_registry["scenario_count"].min()) if not origin_registry.empty else 0
            scenario_count_max = int(origin_registry["scenario_count"].max()) if not origin_registry.empty else 0
            actual_hour_count = int(market_actuals["delivery_start_utc"].nunique())
            delivery_day_count = int(delivery_days.nunique())
            status = "pass"
            findings: list[str] = []
            if delivery_day_count != 7:
                status = "fail"
                findings.append(f"delivery_day_count={delivery_day_count}")
            if actual_hour_count != 168:
                status = "fail"
                findings.append(f"actual_hour_count={actual_hour_count}")
            if actual_missing_rows != 0:
                status = "fail"
                findings.append(f"actual_missing_rows={actual_missing_rows}")
            if not origin_registry["probability_sum"].between(0.999999, 1.000001).all():
                status = "fail"
                findings.append(
                    f"probability_sum_range={probability_sum_min:.6f}..{probability_sum_max:.6f}"
                )
            if not origin_registry["scenario_count"].astype(int).eq(75).all():
                status = "fail"
                findings.append(
                    f"scenario_count_range={scenario_count_min}..{scenario_count_max}"
                )
            audit_rows.append(
                {
                    "artifact_id": artifact_id,
                    "expected_split": expected_split,
                    "requested_identifier": str(entry["label"]),
                    "week_label": str(entry["week_label"]),
                    "week_id": str(entry["week_id"]),
                    "regime_label": str(entry["regime_label"]),
                    "selection_status": str(entry.get("selection_status", "selected_dedicated")),
                    "cache_status": str(resolved_slice.cache_status),
                    "slice_fingerprint": str(resolved_slice.slice_fingerprint),
                    "delivery_day_count": delivery_day_count,
                    "actual_hour_count": actual_hour_count,
                    "actual_missing_rows": actual_missing_rows,
                    "scenario_count_min": scenario_count_min,
                    "scenario_count_max": scenario_count_max,
                    "probability_sum_min": probability_sum_min,
                    "probability_sum_max": probability_sum_max,
                    "status": status,
                    "details": "; ".join(findings) if findings else "selected-week input slice passed preflight",
                }
            )
    return SelectedWeekPreflightResult(
        selected_entries=selected_entries,
        registry_rows=registry_rows,
        audit_rows=pd.DataFrame(audit_rows),
        runtime_profile=profiler.to_frame(),
        output_policy_name=policy.name,
        cache_root=cache_root,
    )
