from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..data_loader import resolve_execution_period
from ..plant_parameters import HydrogenConfig, load_hydrogen_config
from ..scenario_loader import ScenarioArtifactSpec, load_scenarios_for_artifact, resolve_artifact_specs
from .cache_manager import CacheManager
from .fingerprinting import (
    ExperimentFingerprint,
    build_experiment_fingerprint,
    build_input_slice_fingerprint,
    fingerprint_file,
)

MFRR_EXPECTED_SCENARIO_IDS = (
    "threshold_conservative_p75",
    "threshold_central_p90",
    "threshold_optimistic_max",
)
MFRR_EXPECTED_DIRECTIONS = ("Down", "Up")
MFRR_REQUIRED_CAPACITY_PRICE_UNIT = "EUR_per_MW_per_ISP"
MFRR_REQUIRED_CAPACITY_PRODUCT_STRUCTURE = "observed_daily"
MFRR_REQUIRED_KNOWN_AT_ASSUMPTION = "assumed_nl_incident_reserve_capacity_auction_d_minus_1_09am_europe_amsterdam"
MFRR_REQUIRED_REVENUE_RULE_PROXY = (
    "accepted_times_bid_price_eur_per_mw_isp_times_offered_capacity_mw_times_contract_isp_count"
)
MFRR_EXPORT_USECOLS = [
    "market",
    "product",
    "bidding_stage",
    "forecast_origin_utc",
    "forecast_origin_local",
    "known_at_cutoff_utc",
    "known_at_assumption",
    "delivery_date_local",
    "delivery_start_local",
    "delivery_end_local",
    "delivery_start_utc",
    "delivery_end_utc",
    "delivery_block_id",
    "granularity",
    "direction",
    "scenario_id",
    "scenario_role",
    "scenario_probability",
    "contract_isp_count",
    "capacity_product_structure",
    "capacity_price_unit",
    "acceptance_threshold_price_eur_per_mw_isp",
    "threshold_proxy_name",
    "threshold_model_name",
    "threshold_source_scope",
    "threshold_observed_overlap_flag",
    "average_price_forecast_threshold_anchor",
    "average_price_model_threshold_anchor",
    "average_price_forecast_primary",
    "average_price_model_primary",
    "average_price_forecast_comparator",
    "average_price_model_comparator",
    "scenario_generation_method",
    "market_design_regime",
    "source_data_version",
    "methodological_caveat",
    "quality_flags",
    "capacity_revenue_rule_proxy",
    "energy_bid_obligation_if_accepted",
    "activation_modelling_in_scope",
    "mari_modelling_in_scope",
    "availability_obligation_note",
]


@dataclass(frozen=True)
class InputSliceRequest:
    artifact_id: str
    start_local_date: str
    end_local_date: str
    period_mode: str
    period_labels: tuple[str, ...] = ()
    dataset_split: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": str(self.artifact_id),
            "start_local_date": str(self.start_local_date),
            "end_local_date": str(self.end_local_date),
            "period_mode": str(self.period_mode),
            "period_labels": list(self.period_labels),
            "dataset_split": None if self.dataset_split is None else str(self.dataset_split),
        }


@dataclass(frozen=True)
class ResolvedInputSlice:
    artifact_id: str
    spec: ScenarioArtifactSpec
    scenarios: pd.DataFrame
    market_actuals: pd.DataFrame
    origin_registry: pd.DataFrame
    findings: list[str]
    source_fingerprints: list[dict[str, Any]]
    slice_fingerprint: str
    experiment_fingerprint: ExperimentFingerprint
    cache_status: str
    cache_entry_dir: Path | None
    selected_period: dict[str, Any]


@dataclass(frozen=True)
class ResolvedMFRRCapacityPilotInput:
    export_path: Path
    pilot_rows: pd.DataFrame
    candidate_summary: pd.DataFrame
    acceptance_table: pd.DataFrame
    findings: list[str]
    selected_period: dict[str, Any]
    capacity_offer_big_m_mw: float
    offer_continuous_mw: bool


