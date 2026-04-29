from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass

from .endogenous_features import (
    DAY_BLOCK_FEATURES,
    MOMENTUM_FEATURES,
    RAW_LAG_FEATURES,
    ROLLING_FEATURES,
    WEEK_BLOCK_FEATURES,
)
from .external_features import FS3Experiment


CALENDAR_FEATURES: tuple[str, ...] = (
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "month",
    "is_dutch_holiday",
)

WEEKLY_SAME_HOUR_FEATURES: tuple[str, ...] = (
    "lag_24",
    "lag_25",
    "lag_168",
    "lag_169",
    "cross_season_diff",
)

ENGINEERED_ENDOGENOUS_HISTORY_FEATURES: tuple[str, ...] = (
    *MOMENTUM_FEATURES,
    *ROLLING_FEATURES,
    *DAY_BLOCK_FEATURES,
    *WEEK_BLOCK_FEATURES,
)

ENDOGENOUS_CORE_FEATURES: tuple[str, ...] = (
    *RAW_LAG_FEATURES,
    *WEEKLY_SAME_HOUR_FEATURES,
    *ENGINEERED_ENDOGENOUS_HISTORY_FEATURES,
)

SCHEME_VERSION = "1"
SCHEME_NAME_STAGE_A = "stage_a_top_level"
SCHEME_NAME_LAYER_1 = "layer1_mutually_exclusive"
SCHEME_NAME_LAYER_2 = "layer2_subgroups"
FS2_STAGE_A_CALENDAR_BLOCK = "calendar_total"


@dataclass(frozen=True)
class AblationBlockSpec:
    block_name: str
    display_name: str
    description: str


@dataclass(frozen=True)
class AblationSchemeSpec:
    scheme_name: str
    scheme_version: str
    stage_name: str
    layer_name: str
    display_name: str
    description: str
    target_block: str | None
    blocks: tuple[AblationBlockSpec, ...]

    @property
    def scheme_label(self) -> str:
        if self.target_block:
            return f"{self.scheme_name}__{self.target_block}"
        return self.scheme_name


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower()).strip("_")
    return text or "scheme"


def _compact_slug(value: str, *, max_length: int = 18) -> str:
    slug = _slugify(value)
    if len(slug) <= int(max_length):
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:6]
    prefix_length = max(1, int(max_length) - len(digest) - 1)
    return f"{slug[:prefix_length]}_{digest}"


def fs3_feature_columns(experiment: FS3Experiment | None) -> tuple[str, ...]:
    if experiment is None:
        return ()
    columns: list[str] = list(experiment.direct_columns)
    for column in experiment.lagged_columns:
        for lag in experiment.lag_hours:
            columns.append(f"{column}_lag_{lag}")
    return tuple(columns)


