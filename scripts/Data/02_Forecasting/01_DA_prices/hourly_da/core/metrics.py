from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from .reporting import ReportingLevelSpec, reporting_level_specs


@dataclass(frozen=True)
class RMAEDenominatorInheritancePolicy:
    source_of_truth_artifact: str
    source_selection_rule: str
    comparison_context_rule: str
    recompute_per_child_run: bool
    provenance_fields: tuple[str, ...]
    notes: str


RMAE_DENOMINATOR_INHERITANCE_POLICY = RMAEDenominatorInheritancePolicy(
    source_of_truth_artifact="official_naive_reference.json",
    source_selection_rule="inherit_from_parent_benchmark_stage",
    comparison_context_rule="Freeze the naive denominator within one parent benchmark context, fs_level, split, and reporting_level.",
    recompute_per_child_run=False,
    provenance_fields=(
        "rmae_denominator_source_run_id",
        "rmae_denominator_source_run_label",
        "rmae_denominator_source_artifact",
        "inherited_rmae_reference_snapshot",
    ),
    notes="Phase 2 keeps the current run-local rMAE implementation unchanged for parent benchmark runs and formalizes inheritance metadata for future ablation runs.",
)


def rmae_policy_snapshot() -> dict[str, object]:
    return asdict(RMAE_DENOMINATOR_INHERITANCE_POLICY)


def build_inherited_rmae_reference_snapshot(
    official_naive_reference: dict[str, object],
    *,
    source_run_id: str,
    source_run_label: str,
    source_artifact: str = "official_naive_reference.json",
) -> dict[str, object]:
    return {
        "rmae_denominator_source_run_id": source_run_id,
        "rmae_denominator_source_run_label": source_run_label,
        "rmae_denominator_source_artifact": source_artifact,
        "inherited_rmae_reference_snapshot": dict(official_naive_reference),
    }


def add_error_columns(predictions: pd.DataFrame) -> pd.DataFrame:
    scored = predictions.copy()
    scored["error"] = scored["y_pred"] - scored["y_true"]
    scored["abs_error"] = scored["error"].abs()
    scored["squared_error"] = scored["error"] ** 2
    denom_smape = (scored["y_true"].abs() + scored["y_pred"].abs()).replace(0.0, np.nan)
    scored["smape_component"] = (2.0 * scored["abs_error"] / denom_smape) * 100.0
    return scored


def _metric_row(group: pd.DataFrame) -> dict[str, object]:
    valid = group[group["y_true"].notna() & group["y_pred"].notna()].copy()
    if valid.empty:
        return {
            "observations_total": int(group.shape[0]),
            "observations_scored": 0,
            "coverage_pct": 0.0,
            "mae": np.nan,
            "rmse": np.nan,
            "bias": np.nan,
            "smape_pct": np.nan,
        }

    return {
        "observations_total": int(group.shape[0]),
        "observations_scored": int(valid.shape[0]),
        "coverage_pct": float(valid.shape[0] / group.shape[0] * 100.0),
        "mae": float(valid["abs_error"].mean()),
        "rmse": float(math.sqrt(valid["squared_error"].mean())),
        "bias": float(valid["error"].mean()),
        "smape_pct": float(valid["smape_component"].mean(skipna=True)),
    }


def summarize_overall_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    group_cols = ["model", "model_family", "fs_level", "dataset_split"]
    for keys, group in scored.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "mae", "model"]).reset_index(drop=True)


def summarize_metrics_by_lead_day(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    group_cols = ["model", "model_family", "fs_level", "dataset_split", "lead_day", "lead_day_label"]
    for keys, group in scored.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys, strict=True))
        row.update(_metric_row(group))
        row["origins"] = int(group["forecast_origin_utc"].nunique())
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["dataset_split", "lead_day", "mae", "model"]).reset_index(drop=True)


def summarize_metrics_by_reporting_level(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    group_cols = ["model", "model_family", "fs_level", "dataset_split"]
    for spec in reporting_level_specs():
        subset = scored[scored["lead_day"].isin(spec.lead_days)].copy()
        if subset.empty:
            continue
        reporting_cols = spec.to_columns()
        for keys, group in subset.groupby(group_cols, dropna=False):
            row = dict(zip(group_cols, keys, strict=True))
            row.update(_metric_row(group))
            row["origins"] = int(group["forecast_origin_utc"].nunique())
            row.update(reporting_cols)
            rows.append(row)

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["dataset_split", "reporting_level_sort_order", "mae", "model"])
        .reset_index(drop=True)
    )


