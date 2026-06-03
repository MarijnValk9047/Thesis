from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.scenario_loader import _normalize_schema


SCENARIO_FILE_PATTERNS: tuple[str, ...] = (
    "scenario_prices_long.csv",
    "scenario_prices_long.parquet",
    "scenarios_long.csv",
    "scenarios_long.parquet",
)


@dataclass(frozen=True)
class CandidateArtifact:
    artifact_id: str
    file_path: Path
    source: str
    apparent_model: str | None
    raw_model_id: str | None
    granularity: str | None
    dataset_split: str | None
    validation_mode_hint: str | None
    allow_forecast_origin_reconstruction: bool
    summary_path: Path | None
    notes: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported scenario artifact format: {path}")


def _safe_to_iso(value: Any) -> str:
    if pd.isna(value):
        return ""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.isoformat()


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return value


def _artifact_id_from_path(path: Path) -> str:
    parent = path.parent.name or "root"
    grandparent = path.parent.parent.name or "parent"
    stem = path.stem.replace(".", "_")
    return f"direct_{grandparent}_{parent}_{stem}"


def _infer_granularity_from_path(path: Path) -> str | None:
    text = str(path).lower()
    if "quarterhour" in text or "quarter_hour" in text or "15min" in text:
        return "quarter_hour"
    if "hourly" in text:
        return "hourly"
    return None


def _load_catalog_candidates(repo_root: Path, catalog_path: Path) -> list[CandidateArtifact]:
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    artifact_map = payload.get("artifacts", {}) if isinstance(payload, dict) else {}
    candidates: list[CandidateArtifact] = []
    for artifact_id, raw in artifact_map.items():
        if not isinstance(raw, dict):
            continue
        path = Path(str(raw.get("path", "")))
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        candidates.append(
            CandidateArtifact(
                artifact_id=str(artifact_id),
                file_path=path,
                source="scenario_catalog",
                apparent_model=str(raw.get("model_id") or artifact_id),
                raw_model_id=str(raw.get("model_id")) if raw.get("model_id") is not None else None,
                granularity=str(raw.get("granularity")) if raw.get("granularity") is not None else None,
                dataset_split=str(raw.get("dataset_split")) if raw.get("dataset_split") is not None else None,
                validation_mode_hint=str(raw.get("validation_mode")) if raw.get("validation_mode") is not None else None,
                allow_forecast_origin_reconstruction=bool(raw.get("allow_forecast_origin_reconstruction", False)),
                summary_path=None,
                notes="catalog entry",
            )
        )
    return candidates


def _load_registry_candidates(repo_root: Path) -> list[CandidateArtifact]:
    registry_path = repo_root / "data/02_Forecasting/01_DA_prices/scenario_evaluation/20260513_102807/tables/scenario_load_registry.csv"
    if not registry_path.exists():
        return []
    frame = pd.read_csv(registry_path)
    frame = frame.drop_duplicates(subset=["canonical_model_key", "scenario_path"])
    candidates: list[CandidateArtifact] = []
    for row in frame.itertuples(index=False):
        notes = []
        warnings = str(getattr(row, "warnings", "") or "").strip()
        if warnings:
            notes.append(warnings)
        if bool(getattr(row, "scenario_path", "")):
            notes.append(f"registry rows={getattr(row, 'rows', '')}")
        candidates.append(
            CandidateArtifact(
                artifact_id=f"{row.canonical_model_key}__{row.run_id}",
                file_path=Path(str(row.scenario_path)),
                source="scenario_load_registry",
                apparent_model=str(row.canonical_model_key),
                raw_model_id=str(row.raw_model_id) if getattr(row, "raw_model_id", None) is not None else None,
                granularity=str(row.granularity) if getattr(row, "granularity", None) is not None else None,
                dataset_split=None,
                validation_mode_hint=None,
                allow_forecast_origin_reconstruction="forecast_origin_utc reconstructed" in warnings,
                summary_path=Path(str(row.summary_path)) if getattr(row, "summary_path", None) else None,
                notes=" | ".join(notes),
            )
        )
    return candidates


