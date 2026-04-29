from __future__ import annotations

from collections import OrderedDict

from .endogenous_features import (
    DAY_BLOCK_FEATURES,
    MOMENTUM_FEATURES,
    RAW_LAG_FEATURES,
    ROLLING_FEATURES,
    WEEK_BLOCK_FEATURES,
)


def _fs1_family_map() -> OrderedDict[str, tuple[str, ...]]:
    return OrderedDict(
        [
            ("raw_lags", tuple(RAW_LAG_FEATURES)),
            ("momentum_differences", tuple(MOMENTUM_FEATURES)),
            ("rolling_regime", tuple(ROLLING_FEATURES)),
            ("block_summaries", tuple((*DAY_BLOCK_FEATURES, *WEEK_BLOCK_FEATURES))),
        ]
    )


def _fs2_family_map() -> OrderedDict[str, tuple[str, ...]]:
    mapping = _fs1_family_map()
    mapping["calendar_basic"] = ("hour_of_day", "day_of_week", "is_weekend", "month")
    mapping["holidays"] = ("is_dutch_holiday",)
    return mapping


def feature_family_map(fs_level: str, model_family: str) -> OrderedDict[str, tuple[str, ...]]:
    family = str(model_family)
    if fs_level == "FS1" and family in {"lear", "xgboost"}:
        return _fs1_family_map()
    if fs_level == "FS2" and family in {"lear", "xgboost", "prophet"}:
        # Prophet keeps the same explicit regressor families only for the regressors that
        # are genuinely explicit in the current implementation. Built-in seasonality is not
        # represented as an ablatable feature family here.
        return _fs2_family_map()
    return OrderedDict()


def supported_feature_families(fs_level: str, model_family: str) -> list[str]:
    return list(feature_family_map(fs_level, model_family).keys())


def filter_feature_columns(
    feature_columns: list[str],
    *,
    fs_level: str,
    model_family: str,
    excluded_feature_families: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    excluded = {str(name) for name in (excluded_feature_families or ())}
    if not excluded:
        return list(feature_columns)

    family_map = feature_family_map(fs_level, model_family)
    unknown = sorted(excluded - set(family_map.keys()))
    if unknown:
        raise ValueError(
            f"Unsupported feature families for {model_family} at {fs_level}: {unknown}. "
            f"Supported families: {list(family_map.keys())}"
        )

    excluded_columns = {
        column
        for family_name, columns in family_map.items()
        if family_name in excluded
        for column in columns
    }
    return [column for column in feature_columns if column not in excluded_columns]
