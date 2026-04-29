from __future__ import annotations

import json
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.statespace.sarimax import SARIMAX

from ..core.config import HourlyDAPipelineConfig
from .base import ForecastModel


@dataclass(frozen=True)
class SARIMASettings:
    order: tuple[int, int, int] = (1, 1, 1)
    seasonal_order: tuple[int, int, int, int] = (1, 0, 1, 24)
    trend: str | None = None
    history_window_hours: int | None = 24 * 30
    min_observed_history_hours: int = 24 * 25
    maxiter: int = 8


class SARIMAModel(ForecastModel):
    def __init__(self, settings: SARIMASettings | None = None):
        super().__init__(name="sarima", family="sarima", fs_level="FS1")
        self.settings = settings or SARIMASettings()
        self._fitted_model = None
        self._fit_failed = False

    def fit(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> None:
        series = history[config.target_col].astype(float)
        if self.settings.history_window_hours is not None:
            series = series.iloc[-self.settings.history_window_hours :]

        observed_count = int(series.notna().sum())
        if observed_count < self.settings.min_observed_history_hours:
            self._fitted_model = None
            self._fit_failed = True
            self._set_runtime_info(
                {
                    "fit_failed": True,
                    "observed_history_hours": observed_count,
                    "warning_counts_json": "{}",
                    "settings_json": json.dumps(
                        {
                            "order": list(self.settings.order),
                            "seasonal_order": list(self.settings.seasonal_order),
                            "maxiter": self.settings.maxiter,
                        }
                    ),
                }
            )
            return

        warning_counter: dict[str, int] = {}
        try:
            with warnings.catch_warnings(record=True) as records:
                warnings.simplefilter("always")
                model = SARIMAX(
                    series.to_numpy(dtype=float),
                    order=self.settings.order,
                    seasonal_order=self.settings.seasonal_order,
                    trend=self.settings.trend,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                )
                self._fitted_model = model.fit(disp=False, maxiter=self.settings.maxiter)
            for record in records:
                category_name = record.category.__name__
                warning_counter[category_name] = warning_counter.get(category_name, 0) + 1
            self._fit_failed = False
        except Exception as exc:  # noqa: BLE001
            warning_counter[type(exc).__name__] = warning_counter.get(type(exc).__name__, 0) + 1
            self._fitted_model = None
            self._fit_failed = True

        convergence_flag = bool(warning_counter.get(ConvergenceWarning.__name__, 0))
        self._set_runtime_info(
            {
                "fit_failed": self._fit_failed,
                "observed_history_hours": observed_count,
                "convergence_warning": convergence_flag,
                "warning_counts_json": json.dumps(warning_counter, sort_keys=True),
                "settings_json": json.dumps(
                    {
                        "order": list(self.settings.order),
                        "seasonal_order": list(self.settings.seasonal_order),
                        "trend": self.settings.trend,
                        "history_window_hours": self.settings.history_window_hours,
                        "min_observed_history_hours": self.settings.min_observed_history_hours,
                        "maxiter": self.settings.maxiter,
                    },
                    sort_keys=True,
                ),
            }
        )

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> pd.Series:
        if self._fitted_model is None or self._fit_failed:
            return pd.Series(np.nan, index=target_index_utc, name=self.name, dtype=float)
        try:
            forecast = self._fitted_model.forecast(steps=len(target_index_utc))
            return pd.Series(np.asarray(forecast, dtype=float), index=target_index_utc, name=self.name)
        except Exception as exc:  # noqa: BLE001
            runtime_info = self.get_last_runtime_info()
            runtime_info["predict_error"] = type(exc).__name__
            self._set_runtime_info(runtime_info)
            return pd.Series(np.nan, index=target_index_utc, name=self.name, dtype=float)
