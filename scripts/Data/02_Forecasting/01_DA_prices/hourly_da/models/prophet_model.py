from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.config import HourlyDAPipelineConfig
from ..core.external_features import FS3Experiment
from ..core.tabular import build_recursive_feature_row, build_training_data, feature_columns_for_fs_level
from .base import ForecastModel


def _prophet_ds(values: pd.Series | pd.DatetimeIndex) -> pd.Series:
    timestamps = pd.DatetimeIndex(values)
    return pd.Series(timestamps.tz_convert("UTC").tz_localize(None))


@dataclass(frozen=True)
class ProphetSettings:
    fs_level: str = "FS2"
    fs3_experiment: FS3Experiment | None = None
    excluded_feature_families: tuple[str, ...] = ()
    excluded_feature_columns: tuple[str, ...] = ()
    ablation_scheme_name: str | None = None
    ablation_target_block: str | None = None
    training_window_hours: int = 24 * 90
    min_train_rows: int = 24 * 30
    seasonality_mode: str = "multiplicative"
    changepoint_prior_scale: float = 0.05
    seasonality_prior_scale: float = 10.0
    holidays_prior_scale: float = 10.0
    daily_seasonality: bool = True
    weekly_seasonality: bool = True
    yearly_seasonality: bool = False
    n_changepoints: int = 25
    changepoint_range: float = 0.8


class ProphetModel(ForecastModel):
    def __init__(self, settings: ProphetSettings):
        if settings.fs_level == "FS1":
            raise ValueError("Prophet is not part of FS1 in the active DAM methodology.")
        model_name = f"prophet_{settings.fs_level.lower()}"
        if settings.fs_level == "FS3" and settings.fs3_experiment is not None:
            model_name = f"{model_name}_{settings.fs3_experiment.code}"
        super().__init__(name=model_name, family="prophet", fs_level=settings.fs_level)
        self.settings = settings
        self._model = None
        self._regressor_columns: list[str] = []
        self._fit_failed = False

    def fit(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> None:
        training_data = build_training_data(
            history=history,
            config=config,
            fs_level=self.settings.fs_level,
            feature_context=feature_context,
            fs3_experiment=self.settings.fs3_experiment,
            history_window_hours=self.settings.training_window_hours,
            model_family=self.family,
            excluded_feature_families=self.settings.excluded_feature_families,
            excluded_feature_columns=self.settings.excluded_feature_columns,
            ablation_scheme_name=self.settings.ablation_scheme_name,
            ablation_target_block=self.settings.ablation_target_block,
        )
        self._regressor_columns = feature_columns_for_fs_level(
            config,
            self.settings.fs_level,
            fs3_experiment=self.settings.fs3_experiment,
            model_family=self.family,
            excluded_feature_families=self.settings.excluded_feature_families,
            excluded_feature_columns=self.settings.excluded_feature_columns,
            ablation_scheme_name=self.settings.ablation_scheme_name,
            ablation_target_block=self.settings.ablation_target_block,
        )
        if training_data.X.shape[0] < self.settings.min_train_rows:
            self._model = None
            self._fit_failed = True
            self._set_runtime_info(
                {
                    "fit_failed": True,
                    "train_rows": int(training_data.X.shape[0]),
                    "regressor_count": len(self._regressor_columns),
                    "excluded_feature_families": list(self.settings.excluded_feature_families),
                    "excluded_feature_columns": list(self.settings.excluded_feature_columns),
                    "ablation_scheme_name": self.settings.ablation_scheme_name,
                    "ablation_target_block": self.settings.ablation_target_block,
                    "fs3_experiment": self.settings.fs3_experiment.code if self.settings.fs3_experiment else None,
                    "settings_json": json.dumps(self.settings.__dict__, sort_keys=True, default=str),
                }
            )
            return

        try:
            from prophet import Prophet
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise ImportError(
                "ProphetModel requires the 'prophet' package. Install it before running the Prophet benchmark."
            ) from exc

        train_frame = training_data.feature_frame[[config.timestamp_col, "y", *self._regressor_columns]].copy()
        train_frame["ds"] = _prophet_ds(train_frame[config.timestamp_col])
        train_frame = train_frame.drop(columns=[config.timestamp_col])

        model = Prophet(
            seasonality_mode=self.settings.seasonality_mode,
            changepoint_prior_scale=self.settings.changepoint_prior_scale,
            seasonality_prior_scale=self.settings.seasonality_prior_scale,
            holidays_prior_scale=self.settings.holidays_prior_scale,
            daily_seasonality=self.settings.daily_seasonality,
            weekly_seasonality=self.settings.weekly_seasonality,
            yearly_seasonality=self.settings.yearly_seasonality,
            n_changepoints=self.settings.n_changepoints,
            changepoint_range=self.settings.changepoint_range,
        )
        for column in self._regressor_columns:
            model.add_regressor(column)
        model.fit(train_frame.rename(columns={"y": "y"}))
        self._model = model
        self._fit_failed = False
        self._set_runtime_info(
            {
                "fit_failed": False,
                "train_rows": int(training_data.X.shape[0]),
                "regressor_count": len(self._regressor_columns),
                "excluded_feature_families": list(self.settings.excluded_feature_families),
                "excluded_feature_columns": list(self.settings.excluded_feature_columns),
                "ablation_scheme_name": self.settings.ablation_scheme_name,
                "ablation_target_block": self.settings.ablation_target_block,
                "fs3_experiment": self.settings.fs3_experiment.code if self.settings.fs3_experiment else None,
                "settings_json": json.dumps(self.settings.__dict__, sort_keys=True, default=str),
            }
        )

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> pd.Series:
        if self._model is None or self._fit_failed:
            return pd.Series(np.nan, index=target_index_utc, name=self.name, dtype=float)

        target_index_utc = pd.DatetimeIndex(target_index_utc).sort_values()
        working_series = history.set_index(config.timestamp_col)[config.feature_source_col].astype(float).copy()
        history_end = working_series.index.max()
        simulation_index = pd.date_range(start=history_end + pd.Timedelta(hours=1), end=target_index_utc.max(), freq="h", tz="UTC")

        outputs: list[float] = []
        target_lookup = set(target_index_utc)
        predicted_steps = 0
        for timestamp_utc in simulation_index:
            feature_row = build_recursive_feature_row(
                timestamp_utc=timestamp_utc,
                working_series=working_series,
                config=config,
                fs_level=self.settings.fs_level,
                feature_context=feature_context,
                fs3_experiment=self.settings.fs3_experiment,
                model_family=self.family,
                excluded_feature_families=self.settings.excluded_feature_families,
                excluded_feature_columns=self.settings.excluded_feature_columns,
                ablation_scheme_name=self.settings.ablation_scheme_name,
                ablation_target_block=self.settings.ablation_target_block,
            )
            if feature_row.isna().any(axis=None):
                prediction = np.nan
            else:
                future_frame = feature_row.copy()
                future_frame.insert(0, "ds", _prophet_ds(pd.DatetimeIndex([timestamp_utc])))
                prediction = float(self._model.predict(future_frame)["yhat"].iloc[0])
            working_series.loc[timestamp_utc] = prediction
            predicted_steps += 1
            if timestamp_utc in target_lookup:
                outputs.append(prediction)

        runtime_info = self.get_last_runtime_info()
        runtime_info["recursive_steps"] = predicted_steps
        self._set_runtime_info(runtime_info)
        return pd.Series(outputs, index=target_index_utc, name=self.name, dtype=float)
