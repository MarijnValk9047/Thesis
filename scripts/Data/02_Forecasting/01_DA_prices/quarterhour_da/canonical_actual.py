from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .phase05 import (
    _build_observed_shape_library,
    _counterfactual_generation_summary,
    _generate_counterfactual_realized_paths,
    _load_hourly_actuals,
    _load_phase02_model_table,
)


DEFAULT_CANONICAL_VARIANT = "empirical_medium"
DEFAULT_CANONICAL_VERSION = "canonical_v1"

CANONICAL_CSV_NAME = "synthetic_actual_15min_canonical.csv"
CANONICAL_PARQUET_NAME = "synthetic_actual_15min_canonical.parquet"
MANIFEST_NAME = "synthetic_actual_15min_manifest.json"
DIAGNOSTICS_CSV_NAME = "synthetic_actual_15min_diagnostics.csv"
DIAGNOSTICS_JSON_NAME = "synthetic_actual_15min_diagnostics.json"
HASH_NAME = "synthetic_actual_15min_hash.txt"
AUTHORITATIVE_HASH_KEY = "csv"


LEGACY_ACTUAL_PATH_REJECTION_MESSAGE = (
    "Legacy Phase 5/6 realised paths are not authorised as actual market truth for thesis-grade runs. "
    "Use frozen_actual_paths/canonical_v1 via the canonical actual loader."
)


@dataclass(frozen=True)
class FrozenActualRegistryEntry:
    version_id: str
    version_dir: Path
    manifest_path: Path
    canonical_csv_path: Path
    canonical_parquet_path: Path
    diagnostics_csv_path: Path
    diagnostics_json_path: Path
    hash_path: Path
    role: str
    authoritative_sha256: str
    parquet_sha256: str | None
    manifest: dict[str, Any]


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_canonical_actual_freeze")


def find_latest_canonical_actual_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.canonical_actual_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def find_frozen_actual_version(
    config: QuarterHourDAExtensionConfig,
    version_id: str = DEFAULT_CANONICAL_VERSION,
) -> Path | None:
    version_dir = config.frozen_actual_version_dir(version_id)
    return version_dir if (version_dir / MANIFEST_NAME).exists() else None


def load_frozen_actual_manifest(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
    verify_hash: bool = True,
) -> dict[str, Any]:
    entry = resolve_frozen_actual_registry_entry(config, version_id=version_id, verify_hash=verify_hash)
    return dict(entry.manifest)


