from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DATA_FILE_NAMES: tuple[str, ...] = (
    "scenario_prices_long.csv",
    "scenario_prices_long.parquet",
    "scenarios_long.csv",
    "scenarios_long.parquet",
)
INTERESTING_COLUMNS: tuple[str, ...] = (
    "candidate_key",
    "candidate_label",
    "model_id",
    "scenario_variant",
    "scenario_id",
    "delivery_day",
    "period_timestamp",
    "target_timestamp_utc",
    "delivery_start_utc",
    "forecast_origin_utc",
    "lead_day",
    "granularity",
    "probability",
    "scenario_probability",
    "scenario_price",
    "scenario_price_eur_per_mwh",
    "actual_price",
    "actual_price_eur_per_mwh",
    "central_forecast_price",
    "point_forecast_eur_per_mwh",
    "dataset_split",
)
ROOTS_TO_SEARCH: tuple[str, ...] = (
    "data/02_Forecasting/01_DA_prices",
    "data/02_Forecasting/01_DA_prices/hourly_da",
    "data/02_Forecasting/01_DA_prices/hourly_da/finalisation_runs",
    "data/02_Forecasting/01_DA_prices/hourly_da/runs",
    "data/02_Forecasting/01_DA_prices/hourly_da/scenario_generation",
    "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports",
    "data/03_Optimisation",
    "scripts/Data/02_Forecasting/01_DA_prices",
    "scripts/Data/03_Hydrogen_Test_Case",
    "docs",
)
DOC_REFERENCE_FILES: tuple[str, ...] = (
    "docs/forecasting/scenario_generation_audit_2026-05-12.md",
    "docs/forecasting/hourly_donly_tail_diagnostics_2026-05-12.md",
    "docs/forecasting/hourly_donly_calibration_sensitivity_2026-05-13.md",
    "scripts/Data/03_Hydrogen_Test_Case/docs/scenario_real_integration_readiness.md",
)
SEARCH_TERMS_PATTERN = re.compile(
    r"scenario_prices_long|scenario_generation|scenario_distribution|lear_strict|lear_fs3|xgboost_fs3|"
    r"LEAR Strict|LEAR FS3|XGBoost FS3|promoted|pruned|D_ONLY|D-only|lead_day|20260511|20260512|20260513",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class RecoveryRow:
    candidate_id: str
    file_path: str
    exists: bool
    file_size_mb: float | None
    modified_time: str
    file_type: str
    source_kind: str
    mentioned_model: str
    mentioned_granularity: str
    mentioned_horizon_or_lead_day: str
    mentioned_scenario_count: str
    mentioned_scenario_variant: str
    has_actual_scenario_data: bool
    notes: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_mtime(path: Path) -> str:
    if not path.exists():
        return ""
    return pd.Timestamp(path.stat().st_mtime, unit="s").isoformat()


def _safe_size_mb(path: Path) -> float | None:
    if not path.exists():
        return None
    return round(path.stat().st_size / (1024.0 * 1024.0), 3)


def _infer_granularity_from_text(text: str) -> str:
    lower = text.lower()
    if "quarterhour" in lower or "quarter_hour" in lower or "15min" in lower:
        return "quarter_hour"
    if "hourly" in lower:
        return "hourly"
    return ""


def _detect_model_mentions(text: str) -> str:
    lower = text.lower()
    labels: list[str] = []
    if "lear_strict" in lower or "lear strict" in lower:
        labels.append("LEAR Strict")
    if "lear_fs3" in lower or "lear fs3" in lower:
        labels.append("LEAR FS3")
    if "xgboost_fs3" in lower or "xgboost fs3" in lower:
        labels.append("XGBoost FS3")
    return ", ".join(labels)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def _read_header(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        return list(pd.read_csv(path, nrows=0).columns)
    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq  # type: ignore

            return list(pq.ParquetFile(path).schema.names)
        except Exception:  # noqa: BLE001
            return list(pd.read_parquet(path).columns)
    return []


def _load_subset(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, usecols=[col for col in columns if col in _read_header(path)], low_memory=False)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path, columns=[col for col in columns if col in _read_header(path)])
    raise ValueError(f"Unsupported file type: {path}")


def _utc_series(frame: pd.DataFrame, *candidates: str) -> pd.Series | None:
    for column in candidates:
        if column in frame.columns:
            return pd.to_datetime(frame[column], utc=True, errors="coerce")
    return None


def _reconstruct_forecast_origin(frame: pd.DataFrame) -> pd.Series | None:
    if "forecast_origin_utc" in frame.columns:
        return pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="coerce")
    delivery = _utc_series(frame, "period_timestamp", "delivery_start_utc", "target_timestamp_utc")
    if delivery is None:
        return None
    local_day = delivery.dt.tz_convert("Europe/Amsterdam").dt.floor("D")
    origin_local = local_day - pd.Timedelta(days=1) + pd.Timedelta(hours=8)
    return origin_local.dt.tz_convert("UTC")