def choose_official_naive_reference(
    overall_metrics: pd.DataFrame,
    split_name: str = "validation",
    reporting_level: str | None = None,
    minimum_coverage_pct: float = 95.0,
) -> dict[str, object]:
    candidates = overall_metrics[
        (overall_metrics["dataset_split"] == split_name)
        & (overall_metrics["model"].isin(["naive_previous_week", "naive_previous_year"]))
    ].copy()
    if reporting_level is not None:
        if "reporting_level" not in candidates.columns:
            raise ValueError("Reporting-level selection requested but the metrics frame has no reporting_level column.")
        candidates = candidates[candidates["reporting_level"] == reporting_level].copy()
    if candidates.empty:
        raise ValueError("No naive candidates available for official benchmark selection.")
    feasible = candidates[candidates["coverage_pct"] >= minimum_coverage_pct].copy()
    if feasible.empty:
        feasible = candidates.sort_values(["coverage_pct", "mae", "model"], ascending=[False, True, True]).copy()
        selected = feasible.iloc[0].to_dict()
        selected["selection_policy"] = "fallback_highest_coverage_then_mae"
    else:
        selected = feasible.sort_values(["mae", "model"]).iloc[0].to_dict()
        selected["selection_policy"] = "minimum_coverage_then_mae"
    selected["selection_split"] = split_name
    if reporting_level is not None:
        selected["selection_reporting_level"] = reporting_level
    selected["selection_metric"] = "mae"
    selected["minimum_coverage_pct"] = minimum_coverage_pct
    return selected


def add_rmae_column(
    metrics: pd.DataFrame,
    benchmark_model: str,
    group_keys: list[str] | None = None,
    output_col: str = "rmae_vs_official_naive",
) -> pd.DataFrame:
    # Keep the existing benchmark-run behavior unchanged: rMAE is computed from the
    # benchmark model already present in this metrics frame. Future ablation runs should
    # inherit the parent benchmark denominator through run metadata rather than silently
    # recomputing a new naive reference per child run.
    if group_keys is None:
        group_keys = ["dataset_split"]
    reference = metrics[metrics["model"] == benchmark_model][group_keys + ["mae"]].rename(columns={"mae": "benchmark_mae"})
    merged = metrics.merge(reference, on=group_keys, how="left")
    merged[output_col] = merged["mae"] / merged["benchmark_mae"]
    merged.loc[merged["benchmark_mae"].isna(), output_col] = np.nan
    merged.loc[merged["benchmark_mae"] == 0.0, output_col] = np.nan
    merged = merged.drop(columns=["benchmark_mae"])
    return add_rmae_alias_column(merged, source_col=output_col)


def add_rmae_alias_column(
    metrics: pd.DataFrame,
    *,
    source_col: str = "rmae_vs_official_naive",
    alias_col: str = "rmae",
) -> pd.DataFrame:
    if metrics.empty:
        return metrics.copy()
    if source_col not in metrics.columns:
        return metrics.copy()

    result = metrics.copy()
    if alias_col in result.columns:
        result[alias_col] = result[source_col]
        return result

    insert_at = result.columns.get_loc(source_col) + 1
    result.insert(insert_at, alias_col, result[source_col])
    return result


def _newey_west_variance(values: np.ndarray, max_lag: int) -> float:
    centered = values - values.mean()
    n_obs = centered.shape[0]
    gamma0 = float(np.dot(centered, centered) / n_obs)
    variance = gamma0
    for lag in range(1, min(max_lag, n_obs - 1) + 1):
        gamma = float(np.dot(centered[lag:], centered[:-lag]) / n_obs)
        weight = 1.0 - lag / (max_lag + 1.0)
        variance += 2.0 * weight * gamma
    return variance


