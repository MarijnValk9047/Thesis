from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .plant_parameters import HydrogenConfig

REQUIRED_SCHEMA_COLUMNS: tuple[str, ...] = (
    "forecast_origin_utc",
    "delivery_start_utc",
    "delivery_start_local",
    "delivery_day",
    "lead_day",
    "model_id",
    "scenario_id",
    "scenario_probability",
    "point_forecast_eur_per_mwh",
    "scenario_price_eur_per_mwh",
    "actual_price_eur_per_mwh",
    "granularity",
    "scenario_generation_run_id",
)

SCHEMA_ALIASES: dict[str, tuple[str, ...]] = {
    "forecast_origin_utc": ("forecast_origin_utc",),
    "delivery_start_utc": ("delivery_start_utc", "period_timestamp", "target_timestamp_utc"),
    "delivery_start_local": ("delivery_start_local", "period_timestamp_local", "target_timestamp_local"),
    "delivery_day": ("delivery_day", "target_local_date"),
    "lead_day": ("lead_day",),
    "model_id": ("model_id", "candidate_key", "model", "source_model"),
    "scenario_id": ("scenario_id",),
    "scenario_probability": ("scenario_probability", "probability", "reduced_scenario_probability"),
    "point_forecast_eur_per_mwh": ("point_forecast_eur_per_mwh", "central_forecast_price", "point_forecast", "y_pred"),
    "scenario_price_eur_per_mwh": ("scenario_price_eur_per_mwh", "scenario_price"),
    "actual_price_eur_per_mwh": ("actual_price_eur_per_mwh", "actual_price", "y_true"),
    "granularity": ("granularity",),
    "scenario_generation_run_id": ("scenario_generation_run_id", "scenario_run_id", "run_id"),
}


@dataclass(frozen=True)
class ScenarioArtifactSpec:
    artifact_key: str
    path: Path
    model_id: str
    dataset_split: str | None
    granularity: str | None
    validation_mode: str
    allow_forecast_origin_reconstruction: bool
    actuals_path: Path | None = None
    scenario_set_size: int | None = None


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv" or path.name.lower().endswith(".csv.gz"):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported scenario artifact format: {path}")


def _attach_separate_actuals(frame: pd.DataFrame, *, actuals_path: Path, granularity: str | None) -> pd.DataFrame:
    actuals = _read_table(actuals_path).copy()
    rename = {}
    if "target_timestamp_utc" in actuals.columns:
        rename["target_timestamp_utc"] = "delivery_start_utc"
    if "actual_price" in actuals.columns:
        rename["actual_price"] = "actual_price_eur_per_mwh"
    actuals = actuals.rename(columns=rename)
    required = {"forecast_origin_utc", "delivery_start_utc", "lead_day", "actual_price_eur_per_mwh"}
    missing = required.difference(actuals.columns)
    if missing:
        raise ValueError(f"Separate actuals artifact is missing columns: {sorted(missing)}")
    actuals["forecast_origin_utc"] = pd.to_datetime(actuals["forecast_origin_utc"], utc=True, errors="raise")
    actuals["delivery_start_utc"] = pd.to_datetime(actuals["delivery_start_utc"], utc=True, errors="raise")
    if granularity is not None and "granularity" in actuals.columns:
        actuals = actuals[actuals["granularity"].astype(str).str.lower() == str(granularity).lower()].copy()
    keys = ["forecast_origin_utc", "delivery_start_utc", "lead_day"]
    if "granularity" in frame.columns and "granularity" in actuals.columns:
        keys.append("granularity")
    actuals = actuals[keys + ["actual_price_eur_per_mwh"]].drop_duplicates(keys)
    if actuals.duplicated(keys).any():
        raise ValueError("Separate actuals artifact has duplicate origin/timestamp keys.")
    return frame.merge(actuals, on=keys, how="left", validate="many_to_one")


def _pick_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> pd.Series | None:
    for name in candidates:
        if name in frame.columns:
            return frame[name]
    return None


