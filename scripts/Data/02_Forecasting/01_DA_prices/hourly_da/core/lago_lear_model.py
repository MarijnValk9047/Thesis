from __future__ import annotations

import gc
import json
import time
import warnings
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso, LassoLarsIC
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .lago_lear_config import LagoLearBenchmarkConfig


@dataclass(frozen=True)
class LagoLearFitResult:
    predictions_long: pd.DataFrame
    coefficients_long: pd.DataFrame
    model_fit_audit: pd.DataFrame
    alpha_selection_audit: pd.DataFrame
    nonzero_feature_summary: pd.DataFrame
    skipped_predictions: pd.DataFrame
    imputation_summary: pd.DataFrame


class LagoLearModel:
    def __init__(self, max_iter: int = 10_000, *, x2_missing_policy: str = "impute_training_median"):
        self.max_iter = int(max_iter)
        self.x2_missing_policy = str(x2_missing_policy)
        self.selected_alpha: float | None = None
        self.pipeline: Pipeline | None = None
        self.feature_names: list[str] = []
        self.nonzero_count: int = 0
        self.fit_time_sec: float = 0.0
        self.predict_time_sec: float = 0.0
        self.fit_warning: str = ""
        self.converged: bool = True
        self.imputation_values: dict[str, float] = {}
        self.imputer_fit_rows: int = 0

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "LagoLearModel":
        started = time.perf_counter()
        self.feature_names = list(X.columns)
        self.fit_warning = ""
        self.converged = True

        if X.empty or y.empty:
            self.pipeline = None
            self.selected_alpha = np.nan
            self.nonzero_count = 0
            self.fit_warning = "empty_training_data"
            self.fit_time_sec = time.perf_counter() - started
            return self

        X_work = X.replace([np.inf, -np.inf], np.nan).copy()
        y_work = pd.to_numeric(y, errors="coerce").astype(float)
        valid_mask = y_work.notna()
        X_work = X_work.loc[valid_mask]
        y_work = y_work.loc[valid_mask]

        if X_work.empty or y_work.empty:
            self.pipeline = None
            self.selected_alpha = np.nan
            self.nonzero_count = 0
            self.fit_warning = "all_targets_missing_after_cleaning"
            self.fit_time_sec = time.perf_counter() - started
            return self

        if X_work.isna().all(axis=0).any():
            all_missing = X_work.columns[X_work.isna().all(axis=0)].tolist()
            self.pipeline = None
            self.selected_alpha = np.nan
            self.nonzero_count = 0
            self.fit_warning = f"all_missing_feature_in_train::{','.join(all_missing[:10])}"
            self.fit_time_sec = time.perf_counter() - started
            return self

        if self.x2_missing_policy == "fail" and X_work.isna().any().any():
            self.pipeline = None
            self.selected_alpha = np.nan
            self.nonzero_count = 0
            self.fit_warning = "missing_features_in_train_and_policy_fail"
            self.fit_time_sec = time.perf_counter() - started
            return self

        imputer = SimpleImputer(strategy="median")
        X_imputed = imputer.fit_transform(X_work)
        self.imputer_fit_rows = int(X_work.shape[0])
        self.imputation_values = {
            self.feature_names[idx]: float(value) if pd.notna(value) else np.nan
            for idx, value in enumerate(np.asarray(imputer.statistics_, dtype=float))
        }

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_imputed)
        y_np = y_work.to_numpy(dtype=float)

        alpha = np.nan
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                selector = LassoLarsIC(criterion="aic")
                selector.fit(X_scaled, y_np)
                alpha = float(selector.alpha_)
                if not np.isfinite(alpha) or alpha <= 0.0:
                    alpha = np.nan
            except Exception as exc:  # noqa: BLE001
                self.fit_warning = f"alpha_selection_failed::{exc}"

            if not np.isfinite(alpha):
                alpha = 0.01
                if not self.fit_warning:
                    self.fit_warning = "alpha_selection_defaulted_to_0.01"

            lasso = Lasso(alpha=float(alpha), max_iter=self.max_iter)
            try:
                lasso.fit(X_scaled, y_np)
            except Exception as exc:  # noqa: BLE001
                self.pipeline = None
                self.selected_alpha = float(alpha)
                self.nonzero_count = 0
                self.fit_warning = f"lasso_fit_failed::{exc}"
                self.fit_time_sec = time.perf_counter() - started
                return self

            warning_texts = [str(item.message) for item in caught]
            if warning_texts:
                self.fit_warning = (self.fit_warning + " | " if self.fit_warning else "") + " ; ".join(warning_texts)
                if any("did not converge" in text.lower() for text in warning_texts):
                    self.converged = False

        self.selected_alpha = float(alpha)
        self.nonzero_count = int(np.sum(np.abs(lasso.coef_) > 0.0))
        self.pipeline = Pipeline(steps=[("imputer", imputer), ("scaler", scaler), ("lasso", lasso)])
        self.fit_time_sec = time.perf_counter() - started
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        started = time.perf_counter()
        if self.pipeline is None:
            self.predict_time_sec = time.perf_counter() - started
            return np.full(shape=(X.shape[0],), fill_value=np.nan, dtype=float)
        X_work = X.replace([np.inf, -np.inf], np.nan).copy()
        preds = self.pipeline.predict(X_work)
        self.predict_time_sec = time.perf_counter() - started
        return np.asarray(preds, dtype=float)

    def coefficient_frame(self) -> pd.DataFrame:
        if self.pipeline is None:
            return pd.DataFrame(columns=["feature_name", "coefficient", "abs_coefficient", "is_nonzero"])
        lasso: Lasso = self.pipeline.named_steps["lasso"]
        values = np.asarray(lasso.coef_, dtype=float)
        frame = pd.DataFrame({"feature_name": self.feature_names, "coefficient": values})
        frame["abs_coefficient"] = frame["coefficient"].abs()
        frame["is_nonzero"] = frame["abs_coefficient"] > 0.0
        return frame.sort_values(["abs_coefficient", "feature_name"], ascending=[False, True]).reset_index(drop=True)


