from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ReportingLevelSpec:
    reporting_level: str
    reporting_level_label: str
    reporting_level_sort_order: int
    lead_days: tuple[int, ...]

    def to_columns(self) -> dict[str, object]:
        lead_days_text = ",".join(str(value) for value in self.lead_days)
        return {
            "reporting_level": self.reporting_level,
            "reporting_level_label": self.reporting_level_label,
            "reporting_level_sort_order": int(self.reporting_level_sort_order),
            "reporting_lead_days": lead_days_text,
            "reporting_lead_day_start": int(min(self.lead_days)),
            "reporting_lead_day_end": int(max(self.lead_days)),
            "reporting_lead_day_count": int(len(self.lead_days)),
        }


def reporting_level_specs() -> tuple[ReportingLevelSpec, ...]:
    return (
        ReportingLevelSpec(
            reporting_level="d_only",
            reporting_level_label="D only",
            reporting_level_sort_order=0,
            lead_days=(0,),
        ),
        ReportingLevelSpec(
            reporting_level="guidance_only",
            reporting_level_label="Guidance only",
            reporting_level_sort_order=1,
            lead_days=(1, 2, 3, 4),
        ),
        ReportingLevelSpec(
            reporting_level="stitched_all_horizon",
            reporting_level_label="Full-horizon",
            reporting_level_sort_order=2,
            lead_days=(0, 1, 2, 3, 4),
        ),
    )


def _run_label_from_run_dir_name(run_dir_name: str) -> str:
    parts = str(run_dir_name).split("_", 2)
    return parts[2] if len(parts) == 3 else str(run_dir_name)


def find_latest_run(output_root: Path, run_label: str) -> Path:
    run_root = output_root / "runs"
    if not run_root.exists():
        raise FileNotFoundError(f"No run directories found for label '{run_label}' in {run_root}.")
    candidates = sorted(
        candidate
        for candidate in run_root.iterdir()
        if candidate.is_dir() and _run_label_from_run_dir_name(candidate.name) == str(run_label)
    )
    if not candidates:
        raise FileNotFoundError(f"No run directories found for label '{run_label}' in {run_root}.")
    complete_candidates = [candidate for candidate in candidates if (candidate / "run_summary.json").exists()]
    if complete_candidates:
        return complete_candidates[-1]
    return candidates[-1]


def resolve_tabular_path(run_dir: Path, filename: str) -> Path:
    direct_path = run_dir / filename
    if direct_path.exists():
        return direct_path

    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem if suffix in {".csv", ".parquet"} else filename
    candidates = [
        run_dir / f"{stem}.csv",
        run_dir / f"{stem}.parquet",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing expected run artifact: {direct_path}")


def load_csv(run_dir: Path, filename: str) -> pd.DataFrame:
    path = resolve_tabular_path(run_dir, filename)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def load_json(run_dir: Path, filename: str) -> dict[str, object]:
    path = run_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing expected run artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_model_catalog(run_dir: Path) -> pd.DataFrame:
    suite_models_path = run_dir / "suite_models.json"
    if suite_models_path.exists():
        suite_models = load_json(run_dir, "suite_models.json")
        rows: list[dict[str, object]] = []
        for record in suite_models.get("models", []):
            model_name = record.get("model") or record.get("name")
            if not model_name:
                continue
            rows.append(
                {
                    "model": str(model_name),
                    "model_family": str(record.get("model_family") or record.get("family") or ""),
                    "fs_level": str(record.get("fs_level") or ""),
                }
            )
        if rows:
            return pd.DataFrame(rows).drop_duplicates(subset=["model"]).reset_index(drop=True)

    metrics_overall_path = run_dir / "metrics_overall.csv"
    if metrics_overall_path.exists():
        metrics_overall = pd.read_csv(metrics_overall_path)
        required_cols = [column for column in ["model", "model_family", "fs_level"] if column in metrics_overall.columns]
        if "model" in required_cols:
            return (
                metrics_overall[required_cols]
                .drop_duplicates(subset=["model"])
                .assign(
                    model_family=lambda frame: frame["model_family"] if "model_family" in frame.columns else "",
                    fs_level=lambda frame: frame["fs_level"] if "fs_level" in frame.columns else "",
                )
                .reset_index(drop=True)
            )

    return pd.DataFrame(columns=["model", "model_family", "fs_level"])


def source_run_record(run_dir: Path) -> dict[str, object]:
    suite_models = load_run_model_catalog(run_dir)
    run_summary_path = run_dir / "run_summary.json"
    run_summary = load_json(run_dir, "run_summary.json") if run_summary_path.exists() else {"run_id": run_dir.name}
    return {
        "run_id": str(run_summary["run_id"]),
        "run_dir": str(run_dir),
        "models": suite_models.to_dict(orient="records"),
    }
