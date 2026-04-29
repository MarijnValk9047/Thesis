from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from da_forecasting.backtest import run_walk_forward_for_split
from da_forecasting.config import ForecastSetup
from da_forecasting.data import load_target_frame
from da_forecasting.io_utils import write_csv, write_json
from da_forecasting.metrics import add_error_columns, add_relative_metric_vs_reference, summarize_metrics
from da_forecasting.models.arima import ARIMAConfig, ARIMAModel, SARIMAConfig, SARIMAModel
from da_forecasting.models.naive import NaivePreviousWeekModel
from da_forecasting.splits import build_split_summary, generate_origins_for_split, label_splits
from da_forecasting.visualization import (
    canonical_forecast_track,
    plot_split_overview,
    plot_zoom_period,
    select_week_month_periods,
)


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    family: str
    order: tuple[int, int, int]
    seasonal_order: tuple[int, int, int, int] | None
    history_window_days: int
    min_history_days: int
    maxiter: int = 25

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["order"] = list(self.order)
        payload["seasonal_order"] = list(self.seasonal_order) if self.seasonal_order is not None else None
        return payload


SESSION_1_CANDIDATES: list[CandidateSpec] = [
    CandidateSpec("arima__111_win30", "arima", (1, 1, 1), None, history_window_days=30, min_history_days=20, maxiter=15),
    CandidateSpec("arima__212_win60", "arima", (2, 1, 2), None, history_window_days=60, min_history_days=30, maxiter=15),
    CandidateSpec(
        "sarima__111_x_101_24_D0_win60",
        "sarima",
        (1, 1, 1),
        (1, 0, 1, 24),
        history_window_days=60,
        min_history_days=45,
        maxiter=10,
    ),
    CandidateSpec(
        "sarima__111_x_101_168_D0_win60",
        "sarima",
        (1, 1, 1),
        (1, 0, 1, 168),
        history_window_days=60,
        min_history_days=45,
        maxiter=8,
    ),
]

