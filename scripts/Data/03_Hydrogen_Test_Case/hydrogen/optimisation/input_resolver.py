from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..data_loader import resolve_execution_period
from ..plant_parameters import HydrogenConfig, load_hydrogen_config
from ..scenario_loader import ScenarioArtifactSpec, load_scenarios_for_artifact, resolve_artifact_specs
from .cache_manager import CacheManager
from .fingerprinting import (
    ExperimentFingerprint,
    build_experiment_fingerprint,
    build_input_slice_fingerprint,
    fingerprint_file,
)


@dataclass(frozen=True)
class InputSliceRequest:
    artifact_id: str
    start_local_date: str
    end_local_date: str
    period_mode: str
    period_labels: tuple[str, ...] = ()
    dataset_split: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": str(self.artifact_id),
            "start_local_date": str(self.start_local_date),
            "end_local_date": str(self.end_local_date),
            "period_mode": str(self.period_mode),
            "period_labels": list(self.period_labels),
            "dataset_split": None if self.dataset_split is None else str(self.dataset_split),
        }


@dataclass(frozen=True)
class ResolvedInputSlice:
    artifact_id: str
    spec: ScenarioArtifactSpec
    scenarios: pd.DataFrame
    market_actuals: pd.DataFrame
    origin_registry: pd.DataFrame
    findings: list[str]
    source_fingerprints: list[dict[str, Any]]
    slice_fingerprint: str
    experiment_fingerprint: ExperimentFingerprint
    cache_status: str
    cache_entry_dir: Path | None
    selected_period: dict[str, Any]


def _as_config(config_or_path: HydrogenConfig | str | Path) -> HydrogenConfig:
    if isinstance(config_or_path, HydrogenConfig):
        return config_or_path
    return load_hydrogen_config(config_or_path)


def _artifact_config(config: HydrogenConfig, artifact_id: str) -> HydrogenConfig:
    return replace(config, models=replace(config.models, include=(str(artifact_id),)))


def build_request_from_execution_period(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
) -> InputSliceRequest:
    config = _as_config(config_or_path)
    period = resolve_execution_period(config)
    return InputSliceRequest(
        artifact_id=str(artifact_id),
        start_local_date=period.start_local_date.isoformat(),
        end_local_date=period.end_local_date.isoformat(),
        period_mode=str(period.mode),
        period_labels=tuple(str(value) for value in period.labels),
        dataset_split=str(config.experiment.dataset_split) if config.experiment.dataset_split else None,
    )


def _filter_to_local_date_window(
    frame: pd.DataFrame,
    *,
    start_local_date: date,
    end_local_date: date,
) -> pd.DataFrame:
    filtered = frame.copy()
    local_timestamps = pd.to_datetime(filtered["delivery_start_local"], errors="coerce")
    filtered["delivery_local_date"] = local_timestamps.dt.date
    mask = (filtered["delivery_local_date"] >= start_local_date) & (filtered["delivery_local_date"] <= end_local_date)
    filtered = filtered.loc[mask].copy()
    if filtered.empty:
        raise ValueError(
            "Input slice is empty after local-date filtering. "
            f"Requested {start_local_date.isoformat()}..{end_local_date.isoformat()}."
        )
    return filtered.reset_index(drop=True)