def _discover_unregistered_files(repo_root: Path, known_paths: set[Path]) -> list[CandidateArtifact]:
    roots = [
        repo_root / "data/02_Forecasting",
        repo_root / "data/03_Optimisation",
    ]
    discovered: list[CandidateArtifact] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in SCENARIO_FILE_PATTERNS:
            for path in root.rglob(pattern):
                resolved = path.resolve()
                if resolved in known_paths:
                    continue
                discovered.append(
                    CandidateArtifact(
                        artifact_id=_artifact_id_from_path(resolved),
                        file_path=resolved,
                        source="filesystem_discovery",
                        apparent_model=None,
                        raw_model_id=None,
                        granularity=_infer_granularity_from_path(resolved),
                        dataset_split=None,
                        validation_mode_hint=None,
                        allow_forecast_origin_reconstruction=True,
                        summary_path=None,
                        notes="direct file-system discovery",
                    )
                )
    return discovered


def _filter_artifact_frame(frame: pd.DataFrame, candidate: CandidateArtifact) -> pd.DataFrame:
    if candidate.raw_model_id and "candidate_key" in frame.columns:
        matched = frame.loc[frame["candidate_key"].astype(str) == candidate.raw_model_id].copy()
        if not matched.empty:
            return matched
    if candidate.raw_model_id and "model_id" in frame.columns:
        matched = frame.loc[frame["model_id"].astype(str) == candidate.raw_model_id].copy()
        if not matched.empty:
            return matched
    if candidate.apparent_model and "model_id" in frame.columns:
        matched = frame.loc[frame["model_id"].astype(str) == candidate.apparent_model].copy()
        if not matched.empty:
            return matched
    return frame.copy()


def _summarize_lead_day(frame: pd.DataFrame) -> str:
    if "lead_day" not in frame.columns or frame.empty:
        return ""
    values = sorted(pd.unique(frame["lead_day"].dropna()))
    if not values:
        return ""
    if len(values) == 1:
        return f"lead_day={int(values[0])}"
    preview = ",".join(str(int(value)) for value in values[:5])
    return f"mixed:{preview}"


