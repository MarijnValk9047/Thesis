from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / "notebooks"
    / "Data"
    / "01_Cleaning"
    / "MARI DE"
    / "01_17_1_f_de_a16_realised_cleaning_walkthrough.ipynb"
)


def markdown_cell(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code_cell(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


def build_notebook() -> nbf.NotebookNode:
    cells = [
        markdown_cell(
            """
            # 01 17.1.F DE A16 Realised Cleaning Walkthrough

            This notebook walks through the cleaning of ENTSO-E `17.1.F DE A16 (Realised)` step by step:

            - inspect the four raw German zone exports
            - parse them into a readable native points table
            - derive variable-duration blocks and zone-level quarter-hours
            - compare zones for consistency and potential raw-data mistakes
            - build a conservative combined-DE layer while preserving zone separability

            The key structural conclusion is different from NL:

            - DE is an event-like sparse dataset with many short activation windows
            - the four zone exports are kept separately
            - a combined-DE series is only created when the zone values agree
            - the current raw export is flagged because all four zones are exact duplicates
            """
        ),
        code_cell(
            """
            from __future__ import annotations

            import importlib.util
            import sys
            from pathlib import Path

            import pandas as pd
            from IPython import get_ipython

            ip = get_ipython()
            if ip is not None:
                ip.run_line_magic("matplotlib", "inline")

            import matplotlib.pyplot as plt

            pd.set_option("display.max_columns", 200)
            pd.set_option("display.max_colwidth", None)
            pd.set_option("display.width", 240)
            pd.set_option("display.expand_frame_repr", False)
            plt.style.use("seaborn-v0_8-whitegrid")


            def find_repo_root(start: Path | None = None) -> Path:
                start = start or Path.cwd()
                for candidate in [start, *start.parents]:
                    if (candidate / "AGENTS.md").exists() and (candidate / "scripts").exists():
                        return candidate
                raise FileNotFoundError("Could not locate repository root.")


            def load_cleaning_module(repo_root: Path):
                module_path = repo_root / "scripts" / "Data" / "01_cleaning" / "activated_balancing_energy_de_a16_pipeline.py"
                spec = importlib.util.spec_from_file_location("activated_balancing_energy_de_a16_notebook", module_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                return module


            REPO_ROOT = find_repo_root()
            cleaning = load_cleaning_module(REPO_ROOT)
            """
        ),
        code_cell(
            """
            RAW_DIR = REPO_ROOT / "data" / "00_Raw" / "ENTSOE" / "17.1 F - Prices of activated balancing energy" / "DE" / "A16 (Realised)"
            OUTPUT_DIR = REPO_ROOT / "data" / "01_cleaned" / "Balancing" / "MARI DE" / "17_1_f_de_a16_realised"
            DIAGNOSTICS_DIR = OUTPUT_DIR / "diagnostics"

            config_df = pd.DataFrame(
                [
                    {"setting": "Raw input directory", "value": str(RAW_DIR)},
                    {"setting": "Cleaned output directory", "value": str(OUTPUT_DIR)},
                    {"setting": "Market", "value": cleaning.MARKET},
                    {"setting": "Reporting timezone", "value": cleaning.MARKET_TIMEZONE},
                    {"setting": "Canonical cleaned resolution", "value": cleaning.CANONICAL_RESOLUTION},
                    {"setting": "Expected zone count", "value": cleaning.EXPECTED_ZONE_COUNT},
                    {"setting": "Known-at rule", "value": cleaning.KNOWN_AT_RULE},
                ]
            )
            config_df
            """
        ),
        markdown_cell(
            """
            ## 1. Raw XML Inventory by Zone and Year
            """
        ),
        code_cell(
            """
            inventory_rows = []
            for file_path in sorted(RAW_DIR.glob("*.xml")):
                meta = cleaning.parse_file_metadata(file_path.name)
                inventory_rows.append(
                    {
                        "file": file_path.name,
                        "zone_code": meta["source_zone_code"],
                        "year": meta["source_year"],
                        "size_kb": round(file_path.stat().st_size / 1024, 1),
                    }
                )

            inventory_df = pd.DataFrame(inventory_rows).sort_values(["zone_code", "year"])
            inventory_df
            """
        ),
        code_cell(
            """
            inventory_plot = (
                inventory_df.pivot_table(index="year", columns="zone_code", values="size_kb", aggfunc="sum")
                .sort_index()
            )
            inventory_plot.plot(kind="bar", figsize=(12, 4))
            plt.title("DE A16 raw XML size by zone and year")
            plt.ylabel("KB")
            plt.xlabel("Year")
            plt.xticks(rotation=0)
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 2. Inspect One Raw XML Snippet

            The DE files contain many short `TimeSeries` windows instead of a long continuous year chunk.
            """
        ),
        code_cell(
            """
            sample_path = sorted(RAW_DIR.glob("*.xml"))[0]
            sample_text = sample_path.read_text(encoding="utf-8", errors="replace")

            print("File:", sample_path.name)
            print()
            print("\\n".join(sample_text.splitlines()[:100]))
            """
        ),
        markdown_cell(
            """
            ## 3. Parse Raw XML Into a Readable Native Points Table
            """
        ),
        code_cell(
            """
            points_raw, file_summary_df, parse_errors_df = cleaning.parse_xml_files(RAW_DIR)

            print(f"Point rows parsed: {len(points_raw):,}")
            print(f"Files parsed: {len(file_summary_df):,}")
            print(f"Parse errors: {len(parse_errors_df):,}")

            file_summary_df
            """
        ),
        code_cell(
            """
            if not parse_errors_df.empty:
                parse_errors_df
            else:
                print("No parse errors.")

            readable_points = (
                points_raw[
                    [
                        "source_zone_code",
                        "source_file",
                        "flow_direction_label",
                        "series_period_start_utc",
                        "series_period_end_utc",
                        "point_position",
                        "point_timestamp_utc",
                        "activation_price_eur_per_mwh",
                        "imbalance_price_category_code",
                        "area_domain_matches_filename_zone",
                    ]
                ]
                .sort_values(["source_zone_code", "point_timestamp_utc", "flow_direction_label", "point_position"])
                .reset_index(drop=True)
            )
            readable_points.head(20)
            """
        ),
        markdown_cell(
            """
            ## 4. Diagnose Native Structure and Zone-Level Quality
            """
        ),
        code_cell(
            """
            points_long, duplicates_removed = cleaning.deduplicate_points(points_raw)
            period_diagnostics = cleaning.build_period_diagnostics(points_long)
            points_summary = cleaning.summarize_points(points_long)

            overview_df = pd.DataFrame(
                [
                    {"metric": "Point rows after deduplication", "value": len(points_long)},
                    {"metric": "Duplicates removed", "value": len(duplicates_removed)},
                    {"metric": "Unique zones", "value": points_long["source_zone_code"].nunique()},
                    {"metric": "Unique directions", "value": ", ".join(sorted(points_long["flow_direction_label"].dropna().unique()))},
                    {"metric": "Unique price categories", "value": ", ".join(sorted(points_long["imbalance_price_category_code"].dropna().unique()))},
                    {"metric": "Area domain matches filename zone for all rows", "value": bool(points_long["area_domain_matches_filename_zone"].fillna(False).all())},
                ]
            )
            overview_df
            """
        ),
        code_cell(
            """
            points_summary
            """
        ),
        code_cell(
            """
            period_diagnostics.head(20)
            """
        ),
        code_cell(
            """
            fig, ax = plt.subplots(figsize=(10, 4))
            for zone_code, group in period_diagnostics.groupby("source_zone_code"):
                ax.hist(group["point_count"], bins=range(1, 14), alpha=0.55, label=zone_code)
            ax.set_title("DE native point count per Period")
            ax.set_xlabel("Point count in Period")
            ax.set_ylabel("Number of Periods")
            ax.legend(fontsize=8)
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 5. Turn Native Points Into Blocks and Zone-Level Quarter-Hours
            """
        ),
        code_cell(
            """
            blocks_long = cleaning.build_blocks(points_long)
            zone_quarterhour_long = cleaning.expand_blocks_to_quarterhour(blocks_long)
            zone_quarterhour_wide = cleaning.build_zone_quarterhour_wide(zone_quarterhour_long)
            zone_hourly_long = cleaning.aggregate_zone_hourly(zone_quarterhour_long)

            print(f"Block rows: {len(blocks_long):,}")
            print(f"Zone quarter-hour rows: {len(zone_quarterhour_long):,}")
            print(f"Zone hourly rows: {len(zone_hourly_long):,}")
            blocks_long.head(20)
            """
        ),
        code_cell(
            """
            zone_quarterhour_summary = cleaning.summarize_zone_quarterhour(zone_quarterhour_long)
            zone_hourly_summary = cleaning.summarize_zone_hourly(zone_hourly_long)

            zone_quarterhour_summary
            """
        ),
        code_cell(
            """
            zone_hourly_summary
            """
        ),
        markdown_cell(
            """
            ## 6. Compare Zones for Validity and Potential Raw-Data Mistakes

            This is the critical DE-specific diagnostic. We compare the zone-level quarter-hour series pairwise before building the combined-DE layer.
            """
        ),
        code_cell(
            """
            zone_pair_comparison = cleaning.build_zone_pair_comparison(zone_quarterhour_long)
            zone_pair_comparison
            """
        ),
        code_cell(
            """
            combined_quarterhour_long = cleaning.build_combined_quarterhour(zone_quarterhour_long)
            combined_quarterhour_wide = cleaning.build_combined_quarterhour_wide(combined_quarterhour_long)
            combined_hourly_long = cleaning.aggregate_combined_hourly(combined_quarterhour_long)
            combined_hourly_wide = cleaning.build_combined_hourly_wide(combined_hourly_long)
            combined_quarterhour_summary = cleaning.summarize_combined_quarterhour(combined_quarterhour_long)
            combined_hourly_summary = cleaning.summarize_combined_hourly(combined_hourly_long)
            cross_zone_duplicate_summary = cleaning.build_cross_zone_duplicate_summary(combined_quarterhour_long)

            combined_quarterhour_summary
            """
        ),
        code_cell(
            """
            validity_overview = pd.DataFrame(
                [
                    {"metric": "Quarter-hours with all 4 zones reporting", "value": int((combined_quarterhour_long["reporting_zone_count"] == cleaning.EXPECTED_ZONE_COUNT).sum())},
                    {"metric": "Quarter-hours with zone conflicts", "value": int((~combined_quarterhour_long["all_zone_values_identical"]).sum())},
                    {"metric": "Quarter-hours that are exact cross-zone duplicates", "value": int(cross_zone_duplicate_summary["is_exact_cross_zone_duplicate"].sum())},
                    {"metric": "All pairwise zone series identical", "value": bool(zone_pair_comparison["identical_quarterhour_series"].all())},
                ]
            )
            validity_overview
            """
        ),
        code_cell(
            """
            fig, axes = plt.subplots(1, 2, figsize=(12, 4))

            combined_quarterhour_long["reporting_zone_count"].value_counts().sort_index().plot(
                kind="bar", ax=axes[0], color="#4E79A7"
            )
            axes[0].set_title("Reporting zone count per combined quarter-hour")
            axes[0].set_xlabel("Reporting zones")
            axes[0].set_ylabel("Quarter-hour rows")

            axes[1].hist(combined_quarterhour_long["zone_price_spread_eur_per_mwh"], bins=20, color="#E15759", edgecolor="white")
            axes[1].set_title("Cross-zone price spread per quarter-hour")
            axes[1].set_xlabel("Zone price spread (EUR/MWh)")
            axes[1].set_ylabel("Quarter-hour rows")

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 7. Visualise an Objective Active Day

            Select the local day with the highest number of active combined quarter-hours. If there is a tie, pick the one with the highest absolute combined price.
            """
        ),
        code_cell(
            """
            combined_plot = combined_quarterhour_long.copy()
            combined_plot["local_date"] = combined_plot["timestamp_utc"].dt.tz_convert(cleaning.MARKET_TIMEZONE).dt.date
            activity = (
                combined_plot.groupby("local_date", as_index=False)
                .agg(
                    active_quarterhours=("timestamp_utc", "size"),
                    max_abs_price=("combined_activation_price_eur_per_mwh", lambda s: s.abs().max()),
                )
                .sort_values(["active_quarterhours", "max_abs_price"], ascending=[False, False])
            )
            sample_day = pd.to_datetime(activity.iloc[0]["local_date"])

            print("Selected local day:", sample_day.date())
            activity.head(10)
            """
        ),
        code_cell(
            """
            zone_day = zone_quarterhour_long[
                zone_quarterhour_long["timestamp_utc"].dt.tz_convert(cleaning.MARKET_TIMEZONE).dt.date == sample_day.date()
            ].copy()
            combined_day = combined_quarterhour_long[
                combined_quarterhour_long["timestamp_utc"].dt.tz_convert(cleaning.MARKET_TIMEZONE).dt.date == sample_day.date()
            ].copy()

            fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
            for ax, direction in zip(axes, ["Up", "Down"]):
                zone_sub = zone_day.loc[zone_day["flow_direction_label"] == direction]
                for zone_code, group in zone_sub.groupby("source_zone_code"):
                    ax.plot(group["timestamp_utc"], group["activation_price_eur_per_mwh"], linewidth=1.0, label=zone_code)
                combined_sub = combined_day.loc[combined_day["flow_direction_label"] == direction]
                ax.plot(
                    combined_sub["timestamp_utc"],
                    combined_sub["combined_activation_price_eur_per_mwh"],
                    linewidth=2.3,
                    color="black",
                    linestyle="--",
                    label="DE combined",
                )
                ax.set_title(f"{direction} zone prices on the selected active day")
                ax.set_ylabel("EUR/MWh")
                ax.legend(fontsize=8, ncol=3)
            axes[-1].set_xlabel("Timestamp UTC")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 8. Inspect the Combined-DE Hourly Layer
            """
        ),
        code_cell(
            """
            combined_hourly_summary
            """
        ),
        code_cell(
            """
            combined_hourly_long.head(20)
            """
        ),
        markdown_cell(
            """
            ## 9. Write the Cleaned Outputs
            """
        ),
        code_cell(
            """
            cleaning.write_outputs(
                OUTPUT_DIR,
                points_raw=points_raw,
                file_summary=file_summary_df,
                parse_errors=parse_errors_df,
                points_long=points_long,
                duplicates_removed=duplicates_removed,
                period_diagnostics=period_diagnostics,
                blocks_long=blocks_long,
                zone_quarterhour_long=zone_quarterhour_long,
                zone_quarterhour_wide=zone_quarterhour_wide,
                combined_quarterhour_long=combined_quarterhour_long,
                combined_quarterhour_wide=combined_quarterhour_wide,
                zone_hourly_long=zone_hourly_long,
                combined_hourly_long=combined_hourly_long,
                combined_hourly_wide=combined_hourly_wide,
                points_summary=points_summary,
                blocks_summary=cleaning.summarize_blocks(blocks_long),
                zone_quarterhour_summary=zone_quarterhour_summary,
                combined_quarterhour_summary=combined_quarterhour_summary,
                zone_hourly_summary=zone_hourly_summary,
                combined_hourly_summary=combined_hourly_summary,
                zone_pair_comparison=zone_pair_comparison,
                cross_zone_duplicate_summary=cross_zone_duplicate_summary,
            )

            saved_files = sorted(str(path.relative_to(OUTPUT_DIR)) for path in OUTPUT_DIR.rglob("*") if path.is_file())
            pd.DataFrame({"saved_file": saved_files}).head(60)
            """
        ),
    ]

    notebook = nbf.v4.new_notebook()
    notebook["cells"] = cells
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook["metadata"]["language_info"] = {"name": "python"}
    return notebook


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    notebook = build_notebook()
    with NOTEBOOK_PATH.open("w", encoding="utf-8") as handle:
        nbf.write(notebook, handle)


if __name__ == "__main__":
    main()
