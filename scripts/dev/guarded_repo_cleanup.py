from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE6_ROOT = REPO_ROOT / "workspace_triage" / "20260529_214237" / "phase6_guarded_cleanup_setup"
RUNS_ROOT = PHASE6_ROOT / "runs"
DEFAULT_PROTECTED_PATHS = PHASE6_ROOT / "protected_paths.txt"

MODES = {
    "snapshot",
    "plan",
    "dry-run-restore",
    "dry-run-delete",
    "dry-run-archive",
    "execute-restore",
    "execute-delete",
    "execute-archive",
}


@dataclass
class ActionItem:
    action: str
    status: str
    path: str
    detail: str


class CleanupError(RuntimeError):
    pass


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_git(*args: str, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=capture,
        check=check,
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def rel_repo_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def normalize_manifest_path(raw: str) -> Path:
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate.resolve()


def read_manifest(manifest_path: Path) -> list[Path]:
    if not manifest_path.exists():
        raise CleanupError(f"Manifest not found: {manifest_path}")
    paths: list[Path] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        paths.append(normalize_manifest_path(stripped))
    return paths


def read_protected_paths(protected_manifest: Path) -> list[Path]:
    return read_manifest(protected_manifest)


def is_within(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def is_protected(path: Path, protected_paths: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for protected in protected_paths:
        target = protected.resolve()
        if resolved == target or is_within(target, resolved):
            return True
    return False


def require_no_staged_changes() -> None:
    result = run_git("diff", "--cached", "--name-only")
    if result.stdout.strip():
        raise CleanupError("Refusing to operate because staged files are present.")


def tracked_paths() -> set[str]:
    result = run_git("ls-files")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def untracked_paths() -> set[str]:
    result = run_git("ls-files", "--others", "--exclude-standard")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def has_tracked_descendants(path: Path, tracked: set[str]) -> bool:
    rel = rel_repo_path(path)
    prefix = f"{rel}/"
    return any(item == rel or item.startswith(prefix) for item in tracked)


def ensure_repo_member(path: Path) -> None:
    if not is_within(REPO_ROOT.resolve(), path.resolve()):
        raise CleanupError(f"Path is outside the repository root: {path}")


def build_report_dir(mode: str) -> Path:
    return ensure_dir(RUNS_ROOT / f"{now_stamp()}_{mode}")


def write_action_plan(report_dir: Path, items: list[ActionItem]) -> None:
    out = report_dir / "action_plan.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["action", "status", "path", "detail"])
        for item in items:
            writer.writerow([item.action, item.status, item.path, item.detail])


def write_lines(path: Path, lines: Iterable[str]) -> None:
    text = "".join(f"{line}\n" for line in lines)
    write_text(path, text)


def git_output(*args: str) -> str:
    return run_git(*args).stdout


def create_snapshot_outputs(report_dir: Path) -> None:
    write_text(report_dir / "git_status_short.txt", git_output("status", "--short"))
    write_text(report_dir / "git_diff_stat.txt", git_output("diff", "--stat"))
    write_text(report_dir / "git_diff_cached_stat.txt", git_output("diff", "--cached", "--stat"))
    write_text(report_dir / "git_log_recent.txt", git_output("log", "--oneline", "--decorate", "-5"))
    write_text(report_dir / "tracked_worktree.patch", git_output("diff", "--binary"))
    write_text(report_dir / "tracked_name_status.txt", git_output("diff", "--name-status"))
    write_text(report_dir / "untracked_manifest.txt", git_output("ls-files", "--others", "--exclude-standard"))
    write_text(report_dir / "ignored_untracked_manifest.txt", git_output("ls-files", "--others", "-i", "--exclude-standard"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Guarded, path-specific repository cleanup controller. Defaults to non-destructive behavior."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(MODES),
        help="Controller mode.",
    )
    parser.add_argument("--restore-manifest", help="Path to tracked restore manifest.")
    parser.add_argument("--delete-manifest", help="Path to untracked delete manifest.")
    parser.add_argument("--archive-manifest", help="Path to untracked archive manifest.")
    parser.add_argument(
        "--protected-paths",
        default=str(DEFAULT_PROTECTED_PATHS.relative_to(REPO_ROOT)),
        help="Path to protected paths manifest.",
    )
    parser.add_argument(
        "--archive-root",
        default=str(PHASE6_ROOT / "archives"),
        help="Archive destination root used by archive mode.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required alongside execute modes.",
    )
    parser.add_argument(
        "--i-understand-this-can-change-files",
        action="store_true",
        help="Second required acknowledgement alongside execute modes.",
    )
    return parser.parse_args()


def mode_family(mode: str) -> str:
    if "restore" in mode:
        return "restore"
    if "delete" in mode:
        return "delete"
    if "archive" in mode:
        return "archive"
    return mode


def load_manifest_for_mode(args: argparse.Namespace) -> tuple[str, list[Path]]:
    family = mode_family(args.mode)
    manifest_arg = {
        "restore": args.restore_manifest,
        "delete": args.delete_manifest,
        "archive": args.archive_manifest,
    }.get(family)

    if family in {"snapshot", "plan"}:
        manifest_paths: list[Path] = []
        for maybe in (args.restore_manifest, args.delete_manifest, args.archive_manifest):
            if maybe:
                manifest_paths.extend(read_manifest(normalize_manifest_path(maybe)))
        return family, manifest_paths

    if not manifest_arg:
        raise CleanupError(f"--{family}-manifest is required for mode {args.mode}")
    return family, read_manifest(normalize_manifest_path(manifest_arg))


def require_execute_ack(args: argparse.Namespace) -> None:
    if not args.mode.startswith("execute-"):
        return
    if not args.execute or not args.i_understand_this_can_change_files:
        raise CleanupError(
            "Refusing execute mode. Re-run with both --execute and "
            "--i-understand-this-can-change-files."
        )


def validate_delete_candidates(
    candidates: list[Path],
    protected: list[Path],
    tracked: set[str],
    untracked: set[str],
) -> tuple[list[ActionItem], list[str], list[str]]:
    actions: list[ActionItem] = []
    warnings: list[str] = []
    blocked: list[str] = []
    for candidate in candidates:
        ensure_repo_member(candidate)
        rel = rel_repo_path(candidate)
        if is_protected(candidate, protected):
            blocked.append(f"{rel} :: protected path")
            actions.append(ActionItem("delete", "blocked", rel, "protected path"))
            continue
        if rel in tracked:
            blocked.append(f"{rel} :: tracked path")
            actions.append(ActionItem("delete", "blocked", rel, "tracked path cannot be deleted"))
            continue
        if candidate.exists() and candidate.is_dir() and has_tracked_descendants(candidate, tracked):
            blocked.append(f"{rel} :: directory contains tracked files")
            actions.append(ActionItem("delete", "blocked", rel, "directory contains tracked files"))
            continue
        if rel not in untracked and not candidate.exists():
            blocked.append(f"{rel} :: path does not exist")
            actions.append(ActionItem("delete", "blocked", rel, "path does not exist"))
            continue
        actions.append(ActionItem("delete", "planned", rel, "untracked candidate"))
        warnings.append(f"Delete candidate retained for explicit approval only: {rel}")
    return actions, warnings, blocked


def validate_restore_candidates(
    candidates: list[Path],
    protected: list[Path],
    tracked: set[str],
) -> tuple[list[ActionItem], list[str], list[str]]:
    actions: list[ActionItem] = []
    warnings: list[str] = []
    blocked: list[str] = []
    for candidate in candidates:
        ensure_repo_member(candidate)
        rel = rel_repo_path(candidate)
        if is_protected(candidate, protected):
            blocked.append(f"{rel} :: protected path")
            actions.append(ActionItem("restore", "blocked", rel, "protected path"))
            continue
        if rel not in tracked:
            blocked.append(f"{rel} :: not tracked")
            actions.append(ActionItem("restore", "blocked", rel, "restore requires tracked path"))
            continue
        actions.append(ActionItem("restore", "planned", rel, "tracked restore candidate"))
        warnings.append(f"Restore candidate requires explicit review: {rel}")
    return actions, warnings, blocked


def validate_archive_candidates(
    candidates: list[Path],
    protected: list[Path],
    tracked: set[str],
    untracked: set[str],
) -> tuple[list[ActionItem], list[str], list[str]]:
    actions: list[ActionItem] = []
    warnings: list[str] = []
    blocked: list[str] = []
    for candidate in candidates:
        ensure_repo_member(candidate)
        rel = rel_repo_path(candidate)
        if is_protected(candidate, protected):
            blocked.append(f"{rel} :: protected path")
            actions.append(ActionItem("archive", "blocked", rel, "protected path"))
            continue
        if rel in tracked:
            blocked.append(f"{rel} :: tracked path")
            actions.append(ActionItem("archive", "blocked", rel, "archive mode is for untracked paths only"))
            continue
        if candidate.exists() and candidate.is_dir() and has_tracked_descendants(candidate, tracked):
            blocked.append(f"{rel} :: directory contains tracked files")
            actions.append(ActionItem("archive", "blocked", rel, "directory contains tracked files"))
            continue
        if rel not in untracked and not candidate.exists():
            blocked.append(f"{rel} :: path does not exist")
            actions.append(ActionItem("archive", "blocked", rel, "path does not exist"))
            continue
        actions.append(ActionItem("archive", "planned", rel, "untracked archive candidate"))
        warnings.append(f"Archive candidate requires explicit review: {rel}")
    return actions, warnings, blocked


def create_pre_execute_backup(report_dir: Path) -> Path:
    backup_dir = ensure_dir(report_dir / "pre_execute_backup")
    create_snapshot_outputs(backup_dir)
    return backup_dir


def copy_path(src: Path, dst_root: Path) -> Path:
    dest = dst_root / rel_repo_path(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return dest


def execute_restore(items: list[ActionItem]) -> None:
    for item in items:
        run_git("restore", "--", item.path, capture=True, check=True)
        item.status = "executed"
        item.detail = "git restore executed"


def execute_delete(items: list[ActionItem]) -> None:
    for item in items:
        target = REPO_ROOT / item.path
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        item.status = "executed"
        item.detail = "filesystem delete executed"


def execute_archive(items: list[ActionItem], archive_root: Path) -> None:
    archive_run_root = ensure_dir(archive_root / now_stamp())
    for item in items:
        target = REPO_ROOT / item.path
        dest = copy_path(target, archive_run_root)
        item.status = "executed"
        item.detail = f"copied to {dest.relative_to(REPO_ROOT)}"


def write_summary(
    report_dir: Path,
    mode: str,
    items: list[ActionItem],
    warnings: list[str],
    blocked: list[str],
    backup_dir: Path | None,
) -> None:
    planned = sum(1 for item in items if item.status == "planned")
    executed = sum(1 for item in items if item.status == "executed")
    blocked_count = sum(1 for item in items if item.status == "blocked")
    lines = [
        "# Guarded Cleanup Summary",
        "",
        f"- mode: `{mode}`",
        f"- report_dir: `{report_dir.relative_to(REPO_ROOT).as_posix()}`",
        f"- planned_actions: `{planned}`",
        f"- executed_actions: `{executed}`",
        f"- blocked_actions: `{blocked_count}`",
        f"- warnings: `{len(warnings)}`",
        f"- backup_created: `{'yes' if backup_dir else 'no'}`",
    ]
    if backup_dir:
        lines.append(f"- backup_dir: `{backup_dir.relative_to(REPO_ROOT).as_posix()}`")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This controller does not use broad `git clean -fd` or `git clean -fdX`.",
            "- All operations are path-specific and manifest-driven.",
            "- Protected paths are blocked by default.",
        ]
    )
    write_text(report_dir / "summary.md", "\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    protected_manifest = normalize_manifest_path(args.protected_paths)
    protected = read_protected_paths(protected_manifest)

    report_dir = build_report_dir(args.mode)
    ensure_dir(report_dir)
    warnings: list[str] = []
    blocked: list[str] = []
    items: list[ActionItem] = []
    backup_dir: Path | None = None

    try:
        require_execute_ack(args)

        if args.mode == "snapshot":
            create_snapshot_outputs(report_dir)
            warnings.append("Snapshot created. No file-changing actions were attempted.")
            write_action_plan(report_dir, [])
            write_lines(report_dir / "safety_warnings.txt", warnings)
            write_lines(report_dir / "blocked_paths.txt", [])
            write_summary(report_dir, args.mode, [], warnings, [], None)
            print(f"Snapshot written to {report_dir.relative_to(REPO_ROOT).as_posix()}")
            return 0

        family, manifest_candidates = load_manifest_for_mode(args)
        tracked = tracked_paths()
        untracked = untracked_paths()

        if args.mode == "plan":
            if args.restore_manifest:
                plan_items, plan_warnings, plan_blocked = validate_restore_candidates(
                    read_manifest(normalize_manifest_path(args.restore_manifest)),
                    protected,
                    tracked,
                )
                items.extend(plan_items)
                warnings.extend(plan_warnings)
                blocked.extend(plan_blocked)
            if args.delete_manifest:
                plan_items, plan_warnings, plan_blocked = validate_delete_candidates(
                    read_manifest(normalize_manifest_path(args.delete_manifest)),
                    protected,
                    tracked,
                    untracked,
                )
                items.extend(plan_items)
                warnings.extend(plan_warnings)
                blocked.extend(plan_blocked)
            if args.archive_manifest:
                plan_items, plan_warnings, plan_blocked = validate_archive_candidates(
                    read_manifest(normalize_manifest_path(args.archive_manifest)),
                    protected,
                    tracked,
                    untracked,
                )
                items.extend(plan_items)
                warnings.extend(plan_warnings)
                blocked.extend(plan_blocked)
        elif family == "restore":
            items, warnings, blocked = validate_restore_candidates(manifest_candidates, protected, tracked)
        elif family == "delete":
            items, warnings, blocked = validate_delete_candidates(manifest_candidates, protected, tracked, untracked)
        elif family == "archive":
            items, warnings, blocked = validate_archive_candidates(manifest_candidates, protected, tracked, untracked)
        else:
            raise CleanupError(f"Unsupported mode family: {family}")

        if args.mode.startswith("execute-"):
            require_no_staged_changes()
            backup_dir = create_pre_execute_backup(report_dir)
            if family == "restore":
                execute_restore([item for item in items if item.status == "planned"])
            elif family == "delete":
                execute_delete([item for item in items if item.status == "planned"])
            elif family == "archive":
                execute_archive(
                    [item for item in items if item.status == "planned"],
                    normalize_manifest_path(args.archive_root),
                )
        else:
            warnings.append("Dry-run or plan mode only. No file-changing actions were executed.")

        write_action_plan(report_dir, items)
        write_lines(report_dir / "safety_warnings.txt", warnings)
        write_lines(report_dir / "blocked_paths.txt", blocked)
        write_summary(report_dir, args.mode, items, warnings, blocked, backup_dir)

        print(f"Report written to {report_dir.relative_to(REPO_ROOT).as_posix()}")
        if blocked:
            print("Blocked paths were recorded. Review blocked_paths.txt before any later action.")
        return 0
    except CleanupError as exc:
        warnings.append(str(exc))
        write_action_plan(report_dir, items)
        write_lines(report_dir / "safety_warnings.txt", warnings)
        write_lines(report_dir / "blocked_paths.txt", blocked)
        write_summary(report_dir, args.mode, items, warnings, blocked, backup_dir)
        print(str(exc), file=sys.stderr)
        print(f"Failure report written to {report_dir.relative_to(REPO_ROOT).as_posix()}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
