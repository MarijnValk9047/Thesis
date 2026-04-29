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
    / "01_17_1_bc_nl_ir_cleaning_walkthrough.ipynb"
)


def markdown_cell(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code_cell(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


def build_notebook() -> nbf.NotebookNode:
    cells = [
        markdown_cell(
            """
            # 01 17.1 B&C NL Cleaning Walkthrough

            This notebook walks through the cleaning of ENTSO-E `17.1 B&C` for the NL control area:

            - starting from the raw zip archives in `data/00_Raw/ENTSOE/17_1_BC_NL_IR`
            - transforming the XML payloads into a readable native long table
            - running diagnostics on duplicates, time periods, granularities, and missingness
            - explaining the main anomaly in the 2025 raw files
            - cleaning the dataset step by step into hourly long and hourly wide outputs

            The main structural finding is important:

            - the raw files behave like **daily contracted reserve periods**
            - from 2025 onward the XML reports `resolution = PT15M`
            - but each direction still contains only **one point for the whole delivery day**

            So the notebook explicitly checks that inconsistency before applying the cleaning rule.
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
                module_path = repo_root / "scripts" / "Data" / "01_cleaning" / "balancing_reserves_under_contract_pipeline.py"
                spec = importlib.util.spec_from_file_location("balancing_reserves_cleaning_notebook", module_path)
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
            RAW_DIR = REPO_ROOT / "data" / "00_Raw" / "ENTSOE" / "17_1_BC_NL_IR"
            OUTPUT_DIR = REPO_ROOT / "data" / "01_cleaned" / "Balancing" / "IR Capacity" / "balancing_reserves_under_contract"
            PARSED_OUTPUT = OUTPUT_DIR / "parsed" / "balancing_reserves_under_contract_long.csv"
            HOURLY_LONG_OUTPUT = OUTPUT_DIR / "hourly" / "balancing_reserves_under_contract_hourly_long.csv"
            HOURLY_WIDE_OUTPUT = OUTPUT_DIR / "hourly" / "balancing_reserves_under_contract_hourly_wide.csv"
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
            ## 1. Raw Archive Inventory

            Before parsing any XML payload, inspect the archive structure. This tells us how many zip files exist, how many XML members sit inside each archive, and whether some files are clearly page splits rather than one-file-per-year snapshots.
            """
        ),
        code_cell(
            """
            archive_rows = []
            for archive_path in sorted(RAW_DIR.glob("*.zip")):
                with zipfile.ZipFile(archive_path) as zf:
                    xml_members = [name for name in zf.namelist() if name.lower().endswith(".xml")]
                archive_rows.append(
                    {
                        "archive": archive_path.name,
                        "size_kb": round(archive_path.stat().st_size / 1024, 1),
                        "xml_member_count": len(xml_members),
                    }
                )

            archive_inventory_df = pd.DataFrame(archive_rows)
            display(archive_inventory_df)

            fig, ax = plt.subplots(figsize=(14, 4))
            ax.bar(archive_inventory_df["archive"], archive_inventory_df["xml_member_count"], color="#4C78A8")
            ax.set_title("Raw zip archives and their XML member counts")
            ax.set_ylabel("XML members")
            ax.set_xlabel("Archive")
            plt.xticks(rotation=90)
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 2. Inspect One Raw XML Member

            The first useful cleaning step is to make the raw payload readable. We inspect one XML member directly so the document structure is visible before it gets flattened into tables.
            """
        ),
        code_cell(
            """
            sample_archive = sorted(RAW_DIR.glob("*.zip"))[-1]
            with zipfile.ZipFile(sample_archive) as zf:
                sample_member = sorted(name for name in zf.namelist() if name.lower().endswith(".xml"))[0]
                sample_xml_text = zf.read(sample_member).decode("utf-8", errors="replace")

            print("Archive:", sample_archive.name)
            print("Member:", sample_member)
            print()
            print("\\n".join(sample_xml_text.splitlines()[:40]))
            """
        ),
        markdown_cell(
            """
            ## 3. Parse the Raw Files Into a Readable Native Table

            The shared cleaning module parses every zip member and keeps the native contract intervals before any hourly expansion.
            """
        ),
        code_cell(
            """
            raw_parsed, member_summary_df, archive_summary_df, parse_errors_df = cleaning.parse_archives(RAW_DIR)

            print(f"Raw parsed rows: {len(raw_parsed):,}")
            print(f"Member summaries: {len(member_summary_df):,}")
            print(f"Archive summaries: {len(archive_summary_df):,}")
            print(f"Parse errors: {len(parse_errors_df):,}")

            if not parse_errors_df.empty:
                display(parse_errors_df.head())
            """
        ),
        code_cell(
            """
            readable_native = (
                raw_parsed[
                    [
                        "timestamp_utc",
                        "interval_end_utc",
                        "effective_interval_minutes",
                        "quantity_maw",
                        "procurement_price_eur",
                        "flow_direction_label",
                        "contract_type_label",
                        "reserve_source_label",
                        "price_category_label",
                        "reported_resolution",
                        "point_count_in_period",
                        "expected_point_count_from_reported_resolution",
                        "allocation_decision_datetime_utc",
                        "source_archive",
                        "source_member",
                    ]
                ]
                .sort_values(["timestamp_utc", "flow_direction_label"])
                .reset_index(drop=True)
            )

            display(readable_native.head(12))
            """
        ),
        markdown_cell(
            """
            ## 4. Interpret the Native Dataset

            These diagnostics answer the basic structural questions:

            - which codes occur
            - what time coverage we have
            - what interval durations exist
            - whether the source is really UTC
            """
        ),
        code_cell(
            """
            overview_df = pd.DataFrame(
                [
                    {"metric": "Rows", "value": len(raw_parsed)},
                    {"metric": "Min timestamp UTC", "value": raw_parsed["timestamp_utc"].min()},
                    {"metric": "Max interval end UTC", "value": raw_parsed["interval_end_utc"].max()},
                    {"metric": "Unique flow directions", "value": ", ".join(sorted(raw_parsed["flow_direction_label"].dropna().unique()))},
                    {"metric": "Unique contract types", "value": ", ".join(sorted(raw_parsed["contract_type_label"].dropna().unique()))},
                    {"metric": "Unique reserve sources", "value": ", ".join(sorted(raw_parsed["reserve_source_label"].dropna().unique()))},
                    {"metric": "Unique price categories", "value": ", ".join(sorted(raw_parsed["price_category_label"].dropna().unique()))},
                    {"metric": "Unique reported resolutions", "value": ", ".join(sorted(raw_parsed["reported_resolution"].dropna().unique()))},
                ]
            )
            display(overview_df)

            code_tables_df = pd.concat(
                [
                    pd.DataFrame(cleaning.FLOW_DIRECTION_LABELS.items(), columns=["code", "label"]).assign(code_family="flow_direction"),
                    pd.DataFrame(cleaning.CONTRACT_TYPE_LABELS.items(), columns=["code", "label"]).assign(code_family="contract_type"),
                    pd.DataFrame(cleaning.RESERVE_SOURCE_LABELS.items(), columns=["code", "label"]).assign(code_family="reserve_source"),
                    pd.DataFrame(cleaning.PRICE_CATEGORY_LABELS.items(), columns=["code", "label"]).assign(code_family="price_category"),
                ],
                ignore_index=True,
            )
            display(code_tables_df)
            """
        ),
        code_cell(
            """
            native_interval_hours = raw_parsed["effective_interval_minutes"] / 60.0
            native_interval_distribution = native_interval_hours.value_counts().sort_index()
            resolution_distribution = raw_parsed["reported_resolution"].value_counts().sort_index()
            point_count_distribution = (
                raw_parsed.groupby(["reported_resolution", "point_count_in_period", "expected_point_count_from_reported_resolution"])
                .size()
                .reset_index(name="rows")
                .sort_values(["reported_resolution", "point_count_in_period"])
            )

            display(point_count_distribution)

            fig, axes = plt.subplots(1, 3, figsize=(18, 4))
            resolution_distribution.plot(kind="bar", ax=axes[0], color="#4C78A8")
            axes[0].set_title("Reported resolution counts")
            axes[0].set_xlabel("Reported resolution")
            axes[0].set_ylabel("Rows")

            native_interval_distribution.plot(kind="bar", ax=axes[1], color="#F58518")
            axes[1].set_title("Effective interval duration in hours")
            axes[1].set_xlabel("Hours")
            axes[1].set_ylabel("Rows")

            point_count_distribution["label"] = (
                point_count_distribution["reported_resolution"].astype(str)
                + " | actual "
                + point_count_distribution["point_count_in_period"].astype(str)
                + " | expected "
                + point_count_distribution["expected_point_count_from_reported_resolution"].astype(str)
            )
            axes[2].bar(point_count_distribution["label"], point_count_distribution["rows"], color="#54A24B")
            axes[2].set_title("Actual versus expected point counts")
            axes[2].set_ylabel("Rows")
            axes[2].tick_params(axis="x", rotation=90)

            plt.tight_layout()
            plt.show()
            """
        ),
        code_cell(
            """
            known_at_by_year = (
                raw_parsed.assign(delivery_year=pd.to_datetime(raw_parsed["target_delivery_local_date"]).dt.year)
                .groupby("delivery_year", as_index=False)
                .agg(
                    rows=("timestamp_utc", "size"),
                    rows_with_known_at=("allocation_decision_datetime_utc", lambda s: int(s.notna().sum())),
                )
            )
            known_at_by_year["known_at_share"] = known_at_by_year["rows_with_known_at"] / known_at_by_year["rows"]
            display(known_at_by_year)

            fig, ax = plt.subplots(figsize=(10, 4))
            ax.bar(known_at_by_year["delivery_year"].astype(str), known_at_by_year["known_at_share"], color="#E45756")
            ax.set_title("Share of rows with allocation decision timestamps")
            ax.set_xlabel("Delivery year")
            ax.set_ylabel("Share with known_at")
            ax.set_ylim(0, 1.05)
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 5. Spot Duplicates, Missing Days, and Time-Period Issues

            The native daily contracts should yield one row per direction per delivery day. So we explicitly test:

            - duplicate native intervals
            - missing local delivery dates
            - DST-driven 23/24/25-hour day lengths
            """
        ),
        code_cell(
            """
            deduped_native, duplicates_removed = cleaning.deduplicate_rows(raw_parsed)

            duplicate_summary_df = pd.DataFrame(
                [
                    {"metric": "Raw rows", "value": len(raw_parsed)},
                    {"metric": "Rows after deduplication", "value": len(deduped_native)},
                    {"metric": "Duplicate rows removed", "value": len(duplicates_removed)},
                ]
            )
            display(duplicate_summary_df)
            display(duplicates_removed.head(10))
            """
        ),
        code_cell(
            """
            def native_delivery_grid_check(frame: pd.DataFrame) -> pd.DataFrame:
                rows = []
                for direction, group in frame.groupby("flow_direction_label"):
                    observed_dates = pd.to_datetime(group["target_delivery_local_date"]).sort_values().dt.date
                    expected_dates = pd.date_range(observed_dates.min(), observed_dates.max(), freq="D").date
                    missing_dates = sorted(set(expected_dates) - set(observed_dates))
                    rows.append(
                        {
                            "flow_direction": direction,
                            "observed_delivery_days": len(observed_dates),
                            "unique_delivery_days": observed_dates.nunique(),
                            "expected_delivery_days": len(expected_dates),
                            "missing_delivery_days": len(missing_dates),
                            "first_missing_delivery_days": ", ".join(str(value) for value in missing_dates[:10]),
                        }
                    )
                return pd.DataFrame(rows)


            native_grid_check_df = native_delivery_grid_check(deduped_native)
            display(native_grid_check_df)

            interval_hours_by_year = (
                deduped_native.assign(
                    delivery_year=pd.to_datetime(deduped_native["target_delivery_local_date"]).dt.year,
                    interval_hours=deduped_native["effective_interval_minutes"] / 60.0,
                )
                .groupby(["delivery_year", "interval_hours"], as_index=False)
                .size()
                .rename(columns={"size": "rows"})
            )
            display(interval_hours_by_year)

            pivot = interval_hours_by_year.pivot(index="delivery_year", columns="interval_hours", values="rows").fillna(0)
            ax = pivot.plot(kind="bar", figsize=(10, 4))
            ax.set_title("Native interval duration by delivery year")
            ax.set_xlabel("Delivery year")
            ax.set_ylabel("Rows")
            ax.legend(title="Hours")
            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 6. Investigate the 2025 `PT15M` Anomaly

            If the 2025 rows were truly 15-minute native observations, each full delivery day should usually contain around 96 points, with DST exceptions around 92 or 100. Instead, the raw files still publish only one point per direction for the whole period.
            """
        ),
        code_cell(
            """
            pt15m_rows = deduped_native[deduped_native["reported_resolution"] == "PT15M"].copy()
            pt15m_check_df = (
                pt15m_rows[
                    [
                        "timestamp_utc",
                        "interval_end_utc",
                        "flow_direction_label",
                        "reported_resolution",
                        "point_count_in_period",
                        "expected_point_count_from_reported_resolution",
                        "effective_interval_minutes",
                        "quantity_maw",
                        "procurement_price_eur",
                        "allocation_decision_datetime_utc",
                    ]
                ]
                .sort_values(["timestamp_utc", "flow_direction_label"])
                .reset_index(drop=True)
            )
            display(pt15m_check_df.head(12))

            pt15m_expected_counts = (
                pt15m_check_df["expected_point_count_from_reported_resolution"]
                .value_counts()
                .sort_index()
                .rename_axis("expected_points")
                .reset_index(name="rows")
            )
            display(pt15m_expected_counts)
            """
        ),
        code_cell(
            """
            fig, axes = plt.subplots(1, 2, figsize=(14, 4))

            axes[0].scatter(
                pt15m_rows["timestamp_utc"],
                pt15m_rows["point_count_in_period"],
                s=12,
                alpha=0.7,
                color="#4C78A8",
            )
            axes[0].set_title("Actual point count in 2025 PT15M rows")
            axes[0].set_xlabel("Timestamp UTC")
            axes[0].set_ylabel("Actual point count")

            axes[1].scatter(
                pt15m_rows["timestamp_utc"],
                pt15m_rows["expected_point_count_from_reported_resolution"],
                s=12,
                alpha=0.7,
                color="#E45756",
            )
            axes[1].set_title("Expected point count from the PT15M label")
            axes[1].set_xlabel("Timestamp UTC")
            axes[1].set_ylabel("Expected point count")

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 7. Cleaning Step 1: Deduplicate Boundary Overlaps

            The first cleaning action is small but necessary: some year-end periods appear in both the trailing page of one year and the first page of the next. We keep the latest record by creation time and source ordering.
            """
        ),
        code_cell(
            """
            deduped_native, duplicates_removed = cleaning.deduplicate_rows(raw_parsed)

            print(f"Rows before deduplication: {len(raw_parsed):,}")
            print(f"Rows after deduplication: {len(deduped_native):,}")
            print(f"Duplicates removed: {len(duplicates_removed):,}")

            display(
                deduped_native[
                    [
                        "timestamp_utc",
                        "interval_end_utc",
                        "flow_direction_label",
                        "quantity_maw",
                        "procurement_price_eur",
                        "reported_resolution",
                        "interval_interpretation",
                    ]
                ].head(10)
            )
            """
        ),
        markdown_cell(
            """
            ## 8. Cleaning Step 2: Expand Native Contract Periods to Hourly Rows

            The native table is still a contract-period table. To join it later with hourly forecasting inputs, we expand every native interval into hourly rows while preserving the same contract value within the covered period.
            """
        ),
        code_cell(
            """
            hourly_long = cleaning.aggregate_hourly(deduped_native)
            display(hourly_long.head(12))

            hourly_stage_summary = cleaning.summarize_hourly(hourly_long)
            display(hourly_stage_summary)
            """
        ),
        markdown_cell(
            """
            ## 9. Cleaning Step 3: Build an Hourly Wide Table

            The wide table is just a convenience layer for modelling and inspection. It keeps one UTC timestamp per row and exposes separate columns for up/down reserve quantities and procurement prices.
            """
        ),
        code_cell(
            """
            hourly_wide = cleaning.build_hourly_wide(hourly_long)
            display(hourly_wide.head(12))
            """
        ),
        markdown_cell(
            """
            ## 10. Diagnostics on the Cleaned Hourly Outputs

            Once the native intervals are expanded, the hourly outputs should be complete on the UTC grid and free of duplicate hours.
            """
        ),
        code_cell(
            """
            monthly_means = (
                hourly_long.assign(month=hourly_long["timestamp_utc"].dt.to_period("M").astype(str))
                .groupby(["month", "flow_direction_label"], as_index=False)
                .agg(
                    mean_quantity_maw=("quantity_maw", "mean"),
                    mean_procurement_price_eur=("procurement_price_eur", "mean"),
                )
            )
            display(monthly_means.head(12))

            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            for direction, group in monthly_means.groupby("flow_direction_label"):
                axes[0].plot(group["month"], group["mean_quantity_maw"], marker="o", linewidth=1.2, label=direction)
                axes[1].plot(group["month"], group["mean_procurement_price_eur"], marker="o", linewidth=1.2, label=direction)

            axes[0].set_title("Monthly mean contracted reserve quantity")
            axes[0].set_ylabel("MAW")
            axes[0].legend(title="Direction")

            axes[1].set_title("Monthly mean procurement price")
            axes[1].set_ylabel("EUR")
            axes[1].set_xlabel("Month")
            axes[1].legend(title="Direction")
            plt.xticks(rotation=90)
            plt.tight_layout()
            plt.show()
            """
        ),
        code_cell(
            """
            sample_start = pd.Timestamp("2025-01-01T00:00:00Z")
            sample_end = pd.Timestamp("2025-01-10T00:00:00Z")
            sample_hourly = hourly_long[
                (hourly_long["timestamp_utc"] >= sample_start) & (hourly_long["timestamp_utc"] < sample_end)
            ].copy()

            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            for direction, group in sample_hourly.groupby("flow_direction_label"):
                axes[0].plot(group["timestamp_utc"], group["quantity_maw"], linewidth=1.2, label=direction)
                axes[1].plot(group["timestamp_utc"], group["procurement_price_eur"], linewidth=1.2, label=direction)

            axes[0].set_title("Hourly quantity over a sample window")
            axes[0].set_ylabel("MAW")
            axes[0].legend(title="Direction")

            axes[1].set_title("Hourly procurement price over a sample window")
            axes[1].set_ylabel("EUR")
            axes[1].set_xlabel("Timestamp UTC")
            axes[1].legend(title="Direction")

            plt.tight_layout()
            plt.show()
            """
        ),
        markdown_cell(
            """
            ## 11. Saved Outputs and Diagnostics

            The standalone cleaner saves the cleaned artifacts under `data/01_cleaned/Balancing/balancing_reserves_under_contract`.
            """
        ),
        code_cell(
            """
            artifact_df = pd.DataFrame(
                [
                    {"artifact": "Parsed long", "path": str(PARSED_OUTPUT), "exists": PARSED_OUTPUT.exists()},
                    {"artifact": "Hourly long", "path": str(HOURLY_LONG_OUTPUT), "exists": HOURLY_LONG_OUTPUT.exists()},
                    {"artifact": "Hourly wide", "path": str(HOURLY_WIDE_OUTPUT), "exists": HOURLY_WIDE_OUTPUT.exists()},
                    {"artifact": "Diagnostics directory", "path": str(DIAGNOSTICS_DIR), "exists": DIAGNOSTICS_DIR.exists()},
                ]
            )
            display(artifact_df)
            """
        ),
        markdown_cell(
            """
            ## 12. What To Take Away

            The diagnostics support the following interpretation:

            - this is a **contracted reserve** dataset, not an activated-energy dataset
            - the native observation level is effectively **one full contract period per direction**
            - the contract periods are daily in practice, with local-DST effects causing 23/24/25-hour UTC spans
            - year-end archive paging introduces a few duplicate overlaps, which should be removed upstream
            - the 2025 `PT15M` label is not enough to justify quarter-hourly modelling because the payload still contains only one full-period point per direction

            So the cleaned hourly outputs are best understood as an hourly convenience expansion of daily contract data, not as truly native hourly or quarter-hourly reserve procurement observations.
            """
        ),
    ]

    notebook = nbf.v4.new_notebook()
    notebook["cells"] = cells
    notebook["metadata"] = {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.12",
        },
    }
    return notebook


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    notebook = build_notebook()
    nbf.write(notebook, NOTEBOOK_PATH)
    print(f"Wrote notebook to {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
