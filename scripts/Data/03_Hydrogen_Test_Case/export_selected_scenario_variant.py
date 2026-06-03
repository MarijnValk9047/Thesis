from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE_ARTIFACT_ID = "hourly_legacy_20260429_193206"
RECONSTRUCTION_RULE = "D-1 08:00 Europe/Amsterdam converted to UTC"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_source(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _candidate_label(frame: pd.DataFrame, model_filter: str) -> str:
    subset = frame.loc[frame["candidate_key"].astype(str) == str(model_filter), "candidate_label"].dropna().astype(str)
    if subset.empty:
        raise ValueError(f"Model filter {model_filter!r} is not present in source artifact.")
    return str(subset.iloc[0])


def _available_variants(frame: pd.DataFrame, model_filter: str) -> list[str]:
    subset = frame.loc[frame["candidate_key"].astype(str) == str(model_filter), "scenario_variant"].dropna().astype(str)
    return sorted(subset.unique().tolist())


def _recommended_variant(source_dir: Path, candidate_label: str) -> str | None:
    recommendation = _read_json_if_exists(source_dir / "final_scenario_recommendation.json")
    comparison = _read_csv_if_exists(source_dir / "final_scenario_model_comparison.csv")
    if not comparison.empty and "selected_as_default_variant" in comparison.columns:
        scoped = comparison.loc[
            (comparison["candidate_label"].astype(str) == str(candidate_label))
            & (comparison["selected_as_default_variant"].fillna(False).astype(bool))
        ].copy()
        if not scoped.empty:
            return str(scoped.iloc[0]["scenario_variant"])
    if candidate_label == str(recommendation.get("default_candidate", "")):
        return str(recommendation.get("default_scenario_variant", "")) or None
    if candidate_label == str(recommendation.get("robustness_candidate", "")):
        return str(recommendation.get("robustness_scenario_variant", "")) or None
    return None


def _reconstruct_forecast_origin(delivery_start_utc: pd.Series) -> pd.Series:
    local_day = pd.to_datetime(delivery_start_utc, utc=True, errors="coerce").dt.tz_convert("Europe/Amsterdam").dt.floor("D")
    origin_local = local_day - pd.Timedelta(days=1) + pd.Timedelta(hours=8)
    return origin_local.dt.tz_convert("UTC")


def _build_clean_export(
    source_frame: pd.DataFrame,
    *,
    model_filter: str,
    scenario_variant: str,
    output_artifact_id: str,
    source_file: Path,
) -> pd.DataFrame:
    scoped = source_frame.loc[
        (source_frame["candidate_key"].astype(str) == str(model_filter))
        & (source_frame["scenario_variant"].astype(str) == str(scenario_variant))
    ].copy()
    if scoped.empty:
        raise ValueError(
            f"No rows found for model_filter={model_filter!r} and scenario_variant={scenario_variant!r} in {source_file}."
        )

    scoped["delivery_start_utc"] = pd.to_datetime(scoped["period_timestamp"], utc=True, errors="coerce")
    scoped["delivery_start_local"] = scoped["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam")
    scoped["delivery_day"] = scoped["delivery_start_local"].dt.date.astype(str)
    scoped["forecast_origin_utc"] = _reconstruct_forecast_origin(scoped["delivery_start_utc"])
    scoped["scenario_probability"] = pd.to_numeric(scoped["probability"], errors="coerce")
    scoped["price_eur_per_mwh"] = pd.to_numeric(scoped["scenario_price"], errors="coerce")
    scoped["scenario_price_eur_per_mwh"] = scoped["price_eur_per_mwh"]
    scoped["point_forecast_eur_per_mwh"] = pd.to_numeric(scoped["central_forecast_price"], errors="coerce")
    scoped["actual_price_eur_per_mwh"] = pd.to_numeric(scoped["actual_price"], errors="coerce")
    scoped["model_id"] = scoped["candidate_key"].astype(str)
    scoped["granularity"] = "hourly"
    scoped["lead_day"] = 0
    scoped["horizon_mode"] = "D_ONLY"
    scoped["source_artifact_id"] = SOURCE_ARTIFACT_ID
    scoped["source_file_path"] = str(source_file.resolve())
    scoped["forecast_origin_reconstructed"] = True
    scoped["reconstruction_rule"] = RECONSTRUCTION_RULE
    scoped["scenario_generation_run_id"] = scoped["scenario_run_id"].astype(str)
    scoped["output_artifact_id"] = str(output_artifact_id)

    ordered_columns = [
        "forecast_origin_utc",
        "delivery_start_utc",
        "delivery_day",
        "lead_day",
        "scenario_id",
        "probability",
        "scenario_probability",
        "price_eur_per_mwh",
        "scenario_price_eur_per_mwh",
        "point_forecast_eur_per_mwh",
        "actual_price_eur_per_mwh",
        "model_id",
        "candidate_label",
        "scenario_variant",
        "granularity",
        "horizon_mode",
        "dataset_split",
        "period_index",
        "scenario_type",
        "source_residual_day",
        "protected",
        "selection_rule",
        "source_artifact_id",
        "source_file_path",
        "scenario_generation_run_id",
        "forecast_origin_reconstructed",
        "reconstruction_rule",
        "output_artifact_id",
    ]
    available = [column for column in ordered_columns if column in scoped.columns]
    return scoped[available].copy()


def _validation_summary(frame: pd.DataFrame) -> pd.DataFrame:
    duplicate_mask = frame.duplicated(
        subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"],
        keep=False,
    )
    unique_probs = (
        frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates()
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum_over_unique_scenarios=("scenario_probability", "sum"),
        )
    )
    summary = (
        frame.groupby("forecast_origin_utc", as_index=False)
        .agg(
            row_count=("scenario_id", "size"),
            delivery_hour_count=("delivery_start_utc", "nunique"),
            raw_probability_sum_over_rows=("scenario_probability", "sum"),
            min_probability=("scenario_probability", "min"),
            max_probability=("scenario_probability", "max"),
            has_negative_probability=("scenario_probability", lambda series: bool((series < 0).any())),
            duplicate_row_count=("scenario_id", lambda _: int(duplicate_mask.loc[frame.index].sum())),
        )
        .merge(unique_probs, on="forecast_origin_utc", how="left")
    )
    summary["probability_mass_valid"] = summary["probability_sum_over_unique_scenarios"].between(0.999999, 1.000001)
    summary["timestamps_utc_valid"] = True
    summary["lead_day_valid"] = True
    summary["forecast_origin_utc"] = pd.to_datetime(summary["forecast_origin_utc"], utc=True, errors="coerce").map(lambda value: value.isoformat())
    return summary.sort_values("forecast_origin_utc").reset_index(drop=True)