def _validate_probability_mass(frame: pd.DataFrame, artifact_id: str) -> tuple[pd.DataFrame, str, bool]:
    if frame.empty:
        return pd.DataFrame(), "schema/mapping issue", False

    raw_stats = (
        frame.groupby("forecast_origin_utc", as_index=False)
        .agg(
            number_of_rows=("scenario_id", "size"),
            min_probability=("scenario_probability", "min"),
            max_probability=("scenario_probability", "max"),
            has_negative_probability=("scenario_probability", lambda series: bool((series < 0).any())),
            raw_probability_sum_over_rows=("scenario_probability", "sum"),
        )
    )

    unique_stats = (
        frame[
            [
                "forecast_origin_utc",
                "model_id",
                "lead_day",
                "scenario_id",
                "scenario_probability",
            ]
        ]
        .drop_duplicates()
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            number_of_unique_scenarios=("scenario_id", "nunique"),
            probability_sum_over_unique_scenarios=("scenario_probability", "sum"),
        )
    )

    model_block = (
        frame[
            [
                "forecast_origin_utc",
                "model_id",
                "lead_day",
                "scenario_id",
                "scenario_probability",
            ]
        ]
        .drop_duplicates()
        .groupby(["forecast_origin_utc", "model_id", "lead_day"], as_index=False)["scenario_probability"]
        .sum()
    )
    mixed_origin = model_block.groupby("forecast_origin_utc")["scenario_probability"].apply(
        lambda series: bool(series.between(0.999999, 1.000001).all()) and len(series) > 1
    )

    variant_block_ok = pd.Series(dtype=bool)
    if "scenario_variant" in frame.columns:
        variant_block = (
            frame[
                [
                    "forecast_origin_utc",
                    "scenario_variant",
                    "scenario_id",
                    "scenario_probability",
                ]
            ]
            .drop_duplicates()
            .groupby(["forecast_origin_utc", "scenario_variant"], as_index=False)["scenario_probability"]
            .sum()
        )
        variant_block_ok = variant_block.groupby("forecast_origin_utc")["scenario_probability"].apply(
            lambda series: bool(series.between(0.999999, 1.000001).all()) and len(series) > 1
        )

    result = raw_stats.merge(unique_stats, on="forecast_origin_utc", how="left")

    diagnoses: list[str] = []
    overall_diagnosis = "valid"
    valid_unique_probability = True
    for row in result.itertuples(index=False):
        diagnosis = "valid"
        if bool(row.has_negative_probability):
            diagnosis = "genuinely invalid scenario probabilities"
            valid_unique_probability = False
        else:
            unique_ok = 0.999999 <= float(row.probability_sum_over_unique_scenarios) <= 1.000001
            raw_ok = 0.999999 <= float(row.raw_probability_sum_over_rows) <= 1.000001
            if unique_ok and not raw_ok:
                diagnosis = "false failure caused by summing repeated per-timestamp probabilities"
            elif not unique_ok:
                if bool(variant_block_ok.get(row.forecast_origin_utc, False)):
                    diagnosis = "schema/mapping issue"
                elif bool(mixed_origin.get(row.forecast_origin_utc, False)):
                    diagnosis = "mixed forecast-origin grouping issue"
                else:
                    diagnosis = "genuinely invalid scenario probabilities"
                valid_unique_probability = False
        diagnoses.append(diagnosis)
        if diagnosis != "valid" and overall_diagnosis == "valid":
            overall_diagnosis = diagnosis

    result["artifact_id"] = artifact_id
    result["diagnosis"] = diagnoses
    columns = [
        "artifact_id",
        "forecast_origin_utc",
        "number_of_rows",
        "number_of_unique_scenarios",
        "raw_probability_sum_over_rows",
        "probability_sum_over_unique_scenarios",
        "min_probability",
        "max_probability",
        "has_negative_probability",
        "diagnosis",
    ]
    result = result[columns].copy()
    result["forecast_origin_utc"] = result["forecast_origin_utc"].map(_safe_to_iso)
    return result, overall_diagnosis, valid_unique_probability


def _classify_candidate(
    candidate: CandidateArtifact,
    *,
    exists: bool,
    normalized: pd.DataFrame | None,
    used_reconstruction: bool,
    probability_diagnosis: str | None,
    probability_valid: bool | None,
) -> str:
    if not exists:
        return "missing_export_relink_or_regenerate"
    if normalized is None:
        return "schema_mapping_repair_required"
    if probability_diagnosis == "schema/mapping issue":
        return "schema_mapping_repair_required"
    if str(candidate.granularity or "").lower() not in {"", "hourly"} or (
        not str(candidate.granularity or "").lower() and "quarter" in str(candidate.file_path).lower()
    ):
        return "out_of_scope_for_hourly_phase6a_target"
    if used_reconstruction:
        return "smoke_test_only_reconstructed_origin"
    if probability_valid is False:
        return "smoke_test_only_invalid_probability_mass"
    if probability_valid is True:
        return "thesis_grade_candidate"
    return "manual_review_required"


