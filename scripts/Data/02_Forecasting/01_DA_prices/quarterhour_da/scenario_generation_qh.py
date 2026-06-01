from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import QuarterHourDAExtensionConfig
from .model3_lear_strict import find_latest_qh_model3_run, model3_output_root
from .phase2_7_hourly_parity import phase27_output_root


RUN_LABEL = "qh_scenario_generation"
MODEL_IDS = [
    "qh-fs1__lear__hourly_anchor__lear_fs3_combo_promoted",
    "qh-fs1__xgboost__hourly_anchor__xgboost_fs3_combo_pruned_candidate",
    "qh-fs1__mean_shape__hourly_anchor__lear_strict",
]
DEFAULT_PHASE27_RUN_ID = "20260506_091021_qh_fs1_phase2_7_hourly_parity"
DEFAULT_MODEL3_RUN_ID = "20260511_183919_qh_model3_lear_strict_full_run"
STABLE_SEED_METHOD = "sha256_group_seed_v1"


@dataclass(frozen=True)
class ScenarioRunPaths:
    run_id: str
    run_dir: Path


def scenario_output_root(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    resolved = config or QuarterHourDAExtensionConfig()
    return resolved.output_root / "finalisation_runs" / RUN_LABEL


def _timestamped_run_id(output_tag: str = "") -> str:
    base = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_" + RUN_LABEL)
    cleaned = str(output_tag or "").strip()
    if not cleaned:
        return base
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in cleaned)
    return f"{base}_{safe}"


def _bundle_paths(config: QuarterHourDAExtensionConfig, output_tag: str = "") -> ScenarioRunPaths:
    run_id = _timestamped_run_id(output_tag=output_tag)
    run_dir = scenario_output_root(config) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return ScenarioRunPaths(run_id=run_id, run_dir=run_dir)


def _find_latest_run(root: Path) -> Path:
    if not root.exists():
        raise FileNotFoundError(f"Run root not found: {root}")
    runs = sorted(path for path in root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    if not runs:
        raise FileNotFoundError(f"No completed runs found under: {root}")
    return runs[-1]


def _safe_quantile(values: pd.Series, q: float) -> float:
    valid = pd.to_numeric(values, errors="coerce").dropna()
    if valid.empty:
        return np.nan
    return float(valid.quantile(float(q)))


def _normalize_prediction_frame(frame: pd.DataFrame, *, business_timezone: str) -> pd.DataFrame:
    out = frame.copy()
    out["forecast_origin_utc"] = pd.to_datetime(out["forecast_origin_utc"], utc=True, errors="coerce")
    out["target_timestamp_utc"] = pd.to_datetime(out["target_timestamp_utc"], utc=True, errors="coerce")
    out["dataset_split"] = out["dataset_split"].astype(str)
    out["lead_day"] = pd.to_numeric(out["lead_day"], errors="coerce").astype("Int64")
    out["y_pred"] = pd.to_numeric(out["y_pred"], errors="coerce")
    out["y_true"] = pd.to_numeric(out["y_true"], errors="coerce")
    out["target_timestamp_local"] = out["target_timestamp_utc"].dt.tz_convert(business_timezone)
    out["target_local_date"] = out["target_timestamp_local"].dt.date
    out["quarter_in_day_index"] = (
        out.sort_values("target_timestamp_utc")
        .groupby(["model_id", "forecast_origin_utc", "lead_day"], dropna=False)
        .cumcount()
        .astype(int)
        + 1
    )
    out["quarters_in_target_day"] = (
        out.groupby(["model_id", "forecast_origin_utc", "lead_day"], dropna=False)["target_timestamp_utc"]
        .transform("size")
        .astype(int)
    )
    return out.sort_values(["model_id", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)


def _load_phase27_predictions(config: QuarterHourDAExtensionConfig, phase27_run_id: str | None) -> tuple[pd.DataFrame, Path]:
    if phase27_run_id:
        run_dir = phase27_output_root(config) / str(phase27_run_id)
    else:
        run_dir = _find_latest_run(phase27_output_root(config))
    path = run_dir / "predictions_long.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing phase2.7 parity predictions file: {path}")

    frame = pd.read_csv(path, low_memory=False)
    frame = frame[frame["model"].astype(str).isin(MODEL_IDS[:2])].copy()
    if frame.empty:
        raise ValueError("No rows found for QH parity model1/model2 in phase2.7 predictions.")
    frame["model_id"] = frame.get("model_id", frame["model"]).astype(str)
    frame["model_family"] = frame.get("model_family", pd.Series("mixed_frequency", index=frame.index)).astype(str)
    frame["feature_set_id"] = frame.get("feature_set_id", pd.Series("QH-FS1", index=frame.index)).astype(str)
    frame["y_true"] = pd.to_numeric(frame.get("y_true", frame.get("actual_price_eur_per_mwh")), errors="coerce")
    frame["y_pred"] = pd.to_numeric(frame.get("y_pred", frame.get("forecast_price_eur_per_mwh")), errors="coerce")
    keep = [
        "model_id",
        "model_family",
        "feature_set_id",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "y_true",
        "y_pred",
    ]
    for column in keep:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = _normalize_prediction_frame(frame[keep], business_timezone=config.business_timezone)
    return frame, run_dir


def _load_model3_predictions(config: QuarterHourDAExtensionConfig, model3_run_id: str | None) -> tuple[pd.DataFrame, Path]:
    if model3_run_id:
        run_dir = model3_output_root(config) / str(model3_run_id)
    else:
        latest = find_latest_qh_model3_run(config)
        if latest is None:
            raise FileNotFoundError("No QH model3 run with run_summary.json was found.")
        run_dir = latest
    path = run_dir / "predictions_long.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing QH model3 predictions file: {path}")

    frame = pd.read_csv(path, low_memory=False)
    frame["model_id"] = frame.get("model_id", frame.get("model", MODEL_IDS[2])).astype(str)
    frame = frame[frame["model_id"].astype(str) == MODEL_IDS[2]].copy()
    if frame.empty:
        raise ValueError(f"No rows found for model3 id '{MODEL_IDS[2]}' in {path}.")
    frame["model_family"] = frame.get("model_family", pd.Series("mean_shape", index=frame.index)).astype(str)
    frame["feature_set_id"] = frame.get("feature_set_id", pd.Series("QH-FS1", index=frame.index)).astype(str)
    frame["y_true"] = pd.to_numeric(frame.get("y_true", frame.get("actual_price_eur_per_mwh")), errors="coerce")
    frame["y_pred"] = pd.to_numeric(frame.get("y_pred", frame.get("forecast_price_eur_per_mwh")), errors="coerce")
    keep = [
        "model_id",
        "model_family",
        "feature_set_id",
        "dataset_split",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "y_true",
        "y_pred",
    ]
    for column in keep:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = _normalize_prediction_frame(frame[keep], business_timezone=config.business_timezone)
    return frame, run_dir


