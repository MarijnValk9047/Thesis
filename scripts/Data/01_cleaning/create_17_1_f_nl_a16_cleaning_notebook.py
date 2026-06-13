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
    / "03_17_1_f_nl_a16_realised_cleaning_walkthrough.ipynb"
)


def markdown_cell(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code_cell(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


def build_notebook() -> nbf.NotebookNode:
    cells = [
        markdown_cell(
            """
            # 03 17.1.F NL A16 Realised Cleaning Walkthrough

            This notebook walks through the cleaning of ENTSO-E `17.1.F NL A16 (Realised)` step by step:

            - inspect the raw XML exports
            - parse them into a readable native points table
            - diagnose duplicates, sparse positions, gaps, time coverage, and granularity
            - derive variable-duration blocks from the change-point structure
            - expand those blocks to a canonical quarter-hour UTC table
            - aggregate to conservative hourly outputs

            The key structural conclusion is:

            - this is a sparse `curveType = A03` price series
            - points are **change points**, not already-clean quarter-hour rows
            - most of the timeline is continuous after block expansion
            - a small number of real raw-data gaps remain and are kept explicit
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
                module_path = repo_root / "scripts" / "Data" / "01_cleaning" / "activated_balancing_energy_nl_a16_pipeline.py"
                spec = importlib.util.spec_from_file_location("activated_balancing_energy_nl_a16_notebook", module_path)
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
            RAW_DIR = REPO_ROOT / "data" / "00_Raw" / "ENTSOE" / "17.1 F - Prices of activated balancing energy" / "NL" / "A16 (Realised)"
            OUTPUT_DIR = REPO_ROOT / "data" / "01_cleaned" / "02_Balancing_mFRR_IR" / "IR Energy" / "17_1_f_nl_a16_realised"
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
            config_df
            """
        ),
        markdown_cell(
            """
            ## 1. Raw XML Inventory

            Start with the file inventory. This confirms the chunked yearly export structure before we touch any parsing logic.
            """
        ),
        code_cell(
            """
            inventory_rows = []
            for file_path in sorted(RAW_DIR.glob("*.xml")):
                inventory_rows.append(
                    {
                        "file": file_path.name,
                        "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
                    }
                )

            inventory_df = pd.DataFrame(inventory_rows)
            inventory_df
            """
        ),
        code_cell(
            """
            fig, ax = plt.subplots(figsize=(12, 4))
            ax.bar(inventory_df["file"], inventory_df["size_mb"], color="#4C78A8")
            ax.set_title("NL A16 raw XML file sizes")
            ax.set_ylabel("MB")
            ax.set_xlabel("Raw file")
            plt.xticks(rotation=75, ha="right")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 2. Inspect One Raw XML Snippet

            Read the first lines of a raw XML file directly. This makes the payload structure visible:

            - `type = A84`
            - `process = A16`
            - one `TimeSeries` per direction
            - sparse `Point` positions with `activation_Price.amount`
            """
        ),
        code_cell(
            """
            sample_path = sorted(RAW_DIR.glob("*.xml"))[0]
            sample_text = sample_path.read_text(encoding="utf-8", errors="replace")

            print("File:", sample_path.name)
            print()
            print("\\n".join(sample_text.splitlines()[:70]))
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
                        "source_file",
                        "flow_direction_label",
                        "series_period_start_utc",
                        "series_period_end_utc",
                        "reported_resolution",
                        "point_position",
                        "point_timestamp_utc",
                        "activation_price_eur_per_mwh",
                        "imbalance_price_category_code",
                    ]
                ]
                .sort_values(["point_timestamp_utc", "flow_direction_label", "point_position"])
                .reset_index(drop=True)
            )
            readable_points.head(20)
            """
        ),
        markdown_cell(
            """
            ## 4. Diagnose Structure, Duplicates, and Period Compression
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
                    {"metric": "Unique directions", "value": ", ".join(sorted(points_long["flow_direction_label"].dropna().unique()))},
                    {"metric": "Unique resolutions", "value": ", ".join(sorted(points_long["reported_resolution"].dropna().unique()))},
                    {"metric": "Unique imbalance price categories", "value": ", ".join(sorted(points_long["imbalance_price_category_code"].dropna().unique()))},
                    {"metric": "Min point timestamp UTC", "value": points_long["point_timestamp_utc"].min()},
                    {"metric": "Max point timestamp UTC", "value": points_long["point_timestamp_utc"].max()},
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
            fig, axes = plt.subplots(1, 2, figsize=(12, 4))

            axes[0].hist(period_diagnostics["point_count"], bins=20, color="#59A14F", edgecolor="white")
            axes[0].set_title("Native point count per Period")
            axes[0].set_xlabel("Point count")
            axes[0].set_ylabel("Number of Periods")

            axes[1].scatter(
                period_diagnostics["expected_dense_point_count"],
                period_diagnostics["point_count"],
                s=35,
                alpha=0.8,
                color="#E15759",
            )
            axes[1].set_title("Sparse Periods vs dense PT15M grid")
            axes[1].set_xlabel("Expected dense point count")
            axes[1].set_ylabel("Observed sparse point count")

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 5. Turn Change Points Into Blocks

            Each point becomes the start of a block. The block ends at the next point or at the end of the Period.
            """
        ),
        code_cell(
            """
            blocks_long = cleaning.build_blocks(points_long)
            blocks_summary = cleaning.summarize_blocks(blocks_long)

            print(f"Block rows: {len(blocks_long):,}")
            blocks_long.head(20)
            """
        ),
        code_cell(
            """
            blocks_summary
            """
        ),
        code_cell(
            """
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.hist(blocks_long["block_duration_minutes"], bins=40, color="#F28E2B", edgecolor="white")
            ax.set_title("NL A16 block duration distribution")
            ax.set_xlabel("Block duration (minutes)")
            ax.set_ylabel("Block count")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 6. Expand Blocks to Canonical Quarter-Hour Rows and Inspect Gaps
            """
        ),
        code_cell(
            """
            quarterhour_long = cleaning.expand_blocks_to_quarterhour(blocks_long)
            quarterhour_wide = cleaning.build_quarterhour_wide(quarterhour_long)
            quarterhour_summary = cleaning.summarize_quarterhour(quarterhour_long)
            gap_intervals, gap_summary = cleaning.find_gap_intervals(quarterhour_long)

            print(f"Quarter-hour rows: {len(quarterhour_long):,}")
            quarterhour_summary
            """
        ),
        code_cell(
            """
            gap_summary
            """
        ),
        code_cell(
            """
            if not gap_summary.empty:
                gap_plot = gap_summary.copy()
                gap_plot["gap_hours"] = gap_plot["missing_quarterhours"] * 0.25

                fig, ax = plt.subplots(figsize=(10, 4))
                ax.bar(gap_plot["gap_start_utc"].astype(str), gap_plot["gap_hours"], color="#B07AA1")
                ax.set_title("Explicit raw-data gaps after quarter-hour expansion")
                ax.set_xlabel("Gap start UTC")
                ax.set_ylabel("Gap length (hours)")
                plt.xticks(rotation=45, ha="right")
                plt.tight_layout()
                plt.show()
            else:
                print("No quarter-hour gaps detected.")
            """
        ),
        markdown_cell(
            """
            ## 7. Visualise an Objective High-Volatility Week

            Pick the week with the highest 7-day rolling mean of daily quarter-hour price standard deviation. This avoids hand-picking a plot.
            """
        ),
        code_cell(
            """
            qh_plot = quarterhour_long.copy()
            qh_plot["local_date"] = qh_plot["timestamp_utc"].dt.tz_convert(cleaning.MARKET_TIMEZONE).dt.date
            daily_std = (
                qh_plot.groupby(["local_date", "flow_direction_label"], as_index=False)
                .agg(daily_std=("activation_price_eur_per_mwh", "std"))
            )
            daily_score = (
                daily_std.groupby("local_date", as_index=False)
                .agg(score=("daily_std", "mean"))
                .sort_values("local_date")
            )
            daily_score["rolling_score"] = daily_score["score"].rolling(7, min_periods=3).mean()
            sample_week_start = pd.to_datetime(daily_score.loc[daily_score["rolling_score"].idxmax(), "local_date"])
            sample_week_end = sample_week_start + pd.Timedelta(days=7)

            print("Selected local week start:", sample_week_start.date())
            print("Selected local week end:", sample_week_end.date())
            """
        ),
        code_cell(
            """
            week_view = qh_plot[
                (qh_plot["timestamp_utc"].dt.tz_convert(cleaning.MARKET_TIMEZONE) >= sample_week_start.tz_localize(cleaning.MARKET_TIMEZONE))
                & (qh_plot["timestamp_utc"].dt.tz_convert(cleaning.MARKET_TIMEZONE) < sample_week_end.tz_localize(cleaning.MARKET_TIMEZONE))
            ].copy()

            fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
            for ax, direction in zip(axes, ["Up", "Down"]):
                sub = week_view.loc[week_view["flow_direction_label"] == direction]
                ax.plot(sub["timestamp_utc"], sub["activation_price_eur_per_mwh"], linewidth=1.0, color="#4E79A7" if direction == "Up" else "#E15759")
                ax.set_title(f"{direction} quarter-hour activation price during the selected week")
                ax.set_ylabel("EUR/MWh")
            axes[-1].set_xlabel("Timestamp UTC")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 8. Aggregate to Hourly and Keep Incomplete Hours Explicit
            """
        ),
        code_cell(
            """
            hourly_long = cleaning.aggregate_hourly(quarterhour_long)
            hourly_wide = cleaning.build_hourly_wide(hourly_long)
            hourly_summary = cleaning.summarize_hourly(hourly_long)

            print(f"Hourly rows: {len(hourly_long):,}")
            hourly_summary
            """
        ),
        code_cell(
            """
            incomplete_hours = hourly_long.loc[~hourly_long["is_complete_hour"]].copy()
            incomplete_hours.head(20)
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
                quarterhour_long=quarterhour_long,
                quarterhour_wide=quarterhour_wide,
                hourly_long=hourly_long,
                hourly_wide=hourly_wide,
                points_summary=points_summary,
                blocks_summary=blocks_summary,
                quarterhour_summary=quarterhour_summary,
                hourly_summary=hourly_summary,
                gap_intervals=gap_intervals,
                gap_summary=gap_summary,
            )

            saved_files = sorted(str(path.relative_to(OUTPUT_DIR)) for path in OUTPUT_DIR.rglob("*") if path.is_file())
            pd.DataFrame({"saved_file": saved_files}).head(50)
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
