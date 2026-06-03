from __future__ import annotations

import csv
import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "workspace_triage"

COMMIT_EXTENSIONS = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
}

CONFIG_JSON_HINTS = {"config", "manifest", "schema", "settings", "metadata"}
DOC_TOP_LEVELS = {"docs"}
NOTEBOOK_FINAL_HINTS = {"final", "conclusion", "summary", "report", "thesis"}
RUN_OUTPUT_DIR_MARKERS = {
    "runs",
    "run",
    "day_runs",
    "repair_runs",
    "frozen_results",
    "exports",
    "scenario_evaluation",
    "candidate_comparison_new_metrics",
    "qh_anchor_exports",
    "finalisation_runs",
    "canonical_actual_runs",
    "analysis",
}
DO_NOT_STAGE_DIR_MARKERS = {
    "data",
    "runs",
    "run",
    "frozen_results",
    "repair_runs",
    "exports",
    "scenario_evaluation",
    "candidate_comparison_new_metrics",
    "qh_anchor_exports",
    "tmp",
    "temp",
    "__pycache__",
    ".ipynb_checkpoints",
}
TEMP_NAME_MARKERS = {
    "__pycache__",
    ".ipynb_checkpoints",
    ".pytest_cache",
    ".mypy_cache",
    "tmp",
    "temp",
    "scratch",
    "debug",
}
SECRET_MARKERS = {
    "license",
    "licence",
    "secret",
    "token",
    "apikey",
    "api_key",
    "private_key",
    "password",
    "credential",
    "gurobi.lic",
    ".env",
}
REVIEW_NAME_MARKERS = {"copy", "kopie", "draft", "backup", "old"}
SMALL_JSON_COMMIT_MB = 0.25
LARGE_TEXT_MB = 1.0
LARGE_DATA_MB = 5.0


@dataclass
class FileRecord:
    path: str
    git_status_category: str
    tracked_state: str
    status_xy: str
    extension: str
    top_level_folder: str
    size_mb: float
    exists: bool
    is_dir: bool
    likely_role_category: str
    recommendation: str
    recommendation_reason: str
    inserted_lines: int | None = None
    deleted_lines: int | None = None


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def parse_status_short(output: str) -> dict[str, str]:
    status_map: dict[str, str] = {}
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith("?? "):
            path = raw_line[3:]
            status_map[path] = "??"
            continue
        if len(raw_line) < 4:
            continue
        status = raw_line[:2]
        path = raw_line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        status_map[path] = status
    return status_map


def parse_name_status(output: str) -> dict[str, str]:
    name_status: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0]
        path = parts[-1]
        name_status[path] = code
    return name_status


def parse_numstat(output: str) -> dict[str, tuple[int | None, int | None]]:
    numstat: dict[str, tuple[int | None, int | None]] = {}
    for line in output.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        added, deleted, path = line.split("\t", 2)
        add_val = None if added == "-" else int(added)
        del_val = None if deleted == "-" else int(deleted)
        numstat[path] = (add_val, del_val)
    return numstat


def normalized_parts(path: str) -> list[str]:
    return [part.lower() for part in Path(path).parts]


