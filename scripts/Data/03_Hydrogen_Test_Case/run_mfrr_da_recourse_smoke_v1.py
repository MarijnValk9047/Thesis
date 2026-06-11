from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from hydrogen.bidding_model import solve_stochastic_hourly_bidding
from hydrogen.mfrr_da_recourse import (
    CapacityResultRecord,
    align_hourly_da_obligations_to_delivery_hours,
    convert_capacity_results_to_hourly_da_obligations,
    normalize_capacity_result_records,
)
from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.scenario_loader import load_scenarios_for_artifact, resolve_artifact_specs


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
SUPPORTED_ARTIFACT = "hourly_lear_strict"
REAL_TARGET_DELIVERY_DAY = "2025-07-11"
MARKET_TZ = "Europe/Amsterdam"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a compact accepted/rejected mFRR-to-DAM recourse smoke test.",
    )
    parser.add_argument(
        "--artifact-id",
        required=True,
        help="Scenario artifact ID. This smoke runner only supports hourly_lear_strict.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the hydrogen config YAML.",
    )
    return parser


def _prepare_config(config_path: Path, artifact_id: str):
    base_config = load_hydrogen_config(config_path)
    return replace(base_config, models=replace(base_config.models, include=(str(artifact_id),)))


def _load_artifact_frame(config, artifact_id: str) -> tuple[Any, pd.DataFrame, list[str]]:
    specs = [spec for spec in resolve_artifact_specs(config) if spec.artifact_key == str(artifact_id)]
    if len(specs) != 1:
        raise ValueError(f"Expected exactly one resolved artifact spec for {artifact_id!r}, got {len(specs)}.")
    spec = specs[0]
    frame, findings = load_scenarios_for_artifact(spec, config=config)
    frame = frame.copy()
    frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    frame["delivery_day"] = frame["delivery_day"].astype(str)
    frame["scenario_id"] = frame["scenario_id"].astype(str)
    return spec, frame, findings


def _complete_origin_registry(frame: pd.DataFrame) -> pd.DataFrame:
    meta = (
        frame.groupby("forecast_origin_utc", as_index=False)
        .agg(
            delivery_day=("delivery_day", "first"),
            delivery_hour_count=("delivery_start_utc", "nunique"),
            scenario_count=("scenario_id", "nunique"),
        )
        .sort_values("forecast_origin_utc")
        .reset_index(drop=True)
    )
    if meta.empty:
        raise ValueError("No forecast origins are available in the selected scenario artifact.")
    expected_scenario_count = int(meta["scenario_count"].mode().iloc[0])
    complete = meta.loc[
        (meta["delivery_hour_count"].astype(int) == 24)
        & (meta["scenario_count"].astype(int) == expected_scenario_count)
    ].copy()
    if complete.empty:
        raise ValueError("No complete 24-hour forecast origins are available for the selected artifact.")
    return complete


def _select_support(frame: pd.DataFrame) -> tuple[str, pd.Timestamp, str]:
    complete = _complete_origin_registry(frame)
    real = complete.loc[complete["delivery_day"].astype(str) == REAL_TARGET_DELIVERY_DAY].copy()
    if not real.empty:
        row = real.sort_values("forecast_origin_utc").iloc[0]
        return "real_aligned_support", pd.Timestamp(row["forecast_origin_utc"]), str(row["delivery_day"])
    fallback = complete.sort_values("forecast_origin_utc").iloc[0]
    return "synthetic_interface_support", pd.Timestamp(fallback["forecast_origin_utc"]), str(fallback["delivery_day"])


def _select_scenarios_for_origin(frame: pd.DataFrame, forecast_origin_utc: pd.Timestamp) -> pd.DataFrame:
    selected = frame.loc[frame["forecast_origin_utc"] == pd.Timestamp(forecast_origin_utc)].copy()
    if selected.empty:
        raise ValueError(f"No scenarios found for forecast_origin_utc={forecast_origin_utc.isoformat()}.")
    if int(selected["delivery_start_utc"].nunique()) != 24:
        raise ValueError("Selected smoke origin does not have exactly 24 unique delivery hours.")
    if int(selected["delivery_day"].nunique()) != 1:
        raise ValueError("Selected smoke origin spans multiple delivery_day values.")
    return selected.sort_values(["scenario_id", "delivery_start_utc"]).reset_index(drop=True)


def _local_delivery_block(delivery_day: str) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    start_local = pd.Timestamp(f"{delivery_day} 00:00:00", tz=MARKET_TZ)
    end_local = start_local + pd.Timedelta(days=1)
    isp_count = int(round(float((end_local.tz_convert("UTC") - start_local.tz_convert("UTC")) / pd.Timedelta(minutes=15))))
    if isp_count <= 0:
        raise ValueError("Computed nonpositive ISP count for the delivery block.")
    return start_local, end_local, isp_count