def diebold_mariano_test(
    actual: pd.Series,
    forecast_a: pd.Series,
    forecast_b: pd.Series,
    loss: str = "absolute",
    hac_lag: int = 24,
) -> dict[str, object]:
    actual_values = actual.to_numpy(dtype=float)
    forecast_a_values = forecast_a.to_numpy(dtype=float)
    forecast_b_values = forecast_b.to_numpy(dtype=float)

    mask = np.isfinite(actual_values) & np.isfinite(forecast_a_values) & np.isfinite(forecast_b_values)
    actual_values = actual_values[mask]
    forecast_a_values = forecast_a_values[mask]
    forecast_b_values = forecast_b_values[mask]
    n_obs = int(actual_values.shape[0])
    if n_obs < 10:
        return {"n_obs": n_obs, "dm_stat": np.nan, "p_value": np.nan, "loss": loss, "hac_lag": hac_lag}

    if loss == "absolute":
        diff = np.abs(actual_values - forecast_a_values) - np.abs(actual_values - forecast_b_values)
    elif loss == "squared":
        diff = (actual_values - forecast_a_values) ** 2 - (actual_values - forecast_b_values) ** 2
    else:
        raise ValueError(f"Unsupported loss for Diebold-Mariano test: {loss}")

    variance = _newey_west_variance(diff, hac_lag)
    if variance <= 0.0:
        return {"n_obs": n_obs, "dm_stat": np.nan, "p_value": np.nan, "loss": loss, "hac_lag": hac_lag}

    dm_stat = float(diff.mean() / math.sqrt(variance / n_obs))
    p_value = float(2.0 * (1.0 - norm.cdf(abs(dm_stat))))
    return {"n_obs": n_obs, "dm_stat": dm_stat, "p_value": p_value, "loss": loss, "hac_lag": hac_lag}


def pairwise_dm_results(
    predictions: pd.DataFrame,
    benchmark_model: str,
    challenger_models: list[str],
    loss: str = "absolute",
    hac_lag: int = 24,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    base_cols = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true", "y_pred"]
    benchmark = predictions[predictions["model"] == benchmark_model][base_cols].rename(columns={"y_pred": "y_pred_benchmark"})
    for challenger_model in challenger_models:
        challenger = predictions[predictions["model"] == challenger_model][base_cols].rename(
            columns={"y_pred": "y_pred_challenger"}
        )
        merged = benchmark.merge(
            challenger,
            on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true"],
            how="inner",
        )
        if merged.empty:
            continue

        for split_name, split_group in merged.groupby("dataset_split", dropna=False):
            overall = diebold_mariano_test(
                actual=split_group["y_true"],
                forecast_a=split_group["y_pred_challenger"],
                forecast_b=split_group["y_pred_benchmark"],
                loss=loss,
                hac_lag=hac_lag,
            )
            overall.update(
                {
                    "dataset_split": split_name,
                    "challenger_model": challenger_model,
                    "benchmark_model": benchmark_model,
                    "lead_day": "overall",
                }
            )
            rows.append(overall)

            for lead_day, lead_group in split_group.groupby("lead_day", dropna=False):
                per_lead = diebold_mariano_test(
                    actual=lead_group["y_true"],
                    forecast_a=lead_group["y_pred_challenger"],
                    forecast_b=lead_group["y_pred_benchmark"],
                    loss=loss,
                    hac_lag=hac_lag,
                )
                per_lead.update(
                    {
                        "dataset_split": split_name,
                        "challenger_model": challenger_model,
                        "benchmark_model": benchmark_model,
                        "lead_day": int(lead_day),
                    }
                )
                rows.append(per_lead)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["dataset_split", "challenger_model", "lead_day"]).reset_index(drop=True)


def pairwise_dm_results_by_reporting_level(
    predictions: pd.DataFrame,
    benchmark_model: str,
    challenger_models: list[str],
    loss: str = "absolute",
    hac_lag: int = 24,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    base_cols = ["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true", "y_pred"]
    benchmark = predictions[predictions["model"] == benchmark_model][base_cols].rename(columns={"y_pred": "y_pred_benchmark"})
    for challenger_model in challenger_models:
        challenger = predictions[predictions["model"] == challenger_model][base_cols].rename(
            columns={"y_pred": "y_pred_challenger"}
        )
        merged = benchmark.merge(
            challenger,
            on=["dataset_split", "forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_true"],
            how="inner",
        )
        if merged.empty:
            continue

        for spec in reporting_level_specs():
            reporting_subset = merged[merged["lead_day"].isin(spec.lead_days)].copy()
            if reporting_subset.empty:
                continue
            reporting_cols = spec.to_columns()
            for split_name, split_group in reporting_subset.groupby("dataset_split", dropna=False):
                result = diebold_mariano_test(
                    actual=split_group["y_true"],
                    forecast_a=split_group["y_pred_challenger"],
                    forecast_b=split_group["y_pred_benchmark"],
                    loss=loss,
                    hac_lag=hac_lag,
                )
                result.update(
                    {
                        "dataset_split": split_name,
                        "challenger_model": challenger_model,
                        "benchmark_model": benchmark_model,
                    }
                )
                result.update(reporting_cols)
                rows.append(result)

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["dataset_split", "reporting_level_sort_order", "challenger_model"])
        .reset_index(drop=True)
    )
