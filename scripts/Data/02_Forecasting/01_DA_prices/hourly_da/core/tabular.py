from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import HourlyDAPipelineConfig
from .ablation_blocks import filter_fs2_columns_by_ablation_scheme, filter_fs3_columns_by_ablation_scheme
from .endogenous_features import (
    build_endogenous_explicit_features,
    build_endogenous_feature_row,
    endogenous_explicit_feature_names,
    endogenous_required_history_hours,
)
from .external_features import FS3Experiment, lag_source_column_name
from .feature_families import filter_feature_columns
from .features import build_calendar_features


def endogenous_feature_names() -> list[str]:
    return endogenous_explicit_feature_names()


def calendar_feature_names() -> list[str]:
    return ["hour_of_day", "day_of_week", "is_weekend", "month", "is_dutch_holiday"]


def fs3_feature_names(experiment: FS3Experiment) -> list[str]:
    columns = list(experiment.direct_columns)
    for column in experiment.lagged_columns:
        for lag in experiment.lag_hours:
            columns.append(f"{column}_lag_{lag}")
    return columns


def feature_columns_for_fs_level(
    config: HourlyDAPipelineConfig,
    fs_level: str,
    fs3_experiment: FS3Experiment | None = None,
    model_family: str = "lear",
    excluded_feature_families: tuple[str, ...] | list[str] | None = None,
    excluded_feature_columns: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
) -> list[str]:
    always_excluded = {str(value) for value in (excluded_feature_columns or ())}
    if fs_level == "FS1":
        columns = endogenous_feature_names()
        selected = filter_feature_columns(
            columns,
            fs_level=fs_level,
            model_family=model_family,
            excluded_feature_families=excluded_feature_families,
        )
        return [column for column in selected if column not in always_excluded]
    if fs_level == "FS2":
        columns = endogenous_feature_names() + calendar_feature_names()
        if ablation_scheme_name:
            selected = filter_fs2_columns_by_ablation_scheme(
                columns,
                excluded_blocks=excluded_feature_families,
                scheme_name=ablation_scheme_name,
                target_block=ablation_target_block,
            )
            return [column for column in selected if column not in always_excluded]
        selected = filter_feature_columns(
            columns,
            fs_level=fs_level,
            model_family=model_family,
            excluded_feature_families=excluded_feature_families,
        )
        return [column for column in selected if column not in always_excluded]
    if fs_level == "FS3":
        if fs3_experiment is None:
            raise ValueError("FS3 requires an experiment definition.")
        columns = endogenous_feature_names() + calendar_feature_names() + fs3_feature_names(fs3_experiment)
        selected = filter_fs3_columns_by_ablation_scheme(
            columns,
            domestic_market=str(config.market_area),
            excluded_blocks=excluded_feature_families,
            scheme_name=ablation_scheme_name,
            target_block=ablation_target_block,
        )
        return [column for column in selected if column not in always_excluded]
    raise ValueError(f"Unsupported tabular feature set level: {fs_level}")


@dataclass(frozen=True)
class TabularTrainingData:
    feature_frame: pd.DataFrame
    X: pd.DataFrame
    y: pd.Series
    feature_columns: list[str]


