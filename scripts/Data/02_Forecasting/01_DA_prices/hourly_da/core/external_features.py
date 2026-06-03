from __future__ import annotations

from datetime import timedelta
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import HourlyDAPipelineConfig, MARKET_TIMEZONES
from .time_utils import delivery_local_date_for_timestamp, known_at_utc_for_delivery_date


VALID_AVAILABILITY_CLASSES = (
    "historical_lagged_only",
    "future_known_day1_only",
    "future_known_full_horizon",
)

LAG_SOURCE_SUFFIX = "__lag_source"


@dataclass(frozen=True)
class FS3Experiment:
    code: str
    description: str
    direct_columns: tuple[str, ...] = ()
    lagged_columns: tuple[str, ...] = ()
    lag_hours: tuple[int, ...] = ()

    def all_required_columns(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for column in list(self.direct_columns) + list(self.lagged_columns):
            if column not in ordered:
                ordered.append(column)
        return tuple(ordered)


@dataclass(frozen=True)
class ExternalFeatureStore:
    values: pd.DataFrame
    known_at: pd.DataFrame
    experiments: tuple[FS3Experiment, ...]

    def experiment_map(self) -> dict[str, FS3Experiment]:
        return {experiment.code: experiment for experiment in self.experiments}


@dataclass(frozen=True)
class ExternalFamilyCatalogSpec:
    family_name: str
    family_kind: str
    source: str
    raw_resolution: str
    availability_class: str
    lead_scope: str
    allowed_usage_mode: str
    known_at_rule: str
    current_usage_mode: str
    current_issue_status: str
    cleaned_available_on_disk: bool
    expected_in_feature_store: bool
    store_suffixes: tuple[str, ...] = ()


EXTERNAL_FAMILY_CATALOG_SPECS: tuple[ExternalFamilyCatalogSpec, ...] = (
    ExternalFamilyCatalogSpec(
        family_name="actual_total_load",
        family_kind="cleaned_source",
        source="ENTSO-E actual total load",
        raw_resolution="PT15M",
        availability_class="historical_lagged_only",
        lead_scope="historical_lags_only",
        allowed_usage_mode="lagged_only",
        known_at_rule="actual_interval_end",
        current_usage_mode="lagged_active_via_load_history",
        current_issue_status="Usable only via causal lags. Current lagged-history experiments remain diagnostic until coverage handling is stabilized.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_actual_total_load_mw",),
    ),
    ExternalFamilyCatalogSpec(
        family_name="da_total_load_forecast",
        family_kind="cleaned_source",
        source="ENTSO-E day-ahead total load forecast",
        raw_resolution="PT15M",
        availability_class="future_known_day1_only",
        lead_scope="day1_only",
        allowed_usage_mode="direct_day1_only",
        known_at_rule="day_ahead_local_08",
        current_usage_mode="not_directly_active_indirect_via_load_forecast_error",
        current_issue_status="Needs the explicit day-1 branch before it can be used as a direct future regressor.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_da_total_load_forecast_mw",),
    ),
    ExternalFamilyCatalogSpec(
        family_name="week_ahead_total_load_forecast",
        family_kind="cleaned_source",
        source="ENTSO-E week-ahead total load forecast",
        raw_resolution="P1D expanded to hourly",
        availability_class="future_known_full_horizon",
        lead_scope="D_to_D+4",
        allowed_usage_mode="direct_full_horizon",
        known_at_rule="week_ahead_local_08",
        current_usage_mode="direct_active",
        current_issue_status="Currently the cleanest full-horizon FS3 family and the only fair like-for-like external baseline so far.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_week_ahead_total_load_forecast_mw",),
    ),
    ExternalFamilyCatalogSpec(
        family_name="da_generation_forecast",
        family_kind="cleaned_source",
        source="ENTSO-E day-ahead generation forecast",
        raw_resolution="PT60M",
        availability_class="future_known_day1_only",
        lead_scope="day1_only",
        allowed_usage_mode="direct_day1_only",
        known_at_rule="day_ahead_local_08",
        current_usage_mode="not_directly_active_indirect_via_generation_history",
        current_issue_status="Needs the explicit day-1 branch before it can be used as a direct future regressor.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_da_generation_forecast_mw",),
    ),
    ExternalFamilyCatalogSpec(
        family_name="actual_generation_by_psr",
        family_kind="cleaned_source",
        source="ENTSO-E actual generation by production type",
        raw_resolution="PT60M",
        availability_class="historical_lagged_only",
        lead_scope="historical_lags_only",
        allowed_usage_mode="aggregate_then_lagged_only",
        known_at_rule="actual_interval_end",
        current_usage_mode="aggregated_then_lagged",
        current_issue_status="Cleaned on disk, but the forecasting store keeps only lagged aggregate panels rather than raw PSR-level columns.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=False,
    ),
    ExternalFamilyCatalogSpec(
        family_name="installed_capacity_by_psr",
        family_kind="cleaned_source",
        source="ENTSO-E installed capacity by production type",
        raw_resolution="P1Y expanded to hourly",
        availability_class="future_known_full_horizon",
        lead_scope="D_to_D+4",
        allowed_usage_mode="aggregate_then_direct_full_horizon",
        known_at_rule="valid_from_utc",
        current_usage_mode="aggregated_then_direct",
        current_issue_status="Treated as known far enough in advance for the active D through D+4 horizon under the current installed-capacity availability assumption.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=False,
    ),
    ExternalFamilyCatalogSpec(
        family_name="actual_generation_aggregates",
        family_kind="derived_panel",
        source="Derived from actual_generation_by_psr",
        raw_resolution="PT60M aggregated to hourly panels",
        availability_class="historical_lagged_only",
        lead_scope="historical_lags_only",
        allowed_usage_mode="lagged_only",
        known_at_rule="actual_interval_end",
        current_usage_mode="lagged_active",
        current_issue_status="Active in generation-history experiments, but those runs are still diagnostic until lag-source handling is stabilized.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_actual_generation_total_mw", "_actual_generation_res_mw"),
    ),
    ExternalFamilyCatalogSpec(
        family_name="load_forecast_error",
        family_kind="derived_panel",
        source="Derived actual load minus DA total load forecast",
        raw_resolution="Derived hourly panel",
        availability_class="historical_lagged_only",
        lead_scope="historical_lags_only",
        allowed_usage_mode="lagged_only",
        known_at_rule="max(actual_interval_end, day_ahead_local_08)",
        current_usage_mode="lagged_active",
        current_issue_status="Causally safe only when lagged. The explicit day-1 branch is required before related direct DA load features can be tested fairly.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_load_forecast_error_mw",),
    ),
    ExternalFamilyCatalogSpec(
        family_name="gen_minus_actual_load",
        family_kind="derived_panel",
        source="Derived DA generation forecast minus actual load",
        raw_resolution="Derived hourly panel",
        availability_class="historical_lagged_only",
        lead_scope="historical_lags_only",
        allowed_usage_mode="lagged_only",
        known_at_rule="max(day_ahead_local_08, actual_interval_end)",
        current_usage_mode="lagged_active",
        current_issue_status="Causally safe only when lagged. The explicit day-1 branch is required before related direct DA generation features can be tested fairly.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_gen_minus_actual_load_mw",),
    ),
    ExternalFamilyCatalogSpec(
        family_name="installed_capacity_aggregates",
        family_kind="derived_panel",
        source="Derived from installed_capacity_by_psr",
        raw_resolution="P1Y expanded to hourly aggregates",
        availability_class="future_known_full_horizon",
        lead_scope="D_to_D+4",
        allowed_usage_mode="direct_full_horizon",
        known_at_rule="valid_from_utc",
        current_usage_mode="direct_active",
        current_issue_status="Active under the current methodology assumption that installed-capacity aggregates are known across the active D through D+4 horizon.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=(
            "_installed_capacity_total_mw",
            "_installed_capacity_res_mw",
            "_installed_capacity_wind_mw",
            "_installed_capacity_solar_mw",
        ),
    ),
    ExternalFamilyCatalogSpec(
        family_name="neighbor_da_prices",
        family_kind="peer_market_panel",
        source="Existing cleaned DA price pipeline for neighboring markets",
        raw_resolution="PT60M",
        availability_class="historical_lagged_only",
        lead_scope="historical_lags_only",
        allowed_usage_mode="lagged_only",
        known_at_rule="known_at_utc_for_delivery_date",
        current_usage_mode="lagged_active",
        current_issue_status="Currently non-comparable because source gaps and recursive NaN propagation collapse coverage by later lead days.",
        cleaned_available_on_disk=True,
        expected_in_feature_store=True,
        store_suffixes=("_da_price_eur_per_mwh",),
    ),
)