def _expanded_columns_for_codes(
    experiment_map: dict[str, FS3Experiment],
    family_codes: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    ordered: list[str] = []
    for family_code in family_codes:
        experiment = experiment_map.get(str(family_code))
        if experiment is None:
            continue
        for column in fs3_feature_columns(experiment):
            if column not in ordered:
                ordered.append(column)
    return tuple(ordered)


def _market_prefix(column: str) -> tuple[str | None, str]:
    parts = str(column).split("_", 1)
    if len(parts) != 2:
        return None, str(column)
    market = str(parts[0])
    if market not in {"BE", "DE", "NL"}:
        return None, str(column)
    return market, str(parts[1])


def _matches_lagged_base(column_suffix: str, base_names: tuple[str, ...]) -> bool:
    return any(str(column_suffix).startswith(f"{base_name}_lag_") for base_name in base_names)


def _fs2_layer1_block_columns() -> OrderedDict[str, tuple[str, ...]]:
    return OrderedDict(
        [
            ("short_autoregressive_price_lags", tuple(RAW_LAG_FEATURES[:2])),
            ("weekly_same_hour_lag_structure", ("lag_24", "lag_25", "lag_168", "lag_169")),
            ("lag_differences", tuple((*MOMENTUM_FEATURES,))),
            ("rolling_regime_descriptors", tuple(ROLLING_FEATURES)),
            ("block_summary_statistics", tuple((*DAY_BLOCK_FEATURES, *WEEK_BLOCK_FEATURES))),
            ("calendar_routine", ("hour_of_day", "day_of_week", "is_weekend", "month")),
            ("holiday", ("is_dutch_holiday",)),
        ]
    )


def _fs2_stage_a_block_columns() -> OrderedDict[str, tuple[str, ...]]:
    layer1 = _fs2_layer1_block_columns()
    endogenous_columns: list[str] = []
    for block_name, columns in layer1.items():
        if block_name in {"calendar_routine", "holiday"}:
            continue
        for column in columns:
            if column not in endogenous_columns:
                endogenous_columns.append(column)
    calendar_columns: list[str] = []
    for block_name in ("calendar_routine", "holiday"):
        for column in layer1[block_name]:
            if column not in calendar_columns:
                calendar_columns.append(column)
    return OrderedDict(
        [
            ("endogenous_core", tuple(endogenous_columns)),
            (FS2_STAGE_A_CALENDAR_BLOCK, tuple(calendar_columns)),
        ]
    )


def _fs2_layer2_supported_definitions() -> OrderedDict[str, OrderedDict[str, tuple[str, ...]]]:
    supported: OrderedDict[str, OrderedDict[str, tuple[str, ...]]] = OrderedDict()
    supported["weekly_same_hour_lag_structure"] = OrderedDict(
        [
            ("daily_anchor_lags", ("lag_24", "lag_25")),
            ("weekly_anchor_lags", ("lag_168", "lag_169")),
        ]
    )
    supported["lag_differences"] = OrderedDict(
        [
            ("short_horizon_differences", ("diff_1", "diff_24")),
            ("seasonal_differences", ("diff_168", "cross_season_diff")),
        ]
    )
    supported["rolling_regime_descriptors"] = OrderedDict(
        [
            ("rolling_24h_regime", ("roll_mean_24", "roll_std_24")),
            ("rolling_168h_regime", ("roll_mean_168", "roll_std_168")),
        ]
    )
    supported["block_summary_statistics"] = OrderedDict(
        [
            ("previous_day_block_summaries", tuple(DAY_BLOCK_FEATURES)),
            ("previous_week_block_summaries", tuple(WEEK_BLOCK_FEATURES)),
        ]
    )
    supported["calendar_routine"] = OrderedDict(
        [
            ("intraday_weekly_calendar", ("hour_of_day", "day_of_week", "is_weekend")),
            ("month_position", ("month",)),
        ]
    )
    return supported


def fs2_ablation_block_map(
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> OrderedDict[str, tuple[str, ...]]:
    scheme_key = str(scheme_name)
    if scheme_key == SCHEME_NAME_STAGE_A:
        return _fs2_stage_a_block_columns()
    if scheme_key == SCHEME_NAME_LAYER_1:
        return _fs2_layer1_block_columns()
    if scheme_key == SCHEME_NAME_LAYER_2:
        supported = _fs2_layer2_supported_definitions()
        if not target_block:
            raise ValueError("FS2 Layer 2 block maps require a target_block.")
        if str(target_block) not in supported:
            raise ValueError(
                f"Unsupported FS2 Layer 2 target block '{target_block}'. "
                f"Supported target blocks: {sorted(supported.keys())}"
            )
        return supported[str(target_block)]
    raise ValueError(f"Unsupported FS2 ablation scheme name: {scheme_name}")


def supported_fs2_layer2_target_blocks() -> list[str]:
    return list(_fs2_layer2_supported_definitions().keys())


def fs2_block_map_from_feature_columns(
    feature_columns: list[str] | tuple[str, ...],
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> OrderedDict[str, tuple[str, ...]]:
    ordered_columns = [str(column) for column in feature_columns]
    layer1_definitions = _fs2_layer1_block_columns()
    layer1_assignments: OrderedDict[str, list[str]] = OrderedDict(
        (block_name, []) for block_name in layer1_definitions.keys()
    )
    for column in ordered_columns:
        for block_name, columns in layer1_definitions.items():
            if str(column) in set(columns) and str(column) not in layer1_assignments[block_name]:
                layer1_assignments[block_name].append(str(column))

    if str(scheme_name) == SCHEME_NAME_LAYER_1:
        return OrderedDict((block_name, tuple(columns)) for block_name, columns in layer1_assignments.items())

    if str(scheme_name) == SCHEME_NAME_STAGE_A:
        endogenous_columns: list[str] = []
        for block_name, columns in layer1_assignments.items():
            if block_name in {"calendar_routine", "holiday"}:
                continue
            for column in columns:
                if column not in endogenous_columns:
                    endogenous_columns.append(column)
        calendar_columns: list[str] = []
        for block_name in ("calendar_routine", "holiday"):
            for column in layer1_assignments[block_name]:
                if column not in calendar_columns:
                    calendar_columns.append(column)
        return OrderedDict(
            [
                ("endogenous_core", tuple(endogenous_columns)),
                (FS2_STAGE_A_CALENDAR_BLOCK, tuple(calendar_columns)),
            ]
        )

    if str(scheme_name) != SCHEME_NAME_LAYER_2:
        raise ValueError(f"Unsupported FS2 scheme name for feature-column classification: {scheme_name}")
    if not target_block:
        raise ValueError("FS2 Layer 2 block classification requires a target_block.")
    subgroup_map = fs2_ablation_block_map(scheme_name=scheme_name, target_block=target_block)
    subset = tuple(layer1_assignments.get(str(target_block), ()))
    return OrderedDict(
        (
            subgroup_name,
            tuple(column for column in subset if column in set(columns)),
        )
        for subgroup_name, columns in subgroup_map.items()
    )


def filter_fs2_columns_by_ablation_scheme(
    feature_columns: list[str],
    *,
    excluded_blocks: tuple[str, ...] | list[str] | None,
    scheme_name: str | None,
    target_block: str | None = None,
) -> list[str]:
    excluded = {str(value) for value in (excluded_blocks or ())}
    if not excluded:
        return list(feature_columns)
    if not scheme_name:
        raise ValueError("FS2 block exclusion requires an ablation scheme name.")
    block_map = fs2_block_map_from_feature_columns(
        feature_columns,
        scheme_name=str(scheme_name),
        target_block=target_block,
    )
    unknown = sorted(excluded - set(block_map.keys()))
    if unknown:
        raise ValueError(
            f"Unsupported FS2 ablation blocks for scheme '{scheme_name}': {unknown}. "
            f"Supported blocks: {list(block_map.keys())}"
        )
    excluded_columns = {
        column
        for block_name, columns in block_map.items()
        if block_name in excluded
        for column in columns
    }
    return [column for column in feature_columns if column not in excluded_columns]


def _classify_layer1_block(column: str, domestic_market: str) -> str | None:
    market, suffix = _market_prefix(column)
    if str(column) in CALENDAR_FEATURES:
        return "calendar"
    if str(column) in RAW_LAG_FEATURES[:2]:
        return "short_autoregressive_price_lags"
    if str(column) in WEEKLY_SAME_HOUR_FEATURES:
        return "weekly_same_hour_lag_structure"
    if str(column) in ENGINEERED_ENDOGENOUS_HISTORY_FEATURES:
        return "engineered_endogenous_history_stats"
    if market is None:
        return None

    if suffix in {"da_total_load_forecast_mw", "da_generation_forecast_mw"}:
        return (
            "domestic_day_ahead_fundamentals"
            if market == str(domestic_market)
            else "neighbor_only_day_ahead_fundamentals"
        )
    if suffix == "week_ahead_total_load_forecast_mw":
        return (
            "domestic_week_ahead_fundamentals"
            if market == str(domestic_market)
            else "neighbor_only_week_ahead_fundamentals"
        )
    if _matches_lagged_base(
        suffix,
        ("actual_total_load_mw", "load_forecast_error_mw"),
    ):
        return (
            "domestic_historical_fundamentals"
            if market == str(domestic_market)
            else "neighbor_only_historical_fundamentals"
        )
    if _matches_lagged_base(
        suffix,
        (
            "actual_generation_total_mw",
            "actual_generation_res_mw",
            "da_generation_forecast_mw",
            "gen_minus_actual_load_mw",
        ),
    ):
        return (
            "domestic_historical_fundamentals"
            if market == str(domestic_market)
            else "neighbor_only_historical_fundamentals"
        )
    if suffix in {
        "installed_capacity_total_mw",
        "installed_capacity_res_mw",
        "installed_capacity_wind_mw",
        "installed_capacity_solar_mw",
    }:
        return "structural_capacity"
    if _matches_lagged_base(suffix, ("da_price_eur_per_mwh",)):
        return "neighbor_price_proxy" if market != str(domestic_market) else None
    return None


def fs3_block_map_from_feature_columns(
    feature_columns: list[str] | tuple[str, ...],
    *,
    domestic_market: str,
    scheme_name: str,
    target_block: str | None = None,
) -> OrderedDict[str, tuple[str, ...]]:
    ordered_columns = [str(column) for column in feature_columns]
    layer1_assignments: OrderedDict[str, list[str]] = OrderedDict(
        (block_name, [])
        for block_name in _layer1_block_columns({}).keys()
    )
    for column in ordered_columns:
        block_name = _classify_layer1_block(column, domestic_market=str(domestic_market))
        if block_name is None:
            continue
        if column not in layer1_assignments[block_name]:
            layer1_assignments[block_name].append(column)

    if str(scheme_name) == SCHEME_NAME_LAYER_1:
        return OrderedDict((block_name, tuple(columns)) for block_name, columns in layer1_assignments.items())

    if str(scheme_name) == SCHEME_NAME_STAGE_A:
        exogenous_columns: list[str] = []
        for block_name, columns in layer1_assignments.items():
            if block_name in {
                "calendar",
                "short_autoregressive_price_lags",
                "weekly_same_hour_lag_structure",
                "engineered_endogenous_history_stats",
            }:
                continue
            for column in columns:
                if column not in exogenous_columns:
                    exogenous_columns.append(column)
        return OrderedDict(
            [
                ("endogenous_core", tuple(column for column in ordered_columns if column in ENDOGENOUS_CORE_FEATURES)),
                ("calendar", tuple(column for column in ordered_columns if column in CALENDAR_FEATURES)),
                ("exogenous_total", tuple(exogenous_columns)),
            ]
        )

    if str(scheme_name) != SCHEME_NAME_LAYER_2:
        raise ValueError(f"Unsupported FS3 scheme name for feature-column classification: {scheme_name}")
    if not target_block:
        raise ValueError("Layer 2 block classification requires a target_block.")

    subset = tuple(layer1_assignments.get(str(target_block), ()))
    if str(target_block) == "domestic_day_ahead_fundamentals":
        return OrderedDict(
            [
                (
                    "domestic_day_ahead_load",
                    tuple(column for column in subset if column.endswith("_da_total_load_forecast_mw")),
                ),
                (
                    "domestic_day_ahead_generation",
                    tuple(column for column in subset if column.endswith("_da_generation_forecast_mw")),
                ),
            ]
        )
    if str(target_block) == "neighbor_only_day_ahead_fundamentals":
        return OrderedDict(
            [
                (
                    "neighbor_only_day_ahead_load",
                    tuple(column for column in subset if column.endswith("_da_total_load_forecast_mw")),
                ),
                (
                    "neighbor_only_day_ahead_generation",
                    tuple(column for column in subset if column.endswith("_da_generation_forecast_mw")),
                ),
            ]
        )
    if str(target_block) == "domestic_historical_fundamentals":
        return OrderedDict(
            [
                (
                    "domestic_load_history",
                    tuple(
                        column
                        for column in subset
                        if _matches_lagged_base(
                            _market_prefix(column)[1],
                            ("actual_total_load_mw", "load_forecast_error_mw"),
                        )
                    ),
                ),
                (
                    "domestic_generation_history",
                    tuple(
                        column
                        for column in subset
                        if _matches_lagged_base(
                            _market_prefix(column)[1],
                            (
                                "actual_generation_total_mw",
                                "actual_generation_res_mw",
                                "da_generation_forecast_mw",
                                "gen_minus_actual_load_mw",
                            ),
                        )
                    ),
                ),
            ]
        )
    if str(target_block) == "neighbor_only_historical_fundamentals":
        return OrderedDict(
            [
                (
                    "neighbor_only_load_history",
                    tuple(
                        column
                        for column in subset
                        if _matches_lagged_base(
                            _market_prefix(column)[1],
                            ("actual_total_load_mw", "load_forecast_error_mw"),
                        )
                    ),
                ),
                (
                    "neighbor_only_generation_history",
                    tuple(
                        column
                        for column in subset
                        if _matches_lagged_base(
                            _market_prefix(column)[1],
                            (
                                "actual_generation_total_mw",
                                "actual_generation_res_mw",
                                "da_generation_forecast_mw",
                                "gen_minus_actual_load_mw",
                            ),
                        )
                    ),
                ),
            ]
        )
    if str(target_block) == "engineered_endogenous_history_stats":
        return OrderedDict(
            [
                ("momentum_differences", tuple(column for column in subset if column in MOMENTUM_FEATURES)),
                ("rolling_regime_statistics", tuple(column for column in subset if column in ROLLING_FEATURES)),
                (
                    "block_summary_statistics",
                    tuple(column for column in subset if column in DAY_BLOCK_FEATURES or column in WEEK_BLOCK_FEATURES),
                ),
            ]
        )
    if str(target_block) == "weekly_same_hour_lag_structure":
        return OrderedDict(
            [
                ("daily_anchor_lags", tuple(column for column in subset if column in {"lag_24", "lag_25"})),
                ("weekly_anchor_lags", tuple(column for column in subset if column in {"lag_168", "lag_169"})),
                ("cross_season_bridge", tuple(column for column in subset if column == "cross_season_diff")),
            ]
        )
    if str(target_block) == "structural_capacity":
        return OrderedDict(
            [
                (
                    "capacity_total_and_res",
                    tuple(
                        column
                        for column in subset
                        if column.endswith("_installed_capacity_total_mw") or column.endswith("_installed_capacity_res_mw")
                    ),
                ),
                (
                    "capacity_wind_and_solar",
                    tuple(
                        column
                        for column in subset
                        if column.endswith("_installed_capacity_wind_mw") or column.endswith("_installed_capacity_solar_mw")
                    ),
                ),
            ]
        )
    raise ValueError(f"Unsupported Layer 2 target block for feature-column classification: {target_block}")


def filter_fs3_columns_by_ablation_scheme(
    feature_columns: list[str],
    *,
    domestic_market: str,
    excluded_blocks: tuple[str, ...] | list[str] | None,
    scheme_name: str | None,
    target_block: str | None = None,
) -> list[str]:
    excluded = {str(value) for value in (excluded_blocks or ())}
    if not excluded:
        return list(feature_columns)
    if not scheme_name:
        raise ValueError("FS3 block exclusion requires an ablation scheme name.")
    block_map = fs3_block_map_from_feature_columns(
        feature_columns,
        domestic_market=domestic_market,
        scheme_name=str(scheme_name),
        target_block=target_block,
    )
    unknown = sorted(excluded - set(block_map.keys()))
    if unknown:
        raise ValueError(
            f"Unsupported FS3 ablation blocks for scheme '{scheme_name}': {unknown}. "
            f"Supported blocks: {list(block_map.keys())}"
        )
    excluded_columns = {
        column
        for block_name, columns in block_map.items()
        if block_name in excluded
        for column in columns
    }
    return [column for column in feature_columns if column not in excluded_columns]


def fs2_feature_taxonomy_payload() -> dict[str, object]:
    layer1 = _fs2_layer1_block_columns()
    layer2 = _fs2_layer2_supported_definitions()
    return {
        "stage_a_blocks": {block_name: list(columns) for block_name, columns in _fs2_stage_a_block_columns().items()},
        "layer1_blocks": {block_name: list(columns) for block_name, columns in layer1.items()},
        "layer2_blocks": {
            target_block: {block_name: list(columns) for block_name, columns in subgroup_map.items()}
            for target_block, subgroup_map in layer2.items()
        },
    }


def fs2_feature_taxonomy_hash() -> str:
    return _stable_hash(fs2_feature_taxonomy_payload())


def fs2_ablation_scheme_spec(
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> AblationSchemeSpec:
    block_map = fs2_ablation_block_map(scheme_name=scheme_name, target_block=target_block)
    if scheme_name == SCHEME_NAME_STAGE_A:
        display_name = "Stage A top-level ablation"
        description = "Two-block orientation layer: endogenous core and total calendar information."
        stage_name = "fs2"
        layer_name = "stage_a"
        block_specs = (
            AblationBlockSpec(
                block_name="endogenous_core",
                display_name="Endogenous core",
                description="All explicit price-history features excluding calendar and holiday inputs.",
            ),
            AblationBlockSpec(
                block_name=FS2_STAGE_A_CALENDAR_BLOCK,
                display_name="Calendar total",
                description="Known-at-forecast-time calendar and holiday signals combined.",
            ),
        )
    elif scheme_name == SCHEME_NAME_LAYER_1:
        display_name = "Layer 1 mutually exclusive blocks"
        description = "Mutually exclusive endogenous and calendar block ablation on the FS2 parent."
        stage_name = "fs2"
        layer_name = "layer1"
        block_specs = (
            AblationBlockSpec(
                "short_autoregressive_price_lags",
                "Short autoregressive price lags",
                "Short-memory raw price persistence anchors.",
            ),
            AblationBlockSpec(
                "weekly_same_hour_lag_structure",
                "Weekly / same-hour lag structure",
                "Daily and weekly same-hour lag anchors.",
            ),
            AblationBlockSpec(
                "lag_differences",
                "Lag differences",
                "Difference-style endogenous features that summarize short and seasonal change.",
            ),
            AblationBlockSpec(
                "rolling_regime_descriptors",
                "Rolling regime descriptors",
                "Rolling mean and volatility descriptors over short and seasonal windows.",
            ),
            AblationBlockSpec(
                "block_summary_statistics",
                "Block summary statistics",
                "Previous-day and previous-week block summaries.",
            ),
            AblationBlockSpec(
                "calendar_routine",
                "Calendar routine",
                "Hour, weekday, weekend, and month signals known at forecast time.",
            ),
            AblationBlockSpec(
                "holiday",
                "Holiday",
                "Dutch holiday indicator known at forecast time.",
            ),
        )
    elif scheme_name == SCHEME_NAME_LAYER_2:
        display_name = "Layer 2 subgroup follow-up"
        description = "Optional subgroup ablation inside one selected FS2 Layer 1 block."
        stage_name = "fs2"
        layer_name = "layer2"
        block_specs = tuple(
            AblationBlockSpec(
                block_name=block_name,
                display_name=block_name.replace("_", " ").title(),
                description=f"Optional Layer 2 subgroup inside '{target_block}'.",
            )
            for block_name in block_map.keys()
        )
    else:
        raise ValueError(f"Unsupported FS2 scheme name: {scheme_name}")

    return AblationSchemeSpec(
        scheme_name=str(scheme_name),
        scheme_version=SCHEME_VERSION,
        stage_name=stage_name,
        layer_name=layer_name,
        display_name=display_name,
        description=description,
        target_block=str(target_block) if target_block else None,
        blocks=block_specs,
    )


def fs2_ablation_scheme_payload(
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> dict[str, object]:
    spec = fs2_ablation_scheme_spec(scheme_name=scheme_name, target_block=target_block)
    block_map = fs2_ablation_block_map(scheme_name=scheme_name, target_block=target_block)
    payload = {
        "scheme_name": spec.scheme_name,
        "scheme_version": spec.scheme_version,
        "stage_name": spec.stage_name,
        "layer_name": spec.layer_name,
        "display_name": spec.display_name,
        "description": spec.description,
        "target_block": spec.target_block,
        "blocks": [
            {
                "block_name": block_spec.block_name,
                "display_name": block_spec.display_name,
                "description": block_spec.description,
                "column_count": int(len(block_map.get(block_spec.block_name, ()))),
                "columns": list(block_map.get(block_spec.block_name, ())),
            }
            for block_spec in spec.blocks
        ],
    }
    payload["scheme_hash"] = _stable_hash(payload)
    payload["feature_taxonomy_hash"] = fs2_feature_taxonomy_hash()
    return payload


def _layer1_block_columns(
    experiment_map: dict[str, FS3Experiment],
) -> OrderedDict[str, tuple[str, ...]]:
    blocks: OrderedDict[str, tuple[str, ...]] = OrderedDict()
    blocks["calendar"] = CALENDAR_FEATURES
    blocks["short_autoregressive_price_lags"] = tuple(RAW_LAG_FEATURES[:2])
    blocks["weekly_same_hour_lag_structure"] = WEEKLY_SAME_HOUR_FEATURES
    blocks["engineered_endogenous_history_stats"] = ENGINEERED_ENDOGENOUS_HISTORY_FEATURES
    blocks["domestic_day_ahead_fundamentals"] = _expanded_columns_for_codes(
        experiment_map,
        ("da_load_day1_domestic", "da_generation_day1_domestic"),
    )
    blocks["neighbor_only_day_ahead_fundamentals"] = _expanded_columns_for_codes(
        experiment_map,
        ("da_load_day1_crossborder", "da_generation_day1_crossborder"),
    )
    blocks["domestic_week_ahead_fundamentals"] = _expanded_columns_for_codes(
        experiment_map,
        ("wa_load_domestic",),
    )
    blocks["neighbor_only_week_ahead_fundamentals"] = _expanded_columns_for_codes(
        experiment_map,
        ("wa_load_crossborder",),
    )
    blocks["domestic_historical_fundamentals"] = _expanded_columns_for_codes(
        experiment_map,
        ("load_history_domestic", "generation_history_domestic"),
    )
    blocks["neighbor_only_historical_fundamentals"] = _expanded_columns_for_codes(
        experiment_map,
        ("load_history_crossborder", "generation_history_crossborder"),
    )
    blocks["structural_capacity"] = _expanded_columns_for_codes(
        experiment_map,
        ("installed_capacity_crossborder",),
    )
    blocks["neighbor_price_proxy"] = _expanded_columns_for_codes(
        experiment_map,
        ("neighbor_price_weekly",),
    )
    return blocks


def _stage_a_block_columns(
    experiment_map: dict[str, FS3Experiment],
) -> OrderedDict[str, tuple[str, ...]]:
    layer1 = _layer1_block_columns(experiment_map)
    exogenous_block_names = [
        block_name
        for block_name in layer1.keys()
        if block_name not in {
            "calendar",
            "short_autoregressive_price_lags",
            "weekly_same_hour_lag_structure",
            "engineered_endogenous_history_stats",
        }
    ]
    exogenous_columns: list[str] = []
    for block_name in exogenous_block_names:
        for column in layer1[block_name]:
            if column not in exogenous_columns:
                exogenous_columns.append(column)
    return OrderedDict(
        [
            ("endogenous_core", ENDOGENOUS_CORE_FEATURES),
            ("calendar", CALENDAR_FEATURES),
            ("exogenous_total", tuple(exogenous_columns)),
        ]
    )


def _layer2_supported_definitions(
    experiment_map: dict[str, FS3Experiment],
) -> OrderedDict[str, OrderedDict[str, tuple[str, ...]]]:
    supported: OrderedDict[str, OrderedDict[str, tuple[str, ...]]] = OrderedDict()
    supported["domestic_day_ahead_fundamentals"] = OrderedDict(
        [
            ("domestic_day_ahead_load", _expanded_columns_for_codes(experiment_map, ("da_load_day1_domestic",))),
            (
                "domestic_day_ahead_generation",
                _expanded_columns_for_codes(experiment_map, ("da_generation_day1_domestic",)),
            ),
        ]
    )
    supported["neighbor_only_day_ahead_fundamentals"] = OrderedDict(
        [
            ("neighbor_only_day_ahead_load", _expanded_columns_for_codes(experiment_map, ("da_load_day1_crossborder",))),
            (
                "neighbor_only_day_ahead_generation",
                _expanded_columns_for_codes(experiment_map, ("da_generation_day1_crossborder",)),
            ),
        ]
    )
    supported["domestic_historical_fundamentals"] = OrderedDict(
        [
            ("domestic_load_history", _expanded_columns_for_codes(experiment_map, ("load_history_domestic",))),
            (
                "domestic_generation_history",
                _expanded_columns_for_codes(experiment_map, ("generation_history_domestic",)),
            ),
        ]
    )
    supported["neighbor_only_historical_fundamentals"] = OrderedDict(
        [
            ("neighbor_only_load_history", _expanded_columns_for_codes(experiment_map, ("load_history_crossborder",))),
            (
                "neighbor_only_generation_history",
                _expanded_columns_for_codes(experiment_map, ("generation_history_crossborder",)),
            ),
        ]
    )
    supported["engineered_endogenous_history_stats"] = OrderedDict(
        [
            ("momentum_differences", tuple(MOMENTUM_FEATURES)),
            ("rolling_regime_statistics", tuple(ROLLING_FEATURES)),
            ("block_summary_statistics", tuple((*DAY_BLOCK_FEATURES, *WEEK_BLOCK_FEATURES))),
        ]
    )
    supported["weekly_same_hour_lag_structure"] = OrderedDict(
        [
            ("daily_anchor_lags", ("lag_24", "lag_25")),
            ("weekly_anchor_lags", ("lag_168", "lag_169")),
            ("cross_season_bridge", ("cross_season_diff",)),
        ]
    )
    supported["structural_capacity"] = OrderedDict(
        [
            (
                "capacity_total_and_res",
                tuple(
                    column
                    for column in _expanded_columns_for_codes(experiment_map, ("installed_capacity_crossborder",))
                    if column.endswith("_installed_capacity_total_mw") or column.endswith("_installed_capacity_res_mw")
                ),
            ),
            (
                "capacity_wind_and_solar",
                tuple(
                    column
                    for column in _expanded_columns_for_codes(experiment_map, ("installed_capacity_crossborder",))
                    if column.endswith("_installed_capacity_wind_mw") or column.endswith("_installed_capacity_solar_mw")
                ),
            ),
        ]
    )
    return supported


def fs3_ablation_block_map(
    experiment_map: dict[str, FS3Experiment],
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> OrderedDict[str, tuple[str, ...]]:
    scheme_key = str(scheme_name)
    if scheme_key == SCHEME_NAME_STAGE_A:
        return _stage_a_block_columns(experiment_map)
    if scheme_key == SCHEME_NAME_LAYER_1:
        return _layer1_block_columns(experiment_map)
    if scheme_key == SCHEME_NAME_LAYER_2:
        supported = _layer2_supported_definitions(experiment_map)
        if not target_block:
            raise ValueError("Layer 2 block maps require a target_block.")
        if str(target_block) not in supported:
            supported_names = sorted(supported.keys())
            raise ValueError(
                f"Unsupported Layer 2 target block '{target_block}'. Supported target blocks: {supported_names}"
            )
        return supported[str(target_block)]
    raise ValueError(f"Unsupported FS3 ablation scheme name: {scheme_name}")


def supported_layer2_target_blocks(experiment_map: dict[str, FS3Experiment]) -> list[str]:
    return list(_layer2_supported_definitions(experiment_map).keys())


def aggregate_run_label_for_scheme(
    *,
    parent_run_label: str,
    scheme_name: str,
    scheme_version: str = SCHEME_VERSION,
    target_block: str | None = None,
) -> str:
    suffix = f"{_slugify(scheme_name)}_v{_slugify(scheme_version)}"
    if target_block:
        suffix = f"{suffix}__{_compact_slug(target_block)}"
    return f"feature_family_ablation__{parent_run_label}__{suffix}"


def layer2_scheme_name_for_target(target_block: str) -> str:
    return f"{SCHEME_NAME_LAYER_2}__{str(target_block)}"


def _stable_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def fs3_feature_taxonomy_payload(experiment_map: dict[str, FS3Experiment]) -> dict[str, object]:
    layer1 = _layer1_block_columns(experiment_map)
    layer2 = _layer2_supported_definitions(experiment_map)
    return {
        "calendar_features": list(CALENDAR_FEATURES),
        "endogenous_core_features": list(ENDOGENOUS_CORE_FEATURES),
        "layer1_blocks": {block_name: list(columns) for block_name, columns in layer1.items()},
        "layer2_blocks": {
            target_block: {block_name: list(columns) for block_name, columns in subgroup_map.items()}
            for target_block, subgroup_map in layer2.items()
        },
        "available_experiments": {
            experiment_code: {
                "direct_columns": list(experiment.direct_columns),
                "lagged_columns": list(experiment.lagged_columns),
                "lag_hours": list(experiment.lag_hours),
            }
            for experiment_code, experiment in sorted(experiment_map.items())
        },
    }


def fs3_feature_taxonomy_hash(experiment_map: dict[str, FS3Experiment]) -> str:
    return _stable_hash(fs3_feature_taxonomy_payload(experiment_map))


def fs3_ablation_scheme_spec(
    experiment_map: dict[str, FS3Experiment],
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> AblationSchemeSpec:
    block_map = fs3_ablation_block_map(
        experiment_map,
        scheme_name=scheme_name,
        target_block=target_block,
    )

    if scheme_name == SCHEME_NAME_STAGE_A:
        display_name = "Stage A top-level ablation"
        description = "Three-block orientation layer: endogenous core, calendar, and total exogenous information."
        stage_name = "combo"
        layer_name = "stage_a"
        block_specs = (
            AblationBlockSpec(
                block_name="endogenous_core",
                display_name="Endogenous core",
                description="All explicit price-history features excluding calendar and FS3 exogenous inputs.",
            ),
            AblationBlockSpec(
                block_name="calendar",
                display_name="Calendar",
                description="Known-at-forecast-time calendar and holiday signals.",
            ),
            AblationBlockSpec(
                block_name="exogenous_total",
                display_name="Exogenous total",
                description="All active FS3 external regressors combined into one block.",
            ),
        )
    elif scheme_name == SCHEME_NAME_LAYER_1:
        display_name = "Layer 1 mutually exclusive blocks"
        description = "Thesis-grade mutually exclusive block ablation on the full FS3 combo parent."
        stage_name = "combo"
        layer_name = "layer1"
        block_specs = (
            AblationBlockSpec("calendar", "Calendar", "Known-at-forecast-time calendar and holiday signals."),
            AblationBlockSpec(
                "short_autoregressive_price_lags",
                "Short autoregressive price lags",
                "Short-memory raw price persistence anchors.",
            ),
            AblationBlockSpec(
                "weekly_same_hour_lag_structure",
                "Weekly / same-hour lag structure",
                "Daily and weekly same-hour anchors plus the bridge between them.",
            ),
            AblationBlockSpec(
                "engineered_endogenous_history_stats",
                "Engineered endogenous history stats",
                "Momentum, rolling regime descriptors, and block summary statistics.",
            ),
            AblationBlockSpec(
                "domestic_day_ahead_fundamentals",
                "Domestic day-ahead fundamentals",
                "Domestic day-ahead load and generation forecasts for the D-only branch.",
            ),
            AblationBlockSpec(
                "neighbor_only_day_ahead_fundamentals",
                "Neighbor-only day-ahead fundamentals",
                "Neighbor day-ahead load and generation forecasts for the D-only branch.",
            ),
            AblationBlockSpec(
                "domestic_week_ahead_fundamentals",
                "Domestic week-ahead fundamentals",
                "Domestic week-ahead load signals used on the active horizon.",
            ),
            AblationBlockSpec(
                "neighbor_only_week_ahead_fundamentals",
                "Neighbor-only week-ahead fundamentals",
                "Neighbor week-ahead load signals used on the active horizon.",
            ),
            AblationBlockSpec(
                "domestic_historical_fundamentals",
                "Domestic historical fundamentals",
                "Domestic lagged load and generation-derived history signals.",
            ),
            AblationBlockSpec(
                "neighbor_only_historical_fundamentals",
                "Neighbor-only historical fundamentals",
                "Neighbor lagged load and generation-derived history signals.",
            ),
            AblationBlockSpec(
                "structural_capacity",
                "Structural capacity",
                "Installed-capacity summaries. In the active FS3 registry this block is neighbor-only.",
            ),
            AblationBlockSpec(
                "neighbor_price_proxy",
                "Neighbor-price proxy",
                "Neighbor day-ahead price lag signals used as proxy market context.",
            ),
        )
    elif scheme_name == SCHEME_NAME_LAYER_2:
        display_name = "Layer 2 subgroup follow-up"
        description = (
            "Optional subgroup ablation inside one selected Layer 1 block while keeping the full Layer 1 parent bundle fixed."
        )
        stage_name = "combo"
        layer_name = "layer2"
        block_specs = tuple(
            AblationBlockSpec(
                block_name=block_name,
                display_name=block_name.replace("_", " ").title(),
                description=f"Optional Layer 2 subgroup inside '{target_block}'.",
            )
            for block_name in block_map.keys()
        )
    else:
        raise ValueError(f"Unsupported scheme name: {scheme_name}")

    return AblationSchemeSpec(
        scheme_name=str(scheme_name),
        scheme_version=SCHEME_VERSION,
        stage_name=stage_name,
        layer_name=layer_name,
        display_name=display_name,
        description=description,
        target_block=str(target_block) if target_block else None,
        blocks=block_specs,
    )


def fs3_ablation_scheme_payload(
    experiment_map: dict[str, FS3Experiment],
    *,
    scheme_name: str,
    target_block: str | None = None,
) -> dict[str, object]:
    spec = fs3_ablation_scheme_spec(
        experiment_map,
        scheme_name=scheme_name,
        target_block=target_block,
    )
    block_map = fs3_ablation_block_map(
        experiment_map,
        scheme_name=scheme_name,
        target_block=target_block,
    )
    payload = {
        "scheme_name": spec.scheme_name,
        "scheme_version": spec.scheme_version,
        "stage_name": spec.stage_name,
        "layer_name": spec.layer_name,
        "display_name": spec.display_name,
        "description": spec.description,
        "target_block": spec.target_block,
        "blocks": [
            {
                "block_name": block_spec.block_name,
                "display_name": block_spec.display_name,
                "description": block_spec.description,
                "column_count": int(len(block_map.get(block_spec.block_name, ()))),
                "columns": list(block_map.get(block_spec.block_name, ())),
            }
            for block_spec in spec.blocks
        ],
    }
    payload["scheme_hash"] = _stable_hash(payload)
    payload["feature_taxonomy_hash"] = fs3_feature_taxonomy_hash(experiment_map)
    return payload
