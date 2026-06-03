from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SELF_PATH = Path(__file__).resolve()

SCAN_FILES = [
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / ".gitignore",
    REPO_ROOT / ".pre-commit-config.yaml",
]

SCAN_DIRS = [
    REPO_ROOT / "docs",
    REPO_ROOT / "scripts",
]

SKIP_DIR_NAMES = {
    "data",
    "workspace_triage",
    ".venv",
    "__pycache__",
}

SKIP_SUFFIXES = {
    ".ipynb",
}

ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"C:\\Users\\", re.IGNORECASE),
    re.compile(r"/C:/Users/", re.IGNORECASE),
    re.compile(r"file:///C:", re.IGNORECASE),
    re.compile(r"PycharmProjects/Thesis", re.IGNORECASE),
    re.compile(r"[A-Z]:\\[^\"'\s`]*gurobi\.lic", re.IGNORECASE),
    re.compile(r"/C:/[^\"'\s`]*gurobi\.lic", re.IGNORECASE),
]

SECRET_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|authorization)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
]


def should_skip(path: Path) -> bool:
    # This checker contains the risky literals by design, so exclude it from self-scan.
    if (REPO_ROOT / path).resolve() == SELF_PATH:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def iter_scan_paths() -> list[Path]:
    try:
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "AGENTS.md",
                ".gitignore",
                ".pre-commit-config.yaml",
                "docs",
                "scripts",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        paths = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            rel_path = Path(line.strip())
            if should_skip(rel_path):
                continue
            full_path = REPO_ROOT / rel_path
            if full_path.is_file():
                paths.append(full_path)
        return sorted(set(paths))
    except (subprocess.CalledProcessError, FileNotFoundError):
        paths: list[Path] = []

        for file_path in SCAN_FILES:
            if file_path.exists() and not should_skip(file_path.relative_to(REPO_ROOT)):
                paths.append(file_path)

        for directory in SCAN_DIRS:
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                rel_path = path.relative_to(REPO_ROOT)
                if should_skip(rel_path):
                    continue
                paths.append(path)

        return sorted(set(paths))


def find_line_hits(line: str) -> list[str]:
    hits: list[str] = []

    for pattern in ABSOLUTE_PATH_PATTERNS:
        match = pattern.search(line)
        if match:
            hits.append(match.group(0))

    for pattern in SECRET_PATTERNS:
        match = pattern.search(line)
        if match:
            hits.append(match.group(0))

    return hits


def main() -> int:
    findings: list[str] = []

    for path in iter_scan_paths():
        rel_path = path.relative_to(REPO_ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")

        for line_number, line in enumerate(text.splitlines(), start=1):
            for hit in find_line_hits(line):
                findings.append(f"{rel_path}:{line_number}: {hit}")

    if findings:
        for finding in findings:
            print(finding)
        return 1

    print("Portable path and secret check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