SESSION_2_CANDIDATES: list[CandidateSpec] = [
    CandidateSpec("arima__211_win60", "arima", (2, 1, 1), None, history_window_days=60, min_history_days=30, maxiter=25),
    CandidateSpec("arima__212_win90", "arima", (2, 1, 2), None, history_window_days=90, min_history_days=30, maxiter=25),
    CandidateSpec(
        "sarima__111_x_101_24_D0_win90",
        "sarima",
        (1, 1, 1),
        (1, 0, 1, 24),
        history_window_days=90,
        min_history_days=60,
        maxiter=20,
    ),
    CandidateSpec(
        "sarima__111_x_111_24_D1_win90",
        "sarima",
        (1, 1, 1),
        (1, 1, 1, 24),
        history_window_days=90,
        min_history_days=60,
        maxiter=20,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARIMA/SARIMA tuning sessions and final full run.")
    parser.add_argument("--stage", choices=["session1", "session2", "full", "all"], default="all")
    parser.add_argument("--experiment-id", type=str, default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--input-csv", type=Path, default=ForecastSetup.input_csv)
    parser.add_argument("--output-root", type=Path, default=ForecastSetup.output_root)
    parser.add_argument("--market-area", type=str, default=ForecastSetup.market_area)
    parser.add_argument("--local-timezone", type=str, default=ForecastSetup.local_timezone)
    parser.add_argument("--origin-hour-local", type=int, default=ForecastSetup.origin_hour_local)
    parser.add_argument("--horizon-days", type=int, default=ForecastSetup.horizon_days)
    parser.add_argument("--reference-model", type=str, default="naive_7d")
    return parser.parse_args()


def _build_model(spec: CandidateSpec):
    if spec.family == "arima":
        cfg = ARIMAConfig(
            order=spec.order,
            history_window_hours=spec.history_window_days * 24,
            min_history_hours=spec.min_history_days * 24,
            maxiter=spec.maxiter,
        )
        return ARIMAModel(config=cfg, name=spec.candidate_id)
    if spec.family == "sarima":
        cfg = SARIMAConfig(
            order=spec.order,
            seasonal_order=spec.seasonal_order or (1, 0, 1, 24),
            history_window_hours=spec.history_window_days * 24,
            min_history_hours=spec.min_history_days * 24,
            maxiter=spec.maxiter,
        )
        return SARIMAModel(config=cfg, name=spec.candidate_id)
    raise ValueError(f"Unsupported family: {spec.family}")


def _compute_lead_day_metrics(scored_predictions: pd.DataFrame, local_timezone: str) -> pd.DataFrame:
    if scored_predictions.empty:
        return pd.DataFrame(columns=["split", "model", "lead_day", "observations", "mae", "rmse", "bias"])

    frame = scored_predictions.copy()
    frame["origin_local_dt"] = pd.to_datetime(frame["origin_local"], utc=True, errors="coerce").dt.tz_convert(local_timezone)
    frame["target_local_dt"] = (
        pd.to_datetime(frame["target_timestamp_local"], utc=True, errors="coerce").dt.tz_convert(local_timezone)
    )
    frame = frame.dropna(subset=["origin_local_dt", "target_local_dt"]).copy()
    frame["lead_day"] = (frame["target_local_dt"].dt.date - frame["origin_local_dt"].dt.date).apply(lambda delta: delta.days)
    frame = frame[frame["lead_day"].between(1, 5)].copy()
    frame = frame[frame["y_pred"].notna()].copy()

    grouped = (
        frame.groupby(["split", "model", "lead_day"], as_index=False)
        .agg(
            observations=("abs_error", "size"),
            mae=("abs_error", "mean"),
            rmse=("squared_error", lambda x: float((x.mean()) ** 0.5)),
            bias=("error", "mean"),
        )
        .sort_values(["split", "model", "lead_day"])
        .reset_index(drop=True)
    )
    return grouped


def _plot_validation_mae(metrics_vs_ref: pd.DataFrame, output_path: Path, title: str) -> None:
    part = metrics_vs_ref[metrics_vs_ref["split"] == "validation"].copy()
    if part.empty:
        return
    part = part.sort_values("mae")
    fig, ax = plt.subplots(figsize=(13, 5))
    bars = ax.bar(part["model"], part["mae"], color="#6aaed6")
    for bar, value in zip(bars, part["mae"], strict=False):
        ax.text(bar.get_x() + bar.get_width() / 2.0, value, f"{value:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_title(title)
    ax.set_ylabel("MAE")
    ax.set_xlabel("Model")
    ax.tick_params(axis="x", rotation=55)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _plot_lead_day_mae(lead_day_metrics: pd.DataFrame, split_name: str, output_path: Path, title: str) -> None:
    part = lead_day_metrics[lead_day_metrics["split"] == split_name].copy()
    if part.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for model_name, group in part.groupby("model"):
        group = group.sort_values("lead_day")
        ax.plot(group["lead_day"], group["mae"], marker="o", linewidth=1.2, label=model_name)
    ax.set_title(title)
    ax.set_xlabel("Lead Day")
    ax.set_ylabel("MAE")
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.grid(alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _run_single_model(
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    split_names: list[str],
    model,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_predictions: list[pd.DataFrame] = []
    diagnostics_rows: list[dict[str, object]] = []

    for split_name in split_names:
        model.reset_diagnostics()
        pred = run_walk_forward_for_split(labeled, setup, split_name, [model])
        split_predictions.append(pred)

        diag = model.diagnostics_snapshot()
        diag["split"] = split_name
        diagnostics_rows.append(diag)

    all_pred = pd.concat(split_predictions, ignore_index=True) if split_predictions else pd.DataFrame()
    diag_df = pd.DataFrame(diagnostics_rows)
    return all_pred, diag_df


def _run_session(
    session_name: str,
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    split_names: list[str],
    candidates: list[CandidateSpec],
    output_dir: Path,
    reference_model: str,
) -> dict[str, pd.DataFrame]:
    print(f"[{session_name}] start: origin_step_days={setup.origin_step_days}, splits={split_names}")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "session_config.json", {"session": session_name, "origin_step_days": setup.origin_step_days, "splits": split_names})
    write_json(output_dir / "candidate_registry.json", {"candidates": [candidate.to_dict() for candidate in candidates]})

    all_predictions: list[pd.DataFrame] = []
    all_diagnostics: list[pd.DataFrame] = []

    naive = NaivePreviousWeekModel()
    print(f"[{session_name}] running reference model: {naive.name}")
    naive_pred, naive_diag = _run_single_model(labeled, setup, split_names, naive)
    all_predictions.append(naive_pred)
    all_diagnostics.append(naive_diag)

    for index, candidate in enumerate(candidates, start=1):
        print(f"[{session_name}] running candidate {index}/{len(candidates)}: {candidate.candidate_id}")
        model = _build_model(candidate)
        candidate_pred, candidate_diag = _run_single_model(labeled, setup, split_names, model)
        all_predictions.append(candidate_pred)
        if not candidate_diag.empty:
            candidate_diag["candidate_id"] = candidate.candidate_id
            candidate_diag["family"] = candidate.family
        all_diagnostics.append(candidate_diag)

    predictions = pd.concat(all_predictions, ignore_index=True) if all_predictions else pd.DataFrame()
    diagnostics = pd.concat(all_diagnostics, ignore_index=True) if all_diagnostics else pd.DataFrame()

    scored = add_error_columns(predictions)
    metrics = summarize_metrics(scored)
    metrics_vs_ref = add_relative_metric_vs_reference(
        metrics_df=metrics,
        reference_model=reference_model,
        metric_col="mae",
        output_col=f"mae_skill_vs_{reference_model}_pct",
    )
    lead_day_metrics = _compute_lead_day_metrics(scored, local_timezone=setup.local_timezone)

    rank_validation = (
        metrics_vs_ref[metrics_vs_ref["split"] == "validation"]
        .sort_values(["mae", "model"])
        .reset_index(drop=True)
    )

    write_csv(output_dir / "predictions.csv", predictions)
    write_csv(output_dir / "predictions_scored.csv", scored)
    write_csv(output_dir / "metrics.csv", metrics)
    write_csv(output_dir / "metrics_vs_reference.csv", metrics_vs_ref)
    write_csv(output_dir / "lead_day_metrics.csv", lead_day_metrics)
    write_csv(output_dir / "warning_diagnostics.csv", diagnostics)
    write_csv(output_dir / "validation_ranking.csv", rank_validation)

    _plot_validation_mae(
        metrics_vs_ref=metrics_vs_ref,
        output_path=output_dir / "plots" / "validation_mae_bar.png",
        title=f"{session_name}: Validation MAE",
    )
    _plot_lead_day_mae(
        lead_day_metrics=lead_day_metrics,
        split_name="validation",
        output_path=output_dir / "plots" / "validation_lead_day_mae.png",
        title=f"{session_name}: Validation MAE by Lead Day",
    )

    print(f"[{session_name}] completed")
    return {
        "predictions": predictions,
        "scored": scored,
        "metrics": metrics,
        "metrics_vs_ref": metrics_vs_ref,
        "lead_day_metrics": lead_day_metrics,
        "warning_diagnostics": diagnostics,
    }


def _select_best_by_family(metrics_vs_ref: pd.DataFrame, candidates: list[CandidateSpec], family: str) -> str:
    candidate_ids = [candidate.candidate_id for candidate in candidates if candidate.family == family]
    part = metrics_vs_ref[
        (metrics_vs_ref["split"] == "validation")
        & (metrics_vs_ref["model"].isin(candidate_ids))
    ].copy()
    if part.empty:
        raise ValueError(f"No validation results for family '{family}'.")
    part = part.sort_values(["mae", "model"]).reset_index(drop=True)
    return str(part.iloc[0]["model"])


def _build_easy_table(metrics_vs_ref: pd.DataFrame, model_order: list[str], reference_model: str) -> pd.DataFrame:
    val = metrics_vs_ref[metrics_vs_ref["split"] == "validation"].set_index("model")
    test = metrics_vs_ref[metrics_vs_ref["split"] == "test"].set_index("model")
    rows: list[dict[str, object]] = []
    skill_col = f"mae_skill_vs_{reference_model}_pct"

    for model_name in model_order:
        if model_name not in val.index or model_name not in test.index:
            continue
        rows.append(
            {
                "model": model_name,
                "validation_mae": float(val.loc[model_name, "mae"]),
                "test_mae": float(test.loc[model_name, "mae"]),
                "validation_rmse": float(val.loc[model_name, "rmse"]),
                "test_rmse": float(test.loc[model_name, "rmse"]),
                "validation_smape_pct": float(val.loc[model_name, "smape_pct"]),
                "test_smape_pct": float(test.loc[model_name, "smape_pct"]),
                f"validation_skill_vs_{reference_model}_pct": float(val.loc[model_name, skill_col]),
                f"test_skill_vs_{reference_model}_pct": float(test.loc[model_name, skill_col]),
            }
        )
    return pd.DataFrame(rows)


def _plot_full_metric_comparison(easy_table: pd.DataFrame, output_path: Path) -> None:
    if easy_table.empty:
        return

    models = easy_table["model"].tolist()
    x = list(range(len(models)))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar([val - width for val in x], easy_table["test_mae"], width=width, label="Test MAE")
    ax.bar(x, easy_table["test_rmse"], width=width, label="Test RMSE")
    ax.bar([val + width for val in x], easy_table["test_smape_pct"], width=width, label="Test sMAPE (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=25)
    ax.set_title("Final Model Comparison on Test Split")
    ax.set_ylabel("Metric Value")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _render_model_plot_bundle(
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    scored: pd.DataFrame,
    model_name: str,
    output_dir: Path,
) -> None:
    model_output_dir = output_dir / model_name
    model_output_dir.mkdir(parents=True, exist_ok=True)

    validation_track = canonical_forecast_track(scored, split_name="validation", model_name=model_name)
    test_track = canonical_forecast_track(scored, split_name="test", model_name=model_name)
    if validation_track.empty or test_track.empty:
        return

    frame_for_overview = labeled[labeled["split"].isin(["train", "validation", "test"])].copy()

    plot_split_overview(
        labeled=frame_for_overview,
        setup=setup,
        validation_track=validation_track,
        test_track=test_track,
        output_path=model_output_dir / "split_overview_actual_vs_forecast.png",
        model_name=model_name,
    )

    period_selection = select_week_month_periods(test_track, local_timezone=setup.local_timezone)
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["best_week"],
        output_path=model_output_dir / "test_best_week.png",
        title=f"Best Test Week ({model_name})",
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["worst_week"],
        output_path=model_output_dir / "test_worst_week.png",
        title=f"Worst Test Week ({model_name})",
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["best_month"],
        output_path=model_output_dir / "test_best_month.png",
        title=f"Best Test Month ({model_name})",
    )
    plot_zoom_period(
        test_track=test_track,
        selection=period_selection["worst_month"],
        output_path=model_output_dir / "test_worst_month.png",
        title=f"Worst Test Month ({model_name})",
    )

    write_csv(model_output_dir / "canonical_validation_track.csv", validation_track)
    write_csv(model_output_dir / "canonical_test_track.csv", test_track)
    write_csv(model_output_dir / "test_weekly_mae_table.csv", period_selection["week_table"])
    write_csv(model_output_dir / "test_monthly_mae_table.csv", period_selection["month_table"])
    write_json(
        model_output_dir / "test_best_worst_periods.json",
        {
            "model": model_name,
            "best_week": period_selection["best_week"].to_dict(),
            "worst_week": period_selection["worst_week"].to_dict(),
            "best_month": period_selection["best_month"].to_dict(),
            "worst_month": period_selection["worst_month"].to_dict(),
        },
    )


def _run_full_benchmark(
    experiment_dir: Path,
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    reference_model: str,
    best_arima_id: str,
    best_sarima_id: str,
    candidate_lookup: dict[str, CandidateSpec],
) -> None:
    full_dir = experiment_dir / "full_run"
    full_dir.mkdir(parents=True, exist_ok=True)
    print(f"[full_run] start with best_arima={best_arima_id}, best_sarima={best_sarima_id}")

    models = [NaivePreviousWeekModel()]
    models.append(_build_model(candidate_lookup[best_arima_id]))
    models.append(_build_model(candidate_lookup[best_sarima_id]))

    diagnostics_rows: list[dict[str, object]] = []
    all_predictions: list[pd.DataFrame] = []
    for model in models:
        model_name = model.name
        print(f"[full_run] running model {model_name}")
        pred, diag = _run_single_model(labeled, setup, ["validation", "test"], model)
        all_predictions.append(pred)
        if not diag.empty:
            diagnostics_rows.append(diag)

    predictions = pd.concat(all_predictions, ignore_index=True)
    scored = add_error_columns(predictions)
    metrics = summarize_metrics(scored)
    metrics_vs_ref = add_relative_metric_vs_reference(
        metrics_df=metrics,
        reference_model=reference_model,
        metric_col="mae",
        output_col=f"mae_skill_vs_{reference_model}_pct",
    )
    lead_day_metrics = _compute_lead_day_metrics(scored, local_timezone=setup.local_timezone)

    easy_table = _build_easy_table(
        metrics_vs_ref=metrics_vs_ref,
        model_order=[reference_model, best_arima_id, best_sarima_id],
        reference_model=reference_model,
    )

    write_csv(full_dir / "predictions.csv", predictions)
    write_csv(full_dir / "predictions_scored.csv", scored)
    write_csv(full_dir / "metrics.csv", metrics)
    write_csv(full_dir / "metrics_vs_reference.csv", metrics_vs_ref)
    write_csv(full_dir / "lead_day_metrics.csv", lead_day_metrics)
    write_csv(full_dir / "easy_comparison_table.csv", easy_table)
    if diagnostics_rows:
        write_csv(full_dir / "warning_diagnostics.csv", pd.concat(diagnostics_rows, ignore_index=True))

    _plot_validation_mae(
        metrics_vs_ref=metrics_vs_ref,
        output_path=full_dir / "plots" / "validation_mae_bar.png",
        title="Full Run: Validation MAE",
    )
    _plot_lead_day_mae(
        lead_day_metrics=lead_day_metrics,
        split_name="test",
        output_path=full_dir / "plots" / "test_lead_day_mae.png",
        title="Full Run: Test MAE by Lead Day",
    )
    _plot_full_metric_comparison(
        easy_table=easy_table,
        output_path=full_dir / "plots" / "test_metric_comparison.png",
    )

    for model_name in [reference_model, best_arima_id, best_sarima_id]:
        _render_model_plot_bundle(
            labeled=labeled,
            setup=setup,
            scored=scored,
            model_name=model_name,
            output_dir=full_dir / "plots_by_model",
        )

    write_json(
        full_dir / "selected_models.json",
        {
            "reference_model": reference_model,
            "best_arima_id": best_arima_id,
            "best_sarima_id": best_sarima_id,
        },
    )
    print("[full_run] completed")


def _load_metrics_if_exists(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def main() -> None:
    args = parse_args()

    setup_base = replace(
        ForecastSetup(),
        input_csv=args.input_csv,
        output_root=args.output_root,
        market_area=args.market_area,
        local_timezone=args.local_timezone,
        origin_hour_local=args.origin_hour_local,
        horizon_days=args.horizon_days,
    )
    labeled = label_splits(load_target_frame(setup_base), setup_base)

    experiment_dir = setup_base.output_root / "tuning_runs" / args.experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=True)
    write_json(experiment_dir / "config_snapshot.json", setup_base.to_json_dict())
    write_csv(experiment_dir / "split_summary.csv", build_split_summary(labeled))
    write_csv(
        experiment_dir / "origin_summary_full_daily.csv",
        pd.DataFrame(
            [
                {
                    "split": split_name,
                    "origins": len(generate_origins_for_split(setup_base, split_name)),
                    "origin_hour_local": setup_base.origin_hour_local,
                    "origin_step_days": setup_base.origin_step_days,
                    "horizon_days": setup_base.horizon_days,
                }
                for split_name in ("validation", "test")
            ]
        ),
    )

    candidate_lookup = {candidate.candidate_id: candidate for candidate in (SESSION_1_CANDIDATES + SESSION_2_CANDIDATES)}
    write_json(
        experiment_dir / "candidate_registry.json",
        {"session_1": [candidate.to_dict() for candidate in SESSION_1_CANDIDATES], "session_2": [candidate.to_dict() for candidate in SESSION_2_CANDIDATES]},
    )

    run_session_1 = args.stage in {"session1", "all"}
    run_session_2 = args.stage in {"session2", "all"}
    run_full = args.stage in {"full", "all"}

    if run_session_1:
        setup_session_1 = replace(setup_base, origin_step_days=45)
        _run_session(
            session_name="session_1_coarse",
            labeled=labeled,
            setup=setup_session_1,
            split_names=["validation"],
            candidates=SESSION_1_CANDIDATES,
            output_dir=experiment_dir / "session_1_coarse",
            reference_model=args.reference_model,
        )

    if run_session_2:
        setup_session_2 = replace(setup_base, origin_step_days=14)
        _run_session(
            session_name="session_2_refined",
            labeled=labeled,
            setup=setup_session_2,
            split_names=["validation"],
            candidates=SESSION_2_CANDIDATES,
            output_dir=experiment_dir / "session_2_refined",
            reference_model=args.reference_model,
        )

    if run_full:
        session_2_metrics_path = experiment_dir / "session_2_refined" / "metrics_vs_reference.csv"
        session_1_metrics_path = experiment_dir / "session_1_coarse" / "metrics_vs_reference.csv"
        session_2_metrics = _load_metrics_if_exists(session_2_metrics_path)
        session_1_metrics = _load_metrics_if_exists(session_1_metrics_path)

        if session_2_metrics is not None:
            best_arima = _select_best_by_family(session_2_metrics, SESSION_2_CANDIDATES, "arima")
            best_sarima = _select_best_by_family(session_2_metrics, SESSION_2_CANDIDATES, "sarima")
        elif session_1_metrics is not None:
            best_arima = _select_best_by_family(session_1_metrics, SESSION_1_CANDIDATES, "arima")
            best_sarima = _select_best_by_family(session_1_metrics, SESSION_1_CANDIDATES, "sarima")
        else:
            raise FileNotFoundError(
                "No tuning metrics found for selecting best models. Run session1/session2 first or use --stage all."
            )

        _run_full_benchmark(
            experiment_dir=experiment_dir,
            labeled=labeled,
            setup=replace(setup_base, origin_step_days=1),
            reference_model=args.reference_model,
            best_arima_id=best_arima,
            best_sarima_id=best_sarima,
            candidate_lookup=candidate_lookup,
        )

    summary_rows: list[dict[str, object]] = []
    for session_name in ("session_1_coarse", "session_2_refined", "full_run"):
        metrics_path = experiment_dir / session_name / "metrics_vs_reference.csv"
        if not metrics_path.exists():
            continue
        metrics = pd.read_csv(metrics_path)
        split_filter = "validation"
        if session_name == "full_run":
            split_filter = "test"
        part = metrics[metrics["split"] == split_filter].copy()
        if part.empty:
            continue
        best_row = part.sort_values(["mae", "model"]).iloc[0]
        summary_rows.append(
            {
                "session": session_name,
                "split": split_filter,
                "best_model": best_row["model"],
                "best_mae": best_row["mae"],
                "best_rmse": best_row["rmse"],
            }
        )
    if summary_rows:
        write_csv(experiment_dir / "session_best_summary.csv", pd.DataFrame(summary_rows))

    print(f"Experiment completed: {experiment_dir}")


if __name__ == "__main__":
    main()
