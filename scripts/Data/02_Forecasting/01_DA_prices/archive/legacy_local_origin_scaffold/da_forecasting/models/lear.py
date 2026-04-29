from __future__ import annotations

from .base import ForecastModel


class LEARModel(ForecastModel):
    name = "lear"

    def fit(self, history):
        raise NotImplementedError("LEAR scaffold placeholder. Implement in next stage.")

    def predict(self, history, target_index_utc, timestamp_col, target_col):
        raise NotImplementedError("LEAR scaffold placeholder. Implement in next stage.")
