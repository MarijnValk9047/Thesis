from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import load_candidate_predictions
from hourly_da.core.scenario_generation import discover_scenario_candidate_sources
from quarterhour_da.config import QuarterHourDAExtensionConfig
from quarterhour_da.scenario_generation_qh import _load_model3_predictions, _load_phase27_predictions


LEAR_STRICT_PRED = Path(
    "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/"
    "20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run/predictions_long.csv"
)
LEAR_STRICT_BRIDGE = Path(
    "data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/"
    "20260505_134716_phase07_realistic_track_a/bridged_hourly_target_input_all_regions.csv"
)


def _load_hourly_combined_predictions() -> pd.DataFrame:
    config = HourlyDAPipelineConfig(
        input_csv=Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv"),
        raw_root=Path("data/00_Raw/DA_Prices"),
        cleaned_feature_root=Path("data/01_cleaned"),
        output_root=Path("data/02_Forecasting/01_DA_prices/hourly_da"),
    )
    discovery = discover_scenario_candidate_sources(config.output_root)
    candidate_frame = discovery["candidate_frame"].copy()
    base = load_candidate_predictions(candidate_frame=candidate_frame, config=config)
    if LEAR_STRICT_PRED.exists():
        pred = pd.read_csv(LEAR_STRICT_PRED, low_memory=False)
        pred["forecast_origin_utc"] = pd.to_datetime(pred["forecast_origin_utc"], utc=True, errors="coerce")
        pred["target_timestamp_utc"] = pd.to_datetime(pred["target_timestamp_utc"], utc=True, errors="coerce")
        pred["lead_day"] = pd.to_numeric(pred["lead_day"], errors="coerce").astype("Int64")
        pred["y_pred"] = pd.to_numeric(pred["y_pred"], errors="coerce")
        pred["dataset_split"] = pred["dataset_split"].astype(str)
        bridge = pd.read_csv(LEAR_STRICT_BRIDGE, low_memory=False) if LEAR_STRICT_BRIDGE.exists() else pd.DataFrame()
        if not bridge.empty:
            bridge = bridge.rename(columns={"timestamp_utc": "target_timestamp_utc", "price_eur_per_mwh": "y_true"})
            bridge["target_timestamp_utc"] = pd.to_datetime(bridge["target_timestamp_utc"], utc=True, errors="coerce")
            bridge["y_true"] = pd.to_numeric(bridge["y_true"], errors="coerce")
            bridge = bridge[["target_timestamp_utc", "y_true"]].drop_duplicates("target_timestamp_utc", keep="last")
            pred = pred.merge(bridge, on="target_timestamp_utc", how="left")
        pred["candidate_key"] = "lear_strict_hourly_anchor_export"
        pred["candidate_label"] = "LEAR STRICT hourly anchor"
        for col in base.columns:
            if col not in pred.columns:
                pred[col] = pd.NA
        pred = pred[base.columns.intersection(pred.columns).tolist() + [c for c in base.columns if c not in pred.columns]]
        pred = pred.reindex(columns=base.columns)
        base = pd.concat([base, pred], ignore_index=True)
    return base


def _candidate_scan(frame: pd.DataFrame, candidate_key: str, periods_per_day: int, horizon_days: int) -> dict[str, Any]:
    required_cols = {"forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_pred", "dataset_split"}
    available_cols = set(frame.columns)
    missing_cols = sorted(required_cols - available_cols)
    subset = frame[frame["candidate_key"].astype(str) == str(candidate_key)].copy()
    if subset.empty:
        return {
            "candidate_key": candidate_key,
            "rows": 0,
            "missing_required_columns": missing_cols,
            "lead_days_present": [],
            "full_horizon_origins": 0,
            "coherent_block_rows": 0,
            "residual_rows_by_lead_day_validation": {},
        }
    subset["forecast_origin_utc"] = pd.to_datetime(subset["forecast_origin_utc"], utc=True, errors="coerce")
    subset["target_timestamp_utc"] = pd.to_datetime(subset["target_timestamp_utc"], utc=True, errors="coerce")
    subset["lead_day"] = pd.to_numeric(subset["lead_day"], errors="coerce").astype("Int64")
    subset["y_pred"] = pd.to_numeric(subset["y_pred"], errors="coerce")
    subset["y_true"] = pd.to_numeric(subset.get("y_true"), errors="coerce")
    lead_days_present = sorted([int(x) for x in subset["lead_day"].dropna().unique().tolist()])
    block_length = int(periods_per_day * horizon_days)
    by_origin = subset.groupby("forecast_origin_utc", dropna=False)["target_timestamp_utc"].size().reset_index(name="rows")
    full_horizon_origins = int((by_origin["rows"] >= block_length).sum()) if not by_origin.empty else 0
    validation = subset[(subset["dataset_split"].astype(str) == "validation") & subset["y_true"].notna() & subset["y_pred"].notna()].copy()
    residual_rows_by_lead = (
        validation.groupby("lead_day", dropna=False).size().reset_index(name="rows") if not validation.empty else pd.DataFrame()
    )
    residual_rows_map = {
        str(int(row["lead_day"])) if pd.notna(row["lead_day"]) else "nan": int(row["rows"])
        for _, row in residual_rows_by_lead.iterrows()
    }
    source_blocks = (
        validation.groupby("forecast_origin_utc", dropna=False)
        .agg(block_rows=("target_timestamp_utc", "size"), source_residual_start_utc=("target_timestamp_utc", "min"), source_residual_end_utc=("target_timestamp_utc", "max"))
        .reset_index()
    )
    source_blocks = source_blocks[source_blocks["block_rows"] >= block_length].copy()
    target_origins = (
        subset["forecast_origin_utc"].dropna().drop_duplicates().sort_values().to_numpy(dtype="datetime64[ns]")
        if subset["forecast_origin_utc"].notna().any()
        else np.array([], dtype="datetime64[ns]")
    )
    source_ends = (
        source_blocks["source_residual_end_utc"].dropna().sort_values().to_numpy(dtype="datetime64[ns]")
        if not source_blocks.empty
        else np.array([], dtype="datetime64[ns]")
    )
    causal_enforceable = False
    mean_eligible_blocks = 0.0
    min_eligible_blocks = 0
    if target_origins.size > 0 and source_ends.size > 0:
        eligible_counts = np.searchsorted(source_ends, target_origins, side="left")
        mean_eligible_blocks = float(np.mean(eligible_counts))
        min_eligible_blocks = int(np.min(eligible_counts))
        causal_enforceable = bool(np.any(eligible_counts > 0))
    return {
        "candidate_key": candidate_key,
        "rows": int(subset.shape[0]),
        "missing_required_columns": missing_cols,
        "lead_days_present": lead_days_present,
        "full_horizon_origins": full_horizon_origins,
        "coherent_block_rows": int(full_horizon_origins * block_length),
        "residual_rows_by_lead_day_validation": residual_rows_map,
        "source_residual_blocks_full_horizon_validation": int(source_blocks.shape[0]),
        "causal_block_filter_enforceable": bool(causal_enforceable),
        "eligible_source_blocks_mean_per_target_origin": float(mean_eligible_blocks),
        "eligible_source_blocks_min_per_target_origin": int(min_eligible_blocks),
    }