def top_level_folder(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if parts else "."


def file_size_mb(path: Path) -> float:
    if not path.exists() or not path.is_file():
        return 0.0
    return round(path.stat().st_size / (1024 * 1024), 4)


def classify_role(path: str, extension: str, exists: bool, is_dir: bool, size_mb: float) -> str:
    path_lower = path.lower()
    name_lower = Path(path).name.lower()
    parts = normalized_parts(path)
    top = top_level_folder(path).lower()

    if any(marker in path_lower for marker in SECRET_MARKERS):
        return "secret_risk"
    if name_lower == "--config":
        return "cache_temp"
    if any(part in TEMP_NAME_MARKERS for part in parts):
        return "cache_temp"
    if is_dir or path.endswith(("/", "\\")):
        return "review_required"
    if extension == ".ipynb":
        return "notebook"
    if any(part in RUN_OUTPUT_DIR_MARKERS for part in parts):
        if extension in {".md", ".txt"} and "readme" in name_lower:
            return "diagnostic_report"
        return "run_output"
    if top == "data":
        return "generated_data"
    if extension in {".csv", ".parquet", ".xlsx", ".xls"}:
        return "generated_data"
    if extension in {".zip", ".7z", ".tar", ".gz"}:
        return "generated_data"
    if extension in {".png", ".jpg", ".jpeg", ".svg", ".pdf"}:
        return "diagnostic_report"
    if "test" in path_lower or top == "tests":
        return "tests"
    if extension in {".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        return "config"
    if extension == ".json":
        if any(hint in name_lower for hint in CONFIG_JSON_HINTS) and size_mb <= SMALL_JSON_COMMIT_MB:
            return "config"
        if top == "docs":
            return "diagnostic_report"
        return "diagnostic_report" if size_mb <= LARGE_TEXT_MB else "generated_data"
    if top in DOC_TOP_LEVELS or extension in {".md", ".txt"}:
        return "docs"
    if extension in {".py", ".sh", ".ps1", ".bat"}:
        return "source_code"
    if not exists:
        return "review_required"
    return "review_required"


def recommend(record: FileRecord) -> tuple[str, str]:
    path_lower = record.path.lower()
    name_lower = Path(record.path).name.lower()
    parts = normalized_parts(record.path)

    if record.likely_role_category == "secret_risk":
        return "do_not_stage", "secret_risk"
    if record.is_dir or record.path.endswith(("/", "\\")):
        return "review_required", "directory_entry_review"
    if name_lower == "--config" or any(part in TEMP_NAME_MARKERS for part in parts):
        return "delete_later", "temp_or_accidental_file"
    if record.tracked_state == "deleted":
        return "review_required", "tracked_deletion_review"
    if record.tracked_state == "tracked" and record.top_level_folder.lower() == "data":
        return "review_required", "tracked_data_modified_review"
    if record.likely_role_category in {"generated_data", "run_output", "diagnostic_report"}:
        return "do_not_stage", "generated_or_run_output"
    if record.likely_role_category == "notebook":
        if any(hint in path_lower for hint in NOTEBOOK_FINAL_HINTS):
            return "review_required", "notebook_review_final_named"
        return "review_required", "notebook_review_default"
    if record.extension == ".json" and record.likely_role_category != "config":
        return "do_not_stage", "json_output_default"
    if any(marker in parts for marker in DO_NOT_STAGE_DIR_MARKERS):
        if record.likely_role_category in {"source_code", "config", "docs", "tests"} and record.top_level_folder.lower() != "data":
            return "review_required", "mixed_signal_path_review"
        return "do_not_stage", "folder_policy_do_not_stage"
    if record.extension in COMMIT_EXTENSIONS or record.likely_role_category in {"source_code", "config", "docs", "tests"}:
        return "stage_candidate", "source_or_doc_candidate"
    return "review_required", "conservative_default_review"


def build_record(
    path: str,
    status_xy: str,
    tracked_state: str,
    git_status_category: str,
    numstat: dict[str, tuple[int | None, int | None]],
) -> FileRecord:
    abs_path = REPO_ROOT / path
    exists = abs_path.exists()
    is_dir = abs_path.is_dir()
    extension = abs_path.suffix.lower() if exists else Path(path).suffix.lower()
    size_mb = file_size_mb(abs_path)
    role = classify_role(path, extension, exists, is_dir, size_mb)
    inserted, deleted = numstat.get(path, (None, None))
    record = FileRecord(
        path=path,
        git_status_category=git_status_category,
        tracked_state=tracked_state,
        status_xy=status_xy,
        extension=extension,
        top_level_folder=top_level_folder(path),
        size_mb=size_mb,
        exists=exists,
        is_dir=is_dir,
        likely_role_category=role,
        recommendation="",
        recommendation_reason="",
        inserted_lines=inserted,
        deleted_lines=deleted,
    )
    recommendation, reason = recommend(record)
    record.recommendation = recommendation
    record.recommendation_reason = reason
    return record


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def infer_ignore_patterns(records: list[FileRecord]) -> list[dict[str, object]]:
    patterns: list[dict[str, object]] = []
    counts_by_pattern: defaultdict[str, int] = defaultdict(int)

    for record in records:
        path_lower = record.path.lower()
        parts = normalized_parts(record.path)

        if record.likely_role_category == "run_output":
            for marker in RUN_OUTPUT_DIR_MARKERS:
                if marker in parts:
                    counts_by_pattern[f"**/{marker}/"] += 1
                    break
        if record.likely_role_category == "cache_temp":
            if "__pycache__" in parts:
                counts_by_pattern["**/__pycache__/"] += 1
            if ".ipynb_checkpoints" in parts:
                counts_by_pattern["**/.ipynb_checkpoints/"] += 1
        if Path(record.path).name == "--config":
            counts_by_pattern["--config"] += 1
        if path_lower.endswith(".log"):
            counts_by_pattern["*.log"] += 1

    for pattern, count in sorted(counts_by_pattern.items(), key=lambda item: (-item[1], item[0])):
        patterns.append(
            {
                "pattern": pattern,
                "matched_files": count,
                "reason": "candidate ignore pattern inferred from untracked/generated clutter",
            }
        )
    return patterns


def row_dict(record: FileRecord) -> dict[str, object]:
    return {
        "path": record.path,
        "git_status_category": record.git_status_category,
        "tracked_state": record.tracked_state,
        "status_xy": record.status_xy,
        "extension": record.extension,
        "top_level_folder": record.top_level_folder,
        "size_mb": record.size_mb,
        "exists": record.exists,
        "is_dir": record.is_dir,
        "likely_role_category": record.likely_role_category,
        "recommendation": record.recommendation,
        "recommendation_reason": record.recommendation_reason,
        "inserted_lines": record.inserted_lines,
        "deleted_lines": record.deleted_lines,
    }


def write_summary(output_dir: Path, records: list[FileRecord], ignore_patterns: list[dict[str, object]]) -> None:
    recommendation_counts = Counter(record.recommendation for record in records)
    role_counts = Counter(record.likely_role_category for record in records)

    risk_records = [
        record
        for record in records
        if record.recommendation_reason in {
            "secret_risk",
            "tracked_deletion_review",
            "tracked_data_modified_review",
            "temp_or_accidental_file",
        }
    ]
    safe_stage = [
        record
        for record in records
        if record.recommendation == "stage_candidate"
    ][:20]
    do_not_stage_groups = Counter(
        f"{record.top_level_folder}/{record.likely_role_category}"
        for record in records
        if record.recommendation == "do_not_stage"
    )

    lines: list[str] = []
    lines.append("# Workspace Triage Summary")
    lines.append("")
    lines.append(f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`")
    lines.append(f"- Repository: `{REPO_ROOT}`")
    lines.append(f"- Total changed paths classified: `{len(records)}`")
    lines.append("")
    lines.append("## Counts by Recommendation")
    lines.append("")
    for key, value in sorted(recommendation_counts.items()):
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Counts by Role")
    lines.append("")
    for key, value in sorted(role_counts.items()):
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Top Risky Files")
    lines.append("")
    if risk_records:
        for record in risk_records[:20]:
            lines.append(
                f"- `{record.path}` [{record.tracked_state}; {record.likely_role_category}; {record.recommendation_reason}]"
            )
    else:
        lines.append("- None flagged beyond normal review categories.")
    lines.append("")
    lines.append("## Likely Safe Commit Candidates")
    lines.append("")
    if safe_stage:
        for record in safe_stage:
            lines.append(f"- `{record.path}` [{record.likely_role_category}]")
    else:
        lines.append("- None auto-promoted; use `review_required.csv` first.")
    lines.append("")
    lines.append("## Likely Do-Not-Stage Groups")
    lines.append("")
    if do_not_stage_groups:
        for key, value in do_not_stage_groups.most_common(15):
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("## Suggested Ignore Patterns")
    lines.append("")
    if ignore_patterns:
        for row in ignore_patterns[:15]:
            lines.append(f"- `{row['pattern']}` ({row['matched_files']} matches)")
    else:
        lines.append("- No clear ignore pattern candidates inferred.")
    lines.append("")
    lines.append("## Suggested Next Commands")
    lines.append("")
    lines.append("- `python scripts/dev/git_workspace_triage.py`")
    lines.append("- `git diff --name-only --diff-filter=M`")
    lines.append("- `git diff --name-only --diff-filter=D`")
    lines.append("- `git add -p <small source/doc files only>`")
    lines.append("- Manual review only before any restore/clean operation.")
    lines.append("")
    lines.append("## Warnings")
    lines.append("")
    lines.append("- Tracked modified files under `data/` are marked `tracked_data_modified_review` and were not restored.")
    lines.append("- Tracked deleted scripts are marked `tracked_deletion_review` and were not assumed correct.")
    lines.append("- Notebook changes are review-only by default.")
    lines.append("- Potential secrets or licence-like files are do-not-stage by default.")

    (output_dir / "cleanup_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)

    status_short = run_git(["status", "--short"])
    diff_name_status = run_git(["diff", "--name-status"])
    diff_numstat = run_git(["diff", "--numstat"])
    tracked_files_raw = run_git(["ls-files"])
    untracked_raw = run_git(["ls-files", "--others", "--exclude-standard"])

    status_map = parse_status_short(status_short)
    name_status = parse_name_status(diff_name_status)
    numstat = parse_numstat(diff_numstat)
    tracked_files = {line for line in tracked_files_raw.splitlines() if line.strip()}
    untracked_files = {line for line in untracked_raw.splitlines() if line.strip()}

    all_changed_paths = set(status_map) | set(name_status) | untracked_files
    records: list[FileRecord] = []

    for path in sorted(all_changed_paths):
        status_xy = status_map.get(path, "")
        if path in untracked_files or status_xy == "??":
            tracked_state = "untracked"
            git_status_category = "untracked"
        elif path in tracked_files and name_status.get(path, "").startswith("D"):
            tracked_state = "deleted"
            git_status_category = "deleted"
        elif path in tracked_files:
            tracked_state = "tracked"
            git_status_category = "modified"
        else:
            tracked_state = "review_required"
            git_status_category = "unknown"
        records.append(build_record(path, status_xy, tracked_state, git_status_category, numstat))

    tracked_modified = [record for record in records if record.tracked_state == "tracked"]
    untracked = [record for record in records if record.tracked_state == "untracked"]
    deleted_tracked = [record for record in records if record.tracked_state == "deleted"]
    recommended_stage = [record for record in records if record.recommendation == "stage_candidate"]
    recommended_do_not_stage = [
        record for record in records if record.recommendation in {"do_not_stage", "delete_later"}
    ]
    review_required = [record for record in records if record.recommendation == "review_required"]
    ignore_patterns = infer_ignore_patterns(records)

    fieldnames = [
        "path",
        "git_status_category",
        "tracked_state",
        "status_xy",
        "extension",
        "top_level_folder",
        "size_mb",
        "exists",
        "is_dir",
        "likely_role_category",
        "recommendation",
        "recommendation_reason",
        "inserted_lines",
        "deleted_lines",
    ]

    write_csv(output_dir / "tracked_modified.csv", (row_dict(r) for r in tracked_modified), fieldnames)
    write_csv(output_dir / "untracked_files.csv", (row_dict(r) for r in untracked), fieldnames)
    write_csv(output_dir / "deleted_tracked_files.csv", (row_dict(r) for r in deleted_tracked), fieldnames)
    write_csv(output_dir / "recommended_stage.csv", (row_dict(r) for r in recommended_stage), fieldnames)
    write_csv(
        output_dir / "recommended_do_not_stage.csv",
        (row_dict(r) for r in recommended_do_not_stage),
        fieldnames,
    )
    write_csv(
        output_dir / "review_required.csv",
        (row_dict(r) for r in review_required),
        fieldnames,
    )
    write_csv(
        output_dir / "recommended_ignore_patterns.csv",
        ignore_patterns,
        ["pattern", "matched_files", "reason"],
    )
    write_summary(output_dir, records, ignore_patterns)

    print(f"output_dir={output_dir}")
    print(f"total_records={len(records)}")
    print(f"tracked_modified={len(tracked_modified)}")
    print(f"untracked={len(untracked)}")
    print(f"deleted_tracked={len(deleted_tracked)}")
    print(f"recommended_stage={len(recommended_stage)}")
    print(f"recommended_do_not_stage={len(recommended_do_not_stage)}")
    print(f"review_required={len(review_required)}")


if __name__ == "__main__":
    main()