def _inventory_row(candidate: CandidateArtifact, repo_root: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    row: dict[str, Any] = {
        "artifact_id": candidate.artifact_id,
        "file_path": str(candidate.file_path),
        "exists": candidate.file_path.exists(),
        "file_format": candidate.file_path.suffix.lower().lstrip("."),
        "apparent_model": _csv_value(candidate.apparent_model),
        "granularity": _csv_value(candidate.granularity or _infer_granularity_from_path(candidate.file_path)),
        "horizon_or_lead_day": "",
        "row_count": "",
        "forecast_origin_count": "",
        "scenario_count_min": "",
        "scenario_count_max": "",
        "delivery_timestamp_min": "",
        "delivery_timestamp_max": "",
        "has_forecast_origin_utc": False,
        "has_delivery_start_utc": False,
        "has_scenario_id": False,
        "has_probability": False,
        "has_price": False,
        "validation_mode_recommendation": "",
        "notes": candidate.notes,
    }
    probability_detail = pd.DataFrame()
    if not candidate.file_path.exists():
        row["validation_mode_recommendation"] = "missing_export_relink_or_regenerate"
        if candidate.summary_path and candidate.summary_path.exists():
            try:
                payload = json.loads(candidate.summary_path.read_text(encoding="utf-8"))
                horizon_mode = payload.get("horizon_mode")
                if horizon_mode:
                    row["horizon_or_lead_day"] = str(horizon_mode)
                rows_in_final = payload.get("rows_in_final_scenarios")
                if rows_in_final is not None:
                    row["notes"] = f"{row['notes']} | upstream rows_in_final_scenarios={rows_in_final}".strip(" |")
            except Exception:  # noqa: BLE001
                pass
        return row, probability_detail

    raw = _read_table(candidate.file_path)
    scoped = _filter_artifact_frame(raw, candidate)
    row["row_count"] = int(scoped.shape[0])
    row["has_forecast_origin_utc"] = "forecast_origin_utc" in scoped.columns
    row["has_delivery_start_utc"] = any(name in scoped.columns for name in ("delivery_start_utc", "period_timestamp", "target_timestamp_utc"))
    row["has_scenario_id"] = "scenario_id" in scoped.columns
    row["has_probability"] = any(name in scoped.columns for name in ("scenario_probability", "probability", "reduced_scenario_probability"))
    row["has_price"] = any(name in scoped.columns for name in ("scenario_price_eur_per_mwh", "scenario_price"))

    inferred_granularity = str(candidate.granularity or _infer_granularity_from_path(candidate.file_path) or "")
    if inferred_granularity == "quarter_hour":
        row["granularity"] = inferred_granularity
        row["validation_mode_recommendation"] = "out_of_scope_for_hourly_phase6a_target"
        row["notes"] = f"{candidate.notes} | quarter-hour artifact discovered but not validated further in hourly Phase 6a audit"
        return row, probability_detail

    try:
        normalized, used_reconstruction = _normalize_schema(
            scoped,
            fallback_model_id=candidate.raw_model_id or candidate.apparent_model,
            fallback_granularity=candidate.granularity,
            allow_forecast_origin_reconstruction=candidate.allow_forecast_origin_reconstruction,
        )
    except Exception as exc:  # noqa: BLE001
        row["validation_mode_recommendation"] = "schema_mapping_repair_required"
        row["notes"] = f"{candidate.notes} | normalization_error={type(exc).__name__}: {exc}"
        return row, probability_detail

    for optional_column in ("scenario_variant", "dataset_split", "candidate_label", "scenario_type"):
        if optional_column in scoped.columns and optional_column not in normalized.columns:
            normalized[optional_column] = scoped[optional_column].values

    row["granularity"] = _csv_value(candidate.granularity or str(normalized["granularity"].mode().iloc[0]))
    row["horizon_or_lead_day"] = _summarize_lead_day(normalized)
    row["forecast_origin_count"] = int(normalized["forecast_origin_utc"].nunique())
    scenario_counts = normalized.groupby("forecast_origin_utc")["scenario_id"].nunique()
    row["scenario_count_min"] = int(scenario_counts.min()) if not scenario_counts.empty else ""
    row["scenario_count_max"] = int(scenario_counts.max()) if not scenario_counts.empty else ""
    row["delivery_timestamp_min"] = _safe_to_iso(normalized["delivery_start_utc"].min())
    row["delivery_timestamp_max"] = _safe_to_iso(normalized["delivery_start_utc"].max())
    probability_detail, probability_diagnosis, probability_valid = _validate_probability_mass(normalized, candidate.artifact_id)
    row["validation_mode_recommendation"] = _classify_candidate(
        candidate,
        exists=True,
        normalized=normalized,
        used_reconstruction=used_reconstruction,
        probability_diagnosis=probability_diagnosis,
        probability_valid=probability_valid,
    )

    note_parts = [candidate.notes]
    if used_reconstruction:
        note_parts.append("forecast_origin_utc reconstructed from delivery timestamps")
    unique_delivery_hours = normalized.groupby("forecast_origin_utc")["delivery_start_utc"].nunique()
    if not unique_delivery_hours.empty:
        if unique_delivery_hours.min() == unique_delivery_hours.max():
            note_parts.append(f"delivery periods per origin={int(unique_delivery_hours.min())}")
        else:
            note_parts.append(
                f"delivery periods per origin min={int(unique_delivery_hours.min())} max={int(unique_delivery_hours.max())}"
            )
    if probability_valid is False:
        if probability_diagnosis == "schema/mapping issue" and "scenario_variant" in normalized.columns:
            variant_count = int(normalized["scenario_variant"].nunique())
            note_parts.append(f"file contains {variant_count} scenario_variant groups with separate probability mass")
        else:
            note_parts.append("probability mass does not sum to one on unique-scenario basis")
    row["notes"] = " | ".join(part for part in note_parts if part)
    return row, probability_detail


def run_audit(config_path: str | Path, output_dir: Path) -> tuple[Path, Path]:
    config = load_hydrogen_config(config_path)
    repo_root = config.repo_root
    catalog_candidates = _load_catalog_candidates(repo_root, config.models.scenario_catalog)
    registry_candidates = _load_registry_candidates(repo_root)
    known_paths = {candidate.file_path.resolve() for candidate in [*catalog_candidates, *registry_candidates]}
    direct_candidates = _discover_unregistered_files(repo_root, known_paths)

    all_candidates = catalog_candidates + registry_candidates + direct_candidates
    # Preserve one row per artifact id and path combination.
    unique_candidates: list[CandidateArtifact] = []
    seen: set[tuple[str, Path]] = set()
    for candidate in all_candidates:
        key = (candidate.artifact_id, candidate.file_path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)

    inventory_rows: list[dict[str, Any]] = []
    probability_rows: list[pd.DataFrame] = []
    for candidate in unique_candidates:
        inventory_row, probability_detail = _inventory_row(candidate, repo_root)
        inventory_rows.append(inventory_row)
        if not probability_detail.empty:
            probability_rows.append(probability_detail)

    inventory = pd.DataFrame(inventory_rows).sort_values(["exists", "granularity", "artifact_id"], ascending=[False, True, True])
    probability = pd.concat(probability_rows, ignore_index=True) if probability_rows else pd.DataFrame(
        columns=[
            "artifact_id",
            "forecast_origin_utc",
            "number_of_rows",
            "number_of_unique_scenarios",
            "raw_probability_sum_over_rows",
            "probability_sum_over_unique_scenarios",
            "min_probability",
            "max_probability",
            "has_negative_probability",
            "diagnosis",
        ]
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = output_dir / "scenario_artifact_inventory.csv"
    probability_path = output_dir / "probability_mass_by_origin.csv"
    inventory.to_csv(inventory_path, index=False)
    probability.to_csv(probability_path, index=False)
    return inventory_path, probability_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and validate scenario artifacts for hydrogen stochastic readiness.")
    parser.add_argument(
        "--config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml",
        help="Path to the hydrogen config YAML.",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/Data/03_Hydrogen_Test_Case/docs",
        help="Directory where scenario_artifact_inventory.csv and probability_mass_by_origin.csv will be written.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()

    inventory_path, probability_path = run_audit(args.config, output_dir)
    print(
        json.dumps(
            {
                "scenario_artifact_inventory": str(inventory_path),
                "probability_mass_by_origin": str(probability_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
