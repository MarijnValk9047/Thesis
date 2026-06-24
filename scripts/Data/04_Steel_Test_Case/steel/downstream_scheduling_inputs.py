from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_S2_13_INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S2"
    / "s2_provisional_dev_input"
    / "s2_13_downstream_selected_dev_inputs.csv"
)

S2_13_SELECTED_INPUT_COLUMNS = [
    "input_id",
    "configuration_scope",
    "asset",
    "parameter_name",
    "selected_value",
    "selected_lower",
    "selected_upper",
    "unit",
    "activity_basis",
    "source_card_ids",
    "candidate_evidence_ids",
    "evidence_tier",
    "model_use_status",
    "selection_method",
    "sensitivity_required",
    "tata_exact_claim_allowed",
    "thesis_validation_claim_eligible",
    "limitations",
    "notes",
]


class DownstreamSchedulingInputError(ValueError):
    """Raised when S2.13 governed input rows are incomplete or unsafe."""


@dataclass(frozen=True)
class AssetEnvelope:
    max_tph: float
    min_tph: float
    ramp_tph: float
    min_up_steps: int = 0
    min_down_steps: int = 0


@dataclass(frozen=True)
class DownstreamAssumptions:
    configuration_id: str
    horizon_hours: int
    assumption_set_id: str
    final_product_target_t: float
    bf_bof_share: float
    drp_eaf_share: float
    dsp_share: float
    secondary_delay_steps: int
    casting_delay_steps: int
    reheating_delay_steps: int
    hot_slab_window_steps: int
    slab_yard_capacity_t: float
    initial_cold_slab_inventory_t: float
    terminal_cold_inventory_ratio: float
    initial_hot_slab_inventory_t: float
    terminal_hot_slab_inventory_t: float
    initial_reheated_queue_t: float
    terminal_reheated_queue_t: float
    secondary_yield: float
    casting_yield: float
    reheating_yield: float
    dsp_yield: float
    hsm_yield: float
    secondary: AssetEnvelope
    caster: AssetEnvelope
    dsp: AssetEnvelope
    reheater: AssetEnvelope
    hsm: AssetEnvelope
    secondary_weight_cold_slab_creation: float
    secondary_weight_reheated_tonnage: float
    secondary_weight_startup: float
    secondary_weight_throughput_variation: float
    profile_start_utc: str

    @property
    def q_avg_total_tph(self) -> float:
        return self.final_product_target_t / float(self.horizon_hours)

    @property
    def q_avg_dsp_tph(self) -> float:
        return self.q_avg_total_tph * self.dsp_share

    @property
    def q_avg_hsm_tph(self) -> float:
        return self.q_avg_total_tph * (1.0 - self.dsp_share)


