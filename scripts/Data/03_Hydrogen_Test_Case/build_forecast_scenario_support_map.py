from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "docs"
TZ = "Europe/Amsterdam"

SPLIT_ORDER = {"train": 0, "validation": 1, "test": 2}

FILE_COLS = {
    "hourly_thesis_combo": [
        "candidate_key",
        "candidate_label",
        "dataset_split",
        "delivery_day",
        "forecast_origin_utc",
        "period_timestamp",
        "scenario_id",
        "probability",
    ],
    "hourly_thesis_xgb": [
        "candidate_key",
        "candidate_label",
        "dataset_split",
        "delivery_day",
        "forecast_origin_utc",
        "period_timestamp",
        "scenario_id",
        "probability",
    ],
    "hourly_legacy_raw": [
        "candidate_key",
        "candidate_label",
        "dataset_split",
        "delivery_day",
        "period_timestamp",
        "scenario_id",
        "probability",
        "scenario_variant",
    ],
    "hourly_integration": [
        "model_id",
        "candidate_label",
        "dataset_split",
        "delivery_day",
        "forecast_origin_utc",
        "delivery_start_utc",
        "scenario_id",
        "scenario_probability",
        "forecast_origin_reconstructed",
    ],
    "hourly_lear_benchmark": [
        "run_id",
        "model",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_delivery_local_date",
        "lead_day",
        "y_true",
        "y_pred",
    ],
    "hourly_xgb_benchmark": [
        "run_id",
        "model",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_delivery_local_date",
        "lead_day",
        "y_true",
        "y_pred",
    ],
    "hourly_anchor_export": [
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "model",
        "model_family",
        "dataset_split",
        "y_pred",
    ],
    "hourly_lago_dplus4": [
        "run_id",
        "model",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_delivery_local_date",
        "lead_day",
        "y_true",
        "y_pred",
    ],
    "hourly_actuals": ["timestamp_utc", "price_eur_per_mwh"],
    "qh_targets": [
        "delivery_start_local_date",
        "target_timestamp_utc",
        "dataset_split",
        "forecast_origin_utc",
        "is_observed_target",
        "y_true",
    ],
    "qh_model3": [
        "model_id",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "delivery_local_date",
        "lead_day",
        "is_observed_target",
        "y_true",
        "y_pred",
        "scenario_variant",
    ],
    "qh_phase27": [
        "model_id",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "delivery_local_date",
        "lead_day",
        "y_true",
        "y_pred",
    ],
    "qh_scenarios": [
        "model_id",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "target_local_date",
        "lead_day",
        "scenario_id",
        "scenario_probability",
        "y_true",
    ],
    "qh_actuals": [
        "timestamp_utc",
        "delivery_local_date",
        "counterfactual_actual_price_eur_per_mwh",
    ],
    "bridge_phase07": ["timestamp_utc", "region", "price_eur_per_mwh", "bridge_source"],
    "bridge_observed": ["timestamp_utc", "region", "price_eur_per_mwh", "resolution"],
}

FILE_MAP = {
    "hourly_thesis_combo": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/scenario_prices_long.csv",
    "hourly_thesis_xgb": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_084412/scenario_prices_long.csv",
    "hourly_legacy_raw": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/scenario_prices_long.csv",
    "hourly_lear_integration": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/legacy_variant_integration_candidates/hourly_lear_fs3_promoted_base_plus_b_integration_candidate/scenario_prices_long.csv",
    "hourly_xgb_integration": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/legacy_variant_integration_candidates/hourly_xgboost_fs3_pruned_base_plus_b_integration_candidate/scenario_prices_long.csv",
    "hourly_lear_benchmark": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_151547_lear_fs3_combo_pruned_candidate_benchmark/predictions_long.parquet",
    "hourly_xgb_benchmark": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark/predictions_long.parquet",
    "hourly_anchor_export": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run/predictions_long.csv",
    "hourly_lago_dplus4": ROOT
    / "data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/20260508_122730_lago_lear_six_year_benchmark/predictions_long.parquet",
    "hourly_actuals": ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv",
    "qh_targets": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/targets_by_origin.csv",
    "qh_model3": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_model3_lear_strict/20260511_183919_qh_model3_lear_strict_full_run/predictions_long.csv",
    "qh_phase27": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_phase2_7_hourly_parity/20260506_091021_qh_fs1_phase2_7_hourly_parity/predictions_long.csv",
    "qh_scenarios": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/scenario_prices_long.csv",
    "qh_actuals": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/canonical_v1/synthetic_actual_15min_canonical.csv",
    "bridge_phase07": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/20260505_134716_phase07_realistic_track_a/bridged_hourly_target_input_all_regions.csv",
    "bridge_observed": ROOT
    / "data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/hourly_backbone_bridge_input.csv",
}


def model_family(model_id: str) -> str:
    text = (model_id or "").lower()
    if "strict" in text:
        return "LEAR Strict"
    if "xgboost" in text or "xgb" in text:
        return "XGBoost FS3"
    if "lear" in text:
        return "LEAR FS3"
    return "other"


def ordered_splits(values) -> tuple[str, str]:
    vals = [str(v) for v in values if pd.notna(v)]
    if not vals:
        return "", ""
    uniq = sorted(set(vals), key=lambda x: SPLIT_ORDER.get(x, 99))
    return uniq[0], uniq[-1]