def build_training_data(
    history: pd.DataFrame,
    config: HourlyDAPipelineConfig,
    fs_level: str,
    feature_context: pd.DataFrame | None = None,
    fs3_experiment: FS3Experiment | None = None,
    history_window_hours: int | None = None,
    model_family: str = "lear",
    excluded_feature_families: tuple[str, ...] | list[str] | None = None,
    excluded_feature_columns: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
) -> TabularTrainingData:
    work = (
        history[[config.timestamp_col, config.target_col, config.feature_source_col]]
        .copy()
        .sort_values(config.timestamp_col)
        .reset_index(drop=True)
    )
    required_history_hours = endogenous_required_history_hours(config)
    if history_window_hours is not None and history_window_hours > 0:
        keep_rows = max(history_window_hours + required_history_hours, required_history_hours + 24)
        work = work.iloc[-keep_rows:].reset_index(drop=True)

    work = build_endogenous_explicit_features(work, config)

    if fs_level in {"FS2", "FS3"}:
        calendar = build_calendar_features(pd.DatetimeIndex(work[config.timestamp_col]), config)
        work = work.merge(calendar, left_on=config.timestamp_col, right_on="target_timestamp_utc", how="left")
        work = work.drop(columns=["target_timestamp_utc"])

    if fs_level == "FS3":
        if feature_context is None or fs3_experiment is None:
            raise ValueError("FS3 requires feature_context and fs3_experiment in build_training_data.")
        context_indexed = feature_context.set_index(config.timestamp_col).sort_index()
        aligned_index = pd.DatetimeIndex(work[config.timestamp_col])
        for column in fs3_experiment.direct_columns:
            series = (
                context_indexed[column]
                if column in context_indexed.columns
                else pd.Series(index=context_indexed.index, dtype=float)
            )
            work[column] = series.reindex(aligned_index).to_numpy(dtype=float)
        for column in fs3_experiment.lagged_columns:
            source_column = lag_source_column_name(column) if lag_source_column_name(column) in context_indexed.columns else column
            source = (
                context_indexed[source_column]
                if source_column in context_indexed.columns
                else pd.Series(index=context_indexed.index, dtype=float)
            )
            aligned_source = source.reindex(aligned_index)
            for lag in fs3_experiment.lag_hours:
                work[f"{column}_lag_{lag}"] = aligned_source.shift(lag).to_numpy(dtype=float)

    feature_columns = feature_columns_for_fs_level(
        config,
        fs_level,
        fs3_experiment=fs3_experiment,
        model_family=model_family,
        excluded_feature_families=excluded_feature_families,
        excluded_feature_columns=excluded_feature_columns,
        ablation_scheme_name=ablation_scheme_name,
        ablation_target_block=ablation_target_block,
    )
    work["y"] = work[config.target_col].astype(float)
    training = work.dropna(subset=["y"] + feature_columns).reset_index(drop=True)
    X = training[feature_columns].astype(float)
    y = training["y"].astype(float)
    return TabularTrainingData(feature_frame=training, X=X, y=y, feature_columns=feature_columns)


def build_recursive_feature_row(
    timestamp_utc: pd.Timestamp,
    working_series: pd.Series,
    config: HourlyDAPipelineConfig,
    fs_level: str,
    feature_context: pd.DataFrame | None = None,
    fs3_experiment: FS3Experiment | None = None,
    model_family: str = "lear",
    excluded_feature_families: tuple[str, ...] | list[str] | None = None,
    excluded_feature_columns: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
) -> pd.DataFrame:
    row = build_endogenous_feature_row(timestamp_utc=timestamp_utc, working_series=working_series)

    if fs_level in {"FS2", "FS3"}:
        calendar = (
            build_calendar_features(pd.DatetimeIndex([timestamp_utc]), config)
            .drop(columns=["target_timestamp_utc"])
            .iloc[0]
            .to_dict()
        )
        row.update({key: float(value) for key, value in calendar.items()})

    if fs_level == "FS3":
        if feature_context is None or fs3_experiment is None:
            raise ValueError("FS3 requires feature_context and fs3_experiment in build_recursive_feature_row.")
        context_indexed = feature_context.set_index(config.timestamp_col).sort_index()
        for column in fs3_experiment.direct_columns:
            if column not in context_indexed.columns:
                row[column] = np.nan
                continue
            row[column] = float(context_indexed[column].get(timestamp_utc, np.nan))
        for column in fs3_experiment.lagged_columns:
            source_column = lag_source_column_name(column) if lag_source_column_name(column) in context_indexed.columns else column
            if source_column not in context_indexed.columns:
                for lag in fs3_experiment.lag_hours:
                    row[f"{column}_lag_{lag}"] = np.nan
                continue
            source_series = context_indexed[source_column]
            for lag in fs3_experiment.lag_hours:
                source_timestamp = timestamp_utc - pd.Timedelta(hours=lag)
                row[f"{column}_lag_{lag}"] = float(source_series.get(source_timestamp, np.nan))

    feature_row = pd.DataFrame([row])
    feature_columns = feature_columns_for_fs_level(
        config,
        fs_level,
        fs3_experiment=fs3_experiment,
        model_family=model_family,
        excluded_feature_families=excluded_feature_families,
        excluded_feature_columns=excluded_feature_columns,
        ablation_scheme_name=ablation_scheme_name,
        ablation_target_block=ablation_target_block,
    )
    return feature_row[feature_columns]
