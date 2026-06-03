from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_freeze_canonical_actual_path


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    version_dir = run_freeze_canonical_actual_path(config)
    payload = {
        "version_dir": str(version_dir),
        "canonical_csv": str(version_dir / "synthetic_actual_15min_canonical.csv"),
        "manifest_json": str(version_dir / "synthetic_actual_15min_manifest.json"),
        "diagnostics_csv": str(version_dir / "synthetic_actual_15min_diagnostics.csv"),
        "hash_txt": str(version_dir / "synthetic_actual_15min_hash.txt"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