def _classify_status(scans: list[dict[str, Any]]) -> str:
    if not scans:
        return "not_currently_possible_missing_forecast_or_residual_data"
    any_missing_cols = any(bool(item.get("missing_required_columns")) for item in scans)
    has_all_leads = all(set([0, 1, 2, 3, 4]).issubset(set(item.get("lead_days_present", []))) for item in scans if item.get("rows", 0) > 0)
    has_full_blocks = all(int(item.get("full_horizon_origins", 0)) > 0 for item in scans if item.get("rows", 0) > 0)
    causal_enforceable = all(bool(item.get("causal_block_filter_enforceable", False)) for item in scans if item.get("rows", 0) > 0)
    has_residuals_all_leads = True
    for item in scans:
        residual_map = item.get("residual_rows_by_lead_day_validation", {})
        for lead in [0, 1, 2, 3, 4]:
            if int(residual_map.get(str(lead), 0)) <= 0:
                has_residuals_all_leads = False
                break
    if any_missing_cols:
        return "possible_but_requires_artifact_adapter"
    if has_all_leads and has_full_blocks and has_residuals_all_leads and causal_enforceable:
        return "ready_to_implement_coherent_D_PLUS_4"
    if has_all_leads:
        return "possible_but_only_daily_independent_fallback"
    return "not_currently_possible_missing_forecast_or_residual_data"


def main() -> int:
    hourly = _load_hourly_combined_predictions()
    candidate_keys = [
        "lear_fs3_combo_pruned_candidate",
        "xgboost_fs3_combo_pruned_candidate",
        "lear_strict_hourly_anchor_export",
    ]
    hourly_scans = [_candidate_scan(hourly, key, periods_per_day=24, horizon_days=5) for key in candidate_keys]

    qh_config = QuarterHourDAExtensionConfig()
    phase27, _ = _load_phase27_predictions(qh_config, phase27_run_id=None)
    model3, _ = _load_model3_predictions(qh_config, model3_run_id=None)
    qh = pd.concat([phase27, model3], ignore_index=True)
    qh_scans = []
    for model_id in sorted(qh["model_id"].astype(str).unique().tolist()):
        sub = qh[qh["model_id"].astype(str) == model_id].copy()
        sub = sub.rename(columns={"model_id": "candidate_key"})
        qh_scans.append(_candidate_scan(sub, model_id, periods_per_day=96, horizon_days=5))

    output_root = REPO_ROOT / "data" / "02_Forecasting" / "01_DA_prices" / "scenario_evaluation" / "dplus4_applicability"
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_dplus4_applicability_scan")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    payload = {
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "hourly": {
            "status": _classify_status(hourly_scans),
            "candidate_scans": hourly_scans,
        },
        "quarter_hour": {
            "status": _classify_status(qh_scans),
            "candidate_scans": qh_scans,
        },
        "global_status": _classify_status(hourly_scans + qh_scans),
        "notes": [
            "This scan does not generate D+4 scenarios.",
            "Coherent D+4 requires complete 5-day residual blocks and causal source filtering by block end.",
            "If full blocks are sparse, fallback is daily-independent sampling.",
        ],
    }
    (run_dir / "dplus4_applicability_report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pd.DataFrame(hourly_scans).to_csv(run_dir / "hourly_candidate_scan.csv", index=False)
    pd.DataFrame(qh_scans).to_csv(run_dir / "quarter_hour_candidate_scan.csv", index=False)
    print(json.dumps({"run_dir": str(run_dir), "global_status": payload["global_status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