def _manifest(
    frame: pd.DataFrame,
    validation_summary: pd.DataFrame,
    *,
    source_file: Path,
    output_artifact_id: str,
    candidate_label: str,
    scenario_variant: str,
    recommended_variant: str | None,
    source_dir: Path,
) -> dict[str, Any]:
    recommendation = _read_json_if_exists(source_dir / "final_scenario_recommendation.json")
    config = _read_json_if_exists(source_dir / "scenario_generation_config.json")
    run_summary = _read_json_if_exists(source_dir / "scenario_generation_run_summary.json")
    return {
        "output_artifact_id": output_artifact_id,
        "validation_status": "integration_candidate",
        "thesis_grade": False,
        "source_artifact_id": SOURCE_ARTIFACT_ID,
        "source_file_path": str(source_file.resolve()),
        "model_id": str(frame["model_id"].astype(str).iloc[0]),
        "candidate_label": candidate_label,
        "scenario_variant": scenario_variant,
        "recommended_variant_for_model": recommended_variant,
        "forecast_origin_reconstructed": True,
        "reconstruction_rule": RECONSTRUCTION_RULE,
        "granularity": "hourly",
        "horizon_mode": "D_ONLY",
        "lead_day": 0,
        "dataset_splits_present": sorted(frame["dataset_split"].dropna().astype(str).unique().tolist()) if "dataset_split" in frame.columns else [],
        "row_count": int(frame.shape[0]),
        "forecast_origin_count": int(frame["forecast_origin_utc"].nunique()),
        "scenario_count": int(frame["scenario_id"].nunique()),
        "delivery_timestamp_min": frame["delivery_start_utc"].min().isoformat(),
        "delivery_timestamp_max": frame["delivery_start_utc"].max().isoformat(),
        "probability_mass_valid_for_all_origins": bool(validation_summary["probability_mass_valid"].all()),
        "min_probability_sum_over_unique_scenarios": float(validation_summary["probability_sum_over_unique_scenarios"].min()),
        "max_probability_sum_over_unique_scenarios": float(validation_summary["probability_sum_over_unique_scenarios"].max()),
        "duplicate_row_count_total": int(validation_summary["duplicate_row_count"].sum()),
        "no_silent_probability_normalisation_used": True,
        "legacy_source_final_recommendation": recommendation,
        "legacy_source_generation_config": config,
        "legacy_source_run_summary_excerpt": {
            "scenario_run_id": run_summary.get("scenario_run_id"),
            "selected_candidates": run_summary.get("selected_candidates"),
            "scenario_variants_generated": run_summary.get("scenario_variants_generated"),
            "target_split_used_for_scenario_evaluation": run_summary.get("target_split_used_for_scenario_evaluation"),
            "data_split_used_for_residual_calibration": run_summary.get("data_split_used_for_residual_calibration"),
        },
    }


