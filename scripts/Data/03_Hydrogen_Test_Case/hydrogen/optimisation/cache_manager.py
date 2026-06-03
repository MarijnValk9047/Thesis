from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .fingerprinting import stable_json_dumps


def _write_frame(path: Path, frame: pd.DataFrame) -> dict[str, str]:
    try:
        frame.to_parquet(path.with_suffix(".parquet"), index=False)
        return {"filename": path.with_suffix(".parquet").name, "format": "parquet"}
    except Exception:
        frame.to_pickle(path.with_suffix(".pkl"))
        return {"filename": path.with_suffix(".pkl").name, "format": "pickle"}


def _read_frame(path: Path, frame_format: str) -> pd.DataFrame:
    if frame_format == "parquet":
        return pd.read_parquet(path)
    if frame_format == "pickle":
        return pd.read_pickle(path)
    raise ValueError(f"Unsupported cache frame format: {frame_format}")


@dataclass(frozen=True)
class CacheBundle:
    namespace: str
    key: str
    entry_dir: Path
    manifest: dict[str, Any]
    frames: dict[str, pd.DataFrame]
    cache_status: str


class CacheManager:
    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _entry_dir(self, namespace: str, key: str) -> Path:
        return self.cache_root / str(namespace) / str(key)

    def load_bundle(
        self,
        *,
        namespace: str,
        key: str,
        expected_source_fingerprints: list[dict[str, Any]] | None = None,
    ) -> CacheBundle | None:
        entry_dir = self._entry_dir(namespace, key)
        manifest_path = entry_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cached_sources = manifest.get("source_fingerprints", [])
        if expected_source_fingerprints is not None and stable_json_dumps(cached_sources) != stable_json_dumps(expected_source_fingerprints):
            return None
        frames: dict[str, pd.DataFrame] = {}
        frame_records = manifest.get("frames", {})
        if not isinstance(frame_records, dict):
            return None
        for frame_name, record in frame_records.items():
            if not isinstance(record, dict):
                return None
            filename = record.get("filename")
            frame_format = record.get("format")
            if not filename or not frame_format:
                return None
            frame_path = entry_dir / str(filename)
            if not frame_path.exists():
                return None
            frames[str(frame_name)] = _read_frame(frame_path, str(frame_format))
        return CacheBundle(
            namespace=str(namespace),
            key=str(key),
            entry_dir=entry_dir,
            manifest=manifest,
            frames=frames,
            cache_status="hit",
        )

    def save_bundle(
        self,
        *,
        namespace: str,
        key: str,
        frames: dict[str, pd.DataFrame],
        manifest: dict[str, Any],
    ) -> CacheBundle:
        entry_dir = self._entry_dir(namespace, key)
        entry_dir.mkdir(parents=True, exist_ok=True)
        frame_records: dict[str, dict[str, str]] = {}
        for frame_name, frame in frames.items():
            frame_records[str(frame_name)] = _write_frame(entry_dir / str(frame_name), frame)
        payload = {
            **manifest,
            "namespace": str(namespace),
            "key": str(key),
            "frames": frame_records,
            "written_utc": datetime.now(tz=timezone.utc).isoformat(),
        }
        (entry_dir / "manifest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return CacheBundle(
            namespace=str(namespace),
            key=str(key),
            entry_dir=entry_dir,
            manifest=payload,
            frames=frames,
            cache_status="written",
        )