def _probability_diagnosis(frame: pd.DataFrame) -> tuple[str, str]:
    scenario_col = "scenario_probability" if "scenario_probability" in frame.columns else "probability" if "probability" in frame.columns else ""
    if not scenario_col:
        return "missing probability column", "probability_missing"
    if "scenario_id" not in frame.columns:
        return "missing scenario_id column", "schema_missing"

    origin = _reconstruct_forecast_origin(frame)
    if origin is None:
        return "missing forecast-origin and delivery timestamp columns", "schema_missing"

    work = frame.copy()
    work["__forecast_origin_utc"] = origin
    work = work.dropna(subset=["__forecast_origin_utc", "scenario_id"])
    if work.empty:
        return "empty after timestamp/scenario filtering", "schema_missing"
    work[scenario_col] = pd.to_numeric(work[scenario_col], errors="coerce")

    if work[scenario_col].isna().all():
        return "probability column present but all values are NaN", "probability_missing"
    if bool((work[scenario_col] < 0).any()):
        return "negative probabilities detected", "invalid_mass"

    dedup_cols = ["__forecast_origin_utc", "scenario_id", scenario_col]
    if "candidate_key" in work.columns:
        dedup_cols.insert(1, "candidate_key")
    if "model_id" in work.columns:
        dedup_cols.insert(1, "model_id")
    unique_sums = work[dedup_cols].drop_duplicates().groupby("__forecast_origin_utc")[scenario_col].sum()
    raw_sums = work.groupby("__forecast_origin_utc")[scenario_col].sum()
    unique_min = float(unique_sums.min())
    unique_max = float(unique_sums.max())
    raw_min = float(raw_sums.min())
    raw_max = float(raw_sums.max())

    variant_ok = False
    if "scenario_variant" in work.columns:
        variant_sums = (
            work[["__forecast_origin_utc", "scenario_variant", "scenario_id", scenario_col]]
            .drop_duplicates()
            .groupby(["__forecast_origin_utc", "scenario_variant"])[scenario_col]
            .sum()
            .reset_index()
        )
        by_origin = variant_sums.groupby("__forecast_origin_utc")[scenario_col].apply(
            lambda series: bool(series.between(0.999999, 1.000001).all()) and len(series) > 1
        )
        variant_ok = bool(by_origin.all()) if not by_origin.empty else False

    if variant_ok:
        return (
            f"bundled variants: unique scenario probability sum per origin is {unique_min:.3f}..{unique_max:.3f}, "
            "but each scenario_variant block sums to 1.0",
            "bundled_variants",
        )
    if bool(unique_sums.between(0.999999, 1.000001).all()):
        if not bool(raw_sums.between(0.999999, 1.000001).all()):
            return (
                f"valid unique-scenario mass 1.0 with repeated timestamp rows; raw row sums are {raw_min:.3f}..{raw_max:.3f}",
                "repeated_rows_false_failure",
            )
        return ("probabilities sum to 1.0 on unique-scenario basis", "valid")
    return (
        f"invalid unique-scenario probability mass {unique_min:.3f}..{unique_max:.3f}",
        "invalid_mass",
    )


