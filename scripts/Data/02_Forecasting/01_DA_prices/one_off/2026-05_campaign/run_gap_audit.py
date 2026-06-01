from __future__ import annotations

import json

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.gap_audit import build_gap_audit_tables
from hourly_da.core.storage import create_run_directory, write_csv, write_json, write_text


def build_audit_note(summary, domains, artifacts) -> str:
    lines = [
        "# Hourly DA Audit Note",
        "",
        "## Import and source coverage",
    ]
    for row in domains.to_dict(orient="records"):
        raw_summary = summary[(summary["market_area"] == row["market_area"]) & (summary["stage_name"] == "raw_imported_data")].iloc[0]
        years = json.loads(str(raw_summary["raw_xml_years_from_filename_json"]))
        lines.append(
            f"- `{row['market_area']}` raw XML years present: `{years}` | 2021 present: `{bool(raw_summary['raw_xml_has_2021_files'])}`"
        )
    lines.extend(
        [
            "",
            "- The downloader defaults were extended to include 2021 for DA A01 price datasets, but the current live ENTSO-E API verification call returned `HTTP 404`, so 2021 raw backfill is still blocked outside the cleaner.",
            "",
            "## Timestamp entry and UTC standardization",
            "- Raw DA XML periods use explicit UTC timestamps such as `2021-12-31T23:00Z`.",
            "- The cleaner parses them with `utc=True` and the forecasting pipeline keeps timezone-aware UTC internally.",
            "- Local-time construction is only used for split rules, delivery-day logic, and reporting.",
            "",
            "## DA availability assumption",
            "- The pipeline now uses a `known_at_utc` concept.",
            "- Under the current assumption, the full DA curve for local delivery day `t` is treated as known from `t 08:00` local time onward.",
            "- This means that at forecast origin `D-1 08:00`, the full DA curve for day `D-1` is available to the models.",
            "",
            "## Gap-origin summary",
            "- `raw_imported_data` and `parsed_series` show whether gaps already exist in the source import.",
            "- `normalized_utc_series` shows the final observed hourly series after DE sequence filtering, duplicate removal, clipping, and hourly-resolution filtering.",
            "- `post_reindex_series` makes existing missing hours explicit on the canonical hourly UTC grid.",
            "- `feature_source_series` uses deterministic fill for lag construction only; it should not be confused with observed target coverage.",
        ]
    )
    if not artifacts.empty:
        lines.extend(["", "## Existing artifact cross-check"])
        for row in artifacts.to_dict(orient="records"):
            lines.append(
                f"- `{row['market_area']}` `{row['artifact_name']}`: artifact=`{row['artifact_value']}` vs current `{row['current_stage_name']}`=`{row['current_value']}`"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    config = HourlyDAPipelineConfig()
    run_id, run_dir = create_run_directory(config.output_root, "gap_audit")
    summary, intervals, domains, artifacts = build_gap_audit_tables()

    write_json(run_dir / "config_snapshot.json", config.to_json_dict())
    write_csv(run_dir / "gap_stage_summary.csv", summary)
    write_csv(run_dir / "gap_stage_intervals.csv", intervals)
    write_csv(run_dir / "domain_code_audit.csv", domains)
    write_csv(run_dir / "artifact_cross_check.csv", artifacts)
    write_text(run_dir / "audit_note.md", build_audit_note(summary, domains, artifacts))

    print(f"Run completed: {run_id}")
    print(summary[["market_area", "stage_name", "missing_timestamps_count", "gap_count", "gap_origin_assessment"]].to_string(index=False))


if __name__ == "__main__":
    main()
