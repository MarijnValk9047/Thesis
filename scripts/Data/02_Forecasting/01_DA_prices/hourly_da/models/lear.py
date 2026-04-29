from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..core.config import HourlyDAPipelineConfig
from ..core.external_features import FS3Experiment
from ..core.tabular import build_recursive_feature_row, build_training_data
from .base import ForecastModel


@dataclass(frozen=True)
class LEARSettings:
    fs_level: str = "FS2"
    fs3_experiment: FS3Experiment | None = None
    excluded_feature_families: tuple[str, ...] = ()
    excluded_feature_columns: tuple[str, ...] = ()
    ablation_scheme_name: str | None = None
    ablation_target_block: str | None = None
    training_window_hours: int = 24 * 90
    min_train_rows: int = 24 * 30
    alpha: float = 0.01
    max_iter: int = 5000


class LEARModel(ForecastModel):
    def __init__(self, settings: LEARSettings):
        model_name = f"lear_{settings.fs_level.lower()}"
        if settings.fs_level == "FS3" and settings.fs3_experiment is not None:
            model_name = f"{model_name}_{settings.fs3_experiment.code}"
        super().__init__(name=model_name, family="lear", fs_level=settings.fs_level)
        self.settings = settings
        self._pipeline: Pipeline | None = None
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
            self._pipeline = None
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

        pipeline = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("lasso", Lasso(alpha=self.settings.alpha, max_iter=self.settings.max_iter)),
            ]
        )
        pipeline.fit(training_data.X, training_data.y)
        self._pipeline = pipeline
        self._fit_failed = False
        lasso = pipeline.named_steps["lasso"]
        non_zero = int(np.sum(np.abs(lasso.coef_) > 0.0))
        self._set_runtime_info(
            {
                "fit_failed": False,
                "train_rows": int(training_data.X.shape[0]),
                "feature_count": len(self._feature_columns),
                "non_zero_coefficients": non_zero,
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
        if self._pipeline is None or self._fit_failed:
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
                prediction = float(self._pipeline.predict(feature_row)[0])
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

    def coefficient_frame(self) -> pd.DataFrame:
        if self._pipeline is None or self._fit_failed or not self._feature_columns:
            return pd.DataFrame(columns=["feature", "coefficient", "abs_coefficient", "is_nonzero"])
        lasso = self._pipeline.named_steps["lasso"]
        coefficients = np.asarray(lasso.coef_, dtype=float)
        frame = pd.DataFrame(
            {
                "feature": list(self._feature_columns),
                "coefficient": coefficients,
            }
        )
        frame["abs_coefficient"] = frame["coefficient"].abs()
        frame["is_nonzero"] = frame["abs_coefficient"] > 0.0
        return frame.sort_values(["abs_coefficient", "feature"], ascending=[False, True]).reset_index(drop=True)
