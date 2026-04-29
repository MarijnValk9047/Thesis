from __future__ import annotations

import json
import warnings
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import ForecastModel

try:
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.statespace.sarimax import SARIMAX
except ImportError as exc:  # pragma: no cover - handled at runtime
    ARIMA = None
    SARIMAX = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _require_statsmodels() -> None:
    if _IMPORT_ERROR is not None:
        raise ImportError("statsmodels is required for ARIMA/SARIMA models.") from _IMPORT_ERROR


@dataclass(frozen=True)
class ARIMAConfig:
    order: tuple[int, int, int] = (2, 1, 2)
    trend: str | None = None
    history_window_hours: int | None = 24 * 60
    min_history_hours: int = 24 * 30
    maxiter: int = 25


@dataclass(frozen=True)
class SARIMAConfig:
    order: tuple[int, int, int] = (1, 1, 1)
    seasonal_order: tuple[int, int, int, int] = (1, 0, 1, 24)
    trend: str | None = None
    history_window_hours: int | None = 24 * 60
    min_history_hours: int = 24 * 45
    maxiter: int = 25


def _history_series(
    history: pd.DataFrame,
    timestamp_col: str,
    target_col: str,
    history_window_hours: int | None,
) -> pd.Series:
    series = history.sort_values(timestamp_col).set_index(timestamp_col)[target_col]
    series = pd.to_numeric(series, errors="coerce").dropna()
    if history_window_hours is not None and history_window_hours > 0:
        series = series.iloc[-history_window_hours:]
    return series.astype(float).reset_index(drop=True)


def _nan_forecast(target_index_utc: pd.DatetimeIndex, name: str) -> pd.Series:
    return pd.Series(np.nan, index=target_index_utc, name=name, dtype=float)


class ARIMAModel(ForecastModel):
    name = "arima"

    def __init__(self, config: ARIMAConfig | None = None, name: str | None = None):
        self.config = config or ARIMAConfig()
        if name:
            self.name = name
        _require_statsmodels()
        self.reset_diagnostics()

    def reset_diagnostics(self) -> None:
        self._fit_attempts = 0
        self._fit_failures = 0
        self._warning_counter: Counter[str] = Counter()
        self._methodological_warning_counter: Counter[str] = Counter()
        self._error_counter: Counter[str] = Counter()

    def diagnostics_snapshot(self) -> dict[str, object]:
        warning_total = int(sum(self._warning_counter.values()))
        methodological_total = int(sum(self._methodological_warning_counter.values()))
        return {
            "model": self.name,
            "fit_attempts": int(self._fit_attempts),
            "fit_failures": int(self._fit_failures),
            "warning_total": warning_total,
            "methodological_warning_total": methodological_total,
            "warning_counts_json": json.dumps(dict(self._warning_counter), sort_keys=True),
            "methodological_warning_counts_json": json.dumps(dict(self._methodological_warning_counter), sort_keys=True),
            "error_counts_json": json.dumps(dict(self._error_counter), sort_keys=True),
        }

    @staticmethod
    def _is_methodological_warning(record: warnings.WarningMessage) -> bool:
        category = record.category
        message = str(record.message).lower()
        if issubclass(category, ConvergenceWarning):
            return True
        if issubclass(category, RuntimeWarning):
            return True
        flagged_terms = (
            "non-stationary",
            "non invertible",
            "non-invertible",
            "failed to converge",
            "convergence",
            "singular",
            "invalid value encountered",
            "nan",
        )
        return any(term in message for term in flagged_terms)

    def _record_warnings(self, records: list[warnings.WarningMessage]) -> None:
        for record in records:
            category_name = record.category.__name__
            self._warning_counter[category_name] += 1
            if self._is_methodological_warning(record):
                self._methodological_warning_counter[category_name] += 1

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        timestamp_col: str,
        target_col: str,
    ) -> pd.Series:
        target_index_utc = pd.DatetimeIndex(target_index_utc).sort_values()
        if target_index_utc.empty:
            return _nan_forecast(target_index_utc, self.name)

        y = _history_series(
            history=history,
            timestamp_col=timestamp_col,
            target_col=target_col,
            history_window_hours=self.config.history_window_hours,
        )
        if len(y) < self.config.min_history_hours:
            return _nan_forecast(target_index_utc, self.name)

        self._fit_attempts += 1
        captured_warnings: list[warnings.WarningMessage] = []
        try:
            with warnings.catch_warnings(record=True) as records:
                warnings.simplefilter("always")
                model = ARIMA(
                    y,
                    order=self.config.order,
                    trend=self.config.trend,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                )
                fitted = model.fit(method_kwargs={"maxiter": self.config.maxiter})
                forecast = fitted.forecast(steps=len(target_index_utc))
                captured_warnings = list(records)
            self._record_warnings(captured_warnings)
            return pd.Series(np.asarray(forecast, dtype=float), index=target_index_utc, name=self.name)
        except Exception as exc:
            self._fit_failures += 1
            self._error_counter[type(exc).__name__] += 1
            if "records" in locals():
                self._record_warnings(list(records))
            return _nan_forecast(target_index_utc, self.name)


