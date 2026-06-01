from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from ..plant_parameters import HydrogenConfig


def _normalise_for_hash(value: Any) -> Any:
    if is_dataclass(value):
        return _normalise_for_hash(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            return value.isoformat()
        return value.tz_convert("UTC").isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _normalise_for_hash(sub_value) for key, sub_value in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, set):
        return [_normalise_for_hash(item) for item in sorted(value, key=lambda item: str(item))]
    if isinstance(value, (list, tuple)):
        return [_normalise_for_hash(item) for item in value]
    return value


def stable_json_dumps(payload: Any) -> str:
    return json.dumps(_normalise_for_hash(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint_payload(payload: Any, *, length: int = 16) -> str:
    digest = hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()
    return digest[:length] if length > 0 else digest


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    exists: bool
    size_bytes: int | None
    modified_utc: str | None
    sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint_file(path: Path, *, include_sha256: bool = True) -> FileFingerprint:
    if not path.exists():
        return FileFingerprint(
            path=str(path),
            exists=False,
            size_bytes=None,
            modified_utc=None,
            sha256=None,
        )
    stat = path.stat()
    sha256: str | None = None
    if include_sha256:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1_048_576), b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
    return FileFingerprint(
        path=str(path),
        exists=True,
        size_bytes=int(stat.st_size),
        modified_utc=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        sha256=sha256,
    )


def _serialise_series(series: pd.Series) -> pd.Series:
    if is_datetime64_any_dtype(series):
        timestamps = pd.to_datetime(series, errors="coerce", utc=False)
        return timestamps.map(lambda value: None if pd.isna(value) else value.isoformat())
    return series.map(
        lambda value: None
        if pd.isna(value)
        else (
            value.tz_convert("UTC").isoformat()
            if isinstance(value, pd.Timestamp) and value.tzinfo is not None
            else value.isoformat()
            if isinstance(value, (datetime, date))
            else str(value)
            if isinstance(value, Path)
            else value
        )
    )


def dataframe_fingerprint(
    frame: pd.DataFrame,
    *,
    sort_by: Iterable[str] | None = None,
    include_index: bool = False,
) -> str:
    normalized = frame.copy()
    normalized = normalized.reindex(sorted(normalized.columns), axis=1)
    if sort_by:
        sort_columns = [column for column in sort_by if column in normalized.columns]
        if sort_columns:
            normalized = normalized.sort_values(sort_columns).reset_index(drop=True)
    for column in normalized.columns:
        normalized[column] = _serialise_series(normalized[column])
    payload = {
        "columns": list(normalized.columns),
        "index": normalized.index.tolist() if include_index else None,
        "records": normalized.to_dict(orient="records"),
    }
    return fingerprint_payload(payload)


def build_input_slice_fingerprint(
    *,
    artifact_id: str,
    source_fingerprints: list[dict[str, Any]],
    request_payload: dict[str, Any],
    granularity: str,
    horizon_mode: str,
) -> str:
    return fingerprint_payload(
        {
            "artifact_id": str(artifact_id),
            "source_fingerprints": source_fingerprints,
            "request": request_payload,
            "granularity": str(granularity),
            "horizon_mode": str(horizon_mode),
            "contract_version": "optimisation_input_slice_v1",
        }
    )


@dataclass(frozen=True)
class ExperimentFingerprint:
    digest: str
    payload: dict[str, Any]


def build_experiment_fingerprint(
    *,
    config: HydrogenConfig,
    input_slice_fingerprint: str,
    output_policy_name: str,
    methodological_approximations: Iterable[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> ExperimentFingerprint:
    payload = {
        "input_slice_fingerprint": str(input_slice_fingerprint),
        "output_policy": str(output_policy_name),
        "experiment": {
            "name": str(config.experiment.name),
            "granularity": str(config.experiment.granularity),
            "horizon_mode": str(config.experiment.horizon_mode),
            "execution_mode": str(config.experiment.execution_mode),
            "dataset_split": str(config.experiment.dataset_split),
            "random_seed": int(config.experiment.random_seed),
        },
        "models": {
            "include": list(config.models.include),
            "scenario_catalog": str(config.models.scenario_catalog),
        },
        "strategies": list(config.strategies),
        "risk": {
            "alpha": float(config.risk.alpha),
            "gamma": float(config.risk.gamma),
            "gamma_grid": list(config.risk.gamma_grid),
            "gamma_selection": str(config.risk.gamma_selection),
        },
        "bidding": {
            "bid_price_grid_eur_per_mwh": list(config.bidding.bid_price_grid_eur_per_mwh),
            "price_insensitive_bid_price_eur_per_mwh": float(config.bidding.price_insensitive_bid_price_eur_per_mwh),
        },
        "solver": {
            "package_preference": str(config.solver.package_preference),
            "solver_name": str(config.solver.solver_name),
            "mip_gap": float(config.solver.mip_gap),
            "time_limit_seconds": int(config.solver.time_limit_seconds),
        },
        "methodological_approximations": sorted(str(value) for value in methodological_approximations),
        "extra": dict(extra or {}),
        "contract_version": "optimisation_experiment_v1",
    }
    return ExperimentFingerprint(digest=fingerprint_payload(payload), payload=payload)