def _read_selected_inputs(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in S2_13_SELECTED_INPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise DownstreamSchedulingInputError(f"S2.13 selected-input file is missing columns: {missing}")
    if frame["input_id"].duplicated().any():
        duplicates = frame.loc[frame["input_id"].duplicated(), "input_id"].tolist()
        raise DownstreamSchedulingInputError(f"S2.13 selected-input file has duplicate input_id rows: {duplicates}")
    return frame


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _numeric(value: Any, *, parameter_name: str) -> float:
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise DownstreamSchedulingInputError(f"Parameter {parameter_name} must be numeric; got {value!r}.") from exc


def _integer(value: Any, *, parameter_name: str) -> int:
    number = _numeric(value, parameter_name=parameter_name)
    if abs(number - round(number)) > 1e-9:
        raise DownstreamSchedulingInputError(f"Parameter {parameter_name} must be an integer step count.")
    return int(round(number))


def _select_row(frame: pd.DataFrame, *, configuration_id: str, parameter_name: str) -> pd.Series:
    selected = frame.loc[
        frame["parameter_name"].eq(parameter_name)
        & frame["configuration_scope"].isin((configuration_id, "both", "global"))
    ].copy()
    if selected.empty:
        raise DownstreamSchedulingInputError(f"Missing S2.13 selected input parameter {parameter_name!r}.")
    selected["_scope_rank"] = selected["configuration_scope"].map({configuration_id: 0, "both": 1, "global": 2})
    selected = selected.sort_values(["_scope_rank", "input_id"])
    return selected.iloc[0]


def _selected_float(frame: pd.DataFrame, *, configuration_id: str, parameter_name: str) -> float:
    row = _select_row(frame, configuration_id=configuration_id, parameter_name=parameter_name)
    return _numeric(row["selected_value"], parameter_name=parameter_name)


def _selected_int(frame: pd.DataFrame, *, configuration_id: str, parameter_name: str) -> int:
    row = _select_row(frame, configuration_id=configuration_id, parameter_name=parameter_name)
    return _integer(row["selected_value"], parameter_name=parameter_name)


def _selected_text(frame: pd.DataFrame, *, configuration_id: str, parameter_name: str) -> str:
    row = _select_row(frame, configuration_id=configuration_id, parameter_name=parameter_name)
    return str(row["selected_value"]).strip()


def _validate_governed_rows(frame: pd.DataFrame) -> None:
    active = frame.loc[frame["model_use_status"].astype(str).str.strip().ne("blocked")]
    bad_tata = active.loc[active["tata_exact_claim_allowed"].map(_as_bool)]
    if not bad_tata.empty:
        raise DownstreamSchedulingInputError("S2.13 selected inputs must not claim Tata-exact status.")
    bad_validation = active.loc[active["thesis_validation_claim_eligible"].map(_as_bool)]
    if not bad_validation.empty:
        raise DownstreamSchedulingInputError("S2.13 selected inputs must not be validation-claim eligible.")
    tier_d = active.loc[active["evidence_tier"].astype(str).str.startswith("D_")]
    bad_tier_d = tier_d.loc[~tier_d["sensitivity_required"].map(_as_bool)]
    if not bad_tier_d.empty:
        ids = bad_tier_d["input_id"].tolist()
        raise DownstreamSchedulingInputError(f"Tier-D S2.13 selected inputs require sensitivity flags: {ids}")


def _asset_envelope(
    frame: pd.DataFrame,
    *,
    configuration_id: str,
    q_avg_tph: float,
    max_name: str,
    min_name: str,
    ramp_name: str,
    min_up_name: str | None = None,
    min_down_name: str | None = None,
) -> AssetEnvelope:
    max_tph = _selected_float(frame, configuration_id=configuration_id, parameter_name=max_name) * q_avg_tph
    min_tph = _selected_float(frame, configuration_id=configuration_id, parameter_name=min_name) * max_tph
    ramp_tph = _selected_float(frame, configuration_id=configuration_id, parameter_name=ramp_name) * max_tph
    min_up = 0 if min_up_name is None else _selected_int(frame, configuration_id=configuration_id, parameter_name=min_up_name)
    min_down = 0 if min_down_name is None else _selected_int(
        frame,
        configuration_id=configuration_id,
        parameter_name=min_down_name,
    )
    return AssetEnvelope(
        max_tph=max_tph,
        min_tph=min_tph,
        ramp_tph=ramp_tph,
        min_up_steps=min_up,
        min_down_steps=min_down,
    )


def load_downstream_assumptions(
    *,
    configuration_id: str,
    horizon_hours: int = 24,
    input_path: str | Path = DEFAULT_S2_13_INPUT_PATH,
) -> DownstreamAssumptions:
    path = Path(input_path)
    frame = _read_selected_inputs(path)
    _validate_governed_rows(frame)

    final_target_24h = _selected_float(
        frame,
        configuration_id=configuration_id,
        parameter_name="common_final_product_target_24h",
    )
    final_target = final_target_24h * float(horizon_hours) / 24.0
    dsp_share = _selected_float(frame, configuration_id=configuration_id, parameter_name="dsp_final_product_share")
    q_avg_total = final_target / float(horizon_hours)
    q_avg_dsp = q_avg_total * dsp_share
    q_avg_hsm = q_avg_total * (1.0 - dsp_share)

    # Shared parameter names are disambiguated by asset below.
    def by_asset(asset: str, parameter_name: str) -> float:
        rows = frame.loc[
            frame["asset"].eq(asset)
            & frame["parameter_name"].eq(parameter_name)
            & frame["configuration_scope"].isin((configuration_id, "both", "global"))
        ].copy()
        if rows.empty:
            raise DownstreamSchedulingInputError(f"Missing S2.13 parameter {asset}.{parameter_name}.")
        rows["_scope_rank"] = rows["configuration_scope"].map({configuration_id: 0, "both": 1, "global": 2})
        return _numeric(rows.sort_values(["_scope_rank", "input_id"]).iloc[0]["selected_value"], parameter_name=f"{asset}.{parameter_name}")

    def by_asset_int(asset: str, parameter_name: str) -> int:
        return int(round(by_asset(asset, parameter_name)))

    def optional_by_asset(asset: str, parameter_name: str) -> float | None:
        rows = frame.loc[
            frame["asset"].eq(asset)
            & frame["parameter_name"].eq(parameter_name)
            & frame["configuration_scope"].isin((configuration_id, "both", "global"))
        ].copy()
        if rows.empty:
            return None
        rows["_scope_rank"] = rows["configuration_scope"].map({configuration_id: 0, "both": 1, "global": 2})
        return _numeric(
            rows.sort_values(["_scope_rank", "input_id"]).iloc[0]["selected_value"],
            parameter_name=f"{asset}.{parameter_name}",
        )

    secondary = AssetEnvelope(
        max_tph=by_asset("secondary_metallurgy", "max_throughput_multiplier") * q_avg_total,
        min_tph=by_asset("secondary_metallurgy", "min_throughput_multiplier") * q_avg_total,
        ramp_tph=by_asset("secondary_metallurgy", "ramp_limit_fraction_of_max_per_hour")
        * by_asset("secondary_metallurgy", "max_throughput_multiplier")
        * q_avg_total,
    )
    caster = AssetEnvelope(
        max_tph=by_asset("continuous_caster", "max_throughput_multiplier") * q_avg_total,
        min_tph=by_asset("continuous_caster", "min_throughput_multiplier") * q_avg_total,
        ramp_tph=by_asset("continuous_caster", "ramp_limit_fraction_of_max_per_hour")
        * by_asset("continuous_caster", "max_throughput_multiplier")
        * q_avg_total,
    )
    dsp = AssetEnvelope(
        max_tph=by_asset("DSP", "max_throughput_multiplier") * q_avg_dsp,
        min_tph=by_asset("DSP", "min_on_fraction_of_max")
        * by_asset("DSP", "max_throughput_multiplier")
        * q_avg_dsp,
        ramp_tph=by_asset("DSP", "ramp_limit_fraction_of_max_per_hour")
        * by_asset("DSP", "max_throughput_multiplier")
        * q_avg_dsp,
        min_up_steps=by_asset_int("DSP", "minimum_up_time_steps"),
        min_down_steps=by_asset_int("DSP", "minimum_down_time_steps"),
    )
    reheater = AssetEnvelope(
        max_tph=by_asset("reheating_furnace", "max_throughput_multiplier") * q_avg_hsm,
        min_tph=by_asset("reheating_furnace", "min_on_fraction_of_max")
        * by_asset("reheating_furnace", "max_throughput_multiplier")
        * q_avg_hsm,
        ramp_tph=by_asset("reheating_furnace", "ramp_limit_fraction_of_max_per_hour")
        * by_asset("reheating_furnace", "max_throughput_multiplier")
        * q_avg_hsm,
        min_up_steps=by_asset_int("reheating_furnace", "minimum_up_time_steps"),
        min_down_steps=by_asset_int("reheating_furnace", "minimum_down_time_steps"),
    )
    hsm = AssetEnvelope(
        max_tph=by_asset("HSM", "max_throughput_multiplier") * q_avg_hsm,
        min_tph=by_asset("HSM", "min_on_fraction_of_max")
        * by_asset("HSM", "max_throughput_multiplier")
        * q_avg_hsm,
        ramp_tph=by_asset("HSM", "ramp_limit_fraction_of_max_per_hour")
        * by_asset("HSM", "max_throughput_multiplier")
        * q_avg_hsm,
        min_up_steps=by_asset_int("HSM", "minimum_up_time_steps"),
        min_down_steps=by_asset_int("HSM", "minimum_down_time_steps"),
    )
    legacy_slab_yard_capacity = (
        by_asset("cold_slab_yard", "capacity_hours_of_average_hsm_route_throughput") * q_avg_hsm
    )
    slab_yard_capacity = optional_by_asset("cold_slab_yard", "capacity_absolute_t")
    if slab_yard_capacity is None:
        slab_yard_capacity = legacy_slab_yard_capacity
    initial_cold_slab_inventory = optional_by_asset("cold_slab_yard", "initial_inventory_absolute_t")
    if initial_cold_slab_inventory is None:
        initial_cold_slab_inventory = (
            by_asset("cold_slab_yard", "initial_inventory_fraction_of_capacity") * legacy_slab_yard_capacity
        )
    if initial_cold_slab_inventory > slab_yard_capacity + 1e-9:
        raise DownstreamSchedulingInputError(
            "Initial cold-slab inventory cannot exceed selected slab-yard capacity."
        )

    return DownstreamAssumptions(
        configuration_id=configuration_id,
        horizon_hours=horizon_hours,
        assumption_set_id="S2_13_TIER_D_CENTRAL_DEV",
        final_product_target_t=final_target,
        bf_bof_share=_selected_float(frame, configuration_id=configuration_id, parameter_name="bf_bof_share"),
        drp_eaf_share=_selected_float(frame, configuration_id=configuration_id, parameter_name="drp_eaf_share"),
        dsp_share=dsp_share,
        secondary_delay_steps=by_asset_int("secondary_metallurgy", "processing_delay_steps"),
        casting_delay_steps=by_asset_int("continuous_caster", "processing_delay_steps"),
        reheating_delay_steps=by_asset_int("reheating_furnace", "processing_delay_steps"),
        hot_slab_window_steps=by_asset_int("hot_slab_transfer", "hot_slab_window_hours"),
        slab_yard_capacity_t=slab_yard_capacity,
        initial_cold_slab_inventory_t=initial_cold_slab_inventory,
        terminal_cold_inventory_ratio=by_asset("cold_slab_yard", "terminal_inventory_ratio_to_initial"),
        initial_hot_slab_inventory_t=by_asset("hot_slab_transfer", "initial_hot_slab_inventory"),
        terminal_hot_slab_inventory_t=by_asset("hot_slab_transfer", "terminal_hot_slab_inventory"),
        initial_reheated_queue_t=by_asset("reheated_slab_queue", "initial_reheated_slab_queue"),
        terminal_reheated_queue_t=by_asset("reheated_slab_queue", "terminal_reheated_slab_queue"),
        secondary_yield=by_asset("secondary_metallurgy", "yield"),
        casting_yield=by_asset("continuous_caster", "yield"),
        reheating_yield=by_asset("reheating_furnace", "yield"),
        dsp_yield=by_asset("DSP", "yield"),
        hsm_yield=by_asset("HSM", "yield"),
        secondary=secondary,
        caster=caster,
        dsp=dsp,
        reheater=reheater,
        hsm=hsm,
        secondary_weight_cold_slab_creation=by_asset("objective", "secondary_weight_cold_slab_creation"),
        secondary_weight_reheated_tonnage=by_asset("objective", "secondary_weight_reheated_tonnage"),
        secondary_weight_startup=by_asset("objective", "secondary_weight_startup"),
        secondary_weight_throughput_variation=by_asset("objective", "secondary_weight_throughput_variation"),
        profile_start_utc=_selected_text(frame, configuration_id=configuration_id, parameter_name="profile_start_utc"),
    )