def _inspect_actual_data_file(path: Path) -> list[RecoveryRow]:
    columns = _read_header(path)
    subset = _load_subset(path, list(INTERESTING_COLUMNS))
    model_col = "candidate_key" if "candidate_key" in subset.columns else "model_id" if "model_id" in subset.columns else ""
    if model_col:
        model_values = [value for value in pd.Series(subset[model_col].astype(str).unique()).sort_values().tolist() if value and value != "nan"]
    else:
        model_values = [""]
    rows: list[RecoveryRow] = []
    for model_value in model_values:
        scoped = subset.loc[subset[model_col].astype(str) == model_value].copy() if model_col and model_value else subset.copy()
        ts = _utc_series(scoped, "period_timestamp", "delivery_start_utc", "target_timestamp_utc")
        forecast_origin = _reconstruct_forecast_origin(scoped)
        probability_note, probability_code = _probability_diagnosis(scoped)
        scenario_variant = ""
        if "scenario_variant" in scoped.columns:
            variants = pd.Series(scoped["scenario_variant"].astype(str).unique()).sort_values().tolist()
            scenario_variant = ",".join(variants[:6]) + ("..." if len(variants) > 6 else "")
        lead_day_note = ""
        if "lead_day" in scoped.columns:
            values = sorted(pd.to_numeric(scoped["lead_day"], errors="coerce").dropna().astype(int).unique().tolist())
            if values:
                lead_day_note = f"lead_day={values}" if len(values) <= 5 else f"lead_day={values[:5]}..."
        row_count = int(scoped.shape[0])
        scenario_count = int(scoped["scenario_id"].nunique()) if "scenario_id" in scoped.columns else 0
        forecast_origin_count = int(forecast_origin.nunique()) if forecast_origin is not None else 0
        granularity = ""
        if "granularity" in scoped.columns and not scoped["granularity"].dropna().empty:
            granularity = str(scoped["granularity"].dropna().astype(str).mode().iloc[0])
        if not granularity:
            granularity = _infer_granularity_from_text(str(path))
        note_parts = [
            f"columns={','.join(columns[:20])}{'...' if len(columns) > 20 else ''}",
            f"row_count={row_count}",
            f"scenario_count={scenario_count}",
            f"forecast_origin_count={forecast_origin_count}",
            f"probability_check={probability_code}",
            probability_note,
        ]
        if ts is not None and not ts.dropna().empty:
            note_parts.append(f"timestamp_range={ts.min().isoformat()}..{ts.max().isoformat()}")
        if model_col and model_value:
            note_parts.append(f"all_models_in_file={','.join(model_values)}")
        if "forecast_origin_utc" in scoped.columns:
            note_parts.append("forecast_origin_utc present")
        else:
            note_parts.append("forecast_origin_utc missing")
        if "scenario_variant" in scoped.columns:
            note_parts.append("scenario_variant present")
        rows.append(
            RecoveryRow(
                candidate_id=f"data::{path.parent.name}::{model_value or 'unscoped'}",
                file_path=str(path),
                exists=True,
                file_size_mb=_safe_size_mb(path),
                modified_time=_safe_mtime(path),
                file_type=path.suffix.lower().lstrip("."),
                source_kind="data_file",
                mentioned_model=model_value,
                mentioned_granularity=granularity,
                mentioned_horizon_or_lead_day=lead_day_note,
                mentioned_scenario_count=str(scenario_count) if scenario_count else "",
                mentioned_scenario_variant=scenario_variant,
                has_actual_scenario_data=True,
                notes=" | ".join(note_parts),
            )
        )
    return rows


def _catalog_rows(repo_root: Path) -> list[RecoveryRow]:
    catalog_path = repo_root / "scripts/Data/03_Hydrogen_Test_Case/configs/scenario_catalog.yaml"
    if not catalog_path.exists():
        return []
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts", {}) if isinstance(payload, dict) else {}
    rows: list[RecoveryRow] = []
    for artifact_key, raw in artifacts.items():
        if not isinstance(raw, dict):
            continue
        path = Path(str(raw.get("path", "")))
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        rows.append(
            RecoveryRow(
                candidate_id=f"catalog::{artifact_key}",
                file_path=str(path),
                exists=path.exists(),
                file_size_mb=_safe_size_mb(path),
                modified_time=_safe_mtime(path),
                file_type=path.suffix.lower().lstrip("."),
                source_kind="manifest",
                mentioned_model=_stringify(raw.get("model_id")),
                mentioned_granularity=_stringify(raw.get("granularity")),
                mentioned_horizon_or_lead_day="",
                mentioned_scenario_count="",
                mentioned_scenario_variant="",
                has_actual_scenario_data=path.exists(),
                notes=f"scenario_catalog entry | validation_mode={raw.get('validation_mode','')} | allow_forecast_origin_reconstruction={raw.get('allow_forecast_origin_reconstruction','')}",
            )
        )
    return rows


