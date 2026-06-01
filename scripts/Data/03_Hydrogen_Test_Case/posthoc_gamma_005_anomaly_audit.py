from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _frame_to_markdown(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body: list[str] = []
    for _, row in frame.iterrows():
        values = []
        for column in columns:
            value = row[column]
            if pd.isna(value):
                values.append("")
            elif isinstance(value, (float, np.floating)):
                values.append(f"{float(value):.6f}")
            else:
                values.append(str(value))
        body.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *body])


def _load_gamma_frame(path: Path, gamma: float, gamma_column: str = "cvar_gamma") -> pd.DataFrame:
    frame = pd.read_csv(path)
    values = pd.to_numeric(frame[gamma_column], errors="coerce")
    return frame.loc[np.isclose(values, float(gamma))].copy().reset_index(drop=True)


def _weekly_component_frame(daily: pd.DataFrame) -> pd.DataFrame:
    ordered = daily.sort_values(["week_id", "delivery_day"]).copy()
    grouped = ordered.groupby("week_id", sort=False)
    rows: list[dict[str, Any]] = []
    for week_id, group in grouped:
        last = group.iloc[-1]
        rows.append(
            {
                "week_id": str(week_id),
                "hydrogen_revenue_eur": float(pd.to_numeric(group["hydrogen_revenue"], errors="coerce").sum()),
                "da_cost_eur": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum()),
                "unused_penalty_eur": float(pd.to_numeric(group["unused_energy_penalty"], errors="coerce").sum()),
                "emergency_import_cost_eur": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "emergency_import_mwh_component": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "terminal_inventory_correction_eur": float(pd.to_numeric(group["terminal_inventory_correction"], errors="coerce").sum()),
                "hydrogen_sold_or_compressed_kg_component": float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                "rejected_energy_mwh_component": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "unused_cleared_energy_mwh_component": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "storage_min_kg_component": float(pd.to_numeric(group["storage_min_kg"], errors="coerce").min()),
                "storage_max_kg_component": float(pd.to_numeric(group["storage_max_kg"], errors="coerce").max()),
                "weekly_target_progress_ratio": (
                    float(pd.to_numeric(pd.Series([last["cumulative_after_kg"]]), errors="coerce").iloc[0])
                    / float(pd.to_numeric(pd.Series([last["weekly_target_kg"]]), errors="coerce").iloc[0])
                    if float(pd.to_numeric(pd.Series([last["weekly_target_kg"]]), errors="coerce").iloc[0]) > 0.0
                    else np.nan
                ),
                "weekly_target_remaining_end_kg": float(
                    max(
                        0.0,
                        float(pd.to_numeric(pd.Series([last["weekly_target_kg"]]), errors="coerce").iloc[0])
                        - float(pd.to_numeric(pd.Series([last["cumulative_after_kg"]]), errors="coerce").iloc[0]),
                    )
                ),
                "month_id_anchor": str(last.get("month_id", "")),
            }
        )
    return pd.DataFrame(rows)


def _monthly_component_frame(daily: pd.DataFrame) -> pd.DataFrame:
    ordered = daily.copy()
    ordered["month_id"] = pd.to_datetime(ordered["delivery_day"], errors="coerce").dt.strftime("%Y-%m")
    ordered = ordered.sort_values(["month_id", "delivery_day"]).copy()
    weekly_component = _weekly_component_frame(daily)
    weekly_progress_by_month = (
        weekly_component.groupby("month_id_anchor", sort=False)
        .agg(
            mean_weekly_target_progress_ratio=("weekly_target_progress_ratio", "mean"),
            max_weekly_target_progress_ratio=("weekly_target_progress_ratio", "max"),
            min_weekly_target_progress_ratio=("weekly_target_progress_ratio", "min"),
            weeks_in_month=("week_id", "nunique"),
        )
        .reset_index()
        .rename(columns={"month_id_anchor": "month_id"})
    )
    grouped = ordered.groupby("month_id", sort=False)
    rows: list[dict[str, Any]] = []
    for month_id, group in grouped:
        rows.append(
            {
                "month_id": str(month_id),
                "hydrogen_revenue_eur": float(pd.to_numeric(group["hydrogen_revenue"], errors="coerce").sum()),
                "da_cost_eur": float(pd.to_numeric(group["da_settlement_cost"], errors="coerce").sum()),
                "unused_penalty_eur": float(pd.to_numeric(group["unused_energy_penalty"], errors="coerce").sum()),
                "emergency_import_cost_eur": float(pd.to_numeric(group["emergency_import_cost"], errors="coerce").sum()),
                "emergency_import_mwh_component": float(pd.to_numeric(group["emergency_import_mwh"], errors="coerce").sum()),
                "terminal_inventory_correction_eur": float(pd.to_numeric(group["terminal_inventory_correction"], errors="coerce").sum()),
                "hydrogen_sold_or_compressed_kg_component": float(pd.to_numeric(group["hydrogen_sold_or_compressed_kg"], errors="coerce").sum()),
                "rejected_energy_mwh_component": float(pd.to_numeric(group["rejected_energy_mwh"], errors="coerce").sum()),
                "unused_cleared_energy_mwh_component": float(pd.to_numeric(group["unused_cleared_energy_mwh"], errors="coerce").sum()),
                "storage_min_kg_component": float(pd.to_numeric(group["storage_min_kg"], errors="coerce").min()),
                "storage_max_kg_component": float(pd.to_numeric(group["storage_max_kg"], errors="coerce").max()),
            }
        )
    monthly = pd.DataFrame(rows)
    return monthly.merge(weekly_progress_by_month, on="month_id", how="left")


