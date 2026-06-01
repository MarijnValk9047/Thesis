from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import QuarterHourDAExtensionConfig


BASELINE_SENTINEL = "__baseline_no_explicit_features__"
PLACEHOLDER_FS2_SENTINEL = "__pending_historical_shape_features__"
PLACEHOLDER_FS3_SENTINEL = "__pending_exogenous_features__"

REGISTRY_FILENAME = "quarterhour_feature_registry.csv"
FAMILY_MAP_FILENAME = "quarterhour_feature_family_map.csv"
SET_SUMMARY_FILENAME = "quarterhour_feature_set_summary.csv"
AVAILABILITY_FILENAME = "quarterhour_feature_availability_check.csv"
REGISTRY_JSON_FILENAME = "quarterhour_feature_registry.json"


def registry_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "registry"


def _calendar_columns() -> tuple[str, ...]:
    return (
        *(f"hour_{hour}" for hour in range(24)),
        *(f"weekday_{weekday}" for weekday in range(7)),
        "weekend_flag",
        *(f"month_{month}" for month in range(1, 13)),
        *(f"quarter_{quarter}" for quarter in range(1, 5)),
        "season_winter",
        "season_spring",
        "season_summer",
        "season_autumn",
    )


def _anchor_level_columns() -> tuple[str, ...]:
    return (
        "hourly_mean_eur_per_mwh",
        "prev_hour_anchor",
        "next_hour_anchor",
        "daily_anchor_min",
        "daily_anchor_mean",
        "daily_anchor_max",
        "daily_anchor_spread",
        "daily_anchor_rank_pct",
    )


def _regime_flag_columns() -> tuple[str, ...]:
    return (
        "high_price_anchor_flag",
        "negative_anchor_flag",
        "next_hour_missing_flag",
        "prev_hour_missing_flag",
    )


def _ramp_shape_columns() -> tuple[str, ...]:
    return (
        "ramp_in",
        "ramp_out",
        "abs_ramp_in",
        "abs_ramp_out",
    )


def qh_feature_family_map() -> OrderedDict[str, OrderedDict[str, tuple[str, ...]]]:
    return OrderedDict(
        [
            (
                "QH-FS0",
                OrderedDict(
                    [
                        ("baseline_contract", (BASELINE_SENTINEL,)),
                    ]
                ),
            ),
            (
                "QH-FS1",
                OrderedDict(
                    [
                        ("calendar", _calendar_columns()),
                        ("anchor_level", _anchor_level_columns()),
                        ("regime_flags", _regime_flag_columns()),
                        ("ramp_shape_descriptors", _ramp_shape_columns()),
                    ]
                ),
            ),
            (
                "QH-FS2",
                OrderedDict(
                    [
                        ("historical_shape_features", (PLACEHOLDER_FS2_SENTINEL,)),
                    ]
                ),
            ),
            (
                "QH-FS3",
                OrderedDict(
                    [
                        ("exogenous_features", (PLACEHOLDER_FS3_SENTINEL,)),
                    ]
                ),
            ),
        ]
    )


def _feature_origin_type(feature_family: str) -> str:
    if feature_family == "calendar":
        return "calendar_known_at_origin"
    if feature_family in {"anchor_level", "regime_flags", "ramp_shape_descriptors"}:
        return "anchor_derived"
    if feature_family == "historical_shape_features":
        return "endogenous_shape_derived"
    if feature_family == "exogenous_features":
        return "exogenous"
    return "none"


def _availability_scope(feature_set_id: str, feature_family: str) -> str:
    if feature_set_id == "QH-FS0":
        return "forecast_layer_baseline_contract"
    if feature_set_id == "QH-FS1":
        if feature_family == "calendar":
            return "all_horizons_D_to_Dplus4"
        return "all_horizons_D_to_Dplus4_subject_to_hourly_anchor_availability"
    if feature_set_id == "QH-FS2":
        return "not_yet_implemented_pending_causal_shape_history_design"
    if feature_set_id == "QH-FS3":
        return "not_yet_implemented_pending_exogenous_horizon_availability_audit"
    return "unknown"


def _source_description(feature_set_id: str, feature_family: str) -> str:
    if feature_set_id == "QH-FS0":
        return "Explicit registry contract for naive or repeated-hourly baseline layer with no learned feature columns."
    if feature_set_id == "QH-FS1":
        if feature_family == "calendar":
            return "Current quarter-hour dummy-encoded calendar structure assembled by phase04._build_feature_frame and reused by phase07 under minimal_realistic_anchor_features_v1."
        return "Current realistic quarter-hour anchor-derived feature block assembled by phase04._build_feature_frame and reused by phase07 under minimal_realistic_anchor_features_v1."
    if feature_set_id == "QH-FS2":
        return "Placeholder only. Expanded endogenous or shape-history feature layer is not implemented in the active repo."
    if feature_set_id == "QH-FS3":
        return "Placeholder only. Exogenous quarter-hour layer should reuse audited hourly exogenous families after a quarter-hour availability audit."
    return ""


