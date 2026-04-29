from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class ForecastModel(ABC):
    name: str

    def fit(self, history: pd.DataFrame) -> None:
        return None

    def reset_diagnostics(self) -> None:
        return None

    def diagnostics_snapshot(self) -> dict[str, object]:
        return {}

    @abstractmethod
    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        timestamp_col: str,
        target_col: str,
    ) -> pd.Series:
        raise NotImplementedError
