from __future__ import annotations

import time

import pandas as pd


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total_seconds = int(round(float(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class ProgressReporter:
    def __init__(
        self,
        total: int,
        desc: str,
        text_update_every_sec: float = 20.0,
        text_update_every_steps: int | None = None,
    ) -> None:
        self.total = max(int(total), 1)
        self.desc = desc
        self.current = 0
        self.current_split = ""
        self.current_model = ""
        self.current_origin_text = ""
        self.started = time.perf_counter()
        self.last_text_time = self.started
        self.last_text_step = 0
        self.text_update_every_sec = float(text_update_every_sec)
        self.text_update_every_steps = (
            max(int(text_update_every_steps), 1) if text_update_every_steps is not None else max(self.total // 10, 1)
        )

        self._tqdm = None
        try:
            from tqdm.auto import tqdm

            self._tqdm = tqdm(total=self.total, desc=self.desc, unit="model-origin", leave=True)
        except Exception:
            self._tqdm = None

        self._print_snapshot(force=True)

    def _context_text(self) -> str:
        parts = []
        if self.current_split:
            parts.append(f"split={self.current_split}")
        if self.current_model:
            parts.append(f"model={self.current_model}")
        if self.current_origin_text:
            parts.append(f"origin={self.current_origin_text}")
        return " | ".join(parts)

    def _print_snapshot(self, force: bool = False) -> None:
        now = time.perf_counter()
        if not force:
            step_delta = self.current - self.last_text_step
            time_delta = now - self.last_text_time
            if self.current < self.total and step_delta < self.text_update_every_steps and time_delta < self.text_update_every_sec:
                return

        elapsed = now - self.started
        rate = self.current / elapsed if elapsed > 0.0 and self.current > 0 else None
        remaining = (self.total - self.current) / rate if rate not in (None, 0.0) else None
        percent = float(self.current / self.total * 100.0)
        filled = min(int(round(20 * self.current / self.total)), 20)
        bar = "#" * filled + "-" * (20 - filled)
        context_text = self._context_text()
        suffix = f" | {context_text}" if context_text else ""
        print(
            f"{self.desc}: [{bar}] {self.current}/{self.total} ({percent:.1f}%) "
            f"elapsed {_format_duration(elapsed)} eta {_format_duration(remaining)}{suffix}"
        )
        self.last_text_time = now
        self.last_text_step = self.current

    def step(
        self,
        increment: int = 1,
        split_name: str | None = None,
        model_name: str | None = None,
        forecast_origin_utc=None,
    ) -> None:
        self.current = min(self.total, self.current + int(increment))
        self.current_split = split_name or self.current_split
        self.current_model = model_name or self.current_model
        if forecast_origin_utc is not None:
            self.current_origin_text = pd.Timestamp(forecast_origin_utc).isoformat()

        if self._tqdm is not None:
            self._tqdm.update(int(increment))
            try:
                self._tqdm.set_postfix(split=self.current_split, model=self.current_model, refresh=False)
            except Exception:
                pass

        self._print_snapshot()

    def close(self) -> None:
        if self.current != self.last_text_step:
            self._print_snapshot(force=True)
        if self._tqdm is not None:
            self._tqdm.close()