def _lead_day_label(value: int) -> str:
    return "D" if int(value) == 0 else f"D+{int(value)}"


def _target_timestamp_utc(local_day: date, hour_local: int, timezone: str) -> pd.Timestamp:
    local_ts = pd.Timestamp(datetime.combine(local_day, dt_time(hour=int(hour_local), minute=0))).tz_localize(
        timezone,
        ambiguous="raise",
        nonexistent="raise",
    )
    return local_ts.tz_convert("UTC")


def _subset_last_n_days(frame: pd.DataFrame, day_col: str, before_day: date, window_days: int) -> pd.DataFrame:
    train = frame[frame[day_col] < before_day].copy()
    if train.empty:
        return train
    train = train.sort_values(day_col)
    if window_days <= 0:
        return train
    unique_days = sorted(train[day_col].dropna().unique().tolist())
    if not unique_days:
        return train.iloc[0:0].copy()
    if len(unique_days) <= window_days:
        return train
    threshold = unique_days[-window_days]
    return train[train[day_col] >= threshold].copy()


def fit_predict_lago_d_only(
    *,
    X: pd.DataFrame,
    Y: pd.DataFrame,
    metadata: pd.DataFrame,
    split_days: pd.DataFrame,
    config: LagoLearBenchmarkConfig,
    max_origins: int | None = None,
) -> LagoLearFitResult:
    if X.empty or Y.empty or metadata.empty:
        empty = pd.DataFrame()
        return LagoLearFitResult(
            predictions_long=empty,
            coefficients_long=empty,
            model_fit_audit=empty,
            alpha_selection_audit=empty,
            nonzero_feature_summary=empty,
            skipped_predictions=empty,
            imputation_summary=empty,
        )

    matrix = pd.concat([metadata.reset_index(drop=True), X.reset_index(drop=True), Y.reset_index(drop=True)], axis=1)
    matrix["delivery_local_date"] = pd.to_datetime(matrix["delivery_local_date"], errors="coerce").dt.date
    split_lookup = {
        pd.Timestamp(value).date(): split
        for value, split in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False)
        if pd.notna(value) and pd.notna(split)
    }
    matrix["dataset_split"] = matrix["delivery_local_date"].map(split_lookup)
    eval_rows = matrix[matrix["dataset_split"].isin(["validation", "test"])].copy().sort_values("delivery_local_date")
    if max_origins is not None:
        eval_rows = eval_rows.head(int(max_origins)).copy()

    pred_rows: list[dict[str, Any]] = []
    coef_rows: list[dict[str, Any]] = []
    fit_audit_rows: list[dict[str, Any]] = []
    alpha_rows: list[dict[str, Any]] = []
    nonzero_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    imputation_rows: list[dict[str, Any]] = []

    y_cols = [f"y_h{hour:02d}" for hour in range(1, 25)]
    for row in eval_rows.to_dict(orient="records"):
        delivery_day = row["delivery_local_date"]
        origin_utc = pd.Timestamp(row["forecast_origin_utc"], tz="UTC")
        dataset_split = str(row["dataset_split"])
        x_test = pd.DataFrame([{column: row[column] for column in X.columns}])
        y_true_values = [float(row[col]) if pd.notna(row[col]) else np.nan for col in y_cols]

        window_predictions: dict[int, list[float]] = {}
        window_fit_times: dict[int, float] = {}
        window_predict_times: dict[int, float] = {}

        for window_days in config.lago_windows_days:
            train = _subset_last_n_days(matrix, "delivery_local_date", delivery_day, int(window_days))
            min_days = int(config.min_training_days_by_window.get(int(window_days), 1))
            train_day_count = int(train["delivery_local_date"].nunique())
            if train_day_count < min_days:
                skipped_rows.append(
                    {
                        "mode": "d_only",
                        "delivery_local_date": delivery_day.isoformat(),
                        "window_days": int(window_days),
                        "reason": f"insufficient_training_days<{min_days}",
                    }
                )
                continue

            preds_for_window: list[float] = []
            fit_time_total = 0.0
            pred_time_total = 0.0
            for hour_idx, y_col in enumerate(y_cols, start=1):
                y_train = pd.to_numeric(train[y_col], errors="coerce")
                valid = y_train.notna()
                X_train = train.loc[valid, X.columns]
                y_train = y_train.loc[valid]
                if X_train.shape[0] < min_days:
                    preds_for_window = []
                    skipped_rows.append(
                        {
                            "mode": "d_only",
                            "delivery_local_date": delivery_day.isoformat(),
                            "window_days": int(window_days),
                            "reason": f"insufficient_rows_hour_{hour_idx:02d}",
                        }
                    )
                    break

                model = LagoLearModel(x2_missing_policy=config.x2_missing_policy)
                model.fit(X_train, y_train)
                if model.pipeline is None:
                    preds_for_window = []
                    skipped_rows.append(
                        {
                            "mode": "d_only",
                            "delivery_local_date": delivery_day.isoformat(),
                            "window_days": int(window_days),
                            "reason": model.fit_warning or f"model_fit_failed_hour_{hour_idx:02d}",
                        }
                    )
                    break
                pred = float(model.predict(x_test)[0])
                preds_for_window.append(pred)
                fit_time_total += float(model.fit_time_sec)
                pred_time_total += float(model.predict_time_sec)

                fit_audit_rows.append(
                    {
                        "mode": "d_only",
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "window_days": int(window_days),
                        "target_hour_local": int(hour_idx - 1),
                        "train_rows": int(X_train.shape[0]),
                        "fit_time_sec": float(model.fit_time_sec),
                        "predict_time_sec": float(model.predict_time_sec),
                        "fit_warning": model.fit_warning,
                        "converged": bool(model.converged),
                    }
                )
                alpha_rows.append(
                    {
                        "mode": "d_only",
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "window_days": int(window_days),
                        "target_hour_local": int(hour_idx - 1),
                        "selected_alpha": float(model.selected_alpha) if model.selected_alpha is not None else np.nan,
                    }
                )
                nonzero_rows.append(
                    {
                        "mode": "d_only",
                        "delivery_local_date": delivery_day.isoformat(),
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "window_days": int(window_days),
                        "target_hour_local": int(hour_idx - 1),
                        "nonzero_count": int(model.nonzero_count),
                    }
                )

                coef_frame = model.coefficient_frame()
                if not coef_frame.empty:
                    coef_frame = coef_frame.assign(
                        mode="d_only",
                        delivery_local_date=delivery_day.isoformat(),
                        forecast_origin_utc=origin_utc.isoformat(),
                        window_days=int(window_days),
                        target_hour_local=int(hour_idx - 1),
                        model_label=f"lago_lear_247_imputed_x2_{int(window_days)}",
                    )
                    coef_rows.extend(coef_frame.to_dict(orient="records"))

            if len(preds_for_window) == 24:
                window_predictions[int(window_days)] = preds_for_window
                window_fit_times[int(window_days)] = fit_time_total
                window_predict_times[int(window_days)] = pred_time_total

        if not window_predictions:
            skipped_rows.append(
                {
                    "mode": "d_only",
                    "delivery_local_date": delivery_day.isoformat(),
                    "window_days": None,
                    "reason": "no_window_predictions_available",
                }
            )
            continue

        ensemble_values = np.nanmean(np.array(list(window_predictions.values())), axis=0).tolist()
        for hour_zero_based in range(24):
            target_utc = _target_timestamp_utc(delivery_day, hour_zero_based, config.local_timezone)
            y_true = y_true_values[hour_zero_based]
            for window_days, preds in window_predictions.items():
                pred_rows.append(
                    {
                        "model": f"lago_lear_247_imputed_x2_{int(window_days)}",
                        "model_family": "LEAR",
                        "fs_level": "LAGO",
                        "feature_variant": "LEAR_LAGO_247_IMPUTED_X2",
                        "window_days": int(window_days),
                        "ensemble_component": True,
                        "dataset_split": dataset_split,
                        "forecast_origin_utc": origin_utc,
                        "forecast_origin_local": pd.Timestamp(row["forecast_origin_local"]),
                        "target_timestamp_utc": target_utc,
                        "target_delivery_local_date": delivery_day,
                        "target_hour_local": int(hour_zero_based),
                        "target_known_at_utc": origin_utc,
                        "lead_day": 0,
                        "lead_day_label": "D",
                        "horizon_index": int(hour_zero_based + 1),
                        "y_true": y_true,
                        "y_pred": float(preds[hour_zero_based]),
                        "is_observed_target": bool(pd.notna(y_true)),
                        "fit_time_sec": float(window_fit_times.get(window_days, np.nan)),
                        "predict_time_sec": float(window_predict_times.get(window_days, np.nan)),
                        "fit_time_warning": False,
                    }
                )
            pred_rows.append(
                {
                    "model": "lago_lear_247_imputed_x2_ensemble",
                    "model_family": "LEAR",
                    "fs_level": "LAGO",
                    "feature_variant": "LEAR_LAGO_247_IMPUTED_X2",
                    "window_days": "ensemble",
                    "ensemble_component": False,
                    "dataset_split": dataset_split,
                    "forecast_origin_utc": origin_utc,
                    "forecast_origin_local": pd.Timestamp(row["forecast_origin_local"]),
                    "target_timestamp_utc": target_utc,
                    "target_delivery_local_date": delivery_day,
                    "target_hour_local": int(hour_zero_based),
                    "target_known_at_utc": origin_utc,
                    "lead_day": 0,
                    "lead_day_label": "D",
                    "horizon_index": int(hour_zero_based + 1),
                    "y_true": y_true,
                    "y_pred": float(ensemble_values[hour_zero_based]),
                    "is_observed_target": bool(pd.notna(y_true)),
                    "fit_time_sec": float(np.nansum(list(window_fit_times.values()))),
                    "predict_time_sec": float(np.nansum(list(window_predict_times.values()))),
                    "fit_time_warning": False,
                }
            )

    predictions = pd.DataFrame(pred_rows)
    if not predictions.empty:
        predictions = predictions.sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "model"]).reset_index(drop=True)
    return LagoLearFitResult(
        predictions_long=predictions,
        coefficients_long=pd.DataFrame(coef_rows),
        model_fit_audit=pd.DataFrame(fit_audit_rows),
        alpha_selection_audit=pd.DataFrame(alpha_rows),
        nonzero_feature_summary=pd.DataFrame(nonzero_rows),
        skipped_predictions=pd.DataFrame(skipped_rows),
        imputation_summary=pd.DataFrame(imputation_rows),
    )


