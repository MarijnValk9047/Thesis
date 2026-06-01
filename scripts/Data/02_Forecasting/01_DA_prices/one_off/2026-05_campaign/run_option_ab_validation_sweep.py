from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import load_candidate_predictions
from hourly_da.core.scenario_generation import (
    build_residual_daily_profiles,
    build_residual_period_table,
    choose_official_naive_candidate,
    choose_target_evaluation_slice,
    compute_candidate_selection_summary,
    discover_scenario_candidate_sources,
    generate_scenario_bundle,
    score_scenario_variants,
    select_scenario_candidates,
    validate_scenario_set,
)


TUNING_CALIBRATION_START = pd.Timestamp("2023-10-01")
TUNING_CALIBRATION_END = pd.Timestamp("2024-03-31")
TUNING_SELECTION_START = pd.Timestamp("2024-04-01")
TUNING_SELECTION_END = pd.Timestamp("2024-09-30")

N_RAW_SCENARIOS = 30
N_FINAL_SCENARIOS = 15
RANDOM_SEED = 42

OPTION_A_GRID: tuple[tuple[float, float], ...] = (
    (0.10, 0.00),
    (0.10, 0.05),
    (0.10, 0.10),
    (0.20, 0.00),
    (0.20, 0.05),
    (0.20, 0.10),
    (0.30, 0.00),
    (0.30, 0.05),
    (0.30, 0.10),
    (0.40, 0.00),
    (0.40, 0.05),
    (0.40, 0.10),
)
OPTION_B_STRESS_GRID: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.25)


def _output_dir(output_root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = Path(output_root) / "option_ab_sweeps" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _filter_delivery_range(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    delivery_day = pd.to_datetime(frame["delivery_day"], errors="coerce")
    return frame[(delivery_day >= start) & (delivery_day <= end)].copy()


def _tuning_frame(period_residuals: pd.DataFrame, candidate_keys: list[str]) -> pd.DataFrame:
    validation = period_residuals[
        (period_residuals["dataset_split"].astype(str) == "validation")
        & (period_residuals["candidate_key"].astype(str).isin(candidate_keys))
    ].copy()
    calibration = _filter_delivery_range(validation, TUNING_CALIBRATION_START, TUNING_CALIBRATION_END).copy()
    selection = _filter_delivery_range(validation, TUNING_SELECTION_START, TUNING_SELECTION_END).copy()
    calibration["dataset_split"] = "ab_tuning_calibration"
    selection["dataset_split"] = "ab_tuning_selection"
    return pd.concat([calibration, selection], ignore_index=True)


def _single_variant_plan(
    *,
    scenario_variant: str,
    use_option_a: bool,
    use_option_b: bool,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario_variant": scenario_variant,
                "use_option_a": bool(use_option_a),
                "use_option_b": bool(use_option_b),
                "use_option_c": False,
            }
        ]
    )


def _evaluate_variant(
    tuning_periods: pd.DataFrame,
    daily_profiles: pd.DataFrame,
    *,
    config: HourlyDAPipelineConfig,
    selected_candidate_keys: list[str],
    scenario_variant: str,
    use_option_a: bool,
    use_option_b: bool,
    normal_share: float,
    positive_tail_share: float,
    negative_tail_share: float,
    stress_share: float,
    scenario_run_id: str,
) -> pd.DataFrame:
    bundle = generate_scenario_bundle(
        tuning_periods,
        daily_profiles,
        config=config,
        calibration_split="ab_tuning_calibration",
        target_split="ab_tuning_selection",
        selected_candidate_keys=selected_candidate_keys,
        variant_plan=_single_variant_plan(
            scenario_variant=scenario_variant,
            use_option_a=use_option_a,
            use_option_b=use_option_b,
        ),
        scenario_run_id=scenario_run_id,
        random_seed=RANDOM_SEED,
        n_raw_scenarios=N_RAW_SCENARIOS,
        n_final_scenarios=N_FINAL_SCENARIOS,
        normal_share=float(normal_share),
        positive_tail_share=float(positive_tail_share),
        negative_tail_share=float(negative_tail_share),
        stress_share=float(stress_share),
    )
    validation_bundle = validate_scenario_set(bundle["final_scenarios"], config=config)
    scored = score_scenario_variants(validation_bundle["summary"])
    return scored[scored["scenario_variant"].astype(str) == str(scenario_variant)].copy().reset_index(drop=True)