def _build_market_actuals(frame: pd.DataFrame) -> pd.DataFrame:
    market = (
        frame[["delivery_start_utc", "delivery_start_local", "delivery_day", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
        .reset_index(drop=True)
    )
    market["delivery_start_utc"] = pd.to_datetime(market["delivery_start_utc"], utc=True, errors="raise")
    return market


def _build_origin_registry(frame: pd.DataFrame) -> pd.DataFrame:
    deduplicated_probabilities = (
        frame[["forecast_origin_utc", "delivery_day", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "delivery_day", "scenario_id"])
        .copy()
    )
    probability_summary = (
        deduplicated_probabilities.groupby(["forecast_origin_utc", "delivery_day"], as_index=False)["scenario_probability"]
        .sum()
        .rename(columns={"scenario_probability": "probability_sum"})
    )
    registry = (
        frame.groupby(["forecast_origin_utc", "delivery_day"], as_index=False)
        .agg(
            delivery_period_count=("delivery_start_utc", "nunique"),
            scenario_count=("scenario_id", "nunique"),
        )
        .merge(probability_summary, on=["forecast_origin_utc", "delivery_day"], how="left")
        .sort_values(["delivery_day", "forecast_origin_utc"])
        .reset_index(drop=True)
    )
    return registry


def resolve_input_slice(
    config_or_path: HydrogenConfig | str | Path,
    *,
    request: InputSliceRequest,
    output_policy_name: str = "minimal",
    cache_root: Path | None = None,
    use_cache: bool = True,
    methodological_approximations: tuple[str, ...] = (),
) -> ResolvedInputSlice:
    config = _as_config(config_or_path)
    run_config = _artifact_config(config, request.artifact_id)
    spec = resolve_artifact_specs(run_config)[0]
    source_fingerprints = [
        fingerprint_file(config.config_path, include_sha256=True).to_dict(),
        fingerprint_file(config.models.scenario_catalog, include_sha256=True).to_dict(),
        fingerprint_file(spec.path, include_sha256=False).to_dict(),
    ]
    slice_fingerprint = build_input_slice_fingerprint(
        artifact_id=request.artifact_id,
        source_fingerprints=source_fingerprints,
        request_payload=request.as_payload(),
        granularity=config.experiment.granularity,
        horizon_mode=config.experiment.horizon_mode,
    )
    experiment_fingerprint = build_experiment_fingerprint(
        config=config,
        input_slice_fingerprint=slice_fingerprint,
        output_policy_name=output_policy_name,
        methodological_approximations=methodological_approximations,
    )
    cache_manager = CacheManager(cache_root) if cache_root is not None else None
    if cache_manager is not None and use_cache:
        cached = cache_manager.load_bundle(
            namespace="input_slices",
            key=slice_fingerprint,
            expected_source_fingerprints=source_fingerprints,
        )
        if cached is not None:
            manifest = cached.manifest
            return ResolvedInputSlice(
                artifact_id=str(request.artifact_id),
                spec=spec,
                scenarios=cached.frames["scenarios"],
                market_actuals=cached.frames["market_actuals"],
                origin_registry=cached.frames["origin_registry"],
                findings=list(manifest.get("findings", [])),
                source_fingerprints=source_fingerprints,
                slice_fingerprint=slice_fingerprint,
                experiment_fingerprint=experiment_fingerprint,
                cache_status="hit",
                cache_entry_dir=cached.entry_dir,
                selected_period=dict(manifest.get("selected_period", {})),
            )

    start_local_date = pd.Timestamp(request.start_local_date).date()
    end_local_date = pd.Timestamp(request.end_local_date).date()
    scenarios, findings = load_scenarios_for_artifact(spec, config=run_config)
    filtered = _filter_to_local_date_window(
        scenarios,
        start_local_date=start_local_date,
        end_local_date=end_local_date,
    )
    market_actuals = _build_market_actuals(filtered)
    origin_registry = _build_origin_registry(filtered)
    selected_period = {
        "period_mode": str(request.period_mode),
        "period_labels": list(request.period_labels),
        "start_local_date": start_local_date.isoformat(),
        "end_local_date": end_local_date.isoformat(),
        "delivery_day_count": int(filtered["delivery_local_date"].nunique()),
    }
    cache_entry_dir: Path | None = None
    if cache_manager is not None:
        bundle = cache_manager.save_bundle(
            namespace="input_slices",
            key=slice_fingerprint,
            frames={
                "scenarios": filtered.drop(columns=["delivery_local_date"]),
                "market_actuals": market_actuals,
                "origin_registry": origin_registry,
            },
            manifest={
                "artifact_id": str(request.artifact_id),
                "model_id": str(spec.model_id),
                "source_fingerprints": source_fingerprints,
                "selected_period": selected_period,
                "findings": findings,
                "slice_fingerprint": slice_fingerprint,
            },
        )
        cache_entry_dir = bundle.entry_dir
    return ResolvedInputSlice(
        artifact_id=str(request.artifact_id),
        spec=spec,
        scenarios=filtered.drop(columns=["delivery_local_date"]),
        market_actuals=market_actuals,
        origin_registry=origin_registry,
        findings=findings,
        source_fingerprints=source_fingerprints,
        slice_fingerprint=slice_fingerprint,
        experiment_fingerprint=experiment_fingerprint,
        cache_status="miss",
        cache_entry_dir=cache_entry_dir,
        selected_period=selected_period,
    )


def resolve_config_period_input(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
    output_policy_name: str = "minimal",
    cache_root: Path | None = None,
    use_cache: bool = True,
    methodological_approximations: tuple[str, ...] = (),
) -> ResolvedInputSlice:
    request = build_request_from_execution_period(config_or_path, artifact_id=artifact_id)
    return resolve_input_slice(
        config_or_path,
        request=request,
        output_policy_name=output_policy_name,
        cache_root=cache_root,
        use_cache=use_cache,
        methodological_approximations=methodological_approximations,
    )
