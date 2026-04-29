from __future__ import annotations

from .base import ForecastModel


class XGBoostModel(ForecastModel):
    name = "xgboost"

    def fit(self, history):
        raise NotImplementedError("XGBoost scaffold placeholder. Implement in next stage.")

    def predict(self, history, target_index_utc, timestamp_col, target_col):
        raise NotImplementedError("XGBoost scaffold placeholder. Implement in next stage.")
