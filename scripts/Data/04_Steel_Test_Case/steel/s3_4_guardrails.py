from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from pyomo.environ import Binary, Constraint, Expression, NonNegativeReals, Var, value

from .liquid_steel_smoke_builder import (
    DEFAULT_REVIEW_ROOT,
    DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    LiquidSteelSmokeBuilderError,
    build_liquid_steel_smoke_model,
)
from .model import collect_model_stats


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_S34_GUARDRAIL_INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_candidate_review"
    / "s3_4_eaf_drp_guardrail_dev_inputs.csv"
)

S34_C1_CONFIGURATION_ID = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"
S34_MODE_ID = "s3_4_s4_0a_physical_guardrail_dev"
S34_DEV_ONLY_STATUS_RULE = {
    "approval_status": "provisional_development_only",
    "thesis_usability": "false",
    "reviewer_decision_required": "true",
    "codex_may_decide": "false",
}
S34_REQUIRED_EXECUTABLE_PARAMETERS = {
    "eaf_average_dri_input_capacity",
    "eaf_on_state_min_pu",
    "eaf_on_state_max_pu",
    "eaf_electricity_intensity",
    "eaf_dri_to_crude_steel_efficiency",
    "drp_average_pellet_input_capacity",
    "drp_operating_min_pu",
    "drp_operating_max_pu",
    "drp_pellets_to_dri_yield",
    "drp_ramp_limit_pu_per_h",
    "dri_buffer_duration",
    "dri_buffer_capacity",
    "dri_buffer_initial_fraction",
}


@dataclass(frozen=True)
class S34GuardrailInputs:
    input_path: Path
    eaf_average_dri_input_capacity_tph: float
    eaf_on_state_min_pu: float
    eaf_on_state_max_pu: float
    eaf_electricity_intensity_mwh_per_t_dri: float
    eaf_dri_to_crude_steel_efficiency: float
    eaf_scrap_input_ratio_t_per_t_dri: float
    eaf_oxygen_input_ratio_t_per_t_dri: float
    drp_average_pellet_input_capacity_tph: float
    drp_operating_min_pu: float
    drp_operating_max_pu: float
    drp_pellets_to_dri_yield: float
    drp_electricity_intensity_mwh_per_t_pellets: float
    drp_ng_intensity_nm3_per_t_pellets: float
    drp_oxygen_intensity_t_per_t_pellets: float
    drp_ramp_limit_pu_per_h: float
    dri_buffer_duration_h: float
    dri_buffer_capacity_t: float
    dri_buffer_initial_fraction: float
    consumed_input_ids: tuple[str, ...]
    source_candidate_ids: tuple[str, ...]
    source_card_ids: tuple[str, ...]

    @property
    def eaf_dri_input_min_tph(self) -> float:
        return self.eaf_average_dri_input_capacity_tph * self.eaf_on_state_min_pu

    @property
    def eaf_dri_input_max_tph(self) -> float:
        return self.eaf_average_dri_input_capacity_tph * self.eaf_on_state_max_pu

    @property
    def drp_pellet_input_min_tph(self) -> float:
        return self.drp_average_pellet_input_capacity_tph * self.drp_operating_min_pu

    @property
    def drp_pellet_input_max_tph(self) -> float:
        return self.drp_average_pellet_input_capacity_tph * self.drp_operating_max_pu

    @property
    def drp_pellet_ramp_limit_tph_per_h(self) -> float:
        return self.drp_average_pellet_input_capacity_tph * self.drp_ramp_limit_pu_per_h

    @property
    def dri_buffer_initial_t(self) -> float:
        return self.dri_buffer_capacity_t * self.dri_buffer_initial_fraction


def _normalise_lower(value_in: Any) -> str:
    return str(value_in).strip().lower()


def _split_ids(value_in: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value_in).split(";") if item.strip())


