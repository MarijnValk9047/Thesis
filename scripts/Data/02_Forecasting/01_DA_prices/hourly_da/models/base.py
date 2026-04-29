from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..core.config import HourlyDAPipelineConfig


class ForecastModel(ABC):
    name: str
    family: str
    fs_level: str

    def __init__(self, name: str, family: str, fs_level: str):
        self.name = name
        self.family = family
        self.fs_level = fs_level
        self._last_runtime_info: dict[str, object] = {}

    def get_last_runtime_info(self) -> dict[str, object]:
        return dict(self._last_runtime_info)

    def _set_runtime_info(self, payload: dict[str, object]) -> None:
        self._last_runtime_info = dict(payload)

    @abstractmethod
    def fit(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> pd.Series:
        raise NotImplementedError