def _as_config(config_or_path: HydrogenConfig | str | Path) -> HydrogenConfig:
    if isinstance(config_or_path, HydrogenConfig):
        return config_or_path
    return load_hydrogen_config(config_or_path)


def _artifact_config(config: HydrogenConfig, artifact_id: str) -> HydrogenConfig:
    return replace(config, models=replace(config.models, include=(str(artifact_id),)))


def build_request_from_execution_period(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
) -> InputSliceRequest:
    config = _as_config(config_or_path)
    period = resolve_execution_period(config)
    return InputSliceRequest(
        artifact_id=str(artifact_id),
        start_local_date=period.start_local_date.isoformat(),
        end_local_date=period.end_local_date.isoformat(),
        period_mode=str(period.mode),
        period_labels=tuple(str(value) for value in period.labels),
        dataset_split=str(config.experiment.dataset_split) if config.experiment.dataset_split else None,
    )


def _filter_to_local_date_window(
    frame: pd.DataFrame,
    *,
    start_local_date: date,
    end_local_date: date,
) -> pd.DataFrame:
    filtered = frame.copy()
    local_timestamps = pd.to_datetime(filtered["delivery_start_local"], errors="coerce")
    filtered["delivery_local_date"] = local_timestamps.dt.date
    mask = (filtered["delivery_local_date"] >= start_local_date) & (filtered["delivery_local_date"] <= end_local_date)
    filtered = filtered.loc[mask].copy()
    if filtered.empty:
        raise ValueError(
            "Input slice is empty after local-date filtering. "
            f"Requested {start_local_date.isoformat()}..{end_local_date.isoformat()}."
        )
    return filtered.reset_index(drop=True)