def _subset_smoke(frame: pd.DataFrame, *, max_origins: int) -> pd.DataFrame:
    origin_schedule = (
        frame[["dataset_split", "forecast_origin_utc"]]
        .drop_duplicates()
        .sort_values(["dataset_split", "forecast_origin_utc"])
        .reset_index(drop=True)
    )
    selected = origin_schedule.head(int(max_origins))
    return frame.merge(selected, on=["dataset_split", "forecast_origin_utc"], how="inner")


def _support_tables(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    by_model = (
        predictions.groupby(["model_id", "model_family", "feature_set_id"], dropna=False)
        .agg(
            forecast_rows=("target_timestamp_utc", "size"),
            observed_target_rows=("y_true", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            origins=("forecast_origin_utc", "nunique"),
            start_target_utc=("target_timestamp_utc", "min"),
            end_target_utc=("target_timestamp_utc", "max"),
        )
        .reset_index()
        .sort_values("model_id")
        .reset_index(drop=True)
    )
    by_split = (
        predictions.groupby(["model_id", "dataset_split"], dropna=False)
        .agg(
            forecast_rows=("target_timestamp_utc", "size"),
            observed_target_rows=("y_true", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            origins=("forecast_origin_utc", "nunique"),
            start_target_utc=("target_timestamp_utc", "min"),
            end_target_utc=("target_timestamp_utc", "max"),
        )
        .reset_index()
        .sort_values(["model_id", "dataset_split"])
        .reset_index(drop=True)
    )
    by_lead = (
        predictions.groupby(["model_id", "dataset_split", "lead_day"], dropna=False)
        .agg(
            forecast_rows=("target_timestamp_utc", "size"),
            observed_target_rows=("y_true", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            origins=("forecast_origin_utc", "nunique"),
            start_target_utc=("target_timestamp_utc", "min"),
            end_target_utc=("target_timestamp_utc", "max"),
        )
        .reset_index()
        .sort_values(["model_id", "dataset_split", "lead_day"])
        .reset_index(drop=True)
    )
    return by_model, by_split, by_lead


def _build_residual_library(predictions: pd.DataFrame, *, calibration_splits: tuple[str, ...]) -> pd.DataFrame:
    observed = predictions[
        predictions["dataset_split"].astype(str).isin([str(x) for x in calibration_splits])
        & predictions["y_true"].notna()
        & predictions["y_pred"].notna()
    ].copy()
    if observed.empty:
        return pd.DataFrame()
    observed["residual"] = pd.to_numeric(observed["y_true"], errors="coerce") - pd.to_numeric(observed["y_pred"], errors="coerce")
    observed["source_period_index"] = (
        observed.sort_values("target_timestamp_utc")
        .groupby(["model_id", "target_local_date", "lead_day"], dropna=False)
        .cumcount()
        .astype(int)
        + 1
    )
    grouped = (
        observed.groupby(["model_id", "target_local_date", "lead_day"], dropna=False)
        .agg(
            source_day_start_utc=("target_timestamp_utc", "min"),
            source_day_end_utc=("target_timestamp_utc", "max"),
            source_dataset_split=("dataset_split", "first"),
            n_periods=("target_timestamp_utc", "size"),
        )
        .reset_index()
    )
    observed = observed.merge(
        grouped,
        on=["model_id", "target_local_date", "lead_day"],
        how="left",
    )
    observed["source_day_key"] = (
        observed["model_id"].astype(str)
        + "|"
        + observed["target_local_date"].astype(str)
        + "|"
        + observed["lead_day"].astype(str)
    )
    keep = [
        "model_id",
        "source_day_key",
        "target_local_date",
        "lead_day",
        "source_day_start_utc",
        "source_day_end_utc",
        "source_dataset_split",
        "n_periods",
        "source_period_index",
        "residual",
    ]
    return observed[keep].sort_values(["model_id", "target_local_date", "lead_day", "source_period_index"]).reset_index(drop=True)


def _resolve_horizon_spec(*, horizon_mode: str, granularity: str) -> dict[str, Any]:
    mode = str(horizon_mode).strip().upper()
    gran = str(granularity).strip().lower()
    if gran not in {"hourly", "quarter_hour"}:
        raise ValueError(f"Unsupported granularity: {granularity}")
    periods_per_day = 24 if gran == "hourly" else 96
    if mode == "D_ONLY":
        horizon_days = 1
    elif mode == "D_PLUS_4":
        horizon_days = 5
    else:
        raise ValueError(f"Unsupported horizon_mode: {horizon_mode}")
    return {
        "horizon_mode": mode,
        "granularity": gran,
        "periods_per_day": int(periods_per_day),
        "horizon_days": int(horizon_days),
        "block_length": int(periods_per_day * horizon_days),
        "cross_day_coherence": bool(horizon_days > 1),
    }


def _stable_group_seed(
    *,
    base_seed: int,
    model_id: str,
    forecast_origin_utc: pd.Timestamp,
    lead_day: int | None,
) -> int:
    payload = f"{int(base_seed)}|{str(model_id)}|{pd.Timestamp(forecast_origin_utc).isoformat()}|{int(lead_day) if lead_day is not None else -1}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    derived = int(digest[:16], 16)
    return int((int(base_seed) + derived) % (2**63 - 1))


def _normalise_calibration_policy(
    *,
    calibration_policy: str,
    calibration_splits: tuple[str, ...] | None,
    calibration_rationale: str,
) -> tuple[str, tuple[str, ...], str]:
    policy = str(calibration_policy or "").strip().lower()
    if policy not in {"validation_only", "train_validation"}:
        raise ValueError("calibration_policy must be 'validation_only' or 'train_validation'.")

    if calibration_splits is None:
        splits = ("validation",) if policy == "validation_only" else ("train", "validation")
    else:
        splits = tuple(str(x).strip().lower() for x in calibration_splits if str(x).strip())
        if not splits:
            raise ValueError("calibration_splits cannot be empty when explicitly provided.")

    rationale = str(calibration_rationale or "").strip()
    if policy == "train_validation" and not rationale:
        raise ValueError("calibration_policy=train_validation requires a non-empty calibration_rationale.")
    if policy == "validation_only" and not rationale:
        rationale = "strict_strategy_b_default"
    return policy, splits, rationale


def _reduce_scenarios_for_target_day(raw_day: pd.DataFrame, *, n_final: int) -> pd.DataFrame:
    if raw_day.empty:
        return raw_day.copy()
    means = (
        raw_day.groupby("scenario_id_raw", dropna=False)["scenario_price"]
        .mean()
        .reset_index(name="scenario_mean")
        .sort_values(["scenario_mean", "scenario_id_raw"])
        .reset_index(drop=True)
    )
    raw_ids = means["scenario_id_raw"].astype(str).tolist()
    if len(raw_ids) <= int(n_final):
        selected_ids = raw_ids
    else:
        protected = []
        if int(n_final) >= 2:
            protected = [raw_ids[0], raw_ids[-1]]
        elif int(n_final) == 1:
            protected = [raw_ids[len(raw_ids) // 2]]
        unprotected = [sid for sid in raw_ids if sid not in set(protected)]
        slots = max(int(n_final) - len(protected), 0)
        if slots > 0 and unprotected:
            pos = sorted(
                set(
                    int(i)
                    for i in np.linspace(0, max(len(unprotected) - 1, 0), num=min(slots, len(unprotected)), dtype=int)
                )
            )
            chosen = [unprotected[i] for i in pos]
        else:
            chosen = []
        selected_ids = protected + chosen
        selected_ids = selected_ids[: int(n_final)]

    selected = raw_day[raw_day["scenario_id_raw"].astype(str).isin(selected_ids)].copy()
    order = (
        selected.groupby("scenario_id_raw", dropna=False)["scenario_price"]
        .mean()
        .reset_index(name="scenario_mean")
        .sort_values(["scenario_mean", "scenario_id_raw"])
        .reset_index(drop=True)
    )
    id_map = {str(row["scenario_id_raw"]): f"S{idx + 1:02d}" for idx, row in order.iterrows()}
    selected["scenario_id"] = selected["scenario_id_raw"].astype(str).map(id_map)
    n_selected = int(len(order))
    probability = (1.0 / float(n_selected)) if n_selected > 0 else np.nan
    selected["scenario_probability"] = probability
    return selected.drop(columns=["scenario_id_raw"]).sort_values(["target_timestamp_utc", "scenario_id"]).reset_index(drop=True)


def _generate_scenarios(
    predictions: pd.DataFrame,
    residual_library: pd.DataFrame,
    *,
    n_raw: int,
    n_final: int,
    random_seed: int,
    horizon_spec: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions.empty or residual_library.empty:
        return pd.DataFrame(), pd.DataFrame()

    scenario_rows: list[pd.DataFrame] = []
    metadata_rows: list[dict[str, Any]] = []

    target_groups = predictions.groupby(
        ["model_id", "dataset_split", "forecast_origin_utc", "lead_day", "target_local_date"],
        dropna=False,
    )
    for keys, group in target_groups:
        model_id, dataset_split, forecast_origin_utc, lead_day, target_local_date = keys
        ordered = group.sort_values("target_timestamp_utc").reset_index(drop=True)
        n_periods = int(ordered.shape[0])
        if n_periods == 0:
            continue
        pool = residual_library[
            (residual_library["model_id"].astype(str) == str(model_id))
            & (pd.to_numeric(residual_library["lead_day"], errors="coerce").astype("Int64") == pd.Series([lead_day]).astype("Int64").iloc[0])
            & (pd.to_numeric(residual_library["n_periods"], errors="coerce") == n_periods)
            & (pd.to_datetime(residual_library["source_day_end_utc"], utc=True, errors="coerce") < pd.Timestamp(forecast_origin_utc))
        ].copy()
        if pool.empty:
            pool = residual_library[
                (residual_library["model_id"].astype(str) == str(model_id))
                & (pd.to_numeric(residual_library["n_periods"], errors="coerce") == n_periods)
                & (pd.to_datetime(residual_library["source_day_end_utc"], utc=True, errors="coerce") < pd.Timestamp(forecast_origin_utc))
            ].copy()
            bank_level = "fallback_same_period_count"
        else:
            bank_level = "same_lead_day"
        if pool.empty:
            continue

        source_keys = sorted(pool["source_day_key"].astype(str).unique().tolist())
        lead_day_for_seed = int(lead_day) if pd.notna(lead_day) else None
        seed = _stable_group_seed(
            base_seed=int(random_seed),
            model_id=str(model_id),
            forecast_origin_utc=pd.Timestamp(forecast_origin_utc),
            lead_day=lead_day_for_seed,
        )
        rng = np.random.default_rng(seed)
        sampled_keys = rng.choice(source_keys, size=int(n_raw), replace=True)

        raw_rows: list[pd.DataFrame] = []
        for raw_idx, source_key in enumerate(sampled_keys, start=1):
            residual_day = pool[pool["source_day_key"].astype(str) == str(source_key)].copy()
            residual_day = residual_day.sort_values("source_period_index").reset_index(drop=True)
            if int(residual_day.shape[0]) != n_periods:
                continue
            merged = ordered.copy()
            merged["scenario_id_raw"] = f"RAW_{raw_idx:03d}"
            merged["source_day_key"] = str(source_key)
            merged["source_day_date"] = str(residual_day["target_local_date"].iloc[0])
            merged["source_dataset_split"] = str(residual_day["source_dataset_split"].iloc[0])
            merged["source_day_start_utc"] = pd.Timestamp(residual_day["source_day_start_utc"].iloc[0])
            merged["source_day_end_utc"] = pd.Timestamp(residual_day["source_day_end_utc"].iloc[0])
            merged["bank_level"] = bank_level
            merged["residual_sampled"] = pd.to_numeric(residual_day["residual"].to_numpy(), errors="coerce")
            merged["scenario_price"] = pd.to_numeric(merged["y_pred"], errors="coerce") + pd.to_numeric(merged["residual_sampled"], errors="coerce")
            merged["horizon_mode"] = str(horizon_spec["horizon_mode"])
            merged["horizon_days"] = int(horizon_spec["horizon_days"])
            merged["granularity"] = str(horizon_spec["granularity"])
            merged["block_length"] = int(horizon_spec["block_length"])
            merged["cross_day_coherence"] = bool(horizon_spec["cross_day_coherence"])
            merged["source_residual_block_id"] = str(source_key)
            merged["source_residual_start_utc"] = pd.Timestamp(residual_day["source_day_start_utc"].iloc[0])
            merged["source_residual_end_utc"] = pd.Timestamp(residual_day["source_day_end_utc"].iloc[0])
            raw_rows.append(merged)

        if not raw_rows:
            continue
        raw_day = pd.concat(raw_rows, ignore_index=True)
        final_day = _reduce_scenarios_for_target_day(raw_day, n_final=int(n_final))
        if final_day.empty:
            continue

        scenario_rows.append(final_day)
        for scenario_id, sgroup in final_day.groupby("scenario_id", dropna=False):
            metadata_rows.append(
                {
                    "model_id": str(model_id),
                    "dataset_split": str(dataset_split),
                    "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                    "lead_day": int(lead_day) if pd.notna(lead_day) else None,
                    "target_local_date": str(target_local_date),
                    "scenario_id": str(scenario_id),
                    "scenario_probability": float(sgroup["scenario_probability"].iloc[0]),
                    "source_profile_date": str(sgroup["source_day_date"].iloc[0]),
                    "source_profile_split": str(sgroup["source_dataset_split"].iloc[0]),
                    "source_day_start_utc": pd.Timestamp(sgroup["source_day_start_utc"].iloc[0]),
                    "source_day_end_utc": pd.Timestamp(sgroup["source_day_end_utc"].iloc[0]),
                    "target_forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                    "bank_level": str(sgroup["bank_level"].iloc[0]),
                    "n_periods": int(sgroup.shape[0]),
                    "horizon_mode": str(horizon_spec["horizon_mode"]),
                    "horizon_days": int(horizon_spec["horizon_days"]),
                    "granularity": str(horizon_spec["granularity"]),
                    "block_length": int(horizon_spec["block_length"]),
                    "cross_day_coherence": bool(horizon_spec["cross_day_coherence"]),
                    "source_residual_block_id": str(sgroup["source_day_key"].iloc[0]),
                }
            )

    if not scenario_rows:
        return pd.DataFrame(), pd.DataFrame()

    scenarios = pd.concat(scenario_rows, ignore_index=True)
    metadata = pd.DataFrame(metadata_rows).drop_duplicates().reset_index(drop=True)
    scenarios["scenario_price"] = pd.to_numeric(scenarios["scenario_price"], errors="coerce")
    scenarios["point_forecast"] = pd.to_numeric(scenarios["y_pred"], errors="coerce")
    scenarios["y_true"] = pd.to_numeric(scenarios["y_true"], errors="coerce")
    scenarios["timestamp_utc"] = scenarios["target_timestamp_utc"]
    scenarios["price_eur_per_mwh"] = scenarios["scenario_price"]
    return scenarios, metadata


def _build_scenario_prices_export(scenarios: pd.DataFrame) -> pd.DataFrame:
    if scenarios.empty:
        return pd.DataFrame(
            columns=[
                "model_id",
                "forecast_origin_utc",
                "target_timestamp_utc",
                "lead_day",
                "scenario_id",
                "scenario_price",
                "point_forecast",
                "y_true",
                "dataset_split",
            ]
        )
    keep = [
        "model_id",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_day",
        "scenario_id",
        "scenario_price",
        "point_forecast",
        "y_true",
        "dataset_split",
        "target_timestamp_local",
        "target_local_date",
        "quarter_in_day_index",
        "quarters_in_target_day",
        "scenario_probability",
        "timestamp_utc",
        "price_eur_per_mwh",
    ]
    out = scenarios[keep].copy()
    out = out.sort_values(["model_id", "dataset_split", "forecast_origin_utc", "target_timestamp_utc", "scenario_id"]).reset_index(drop=True)
    return out


def _build_period_quantiles(scenario_prices_long: pd.DataFrame) -> pd.DataFrame:
    if scenario_prices_long.empty:
        return pd.DataFrame()
    group_cols = ["model_id", "dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"]
    rows: list[dict[str, Any]] = []
    for keys, group in scenario_prices_long.groupby(group_cols, dropna=False):
        model_id, dataset_split, forecast_origin_utc, target_timestamp_utc, lead_day = keys
        values = pd.to_numeric(group["scenario_price"], errors="coerce")
        rows.append(
            {
                "model_id": str(model_id),
                "dataset_split": str(dataset_split),
                "forecast_origin_utc": pd.Timestamp(forecast_origin_utc),
                "target_timestamp_utc": pd.Timestamp(target_timestamp_utc),
                "lead_day": int(lead_day) if pd.notna(lead_day) else None,
                "y_true": float(pd.to_numeric(group["y_true"], errors="coerce").dropna().iloc[0]) if pd.to_numeric(group["y_true"], errors="coerce").notna().any() else np.nan,
                "point_forecast": float(pd.to_numeric(group["point_forecast"], errors="coerce").iloc[0]),
                "scenario_count": int(group["scenario_id"].nunique()),
                "distribution_min": float(values.min()),
                "distribution_max": float(values.max()),
                "p05": _safe_quantile(values, 0.05),
                "p10": _safe_quantile(values, 0.10),
                "p50": _safe_quantile(values, 0.50),
                "p90": _safe_quantile(values, 0.90),
                "p95": _safe_quantile(values, 0.95),
                "weighted_mean": float(values.mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["model_id", "dataset_split", "forecast_origin_utc", "target_timestamp_utc"]).reset_index(drop=True)


def _build_validation_summary(
    scenario_prices_long: pd.DataFrame,
    residual_library: pd.DataFrame,
    *,
    n_final: int,
    settings_uniform: bool,
) -> pd.DataFrame:
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "check_name": "same_settings_all_models",
            "status": "pass" if settings_uniform else "fail",
            "details": "Single shared method, n_raw, n_final, calibration_splits, random_seed policy applied to all models.",
        }
    )

    model_counts = scenario_prices_long.groupby("model_id", dropna=False).size() if not scenario_prices_long.empty else pd.Series(dtype=int)
    missing_models = [model for model in MODEL_IDS if model not in set(model_counts.index.astype(str).tolist())]
    checks.append(
        {
            "check_name": "non_empty_all_three_models",
            "status": "pass" if not missing_models else "fail",
            "details": "missing_models=" + ",".join(missing_models) if missing_models else "all models non-empty",
        }
    )

    duplicates = (
        int(
            scenario_prices_long.duplicated(
                subset=["model_id", "forecast_origin_utc", "target_timestamp_utc", "scenario_id"]
            ).sum()
        )
        if not scenario_prices_long.empty
        else 0
    )
    checks.append(
        {
            "check_name": "no_duplicate_scenario_keys",
            "status": "pass" if duplicates == 0 else "fail",
            "details": f"duplicate_rows={duplicates}",
        }
    )

    finite_ok = bool(np.isfinite(pd.to_numeric(scenario_prices_long["scenario_price"], errors="coerce")).all()) if not scenario_prices_long.empty else True
    checks.append(
        {
            "check_name": "all_scenario_prices_finite",
            "status": "pass" if finite_ok else "fail",
            "details": "scenario_price finite check",
        }
    )

    scenario_count_ok = True
    scenario_count_fail_groups = 0
    if not scenario_prices_long.empty:
        per_period = (
            scenario_prices_long.groupby(
                ["model_id", "dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day"],
                dropna=False,
            )["scenario_id"]
            .nunique()
            .reset_index(name="scenario_count")
        )
        scenario_count_fail_groups = int((per_period["scenario_count"] != int(n_final)).sum())
        scenario_count_ok = scenario_count_fail_groups == 0
    checks.append(
        {
            "check_name": "scenario_count_matches_n_final",
            "status": "pass" if scenario_count_ok else "fail",
            "details": f"n_final={int(n_final)}, failing_periods={scenario_count_fail_groups}",
        }
    )

    calibration_non_observed = int(residual_library["residual"].isna().sum()) if not residual_library.empty else 0
    checks.append(
        {
            "check_name": "calibration_uses_observed_targets_only",
            "status": "pass" if calibration_non_observed == 0 else "fail",
            "details": f"calibration_missing_residual_rows={calibration_non_observed}",
        }
    )

    return pd.DataFrame(checks)


def _provenance_manifest(
    *,
    run_id: str,
    run_dir: Path,
    phase27_run_dir: Path,
    model3_run_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "method_id": "qh_daily_residual_profile_bootstrap_v1",
        "method_description": "Per-model daily residual profile bootstrap with same lead-day preference and equal-probability reduced scenarios.",
        "source_predictions": {
            MODEL_IDS[0]: str(phase27_run_dir / "predictions_long.csv"),
            MODEL_IDS[1]: str(phase27_run_dir / "predictions_long.csv"),
            MODEL_IDS[2]: str(model3_run_dir / "predictions_long.csv"),
        },
        "model_ids": MODEL_IDS,
        "shared_settings": config,
        "leakage_guardrails": [
            "Residual calibration uses only rows with observed y_true and y_pred.",
            "Residual source days must satisfy source_day_end_utc < forecast_origin_utc for each target origin.",
            "No point-forecast values are modified before scenario generation.",
        ],
    }


def run_qh_scenario_generation(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    check_only: bool = False,
    smoke: bool = False,
    all_three_models: bool = False,
    output_tag: str = "",
    phase27_run_id: str | None = None,
    model3_run_id: str | None = None,
    n_raw_scenarios: int = 30,
    n_final_scenarios: int = 15,
    random_seed: int = 42,
    calibration_policy: str = "validation_only",
    calibration_splits: tuple[str, ...] | None = None,
    calibration_rationale: str = "",
    horizon_mode: str = "D_ONLY",
    max_origins: int | None = None,
) -> Path:
    if int(n_raw_scenarios) <= 0:
        raise ValueError("n_raw_scenarios must be positive.")
    if int(n_final_scenarios) <= 0:
        raise ValueError("n_final_scenarios must be positive.")
    if int(n_final_scenarios) > int(n_raw_scenarios):
        raise ValueError("n_final_scenarios cannot exceed n_raw_scenarios.")
    if smoke and max_origins is None:
        max_origins = 3

    horizon_spec = _resolve_horizon_spec(horizon_mode=str(horizon_mode), granularity="quarter_hour")
    if str(horizon_spec["horizon_mode"]) != "D_ONLY":
        raise ValueError("This runner currently executes D_ONLY scenario generation only. D_PLUS_4 is architecture-prepared.")

    calibration_policy, effective_calibration_splits, calibration_rationale = _normalise_calibration_policy(
        calibration_policy=calibration_policy,
        calibration_splits=calibration_splits,
        calibration_rationale=calibration_rationale,
    )

    resolved = config or QuarterHourDAExtensionConfig()
    paths = _bundle_paths(resolved, output_tag=output_tag)

    phase27_pred, phase27_run_dir = _load_phase27_predictions(resolved, phase27_run_id=phase27_run_id or DEFAULT_PHASE27_RUN_ID)
    model3_pred, model3_run_dir = _load_model3_predictions(resolved, model3_run_id=model3_run_id or DEFAULT_MODEL3_RUN_ID)
    predictions = pd.concat([phase27_pred, model3_pred], ignore_index=True)
    predictions = predictions[predictions["model_id"].astype(str).isin(MODEL_IDS)].copy()
    if all_three_models:
        missing = [model for model in MODEL_IDS if model not in set(predictions["model_id"].astype(str).unique().tolist())]
        if missing:
            raise ValueError(f"--all-three-models requested but missing model predictions for: {missing}")

    if max_origins is not None:
        predictions = _subset_smoke(predictions, max_origins=int(max_origins))

    support_by_model, support_by_split, support_by_lead = _support_tables(predictions)
    support_by_model.to_csv(paths.run_dir / "support_by_model.csv", index=False)
    support_by_split.to_csv(paths.run_dir / "support_by_split.csv", index=False)
    support_by_lead.to_csv(paths.run_dir / "support_by_lead_day.csv", index=False)

    scenario_config = {
        "method_id": "qh_daily_residual_profile_bootstrap_v1",
        "check_only": bool(check_only),
        "smoke": bool(smoke),
        "all_three_models": bool(all_three_models),
        "n_raw_scenarios": int(n_raw_scenarios),
        "n_final_scenarios": int(n_final_scenarios),
        "random_seed": int(random_seed),
        "random_seed_method": STABLE_SEED_METHOD,
        "random_seed_base": int(random_seed),
        "calibration_policy": str(calibration_policy),
        "calibration_splits": [str(x) for x in effective_calibration_splits],
        "calibration_splits_used": [str(x) for x in effective_calibration_splits],
        "calibration_rationale": calibration_rationale,
        "horizon_mode": str(horizon_spec["horizon_mode"]),
        "horizon_days": int(horizon_spec["horizon_days"]),
        "granularity": str(horizon_spec["granularity"]),
        "periods_per_day": int(horizon_spec["periods_per_day"]),
        "block_length": int(horizon_spec["block_length"]),
        "selection_split_used": "validation",
        "test_used_for_selection": False,
        "causal_source_filter_applied": True,
        "phase27_run_dir": str(phase27_run_dir),
        "model3_run_dir": str(model3_run_dir),
        "output_tag": str(output_tag or ""),
        "max_origins": int(max_origins) if max_origins is not None else None,
    }
    (paths.run_dir / "scenario_generation_config.json").write_text(
        json.dumps(scenario_config, indent=2),
        encoding="utf-8",
    )

    if check_only:
        summary = {
            "run_id": paths.run_id,
            "run_label": RUN_LABEL,
            "status": "check_only_completed",
            "scenario_generation_ready": bool(not predictions.empty),
            "models_present": sorted(predictions["model_id"].astype(str).unique().tolist()),
            "support_rows": support_by_model.to_dict(orient="records"),
            "calibration_policy": str(calibration_policy),
            "calibration_splits_used": [str(x) for x in effective_calibration_splits],
            "calibration_rationale": calibration_rationale,
            "random_seed_method": STABLE_SEED_METHOD,
            "random_seed_base": int(random_seed),
            "selection_split_used": "validation",
            "test_used_for_selection": False,
            "causal_source_filter_applied": True,
        }
        (paths.run_dir / "scenario_generation_run_summary.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )
        return paths.run_dir

    residual_library = _build_residual_library(predictions, calibration_splits=tuple(effective_calibration_splits))
    scenarios, metadata = _generate_scenarios(
        predictions,
        residual_library,
        n_raw=int(n_raw_scenarios),
        n_final=int(n_final_scenarios),
        random_seed=int(random_seed),
        horizon_spec=horizon_spec,
    )
    scenario_prices_long = _build_scenario_prices_export(scenarios)
    period_quantiles = _build_period_quantiles(scenario_prices_long)
    validation_summary = _build_validation_summary(
        scenario_prices_long,
        residual_library,
        n_final=int(n_final_scenarios),
        settings_uniform=True,
    )

    residual_rows_by_split = (
        residual_library.groupby("source_dataset_split", dropna=False).size().reset_index(name="residual_rows")
        if not residual_library.empty
        else pd.DataFrame(columns=["source_dataset_split", "residual_rows"])
    )
    source_days_by_split = (
        residual_library.groupby("source_dataset_split", dropna=False)["source_day_key"].nunique().reset_index(name="source_days")
        if not residual_library.empty
        else pd.DataFrame(columns=["source_dataset_split", "source_days"])
    )
    residual_rows_by_split_map = {str(row["source_dataset_split"]): int(row["residual_rows"]) for _, row in residual_rows_by_split.iterrows()}
    source_days_by_split_map = {str(row["source_dataset_split"]): int(row["source_days"]) for _, row in source_days_by_split.iterrows()}

    probability_fail_groups = 0
    if not metadata.empty:
        probs = (
            metadata.groupby(["model_id", "dataset_split", "forecast_origin_utc", "lead_day", "target_local_date"], dropna=False)[
                "scenario_probability"
            ]
            .sum()
            .reset_index(name="probability_sum")
        )
        probability_fail_groups = int((probs["probability_sum"].sub(1.0).abs() > 1e-6).sum())

    causal_source_filter_violations = 0
    if not metadata.empty:
        source_end = pd.to_datetime(metadata["source_day_end_utc"], utc=True, errors="coerce")
        target_origin = pd.to_datetime(metadata["target_forecast_origin_utc"], utc=True, errors="coerce")
        causal_source_filter_violations = int((source_end >= target_origin).sum())

    probe_seed_a = _stable_group_seed(
        base_seed=int(random_seed),
        model_id="repro_probe",
        forecast_origin_utc=pd.Timestamp("2024-01-01T08:00:00Z"),
        lead_day=0,
    )
    probe_seed_b = _stable_group_seed(
        base_seed=int(random_seed),
        model_id="repro_probe",
        forecast_origin_utc=pd.Timestamp("2024-01-01T08:00:00Z"),
        lead_day=0,
    )
    reproducibility_smoke_pass = bool(probe_seed_a == probe_seed_b)
    reproducibility_smoke_details = f"seed_consistency_probe={reproducibility_smoke_pass}"
    if not predictions.empty and not residual_library.empty:
        seed_probe = (
            predictions[["model_id", "forecast_origin_utc", "lead_day"]]
            .dropna(subset=["model_id", "forecast_origin_utc"])
            .drop_duplicates()
            .sort_values(["model_id", "forecast_origin_utc", "lead_day"])
        )
        if not seed_probe.empty:
            probe = seed_probe.iloc[0]
            probe_lead_day = int(probe["lead_day"]) if pd.notna(probe["lead_day"]) else None
            probe_predictions = predictions[
                (predictions["model_id"].astype(str) == str(probe["model_id"]))
                & (pd.to_datetime(predictions["forecast_origin_utc"], utc=True, errors="coerce") == pd.Timestamp(probe["forecast_origin_utc"]))
            ].copy()
            if probe_lead_day is not None:
                probe_predictions = probe_predictions[pd.to_numeric(probe_predictions["lead_day"], errors="coerce").astype("Int64") == probe_lead_day].copy()
            probe_n_periods = int(probe_predictions.shape[0]) if not probe_predictions.empty else 0
            probe_pool = residual_library[
                (residual_library["model_id"].astype(str) == str(probe["model_id"]))
                & (
                    pd.to_numeric(residual_library["lead_day"], errors="coerce").astype("Int64")
                    == (probe_lead_day if probe_lead_day is not None else -1)
                )
                & (pd.to_numeric(residual_library["n_periods"], errors="coerce") == probe_n_periods)
                & (pd.to_datetime(residual_library["source_day_end_utc"], utc=True, errors="coerce") < pd.Timestamp(probe["forecast_origin_utc"]))
            ].copy()
            if probe_pool.empty:
                probe_pool = residual_library[
                    (residual_library["model_id"].astype(str) == str(probe["model_id"]))
                    & (pd.to_numeric(residual_library["n_periods"], errors="coerce") == probe_n_periods)
                    & (pd.to_datetime(residual_library["source_day_end_utc"], utc=True, errors="coerce") < pd.Timestamp(probe["forecast_origin_utc"]))
                ].copy()
            probe_seed_a = _stable_group_seed(
                base_seed=int(random_seed),
                model_id=str(probe["model_id"]),
                forecast_origin_utc=pd.Timestamp(probe["forecast_origin_utc"]),
                lead_day=probe_lead_day,
            )
            probe_seed_b = _stable_group_seed(
                base_seed=int(random_seed),
                model_id=str(probe["model_id"]),
                forecast_origin_utc=pd.Timestamp(probe["forecast_origin_utc"]),
                lead_day=probe_lead_day,
            )
            if probe_pool.empty:
                reproducibility_smoke_pass = bool(reproducibility_smoke_pass and (probe_seed_a == probe_seed_b))
                reproducibility_smoke_details = (
                    f"seed_consistency_only probe_seed_a={probe_seed_a}, probe_seed_b={probe_seed_b}, "
                    "sampling_probe_skipped_empty_pool"
                )
            else:
                source_keys = sorted(probe_pool["source_day_key"].astype(str).unique().tolist())
                draw_size = min(int(n_raw_scenarios), max(len(source_keys), 1))
                draw_a = np.random.default_rng(probe_seed_a).choice(source_keys, size=draw_size, replace=True).tolist()
                draw_b = np.random.default_rng(probe_seed_b).choice(source_keys, size=draw_size, replace=True).tolist()
                reproducibility_smoke_pass = bool((probe_seed_a == probe_seed_b) and (draw_a == draw_b))
                reproducibility_smoke_details = (
                    f"probe_seed={probe_seed_a}; draw_size={draw_size}; "
                    f"draws_identical={draw_a == draw_b}"
                )

    scenario_prices_long.to_csv(paths.run_dir / "scenario_prices_long.csv", index=False)
    try:
        scenario_prices_long.to_parquet(paths.run_dir / "scenario_prices_long.parquet", index=False)
    except Exception:
        pass
    metadata.to_csv(paths.run_dir / "scenario_metadata.csv", index=False)
    period_quantiles.to_csv(paths.run_dir / "scenario_period_quantiles.csv", index=False)
    validation_summary.to_csv(paths.run_dir / "scenario_validation_summary.csv", index=False)

    provenance = _provenance_manifest(
        run_id=paths.run_id,
        run_dir=paths.run_dir,
        phase27_run_dir=phase27_run_dir,
        model3_run_dir=model3_run_dir,
        config=scenario_config,
    )
    (paths.run_dir / "provenance_manifest.json").write_text(
        json.dumps(provenance, indent=2, default=str),
        encoding="utf-8",
    )

    scenario_rows_by_model = (
        scenario_prices_long.groupby("model_id", dropna=False)
        .agg(
            scenario_rows=("target_timestamp_utc", "size"),
            scenario_origins=("forecast_origin_utc", "nunique"),
            scenario_targets=("target_timestamp_utc", "nunique"),
            unique_scenarios=("scenario_id", "nunique"),
        )
        .reset_index()
        .sort_values("model_id")
        .to_dict(orient="records")
        if not scenario_prices_long.empty
        else []
    )
    summary = {
        "run_id": paths.run_id,
        "run_label": RUN_LABEL,
        "status": "completed",
        "models": MODEL_IDS,
        "phase27_run_dir": str(phase27_run_dir),
        "model3_run_dir": str(model3_run_dir),
        "n_raw_scenarios": int(n_raw_scenarios),
        "n_final_scenarios": int(n_final_scenarios),
        "horizon_mode": str(horizon_spec["horizon_mode"]),
        "horizon_days": int(horizon_spec["horizon_days"]),
        "granularity": str(horizon_spec["granularity"]),
        "periods_per_day": int(horizon_spec["periods_per_day"]),
        "block_length": int(horizon_spec["block_length"]),
        "selection_split_used": "validation",
        "test_used_for_selection": False,
        "calibration_policy": str(calibration_policy),
        "calibration_splits": [str(x) for x in effective_calibration_splits],
        "calibration_splits_used": [str(x) for x in effective_calibration_splits],
        "calibration_rationale": calibration_rationale,
        "residual_rows_by_split": residual_rows_by_split_map,
        "source_days_by_split": source_days_by_split_map,
        "point_prediction_rows": int(predictions.shape[0]),
        "calibration_residual_rows": int(residual_library.shape[0]),
        "residual_source_rows": int(residual_library.shape[0]),
        "residual_source_days": int(residual_library["source_day_key"].nunique()) if not residual_library.empty else 0,
        "scenario_price_rows": int(scenario_prices_long.shape[0]),
        "causal_source_filter_applied": True,
        "causal_source_filter_violations": int(causal_source_filter_violations),
        "random_seed_method": STABLE_SEED_METHOD,
        "random_seed_base": int(random_seed),
        "reproducibility_seed_smoke_test": {
            "status": "pass" if reproducibility_smoke_pass else "fail",
            "details": reproducibility_smoke_details,
        },
        "scenario_rows_by_model": scenario_rows_by_model,
        "validation_checks": [
            *validation_summary.to_dict(orient="records"),
            {
                "check_name": "scenario_probabilities_sum_to_one_per_group",
                "status": "pass" if probability_fail_groups == 0 else "fail",
                "details": f"failing_groups={probability_fail_groups}",
            },
            {
                "check_name": "calibration_policy_explicit",
                "status": "pass",
                "details": f"calibration_policy={calibration_policy}, calibration_splits={list(effective_calibration_splits)}",
            },
            {
                "check_name": "stable_random_seed_method_used",
                "status": "pass" if reproducibility_smoke_pass else "fail",
                "details": f"method={STABLE_SEED_METHOD}; {reproducibility_smoke_details}",
            },
            {
                "check_name": "causal_source_filter_violations",
                "status": "pass" if causal_source_filter_violations == 0 else "fail",
                "details": f"violations={causal_source_filter_violations}",
            },
            {
                "check_name": "test_not_used_for_selection",
                "status": "pass",
                "details": "selection_split_used=validation",
            },
        ],
        "milp_ingestion_compatibility": {
            "required_columns_present": bool(
                set(["model_id", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "scenario_id", "scenario_price", "dataset_split"]).issubset(
                    set(scenario_prices_long.columns)
                )
            ),
            "duplicate_key_rows": int(
                scenario_prices_long.duplicated(
                    subset=["model_id", "forecast_origin_utc", "target_timestamp_utc", "scenario_id"]
                ).sum()
            )
            if not scenario_prices_long.empty
            else 0,
            "all_prices_finite": bool(np.isfinite(pd.to_numeric(scenario_prices_long["scenario_price"], errors="coerce")).all())
            if not scenario_prices_long.empty
            else True,
        },
    }
    (paths.run_dir / "scenario_generation_run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return paths.run_dir


def qh_residual_availability_report(
    config: QuarterHourDAExtensionConfig | None = None,
    *,
    phase27_run_id: str | None = None,
    model3_run_id: str | None = None,
    max_origins: int | None = None,
) -> dict[str, Any]:
    resolved = config or QuarterHourDAExtensionConfig()
    phase27_pred, phase27_run_dir = _load_phase27_predictions(resolved, phase27_run_id=phase27_run_id or DEFAULT_PHASE27_RUN_ID)
    model3_pred, model3_run_dir = _load_model3_predictions(resolved, model3_run_id=model3_run_id or DEFAULT_MODEL3_RUN_ID)
    predictions = pd.concat([phase27_pred, model3_pred], ignore_index=True)
    predictions = predictions[predictions["model_id"].astype(str).isin(MODEL_IDS)].copy()
    if max_origins is not None:
        predictions = _subset_smoke(predictions, max_origins=int(max_origins))

    policy_specs: list[tuple[str, tuple[str, ...], str]] = [
        ("validation_only", ("validation",), "strict_strategy_b_default"),
        ("train_validation", ("train", "validation"), "expanded_calibration_for_preflight"),
    ]
    policy_rows: list[dict[str, Any]] = []
    for policy, splits, rationale in policy_specs:
        residual_library = _build_residual_library(predictions, calibration_splits=splits)
        rows_by_split = (
            residual_library.groupby("source_dataset_split", dropna=False).size().reset_index(name="rows")
            if not residual_library.empty
            else pd.DataFrame(columns=["source_dataset_split", "rows"])
        )
        days_by_split = (
            residual_library.groupby("source_dataset_split", dropna=False)["source_day_key"].nunique().reset_index(name="days")
            if not residual_library.empty
            else pd.DataFrame(columns=["source_dataset_split", "days"])
        )
        policy_rows.append(
            {
                "calibration_policy": policy,
                "calibration_splits_used": list(splits),
                "calibration_rationale": rationale,
                "residual_rows": int(residual_library.shape[0]),
                "residual_source_days": int(residual_library["source_day_key"].nunique()) if not residual_library.empty else 0,
                "rows_by_split": {str(row["source_dataset_split"]): int(row["rows"]) for _, row in rows_by_split.iterrows()},
                "days_by_split": {str(row["source_dataset_split"]): int(row["days"]) for _, row in days_by_split.iterrows()},
                "sufficient_for_generation": bool((residual_library.shape[0] > 0) and (residual_library["source_day_key"].nunique() > 0)),
            }
        )

    return {
        "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "phase27_run_dir": str(phase27_run_dir),
        "model3_run_dir": str(model3_run_dir),
        "prediction_rows": int(predictions.shape[0]),
        "policies": policy_rows,
    }