def utc(series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def local_dates(series) -> pd.Series:
    return utc(series).dt.tz_convert(TZ).dt.date


class Loader:
    def __init__(self):
        self.cache: dict[str, pd.DataFrame] = {}

    def get(self, key: str) -> pd.DataFrame:
        if key in self.cache:
            return self.cache[key]
        path = FILE_MAP[key]
        cols = FILE_COLS["hourly_integration"] if "integration" in key else FILE_COLS[key]
        if path.suffix == ".parquet":
            df = pd.read_parquet(path, columns=cols)
        else:
            df = pd.read_csv(path, usecols=cols, low_memory=False)
        self.cache[key] = df
        return df


def summarize_frame(df: pd.DataFrame | None, artifact_type: str) -> dict[str, object]:
    out = {
        "forecast_origin_min_utc": "",
        "forecast_origin_max_utc": "",
        "delivery_start_min_utc": "",
        "delivery_start_max_utc": "",
        "delivery_day_min": "",
        "delivery_day_max": "",
        "dataset_split_min": "",
        "dataset_split_max": "",
        "scenario_count_min": "",
        "scenario_count_median": "",
        "scenario_count_max": "",
        "probability_mass_check": "",
    }
    if df is None or df.empty:
        return out

    if "dataset_split" in df.columns:
        out["dataset_split_min"], out["dataset_split_max"] = ordered_splits(
            df["dataset_split"].dropna().unique()
        )

    if "forecast_origin_utc" in df.columns:
        values = utc(df["forecast_origin_utc"])
        if values.notna().any():
            out["forecast_origin_min_utc"] = values.min().isoformat()
            out["forecast_origin_max_utc"] = values.max().isoformat()

    delivery_ts_col = None
    for col in ["delivery_start_utc", "period_timestamp", "target_timestamp_utc", "timestamp_utc"]:
        if col in df.columns:
            delivery_ts_col = col
            break
    if delivery_ts_col:
        values = utc(df[delivery_ts_col])
        if values.notna().any():
            out["delivery_start_min_utc"] = values.min().isoformat()
            out["delivery_start_max_utc"] = values.max().isoformat()

    if "delivery_day" in df.columns:
        day_values = pd.to_datetime(df["delivery_day"], errors="coerce").dt.date
    elif "target_delivery_local_date" in df.columns:
        day_values = pd.to_datetime(df["target_delivery_local_date"], errors="coerce").dt.date
    elif "delivery_local_date" in df.columns:
        day_values = pd.to_datetime(df["delivery_local_date"], errors="coerce").dt.date
    elif "target_local_date" in df.columns:
        day_values = pd.to_datetime(df["target_local_date"], errors="coerce").dt.date
    elif "delivery_start_local_date" in df.columns:
        day_values = pd.to_datetime(df["delivery_start_local_date"], errors="coerce").dt.date
    elif delivery_ts_col:
        day_values = local_dates(df[delivery_ts_col])
    else:
        day_values = None
    if day_values is not None and len(day_values.dropna()) > 0:
        out["delivery_day_min"] = day_values.min().isoformat()
        out["delivery_day_max"] = day_values.max().isoformat()

    scenario_id_col = "scenario_id" if "scenario_id" in df.columns else None
    prob_col = (
        "scenario_probability"
        if "scenario_probability" in df.columns
        else ("probability" if "probability" in df.columns else None)
    )
    if artifact_type == "scenario_prices" and scenario_id_col and prob_col:
        if "forecast_origin_utc" in df.columns:
            unique_probs = df[["forecast_origin_utc", scenario_id_col, prob_col]].drop_duplicates()
            counts = unique_probs.groupby("forecast_origin_utc")[scenario_id_col].nunique()
            out["scenario_count_min"] = int(counts.min())
            out["scenario_count_median"] = float(counts.median())
            out["scenario_count_max"] = int(counts.max())
            mass = unique_probs.groupby("forecast_origin_utc")[prob_col].sum()
            min_mass = float(mass.min())
            max_mass = float(mass.max())
            if abs(min_mass - 1.0) < 1e-9 and abs(max_mass - 1.0) < 1e-9:
                out["probability_mass_check"] = "pass_unique_scenario_sum_1.0"
            else:
                out["probability_mass_check"] = (
                    f"fail_unique_scenario_sum_{min_mass:.3f}_to_{max_mass:.3f}"
                )
        else:
            out["probability_mass_check"] = "not_checkable_forecast_origin_missing"
    return out


def inventory_specs():
    return [
        {
            "artifact_id": "hourly_lear_fs3_thesis_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_thesis_combo",
            "filters": {"candidate_key": "lear_fs3_combo_pruned_candidate"},
            "model_id": "lear_fs3_combo_pruned_candidate",
            "model_family": "LEAR FS3",
            "candidate_label": "LEAR FS3 pruned candidate",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260426_151547_lear_fs3_combo_pruned_candidate_benchmark",
            "notes": "Catalog entry hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate; delivery support reaches 2025-09-26 only.",
        },
        {
            "artifact_id": "hourly_lear_strict_thesis_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_thesis_combo",
            "filters": {"candidate_key": "lear_strict_hourly_anchor_export"},
            "model_id": "lear_strict_hourly_anchor_export",
            "model_family": "LEAR Strict",
            "candidate_label": "LEAR STRICT hourly anchor",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run",
            "notes": "Catalog default artifact; support belongs to the later observed quarter-hour bridge window, not the 2024-10-01 to 2025-09-30 hourly test year.",
        },
        {
            "artifact_id": "hourly_20260516_002902_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/scenario_generation_run_summary.json",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_combo",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "run manifest",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_002902",
            "notes": "Scenario generation run summary for the combined LEAR FS3 pruned candidate + LEAR Strict hourly anchor export.",
        },
        {
            "artifact_id": "hourly_20260516_002902_config",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/scenario_generation_config.json",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_combo",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "run config",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_002902",
            "notes": "Companion config for the thesis-grade LEAR FS3 + LEAR Strict scenario run.",
        },
        {
            "artifact_id": "hourly_20260516_002902_recommendation",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/final_scenario_recommendation.json",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_combo",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "final scenario recommendation",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_002902",
            "notes": "Default candidate = LEAR FS3 pruned candidate; robustness candidate = LEAR STRICT hourly anchor.",
        },
        {
            "artifact_id": "hourly_20260516_002902_selected_candidates",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_002902/selected_candidate_keys.csv",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_combo",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "selected candidate keys",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_002902",
            "notes": "Selected candidate keys file for the combined LEAR FS3 + LEAR Strict run.",
        },
        {
            "artifact_id": "hourly_xgboost_thesis_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_084412/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_thesis_xgb",
            "filters": {"candidate_key": "xgboost_fs3_combo_pruned_candidate"},
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "XGBoost FS3 pruned candidate",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark",
            "notes": "Catalog entry hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate; delivery support reaches 2025-09-26 only.",
        },
        {
            "artifact_id": "hourly_20260516_084412_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_084412/scenario_generation_run_summary.json",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_xgb",
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "run manifest",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_084412",
            "notes": "Scenario generation run summary for the thesis-grade XGBoost FS3 D-only scenario file.",
        },
        {
            "artifact_id": "hourly_20260516_084412_config",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_084412/scenario_generation_config.json",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_xgb",
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "run config",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_084412",
            "notes": "Companion config for the thesis-grade XGBoost scenario run.",
        },
        {
            "artifact_id": "hourly_20260516_084412_recommendation",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_084412/final_scenario_recommendation.json",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_xgb",
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "final scenario recommendation",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_084412",
            "notes": "Default and robustness candidate are both XGBoost FS3 pruned candidate with tail_stress_v1.",
        },
        {
            "artifact_id": "hourly_20260516_084412_selected_candidates",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260516_084412/selected_candidate_keys.csv",
            "artifact_type": "manifest",
            "data_key": "hourly_thesis_xgb",
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "selected candidate keys",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "true",
            "validation_mode": "thesis_grade",
            "source_run_id": "20260516_084412",
            "notes": "Selected candidate keys file for the thesis-grade XGBoost run.",
        },
        {
            "artifact_id": "hourly_lear_fs3_integration_candidate_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/legacy_variant_integration_candidates/hourly_lear_fs3_promoted_base_plus_b_integration_candidate/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_lear_integration",
            "model_id": "lear_fs3_combo_promoted",
            "model_family": "LEAR FS3",
            "candidate_label": "LEAR FS3 promoted",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "true",
            "thesis_grade": "false",
            "validation_mode": "integration_candidate",
            "source_run_id": "20260429_193206_01_da_price_scenario_generation_hourly",
            "notes": "Single-variant export from the legacy bundled artifact; valid probability mass after variant selection.",
        },
        {
            "artifact_id": "hourly_xgboost_integration_candidate_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/legacy_variant_integration_candidates/hourly_xgboost_fs3_pruned_base_plus_b_integration_candidate/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_xgb_integration",
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "XGBoost FS3 pruned candidate",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "true",
            "thesis_grade": "false",
            "validation_mode": "integration_candidate",
            "source_run_id": "20260429_193206_01_da_price_scenario_generation_hourly",
            "notes": "Single-variant export from the legacy bundled artifact; valid probability mass after variant selection.",
        },
        {
            "artifact_id": "hourly_legacy_bundled_lear_fs3_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_legacy_raw",
            "filters": {"candidate_key": "lear_fs3_combo_promoted"},
            "model_id": "lear_fs3_combo_promoted",
            "model_family": "LEAR FS3",
            "candidate_label": "LEAR FS3 promoted",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "unknown",
            "thesis_grade": "false",
            "validation_mode": "legacy_bundled_source",
            "source_run_id": "20260429_193206",
            "notes": "Bundled four-variant source artifact; unique-scenario probability mass sums to 4.0 before variant selection.",
        },
        {
            "artifact_id": "hourly_legacy_bundled_xgboost_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "hourly_legacy_raw",
            "filters": {"candidate_key": "xgboost_fs3_combo_pruned_candidate"},
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "XGBoost FS3 pruned candidate",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "unknown",
            "thesis_grade": "false",
            "validation_mode": "legacy_bundled_source",
            "source_run_id": "20260429_193206",
            "notes": "Bundled four-variant source artifact; unique-scenario probability mass sums to 4.0 before variant selection.",
        },
        {
            "artifact_id": "hourly_20260429_193206_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/scenario_generation_run_summary.json",
            "artifact_type": "manifest",
            "data_key": "hourly_legacy_raw",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "run manifest",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "unknown",
            "thesis_grade": "false",
            "validation_mode": "legacy_bundled_source",
            "source_run_id": "20260429_193206",
            "notes": "Legacy hourly scenario run summary backing the integration-candidate exports.",
        },
        {
            "artifact_id": "hourly_20260429_193206_config",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/scenario_generation_config.json",
            "artifact_type": "manifest",
            "data_key": "hourly_legacy_raw",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "run config",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "unknown",
            "thesis_grade": "false",
            "validation_mode": "legacy_bundled_source",
            "source_run_id": "20260429_193206",
            "notes": "Legacy hourly scenario config backing the integration-candidate exports.",
        },
        {
            "artifact_id": "hourly_20260429_193206_recommendation",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly/20260429_193206/final_scenario_recommendation.json",
            "artifact_type": "manifest",
            "data_key": "hourly_legacy_raw",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "final scenario recommendation",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_ONLY",
            "forecast_origin_reconstructed": "unknown",
            "thesis_grade": "false",
            "validation_mode": "legacy_bundled_source",
            "source_run_id": "20260429_193206",
            "notes": "Legacy recommendation selects LEAR FS3 promoted as default and XGBoost FS3 pruned candidate as robustness under base_plus_b.",
        },
        {
            "artifact_id": "hourly_lear_fs3_benchmark_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_151547_lear_fs3_combo_pruned_candidate_benchmark/predictions_long.parquet",
            "artifact_type": "forecast_predictions",
            "data_key": "hourly_lear_benchmark",
            "filters": {"model": "lear_fs3_combo_promoted"},
            "model_id": "lear_fs3_combo_pruned_candidate",
            "model_family": "LEAR FS3",
            "candidate_label": "LEAR FS3 pruned candidate benchmark run",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "benchmark",
            "source_run_id": "20260426_151547_lear_fs3_combo_pruned_candidate_benchmark",
            "notes": "Lead-day forecast file spans D..D+4; internal model column is lear_fs3_combo_promoted.",
        },
        {
            "artifact_id": "hourly_xgboost_fs3_benchmark_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/runs/20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark/predictions_long.parquet",
            "artifact_type": "forecast_predictions",
            "data_key": "hourly_xgb_benchmark",
            "filters": {"model": "xgboost_fs3_combo_promoted"},
            "model_id": "xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "XGBoost FS3 pruned candidate benchmark run",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "benchmark",
            "source_run_id": "20260426_153605_xgboost_fs3_combo_pruned_candidate_benchmark",
            "notes": "Lead-day forecast file spans D..D+4; internal model column is xgboost_fs3_combo_promoted.",
        },
        {
            "artifact_id": "hourly_lear_strict_observed_qh_anchor_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run/predictions_long.csv",
            "artifact_type": "forecast_predictions",
            "data_key": "hourly_anchor_export",
            "filters": {"model": "lear_lago_direct_dplus4_strict_no_future_1092"},
            "model_id": "lear_strict_hourly_anchor_export",
            "model_family": "LEAR Strict",
            "candidate_label": "LEAR STRICT hourly anchor export",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_bridge_export",
            "source_run_id": "20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run",
            "notes": "Observed quarter-hour bridge export over the later 2025/2026 window; not aligned to the hourly 2024/2025 test year.",
        },
        {
            "artifact_id": "hourly_lago_dplus4_forecast_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/hourly_da/runs_lago_lear/20260508_122730_lago_lear_six_year_benchmark/predictions_long.parquet",
            "artifact_type": "forecast_predictions",
            "data_key": "hourly_lago_dplus4",
            "filters": {"model": "lear_lago_direct_dplus4_strict_no_future_1092"},
            "lead_day_only": 4,
            "model_id": "lear_lago_direct_dplus4_strict_no_future_1092",
            "model_family": "LEAR Strict",
            "candidate_label": "LEAR LAGO direct D+4 strict no-future",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "D_PLUS_4",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "benchmark",
            "source_run_id": "20260508_122730_lago_lear_six_year_benchmark",
            "notes": "Only forecast predictions are present; no matching D+4 scenario_prices artifact was found under the audited roots.",
        },
        {
            "artifact_id": "hourly_observed_actual_prices",
            "file_path": "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv",
            "artifact_type": "actual_prices",
            "data_key": "hourly_actuals",
            "model_id": "nl_hourly_da_observed",
            "model_family": "other",
            "candidate_label": "Observed hourly DA market prices",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "unknown",
            "forecast_origin_reconstructed": "n/a",
            "thesis_grade": "false",
            "validation_mode": "truth_source",
            "source_run_id": "",
            "notes": "Settlement truth source for hourly experiments.",
        },
        {
            "artifact_id": "qh_observed_targets_by_origin",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/targets_by_origin.csv",
            "artifact_type": "actual_prices",
            "data_key": "qh_targets",
            "observed_only": True,
            "model_id": "observed_market_targets",
            "model_family": "other",
            "candidate_label": "Observed quarter-hour DA targets by origin",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260503_174631_observed_market_deterministic_forecast",
            "notes": "Observed-target-only truth store; non-observed targets remain in the file but are excluded here.",
        },
        {
            "artifact_id": "qh_observed_deterministic_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/run_summary.json",
            "artifact_type": "manifest",
            "data_key": "qh_targets",
            "observed_only": True,
            "model_id": "observed_market_targets",
            "model_family": "other",
            "candidate_label": "observed market run summary",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260503_174631_observed_market_deterministic_forecast",
            "notes": "Observed-market deterministic forecast run summary; split policy is 2025-09-27 to 2026-04-30 with observed-target-only scoring.",
        },
        {
            "artifact_id": "qh_lear_strict_observed_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_model3_lear_strict/20260511_183919_qh_model3_lear_strict_full_run/predictions_long.csv",
            "artifact_type": "forecast_predictions",
            "data_key": "qh_model3",
            "filters": {"model_id": "qh-fs1__mean_shape__hourly_anchor__lear_strict"},
            "observed_only": True,
            "model_id": "qh-fs1__mean_shape__hourly_anchor__lear_strict",
            "model_family": "LEAR Strict",
            "candidate_label": "QH FS1 mean-shape with LEAR Strict hourly anchor",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260511_183919_qh_model3_lear_strict_full_run",
            "notes": "Deterministic quarter-hour LEAR Strict extension; observed-target-only scoring preserved.",
        },
        {
            "artifact_id": "qh_lear_fs3_observed_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_phase2_7_hourly_parity/20260506_091021_qh_fs1_phase2_7_hourly_parity/predictions_long.csv",
            "artifact_type": "forecast_predictions",
            "data_key": "qh_phase27",
            "filters": {"model_id": "qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted"},
            "model_id": "qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted",
            "model_family": "LEAR FS3",
            "candidate_label": "QH FS1 LEAR hourly-anchor parity",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260506_091021_qh_fs1_phase2_7_hourly_parity",
            "notes": "Quarter-hour LEAR parity export for the later observed 2025/2026 window.",
        },
        {
            "artifact_id": "qh_xgboost_observed_predictions",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_phase2_7_hourly_parity/20260506_091021_qh_fs1_phase2_7_hourly_parity/predictions_long.csv",
            "artifact_type": "forecast_predictions",
            "data_key": "qh_phase27",
            "filters": {"model_id": "qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate"},
            "model_id": "qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "QH FS1 XGBoost hourly-anchor parity",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260506_091021_qh_fs1_phase2_7_hourly_parity",
            "notes": "Quarter-hour XGBoost parity export for the later observed 2025/2026 window.",
        },
        {
            "artifact_id": "qh_phase27_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_phase2_7_hourly_parity/20260506_091021_qh_fs1_phase2_7_hourly_parity/run_summary.json",
            "artifact_type": "manifest",
            "data_key": "qh_phase27",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "phase2_7 parity run summary",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260506_091021_qh_fs1_phase2_7_hourly_parity",
            "notes": "Run summary for the two-model quarter-hour parity forecasts aligned to the observed market window.",
        },
        {
            "artifact_id": "qh_model3_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_model3_lear_strict/20260511_183919_qh_model3_lear_strict_full_run/run_summary.json",
            "artifact_type": "manifest",
            "data_key": "qh_model3",
            "model_id": "qh-fs1__mean_shape__hourly_anchor__lear_strict",
            "model_family": "LEAR Strict",
            "candidate_label": "model3 run summary",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_eval",
            "source_run_id": "20260511_183919_qh_model3_lear_strict_full_run",
            "notes": "Run summary for the LEAR Strict quarter-hour extension with 95.07% row coverage versus expected anchors.",
        },
        {
            "artifact_id": "qh_lear_fs3_observed_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "qh_scenarios",
            "filters": {"model_id": "qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted"},
            "model_id": "qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted",
            "model_family": "LEAR FS3",
            "candidate_label": "QH LEAR observed-market scenarios",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_scenarios",
            "source_run_id": "20260511_192858_qh_scenario_generation_full",
            "notes": "Quarter-hour scenario file calibrated on observed train/validation residuals only.",
        },
        {
            "artifact_id": "qh_xgboost_observed_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "qh_scenarios",
            "filters": {"model_id": "qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate"},
            "model_id": "qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate",
            "model_family": "XGBoost FS3",
            "candidate_label": "QH XGBoost observed-market scenarios",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_scenarios",
            "source_run_id": "20260511_192858_qh_scenario_generation_full",
            "notes": "Quarter-hour scenario file calibrated on observed train/validation residuals only.",
        },
        {
            "artifact_id": "qh_lear_strict_observed_scenarios",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/scenario_prices_long.csv",
            "artifact_type": "scenario_prices",
            "data_key": "qh_scenarios",
            "filters": {"model_id": "qh-fs1__mean_shape__hourly_anchor__lear_strict"},
            "model_id": "qh-fs1__mean_shape__hourly_anchor__lear_strict",
            "model_family": "LEAR Strict",
            "candidate_label": "QH LEAR Strict observed-market scenarios",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_scenarios",
            "source_run_id": "20260511_192858_qh_scenario_generation_full",
            "notes": "Quarter-hour scenario file calibrated on observed train/validation residuals only.",
        },
        {
            "artifact_id": "qh_scenario_generation_full_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/scenario_generation_run_summary.json",
            "artifact_type": "manifest",
            "data_key": "qh_scenarios",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "scenario generation run summary",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_scenarios",
            "source_run_id": "20260511_192858_qh_scenario_generation_full",
            "notes": "All-three-model quarter-hour scenario generation summary; validation checks passed and calibration uses observed targets only.",
        },
        {
            "artifact_id": "qh_scenario_generation_full_config",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_scenario_generation/20260511_192858_qh_scenario_generation_full/scenario_generation_config.json",
            "artifact_type": "manifest",
            "data_key": "qh_scenarios",
            "model_id": "multiple",
            "model_family": "other",
            "candidate_label": "scenario generation config",
            "granularity": "quarter_hour",
            "market_truth_type": "observed",
            "horizon": "lead_day",
            "forecast_origin_reconstructed": "false",
            "thesis_grade": "false",
            "validation_mode": "observed_market_scenarios",
            "source_run_id": "20260511_192858_qh_scenario_generation_full",
            "notes": "Scenario generation config for the observed-market quarter-hour scenarios.",
        },
        {
            "artifact_id": "qh_counterfactual_actual_canonical",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/canonical_v1/synthetic_actual_15min_canonical.csv",
            "artifact_type": "actual_prices",
            "data_key": "qh_actuals",
            "model_id": "synthetic_actual_15min_canonical",
            "model_family": "other",
            "candidate_label": "Frozen counterfactual 15-minute actual path",
            "granularity": "quarter_hour",
            "market_truth_type": "counterfactual",
            "horizon": "unknown",
            "forecast_origin_reconstructed": "n/a",
            "thesis_grade": "false",
            "validation_mode": "counterfactual_freeze",
            "source_run_id": "20260502_115515_canonical_actual_freeze",
            "notes": "Frozen synthetic within-hour path for 2024-10-01 to 2025-09-30; must not be treated as observed-market scoring truth.",
        },
        {
            "artifact_id": "qh_counterfactual_canonical_run_summary",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/canonical_actual_runs/20260502_115515_canonical_actual_freeze/run_summary.json",
            "artifact_type": "manifest",
            "data_key": "qh_actuals",
            "model_id": "synthetic_actual_15min_canonical",
            "model_family": "other",
            "candidate_label": "canonical actual freeze run summary",
            "granularity": "quarter_hour",
            "market_truth_type": "counterfactual",
            "horizon": "unknown",
            "forecast_origin_reconstructed": "n/a",
            "thesis_grade": "false",
            "validation_mode": "counterfactual_freeze",
            "source_run_id": "20260502_115515_canonical_actual_freeze",
            "notes": "Counterfactual freeze manifest; canonical period is 2024-10-01 to 2025-09-30.",
        },
        {
            "artifact_id": "qh_phase07_hourly_bridge_file",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/20260505_134716_phase07_realistic_track_a/bridged_hourly_target_input_all_regions.csv",
            "artifact_type": "bridge_file",
            "data_key": "bridge_phase07",
            "model_id": "phase07_hourly_bridge",
            "model_family": "other",
            "candidate_label": "Phase07 hourly bridge input",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "unknown",
            "forecast_origin_reconstructed": "n/a",
            "thesis_grade": "false",
            "validation_mode": "bridge",
            "source_run_id": "20260505_134716_phase07_realistic_track_a",
            "notes": "Hourly multi-region bridge used for the observed-market quarter-hour realistic track.",
        },
        {
            "artifact_id": "qh_observed_hourly_backbone_bridge_file",
            "file_path": "data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/hourly_backbone_bridge_input.csv",
            "artifact_type": "bridge_file",
            "data_key": "bridge_observed",
            "model_id": "observed_market_hourly_bridge",
            "model_family": "other",
            "candidate_label": "Observed-market hourly backbone bridge",
            "granularity": "hourly",
            "market_truth_type": "observed",
            "horizon": "unknown",
            "forecast_origin_reconstructed": "n/a",
            "thesis_grade": "false",
            "validation_mode": "bridge",
            "source_run_id": "20260503_174631_observed_market_deterministic_forecast",
            "notes": "Hourly bridge input used to align the observed quarter-hour deterministic pipeline.",
        },
    ]


def build_inventory(loader: Loader) -> pd.DataFrame:
    rows = []
    for spec in inventory_specs():
        path = ROOT / spec["file_path"]
        exists = path.exists()
        df = None
        if exists and spec.get("data_key"):
            df = loader.get(spec["data_key"]).copy()
            for col, value in spec.get("filters", {}).items():
                df = df[df[col].eq(value)]
            if spec.get("observed_only") and "is_observed_target" in df.columns:
                df = df[df["is_observed_target"].eq(True)]
            if spec.get("lead_day_only") is not None and "lead_day" in df.columns:
                df = df[df["lead_day"].eq(spec["lead_day_only"])]
        stats = summarize_frame(df, spec["artifact_type"]) if exists else summarize_frame(None, spec["artifact_type"])
        row = {
            "artifact_id": spec["artifact_id"],
            "file_path": spec["file_path"].replace("\\", "/"),
            "exists": exists,
            "artifact_type": spec["artifact_type"],
            "model_id": spec["model_id"],
            "model_family": spec["model_family"],
            "candidate_label": spec["candidate_label"],
            "granularity": spec["granularity"],
            "market_truth_type": spec["market_truth_type"],
            "horizon": spec["horizon"],
            **stats,
            "forecast_origin_reconstructed": spec["forecast_origin_reconstructed"],
            "thesis_grade": spec["thesis_grade"],
            "validation_mode": spec["validation_mode"],
            "source_run_id": spec["source_run_id"],
            "notes": spec["notes"],
        }
        rows.append(row)
    return pd.DataFrame(rows)


def build_matrix(loader: Loader) -> pd.DataFrame:
    hourly_lear = loader.get("hourly_thesis_combo")
    hourly_xgb = loader.get("hourly_thesis_xgb")

    lear_fs3_days = set(
        pd.to_datetime(
            hourly_lear.loc[hourly_lear["candidate_key"].eq("lear_fs3_combo_pruned_candidate"), "delivery_day"]
        ).dt.date.unique()
    )
    strict_days = set(
        pd.to_datetime(
            hourly_lear.loc[hourly_lear["candidate_key"].eq("lear_strict_hourly_anchor_export"), "delivery_day"]
        ).dt.date.unique()
    )
    xgb_days = set(
        pd.to_datetime(
            hourly_xgb.loc[hourly_xgb["candidate_key"].eq("xgboost_fs3_combo_pruned_candidate"), "delivery_day"]
        ).dt.date.unique()
    )
    hourly_test_days = set(pd.date_range("2024-10-01", "2025-09-30", freq="D").date)
    hourly_validation_days = set(pd.date_range("2023-10-01", "2024-09-30", freq="D").date)

    qh_scen = loader.get("qh_scenarios").copy()
    qh_scen["target_local_date"] = pd.to_datetime(qh_scen["target_local_date"]).dt.date
    qh_sets = {mid: set(g["target_local_date"].unique()) for mid, g in qh_scen.groupby("model_id")}
    qh_common = sorted(set.intersection(*qh_sets.values()))
    qh_test_common = sorted(
        set.intersection(
            *(
                set(g.loc[g["dataset_split"].eq("test"), "target_local_date"].unique())
                for _, g in qh_scen.groupby("model_id")
            )
        )
    )

    rows = [
        {
            "experiment_id": "hourly_donly_three_model_test_year",
            "intended_question": "Can the three hourly scenario models be compared fairly on the common 2024-10-01 to 2025-09-30 D-only test year?",
            "required_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "required_period": "2024-10-01 to 2025-09-30",
            "required_granularity": "hourly",
            "required_truth_type": "observed",
            "available_models": "LEAR FS3 thesis-grade tail_stress_v1; XGBoost FS3 thesis-grade tail_stress_v1",
            "missing_models": "LEAR Strict on the same delivery window",
            "common_support_start": "",
            "common_support_end": "",
            "common_support_days": 0,
            "ready_status": "blocked",
            "blocker": "No three-model overlap exists inside the intended test year. LEAR Strict support is 2026-02-05 to 2026-04-30, while LEAR FS3 and XGBoost only cover D-only deliveries through 2025-09-26.",
            "allowed_use": "not_allowed",
            "methodological_notes": "The current LEAR FS3 and XGBoost D-only scenario files inherit a multi-horizon origin cutoff, so their D-only slice ends four days before 2025-09-30.",
        },
        {
            "experiment_id": "hourly_donly_selected_test_weeks",
            "intended_question": "Can the current selected weeks support a clean three-model hourly D-only comparison?",
            "required_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "required_period": "Selected weeks in selected_weeks.yaml",
            "required_granularity": "hourly",
            "required_truth_type": "observed",
            "available_models": "LEAR FS3 and XGBoost on the winter and volatility weeks only",
            "missing_models": "LEAR Strict on all selected weeks; all models on typical_summer because it is outside the intended test year",
            "common_support_start": "",
            "common_support_end": "",
            "common_support_days": 0,
            "ready_status": "blocked",
            "blocker": "typical_summer is 2024-06-24 to 2024-06-30 and lies outside the intended hourly test period. LEAR Strict also has no support on the in-period winter and volatility weeks.",
            "allowed_use": "not_allowed",
            "methodological_notes": "Selected-week experiments should be redefined after the hourly support window is fixed; otherwise they violate the test-period policy before optimisation even starts.",
        },
        {
            "experiment_id": "hourly_donly_validation_cvar_tuning",
            "intended_question": "Is there enough validation-period support to tune scenario choice or CVaR settings without using the final test year?",
            "required_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "required_period": "2023-10-01 to 2024-09-30",
            "required_granularity": "hourly",
            "required_truth_type": "observed",
            "available_models": "LEAR FS3 thesis-grade; XGBoost FS3 thesis-grade",
            "missing_models": "LEAR Strict validation-period scenario support",
            "common_support_start": "",
            "common_support_end": "",
            "common_support_days": 0,
            "ready_status": "partial",
            "blocker": "Three-model parity is unavailable. LEAR FS3 and XGBoost share 2023-10-05 to 2024-09-30, but LEAR Strict has no validation-era scenario support.",
            "allowed_use": "diagnostic_only",
            "methodological_notes": "A two-model LEAR FS3 versus XGBoost validation tuning exercise is possible, but it cannot justify a final three-model thesis ranking.",
        },
        {
            "experiment_id": "hourly_dplus4_if_available",
            "intended_question": "Are hourly D+4 optimisation artifacts available at all?",
            "required_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "required_period": "2024-10-01 to 2025-09-30 if used for final hourly comparison",
            "required_granularity": "hourly",
            "required_truth_type": "observed",
            "available_models": "LEAR Strict D+4 forecast predictions only",
            "missing_models": "D+4 scenario_prices for all three models; matched LEAR FS3 and XGBoost D+4 scenario exports; LEAR Strict support on the hourly test year",
            "common_support_start": "",
            "common_support_end": "",
            "common_support_days": 0,
            "ready_status": "partial",
            "blocker": "The audit found a LEAR Strict D+4 forecast file but no D+4 scenario_prices files under the audited roots.",
            "allowed_use": "diagnostic_only",
            "methodological_notes": "Treat D+4 as forecast-support-only until scenario generation is exported with explicit probabilities and a period that matches the intended comparison.",
        },
        {
            "experiment_id": "qh_counterfactual_full_year",
            "intended_question": "Can a full-year quarter-hour counterfactual experiment be run on the 2024-10-01 to 2025-09-30 hourly test year?",
            "required_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "required_period": "2024-10-01 to 2025-09-30",
            "required_granularity": "quarter_hour",
            "required_truth_type": "counterfactual",
            "available_models": "Frozen synthetic quarter-hour actual path; hourly LEAR FS3 and XGBoost D-only support on 2024-10-01 to 2025-09-26",
            "missing_models": "Quarter-hour predictions/scenarios aligned to 2024-10-01 to 2025-09-30; LEAR Strict hourly support on the same year",
            "common_support_start": "",
            "common_support_end": "",
            "common_support_days": 0,
            "ready_status": "partial",
            "blocker": "The synthetic actual path exists for the full year, but the quarter-hour model artifacts are on the later observed 2025/2026 window and LEAR Strict does not support the 2024/2025 hourly year.",
            "allowed_use": "diagnostic_only",
            "methodological_notes": "Any use of the frozen 15-minute path must stay explicitly labelled counterfactual or synthetic; it cannot be used as observed-market truth.",
        },
        {
            "experiment_id": "qh_observed_market_window",
            "intended_question": "Is there a valid observed-market quarter-hour window for separate optimisation experiments?",
            "required_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "required_period": "Later observed 2025/2026 quarter-hour window",
            "required_granularity": "quarter_hour",
            "required_truth_type": "observed",
            "available_models": "LEAR Strict; LEAR FS3; XGBoost FS3",
            "missing_models": "",
            "common_support_start": qh_common[0].isoformat(),
            "common_support_end": qh_common[-1].isoformat(),
            "common_support_days": len(qh_common),
            "ready_status": "ready",
            "blocker": "",
            "allowed_use": "thesis_result",
            "methodological_notes": f"Use observed targets only. All-three-model scenario common support is {qh_common[0]} to {qh_common[-1]}; the held-out all-three-model test subset is {qh_test_common[0]} to {qh_test_common[-1]} ({len(qh_test_common)} days).",
        },
        {
            "experiment_id": "qh_vs_hourly_matched_period_if_possible",
            "intended_question": "Can hourly and quarter-hour results be compared as a clean granularity effect on a matched period?",
            "required_models": "Same model families on the same delivery window and same truth type",
            "required_period": "Matched hourly and quarter-hour period",
            "required_granularity": "hourly_vs_quarter_hour",
            "required_truth_type": "matched",
            "available_models": "Hourly thesis-grade D-only scenarios on 2024/2025; quarter-hour observed artifacts on 2025/2026; quarter-hour counterfactual synthetic path on 2024/2025",
            "missing_models": "A matched observed quarter-hour window for the hourly test year, or a matched hourly three-model support window for the quarter-hour observed period",
            "common_support_start": "",
            "common_support_end": "",
            "common_support_days": 0,
            "ready_status": "blocked",
            "blocker": "The observed quarter-hour track is 2025/2026, while the final hourly comparison target is 2024/2025. The counterfactual quarter-hour track is synthetic, so it is not a clean observed granularity comparison.",
            "allowed_use": "not_allowed",
            "methodological_notes": "Without matched support and matched truth type, hourly-versus-quarter-hour results must be reported as separate studies rather than as a direct granularity claim.",
        },
    ]
    return pd.DataFrame(rows)


def build_report() -> str:
    lines = [
        "# Optimisation Data Support Map",
        "",
        "This is an audit-only support map. No optimisation runs were performed, no scenarios were regenerated, and no MILP code was changed.",
        "",
        "## Tracks",
        "",
        "- `Hourly D-only thesis track`: intended final comparison period is `2024-10-01` to `2025-09-30`.",
        "- `Hourly D+4 track`: forecast support exists, but scenario support was not found.",
        "- `Quarter-hour observed-market track`: separate observed 15-minute evaluation window in late `2025/2026` data.",
        "- `Quarter-hour counterfactual track`: frozen synthetic within-hour paths for `2024-10-01` to `2025-09-30`, which must stay labelled counterfactual.",
        "",
        "## Hourly Support Summary",
        "",
        "| Model | Artifact status | Delivery support | Thesis-grade | Notes |",
        "| --- | --- | --- | --- | --- |",
        "| LEAR Strict | thesis-grade scenario file exists | 2026-02-05 to 2026-04-30 | yes | later observed-quarter-hour bridge window, not the intended hourly test year |",
        "| LEAR FS3 | thesis-grade scenario file exists | 2023-10-05 to 2025-09-26 | yes | overlaps the hourly test year for 361 days only |",
        "| XGBoost FS3 | thesis-grade scenario file exists | 2023-10-05 to 2025-09-26 | yes | overlaps the hourly test year for 361 days only |",
        "| LEAR FS3 legacy integration candidate | single-variant export exists | 2024-10-01 to 2025-09-26 | no | reconstructed forecast origins; diagnostic/integration use only |",
        "| XGBoost FS3 legacy integration candidate | single-variant export exists | 2024-10-01 to 2025-09-26 | no | reconstructed forecast origins; diagnostic/integration use only |",
        "",
        "Three-model common support inside the intended hourly test period: `none`.",
        "",
        "Two-model LEAR FS3 / XGBoost support inside the intended hourly test period: `2024-10-01` to `2025-09-26` (`361` days).",
        "",
        "Likely reason for the LEAR FS3 / XGBoost stop at `2025-09-26`: the upstream benchmark and scenario generation were capped on a shared `D..D+4` rolling-origin window, so the last forecast origin is `2025-09-25`. That gives `D+4` support through `2025-09-30`, but only `D` support through `2025-09-26`.",
        "",
        "## Quarter-Hour Support Summary",
        "",
        "### Observed-market quarter-hour track",
        "",
        "- Observed target store: `2025-09-27` to `2026-04-30` on observed targets only.",
        "- Deterministic LEAR Strict quarter-hour extension: `2025-09-27` to `2026-04-30` with observed-target-only scoring.",
        "- Three-model quarter-hour scenario common support: `2026-01-03` to `2026-04-30` (`111` days).",
        "- Three-model held-out test support for quarter-hour scenarios: `2026-03-18` to `2026-04-30` (`38` days).",
        "",
        "### Counterfactual quarter-hour track",
        "",
        "- Frozen synthetic 15-minute actual path exists for `2024-10-01` to `2025-09-30` (`365` days).",
        "- This path is counterfactual/synthetic, not observed-market truth.",
        "- No matching three-model quarter-hour scenario or prediction exports were found on that same `2024/2025` counterfactual year.",
        "",
        "## Direct Answers",
        "",
        "- A. The intended hourly test period is `2024-10-01 to 2025-09-30`.",
        "- B. On that intended hourly period, no model currently has a thesis-grade scenario file with full end-to-end support through `2025-09-30`. LEAR FS3 and XGBoost thesis-grade scenarios cover `2024-10-01` to `2025-09-26`; LEAR Strict does not overlap the period at all.",
        "- C. No. LEAR Strict is not available on the same hourly test period as LEAR FS3 and XGBoost.",
        "- D. The LEAR Strict thesis-grade artifact was generated from the later observed quarter-hour bridge window, so its delivery support is `2026-02-05` to `2026-04-30`. Separately, the LEAR FS3 and XGBoost D-only scenario files inherit a multi-horizon cutoff that leaves the last four test-year days uncovered for `D`.",
        "- E. Observed quarter-hour artifacts are the observed target store (`2025-09-27` to `2026-04-30`), the LEAR Strict deterministic extension on the same window, the LEAR/XGBoost parity forecasts (`2026-01-01` to `2026-04-30`), and the three-model quarter-hour scenario file with common support `2026-01-03` to `2026-04-30`.",
        "- F. Counterfactual/synthetic quarter-hour artifacts are the frozen synthetic actual path under `frozen_actual_paths/canonical_v1`, covering `2024-10-01` to `2025-09-30`. It is suitable only for explicitly counterfactual experiments.",
        "- G. Currently fair comparisons are: LEAR FS3 versus XGBoost hourly D-only diagnostics on `2024-10-01` to `2025-09-26`; and three-model quarter-hour observed-market comparisons on the common observed window, especially the held-out `2026-03-18` to `2026-04-30` test slice.",
        "- H. Diagnostic-only comparisons are: two-model hourly validation tuning (LEAR FS3 versus XGBoost), any use of the legacy reconstructed integration-candidate scenario files, the available LEAR Strict D+4 forecast support without scenario exports, and any quarter-hour counterfactual run on the frozen synthetic path.",
        "- I. Blocked comparisons are: the hourly three-model thesis comparison on `2024-10-01` to `2025-09-30`; the current selected-week hourly comparison; and any clean hourly-versus-quarter-hour granularity claim on a matched observed period.",
        "- J. Next regeneration/export step: rerun or re-export the hourly D-only thesis-grade scenario set so all three hourly models expose the same delivery days on `2024-10-01` to `2025-09-30`, with explicit `forecast_origin_utc`, probabilities, and a D-only support definition that does not stop at `2025-09-26`.",
        "",
        "## Readiness Calls",
        "",
        "- `hourly_donly_three_model_test_year`: `blocked`",
        "- `hourly_donly_selected_test_weeks`: `blocked`",
        "- `hourly_donly_validation_cvar_tuning`: `partial`",
        "- `hourly_dplus4_if_available`: `partial`",
        "- `qh_counterfactual_full_year`: `partial`",
        "- `qh_observed_market_window`: `ready`",
        "- `qh_vs_hourly_matched_period_if_possible`: `blocked`",
        "",
        "## Methodological Guardrails",
        "",
        "- Quarter-hour observed-market experiments must score observed targets only.",
        "- Quarter-hour counterfactual experiments must stay labelled counterfactual or synthetic and must not be reported as observed-market evidence.",
        "- Hourly-versus-quarter-hour comparisons are not clean granularity comparisons unless period support and truth type are matched.",
    ]
    return "\n".join(lines) + "\n"


def main():
    _ = yaml.safe_load(
        (ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "scenario_catalog.yaml").read_text()
    )
    loader = Loader()
    inventory = build_inventory(loader)
    matrix = build_matrix(loader)
    inventory.to_csv(DOCS / "forecast_scenario_support_inventory.csv", index=False)
    matrix.to_csv(DOCS / "optimisation_experiment_readiness_matrix.csv", index=False)
    (DOCS / "optimisation_data_support_map.md").write_text(build_report(), encoding="utf-8")


if __name__ == "__main__":
    main()
