from __future__ import annotations

from statistics import median

from .config import MonitoringConfig


class FitTimeMonitor:
    def __init__(self, config: MonitoringConfig):
        self.config = config
        self._fit_times: list[float] = []

    def evaluate(self, fit_time_sec: float) -> dict[str, object]:
        recent = self._fit_times[-self.config.fit_time_recent_window :]
        recent_mean = sum(recent) / len(recent) if recent else None
        recent_median = median(recent) if recent else None
        relative_threshold_sec = None
        exceeded_relative = False

        if recent_median is not None and len(recent) >= self.config.fit_time_min_history:
            relative_threshold_sec = max(
                recent_median * self.config.fit_time_relative_factor,
                self.config.fit_time_absolute_threshold_sec / 20.0,
            )
            exceeded_relative = fit_time_sec > relative_threshold_sec

        exceeded_absolute = fit_time_sec > self.config.fit_time_absolute_threshold_sec
        self._fit_times.append(fit_time_sec)
        return {
            "recent_fit_mean_sec": recent_mean,
            "recent_fit_median_sec": recent_median,
            "fit_time_absolute_threshold_sec": self.config.fit_time_absolute_threshold_sec,
            "fit_time_relative_threshold_sec": relative_threshold_sec,
            "fit_time_relative_factor": self.config.fit_time_relative_factor,
            "fit_time_warning_absolute": exceeded_absolute,
            "fit_time_warning_relative": exceeded_relative,
            "fit_time_warning": exceeded_absolute or exceeded_relative,
        }