def _aggregate_summary(frame: pd.DataFrame, *, stage_name: str, scenario_variant: str) -> dict[str, Any]:
    return {
        "stage_name": stage_name,
        "scenario_variant": scenario_variant,
        "mean_scenario_score": float(frame["scenario_score"].mean()),
        "mean_minmax_coverage": float(frame["minmax_coverage"].mean()),
        "mean_p10_p90_coverage": float(frame["p10_p90_coverage"].mean()),
        "mean_p05_p95_coverage": float(frame["p05_p95_coverage"].mean()),
        "mean_high_tail_miss_rate": float(frame["high_tail_miss_rate"].mean()),
        "mean_low_tail_miss_rate": float(frame["low_tail_miss_rate"].mean()),
        "mean_average_p10_p90_width": float(frame["average_p10_p90_width"].mean()),
        "mean_daily_max_coverage_p10_p90": float(frame["daily_max_coverage_p10_p90"].mean()),
        "mean_top3_expensive_recall": float(frame["scenario_top3_expensive_recall"].mean()),
        "mean_top3_cheap_recall": float(frame["scenario_top3_cheap_recall"].mean()),
    }


def _delta_against_baseline(candidate_results: pd.DataFrame, baseline_rows: pd.DataFrame) -> pd.DataFrame:
    merged = candidate_results.merge(
        baseline_rows[
            [
                "candidate_key",
                "scenario_score",
                "minmax_coverage",
                "p10_p90_coverage",
                "p05_p95_coverage",
                "high_tail_miss_rate",
                "low_tail_miss_rate",
                "average_p10_p90_width",
                "daily_max_coverage_p10_p90",
                "scenario_top3_expensive_recall",
                "scenario_top3_cheap_recall",
            ]
        ].rename(
            columns={
                "scenario_score": "baseline_scenario_score",
                "minmax_coverage": "baseline_minmax_coverage",
                "p10_p90_coverage": "baseline_p10_p90_coverage",
                "p05_p95_coverage": "baseline_p05_p95_coverage",
                "high_tail_miss_rate": "baseline_high_tail_miss_rate",
                "low_tail_miss_rate": "baseline_low_tail_miss_rate",
                "average_p10_p90_width": "baseline_average_p10_p90_width",
                "daily_max_coverage_p10_p90": "baseline_daily_max_coverage_p10_p90",
                "scenario_top3_expensive_recall": "baseline_top3_expensive_recall",
                "scenario_top3_cheap_recall": "baseline_top3_cheap_recall",
            }
        ),
        on="candidate_key",
        how="left",
    )
    merged["scenario_score_gain"] = merged["scenario_score"] - merged["baseline_scenario_score"]
    merged["high_tail_miss_reduction"] = merged["baseline_high_tail_miss_rate"] - merged["high_tail_miss_rate"]
    merged["p10_p90_coverage_gain"] = merged["p10_p90_coverage"] - merged["baseline_p10_p90_coverage"]
    merged["width_change"] = merged["average_p10_p90_width"] - merged["baseline_average_p10_p90_width"]
    return merged


def _choose_best_setting(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows).sort_values(
        [
            "mean_scenario_score",
            "mean_high_tail_miss_rate",
            "mean_p10_p90_coverage",
            "mean_average_p10_p90_width",
        ],
        ascending=[False, True, False, True],
    ).reset_index(drop=True)
    return frame.iloc[0].to_dict()