def load_s34_guardrail_inputs(
    input_path: str | Path = DEFAULT_S34_GUARDRAIL_INPUT_PATH,
) -> S34GuardrailInputs:
    path = Path(input_path)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_columns = {
        "input_id",
        "parameter_name",
        "selected_value",
        "executable_status",
        "source_candidate_ids",
        "source_card_ids",
        *S34_DEV_ONLY_STATUS_RULE,
    } - set(frame.columns)
    if missing_columns:
        raise LiquidSteelSmokeBuilderError(f"S3.4 guardrail input file is missing columns: {sorted(missing_columns)}.")

    values: dict[str, float] = {}
    consumed_input_ids: list[str] = []
    candidate_ids: set[str] = set()
    source_card_ids: set[str] = set()
    for row in frame.to_dict(orient="records"):
        parameter_name = str(row["parameter_name"]).strip()
        if parameter_name in values:
            raise LiquidSteelSmokeBuilderError(f"Duplicate S3.4 guardrail parameter: {parameter_name}.")
        for field_name, expected_value in S34_DEV_ONLY_STATUS_RULE.items():
            if _normalise_lower(row[field_name]) != expected_value:
                raise LiquidSteelSmokeBuilderError(
                    f"S3.4 guardrail row {row['input_id']} is not development-only: {field_name}={row[field_name]!r}."
                )
        if parameter_name in S34_REQUIRED_EXECUTABLE_PARAMETERS and _normalise_lower(row["executable_status"]) != "dev_executable_only":
            raise LiquidSteelSmokeBuilderError(
                f"S3.4 guardrail row {row['input_id']} must be dev_executable_only for {parameter_name}."
            )
        selected_value = pd.to_numeric(row["selected_value"], errors="coerce")
        if pd.isna(selected_value):
            raise LiquidSteelSmokeBuilderError(f"S3.4 guardrail row {row['input_id']} has non-numeric selected_value.")
        values[parameter_name] = float(selected_value)
        consumed_input_ids.append(str(row["input_id"]).strip())
        candidate_ids.update(_split_ids(row["source_candidate_ids"]))
        source_card_ids.update(_split_ids(row["source_card_ids"]))

    missing_parameters = S34_REQUIRED_EXECUTABLE_PARAMETERS - set(values)
    if missing_parameters:
        raise LiquidSteelSmokeBuilderError(f"S3.4 guardrail input file is missing parameters: {sorted(missing_parameters)}.")
    if values["eaf_on_state_min_pu"] <= 0.0 or values["eaf_on_state_min_pu"] > values["eaf_on_state_max_pu"]:
        raise LiquidSteelSmokeBuilderError("S3.4 EAF on-state range is invalid.")
    if values["drp_operating_min_pu"] <= 0.0 or values["drp_operating_min_pu"] > values["drp_operating_max_pu"]:
        raise LiquidSteelSmokeBuilderError("S3.4 DRP operating range is invalid.")
    if values["dri_buffer_initial_fraction"] < 0.0 or values["dri_buffer_initial_fraction"] > 1.0:
        raise LiquidSteelSmokeBuilderError("S3.4 DRI buffer initial fraction must stay within [0, 1].")

    return S34GuardrailInputs(
        input_path=path,
        eaf_average_dri_input_capacity_tph=values["eaf_average_dri_input_capacity"],
        eaf_on_state_min_pu=values["eaf_on_state_min_pu"],
        eaf_on_state_max_pu=values["eaf_on_state_max_pu"],
        eaf_electricity_intensity_mwh_per_t_dri=values["eaf_electricity_intensity"],
        eaf_dri_to_crude_steel_efficiency=values["eaf_dri_to_crude_steel_efficiency"],
        eaf_scrap_input_ratio_t_per_t_dri=values.get("eaf_scrap_input_ratio", 0.0),
        eaf_oxygen_input_ratio_t_per_t_dri=values.get("eaf_oxygen_input_ratio", 0.0),
        drp_average_pellet_input_capacity_tph=values["drp_average_pellet_input_capacity"],
        drp_operating_min_pu=values["drp_operating_min_pu"],
        drp_operating_max_pu=values["drp_operating_max_pu"],
        drp_pellets_to_dri_yield=values["drp_pellets_to_dri_yield"],
        drp_electricity_intensity_mwh_per_t_pellets=values.get("drp_electricity_intensity", 0.0),
        drp_ng_intensity_nm3_per_t_pellets=values.get("drp_ng_intensity", 0.0),
        drp_oxygen_intensity_t_per_t_pellets=values.get("drp_oxygen_intensity", 0.0),
        drp_ramp_limit_pu_per_h=values["drp_ramp_limit_pu_per_h"],
        dri_buffer_duration_h=values["dri_buffer_duration"],
        dri_buffer_capacity_t=values["dri_buffer_capacity"],
        dri_buffer_initial_fraction=values["dri_buffer_initial_fraction"],
        consumed_input_ids=tuple(consumed_input_ids),
        source_candidate_ids=tuple(sorted(candidate_ids)),
        source_card_ids=tuple(sorted(source_card_ids)),
    )


