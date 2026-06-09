from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / "notebooks"
    / "Data"
    / "01_Cleaning"
    / "IR Capacity"
    / "02_12_3_f_nl_ir_cleaning_walkthrough.ipynb"
)


def markdown_cell(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code_cell(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


def build_notebook() -> nbf.NotebookNode:
    cells = [
        markdown_cell(
            """
            # 03 12.3 F NL IR Cleaning Walkthrough

            This notebook walks through the cleaning of ENTSO-E `12.3 F NL IR` step by step:

            - starting from the raw paginated zip/XML files in `data/00_Raw/ENTSOE/12_3_F_NL_IR`
            - transforming the XML payload into a readable native offer table
            - diagnosing pagination, full-period rows, ambiguous duplicates, and delivery coverage
            - building cleaned offer-stack features
            - aggregating offers into daily direction summaries
            - expanding those summaries to hourly outputs for a consistent time axis

            The key structural finding here is different from both `17.1 B&C` and `12.3 E A61`:

            - this dataset contains **many offer rows per delivery day**
            - the raw API export is paginated in 100-row chunks
            - each offer row is still a **one-point full-period daily record**

            So the cleaning keeps the native offer rows intact and then builds comparable aggregated totals on top.
            """
        ),
        code_cell(
            """
            from __future__ import annotations

            import importlib.util
            import json
            import sys
            import zipfile
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
                module_path = repo_root / "scripts" / "Data" / "01_cleaning" / "procured_balancing_capacity_pipeline.py"
                spec = importlib.util.spec_from_file_location("procured_balancing_capacity_cleaning_notebook", module_path)
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
            RAW_DIR = REPO_ROOT / "data" / "00_Raw" / "ENTSOE" / "12_3_F_NL_IR"
            OUTPUT_DIR = REPO_ROOT / "data" / "01_cleaned" / "02_Balancing_mFRR_IR" / "IR Capacity" / "12_3_f_nl_ir"
            DIAGNOSTICS_DIR = OUTPUT_DIR / "diagnostics"

            config_df = pd.DataFrame(
                [
                    {"setting": "Raw input directory", "value": str(RAW_DIR)},
                    {"setting": "Cleaned output directory", "value": str(OUTPUT_DIR)},
                    {"setting": "Market", "value": cleaning.MARKET},
                    {"setting": "Reporting timezone", "value": cleaning.MARKET_TIMEZONE},
                    {"setting": "Known-at rule", "value": cleaning.KNOWN_AT_RULE},
                ]
            )
            display(config_df)
            """
        ),
        markdown_cell(
            """
            ## 1. Raw Zip Inventory

            Start with the archive inventory. Because this export is paginated, the zip-level view is part of the diagnosis rather than just a file check.
            """
        ),
        code_cell(
            """
            inventory_rows = []
            for archive_path in sorted(RAW_DIR.glob("*.zip")):
                with zipfile.ZipFile(archive_path) as zf:
                    xml_members = [name for name in zf.namelist() if name.lower().endswith(".xml")]
                inventory_rows.append(
                    {
                        "archive": archive_path.name,
                        "offset": cleaning.parse_archive_offset(archive_path.name),
                        "size_kb": round(archive_path.stat().st_size / 1024, 1),
                        "xml_member_count": len(xml_members),
                    }
                )

            inventory_df = pd.DataFrame(inventory_rows).sort_values("offset").reset_index(drop=True)
            display(inventory_df.head(20))

            fig, ax = plt.subplots(figsize=(14, 4))
            ax.plot(inventory_df["offset"], inventory_df["size_kb"], marker="o", color="#4C78A8")
            ax.set_title("Raw zip sizes by archive offset")
            ax.set_xlabel("Offset")
            ax.set_ylabel("Size (KB)")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 2. Inspect One Raw XML Member

            Read one XML member directly to make the document structure visible before flattening it into tables.
            """
        ),
        code_cell(
            """
            sample_archive = sorted(RAW_DIR.glob("*.zip"))[0]
            with zipfile.ZipFile(sample_archive) as zf:
                sample_member = sorted(name for name in zf.namelist() if name.lower().endswith(".xml"))[0]
                sample_xml_text = zf.read(sample_member).decode("utf-8", errors="replace")

            print("Archive:", sample_archive.name)
            print("Member:", sample_member)
            print()
            print("\\n".join(sample_xml_text.splitlines()[:50]))
            """
        ),
        markdown_cell(
            """
            ## 3. Parse the Raw Files Into a Readable Offer Table

            The first cleaned table keeps one row per native offer row from the XML.
            """
        ),
        code_cell(
            """
            offers_raw, archive_summary_df, parse_errors_df = cleaning.parse_archives(RAW_DIR)

            print(f"Offer rows parsed: {len(offers_raw):,}")
            print(f"Archive summaries: {len(archive_summary_df):,}")
            print(f"Parse errors: {len(parse_errors_df):,}")

            display(archive_summary_df.head(20))
            if not parse_errors_df.empty:
                display(parse_errors_df)
            """
        ),
        code_cell(
            """
            readable_offers = (
                offers_raw[
                    [
                        "source_archive",
                        "source_archive_offset",
                        "timestamp_utc",
                        "interval_end_utc",
                        "flow_direction_label",
                        "quantity_maw",
                        "procurement_price_eur_per_maw",
                        "interval_interpretation",
                        "timeseries_mrid",
                    ]
                ]
                .sort_values(["timestamp_utc", "flow_direction_label", "procurement_price_eur_per_maw", "quantity_maw"])
                .reset_index(drop=True)
            )
            display(readable_offers.head(20))
            """
        ),
        markdown_cell(
            """
            ## 4. Diagnose Structure, Pagination, and Identity

            The key structural questions are:

            - how many delivery periods appear
            - how many offers land in each delivery period
            - whether rows are full-period records
            - whether `timeseries mRID` is a stable identifier across pages
            """
        ),
        code_cell(
            """
            offers_long = cleaning.build_offer_stack(offers_raw)
            offers_summary_df = cleaning.summarize_offers(offers_long)
            ambiguous_duplicates_df = cleaning.build_ambiguous_duplicate_content_summary(offers_long)
            mrid_reuse_df = cleaning.build_timeseries_mrid_reuse_summary(offers_long)

            overview_df = pd.DataFrame(
                [
                    {"metric": "Offer rows", "value": len(offers_long)},
                    {"metric": "Unique delivery periods", "value": offers_long[["timestamp_utc", "interval_end_utc"]].drop_duplicates().shape[0]},
                    {"metric": "Min timestamp UTC", "value": offers_long["timestamp_utc"].min()},
                    {"metric": "Max interval end UTC", "value": offers_long["interval_end_utc"].max()},
                    {"metric": "Unique archive offsets", "value": offers_long["source_archive_offset"].nunique()},
                    {"metric": "Ambiguous duplicate-content groups", "value": len(ambiguous_duplicates_df)},
                ]
            )
            display(overview_df)
            display(offers_summary_df)
            display(mrid_reuse_df.head(20))
            """
        ),
        code_cell(
            """
            offers_per_period = (
                offers_long.groupby(["timestamp_utc", "interval_end_utc", "flow_direction_label"], as_index=False)
                .agg(offers=("native_offer_id", "size"), total_quantity_maw=("quantity_maw", "sum"))
            )

            fig, axes = plt.subplots(1, 2, figsize=(16, 4))

            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = offers_per_period[offers_per_period["flow_direction_label"] == label]
                axes[0].plot(subset["timestamp_utc"], subset["offers"], marker="o", label=label, color=color)
                axes[1].plot(subset["timestamp_utc"], subset["total_quantity_maw"], marker="o", label=label, color=color)

            axes[0].set_title("Offer count per delivery period")
            axes[0].set_ylabel("Offers")
            axes[0].set_xlabel("Delivery start UTC")
            axes[0].legend()

            axes[1].set_title("Total quantity per delivery period")
            axes[1].set_ylabel("MAW")
            axes[1].set_xlabel("Delivery start UTC")
            axes[1].legend()

            for ax in axes:
                ax.tick_params(axis="x", rotation=30)

            plt.tight_layout()
            plt.show()
            """
        ),
        code_cell(
            """
            display(ambiguous_duplicates_df.head(30))

            code_tables_df = pd.concat(
                [
                    pd.DataFrame(cleaning.DOCUMENT_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="document_type"),
                    pd.DataFrame(cleaning.PROCESS_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="process_type"),
                    pd.DataFrame(cleaning.BUSINESS_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="business_type"),
                    pd.DataFrame(cleaning.CONTRACT_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="contract_type"),
                    pd.DataFrame(cleaning.RESERVE_SOURCE_LABELS.items(), columns=["code", "label"]).assign(code_family="reserve_source"),
                    pd.DataFrame(cleaning.FLOW_DIRECTION_LABELS.items(), columns=["code", "label"]).assign(code_family="flow_direction"),
                ],
                ignore_index=True,
            )
            display(code_tables_df)
            """
        ),
        markdown_cell(
            """
            ## 5. Cleaning Step 1: Build the Offer Stack

            The cleaned native table keeps every offer row and adds stack features:

            - offer rank by ascending procurement price
            - cumulative quantity within delivery period and direction
            - quantity shares within the day-direction stack
            """
        ),
        code_cell(
            """
            display(
                offers_long[
                    [
                        "timestamp_utc",
                        "flow_direction_label",
                        "offer_rank_price_asc",
                        "quantity_maw",
                        "procurement_price_eur_per_maw",
                        "cumulative_quantity_maw",
                        "cumulative_quantity_share",
                    ]
                ].head(30)
            )
            """
        ),
        code_cell(
            """
            sample_period = (
                offers_long.groupby(["timestamp_utc", "flow_direction_label"], as_index=False)
                .agg(offers=("native_offer_id", "size"))
                .sort_values("offers", ascending=False)
                .iloc[0]["timestamp_utc"]
            )

            sample_stack = offers_long[offers_long["timestamp_utc"] == sample_period].copy()

            fig, ax = plt.subplots(figsize=(12, 5))
            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = sample_stack[sample_stack["flow_direction_label"] == label].sort_values("offer_rank_price_asc")
                ax.step(subset["cumulative_quantity_maw"], subset["procurement_price_eur_per_maw"], where="post", label=label, color=color)
            ax.set_title(f"Offer stack on {sample_period}")
            ax.set_xlabel("Cumulative quantity (MAW)")
            ax.set_ylabel("Procurement price (EUR/MAW)")
            ax.legend()
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 6. Cleaning Step 2: Aggregate to Daily Direction Summaries

            The native offers are then aggregated into comparable day-direction totals:

            - offer count
            - total quantity
            - quantity-weighted procurement price
            - price distribution summaries
            """
        ),
        code_cell(
            """
            daily_long = cleaning.build_daily_direction_summary(offers_long)
            daily_wide = cleaning.build_daily_direction_wide(daily_long)
            daily_summary_df = cleaning.summarize_daily(daily_long)

            print(f"Daily summary rows: {len(daily_long):,}")
            display(daily_summary_df)
            display(daily_long.head(20))
            display(daily_wide.head(12))
            """
        ),
        code_cell(
            """
            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = daily_long[daily_long["flow_direction_label"] == label]
                axes[0].plot(subset["timestamp_utc"], subset["total_quantity_maw"], marker="o", label=label, color=color)
                axes[1].plot(subset["timestamp_utc"], subset["quantity_weighted_price_eur_per_maw"], marker="o", label=label, color=color)

            axes[0].set_title("Daily total procured quantity")
            axes[0].set_ylabel("MAW")
            axes[0].legend()

            axes[1].set_title("Daily quantity-weighted procurement price")
            axes[1].set_ylabel("EUR/MAW")
            axes[1].set_xlabel("Delivery start UTC")
            axes[1].legend()
            axes[1].tick_params(axis="x", rotation=30)

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 7. Cleaning Step 3: Expand Aggregated Totals to Hourly

            The raw offers are daily full-period records, so the hourly layer is an expansion of the aggregated daily totals over the covered UTC hours.
            """
        ),
        code_cell(
            """
            hourly_long = cleaning.build_hourly_direction_summary(daily_long)
            hourly_wide = cleaning.build_hourly_direction_wide(hourly_long)
            hourly_summary_df = cleaning.summarize_hourly(hourly_long)

            print(f"Hourly summary rows: {len(hourly_long):,}")
            display(hourly_summary_df)
            display(hourly_long.head(20))
            display(hourly_wide.head(12))
            """
        ),
        code_cell(
            """
            sample_hourly = hourly_long[
                (hourly_long["timestamp_utc"] >= hourly_long["timestamp_utc"].min())
                & (hourly_long["timestamp_utc"] < hourly_long["timestamp_utc"].min() + pd.Timedelta(days=7))
            ]

            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            for label, color in [("Up", "#E45756"), ("Down", "#4C78A8")]:
                subset = sample_hourly[sample_hourly["flow_direction_label"] == label]
                axes[0].plot(subset["timestamp_utc"], subset["total_quantity_maw"], label=label, color=color)
                axes[1].plot(subset["timestamp_utc"], subset["quantity_weighted_price_eur_per_maw"], label=label, color=color)

            axes[0].set_title("Hourly-expanded quantity over the first week")
            axes[0].set_ylabel("MAW")
            axes[0].legend()

            axes[1].set_title("Hourly-expanded weighted price over the first week")
            axes[1].set_ylabel("EUR/MAW")
            axes[1].set_xlabel("Timestamp UTC")
            axes[1].legend()
            axes[1].tick_params(axis="x", rotation=30)

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 8. Save the Cleaned Outputs

            The final step writes the cleaned offer table, aggregated daily/hourly outputs, and diagnostics to the `IR Capacity` dataset folder.
            """
        ),
        code_cell(
            """
            metadata = cleaning.write_outputs(
                output_root=REPO_ROOT / "data" / "01_cleaned",
                offers_long=offers_long,
                daily_long=daily_long,
                daily_wide=daily_wide,
                hourly_long=hourly_long,
                hourly_wide=hourly_wide,
                archive_summary=archive_summary_df,
                parse_errors=parse_errors_df,
                offers_summary=offers_summary_df,
                daily_summary=daily_summary_df,
                hourly_summary=hourly_summary_df,
                ambiguous_duplicate_content=ambiguous_duplicates_df,
                timeseries_mrid_reuse=mrid_reuse_df,
            )

            display(pd.DataFrame({"artifact": list(metadata.keys()), "path_or_value": [str(v) for v in metadata.values()]}))
            """
        ),
        markdown_cell(
            """
            ## 9. Interpretation

            The diagnostics point to a clear cleaning stance:

            - `12.3 F` is a paginated offer-level export, not a one-row total series
            - native rows are daily full-period offers with quantity and procurement price
            - `timeseries mRID` resets by page and cannot be treated as a global identifier
            - identical quantity-price tuples occur often, so apparent duplicate-looking rows are retained
            - the safe aggregation step is therefore offer-level preservation first, day-direction totals second
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
