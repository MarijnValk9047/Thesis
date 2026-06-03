from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, write_phase2_7_hourly_parity_bundle


def main() -> None:
    config = QuarterHourDAExtensionConfig()
    paths = write_phase2_7_hourly_parity_bundle(config)
    summary = json.loads((paths.run_dir / "run_summary.json").read_text(encoding="utf-8"))
    print("Phase 2.7 hourly-parity retrofit bundle written:")
    print(paths.run_dir)
    print("Status:", summary.get("status"))
    print("Parent run:", summary.get("source_runs", {}).get("phase2_parent_finalisation_run_id"))
    print("Official naive model:", summary.get("official_naive_denominator_policy", {}).get("model"))
    print("Phase 3 ready:", summary.get("phase3_readiness", {}).get("ready_for_phase3_heavy"))


if __name__ == "__main__":
    main()