def apply_s34_guardrails(model, inputs: S34GuardrailInputs):
    configuration_id = model.s2_metadata.get("configuration_id")
    if configuration_id != S34_C1_CONFIGURATION_ID:
        raise LiquidSteelSmokeBuilderError("S3.4 guardrails may be applied only to the C1 DRP/EAF configuration.")
    required_processes = {"c1_ng_drp", "c1_eaf"}
    if not required_processes.issubset(set(model.PROCESSES.data())):
        raise LiquidSteelSmokeBuilderError("S3.4 guardrails require c1_ng_drp and c1_eaf processes.")

    for process_unit_id in required_processes:
        for time_index in model.TIME:
            if (process_unit_id, time_index) in model.process_min_bound:
                model.process_min_bound[process_unit_id, time_index].deactivate()
            if (process_unit_id, time_index) in model.process_max_bound:
                model.process_max_bound[process_unit_id, time_index].deactivate()
    for time_index in model.TIME:
        if ("DRI_or_HDRI", time_index) in model.internal_material_balance:
            model.internal_material_balance["DRI_or_HDRI", time_index].deactivate()

    time_points = list(model.TIME.data())
    first_time = time_points[0]
    previous_time = {time_points[idx]: time_points[idx - 1] for idx in range(1, len(time_points))}
    eaf_eta = inputs.eaf_dri_to_crude_steel_efficiency
    drp_yield = inputs.drp_pellets_to_dri_yield

    model.s34_eaf_on = Var(model.TIME, domain=Binary)
    model.s34_drp_pellet_input = Var(model.TIME, domain=NonNegativeReals)
    model.s34_dri_buffer_inventory = Var(model.TIME, domain=NonNegativeReals)

    model.s34_eaf_dri_input = Expression(model.TIME, rule=lambda m, t: m.process_activity["c1_eaf", t] / eaf_eta)
    model.s34_eaf_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eaf_electricity_intensity_mwh_per_t_dri * m.s34_eaf_dri_input[t],
    )
    model.s34_eaf_scrap_input_t = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eaf_scrap_input_ratio_t_per_t_dri * m.s34_eaf_dri_input[t],
    )
    model.s34_eaf_oxygen_input_t = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eaf_oxygen_input_ratio_t_per_t_dri * m.s34_eaf_dri_input[t],
    )
    model.s34_drp_dri_output = Expression(model.TIME, rule=lambda m, t: drp_yield * m.s34_drp_pellet_input[t])
    model.s34_drp_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_electricity_intensity_mwh_per_t_pellets * m.s34_drp_pellet_input[t],
    )
    model.s34_drp_ng_nm3 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_ng_intensity_nm3_per_t_pellets * m.s34_drp_pellet_input[t],
    )
    model.s34_drp_oxygen_input_t = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_oxygen_intensity_t_per_t_pellets * m.s34_drp_pellet_input[t],
    )

    model.s34_eaf_dri_input_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.s34_eaf_dri_input[t] <= inputs.eaf_dri_input_max_tph * m.s34_eaf_on[t],
    )
    model.s34_eaf_dri_input_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.s34_eaf_dri_input[t] >= inputs.eaf_dri_input_min_tph * m.s34_eaf_on[t],
    )
    model.s34_drp_pellet_input_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.s34_drp_pellet_input[t] >= inputs.drp_pellet_input_min_tph,
    )
    model.s34_drp_pellet_input_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.s34_drp_pellet_input[t] <= inputs.drp_pellet_input_max_tph,
    )
    model.s34_drp_activity_link = Constraint(
        model.TIME,
        rule=lambda m, t: m.process_activity["c1_ng_drp", t] == m.s34_drp_dri_output[t],
    )
    model.s34_dri_buffer_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.s34_dri_buffer_inventory[t]
        == (inputs.dri_buffer_initial_t if t == first_time else m.s34_dri_buffer_inventory[previous_time[t]])
        + m.s34_drp_dri_output[t]
        - m.s34_eaf_dri_input[t],
    )
    model.s34_dri_buffer_capacity = Constraint(
        model.TIME,
        rule=lambda m, t: m.s34_dri_buffer_inventory[t] <= inputs.dri_buffer_capacity_t,
    )
    model.s34_dri_buffer_terminal = Constraint(
        expr=model.s34_dri_buffer_inventory[time_points[-1]] == inputs.dri_buffer_initial_t
    )

    if len(time_points) > 1:
        model.s34_drp_ramp_up = Constraint(
            time_points[1:],
            rule=lambda m, t: m.s34_drp_pellet_input[t] - m.s34_drp_pellet_input[previous_time[t]]
            <= inputs.drp_pellet_ramp_limit_tph_per_h,
        )
        model.s34_drp_ramp_down = Constraint(
            time_points[1:],
            rule=lambda m, t: m.s34_drp_pellet_input[previous_time[t]] - m.s34_drp_pellet_input[t]
            <= inputs.drp_pellet_ramp_limit_tph_per_h,
        )

    model.s34_guardrail_inputs = inputs
    model.s34_metadata = {
        "guardrail_mode": S34_MODE_ID,
        "configuration_id": configuration_id,
        "input_surface": "s3_4_eaf_drp_guardrail_dev_inputs",
        "thesis_usability": False,
        "approval_status": "provisional_development_only",
        "da_price_logic_active": False,
        "bidding_logic_active": False,
        "stochastic_logic_active": False,
        "detailed_heat_sequencing_active": False,
        "eaf_binary_on_off_active": True,
        "drp_continuous_guardrail_active": True,
        "dri_buffer_guardrail_active": True,
        "consumed_input_ids": list(inputs.consumed_input_ids),
        "source_candidate_ids": list(inputs.source_candidate_ids),
        "source_card_ids": list(inputs.source_card_ids),
        "notes": [
            "Development-only S3.4/S4.0a physical guardrail layer.",
            "Athanasiadis DRP/EAF values are not treated as measured Tata operating truth.",
            "No DA price-taking, bidding, stochastic, CVaR, mFRR, quarter-hour, or detailed heat sequencing logic is active.",
        ],
    }
    model.s34_model_stats = collect_model_stats(model)
    return model