def _build_branch_record(
    *,
    forecast_origin_utc: pd.Timestamp,
    delivery_day: str,
    case_id: str,
    branch_id: str,
    direction: str,
    offered_capacity_mw: float,
    accepted_capacity_mw: float,
    accepted_flag: bool,
) -> CapacityResultRecord:
    delivery_start_local, delivery_end_local, contract_isp_count = _local_delivery_block(delivery_day)
    return CapacityResultRecord(
        branch_id=str(branch_id),
        forecast_origin=forecast_origin_utc,
        delivery_date=str(delivery_day),
        delivery_start=delivery_start_local,
        delivery_end=delivery_end_local,
        capacity_contract_block_id=f"{case_id}_daily_block",
        capacity_product_structure="observed_daily",
        direction=str(direction),
        offered_capacity_mw=float(offered_capacity_mw),
        accepted_capacity_mw=float(accepted_capacity_mw),
        accepted_flag=bool(accepted_flag),
        capacity_price_eur_per_mw_isp=None,
        contract_isp_count=int(contract_isp_count),
        energy_bid_obligation_if_accepted=True,
        activation_modelled=False,
    )


def _prepare_obligations(
    *,
    record: CapacityResultRecord,
    delivery_timestamps_utc: pd.DatetimeIndex,
    site_max_load_mw: float,
) -> pd.DataFrame:
    normalized = normalize_capacity_result_records([record])
    hourly = convert_capacity_results_to_hourly_da_obligations(normalized)
    return align_hourly_da_obligations_to_delivery_hours(
        hourly,
        delivery_timestamps_utc=delivery_timestamps_utc,
        site_max_load_mw=float(site_max_load_mw),
    )


def _synthetic_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "synthetic_up",
            "accepted_direction": "Up",
            "offered_capacity_mw": 2.0,
            "accepted_capacity_mw": 2.0,
            "historical_mfrr_case": False,
            "notes": "Synthetic interface support only; small Up obligation on supported LEAR Strict day.",
        },
        {
            "case_id": "synthetic_down",
            "accepted_direction": "Down",
            "offered_capacity_mw": 1.0,
            "accepted_capacity_mw": 1.0,
            "historical_mfrr_case": False,
            "notes": "Synthetic interface support only; small Down obligation on supported LEAR Strict day.",
        },
    ]


def _real_cases() -> list[dict[str, Any]]:
    raise NotImplementedError(
        "Real aligned historical mFRR cases are not wired here because the current DAM path still exposes "
        "legacy daily-target semantics rather than the rolling target interface required to represent those cases faithfully."
    )


