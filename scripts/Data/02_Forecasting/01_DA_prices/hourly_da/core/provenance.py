from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pandas as pd


def _json_safe(value):
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _model_settings_payload(model) -> tuple[str, dict[str, object]]:
    settings = getattr(model, "settings", None)
    if settings is not None:
        payload = _json_safe(settings)
        if isinstance(payload, dict):
            return "model.settings", payload
        return "model.settings", {"value": payload}

    # Naive baselines have no explicit settings dataclass, so surface the frozen strategy instead.
    return "implicit_model_defaults", {"strategy": str(model.name)}


def model_settings_summary_frame(models: list) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for model in models:
        settings_source, payload = _model_settings_payload(model)
        row = {
            "model": str(model.name),
            "model_family": str(model.family),
            "fs_level": str(model.fs_level),
            "settings_source": settings_source,
            "settings_json": json.dumps(payload, sort_keys=True, default=str),
        }
        if isinstance(payload, dict):
            row.update(payload)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["fs_level", "model_family", "model"]).reset_index(drop=True)


def model_settings_summary_from_source_runs(
    source_runs: list[dict[str, object]],
    *,
    selected_models: set[str] | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    selected_models = {str(model) for model in (selected_models or set())}

    for record in source_runs:
        run_dir = Path(str(record["run_dir"]))
        summary_path = run_dir / "model_settings_summary.csv"
        if summary_path.exists():
            frame = pd.read_csv(summary_path)
            if "model" not in frame.columns:
                continue
            if selected_models:
                frame = frame[frame["model"].astype(str).isin(selected_models)].copy()
            if frame.empty:
                continue
            frame.insert(0, "source_run_id", str(record["run_id"]))
            frames.append(frame)
            continue

        timing_path = run_dir / "origin_timing.csv"
        if not timing_path.exists():
            continue

        timing = pd.read_csv(timing_path)
        required_cols = {"model", "runtime_info_json"}
        if not required_cols.issubset(timing.columns):
            continue
        if selected_models:
            timing = timing[timing["model"].astype(str).isin(selected_models)].copy()
        if timing.empty:
            continue

        backfill_rows: list[dict[str, object]] = []
        for model_name, group in timing.groupby("model", sort=True):
            first = group.iloc[0]
            runtime_info = json.loads(str(first["runtime_info_json"])) if pd.notna(first["runtime_info_json"]) else {}
            if "settings_json" in runtime_info:
                payload = json.loads(str(runtime_info["settings_json"]))
            else:
                payload = runtime_info
            row = {
                "source_run_id": str(record["run_id"]),
                "model": str(model_name),
                "model_family": str(first.get("model_family", "")),
                "fs_level": str(first.get("fs_level", "")),
                "settings_source": "runtime_info_json_backfill",
                "settings_json": json.dumps(payload, sort_keys=True, default=str),
            }
            if isinstance(payload, dict):
                row.update(payload)
            backfill_rows.append(row)
        if backfill_rows:
            frames.append(pd.DataFrame(backfill_rows))

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=["model"], keep="last").reset_index(drop=True)