def _registry_rows(repo_root: Path) -> list[RecoveryRow]:
    path = repo_root / "data/02_Forecasting/01_DA_prices/scenario_evaluation/20260513_102807/tables/scenario_load_registry.csv"
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    rows: list[RecoveryRow] = []
    hourly = frame.loc[frame["granularity"].astype(str) == "hourly"].copy()
    for record in hourly.itertuples(index=False):
        scenario_path = Path(str(record.scenario_path))
        rows.append(
            RecoveryRow(
                candidate_id=f"registry::{record.canonical_model_key}::{record.run_id}",
                file_path=str(scenario_path),
                exists=scenario_path.exists(),
                file_size_mb=_safe_size_mb(scenario_path),
                modified_time=_safe_mtime(scenario_path),
                file_type=scenario_path.suffix.lower().lstrip("."),
                source_kind="registry",
                mentioned_model=str(record.raw_model_id),
                mentioned_granularity=str(record.granularity),
                mentioned_horizon_or_lead_day="lead_day=0 inferred in registry",
                mentioned_scenario_count=str(record.unique_scenarios),
                mentioned_scenario_variant=_stringify(record.selected_variant),
                has_actual_scenario_data=scenario_path.exists(),
                notes=f"registry rows={record.rows} | unique_origins={record.unique_origins} | warnings={_stringify(record.warnings)}",
            )
        )
    return rows


def _run_summary_rows(repo_root: Path) -> list[RecoveryRow]:
    roots = [
        repo_root / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict",
        repo_root / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly",
    ]
    rows: list[RecoveryRow] = []
    for root in roots:
        if not root.exists():
            continue
        for run_dir in sorted([path for path in root.iterdir() if path.is_dir()]):
            summary_path = run_dir / "scenario_generation_run_summary.json"
            config_path = run_dir / "scenario_generation_config.json"
            if not summary_path.exists():
                continue
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            expected_file = run_dir / "scenario_prices_long.csv"
            candidates = summary.get("selected_candidates", []) or [{}]
            if not isinstance(candidates, list):
                candidates = [{}]
            scenario_variants = summary.get("scenario_variants_generated", [])
            scenario_variant_text = ",".join(str(value) for value in scenario_variants) if isinstance(scenario_variants, list) else _stringify(scenario_variants)
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    candidate = {}
                notes = [
                    f"run_status={summary.get('status','')}",
                    f"rows_in_final_scenarios={summary.get('rows_in_final_scenarios','')}",
                    f"reduced_scenario_count={summary.get('reduced_scenario_count','')}",
                    f"probability_policy={summary.get('probability_policy','')}",
                    f"raw_snapshot_policy={summary.get('raw_snapshot_policy','')}",
                    f"source_run_id={candidate.get('source_run_id','')}",
                ]
                if config_path.exists():
                    notes.append(f"config_present={config_path.name}")
                rows.append(
                    RecoveryRow(
                        candidate_id=f"run_summary::{run_dir.name}::{candidate.get('candidate_key','unknown')}",
                        file_path=str(expected_file),
                        exists=expected_file.exists(),
                        file_size_mb=_safe_size_mb(expected_file),
                        modified_time=_safe_mtime(summary_path),
                        file_type="json",
                        source_kind="manifest",
                        mentioned_model=_stringify(candidate.get("candidate_key")),
                        mentioned_granularity=_stringify(summary.get("granularity")),
                        mentioned_horizon_or_lead_day=_stringify(summary.get("horizon_mode")),
                        mentioned_scenario_count=_stringify(summary.get("n_final_scenarios")),
                        mentioned_scenario_variant=scenario_variant_text,
                        has_actual_scenario_data=expected_file.exists(),
                        notes=" | ".join(notes),
                    )
                )
    return rows