def load_frozen_actual_path(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
    verify_hash: bool = True,
    thesis_grade: bool = True,
) -> pd.DataFrame:
    config = config or QuarterHourDAExtensionConfig()
    entry = resolve_frozen_actual_registry_entry(config, version_id=version_id, verify_hash=verify_hash)
    assert_thesis_grade_actual_source_authorized(entry.canonical_csv_path, config=config, thesis_grade=thesis_grade)
    frame = pd.read_csv(entry.canonical_csv_path, low_memory=False)
    for column in ("timestamp_utc", "hour_start_utc"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    for column in ("timestamp_local", "hour_start_local"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce").dt.tz_convert(config.business_timezone)
    frame.attrs.update(build_thesis_grade_frozen_actual_metadata(config, version_id=version_id, verify_hash=False))
    frame.attrs["frozen_actual_version_dir"] = str(entry.version_dir)
    frame.attrs["frozen_actual_csv_path"] = str(entry.canonical_csv_path)
    return frame


def load_frozen_actual_diagnostics(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
    verify_hash: bool = True,
) -> pd.DataFrame:
    entry = resolve_frozen_actual_registry_entry(config, version_id=version_id, verify_hash=verify_hash)
    return pd.read_csv(entry.diagnostics_csv_path)


def _git_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    value = completed.stdout.strip()
    return value or None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_hash_sidecar(hash_path: Path) -> dict[str, str]:
    if not hash_path.exists():
        raise FileNotFoundError(f"Frozen actual hash sidecar not found: {hash_path}")
    rows: dict[str, str] = {}
    for raw_line in hash_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, sep, value = line.partition(" ")
        if not sep or not value.strip():
            raise ValueError(f"Malformed hash sidecar line in {hash_path}: {raw_line!r}")
        rows[key.strip()] = value.strip()
    return rows


def resolve_frozen_actual_registry_entry(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
    verify_hash: bool = True,
) -> FrozenActualRegistryEntry:
    config = config or QuarterHourDAExtensionConfig()
    version_dir = config.frozen_actual_version_dir(version_id)
    manifest_path = version_dir / MANIFEST_NAME
    csv_path = version_dir / CANONICAL_CSV_NAME
    parquet_path = version_dir / CANONICAL_PARQUET_NAME
    diagnostics_csv_path = version_dir / DIAGNOSTICS_CSV_NAME
    diagnostics_json_path = version_dir / DIAGNOSTICS_JSON_NAME
    hash_path = version_dir / HASH_NAME

    if not manifest_path.exists():
        raise FileNotFoundError(f"Frozen actual manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing_paths = [
        path
        for path in (csv_path, diagnostics_csv_path, diagnostics_json_path, hash_path)
        if not path.exists()
    ]
    if missing_paths:
        raise FileNotFoundError(
            "Frozen actual version is incomplete. Missing required files: "
            + ", ".join(str(path) for path in missing_paths)
        )

    manifest_version = str(manifest.get("version_id") or "")
    if manifest_version != str(version_id):
        raise ValueError(
            f"Frozen actual manifest version mismatch: requested '{version_id}' but manifest recorded '{manifest_version}'."
        )

    manifest_hashes = dict(manifest.get("file_hash_sha256") or {})
    csv_hash_manifest = str(manifest_hashes.get(AUTHORITATIVE_HASH_KEY) or "").strip()
    parquet_hash_manifest = str(manifest_hashes.get("parquet") or "").strip() or None
    if not csv_hash_manifest:
        raise ValueError(
            f"Frozen actual manifest does not record the authoritative {AUTHORITATIVE_HASH_KEY} checksum: {manifest_path}"
        )

    sidecar_hashes = _parse_hash_sidecar(hash_path)
    csv_hash_sidecar = sidecar_hashes.get(f"{AUTHORITATIVE_HASH_KEY}_sha256")
    parquet_hash_sidecar = sidecar_hashes.get("parquet_sha256")
    if csv_hash_sidecar != csv_hash_manifest:
        raise ValueError(
            "Frozen actual checksum mismatch between manifest and hash sidecar for the authoritative CSV artifact."
        )
    if parquet_hash_manifest and parquet_hash_sidecar and parquet_hash_sidecar != parquet_hash_manifest:
        raise ValueError("Frozen actual parquet checksum mismatch between manifest and hash sidecar.")

    if verify_hash:
        actual_csv_hash = _sha256_file(csv_path)
        if actual_csv_hash != csv_hash_manifest:
            raise ValueError(
                f"Frozen actual CSV hash verification failed for {csv_path}. "
                f"Expected {csv_hash_manifest}, observed {actual_csv_hash}."
            )
        if parquet_path.exists() and parquet_hash_manifest:
            actual_parquet_hash = _sha256_file(parquet_path)
            if actual_parquet_hash != parquet_hash_manifest:
                raise ValueError(
                    f"Frozen actual parquet hash verification failed for {parquet_path}. "
                    f"Expected {parquet_hash_manifest}, observed {actual_parquet_hash}."
                )

    return FrozenActualRegistryEntry(
        version_id=str(version_id),
        version_dir=version_dir,
        manifest_path=manifest_path,
        canonical_csv_path=csv_path,
        canonical_parquet_path=parquet_path,
        diagnostics_csv_path=diagnostics_csv_path,
        diagnostics_json_path=diagnostics_json_path,
        hash_path=hash_path,
        role=str(manifest.get("role") or ""),
        authoritative_sha256=csv_hash_manifest,
        parquet_sha256=parquet_hash_manifest,
        manifest=manifest,
    )


def build_thesis_grade_frozen_actual_metadata(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
    verify_hash: bool = True,
) -> dict[str, Any]:
    entry = resolve_frozen_actual_registry_entry(config, version_id=version_id, verify_hash=verify_hash)
    manifest = entry.manifest
    return {
        "frozen_actual_version_id": entry.version_id,
        "frozen_actual_manifest_path": str(entry.manifest_path),
        "frozen_actual_sha256": entry.authoritative_sha256,
        "frozen_actual_role": entry.role,
        "frozen_actual_loaded_via_canonical_loader": True,
        "forecast_outputs_used_to_build_actual": bool(manifest.get("forecast_outputs_used", False)),
        "optimisation_outputs_used_to_build_actual": bool(manifest.get("optimisation_outputs_used", False)),
        "economic_results_used_for_selection": bool(manifest.get("economic_results_used_for_selection", False)),
    }


def is_legacy_phase05_or_phase06_realized_path(path_or_text: str | Path) -> bool:
    normalized = str(path_or_text).replace("\\", "/").lower()
    return (
        ("phase05_runs/" in normalized and normalized.endswith("/counterfactual_realized_15min_long.csv"))
        or ("phase06_runs/" in normalized and "/counterfactual_15min_realized__" in normalized and normalized.endswith("/data.csv"))
        or ("phase06_runs/" in normalized and "/counterfactual_15min_realized__" in normalized and normalized.endswith("/data.parquet"))
    )


def assert_thesis_grade_actual_source_authorized(
    source: str | Path,
    *,
    config: QuarterHourDAExtensionConfig | None = None,
    thesis_grade: bool = True,
) -> None:
    if not thesis_grade:
        return
    config = config or QuarterHourDAExtensionConfig()
    normalized = Path(str(source)).resolve()
    if is_legacy_phase05_or_phase06_realized_path(normalized):
        raise ValueError(LEGACY_ACTUAL_PATH_REJECTION_MESSAGE)
    try:
        normalized.relative_to(config.frozen_actual_root.resolve())
    except ValueError as exc:
        raise ValueError(
            "Thesis-grade actual market truth must be loaded from the frozen actual-path registry under "
            f"{config.frozen_actual_root}."
        ) from exc


def _build_canonical_frame(realized: pd.DataFrame, *, canonical_variant: str, version_id: str) -> pd.DataFrame:
    frame = realized[realized["scenario_variant"].astype(str) == str(canonical_variant)].copy()
    if frame.empty:
        raise ValueError(f"Canonical variant '{canonical_variant}' was not present in the generated realized paths.")
    frame = frame.sort_values(["timestamp_utc"]).reset_index(drop=True)
    frame["counterfactual_actual_price_eur_per_mwh"] = pd.to_numeric(
        frame["predicted_price_eur_per_mwh"],
        errors="coerce",
    )
    frame["observed_hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(
        frame["hourly_anchor_price_eur_per_mwh"],
        errors="coerce",
    )
    frame["shape_sampler_source_hour_start_utc"] = frame["sampled_delta_source_hour_start_utc"]
    frame["shape_sampler_backoff_level"] = frame["sampler_backoff_level"]
    frame["actual_path_role"] = "frozen_counterfactual_actual_market_path"
    frame["actual_path_version"] = str(version_id)
    frame["actual_path_variant"] = str(canonical_variant)
    columns = [
        "timestamp_utc",
        "timestamp_local",
        "delivery_local_date",
        "hour_start_utc",
        "hour_start_local",
        "local_hour_of_day",
        "local_minute",
        "quarter_index",
        "counterfactual_actual_price_eur_per_mwh",
        "observed_hourly_anchor_price_eur_per_mwh",
        "sampled_delta_eur_per_mwh",
        "shape_sampler_source_hour_start_utc",
        "shape_sampler_backoff_level",
        "actual_path_role",
        "actual_path_version",
        "actual_path_variant",
    ]
    return frame[columns].reset_index(drop=True)


def _diagnostic_row(
    *,
    section: str,
    group: str,
    metric: str,
    value: Any,
    status: str = "info",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "section": section,
        "group": group,
        "metric": metric,
        "value": value,
        "status": status,
        "notes": notes,
    }


def _build_diagnostics(
    *,
    canonical_frame: pd.DataFrame,
    random_seed: int,
    canonical_variant: str,
    version_id: str,
    config: QuarterHourDAExtensionConfig,
    phase02_run: Path,
    shape_target_path: Path,
    hourly_source_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    frame = canonical_frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["hour_start_utc"] = pd.to_datetime(frame["hour_start_utc"], utc=True, errors="coerce")
    frame["timestamp_local"] = pd.to_datetime(frame["timestamp_local"], utc=True, errors="coerce")
    frame["hour_start_local"] = pd.to_datetime(frame["hour_start_local"], utc=True, errors="coerce")
    frame["counterfactual_actual_price_eur_per_mwh"] = pd.to_numeric(
        frame["counterfactual_actual_price_eur_per_mwh"],
        errors="coerce",
    )
    frame["observed_hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(
        frame["observed_hourly_anchor_price_eur_per_mwh"],
        errors="coerce",
    )
    frame["sampled_delta_eur_per_mwh"] = pd.to_numeric(frame["sampled_delta_eur_per_mwh"], errors="coerce")

    timestamps = pd.DatetimeIndex(frame["timestamp_utc"]).sort_values()
    expected = pd.date_range(start=timestamps.min(), end=timestamps.max(), freq="15min", tz="UTC")
    missing_timestamps = int(expected.difference(timestamps).shape[0])
    duplicate_timestamps = int(frame["timestamp_utc"].duplicated().sum())
    inferred_freq = pd.infer_freq(timestamps[: min(len(timestamps), 1000)]) if len(timestamps) >= 3 else None

    rows.extend(
        [
            _diagnostic_row(
                section="timestamp_completeness",
                group="overall",
                metric="row_count",
                value=int(frame.shape[0]),
                status="pass",
            ),
            _diagnostic_row(
                section="timestamp_completeness",
                group="overall",
                metric="duplicate_timestamps",
                value=duplicate_timestamps,
                status="pass" if duplicate_timestamps == 0 else "fail",
            ),
            _diagnostic_row(
                section="timestamp_completeness",
                group="overall",
                metric="missing_timestamps",
                value=missing_timestamps,
                status="pass" if missing_timestamps == 0 else "fail",
            ),
            _diagnostic_row(
                section="timestamp_completeness",
                group="overall",
                metric="inferred_utc_frequency",
                value=inferred_freq or "unknown",
                status="pass" if inferred_freq == "15min" else "warn",
                notes="Internal canonical storage remains UTC.",
            ),
        ]
    )

    local_day_counts = (
        frame.groupby("delivery_local_date", dropna=False)
        .size()
        .rename("quarterhour_count")
        .reset_index()
        .sort_values("delivery_local_date")
        .reset_index(drop=True)
    )
    nonstandard_days = local_day_counts[local_day_counts["quarterhour_count"].ne(96)].copy()
    rows.append(
        _diagnostic_row(
            section="timestamp_completeness",
            group="local_day_counts",
            metric="non_96_quarterhour_days",
            value=int(nonstandard_days.shape[0]),
            status="pass",
            notes="DST is explicit in local reporting while UTC storage stays regular.",
        )
    )
    if not nonstandard_days.empty:
        for row in nonstandard_days.to_dict(orient="records"):
            rows.append(
                _diagnostic_row(
                    section="dst_handling",
                    group=str(row["delivery_local_date"]),
                    metric="quarterhour_count",
                    value=int(row["quarterhour_count"]),
                    status="info",
                    notes="Local-day quarter-hour count departs from 96 because of DST.",
                )
            )

    hourly_reconciliation = (
        frame.groupby("hour_start_utc", dropna=False)
        .agg(
            synthetic_hour_mean=("counterfactual_actual_price_eur_per_mwh", "mean"),
            observed_hour_anchor=("observed_hourly_anchor_price_eur_per_mwh", "first"),
        )
        .reset_index()
    )
    hourly_reconciliation["reconciliation_error"] = (
        hourly_reconciliation["synthetic_hour_mean"] - hourly_reconciliation["observed_hour_anchor"]
    )
    abs_recon = hourly_reconciliation["reconciliation_error"].abs()
    rows.extend(
        [
            _diagnostic_row(
                section="hourly_reconciliation",
                group="overall",
                metric="mean_abs_error",
                value=float(abs_recon.mean()),
                status="pass" if float(abs_recon.max()) < 1e-9 else "warn",
            ),
            _diagnostic_row(
                section="hourly_reconciliation",
                group="overall",
                metric="max_abs_error",
                value=float(abs_recon.max()),
                status="pass" if float(abs_recon.max()) < 1e-9 else "fail",
                notes="Canonical construction enforces zero-mean within-hour deviations.",
            ),
            _diagnostic_row(
                section="hourly_reconciliation",
                group="overall",
                metric="p95_abs_error",
                value=float(abs_recon.quantile(0.95)),
                status="pass",
            ),
        ]
    )

    rows.extend(
        [
            _diagnostic_row(
                section="input_independence",
                group="governance",
                metric="forecast_outputs_used",
                value=False,
                status="pass",
                notes="Canonical actual-path generation uses observed hourly actuals plus the observed quarter-hour shape library only.",
            ),
            _diagnostic_row(
                section="input_independence",
                group="governance",
                metric="optimisation_outputs_used",
                value=False,
                status="pass",
            ),
            _diagnostic_row(
                section="input_independence",
                group="governance",
                metric="economic_results_used_for_selection",
                value=False,
                status="pass",
            ),
            _diagnostic_row(
                section="forecast_origin_safety",
                group="contract",
                metric="canonical_actual_path_is_read_only_for_downstream_forecasts",
                value=True,
                status="pass",
                notes="Forecast/scenario artifacts must live outside the frozen actual-path version directory.",
            ),
            _diagnostic_row(
                section="randomness_governance",
                group="overall",
                metric="random_seed",
                value=int(random_seed),
                status="pass",
            ),
            _diagnostic_row(
                section="randomness_governance",
                group="overall",
                metric="canonical_variant",
                value=str(canonical_variant),
                status="pass",
                notes="The canonical variant is pre-specified and not selected by downstream economics.",
            ),
            _diagnostic_row(
                section="randomness_governance",
                group="overall",
                metric="version_id",
                value=str(version_id),
                status="pass",
            ),
        ]
    )

    price = frame["counterfactual_actual_price_eur_per_mwh"].astype(float)
    abs_delta = frame["sampled_delta_eur_per_mwh"].abs().astype(float)
    intra_hour_spread = (
        frame.groupby("hour_start_utc", dropna=False)["counterfactual_actual_price_eur_per_mwh"]
        .agg(lambda values: float(np.max(values) - np.min(values)))
        .astype(float)
    )
    distribution_metrics = {
        "mean_price": float(price.mean()),
        "std_price": float(price.std(ddof=0)),
        "min_price": float(price.min()),
        "max_price": float(price.max()),
        "negative_share": float(price.lt(0.0).mean()),
        "p01_price": float(price.quantile(0.01)),
        "p05_price": float(price.quantile(0.05)),
        "p50_price": float(price.quantile(0.50)),
        "p95_price": float(price.quantile(0.95)),
        "p99_price": float(price.quantile(0.99)),
        "share_price_gt_200": float(price.gt(200.0).mean()),
        "share_price_gt_500": float(price.gt(500.0).mean()),
        "mean_abs_quarterhour_deviation": float(abs_delta.mean()),
        "p95_abs_quarterhour_deviation": float(abs_delta.quantile(0.95)),
        "mean_intra_hour_spread": float(intra_hour_spread.mean()),
        "p95_intra_hour_spread": float(intra_hour_spread.quantile(0.95)),
    }
    rows.extend(
        _diagnostic_row(
            section="distribution",
            group="overall",
            metric=metric,
            value=value,
            status="info",
        )
        for metric, value in distribution_metrics.items()
    )

    season_summary = (
        frame.assign(
            local_month=frame["timestamp_local"].dt.month,
            season=np.select(
                [
                    frame["timestamp_local"].dt.month.isin([12, 1, 2]),
                    frame["timestamp_local"].dt.month.isin([3, 4, 5]),
                    frame["timestamp_local"].dt.month.isin([6, 7, 8]),
                ],
                ["winter", "spring", "summer"],
                default="autumn",
            ),
        )
        .groupby("season", dropna=False)["counterfactual_actual_price_eur_per_mwh"]
        .agg(["mean", "std", "min", "max"])
        .reset_index()
    )
    for row in season_summary.to_dict(orient="records"):
        rows.extend(
            [
                _diagnostic_row(
                    section="distribution_by_season",
                    group=str(row["season"]),
                    metric="mean_price",
                    value=float(row["mean"]),
                    status="info",
                ),
                _diagnostic_row(
                    section="distribution_by_season",
                    group=str(row["season"]),
                    metric="std_price",
                    value=float(row["std"]) if pd.notna(row["std"]) else np.nan,
                    status="info",
                ),
            ]
        )

    diagnostics = pd.DataFrame(rows)
    summary = {
        "phase02_run_dir": str(phase02_run),
        "shape_target_path": str(shape_target_path),
        "hourly_actual_source_path": str(hourly_source_path),
        "canonical_period_start_local_date": str(frame["delivery_local_date"].min()),
        "canonical_period_end_local_date": str(frame["delivery_local_date"].max()),
        "row_count": int(frame.shape[0]),
        "hour_count": int(frame["hour_start_utc"].nunique()),
        "missing_timestamps": missing_timestamps,
        "duplicate_timestamps": duplicate_timestamps,
        "max_hourly_reconciliation_abs_error": float(abs_recon.max()),
        "mean_hourly_reconciliation_abs_error": float(abs_recon.mean()),
        "negative_price_share": float(price.lt(0.0).mean()),
    }
    return diagnostics, summary


def run_freeze_canonical_actual_path(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    version_id: str = DEFAULT_CANONICAL_VERSION,
    canonical_variant: str = DEFAULT_CANONICAL_VARIANT,
    random_seed: int = 42,
    overwrite: bool = False,
) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    if overwrite:
        raise ValueError("Overwrite is disabled. Create a new version id such as 'canonical_v2' instead.")

    version_dir = config.frozen_actual_version_dir(version_id)
    if version_dir.exists():
        raise FileExistsError(
            f"Frozen actual version already exists at {version_dir}. "
            "Create a new version identifier instead of overwriting the canonical artifact."
        )

    run_id = _timestamped_run_id()
    run_dir = config.canonical_actual_runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    phase02_run, model_table, _ = _load_phase02_model_table(config)
    shape_target_path = phase02_run / "shape_target_long.csv"
    observed_start = str(model_table["delivery_local_date"].min())
    observed_end = str(model_table["delivery_local_date"].max())
    library, thresholds = _build_observed_shape_library(model_table.reset_index(drop=True))

    hourly_actuals = _load_hourly_actuals(config)
    hourly_actuals.to_csv(run_dir / "hourly_actual_test_period.csv", index=False)

    realized, backoff = _generate_counterfactual_realized_paths(
        hourly_actuals,
        library=library,
        thresholds=thresholds,
        random_seed=random_seed,
    )
    realized.to_csv(run_dir / "counterfactual_realized_15min_long.csv", index=False)
    backoff.to_csv(run_dir / "counterfactual_sampler_backoff_log.csv", index=False)

    generation_summary, backoff_summary = _counterfactual_generation_summary(
        realized,
        backoff,
        observed_start=observed_start,
        observed_end=observed_end,
        random_seed=random_seed,
    )
    generation_summary.to_csv(run_dir / "counterfactual_generation_summary.csv", index=False)
    backoff_summary.to_csv(run_dir / "counterfactual_backoff_summary.csv", index=False)

    canonical_frame = _build_canonical_frame(
        realized,
        canonical_variant=canonical_variant,
        version_id=version_id,
    )
    diagnostics, diagnostic_summary = _build_diagnostics(
        canonical_frame=canonical_frame,
        random_seed=random_seed,
        canonical_variant=canonical_variant,
        version_id=version_id,
        config=config,
        phase02_run=phase02_run,
        shape_target_path=shape_target_path,
        hourly_source_path=config.shared_hourly_csv,
    )
    diagnostics.to_csv(run_dir / DIAGNOSTICS_CSV_NAME, index=False)
    (run_dir / DIAGNOSTICS_JSON_NAME).write_text(
        json.dumps(diagnostic_summary, indent=2, default=str),
        encoding="utf-8",
    )

    version_dir.mkdir(parents=True, exist_ok=False)
    canonical_csv_path = version_dir / CANONICAL_CSV_NAME
    canonical_parquet_path = version_dir / CANONICAL_PARQUET_NAME
    diagnostics_csv_path = version_dir / DIAGNOSTICS_CSV_NAME
    diagnostics_json_path = version_dir / DIAGNOSTICS_JSON_NAME
    manifest_path = version_dir / MANIFEST_NAME
    hash_path = version_dir / HASH_NAME

    canonical_frame.to_csv(canonical_csv_path, index=False)
    canonical_frame.to_parquet(canonical_parquet_path, index=False)
    diagnostics.to_csv(diagnostics_csv_path, index=False)
    diagnostics_json_path.write_text(json.dumps(diagnostic_summary, indent=2, default=str), encoding="utf-8")

    csv_hash = _sha256_file(canonical_csv_path)
    parquet_hash = _sha256_file(canonical_parquet_path)

    manifest = {
        "role": "frozen counterfactual actual market path",
        "version_id": str(version_id),
        "generation_timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "generator_module": "quarterhour_da.canonical_actual",
        "generator_git_commit": _git_commit(config.repo_root),
        "generator_run_dir": str(run_dir),
        "input_hourly_price_source": str(config.shared_hourly_csv),
        "input_quarterhour_shape_source": str(shape_target_path),
        "input_phase02_run_dir": str(phase02_run),
        "evaluation_period": {
            "start_local_date": diagnostic_summary["canonical_period_start_local_date"],
            "end_local_date": diagnostic_summary["canonical_period_end_local_date"],
        },
        "timezone_convention": {
            "internal_storage_timezone": "UTC",
            "reporting_timezone": config.business_timezone,
        },
        "random_seed": int(random_seed),
        "forecast_outputs_used": False,
        "optimisation_outputs_used": False,
        "economic_results_used_for_selection": False,
        "hourly_reconciliation_rule": (
            "For each hour, the arithmetic mean of the four quarter-hour synthetic prices equals the observed hourly DA price "
            "after zero-mean normalization of the sampled within-hour deviation vector."
        ),
        "canonical_variant": str(canonical_variant),
        "available_diagnostic_variants": [
            "flat",
            "low_volatility",
            "empirical_medium",
            "high_volatility",
            "stress",
        ],
        "file_hash_sha256": {
            "csv": csv_hash,
            "parquet": parquet_hash,
        },
        "frozen_files": {
            "canonical_csv": str(canonical_csv_path),
            "canonical_parquet": str(canonical_parquet_path),
            "diagnostics_csv": str(diagnostics_csv_path),
            "diagnostics_json": str(diagnostics_json_path),
            "hash_file": str(hash_path),
        },
        "known_limitations": [
            "The frozen 15-minute path is a plausible counterfactual environment, not a direct historical backtest of realized 15-minute DA prices for the hourly test year.",
            "The within-hour shape library is estimated from the observed Dutch quarter-hour DA period available in the repository and then projected onto the earlier official hourly test year.",
            "Downstream bidding results are conditional on this single frozen market environment unless additional robustness variants are explicitly studied.",
        ],
        "methodology_note": (
            "Because a full historical 15-minute DA test year is not available for the study period, this repository freezes one canonical "
            "counterfactual 15-minute realized path before downstream bidding analysis. The path is generated from a pre-specified empirical "
            "within-hour sampler anchored to observed hourly DA prices and is not selected by forecast, optimization, or economic outcomes."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    hash_path.write_text(
        "\n".join(
            [
                f"csv_sha256 {csv_hash}",
                f"parquet_sha256 {parquet_hash}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    run_summary = {
        "run_id": run_id,
        "phase": "canonical_actual_freeze",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "phase02_run_dir": str(phase02_run),
        "shape_library_observed_start": observed_start,
        "shape_library_observed_end": observed_end,
        "canonical_variant": str(canonical_variant),
        "version_id": str(version_id),
        "frozen_version_dir": str(version_dir),
        "diagnostic_summary": diagnostic_summary,
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return version_dir
