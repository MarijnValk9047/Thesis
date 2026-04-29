from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.config import HourlyDAPipelineConfig
from ..core.time_utils import delivery_local_date_for_timestamp
from .base import ForecastModel


@dataclass(frozen=True)
class BranchedModelSettings:
    fs_level: str
    branch_mode: str
    d_only_model_name: str
    d_only_model_family: str
    d_only_model_settings: object | None
    guidance_model_name: str
    guidance_model_family: str
    guidance_model_settings: object | None


class BranchedForecastModel(ForecastModel):
    def __init__(
        self,
        name: str,
        family: str,
        fs_level: str,
        d_only_model: ForecastModel,
        guidance_model: ForecastModel,
    ):
        super().__init__(name=name, family=family, fs_level=fs_level)
        self._d_only_model = d_only_model
        self._guidance_model = guidance_model
        self.settings = BranchedModelSettings(
            fs_level=fs_level,
            branch_mode="d_only_vs_guidance",
            d_only_model_name=d_only_model.name,
            d_only_model_family=d_only_model.family,
            d_only_model_settings=getattr(d_only_model, "settings", None),
            guidance_model_name=guidance_model.name,
            guidance_model_family=guidance_model.family,
            guidance_model_settings=getattr(guidance_model, "settings", None),
        )

    def fit(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> None:
        self._d_only_model.fit(
            history=history,
            target_index_utc=target_index_utc,
            config=config,
            feature_context=feature_context,
        )
        self._guidance_model.fit(
            history=history,
            target_index_utc=target_index_utc,
            config=config,
            feature_context=feature_context,
        )
        self._set_runtime_info(
            {
                "branch_mode": "d_only_vs_guidance",
                "d_only_model": self._d_only_model.name,
                "guidance_model": self._guidance_model.name,
                "d_only_runtime_info": self._d_only_model.get_last_runtime_info(),
                "guidance_runtime_info": self._guidance_model.get_last_runtime_info(),
            }
        )

    def predict(
        self,
        history: pd.DataFrame,
        target_index_utc: pd.DatetimeIndex,
        config: HourlyDAPipelineConfig,
        feature_context: pd.DataFrame | None = None,
    ) -> pd.Series:
        target_index_utc = pd.DatetimeIndex(target_index_utc).sort_values()
        if target_index_utc.empty:
            return pd.Series(dtype=float, index=target_index_utc, name=self.name)

        timezone = config.resolved_business_timezone()
        local_dates = pd.Series(
            [delivery_local_date_for_timestamp(timestamp, timezone) for timestamp in target_index_utc],
            index=target_index_utc,
        )
        d_only_date = sorted(local_dates.unique())[0]
        d_only_index = pd.DatetimeIndex(local_dates[local_dates == d_only_date].index)
        guidance_index = pd.DatetimeIndex(local_dates[local_dates != d_only_date].index)

        predictions = pd.Series(np.nan, index=target_index_utc, name=self.name, dtype=float)
        if len(d_only_index) > 0:
            d_only_predictions = self._d_only_model.predict(
                history=history,
                target_index_utc=d_only_index,
                config=config,
                feature_context=feature_context,
            )
            predictions.loc[d_only_index] = d_only_predictions.reindex(d_only_index).to_numpy(dtype=float)

        if len(guidance_index) > 0:
            guidance_predictions = self._guidance_model.predict(
                history=history,
                target_index_utc=guidance_index,
                config=config,
                feature_context=feature_context,
            )
            predictions.loc[guidance_index] = guidance_predictions.reindex(guidance_index).to_numpy(dtype=float)

        runtime_info = self.get_last_runtime_info()
        runtime_info.update(
            {
                "d_only_timestamps": int(len(d_only_index)),
                "guidance_timestamps": int(len(guidance_index)),
                "d_only_local_date": d_only_date.isoformat(),
                "d_only_runtime_info": self._d_only_model.get_last_runtime_info(),
                "guidance_runtime_info": self._guidance_model.get_last_runtime_info(),
            }
        )
        self._set_runtime_info(runtime_info)
        predictions.name = self.name
        return predictions

    def branch_models(self) -> dict[str, ForecastModel]:
        return {
            "d_only": self._d_only_model,
            "guidance": self._guidance_model,
        }
