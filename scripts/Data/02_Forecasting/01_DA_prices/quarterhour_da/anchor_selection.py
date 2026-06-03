from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.forecast_evaluation import load_candidate_predictions
from hourly_da.core.scenario_generation import (
    choose_official_naive_candidate,
    choose_target_evaluation_slice,
    compute_candidate_selection_summary,
    discover_scenario_candidate_sources,
    select_scenario_candidates,
)


def build_dynamic_hourly_anchor_selection(
    *,
    output_root: Path,
    config: HourlyDAPipelineConfig,
) -> dict[str, Any]:
    discovery = discover_scenario_candidate_sources(output_root)
    candidate_frame = discovery["candidate_frame"].copy()
    predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=config)
    evaluation_choice = choose_target_evaluation_slice(
        predictions,
        preferred_splits=("test", "validation"),
        preferred_lead_day=0,
    )
    official_naive = choose_official_naive_candidate(predictions)
    selection_summary = compute_candidate_selection_summary(
        predictions,
        selection_split=str(evaluation_choice["dataset_split"]),
        selection_lead_day=int(evaluation_choice["lead_day"]),
        official_naive_candidate_key=str(official_naive["selected"]["candidate_key"]),
    )
    selection_bundle = select_scenario_candidates(selection_summary)
    return {
        "discovery": discovery,
        "candidate_frame": candidate_frame,
        "predictions": predictions,
        "evaluation_choice": evaluation_choice,
        "official_naive": official_naive,
        "selection_summary": selection_bundle["selection_summary"].copy(),
        "selected_candidate_keys": list(selection_bundle["selected_candidate_keys"]),
        "role_rows": selection_bundle["role_rows"].copy(),
        "deterministic_candidate_key": selection_bundle["deterministic_candidate_key"],
        "ranking_candidate_key": selection_bundle["ranking_candidate_key"],
        "ranking_runner_up_key": selection_bundle["ranking_runner_up_key"],
    }


def selection_contract_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_name": "dynamic_hourly_anchor_selection",
                "authority_module": "hourly_da.core.scenario_generation",
                "selection_roles": "deterministic_winner, hour_ranking_winner, both",
                "selection_slice_rule": "prefer test D-only; fall back to validation if needed",
                "hardcoded_model_names_allowed": False,
                "notes": (
                    "The quarter-hour extension inherits the hourly scenario-generation candidate discovery and "
                    "selection logic. If one model wins both roles, the downstream layer accepts that result."
                ),
            }
        ]
    )