def _rename_with_gamma(frame: pd.DataFrame, gamma_label: str, key: str) -> pd.DataFrame:
    renamed = frame.copy()
    rename_map = {column: f"{column}_{gamma_label}" for column in renamed.columns if column != key}
    return renamed.rename(columns=rename_map)


def _profit_driver_fields(prefix_005: str, prefix_cmp: str) -> dict[str, str]:
    return {
        "lower_hydrogen_revenue": f"hydrogen_revenue_eur_{prefix_005}",
        "higher_da_cost": f"da_cost_eur_{prefix_005}",
        "higher_emergency_cost": f"emergency_import_cost_eur_{prefix_005}",
        "higher_unused_penalty": f"unused_penalty_eur_{prefix_005}",
        "terminal_inventory_change": f"terminal_inventory_correction_eur_{prefix_005}",
        "_cmp_revenue": f"hydrogen_revenue_eur_{prefix_cmp}",
        "_cmp_da_cost": f"da_cost_eur_{prefix_cmp}",
        "_cmp_emergency_cost": f"emergency_import_cost_eur_{prefix_cmp}",
        "_cmp_unused_penalty": f"unused_penalty_eur_{prefix_cmp}",
        "_cmp_terminal": f"terminal_inventory_correction_eur_{prefix_cmp}",
    }


def _dominant_driver(row: pd.Series, prefix_005: str, prefix_cmp: str) -> str:
    drivers = _profit_driver_fields(prefix_005, prefix_cmp)
    contributions = {
        "lower_production_revenue": float(row[drivers["lower_hydrogen_revenue"]] - row[drivers["_cmp_revenue"]]),
        "higher_DA_cost": float(-(row[drivers["higher_da_cost"]] - row[drivers["_cmp_da_cost"]])),
        "higher_emergency_import_cost": float(-(row[drivers["higher_emergency_cost"]] - row[drivers["_cmp_emergency_cost"]])),
        "higher_unused_energy_penalty": float(-(row[drivers["higher_unused_penalty"]] - row[drivers["_cmp_unused_penalty"]])),
        "terminal_inventory_effect": float(row[drivers["terminal_inventory_change"]] - row[drivers["_cmp_terminal"]]),
    }
    return min(contributions.items(), key=lambda item: item[1])[0]


