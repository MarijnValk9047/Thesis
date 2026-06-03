from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd


def _running_inside_ipykernel() -> bool:
    try:
        from IPython import get_ipython
    except Exception:
        return False
    shell = get_ipython()
    return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"


if not _running_inside_ipykernel():
    matplotlib.use("Agg")

import matplotlib.pyplot as plt


def _ensure_datetime_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "forecast_origin_utc" in out.columns:
        out["forecast_origin_utc"] = pd.to_datetime(out["forecast_origin_utc"], utc=True, errors="coerce")
    if "target_timestamp_utc" in out.columns:
        out["target_timestamp_utc"] = pd.to_datetime(out["target_timestamp_utc"], utc=True, errors="coerce")
    if "target_delivery_local_date" in out.columns:
        out["target_delivery_local_date"] = pd.to_datetime(out["target_delivery_local_date"], errors="coerce").dt.date
    return out


def _savefig(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def plot_selected_week_overlays(
    predictions: pd.DataFrame,
    selected_weeks: pd.DataFrame,
    output_root: Path,
    *,
    baseline_models: list[str] | None = None,
) -> None:
    if predictions.empty or selected_weeks.empty:
        return
    frame = _ensure_datetime_columns(predictions)
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    baseline_models = baseline_models or []
    for week in selected_weeks.to_dict(orient="records"):
        start_day = pd.Timestamp(week["week_start_local_date"]).date()
        end_day = pd.Timestamp(week["week_end_local_date"]).date()
        part = frame[
            (frame["target_delivery_local_date"] >= start_day)
            & (frame["target_delivery_local_date"] <= end_day)
        ].copy()
        if part.empty:
            continue

        preferred_models = [
            "lago_lear_d_exact_available_x2_ensemble",
            "lago_lear_dplus4_available_ensemble",
            *baseline_models,
        ]
        keep = [model for model in preferred_models if model in set(part["model"].astype(str))]
        if keep:
            part = part[part["model"].astype(str).isin(keep)].copy()

        fig, ax = plt.subplots(figsize=(18, 5.6))
        actual = part[["target_timestamp_local", "y_true"]].drop_duplicates().sort_values("target_timestamp_local")
        ax.plot(actual["target_timestamp_local"], actual["y_true"], color="#1f2937", linewidth=2.4, label="actual")
        for model_name, model_group in part.groupby("model", dropna=False):
            model_group = model_group.sort_values("target_timestamp_local")
            ax.plot(model_group["target_timestamp_local"], model_group["y_pred"], linewidth=1.6, label=str(model_name))
        ax.set_title(f"{week['category']} ({week['iso_week_id']}) actual vs forecasts", loc="left")
        ax.set_xlabel("Local timestamp")
        ax.set_ylabel("EUR/MWh")
        ax.grid(alpha=0.25)
        ax.legend(loc="best", ncols=2)
        _savefig(output_root / "selected_weeks" / f"{week['category']}_actual_vs_models.png")


def plot_week_error_series(predictions: pd.DataFrame, selected_weeks: pd.DataFrame, output_root: Path) -> None:
    if predictions.empty or selected_weeks.empty:
        return
    frame = _ensure_datetime_columns(predictions)
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    frame["abs_error"] = (pd.to_numeric(frame["y_pred"], errors="coerce") - pd.to_numeric(frame["y_true"], errors="coerce")).abs()
    for week in selected_weeks.to_dict(orient="records"):
        start_day = pd.Timestamp(week["week_start_local_date"]).date()
        end_day = pd.Timestamp(week["week_end_local_date"]).date()
        part = frame[
            (frame["target_delivery_local_date"] >= start_day)
            & (frame["target_delivery_local_date"] <= end_day)
        ].copy()
        if part.empty:
            continue
        fig, ax = plt.subplots(figsize=(18, 5.2))
        for model_name, model_group in part.groupby("model", dropna=False):
            model_group = model_group.sort_values("target_timestamp_local")
            ax.plot(model_group["target_timestamp_local"], model_group["abs_error"], linewidth=1.4, label=str(model_name))
        ax.set_title(f"{week['category']} ({week['iso_week_id']}) absolute error series", loc="left")
        ax.set_xlabel("Local timestamp")
        ax.set_ylabel("Absolute error")
        ax.grid(alpha=0.25)
        ax.legend(loc="best", ncols=2)
        _savefig(output_root / "selected_weeks" / f"{week['category']}_error_series.png")


def plot_abs_error_heatmap(predictions: pd.DataFrame, output_root: Path) -> None:
    if predictions.empty:
        return
    frame = _ensure_datetime_columns(predictions)
    frame["target_hour_local"] = pd.to_numeric(frame["target_hour_local"], errors="coerce")
    frame["abs_error"] = (pd.to_numeric(frame["y_pred"], errors="coerce") - pd.to_numeric(frame["y_true"], errors="coerce")).abs()
    matrix = (
        frame.groupby(["model", "target_hour_local"], dropna=False)["abs_error"]
        .mean()
        .unstack(fill_value=np.nan)
        .sort_index()
    )
    if matrix.empty:
        return
    fig, ax = plt.subplots(figsize=(14, 5.5))
    im = ax.imshow(matrix.values, aspect="auto")
    ax.set_yticks(range(len(matrix.index)))
    ax.set_yticklabels([str(value) for value in matrix.index.tolist()])
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_xticklabels([str(int(value)) for value in matrix.columns.tolist()], rotation=45, ha="right")
    ax.set_title("Absolute error heatmap by model and hour", loc="left")
    ax.set_xlabel("Target hour local")
    ax.set_ylabel("Model")
    fig.colorbar(im, ax=ax, label="Mean absolute error")
    _savefig(output_root / "diagnostics" / "abs_error_heatmap_model_hour.png")


def plot_residual_distribution(predictions: pd.DataFrame, output_root: Path) -> None:
    if predictions.empty:
        return
    frame = predictions.copy()
    frame["error"] = pd.to_numeric(frame["y_pred"], errors="coerce") - pd.to_numeric(frame["y_true"], errors="coerce")
    frame = frame[frame["error"].notna()].copy()
    if frame.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for model_name, group in frame.groupby("model", dropna=False):
        ax.hist(group["error"], bins=80, alpha=0.35, label=str(model_name), density=True)
    ax.set_title("Residual distribution by model", loc="left")
    ax.set_xlabel("Forecast error (y_pred - y_true)")
    ax.set_ylabel("Density")
    ax.legend(loc="best")
    ax.grid(alpha=0.2)
    _savefig(output_root / "diagnostics" / "residual_distribution.png")


def plot_residuals_by_hour_lead(predictions: pd.DataFrame, output_root: Path) -> None:
    if predictions.empty:
        return
    frame = predictions.copy()
    frame["error"] = pd.to_numeric(frame["y_pred"], errors="coerce") - pd.to_numeric(frame["y_true"], errors="coerce")
    frame["target_hour_local"] = pd.to_numeric(frame["target_hour_local"], errors="coerce")
    agg = (
        frame.groupby(["model", "lead_day", "target_hour_local"], dropna=False)["error"]
        .mean()
        .reset_index()
    )
    if agg.empty:
        return
    for model_name, part in agg.groupby("model", dropna=False):
        pivot = part.pivot(index="lead_day", columns="target_hour_local", values="error")
        if pivot.empty:
            continue
        fig, ax = plt.subplots(figsize=(12, 4.5))
        im = ax.imshow(pivot.values, aspect="auto")
        ax.set_title(f"Mean residual by lead-day/hour: {model_name}", loc="left")
        ax.set_xlabel("Hour local")
        ax.set_ylabel("Lead day")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([str(int(value)) for value in pivot.columns.tolist()], rotation=45, ha="right")
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(int(value)) for value in pivot.index.tolist()])
        fig.colorbar(im, ax=ax, label="Mean residual")
        _savefig(output_root / "diagnostics" / f"residuals_by_hour_lead_{model_name}.png")


