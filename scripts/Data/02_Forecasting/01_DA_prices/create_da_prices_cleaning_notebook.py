from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


NOTEBOOK_PATH = (
    Path(__file__).resolve().parents[4]
    / "notebooks"
    / "Data"
    / "02_Forecasting"
    / "01_DA_prices"
    / "01_da_prices_cleaning_walkthrough.ipynb"
)


def markdown_cell(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code_cell(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


def build_notebook() -> nbf.NotebookNode:
    cells = [
        markdown_cell(
            """
            # 01 DA Prices Cleaning Walkthrough

            This notebook follows the shared DA prices cleaning pipeline in `scripts/Data/01_cleaning/day_ahead_prices_pipeline.py`.

            It shows:

            - how the raw XML files are parsed
            - the main intermediate cleaning stages
            - the upstream missing-datapoint fix
            - the final cleaned hourly and quarter-hourly outputs

            This is the upstream cleaning stage for the forecasting notebooks:

            - raw missing-datapoint handling belongs here
            - later forecasting notebooks treat the cleaned target series as fixed
            - if a later notebook builds a causal helper series, that is only for leakage-safe feature construction and does **not** overwrite the cleaned target

            The active rule is:

            - interpolate only real missing datapoints on the canonical UTC grid
            - do not treat DST as a missing-data problem, because the source timestamps are already UTC
            - if more than two consecutive datapoints are missing, flag them and leave them missing
            """
        ),
        code_cell(
            """
            from __future__ import annotations

            import importlib.util
            import sys
            from pathlib import Path
            from typing import Any

            import pandas as pd
            from IPython import get_ipython
            from IPython.display import Markdown, display

            ip = get_ipython()
            if ip is not None:
                ip.run_line_magic("matplotlib", "inline")

            import matplotlib.pyplot as plt

            pd.set_option("display.max_columns", 200)
            pd.set_option("display.width", 200)
            plt.style.use("seaborn-v0_8-whitegrid")


            def find_repo_root(start: Path | None = None) -> Path:
                start = start or Path.cwd()
                for candidate in [start, *start.parents]:
                    if (candidate / "AGENTS.md").exists() and (candidate / "scripts").exists():
                        return candidate
                raise FileNotFoundError("Could not locate the repository root from the current notebook directory.")


            REPO_ROOT = find_repo_root()


            def load_cleaning_module():
                module_path = REPO_ROOT / "scripts" / "Data" / "01_cleaning" / "day_ahead_prices_pipeline.py"
                spec = importlib.util.spec_from_file_location("day_ahead_prices_pipeline_notebook", module_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                return module


            cleaning = load_cleaning_module()
            """
        ),
        code_cell(
            """
            REGIONS = ["BE", "DE", "NL"]
            FOCUS_REGION = "NL"
            MARKET_TIMEZONES = {
                "BE": "Europe/Brussels",
                "DE": "Europe/Berlin",
                "NL": "Europe/Amsterdam",
            }

            RAW_ROOT = REPO_ROOT / "data" / "00_Raw" / "DA_Prices"
            OUTPUT_ROOT = REPO_ROOT / "data" / "01_cleaned" / "Day_ahead_prices"
            CUTOFF_LOCAL_DATE = "2025-10-01"
            LOCAL_TIMEZONE = "Europe/Brussels"
            MAX_TIMESTAMP_UTC = pd.Timestamp("2026-01-01T00:00:00Z")

            CUTOFF_LOCAL = pd.Timestamp(CUTOFF_LOCAL_DATE).tz_localize(LOCAL_TIMEZONE)
            CUTOFF_UTC = CUTOFF_LOCAL.tz_convert("UTC")

            config_df = pd.DataFrame(
                [
                    {"setting": "Raw root", "value": str(RAW_ROOT)},
                    {"setting": "Output root", "value": str(OUTPUT_ROOT)},
                    {"setting": "Regions", "value": ", ".join(REGIONS)},
                    {"setting": "Focus region", "value": FOCUS_REGION},
                    {"setting": "Cutoff local date", "value": CUTOFF_LOCAL_DATE},
                    {"setting": "Cutoff UTC", "value": CUTOFF_UTC.isoformat()},
                    {"setting": "Max timestamp UTC", "value": MAX_TIMESTAMP_UTC.isoformat()},
                ]
            )
            display(config_df)
            """
        ),
        markdown_cell(
            """
            ## Notebook Helpers

            These helpers intentionally reuse the same parsing, deduplication, clipping, and missing-datapoint interpolation logic as the shared cleaning script.
            """
        ),
        code_cell(
            """
            def build_region_result(region: str) -> dict[str, Any]:
                xml_files = sorted((RAW_ROOT / f"DA_prices_{region}").rglob("*.xml"))
                rows: list[dict[str, Any]] = []
                file_summaries: list[dict[str, Any]] = []
                parse_errors: list[dict[str, Any]] = []

                for xml_file in xml_files:
                    try:
                        file_rows, file_summary = cleaning.parse_single_xml(region, xml_file)
                    except Exception as exc:  # noqa: BLE001
                        parse_errors.append(
                            {
                                "region": region,
                                "source_path": str(xml_file),
                                "error": str(exc),
                            }
                        )
                        continue
                    rows.extend(file_rows)
                    file_summaries.append(file_summary)

                df_raw = cleaning.make_region_dataframe(rows)
                df_after_sequence_filter = df_raw.copy()
                sequence_2_rows_removed = 0
                if region == "DE" and not df_after_sequence_filter.empty:
                    mask_seq2 = df_after_sequence_filter["timeseries_sequence_position"] == 2
                    sequence_2_rows_removed = int(mask_seq2.sum())
                    df_after_sequence_filter = df_after_sequence_filter[~mask_seq2].copy()

                df_after_dedup_clip, duplicate_rows_removed = cleaning.split_duplicate_stats(df_after_sequence_filter)
                df_after_dedup_clip = cleaning.clip_to_max_timestamp(
                    df_after_dedup_clip,
                    max_timestamp_utc=MAX_TIMESTAMP_UTC,
                )

                pre_cutoff = df_after_dedup_clip[df_after_dedup_clip["timestamp_utc"] < CUTOFF_UTC].copy()
                post_cutoff = df_after_dedup_clip[df_after_dedup_clip["timestamp_utc"] >= CUTOFF_UTC].copy()

                hourly_before_fix = pre_cutoff[pre_cutoff["resolution_minutes"] == 60].copy()
                quarterly_before_fix = post_cutoff[post_cutoff["resolution_minutes"] == 15].copy()

                timezone = MARKET_TIMEZONES.get(region, LOCAL_TIMEZONE)
                hourly_fix = cleaning.apply_missing_datapoint_fix(
                    hourly_before_fix,
                    expected_minutes=60,
                    dataset="hourly",
                    local_timezone=timezone,
                )
                quarterly_fix = cleaning.apply_missing_datapoint_fix(
                    quarterly_before_fix,
                    expected_minutes=15,
                    dataset="quarterly",
                    local_timezone=timezone,
                )

                other_rows = df_after_dedup_clip.copy()
                hourly_scope_mask = (other_rows["timestamp_utc"] < CUTOFF_UTC) & (other_rows["resolution_minutes"] == 60)
                quarterly_scope_mask = (other_rows["timestamp_utc"] >= CUTOFF_UTC) & (other_rows["resolution_minutes"] == 15)
                other_rows = other_rows[~hourly_scope_mask & ~quarterly_scope_mask].copy()

                final_frames = [frame for frame in [other_rows, hourly_fix.cleaned_frame, quarterly_fix.cleaned_frame] if not frame.empty]
                final_aggregated = (
                    pd.concat(final_frames, ignore_index=True).sort_values("timestamp_utc").reset_index(drop=True)
                    if final_frames
                    else pd.DataFrame()
                )

                return {
                    "region": region,
                    "xml_files": xml_files,
                    "file_summary_df": pd.DataFrame(file_summaries),
                    "parse_errors_df": pd.DataFrame(parse_errors),
                    "df_raw": df_raw,
                    "df_after_sequence_filter": df_after_sequence_filter,
                    "df_after_dedup_clip": df_after_dedup_clip,
                    "hourly_before_fix": hourly_before_fix,
                    "quarterly_before_fix": quarterly_before_fix,
                    "hourly_fix": hourly_fix,
                    "quarterly_fix": quarterly_fix,
                    "hourly_final": hourly_fix.cleaned_frame,
                    "quarterly_final": quarterly_fix.cleaned_frame,
                    "final_aggregated": final_aggregated,
                    "duplicate_rows_removed": duplicate_rows_removed,
                    "sequence_2_rows_removed": sequence_2_rows_removed,
                }


            def summarize_stage(region: str, stage_name: str, df: pd.DataFrame, expected_minutes: int | None = None) -> dict[str, Any]:
                if df.empty:
                    return {
                        "region": region,
                        "stage": stage_name,
                        "rows": 0,
                        "min_timestamp_utc": None,
                        "max_timestamp_utc": None,
                        "duplicate_timestamps": 0,
                        "missing_timestamps": 0,
                        "missing_price_points": 0,
                        "interpolated_points": 0,
                    }

                timestamps = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
                return {
                    "region": region,
                    "stage": stage_name,
                    "rows": int(df.shape[0]),
                    "min_timestamp_utc": timestamps.min().isoformat(),
                    "max_timestamp_utc": timestamps.max().isoformat(),
                    "duplicate_timestamps": int(timestamps.duplicated().sum()),
                    "missing_timestamps": cleaning.missing_timestamps(df, expected_minutes),
                    "missing_price_points": int(pd.to_numeric(df["price_eur_per_mwh"], errors="coerce").isna().sum()),
                    "interpolated_points": int(df["is_interpolated_value"].sum()) if "is_interpolated_value" in df.columns else 0,
                }
            """
        ),
    ]
    cells.extend(
        [
            code_cell(
                """
                def build_stage_summary(region_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
                    rows: list[dict[str, Any]] = []
                    for region, result in region_results.items():
                        rows.extend(
                            [
                                summarize_stage(region, "raw_parsed", result["df_raw"], None),
                                summarize_stage(region, "after_sequence_filter", result["df_after_sequence_filter"], None),
                                summarize_stage(region, "after_dedup_clip", result["df_after_dedup_clip"], None),
                                summarize_stage(region, "hourly_before_fix", result["hourly_before_fix"], 60),
                                summarize_stage(region, "hourly_after_fix", result["hourly_final"], 60),
                                summarize_stage(region, "quarterly_before_fix", result["quarterly_before_fix"], 15),
                                summarize_stage(region, "quarterly_after_fix", result["quarterly_final"], 15),
                            ]
                        )
                    return pd.DataFrame(rows)


                def build_final_diagnostics(region_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
                    rows: list[dict[str, Any]] = []
                    for region, result in region_results.items():
                        rows.append(
                            cleaning.stats_row(
                                region=region,
                                dataset="aggregated",
                                df=result["final_aggregated"],
                                duplicate_rows_removed=result["duplicate_rows_removed"],
                                sequence_2_rows_removed=result["sequence_2_rows_removed"],
                            )
                        )
                        rows.append(
                            cleaning.stats_row(
                                region=region,
                                dataset="hourly",
                                df=result["hourly_final"],
                                gap_fix_summary=result["hourly_fix"].summary,
                                missing_timestamps_count_override=result["hourly_fix"].summary["missing_timestamps_before_fix"],
                            )
                        )
                        rows.append(
                            cleaning.stats_row(
                                region=region,
                                dataset="quarterly",
                                df=result["quarterly_final"],
                                gap_fix_summary=result["quarterly_fix"].summary,
                                missing_timestamps_count_override=result["quarterly_fix"].summary["missing_timestamps_before_fix"],
                            )
                        )
                    return pd.DataFrame(rows).sort_values(["dataset", "region"]).reset_index(drop=True)


                def combine_gap_fix_summaries(region_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
                    rows: list[dict[str, Any]] = []
                    for result in region_results.values():
                        rows.append(result["hourly_fix"].summary)
                        rows.append(result["quarterly_fix"].summary)
                    return pd.DataFrame(rows).sort_values(["dataset", "region"]).reset_index(drop=True)


                def combine_gap_fix_details(region_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
                    frames = []
                    for result in region_results.values():
                        if not result["hourly_fix"].gap_details.empty:
                            frames.append(result["hourly_fix"].gap_details)
                        if not result["quarterly_fix"].gap_details.empty:
                            frames.append(result["quarterly_fix"].gap_details)
                    if not frames:
                        return cleaning.empty_gap_details_frame()
                    return pd.concat(frames, ignore_index=True).sort_values(["dataset", "region", "gap_start_utc"]).reset_index(drop=True)


                def build_source_coverage(region_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
                    rows = []
                    for region, result in region_results.items():
                        file_summary_df = result["file_summary_df"]
                        rows.append(
                            {
                                "region": region,
                                "xml_files": int(len(result["xml_files"])),
                                "parsed_rows": int(result["df_raw"].shape[0]),
                                "min_doc_period_start_utc": file_summary_df["doc_period_start_utc"].min() if not file_summary_df.empty else None,
                                "max_doc_period_end_utc": file_summary_df["doc_period_end_utc"].max() if not file_summary_df.empty else None,
                                "parsed_timestamp_dtype": str(result["df_raw"]["timestamp_utc"].dtype) if not result["df_raw"].empty else None,
                                "parsed_tz": str(result["df_raw"]["timestamp_utc"].dt.tz) if not result["df_raw"].empty else None,
                            }
                        )
                    return pd.DataFrame(rows).sort_values("region").reset_index(drop=True)


                def build_cleaning_delta_table(region_results: dict[str, dict[str, Any]]) -> pd.DataFrame:
                    rows = []
                    for region, result in region_results.items():
                        rows.append(
                            {
                                "region": region,
                                "sequence_2_rows_removed": result["sequence_2_rows_removed"],
                                "duplicate_rows_removed": result["duplicate_rows_removed"],
                                "rows_after_dedup_clip": int(result["df_after_dedup_clip"].shape[0]),
                                "hourly_rows_before_fix": int(result["hourly_before_fix"].shape[0]),
                                "hourly_rows_after_fix": int(result["hourly_final"].shape[0]),
                                "quarterly_rows_before_fix": int(result["quarterly_before_fix"].shape[0]),
                                "quarterly_rows_after_fix": int(result["quarterly_final"].shape[0]),
                            }
                        )
                    return pd.DataFrame(rows).sort_values("region").reset_index(drop=True)
                """
            ),
            code_cell(
                """
                def plot_stage_row_counts(stage_summary_df: pd.DataFrame) -> None:
                    stage_order = [
                        "raw_parsed",
                        "after_sequence_filter",
                        "after_dedup_clip",
                        "hourly_before_fix",
                        "hourly_after_fix",
                        "quarterly_before_fix",
                        "quarterly_after_fix",
                    ]
                    pivot = stage_summary_df.pivot(index="stage", columns="region", values="rows").reindex(stage_order)
                    ax = pivot.plot(kind="bar", figsize=(13, 5), width=0.82)
                    ax.set_title("Rows by cleaning stage")
                    ax.set_xlabel("Stage")
                    ax.set_ylabel("Rows")
                    ax.legend(title="Region")
                    plt.xticks(rotation=30, ha="right")
                    plt.tight_layout()
                    plt.show()


                def plot_gap_fix_summary(gap_fix_summary_df: pd.DataFrame) -> None:
                    work = gap_fix_summary_df.copy()
                    work["label"] = work["region"] + " " + work["dataset"]
                    ax = work.set_index("label")[
                        [
                            "missing_datapoints_before_fix",
                            "interpolated_points_count",
                            "remaining_missing_points_after_fix",
                        ]
                    ].plot(kind="bar", figsize=(13, 5), width=0.82)
                    ax.set_title("Missing datapoints before and after the interpolation fix")
                    ax.set_xlabel("Region and dataset")
                    ax.set_ylabel("Datapoints")
                    plt.xticks(rotation=30, ha="right")
                    plt.tight_layout()
                    plt.show()


                def plot_daily_means(region_results: dict[str, dict[str, Any]], dataset: str) -> None:
                    key = "hourly_final" if dataset == "hourly" else "quarterly_final"
                    fig, ax = plt.subplots(figsize=(14, 5))
                    for region in REGIONS:
                        frame = region_results[region][key].copy()
                        if frame.empty:
                            continue
                        series = (
                            frame.dropna(subset=["price_eur_per_mwh"])
                            .set_index("timestamp_utc")["price_eur_per_mwh"]
                            .sort_index()
                            .resample("D")
                            .mean()
                        )
                        ax.plot(series.index, series.values, linewidth=1.3, label=region)
                    ax.set_title(f"Final cleaned {dataset} series | daily mean prices")
                    ax.set_xlabel("UTC date")
                    ax.set_ylabel("EUR/MWh")
                    ax.legend(title="Region")
                    plt.tight_layout()
                    plt.show()
                """
            ),
        ]
    )
    cells.extend(
        [
            code_cell(
                """
                def plot_gap_windows(region_result: dict[str, Any], dataset: str, action: str, max_windows: int = 3) -> None:
                    fix = region_result["hourly_fix"] if dataset == "hourly" else region_result["quarterly_fix"]
                    raw = region_result["hourly_before_fix"] if dataset == "hourly" else region_result["quarterly_before_fix"]
                    candidates = fix.gap_details[fix.gap_details["action"] == action].copy()
                    if candidates.empty:
                        print(f"No gaps with action='{action}' for {region_result['region']} {dataset}.")
                        return

                    candidates["gap_start_utc"] = pd.to_datetime(candidates["gap_start_utc"], utc=True)
                    candidates["gap_end_utc"] = pd.to_datetime(candidates["gap_end_utc"], utc=True)
                    if action == "interpolate":
                        candidates = candidates.sort_values("gap_start_utc", ascending=True)
                    else:
                        candidates = candidates.sort_values(["gap_length_points", "gap_start_utc"], ascending=[False, True])
                    candidates = candidates.head(max_windows).reset_index(drop=True)

                    pad = pd.Timedelta(hours=24) if dataset == "hourly" else pd.Timedelta(hours=6)
                    step = pd.Timedelta(minutes=60 if dataset == "hourly" else 15)
                    fig, axes = plt.subplots(len(candidates), 1, figsize=(14, 4 * len(candidates)), sharex=False)
                    if len(candidates) == 1:
                        axes = [axes]

                    for axis, row in zip(axes, candidates.itertuples(index=False)):
                        window_start = row.gap_start_utc - pad
                        window_end = row.gap_end_utc + pad
                        raw_slice = raw[(raw["timestamp_utc"] >= window_start) & (raw["timestamp_utc"] <= window_end)].copy()
                        final_slice = fix.cleaned_frame[
                            (fix.cleaned_frame["timestamp_utc"] >= window_start) & (fix.cleaned_frame["timestamp_utc"] <= window_end)
                        ].copy()

                        axis.plot(
                            final_slice["timestamp_utc"],
                            final_slice["price_eur_per_mwh"],
                            color="#005f73",
                            linewidth=2.0,
                            label="Final cleaned series",
                        )
                        axis.scatter(
                            raw_slice["timestamp_utc"],
                            raw_slice["price_eur_per_mwh"],
                            color="#6c757d",
                            s=30,
                            alpha=0.8,
                            label="Observed before fix",
                        )

                        if action == "interpolate":
                            highlighted = final_slice[final_slice["gap_fix_action"] == "interpolate"].copy()
                            axis.scatter(
                                highlighted["timestamp_utc"],
                                highlighted["price_eur_per_mwh"],
                                color="#bb3e03",
                                s=50,
                                label="Interpolated points",
                                zorder=5,
                            )
                        else:
                            axis.axvspan(row.gap_start_utc, row.gap_end_utc + step, color="#ae2012", alpha=0.18, label="Flagged gap")

                        axis.set_title(
                            f"{region_result['region']} {dataset} | {action} | "
                            f"{row.gap_start_utc.date()} | {row.gap_length_points} datapoints"
                        )
                        axis.set_xlabel("Timestamp UTC")
                        axis.set_ylabel("EUR/MWh")
                        handles, labels = axis.get_legend_handles_labels()
                        unique = dict(zip(labels, handles))
                        axis.legend(unique.values(), unique.keys(), loc="best")

                    plt.tight_layout()
                    plt.show()
                """
            ),
            code_cell(
                """
                region_results = {region: build_region_result(region) for region in REGIONS}

                source_coverage_df = build_source_coverage(region_results)
                cleaning_delta_df = build_cleaning_delta_table(region_results)
                stage_summary_df = build_stage_summary(region_results)
                gap_fix_summary_df = combine_gap_fix_summaries(region_results)
                gap_fix_details_df = combine_gap_fix_details(region_results)
                final_diagnostics_df = build_final_diagnostics(region_results)

                file_summary_df = pd.concat(
                    [result["file_summary_df"] for result in region_results.values() if not result["file_summary_df"].empty],
                    ignore_index=True,
                )
                parse_errors_df = pd.concat(
                    [result["parse_errors_df"] for result in region_results.values() if not result["parse_errors_df"].empty],
                    ignore_index=True,
                ) if any(not result["parse_errors_df"].empty for result in region_results.values()) else pd.DataFrame()
                """
            ),
            markdown_cell(
                """
                ## 1. Raw Source Parsing and UTC Verification

                The existing cleaner parses the ENTSO-E XML periods with `utc=True`. Because the raw timestamps are explicit UTC timestamps, DST does not create missing UTC observations.
                """
            ),
            code_cell(
                """
                display(source_coverage_df)
                """
            ),
            code_cell(
                """
                if not file_summary_df.empty:
                    display(file_summary_df.head(10))
                else:
                    print("No XML file summaries were created.")

                if not parse_errors_df.empty:
                    display(parse_errors_df)
                else:
                    display(Markdown("**XML parse errors:** none"))
                """
            ),
            code_cell(
                """
                fig, ax = plt.subplots(figsize=(12, 4.8))
                for region in REGIONS:
                    frame = region_results[region]["df_after_dedup_clip"].copy()
                    if frame.empty:
                        continue
                    series = (
                        frame.dropna(subset=["price_eur_per_mwh"])
                        .set_index("timestamp_utc")["price_eur_per_mwh"]
                        .sort_index()
                        .resample("D")
                        .mean()
                    )
                    ax.plot(series.index, series.values, linewidth=1.1, label=region)
                ax.set_title("Daily mean prices after parse, sequence filtering, deduplication, and clipping")
                ax.set_xlabel("UTC date")
                ax.set_ylabel("EUR/MWh")
                ax.legend(title="Region")
                plt.tight_layout()
                plt.show()
                """
            ),
            markdown_cell(
                """
                ## 2. Intermediate Cleaning Stages

                This section shows how many rows remain after the main shared cleaning steps, including the special Germany sequence-2 removal and duplicate removal.
                """
            ),
            code_cell(
                """
                display(cleaning_delta_df)
                display(stage_summary_df)
                """
            ),
            code_cell(
                """
                plot_stage_row_counts(stage_summary_df)
                """
            ),
        ]
    )
    cells.extend(
        [
            markdown_cell(
                """
                ## 3. Upstream Missing-Datapoint Fix

                The new fix works on the canonical UTC grid for each final dataset:

                - single and double missing datapoints are linearly interpolated between the closest known values
                - runs longer than two datapoints are left missing and flagged
                - DST is not treated as a missing-data source because the raw timestamps are already UTC
                """
            ),
            code_cell(
                """
                display(gap_fix_summary_df)
                """
            ),
            code_cell(
                """
                if gap_fix_details_df.empty:
                    display(Markdown("**Gap detail rows:** none"))
                else:
                    gap_action_summary = (
                        gap_fix_details_df.groupby(["region", "dataset", "action"], as_index=False)
                        .agg(
                            gap_runs=("gap_run_id", "count"),
                            datapoints=("gap_length_points", "sum"),
                            max_gap_length=("gap_length_points", "max"),
                        )
                        .sort_values(["dataset", "region", "action"])
                        .reset_index(drop=True)
                    )
                    display(gap_action_summary)
                    display(gap_fix_details_df.head(20))
                """
            ),
            code_cell(
                """
                plot_gap_fix_summary(gap_fix_summary_df)
                """
            ),
            markdown_cell(
                """
                ## 4. Focus Region Examples

                The examples below use the selected focus region so you can inspect actual interpolated rows and longer flagged gaps directly in the time series.
                """
            ),
            code_cell(
                """
                focus_result = region_results[FOCUS_REGION]

                focus_hourly_changes = focus_result["hourly_final"][
                    focus_result["hourly_final"]["gap_fix_action"] != "observed"
                ][
                    [
                        "timestamp_utc",
                        "price_eur_per_mwh",
                        "price_eur_per_mwh_original",
                        "missing_datapoint_source",
                        "gap_fix_action",
                    ]
                ].head(20)

                focus_quarterly_changes = focus_result["quarterly_final"][
                    focus_result["quarterly_final"]["gap_fix_action"] != "observed"
                ][
                    [
                        "timestamp_utc",
                        "price_eur_per_mwh",
                        "price_eur_per_mwh_original",
                        "missing_datapoint_source",
                        "gap_fix_action",
                    ]
                ].head(20)

                display(Markdown(f"**{FOCUS_REGION} hourly changed rows**"))
                display(focus_hourly_changes)
                display(Markdown(f"**{FOCUS_REGION} quarterly changed rows**"))
                display(focus_quarterly_changes)
                """
            ),
            code_cell(
                """
                display(
                    gap_fix_details_df[
                        (gap_fix_details_df["region"] == FOCUS_REGION)
                        & (gap_fix_details_df["action"] != "interpolate")
                    ].head(20)
                )
                """
            ),
            code_cell(
                """
                plot_gap_windows(focus_result, dataset="hourly", action="interpolate", max_windows=3)
                """
            ),
            code_cell(
                """
                plot_gap_windows(focus_result, dataset="hourly", action="flag_long_gap", max_windows=3)
                """
            ),
            code_cell(
                """
                plot_gap_windows(focus_result, dataset="quarterly", action="interpolate", max_windows=2)
                """
            ),
            markdown_cell(
                """
                ## 5. Final Cleaned Outputs and Summary

                The final tables below summarize the cleaned outputs that would be written by the shared pipeline, including the pre-fix gap counts, the interpolation counts, and the remaining flagged missing datapoints.
                """
            ),
            code_cell(
                """
                display(final_diagnostics_df)
                """
            ),
            code_cell(
                """
                plot_daily_means(region_results, dataset="hourly")
                plot_daily_means(region_results, dataset="quarterly")
                """
            ),
            code_cell(
                """
                summary_view = gap_fix_summary_df[
                    [
                        "region",
                        "dataset",
                        "missing_datapoints_before_fix",
                        "interpolated_points_count",
                        "flagged_long_gap_points_count",
                        "flagged_unbounded_gap_points_count",
                        "remaining_missing_points_after_fix",
                    ]
                ].copy()
                display(summary_view)

                summary_lines = []
                for row in summary_view.itertuples(index=False):
                    summary_lines.append(
                        f"- {row.region} {row.dataset}: "
                        f"{row.interpolated_points_count} interpolated, "
                        f"{row.remaining_missing_points_after_fix} remaining missing, "
                        f"{row.flagged_long_gap_points_count} in long flagged runs."
                    )

                display(Markdown("### Notebook summary\\n" + "\\n".join(summary_lines)))
                """
            ),
        ]
    )
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
    notebook = build_notebook()
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(notebook, NOTEBOOK_PATH)
    print(f"Wrote notebook: {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
