from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from hydrogen.bidding import (  # noqa: E402
    HIGH_PRICE_BID_EUR_PER_MWH,
    REFERENCE_PRICE_BID_EUR_PER_MWH,
    dispatch_schedule_to_one_block_bid_curve,
)
from hydrogen.bidding_metrics import compute_bridge_clearing_metrics  # noqa: E402
from hydrogen.clearing import aggregate_cleared_energy, clear_hourly_bids  # noqa: E402
from hydrogen.plots import (  # noqa: E402
    plot_actual_price_vs_bid_price,
    plot_bid_clearing_waterfall,
    plot_bridge_clearing_heatmap,
    plot_scheduled_vs_cleared_electricity,
)


DEFAULT_INPUT_RUN = ROOT / "runs" / "20260515_122405_hydrogen_phase0_one_day_smoke"


def _resolve_latest_phase0_run() -> Path:
    runs_root = ROOT / "runs"
    candidates = sorted(
        [
            path
            for path in runs_root.iterdir()
            if path.is_dir() and (path / "results_timeseries.parquet").exists()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No run folder with results_timeseries.parquet was found under scripts/Data/03_Hydrogen_Test_Case/runs.")
    return candidates[0]


def _read_run_config(input_run_dir: Path) -> dict[str, Any]:
    config_path = input_run_dir / "config_resolved.yaml"
    if not config_path.exists():
        return {}
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _extract_run_metadata(input_run_dir: Path) -> dict[str, Any]:
    payload = _read_run_config(input_run_dir)
    experiment = payload.get("experiment", {}) if isinstance(payload.get("experiment"), dict) else {}
    economics = payload.get("economics", {}) if isinstance(payload.get("economics"), dict) else {}
    bidding = payload.get("bidding", {}) if isinstance(payload.get("bidding"), dict) else {}
    return {
        "granularity": str(experiment.get("granularity", "hourly")),
        "horizon": str(experiment.get("horizon_mode", "unknown")),
        "reference_price_eur_per_mwh": float(economics.get("p_ref_eur_per_mwh", REFERENCE_PRICE_BID_EUR_PER_MWH)),
        "price_insensitive_bid_price_eur_per_mwh": float(
            bidding.get("price_insensitive_bid_price_eur_per_mwh", HIGH_PRICE_BID_EUR_PER_MWH)
        ),
    }


def _build_bridge_bid_curves(
    timeseries: pd.DataFrame,
    *,
    run_id: str,
    granularity: str,
    horizon: str,
    reference_price_eur_per_mwh: float,
    price_insensitive_bid_price_eur_per_mwh: float,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    grouping_columns = ["strategy", "model_id", "forecast_origin_utc"]
    for keys, group in timeseries.groupby(grouping_columns, dropna=False):
        source_strategy, model_id, forecast_origin_utc = keys
        shared_kwargs = {
            "dispatch_timeseries": group.sort_values("delivery_start_utc"),
            "run_id": run_id,
            "source_strategy": str(source_strategy),
            "granularity": granularity,
            "horizon": horizon,
            "scenario_model": None if pd.isna(model_id) else str(model_id),
            "forecast_origin_utc": forecast_origin_utc,
        }
        frames.append(
            dispatch_schedule_to_one_block_bid_curve(
                **shared_kwargs,
                bridge_strategy="reference_price_bid",
                bid_price_eur_per_mwh=reference_price_eur_per_mwh,
            )
        )
        frames.append(
            dispatch_schedule_to_one_block_bid_curve(
                **shared_kwargs,
                bridge_strategy="high_price_bid",
                bid_price_eur_per_mwh=HIGH_PRICE_BID_EUR_PER_MWH,
            )
        )
        if str(source_strategy) == "price_insensitive":
            frames.append(
                dispatch_schedule_to_one_block_bid_curve(
                    **shared_kwargs,
                    bridge_strategy="price_insensitive_plan_first_market_cap",
                    bid_price_eur_per_mwh=price_insensitive_bid_price_eur_per_mwh,
                )
            )
        elif str(source_strategy) == "price_insensitive_heuristic":
            frames.append(
                dispatch_schedule_to_one_block_bid_curve(
                    **shared_kwargs,
                    bridge_strategy="price_insensitive_heuristic_plan_first_market_cap",
                    bid_price_eur_per_mwh=price_insensitive_bid_price_eur_per_mwh,
                )
            )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _build_actual_price_frame(timeseries: pd.DataFrame) -> pd.DataFrame:
    price_frame = (
        timeseries[["delivery_start_utc", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
        .reset_index(drop=True)
    )
    if price_frame["delivery_start_utc"].duplicated().any():
        raise ValueError("Actual price frame still has duplicate delivery_start_utc rows after deduplication.")
    return price_frame


def _write_readme(
    output_dir: Path,
    *,
    input_run_dir: Path,
    metrics: pd.DataFrame,
) -> None:
    summary_table = metrics.to_csv(index=False).strip()
    lines = [
        "# Schedule-To-Bid Bridge",
        "",
        "This run converts an existing schedule-and-settle dispatch output into one-block day-ahead demand bids.",
        "",
        f"- Input run folder: `{input_run_dir}`",
        "- Bridge strategies: `reference_price_bid`, `high_price_bid`, `price_insensitive_plan_first_market_cap`, and legacy `price_insensitive_heuristic_plan_first_market_cap` when present",
        "- Clearing rule: accepted if `bid_price_eur_per_mwh >= actual_price_eur_per_mwh`",
        "- Settlement interpretation: accepted energy is paid at the realised DA price, not the bid price",
        "- Physical redispatch after under-clearing is not implemented in this phase",
        "",
        "## Strategy summary",
        "",
        "```csv",
        summary_table,
        "```",
    ]
    (output_dir / "README_bridge.md").write_text("\n".join(lines), encoding="utf-8")


def run_bridge(input_run_dir: Path, output_root: Path) -> Path:
    input_run_dir = input_run_dir.resolve()
    timeseries_path = input_run_dir / "results_timeseries.parquet"
    if not timeseries_path.exists():
        raise FileNotFoundError(f"Missing input file: {timeseries_path}")

    run_metadata = _extract_run_metadata(input_run_dir)
    timeseries = pd.read_parquet(timeseries_path)
    output_dir = output_root / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_hydrogen_phase2_schedule_to_bid_bridge"
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    run_id = input_run_dir.name
    bridge_bids = _build_bridge_bid_curves(
        timeseries,
        run_id=run_id,
        granularity=run_metadata["granularity"],
        horizon=run_metadata["horizon"],
        reference_price_eur_per_mwh=run_metadata["reference_price_eur_per_mwh"],
        price_insensitive_bid_price_eur_per_mwh=run_metadata["price_insensitive_bid_price_eur_per_mwh"],
    )
    actual_prices = _build_actual_price_frame(timeseries)
    actual_clearing = clear_hourly_bids(bridge_bids, actual_prices)
    clearing_by_hour = aggregate_cleared_energy(actual_clearing)
    bid_price_lookup = (
        bridge_bids[
            [
                "run_id",
                "strategy",
                "source_strategy",
                "bridge_strategy",
                "delivery_start_utc",
                "bid_price_eur_per_mwh",
            ]
        ]
        .drop_duplicates()
    )
    clearing_by_hour = clearing_by_hour.merge(
        bid_price_lookup,
        on=[
            "run_id",
            "strategy",
            "source_strategy",
            "bridge_strategy",
            "delivery_start_utc",
        ],
        how="left",
        validate="one_to_one",
    )
    metrics = compute_bridge_clearing_metrics(actual_clearing)

    bridge_bids.to_parquet(output_dir / "bridge_submitted_bids.parquet", index=False)
    actual_clearing.to_parquet(output_dir / "bridge_actual_clearing.parquet", index=False)
    clearing_by_hour.to_parquet(output_dir / "bridge_clearing_by_hour.parquet", index=False)
    metrics.to_csv(output_dir / "bridge_clearing_metrics.csv", index=False)
    (output_dir / "bridge_run_manifest.json").write_text(
        json.dumps(
            {
                "input_run_dir": str(input_run_dir),
                "output_dir": str(output_dir),
                "granularity": run_metadata["granularity"],
                "horizon": run_metadata["horizon"],
                "reference_price_eur_per_mwh": run_metadata["reference_price_eur_per_mwh"],
                "high_price_eur_per_mwh": HIGH_PRICE_BID_EUR_PER_MWH,
                "price_insensitive_bid_price_eur_per_mwh": run_metadata["price_insensitive_bid_price_eur_per_mwh"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    for row in metrics.to_dict(orient="records"):
        subset = clearing_by_hour[
            (clearing_by_hour["source_strategy"] == row["source_strategy"])
            & (clearing_by_hour["bridge_strategy"] == row["bridge_strategy"])
        ].sort_values("delivery_start_utc")
        stem = f"{row['source_strategy']}__{row['bridge_strategy']}"
        plot_scheduled_vs_cleared_electricity(
            clearing_by_hour=subset,
            output_dir=figures_dir,
            filename=f"{stem}__scheduled_vs_cleared.png",
            title=f"{row['source_strategy']} | {row['bridge_strategy']}",
        )
        plot_actual_price_vs_bid_price(
            clearing_by_hour=subset,
            output_dir=figures_dir,
            filename=f"{stem}__actual_vs_bid_price.png",
            title=f"{row['source_strategy']} | {row['bridge_strategy']}",
        )
        plot_bid_clearing_waterfall(
            metrics_row=pd.Series(row),
            output_dir=figures_dir,
            filename=f"{stem}__waterfall.png",
            title=f"{row['source_strategy']} | {row['bridge_strategy']}",
        )

    plot_bridge_clearing_heatmap(
        clearing_by_hour=clearing_by_hour,
        output_dir=figures_dir,
        filename="bridge_clearing_heatmap.png",
    )
    _write_readme(output_dir, input_run_dir=input_run_dir, metrics=metrics)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a saved hydrogen dispatch run into one-block DA bridge bids and clear them.")
    parser.add_argument(
        "--input-run",
        type=Path,
        default=DEFAULT_INPUT_RUN if DEFAULT_INPUT_RUN.exists() else _resolve_latest_phase0_run(),
        help="Run folder containing results_timeseries.parquet.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "runs",
        help="Root folder for bridge output runs.",
    )
    args = parser.parse_args()
    output_dir = run_bridge(args.input_run, args.output_root)
    print(output_dir)


if __name__ == "__main__":
    main()