def plot_mae_by_lead_day(metrics_by_lead_day: pd.DataFrame, output_root: Path) -> None:
    if metrics_by_lead_day.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for model_name, part in metrics_by_lead_day.groupby("model", dropna=False):
        part = part.sort_values("lead_day")
        ax.plot(part["lead_day"], part["mae"], marker="o", linewidth=1.8, label=str(model_name))
    ax.set_title("MAE by lead day", loc="left")
    ax.set_xlabel("Lead day")
    ax.set_ylabel("MAE")
    ax.set_xticks(sorted(metrics_by_lead_day["lead_day"].dropna().astype(int).unique().tolist()))
    ax.legend(loc="best")
    ax.grid(alpha=0.25)
    _savefig(output_root / "diagnostics" / "mae_by_lead_day.png")


def plot_top_bottom_identification(predictions: pd.DataFrame, selected_weeks: pd.DataFrame, output_root: Path) -> None:
    if predictions.empty or selected_weeks.empty:
        return
    frame = _ensure_datetime_columns(predictions)
    frame["target_timestamp_local"] = frame["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    preferred = frame[frame["model"].astype(str).str.endswith("_ensemble")].copy()
    if preferred.empty:
        preferred = frame.copy()
    for week in selected_weeks.to_dict(orient="records"):
        start_day = pd.Timestamp(week["week_start_local_date"]).date()
        end_day = pd.Timestamp(week["week_end_local_date"]).date()
        part = preferred[
            (preferred["target_delivery_local_date"] >= start_day)
            & (preferred["target_delivery_local_date"] <= end_day)
        ].copy()
        if part.empty:
            continue
        # Use first model only for readability.
        model_name = str(part["model"].iloc[0])
        model_part = part[part["model"].astype(str) == model_name].copy().sort_values("target_timestamp_local")
        if model_part.empty:
            continue
        fig, ax = plt.subplots(figsize=(18, 5.6))
        ax.plot(model_part["target_timestamp_local"], model_part["y_true"], color="#111827", linewidth=2.1, label="actual")
        ax.plot(model_part["target_timestamp_local"], model_part["y_pred"], color="#2563eb", linewidth=1.6, label=model_name)
        for k, color in ((4, "#dc2626"), (8, "#d97706")):
            if model_part.shape[0] < k:
                continue
            actual_top_idx = model_part.sort_values("y_true", ascending=False).head(k).index
            pred_top_idx = model_part.sort_values("y_pred", ascending=False).head(k).index
            ax.scatter(model_part.loc[actual_top_idx, "target_timestamp_local"], model_part.loc[actual_top_idx, "y_true"], color=color, s=30, label=f"actual top-{k}")
            ax.scatter(model_part.loc[pred_top_idx, "target_timestamp_local"], model_part.loc[pred_top_idx, "y_pred"], color=color, s=22, marker="x", label=f"pred top-{k}")
        ax.set_title(f"{week['category']} ({week['iso_week_id']}) top/bottom hour identification", loc="left")
        ax.set_xlabel("Local timestamp")
        ax.set_ylabel("EUR/MWh")
        ax.grid(alpha=0.2)
        ax.legend(loc="best", ncols=3)
        _savefig(output_root / "selected_weeks" / f"{week['category']}_top_bottom_identification.png")


def _feature_family(name: str) -> str:
    if name.startswith("price_"):
        return "price_lag"
    if name.startswith("x1_"):
        return "x1_load"
    if name.startswith("x2_"):
        return "x2_generation"
    if name.startswith("dow_"):
        return "weekday"
    if name.startswith("lead_day_"):
        return "lead_day"
    return "other"


def plot_coefficient_heatmap(coefficients_long: pd.DataFrame, output_root: Path) -> None:
    if coefficients_long.empty:
        return
    frame = coefficients_long.copy()
    if "is_nonzero" not in frame.columns:
        frame["is_nonzero"] = pd.to_numeric(frame.get("coefficient", np.nan), errors="coerce").abs() > 0.0
    frame["feature_family"] = frame["feature_name"].astype(str).map(_feature_family)
    agg = (
        frame.groupby(["model_label", "feature_family"], dropna=False)["is_nonzero"]
        .mean()
        .unstack(fill_value=np.nan)
    )
    if agg.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 4.5))
    im = ax.imshow(agg.values, aspect="auto")
    ax.set_yticks(range(len(agg.index)))
    ax.set_yticklabels([str(value) for value in agg.index.tolist()])
    ax.set_xticks(range(len(agg.columns)))
    ax.set_xticklabels([str(value) for value in agg.columns.tolist()], rotation=35, ha="right")
    ax.set_title("Nonzero coefficient frequency by feature family", loc="left")
    fig.colorbar(im, ax=ax, label="Nonzero frequency")
    _savefig(output_root / "features" / "coefficient_family_heatmap.png")


