from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from ..core.config import HourlyDAPipelineConfig
from ..core.external_features import FS3Experiment
from ..core.tabular import build_recursive_feature_row, build_training_data
from .base import ForecastModel


@dataclass(frozen=True)
class XGBoostSettings:
    fs_level: str = "FS2"
    fs3_experiment: FS3Experiment | None = None
    excluded_feature_families: tuple[str, ...] = ()
    excluded_feature_columns: tuple[str, ...] = ()
    ablation_scheme_name: str | None = None
    ablation_target_block: str | None = None
    training_window_hours: int = 24 * 90
    min_train_rows: int = 24 * 30
    n_estimators: int = 80
    max_depth: int = 4
    learning_rate: float = 0.05
    subsample: float = 0.9
    colsample_bytree: float = 0.9
    reg_alpha: float = 0.0
    reg_lambda: float = 1.0
    random_state: int = 42
    n_jobs: int = 1


class XGBoostModel(ForecastModel):
    def __init__(self, settings: XGBoostSettings):
        model_name = f"xgboost_{settings.fs_level.lower()}"
        if settings.fs_level == "FS3" and settings.fs3_experiment is not None:
            model_name = f"{model_name}_{settings.fs3_experiment.code}"
        super().__init__(name=model_name, family="xgboost", fs_level=settings.fs_level)
        self.settings = settings
        self._model: XGBRegressor | None = None
        self._feature_columns: list[str] = []
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
        self._feature_columns = list(training_data.feature_columns)
        if training_data.X.shape[0] < self.settings.min_train_rows:
            self._model = None
            self._fit_failed = True
            self._set_runtime_info(
                {
                    "fit_failed": True,
                    "train_rows": int(training_data.X.shape[0]),
                    "feature_count": len(self._feature_columns),
                    "excluded_feature_families": list(self.settings.excluded_feature_families),
                    "excluded_feature_columns": list(self.settings.excluded_feature_columns),
                    "ablation_scheme_name": self.settings.ablation_scheme_name,
                    "ablation_target_block": self.settings.ablation_target_block,
                    "fs3_experiment": self.settings.fs3_experiment.code if self.settings.fs3_experiment else None,
                    "settings_json": json.dumps(self.settings.__dict__, sort_keys=True, default=str),
                }
            )
            return

        model = XGBRegressor(
            objective="reg:squarederror",
            n_estimators=self.settings.n_estimators,
            max_depth=self.settings.max_depth,
            learning_rate=self.settings.learning_rate,
            subsample=self.settings.subsample,
            colsample_bytree=self.settings.colsample_bytree,
            reg_alpha=self.settings.reg_alpha,
            reg_lambda=self.settings.reg_lambda,
            random_state=self.settings.random_state,
            n_jobs=self.settings.n_jobs,
        )
        model.fit(training_data.X, training_data.y)
        self._model = model
        self._fit_failed = False
        self._set_runtime_info(
            {
                "fit_failed": False,
                "train_rows": int(training_data.X.shape[0]),
                "feature_count": len(self._feature_columns),
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
                prediction = float(self._model.predict(feature_row)[0])
            working_series.loc[timestamp_utc] = prediction
            predicted_steps += 1
            if timestamp_utc in target_lookup:
                outputs.append(prediction)

        runtime_info = self.get_last_runtime_info()
        runtime_info["recursive_steps"] = predicted_steps
        self._set_runtime_info(runtime_info)
        return pd.Series(outputs, index=target_index_utc, name=self.name, dtype=float)

    def get_feature_columns(self) -> list[str]:
        return list(self._feature_columns)

    def importance_frame(self) -> pd.DataFrame:
        if self._model is None or self._fit_failed or not self._feature_columns:
            return pd.DataFrame(columns=["feature", "gain", "split_count"])
        booster = self._model.get_booster()
        gain_scores = booster.get_score(importance_type="gain")
        split_scores = booster.get_score(importance_type="weight")
        rows: list[dict[str, object]] = []
        for feature_name in self._feature_columns:
            rows.append(
                {
                    "feature": str(feature_name),
                    "gain": float(gain_scores.get(str(feature_name), 0.0)),
                    "split_count": float(split_scores.get(str(feature_name), 0.0)),
                }
            )
        return (
            pd.DataFrame(rows)
            .sort_values(["gain", "split_count", "feature"], ascending=[False, False, True])
            .reset_index(drop=True)
        )