def fit_predict_lago_dplus4(
    *,
    X_long: pd.DataFrame,
    y_long: pd.DataFrame,
    metadata_long: pd.DataFrame,
    split_days: pd.DataFrame,
    config: LagoLearBenchmarkConfig,
    max_origins: int | None = None,
    dplus4_windows: tuple[int, ...] | None = None,
    dplus4_use_ensemble: bool = True,
    checkpoint_predictions: bool = False,
    checkpoint_dir: Path | None = None,
    checkpoint_chunk_rows: int = 5000,
    dplus4_save_full_coefs: bool = False,
    progress_path: Path | None = None,
) -> LagoLearFitResult:
    if X_long.empty or y_long.empty or metadata_long.empty:
        empty = pd.DataFrame()
        return LagoLearFitResult(
            predictions_long=empty,
            coefficients_long=empty,
            model_fit_audit=empty,
            alpha_selection_audit=empty,
            nonzero_feature_summary=empty,
            skipped_predictions=empty,
            imputation_summary=empty,
        )

    matrix = pd.concat([metadata_long.reset_index(drop=True), X_long.reset_index(drop=True), y_long.reset_index(drop=True)], axis=1)
    matrix["forecast_origin_utc"] = pd.to_datetime(matrix["forecast_origin_utc"], utc=True, errors="coerce")
    matrix["forecast_origin_local"] = pd.to_datetime(matrix["forecast_origin_local"], errors="coerce")
    matrix["target_timestamp_utc"] = pd.to_datetime(matrix["target_timestamp_utc"], utc=True, errors="coerce")
    matrix["target_delivery_local_date"] = pd.to_datetime(matrix["target_delivery_local_date"], errors="coerce").dt.date

    split_lookup = {
        pd.Timestamp(value).date(): split
        for value, split in split_days[["delivery_local_date", "dataset_split"]].itertuples(index=False)
        if pd.notna(value) and pd.notna(split)
    }
    matrix["dataset_split"] = matrix["target_delivery_local_date"].map(split_lookup)
    eval_rows = matrix[matrix["dataset_split"].isin(["validation", "test"])].copy()
    eval_origins = (
        eval_rows[["forecast_origin_utc"]]
        .drop_duplicates()
        .sort_values("forecast_origin_utc")
        .reset_index(drop=True)
    )
    if max_origins is not None:
        keep_origins = set(eval_origins.head(int(max_origins))["forecast_origin_utc"].tolist())
        eval_rows = eval_rows[eval_rows["forecast_origin_utc"].isin(keep_origins)].copy()

    feature_cols = list(X_long.columns)
    windows_to_use = tuple(int(value) for value in (dplus4_windows or config.lago_windows_days))
    windows_to_use = tuple(sorted(set(windows_to_use)))
    if not windows_to_use:
        empty = pd.DataFrame()
        return LagoLearFitResult(
            predictions_long=empty,
            coefficients_long=empty,
            model_fit_audit=empty,
            alpha_selection_audit=empty,
            nonzero_feature_summary=empty,
            skipped_predictions=empty,
            imputation_summary=empty,
        )

    pred_rows: list[dict[str, Any]] = []
    coef_rows: list[dict[str, Any]] = []
    fit_audit_rows: list[dict[str, Any]] = []
    alpha_rows: list[dict[str, Any]] = []
    nonzero_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    imputation_rows: list[dict[str, Any]] = []

    checkpoint_mode = bool(checkpoint_predictions and checkpoint_dir is not None)
    chunk_threshold = max(1, int(checkpoint_chunk_rows))
    chunk_counters = {
        "predictions": 0,
        "skipped_predictions": 0,
        "model_fit_audit": 0,
        "alpha_selection_audit": 0,
        "nonzero_feature_summary": 0,
        "imputation_summary": 0,
        "coefficients_long": 0,
    }
    if checkpoint_mode:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _flush_rows(kind: str, rows: list[dict[str, Any]], *, force: bool = False) -> None:
        if not checkpoint_mode:
            return
        if not rows:
            return
        if (not force) and len(rows) < chunk_threshold:
            return
        chunk_counters[kind] += 1
        chunk_path = checkpoint_dir / f"{kind}_chunk_{chunk_counters[kind]:06d}.csv"
        pd.DataFrame(rows).to_csv(chunk_path, index=False)
        rows.clear()

    def _combine_chunks(kind: str) -> pd.DataFrame:
        if not checkpoint_mode:
            return pd.DataFrame()
        chunk_paths = sorted(checkpoint_dir.glob(f"{kind}_chunk_*.csv"))
        if not chunk_paths:
            return pd.DataFrame()
        frames = [pd.read_csv(path) for path in chunk_paths]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    total_eval_rows = int(eval_rows.shape[0])
    planned_origins = int(eval_rows["forecast_origin_utc"].nunique())
    started = time.perf_counter()
    completed_rows = 0
    completed_origins: set[pd.Timestamp] = set()

    def _write_progress(*, current_origin: pd.Timestamp | None = None, current_lead_day: int | None = None, current_window: int | None = None) -> None:
        if progress_path is None:
            return
        elapsed = float(time.perf_counter() - started)
        if completed_rows > 0:
            eta = (elapsed / float(completed_rows)) * float(max(0, total_eval_rows - completed_rows))
        else:
            eta = None
        payload = {
            "total_eval_rows": int(total_eval_rows),
            "completed_eval_rows": int(completed_rows),
            "planned_origins": int(planned_origins),
            "completed_origins": int(len(completed_origins)),
            "prediction_rows_in_memory": int(len(pred_rows)),
            "skipped_rows_in_memory": int(len(skipped_rows)),
            "elapsed_seconds": elapsed,
            "estimated_remaining_seconds": eta,
            "current_origin_utc": current_origin.isoformat() if current_origin is not None else None,
            "current_lead_day": int(current_lead_day) if current_lead_day is not None else None,
            "current_window_days": int(current_window) if current_window is not None else None,
            "checkpoint_mode": bool(checkpoint_mode),
            "windows": [int(value) for value in windows_to_use],
            "ensemble_enabled": bool(dplus4_use_ensemble),
            "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    eval_rows = eval_rows.sort_values(["forecast_origin_utc", "lead_day", "target_hour_local", "target_timestamp_utc"])
    for row in eval_rows.itertuples(index=False):
        row_dict = row._asdict()
        origin_utc = pd.Timestamp(row_dict["forecast_origin_utc"])
        lead_day = int(row_dict["lead_day"])
        target_hour_local = int(row_dict["target_hour_local"])
        y_true = float(row_dict["y_true"]) if pd.notna(row_dict["y_true"]) else np.nan

        # Direct model per lead-day/hour, trained only on prior forecast origins.
        candidate_pool = matrix.loc[
            (matrix["forecast_origin_utc"] < origin_utc)
            & (matrix["lead_day"].astype(int) == lead_day)
            & (matrix["target_hour_local"].astype(int) == target_hour_local)
        ]
        if candidate_pool.empty:
            skipped_rows.append(
                {
                    "mode": "dplus4",
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "lead_day": lead_day,
                    "target_hour_local": target_hour_local,
                    "window_days": None,
                    "reason": "no_prior_rows_for_lead_hour",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            if checkpoint_mode:
                _flush_rows("skipped_predictions", skipped_rows)
            if completed_rows % 250 == 0:
                _write_progress(current_origin=origin_utc, current_lead_day=lead_day, current_window=None)
            continue

        window_preds: dict[int, float] = {}
        window_fit_times: dict[int, float] = {}
        window_predict_times: dict[int, float] = {}
        for window_days in windows_to_use:
            origin_dates = sorted(candidate_pool["forecast_origin_utc"].dropna().unique().tolist())
            if len(origin_dates) > int(window_days):
                threshold_origin = origin_dates[-int(window_days)]
                train = candidate_pool.loc[candidate_pool["forecast_origin_utc"] >= threshold_origin]
            else:
                train = candidate_pool

            min_days = int(config.min_training_days_by_window.get(int(window_days), 1))
            if int(train["forecast_origin_utc"].nunique()) < min_days:
                skipped_rows.append(
                    {
                        "mode": "dplus4",
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "lead_day": lead_day,
                        "target_hour_local": target_hour_local,
                        "window_days": int(window_days),
                        "reason": f"insufficient_training_origins<{min_days}",
                    }
                )
                continue

            y_train = pd.to_numeric(train["y_true"], errors="coerce")
            valid = y_train.notna()
            X_train = train.loc[valid, feature_cols]
            y_train = y_train.loc[valid]
            if X_train.empty:
                continue

            model = LagoLearModel(x2_missing_policy=config.x2_missing_policy)
            model.fit(X_train, y_train)
            if model.pipeline is None:
                skipped_rows.append(
                    {
                        "mode": "dplus4",
                        "forecast_origin_utc": origin_utc.isoformat(),
                        "lead_day": lead_day,
                        "target_hour_local": target_hour_local,
                        "window_days": int(window_days),
                        "reason": model.fit_warning or "model_fit_failed",
                    }
                )
                continue
            X_test = pd.DataFrame([{col: row_dict[col] for col in feature_cols}])
            pred = float(model.predict(X_test)[0])

            window_preds[int(window_days)] = pred
            window_fit_times[int(window_days)] = float(model.fit_time_sec)
            window_predict_times[int(window_days)] = float(model.predict_time_sec)

            fit_audit_rows.append(
                {
                    "mode": "dplus4",
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "lead_day": lead_day,
                    "target_hour_local": target_hour_local,
                    "window_days": int(window_days),
                    "train_rows": int(X_train.shape[0]),
                    "fit_time_sec": float(model.fit_time_sec),
                    "predict_time_sec": float(model.predict_time_sec),
                    "fit_warning": model.fit_warning,
                    "converged": bool(model.converged),
                }
            )
            alpha_rows.append(
                {
                    "mode": "dplus4",
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "lead_day": lead_day,
                    "target_hour_local": target_hour_local,
                    "window_days": int(window_days),
                    "selected_alpha": float(model.selected_alpha) if model.selected_alpha is not None else np.nan,
                }
            )
            nonzero_rows.append(
                {
                    "mode": "dplus4",
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "lead_day": lead_day,
                    "target_hour_local": target_hour_local,
                    "window_days": int(window_days),
                    "nonzero_count": int(model.nonzero_count),
                }
            )
            coef_frame = model.coefficient_frame()
            if not coef_frame.empty:
                top_coef = coef_frame.iloc[0]
                nonzero_rows[-1]["top_feature_name"] = str(top_coef["feature_name"])
                nonzero_rows[-1]["top_abs_coefficient"] = float(top_coef["abs_coefficient"])
            coef_frame = model.coefficient_frame()
            if dplus4_save_full_coefs and not coef_frame.empty:
                coef_frame = coef_frame.assign(
                    mode="dplus4",
                    forecast_origin_utc=origin_utc.isoformat(),
                    lead_day=lead_day,
                    target_hour_local=target_hour_local,
                    window_days=int(window_days),
                    model_label=f"lear_lago_direct_dplus4_strict_no_future_{int(window_days)}",
                )
                coef_rows.extend(coef_frame.to_dict(orient="records"))
            train_missing_counts = pd.to_numeric(X_train.stack(), errors="coerce").isna().sum()
            predict_missing_counts = pd.to_numeric(X_test.stack(), errors="coerce").isna().sum()
            x2_missing_train = int(pd.to_numeric(X_train[[col for col in feature_cols if str(col).startswith("x2_")]].stack(), errors="coerce").isna().sum()) if any(str(col).startswith("x2_") for col in feature_cols) else 0
            imputation_rows.append(
                {
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "model_label": f"lear_lago_direct_dplus4_strict_no_future_{int(window_days)}",
                    "window_days": int(window_days),
                    "lead_day": _lead_day_label(lead_day),
                    "target_hour": int(target_hour_local),
                    "train_missing_cells_total": int(train_missing_counts),
                    "predict_missing_cells_total": int(predict_missing_counts),
                    "x2_train_missing_cells": int(x2_missing_train),
                    "imputer_fit_rows": int(model.imputer_fit_rows),
                    "imputer_strategy": "median",
                }
            )
            if checkpoint_mode:
                _flush_rows("model_fit_audit", fit_audit_rows)
                _flush_rows("alpha_selection_audit", alpha_rows)
                _flush_rows("nonzero_feature_summary", nonzero_rows)
                _flush_rows("imputation_summary", imputation_rows)
                if dplus4_save_full_coefs:
                    _flush_rows("coefficients_long", coef_rows)
            if (completed_rows % 250 == 0) or (window_days == windows_to_use[-1]):
                _write_progress(current_origin=origin_utc, current_lead_day=lead_day, current_window=int(window_days))

        if not window_preds:
            skipped_rows.append(
                {
                    "mode": "dplus4",
                    "forecast_origin_utc": origin_utc.isoformat(),
                    "lead_day": lead_day,
                    "target_hour_local": target_hour_local,
                    "window_days": None,
                    "reason": "no_window_predictions_available",
                }
            )
            completed_rows += 1
            completed_origins.add(origin_utc)
            if checkpoint_mode:
                _flush_rows("skipped_predictions", skipped_rows)
            if completed_rows % 250 == 0:
                _write_progress(current_origin=origin_utc, current_lead_day=lead_day, current_window=None)
            continue

        if dplus4_use_ensemble:
            ensemble_pred = float(np.nanmean(np.array(list(window_preds.values()), dtype=float)))
        for window_days, pred_value in window_preds.items():
            pred_rows.append(
                {
                    "model": f"lear_lago_direct_dplus4_strict_no_future_{int(window_days)}",
                    "model_family": "LEAR",
                    "fs_level": "LAGO",
                    "feature_variant": "LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE",
                    "window_days": int(window_days),
                    "ensemble_component": True,
                    "dataset_split": str(row_dict["dataset_split"]),
                    "forecast_origin_utc": origin_utc,
                    "forecast_origin_local": row_dict["forecast_origin_local"],
                    "target_timestamp_utc": row_dict["target_timestamp_utc"],
                    "target_delivery_local_date": row_dict["target_delivery_local_date"],
                    "target_hour_local": target_hour_local,
                    "target_known_at_utc": origin_utc,
                    "lead_day": lead_day,
                    "lead_day_label": _lead_day_label(lead_day),
                    "horizon_index": int((lead_day * 24) + target_hour_local + 1),
                    "y_true": y_true,
                    "y_pred": float(pred_value),
                    "is_observed_target": bool(row_dict.get("is_observed_target", True)),
                    "fit_time_sec": float(window_fit_times.get(window_days, np.nan)),
                    "predict_time_sec": float(window_predict_times.get(window_days, np.nan)),
                    "fit_time_warning": False,
                }
            )
        if dplus4_use_ensemble:
            pred_rows.append(
                {
                    "model": "lear_lago_direct_dplus4_strict_no_future_ensemble",
                    "model_family": "LEAR",
                    "fs_level": "LAGO",
                    "feature_variant": "LEAR_LAGO_DIRECT_DPLUS4_STRICT_NO_FUTURE",
                    "window_days": "ensemble",
                    "ensemble_component": False,
                    "dataset_split": str(row_dict["dataset_split"]),
                    "forecast_origin_utc": origin_utc,
                    "forecast_origin_local": row_dict["forecast_origin_local"],
                    "target_timestamp_utc": row_dict["target_timestamp_utc"],
                    "target_delivery_local_date": row_dict["target_delivery_local_date"],
                    "target_hour_local": target_hour_local,
                    "target_known_at_utc": origin_utc,
                    "lead_day": lead_day,
                    "lead_day_label": _lead_day_label(lead_day),
                    "horizon_index": int((lead_day * 24) + target_hour_local + 1),
                    "y_true": y_true,
                    "y_pred": ensemble_pred,
                    "is_observed_target": bool(row_dict.get("is_observed_target", True)),
                    "fit_time_sec": float(np.nansum(list(window_fit_times.values()))),
                    "predict_time_sec": float(np.nansum(list(window_predict_times.values()))),
                    "fit_time_warning": False,
                }
            )

        completed_rows += 1
        completed_origins.add(origin_utc)
        if checkpoint_mode:
            _flush_rows("predictions", pred_rows)
            _flush_rows("skipped_predictions", skipped_rows)
        if completed_rows % 250 == 0:
            _write_progress(current_origin=origin_utc, current_lead_day=lead_day, current_window=None)
            gc.collect()

    if checkpoint_mode:
        _flush_rows("predictions", pred_rows, force=True)
        _flush_rows("skipped_predictions", skipped_rows, force=True)
        _flush_rows("model_fit_audit", fit_audit_rows, force=True)
        _flush_rows("alpha_selection_audit", alpha_rows, force=True)
        _flush_rows("nonzero_feature_summary", nonzero_rows, force=True)
        _flush_rows("imputation_summary", imputation_rows, force=True)
        if dplus4_save_full_coefs:
            _flush_rows("coefficients_long", coef_rows, force=True)
        _write_progress(current_origin=None, current_lead_day=None, current_window=None)

    predictions = _combine_chunks("predictions") if checkpoint_mode else pd.DataFrame(pred_rows)
    if not predictions.empty:
        if "forecast_origin_utc" in predictions.columns:
            predictions["forecast_origin_utc"] = pd.to_datetime(predictions["forecast_origin_utc"], utc=True, errors="coerce")
        if "target_timestamp_utc" in predictions.columns:
            predictions["target_timestamp_utc"] = pd.to_datetime(predictions["target_timestamp_utc"], utc=True, errors="coerce")
        predictions = predictions.sort_values(["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "model"]).reset_index(drop=True)

    coefficients_long = _combine_chunks("coefficients_long") if checkpoint_mode else pd.DataFrame(coef_rows)
    model_fit_audit = _combine_chunks("model_fit_audit") if checkpoint_mode else pd.DataFrame(fit_audit_rows)
    alpha_selection_audit = _combine_chunks("alpha_selection_audit") if checkpoint_mode else pd.DataFrame(alpha_rows)
    nonzero_feature_summary = _combine_chunks("nonzero_feature_summary") if checkpoint_mode else pd.DataFrame(nonzero_rows)
    skipped_predictions = _combine_chunks("skipped_predictions") if checkpoint_mode else pd.DataFrame(skipped_rows)
    imputation_summary = _combine_chunks("imputation_summary") if checkpoint_mode else pd.DataFrame(imputation_rows)

    return LagoLearFitResult(
        predictions_long=predictions,
        coefficients_long=coefficients_long,
        model_fit_audit=model_fit_audit,
        alpha_selection_audit=alpha_selection_audit,
        nonzero_feature_summary=nonzero_feature_summary,
        skipped_predictions=skipped_predictions,
        imputation_summary=imputation_summary,
    )
