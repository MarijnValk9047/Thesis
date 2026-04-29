from __future__ import annotations

import pandas as pd

from .config import ForecastSetup
from .models.base import ForecastModel
from .splits import generate_origins_for_split, target_window_for_origin


def run_walk_forward_for_split(
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    split_name: str,
    models: list[ForecastModel],
) -> pd.DataFrame:
    output_frames: list[pd.DataFrame] = []
    origins_local = generate_origins_for_split(setup, split_name)

    for origin_local in origins_local:
        origin_utc = origin_local.tz_convert("UTC")
        history = labeled[labeled[setup.timestamp_col] < origin_utc].copy()
        target_window = target_window_for_origin(
            labeled=labeled,
            setup=setup,
            split_name=split_name,
            origin_local=origin_local,
        )
        if target_window.empty:
            continue

        target_base = target_window[
            [
                setup.timestamp_col,
                "timestamp_local",
                "local_date",
                setup.target_col,
            ]
        ].copy()

        target_index_utc = pd.DatetimeIndex(target_base[setup.timestamp_col])
        start_local = (origin_local + pd.Timedelta(days=1)).normalize()
        target_base["horizon_hour"] = (((target_base["timestamp_local"] - start_local) / pd.Timedelta(hours=1)) + 1).astype(
            int
        )

        for model in models:
            model.fit(history)
            preds = model.predict(
                history=history,
                target_index_utc=target_index_utc,
                timestamp_col=setup.timestamp_col,
                target_col=setup.target_col,
            )

            if not preds.index.equals(target_index_utc):
                preds = preds.reindex(target_index_utc)

            model_output = pd.DataFrame(
                {
                    "split": split_name,
                    "model": model.name,
                    "origin_utc": origin_utc,
                    "origin_local": origin_local,
                    "target_timestamp_utc": target_base[setup.timestamp_col].values,
                    "target_timestamp_local": target_base["timestamp_local"].values,
                    "target_local_date": target_base["local_date"].values,
                    "horizon_hour": target_base["horizon_hour"].values,
                    "y_true": target_base[setup.target_col].astype(float).values,
                    "y_pred": preds.values,
                }
            )
            output_frames.append(model_output)

    if not output_frames:
        return pd.DataFrame(
            columns=[
                "split",
                "model",
                "origin_utc",
                "origin_local",
                "target_timestamp_utc",
                "target_timestamp_local",
                "target_local_date",
                "horizon_hour",
                "y_true",
                "y_pred",
            ]
        )

    result = pd.concat(output_frames, ignore_index=True)
    result = result.sort_values(["split", "model", "origin_local", "target_timestamp_utc"])
    return result.reset_index(drop=True)