def _build_market_actuals(frame: pd.DataFrame) -> pd.DataFrame:
    market = (
        frame[["delivery_start_utc", "delivery_start_local", "delivery_day", "actual_price_eur_per_mwh"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
        .reset_index(drop=True)
    )
    market["delivery_start_utc"] = pd.to_datetime(market["delivery_start_utc"], utc=True, errors="raise")
    return market


def _build_origin_registry(frame: pd.DataFrame) -> pd.DataFrame:
    deduplicated_probabilities = (
        frame[["forecast_origin_utc", "delivery_day", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "delivery_day", "scenario_id"])
        .copy()
    )
    probability_summary = (
        deduplicated_probabilities.groupby(["forecast_origin_utc", "delivery_day"], as_index=False)["scenario_probability"]
        .sum()
        .rename(columns={"scenario_probability": "probability_sum"})
    )
    registry = (
        frame.groupby(["forecast_origin_utc", "delivery_day"], as_index=False)
        .agg(
            delivery_period_count=("delivery_start_utc", "nunique"),
            scenario_count=("scenario_id", "nunique"),
        )
        .merge(probability_summary, on=["forecast_origin_utc", "delivery_day"], how="left")
        .sort_values(["delivery_day", "forecast_origin_utc"])
        .reset_index(drop=True)
    )
    return registry


def _parse_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"Cannot parse boolean-like value: {value!r}")


def _resolve_mfrr_capacity_pilot_dates(
    config: HydrogenConfig,
    *,
    start_local_date: str | None,
    end_local_date: str | None,
) -> tuple[str, str]:
    resolved_start = start_local_date or config.mfrr_capacity_pilot.pilot_start_date
    resolved_end = end_local_date or config.mfrr_capacity_pilot.pilot_end_date
    if not resolved_start or not resolved_end:
        raise ValueError(
            "mFRR capacity pilot start/end dates are required. "
            "Set mfrr_capacity_pilot.pilot_start_date and pilot_end_date or pass explicit overrides."
        )
    return str(resolved_start), str(resolved_end)


def _resolve_mfrr_capacity_export_path(
    config: HydrogenConfig,
    *,
    export_path: str | Path | None,
) -> Path:
    if export_path is not None:
        candidate = Path(export_path)
        return candidate if candidate.is_absolute() else (config.repo_root / candidate).resolve()
    configured = config.mfrr_capacity_pilot.export_path
    if configured is None:
        raise ValueError("mfrr_capacity_pilot.export_path is not configured.")
    return configured


def _validate_mfrr_capacity_timing(frame: pd.DataFrame) -> None:
    forecast_origin_local = pd.to_datetime(frame["forecast_origin_local"], errors="raise")
    if not (
        (forecast_origin_local.dt.hour == 9)
        & (forecast_origin_local.dt.minute == 0)
        & (forecast_origin_local.dt.second == 0)
    ).all():
        raise ValueError("mFRR capacity export does not preserve the repaired D-1 09:00 local timing.")

    forecast_origin_utc = pd.to_datetime(frame["forecast_origin_utc"], utc=True, errors="raise")
    known_at_cutoff_utc = pd.to_datetime(frame["known_at_cutoff_utc"], utc=True, errors="raise")
    expected_utc = forecast_origin_local.dt.tz_convert("UTC")
    if not forecast_origin_utc.equals(expected_utc):
        raise ValueError("forecast_origin_utc does not match the UTC conversion of forecast_origin_local.")
    if not known_at_cutoff_utc.equals(expected_utc):
        raise ValueError("known_at_cutoff_utc does not match the UTC conversion of forecast_origin_local.")
    if not frame["known_at_assumption"].astype(str).eq(MFRR_REQUIRED_KNOWN_AT_ASSUMPTION).all():
        raise ValueError("mFRR capacity export does not preserve the repaired D-1 09:00 known_at_assumption.")


def _validate_mfrr_capacity_contract_metadata(frame: pd.DataFrame) -> None:
    price_units = sorted(frame["capacity_price_unit"].dropna().astype(str).unique().tolist())
    if price_units != [MFRR_REQUIRED_CAPACITY_PRICE_UNIT]:
        raise ValueError(
            "mFRR capacity export must use ENTSO-E-native EUR_per_MW_per_ISP prices. "
            f"Got: {price_units}"
        )

    product_structures = sorted(frame["capacity_product_structure"].dropna().astype(str).unique().tolist())
    if product_structures != [MFRR_REQUIRED_CAPACITY_PRODUCT_STRUCTURE]:
        raise ValueError(
            "mFRR capacity export must be the source-backed daily observed product. "
            f"Got: {product_structures}"
        )

    if not frame["energy_bid_obligation_if_accepted"].astype(bool).all():
        raise ValueError("mFRR capacity export must preserve the mandatory energy-bid obligation flag as True.")
    if frame["activation_modelling_in_scope"].astype(bool).any():
        raise ValueError("mFRR capacity export unexpectedly enables activation modelling.")
    if frame["mari_modelling_in_scope"].astype(bool).any():
        raise ValueError("mFRR capacity export unexpectedly enables MARI modelling.")

    revenue_rule_proxies = sorted(frame["capacity_revenue_rule_proxy"].dropna().astype(str).unique().tolist())
    if revenue_rule_proxies != [MFRR_REQUIRED_REVENUE_RULE_PROXY]:
        raise ValueError(
            "mFRR capacity export has an unexpected revenue rule proxy. "
            f"Got: {revenue_rule_proxies}"
        )

    contract_isp_count = pd.to_numeric(frame["contract_isp_count"], errors="raise")
    if contract_isp_count.isna().any():
        raise ValueError("mFRR capacity export contains missing contract_isp_count values.")
    if (contract_isp_count <= 0).any():
        raise ValueError("mFRR capacity export contains nonpositive contract_isp_count values.")

    delivery_start_utc = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    delivery_end_utc = pd.to_datetime(frame["delivery_end_utc"], utc=True, errors="raise")
    derived_contract_isp_count = (delivery_end_utc - delivery_start_utc) / pd.Timedelta(minutes=15)
    if not derived_contract_isp_count.round(12).eq(contract_isp_count.astype(float)).all():
        raise ValueError("contract_isp_count does not match the delivery_start_utc/delivery_end_utc interval.")


def _validate_mfrr_capacity_slice(frame: pd.DataFrame, *, start_local_date: str, end_local_date: str) -> None:
    if frame.empty:
        raise ValueError("Filtered mFRR capacity pilot slice is empty.")
    if frame["acceptance_threshold_price_eur_per_mw_isp"].isna().any():
        raise ValueError("mFRR capacity pilot slice contains missing acceptance_threshold_price_eur_per_mw_isp values.")
    if sorted(frame["direction"].drop_duplicates().tolist()) != list(MFRR_EXPECTED_DIRECTIONS):
        raise ValueError("mFRR capacity pilot slice does not contain exactly the expected Up/Down directions.")
    if sorted(frame["scenario_id"].drop_duplicates().tolist()) != sorted(MFRR_EXPECTED_SCENARIO_IDS):
        raise ValueError("mFRR capacity pilot slice does not contain exactly the expected scenario IDs.")

    _validate_mfrr_capacity_timing(frame)
    _validate_mfrr_capacity_contract_metadata(frame)

    grouped = frame.groupby(["delivery_date_local", "direction"], as_index=False).agg(
        scenario_count=("scenario_id", "nunique"),
        probability_sum=("scenario_probability", "sum"),
        contract_isp_count_nunique=("contract_isp_count", "nunique"),
    )
    if not (grouped["scenario_count"] == 3).all():
        raise ValueError("Expected exactly three threshold scenarios per delivery_date_local x direction.")
    if not (grouped["probability_sum"] - 1.0).abs().le(1e-9).all():
        raise ValueError("Scenario probabilities must sum to 1 per delivery_date_local x direction.")
    if not (grouped["contract_isp_count_nunique"] == 1).all():
        raise ValueError("contract_isp_count must be unique per delivery_date_local x direction.")

    expected_day_count = len(pd.date_range(start_local_date, end_local_date, freq="D"))
    expected_row_count = expected_day_count * len(MFRR_EXPECTED_DIRECTIONS) * len(MFRR_EXPECTED_SCENARIO_IDS)
    if len(frame) != expected_row_count:
        raise ValueError(
            "Unexpected mFRR capacity pilot slice row count. "
            f"Expected {expected_row_count}, got {len(frame)}."
        )


def _build_mfrr_capacity_candidate_tables(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot = (
        frame.pivot_table(
            index=["delivery_date_local", "direction"],
            columns="scenario_id",
            values="acceptance_threshold_price_eur_per_mw_isp",
            aggfunc="first",
        )
        .reset_index()
    )
    missing_candidate_columns = set(MFRR_EXPECTED_SCENARIO_IDS).difference(pivot.columns)
    if missing_candidate_columns:
        raise ValueError(f"Missing candidate threshold columns: {sorted(missing_candidate_columns)}")

    scenario_frame = frame[
        [
            "delivery_date_local",
            "direction",
            "scenario_id",
            "scenario_probability",
            "contract_isp_count",
            "capacity_price_unit",
            "acceptance_threshold_price_eur_per_mw_isp",
        ]
    ].copy()
    scenario_frame["scenario_probability"] = pd.to_numeric(scenario_frame["scenario_probability"], errors="raise")
    scenario_frame["contract_isp_count"] = pd.to_numeric(scenario_frame["contract_isp_count"], errors="raise").astype(int)
    scenario_frame["acceptance_threshold_price_eur_per_mw_isp"] = pd.to_numeric(
        scenario_frame["acceptance_threshold_price_eur_per_mw_isp"], errors="raise"
    )

    candidate_rows: list[dict[str, Any]] = []
    acceptance_rows: list[dict[str, Any]] = []
    candidate_rank = {scenario_id: idx for idx, scenario_id in enumerate(MFRR_EXPECTED_SCENARIO_IDS)}

    for pivot_row in pivot.to_dict(orient="records"):
        delivery_date_local = str(pivot_row["delivery_date_local"])
        direction = str(pivot_row["direction"])
        threshold_rows = scenario_frame[
            (scenario_frame["delivery_date_local"].astype(str) == delivery_date_local)
            & (scenario_frame["direction"].astype(str) == direction)
        ].copy()
        contract_isp_count = int(threshold_rows["contract_isp_count"].iloc[0])
        capacity_price_unit = str(threshold_rows["capacity_price_unit"].iloc[0])
        for candidate_id in MFRR_EXPECTED_SCENARIO_IDS:
            candidate_price = float(pivot_row[candidate_id])
            threshold_rows["candidate_id"] = candidate_id
            threshold_rows["candidate_price_eur_per_mw_isp"] = candidate_price
            threshold_rows["acceptance_param"] = (
                threshold_rows["candidate_price_eur_per_mw_isp"] <= threshold_rows["acceptance_threshold_price_eur_per_mw_isp"]
            ).astype(int)
            expected_acceptance_probability = float(
                (threshold_rows["scenario_probability"] * threshold_rows["acceptance_param"]).sum()
            )
            expected_revenue_coefficient_eur_per_mw = float(
                candidate_price * expected_acceptance_probability * contract_isp_count
            )
            candidate_rows.append(
                {
                    "delivery_date_local": delivery_date_local,
                    "direction": direction,
                    "candidate_id": candidate_id,
                    "candidate_rank": candidate_rank[candidate_id],
                    "candidate_price_eur_per_mw_isp": candidate_price,
                    "capacity_price_unit": capacity_price_unit,
                    "contract_isp_count": contract_isp_count,
                    "expected_acceptance_probability": expected_acceptance_probability,
                    "expected_revenue_coefficient_eur_per_mw": expected_revenue_coefficient_eur_per_mw,
                }
            )
            for acceptance_row in threshold_rows.to_dict(orient="records"):
                acceptance_rows.append(
                    {
                        "delivery_date_local": delivery_date_local,
                        "direction": direction,
                        "candidate_id": candidate_id,
                        "scenario_id": str(acceptance_row["scenario_id"]),
                        "scenario_probability": float(acceptance_row["scenario_probability"]),
                        "contract_isp_count": int(acceptance_row["contract_isp_count"]),
                        "candidate_price_eur_per_mw_isp": candidate_price,
                        "acceptance_threshold_price_eur_per_mw_isp": float(
                            acceptance_row["acceptance_threshold_price_eur_per_mw_isp"]
                        ),
                        "acceptance_param": int(acceptance_row["acceptance_param"]),
                    }
                )

    candidate_summary = pd.DataFrame(candidate_rows).sort_values(
        ["delivery_date_local", "direction", "candidate_rank"]
    ).reset_index(drop=True)
    acceptance_table = pd.DataFrame(acceptance_rows).sort_values(
        ["delivery_date_local", "direction", "candidate_id", "scenario_id"]
    ).reset_index(drop=True)
    if candidate_summary.empty or acceptance_table.empty:
        raise ValueError("mFRR capacity candidate construction produced empty outputs.")

    for _, group in candidate_summary.groupby(["delivery_date_local", "direction"], as_index=False):
        ordered = group.sort_values("candidate_rank")
        probabilities = ordered["expected_acceptance_probability"].tolist()
        if not (probabilities[0] >= probabilities[1] >= probabilities[2]):
            raise ValueError("Expected acceptance probabilities are not monotone conservative >= central >= optimistic.")
        if (ordered["expected_revenue_coefficient_eur_per_mw"] < -1e-9).any():
            raise ValueError("Expected revenue coefficients must be nonnegative.")
    return candidate_summary, acceptance_table


def _load_mfrr_capacity_export_frame(resolved_export_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(resolved_export_path, usecols=MFRR_EXPORT_USECOLS)
    frame["delivery_date_local"] = frame["delivery_date_local"].astype(str)
    frame["scenario_probability"] = pd.to_numeric(frame["scenario_probability"], errors="raise")
    frame["contract_isp_count"] = pd.to_numeric(frame["contract_isp_count"], errors="raise").astype(int)
    frame["acceptance_threshold_price_eur_per_mw_isp"] = pd.to_numeric(
        frame["acceptance_threshold_price_eur_per_mw_isp"], errors="raise"
    )
    for column in (
        "threshold_observed_overlap_flag",
        "energy_bid_obligation_if_accepted",
        "activation_modelling_in_scope",
        "mari_modelling_in_scope",
    ):
        frame[column] = frame[column].map(_parse_boolish)
    return frame


def resolve_mfrr_capacity_pilot_input(
    config_or_path: HydrogenConfig | str | Path,
    *,
    start_local_date: str | None = None,
    end_local_date: str | None = None,
    export_path: str | Path | None = None,
    require_enabled: bool = False,
) -> ResolvedMFRRCapacityPilotInput:
    config = _as_config(config_or_path)
    if require_enabled and not config.mfrr_capacity_pilot.enabled:
        raise ValueError("mFRR capacity pilot is disabled in the current hydrogen config.")
    if bool(config.mfrr_capacity_pilot.offer_continuous_mw):
        raise ValueError(
            "mfrr_capacity_pilot.offer_continuous_mw=True is not allowed for Dutch incident reserve. "
            "Capacity bids must use integer MW steps."
        )

    resolved_start, resolved_end = _resolve_mfrr_capacity_pilot_dates(
        config,
        start_local_date=start_local_date,
        end_local_date=end_local_date,
    )
    resolved_export_path = _resolve_mfrr_capacity_export_path(config, export_path=export_path)
    if not resolved_export_path.exists():
        raise FileNotFoundError(f"mFRR capacity export not found: {resolved_export_path}")
    frame = _load_mfrr_capacity_export_frame(resolved_export_path)

    mask = (
        frame["delivery_date_local"].between(str(resolved_start), str(resolved_end))
        & frame["direction"].isin(MFRR_EXPECTED_DIRECTIONS)
        & frame["scenario_id"].isin(MFRR_EXPECTED_SCENARIO_IDS)
        & frame["product"].astype(str).eq("mFRRda_capacity")
        & frame["market"].astype(str).eq("NL_incident_reserve")
        & frame["bidding_stage"].astype(str).eq("capacity_auction_D_minus_1_09am")
        & frame["capacity_product_structure"].astype(str).eq(MFRR_REQUIRED_CAPACITY_PRODUCT_STRUCTURE)
        & frame["capacity_price_unit"].astype(str).eq(MFRR_REQUIRED_CAPACITY_PRICE_UNIT)
        & frame["energy_bid_obligation_if_accepted"]
        & ~frame["activation_modelling_in_scope"]
        & ~frame["mari_modelling_in_scope"]
    )
    filtered = frame.loc[mask].copy().reset_index(drop=True)
    _validate_mfrr_capacity_slice(filtered, start_local_date=str(resolved_start), end_local_date=str(resolved_end))
    candidate_summary, acceptance_table = _build_mfrr_capacity_candidate_tables(filtered)

    findings = [
        "frozen_mfrr_capacity_export_consumed_without_recomputation",
        "capacity_auction_timing_preserved_at_d_minus_1_09am_europe_amsterdam",
        "capacity_price_unit_verified_eur_per_mw_per_isp",
        "contract_isp_count_consumed_in_expected_revenue_coefficients",
        "energy_bid_obligation_preserved_as_metadata_only",
        "activation_and_mari_flags_verified_false",
    ]
    selected_period = {
        "start_local_date": str(resolved_start),
        "end_local_date": str(resolved_end),
        "delivery_day_count": int(filtered["delivery_date_local"].nunique()),
    }
    return ResolvedMFRRCapacityPilotInput(
        export_path=resolved_export_path,
        pilot_rows=filtered,
        candidate_summary=candidate_summary,
        acceptance_table=acceptance_table,
        findings=findings,
        selected_period=selected_period,
        capacity_offer_big_m_mw=float(config.mfrr_capacity_pilot.capacity_offer_big_m_mw),
        offer_continuous_mw=bool(config.mfrr_capacity_pilot.offer_continuous_mw),
    )


def load_mfrr_capacity_pilot_inputs(
    export_path: str | Path,
    *,
    start_local_date: str = "2025-07-07",
    end_local_date: str = "2025-07-13",
    capacity_offer_big_m_mw: float | None = None,
    offer_continuous_mw: bool = False,
) -> ResolvedMFRRCapacityPilotInput:
    if bool(offer_continuous_mw):
        raise ValueError(
            "offer_continuous_mw=True is not allowed for Dutch incident reserve. "
            "Capacity bids must use integer MW steps."
        )
    resolved_export_path = Path(export_path)
    if not resolved_export_path.is_absolute():
        resolved_export_path = resolved_export_path.resolve()
    if not resolved_export_path.exists():
        raise FileNotFoundError(f"mFRR capacity export not found: {resolved_export_path}")
    frame = _load_mfrr_capacity_export_frame(resolved_export_path)

    mask = (
        frame["delivery_date_local"].between(str(start_local_date), str(end_local_date))
        & frame["direction"].isin(MFRR_EXPECTED_DIRECTIONS)
        & frame["scenario_id"].isin(MFRR_EXPECTED_SCENARIO_IDS)
        & frame["product"].astype(str).eq("mFRRda_capacity")
        & frame["market"].astype(str).eq("NL_incident_reserve")
        & frame["bidding_stage"].astype(str).eq("capacity_auction_D_minus_1_09am")
        & frame["capacity_product_structure"].astype(str).eq(MFRR_REQUIRED_CAPACITY_PRODUCT_STRUCTURE)
        & frame["capacity_price_unit"].astype(str).eq(MFRR_REQUIRED_CAPACITY_PRICE_UNIT)
        & frame["energy_bid_obligation_if_accepted"]
        & ~frame["activation_modelling_in_scope"]
        & ~frame["mari_modelling_in_scope"]
    )
    filtered = frame.loc[mask].copy().reset_index(drop=True)
    _validate_mfrr_capacity_slice(filtered, start_local_date=str(start_local_date), end_local_date=str(end_local_date))
    candidate_summary, acceptance_table = _build_mfrr_capacity_candidate_tables(filtered)

    findings = [
        "frozen_mfrr_capacity_export_consumed_without_recomputation",
        "capacity_auction_timing_preserved_at_d_minus_1_09am_europe_amsterdam",
        "capacity_price_unit_verified_eur_per_mw_per_isp",
        "contract_isp_count_consumed_in_expected_revenue_coefficients",
        "energy_bid_obligation_preserved_as_metadata_only",
        "activation_and_mari_flags_verified_false",
    ]
    selected_period = {
        "start_local_date": str(start_local_date),
        "end_local_date": str(end_local_date),
        "delivery_day_count": int(filtered["delivery_date_local"].nunique()),
    }
    return ResolvedMFRRCapacityPilotInput(
        export_path=resolved_export_path,
        pilot_rows=filtered,
        candidate_summary=candidate_summary,
        acceptance_table=acceptance_table,
        findings=findings,
        selected_period=selected_period,
        capacity_offer_big_m_mw=float(capacity_offer_big_m_mw) if capacity_offer_big_m_mw is not None else 0.0,
        offer_continuous_mw=bool(offer_continuous_mw),
    )


def resolve_input_slice(
    config_or_path: HydrogenConfig | str | Path,
    *,
    request: InputSliceRequest,
    output_policy_name: str = "minimal",
    cache_root: Path | None = None,
    use_cache: bool = True,
    methodological_approximations: tuple[str, ...] = (),
) -> ResolvedInputSlice:
    config = _as_config(config_or_path)
    run_config = _artifact_config(config, request.artifact_id)
    spec = resolve_artifact_specs(run_config)[0]
    source_fingerprints = [
        fingerprint_file(config.config_path, include_sha256=True).to_dict(),
        fingerprint_file(config.models.scenario_catalog, include_sha256=True).to_dict(),
        fingerprint_file(spec.path, include_sha256=False).to_dict(),
    ]
    if spec.actuals_path is not None:
        source_fingerprints.append(fingerprint_file(spec.actuals_path, include_sha256=False).to_dict())
    slice_fingerprint = build_input_slice_fingerprint(
        artifact_id=request.artifact_id,
        source_fingerprints=source_fingerprints,
        request_payload=request.as_payload(),
        granularity=config.experiment.granularity,
        horizon_mode=config.experiment.horizon_mode,
    )
    experiment_fingerprint = build_experiment_fingerprint(
        config=config,
        input_slice_fingerprint=slice_fingerprint,
        output_policy_name=output_policy_name,
        methodological_approximations=methodological_approximations,
    )
    cache_manager = CacheManager(cache_root) if cache_root is not None else None
    if cache_manager is not None and use_cache:
        cached = cache_manager.load_bundle(
            namespace="input_slices",
            key=slice_fingerprint,
            expected_source_fingerprints=source_fingerprints,
        )
        if cached is not None:
            manifest = cached.manifest
            return ResolvedInputSlice(
                artifact_id=str(request.artifact_id),
                spec=spec,
                scenarios=cached.frames["scenarios"],
                market_actuals=cached.frames["market_actuals"],
                origin_registry=cached.frames["origin_registry"],
                findings=list(manifest.get("findings", [])),
                source_fingerprints=source_fingerprints,
                slice_fingerprint=slice_fingerprint,
                experiment_fingerprint=experiment_fingerprint,
                cache_status="hit",
                cache_entry_dir=cached.entry_dir,
                selected_period=dict(manifest.get("selected_period", {})),
            )

    start_local_date = pd.Timestamp(request.start_local_date).date()
    end_local_date = pd.Timestamp(request.end_local_date).date()
    scenarios, findings = load_scenarios_for_artifact(spec, config=run_config)
    filtered = _filter_to_local_date_window(
        scenarios,
        start_local_date=start_local_date,
        end_local_date=end_local_date,
    )
    market_actuals = _build_market_actuals(filtered)
    origin_registry = _build_origin_registry(filtered)
    selected_period = {
        "period_mode": str(request.period_mode),
        "period_labels": list(request.period_labels),
        "start_local_date": start_local_date.isoformat(),
        "end_local_date": end_local_date.isoformat(),
        "delivery_day_count": int(filtered["delivery_local_date"].nunique()),
    }
    cache_entry_dir: Path | None = None
    if cache_manager is not None:
        bundle = cache_manager.save_bundle(
            namespace="input_slices",
            key=slice_fingerprint,
            frames={
                "scenarios": filtered.drop(columns=["delivery_local_date"]),
                "market_actuals": market_actuals,
                "origin_registry": origin_registry,
            },
            manifest={
                "artifact_id": str(request.artifact_id),
                "model_id": str(spec.model_id),
                "source_fingerprints": source_fingerprints,
                "selected_period": selected_period,
                "findings": findings,
                "slice_fingerprint": slice_fingerprint,
            },
        )
        cache_entry_dir = bundle.entry_dir
    return ResolvedInputSlice(
        artifact_id=str(request.artifact_id),
        spec=spec,
        scenarios=filtered.drop(columns=["delivery_local_date"]),
        market_actuals=market_actuals,
        origin_registry=origin_registry,
        findings=findings,
        source_fingerprints=source_fingerprints,
        slice_fingerprint=slice_fingerprint,
        experiment_fingerprint=experiment_fingerprint,
        cache_status="miss",
        cache_entry_dir=cache_entry_dir,
        selected_period=selected_period,
    )


def resolve_config_period_input(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_id: str,
    output_policy_name: str = "minimal",
    cache_root: Path | None = None,
    use_cache: bool = True,
    methodological_approximations: tuple[str, ...] = (),
) -> ResolvedInputSlice:
    request = build_request_from_execution_period(config_or_path, artifact_id=artifact_id)
    return resolve_input_slice(
        config_or_path,
        request=request,
        output_policy_name=output_policy_name,
        cache_root=cache_root,
        use_cache=use_cache,
        methodological_approximations=methodological_approximations,
    )