def _leakage_risk_note(feature_set_id: str, feature_family: str) -> str:
    if feature_set_id == "QH-FS0":
        return "Baseline layer must remain causal and must not rely on future quarter-hour realized values."
    if feature_set_id == "QH-FS1":
        if feature_family == "calendar":
            return "Calendar fields are safe only because they are known at forecast origin and remain timestamp-derived rather than target-derived."
        return "Safe only if derived from hourly anchor paths and information available under known_at_utc <= forecast_origin_utc. Do not backfill from future quarter-hour realized prices."
    if feature_set_id == "QH-FS2":
        return "High leakage risk until historical shape inputs are formally constrained to observed and known-at-origin information."
    if feature_set_id == "QH-FS3":
        return "High leakage risk until exogenous publication timing is audited by horizon and known_at semantics."
    return ""


def _active_flag(feature_set_id: str) -> bool:
    return feature_set_id in {"QH-FS0", "QH-FS1"}


def _implementation_status(feature_set_id: str) -> str:
    if feature_set_id in {"QH-FS0", "QH-FS1"}:
        return "implemented"
    return "placeholder_not_yet_implemented"


def _model_scope(feature_set_id: str) -> str:
    if feature_set_id == "QH-FS1":
        return "all_candidate_models"
    if feature_set_id == "QH-FS0":
        return "baseline_family_only"
    return "all_candidate_models"


def _is_placeholder_feature(column_name: str) -> bool:
    return str(column_name).startswith("__")