def _normalize_schema(
    frame: pd.DataFrame,
    *,
    fallback_model_id: str | None,
    fallback_granularity: str | None,
    allow_forecast_origin_reconstruction: bool,
) -> tuple[pd.DataFrame, bool]:
    normalized = pd.DataFrame(index=frame.index)
    used_forecast_origin_reconstruction = False
    for target, aliases in SCHEMA_ALIASES.items():
        source = _pick_column(frame, aliases)
        if source is not None:
            normalized[target] = source

    if "model_id" not in normalized.columns and fallback_model_id is not None:
        normalized["model_id"] = fallback_model_id
    if "granularity" not in normalized.columns and fallback_granularity is not None:
        normalized["granularity"] = fallback_granularity
    if "scenario_generation_run_id" not in normalized.columns:
        normalized["scenario_generation_run_id"] = "unknown_scenario_run"
    if "dataset_split" in frame.columns:
        normalized["dataset_split"] = frame["dataset_split"].astype(str)
    for optional_column in (
        "scenario_set_size",
        "parent_scenario_id",
        "source_residual_block_id",
    ):
        if optional_column in frame.columns:
            normalized[optional_column] = frame[optional_column]

    if "delivery_start_local" not in normalized.columns and "delivery_start_utc" in normalized.columns:
        delivery_utc = pd.to_datetime(normalized["delivery_start_utc"], utc=True, errors="coerce")
        normalized["delivery_start_local"] = delivery_utc.dt.tz_convert("Europe/Amsterdam")
    if "delivery_start_utc" in normalized.columns:
        normalized["delivery_start_utc"] = pd.to_datetime(normalized["delivery_start_utc"], utc=True, errors="coerce")
    if "delivery_start_local" in normalized.columns:
        local = pd.to_datetime(normalized["delivery_start_local"], errors="coerce")
        if getattr(local.dt, "tz", None) is None:
            local = local.dt.tz_localize("Europe/Amsterdam", nonexistent="shift_forward", ambiguous="NaT")
        normalized["delivery_start_local"] = local
    if "forecast_origin_utc" in normalized.columns:
        normalized["forecast_origin_utc"] = pd.to_datetime(normalized["forecast_origin_utc"], utc=True, errors="coerce")
    elif "delivery_start_utc" in normalized.columns:
        if not allow_forecast_origin_reconstruction:
            raise ValueError(
                "Scenario schema mapping failed: forecast_origin_utc is missing and reconstruction is disabled "
                "for this artifact."
            )
        delivery_local_day = pd.to_datetime(normalized["delivery_start_utc"], utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam").dt.floor("D")
        forecast_origin_local = delivery_local_day - pd.Timedelta(days=1) + pd.Timedelta(hours=8)
        normalized["forecast_origin_utc"] = forecast_origin_local.dt.tz_convert("UTC")
        used_forecast_origin_reconstruction = True

    if "delivery_day" not in normalized.columns and "delivery_start_local" in normalized.columns:
        normalized["delivery_day"] = normalized["delivery_start_local"].dt.date.astype(str)
    else:
        normalized["delivery_day"] = normalized["delivery_day"].astype(str)

    if "lead_day" not in normalized.columns:
        if {"delivery_start_utc", "forecast_origin_utc"}.issubset(normalized.columns):
            origin_local_day = normalized["forecast_origin_utc"].dt.tz_convert("Europe/Amsterdam").dt.floor("D")
            delivery_local_day = normalized["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam").dt.floor("D")
            # DA convention in this repo uses lead_day=0 for delivery day D when forecast origin is D-1 08:00.
            normalized["lead_day"] = (delivery_local_day - (origin_local_day + pd.Timedelta(days=1))).dt.days
        else:
            normalized["lead_day"] = 0
    normalized["lead_day"] = pd.to_numeric(normalized["lead_day"], errors="coerce").fillna(0).astype(int)

    for numeric_col in (
        "scenario_probability",
        "point_forecast_eur_per_mwh",
        "scenario_price_eur_per_mwh",
        "actual_price_eur_per_mwh",
    ):
        normalized[numeric_col] = pd.to_numeric(normalized[numeric_col], errors="coerce")

    missing = [column for column in REQUIRED_SCHEMA_COLUMNS if column not in normalized.columns]
    if missing:
        raise ValueError(f"Scenario schema mapping failed. Missing columns after normalization: {missing}")
    return normalized, used_forecast_origin_reconstruction


def _validate_probabilities(frame: pd.DataFrame) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if (frame["scenario_probability"] < 0).any():
        errors.append("Negative scenario probabilities detected.")
    dedup = frame[["forecast_origin_utc", "model_id", "lead_day", "scenario_id", "scenario_probability"]].drop_duplicates()
    sums = (
        dedup.groupby(["forecast_origin_utc", "model_id", "lead_day"], as_index=False)["scenario_probability"]
        .sum()
        .rename(columns={"scenario_probability": "probability_sum"})
    )
    bad = sums[~sums["probability_sum"].between(0.999999, 1.000001)]
    if not bad.empty:
        errors.append(f"Scenario probability sums are not 1 for {bad.shape[0]} origin/model/lead_day blocks.")
    count_frame = dedup.groupby(["forecast_origin_utc", "model_id", "lead_day"], as_index=False)["scenario_id"].nunique()
    return errors, {
        "group_count": int(sums.shape[0]),
        "failing_probability_blocks": int(bad.shape[0]),
        "scenario_count_min": int(count_frame["scenario_id"].min()) if not count_frame.empty else 0,
        "scenario_count_max": int(count_frame["scenario_id"].max()) if not count_frame.empty else 0,
        "scenario_count_median": float(count_frame["scenario_id"].median()) if not count_frame.empty else 0.0,
    }


def _validate_integrity(frame: pd.DataFrame, *, used_forecast_origin_reconstruction: bool) -> tuple[list[str], list[str]]:
    errors, probability_stats = _validate_probabilities(frame)
    warnings: list[str] = []
    if frame["actual_price_eur_per_mwh"].isna().any():
        errors.append("Missing actual_price_eur_per_mwh values were found.")
    if frame["forecast_origin_utc"].isna().any() or frame["delivery_start_utc"].isna().any():
        errors.append("Missing or invalid UTC timestamps were found in forecast_origin_utc or delivery_start_utc.")
    duplicate_rows = frame.duplicated(
        subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"],
        keep=False,
    )
    if bool(duplicate_rows.any()):
        errors.append(
            "Duplicate scenario rows were found for the same forecast_origin_utc, delivery_start_utc, scenario_id, and model_id."
        )
    fo_dtype = str(frame["forecast_origin_utc"].dtype)
    ds_dtype = str(frame["delivery_start_utc"].dtype)
    fo_utc = fo_dtype.startswith("datetime64[") and fo_dtype.endswith(", UTC]")
    ds_utc = ds_dtype.startswith("datetime64[") and ds_dtype.endswith(", UTC]")
    if not (fo_utc and ds_utc):
        errors.append("Scenario timestamps are not timezone-aware UTC after parsing.")
    if used_forecast_origin_reconstruction:
        warnings.append(
            "forecast_origin_utc was reconstructed from delivery timestamps (D-1 08:00 Europe/Amsterdam) for legacy compatibility."
        )
    warnings.append(
        "Scenario count per origin block: "
        f"min={probability_stats['scenario_count_min']}, "
        f"median={probability_stats['scenario_count_median']:.1f}, "
        f"max={probability_stats['scenario_count_max']}."
    )
    if frame["delivery_start_utc"].duplicated().all():
        warnings.append("All delivery_start_utc rows are duplicated; expected for long scenario tables with scenario dimension.")
    return errors, warnings


def load_scenario_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Scenario catalog file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid scenario catalog YAML: {path}")
    return payload


def resolve_artifact_specs(config: HydrogenConfig) -> list[ScenarioArtifactSpec]:
    payload = load_scenario_catalog(config.models.scenario_catalog)
    default_artifact = payload.get("default_artifact")
    artifact_map = payload.get("artifacts", {})
    if not isinstance(artifact_map, dict):
        raise ValueError("scenario_catalog.yaml must contain an 'artifacts' mapping.")

    include_keys = list(config.models.include)
    if not include_keys:
        if not default_artifact:
            raise ValueError(
                "No scenario artifacts were configured in models.include and scenario_catalog has no default_artifact."
            )
        include_keys = [str(default_artifact)]

    specs: list[ScenarioArtifactSpec] = []
    for artifact_key in include_keys:
        if artifact_key not in artifact_map:
            raise KeyError(f"Scenario artifact '{artifact_key}' is missing in {config.models.scenario_catalog}")
        raw = artifact_map[artifact_key]
        if not isinstance(raw, dict):
            raise ValueError(f"Scenario artifact '{artifact_key}' must be a mapping.")
        artifact_path = Path(str(raw["path"]))
        if not artifact_path.is_absolute():
            artifact_path = (config.repo_root / artifact_path).resolve()
        validation_mode = str(raw.get("validation_mode", "thesis_grade")).strip().lower()
        if validation_mode not in {"thesis_grade", "smoke_test"}:
            raise ValueError(
                f"Unsupported validation_mode for artifact '{artifact_key}': {validation_mode}. "
                "Use 'thesis_grade' or 'smoke_test'."
            )
        allow_reconstruction = bool(raw.get("allow_forecast_origin_reconstruction", False))
        actuals_path = Path(str(raw["actuals_path"])) if raw.get("actuals_path") else None
        if actuals_path is not None and not actuals_path.is_absolute():
            actuals_path = (config.repo_root / actuals_path).resolve()
        specs.append(
            ScenarioArtifactSpec(
                artifact_key=str(artifact_key),
                path=artifact_path,
                model_id=str(raw.get("model_id", artifact_key)),
                dataset_split=str(raw["dataset_split"]) if raw.get("dataset_split") is not None else None,
                granularity=str(raw["granularity"]) if raw.get("granularity") is not None else None,
                validation_mode=validation_mode,
                allow_forecast_origin_reconstruction=allow_reconstruction,
                actuals_path=actuals_path,
                scenario_set_size=int(raw["scenario_set_size"]) if raw.get("scenario_set_size") is not None else None,
            )
        )
    return specs


def load_scenarios_for_artifact(
    spec: ScenarioArtifactSpec,
    *,
    config: HydrogenConfig,
    frame_override: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    if not spec.path.exists():
        raise FileNotFoundError(
            "Scenario input not found for "
            f"'{spec.artifact_key}' ({spec.validation_mode}): {spec.path}. "
            "Update scenario_catalog.yaml to an existing artifact path before running optimisation."
        )
    frame = frame_override.copy() if frame_override is not None else _read_table(spec.path)
    if spec.scenario_set_size is not None and "scenario_set_size" in frame.columns:
        frame = frame[pd.to_numeric(frame["scenario_set_size"], errors="coerce") == int(spec.scenario_set_size)].copy()
    if "actual_price_eur_per_mwh" not in frame.columns and "actual_price" not in frame.columns and "y_true" not in frame.columns:
        if spec.actuals_path is None:
            raise ValueError(
                f"Scenario artifact '{spec.artifact_key}' contains no actuals and has no separate actuals_path."
            )
        if not spec.actuals_path.exists():
            raise FileNotFoundError(f"Separate actuals artifact not found: {spec.actuals_path}")
        pre_normalized = frame.rename(columns={"target_timestamp_utc": "delivery_start_utc"}).copy()
        pre_normalized["forecast_origin_utc"] = pd.to_datetime(pre_normalized["forecast_origin_utc"], utc=True, errors="raise")
        pre_normalized["delivery_start_utc"] = pd.to_datetime(pre_normalized["delivery_start_utc"], utc=True, errors="raise")
        frame = _attach_separate_actuals(pre_normalized, actuals_path=spec.actuals_path, granularity=spec.granularity)
    normalized, used_reconstruction = _normalize_schema(
        frame,
        fallback_model_id=spec.model_id,
        fallback_granularity=spec.granularity,
        allow_forecast_origin_reconstruction=spec.allow_forecast_origin_reconstruction,
    )

    if spec.dataset_split and "dataset_split" in frame.columns:
        normalized = normalized[frame["dataset_split"].astype(str) == spec.dataset_split].copy()
    if spec.model_id:
        normalized = normalized[normalized["model_id"].astype(str) == str(spec.model_id)].copy()
    if config.experiment.horizon_mode.strip().upper() == "D_ONLY":
        normalized = normalized[normalized["lead_day"] == 0].copy()
    if normalized.empty:
        available_models = sorted(frame["candidate_key"].dropna().astype(str).unique().tolist()) if "candidate_key" in frame.columns else []
        available_days = pd.to_datetime(frame["delivery_day"], errors="coerce") if "delivery_day" in frame.columns else pd.Series(dtype="datetime64[ns]")
        min_day = str(available_days.min().date()) if not available_days.dropna().empty else "unknown"
        max_day = str(available_days.max().date()) if not available_days.dropna().empty else "unknown"
        raise ValueError(
            "Scenario dataset is empty after filtering for artifact "
            f"'{spec.artifact_key}' (model_id={spec.model_id}, split={spec.dataset_split}, horizon={config.experiment.horizon_mode}). "
            f"Available file coverage: {min_day}..{max_day}; candidate_key values: {available_models[:10]}"
        )
    errors, warnings = _validate_integrity(
        normalized,
        used_forecast_origin_reconstruction=used_reconstruction,
    )
    normalized["scenario_validation_mode"] = spec.validation_mode
    normalized["allow_forecast_origin_reconstruction"] = bool(spec.allow_forecast_origin_reconstruction)
    normalized["scenario_artifact_key"] = spec.artifact_key

    if errors and spec.validation_mode == "thesis_grade":
        joined = "; ".join(errors)
        raise ValueError(
            f"Thesis-grade scenario artifact '{spec.artifact_key}' failed validation: {joined}"
        )

    findings: list[str] = []
    if errors:
        findings.extend([f"SMOKE_WARNING: {message}" for message in errors])
    findings.extend([f"INFO: {message}" for message in warnings])
    return normalized.reset_index(drop=True), findings


def load_all_scenarios(config: HydrogenConfig) -> tuple[pd.DataFrame, list[ScenarioArtifactSpec], list[str]]:
    frames: list[pd.DataFrame] = []
    specs = resolve_artifact_specs(config)
    all_errors: list[str] = []
    for spec in specs:
        frame, findings = load_scenarios_for_artifact(spec, config=config)
        frame["artifact_key"] = spec.artifact_key
        frames.append(frame)
        all_errors.extend([f"{spec.artifact_key}: {finding}" for finding in findings])
    combined = pd.concat(frames, ignore_index=True)
    if config.experiment.granularity:
        combined = combined[combined["granularity"].astype(str).str.lower() == config.experiment.granularity.lower()].copy()
    if combined.empty:
        raise ValueError("No scenarios remain after artifact and granularity filtering.")
    return combined.reset_index(drop=True), specs, all_errors
