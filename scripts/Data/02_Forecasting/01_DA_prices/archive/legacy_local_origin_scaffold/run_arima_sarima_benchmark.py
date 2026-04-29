from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from da_forecasting.backtest import run_walk_forward_for_split
from da_forecasting.config import ForecastSetup
from da_forecasting.data import load_target_frame
from da_forecasting.io_utils import create_run_directory, write_csv, write_json
from da_forecasting.metrics import add_error_columns, add_relative_metric_vs_reference, summarize_metrics
from da_forecasting.models.arima import ARIMAConfig, ARIMAModel, SARIMAConfig, SARIMAModel
from da_forecasting.models.naive import NaivePreviousWeekModel
from da_forecasting.splits import build_split_summary, generate_origins_for_split, label_splits
from da_forecasting.visualization import canonical_forecast_track


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run rolling-origin ARIMA/SARIMA benchmark against naive_7d.")
    parser.add_argument("--input-csv", type=Path, default=ForecastSetup.input_csv)
    parser.add_argument("--output-root", type=Path, default=ForecastSetup.output_root)
    parser.add_argument("--market-area", type=str, default=ForecastSetup.market_area)
    parser.add_argument("--local-timezone", type=str, default=ForecastSetup.local_timezone)
    parser.add_argument("--origin-hour-local", type=int, default=ForecastSetup.origin_hour_local)
    parser.add_argument("--origin-step-days", type=int, default=ForecastSetup.origin_step_days)
    parser.add_argument("--horizon-days", type=int, default=ForecastSetup.horizon_days)

    parser.add_argument("--arima-order", type=str, default="2,1,2", help="ARIMA (p,d,q)")
    parser.add_argument("--sarima-order", type=str, default="1,1,1", help="SARIMA non-seasonal (p,d,q)")
    parser.add_argument("--sarima-seasonal-order", type=str, default="1,0,1,24", help="SARIMA seasonal (P,D,Q,s)")
    parser.add_argument("--history-window-days", type=int, default=60)
    parser.add_argument("--arima-min-history-days", type=int, default=30)
    parser.add_argument("--sarima-min-history-days", type=int, default=45)
    parser.add_argument("--maxiter", type=int, default=25)
    parser.add_argument("--reference-model", type=str, default="naive_7d")
    return parser.parse_args()


def _parse_tuple(text: str, expected_len: int) -> tuple[int, ...]:
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) != expected_len:
        raise ValueError(f"Expected {expected_len} comma-separated integers, got: {text}")
    return tuple(int(part) for part in parts)


def _to_json_serializable(payload: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, tuple):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def main() -> None:
    args = parse_args()

    setup = replace(
        ForecastSetup(),
        input_csv=args.input_csv,
        output_root=args.output_root,
        market_area=args.market_area,
        local_timezone=args.local_timezone,
        origin_hour_local=args.origin_hour_local,
        origin_step_days=args.origin_step_days,
        horizon_days=args.horizon_days,
    )

    arima_order = _parse_tuple(args.arima_order, 3)
    sarima_order = _parse_tuple(args.sarima_order, 3)
    sarima_seasonal_order = _parse_tuple(args.sarima_seasonal_order, 4)
    history_window_hours = args.history_window_days * 24 if args.history_window_days > 0 else None

    arima_cfg = ARIMAConfig(
        order=arima_order,
        history_window_hours=history_window_hours,
        min_history_hours=args.arima_min_history_days * 24,
        maxiter=args.maxiter,
    )
    sarima_cfg = SARIMAConfig(
        order=sarima_order,
        seasonal_order=sarima_seasonal_order,
        history_window_hours=history_window_hours,
        min_history_hours=args.sarima_min_history_days * 24,
        maxiter=args.maxiter,
    )

    labeled = label_splits(load_target_frame(setup), setup)
    split_summary = build_split_summary(labeled)

    models = [
        NaivePreviousWeekModel(),
        ARIMAModel(config=arima_cfg),
        SARIMAModel(config=sarima_cfg),
    ]

    validation_predictions = run_walk_forward_for_split(labeled, setup, "validation", models)
    test_predictions = run_walk_forward_for_split(labeled, setup, "test", models)
    all_predictions = pd.concat([validation_predictions, test_predictions], ignore_index=True)

    scored = add_error_columns(all_predictions)
    metrics_df = summarize_metrics(scored)
    metrics_vs_ref = add_relative_metric_vs_reference(
        metrics_df=metrics_df,
        reference_model=args.reference_model,
        metric_col="mae",
        output_col="mae_skill_vs_reference_pct",
    )

    challenger_rows = metrics_vs_ref[
        (metrics_vs_ref["split"] == "validation") & (metrics_vs_ref["model"].isin(["arima", "sarima"]))
    ].copy()
    challenger_rows = challenger_rows.dropna(subset=["mae"]).sort_values(["mae", "model"]).reset_index(drop=True)
    best_challenger = challenger_rows.iloc[0].to_dict() if not challenger_rows.empty else {}

    origin_summary_rows: list[dict[str, object]] = []
    for split_name in ("validation", "test"):
        origin_summary_rows.append(
            {
                "split": split_name,
                "origins": len(generate_origins_for_split(setup, split_name)),
                "origin_hour_local": setup.origin_hour_local,
                "origin_step_days": setup.origin_step_days,
                "horizon_days": setup.horizon_days,
            }
        )
    origins_summary = pd.DataFrame(origin_summary_rows)

    run_dir = create_run_directory(setup.output_root)
    model_cfg_snapshot = {
        "reference_model": args.reference_model,
        "arima": _to_json_serializable(asdict(arima_cfg)),
        "sarima": _to_json_serializable(asdict(sarima_cfg)),
    }
    write_json(run_dir / "config_snapshot.json", setup.to_json_dict())
    write_json(run_dir / "model_config_snapshot.json", model_cfg_snapshot)
    write_csv(run_dir / "split_summary.csv", split_summary)
    write_csv(run_dir / "origin_summary.csv", origins_summary)
    write_csv(run_dir / "predictions_validation.csv", validation_predictions)
    write_csv(run_dir / "predictions_test.csv", test_predictions)
    write_csv(run_dir / "predictions_all_scored.csv", scored)
    write_csv(run_dir / "metrics_by_split_model.csv", metrics_df)
    write_csv(run_dir / "metrics_vs_reference.csv", metrics_vs_ref)

    for model_name in ("naive_7d", "arima", "sarima"):
        val_track = canonical_forecast_track(scored, split_name="validation", model_name=model_name)
        test_track = canonical_forecast_track(scored, split_name="test", model_name=model_name)
        write_csv(run_dir / f"canonical_validation_track_{model_name}.csv", val_track)
        write_csv(run_dir / f"canonical_test_track_{model_name}.csv", test_track)

    write_json(
        run_dir / "comparison_summary.json",
        {
            "reference_model": args.reference_model,
            "best_challenger_on_validation": best_challenger,
        },
    )

    print(f"Run completed. Artifacts written to: {run_dir}")
    if best_challenger:
        print(
            "Best challenger on validation: "
            f"{best_challenger['model']} (MAE={best_challenger['mae']:.4f}, "
            f"skill_vs_{args.reference_model}={best_challenger['mae_skill_vs_reference_pct']:.2f}%)"
        )


if __name__ == "__main__":
    main()
