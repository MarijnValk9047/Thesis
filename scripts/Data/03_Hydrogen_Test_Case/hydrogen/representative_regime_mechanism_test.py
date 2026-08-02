"""Short observed/counterfactual H2 mechanism bridge for the D-only study."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from .horizon_granularity_comparison import (
    _read_actuals,
    _read_scenarios,
    resolved_hydrogen_config,
    run_rolling_policy,
)
from .plant_parameters import load_hydrogen_config


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "03_Hydrogen_Test_Case"
    / "configs"
    / "representative_regime_h2_mechanism_test.yaml"
)
LOCAL_TZ = "Europe/Amsterdam"
STRICT_MODEL_ID = "lear_lago_direct_dplus4_strict_no_future_1092"
REQUIRED_SCENARIO_COLUMNS = {
    "forecast_origin_utc",
    "delivery_start_utc",
    "lead_day",
    "scenario_set_size",
    "scenario_id",
    "scenario_probability",
    "point_forecast_eur_per_mwh",
    "scenario_price_eur_per_mwh",
}


class H2MechanismError(RuntimeError):
    """Raised when the short H2 mechanism-test contract is violated."""


@dataclass(frozen=True)
class H2CaseArmInputs:
    case_id: str
    arm: str
    episode_days: tuple[str, ...]
    scenario_30: pd.DataFrame
    scenario_10: pd.DataFrame
    actuals: pd.DataFrame
    granularity: str
    counterfactual: bool


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_mechanism_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = _resolve(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("output_policy") != "minimal":
        raise H2MechanismError("H2 mechanism config must use output_policy=minimal.")
    if payload.get("run_class") != "diagnostic_validation":
        raise H2MechanismError("H2 bridge is diagnostic validation only.")
    if payload.get("arms") != ["A_hourly", "B_qh_flat", "C_qh_shape"]:
        raise H2MechanismError("Frozen H2 A/B/C arms changed.")
    if payload.get("policies") != ["stochastic_10", "price_insensitive", "true_pf"]:
        raise H2MechanismError("Frozen H2 policy set changed.")
    if (
        int(payload.get("scenario_count", 0)) != 10
        or payload.get("horizon_lead_days") != [0]
        or bool(payload.get("horizon_sweep"))
        or bool(payload.get("scenario_count_sweep"))
        or payload.get("risk_measure") != "risk_neutral"
        or float(payload.get("cvar_gamma", -1.0)) != 0.0
    ):
        raise H2MechanismError("H2 bridge must remain D-only/S10 without sweeps.")
    claims = payload.get("claims", {})
    if any(bool(claims.get(key, True)) for key in claims):
        raise H2MechanismError("A forbidden H2 result claim was activated.")
    return payload


def _delivery_days(start: str, end: str) -> tuple[str, ...]:
    values = pd.date_range(start, end, freq="D").strftime("%Y-%m-%d").tolist()
    if len(values) != 7:
        raise H2MechanismError("H2 mechanism cases must contain exactly seven days.")
    return tuple(values)


def _delivery_day(frame: pd.DataFrame, column: str = "delivery_start_utc") -> pd.Series:
    return pd.to_datetime(frame[column], utc=True).dt.tz_convert(LOCAL_TZ).dt.date.astype(str)


def _filter_week(frame: pd.DataFrame, days: Sequence[str]) -> pd.DataFrame:
    return frame[_delivery_day(frame).isin(days)].copy()


def _validate_input_bundle(bundle: H2CaseArmInputs) -> None:
    expected_steps = 24 if bundle.granularity == "hourly" else 96
    expected_rows = expected_steps * len(bundle.episode_days)
    for set_size, scenarios in ((30, bundle.scenario_30), (10, bundle.scenario_10)):
        missing = REQUIRED_SCENARIO_COLUMNS - set(scenarios.columns)
        if missing:
            raise H2MechanismError(f"Scenario bundle misses columns: {sorted(missing)}")
        if not scenarios["lead_day"].eq(0).all():
            raise H2MechanismError("H2 mechanism input contains a non-D lead.")
        counts = scenarios.groupby("forecast_origin_utc")["scenario_id"].nunique()
        if not counts.eq(set_size).all():
            raise H2MechanismError(f"H2 scenario count differs from {set_size}.")
        support = scenarios.groupby("forecast_origin_utc")["delivery_start_utc"].nunique()
        if not support.eq(expected_steps).all():
            raise H2MechanismError("H2 scenario path has incomplete daily support.")
        mass = (
            scenarios.drop_duplicates(["forecast_origin_utc", "scenario_id"])
            .groupby("forecast_origin_utc")["scenario_probability"]
            .sum()
        )
        if (mass - 1.0).abs().max() > 1e-10:
            raise H2MechanismError("H2 scenario probability mass differs from one.")
    if bundle.actuals[["forecast_origin_utc", "delivery_start_utc"]].drop_duplicates().shape[0] != expected_rows:
        raise H2MechanismError("H2 actual support differs from one complete week.")


def _repeat_hourly_scenarios_to_qh(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for quarter in range(4):
        copy = frame.copy()
        copy["delivery_start_utc"] = pd.to_datetime(
            copy["delivery_start_utc"], utc=True
        ) + pd.Timedelta(minutes=15 * quarter)
        copy["granularity"] = "quarterhour"
        rows.append(copy)
    return pd.concat(rows, ignore_index=True).sort_values(
        ["forecast_origin_utc", "scenario_id", "delivery_start_utc"]
    )


def _normalise_family_scenarios(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.rename(
        columns={
            "target_timestamp_utc": "delivery_start_utc",
            "point_forecast": "point_forecast_eur_per_mwh",
            "scenario_price": "scenario_price_eur_per_mwh",
        }
    ).copy()
    result["forecast_origin_utc"] = pd.to_datetime(result["forecast_origin_utc"], utc=True)
    result["delivery_start_utc"] = pd.to_datetime(result["delivery_start_utc"], utc=True)
    return result


def _observed_inputs(config: Mapping[str, Any]) -> list[H2CaseArmInputs]:
    root = _resolve(config["strict_qh_run_root"])
    case = config["cases"]["observed_non_extreme"]
    days = _delivery_days(case["week_start"], case["week_end"])
    actual_path = root / "evaluation_actuals.parquet"
    actual_hourly = _filter_week(_read_actuals(actual_path, "hourly"), days)
    actual_hourly = actual_hourly[actual_hourly["lead_day"].eq(0)].copy()
    actual_qh = _filter_week(_read_actuals(actual_path, "quarter_hour"), days)
    actual_qh = actual_qh[actual_qh["lead_day"].eq(0)].copy()
    if float(actual_qh["actual_price_eur_per_mwh"].min()) <= -499.0:
        raise H2MechanismError("Observed economic H2 week contains the excluded extreme price.")
    sets: dict[tuple[str, int], pd.DataFrame] = {}
    for granularity, prefix in (("hourly", "hourly"), ("quarter_hour", "quarterhour")):
        for count in (10, 30):
            frame = _read_scenarios(
                root / f"optimisation_inputs/{prefix}_scenarios_{count}.parquet",
                count,
                [0],
            )
            sets[(granularity, count)] = _filter_week(frame, days)
    bundles = [
        H2CaseArmInputs(
            "observed_non_extreme",
            "A_hourly",
            days,
            sets[("hourly", 30)],
            sets[("hourly", 10)],
            actual_hourly,
            "hourly",
            False,
        ),
        H2CaseArmInputs(
            "observed_non_extreme",
            "B_qh_flat",
            days,
            _repeat_hourly_scenarios_to_qh(sets[("hourly", 30)]),
            _repeat_hourly_scenarios_to_qh(sets[("hourly", 10)]),
            actual_qh,
            "quarter_hour",
            False,
        ),
        H2CaseArmInputs(
            "observed_non_extreme",
            "C_qh_shape",
            days,
            sets[("quarter_hour", 30)],
            sets[("quarter_hour", 10)],
            actual_qh,
            "quarter_hour",
            False,
        ),
    ]
    for bundle in bundles:
        _validate_input_bundle(bundle)
    return bundles


def _overlay_scenarios(
    overlay: pd.DataFrame,
    *,
    path_kind: str,
    scenario_count: int,
) -> pd.DataFrame:
    scenarios = overlay[
        overlay["path_kind"].eq(path_kind)
        & overlay["scenario_set_size"].eq(scenario_count)
    ].copy()
    point_kind = "point_flat" if path_kind == "scenario_flat" else "point_shape"
    points = overlay[overlay["path_kind"].eq(point_kind)][
        ["target_timestamp_utc", "quarterhour_price"]
    ].rename(columns={"quarterhour_price": "point_forecast_eur_per_mwh"})
    scenarios = scenarios.merge(points, on="target_timestamp_utc", validate="many_to_one")
    local_day = pd.to_datetime(scenarios["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.date
    scenarios["forecast_origin_utc"] = pd.to_datetime(
        [pd.Timestamp(day, tz=LOCAL_TZ) - pd.Timedelta(days=1) + pd.Timedelta(hours=8) for day in local_day],
        utc=True,
    )
    return scenarios.rename(
        columns={
            "target_timestamp_utc": "delivery_start_utc",
            "quarterhour_price": "scenario_price_eur_per_mwh",
            "source_profile_id": "source_residual_block_id",
        }
    ).assign(lead_day=0, granularity="quarterhour")


def _counterfactual_inputs(config: Mapping[str, Any]) -> list[H2CaseArmInputs]:
    study_root = _resolve(config["study_run_root"])
    resolved = yaml.safe_load((study_root / "resolved_config.yaml").read_text(encoding="utf-8"))
    family_root = _resolve(resolved["forecast_family_audit"]["accepted_run_root"])
    case = config["cases"]["counterfactual_typical_winter"]
    days = _delivery_days(case["week_start"], case["week_end"])
    week_id = str(case["week_id"])
    overlay = pd.read_parquet(study_root / "counterfactual_qh_overlay.parquet")
    overlay = overlay[overlay["week_id"].eq(week_id)].copy()
    points = pd.read_parquet(family_root / "common_point_forecasts_with_actuals.parquet")
    points = points[
        points["model_id"].eq(STRICT_MODEL_ID)
        & points["delivery_date_local"].isin(days)
    ].copy()
    actual_hourly = points.rename(
        columns={
            "target_timestamp_utc": "delivery_start_utc",
            "actual_price": "actual_price_eur_per_mwh",
        }
    )[["forecast_origin_utc", "delivery_start_utc", "lead_day", "actual_price_eur_per_mwh"]]
    actual_qh_rows = overlay[overlay["path_kind"].eq("counterfactual_actual")].copy()
    local_day = pd.to_datetime(actual_qh_rows["target_timestamp_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.date
    actual_qh_rows["forecast_origin_utc"] = pd.to_datetime(
        [pd.Timestamp(day, tz=LOCAL_TZ) - pd.Timedelta(days=1) + pd.Timedelta(hours=8) for day in local_day],
        utc=True,
    )
    actual_qh = actual_qh_rows.rename(
        columns={
            "target_timestamp_utc": "delivery_start_utc",
            "quarterhour_price": "actual_price_eur_per_mwh",
        }
    ).assign(lead_day=0)[
        ["forecast_origin_utc", "delivery_start_utc", "lead_day", "actual_price_eur_per_mwh"]
    ]
    family_sets = {
        10: pd.read_parquet(family_root / "scenario_prices_long.parquet"),
        30: pd.read_parquet(family_root / "strict_scenario_prices_30.parquet"),
    }
    hourly_sets = {
        count: _normalise_family_scenarios(
            frame[
                frame["model_id"].eq(STRICT_MODEL_ID)
                & frame["delivery_date_local"].isin(days)
            ]
        )
        for count, frame in family_sets.items()
    }
    flat_sets = {count: _overlay_scenarios(overlay, path_kind="scenario_flat", scenario_count=count) for count in (10, 30)}
    shape_sets = {count: _overlay_scenarios(overlay, path_kind="scenario_shape", scenario_count=count) for count in (10, 30)}
    bundles = [
        H2CaseArmInputs(
            "counterfactual_typical_winter", "A_hourly", days,
            hourly_sets[30], hourly_sets[10], actual_hourly, "hourly", True,
        ),
        H2CaseArmInputs(
            "counterfactual_typical_winter", "B_qh_flat", days,
            flat_sets[30], flat_sets[10], actual_qh, "quarter_hour", True,
        ),
        H2CaseArmInputs(
            "counterfactual_typical_winter", "C_qh_shape", days,
            shape_sets[30], shape_sets[10], actual_qh, "quarter_hour", True,
        ),
    ]
    for bundle in bundles:
        _validate_input_bundle(bundle)
    return bundles


def build_mechanism_inputs(config: Mapping[str, Any]) -> list[H2CaseArmInputs]:
    return [*_observed_inputs(config), *_counterfactual_inputs(config)]


def preflight(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = load_mechanism_config(path)
    bundles = build_mechanism_inputs(config)
    return {
        "status": "pass",
        "case_count": len({bundle.case_id for bundle in bundles}),
        "arm_count": len(bundles),
        "policies": config["policies"],
        "horizon_lead_days": [0],
        "scenario_count": 10,
        "horizon_sweep": False,
        "scenario_count_sweep": False,
        "bundles": [
            {
                "case_id": bundle.case_id,
                "arm": bundle.arm,
                "granularity": bundle.granularity,
                "days": len(bundle.episode_days),
                "counterfactual": bundle.counterfactual,
                "scenario_10_origins": int(bundle.scenario_10["forecast_origin_utc"].nunique()),
                "actual_rows": int(len(bundle.actuals)),
            }
            for bundle in bundles
        ],
    }


def _economic_comparisons(daily: pd.DataFrame) -> pd.DataFrame:
    aggregate = daily.groupby(["case_id", "arm", "policy"], as_index=False)[
        "realised_adjusted_profit_ex_terminal_eur"
    ].sum()
    rows = []
    for (case_id, policy), group in aggregate.groupby(["case_id", "policy"]):
        values = group.set_index("arm")["realised_adjusted_profit_ex_terminal_eur"].to_dict()
        if not {"A_hourly", "B_qh_flat", "C_qh_shape"}.issubset(values):
            continue
        rows.append(
            {
                "case_id": case_id,
                "policy": policy,
                "profit_A_hourly_eur": values["A_hourly"],
                "profit_B_qh_flat_eur": values["B_qh_flat"],
                "profit_C_qh_shape_eur": values["C_qh_shape"],
                "delta_qh_market_profit_eur": values["B_qh_flat"] - values["A_hourly"],
                "delta_shape_profit_eur": values["C_qh_shape"] - values["B_qh_flat"],
                "delta_total_profit_eur": values["C_qh_shape"] - values["A_hourly"],
                "positive_means_improvement": True,
                "economic_improvement_required": False,
            }
        )
    return pd.DataFrame(rows)


def _benchmark_comparisons(daily: pd.DataFrame) -> pd.DataFrame:
    aggregate = daily.groupby(["case_id", "arm", "policy"], as_index=False)[
        "realised_adjusted_profit_ex_terminal_eur"
    ].sum()
    rows = []
    for (case_id, arm), group in aggregate.groupby(["case_id", "arm"]):
        values = group.set_index("policy")["realised_adjusted_profit_ex_terminal_eur"].to_dict()
        if not {"stochastic_10", "price_insensitive", "true_pf"}.issubset(values):
            continue
        rows.append(
            {
                "case_id": case_id,
                "arm": arm,
                "stochastic_10_profit_eur": values["stochastic_10"],
                "price_insensitive_profit_eur": values["price_insensitive"],
                "true_pf_profit_eur": values["true_pf"],
                "uplift_vs_price_insensitive_eur": (
                    values["stochastic_10"] - values["price_insensitive"]
                ),
                "perfect_foresight_regret_eur": (
                    values["true_pf"] - values["stochastic_10"]
                ),
                "economic_improvement_required": False,
            }
        )
    return pd.DataFrame(rows)


def run_mechanism_test(
    config_path: str | Path,
    *,
    run_id: str,
    selected_cases: Sequence[str] = (),
    selected_arms: Sequence[str] = (),
    selected_policies: Sequence[str] = (),
) -> dict[str, Any]:
    config = load_mechanism_config(config_path)
    config_path = _resolve(config_path)
    bundles = build_mechanism_inputs(config)
    cases = set(selected_cases or config["cases"].keys())
    arms = set(selected_arms or config["arms"])
    policies = list(selected_policies or config["policies"])
    bundles = [bundle for bundle in bundles if bundle.case_id in cases and bundle.arm in arms]
    if not bundles or not policies:
        raise H2MechanismError("No H2 mechanism trajectories were selected.")
    output_root = _resolve(config["output_root"]) / run_id
    declaration = {
        "output_root": str(output_root.relative_to(REPO_ROOT)),
        "trajectory_count": len(bundles) * len(policies),
        "estimated_daily_solves": len(bundles) * len(policies) * 7 * 2,
        "estimated_size": "minimal daily and solver summaries, normally <10 MB",
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": config["lineage_role"],
    }
    output_root.mkdir(parents=True, exist_ok=False)
    _write_json(output_root / "output_declaration.json", declaration)
    _write_json(
        output_root / "input_manifest.json",
        {
            "config_sha256": _sha256(config_path),
            "strict_qh_run_summary_sha256": _sha256(
                _resolve(config["strict_qh_run_root"]) / "run_summary.json"
            ),
            "study_run_summary_sha256": _sha256(
                _resolve(config["study_run_root"]) / "run_summary.json"
            ),
        },
    )
    base = load_hydrogen_config(_resolve(config["base_hydrogen_config"]))
    daily_frames = []
    solver_frames = []
    metadata_rows = []
    failures = []
    started = time.perf_counter()
    for bundle in bundles:
        hydrogen_config = resolved_hydrogen_config(
            base,
            granularity=bundle.granularity,
            horizon_mode="D_only",
            comparison_config=config,
        )
        for policy in policies:
            try:
                daily, _dispatch, solver, metadata = run_rolling_policy(
                    config_id=bundle.arm,
                    policy=policy,
                    episode_id=bundle.case_id,
                    episode_days=list(bundle.episode_days),
                    scenario_30=bundle.scenario_30,
                    scenario_10=bundle.scenario_10,
                    actuals=bundle.actuals,
                    hydrogen_config=hydrogen_config,
                    comparison_config=config,
                    run_id=run_id,
                )
                daily.insert(0, "counterfactual", bundle.counterfactual)
                daily.insert(0, "arm", bundle.arm)
                daily.insert(0, "case_id", bundle.case_id)
                solver.insert(0, "counterfactual", bundle.counterfactual)
                solver.insert(0, "arm", bundle.arm)
                solver.insert(0, "case_id", bundle.case_id)
                daily_frames.append(daily)
                solver_frames.append(solver)
                metadata_rows.append(metadata)
            except Exception as exc:  # noqa: BLE001 - preserve every solver/data failure as evidence
                failures.append(
                    {
                        "case_id": bundle.case_id,
                        "arm": bundle.arm,
                        "policy": policy,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    solver = pd.concat(solver_frames, ignore_index=True) if solver_frames else pd.DataFrame()
    comparisons = _economic_comparisons(daily) if not daily.empty else pd.DataFrame()
    benchmarks = _benchmark_comparisons(daily) if not daily.empty else pd.DataFrame()
    daily.to_csv(output_root / "daily_results.csv", index=False)
    solver.to_csv(output_root / "solver_diagnostics.csv", index=False)
    comparisons.to_csv(output_root / "economic_mechanism_comparisons.csv", index=False)
    benchmarks.to_csv(output_root / "benchmark_comparisons.csv", index=False)
    pd.DataFrame(failures).to_csv(output_root / "failures.csv", index=False)
    _write_json(output_root / "episode_metadata.json", metadata_rows)
    summary = {
        "run_id": run_id,
        "status": "pass" if not failures else "incomplete",
        "trajectory_count": len(bundles) * len(policies),
        "completed_count": len(metadata_rows),
        "failure_count": len(failures),
        "benchmark_comparison_count": int(len(benchmarks)),
        "runtime_seconds": time.perf_counter() - started,
        "horizon_sweep": False,
        "scenario_count_sweep": False,
        "scenario_count": 10,
        "economic_improvement_required": False,
        "annualisation_allowed": False,
        "steel_model_choice_affected": False,
    }
    _write_json(output_root / "run_summary.json", summary)
    return {"declaration": declaration, "summary": summary}


__all__ = [
    "DEFAULT_CONFIG",
    "H2CaseArmInputs",
    "H2MechanismError",
    "build_mechanism_inputs",
    "load_mechanism_config",
    "preflight",
    "run_mechanism_test",
]