def _cvar_consistency_checks(
    baseline_run_dir: Path,
    extension_run_dir: Path,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sources = [
        ("0.0", baseline_run_dir, 0.0),
        ("0.05", extension_run_dir, 0.05),
        ("0.25", baseline_run_dir, 0.25),
    ]
    for label, run_dir, gamma in sources:
        daily = _load_gamma_frame(run_dir / "daily_metrics.csv", gamma)
        weekly = _load_gamma_frame(run_dir / "weekly_metrics.csv", gamma)
        monthly = _load_gamma_frame(run_dir / "monthly_metrics.csv", gamma)
        annual = pd.read_csv(run_dir / "annual_metrics_by_gamma.csv")
        annual_row = annual.loc[np.isclose(pd.to_numeric(annual["gamma"], errors="coerce"), float(gamma))].iloc[0]
        annual_value = float(pd.to_numeric(pd.Series([annual_row["annual_cvar_tail_profit"]]), errors="coerce").iloc[0])
        rows.append(
            {
                "gamma": float(gamma),
                "annual_cvar_tail_profit": annual_value,
                "sum_daily_cvar_tail_profit": float(pd.to_numeric(daily["cvar_tail_profit"], errors="coerce").sum()),
                "sum_weekly_cvar_tail_profit": float(pd.to_numeric(weekly["cvar_tail_profit"], errors="coerce").sum()),
                "sum_monthly_cvar_tail_profit": float(pd.to_numeric(monthly["cvar_tail_profit"], errors="coerce").sum()),
            }
        )
    frame = pd.DataFrame(rows)
    for column in ["sum_daily_cvar_tail_profit", "sum_weekly_cvar_tail_profit", "sum_monthly_cvar_tail_profit"]:
        frame[f"{column}_matches_annual"] = np.isclose(
            pd.to_numeric(frame["annual_cvar_tail_profit"], errors="coerce"),
            pd.to_numeric(frame[column], errors="coerce"),
            atol=1e-6,
        )
    return frame


def build_anomaly_audit(baseline_run_dir: Path, extension_run_dir: Path) -> dict[str, Path]:
    baseline_weekly = pd.read_csv(baseline_run_dir / "weekly_metrics.csv")
    baseline_monthly = pd.read_csv(baseline_run_dir / "monthly_metrics.csv")
    baseline_daily = pd.read_csv(baseline_run_dir / "daily_metrics.csv")
    extension_weekly = pd.read_csv(extension_run_dir / "weekly_metrics.csv")
    extension_monthly = pd.read_csv(extension_run_dir / "monthly_metrics.csv")
    extension_daily = pd.read_csv(extension_run_dir / "daily_metrics.csv")
    true_pf_weekly = pd.read_csv(baseline_run_dir / "true_perfect_foresight_weekly_metrics.csv")
    true_pf_monthly = pd.read_csv(baseline_run_dir / "true_perfect_foresight_monthly_metrics.csv")
    baseline_annual = pd.read_csv(baseline_run_dir / "annual_metrics_by_gamma_with_true_pf.csv")
    extension_annual = pd.read_csv(extension_run_dir / "annual_metrics_by_gamma_with_true_pf.csv")

    weekly_0 = _load_gamma_frame(baseline_run_dir / "weekly_metrics.csv", 0.0)
    weekly_025 = _load_gamma_frame(baseline_run_dir / "weekly_metrics.csv", 0.25)
    weekly_005 = _load_gamma_frame(extension_run_dir / "weekly_metrics.csv", 0.05)
    monthly_0 = _load_gamma_frame(baseline_run_dir / "monthly_metrics.csv", 0.0)
    monthly_025 = _load_gamma_frame(baseline_run_dir / "monthly_metrics.csv", 0.25)
    monthly_005 = _load_gamma_frame(extension_run_dir / "monthly_metrics.csv", 0.05)
    daily_0 = _load_gamma_frame(baseline_run_dir / "daily_metrics.csv", 0.0)
    daily_025 = _load_gamma_frame(baseline_run_dir / "daily_metrics.csv", 0.25)
    daily_005 = _load_gamma_frame(extension_run_dir / "daily_metrics.csv", 0.05)

    weekly_key = "week_id"
    monthly_key = "month_id"
    weekly_metrics_cols = [
        weekly_key,
        "week_label",
        "week_start",
        "week_end",
        "included_delivery_day_count",
        "is_partial_week",
        "expected_adjusted_profit",
        "realised_adjusted_profit",
        "cvar_tail_profit",
        "worst_scenario_profit",
        "emergency_import_mwh",
        "emergency_import_cost",
        "rejected_energy_mwh",
        "unused_cleared_energy_mwh",
        "storage_min_kg",
        "storage_max_kg",
        "weekly_target_met",
        "hydrogen_sold_or_compressed_kg",
        "terminal_inventory_correction",
    ]
    monthly_metrics_cols = [
        monthly_key,
        "month_start",
        "month_end",
        "number_of_delivery_days",
        "expected_adjusted_profit",
        "realised_adjusted_profit",
        "cvar_tail_profit",
        "worst_scenario_profit",
        "emergency_import_mwh",
        "emergency_import_cost",
        "rejected_energy_mwh",
        "unused_cleared_energy_mwh",
        "storage_min_kg",
        "storage_max_kg",
        "weekly_target_met",
        "hydrogen_sold_or_compressed_kg",
        "terminal_inventory_correction",
    ]

    weekly_components_0 = _weekly_component_frame(daily_0)
    weekly_components_005 = _weekly_component_frame(daily_005)
    weekly_components_025 = _weekly_component_frame(daily_025)
    monthly_components_0 = _monthly_component_frame(daily_0)
    monthly_components_005 = _monthly_component_frame(daily_005)
    monthly_components_025 = _monthly_component_frame(daily_025)

    weekly_pf = true_pf_weekly[["week_id", "realised_adjusted_profit"]].rename(columns={"realised_adjusted_profit": "true_pf_profit_week"})
    monthly_pf = true_pf_monthly[["month_id", "realised_adjusted_profit"]].rename(columns={"realised_adjusted_profit": "true_pf_profit_month"})

    weekly = (
        _rename_with_gamma(weekly_0[weekly_metrics_cols], "g0", weekly_key)
        .merge(_rename_with_gamma(weekly_005[weekly_metrics_cols], "g005", weekly_key), on=weekly_key, how="outer")
        .merge(_rename_with_gamma(weekly_025[weekly_metrics_cols], "g025", weekly_key), on=weekly_key, how="outer")
        .merge(_rename_with_gamma(weekly_components_0, "g0", weekly_key), on=weekly_key, how="left")
        .merge(_rename_with_gamma(weekly_components_005, "g005", weekly_key), on=weekly_key, how="left")
        .merge(_rename_with_gamma(weekly_components_025, "g025", weekly_key), on=weekly_key, how="left")
        .merge(weekly_pf, on=weekly_key, how="left")
    )
    weekly["true_pf_regret_g0"] = pd.to_numeric(weekly["true_pf_profit_week"], errors="coerce") - pd.to_numeric(weekly["realised_adjusted_profit_g0"], errors="coerce")
    weekly["true_pf_regret_g005"] = pd.to_numeric(weekly["true_pf_profit_week"], errors="coerce") - pd.to_numeric(weekly["realised_adjusted_profit_g005"], errors="coerce")
    weekly["true_pf_regret_g025"] = pd.to_numeric(weekly["true_pf_profit_week"], errors="coerce") - pd.to_numeric(weekly["realised_adjusted_profit_g025"], errors="coerce")
    weekly["delta_realised_profit_g005_vs_g0"] = pd.to_numeric(weekly["realised_adjusted_profit_g005"], errors="coerce") - pd.to_numeric(weekly["realised_adjusted_profit_g0"], errors="coerce")
    weekly["delta_realised_profit_g005_vs_g025"] = pd.to_numeric(weekly["realised_adjusted_profit_g005"], errors="coerce") - pd.to_numeric(weekly["realised_adjusted_profit_g025"], errors="coerce")
    weekly["delta_expected_profit_g005_vs_g0"] = pd.to_numeric(weekly["expected_adjusted_profit_g005"], errors="coerce") - pd.to_numeric(weekly["expected_adjusted_profit_g0"], errors="coerce")
    weekly["delta_cvar_tail_profit_g005_vs_g0"] = pd.to_numeric(weekly["cvar_tail_profit_g005"], errors="coerce") - pd.to_numeric(weekly["cvar_tail_profit_g0"], errors="coerce")
    weekly["delta_worst_scenario_profit_g005_vs_g0"] = pd.to_numeric(weekly["worst_scenario_profit_g005"], errors="coerce") - pd.to_numeric(weekly["worst_scenario_profit_g0"], errors="coerce")
    weekly["dominant_driver_g005_vs_g0"] = weekly.apply(lambda row: _dominant_driver(row, "g005", "g0"), axis=1)
    weekly["dominant_driver_g005_vs_g025"] = weekly.apply(lambda row: _dominant_driver(row, "g005", "g025"), axis=1)

    monthly = (
        _rename_with_gamma(monthly_0[monthly_metrics_cols], "g0", monthly_key)
        .merge(_rename_with_gamma(monthly_005[monthly_metrics_cols], "g005", monthly_key), on=monthly_key, how="outer")
        .merge(_rename_with_gamma(monthly_025[monthly_metrics_cols], "g025", monthly_key), on=monthly_key, how="outer")
        .merge(_rename_with_gamma(monthly_components_0, "g0", monthly_key), on=monthly_key, how="left")
        .merge(_rename_with_gamma(monthly_components_005, "g005", monthly_key), on=monthly_key, how="left")
        .merge(_rename_with_gamma(monthly_components_025, "g025", monthly_key), on=monthly_key, how="left")
        .merge(monthly_pf, on=monthly_key, how="left")
    )
    monthly["true_pf_regret_g0"] = pd.to_numeric(monthly["true_pf_profit_month"], errors="coerce") - pd.to_numeric(monthly["realised_adjusted_profit_g0"], errors="coerce")
    monthly["true_pf_regret_g005"] = pd.to_numeric(monthly["true_pf_profit_month"], errors="coerce") - pd.to_numeric(monthly["realised_adjusted_profit_g005"], errors="coerce")
    monthly["true_pf_regret_g025"] = pd.to_numeric(monthly["true_pf_profit_month"], errors="coerce") - pd.to_numeric(monthly["realised_adjusted_profit_g025"], errors="coerce")
    monthly["delta_realised_profit_g005_vs_g0"] = pd.to_numeric(monthly["realised_adjusted_profit_g005"], errors="coerce") - pd.to_numeric(monthly["realised_adjusted_profit_g0"], errors="coerce")
    monthly["delta_realised_profit_g005_vs_g025"] = pd.to_numeric(monthly["realised_adjusted_profit_g005"], errors="coerce") - pd.to_numeric(monthly["realised_adjusted_profit_g025"], errors="coerce")
    monthly["delta_expected_profit_g005_vs_g0"] = pd.to_numeric(monthly["expected_adjusted_profit_g005"], errors="coerce") - pd.to_numeric(monthly["expected_adjusted_profit_g0"], errors="coerce")
    monthly["delta_cvar_tail_profit_g005_vs_g0"] = pd.to_numeric(monthly["cvar_tail_profit_g005"], errors="coerce") - pd.to_numeric(monthly["cvar_tail_profit_g0"], errors="coerce")
    monthly["delta_worst_scenario_profit_g005_vs_g0"] = pd.to_numeric(monthly["worst_scenario_profit_g005"], errors="coerce") - pd.to_numeric(monthly["worst_scenario_profit_g0"], errors="coerce")
    monthly["dominant_driver_g005_vs_g0"] = monthly.apply(lambda row: _dominant_driver(row, "g005", "g0"), axis=1)
    monthly["dominant_driver_g005_vs_g025"] = monthly.apply(lambda row: _dominant_driver(row, "g005", "g025"), axis=1)

    weekly = weekly.sort_values("delta_realised_profit_g005_vs_g0").reset_index(drop=True)
    monthly = monthly.sort_values("delta_realised_profit_g005_vs_g0").reset_index(drop=True)

    cvar_consistency = _cvar_consistency_checks(baseline_run_dir, extension_run_dir)
    same_included_dates = (
        set(daily_0["delivery_day"].astype(str))
        == set(daily_005["delivery_day"].astype(str))
        == set(daily_025["delivery_day"].astype(str))
    )
    same_target_policy = (
        sorted(daily_0["target_accounting_policy"].astype(str).unique().tolist())
        == sorted(daily_005["target_accounting_policy"].astype(str).unique().tolist())
        == sorted(daily_025["target_accounting_policy"].astype(str).unique().tolist())
    )
    same_emergency_price = (
        sorted(pd.to_numeric(daily_0["emergency_import_price_eur_per_mwh"], errors="coerce").dropna().unique().tolist())
        == sorted(pd.to_numeric(daily_005["emergency_import_price_eur_per_mwh"], errors="coerce").dropna().unique().tolist())
        == sorted(pd.to_numeric(daily_025["emergency_import_price_eur_per_mwh"], errors="coerce").dropna().unique().tolist())
    )
    true_pf_values = [
        float(pd.to_numeric(baseline_annual.loc[np.isclose(pd.to_numeric(baseline_annual["gamma"], errors="coerce"), gamma), "true_pf_annual_profit"], errors="coerce").iloc[0])
        for gamma in [0.0, 0.25]
    ] + [
        float(pd.to_numeric(extension_annual.loc[np.isclose(pd.to_numeric(extension_annual["gamma"], errors="coerce"), 0.05), "true_pf_annual_profit"], errors="coerce").iloc[0])
    ]
    same_true_pf_reference = max(true_pf_values) - min(true_pf_values) <= 1e-6

    top5_weeks = weekly.head(5)[
        [
            "week_label_g005",
            "delta_realised_profit_g005_vs_g0",
            "delta_expected_profit_g005_vs_g0",
            "delta_cvar_tail_profit_g005_vs_g0",
            "delta_worst_scenario_profit_g005_vs_g0",
            "true_pf_regret_g005",
            "dominant_driver_g005_vs_g0",
            "emergency_import_mwh_g005",
            "hydrogen_revenue_eur_g005",
            "da_cost_eur_g005",
            "terminal_inventory_correction_eur_g005",
        ]
    ].copy()

    summary_lines = [
        "# Gamma 0.05 Anomaly Summary",
        "",
        "## Top 5 Weeks Causing Gamma 0.05 Underperformance vs Gamma 0",
        "",
        _frame_to_markdown(top5_weeks),
        "",
        "## Conclusions",
        "",
        f"1. Largest weekly underperformance is concentrated in the weeks listed above; the worst months are {', '.join(monthly.head(3)['month_id'].astype(str).tolist())}.",
        "2. The attribution columns show whether the drag came mainly from lower hydrogen revenue, higher DA cost, higher emergency cost, higher unused-energy penalty, or terminal inventory effects.",
        f"3. Annual CVaR tail profit is mechanically consistent across runs: all daily/weekly/monthly sums match the reported annual value = {bool(cvar_consistency[['sum_daily_cvar_tail_profit_matches_annual','sum_weekly_cvar_tail_profit_matches_annual','sum_monthly_cvar_tail_profit_matches_annual']].all().all())}.",
        f"4. Included dates identical={same_included_dates}; target accounting identical={same_target_policy}; true-PF reference identical={same_true_pf_reference}; emergency import price identical={same_emergency_price}.",
    ]
    dominated = (
        float(pd.to_numeric(extension_annual["annual_realised_adjusted_profit"], errors="coerce").iloc[0])
        < float(pd.to_numeric(baseline_annual.loc[np.isclose(pd.to_numeric(baseline_annual['gamma'], errors='coerce'), 0.0), 'annual_realised_adjusted_profit'], errors='coerce').iloc[0])
        and float(pd.to_numeric(extension_annual["annual_cvar_tail_profit"], errors="coerce").iloc[0])
        < float(pd.to_numeric(baseline_annual.loc[np.isclose(pd.to_numeric(baseline_annual['gamma'], errors='coerce'), 0.0), 'annual_cvar_tail_profit'], errors='coerce').iloc[0])
    )
    summary_lines.append(
        "5. Gamma=0.05 appears genuinely dominated rather than broken by output aggregation."
        if dominated and same_included_dates and same_target_policy and same_true_pf_reference and same_emergency_price and bool(cvar_consistency[['sum_daily_cvar_tail_profit_matches_annual','sum_weekly_cvar_tail_profit_matches_annual','sum_monthly_cvar_tail_profit_matches_annual']].all().all())
        else "5. The anomaly needs caution; at least one consistency check failed or the dominance pattern is not clean."
    )
    summary_lines.extend(
        [
            "",
            "## CVaR Consistency",
            "",
            _frame_to_markdown(cvar_consistency),
        ]
    )

    weekly_path = extension_run_dir / "gamma_005_anomaly_by_week.csv"
    monthly_path = extension_run_dir / "gamma_005_anomaly_by_month.csv"
    summary_path = extension_run_dir / "gamma_005_anomaly_summary.md"
    weekly.to_csv(weekly_path, index=False)
    monthly.to_csv(monthly_path, index=False)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return {"weekly": weekly_path, "monthly": monthly_path, "summary": summary_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a post-hoc gamma=0.05 anomaly audit from existing outputs only.")
    parser.add_argument("--baseline-run-dir", required=True)
    parser.add_argument("--extension-run-dir", required=True)
    args = parser.parse_args()
    paths = build_anomaly_audit(Path(args.baseline_run_dir), Path(args.extension_run_dir))
    for name, path in paths.items():
        print(f"{name}={path}")


if __name__ == "__main__":
    main()
