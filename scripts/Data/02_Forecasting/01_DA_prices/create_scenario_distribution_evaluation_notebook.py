from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


NOTEBOOK_PATH = Path(
    "notebooks/Data/02_Forecasting/01_DA_prices/29_scenario_distribution_evaluation_all_models.ipynb"
)


def md(text: str):
    return new_markdown_cell(dedent(text).strip())


def code(text: str):
    return new_code_cell(dedent(text).strip())


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 29 Scenario Distribution Evaluation Across All DA Models

            ## 1. Title and purpose
            This notebook evaluates **scenario quality**, not point-forecast winner selection. The downstream use case is stochastic MILP bidding/scheduling, where scenario calibration, width, tails, and temporal behaviour matter directly.

            We evaluate all discovered hourly and quarter-hour DA scenario sets for the active three-model stack:
            - LEAR FS3 promoted
            - XGBoost FS3 promoted/pruned candidate lineage
            - LEAR strict

            The notebook does **not** retrain forecasting models and does **not** regenerate scenarios. It discovers and evaluates existing artifacts only.
            """
        ),
        md(
            """
            ## 2. Methodological note: pointwise versus pathwise coverage
            Avoid judging scenario quality mainly by whether the **full daily path** stays inside one pointwise interval.

            For a pointwise 90% interval:
            - expected outside share per timestamp is about 10%
            - probability that at least one period in a day is outside:
              - hourly day (24 periods): `1 - 0.9^24 ≈ 92%`
              - quarter-hour day (96 periods): `1 - 0.9^96 ≈ 99.996%`

            Therefore:
            - daily "any outside" is a diagnostic, not a failure criterion
            - main calibration criteria are pointwise and distributional coverage
            - long same-sided exceedance clusters remain important because they can indicate level/regime misspecification or weak temporal dependence.
            """
        ),
        code(
            """
            from __future__ import annotations

            import json
            import math
            import os
            import re
            import subprocess
            import sys
            import warnings
            from dataclasses import dataclass
            from datetime import datetime, timezone
            from pathlib import Path
            from typing import Any

            import matplotlib.pyplot as plt
            import numpy as np
            import pandas as pd
            from IPython.display import Markdown, display

            pd.set_option("display.max_columns", 200)
            pd.set_option("display.width", 220)
            warnings.filterwarnings("ignore", message="FigureCanvasAgg is non-interactive, and thus cannot be shown")
            warnings.filterwarnings("ignore", message="Converting to PeriodArray/Index representation will drop timezone information.")

            NOTEBOOK_CWD = Path.cwd()
            REPO_ROOT = next(path for path in [NOTEBOOK_CWD, *NOTEBOOK_CWD.parents] if (path / "AGENTS.md").exists())
            os.chdir(REPO_ROOT)

            PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
            if str(PACKAGE_ROOT) not in sys.path:
                sys.path.insert(0, str(PACKAGE_ROOT))

            RUN_TS = pd.Timestamp.now(tz="UTC")
            RUN_ID = RUN_TS.strftime("%Y%m%d_%H%M%S")
            OUTPUT_ROOT = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "scenario_evaluation" / RUN_ID
            FIG_DIR = OUTPUT_ROOT / "figures"
            TABLE_DIR = OUTPUT_ROOT / "tables"
            FIG_DIR.mkdir(parents=True, exist_ok=True)
            TABLE_DIR.mkdir(parents=True, exist_ok=True)

            NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "Data" / "02_Forecasting" / "01_DA_prices" / "29_scenario_distribution_evaluation_all_models.ipynb"

            EXPECTED_MODEL_KEYS = [
                "hourly_lear_fs3",
                "hourly_xgboost_fs3",
                "hourly_lear_strict",
                "quarter_hour_lear_fs3",
                "quarter_hour_xgboost_fs3",
                "quarter_hour_lear_strict",
            ]

            MODEL_DISPLAY_NAME = {
                "hourly_lear_fs3": "Hourly LEAR FS3 promoted",
                "hourly_xgboost_fs3": "Hourly XGBoost FS3 promoted/pruned",
                "hourly_lear_strict": "Hourly LEAR strict",
                "quarter_hour_lear_fs3": "Quarter-hour LEAR FS3 promoted",
                "quarter_hour_xgboost_fs3": "Quarter-hour XGBoost FS3 promoted/pruned",
                "quarter_hour_lear_strict": "Quarter-hour LEAR strict (mean-shape deviation on LEAR strict anchor)",
            }

            # Optional explicit old/new run selection for before-after diagnostics.
            # Values can be absolute or repo-relative paths to scenario run directories.
            RUN_SELECTION = {
                "hourly_old_run_dir": os.getenv("SCENARIO_HOURLY_OLD_RUN_DIR", "").strip(),
                "hourly_new_run_dir": os.getenv("SCENARIO_HOURLY_NEW_RUN_DIR", "").strip(),
                "quarterhour_old_run_dir": os.getenv("SCENARIO_QH_OLD_RUN_DIR", "").strip(),
                "quarterhour_new_run_dir": os.getenv("SCENARIO_QH_NEW_RUN_DIR", "").strip(),
                "calibration_summary_csv": os.getenv("SCENARIO_CALIBRATION_SUMMARY_CSV", "").strip(),
            }

            COVERAGE_TARGETS = {
                "p25_p75": 0.50,
                "p10_p90": 0.80,
                "p05_p95": 0.90,
                "p025_p975": 0.95,
            }

            warnings_log: list[str] = []

            print(f"Repo root: {REPO_ROOT}")
            print(f"Output root: {OUTPUT_ROOT}")
            """
        ),
        md(
            """
            ## 3. Imports and configuration
            The notebook uses only project-local artifacts, with configurable paths and explicit warning collection.
            """
        ),
        code(
            """
            @dataclass(frozen=True)
            class ScenarioSource:
                granularity: str
                run_dir: Path
                scenario_path: Path
                summary_path: Path | None
                run_id: str
                run_status: str
                run_timestamp_utc: pd.Timestamp


            def _safe_read_json(path: Path) -> dict[str, Any]:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    return {}


            def _parse_run_timestamp(run_id: str) -> pd.Timestamp:
                text = str(run_id)
                m = re.match(r"^(\\d{8})_(\\d{6})", text)
                if not m:
                    return pd.NaT
                parsed = pd.to_datetime(f"{m.group(1)} {m.group(2)}", format="%Y%m%d %H%M%S", utc=True, errors="coerce")
                return parsed


            def _infer_granularity(path: Path) -> str:
                lower = str(path).lower()
                if "quarterhour_da" in lower:
                    return "quarter_hour"
                if "hourly_da" in lower:
                    return "hourly"
                return "unknown"


            def _canonical_model_key(raw_model: str, granularity: str) -> str | None:
                txt = str(raw_model).lower()
                if granularity == "hourly":
                    if "lear_strict" in txt:
                        return "hourly_lear_strict"
                    if "xgboost" in txt:
                        return "hourly_xgboost_fs3"
                    if "lear" in txt:
                        return "hourly_lear_fs3"
                    return None
                if granularity == "quarter_hour":
                    if "mean_shape" in txt or "lear_strict" in txt:
                        return "quarter_hour_lear_strict"
                    if "xgboost" in txt:
                        return "quarter_hour_xgboost_fs3"
                    if "__lear__" in txt or "lear" in txt:
                        return "quarter_hour_lear_fs3"
                    return None
                return None


            def _preferred_variant_map(run_dir: Path) -> dict[str, str]:
                mapping: dict[str, str] = {}
                cmp_path = run_dir / "final_scenario_model_comparison.csv"
                if not cmp_path.exists():
                    return mapping
                try:
                    frame = pd.read_csv(cmp_path, low_memory=False)
                except Exception:
                    return mapping
                if "selected_as_default_variant" not in frame.columns:
                    return mapping
                selected = frame[frame["selected_as_default_variant"].fillna(False).astype(bool)].copy()
                if selected.empty:
                    return mapping
                key_col = "candidate_key" if "candidate_key" in selected.columns else None
                label_col = "candidate_label" if "candidate_label" in selected.columns else None
                for _, row in selected.iterrows():
                    variant = str(row.get("scenario_variant", "")).strip()
                    if not variant:
                        continue
                    if key_col:
                        ck = str(row.get(key_col, "")).strip()
                        if ck:
                            mapping[ck] = variant
                    if label_col:
                        cl = str(row.get(label_col, "")).strip()
                        if cl:
                            mapping[cl] = variant
                return mapping


            def discover_scenario_sources() -> pd.DataFrame:
                roots = [
                    REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da" / "notebook_artifacts",
                    REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "quarterhour_da" / "finalisation_runs",
                    REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "quarterhour_da" / "runs",
                ]
                rows: list[dict[str, Any]] = []
                for root in roots:
                    if not root.exists():
                        continue
                    for scenario_path in root.rglob("scenario_prices_long.csv"):
                        run_dir = scenario_path.parent
                        granularity = _infer_granularity(scenario_path)
                        summary_candidates = [
                            run_dir / "scenario_generation_run_summary.json",
                            run_dir / "run_summary.json",
                        ]
                        summary_path = next((p for p in summary_candidates if p.exists()), None)
                        summary = _safe_read_json(summary_path) if summary_path else {}
                        run_id = str(summary.get("run_id") or run_dir.name)
                        run_status = str(summary.get("status") or "").strip().lower() or "unknown"
                        run_ts = _parse_run_timestamp(run_id if run_id else run_dir.name)
                        if pd.isna(run_ts):
                            run_ts = _parse_run_timestamp(run_dir.name)
                        rows.append(
                            {
                                "granularity": granularity,
                                "run_dir": str(run_dir),
                                "scenario_path": str(scenario_path),
                                "summary_path": str(summary_path) if summary_path else None,
                                "run_id": run_id,
                                "run_status": run_status,
                                "run_timestamp_utc": run_ts,
                                "discovery_root": str(root),
                            }
                        )
                frame = pd.DataFrame(rows)
                if frame.empty:
                    return frame
                frame = frame.sort_values(["run_timestamp_utc", "run_id"]).reset_index(drop=True)
                return frame


            def _read_header_columns(path: Path) -> list[str]:
                try:
                    return pd.read_csv(path, nrows=0).columns.tolist()
                except Exception:
                    return []


            def _id_column(cols: list[str]) -> str | None:
                if "model_id" in cols:
                    return "model_id"
                if "candidate_key" in cols:
                    return "candidate_key"
                if "candidate_label" in cols:
                    return "candidate_label"
                if "model_name" in cols:
                    return "model_name"
                return None


            def _read_unique_model_ids(path: Path) -> tuple[str | None, list[str]]:
                cols = _read_header_columns(path)
                id_col = _id_column(cols)
                if id_col is None:
                    return None, []
                series = pd.read_csv(path, usecols=[id_col], low_memory=False)[id_col].astype(str)
                return id_col, sorted(series.dropna().unique().tolist())


            def _select_latest_rows_per_expected_model(source_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
                discovered_rows: list[dict[str, Any]] = []
                if source_df.empty:
                    return pd.DataFrame(), pd.DataFrame()

                for _, src in source_df.iterrows():
                    scenario_path = Path(src["scenario_path"])
                    try:
                        id_col, raw_ids = _read_unique_model_ids(scenario_path)
                    except Exception as exc:
                        warnings_log.append(f"Failed to inspect model ids for {scenario_path}: {exc}")
                        continue
                    if not id_col or not raw_ids:
                        warnings_log.append(f"No model identifier column found in scenario file: {scenario_path}")
                        continue
                    for raw_id in raw_ids:
                        canonical_key = _canonical_model_key(raw_id, str(src["granularity"]))
                        discovered_rows.append(
                            {
                                **src.to_dict(),
                                "id_column": id_col,
                                "raw_model_id": raw_id,
                                "canonical_model_key": canonical_key,
                            }
                        )

                discovered = pd.DataFrame(discovered_rows)
                if discovered.empty:
                    return discovered, pd.DataFrame()

                # Completed-first, then newest timestamp.
                discovered["is_completed_like"] = discovered["run_status"].astype(str).str.startswith("completed")
                discovered = discovered.sort_values(
                    ["is_completed_like", "run_timestamp_utc", "run_id", "raw_model_id"],
                    ascending=[False, False, False, True],
                ).reset_index(drop=True)

                selected_rows: list[dict[str, Any]] = []
                for key in EXPECTED_MODEL_KEYS:
                    subset = discovered[discovered["canonical_model_key"] == key].copy()
                    if subset.empty:
                        selected_rows.append(
                            {
                                "canonical_model_key": key,
                                "display_name": MODEL_DISPLAY_NAME[key],
                                "selected": False,
                                "selection_reason": "missing_model",
                            }
                        )
                        warnings_log.append(f"Expected model not found in discovered scenario files: {MODEL_DISPLAY_NAME[key]}")
                        continue

                    chosen = subset.iloc[0].to_dict()
                    chosen["selected"] = True
                    chosen["display_name"] = MODEL_DISPLAY_NAME[key]
                    chosen["selection_reason"] = "latest_completed_like"
                    selected_rows.append(chosen)

                selected = pd.DataFrame(selected_rows)
                return discovered, selected


            def _first_present(cols: list[str], options: list[str]) -> str | None:
                for name in options:
                    if name in cols:
                        return name
                return None


            def _to_utc(series: pd.Series) -> pd.Series:
                return pd.to_datetime(series, utc=True, errors="coerce")


            def _resolve_lead_day(df: pd.DataFrame) -> pd.Series:
                if "lead_day" in df.columns:
                    return pd.to_numeric(df["lead_day"], errors="coerce").astype("Int64")
                if "forecast_origin_utc" in df.columns and "delivery_start_utc" in df.columns:
                    fo = pd.to_datetime(df["forecast_origin_utc"], utc=True, errors="coerce")
                    de = pd.to_datetime(df["delivery_start_utc"], utc=True, errors="coerce")
                    return (de.dt.tz_convert("Europe/Amsterdam").dt.date - fo.dt.tz_convert("Europe/Amsterdam").dt.date).astype("Int64")
                return pd.Series(pd.array([pd.NA] * len(df), dtype="Int64"), index=df.index)


            def load_actuals_for_granularity(granularity: str) -> tuple[pd.DataFrame, str]:
                if granularity == "hourly":
                    path = REPO_ROOT / "data" / "01_cleaned" / "Day_ahead_prices" / "DA_prices" / "hourly" / "da_prices_NL_hourly.csv"
                    frame = pd.read_csv(path, low_memory=False)
                    ts_col = _first_present(frame.columns.tolist(), ["timestamp_utc", "target_timestamp_utc"])
                    price_col = _first_present(frame.columns.tolist(), ["price_eur_per_mwh", "y_true", "actual_price"])
                    if ts_col is None or price_col is None:
                        raise ValueError(f"Hourly actual file missing required columns: {path}")
                    out = pd.DataFrame(
                        {
                            "delivery_start_utc": _to_utc(frame[ts_col]),
                            "y_true_join": pd.to_numeric(frame[price_col], errors="coerce"),
                        }
                    ).dropna(subset=["delivery_start_utc"]).drop_duplicates("delivery_start_utc", keep="last")
                    return out, f"hourly_csv:{path}"

                # quarter-hour fallback: observed deterministic canonical frame
                from quarterhour_da.observed_deterministic import load_and_build_canonical_quarterhour_frame
                from quarterhour_da.config import QuarterHourDAExtensionConfig

                canonical, _, source_summary = load_and_build_canonical_quarterhour_frame(QuarterHourDAExtensionConfig())
                out = canonical[["timestamp_utc", "price_eur_per_mwh", "is_observed_target"]].copy()
                out["delivery_start_utc"] = _to_utc(out["timestamp_utc"])
                out["y_true_join"] = np.where(out["is_observed_target"].fillna(False), pd.to_numeric(out["price_eur_per_mwh"], errors="coerce"), np.nan)
                out = out[["delivery_start_utc", "y_true_join"]].dropna(subset=["delivery_start_utc"]).drop_duplicates("delivery_start_utc", keep="last")
                source_note = "quarterhour_observed_deterministic_loader:" + str(source_summary.get("authoritative_quarterhour_path", "unknown"))
                return out, source_note


            def standardise_scenario_schema(
                path: Path,
                *,
                granularity: str,
                raw_model_id: str,
                canonical_model_key: str,
                display_name: str,
            ) -> tuple[pd.DataFrame, dict[str, Any]]:
                meta: dict[str, Any] = {"path": str(path), "warnings": []}
                frame = pd.read_csv(path, low_memory=False)
                cols = frame.columns.tolist()

                id_col = _id_column(cols)
                if id_col is None:
                    raise ValueError(f"No model id column found in scenario file: {path}")

                frame[id_col] = frame[id_col].astype(str)
                frame = frame[frame[id_col] == str(raw_model_id)].copy()
                if frame.empty:
                    raise ValueError(f"No rows found for model '{raw_model_id}' in {path}")

                # Optional default-variant filtering (hourly artifacts).
                if "scenario_variant" in frame.columns:
                    vmap = _preferred_variant_map(path.parent)
                    preferred = vmap.get(str(raw_model_id))
                    if preferred is None and "candidate_label" in frame.columns:
                        labels = frame["candidate_label"].astype(str).unique().tolist()
                        for lbl in labels:
                            if lbl in vmap:
                                preferred = vmap[lbl]
                                break
                    if preferred is None:
                        variant_counts = frame["scenario_variant"].astype(str).value_counts()
                        preferred = str(variant_counts.index[0])
                        meta["warnings"].append(
                            f"No explicit default variant found for {raw_model_id}; using most frequent variant '{preferred}'."
                        )
                    frame = frame[frame["scenario_variant"].astype(str) == str(preferred)].copy()
                    meta["selected_variant"] = preferred
                else:
                    meta["selected_variant"] = None

                # Long vs wide handling.
                if "scenario_price" not in frame.columns:
                    scenario_cols = [c for c in frame.columns if re.match(r"^(scenario_?\\d+|s\\d+)$", str(c).lower())]
                    if scenario_cols:
                        keep_base = [c for c in frame.columns if c not in scenario_cols]
                        frame = frame.melt(id_vars=keep_base, value_vars=scenario_cols, var_name="scenario_id", value_name="scenario_price")
                        meta["warnings"].append("Wide scenario format detected and reshaped to long format.")
                    else:
                        raise ValueError(f"No scenario_price column and no wide scenario columns found in {path}")

                forecast_origin_col = _first_present(cols, ["forecast_origin_utc", "forecast_origin", "origin_timestamp"])
                delivery_col = _first_present(cols, ["target_timestamp_utc", "period_timestamp", "delivery_start", "timestamp_utc"])
                lead_col = _first_present(cols, ["lead_day", "horizon_day", "lead"])
                split_col = _first_present(cols, ["dataset_split", "split"])
                scen_id_col = _first_present(frame.columns.tolist(), ["scenario_id", "scenario"])
                scen_price_col = _first_present(frame.columns.tolist(), ["scenario_price", "price_eur_per_mwh"])
                y_true_col = _first_present(frame.columns.tolist(), ["y_true", "actual_price", "actual_price_eur_per_mwh", "price_actual"])
                point_col = _first_present(frame.columns.tolist(), ["point_forecast", "central_forecast_price", "y_pred", "original_forecast_price"])
                prob_col = _first_present(frame.columns.tolist(), ["scenario_probability", "probability"])

                out = pd.DataFrame(index=frame.index)
                out["model_key"] = canonical_model_key
                out["model_display_name"] = display_name
                out["model_instance_id"] = str(raw_model_id)
                out["granularity"] = granularity
                out["forecast_origin_utc"] = _to_utc(frame[forecast_origin_col]) if forecast_origin_col else pd.NaT
                out["delivery_start_utc"] = _to_utc(frame[delivery_col]) if delivery_col else pd.NaT
                out["lead_day"] = pd.to_numeric(frame[lead_col], errors="coerce").astype("Int64") if lead_col else pd.Series(pd.array([pd.NA] * len(frame), dtype="Int64"))
                out["dataset_split"] = frame[split_col].astype(str) if split_col else "unknown"
                out["scenario_id"] = frame[scen_id_col].astype(str) if scen_id_col else "S00"
                out["scenario_price"] = pd.to_numeric(frame[scen_price_col], errors="coerce")
                out["y_true"] = pd.to_numeric(frame[y_true_col], errors="coerce") if y_true_col else np.nan
                out["point_forecast"] = pd.to_numeric(frame[point_col], errors="coerce") if point_col else np.nan
                out["scenario_probability"] = pd.to_numeric(frame[prob_col], errors="coerce") if prob_col else np.nan
                out["scenario_variant"] = frame["scenario_variant"].astype(str) if "scenario_variant" in frame.columns else "base"
                out["source_scenario_file"] = str(path)
                out["actuals_joined_by_notebook"] = False

                # Hourly scenario notebook artifacts can be D-only and may miss explicit origin columns.
                if out["forecast_origin_utc"].isna().all() and "delivery_day" in frame.columns:
                    delivery_day_local = pd.to_datetime(frame["delivery_day"], errors="coerce")
                    origin_local = delivery_day_local - pd.Timedelta(days=1) + pd.Timedelta(hours=8)
                    out["forecast_origin_utc"] = pd.to_datetime(origin_local).dt.tz_localize(
                        "Europe/Amsterdam",
                        nonexistent="shift_forward",
                        ambiguous="NaT",
                    ).dt.tz_convert("UTC")
                    meta["warnings"].append(
                        "forecast_origin_utc reconstructed from delivery_day using D-1 08:00 Europe/Amsterdam semantics."
                    )
                if out["lead_day"].isna().all() and granularity == "hourly":
                    out["lead_day"] = pd.Series(pd.array([0] * len(out), dtype="Int64"), index=out.index)
                    meta["warnings"].append("lead_day missing in hourly artifact; defaulted to 0 for D-only scenario output.")

                # Fill lead day if still missing.
                out["lead_day"] = _resolve_lead_day(out)

                required = ["delivery_start_utc", "scenario_price", "scenario_id"]
                for col in required:
                    if col not in out.columns:
                        raise ValueError(f"Standardisation failed to produce required column '{col}' for {path}")

                if out["delivery_start_utc"].isna().all():
                    meta["warnings"].append("All delivery_start_utc values are missing after parsing.")
                if out["forecast_origin_utc"].isna().all():
                    meta["warnings"].append("All forecast_origin_utc values are missing after parsing.")

                out = out.sort_values(["forecast_origin_utc", "delivery_start_utc", "scenario_id"]).reset_index(drop=True)
                meta["rows"] = int(out.shape[0])
                meta["unique_origins"] = int(out["forecast_origin_utc"].nunique(dropna=True))
                meta["unique_delivery_timestamps"] = int(out["delivery_start_utc"].nunique(dropna=True))
                meta["unique_scenarios"] = int(out["scenario_id"].nunique(dropna=True))
                return out, meta


            def join_actuals_if_needed(scenarios: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
                by_model: list[pd.DataFrame] = []
                join_rows: list[dict[str, Any]] = []
                for model_key, group in scenarios.groupby("model_key", dropna=False):
                    part = group.copy()
                    granularity = str(part["granularity"].iloc[0])
                    missing_rate_before = float(part["y_true"].isna().mean())
                    joined = False
                    source_note = "already_present"
                    if missing_rate_before > 0:
                        try:
                            actuals, source_note = load_actuals_for_granularity(granularity)
                            part = part.merge(actuals, on="delivery_start_utc", how="left")
                            part["y_true"] = part["y_true"].where(part["y_true"].notna(), part["y_true_join"])
                            part["actuals_joined_by_notebook"] = part["y_true_join"].notna()
                            part = part.drop(columns=["y_true_join"])
                            joined = True
                        except Exception as exc:
                            warnings_log.append(f"Actuals join failed for {model_key}: {exc}")
                    join_rows.append(
                        {
                            "model_key": model_key,
                            "granularity": granularity,
                            "missing_actual_rate_before": missing_rate_before,
                            "missing_actual_rate_after": float(part["y_true"].isna().mean()),
                            "actuals_joined_by_notebook_any": bool(part["actuals_joined_by_notebook"].fillna(False).any()),
                            "actuals_source_note": source_note,
                            "actuals_join_attempted": bool(joined or missing_rate_before > 0),
                        }
                    )
                    by_model.append(part)
                return pd.concat(by_model, ignore_index=True), pd.DataFrame(join_rows)
            """
        ),
        md(
            """
            ## 4. Scenario discovery and registry
            Discovery scans known hourly and quarter-hour scenario run trees and builds a registry.
            Selection policy is explicit: for each expected thesis model family, choose the latest run with a completed-like status.

            Missing model families are reported as warnings and kept visible in outputs.
            """
        ),
        code(
            """
            source_registry = discover_scenario_sources()
            if source_registry.empty:
                raise RuntimeError("No scenario source files were discovered.")

            discovered_models, selected_models = _select_latest_rows_per_expected_model(source_registry)

            if discovered_models.empty:
                raise RuntimeError("Scenario files were found, but no model identifiers could be extracted.")

            selected_models = selected_models.copy()
            selected_models["scenario_path"] = selected_models.get("scenario_path")
            selected_models["run_dir"] = selected_models.get("run_dir")
            selected_models["run_id"] = selected_models.get("run_id")
            selected_models["run_status"] = selected_models.get("run_status")
            selected_models["run_timestamp_utc"] = selected_models.get("run_timestamp_utc")
            selected_models["granularity"] = selected_models.get("granularity")
            selected_models["raw_model_id"] = selected_models.get("raw_model_id")
            selected_models["id_column"] = selected_models.get("id_column")

            display(Markdown("### Selected Scenario Sources"))
            display(
                selected_models[
                    [
                        "display_name",
                        "selected",
                        "selection_reason",
                        "granularity",
                        "raw_model_id",
                        "run_id",
                        "run_status",
                        "scenario_path",
                    ]
                ]
            )

            discovered_models.to_csv(TABLE_DIR / "scenario_discovery_candidates.csv", index=False)
            selected_models.to_csv(TABLE_DIR / "scenario_model_registry.csv", index=False)

            models_found = int(selected_models["selected"].fillna(False).sum())
            if models_found < 6:
                warnings_log.append(f"Expected 6 model families; found {models_found}.")
            """
        ),
        md(
            """
            ## 5. Load and harmonise scenarios
            All selected files are transformed to one canonical long schema:

            `model_key, granularity, forecast_origin_utc, delivery_start_utc, lead_day, scenario_id, scenario_price, y_true`

            The loader:
            - handles long and wide scenario formats,
            - applies explicit variant selection where variant columns exist,
            - records schema warnings instead of silently dropping issues,
            - joins actuals only when required and logs the source.
            """
        ),
        code(
            """
            loaded_parts: list[pd.DataFrame] = []
            load_meta_rows: list[dict[str, Any]] = []

            for _, row in selected_models.iterrows():
                if not bool(row.get("selected", False)):
                    continue
                scenario_path = Path(str(row["scenario_path"]))
                try:
                    part, meta = standardise_scenario_schema(
                        scenario_path,
                        granularity=str(row["granularity"]),
                        raw_model_id=str(row["raw_model_id"]),
                        canonical_model_key=str(row["canonical_model_key"]),
                        display_name=str(row["display_name"]),
                    )
                    loaded_parts.append(part)
                    load_meta_rows.append(
                        {
                            "canonical_model_key": str(row["canonical_model_key"]),
                            "display_name": str(row["display_name"]),
                            "granularity": str(row["granularity"]),
                            "raw_model_id": str(row["raw_model_id"]),
                            "run_id": str(row.get("run_id", "")),
                            "scenario_path": str(scenario_path),
                            "rows": int(meta.get("rows", 0)),
                            "unique_origins": int(meta.get("unique_origins", 0)),
                            "unique_delivery_timestamps": int(meta.get("unique_delivery_timestamps", 0)),
                            "unique_scenarios": int(meta.get("unique_scenarios", 0)),
                            "selected_variant": meta.get("selected_variant"),
                            "warnings": " | ".join(meta.get("warnings", [])),
                        }
                    )
                    for msg in meta.get("warnings", []):
                        warnings_log.append(f"[{row['display_name']}] {msg}")
                except Exception as exc:
                    warnings_log.append(f"Failed loading {row.get('display_name', row.get('canonical_model_key'))}: {exc}")

            if not loaded_parts:
                raise RuntimeError("No scenario model could be loaded successfully.")

            scenarios = pd.concat(loaded_parts, ignore_index=True)
            load_registry = pd.DataFrame(load_meta_rows)

            scenarios, actual_join_log = join_actuals_if_needed(scenarios)

            # Core integrity checks recorded for visibility.
            duplicate_key_mask = scenarios.duplicated(
                subset=["model_key", "forecast_origin_utc", "delivery_start_utc", "scenario_id"],
                keep=False,
            )
            n_dup = int(duplicate_key_mask.sum())
            if n_dup > 0:
                warnings_log.append(f"Duplicate scenario keys detected: {n_dup} rows.")

            if scenarios["scenario_price"].isna().any():
                warnings_log.append(
                    f"Missing scenario_price values detected: {int(scenarios['scenario_price'].isna().sum())} rows."
                )

            if scenarios["delivery_start_utc"].isna().any():
                warnings_log.append(
                    f"Missing delivery_start_utc detected: {int(scenarios['delivery_start_utc'].isna().sum())} rows."
                )

            # Enrich local-time fields for diagnostics/plots.
            local_ts = scenarios["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam")
            scenarios["delivery_local_timestamp"] = local_ts
            scenarios["delivery_local_date"] = local_ts.dt.date
            scenarios["hour_of_day"] = local_ts.dt.hour.astype("Int64")
            scenarios["quarter_of_day"] = (local_ts.dt.hour * 4 + (local_ts.dt.minute // 15) + 1).astype("Int64")
            scenarios["month"] = local_ts.dt.month.astype("Int64")
            scenarios["season"] = np.select(
                [
                    scenarios["month"].isin([12, 1, 2]),
                    scenarios["month"].isin([3, 4, 5]),
                    scenarios["month"].isin([6, 7, 8]),
                    scenarios["month"].isin([9, 10, 11]),
                ],
                ["winter", "spring", "summer", "autumn"],
                default="unknown",
            )

            # Per-model registry with required fields.
            model_registry_rows = []
            for (mk, disp, gran), grp in scenarios.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                per_key = grp.groupby(["forecast_origin_utc", "delivery_start_utc"], dropna=False)["scenario_id"].nunique()
                model_registry_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "scenario_file_path": "; ".join(sorted(set(grp["source_scenario_file"].astype(str).tolist()))),
                        "prediction_scenario_rows": int(grp.shape[0]),
                        "n_unique_origins": int(grp["forecast_origin_utc"].nunique(dropna=True)),
                        "n_unique_delivery_timestamps": int(grp["delivery_start_utc"].nunique(dropna=True)),
                        "n_unique_origin_delivery_keys": int(grp[["forecast_origin_utc", "delivery_start_utc"]].drop_duplicates().shape[0]),
                        "scenarios_per_origin_delivery_min": float(per_key.min()) if not per_key.empty else np.nan,
                        "scenarios_per_origin_delivery_mean": float(per_key.mean()) if not per_key.empty else np.nan,
                        "scenarios_per_origin_delivery_max": float(per_key.max()) if not per_key.empty else np.nan,
                        "start_delivery_utc": str(grp["delivery_start_utc"].min()),
                        "end_delivery_utc": str(grp["delivery_start_utc"].max()),
                        "split_coverage": ", ".join(sorted(grp["dataset_split"].dropna().astype(str).unique().tolist())),
                        "actuals_already_present_rate": float(grp["y_true"].notna().mean()),
                        "actuals_joined_by_notebook_any": bool(grp["actuals_joined_by_notebook"].fillna(False).any()),
                    }
                )

            scenario_model_registry = pd.DataFrame(model_registry_rows).sort_values("model_name").reset_index(drop=True)
            scenario_model_registry.to_csv(TABLE_DIR / "scenario_model_registry.csv", index=False)
            load_registry.to_csv(TABLE_DIR / "scenario_load_registry.csv", index=False)
            actual_join_log.to_csv(TABLE_DIR / "scenario_actual_join_log.csv", index=False)

            print(f"Loaded scenario rows: {scenarios.shape[0]:,}")
            display(scenario_model_registry)
            """
        ),
        md(
            """
            ## 6. Quantile construction
            For each model/origin/delivery timestamp, the notebook computes:

            - `p01, p025, p05, p10, p25, p50, p75, p90, p95, p975, p99`
            - `scenario_mean, scenario_std, scenario_min, scenario_max, n_scenarios`

            These summaries drive coverage, sharpness, interval scoring, and diagnostics.
            """
        ),
        code(
            """
            quantiles = [0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.975, 0.99]
            qname = {
                0.01: "p01",
                0.025: "p025",
                0.05: "p05",
                0.10: "p10",
                0.25: "p25",
                0.50: "p50",
                0.75: "p75",
                0.90: "p90",
                0.95: "p95",
                0.975: "p975",
                0.99: "p99",
            }

            def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
                if values.size == 0:
                    return np.nan
                if values.size == 1:
                    return float(values[0])
                order = np.argsort(values)
                sorted_values = values[order]
                sorted_weights = weights[order]
                cumulative = np.cumsum(sorted_weights)
                if cumulative[-1] <= 0:
                    return np.nan
                cumulative = cumulative / cumulative[-1]
                return float(np.interp(float(quantile), cumulative, sorted_values))

            key_cols = [
                "model_key",
                "model_display_name",
                "model_instance_id",
                "granularity",
                "dataset_split",
                "forecast_origin_utc",
                "delivery_start_utc",
                "lead_day",
                "delivery_local_date",
                "hour_of_day",
                "quarter_of_day",
                "month",
                "season",
            ]

            grouped = scenarios.groupby(key_cols, dropna=False)
            stats = grouped.agg(
                y_true=("y_true", "first"),
                scenario_mean=("scenario_price", "mean"),
                scenario_std=("scenario_price", "std"),
                scenario_min=("scenario_price", "min"),
                scenario_max=("scenario_price", "max"),
                n_scenarios=("scenario_id", "nunique"),
            ).reset_index()

            # Unweighted quantiles kept as secondary diagnostics.
            qtab_unweighted = grouped["scenario_price"].quantile(quantiles).unstack()
            qtab_unweighted = qtab_unweighted.rename(columns=qname).reset_index()
            qdf_unweighted = stats.merge(qtab_unweighted, on=key_cols, how="left")
            qdf_unweighted["scenario_std"] = qdf_unweighted["scenario_std"].fillna(0.0)
            qdf_unweighted["quantile_mode"] = "unweighted"

            # Weighted quantiles are the primary diagnostics when scenario probabilities are unequal.
            qrows_weighted: list[dict[str, Any]] = []
            for keys, part in grouped:
                row = {col: value for col, value in zip(key_cols, keys, strict=True)}
                vals = pd.to_numeric(part["scenario_price"], errors="coerce").to_numpy(dtype=float)
                if "scenario_probability" in part.columns:
                    probs = pd.to_numeric(part["scenario_probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                elif "probability" in part.columns:
                    probs = pd.to_numeric(part["probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                else:
                    probs = np.zeros(vals.shape[0], dtype=float)
                if vals.size == 0:
                    continue
                if probs.size != vals.size or probs.sum() <= 0.0:
                    probs = np.ones_like(vals, dtype=float)
                for q in quantiles:
                    row[qname[q]] = _weighted_quantile(vals, probs, q)
                qrows_weighted.append(row)
            qtab_weighted = pd.DataFrame(qrows_weighted)
            qdf_weighted = stats.merge(qtab_weighted, on=key_cols, how="left")
            qdf_weighted["scenario_std"] = qdf_weighted["scenario_std"].fillna(0.0)
            qdf_weighted["quantile_mode"] = "weighted"

            qdf = qdf_weighted.copy()

            # Duplicate check on aggregated keys.
            agg_dup_count = int(qdf.duplicated(subset=key_cols, keep=False).sum())
            if agg_dup_count > 0:
                warnings_log.append(f"Duplicate aggregated quantile keys detected: {agg_dup_count}")

            qdf.to_csv(TABLE_DIR / "scenario_quantile_table.csv", index=False)
            qdf_weighted.to_csv(TABLE_DIR / "scenario_quantile_table_weighted.csv", index=False)
            qdf_unweighted.to_csv(TABLE_DIR / "scenario_quantile_table_unweighted.csv", index=False)

            # Weighted vs unweighted summary for calibration diagnostics.
            cmp = qdf_weighted.merge(
                qdf_unweighted,
                on=key_cols,
                how="inner",
                suffixes=("_weighted", "_unweighted"),
            )
            if not cmp.empty and "y_true_weighted" in cmp.columns:
                cmp["inside_weighted"] = (
                    cmp["y_true_weighted"].notna()
                    & (cmp["y_true_weighted"] >= cmp["p05_weighted"])
                    & (cmp["y_true_weighted"] <= cmp["p95_weighted"])
                ).astype(float)
                cmp["inside_unweighted"] = (
                    cmp["y_true_unweighted"].notna()
                    & (cmp["y_true_unweighted"] >= cmp["p05_unweighted"])
                    & (cmp["y_true_unweighted"] <= cmp["p95_unweighted"])
                ).astype(float)
                cmp["width_weighted"] = cmp["p95_weighted"] - cmp["p05_weighted"]
                cmp["width_unweighted"] = cmp["p95_unweighted"] - cmp["p05_unweighted"]
                weighted_unweighted = (
                    cmp.groupby(["model_key", "model_display_name", "granularity", "dataset_split"], dropna=False)
                    .agg(
                        coverage_p05_p95_weighted=("inside_weighted", "mean"),
                        coverage_p05_p95_unweighted=("inside_unweighted", "mean"),
                        avg_width_weighted=("width_weighted", "mean"),
                        avg_width_unweighted=("width_unweighted", "mean"),
                    )
                    .reset_index()
                )
                weighted_unweighted["coverage_delta_weighted_minus_unweighted"] = (
                    weighted_unweighted["coverage_p05_p95_weighted"] - weighted_unweighted["coverage_p05_p95_unweighted"]
                )
                weighted_unweighted["avg_width_delta_weighted_minus_unweighted"] = (
                    weighted_unweighted["avg_width_weighted"] - weighted_unweighted["avg_width_unweighted"]
                )
                weighted_unweighted.to_csv(TABLE_DIR / "weighted_vs_unweighted_quantile_summary.csv", index=False)
                display(Markdown("### Weighted vs Unweighted Quantile Diagnostics"))
                display(weighted_unweighted)

            print(f"Quantile rows (weighted primary): {qdf.shape[0]:,}")
            """
        ),
        md(
            """
            ## 7. Metric explanations and calculations

            ### Group A: data quality and scenario integrity
            - Counts, missingness, duplicate keys, zero-spread rate, and extreme values.
            - Why: invalid or degenerate scenario structures can invalidate every later metric.

            ### Group B: pointwise interval coverage
            Coverage is computed against nominal levels:
            - `p25-p75` nominal 50%
            - `p10-p90` nominal 80%
            - `p05-p95` nominal 90%
            - `p025-p975` nominal 95%

            Calibration error = realised coverage - nominal coverage.

            Interpretation:
            - undercoverage: intervals too narrow and/or biased
            - overcoverage: intervals may be too wide and weakly informative
            - upper-tail undercoverage is especially risky for procurement exposure.

            ### Group C: sharpness / spread
            Width metrics:
            - mean and median width for 90% and 95% intervals
            - width profiles by lead day, period-of-day, and season
            - widths normalised by realised volatility/level.

            Sharpness is useful only if calibration is acceptable.

            ### Group D: interval scores (Winkler)
            For interval `[L, U]` with nominal `1-alpha`:
            `score = (U-L) + (2/alpha)*(L-y)*I(y<L) + (2/alpha)*(y-U)*I(y>U)`

            Lower is better: narrow but penalised when misses occur.

            ### Group E: distributional scores
            - CRPS from empirical scenarios (full distribution score)
            - pinball losses at q = 0.05, 0.10, 0.50, 0.90, 0.95
            - average pinball score.

            ### Group F: PIT / rank calibration
            PIT from ensemble rank share:
            `PIT = ( # {scenario <= y} ) / n` (randomized for ties).

            - U-shape: too narrow
            - hump-shape: too wide
            - skew: systematic bias.

            ### Group G: central forecast quality (mean/median of scenarios)
            - MAE, RMSE, bias, median AE, p90/p95 AE
            - Spearman and Pearson correlation
            - ramp MAE and ramp sign accuracy.

            These are secondary checks for scenario centre reasonableness.

            ### Group H: tail and event performance
            Events use realised quantiles within each model evaluation sample:
            - high: above p90 / p95
            - low: below p10 / p5

            We report tail representation, segment-wise MAE, and top/bottom-k hit rates.

            ### Group I: temporal/path diagnostics
            Daily diagnostics include:
            - daily inside-share
            - any-outside flags
            - max consecutive above/below exceedance runs
            - exceedance magnitudes and range mismatch.

            Emphasis: long same-sided exceedance clusters are more concerning than isolated misses.

            ### Group J: MILP readiness summary
            Rule-of-thumb thresholds (indicative, not absolute):
            - 90% coverage good in 87.5%-92.5%
            - p95 upper exceedance good in 3.5%-6.5%
            - wider warning/fail bands applied around these targets.
            """
        ),
        code(
            """
            def _coverage(y: pd.Series, low: pd.Series, high: pd.Series) -> float:
                m = y.notna() & low.notna() & high.notna()
                if not m.any():
                    return np.nan
                inside = (y[m] >= low[m]) & (y[m] <= high[m])
                return float(inside.mean())


            def _interval_score(y: pd.Series, low: pd.Series, high: pd.Series, alpha: float) -> pd.Series:
                yv = pd.to_numeric(y, errors="coerce")
                lv = pd.to_numeric(low, errors="coerce")
                uv = pd.to_numeric(high, errors="coerce")
                base = uv - lv
                below = (2.0 / alpha) * (lv - yv).clip(lower=0)
                above = (2.0 / alpha) * (yv - uv).clip(lower=0)
                return base + below + above


            def _pinball(y: pd.Series, qhat: pd.Series, q: float) -> pd.Series:
                e = pd.to_numeric(y, errors="coerce") - pd.to_numeric(qhat, errors="coerce")
                return np.where(e >= 0, q * e, (q - 1.0) * e)


            def _crps_from_ensemble(values: np.ndarray, y: float) -> float:
                x = np.asarray(values, dtype=float)
                x = x[np.isfinite(x)]
                if x.size == 0 or not np.isfinite(y):
                    return np.nan
                x.sort()
                m = x.size
                term1 = float(np.mean(np.abs(x - y)))
                coeff = (2 * np.arange(1, m + 1) - m - 1).astype(float)
                term2 = float(np.sum(coeff * x) / (m * m))
                return term1 - term2


            def _max_consecutive_true(mask: np.ndarray) -> int:
                max_run = 0
                run = 0
                for v in mask.astype(bool):
                    if v:
                        run += 1
                        max_run = max(max_run, run)
                    else:
                        run = 0
                return int(max_run)


            # ----------------------------
            # Group A: data quality
            # ----------------------------
            quality_rows = []
            for (mk, disp, gran), grp in scenarios.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                per_key = grp.groupby(["forecast_origin_utc", "delivery_start_utc"], dropna=False)["scenario_id"].nunique()
                qgrp = qdf[qdf["model_key"] == mk].copy()
                spread90 = pd.to_numeric(qgrp["p95"], errors="coerce") - pd.to_numeric(qgrp["p05"], errors="coerce")
                quality_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "n_scenario_rows": int(grp.shape[0]),
                        "n_unique_delivery_timestamps": int(grp["delivery_start_utc"].nunique(dropna=True)),
                        "n_unique_forecast_origins": int(grp["forecast_origin_utc"].nunique(dropna=True)),
                        "scenarios_per_origin_delivery_min": float(per_key.min()) if not per_key.empty else np.nan,
                        "scenarios_per_origin_delivery_mean": float(per_key.mean()) if not per_key.empty else np.nan,
                        "scenarios_per_origin_delivery_max": float(per_key.max()) if not per_key.empty else np.nan,
                        "missing_actual_rate": float(grp["y_true"].isna().mean()),
                        "missing_scenario_value_rate": float(grp["scenario_price"].isna().mean()),
                        "duplicate_scenario_rows": int(
                            grp.duplicated(subset=["model_key", "forecast_origin_utc", "delivery_start_utc", "scenario_id"], keep=False).sum()
                        ),
                        "duplicate_delivery_timestamps_after_aggregation": int(
                            qgrp.duplicated(
                                subset=["model_key", "forecast_origin_utc", "delivery_start_utc"],
                                keep=False,
                            ).sum()
                        ),
                        "zero_spread_rate_p95_p05": float((spread90.abs() <= 1e-9).mean()) if not qgrp.empty else np.nan,
                        "scenario_price_min": float(pd.to_numeric(grp["scenario_price"], errors="coerce").min()),
                        "scenario_price_max": float(pd.to_numeric(grp["scenario_price"], errors="coerce").max()),
                    }
                )
            data_quality_summary = pd.DataFrame(quality_rows).sort_values("model_name").reset_index(drop=True)

            # ----------------------------
            # Group B: calibration / coverage
            # ----------------------------
            cov_rows = []
            for (mk, disp, gran), grp in qdf.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                y = grp["y_true"]
                c50 = _coverage(y, grp["p25"], grp["p75"])
                c80 = _coverage(y, grp["p10"], grp["p90"])
                c90 = _coverage(y, grp["p05"], grp["p95"])
                c95 = _coverage(y, grp["p025"], grp["p975"])
                mask90 = y.notna() & grp["p05"].notna() & grp["p95"].notna()
                mask95 = y.notna() & grp["p025"].notna() & grp["p975"].notna()
                upper95 = float((y[mask90] > grp.loc[mask90, "p95"]).mean()) if mask90.any() else np.nan
                lower95 = float((y[mask90] < grp.loc[mask90, "p05"]).mean()) if mask90.any() else np.nan
                upper975 = float((y[mask95] > grp.loc[mask95, "p975"]).mean()) if mask95.any() else np.nan
                lower025 = float((y[mask95] < grp.loc[mask95, "p025"]).mean()) if mask95.any() else np.nan
                cov_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "n_scored_rows": int(y.notna().sum()),
                        "coverage_p25_p75": c50,
                        "coverage_p10_p90": c80,
                        "coverage_p05_p95": c90,
                        "coverage_p025_p975": c95,
                        "upper_exceed_rate_above_p95": upper95,
                        "lower_exceed_rate_below_p05": lower95,
                        "upper_exceed_rate_above_p975": upper975,
                        "lower_exceed_rate_below_p025": lower025,
                        "calibration_error_50": c50 - 0.50 if pd.notna(c50) else np.nan,
                        "calibration_error_80": c80 - 0.80 if pd.notna(c80) else np.nan,
                        "calibration_error_90": c90 - 0.90 if pd.notna(c90) else np.nan,
                        "calibration_error_95": c95 - 0.95 if pd.notna(c95) else np.nan,
                        "tail_imbalance_p95": (upper95 - lower95) if pd.notna(upper95) and pd.notna(lower95) else np.nan,
                    }
                )
            scenario_calibration_summary = pd.DataFrame(cov_rows).sort_values("model_name").reset_index(drop=True)

            # ----------------------------
            # Group C: sharpness
            # ----------------------------
            qdf["width_90"] = pd.to_numeric(qdf["p95"], errors="coerce") - pd.to_numeric(qdf["p05"], errors="coerce")
            qdf["width_95"] = pd.to_numeric(qdf["p975"], errors="coerce") - pd.to_numeric(qdf["p025"], errors="coerce")
            qdf["abs_price_level"] = pd.to_numeric(qdf["y_true"], errors="coerce").abs()

            sharp_rows = []
            width_profiles = []
            for (mk, disp, gran), grp in qdf.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                valid = grp[grp["y_true"].notna()].copy()
                realised_std = float(pd.to_numeric(valid["y_true"], errors="coerce").std()) if not valid.empty else np.nan
                sharp_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "mean_width_90": float(valid["width_90"].mean()) if not valid.empty else np.nan,
                        "median_width_90": float(valid["width_90"].median()) if not valid.empty else np.nan,
                        "mean_width_95": float(valid["width_95"].mean()) if not valid.empty else np.nan,
                        "median_width_95": float(valid["width_95"].median()) if not valid.empty else np.nan,
                        "width_90_over_realised_std": float(valid["width_90"].mean() / realised_std) if valid.shape[0] and realised_std not in (0, np.nan) else np.nan,
                        "width_95_over_realised_std": float(valid["width_95"].mean() / realised_std) if valid.shape[0] and realised_std not in (0, np.nan) else np.nan,
                        "width_90_over_abs_level": float((valid["width_90"] / valid["abs_price_level"].clip(lower=1e-6)).median()) if not valid.empty else np.nan,
                    }
                )

                period_col = "hour_of_day" if gran == "hourly" else "quarter_of_day"
                prof_period = (
                    valid.groupby(period_col, dropna=False)[["width_90", "width_95"]]
                    .mean()
                    .reset_index()
                    .assign(profile_type="period_of_day", model_key=mk, model_name=disp, granularity=gran)
                )
                prof_lead = (
                    valid.groupby("lead_day", dropna=False)[["width_90", "width_95"]]
                    .mean()
                    .reset_index()
                    .assign(profile_type="lead_day", model_key=mk, model_name=disp, granularity=gran)
                )
                prof_month = (
                    valid.groupby("month", dropna=False)[["width_90", "width_95"]]
                    .mean()
                    .reset_index()
                    .assign(profile_type="month", model_key=mk, model_name=disp, granularity=gran)
                )
                width_profiles.extend([prof_period, prof_lead, prof_month])

            sharpness_summary = pd.DataFrame(sharp_rows).sort_values("model_name").reset_index(drop=True)
            width_profile_table = pd.concat(width_profiles, ignore_index=True) if width_profiles else pd.DataFrame()

            # ----------------------------
            # Group D: interval scores
            # ----------------------------
            interval_rows = []
            for (mk, disp, gran), grp in qdf.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                valid = grp[grp["y_true"].notna()].copy()
                if valid.empty:
                    interval_rows.append({"model_key": mk, "model_name": disp, "granularity": gran, "interval_score_90_mean": np.nan, "interval_score_95_mean": np.nan})
                    continue
                s90 = _interval_score(valid["y_true"], valid["p05"], valid["p95"], alpha=0.10)
                s95 = _interval_score(valid["y_true"], valid["p025"], valid["p975"], alpha=0.05)
                interval_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "interval_score_90_mean": float(pd.Series(s90).mean()),
                        "interval_score_95_mean": float(pd.Series(s95).mean()),
                    }
                )
            scenario_interval_scores = pd.DataFrame(interval_rows).sort_values("model_name").reset_index(drop=True)

            # ----------------------------
            # Group E/F: distributional scores and PIT
            # ----------------------------
            score_key_cols = ["model_key", "forecast_origin_utc", "delivery_start_utc"]
            scenarios_valid = scenarios[scenarios["delivery_start_utc"].notna()].copy()

            # CRPS
            crps_rows = []
            for (mk, fo, de), grp in scenarios_valid.groupby(score_key_cols, dropna=False):
                y_vals = pd.to_numeric(grp["y_true"], errors="coerce")
                y = float(y_vals.dropna().iloc[0]) if y_vals.notna().any() else np.nan
                crps = _crps_from_ensemble(pd.to_numeric(grp["scenario_price"], errors="coerce").to_numpy(dtype=float), y)
                crps_rows.append({"model_key": mk, "forecast_origin_utc": fo, "delivery_start_utc": de, "crps": crps, "y_true": y})
            crps_df = pd.DataFrame(crps_rows)

            # Pinball on quantiles
            pin_levels = [0.05, 0.10, 0.50, 0.90, 0.95]
            pin_col = {0.05: "p05", 0.10: "p10", 0.50: "p50", 0.90: "p90", 0.95: "p95"}
            pin_rows = []
            valid_q = qdf[qdf["y_true"].notna()].copy()
            for q in pin_levels:
                losses = _pinball(valid_q["y_true"], valid_q[pin_col[q]], q)
                tmp = valid_q[["model_key", "model_display_name", "granularity"]].copy()
                tmp["q"] = q
                tmp["pinball"] = losses
                pin_rows.append(tmp)
            pin_df = pd.concat(pin_rows, ignore_index=True) if pin_rows else pd.DataFrame()
            pin_summary = (
                pin_df.groupby(["model_key", "model_display_name", "granularity", "q"], dropna=False)["pinball"]
                .mean()
                .reset_index()
            ) if not pin_df.empty else pd.DataFrame()
            pin_wide = pin_summary.pivot_table(
                index=["model_key", "model_display_name", "granularity"],
                columns="q",
                values="pinball",
                aggfunc="mean",
            ).reset_index() if not pin_summary.empty else pd.DataFrame()
            if not pin_wide.empty:
                pin_wide = pin_wide.rename(columns={0.05: "pinball_q05", 0.10: "pinball_q10", 0.50: "pinball_q50", 0.90: "pinball_q90", 0.95: "pinball_q95"})
                pin_wide["pinball_avg_q05_q10_q50_q90_q95"] = pin_wide[["pinball_q05", "pinball_q10", "pinball_q50", "pinball_q90", "pinball_q95"]].mean(axis=1)

            # PIT
            pit_seed = np.random.default_rng(42)
            pit_work = scenarios_valid[scenarios_valid["y_true"].notna()].copy()
            pit_work["lt"] = (pd.to_numeric(pit_work["scenario_price"], errors="coerce") < pd.to_numeric(pit_work["y_true"], errors="coerce")).astype(int)
            pit_work["eq"] = (pd.to_numeric(pit_work["scenario_price"], errors="coerce") == pd.to_numeric(pit_work["y_true"], errors="coerce")).astype(int)
            pit_grp = (
                pit_work.groupby(score_key_cols, dropna=False)
                .agg(
                    less=("lt", "sum"),
                    equal=("eq", "sum"),
                    n=("scenario_price", "size"),
                    model_display_name=("model_display_name", "first"),
                    granularity=("granularity", "first"),
                )
                .reset_index()
            )
            pit_grp["u"] = pit_seed.random(pit_grp.shape[0])
            pit_grp["pit"] = (pit_grp["less"] + pit_grp["u"] * pit_grp["equal"]) / pit_grp["n"].replace(0, np.nan)

            pit_summary = (
                pit_grp.groupby(["model_key", "model_display_name", "granularity"], dropna=False)
                .agg(
                    pit_mean=("pit", "mean"),
                    pit_median=("pit", "median"),
                    pit_share_below_0_05=("pit", lambda s: float((s < 0.05).mean())),
                    pit_share_above_0_95=("pit", lambda s: float((s > 0.95).mean())),
                    pit_uniform_ks_distance=("pit", lambda s: float(np.max(np.abs(np.sort(s.to_numpy()) - np.linspace(0, 1, len(s), endpoint=False)))) if len(s) else np.nan),
                )
                .reset_index()
            )

            # Merge CRPS + pinball + PIT
            crps_summary = (
                crps_df[crps_df["y_true"].notna()]
                .groupby("model_key", dropna=False)["crps"]
                .mean()
                .reset_index()
                .rename(columns={"crps": "crps_mean"})
            )
            distribution_scores = scenario_calibration_summary[["model_key", "model_name", "granularity"]].copy()
            distribution_scores = distribution_scores.merge(crps_summary, on="model_key", how="left")
            if not pin_wide.empty:
                distribution_scores = distribution_scores.merge(
                    pin_wide.rename(columns={"model_display_name": "model_name"}),
                    on=["model_key", "model_name", "granularity"],
                    how="left",
                )
            distribution_scores = distribution_scores.merge(
                pit_summary.rename(columns={"model_display_name": "model_name"}),
                on=["model_key", "model_name", "granularity"],
                how="left",
            )

            # ----------------------------
            # Group G: central forecast metrics
            # ----------------------------
            central_rows = []
            for center_col, center_name in [("scenario_mean", "scenario_mean"), ("p50", "scenario_median")]:
                for (mk, disp, gran), grp in qdf.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                    valid = grp[grp["y_true"].notna() & grp[center_col].notna()].copy()
                    if valid.empty:
                        central_rows.append({"model_key": mk, "model_name": disp, "granularity": gran, "central_type": center_name})
                        continue
                    err = pd.to_numeric(valid[center_col], errors="coerce") - pd.to_numeric(valid["y_true"], errors="coerce")
                    ae = err.abs()

                    pearson = np.nan
                    spearman = np.nan
                    if valid.shape[0] >= 3:
                        pearson = float(valid[["y_true", center_col]].corr(method="pearson").iloc[0, 1])
                        spearman = float(valid[["y_true", center_col]].corr(method="spearman").iloc[0, 1])

                    ramp_df = valid.sort_values(["forecast_origin_utc", "delivery_start_utc"]).copy()
                    ramp_df["dy_true"] = ramp_df.groupby("forecast_origin_utc", dropna=False)["y_true"].diff()
                    ramp_df["dy_pred"] = ramp_df.groupby("forecast_origin_utc", dropna=False)[center_col].diff()
                    ramp_valid = ramp_df[ramp_df["dy_true"].notna() & ramp_df["dy_pred"].notna()].copy()
                    ramp_mae = float((ramp_valid["dy_true"] - ramp_valid["dy_pred"]).abs().mean()) if not ramp_valid.empty else np.nan
                    ramp_sign_acc = float((np.sign(ramp_valid["dy_true"]) == np.sign(ramp_valid["dy_pred"])).mean()) if not ramp_valid.empty else np.nan

                    central_rows.append(
                        {
                            "model_key": mk,
                            "model_name": disp,
                            "granularity": gran,
                            "central_type": center_name,
                            "mae": float(ae.mean()),
                            "rmse": float(np.sqrt(np.mean(np.square(err)))),
                            "bias": float(err.mean()),
                            "median_absolute_error": float(ae.median()),
                            "p90_absolute_error": float(ae.quantile(0.90)),
                            "p95_absolute_error": float(ae.quantile(0.95)),
                            "spearman_correlation": spearman,
                            "pearson_correlation": pearson,
                            "ramp_mae": ramp_mae,
                            "ramp_sign_accuracy": ramp_sign_acc,
                        }
                    )
            central_metrics = pd.DataFrame(central_rows).sort_values(["model_name", "central_type"]).reset_index(drop=True)

            # ----------------------------
            # Group H: tail/events
            # ----------------------------
            tail_rows = []
            topk_rows = []
            for (mk, disp, gran), grp in qdf.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                valid = grp[grp["y_true"].notna()].copy()
                if valid.empty:
                    tail_rows.append({"model_key": mk, "model_name": disp, "granularity": gran})
                    continue

                y = pd.to_numeric(valid["y_true"], errors="coerce")
                q05, q10, q90, q95 = y.quantile([0.05, 0.10, 0.90, 0.95]).tolist()
                high90 = y > q90
                high95 = y > q95
                low10 = y < q10
                low05 = y < q05

                k = 4 if gran == "hourly" else 16
                daily_keys = ["forecast_origin_utc", "delivery_local_date"]
                hr_top, hr_bottom, n_days = [], [], 0
                for _, dayg in valid.groupby(daily_keys, dropna=False):
                    dg = dayg.dropna(subset=["y_true", "scenario_mean", "delivery_start_utc"]).sort_values("delivery_start_utc")
                    if dg.shape[0] < k:
                        continue
                    n_days += 1
                    actual_top = set(dg.nlargest(k, "y_true")["delivery_start_utc"].tolist())
                    pred_top = set(dg.nlargest(k, "scenario_mean")["delivery_start_utc"].tolist())
                    actual_bottom = set(dg.nsmallest(k, "y_true")["delivery_start_utc"].tolist())
                    pred_bottom = set(dg.nsmallest(k, "scenario_mean")["delivery_start_utc"].tolist())
                    hr_top.append(len(actual_top & pred_top) / float(k))
                    hr_bottom.append(len(actual_bottom & pred_bottom) / float(k))
                topk_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "topk_k": k,
                        "n_days_used": n_days,
                        "topk_hit_rate": float(np.mean(hr_top)) if hr_top else np.nan,
                        "bottomk_hit_rate": float(np.mean(hr_bottom)) if hr_bottom else np.nan,
                    }
                )

                # Segment MAE on scenario mean.
                mean_err = (valid["scenario_mean"] - valid["y_true"]).abs()
                tail_rows.append(
                    {
                        "model_key": mk,
                        "model_name": disp,
                        "granularity": gran,
                        "realised_q05": q05,
                        "realised_q10": q10,
                        "realised_q90": q90,
                        "realised_q95": q95,
                        "high_event_above_p90_share": float(high90.mean()),
                        "high_event_above_p95_share": float(high95.mean()),
                        "low_event_below_p10_share": float(low10.mean()),
                        "low_event_below_p05_share": float(low05.mean()),
                        "high90_inside_upper95_rate": float((valid.loc[high90, "y_true"] <= valid.loc[high90, "p95"]).mean()) if high90.any() else np.nan,
                        "high95_inside_upper975_rate": float((valid.loc[high95, "y_true"] <= valid.loc[high95, "p975"]).mean()) if high95.any() else np.nan,
                        "low10_inside_lower05_rate": float((valid.loc[low10, "y_true"] >= valid.loc[low10, "p05"]).mean()) if low10.any() else np.nan,
                        "low05_inside_lower025_rate": float((valid.loc[low05, "y_true"] >= valid.loc[low05, "p025"]).mean()) if low05.any() else np.nan,
                        "tail_mae_top10_mean": float(mean_err[high90].mean()) if high90.any() else np.nan,
                        "tail_mae_bottom10_mean": float(mean_err[low10].mean()) if low10.any() else np.nan,
                        "tail_mae_middle80_mean": float(mean_err[~(high90 | low10)].mean()) if (~(high90 | low10)).any() else np.nan,
                    }
                )
            scenario_tail_event_summary = pd.DataFrame(tail_rows).merge(
                pd.DataFrame(topk_rows),
                on=["model_key", "model_name", "granularity"],
                how="left",
            )

            # ----------------------------
            # Group I: temporal/path diagnostics
            # ----------------------------
            daily_rows = []
            for (mk, disp, gran), grp in qdf.groupby(["model_key", "model_display_name", "granularity"], dropna=False):
                valid = grp[grp["y_true"].notna()].copy()
                for (fo, day), dayg in valid.groupby(["forecast_origin_utc", "delivery_local_date"], dropna=False):
                    dg = dayg.sort_values("delivery_start_utc").copy()
                    lead_day_value = pd.to_numeric(dg["lead_day"], errors="coerce").dropna()
                    split_value = dg["dataset_split"].dropna().astype(str)
                    inside90 = (dg["y_true"] >= dg["p05"]) & (dg["y_true"] <= dg["p95"])
                    inside95 = (dg["y_true"] >= dg["p025"]) & (dg["y_true"] <= dg["p975"])
                    above95 = dg["y_true"] > dg["p95"]
                    below05 = dg["y_true"] < dg["p05"]

                    exceed_above_mag = (dg["y_true"] - dg["p95"]).where(above95, 0.0).sum()
                    exceed_below_mag = (dg["p05"] - dg["y_true"]).where(below05, 0.0).sum()

                    actual_range = float(dg["y_true"].max() - dg["y_true"].min()) if dg["y_true"].notna().any() else np.nan
                    band_range = float(dg["p95"].max() - dg["p05"].min()) if dg["p95"].notna().any() and dg["p05"].notna().any() else np.nan

                    dy_actual = dg["y_true"].diff()
                    dy_mean = dg["scenario_mean"].diff()
                    ramp_spread = (dg["p95"].diff() - dg["p05"].diff()).abs()

                    daily_rows.append(
                        {
                            "model_key": mk,
                            "model_name": disp,
                            "granularity": gran,
                            "forecast_origin_utc": fo,
                            "delivery_local_date": day,
                            "dataset_split": str(split_value.iloc[0]) if not split_value.empty else "unknown",
                            "lead_day": int(lead_day_value.iloc[0]) if not lead_day_value.empty else pd.NA,
                            "n_periods": int(dg.shape[0]),
                            "share_inside_p05_p95": float(inside90.mean()),
                            "share_inside_p025_p975": float(inside95.mean()),
                            "any_outside_p05_p95": bool((~inside90).any()),
                            "max_consecutive_above_p95": _max_consecutive_true(above95.to_numpy()),
                            "max_consecutive_below_p05": _max_consecutive_true(below05.to_numpy()),
                            "total_exceedance_above_p95": float(exceed_above_mag),
                            "total_exceedance_below_p05": float(exceed_below_mag),
                            "total_exceedance_magnitude": float(exceed_above_mag + exceed_below_mag),
                            "actual_daily_range": actual_range,
                            "scenario_p05_p95_daily_range": band_range,
                            "range_gap_actual_minus_band": float(actual_range - band_range) if pd.notna(actual_range) and pd.notna(band_range) else np.nan,
                            "actual_max_abs_ramp": float(dy_actual.abs().max()) if dy_actual.notna().any() else np.nan,
                            "scenario_mean_max_abs_ramp": float(dy_mean.abs().max()) if dy_mean.notna().any() else np.nan,
                            "scenario_ramp_spread_proxy": float(ramp_spread.max()) if ramp_spread.notna().any() else np.nan,
                        }
                    )

            daily_temporal = pd.DataFrame(daily_rows)
            scenario_temporal_diagnostics = (
                daily_temporal.groupby(["model_key", "model_name", "granularity"], dropna=False)
                .agg(
                    days=("delivery_local_date", "nunique"),
                    mean_share_inside_p05_p95=("share_inside_p05_p95", "mean"),
                    mean_share_inside_p025_p975=("share_inside_p025_p975", "mean"),
                    any_outside_day_rate_p05_p95=("any_outside_p05_p95", "mean"),
                    mean_max_consecutive_above_p95=("max_consecutive_above_p95", "mean"),
                    mean_max_consecutive_below_p05=("max_consecutive_below_p05", "mean"),
                    mean_total_exceedance_above_p95=("total_exceedance_above_p95", "mean"),
                    mean_total_exceedance_below_p05=("total_exceedance_below_p05", "mean"),
                    mean_total_exceedance_magnitude=("total_exceedance_magnitude", "mean"),
                    mean_range_gap_actual_minus_band=("range_gap_actual_minus_band", "mean"),
                )
                .reset_index()
                .sort_values("model_name")
                .reset_index(drop=True)
            )

            # ----------------------------
            # Group J: MILP readiness (rule-of-thumb)
            # ----------------------------
            readiness = scenario_calibration_summary.merge(
                sharpness_summary[["model_key", "width_90_over_realised_std"]],
                on="model_key",
                how="left",
            ).merge(
                scenario_temporal_diagnostics[
                    [
                        "model_key",
                        "mean_max_consecutive_above_p95",
                        "mean_max_consecutive_below_p05",
                    ]
                ],
                on="model_key",
                how="left",
            )

            def classify_coverage90(v: float) -> str:
                if pd.isna(v):
                    return "fail"
                if 0.875 <= v <= 0.925:
                    return "yes"
                if (0.85 <= v < 0.875) or (0.925 < v <= 0.95):
                    return "warning"
                return "fail"


            def classify_exceed(v: float) -> str:
                if pd.isna(v):
                    return "fail"
                if 0.035 <= v <= 0.065:
                    return "yes"
                if (0.025 <= v < 0.035) or (0.065 < v <= 0.08):
                    return "warning"
                return "fail"


            def classify_width(v: float) -> str:
                if pd.isna(v):
                    return "warning"
                if v < 0.8:
                    return "fail"
                if v > 3.5:
                    return "fail"
                if v > 2.5:
                    return "warning"
                return "yes"


            def classify_temporal(a: float, b: float) -> str:
                if pd.isna(a) or pd.isna(b):
                    return "warning"
                worst = max(float(a), float(b))
                if worst <= 2:
                    return "yes"
                if worst <= 4:
                    return "warning"
                return "fail"


            readiness["coverage_acceptable"] = readiness["coverage_p05_p95"].map(classify_coverage90)
            readiness["upper_tail_risk_represented"] = readiness["upper_exceed_rate_above_p95"].map(classify_exceed)
            readiness["lower_tail_opportunity_represented"] = readiness["lower_exceed_rate_below_p05"].map(classify_exceed)
            readiness["scenario_spread_too_narrow_or_wide"] = readiness["width_90_over_realised_std"].map(classify_width)
            readiness["temporal_coherence_acceptable"] = readiness.apply(
                lambda r: classify_temporal(r["mean_max_consecutive_above_p95"], r["mean_max_consecutive_below_p05"]),
                axis=1,
            )

            def _recommend(row: pd.Series) -> str:
                flags = [
                    row["coverage_acceptable"],
                    row["upper_tail_risk_represented"],
                    row["lower_tail_opportunity_represented"],
                    row["scenario_spread_too_narrow_or_wide"],
                    row["temporal_coherence_acceptable"],
                ]
                if all(v == "yes" for v in flags):
                    return "acceptable as-is"
                if "fail" not in flags:
                    return "acceptable with caution"
                if row["coverage_acceptable"] == "fail" and row["scenario_spread_too_narrow_or_wide"] in {"fail", "warning"}:
                    return "recalibrate/widen residuals"
                if row["upper_tail_risk_represented"] == "fail" or row["lower_tail_opportunity_represented"] == "fail":
                    return "add tail/stress scenarios"
                if row["temporal_coherence_acceptable"] == "fail":
                    return "improve temporal dependence / block sampling"
                return "inspect scenario-generation methodology"

            readiness["recommended_use"] = readiness.apply(_recommend, axis=1)
            scenario_milp_readiness_summary = readiness[
                [
                    "model_key",
                    "model_name",
                    "granularity",
                    "coverage_acceptable",
                    "upper_tail_risk_represented",
                    "lower_tail_opportunity_represented",
                    "scenario_spread_too_narrow_or_wide",
                    "temporal_coherence_acceptable",
                    "recommended_use",
                ]
            ].copy()

            # Save required tables.
            scenario_calibration_summary.to_csv(TABLE_DIR / "scenario_calibration_summary.csv", index=False)
            scenario_interval_scores.to_csv(TABLE_DIR / "scenario_interval_scores.csv", index=False)
            distribution_scores.to_csv(TABLE_DIR / "scenario_distribution_scores.csv", index=False)
            scenario_tail_event_summary.to_csv(TABLE_DIR / "scenario_tail_event_summary.csv", index=False)
            scenario_temporal_diagnostics.to_csv(TABLE_DIR / "scenario_temporal_diagnostics.csv", index=False)
            scenario_milp_readiness_summary.to_csv(TABLE_DIR / "scenario_milp_readiness_summary.csv", index=False)
            data_quality_summary.to_csv(TABLE_DIR / "scenario_data_quality_summary.csv", index=False)
            central_metrics.to_csv(TABLE_DIR / "scenario_central_metrics.csv", index=False)
            daily_temporal.to_csv(TABLE_DIR / "scenario_daily_temporal_diagnostics.csv", index=False)
            pit_grp.to_csv(TABLE_DIR / "scenario_pit_values.csv", index=False)

            display(Markdown("### Calibration Summary"))
            display(scenario_calibration_summary)
            display(Markdown("### MILP Readiness Summary"))
            display(scenario_milp_readiness_summary)
            """
        ),
        md(
            """
            ## 8. Visual diagnostics
            Per model/granularity, the notebook writes:
            - coverage bars (50/80/90/95 vs nominal),
            - upper/lower exceedance bars,
            - width by lead day,
            - width by hour-of-day or quarter-of-day,
            - PIT histogram,
            - objective-week band plots (actual, p05-p95, p025-p975, p50, mean),
            - worst undercoverage / upper-tail miss / lower-tail miss day plots.

            A summary heatmap is also saved across models.
            """
        ),
        code(
            """
            def _sanitize_filename(text: str) -> str:
                return re.sub(r"[^A-Za-z0-9_\\-]+", "_", text).strip("_")


            # Helper: objective weeks from lead-day 0 test sample.
            def select_objective_weeks(model_frame: pd.DataFrame) -> dict[str, pd.Timestamp]:
                sample = model_frame[
                    (model_frame["dataset_split"].astype(str) == "test")
                    & (pd.to_numeric(model_frame["lead_day"], errors="coerce") == 0)
                    & model_frame["y_true"].notna()
                ].copy()
                if sample.empty:
                    return {}
                sample["local_ts"] = sample["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam")
                sample = sample.drop_duplicates("delivery_start_utc").sort_values("delivery_start_utc")
                local_naive = sample["local_ts"].dt.tz_localize(None)
                sample["week_start"] = local_naive.dt.to_period("W-MON").dt.start_time
                weekly = (
                    sample.groupby("week_start")
                    .agg(
                        std_price=("y_true", "std"),
                        mean_price=("y_true", "mean"),
                        month=("local_ts", lambda s: int(s.dt.month.iloc[0])),
                    )
                    .reset_index()
                )
                if weekly.empty:
                    return {}

                out: dict[str, pd.Timestamp] = {}
                winter = weekly[weekly["month"].isin([12, 1, 2])].copy()
                summer = weekly[weekly["month"].isin([6, 7, 8])].copy()
                if not winter.empty:
                    med = winter["std_price"].median()
                    out["typical_winter"] = pd.Timestamp(winter.iloc[(winter["std_price"] - med).abs().argmin()]["week_start"])
                if not summer.empty:
                    med = summer["std_price"].median()
                    out["typical_summer"] = pd.Timestamp(summer.iloc[(summer["std_price"] - med).abs().argmin()]["week_start"])
                out["high_volatility"] = pd.Timestamp(weekly.iloc[weekly["std_price"].argmax()]["week_start"])
                return out


            def plot_band_week(df_week: pd.DataFrame, title: str, out_path: Path) -> None:
                fig, ax = plt.subplots(figsize=(14, 5))
                x = df_week["delivery_start_utc"]
                ax.fill_between(x, df_week["p025"], df_week["p975"], alpha=0.20, label="p025-p975")
                ax.fill_between(x, df_week["p05"], df_week["p95"], alpha=0.35, label="p05-p95")
                ax.plot(x, df_week["y_true"], linewidth=1.8, label="actual")
                ax.plot(x, df_week["p50"], linewidth=1.2, label="p50")
                ax.plot(x, df_week["scenario_mean"], linewidth=1.2, label="scenario_mean")
                ax.set_title(title)
                ax.set_ylabel("EUR/MWh")
                ax.legend(loc="best", ncol=3)
                ax.grid(alpha=0.3)
                fig.tight_layout()
                fig.savefig(out_path, dpi=150)
                plt.close(fig)


            def plot_day_band(df_day: pd.DataFrame, title: str, out_path: Path) -> None:
                fig, ax = plt.subplots(figsize=(12, 4))
                x = df_day["delivery_start_utc"]
                ax.fill_between(x, df_day["p05"], df_day["p95"], alpha=0.35, label="p05-p95")
                ax.fill_between(x, df_day["p025"], df_day["p975"], alpha=0.20, label="p025-p975")
                ax.plot(x, df_day["y_true"], linewidth=1.6, label="actual")
                ax.plot(x, df_day["scenario_mean"], linewidth=1.1, label="scenario_mean")
                ax.plot(x, df_day["p50"], linewidth=1.1, label="p50")
                ax.set_title(title)
                ax.set_ylabel("EUR/MWh")
                ax.legend(loc="best", ncol=3)
                ax.grid(alpha=0.3)
                fig.tight_layout()
                fig.savefig(out_path, dpi=150)
                plt.close(fig)


            # Main per-model plotting loop.
            for _, mrow in scenario_calibration_summary.sort_values("model_name").iterrows():
                mk = mrow["model_key"]
                mname = mrow["model_name"]
                gran = mrow["granularity"]
                safe = _sanitize_filename(f"{mk}_{gran}")
                mdir = FIG_DIR / safe
                mdir.mkdir(parents=True, exist_ok=True)

                qsub = qdf[qdf["model_key"] == mk].copy()
                if qsub.empty:
                    continue

                # 1) Coverage bar chart.
                cov_names = ["50%", "80%", "90%", "95%"]
                cov_vals = [
                    float(mrow["coverage_p25_p75"]) if pd.notna(mrow["coverage_p25_p75"]) else np.nan,
                    float(mrow["coverage_p10_p90"]) if pd.notna(mrow["coverage_p10_p90"]) else np.nan,
                    float(mrow["coverage_p05_p95"]) if pd.notna(mrow["coverage_p05_p95"]) else np.nan,
                    float(mrow["coverage_p025_p975"]) if pd.notna(mrow["coverage_p025_p975"]) else np.nan,
                ]
                nominal = [0.50, 0.80, 0.90, 0.95]
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.bar(cov_names, cov_vals, alpha=0.8, label="realised")
                ax.plot(cov_names, nominal, color="black", marker="o", linewidth=1.2, label="nominal")
                ax.set_ylim(0, 1.0)
                ax.set_title(f"Coverage: {mname}")
                ax.set_ylabel("Coverage")
                ax.grid(alpha=0.3, axis="y")
                ax.legend()
                fig.tight_layout()
                fig.savefig(mdir / "coverage_bars.png", dpi=150)
                plt.close(fig)

                # 2) Exceedance bars.
                exc_names = ["Above p95", "Below p05", "Above p975", "Below p025"]
                exc_vals = [
                    mrow["upper_exceed_rate_above_p95"],
                    mrow["lower_exceed_rate_below_p05"],
                    mrow["upper_exceed_rate_above_p975"],
                    mrow["lower_exceed_rate_below_p025"],
                ]
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.bar(exc_names, exc_vals, alpha=0.85)
                ax.axhline(0.05, color="black", linewidth=1.0, linestyle="--")
                ax.set_ylim(0, max(0.12, np.nanmax(exc_vals) * 1.2 if np.isfinite(np.nanmax(exc_vals)) else 0.12))
                ax.set_title(f"Exceedance: {mname}")
                ax.set_ylabel("Rate")
                ax.grid(alpha=0.3, axis="y")
                fig.tight_layout()
                fig.savefig(mdir / "exceedance_bars.png", dpi=150)
                plt.close(fig)

                # 3) Width by lead day.
                lead = (
                    qsub[qsub["y_true"].notna()]
                    .groupby("lead_day", dropna=False)[["width_90", "width_95"]]
                    .mean()
                    .reset_index()
                    .sort_values("lead_day")
                )
                if not lead.empty:
                    fig, ax = plt.subplots(figsize=(7, 4))
                    ax.plot(lead["lead_day"], lead["width_90"], marker="o", label="mean width p05-p95")
                    ax.plot(lead["lead_day"], lead["width_95"], marker="o", label="mean width p025-p975")
                    ax.set_title(f"Interval Width by Lead Day: {mname}")
                    ax.set_xlabel("Lead day")
                    ax.set_ylabel("Width (EUR/MWh)")
                    ax.grid(alpha=0.3)
                    ax.legend()
                    fig.tight_layout()
                    fig.savefig(mdir / "width_by_lead_day.png", dpi=150)
                    plt.close(fig)

                # 4) Width by hour/quarter of day.
                period_col = "hour_of_day" if gran == "hourly" else "quarter_of_day"
                pod = (
                    qsub[qsub["y_true"].notna()]
                    .groupby(period_col, dropna=False)[["width_90", "width_95"]]
                    .mean()
                    .reset_index()
                    .sort_values(period_col)
                )
                if not pod.empty:
                    fig, ax = plt.subplots(figsize=(9, 4))
                    ax.plot(pod[period_col], pod["width_90"], linewidth=1.3, label="width p05-p95")
                    ax.plot(pod[period_col], pod["width_95"], linewidth=1.3, label="width p025-p975")
                    ax.set_title(f"Interval Width by Period of Day: {mname}")
                    ax.set_xlabel("Hour of day" if gran == "hourly" else "Quarter of day")
                    ax.set_ylabel("Width (EUR/MWh)")
                    ax.grid(alpha=0.3)
                    ax.legend()
                    fig.tight_layout()
                    fig.savefig(mdir / "width_by_period_of_day.png", dpi=150)
                    plt.close(fig)

                # 5) PIT histogram.
                pit_sub = pit_grp[pit_grp["model_key"] == mk].copy()
                if not pit_sub.empty:
                    fig, ax = plt.subplots(figsize=(7, 4))
                    ax.hist(pit_sub["pit"].dropna(), bins=20, alpha=0.85, edgecolor="black")
                    ax.axhline(len(pit_sub) / 20.0, color="black", linestyle="--", linewidth=1.0)
                    ax.set_title(f"PIT Histogram: {mname}")
                    ax.set_xlabel("PIT")
                    ax.set_ylabel("Count")
                    ax.grid(alpha=0.25)
                    fig.tight_layout()
                    fig.savefig(mdir / "pit_histogram.png", dpi=150)
                    plt.close(fig)

                # 6) Band plots for objective weeks.
                weeks = select_objective_weeks(qsub)
                lead0 = qsub[
                    (qsub["dataset_split"].astype(str) == "test")
                    & (pd.to_numeric(qsub["lead_day"], errors="coerce") == 0)
                ].copy()
                lead0 = lead0.drop_duplicates("delivery_start_utc").sort_values("delivery_start_utc")
                for label, wstart in weeks.items():
                    wend = wstart + pd.Timedelta(days=7)
                    wk = lead0[
                        (lead0["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam").dt.tz_localize(None) >= wstart)
                        & (lead0["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam").dt.tz_localize(None) < wend)
                    ].copy()
                    if wk.empty:
                        continue
                    plot_band_week(
                        wk,
                        title=f"{mname} | {label.replace('_', ' ').title()}",
                        out_path=mdir / f"band_{label}.png",
                    )

                # 7/8/9) Worst-day diagnostics.
                dsub = daily_temporal[
                    (daily_temporal["model_key"] == mk)
                    & (daily_temporal["dataset_split"].astype(str) == "test")
                    & (pd.to_numeric(daily_temporal["lead_day"], errors="coerce") == 0)
                ].copy()
                q_day = qsub[
                    (qsub["dataset_split"].astype(str) == "test")
                    & (pd.to_numeric(qsub["lead_day"], errors="coerce") == 0)
                ].copy()
                if not dsub.empty and not q_day.empty:
                    # undercoverage days
                    top_under = dsub.sort_values("total_exceedance_magnitude", ascending=False).head(5)
                    top_up = dsub.sort_values("total_exceedance_above_p95", ascending=False).head(5)
                    top_low = dsub.sort_values("total_exceedance_below_p05", ascending=False).head(5)

                    for tag, table in [
                        ("worst_undercoverage", top_under),
                        ("worst_upper_tail_miss", top_up),
                        ("worst_lower_tail_miss", top_low),
                    ]:
                        for i, row in table.reset_index(drop=True).iterrows():
                            day = row["delivery_local_date"]
                            origin = row["forecast_origin_utc"]
                            dayf = q_day[
                                (q_day["delivery_local_date"] == day)
                                & (q_day["forecast_origin_utc"] == origin)
                            ].sort_values("delivery_start_utc")
                            if dayf.empty:
                                continue
                            plot_day_band(
                                dayf,
                                title=f"{mname} | {tag} #{i+1} | {day}",
                                out_path=mdir / f"{tag}_{i+1}.png",
                            )

            # 10) Summary heatmap across models.
            heat = scenario_calibration_summary.merge(
                sharpness_summary[["model_key", "mean_width_90"]],
                on="model_key",
                how="left",
            ).merge(
                distribution_scores[["model_key", "crps_mean"]],
                on="model_key",
                how="left",
            )
            heat = heat[
                [
                    "model_name",
                    "coverage_p05_p95",
                    "coverage_p025_p975",
                    "upper_exceed_rate_above_p95",
                    "lower_exceed_rate_below_p05",
                    "mean_width_90",
                    "crps_mean",
                ]
            ].copy()
            heat = heat.set_index("model_name")
            if not heat.empty:
                z = (heat - heat.mean()) / heat.std(ddof=0).replace(0, np.nan)
                fig, ax = plt.subplots(figsize=(10, max(4, 0.6 * heat.shape[0])))
                im = ax.imshow(z.fillna(0).to_numpy(), aspect="auto")
                ax.set_xticks(range(heat.shape[1]))
                ax.set_xticklabels(heat.columns, rotation=30, ha="right")
                ax.set_yticks(range(heat.shape[0]))
                ax.set_yticklabels(heat.index)
                ax.set_title("Scenario Metric Heatmap (z-score scaled)")
                fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
                fig.tight_layout()
                fig.savefig(FIG_DIR / "scenario_summary_heatmap.png", dpi=150)
                plt.close(fig)
            """
        ),
        md(
            """
            ## 9. P0/P1 methodology compliance and old-versus-new comparison
            This section can compare baseline and fixed runs if run paths are provided through `RUN_SELECTION`.
            If paths are not provided, it auto-selects the latest two runs per granularity when possible.
            """
        ),
        code(
            """
            def _resolve_optional_run_dir(value: str) -> Path | None:
                txt = str(value or "").strip()
                if not txt:
                    return None
                candidate = Path(txt)
                if not candidate.is_absolute():
                    candidate = (REPO_ROOT / candidate).resolve()
                if not candidate.exists():
                    warnings_log.append(f"Configured run path does not exist: {candidate}")
                    return None
                return candidate


            def _find_latest_two_runs(granularity: str) -> list[Path]:
                if granularity == "hourly":
                    root = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "hourly_da" / "notebook_artifacts"
                else:
                    root = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "quarterhour_da" / "finalisation_runs"
                if not root.exists():
                    return []
                runs = sorted(
                    [
                        path
                        for path in root.rglob("*")
                        if path.is_dir() and (path / "scenario_prices_long.csv").exists()
                    ]
                )
                if not runs:
                    return []
                return runs[-2:] if len(runs) >= 2 else runs


            comparison_plan: list[dict[str, Any]] = []
            hourly_old = _resolve_optional_run_dir(RUN_SELECTION.get("hourly_old_run_dir", ""))
            hourly_new = _resolve_optional_run_dir(RUN_SELECTION.get("hourly_new_run_dir", ""))
            qh_old = _resolve_optional_run_dir(RUN_SELECTION.get("quarterhour_old_run_dir", ""))
            qh_new = _resolve_optional_run_dir(RUN_SELECTION.get("quarterhour_new_run_dir", ""))

            if hourly_old is None and hourly_new is None:
                latest_hourly = _find_latest_two_runs("hourly")
                if len(latest_hourly) == 2:
                    hourly_old, hourly_new = latest_hourly[0], latest_hourly[1]
            if qh_old is None and qh_new is None:
                latest_qh = _find_latest_two_runs("quarter_hour")
                if len(latest_qh) == 2:
                    qh_old, qh_new = latest_qh[0], latest_qh[1]

            if hourly_old is not None:
                comparison_plan.append({"run_label": "hourly_old", "granularity": "hourly", "run_dir": hourly_old})
            if hourly_new is not None:
                comparison_plan.append({"run_label": "hourly_new", "granularity": "hourly", "run_dir": hourly_new})
            if qh_old is not None:
                comparison_plan.append({"run_label": "quarterhour_old", "granularity": "quarter_hour", "run_dir": qh_old})
            if qh_new is not None:
                comparison_plan.append({"run_label": "quarterhour_new", "granularity": "quarter_hour", "run_dir": qh_new})

            if not comparison_plan:
                # Single-run fallback from already loaded model registry.
                loaded_run_dirs = sorted({str(Path(p).parent) for p in scenarios["source_scenario_file"].astype(str).tolist()})
                for idx, run_dir_text in enumerate(loaded_run_dirs[:2], start=1):
                    g = _infer_granularity(Path(run_dir_text))
                    comparison_plan.append({"run_label": f"loaded_run_{idx}", "granularity": g, "run_dir": Path(run_dir_text)})

            display(Markdown("### Run Selection"))
            display(pd.DataFrame([{**row, "run_dir": str(row["run_dir"])} for row in comparison_plan]))

            calibration_summary_csv = _resolve_optional_run_dir(RUN_SELECTION.get("calibration_summary_csv", ""))
            if calibration_summary_csv is not None and calibration_summary_csv.exists():
                try:
                    calibration_summary = pd.read_csv(calibration_summary_csv, low_memory=False)
                    calibration_summary.to_csv(OUTPUT_ROOT / "scenario_calibration_sensitivity_summary.csv", index=False)
                    display(Markdown("### Calibration Sensitivity Summary (External Input)"))
                    display(calibration_summary.head(50))
                except Exception as exc:
                    warnings_log.append(f"Failed to load calibration summary CSV: {calibration_summary_csv} ({exc})")


            def _load_run_summary_payload(run_dir: Path) -> dict[str, Any]:
                for name in ["scenario_generation_run_summary.json", "run_summary.json"]:
                    path = run_dir / name
                    if path.exists():
                        return _safe_read_json(path)
                return {}


            def _metadata_field(payload: dict[str, Any], key: str) -> Any:
                value = payload.get(key, None)
                if value is None or value == "":
                    return "missing/not recorded"
                return value


            def _load_standardized_run_bundle(run_dir: Path, granularity: str, run_label: str) -> pd.DataFrame:
                scenario_path = run_dir / "scenario_prices_long.csv"
                if not scenario_path.exists():
                    warnings_log.append(f"scenario_prices_long.csv missing for run {run_label}: {run_dir}")
                    return pd.DataFrame()
                id_col, raw_ids = _read_unique_model_ids(scenario_path)
                if not id_col or not raw_ids:
                    warnings_log.append(f"No model ids found for run {run_label}: {scenario_path}")
                    return pd.DataFrame()

                parts: list[pd.DataFrame] = []
                for raw_id in raw_ids:
                    base_key = _canonical_model_key(raw_id, granularity)
                    if base_key is None:
                        continue
                    disp = MODEL_DISPLAY_NAME.get(base_key, base_key) + f" [{run_label}]"
                    tagged_key = f"{base_key}__{run_label}"
                    try:
                        part, _ = standardise_scenario_schema(
                            scenario_path,
                            granularity=granularity,
                            raw_model_id=str(raw_id),
                            canonical_model_key=tagged_key,
                            display_name=disp,
                        )
                        part["run_label"] = run_label
                        part["base_model_key"] = base_key
                        part["source_run_dir"] = str(run_dir)
                        parts.append(part)
                    except Exception as exc:
                        warnings_log.append(f"Failed to standardize {run_label}/{raw_id}: {exc}")
                if not parts:
                    return pd.DataFrame()
                merged = pd.concat(parts, ignore_index=True)
                merged, _ = join_actuals_if_needed(merged)
                return merged


            comparison_parts: list[pd.DataFrame] = []
            metadata_rows: list[dict[str, Any]] = []
            tail_run_model_rows: list[dict[str, Any]] = []
            for row in comparison_plan:
                run_label = str(row["run_label"])
                granularity = str(row["granularity"])
                run_dir = Path(row["run_dir"])
                payload = _load_run_summary_payload(run_dir)
                bundle = _load_standardized_run_bundle(run_dir, granularity, run_label)
                if not bundle.empty:
                    comparison_parts.append(bundle)

                metadata_rows.append(
                    {
                        "run_label": run_label,
                        "granularity": granularity,
                        "scenario_run_path": str(run_dir),
                        "generated_timestamp": _metadata_field(payload, "timestamp"),
                        "model_candidate_ids": _metadata_field(payload, "models"),
                        "selection_split_used": _metadata_field(payload, "selection_split_used"),
                        "test_used_for_selection": _metadata_field(payload, "test_used_for_selection"),
                        "calibration_policy": _metadata_field(payload, "calibration_policy"),
                        "calibration_splits_used": _metadata_field(payload, "calibration_splits_used"),
                        "causal_source_filter_applied": _metadata_field(payload, "causal_source_filter_applied"),
                        "causal_source_filter_violations": _metadata_field(payload, "causal_source_filter_violations"),
                        "random_seed_method": _metadata_field(payload, "random_seed_method"),
                        "random_seed_base": _metadata_field(payload, "random_seed_base"),
                        "residual_source_rows": _metadata_field(payload, "residual_source_rows"),
                        "residual_source_days": _metadata_field(payload, "residual_source_days"),
                        "raw_scenario_count": _metadata_field(payload, "raw_scenario_count"),
                        "reduced_scenario_count": _metadata_field(payload, "reduced_scenario_count"),
                        "protected_tail_count": _metadata_field(payload, "protected_tail_count"),
                        "protected_tail_probability_mass": _metadata_field(payload, "protected_tail_probability_mass"),
                        "protected_tail_categories": _metadata_field(payload, "protected_tail_categories"),
                        "scenarios_per_group": _metadata_field(payload, "n_final_scenarios"),
                        "scenario_probability_policy": _metadata_field(payload, "probability_policy"),
                        "scenario_reduction_method": _metadata_field(payload, "reduction_method"),
                        "forecast_artifact_linkage": bool(payload.get("phase27_run_dir") or payload.get("phase27_run_id") or payload.get("selected_candidates")),
                    }
                )

                tail_meta_path = run_dir / "scenario_metadata.csv"
                if tail_meta_path.exists():
                    try:
                        tail_meta = pd.read_csv(tail_meta_path, low_memory=False)
                    except Exception:
                        tail_meta = pd.DataFrame()
                    if not tail_meta.empty:
                        model_col = _first_present(tail_meta.columns.tolist(), ["model_id", "candidate_key", "candidate_label"])
                        if model_col is not None:
                            if "tail_protection_flag" not in tail_meta.columns:
                                tail_meta["tail_protection_flag"] = tail_meta.get("scenario_type", pd.Series(index=tail_meta.index)).astype(str) == "protected_tail"
                            if "reduced_scenario_probability" not in tail_meta.columns:
                                tail_meta["reduced_scenario_probability"] = pd.to_numeric(
                                    tail_meta.get("scenario_probability", tail_meta.get("probability")), errors="coerce"
                                )
                            if "tail_categories" not in tail_meta.columns:
                                tail_meta["tail_categories"] = ""
                            for model_id, grp in tail_meta.groupby(model_col, dropna=False):
                                base_model = _canonical_model_key(str(model_id), granularity)
                                tail_run_model_rows.append(
                                    {
                                        "run_label": run_label,
                                        "granularity": granularity,
                                        "base_model_key": base_model or str(model_id),
                                        "tail_rows": int(grp.shape[0]),
                                        "protected_tail_count": int(grp["tail_protection_flag"].fillna(False).astype(bool).sum()),
                                        "protected_tail_probability_mass": float(
                                            pd.to_numeric(
                                                grp.loc[grp["tail_protection_flag"].fillna(False).astype(bool), "reduced_scenario_probability"],
                                                errors="coerce",
                                            ).fillna(0.0).sum()
                                        ),
                                        "protected_tail_categories": ",".join(
                                            sorted(
                                                {
                                                    category.strip()
                                                    for categories in grp["tail_categories"].dropna().astype(str).tolist()
                                                    for category in categories.split(",")
                                                    if category.strip()
                                                }
                                            )
                                        ),
                                    }
                                )

            methodology_metadata = pd.DataFrame(metadata_rows)
            methodology_metadata.to_csv(OUTPUT_ROOT / "scenario_methodology_metadata_panel.csv", index=False)
            display(Markdown("### Methodology Metadata Panel"))
            display(methodology_metadata)
            tail_run_model_summary = pd.DataFrame(tail_run_model_rows)
            if not tail_run_model_summary.empty:
                tail_run_model_summary.to_csv(OUTPUT_ROOT / "scenario_tail_protection_summary_by_model.csv", index=False)
                display(Markdown("### Tail Protection Summary by Run/Model"))
                display(tail_run_model_summary)

            # D+4 applicability panel (scan-only; no D+4 generation in this notebook).
            dplus4_root = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "scenario_evaluation" / "dplus4_applicability"
            dplus4_payload = {}
            if dplus4_root.exists():
                candidate_reports = sorted(dplus4_root.glob("*/dplus4_applicability_report.json"))
                if candidate_reports:
                    dplus4_payload = _safe_read_json(candidate_reports[-1])
            if dplus4_payload:
                dplus4_panel = pd.DataFrame(
                    [
                        {
                            "scope": "hourly",
                            "status": str(dplus4_payload.get("hourly", {}).get("status", "missing/not recorded")),
                        },
                        {
                            "scope": "quarter_hour",
                            "status": str(dplus4_payload.get("quarter_hour", {}).get("status", "missing/not recorded")),
                        },
                        {
                            "scope": "global",
                            "status": str(dplus4_payload.get("global_status", "missing/not recorded")),
                        },
                    ]
                )
                dplus4_panel.to_csv(OUTPUT_ROOT / "dplus4_applicability_panel.csv", index=False)
                display(Markdown("### D+4 Applicability Panel (Scan Only)"))
                display(dplus4_panel)

            comparison_scenarios = pd.concat(comparison_parts, ignore_index=True) if comparison_parts else pd.DataFrame()

            scenario_quality_summary_by_run = pd.DataFrame()
            scenario_quality_summary_by_model = pd.DataFrame()
            scenario_methodology_compliance_summary = pd.DataFrame()
            scenario_before_after_comparison = pd.DataFrame()

            if not comparison_scenarios.empty:
                comparison_scenarios["delivery_local_date"] = (
                    pd.to_datetime(comparison_scenarios["delivery_start_utc"], utc=True, errors="coerce")
                    .dt.tz_convert("Europe/Amsterdam")
                    .dt.date
                )
                # Quantiles per run/model/timestamp.
                qrows: list[dict[str, Any]] = []
                for keys, grp in comparison_scenarios.groupby(
                    ["run_label", "granularity", "base_model_key", "forecast_origin_utc", "delivery_start_utc", "lead_day"],
                    dropna=False,
                ):
                    run_label, granularity, base_model_key, forecast_origin_utc, delivery_start_utc, lead_day = keys
                    values = pd.to_numeric(grp["scenario_price"], errors="coerce").dropna()
                    if values.empty:
                        continue
                    y = pd.to_numeric(grp["y_true"], errors="coerce").dropna()
                    if "scenario_probability" in grp.columns:
                        probs = pd.to_numeric(grp["scenario_probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                    elif "probability" in grp.columns:
                        probs = pd.to_numeric(grp["probability"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                    else:
                        probs = np.zeros(values.shape[0], dtype=float)
                    val_arr = values.to_numpy(dtype=float)
                    if probs.size != val_arr.size or probs.sum() <= 0.0:
                        probs = np.ones_like(val_arr, dtype=float)
                    qrows.append(
                        {
                            "run_label": run_label,
                            "granularity": granularity,
                            "base_model_key": base_model_key,
                            "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                            "delivery_start_utc": pd.Timestamp(delivery_start_utc),
                            "lead_day": int(lead_day) if pd.notna(lead_day) else None,
                            "y_true": float(y.iloc[0]) if not y.empty else np.nan,
                            "p05": _weighted_quantile(val_arr, probs, 0.05),
                            "p50": _weighted_quantile(val_arr, probs, 0.50),
                            "p95": _weighted_quantile(val_arr, probs, 0.95),
                            "scenario_min": float(values.min()),
                            "scenario_max": float(values.max()),
                            "spread_90": float(_weighted_quantile(val_arr, probs, 0.95) - _weighted_quantile(val_arr, probs, 0.05)),
                        }
                    )
                comp_q = pd.DataFrame(qrows)

                if not comp_q.empty:
                    comp_q["in_p05_p95"] = (
                        comp_q["y_true"].notna()
                        & (comp_q["y_true"] >= comp_q["p05"])
                        & (comp_q["y_true"] <= comp_q["p95"])
                    ).astype(float)
                    comp_q["outside_spread"] = (
                        comp_q["y_true"].notna()
                        & ((comp_q["y_true"] < comp_q["scenario_min"]) | (comp_q["y_true"] > comp_q["scenario_max"]))
                    ).astype(float)
                    comp_q["upper_tail_miss"] = (comp_q["y_true"] > comp_q["p95"]).astype(float)
                    comp_q["lower_tail_miss"] = (comp_q["y_true"] < comp_q["p05"]).astype(float)
                    comp_q["p50_bias"] = comp_q["p50"] - comp_q["y_true"]

                    # High/low regime diagnostics.
                    comp_q["high_price_cutoff"] = comp_q.groupby(["run_label", "base_model_key"], dropna=False)["y_true"].transform(
                        lambda s: pd.to_numeric(s, errors="coerce").quantile(0.90)
                    )
                    comp_q["low_price_cutoff"] = comp_q.groupby(["run_label", "base_model_key"], dropna=False)["y_true"].transform(
                        lambda s: pd.to_numeric(s, errors="coerce").quantile(0.10)
                    )
                    comp_q["is_high_price_period"] = comp_q["y_true"] >= comp_q["high_price_cutoff"]
                    comp_q["is_low_price_period"] = comp_q["y_true"] <= comp_q["low_price_cutoff"]
                    comp_q["is_negative_price_period"] = comp_q["y_true"] < 0.0

                    model_rows: list[dict[str, Any]] = []
                    for keys, grp in comp_q.groupby(["run_label", "granularity", "base_model_key"], dropna=False):
                        run_label, granularity, base_model_key = keys
                        high_grp = grp[grp["is_high_price_period"]].copy()
                        low_grp = grp[grp["is_low_price_period"]].copy()
                        neg_grp = grp[grp["is_negative_price_period"]].copy()
                        model_rows.append(
                            {
                                "run_label": run_label,
                                "granularity": granularity,
                                "base_model_key": base_model_key,
                                "coverage_p05_p95": float(grp["in_p05_p95"].mean()),
                                "actual_outside_spread_frequency": float(grp["outside_spread"].mean()),
                                "p50_bias": float(grp["p50_bias"].mean()),
                                "average_scenario_spread_p05_p95": float(grp["spread_90"].mean()),
                                "high_price_tail_miss_rate": float(high_grp["upper_tail_miss"].mean()) if not high_grp.empty else np.nan,
                                "low_price_tail_miss_rate": float(low_grp["lower_tail_miss"].mean()) if not low_grp.empty else np.nan,
                                "negative_price_tail_miss_rate": float(neg_grp["lower_tail_miss"].mean()) if not neg_grp.empty else np.nan,
                                "n_points": int(grp.shape[0]),
                            }
                        )
                    scenario_quality_summary_by_model = pd.DataFrame(model_rows).sort_values(
                        ["granularity", "base_model_key", "run_label"]
                    ).reset_index(drop=True)
                    if not tail_run_model_summary.empty:
                        scenario_quality_summary_by_model = scenario_quality_summary_by_model.merge(
                            tail_run_model_summary[
                                [
                                    "run_label",
                                    "granularity",
                                    "base_model_key",
                                    "protected_tail_count",
                                    "protected_tail_probability_mass",
                                    "protected_tail_categories",
                                ]
                            ],
                            on=["run_label", "granularity", "base_model_key"],
                            how="left",
                        )

                    # CVaR tail cardinality diagnostics at alpha=0.95.
                    cvar_rows: list[dict[str, Any]] = []
                    group_cols = ["run_label", "granularity", "base_model_key", "forecast_origin_utc", "delivery_local_date", "scenario_id"]
                    if {"scenario_probability", "scenario_id"}.issubset(set(comparison_scenarios.columns)):
                        for keys, grp in comparison_scenarios.groupby(group_cols, dropna=False):
                            run_label, granularity, base_model_key, forecast_origin_utc, delivery_local_date, scenario_id = keys
                            cvar_rows.append(
                                {
                                    "run_label": run_label,
                                    "granularity": granularity,
                                    "base_model_key": base_model_key,
                                    "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                                    "delivery_local_date": str(delivery_local_date),
                                    "scenario_id": str(scenario_id),
                                    "scenario_daily_mean": float(pd.to_numeric(grp["scenario_price"], errors="coerce").mean()),
                                    "scenario_probability": float(pd.to_numeric(grp["scenario_probability"], errors="coerce").dropna().iloc[0])
                                    if pd.to_numeric(grp["scenario_probability"], errors="coerce").notna().any()
                                    else np.nan,
                                }
                            )
                    cvar_df = pd.DataFrame(cvar_rows)
                    if not cvar_df.empty:
                        tail_card_rows: list[dict[str, Any]] = []
                        for keys, grp in cvar_df.groupby(["run_label", "granularity", "base_model_key", "forecast_origin_utc", "delivery_local_date"], dropna=False):
                            run_label, granularity, base_model_key, forecast_origin_utc, delivery_local_date = keys
                            ordered = grp.sort_values(["scenario_daily_mean", "scenario_id"], ascending=[False, True]).copy()
                            probs = pd.to_numeric(ordered["scenario_probability"], errors="coerce").fillna(0.0)
                            if probs.sum() > 0:
                                probs = probs / probs.sum()
                            ordered["prob_norm"] = probs
                            ordered["cum_prob"] = ordered["prob_norm"].cumsum()
                            tail = ordered[ordered["cum_prob"] <= 0.05].copy()
                            if tail.empty and not ordered.empty:
                                tail = ordered.head(1).copy()
                            tail_card_rows.append(
                                {
                                    "run_label": run_label,
                                    "granularity": granularity,
                                    "base_model_key": base_model_key,
                                    "tail_cardinality": int(tail["scenario_id"].nunique()),
                                }
                            )
                        tail_card = pd.DataFrame(tail_card_rows)
                        if not tail_card.empty:
                            tail_card_summary = (
                                tail_card.groupby(["run_label", "granularity", "base_model_key"], dropna=False)["tail_cardinality"]
                                .mean()
                                .reset_index(name="cvar_tail_cardinality_avg")
                            )
                            scenario_quality_summary_by_model = scenario_quality_summary_by_model.merge(
                                tail_card_summary,
                                on=["run_label", "granularity", "base_model_key"],
                                how="left",
                            )
                            scenario_quality_summary_by_model["cvar_tail_cardinality_flag"] = np.where(
                                pd.to_numeric(scenario_quality_summary_by_model["cvar_tail_cardinality_avg"], errors="coerce") < 2.0,
                                "warn_fewer_than_2_tail_scenarios",
                                "pass",
                            )

                    run_rows: list[dict[str, Any]] = []
                    for keys, grp in scenario_quality_summary_by_model.groupby(["run_label", "granularity"], dropna=False):
                        run_label, granularity = keys
                        run_rows.append(
                            {
                                "run_label": run_label,
                                "granularity": granularity,
                                "coverage_p05_p95_mean": float(grp["coverage_p05_p95"].mean()),
                                "outside_spread_mean": float(grp["actual_outside_spread_frequency"].mean()),
                                "p50_bias_mean": float(grp["p50_bias"].mean()),
                                "avg_spread_mean": float(grp["average_scenario_spread_p05_p95"].mean()),
                                "high_tail_miss_mean": float(grp["high_price_tail_miss_rate"].mean()),
                                "low_tail_miss_mean": float(grp["low_price_tail_miss_rate"].mean()),
                                "negative_tail_miss_mean": float(grp["negative_price_tail_miss_rate"].mean()),
                                "protected_tail_count_mean": float(pd.to_numeric(grp.get("protected_tail_count"), errors="coerce").mean())
                                if "protected_tail_count" in grp.columns
                                else np.nan,
                                "protected_tail_probability_mass_mean": float(
                                    pd.to_numeric(grp.get("protected_tail_probability_mass"), errors="coerce").mean()
                                )
                                if "protected_tail_probability_mass" in grp.columns
                                else np.nan,
                                "cvar_tail_cardinality_avg_mean": float(
                                    pd.to_numeric(grp.get("cvar_tail_cardinality_avg"), errors="coerce").mean()
                                )
                                if "cvar_tail_cardinality_avg" in grp.columns
                                else np.nan,
                                "models_count": int(grp["base_model_key"].nunique()),
                            }
                        )
                    scenario_quality_summary_by_run = pd.DataFrame(run_rows).sort_values(["granularity", "run_label"]).reset_index(drop=True)

                    # Compliance checks.
                    comp_rows: list[dict[str, Any]] = []
                    for _, meta in methodology_metadata.iterrows():
                        run_label = str(meta["run_label"])
                        granularity = str(meta["granularity"])
                        run_data = comparison_scenarios[comparison_scenarios["run_label"].astype(str) == run_label].copy()
                        probs_ok = True
                        if not run_data.empty:
                            pgrp = (
                                run_data.groupby(
                                    ["base_model_key", "forecast_origin_utc", "delivery_start_utc"],
                                    dropna=False,
                                )["scenario_probability"]
                                .sum(min_count=1)
                                .reset_index(name="prob_sum")
                            )
                            pgrp = pgrp[pgrp["prob_sum"].notna()].copy()
                            probs_ok = bool((pgrp["prob_sum"].sub(1.0).abs() <= 1e-6).all()) if not pgrp.empty else True

                        checks = [
                            ("test_data_not_used_for_selection", str(meta["test_used_for_selection"]).lower() in {"false", "missing/not recorded"}),
                            ("calibration_policy_recorded", str(meta["calibration_policy"]) != "missing/not recorded"),
                            ("hourly_causal_filter_applied", True if granularity != "hourly" else str(meta["causal_source_filter_applied"]).lower() == "true"),
                            ("causal_filter_violations_zero", str(meta["causal_source_filter_violations"]) in {"0", "0.0", "missing/not recorded"}),
                            ("probabilities_sum_to_one", probs_ok),
                            ("stable_qh_seed_method", True if granularity != "quarter_hour" else "hash" not in str(meta["random_seed_method"]).lower()),
                            ("forecast_and_residual_linkage_recorded", bool(meta["forecast_artifact_linkage"])),
                        ]
                        for check_name, passed in checks:
                            comp_rows.append(
                                {
                                    "run_label": run_label,
                                    "granularity": granularity,
                                    "check_name": check_name,
                                    "status": "pass" if passed else "warn",
                                }
                            )
                    scenario_methodology_compliance_summary = pd.DataFrame(comp_rows)

                    # Before-after table when both old and new are present.
                    pair_rows: list[dict[str, Any]] = []
                    pair_specs = [
                        ("hourly_old", "hourly_new", "hourly"),
                        ("quarterhour_old", "quarterhour_new", "quarter_hour"),
                    ]
                    for old_label, new_label, granularity in pair_specs:
                        oldm = scenario_quality_summary_by_model[
                            (scenario_quality_summary_by_model["run_label"] == old_label)
                            & (scenario_quality_summary_by_model["granularity"] == granularity)
                        ].copy()
                        newm = scenario_quality_summary_by_model[
                            (scenario_quality_summary_by_model["run_label"] == new_label)
                            & (scenario_quality_summary_by_model["granularity"] == granularity)
                        ].copy()
                        if oldm.empty or newm.empty:
                            continue
                        merged = oldm.merge(
                            newm,
                            on=["granularity", "base_model_key"],
                            how="inner",
                            suffixes=("_old", "_new"),
                        )
                        for _, row in merged.iterrows():
                            pair_rows.append(
                                {
                                    "granularity": granularity,
                                    "base_model_key": row["base_model_key"],
                                    "coverage_p05_p95_old": row["coverage_p05_p95_old"],
                                    "coverage_p05_p95_new": row["coverage_p05_p95_new"],
                                    "coverage_delta_new_minus_old": row["coverage_p05_p95_new"] - row["coverage_p05_p95_old"],
                                    "outside_spread_old": row["actual_outside_spread_frequency_old"],
                                    "outside_spread_new": row["actual_outside_spread_frequency_new"],
                                    "outside_spread_delta_new_minus_old": row["actual_outside_spread_frequency_new"] - row["actual_outside_spread_frequency_old"],
                                    "p50_bias_old": row["p50_bias_old"],
                                    "p50_bias_new": row["p50_bias_new"],
                                    "avg_spread_old": row["average_scenario_spread_p05_p95_old"],
                                    "avg_spread_new": row["average_scenario_spread_p05_p95_new"],
                                    "high_tail_miss_old": row["high_price_tail_miss_rate_old"],
                                    "high_tail_miss_new": row["high_price_tail_miss_rate_new"],
                                    "low_tail_miss_old": row["low_price_tail_miss_rate_old"],
                                    "low_tail_miss_new": row["low_price_tail_miss_rate_new"],
                                    "negative_tail_miss_old": row["negative_price_tail_miss_rate_old"],
                                    "negative_tail_miss_new": row["negative_price_tail_miss_rate_new"],
                                }
                            )
                    scenario_before_after_comparison = pd.DataFrame(pair_rows)

                    # Plots: old vs new where pairs exist.
                    if not scenario_before_after_comparison.empty:
                        for granularity, grp in scenario_before_after_comparison.groupby("granularity", dropna=False):
                            safe_gr = _sanitize_filename(str(granularity))
                            # Coverage old/new bars.
                            fig, ax = plt.subplots(figsize=(10, 4.5))
                            x = np.arange(grp.shape[0])
                            ax.bar(x - 0.18, grp["coverage_p05_p95_old"], width=0.36, label="old")
                            ax.bar(x + 0.18, grp["coverage_p05_p95_new"], width=0.36, label="new")
                            ax.axhline(0.90, color="black", linestyle="--", linewidth=1.0)
                            ax.set_xticks(x)
                            ax.set_xticklabels(grp["base_model_key"], rotation=25, ha="right")
                            ax.set_ylabel("Coverage p05-p95")
                            ax.set_title(f"{granularity}: coverage by model (old vs new)")
                            ax.legend()
                            fig.tight_layout()
                            fig.savefig(FIG_DIR / f"{safe_gr}_coverage_old_vs_new.png", dpi=150)
                            plt.close(fig)

                            fig, ax = plt.subplots(figsize=(10, 4.5))
                            ax.bar(x - 0.18, grp["outside_spread_old"], width=0.36, label="old")
                            ax.bar(x + 0.18, grp["outside_spread_new"], width=0.36, label="new")
                            ax.set_xticks(x)
                            ax.set_xticklabels(grp["base_model_key"], rotation=25, ha="right")
                            ax.set_ylabel("Outside spread frequency")
                            ax.set_title(f"{granularity}: actual-outside-spread (old vs new)")
                            ax.legend()
                            fig.tight_layout()
                            fig.savefig(FIG_DIR / f"{safe_gr}_outside_spread_old_vs_new.png", dpi=150)
                            plt.close(fig)

                        # Spread by hour/quarter (old vs new).
                        comp_q_local = comp_q.copy()
                        comp_q_local["delivery_local"] = comp_q_local["delivery_start_utc"].dt.tz_convert("Europe/Amsterdam")
                        comp_q_local["hour_of_day"] = comp_q_local["delivery_local"].dt.hour
                        comp_q_local["quarter_of_day"] = comp_q_local["delivery_local"].dt.hour * 4 + (comp_q_local["delivery_local"].dt.minute // 15) + 1
                        for granularity, period_col in [("hourly", "hour_of_day"), ("quarter_hour", "quarter_of_day")]:
                            subset = comp_q_local[comp_q_local["granularity"] == granularity].copy()
                            if subset.empty:
                                continue
                            old_label = "hourly_old" if granularity == "hourly" else "quarterhour_old"
                            new_label = "hourly_new" if granularity == "hourly" else "quarterhour_new"
                            old_line = subset[subset["run_label"] == old_label].groupby(period_col)["spread_90"].mean()
                            new_line = subset[subset["run_label"] == new_label].groupby(period_col)["spread_90"].mean()
                            if old_line.empty and new_line.empty:
                                continue
                            fig, ax = plt.subplots(figsize=(10, 4.2))
                            if not old_line.empty:
                                ax.plot(old_line.index, old_line.values, label="old", linewidth=1.5)
                            if not new_line.empty:
                                ax.plot(new_line.index, new_line.values, label="new", linewidth=1.5)
                            ax.set_title(f"{granularity}: average spread p05-p95 by period (old vs new)")
                            ax.set_xlabel(period_col)
                            ax.set_ylabel("Average spread")
                            ax.legend()
                            fig.tight_layout()
                            fig.savefig(FIG_DIR / f"{_sanitize_filename(granularity)}_spread_by_period_old_vs_new.png", dpi=150)
                            plt.close(fig)

            # Persist thesis-facing outputs (requested names).
            scenario_quality_summary_by_run.to_csv(OUTPUT_ROOT / "scenario_quality_summary_by_run.csv", index=False)
            scenario_quality_summary_by_model.to_csv(OUTPUT_ROOT / "scenario_quality_summary_by_model.csv", index=False)
            scenario_methodology_compliance_summary.to_csv(OUTPUT_ROOT / "scenario_methodology_compliance_summary.csv", index=False)
            if not scenario_before_after_comparison.empty:
                scenario_before_after_comparison.to_csv(OUTPUT_ROOT / "scenario_before_after_comparison.csv", index=False)

            # Minimal README for interpretation guidance.
            readme_lines = [
                "# Scenario Distribution Evaluation (P0/P1 aligned)",
                "",
                "This folder contains methodology-compliance and distribution-quality diagnostics.",
                "",
                "Interpretation order:",
                "1. `scenario_methodology_compliance_summary.csv`: Strategy-B/P0/P1 compliance checks.",
                "2. `scenario_quality_summary_by_run.csv`: aggregate quality by run.",
                "3. `scenario_quality_summary_by_model.csv`: model-level coverage, spread, bias, tails.",
                "4. `scenario_before_after_comparison.csv`: old-vs-new deltas when both are available.",
                "",
                "Important: passing compliance checks does not imply CVaR readiness. Tail coverage and spread quality still govern CVaR suitability.",
            ]
            (OUTPUT_ROOT / "README.md").write_text("\\n".join(readme_lines), encoding="utf-8")

            display(Markdown("### P0/P1 Compliance Summary"))
            display(scenario_methodology_compliance_summary if not scenario_methodology_compliance_summary.empty else pd.DataFrame())
            if not scenario_before_after_comparison.empty:
                display(Markdown("### Old vs New Comparison"))
                display(scenario_before_after_comparison)
            """
        ),
        md(
            """
            ## 10. Final thesis-ready interpretation
            The notebook now composes a concise interpretation from computed metrics.
            """
        ),
        code(
            """
            # Best-by-metric helper picks.
            best_cal = scenario_calibration_summary.loc[
                (scenario_calibration_summary["calibration_error_90"].abs()).idxmin()
            ] if not scenario_calibration_summary.empty else None
            best_sharp = sharpness_summary.loc[
                sharpness_summary["mean_width_90"].idxmin()
            ] if not sharpness_summary.empty else None

            tradeoff = scenario_calibration_summary.merge(
                sharpness_summary[["model_key", "mean_width_90"]],
                on="model_key",
                how="left",
            )
            if not tradeoff.empty:
                tradeoff["tradeoff_score"] = tradeoff["calibration_error_90"].abs() + (
                    tradeoff["mean_width_90"] / tradeoff["mean_width_90"].median()
                )
                best_trade = tradeoff.loc[tradeoff["tradeoff_score"].idxmin()]
            else:
                best_trade = None

            upper_risk = scenario_calibration_summary.sort_values("upper_exceed_rate_above_p95", ascending=False)
            lower_opp = scenario_calibration_summary.sort_values("lower_exceed_rate_below_p05", ascending=False)

            qh_vs_hourly = scenario_calibration_summary.groupby("granularity")["coverage_p05_p95"].mean(numeric_only=True).to_dict()

            lines = []
            lines.append("### Thesis-ready interpretation")
            if best_cal is not None:
                lines.append(
                    f"- Best pointwise calibration (90% interval): **{best_cal['model_name']}** "
                    f"(coverage={best_cal['coverage_p05_p95']:.3f}, error={best_cal['calibration_error_90']:+.3f})."
                )
            if best_sharp is not None:
                lines.append(
                    f"- Sharpest 90% intervals: **{best_sharp['model_name']}** "
                    f"(mean width={best_sharp['mean_width_90']:.3f})."
                )
            if best_trade is not None:
                lines.append(
                    f"- Best calibration–sharpness trade-off (rule-of-thumb composite): **{best_trade['model_name']}**."
                )
            if not upper_risk.empty:
                worst_upper = upper_risk.iloc[0]
                lines.append(
                    f"- Strongest upper-tail underrepresentation risk: **{worst_upper['model_name']}** "
                    f"(above-p95 exceedance={worst_upper['upper_exceed_rate_above_p95']:.3f})."
                )
            if not lower_opp.empty:
                worst_lower = lower_opp.iloc[0]
                lines.append(
                    f"- Strongest low-price opportunity underrepresentation risk: **{worst_lower['model_name']}** "
                    f"(below-p05 exceedance={worst_lower['lower_exceed_rate_below_p05']:.3f})."
                )
            if "hourly" in qh_vs_hourly and "quarter_hour" in qh_vs_hourly:
                lines.append(
                    f"- Average 90% coverage by granularity: hourly={qh_vs_hourly['hourly']:.3f}, "
                    f"quarter-hour={qh_vs_hourly['quarter_hour']:.3f}."
                )

            lines.append("- MILP readiness is judged by calibration, tails, spread, and temporal coherence jointly; high coverage alone is not sufficient.")
            lines.append("- If recalibration is required, preferred sequence is: conformal calibration on validation residuals, targeted tail/stress enrichment, then bias correction by lead-day/hour.")

            display(Markdown("\\n".join(lines)))

            # Run summary json.
            git_commit = None
            try:
                git_commit = (
                    subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=REPO_ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    .stdout.strip()
                )
            except Exception:
                git_commit = None

            run_summary = {
                "timestamp_utc": RUN_TS.isoformat(),
                "run_id": RUN_ID,
                "git_commit": git_commit,
                "notebook_path": str(NOTEBOOK_PATH),
                "paths_loaded": sorted(set(scenarios["source_scenario_file"].astype(str).tolist())),
                "number_of_models_found": int(selected_models["selected"].fillna(False).sum()),
                "number_of_models_evaluated": int(scenarios["model_key"].nunique()),
                "model_keys_evaluated": sorted(scenarios["model_key"].dropna().unique().tolist()),
                "date_range_start_utc": str(scenarios["delivery_start_utc"].min()),
                "date_range_end_utc": str(scenarios["delivery_start_utc"].max()),
                "scenarios_per_model": scenario_model_registry[["model_key", "scenarios_per_origin_delivery_mean"]].to_dict(orient="records"),
                "actuals_source": actual_join_log.to_dict(orient="records"),
                "warnings": warnings_log,
                "generated_output_paths": {
                    "output_root": str(OUTPUT_ROOT),
                    "tables": str(TABLE_DIR),
                    "figures": str(FIG_DIR),
                },
                "p0_p1_outputs": {
                    "scenario_quality_summary_by_run": str(OUTPUT_ROOT / "scenario_quality_summary_by_run.csv"),
                    "scenario_quality_summary_by_model": str(OUTPUT_ROOT / "scenario_quality_summary_by_model.csv"),
                    "scenario_methodology_compliance_summary": str(OUTPUT_ROOT / "scenario_methodology_compliance_summary.csv"),
                    "scenario_before_after_comparison": str(OUTPUT_ROOT / "scenario_before_after_comparison.csv"),
                    "methodology_metadata_panel": str(OUTPUT_ROOT / "scenario_methodology_metadata_panel.csv"),
                    "readme": str(OUTPUT_ROOT / "README.md"),
                },
            }
            (OUTPUT_ROOT / "run_summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
            (OUTPUT_ROOT / "notebook_run_summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")

            # Required short console summary.
            print("\\n=== Scenario Evaluation Summary ===")
            print(f"Notebook path: {NOTEBOOK_PATH}")
            print(f"Models found (expected families): {int(selected_models['selected'].fillna(False).sum())}")
            print(f"Models evaluated: {int(scenarios['model_key'].nunique())}")
            print(f"Output folder: {OUTPUT_ROOT}")
            if warnings_log:
                print("Main warnings:")
                for w in warnings_log[:12]:
                    print(f"- {w}")
                if len(warnings_log) > 12:
                    print(f"- ... ({len(warnings_log) - 12} additional warnings)")
            else:
                print("Main warnings: none")
            """
        ),
    ]

    nb = new_notebook(cells=cells)
    nb.metadata.kernelspec = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nb.metadata.language_info = {
        "name": "python",
        "version": "3.12",
    }
    return nb


def main() -> None:
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    nb = build_notebook()
    nbformat.write(nb, NOTEBOOK_PATH)
    print(f"Notebook written: {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