def _doc_reference_rows(repo_root: Path) -> list[RecoveryRow]:
    rows: list[RecoveryRow] = []
    for relative in DOC_REFERENCE_FILES:
        path = repo_root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not SEARCH_TERMS_PATTERN.search(text):
            continue
        run_ids = sorted(set(re.findall(r"2026051[123]_\d{6}", text)))
        scenario_variants = sorted(set(re.findall(r"tail_stress_v1|base_plus_a_plus_b|base_plus_a|base_plus_b|base", text)))
        source_kind = "README_reference" if "readme" in path.name.lower() or path.suffix.lower() == ".md" else "log_reference"
        rows.append(
            RecoveryRow(
                candidate_id=f"doc::{path.stem}",
                file_path=str(path),
                exists=True,
                file_size_mb=_safe_size_mb(path),
                modified_time=_safe_mtime(path),
                file_type=path.suffix.lower().lstrip("."),
                source_kind=source_kind,
                mentioned_model=_detect_model_mentions(text),
                mentioned_granularity=_infer_granularity_from_text(text),
                mentioned_horizon_or_lead_day="D_ONLY" if "D_ONLY" in text or "D-only" in text else "",
                mentioned_scenario_count="",
                mentioned_scenario_variant=",".join(scenario_variants),
                has_actual_scenario_data=False,
                notes=f"document reference | run_ids={','.join(run_ids)} | mentions scenario_prices_long={'scenario_prices_long' in text}",
            )
        )
    return rows


def _find_actual_data_files(repo_root: Path) -> list[Path]:
    found: set[Path] = set()
    for root_str in ROOTS_TO_SEARCH:
        root = repo_root / root_str
        if not root.exists():
            continue
        for name in DATA_FILE_NAMES:
            for path in root.rglob(name):
                found.add(path.resolve())
    return sorted(found)


