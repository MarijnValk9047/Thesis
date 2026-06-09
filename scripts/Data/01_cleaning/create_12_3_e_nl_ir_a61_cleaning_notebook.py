from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / "notebooks"
    / "Data"
    / "01_Cleaning"
    / "IR Energy"
    / "01_12_3_e_nl_ir_a61_cleaning_walkthrough.ipynb"
)


def markdown_cell(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code_cell(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


def build_notebook() -> nbf.NotebookNode:
    cells = [
        markdown_cell(
            """
            # 02 12.3.E NL IR A61 Cleaning Walkthrough

            This notebook walks through the cleaning of ENTSO-E `12.3.E NL IR A61` step by step:

            - starting from the raw XML files in `data/00_Raw/ENTSOE/12_3_E/12_3_E_NL_IR_A61`
            - transforming the sparse XML payload into a readable points table
            - diagnosing duplicates, period boundaries, granularity, gaps, and time coverage
            - deriving block intervals from point positions
            - expanding those blocks to a canonical quarter-hour UTC grid
            - aggregating to conservative hourly outputs

            The key structural finding is different from `17.1 B&C`:

            - this dataset is **not** one dense row per reported quarter-hour
            - the XML uses `curveType = A03`
            - points behave like **change points** for variable-duration blocks

            So the cleaning rule is: interpret each point as the start of a block that runs until the next point or the end of the Period.
            """
        ),
        code_cell(
            """
            from __future__ import annotations

            import importlib.util
            import json
            import sys
            from pathlib import Path

            import pandas as pd
            from IPython import get_ipython
            from IPython.display import Markdown, display

            ip = get_ipython()
            if ip is not None:
                ip.run_line_magic("matplotlib", "inline")

            import matplotlib.pyplot as plt

            pd.set_option("display.max_columns", 200)
            pd.set_option("display.max_colwidth", None)
            pd.set_option("display.width", 220)
            pd.set_option("display.expand_frame_repr", False)
            plt.style.use("seaborn-v0_8-whitegrid")


            def find_repo_root(start: Path | None = None) -> Path:
                start = start or Path.cwd()
                for candidate in [start, *start.parents]:
                    if (candidate / "AGENTS.md").exists() and (candidate / "scripts").exists():
                        return candidate
                raise FileNotFoundError("Could not locate repository root.")


            def load_cleaning_module(repo_root: Path):
                module_path = repo_root / "scripts" / "Data" / "01_cleaning" / "balancing_bid_document_a61_pipeline.py"
                spec = importlib.util.spec_from_file_location("balancing_bid_document_a61_cleaning_notebook", module_path)
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
            RAW_DIR = REPO_ROOT / "data" / "00_Raw" / "ENTSOE" / "12_3_E" / "12_3_E_NL_IR_A61"
            OUTPUT_DIR = REPO_ROOT / "data" / "01_cleaned" / "02_Balancing_mFRR_IR" / "IR Energy" / "12_3_e_nl_ir_a61"
            DIAGNOSTICS_DIR = OUTPUT_DIR / "diagnostics"

            config_df = pd.DataFrame(
                [
                    {"setting": "Raw input directory", "value": str(RAW_DIR)},
                    {"setting": "Cleaned output directory", "value": str(OUTPUT_DIR)},
                    {"setting": "Market", "value": cleaning.MARKET},
                    {"setting": "Reporting timezone", "value": cleaning.MARKET_TIMEZONE},
                    {"setting": "Canonical cleaned resolution", "value": cleaning.CANONICAL_RESOLUTION},
                    {"setting": "Known-at rule", "value": cleaning.KNOWN_AT_RULE},
                ]
            )
            display(config_df)
            """
        ),
        markdown_cell(
            """
            ## 1. Raw XML Inventory

            Start with the raw files themselves: file sizes, file counts, and the year-style split. This is the quickest way to see whether the export is archived, paginated, or already flattened into plain XML files.
            """
        ),
        code_cell(
            """
            inventory_rows = []
            for file_path in sorted(RAW_DIR.glob("*.xml")):
                inventory_rows.append(
                    {
                        "file": file_path.name,
                        "size_kb": round(file_path.stat().st_size / 1024, 1),
                    }
                )

            inventory_df = pd.DataFrame(inventory_rows)
            display(inventory_df)

            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(inventory_df["file"], inventory_df["size_kb"], color="#4C78A8")
            ax.set_title("Raw XML file sizes")
            ax.set_ylabel("KB")
            ax.set_xlabel("File")
            plt.xticks(rotation=30, ha="right")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 2. Inspect One Raw XML Snippet

            Before parsing anything, read the first lines of one raw XML file directly. This makes the document structure visible: document type, process type, Period definitions, and Point payload fields.
            """
        ),
        code_cell(
            """
            sample_path = sorted(RAW_DIR.glob("*.xml"))[0]
            sample_text = sample_path.read_text(encoding="utf-8", errors="replace")

            print("File:", sample_path.name)
            print()
            print("\\n".join(sample_text.splitlines()[:60]))
            """
        ),
        markdown_cell(
            """
            ## 3. Parse the Raw XML Into a Readable Sparse Points Table

            The first real transformation is a readable long table with one row per XML `Point`. At this stage the dataset is still sparse, which is exactly what we want for diagnostics.
            """
        ),
        code_cell(
            """
            points_raw, file_summary_df, parse_errors_df = cleaning.parse_xml_files(RAW_DIR)

            print(f"Point rows parsed: {len(points_raw):,}")
            print(f"Files parsed: {len(file_summary_df):,}")
            print(f"Parse errors: {len(parse_errors_df):,}")

            display(file_summary_df)
            if not parse_errors_df.empty:
                display(parse_errors_df)
            """
        ),
        code_cell(
            """
            readable_points = (
                points_raw[
                    [
                        "source_file",
                        "flow_direction_label",
                        "curve_type_label",
                        "series_period_start_utc",
                        "series_period_end_utc",
                        "reported_resolution",
                        "point_position",
                        "point_timestamp_utc",
                        "quantity_maw",
                        "secondary_quantity_maw",
                        "unavailable_quantity_maw",
                    ]
                ]
                .sort_values(["point_timestamp_utc", "flow_direction_label", "point_position"])
                .reset_index(drop=True)
            )

            display(readable_points.head(20))
            """
        ),
        markdown_cell(
            """
            ## 4. Interpret the Structure

            Now answer the structural questions:

            - which codes occur
            - whether the dataset is truly sparse
            - how many points each Period carries versus a dense PT15M grid
            - whether there are duplicates to remove
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
                    {"metric": "Min point timestamp UTC", "value": points_long["point_timestamp_utc"].min()},
                    {"metric": "Max point timestamp UTC", "value": points_long["point_timestamp_utc"].max()},
                    {"metric": "Unique directions", "value": ", ".join(sorted(points_long["flow_direction_label"].dropna().unique()))},
                    {"metric": "Unique curve types", "value": ", ".join(sorted(points_long["curve_type_label"].dropna().unique()))},
                    {"metric": "Unique resolutions", "value": ", ".join(sorted(points_long["reported_resolution"].dropna().unique()))},
                ]
            )
            display(overview_df)
            display(points_summary)
            """
        ),
        code_cell(
            """
            code_tables_df = pd.concat(
                [
                    pd.DataFrame(cleaning.DOCUMENT_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="document_type"),
                    pd.DataFrame(cleaning.PROCESS_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="process_type"),
                    pd.DataFrame(cleaning.BUSINESS_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="business_type"),
                    pd.DataFrame(cleaning.CURVE_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="curve_type"),
                    pd.DataFrame(cleaning.FLOW_DIRECTION_LABELS.items(), columns=["code", "label"]).assign(code_family="flow_direction"),
                ],
                ignore_index=True,
            )
            display(code_tables_df)
            """
        ),
        code_cell(
            """
            display(period_diagnostics)
            display(duplicates_removed.head(20))

            fig, axes = plt.subplots(1, 2, figsize=(14, 4))

            dense_compare = period_diagnostics.copy()
            dense_compare["period_label"] = (
                dense_compare["flow_direction_label"]
                + " | "
                + dense_compare["series_period_start_utc"].dt.strftime("%Y-%m-%d %H:%M")
            )
            axes[0].bar(dense_compare["period_label"], dense_compare["expected_dense_point_count"], color="#9ECAE1", label="Dense PT15M grid")
            axes[0].bar(dense_compare["period_label"], dense_compare["point_count"], color="#1F77B4", label="Actual sparse points")
            axes[0].set_title("Sparse points versus dense PT15M grid")
            axes[0].set_ylabel("Point count")
            axes[0].tick_params(axis="x", rotation=90)
            axes[0].legend()

            period_diagnostics["compression_ratio_vs_dense_grid"].plot(kind="bar", ax=axes[1], color="#F58518")
            axes[1].set_title("Compression ratio versus dense grid")
            axes[1].set_xlabel("Period row")
            axes[1].set_ylabel("Sparse points / dense points")

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 5. Cleaning Step 1: Convert Sparse Points Into Blocks

            This is the central cleaning step. For `curveType = A03`, each point is treated as a block start:

            - `block_start_utc = point_timestamp_utc`
            - `block_end_utc = next point timestamp`
            - if there is no next point, the block ends at the Period end
            """
        ),
        code_cell(
            """
            blocks_long = cleaning.build_blocks(points_long)
            blocks_summary = cleaning.summarize_blocks(blocks_long)

            display(blocks_long.head(20))
            display(blocks_summary)
            """
        ),
        code_cell(
            """
            fig, axes = plt.subplots(1, 2, figsize=(14, 4))

            block_duration_hours = blocks_long["block_duration_minutes"] / 60.0
            block_duration_hours.value_counts().sort_index().plot(kind="bar", ax=axes[0], color="#54A24B")
            axes[0].set_title("Block duration distribution")
            axes[0].set_xlabel("Hours")
            axes[0].set_ylabel("Blocks")

            sample_blocks = blocks_long.head(80).copy()
            axes[1].scatter(
                sample_blocks["native_point_timestamp_utc"],
                sample_blocks["block_quarterhour_count"],
                c=sample_blocks["flow_direction_code"].map({"A01": "#E45756", "A02": "#4C78A8"}),
                s=20,
            )
            axes[1].set_title("Early sample of block lengths over time")
            axes[1].set_ylabel("Quarter-hours in block")
            axes[1].set_xlabel("Block start UTC")

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 6. Cleaning Step 2: Expand Blocks to a Canonical Quarter-Hour UTC Grid

            Once blocks are explicit, expand them to one row per actual quarter-hour covered by the block. This creates the canonical cleaned grid used for diagnostics, visualization, and later hourly aggregation.
            """
        ),
        code_cell(
            """
            quarterhour_long = cleaning.expand_blocks_to_quarterhour(blocks_long)
            quarterhour_wide = cleaning.build_quarterhour_wide(quarterhour_long)
            quarterhour_summary = cleaning.summarize_quarterhour(quarterhour_long)
            gap_intervals, gap_summary = cleaning.find_gap_intervals(quarterhour_long)

            print(f"Quarter-hour rows: {len(quarterhour_long):,}")
            display(quarterhour_summary)
            display(quarterhour_long.head(20))
            display(quarterhour_wide.head(12))
            """
        ),
        code_cell(
            """
            display(gap_intervals.head(20))
            display(gap_summary)

            coverage_window = (
                quarterhour_long.assign(hour_timestamp_utc=quarterhour_long["timestamp_utc"].dt.floor("h"))
                .groupby(["hour_timestamp_utc", "flow_direction_label"], as_index=False)
                .agg(quarterhours=("timestamp_utc", "size"))
            )
            coverage_window = coverage_window[
                (coverage_window["hour_timestamp_utc"] >= pd.Timestamp("2024-10-26 20:00:00+00:00"))
                & (coverage_window["hour_timestamp_utc"] <= pd.Timestamp("2024-10-27 04:00:00+00:00"))
            ]

            fig, ax = plt.subplots(figsize=(12, 4))
            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = coverage_window[coverage_window["flow_direction_label"] == label]
                ax.plot(subset["hour_timestamp_utc"], subset["quarterhours"], marker="o", label=label, color=color)
            ax.axhspan(0, 3.99, color="#FEE08B", alpha=0.2)
            ax.set_title("Quarter-hour coverage around the DST-boundary split")
            ax.set_ylabel("Observed quarter-hours in the hour")
            ax.set_xlabel("Hour UTC")
            ax.legend()
            plt.xticks(rotation=30, ha="right")
            plt.tight_layout()
            plt.show()
            """
        ),
        code_cell(
            """
            monthly_quantity = (
                quarterhour_long.assign(month=quarterhour_long["timestamp_utc"].dt.to_period("M").astype(str))
                .groupby(["month", "flow_direction_label"], as_index=False)
                .agg(mean_quantity_maw=("quantity_maw", "mean"))
            )

            fig, ax = plt.subplots(figsize=(14, 4))
            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = monthly_quantity[monthly_quantity["flow_direction_label"] == label]
                ax.plot(subset["month"], subset["mean_quantity_maw"], marker="o", label=label, color=color)
            ax.set_title("Monthly mean quarter-hour quantity")
            ax.set_ylabel("Mean quantity (MAW)")
            ax.set_xlabel("Month")
            ax.legend()
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 7. Cleaning Step 3: Aggregate to Conservative Hourly Outputs

            Hourly aggregation is done from the cleaned quarter-hour table:

            - average across quarter-hours inside the hour
            - keep coverage diagnostics
            - set value columns to missing when the hour is incomplete
            """
        ),
        code_cell(
            """
            hourly_long = cleaning.aggregate_hourly(quarterhour_long)
            hourly_wide = cleaning.build_hourly_wide(hourly_long)
            hourly_summary = cleaning.summarize_hourly(hourly_long)

            print(f"Hourly rows: {len(hourly_long):,}")
            display(hourly_summary)
            display(hourly_long.head(20))
            display(hourly_wide.head(12))
            """
        ),
        code_cell(
            """
            incomplete_hours = hourly_long.loc[~hourly_long["is_complete_hour"]].copy()
            display(incomplete_hours)

            sample_hourly = hourly_long[
                (hourly_long["timestamp_utc"] >= pd.Timestamp("2024-10-20 00:00:00+00:00"))
                & (hourly_long["timestamp_utc"] < pd.Timestamp("2024-11-05 00:00:00+00:00"))
            ]

            fig, ax = plt.subplots(figsize=(14, 4))
            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = sample_hourly[sample_hourly["flow_direction_label"] == label]
                ax.plot(subset["timestamp_utc"], subset["quantity_maw"], label=label, color=color)
            ax.set_title("Hourly cleaned quantity around the boundary period")
            ax.set_ylabel("Quantity (MAW)")
            ax.set_xlabel("Timestamp UTC")
            ax.legend()
            plt.xticks(rotation=30, ha="right")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 8. Save the Cleaned Outputs

            The final step writes every cleaned artifact and diagnostic table to the dataset-specific cleaned folder.
            """
        ),
        code_cell(
            """
            metadata = cleaning.write_outputs(
                output_root=REPO_ROOT / "data" / "01_cleaned",
                points_long=points_long,
                blocks_long=blocks_long,
                quarterhour_long=quarterhour_long,
                quarterhour_wide=quarterhour_wide,
                hourly_long=hourly_long,
                hourly_wide=hourly_wide,
                file_summary=file_summary_df,
                parse_errors=parse_errors_df,
                points_summary=points_summary,
                period_diagnostics=period_diagnostics,
                blocks_summary=blocks_summary,
                quarterhour_summary=quarterhour_summary,
                hourly_summary=hourly_summary,
                gap_intervals=gap_intervals,
                gap_summary=gap_summary,
                duplicates_removed=duplicates_removed,
            )

            display(pd.DataFrame({"artifact": list(metadata.keys()), "path_or_value": [str(v) for v in metadata.values()]}))
            """
        ),
        markdown_cell(
            """
            ## 9. Interpretation

            The diagnostics show a clear cleaning story:

            - the raw XML is a sparse `curveType A03` change-point series
            - sparse points compress a much denser PT15M delivery grid
            - the 2024 file splits around `2024-10-27 00:30Z` and `2024-10-27 01:00Z`
            - that split leaves one uncovered 30-minute gap per direction on the canonical quarter-hour grid
            - the cleaning keeps that gap explicit instead of filling it silently
            - the hourly layer carries the gap forward as incomplete-hour missingness
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
    notebook["metadata"]["language_info"] = {"name": "python", "version": "3.x"}
    return notebook


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    notebook = build_notebook()
    with NOTEBOOK_PATH.open("w", encoding="utf-8") as handle:
        nbf.write(notebook, handle)
    print(f"Wrote notebook to {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