def plot_feature_schematic(output_root: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.2))
    ax.axis("off")
    lines = [
        "Lago D-only feature schematic (247 features)",
        "",
        "Price lags: p_{d-1}, p_{d-2}, p_{d-3}, p_{d-7} (4 x 24 = 96)",
        "Current exogenous: x1_d (load), x2_d (RES forecast) (2 x 24 = 48)",
        "Lagged exogenous: x1_{d-1}, x1_{d-7}, x2_{d-1}, x2_{d-7} (4 x 24 = 96)",
        "Weekday dummies: 7",
        "Total = 96 + 48 + 96 + 7 = 247",
    ]
    ax.text(0.02, 0.95, "\n".join(lines), va="top", ha="left", fontsize=11)
    _savefig(output_root / "features" / "feature_construction_schematic.png")


def plot_res_forecast_diagnostics(
    res_by_psr: pd.DataFrame,
    res_agg: pd.DataFrame,
    output_root: Path,
) -> None:
    if res_by_psr.empty and res_agg.empty:
        return
    if not res_by_psr.empty:
        by_psr = res_by_psr.copy()
        by_psr["timestamp_utc"] = pd.to_datetime(by_psr["timestamp_utc"], utc=True, errors="coerce")
        by_psr["timestamp_local"] = by_psr["timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
        by_psr["year"] = by_psr["timestamp_local"].dt.year.astype("Int64")
        by_psr["is_missing"] = by_psr["value_mw"].isna()

        if "psr_type" in by_psr.columns:
            sample = by_psr[by_psr["psr_type"].astype(str).isin(["B16", "B18", "B19"])].copy()
            if not sample.empty:
                start = sample["timestamp_utc"].min()
                week = sample[
                    (sample["timestamp_utc"] >= start)
                    & (sample["timestamp_utc"] < start + pd.Timedelta(days=7))
                ].copy()
                if not week.empty:
                    fig, ax = plt.subplots(figsize=(18, 5.2))
                    for psr, group in week.groupby("psr_type", dropna=False):
                        ax.plot(group["timestamp_local"], group["value_mw"], linewidth=1.7, label=str(psr))
                    ax.set_title("A69 RES forecast components (sample week)", loc="left")
                    ax.set_xlabel("Local timestamp")
                    ax.set_ylabel("MW")
                    ax.legend(loc="best")
                    ax.grid(alpha=0.25)
                    _savefig(output_root / "features" / "res_components_sample_week.png")

            miss = (
                by_psr.groupby(["year", "psr_type"], dropna=False)["is_missing"]
                .mean()
                .reset_index()
                .pivot(index="psr_type", columns="year", values="is_missing")
            )
            if not miss.empty:
                fig, ax = plt.subplots(figsize=(10, 3.8))
                im = ax.imshow(miss.values, aspect="auto")
                ax.set_yticks(range(len(miss.index)))
                ax.set_yticklabels([str(value) for value in miss.index.tolist()])
                ax.set_xticks(range(len(miss.columns)))
                ax.set_xticklabels([str(value) for value in miss.columns.tolist()], rotation=30, ha="right")
                ax.set_title("RES forecast missingness by PSR/year", loc="left")
                fig.colorbar(im, ax=ax, label="Missing share")
                _savefig(output_root / "features" / "res_missingness_by_psr_year.png")

    if not res_agg.empty:
        agg = res_agg.copy()
        agg["timestamp_utc"] = pd.to_datetime(agg["timestamp_utc"], utc=True, errors="coerce")
        agg["timestamp_local"] = agg["timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
        start = agg["timestamp_utc"].min()
        week = agg[(agg["timestamp_utc"] >= start) & (agg["timestamp_utc"] < start + pd.Timedelta(days=7))].copy()
        if not week.empty:
            fig, ax = plt.subplots(figsize=(18, 5))
            ax.plot(week["timestamp_local"], week["value_mw"], linewidth=1.8, color="#2563eb")
            ax.set_title("Aggregated RES forecast x2 (sample week)", loc="left")
            ax.set_xlabel("Local timestamp")
            ax.set_ylabel("MW")
            ax.grid(alpha=0.25)
            _savefig(output_root / "features" / "res_aggregate_sample_week.png")