def build_s34_guardrail_smoke_model(
    *,
    horizon_hours: int = 24,
    target_variant: str | None = "feasible_smoke",
    guardrail_input_path: str | Path = DEFAULT_S34_GUARDRAIL_INPUT_PATH,
    provisional_dev_input_root: str | Path = DEFAULT_PROVISIONAL_DEV_INPUT_ROOT,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
):
    inputs = load_s34_guardrail_inputs(guardrail_input_path)
    model = build_liquid_steel_smoke_model(
        configuration_id=S34_C1_CONFIGURATION_ID,
        horizon_hours=horizon_hours,
        target_variant=target_variant,
        provisional_dev_input_root=provisional_dev_input_root,
        review_root=review_root,
        inventory_mode="inactive",
        sensitivity_id=S34_MODE_ID,
    )
    return apply_s34_guardrails(model, inputs)


def summarise_s34_guardrails(model, *, solved: bool) -> dict[str, Any]:
    inputs = model.s34_guardrail_inputs
    summary: dict[str, Any] = {
        "guardrail_mode": model.s34_metadata["guardrail_mode"],
        "solved": solved,
        "variable_count": model.s34_model_stats.variables,
        "binary_count": model.s34_model_stats.binaries,
        "constraint_count": model.s34_model_stats.constraints,
        "eaf_binary_on_off_active": True,
        "drp_continuous_guardrail_active": True,
        "dri_buffer_guardrail_active": True,
        "dri_buffer_capacity_t": inputs.dri_buffer_capacity_t,
        "dri_buffer_initial_t": inputs.dri_buffer_initial_t,
    }
    if not solved:
        return summary

    eaf_on = [float(value(model.s34_eaf_on[t])) for t in model.TIME]
    eaf_dri = [float(value(model.s34_eaf_dri_input[t])) for t in model.TIME]
    drp_pellets = [float(value(model.s34_drp_pellet_input[t])) for t in model.TIME]
    dri_inventory = [float(value(model.s34_dri_buffer_inventory[t])) for t in model.TIME]
    ramp_values = [
        abs(drp_pellets[idx] - drp_pellets[idx - 1])
        for idx in range(1, len(drp_pellets))
    ]
    summary.update(
        {
            "eaf_on_count": int(round(sum(eaf_on))),
            "eaf_off_count": len(eaf_on) - int(round(sum(eaf_on))),
            "eaf_min_bound_hits": sum(
                1 for on_value, dri_value in zip(eaf_on, eaf_dri) if on_value >= 0.5 and abs(dri_value - inputs.eaf_dri_input_min_tph) <= 1e-5
            ),
            "eaf_max_bound_hits": sum(
                1 for on_value, dri_value in zip(eaf_on, eaf_dri) if on_value >= 0.5 and abs(dri_value - inputs.eaf_dri_input_max_tph) <= 1e-5
            ),
            "eaf_electricity_mwh": round(sum(float(value(model.s34_eaf_electricity_mwh[t])) for t in model.TIME), 6),
            "drp_min_bound_hits": sum(1 for item in drp_pellets if abs(item - inputs.drp_pellet_input_min_tph) <= 1e-5),
            "drp_max_bound_hits": sum(1 for item in drp_pellets if abs(item - inputs.drp_pellet_input_max_tph) <= 1e-5),
            "drp_max_ramp_usage_tph": round(max(ramp_values) if ramp_values else 0.0, 6),
            "drp_ramp_limit_tph": inputs.drp_pellet_ramp_limit_tph_per_h,
            "dri_buffer_min_t": round(min(dri_inventory), 6),
            "dri_buffer_max_t": round(max(dri_inventory), 6),
            "dri_buffer_terminal_residual_t": round(dri_inventory[-1] - inputs.dri_buffer_initial_t, 6),
            "production_target_residual_t": round(float(value(model.production_target_residual)), 6),
        }
    )
    return summary