def build_registry_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    family_map = qh_feature_family_map()
    for feature_set_id, feature_families in family_map.items():
        for family_order_index, (feature_family, feature_columns) in enumerate(feature_families.items()):
            for feature_order_index, feature_column in enumerate(feature_columns):
                rows.append(
                    {
                        "feature_set_id": feature_set_id,
                        "fs_layer": feature_set_id,
                        "feature_column": str(feature_column),
                        "feature_family": str(feature_family),
                        "feature_origin_type": _feature_origin_type(str(feature_family)),
                        "availability_scope": _availability_scope(feature_set_id, str(feature_family)),
                        "source_description": _source_description(feature_set_id, str(feature_family)),
                        "leakage_risk_note": _leakage_risk_note(feature_set_id, str(feature_family)),
                        "active_flag": bool(_active_flag(feature_set_id)),
                        "implementation_status": _implementation_status(feature_set_id),
                        "model_scope": _model_scope(feature_set_id),
                        "is_placeholder_feature": bool(_is_placeholder_feature(str(feature_column))),
                        "feature_family_order_index": int(family_order_index),
                        "feature_order_index": int(feature_order_index),
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["feature_set_id", "feature_family_order_index", "feature_order_index", "feature_column"]
    ).reset_index(drop=True)


def build_feature_family_map_frame() -> pd.DataFrame:
    registry = build_registry_frame()
    family_rows: list[dict[str, object]] = []
    for keys, group in registry.groupby(["feature_set_id", "feature_family"], dropna=False):
        feature_set_id, feature_family = keys
        active_non_placeholder = group[
            group["active_flag"].fillna(False).astype(bool) & ~group["is_placeholder_feature"].fillna(False).astype(bool)
        ].copy()
        family_rows.append(
            {
                "feature_set_id": str(feature_set_id),
                "fs_layer": str(feature_set_id),
                "feature_family": str(feature_family),
                "feature_origin_type": str(group["feature_origin_type"].iloc[0]),
                "availability_scope": str(group["availability_scope"].iloc[0]),
                "active_flag": bool(group["active_flag"].iloc[0]),
                "implementation_status": str(group["implementation_status"].iloc[0]),
                "model_scope": str(group["model_scope"].iloc[0]),
                "feature_count_total": int(group.shape[0]),
                "feature_count_active_non_placeholder": int(active_non_placeholder.shape[0]),
                "feature_columns_csv": ", ".join(active_non_placeholder["feature_column"].astype(str).tolist()),
            }
        )
    return pd.DataFrame(family_rows).sort_values(["feature_set_id", "feature_family"]).reset_index(drop=True)


def build_feature_set_summary_frame() -> pd.DataFrame:
    registry = build_registry_frame()
    summary_rows: list[dict[str, object]] = []
    for feature_set_id, group in registry.groupby("feature_set_id", dropna=False):
        active_non_placeholder = group[
            group["active_flag"].fillna(False).astype(bool) & ~group["is_placeholder_feature"].fillna(False).astype(bool)
        ].copy()
        summary_rows.append(
            {
                "feature_set_id": str(feature_set_id),
                "fs_layer": str(feature_set_id),
                "active_flag": bool(group["active_flag"].iloc[0]),
                "implementation_status": str(group["implementation_status"].iloc[0]),
                "model_scope": str(group["model_scope"].iloc[0]),
                "feature_family_count_total": int(group["feature_family"].nunique()),
                "feature_family_count_active_non_placeholder": int(active_non_placeholder["feature_family"].nunique()),
                "feature_column_count_total": int(group.shape[0]),
                "feature_column_count_active_non_placeholder": int(active_non_placeholder.shape[0]),
                "source_feature_mode": (
                    "no_explicit_feature_columns"
                    if feature_set_id == "QH-FS0"
                    else "minimal_realistic_anchor_features_v1"
                    if feature_set_id == "QH-FS1"
                    else "placeholder_only_not_implemented"
                ),
                "notes": (
                    "Explicit baseline contract. No learned feature columns."
                    if feature_set_id == "QH-FS0"
                    else "Active quarter-hour realistic feature layer for later LEAR and XGBoost comparison."
                    if feature_set_id == "QH-FS1"
                    else "Registered as inactive placeholder only."
                ),
            }
        )
    return pd.DataFrame(summary_rows).sort_values(["feature_set_id"]).reset_index(drop=True)


def build_feature_availability_check_frame() -> pd.DataFrame:
    registry = build_registry_frame()
    rows: list[dict[str, object]] = []
    for keys, group in registry.groupby(["feature_set_id", "feature_family"], dropna=False):
        feature_set_id, feature_family = keys
        active_non_placeholder = group[
            group["active_flag"].fillna(False).astype(bool) & ~group["is_placeholder_feature"].fillna(False).astype(bool)
        ].copy()
        if str(feature_set_id) == "QH-FS0":
            availability_status = "not_applicable_baseline_contract"
        elif str(feature_set_id) == "QH-FS1":
            availability_status = "registered_active_assumed_available_from_current_realistic_feature_builder"
        else:
            availability_status = "placeholder_not_yet_implemented"
        rows.append(
            {
                "feature_set_id": str(feature_set_id),
                "fs_layer": str(feature_set_id),
                "feature_family": str(feature_family),
                "active_flag": bool(group["active_flag"].iloc[0]),
                "implementation_status": str(group["implementation_status"].iloc[0]),
                "availability_scope": str(group["availability_scope"].iloc[0]),
                "availability_status": availability_status,
                "feature_count_checked": int(active_non_placeholder.shape[0]),
                "missing_feature_columns_count": 0 if str(feature_set_id) in {"QH-FS0", "QH-FS1"} else int(active_non_placeholder.shape[0]),
                "notes": (
                    "No explicit feature columns to validate."
                    if str(feature_set_id) == "QH-FS0"
                    else "Static registry check only. Full data-frame availability validation should run inside later modeling stages."
                    if str(feature_set_id) == "QH-FS1"
                    else "Placeholder definition only. Full availability audit is deferred."
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["feature_set_id", "feature_family"]).reset_index(drop=True)


def build_registry_bundle() -> dict[str, pd.DataFrame]:
    return {
        "registry": build_registry_frame(),
        "family_map": build_feature_family_map_frame(),
        "set_summary": build_feature_set_summary_frame(),
        "availability_check": build_feature_availability_check_frame(),
    }


def write_registry_artifacts(config: QuarterHourDAExtensionConfig | None = None) -> dict[str, Path]:
    resolved = config or QuarterHourDAExtensionConfig()
    output_dir = registry_root(resolved)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle = build_registry_bundle()
    registry_paths = {
        "registry_csv": output_dir / REGISTRY_FILENAME,
        "family_map_csv": output_dir / FAMILY_MAP_FILENAME,
        "set_summary_csv": output_dir / SET_SUMMARY_FILENAME,
        "availability_check_csv": output_dir / AVAILABILITY_FILENAME,
        "registry_json": output_dir / REGISTRY_JSON_FILENAME,
    }

    bundle["registry"].to_csv(registry_paths["registry_csv"], index=False)
    bundle["family_map"].to_csv(registry_paths["family_map_csv"], index=False)
    bundle["set_summary"].to_csv(registry_paths["set_summary_csv"], index=False)
    bundle["availability_check"].to_csv(registry_paths["availability_check_csv"], index=False)

    json_payload = {
        "feature_registry": bundle["registry"].to_dict(orient="records"),
        "feature_family_map": bundle["family_map"].to_dict(orient="records"),
        "feature_set_summary": bundle["set_summary"].to_dict(orient="records"),
        "feature_availability_check": bundle["availability_check"].to_dict(orient="records"),
    }
    registry_paths["registry_json"].write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
    return registry_paths


def load_feature_registry(config: QuarterHourDAExtensionConfig | None = None) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    path = registry_root(resolved) / REGISTRY_FILENAME
    if path.exists():
        return pd.read_csv(path)
    return build_registry_frame()


def load_feature_family_map(config: QuarterHourDAExtensionConfig | None = None) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    path = registry_root(resolved) / FAMILY_MAP_FILENAME
    if path.exists():
        return pd.read_csv(path)
    return build_feature_family_map_frame()


def _active_non_placeholder_rows(
    registry: pd.DataFrame,
    *,
    feature_set_id: str,
    active_only: bool = True,
) -> pd.DataFrame:
    subset = registry[registry["feature_set_id"].astype(str) == str(feature_set_id)].copy()
    if active_only:
        subset = subset[subset["active_flag"].fillna(False).astype(bool)].copy()
    subset = subset[~subset["is_placeholder_feature"].fillna(False).astype(bool)].copy()
    order_columns = [
        column_name
        for column_name in ("feature_family_order_index", "feature_order_index", "feature_column")
        if column_name in subset.columns
    ]
    if order_columns:
        subset = subset.sort_values(order_columns).reset_index(drop=True)
    return subset.reset_index(drop=True)


def get_feature_columns_by_set(
    feature_set_id: str,
    *,
    config: QuarterHourDAExtensionConfig | None = None,
    active_only: bool = True,
) -> list[str]:
    registry = load_feature_registry(config)
    subset = _active_non_placeholder_rows(registry, feature_set_id=feature_set_id, active_only=active_only)
    return subset["feature_column"].astype(str).tolist()


def get_feature_families_for_set(
    feature_set_id: str,
    *,
    config: QuarterHourDAExtensionConfig | None = None,
    active_only: bool = True,
) -> list[str]:
    registry = load_feature_registry(config)
    subset = _active_non_placeholder_rows(registry, feature_set_id=feature_set_id, active_only=active_only)
    return subset["feature_family"].drop_duplicates().astype(str).tolist()


def validate_registry_feature_columns_exist(
    frame: pd.DataFrame,
    *,
    feature_set_id: str,
    config: QuarterHourDAExtensionConfig | None = None,
    active_only: bool = True,
) -> list[str]:
    expected_columns = get_feature_columns_by_set(feature_set_id, config=config, active_only=active_only)
    missing = sorted(column for column in expected_columns if str(column) not in set(frame.columns))
    return missing


def smoke_check_feature_registry(config: QuarterHourDAExtensionConfig | None = None) -> pd.DataFrame:
    resolved = config or QuarterHourDAExtensionConfig()
    bundle = build_registry_bundle()
    registry = bundle["registry"]
    qh_fs1_columns = get_feature_columns_by_set("QH-FS1", config=resolved, active_only=True)
    expected_qh_fs1_columns = [
        *qh_feature_family_map()["QH-FS1"]["calendar"],
        *qh_feature_family_map()["QH-FS1"]["anchor_level"],
        *qh_feature_family_map()["QH-FS1"]["regime_flags"],
        *qh_feature_family_map()["QH-FS1"]["ramp_shape_descriptors"],
    ]
    checks = [
        {
            "check_name": "registry_loads",
            "status": "pass" if not registry.empty else "fail",
            "details": f"rows={int(registry.shape[0])}",
        },
        {
            "check_name": "qh_fs1_feature_list_matches_current_known_columns",
            "status": "pass" if qh_fs1_columns == expected_qh_fs1_columns else "fail",
            "details": f"registry_count={len(qh_fs1_columns)} expected_count={len(expected_qh_fs1_columns)}",
        },
        {
            "check_name": "no_duplicate_feature_set_and_feature_column_rows",
            "status": "pass"
            if not registry[["feature_set_id", "feature_column"]].duplicated().any()
            else "fail",
            "details": f"duplicate_count={int(registry[['feature_set_id', 'feature_column']].duplicated().sum())}",
        },
        {
            "check_name": "every_active_non_placeholder_feature_has_family",
            "status": "pass"
            if registry.loc[
                registry["active_flag"].fillna(False).astype(bool) & ~registry["is_placeholder_feature"].fillna(False).astype(bool),
                "feature_family",
            ]
            .astype(str)
            .str.strip()
            .ne("")
            .all()
            else "fail",
            "details": "active non-placeholder rows have non-empty feature_family values",
        },
    ]
    return pd.DataFrame(checks)


def _main() -> int:
    paths = write_registry_artifacts()
    checks = smoke_check_feature_registry()
    print("Wrote quarter-hour feature registry artifacts:")
    for key, value in paths.items():
        print(f"- {key}: {value}")
    print(checks.to_string(index=False))
    if (checks["status"].astype(str) != "pass").any():
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