def _run_branch(
    *,
    config,
    artifact_id: str,
    support_status: str,
    forecast_origin_utc: pd.Timestamp,
    delivery_day: str,
    selected_scenarios: pd.DataFrame,
    case: dict[str, Any],
    branch_label: str,
) -> dict[str, Any]:
    accepted = branch_label == "accepted"
    accepted_capacity = float(case["accepted_capacity_mw"]) if accepted else 0.0
    record = _build_branch_record(
        forecast_origin_utc=forecast_origin_utc,
        delivery_day=delivery_day,
        case_id=str(case["case_id"]),
        branch_id=f"{case['case_id']}_{branch_label}",
        direction=str(case["accepted_direction"]),
        offered_capacity_mw=float(case["offered_capacity_mw"]),
        accepted_capacity_mw=accepted_capacity,
        accepted_flag=accepted,
    )
    delivery_timestamps = pd.DatetimeIndex(
        sorted(selected_scenarios["delivery_start_utc"].drop_duplicates().tolist())
    )
    site_max_load_mw = float(config.hydrogen_system.electrolyser_nominal_mw + config.hydrogen_system.compressor_max_mw)
    obligations = _prepare_obligations(
        record=record,
        delivery_timestamps_utc=delivery_timestamps,
        site_max_load_mw=site_max_load_mw,
    )
    energy_bid_flag = bool(obligations["energy_bid_obligation_created"].astype(bool).any())
    try:
        result = solve_stochastic_hourly_bidding(
            scenarios=selected_scenarios,
            config=config,
            run_id=f"mfrr_da_recourse_smoke::{case['case_id']}::{branch_label}",
            strategy_name="mfrr_da_recourse_smoke",
            toy_case=f"real_scenario::{artifact_id}",
            reserve_obligations_by_hour=obligations,
        )
        summary_row = result.summary.iloc[0].to_dict()
        worst_shortfall = float(result.scenario_economics["shortfall_kg"].astype(float).max())
        reserve_diag = dict(result.reserve_diagnostics)
        required_up = float(reserve_diag.get("max_required_up_reserve_mw") or 0.0)
        required_down = float(reserve_diag.get("max_required_down_reserve_mw") or 0.0)
        min_up = reserve_diag.get("min_available_up_reserve_mw")
        min_down = reserve_diag.get("min_available_down_reserve_mw")
        violated = False
        if required_up > 1e-9 and min_up is not None and float(min_up) + 1e-9 < required_up:
            violated = True
        if required_down > 1e-9 and min_down is not None and float(min_down) + 1e-9 < required_down:
            violated = True
        return {
            "support_status": support_status,
            "artifact_id": artifact_id,
            "forecast_origin_utc": forecast_origin_utc.isoformat(),
            "delivery_day": delivery_day,
            "case_id": str(case["case_id"]),
            "branch_id": str(record.branch_id),
            "historical_mfrr_case": bool(case["historical_mfrr_case"]),
            "solve_status": str(result.solver.status),
            "accepted_direction": str(case["accepted_direction"]),
            "accepted_capacity_mw": float(accepted_capacity),
            "energy_bid_obligation_created": bool(energy_bid_flag),
            "objective_or_expected_adjusted_profit": float(summary_row.get("expected_adjusted_profit_eur")),
            "production_fulfilled_if_available": bool(worst_shortfall <= 1e-9),
            "reserve_hook_active": bool(reserve_diag.get("reserve_hook_active", False)),
            "reserve_constraints_added_count": int(reserve_diag.get("reserve_constraints_added_count", 0)),
            "max_required_up_reserve_mw": float(required_up),
            "max_required_down_reserve_mw": float(required_down),
            "min_available_up_reserve_mw": None if min_up is None else float(min_up),
            "min_available_down_reserve_mw": None if min_down is None else float(min_down),
            "reserve_obligation_violated": bool(violated),
            "notes": str(case["notes"]),
        }
    except Exception as exc:
        return {
            "support_status": support_status,
            "artifact_id": artifact_id,
            "forecast_origin_utc": forecast_origin_utc.isoformat(),
            "delivery_day": delivery_day,
            "case_id": str(case["case_id"]),
            "branch_id": str(record.branch_id),
            "historical_mfrr_case": bool(case["historical_mfrr_case"]),
            "solve_status": f"error:{type(exc).__name__}",
            "accepted_direction": str(case["accepted_direction"]),
            "accepted_capacity_mw": float(accepted_capacity),
            "energy_bid_obligation_created": bool(energy_bid_flag),
            "objective_or_expected_adjusted_profit": None,
            "production_fulfilled_if_available": None,
            "reserve_hook_active": None,
            "reserve_constraints_added_count": None,
            "max_required_up_reserve_mw": float(obligations["accepted_up_reserve_mw_for_da"].max()),
            "max_required_down_reserve_mw": float(obligations["accepted_down_reserve_mw_for_da"].max()),
            "min_available_up_reserve_mw": None,
            "min_available_down_reserve_mw": None,
            "reserve_obligation_violated": None,
            "notes": f"{case['notes']} Solve failed: {exc}",
        }


def run_smoke(*, config_path: Path, artifact_id: str) -> pd.DataFrame:
    if str(artifact_id) != SUPPORTED_ARTIFACT:
        raise ValueError(
            f"This interface smoke runner is restricted to artifact_id={SUPPORTED_ARTIFACT!r}. "
            f"Got {artifact_id!r}."
        )
    config = _prepare_config(config_path, artifact_id)
    _, frame, _ = _load_artifact_frame(config, artifact_id)
    support_status, forecast_origin_utc, delivery_day = _select_support(frame)
    selected_scenarios = _select_scenarios_for_origin(frame, forecast_origin_utc)

    if support_status == "real_aligned_support":
        cases = _real_cases()
    elif support_status == "synthetic_interface_support":
        cases = _synthetic_cases()
    else:
        raise ValueError(f"Unsupported support_status={support_status!r}")

    rows: list[dict[str, Any]] = []
    for case in cases:
        for branch_label in ("accepted", "rejected"):
            rows.append(
                _run_branch(
                    config=config,
                    artifact_id=str(artifact_id),
                    support_status=support_status,
                    forecast_origin_utc=forecast_origin_utc,
                    delivery_day=delivery_day,
                    selected_scenarios=selected_scenarios,
                    case=case,
                    branch_label=branch_label,
                )
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    results = run_smoke(
        config_path=Path(args.config),
        artifact_id=str(args.artifact_id),
    )
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