def main() -> None:
    config = HourlyDAPipelineConfig(
        input_csv=REPO_ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv",
        raw_root=REPO_ROOT / "data/00_Raw/DA_Prices",
        cleaned_feature_root=REPO_ROOT / "data/01_cleaned",
        output_root=REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da",
    )
    out_dir = _output_dir(config.output_root)

    discovery = discover_scenario_candidate_sources(config.output_root)
    candidate_frame = discovery["candidate_frame"].copy()
    candidate_predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=config)

    official_naive_info = choose_official_naive_candidate(candidate_predictions)
    evaluation_choice = choose_target_evaluation_slice(candidate_predictions, preferred_splits=("test", "validation"), preferred_lead_day=0)
    candidate_selection_summary = compute_candidate_selection_summary(
        candidate_predictions,
        selection_split=str(evaluation_choice["dataset_split"]),
        selection_lead_day=int(evaluation_choice["lead_day"]),
        official_naive_candidate_key=str(official_naive_info["selected"]["candidate_key"]),
        k_top_hours=3,
    )
    selection_bundle = select_scenario_candidates(candidate_selection_summary)
    selected_candidate_keys = [str(value) for value in selection_bundle["selected_candidate_keys"]]

    residual_periods = build_residual_period_table(candidate_predictions, config=config, lead_day=0)
    tuning_periods = _tuning_frame(residual_periods, selected_candidate_keys)
    daily_profiles = build_residual_daily_profiles(tuning_periods)

    baseline_rows = _evaluate_variant(
        tuning_periods,
        daily_profiles,
        config=config,
        selected_candidate_keys=selected_candidate_keys,
        scenario_variant="base",
        use_option_a=False,
        use_option_b=False,
        normal_share=1.0,
        positive_tail_share=0.0,
        negative_tail_share=0.0,
        stress_share=0.0,
        scenario_run_id="ab_sweep_base",
    )

    option_a_rows: list[dict[str, Any]] = []
    option_a_candidate_rows: list[pd.DataFrame] = []
    for positive_tail_share, negative_tail_share in OPTION_A_GRID:
        normal_share = 1.0 - float(positive_tail_share) - float(negative_tail_share)
        scored = _evaluate_variant(
            tuning_periods,
            daily_profiles,
            config=config,
            selected_candidate_keys=selected_candidate_keys,
            scenario_variant="base_plus_a",
            use_option_a=True,
            use_option_b=False,
            normal_share=normal_share,
            positive_tail_share=float(positive_tail_share),
            negative_tail_share=float(negative_tail_share),
            stress_share=0.0,
            scenario_run_id=f"ab_sweep_option_a_{positive_tail_share}_{negative_tail_share}",
        )
        with_delta = _delta_against_baseline(scored, baseline_rows)
        with_delta["positive_tail_share"] = float(positive_tail_share)
        with_delta["negative_tail_share"] = float(negative_tail_share)
        with_delta["normal_share"] = float(normal_share)
        option_a_candidate_rows.append(with_delta)
        summary = _aggregate_summary(with_delta, stage_name="option_a", scenario_variant="base_plus_a")
        summary.update(
            {
                "positive_tail_share": float(positive_tail_share),
                "negative_tail_share": float(negative_tail_share),
                "normal_share": float(normal_share),
                "mean_scenario_score_gain": float(with_delta["scenario_score_gain"].mean()),
                "mean_high_tail_miss_reduction": float(with_delta["high_tail_miss_reduction"].mean()),
                "mean_p10_p90_coverage_gain": float(with_delta["p10_p90_coverage_gain"].mean()),
                "mean_width_change": float(with_delta["width_change"].mean()),
            }
        )
        option_a_rows.append(summary)

    option_a_best = _choose_best_setting(option_a_rows)

    option_b_rows: list[dict[str, Any]] = []
    option_b_candidate_rows: list[pd.DataFrame] = []
    for stress_share in OPTION_B_STRESS_GRID:
        scored = _evaluate_variant(
            tuning_periods,
            daily_profiles,
            config=config,
            selected_candidate_keys=selected_candidate_keys,
            scenario_variant="base_plus_b",
            use_option_a=False,
            use_option_b=True,
            normal_share=float(option_a_best["normal_share"]),
            positive_tail_share=float(option_a_best["positive_tail_share"]),
            negative_tail_share=float(option_a_best["negative_tail_share"]),
            stress_share=float(stress_share),
            scenario_run_id=f"ab_sweep_option_b_{stress_share}",
        )
        with_delta = _delta_against_baseline(scored, baseline_rows)
        with_delta["stress_share"] = float(stress_share)
        option_b_candidate_rows.append(with_delta)
        summary = _aggregate_summary(with_delta, stage_name="option_b", scenario_variant="base_plus_b")
        summary.update(
            {
                "stress_share": float(stress_share),
                "mean_scenario_score_gain": float(with_delta["scenario_score_gain"].mean()),
                "mean_high_tail_miss_reduction": float(with_delta["high_tail_miss_reduction"].mean()),
                "mean_p10_p90_coverage_gain": float(with_delta["p10_p90_coverage_gain"].mean()),
                "mean_width_change": float(with_delta["width_change"].mean()),
            }
        )
        option_b_rows.append(summary)

    option_b_best = _choose_best_setting(option_b_rows)

    baseline_summary = _aggregate_summary(baseline_rows, stage_name="baseline", scenario_variant="base")
    baseline_summary.update(
        {
            "positive_tail_share": 0.0,
            "negative_tail_share": 0.0,
            "normal_share": 1.0,
            "stress_share": 0.0,
        }
    )

    notebook_defaults = {
        "use_option_a_tail_enrichment": True,
        "use_option_b_stress_scenarios": True,
        "use_option_c_bias_correction": False,
        "normal_share": float(option_a_best["normal_share"]),
        "positive_tail_share": float(option_a_best["positive_tail_share"]),
        "negative_tail_share": float(option_a_best["negative_tail_share"]),
        "stress_share": float(option_b_best["stress_share"]),
        "n_raw_scenarios": int(N_RAW_SCENARIOS),
        "n_final_scenarios": int(N_FINAL_SCENARIOS),
    }

    recommendation_payload = {
        "timestamp": pd.Timestamp.utcnow().isoformat(),
        "tuning_windows": {
            "calibration_start": str(TUNING_CALIBRATION_START.date()),
            "calibration_end": str(TUNING_CALIBRATION_END.date()),
            "selection_start": str(TUNING_SELECTION_START.date()),
            "selection_end": str(TUNING_SELECTION_END.date()),
        },
        "selected_candidates": selected_candidate_keys,
        "fixed_scenario_counts": {
            "n_raw_scenarios": int(N_RAW_SCENARIOS),
            "n_final_scenarios": int(N_FINAL_SCENARIOS),
        },
        "baseline_summary": baseline_summary,
        "option_a_selected": option_a_best,
        "option_b_selected": option_b_best,
        "notebook_defaults": notebook_defaults,
    }

    pd.DataFrame([baseline_summary]).to_csv(out_dir / "option_ab_baseline_summary.csv", index=False)
    pd.DataFrame(option_a_rows).sort_values("mean_scenario_score", ascending=False).to_csv(
        out_dir / "option_a_validation_sweep_summary.csv", index=False
    )
    pd.concat(option_a_candidate_rows, ignore_index=True).to_csv(out_dir / "option_a_validation_candidate_results.csv", index=False)
    pd.DataFrame(option_b_rows).sort_values("mean_scenario_score", ascending=False).to_csv(
        out_dir / "option_b_validation_sweep_summary.csv", index=False
    )
    pd.concat(option_b_candidate_rows, ignore_index=True).to_csv(out_dir / "option_b_validation_candidate_results.csv", index=False)
    pd.DataFrame([option_a_best]).to_csv(out_dir / "option_a_selected_setting.csv", index=False)
    pd.DataFrame([option_b_best]).to_csv(out_dir / "option_b_selected_setting.csv", index=False)
    pd.DataFrame([notebook_defaults]).to_csv(out_dir / "option_ab_notebook_defaults.csv", index=False)
    (out_dir / "option_ab_sweep_recommendation.json").write_text(
        json.dumps(recommendation_payload, indent=2, default=str),
        encoding="utf-8",
    )

    print(out_dir)


if __name__ == "__main__":
    main()