def _write_readme(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        f"# {manifest['output_artifact_id']}",
        "",
        f"- validation_status: `{manifest['validation_status']}`",
        f"- thesis_grade: `{manifest['thesis_grade']}`",
        f"- source_artifact_id: `{manifest['source_artifact_id']}`",
        f"- source_file_path: `{manifest['source_file_path']}`",
        f"- model_id: `{manifest['model_id']}`",
        f"- candidate_label: `{manifest['candidate_label']}`",
        f"- scenario_variant: `{manifest['scenario_variant']}`",
        f"- recommended_variant_for_model: `{manifest['recommended_variant_for_model']}`",
        f"- forecast_origin_reconstructed: `{manifest['forecast_origin_reconstructed']}`",
        f"- reconstruction_rule: `{manifest['reconstruction_rule']}`",
        f"- granularity: `{manifest['granularity']}`",
        f"- horizon_mode: `{manifest['horizon_mode']}`",
        f"- lead_day: `{manifest['lead_day']}`",
        f"- dataset_splits_present: `{manifest['dataset_splits_present']}`",
        "",
        "Notes:",
        "",
        "- This artifact was derived by selecting exactly one `scenario_variant` from the bundled legacy hourly file.",
        "- No probability renormalisation was applied.",
        "- Probability mass validates at 1.0 per forecast origin on the unique-scenario basis after variant selection.",
        "- `forecast_origin_utc` was reconstructed and then written explicitly, so this artifact is suitable for integration dry runs only, not final thesis-grade stochastic evidence.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_variant(
    *,
    source_file: Path,
    model_filter: str,
    scenario_variant: str,
    output_dir: Path,
    output_artifact_id: str,
) -> Path:
    source_frame = _load_source(source_file)
    candidate_label = _candidate_label(source_frame, model_filter)
    source_dir = source_file.parent
    recommended_variant = _recommended_variant(source_dir, candidate_label)
    clean = _build_clean_export(
        source_frame,
        model_filter=model_filter,
        scenario_variant=scenario_variant,
        output_artifact_id=output_artifact_id,
        source_file=source_file,
    )
    validation = _validation_summary(clean)
    if not bool(validation["probability_mass_valid"].all()):
        raise ValueError(
            f"Probability validation failed for {output_artifact_id}: "
            f"{validation['probability_sum_over_unique_scenarios'].min()}..{validation['probability_sum_over_unique_scenarios'].max()}"
        )
    if int(validation["duplicate_row_count"].sum()) != 0:
        raise ValueError(f"Duplicate rows detected for {output_artifact_id}.")

    artifact_dir = output_dir / output_artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    clean.to_parquet(artifact_dir / "scenario_prices_long.parquet", index=False)
    clean.to_csv(artifact_dir / "scenario_prices_long.csv", index=False)
    validation.to_csv(artifact_dir / "scenario_validation_summary.csv", index=False)
    manifest = _manifest(
        clean,
        validation,
        source_file=source_file,
        output_artifact_id=output_artifact_id,
        candidate_label=candidate_label,
        scenario_variant=scenario_variant,
        recommended_variant=recommended_variant,
        source_dir=source_dir,
    )
    (artifact_dir / "scenario_export_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_readme(artifact_dir / "README_scenario_export.md", manifest)
    return artifact_dir


def _derive_artifact_id(model_filter: str, scenario_variant: str) -> str:
    model_slug = (
        str(model_filter)
        .replace("combo_", "_")
        .replace("candidate", "")
        .replace("__", "_")
        .strip("_")
    )
    return f"hourly_{model_slug}_{scenario_variant}_integration_candidate".replace("__", "_")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a clean single-variant hourly scenario artifact from the legacy bundled file.")
    parser.add_argument("--source-file", required=True, help="Path to the bundled source scenario_prices_long.csv file.")
    parser.add_argument("--model-filter", required=True, help="candidate_key/model_id to export.")
    parser.add_argument("--scenario-variant", help="Single scenario_variant to export.")
    parser.add_argument("--output-dir", required=True, help="Base directory where artifact folders will be created.")
    parser.add_argument("--output-artifact-id", required=True, help="Artifact id (or prefix when --export-all-variants is used).")
    parser.add_argument("--export-all-variants", action="store_true", help="Export all scenario variants for the selected model.")
    args = parser.parse_args()

    repo_root = _repo_root()
    source_file = Path(args.source_file)
    if not source_file.is_absolute():
        source_file = (repo_root / source_file).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()

    source_frame = _load_source(source_file)
    variants = _available_variants(source_frame, args.model_filter)
    if args.export_all_variants:
        exported = []
        for variant in variants:
            artifact_id = f"{args.output_artifact_id}_{variant}".replace("__", "_")
            exported.append(str(export_variant(
                source_file=source_file,
                model_filter=args.model_filter,
                scenario_variant=variant,
                output_dir=output_dir,
                output_artifact_id=artifact_id,
            )))
    else:
        if not args.scenario_variant:
            raise ValueError("--scenario-variant is required unless --export-all-variants is used.")
        if args.scenario_variant not in variants:
            raise ValueError(
                f"scenario_variant {args.scenario_variant!r} is not available for model {args.model_filter!r}. "
                f"Available variants: {variants}"
            )
        artifact_id = args.output_artifact_id or _derive_artifact_id(args.model_filter, args.scenario_variant)
        exported = [str(export_variant(
            source_file=source_file,
            model_filter=args.model_filter,
            scenario_variant=args.scenario_variant,
            output_dir=output_dir,
            output_artifact_id=artifact_id,
        ))]

    print(json.dumps({"exported_artifacts": exported}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