def _ensure_datetime_index(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").drop_duplicates(subset=["timestamp_utc"])
    return frame.set_index("timestamp_utc")


def _load_long_family(long_csv_path: Path, family_name: str, has_psr_dimension: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(long_csv_path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["known_at_utc"] = pd.to_datetime(frame["known_at_utc"], utc=True, errors="coerce")
    frame["value_mw"] = pd.to_numeric(frame["value_mw"], errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).copy()

    if has_psr_dimension:
        frame["column_key"] = frame.apply(
            lambda row: f"{row['market']}_{row['psr_type']}_{str(row['psr_label']).strip().replace(' ', '_').lower()}_mw",
            axis=1,
        )
    else:
        frame["column_key"] = frame["market"].map(lambda market: f"{market}_{family_name}_mw")

    value_panel = frame.pivot_table(index="timestamp_utc", columns="column_key", values="value_mw", aggfunc="last").sort_index()
    known_panel = frame.pivot_table(index="timestamp_utc", columns="column_key", values="known_at_utc", aggfunc="last").sort_index()
    value_panel.columns.name = None
    known_panel.columns.name = None
    return value_panel, known_panel


def _load_neighbor_price_panel(config: HourlyDAPipelineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(config.input_csv)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame[config.target_col] = pd.to_numeric(frame[config.target_col], errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).copy()

    values: dict[str, pd.Series] = {}
    known_at: dict[str, pd.Series] = {}
    for market in sorted(frame["region"].dropna().unique()):
        market_frame = frame[frame["region"] == market].copy().sort_values("timestamp_utc")
        column = f"{market}_da_price_eur_per_mwh"
        values[column] = market_frame.set_index("timestamp_utc")[config.target_col].astype(float)

        market_config = HourlyDAPipelineConfig(market_area=market)
        known_series = pd.Series(
            [
                known_at_utc_for_delivery_date(
                    delivery_local_date_for_timestamp(timestamp, MARKET_TIMEZONES[market]),
                    market_config,
                )
                for timestamp in market_frame["timestamp_utc"]
            ],
            index=pd.DatetimeIndex(market_frame["timestamp_utc"]),
        )
        known_at[column] = known_series

    return pd.DataFrame(values).sort_index(), pd.DataFrame(known_at).sort_index()


def _sum_selected_columns(
    values: pd.DataFrame,
    known_at: pd.DataFrame,
    markets: list[str],
    base_name: str,
    selector,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out_values: dict[str, pd.Series] = {}
    out_known: dict[str, pd.Series] = {}
    for market in markets:
        columns = [column for column in values.columns if selector(market, column)]
        if not columns:
            continue
        out_values[f"{market}_{base_name}"] = values[columns].sum(axis=1, min_count=1)
        out_known[f"{market}_{base_name}"] = known_at[columns].max(axis=1)
    return pd.DataFrame(out_values).sort_index(), pd.DataFrame(out_known).sort_index()


def _derive_generation_aggregates(
    base_values: pd.DataFrame,
    base_known_at: pd.DataFrame,
    markets: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    total_values, total_known = _sum_selected_columns(
        base_values,
        base_known_at,
        markets,
        base_name="actual_generation_total_mw",
        selector=lambda market, column: column.startswith(f"{market}_"),
    )
    res_values, res_known = _sum_selected_columns(
        base_values,
        base_known_at,
        markets,
        base_name="actual_generation_res_mw",
        selector=lambda market, column: column.startswith(f"{market}_")
        and any(token in column for token in ["_B16_", "_B18_", "_B19_"]),
    )
    return (
        pd.concat([total_values, res_values], axis=1).sort_index(),
        pd.concat([total_known, res_known], axis=1).sort_index(),
    )


def _derive_installed_capacity_aggregates(
    base_values: pd.DataFrame,
    base_known_at: pd.DataFrame,
    markets: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    total_values, total_known = _sum_selected_columns(
        base_values,
        base_known_at,
        markets,
        base_name="installed_capacity_total_mw",
        selector=lambda market, column: column.startswith(f"{market}_"),
    )
    res_values, res_known = _sum_selected_columns(
        base_values,
        base_known_at,
        markets,
        base_name="installed_capacity_res_mw",
        selector=lambda market, column: column.startswith(f"{market}_")
        and any(token in column for token in ["_B16_", "_B18_", "_B19_"]),
    )
    wind_values, wind_known = _sum_selected_columns(
        base_values,
        base_known_at,
        markets,
        base_name="installed_capacity_wind_mw",
        selector=lambda market, column: column.startswith(f"{market}_")
        and any(token in column for token in ["_B18_", "_B19_"]),
    )
    solar_values, solar_known = _sum_selected_columns(
        base_values,
        base_known_at,
        markets,
        base_name="installed_capacity_solar_mw",
        selector=lambda market, column: column.startswith(f"{market}_") and "_B16_" in column,
    )
    return (
        pd.concat([total_values, res_values, wind_values, solar_values], axis=1).sort_index(),
        pd.concat([total_known, res_known, wind_known, solar_known], axis=1).sort_index(),
    )


def _derive_difference_panel(
    left_values: pd.DataFrame,
    left_known_at: pd.DataFrame,
    right_values: pd.DataFrame,
    right_known_at: pd.DataFrame,
    suffix: str,
    markets: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out_values: dict[str, pd.Series] = {}
    out_known: dict[str, pd.Series] = {}
    for market in markets:
        left_column = next((column for column in left_values.columns if column.startswith(f"{market}_")), None)
        right_column = next((column for column in right_values.columns if column.startswith(f"{market}_")), None)
        if left_column is None or right_column is None:
            continue
        out_values[f"{market}_{suffix}"] = left_values[left_column] - right_values[right_column]
        out_known[f"{market}_{suffix}"] = pd.concat(
            [left_known_at[left_column], right_known_at[right_column]],
            axis=1,
        ).max(axis=1)
    return pd.DataFrame(out_values).sort_index(), pd.DataFrame(out_known).sort_index()


def _join_panels(panels: list[tuple[pd.DataFrame, pd.DataFrame]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    value_frames = [value for value, _ in panels if not value.empty]
    known_frames = [known for _, known in panels if not known.empty]
    value_panel = pd.concat(value_frames, axis=1).sort_index() if value_frames else pd.DataFrame()
    known_panel = pd.concat(known_frames, axis=1).sort_index() if known_frames else pd.DataFrame()
    value_panel = value_panel.loc[:, ~value_panel.columns.duplicated()].sort_index(axis=1)
    known_panel = known_panel.loc[:, ~known_panel.columns.duplicated()].sort_index(axis=1)
    return value_panel, known_panel


def lag_source_column_name(column: str) -> str:
    return f"{column}{LAG_SOURCE_SUFFIX}"


def _compress_known_at_to_value_block_start(values: pd.DataFrame, known_at: pd.DataFrame) -> pd.DataFrame:
    corrected = known_at.copy()
    for column in values.columns:
        series = values[column]
        if series.dropna().empty:
            continue
        block_id = series.ne(series.shift()).cumsum()
        corrected_series = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
        for _, block in series.groupby(block_id, dropna=False):
            valid = block.dropna()
            if valid.empty:
                continue
            corrected_series.loc[block.index] = valid.index[0]
        corrected[column] = corrected_series
    return corrected


def _gap_fill_within_observed_support(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    valid = values.dropna()
    if valid.empty:
        return values
    start = valid.index[0]
    end = valid.index[-1]
    filled = values.copy()
    window = filled.loc[start:end].interpolate(method="time", limit_direction="both").ffill().bfill()
    filled.loc[start:end] = window
    return filled


def _shift_known_at_back_one_local_day(index: pd.DatetimeIndex, market: str) -> pd.Series:
    market_config = HourlyDAPipelineConfig(market_area=market)
    timezone = MARKET_TIMEZONES[market]
    return pd.Series(
        [
            known_at_utc_for_delivery_date(
                delivery_local_date_for_timestamp(timestamp, timezone) - timedelta(days=1),
                market_config,
            )
            for timestamp in index
        ],
        index=index,
    )


def _correct_day_ahead_known_at(values: pd.DataFrame, known_at: pd.DataFrame) -> pd.DataFrame:
    corrected = known_at.copy()
    for column in values.columns:
        market = column.split("_", 1)[0]
        corrected[column] = _shift_known_at_back_one_local_day(values.index, market)
    return corrected


def _correct_full_horizon_known_at(
    values: pd.DataFrame,
    known_at: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    days_before_target: int | None = None,
) -> pd.DataFrame:
    corrected = known_at.copy()
    days_back = int(days_before_target if days_before_target is not None else config.forecast_horizon_days)
    for column in values.columns:
        market = column.split("_", 1)[0]
        market_config = HourlyDAPipelineConfig(market_area=market)
        timezone = MARKET_TIMEZONES[market]
        corrected[column] = pd.Series(
            [
                known_at_utc_for_delivery_date(
                    delivery_local_date_for_timestamp(timestamp, timezone) - timedelta(days=days_back),
                    market_config,
                )
                for timestamp in values.index
            ],
            index=values.index,
        )
    return corrected


def _available_markets(config: HourlyDAPipelineConfig) -> list[str]:
    return ["BE", "DE", "NL"]


def _neighbor_markets(config: HourlyDAPipelineConfig) -> list[str]:
    return [market for market in _available_markets(config) if market != config.market_area]


def _fs3_candidate_experiments(config: HourlyDAPipelineConfig) -> tuple[FS3Experiment, ...]:
    domestic = config.market_area
    neighbors = _neighbor_markets(config)
    safe_lags = tuple(config.exogenous_safe_lags_hours)

    return (
        FS3Experiment(
            code="wa_load_domestic",
            description="Domestic week-ahead total load forecast.",
            direct_columns=(f"{domestic}_week_ahead_total_load_forecast_mw",),
        ),
        FS3Experiment(
            code="wa_load_crossborder",
            description="Neighboring week-ahead total load forecasts only.",
            direct_columns=tuple(f"{market}_week_ahead_total_load_forecast_mw" for market in neighbors),
        ),
        FS3Experiment(
            code="da_load_day1_domestic",
            description="Domestic day-ahead total load forecast for the explicit D-only branch.",
            direct_columns=(f"{domestic}_da_total_load_forecast_mw",),
        ),
        FS3Experiment(
            code="da_load_day1_crossborder",
            description="Neighboring day-ahead total load forecasts only for the explicit D-only branch.",
            direct_columns=tuple(f"{market}_da_total_load_forecast_mw" for market in neighbors),
        ),
        FS3Experiment(
            code="da_generation_day1_domestic",
            description="Domestic day-ahead generation forecast for the explicit D-only branch.",
            direct_columns=(f"{domestic}_da_generation_forecast_mw",),
        ),
        FS3Experiment(
            code="da_generation_day1_crossborder",
            description="Neighboring day-ahead generation forecasts only for the explicit D-only branch.",
            direct_columns=tuple(f"{market}_da_generation_forecast_mw" for market in neighbors),
        ),
        FS3Experiment(
            code="load_history_domestic",
            description="Domestic lagged actual load and lagged load-forecast error using weekly-safe lags.",
            lagged_columns=(f"{domestic}_actual_total_load_mw", f"{domestic}_load_forecast_error_mw"),
            lag_hours=safe_lags,
        ),
        FS3Experiment(
            code="load_history_crossborder",
            description="Neighboring lagged actual load and lagged load-forecast errors only.",
            lagged_columns=tuple(
                column
                for market in neighbors
                for column in (f"{market}_actual_total_load_mw", f"{market}_load_forecast_error_mw")
            ),
            lag_hours=safe_lags,
        ),
        FS3Experiment(
            code="generation_history_domestic",
            description="Domestic lagged generation regime indicators: total, RES, DA generation, and DA generation minus actual load.",
            lagged_columns=(
                f"{domestic}_actual_generation_total_mw",
                f"{domestic}_actual_generation_res_mw",
                f"{domestic}_da_generation_forecast_mw",
                f"{domestic}_gen_minus_actual_load_mw",
            ),
            lag_hours=safe_lags,
        ),
        FS3Experiment(
            code="generation_history_crossborder",
            description="Neighboring lagged generation regime indicators only.",
            lagged_columns=tuple(
                column
                for market in neighbors
                for column in (
                    f"{market}_actual_generation_total_mw",
                    f"{market}_actual_generation_res_mw",
                    f"{market}_da_generation_forecast_mw",
                    f"{market}_gen_minus_actual_load_mw",
                )
            ),
            lag_hours=safe_lags,
        ),
        FS3Experiment(
            code="installed_capacity_crossborder",
            description="Neighboring installed-capacity summaries only.",
            direct_columns=tuple(
                column
                for market in neighbors
                for column in (
                    f"{market}_installed_capacity_total_mw",
                    f"{market}_installed_capacity_res_mw",
                    f"{market}_installed_capacity_wind_mw",
                    f"{market}_installed_capacity_solar_mw",
                )
            ),
        ),
        FS3Experiment(
            code="neighbor_price_weekly",
            description="Neighboring day-ahead price weekly-safe lags.",
            lagged_columns=tuple(f"{market}_da_price_eur_per_mwh" for market in neighbors),
            lag_hours=safe_lags,
        ),
    )


def _fs3_family_group(experiment_code: str) -> str:
    if experiment_code.startswith("wa_") or experiment_code == "installed_capacity_crossborder":
        return "full_horizon"
    if experiment_code.startswith("da_"):
        return "day1_only"
    return "historical"


def fs3_taxonomy_inventory_frame(config: HourlyDAPipelineConfig, store: ExternalFeatureStore) -> pd.DataFrame:
    available_columns = set(store.values.columns)
    rows: list[dict[str, object]] = []
    for candidate in _fs3_candidate_experiments(config):
        required_columns = list(candidate.all_required_columns())
        available_required = [column for column in required_columns if column in available_columns]
        missing_required = [column for column in required_columns if column not in available_columns]
        currently_available = len(required_columns) > 0 and not missing_required
        if currently_available:
            availability_reason = "all_required_columns_present"
        elif available_required:
            availability_reason = "partially_available_missing_required_columns"
        else:
            availability_reason = "no_required_columns_present"
        rows.append(
            {
                "experiment_name": candidate.code,
                "family_group": _fs3_family_group(candidate.code),
                "defined_in_code": True,
                "currently_available": bool(currently_available),
                "availability_reason": availability_reason,
                "missing_requirements": ", ".join(missing_required),
                "required_column_count": int(len(required_columns)),
                "available_required_column_count": int(len(available_required)),
                "missing_required_column_count": int(len(missing_required)),
                "direct_column_count": int(len(candidate.direct_columns)),
                "lagged_column_count": int(len(candidate.lagged_columns)),
                "lag_hours": ", ".join(str(hour) for hour in candidate.lag_hours),
                "description": candidate.description,
            }
        )
    return pd.DataFrame(rows).sort_values(["family_group", "experiment_name"]).reset_index(drop=True)


def build_fs3_experiments(config: HourlyDAPipelineConfig, store: ExternalFeatureStore) -> tuple[FS3Experiment, ...]:
    candidates = _fs3_candidate_experiments(config)

    available_columns = set(store.values.columns)
    experiments: list[FS3Experiment] = []
    for candidate in candidates:
        direct_columns = tuple(column for column in candidate.direct_columns if column in available_columns)
        lagged_columns = tuple(column for column in candidate.lagged_columns if column in available_columns)
        if not direct_columns and not lagged_columns:
            continue
        experiments.append(
            FS3Experiment(
                code=candidate.code,
                description=candidate.description,
                direct_columns=direct_columns,
                lagged_columns=lagged_columns,
                lag_hours=candidate.lag_hours,
            )
        )
    return tuple(experiments)


def build_external_family_catalog(config: HourlyDAPipelineConfig, store: ExternalFeatureStore) -> pd.DataFrame:
    available_columns = [column for column in store.values.columns if column != config.timestamp_col]
    active_direct_lookup: dict[str, list[str]] = {}
    active_lagged_lookup: dict[str, list[str]] = {}
    for experiment in store.experiments:
        for column in experiment.direct_columns:
            active_direct_lookup.setdefault(column, []).append(experiment.code)
        for column in experiment.lagged_columns:
            active_lagged_lookup.setdefault(column, []).append(experiment.code)

    rows: list[dict[str, object]] = []
    for spec in EXTERNAL_FAMILY_CATALOG_SPECS:
        if spec.availability_class not in VALID_AVAILABILITY_CLASSES:
            raise ValueError(f"Unsupported availability_class in external family catalog: {spec.availability_class}")

        matching_columns = (
            sorted(
                column
                for column in available_columns
                if any(column.endswith(suffix) for suffix in spec.store_suffixes)
            )
            if spec.store_suffixes
            else []
        )
        direct_experiments = sorted(
            {
                experiment_code
                for column in matching_columns
                for experiment_code in active_direct_lookup.get(column, [])
            }
        )
        lagged_experiments = sorted(
            {
                experiment_code
                for column in matching_columns
                for experiment_code in active_lagged_lookup.get(column, [])
            }
        )
        if direct_experiments and lagged_experiments:
            experiment_usage_mode = "direct_and_lagged_active"
        elif direct_experiments:
            experiment_usage_mode = "direct_active"
        elif lagged_experiments:
            experiment_usage_mode = "lagged_active"
        elif matching_columns:
            experiment_usage_mode = "available_not_active"
        else:
            experiment_usage_mode = "not_present_in_store"

        rows.append(
            {
                "market_area": config.market_area,
                "family_name": spec.family_name,
                "family_kind": spec.family_kind,
                "source": spec.source,
                "raw_resolution": spec.raw_resolution,
                "availability_class": spec.availability_class,
                "lead_scope": spec.lead_scope,
                "allowed_usage_mode": spec.allowed_usage_mode,
                "known_at_rule": spec.known_at_rule,
                "cleaned_available_on_disk": bool(spec.cleaned_available_on_disk),
                "available_in_feature_store": bool(matching_columns),
                "expected_in_feature_store": bool(spec.expected_in_feature_store),
                "available_column_count": int(len(matching_columns)),
                "available_column_examples": ", ".join(matching_columns[:6]),
                "active_direct_experiments": ", ".join(direct_experiments),
                "active_lagged_experiments": ", ".join(lagged_experiments),
                "experiment_usage_mode": experiment_usage_mode,
                "current_usage_mode": spec.current_usage_mode,
                "current_issue_status": spec.current_issue_status,
            }
        )
    return pd.DataFrame(rows).sort_values(["availability_class", "family_name"]).reset_index(drop=True)


def load_external_feature_store(config: HourlyDAPipelineConfig) -> ExternalFeatureStore:
    feature_root = Path(config.cleaned_feature_root)
    markets = _available_markets(config)

    actual_load_values, actual_load_known = _load_long_family(
        feature_root / "Load/actual_total_load/hourly/actual_total_load_hourly_long.csv",
        family_name="actual_total_load",
        has_psr_dimension=False,
    )
    da_load_values, da_load_known = _load_long_family(
        feature_root / "Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv",
        family_name="da_total_load_forecast",
        has_psr_dimension=False,
    )
    da_load_known = _correct_day_ahead_known_at(da_load_values, da_load_known)
    wa_load_values, wa_load_known = _load_long_family(
        feature_root / "Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv",
        family_name="week_ahead_total_load_forecast",
        has_psr_dimension=False,
    )
    da_generation_values, da_generation_known = _load_long_family(
        feature_root / "Generation/da_generation_forecast/hourly/da_generation_forecast_hourly_long.csv",
        family_name="da_generation_forecast",
        has_psr_dimension=False,
    )
    da_generation_known = _correct_day_ahead_known_at(da_generation_values, da_generation_known)
    generation_psr_values, generation_psr_known = _load_long_family(
        feature_root / "Generation/actual_generation_by_psr/hourly/actual_generation_by_psr_hourly_long.csv",
        family_name="actual_generation_by_psr",
        has_psr_dimension=True,
    )
    installed_values, installed_known = _load_long_family(
        feature_root / "Generation/installed_capacity_by_psr/hourly/installed_capacity_by_psr_hourly_long.csv",
        family_name="installed_capacity_by_psr",
        has_psr_dimension=True,
    )
    installed_known = _correct_full_horizon_known_at(installed_values, installed_known, config)

    generation_agg_values, generation_agg_known = _derive_generation_aggregates(generation_psr_values, generation_psr_known, markets)
    installed_agg_values, installed_agg_known = _derive_installed_capacity_aggregates(installed_values, installed_known, markets)
    load_error_values, load_error_known = _derive_difference_panel(
        left_values=actual_load_values,
        left_known_at=actual_load_known,
        right_values=da_load_values,
        right_known_at=da_load_known,
        suffix="load_forecast_error_mw",
        markets=markets,
    )
    gen_minus_load_values, gen_minus_load_known = _derive_difference_panel(
        left_values=da_generation_values,
        left_known_at=da_generation_known,
        right_values=actual_load_values,
        right_known_at=actual_load_known,
        suffix="gen_minus_actual_load_mw",
        markets=markets,
    )
    neighbor_price_values, neighbor_price_known = _load_neighbor_price_panel(config)

    values, known_at = _join_panels(
        [
            (actual_load_values, actual_load_known),
            (da_load_values, da_load_known),
            (wa_load_values, wa_load_known),
            (da_generation_values, da_generation_known),
            (generation_agg_values, generation_agg_known),
            (installed_agg_values, installed_agg_known),
            (load_error_values, load_error_known),
            (gen_minus_load_values, gen_minus_load_known),
            (neighbor_price_values, neighbor_price_known),
        ]
    )

    values = values.sort_index().reset_index()
    known_at = known_at.sort_index().reset_index()
    values = _ensure_datetime_index(values).reset_index()
    known_at = _ensure_datetime_index(known_at).reset_index()
    store = ExternalFeatureStore(values=values, known_at=known_at, experiments=())
    experiments = build_fs3_experiments(config, store)
    return ExternalFeatureStore(values=values, known_at=known_at, experiments=experiments)


def build_feature_context_for_origin(
    store: ExternalFeatureStore,
    forecast_origin_utc: pd.Timestamp,
) -> pd.DataFrame:
    values = _ensure_datetime_index(store.values)
    known_at = _ensure_datetime_index(store.known_at)
    masked = values.where(known_at.le(forecast_origin_utc))
    direct_columns = sorted(
        {
            column
            for experiment in store.experiments
            for column in experiment.direct_columns
            if column in masked.columns
        }
    )
    for column in direct_columns:
        masked[column] = _gap_fill_within_observed_support(masked[column])
    lagged_columns = sorted({column for experiment in store.experiments for column in experiment.lagged_columns if column in masked.columns})
    for column in lagged_columns:
        masked[lag_source_column_name(column)] = _gap_fill_within_observed_support(masked[column])
    masked = masked.reset_index()
    return masked
