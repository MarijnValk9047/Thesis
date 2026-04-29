from __future__ import annotations

import numpy as np
import pandas as pd


def add_error_columns(predictions: pd.DataFrame) -> pd.DataFrame:
    scored = predictions.copy()
    scored["error"] = scored["y_pred"] - scored["y_true"]
    scored["abs_error"] = scored["error"].abs()
    scored["squared_error"] = scored["error"] ** 2

    denom_mape = scored["y_true"].abs().replace(0.0, np.nan)
    scored["ape"] = (scored["abs_error"] / denom_mape) * 100.0

    denom_smape = (scored["y_true"].abs() + scored["y_pred"].abs()).replace(0.0, np.nan)
    scored["smape_component"] = (2.0 * scored["abs_error"] / denom_smape) * 100.0
    return scored


def summarize_metrics(scored_predictions: pd.DataFrame) -> pd.DataFrame:
    if scored_predictions.empty:
        return pd.DataFrame(
            columns=[
                "split",
                "model",
                "origins",
                "observations",
                "coverage_pct",
                "mae",
                "rmse",
                "bias",
                "mape_pct",
                "smape_pct",
            ]
        )

    rows: list[dict[str, object]] = []
    for (split_name, model_name), group in scored_predictions.groupby(["split", "model"], dropna=False):
        coverage = group["y_pred"].notna().mean() * 100.0
        valid = group[group["y_pred"].notna()].copy()
        if valid.empty:
            rows.append(
                {
                    "split": split_name,
                    "model": model_name,
                    "origins": int(group["origin_local"].nunique()),
                    "observations": int(len(group)),
                    "coverage_pct": round(float(coverage), 4),
                    "mae": np.nan,
                    "rmse": np.nan,
                    "bias": np.nan,
                    "mape_pct": np.nan,
                    "smape_pct": np.nan,
                }
            )
            continue

        rows.append(
            {
                "split": split_name,
                "model": model_name,
                "origins": int(group["origin_local"].nunique()),
                "observations": int(len(group)),
                "coverage_pct": round(float(coverage), 4),
                "mae": float(valid["abs_error"].mean()),
                "rmse": float(np.sqrt(valid["squared_error"].mean())),
                "bias": float(valid["error"].mean()),
                "mape_pct": float(valid["ape"].mean(skipna=True)),
                "smape_pct": float(valid["smape_component"].mean(skipna=True)),
            }
        )

    return pd.DataFrame(rows).sort_values(["split", "mae", "model"]).reset_index(drop=True)


def choose_official_naive(
    metrics_df: pd.DataFrame,
    split_name: str = "validation",
    metric_col: str = "mae",
) -> dict[str, object]:
    candidates = metrics_df[
        (metrics_df["split"] == split_name) & (metrics_df["model"].isin(["naive_1d", "naive_7d"]))
    ].copy()
    if candidates.empty:
        raise ValueError("No naive candidates found to select the official reference.")
    if metric_col not in candidates.columns:
        raise ValueError(f"Metric column not found: {metric_col}")

    candidates = candidates.sort_values([metric_col, "model"], ascending=[True, True]).reset_index(drop=True)
    best = candidates.iloc[0].to_dict()
    best["selection_split"] = split_name
    best["selection_metric"] = metric_col
    return best


def add_relative_metric_vs_reference(
    metrics_df: pd.DataFrame,
    reference_model: str,
    metric_col: str = "mae",
    output_col: str = "skill_vs_reference_pct",
) -> pd.DataFrame:
    scored = metrics_df.copy()
    if metric_col not in scored.columns:
        raise ValueError(f"Metric column not found: {metric_col}")

    reference = (
        scored[scored["model"] == reference_model][["split", metric_col]]
        .rename(columns={metric_col: "reference_metric"})
        .copy()
    )
    if reference.empty:
        raise ValueError(f"Reference model '{reference_model}' not present in metrics.")

    merged = scored.merge(reference, on="split", how="left")
    merged[output_col] = (1.0 - (merged[metric_col] / merged["reference_metric"])) * 100.0
    merged.loc[merged["reference_metric"].isna(), output_col] = np.nan
    merged.loc[merged["reference_metric"] == 0.0, output_col] = np.nan
    return merged.drop(columns=["reference_metric"])
