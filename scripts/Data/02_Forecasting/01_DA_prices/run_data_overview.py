from __future__ import annotations

from dataclasses import replace

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.pipeline import prepare_data_bundle
from hourly_da.core.plotting import plot_price_overview
from hourly_da.core.storage import create_run_directory, write_csv, write_json


def main() -> None:
    config = replace(HourlyDAPipelineConfig())
    prepared = prepare_data_bundle(config)
    run_id, run_dir = create_run_directory(config.output_root, "data_overview")

    write_json(run_dir / "config_snapshot.json", config.to_json_dict())
    write_json(run_dir / "timezone_audit.json", prepared["timezone_audit"].to_dict())
    write_csv(run_dir / "gap_summary.csv", prepared["gap_summary"])
    write_csv(run_dir / "gap_intervals.csv", prepared["gap_intervals"])
    write_csv(run_dir / "split_summary.csv", prepared["split_summary"])
    write_csv(run_dir / "canonical_hourly_targets.csv", prepared["canonical_frame"])

    plot_price_overview(
        canonical_frame=prepared["canonical_frame"],
        split_summary=prepared["split_summary"],
        output_path=run_dir / "plots" / "price_overview_with_splits.png",
        target_col=config.target_col,
    )

    gap_count = int(prepared["gap_summary"]["rows_missing"].iloc[0])
    print(f"Run completed: {run_id}")
    print(f"UTC audit verdict: {prepared['timezone_audit'].verdict}")
    print(f"Missing hourly targets on canonical grid: {gap_count}")


if __name__ == "__main__":
    main()