class SARIMAModel(ForecastModel):
    name = "sarima"

    def __init__(self, config: SARIMAConfig | None = None, name: str | None = None):
        self.config = config or SARIMAConfig()
        if name:
            self.name = name
        _require_statsmodels()
        self.reset_diagnostics()

    def reset_diagnostics(self) -> None:
        self._fit_attempts = 0
        self._fit_failures = 0
        self._warning_counter: Counter[str] = Counter()
        self._methodological_warning_counter: Counter[str] = Counter()
        self._error_counter: Counter[str] = Counter()

    def diagnostics_snapshot(self) -> dict[str, object]:
        warning_total = int(sum(self._warning_counter.values()))
        methodological_total = int(sum(self._methodological_warning_counter.values()))
        return {
            "model": self.name,
            "fit_attempts": int(self._fit_attempts),
            "fit_failures": int(self._fit_failures),
            "warning_total": warning_total,
            "methodological_warning_total": methodological_total,
            "warning_counts_json": json.dumps(dict(self._warning_counter), sort_keys=True),
            "methodological_warning_counts_json": json.dumps(
                dict(self._methodological_warning_counter), sort_keys=True
            ),
            "error_counts_json": json.dumps(dict(self._error_counter), sort_keys=True),
        }

    @staticmethod
    def _is_methodological_warning(record: warnings.WarningMessage) -> bool:
        category = record.category
        message = str(record.message).lower()
        if issubclass(category, ConvergenceWarning):
            return True
        if issubclass(category, RuntimeWarning):
            return True
        flagged_terms = (
            "non-stationary",
            "non invertible",
            "non-invertible",
            "failed to converge",
            "convergence",
            "singular",
            "invalid value encountered",
            "nan",
        )
        return any(term in message for term in flagged_terms)

    def _record_warnings(self, records: list[warnings.WarningMessage]) -> None:
        for record in records:
            category_name = record.category.__name__
            self._warning_counter[category_name] += 1
            if self._is_methodological_warning(record):
                self._methodological_warning_counter[category_name] += 1

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        timestamp_col: str,
        target_col: str,
    ) -> pd.Series:
        target_index_utc = pd.DatetimeIndex(target_index_utc).sort_values()
        if target_index_utc.empty:
            return _nan_forecast(target_index_utc, self.name)

        y = _history_series(
            history=history,
            timestamp_col=timestamp_col,
            target_col=target_col,
            history_window_hours=self.config.history_window_hours,
        )
        if len(y) < self.config.min_history_hours:
            return _nan_forecast(target_index_utc, self.name)

        self._fit_attempts += 1
        captured_warnings: list[warnings.WarningMessage] = []
        try:
            with warnings.catch_warnings(record=True) as records:
                warnings.simplefilter("always")
                model = SARIMAX(
                    y,
                    order=self.config.order,
                    seasonal_order=self.config.seasonal_order,
                    trend=self.config.trend,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                )
                fitted = model.fit(disp=False, maxiter=self.config.maxiter)
                forecast = fitted.forecast(steps=len(target_index_utc))
                captured_warnings = list(records)
            self._record_warnings(captured_warnings)
            return pd.Series(np.asarray(forecast, dtype=float), index=target_index_utc, name=self.name)
        except Exception as exc:
            self._fit_failures += 1
            self._error_counter[type(exc).__name__] += 1
            if "records" in locals():
                self._record_warnings(list(records))
            return _nan_forecast(target_index_utc, self.name)