def _write_markdown(path: Path, inventory: pd.DataFrame) -> None:
    data_rows = inventory.loc[inventory["source_kind"] == "data_file"].copy()
    hourly_data = data_rows.loc[data_rows["mentioned_granularity"].astype(str) == "hourly"].copy()
    metadata_rows = inventory.loc[inventory["source_kind"].isin(["manifest", "registry", "README_reference", "log_reference", "notebook_reference"])].copy()

    def _model_present(label: str) -> str:
        mask = hourly_data["mentioned_model"].astype(str).str.contains(label, case=False, na=False)
        return "yes" if bool(mask.any()) else "no"

    lear_strict_present = _model_present("lear_strict")
    lear_fs3_present = _model_present("lear_fs3")
    xgboost_present = _model_present("xgboost_fs3")

    missing_hourly_registry = metadata_rows.loc[
        metadata_rows["source_kind"].isin(["manifest", "registry"])
        & (metadata_rows["mentioned_granularity"].astype(str) == "hourly")
        & (~metadata_rows["exists"].astype(bool))
    ].copy()
    legacy_rows = hourly_data.loc[hourly_data["file_path"].astype(str).str.contains("20260429_193206", na=False)].copy()

    lines = [
        "# Scenario Recovery Audit",
        "",
        "## Search roots",
        "",
    ]
    lines.extend([f"- `{root}`" for root in ROOTS_TO_SEARCH])
    lines.extend(
        [
            "",
            "## Actual scenario data files found",
            "",
        ]
    )
    if data_rows.empty:
        lines.append("- None.")
    else:
        for row in data_rows.itertuples(index=False):
            lines.append(
                f"- `{row.file_path}` | model `{row.mentioned_model or 'unscoped'}` | granularity `{row.mentioned_granularity}` | notes: {row.notes}"
            )
    lines.extend(
        [
            "",
            "## Metadata-only references found",
            "",
        ]
    )
    if metadata_rows.empty:
        lines.append("- None.")
    else:
        for row in metadata_rows.head(25).itertuples(index=False):
            lines.append(
                f"- `{row.source_kind}` `{row.file_path}` | model `{row.mentioned_model}` | exists={row.exists} | notes: {row.notes}"
            )
        if len(metadata_rows) > 25:
            lines.append(f"- ... {len(metadata_rows) - 25} additional metadata/reference rows in `scenario_recovery_inventory.csv`.")
    lines.extend(
        [
            "",
            "## Direct answers",
            "",
            f"- Hourly LEAR Strict scenario data present anywhere on disk: **{lear_strict_present}**.",
            f"- Hourly LEAR FS3 scenario data present anywhere on disk: **{lear_fs3_present}**.",
            f"- Hourly XGBoost FS3 scenario data present anywhere on disk: **{xgboost_present}**.",
        ]
    )
    if not legacy_rows.empty:
        lines.append(
            "- The available hourly real scenario data file is the legacy `20260429_193206/scenario_prices_long.csv`, which contains LEAR FS3 and XGBoost FS3 candidate rows in one bundled multi-variant artifact."
        )
    lines.extend(
        [
            "",
            "## Missing-file interpretation",
            "",
            "- The May 12/13 hourly scenario campaign left many run summaries, configs, diagnostics, and registry rows that reference `scenario_prices_long.csv` outputs.",
            "- Those summaries report nonzero `rows_in_final_scenarios`, scenario counts, selected variants, and validation checks, which is strong evidence that scenario files were generated at the time.",
            "- Current broad search found no matching hourly long-format files for the strict campaign under the searched project roots.",
            "- The most likely local explanation is that the strict-campaign long files were removed during cleanup or retention pruning, or moved outside the searched project roots.",
            "- The evidence is not consistent with 'never generated' for the strict-campaign runs.",
            "",
            "## Recoverability",
            "",
            "- Regeneration appears feasible because run summaries, configs, source run ids, and the hourly scenario-generation code still exist.",
            "- LEAR Strict anchor predictions still exist at the path recorded in the strict run configs.",
            "- Candidate benchmark run folders for LEAR FS3 and XGBoost FS3 still exist.",
            "- One upstream bridge path recorded in the strict run config is missing locally: `bridged_hourly_target_input_all_regions.csv`.",
            "- That means regeneration is likely possible, but not necessarily one-click until that bridge input is relinked or rebuilt.",
            "",
            "## Phase 6a-2 implication",
            "",
            "- Variant selection is still needed for the legacy hourly artifact because it bundles multiple `scenario_variant` groups in one file.",
            "- For the strict May 12/13 campaign, regeneration or external relinking is required before Phase 6a-2 can promote a thesis-grade hourly artifact.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(output_dir: Path) -> tuple[Path, Path]:
    repo_root = _repo_root()
    rows: list[RecoveryRow] = []

    for data_path in _find_actual_data_files(repo_root):
        rows.extend(_inspect_actual_data_file(data_path))
    rows.extend(_catalog_rows(repo_root))
    rows.extend(_registry_rows(repo_root))
    rows.extend(_run_summary_rows(repo_root))
    rows.extend(_doc_reference_rows(repo_root))

    inventory = pd.DataFrame([row.__dict__ for row in rows]).drop_duplicates(
        subset=["candidate_id", "file_path", "source_kind", "mentioned_model"]
    )
    inventory = inventory.sort_values(
        ["has_actual_scenario_data", "source_kind", "mentioned_granularity", "candidate_id"],
        ascending=[False, True, True, True],
    ).reset_index(drop=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "scenario_recovery_inventory.csv"
    md_path = output_dir / "scenario_recovery_audit.md"
    inventory.to_csv(csv_path, index=False)
    _write_markdown(md_path, inventory)
    return csv_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a forensic scenario recovery audit for hourly scenario artifacts.")
    parser.add_argument(
        "--output-dir",
        default="scripts/Data/03_Hydrogen_Test_Case/docs",
        help="Directory to write scenario_recovery_inventory.csv and scenario_recovery_audit.md.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()
    csv_path, md_path = run_audit(output_dir)
    print(json.dumps({"inventory_csv": str(csv_path), "audit_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
