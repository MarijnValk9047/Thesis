from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from functools import lru_cache

import pandas as pd

from hourly_da.core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_NAME_STAGE_A,
    aggregate_run_label_for_scheme,
    supported_layer2_target_blocks,
)
from hourly_da.core.config import HourlyDAPipelineConfig, MonitoringConfig
from hourly_da.core.external_features import FS3Experiment, build_external_family_catalog, load_external_feature_store
from hourly_da.core.feature_value import (
    _excluded_feature_columns_from_settings_payload,
    _normalized_model_settings_payload,
    apply_inherited_rmae_to_child_run,
    build_fs3_ablation_preflight,
    build_parent_child_comparison_frames,
    feature_family_metadata_payload,
    resolve_parent_stage_run,
)
from hourly_da.core.metrics import pairwise_dm_results_by_reporting_level
from hourly_da.core.pipeline import run_benchmark_suite
from hourly_da.core.reporting import load_csv
from hourly_da.core.run_storage_policy import apply_default_storage_policy, format_storage_summary_lines
from hourly_da.core.schedule import generate_forecast_origins
from hourly_da.core.storage import create_run_directory, write_csv, write_json, write_text
from hourly_da.models.branched import BranchedForecastModel
from hourly_da.models.lear import LEARModel, LEARSettings
from hourly_da.models.registry import build_naive_baseline_models
from hourly_da.models.xgboost_model import XGBoostModel, XGBoostSettings


@dataclass(frozen=True)
class PhaseSpec:
    stage: str
    label: str
    experiment_codes: tuple[str, ...]
    primary_reporting_level: str
    uses_day1_branch: bool
    screen_run_label: str
    confirm_run_label: str


@dataclass(frozen=True)
class FeatureValueContextSpec:
    context_code: str
    stage: str
    model_family: str
    label: str
    family_codes: tuple[str, ...]
    primary_reporting_level: str
    uses_day1_branch: bool
    support_status: str
    support_note: str
    benchmark_ready: bool


FULL_HORIZON_PHASE = PhaseSpec(
    stage="full_horizon",
    label="Future-known full-horizon families",
    experiment_codes=("wa_load_domestic", "wa_load_crossborder", "installed_capacity_crossborder"),
    primary_reporting_level="stitched_all_horizon",
    uses_day1_branch=False,
    screen_run_label="fs3_full_horizon_xgboost_screen",
    confirm_run_label="fs3_full_horizon_confirm",
)

DAY1_PHASE = PhaseSpec(
    stage="day1_only",
    label="Future-known day-1-only families",
    experiment_codes=(
        "da_load_day1_domestic",
        "da_load_day1_crossborder",
        "da_generation_day1_domestic",
        "da_generation_day1_crossborder",
    ),
    primary_reporting_level="d_only",
    uses_day1_branch=True,
    screen_run_label="fs3_day1_branch_xgboost_screen",
    confirm_run_label="fs3_day1_branch_confirm",
)

HISTORICAL_PHASE = PhaseSpec(
    stage="historical",
    label="Historical lagged-only families",
    experiment_codes=(
        "load_history_domestic",
        "load_history_crossborder",
        "generation_history_domestic",
        "generation_history_crossborder",
        "neighbor_price_weekly",
    ),
    primary_reporting_level="stitched_all_horizon",
    uses_day1_branch=False,
    screen_run_label="fs3_historical_xgboost_screen",
    confirm_run_label="fs3_historical_confirm",
)

PHASE_SEQUENCE = (FULL_HORIZON_PHASE, DAY1_PHASE, HISTORICAL_PHASE)
PHASE_BY_STAGE = {phase.stage: phase for phase in PHASE_SEQUENCE}
DAY1_EXPERIMENT_CODES = set(DAY1_PHASE.experiment_codes)
COMBO_PROMOTED_FAMILY_CODES = tuple(
    dict.fromkeys(
        [
            *FULL_HORIZON_PHASE.experiment_codes,
            *DAY1_PHASE.experiment_codes,
            *HISTORICAL_PHASE.experiment_codes,
        ]
    )
)
LEAR_COMBO_BENCHMARK_RUN_LABEL = "lear_fs3_combo_promoted_benchmark"
XGBOOST_COMBO_BENCHMARK_RUN_LABEL = "xgboost_fs3_combo_promoted_benchmark"
FS2_SEED_PARENT_CANDIDATE_LABELS = {
    "lear": "lear_fs2_pruned_candidate_benchmark",
    "xgboost": "xgboost_fs2_pruned_candidate_benchmark",
}
FS2_SEED_PARENT_BASELINE_LABELS = {
    "lear": "lear_fs2_benchmark",
    "xgboost": "xgboost_fs2_benchmark",
}

FEATURE_VALUE_CONTEXT_SPECS = (
    FeatureValueContextSpec(
        context_code="combo_promoted",
        stage="combo",
        model_family="xgboost",
        label="XGBoost FS3 all-exogenous combo bundle",
        family_codes=COMBO_PROMOTED_FAMILY_CODES,
        primary_reporting_level="stitched_all_horizon",
        uses_day1_branch=True,
        support_status="complete",
        support_note="Benchmark-ready FS3 combo parent for staged block ablation: Stage A, Layer 1, and optional Layer 2 all run against the dedicated XGBoost combo benchmark.",
        benchmark_ready=True,
    ),
    FeatureValueContextSpec(
        context_code="combo_promoted",
        stage="combo",
        model_family="lear",
        label="LEAR FS3 all-exogenous combo bundle",
        family_codes=COMBO_PROMOTED_FAMILY_CODES,
        primary_reporting_level="stitched_all_horizon",
        uses_day1_branch=True,
        support_status="complete",
        support_note="Benchmark-ready FS3 combo parent for staged block ablation: Stage A, Layer 1, and optional Layer 2 all run against the dedicated LEAR combo benchmark.",
        benchmark_ready=True,
    ),
    FeatureValueContextSpec(
        context_code="day1_crossborder_bundle",
        stage="day1_only",
        model_family="xgboost",
        label="XGBoost FS3 day-1 crossborder bundle",
        family_codes=("da_load_day1_crossborder", "da_generation_day1_crossborder"),
        primary_reporting_level="d_only",
        uses_day1_branch=True,
        support_status="complete",
        support_note="Benchmark-ready first-wave FS3 context: explicit day-1 branch with crossborder load and generation families.",
        benchmark_ready=True,
    ),
    FeatureValueContextSpec(
        context_code="day1_crossborder_bundle",
        stage="day1_only",
        model_family="lear",
        label="LEAR FS3 day-1 crossborder bundle",
        family_codes=("da_load_day1_crossborder", "da_generation_day1_crossborder"),
        primary_reporting_level="d_only",
        uses_day1_branch=True,
        support_status="complete",
        support_note="Benchmark-ready first-wave FS3 context: explicit day-1 branch with crossborder load and generation families.",
        benchmark_ready=True,
    ),
    FeatureValueContextSpec(
        context_code="full_horizon_bundle",
        stage="full_horizon",
        model_family="xgboost",
        label="XGBoost FS3 full-horizon bundle",
        family_codes=("wa_load_crossborder", "installed_capacity_crossborder"),
        primary_reporting_level="stitched_all_horizon",
        uses_day1_branch=False,
        support_status="unsupported",
        support_note="Deferred because the grouped-ablation path is still scoped to the narrower dedicated FS3 contexts, even though the full-horizon family inventory is now carried in the all-exogenous parent benchmark.",
        benchmark_ready=False,
    ),
    FeatureValueContextSpec(
        context_code="full_horizon_bundle",
        stage="full_horizon",
        model_family="lear",
        label="LEAR FS3 full-horizon bundle",
        family_codes=("wa_load_crossborder", "installed_capacity_crossborder"),
        primary_reporting_level="stitched_all_horizon",
        uses_day1_branch=False,
        support_status="unsupported",
        support_note="Deferred because the grouped-ablation path is still scoped to the narrower dedicated FS3 contexts, even though the full-horizon family inventory is now carried in the all-exogenous parent benchmark.",
        benchmark_ready=False,
    ),
    FeatureValueContextSpec(
        context_code="historical_bundle",
        stage="historical",
        model_family="xgboost",
        label="XGBoost FS3 historical bundle",
        family_codes=("load_history_crossborder", "generation_history_crossborder", "neighbor_price_weekly"),
        primary_reporting_level="stitched_all_horizon",
        uses_day1_branch=False,
        support_status="unsupported",
        support_note="Deferred because historical-family coverage and comparability remain diagnostic under the current methodology.",
        benchmark_ready=False,
    ),
    FeatureValueContextSpec(
        context_code="historical_bundle",
        stage="historical",
        model_family="lear",
        label="LEAR FS3 historical bundle",
        family_codes=("load_history_crossborder", "generation_history_crossborder", "neighbor_price_weekly"),
        primary_reporting_level="stitched_all_horizon",
        uses_day1_branch=False,
        support_status="unsupported",
        support_note="Deferred because historical-family coverage and comparability remain diagnostic under the current methodology.",
        benchmark_ready=False,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the phased hourly DA FS3 family workflow on the shared evaluation pipeline.")
    parser.add_argument(
        "--execution-mode",
        type=str,
        default="ordered",
        choices=["ordered", "feature_value", "all"],
        help="Run the legacy ordered FS3 workflow, the Phase 5 FS3 feature-family evaluation path, or both.",
    )
    parser.add_argument(
        "--stage",
        type=str,
        default="all",
        choices=["full_horizon", "day1_only", "historical", "combo", "all"],
    )
    parser.add_argument("--market-area", type=str, default="NL", choices=["BE", "DE", "NL"])
    parser.add_argument("--training-window-days", type=int, default=90)
    parser.add_argument("--min-train-days", type=int, default=30)
    parser.add_argument("--alpha", type=float, default=0.01)
    parser.add_argument("--n-estimators", type=int, default=80)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--fit-time-threshold-sec", type=float, default=20.0)
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show a progress bar for the underlying shared rolling-origin benchmark runs.",
    )
    parser.add_argument(
        "--shortlist-k",
        type=int,
        default=2,
        help="Maximum number of improving benchmark-comparable feature families to confirm per phase after the FS2 model shortlist.",
    )
    parser.add_argument(
        "--coverage-gap-threshold-pct",
        type=float,
        default=1.0,
        help="Maximum allowed coverage drop versus the same-family FS2 reference before the run is labeled diagnostic_non_comparable.",
    )
    parser.add_argument(
        "--promoted-codes",
        nargs="+",
        default=None,
        help="Optional promoted experiment codes for running the combo stage directly.",
    )
    parser.add_argument(
        "--combo-model-family",
        type=str,
        default="all",
        choices=["lear", "xgboost", "all"],
        help="Model family scope for the combo stage. Use a single family for the notebook-specific FS3 parent reruns.",
    )
    parser.add_argument(
        "--combo-run-label",
        type=str,
        default=None,
        help="Optional explicit run label override for the combo stage.",
    )
    parser.add_argument(
        "--feature-value-model-family",
        nargs="+",
        default=["xgboost"],
        choices=["lear", "xgboost", "all"],
        help="Model families to include in the Phase 5 FS3 feature-family evaluation path.",
    )
    parser.add_argument(
        "--feature-value-step",
        type=str,
        default="all",
        choices=["parent", "ablation", "all"],
        help="Run only the FS3 parent benchmark, only the grouped-ablation children/aggregate, or both.",
    )
    parser.add_argument(
        "--ablation-schemes",
        nargs="+",
        default=None,
        choices=[SCHEME_NAME_STAGE_A, SCHEME_NAME_LAYER_1, SCHEME_NAME_LAYER_2],
        help="FS3 combo ablation layers to run. Default uses Stage A and Layer 1; Layer 2 is opt-in.",
    )
    parser.add_argument(
        "--layer2-target-block",
        nargs="+",
        default=None,
        help="Layer 1 block names to drill into with the optional Layer 2 subgroup ablation.",
    )
    parser.add_argument("--smoke-test", action="store_true", help="Run only a small number of origins per split.")
    parser.add_argument(
        "--smoke-origins-per-split",
        type=int,
        default=2,
        help="Origins per split to keep when --smoke-test is enabled.",
    )
    return parser.parse_args()


@lru_cache(maxsize=None)
def _resolve_fs2_seed_parent(market_area: str, model_family: str):
    config = HourlyDAPipelineConfig(market_area=str(market_area))
    family = str(model_family)
    labels = [
        FS2_SEED_PARENT_CANDIDATE_LABELS.get(family),
        FS2_SEED_PARENT_BASELINE_LABELS.get(family),
    ]
    errors: list[str] = []
    for label in labels:
        if not label:
            continue
        try:
            return resolve_parent_stage_run(
                config,
                model_family=family,
                fs_level="FS2",
                parent_run_label=str(label),
            )
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    detail = "; ".join(errors) if errors else "no candidate or baseline FS2 seed labels were configured"
    raise RuntimeError(f"Could not resolve an FS2 seed parent for {family}. {detail}")


def _seeded_settings_payload(
    *,
    market_area: str,
    model_family: str,
    fs_level: str,
    experiment: FS3Experiment | None,
    excluded_blocks: tuple[str, ...] | list[str] | None,
    ablation_scheme_name: str | None,
    ablation_target_block: str | None,
) -> dict[str, object]:
    parent = _resolve_fs2_seed_parent(str(market_area), str(model_family))
    payload = _normalized_model_settings_payload(dict(parent.settings_payload))

    persistent_columns = tuple(str(value) for value in (payload.get("excluded_feature_columns", ()) or ()))
    inherited_blocks = tuple(str(value) for value in (payload.get("excluded_feature_families", ()) or ()))
    inherited_scheme = str(payload.get("ablation_scheme_name")) if payload.get("ablation_scheme_name") else None
    if inherited_blocks and inherited_scheme:
        derived_columns = _excluded_feature_columns_from_settings_payload(
            fs_level=parent.fs_level,
            model_family=parent.model_family,
            settings_payload=payload,
        )
        persistent_columns = tuple(dict.fromkeys([*persistent_columns, *derived_columns]))

    payload["fs_level"] = str(fs_level)
    payload["fs3_experiment"] = experiment
    payload["excluded_feature_columns"] = persistent_columns
    payload["excluded_feature_families"] = tuple(str(value) for value in (excluded_blocks or ()))
    payload["ablation_scheme_name"] = str(ablation_scheme_name) if ablation_scheme_name else None
    payload["ablation_target_block"] = str(ablation_target_block) if ablation_target_block else None
    return payload


def build_lear_model(
    args: argparse.Namespace,
    fs_level: str,
    experiment: FS3Experiment | None = None,
    excluded_blocks: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
) -> LEARModel:
    payload = _seeded_settings_payload(
        market_area=args.market_area,
        model_family="lear",
        fs_level=fs_level,
        experiment=experiment,
        excluded_blocks=excluded_blocks,
        ablation_scheme_name=ablation_scheme_name,
        ablation_target_block=ablation_target_block,
    )
    return LEARModel(LEARSettings(**payload))


def build_xgboost_model(
    args: argparse.Namespace,
    fs_level: str,
    experiment: FS3Experiment | None = None,
    excluded_blocks: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
) -> XGBoostModel:
    payload = _seeded_settings_payload(
        market_area=args.market_area,
        model_family="xgboost",
        fs_level=fs_level,
        experiment=experiment,
        excluded_blocks=excluded_blocks,
        ablation_scheme_name=ablation_scheme_name,
        ablation_target_block=ablation_target_block,
    )
    return XGBoostModel(XGBoostSettings(**payload))


def build_day1_branch_model(
    args: argparse.Namespace,
    family: str,
    name: str,
    d_only_experiment: FS3Experiment | None,
    guidance_experiment: FS3Experiment | None = None,
    excluded_blocks: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
) -> BranchedForecastModel:
    if family == "lear":
        d_only_model = build_lear_model(
            args,
            "FS3" if d_only_experiment is not None else "FS2",
            d_only_experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
        guidance_model = build_lear_model(
            args,
            "FS3" if guidance_experiment is not None else "FS2",
            guidance_experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
    elif family == "xgboost":
        d_only_model = build_xgboost_model(
            args,
            "FS3" if d_only_experiment is not None else "FS2",
            d_only_experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
        guidance_model = build_xgboost_model(
            args,
            "FS3" if guidance_experiment is not None else "FS2",
            guidance_experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
    else:
        raise ValueError(f"Unsupported family for day-1 branch model: {family}")
    return BranchedForecastModel(
        name=name,
        family=family,
        fs_level="FS3",
        d_only_model=d_only_model,
        guidance_model=guidance_model,
    )


def fs3_model_name(family: str, experiment: FS3Experiment) -> str:
    return f"{family}_fs3_{experiment.code}"


def screening_models(args: argparse.Namespace, phase: PhaseSpec, experiments: list[FS3Experiment]) -> list:
    models = [
        *build_naive_baseline_models(),
        build_xgboost_model(args, "FS2"),
    ]
    for experiment in experiments:
        if phase.uses_day1_branch:
            models.append(
                build_day1_branch_model(
                    args,
                    family="xgboost",
                    name=fs3_model_name("xgboost", experiment),
                    d_only_experiment=experiment,
                    guidance_experiment=None,
                )
            )
        else:
            models.append(build_xgboost_model(args, "FS3", experiment))
    return models


def confirmation_models(args: argparse.Namespace, phase: PhaseSpec, experiments: list[FS3Experiment]) -> list:
    models = [
        *build_naive_baseline_models(),
        build_lear_model(args, "FS2"),
        build_xgboost_model(args, "FS2"),
    ]
    for experiment in experiments:
        if phase.uses_day1_branch:
            models.append(
                build_day1_branch_model(
                    args,
                    family="lear",
                    name=fs3_model_name("lear", experiment),
                    d_only_experiment=experiment,
                    guidance_experiment=None,
                )
            )
            models.append(
                build_day1_branch_model(
                    args,
                    family="xgboost",
                    name=fs3_model_name("xgboost", experiment),
                    d_only_experiment=experiment,
                    guidance_experiment=None,
                )
            )
        else:
            models.append(build_lear_model(args, "FS3", experiment))
            models.append(build_xgboost_model(args, "FS3", experiment))
    return models


def combine_experiments(code: str, description: str, experiments: list[FS3Experiment]) -> FS3Experiment:
    direct_columns: list[str] = []
    lagged_columns: list[str] = []
    lag_hours: list[int] = []
    for experiment in experiments:
        for column in experiment.direct_columns:
            if column not in direct_columns:
                direct_columns.append(column)
        for column in experiment.lagged_columns:
            if column not in lagged_columns:
                lagged_columns.append(column)
        for lag in experiment.lag_hours:
            if lag not in lag_hours:
                lag_hours.append(lag)
    return FS3Experiment(
        code=code,
        description=description,
        direct_columns=tuple(direct_columns),
        lagged_columns=tuple(lagged_columns),
        lag_hours=tuple(sorted(lag_hours)),
    )


def combo_target_families(combo_model_family: str) -> tuple[str, ...]:
    if str(combo_model_family) == "all":
        return ("lear", "xgboost")
    return (str(combo_model_family),)


def default_combo_run_label(combo_model_family: str) -> str:
    if str(combo_model_family) == "lear":
        return LEAR_COMBO_BENCHMARK_RUN_LABEL
    if str(combo_model_family) == "xgboost":
        return XGBOOST_COMBO_BENCHMARK_RUN_LABEL
    return "fs3_combo_promoted_confirm"


def combo_models(args: argparse.Namespace, promoted_experiments: list[FS3Experiment]) -> tuple[list, dict[str, object]]:
    day1_promoted = [experiment for experiment in promoted_experiments if experiment.code in DAY1_EXPERIMENT_CODES]
    non_day1_promoted = [experiment for experiment in promoted_experiments if experiment.code not in DAY1_EXPERIMENT_CODES]
    target_families = combo_target_families(args.combo_model_family)
    metadata: dict[str, object] = {
        "promoted_codes": [experiment.code for experiment in promoted_experiments],
        "day1_promoted_codes": [experiment.code for experiment in day1_promoted],
        "non_day1_promoted_codes": [experiment.code for experiment in non_day1_promoted],
        "combo_model_family": str(args.combo_model_family),
        "target_families": list(target_families),
    }

    models = [*build_naive_baseline_models()]
    if "lear" in target_families:
        models.append(build_lear_model(args, "FS2"))
    if "xgboost" in target_families:
        models.append(build_xgboost_model(args, "FS2"))

    if not promoted_experiments:
        return models, metadata

    if day1_promoted:
        d_only_experiment = combine_experiments(
            code="combo_promoted_d_only",
            description="Union of promoted full-horizon, historical, and D-only experiments for the D-only branch.",
            experiments=promoted_experiments,
        )
        guidance_experiment = (
            combine_experiments(
                code="combo_promoted_guidance",
                description="Union of promoted full-horizon and historical experiments for the guidance branch.",
                experiments=non_day1_promoted,
            )
            if non_day1_promoted
            else None
        )
        if "lear" in target_families:
            models.append(
                build_day1_branch_model(
                    args,
                    family="lear",
                    name="lear_fs3_combo_promoted",
                    d_only_experiment=d_only_experiment,
                    guidance_experiment=guidance_experiment,
                )
            )
        if "xgboost" in target_families:
            models.append(
                build_day1_branch_model(
                    args,
                    family="xgboost",
                    name="xgboost_fs3_combo_promoted",
                    d_only_experiment=d_only_experiment,
                    guidance_experiment=guidance_experiment,
                )
            )
        metadata["combo_mode"] = "branched_day1_plus_guidance"
        metadata["d_only_experiment"] = {
            "code": d_only_experiment.code,
            "direct_columns": list(d_only_experiment.direct_columns),
            "lagged_columns": list(d_only_experiment.lagged_columns),
            "lag_hours": list(d_only_experiment.lag_hours),
        }
        metadata["guidance_experiment"] = (
            {
                "code": guidance_experiment.code,
                "direct_columns": list(guidance_experiment.direct_columns),
                "lagged_columns": list(guidance_experiment.lagged_columns),
                "lag_hours": list(guidance_experiment.lag_hours),
            }
            if guidance_experiment is not None
            else None
        )
        return models, metadata

    guidance_experiment = combine_experiments(
        code="combo_promoted",
        description="Union of promoted full-horizon and historical experiments.",
        experiments=non_day1_promoted,
    )
    if "lear" in target_families:
        models.append(build_lear_model(args, "FS3", guidance_experiment))
    if "xgboost" in target_families:
        models.append(build_xgboost_model(args, "FS3", guidance_experiment))
    metadata["combo_mode"] = "shared_full_horizon"
    metadata["guidance_experiment"] = {
        "code": guidance_experiment.code,
        "direct_columns": list(guidance_experiment.direct_columns),
        "lagged_columns": list(guidance_experiment.lagged_columns),
        "lag_hours": list(guidance_experiment.lag_hours),
    }
    return models, metadata


def _baseline_model_for_family(model_family: str) -> str:
    if model_family == "lear":
        return "lear_fs2"
    if model_family == "xgboost":
        return "xgboost_fs2"
    raise ValueError(f"Unsupported model family for FS3 baseline comparison: {model_family}")


def _run_dir(config: HourlyDAPipelineConfig, run_id: str):
    return config.output_root / "runs" / run_id


def build_reporting_level_summary(
    run_dir,
    model_metadata: dict[str, dict[str, str]],
    coverage_gap_threshold_pct: float,
    phase_name: str,
) -> pd.DataFrame:
    metrics = load_csv(run_dir, "metrics_by_reporting_level.csv")
    dm_vs_naive = load_csv(run_dir, "diebold_mariano_by_reporting_level.csv")
    predictions = load_csv(run_dir, "predictions_long.csv")
    relevant_models = sorted(set(model_metadata) | {"lear_fs2", "xgboost_fs2"})
    metrics = metrics[metrics["model"].isin(relevant_models)].copy()
    metrics["phase_name"] = phase_name

    dm_vs_naive_lookup = {
        (str(row["challenger_model"]), str(row["dataset_split"]), str(row["reporting_level"])): row
        for _, row in dm_vs_naive[dm_vs_naive["challenger_model"].isin(relevant_models)].iterrows()
    }

    dm_vs_family_frames: list[pd.DataFrame] = []
    for baseline_model in [model for model in ["lear_fs2", "xgboost_fs2"] if model in metrics["model"].unique()]:
        model_family = str(metrics.loc[metrics["model"] == baseline_model, "model_family"].iloc[0])
        challengers = sorted(
            model
            for model in relevant_models
            if model != baseline_model and model in set(metrics["model"]) and model.startswith(f"{model_family}_")
        )
        if not challengers:
            continue
        family_dm = pairwise_dm_results_by_reporting_level(
            predictions=predictions,
            benchmark_model=baseline_model,
            challenger_models=challengers,
        )
        if family_dm.empty:
            continue
        family_dm["benchmark_model_family"] = model_family
        dm_vs_family_frames.append(family_dm)
    dm_vs_family = pd.concat(dm_vs_family_frames, ignore_index=True) if dm_vs_family_frames else pd.DataFrame()
    dm_vs_family_lookup = {
        (str(row["challenger_model"]), str(row["benchmark_model"]), str(row["dataset_split"]), str(row["reporting_level"])): row
        for _, row in dm_vs_family.iterrows()
    }

    rows: list[dict[str, object]] = []
    for _, metric_row in metrics.iterrows():
        payload = metric_row.to_dict()
        model = str(payload["model"])
        model_family = str(payload["model_family"])
        baseline_model = _baseline_model_for_family(model_family)
        metadata = model_metadata.get(model, {})
        payload["family_code"] = metadata.get("family_code", "")
        payload["evaluation_role"] = metadata.get("evaluation_role", "fs2_reference" if model == baseline_model else "phase_candidate")
        payload["baseline_model"] = baseline_model

        baseline_slice = metrics[
            (metrics["model"] == baseline_model)
            & (metrics["dataset_split"] == payload["dataset_split"])
            & (metrics["reporting_level"] == payload["reporting_level"])
        ]
        baseline_coverage = float(baseline_slice["coverage_pct"].iloc[0]) if not baseline_slice.empty else float("nan")
        payload["baseline_coverage_pct"] = baseline_coverage
        payload["coverage_gap_pct_pts"] = float(baseline_coverage - float(payload["coverage_pct"])) if pd.notna(baseline_coverage) else float("nan")
        payload["coverage_gap_threshold_pct_pts"] = float(coverage_gap_threshold_pct)

        if model == baseline_model:
            payload["comparability_status"] = "benchmark_reference"
            payload["mae_improvement_vs_family_fs2"] = 0.0
            payload["rmse_improvement_vs_family_fs2"] = 0.0
            payload["bias_delta_vs_family_fs2"] = 0.0
        elif baseline_slice.empty:
            payload["comparability_status"] = "baseline_missing"
            payload["mae_improvement_vs_family_fs2"] = float("nan")
            payload["rmse_improvement_vs_family_fs2"] = float("nan")
            payload["bias_delta_vs_family_fs2"] = float("nan")
        else:
            baseline_metrics = baseline_slice.iloc[0]
            payload["comparability_status"] = (
                "benchmark_comparable"
                if float(payload["coverage_gap_pct_pts"]) <= float(coverage_gap_threshold_pct)
                else "diagnostic_non_comparable"
            )
            payload["mae_improvement_vs_family_fs2"] = float(baseline_metrics["mae"]) - float(payload["mae"])
            payload["rmse_improvement_vs_family_fs2"] = float(baseline_metrics["rmse"]) - float(payload["rmse"])
            payload["bias_delta_vs_family_fs2"] = float(payload["bias"]) - float(baseline_metrics["bias"])

        dm_naive_row = dm_vs_naive_lookup.get((model, str(payload["dataset_split"]), str(payload["reporting_level"])))
        payload["benchmark_model"] = dm_naive_row["benchmark_model"] if dm_naive_row is not None else ""
        payload["dm_vs_official_naive_n_obs"] = dm_naive_row["n_obs"] if dm_naive_row is not None else float("nan")
        payload["dm_vs_official_naive_stat"] = dm_naive_row["dm_stat"] if dm_naive_row is not None else float("nan")
        payload["dm_vs_official_naive_p_value"] = dm_naive_row["p_value"] if dm_naive_row is not None else float("nan")

        dm_family_row = dm_vs_family_lookup.get(
            (model, baseline_model, str(payload["dataset_split"]), str(payload["reporting_level"]))
        )
        payload["benchmark_model_family"] = dm_family_row["benchmark_model_family"] if dm_family_row is not None else ""
        payload["dm_vs_family_fs2_n_obs"] = dm_family_row["n_obs"] if dm_family_row is not None else float("nan")
        payload["dm_vs_family_fs2_stat"] = dm_family_row["dm_stat"] if dm_family_row is not None else float("nan")
        payload["dm_vs_family_fs2_p_value"] = dm_family_row["p_value"] if dm_family_row is not None else float("nan")
        rows.append(payload)

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["phase_name", "dataset_split", "reporting_level_sort_order", "model_family", "model"])
        .reset_index(drop=True)
    )


def shortlist_codes(summary: pd.DataFrame, phase: PhaseSpec, shortlist_k: int) -> list[str]:
    if summary.empty:
        return []
    candidates = summary[
        (summary["dataset_split"] == "validation")
        & (summary["reporting_level"] == phase.primary_reporting_level)
        & (summary["model_family"] == "xgboost")
        & (summary["evaluation_role"] == "screen_candidate")
        & (summary["comparability_status"] == "benchmark_comparable")
        & (pd.to_numeric(summary["mae_improvement_vs_family_fs2"], errors="coerce") > 0.0)
    ].copy()
    if candidates.empty:
        return []
    return (
        candidates.sort_values(["mae", "family_code"])["family_code"].drop_duplicates().astype(str).tolist()[:shortlist_k]
    )


def promoted_codes(summary: pd.DataFrame, phase: PhaseSpec) -> list[str]:
    if summary.empty:
        return []
    candidates = summary[
        (summary["dataset_split"] == "validation")
        & (summary["reporting_level"] == phase.primary_reporting_level)
        & (summary["model_family"] == "xgboost")
        & (summary["evaluation_role"] == "phase_candidate")
        & (summary["comparability_status"] == "benchmark_comparable")
        & (pd.to_numeric(summary["mae_improvement_vs_family_fs2"], errors="coerce") > 0.0)
    ].copy()
    if candidates.empty:
        return []
    return (
        candidates.sort_values(["mae", "family_code"])["family_code"].drop_duplicates().astype(str).tolist()
    )


def phase_decision_rows(
    summary: pd.DataFrame,
    phase: PhaseSpec,
    shortlisted: list[str],
    promoted: list[str],
) -> list[dict[str, object]]:
    if summary.empty:
        return []
    candidates = summary[
        (summary["dataset_split"] == "validation")
        & (summary["reporting_level"] == phase.primary_reporting_level)
        & (summary["model_family"] == "xgboost")
        & (summary["evaluation_role"].isin(["screen_candidate", "phase_candidate"]))
    ].copy()
    if candidates.empty:
        return []
    latest_role = (
        candidates.sort_values(["evaluation_role"])
        .drop_duplicates(subset=["family_code"], keep="last")
        .sort_values(["mae", "family_code"])
    )
    rows: list[dict[str, object]] = []
    for _, row in latest_role.iterrows():
        rows.append(
            {
                "phase_name": phase.stage,
                "phase_label": phase.label,
                "primary_reporting_level": phase.primary_reporting_level,
                "family_code": str(row["family_code"]),
                "validation_model": str(row["model"]),
                "validation_coverage_pct": float(row["coverage_pct"]),
                "validation_mae": float(row["mae"]),
                "validation_rmse": float(row["rmse"]),
                "validation_bias": float(row["bias"]),
                "validation_mae_improvement_vs_xgboost_fs2": float(row["mae_improvement_vs_family_fs2"]),
                "validation_comparability_status": str(row["comparability_status"]),
                "shortlisted_for_confirmation": bool(str(row["family_code"]) in shortlisted),
                "promoted_for_combo": bool(str(row["family_code"]) in promoted),
            }
        )
    return rows


def model_metadata_for_phase(experiments: list[FS3Experiment], evaluation_role: str, families: tuple[str, ...]) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for experiment in experiments:
        for family in families:
            metadata[fs3_model_name(family, experiment)] = {"family_code": experiment.code, "evaluation_role": evaluation_role}
    return metadata


def smoke_origin_schedules(config: HourlyDAPipelineConfig, limit: int) -> dict[str, pd.DataFrame]:
    return {
        split_name: generate_forecast_origins(config, split_name).head(int(limit)).reset_index(drop=True)
        for split_name in config.evaluation_splits()
    }


def _rename_model(model, name: str):
    model.name = name
    return model


def build_named_lear_model(
    args: argparse.Namespace,
    *,
    name: str,
    fs_level: str,
    experiment: FS3Experiment | None = None,
    excluded_blocks: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
):
    return _rename_model(
        build_lear_model(
            args,
            fs_level,
            experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        ),
        name,
    )


def build_named_xgboost_model(
    args: argparse.Namespace,
    *,
    name: str,
    fs_level: str,
    experiment: FS3Experiment | None = None,
    excluded_blocks: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
):
    return _rename_model(
        build_xgboost_model(
            args,
            fs_level,
            experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        ),
        name,
    )


def feature_value_context_registry_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "context_code": spec.context_code,
                "stage": spec.stage,
                "model_family": spec.model_family,
                "context_label": spec.label,
                "family_codes": ", ".join(spec.family_codes),
                "primary_reporting_level": spec.primary_reporting_level,
                "uses_day1_branch": bool(spec.uses_day1_branch),
                "support_status": spec.support_status,
                "benchmark_ready": bool(spec.benchmark_ready),
                "support_note": spec.support_note,
            }
            for spec in FEATURE_VALUE_CONTEXT_SPECS
        ]
    ).sort_values(["stage", "model_family", "context_code"]).reset_index(drop=True)


def selected_feature_value_contexts(args: argparse.Namespace) -> list[FeatureValueContextSpec]:
    requested_model_families = {value for value in args.feature_value_model_family if value != "all"}
    contexts: list[FeatureValueContextSpec] = []
    for spec in FEATURE_VALUE_CONTEXT_SPECS:
        if args.stage != "all" and spec.stage != args.stage:
            continue
        if requested_model_families and spec.model_family not in requested_model_families:
            continue
        contexts.append(spec)
    return contexts


def feature_value_model_name(spec: FeatureValueContextSpec) -> str:
    return f"{spec.model_family}_fs3_{spec.context_code}"


def feature_value_parent_run_label(spec: FeatureValueContextSpec) -> str:
    if spec.stage == "combo" and spec.context_code == "combo_promoted":
        return LEAR_COMBO_BENCHMARK_RUN_LABEL if spec.model_family == "lear" else XGBOOST_COMBO_BENCHMARK_RUN_LABEL
    return f"fs3_{spec.stage}_{spec.model_family}_{spec.context_code}_parent"


def feature_value_parent_context_label(spec: FeatureValueContextSpec) -> str:
    return spec.label


def build_feature_value_model(
    args: argparse.Namespace,
    *,
    spec: FeatureValueContextSpec,
    model_name: str,
    experiments: list[FS3Experiment],
    excluded_blocks: tuple[str, ...] | list[str] | None = None,
    ablation_scheme_name: str | None = None,
    ablation_target_block: str | None = None,
):
    if spec.stage == "combo" and spec.context_code == "combo_promoted":
        day1_experiments = [experiment for experiment in experiments if experiment.code in DAY1_EXPERIMENT_CODES]
        non_day1_experiments = [experiment for experiment in experiments if experiment.code not in DAY1_EXPERIMENT_CODES]
        if day1_experiments:
            d_only_experiment = combine_experiments(
                code="combo_promoted_d_only",
                description=f"Combined D-only plus guidance experiment bundle for {spec.label}.",
                experiments=experiments,
            )
            guidance_experiment = (
                combine_experiments(
                    code="combo_promoted_guidance",
                    description=f"Combined guidance experiment bundle for {spec.label}.",
                    experiments=non_day1_experiments,
                )
                if non_day1_experiments
                else None
            )
            return build_day1_branch_model(
                args,
                family=spec.model_family,
                name=model_name,
                d_only_experiment=d_only_experiment,
                guidance_experiment=guidance_experiment,
                excluded_blocks=excluded_blocks,
                ablation_scheme_name=ablation_scheme_name,
                ablation_target_block=ablation_target_block,
            )

    combined_experiment = (
        combine_experiments(
            code=f"{spec.context_code}_bundle",
            description=f"Combined FS3 bundle for {spec.label}.",
            experiments=experiments,
        )
        if experiments
        else None
    )
    if spec.uses_day1_branch:
        return build_day1_branch_model(
            args,
            family=spec.model_family,
            name=model_name,
            d_only_experiment=combined_experiment,
            guidance_experiment=None,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
    if spec.model_family == "lear":
        return build_named_lear_model(
            args,
            name=model_name,
            fs_level="FS3" if combined_experiment is not None else "FS2",
            experiment=combined_experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
    if spec.model_family == "xgboost":
        return build_named_xgboost_model(
            args,
            name=model_name,
            fs_level="FS3" if combined_experiment is not None else "FS2",
            experiment=combined_experiment,
            excluded_blocks=excluded_blocks,
            ablation_scheme_name=ablation_scheme_name,
            ablation_target_block=ablation_target_block,
        )
    raise ValueError(f"Unsupported feature-value model family: {spec.model_family}")


def run_feature_value_parent_context(
    args: argparse.Namespace,
    *,
    config: HourlyDAPipelineConfig,
    spec: FeatureValueContextSpec,
    experiment_map: dict[str, FS3Experiment],
) -> dict[str, object]:
    requested_codes = list(spec.family_codes)
    available_codes = [code for code in requested_codes if code in experiment_map]
    missing_codes = [code for code in requested_codes if code not in experiment_map]
    model_name = feature_value_model_name(spec)
    parent_run_label = feature_value_parent_run_label(spec)
    origin_schedule_by_split = smoke_origin_schedules(config, args.smoke_origins_per_split) if args.smoke_test else None

    if spec.support_status != "complete":
        raise RuntimeError(f"Context {spec.label} is not benchmark-ready: {spec.support_note}")
    if missing_codes:
        raise RuntimeError(f"Missing required experiment definitions for {spec.label}: {missing_codes}")

    parent_model = build_feature_value_model(
        args,
        spec=spec,
        model_name=model_name,
        experiments=[experiment_map[code] for code in available_codes],
    )
    if spec.stage == "combo" and spec.context_code == "combo_promoted":
        combo_args = argparse.Namespace(**vars(args))
        combo_args.combo_model_family = spec.model_family
        parent_models, _ = combo_models(combo_args, [experiment_map[code] for code in available_codes])
    else:
        parent_models = [*build_naive_baseline_models(), parent_model]
    parent_run_id, _, _, _, _ = run_benchmark_suite(
        config=config,
        run_label=parent_run_label,
        models=parent_models,
        include_external_features=True,
        show_progress=args.show_progress,
        progress_label=f"{spec.stage}_{spec.model_family}_parent",
        origin_schedule_by_split=origin_schedule_by_split,
    )
    parent = resolve_parent_stage_run(
        config,
        model_family=spec.model_family,
        fs_level="FS3",
        parent_run_label=parent_run_label,
    )
    return {
        "parent": parent,
        "parent_run_id": parent_run_id,
        "parent_run_label": parent_run_label,
        "requested_codes": requested_codes,
        "available_codes": available_codes,
        "missing_codes": missing_codes,
    }


def resolve_feature_value_parent_context(
    config: HourlyDAPipelineConfig,
    *,
    spec: FeatureValueContextSpec,
    experiment_map: dict[str, FS3Experiment],
) -> dict[str, object]:
    requested_codes = list(spec.family_codes)
    available_codes = [code for code in requested_codes if code in experiment_map]
    missing_codes = [code for code in requested_codes if code not in experiment_map]
    parent_run_label = feature_value_parent_run_label(spec)
    if spec.support_status != "complete":
        raise RuntimeError(f"Context {spec.label} is not benchmark-ready: {spec.support_note}")
    if missing_codes:
        raise RuntimeError(f"Missing required experiment definitions for {spec.label}: {missing_codes}")
    parent = resolve_parent_stage_run(
        config,
        model_family=spec.model_family,
        fs_level="FS3",
        parent_run_label=parent_run_label,
    )
    return {
        "parent": parent,
        "parent_run_id": parent.run_id,
        "parent_run_label": parent_run_label,
        "requested_codes": requested_codes,
        "available_codes": available_codes,
        "missing_codes": missing_codes,
    }


def _ordered_unique(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        text = str(value)
        if text not in ordered:
            ordered.append(text)
    return ordered


def selected_ablation_scheme_requests(
    args: argparse.Namespace,
    *,
    experiment_map: dict[str, FS3Experiment],
) -> list[dict[str, str | None]]:
    requested_schemes = list(args.ablation_schemes or [SCHEME_NAME_STAGE_A, SCHEME_NAME_LAYER_1])
    if args.layer2_target_block and SCHEME_NAME_LAYER_2 not in requested_schemes:
        requested_schemes.append(SCHEME_NAME_LAYER_2)
    requested_schemes = _ordered_unique([str(value) for value in requested_schemes])

    requests: list[dict[str, str | None]] = []
    for scheme_name in requested_schemes:
        if scheme_name != SCHEME_NAME_LAYER_2:
            requests.append({"scheme_name": str(scheme_name), "target_block": None})
            continue
        target_blocks = _ordered_unique([str(value) for value in (args.layer2_target_block or [])])
        if not target_blocks:
            continue
        supported_targets = set(supported_layer2_target_blocks(experiment_map))
        unknown_targets = [block_name for block_name in target_blocks if block_name not in supported_targets]
        if unknown_targets:
            raise ValueError(
                f"Unsupported Layer 2 target blocks: {unknown_targets}. "
                f"Supported targets: {sorted(supported_targets)}"
            )
        for target_block in target_blocks:
            requests.append({"scheme_name": SCHEME_NAME_LAYER_2, "target_block": str(target_block)})
    return requests


def _write_scheme_aggregate_artifacts(
    *,
    aggregate_run_dir,
    by_origin: pd.DataFrame,
    by_reporting_level: pd.DataFrame,
    summary: pd.DataFrame,
    parent_child_map: pd.DataFrame,
    metadata: dict[str, object],
    run_summary_payload: dict[str, object],
    preflight_summary: pd.DataFrame,
    preflight_assignments: pd.DataFrame,
    preflight_block_sizes: pd.DataFrame,
) -> None:
    write_csv(aggregate_run_dir / "feature_family_value_by_origin.csv", by_origin)
    write_csv(aggregate_run_dir / "feature_family_value_by_reporting_level.csv", by_reporting_level)
    write_csv(aggregate_run_dir / "feature_family_value_summary.csv", summary)
    write_csv(aggregate_run_dir / "feature_family_parent_child_map.csv", parent_child_map)
    write_csv(aggregate_run_dir / "ablation_preflight_summary.csv", preflight_summary)
    write_csv(aggregate_run_dir / "ablation_preflight_assignments.csv", preflight_assignments)
    write_csv(aggregate_run_dir / "ablation_preflight_block_sizes.csv", preflight_block_sizes)
    write_json(aggregate_run_dir / "feature_family_value_metadata.json", metadata)
    write_json(aggregate_run_dir / "run_summary.json", run_summary_payload)


def _run_fs3_combo_block_ablation_from_parent(
    args: argparse.Namespace,
    *,
    config: HourlyDAPipelineConfig,
    spec: FeatureValueContextSpec,
    experiment_map: dict[str, FS3Experiment],
    parent_bundle: dict[str, object],
) -> dict[str, object]:
    requested_codes = list(parent_bundle["requested_codes"])
    available_codes = list(parent_bundle["available_codes"])
    missing_codes = list(parent_bundle["missing_codes"])
    parent = parent_bundle["parent"]
    origin_schedule_by_split = smoke_origin_schedules(config, args.smoke_origins_per_split) if args.smoke_test else None
    scheme_requests = selected_ablation_scheme_requests(args, experiment_map=experiment_map)

    if not scheme_requests:
        return {
            "context_code": spec.context_code,
            "stage": spec.stage,
            "model_family": spec.model_family,
            "parent_context_label": feature_value_parent_context_label(spec),
            "parent_run_label": parent.run_label,
            "aggregate_run_id": "",
            "aggregate_run_label": "",
            "parent_run_id": parent.run_id,
            "status": "skipped",
            "benchmark_ready": bool(spec.benchmark_ready),
            "support_note": "No ablation schemes were selected for execution.",
            "smoke_test": bool(args.smoke_test),
            "requested_family_codes": ", ".join(requested_codes),
            "completed_child_count": 0,
            "expected_child_count": 0,
        }

    parent_model = build_feature_value_model(
        args,
        spec=spec,
        model_name=parent.model_name,
        experiments=[experiment_map[code] for code in available_codes],
    )
    aggregate_labels: list[str] = []
    aggregate_ids: list[str] = []
    total_completed = 0
    total_expected = 0
    any_failed = False

    for request in scheme_requests:
        scheme_name = str(request["scheme_name"])
        target_block = str(request["target_block"]) if request["target_block"] else None
        preflight = build_fs3_ablation_preflight(
            config=config,
            model=parent_model,
            experiment_map=experiment_map,
            scheme_name=scheme_name,
            target_block=target_block,
        )
        scheme_payload = dict(preflight["scheme_payload"])
        block_names = [str(block["block_name"]) for block in scheme_payload["blocks"]]
        aggregate_run_label = aggregate_run_label_for_scheme(
            parent_run_label=parent.run_label,
            scheme_name=scheme_name,
            scheme_version=str(scheme_payload["scheme_version"]),
            target_block=target_block,
        )
        aggregate_run_id, aggregate_run_dir = create_run_directory(config.output_root, aggregate_run_label)
        aggregate_labels.append(aggregate_run_label)
        aggregate_ids.append(aggregate_run_id)

        metadata = feature_family_metadata_payload(
            parent,
            aggregate_run_id=aggregate_run_id,
            aggregate_run_label=aggregate_run_label,
            selected_feature_families=block_names,
            smoke_test=args.smoke_test,
            smoke_origins_per_split=args.smoke_origins_per_split if args.smoke_test else None,
        )
        metadata.update(
            {
                "comparison_unit_name": "ablation_block",
                "artifact_field_name": "feature_family",
                "selected_blocks": block_names,
                "ablation_scheme": scheme_payload,
                "scheme_name": scheme_payload["scheme_name"],
                "scheme_version": scheme_payload["scheme_version"],
                "stage_name": scheme_payload["stage_name"],
                "layer_name": scheme_payload["layer_name"],
                "target_block": target_block or "",
                "scheme_hash": scheme_payload["scheme_hash"],
                "static_scheme_hash": scheme_payload["static_scheme_hash"],
                "feature_taxonomy_hash": scheme_payload["feature_taxonomy_hash"],
                "preflight_valid": bool(preflight["valid"]),
                "preflight_summary_rows": preflight["summary"].to_dict(orient="records"),
            }
        )

        if not preflight["valid"]:
            any_failed = True
            metadata.update(
                {
                    "aggregate_status": "invalid",
                    "run_completeness_status": "invalid",
                    "execution_status": "invalid_preflight",
                    "parent_context_label": feature_value_parent_context_label(spec),
                    "stage": spec.stage,
                    "context_code": spec.context_code,
                    "benchmark_ready": bool(spec.benchmark_ready),
                    "support_status": spec.support_status,
                    "support_note": (
                        "Ablation preflight failed because the effective model inputs were not assigned exactly once "
                        "under the current block scheme."
                    ),
                    "requested_family_codes": requested_codes,
                    "selected_feature_families": block_names,
                    "missing_family_codes": missing_codes,
                    "completed_child_family_codes": [],
                    "failed_child_family_codes": block_names,
                    "family_name_policy": "artifact_field_reused_for_block_names",
                    "stage_tuning_status": "fs3_parent_context_uses_stage_level_configuration",
                    "child_tuning_status": "reuse_parent_stage_tuned_hyperparameters",
                    "bounded_light_retune_applied": False,
                }
            )
            _write_scheme_aggregate_artifacts(
                aggregate_run_dir=aggregate_run_dir,
                by_origin=pd.DataFrame(),
                by_reporting_level=pd.DataFrame(),
                summary=pd.DataFrame(),
                parent_child_map=pd.DataFrame(),
                metadata=metadata,
                run_summary_payload={
                    "run_id": aggregate_run_id,
                    "run_label": aggregate_run_label,
                    "run_role": "feature_family_ablation_aggregate",
                    "model": parent.model_name,
                    "model_family": parent.model_family,
                    "fs_stage": parent.fs_level,
                    "stage": spec.stage,
                    "context_code": spec.context_code,
                    "parent_context_label": feature_value_parent_context_label(spec),
                    "parent_run_id": parent.run_id,
                    "parent_run_label": parent.run_label,
                    "feature_families": block_names,
                    "smoke_test": bool(args.smoke_test),
                    "aggregate_status": "invalid",
                    "execution_status": "invalid_preflight",
                    "completed_child_count": 0,
                    "expected_child_count": len(block_names),
                    "failed_child_family_codes": block_names,
                    "support_status": spec.support_status,
                    "support_note": metadata["support_note"],
                    "benchmark_ready": bool(spec.benchmark_ready),
                    "scheme_name": scheme_payload["scheme_name"],
                    "scheme_version": scheme_payload["scheme_version"],
                    "layer_name": scheme_payload["layer_name"],
                    "target_block": target_block or "",
                    "scheme_hash": scheme_payload["scheme_hash"],
                    "feature_taxonomy_hash": scheme_payload["feature_taxonomy_hash"],
                },
                preflight_summary=preflight["summary"],
                preflight_assignments=preflight["assignments"],
                preflight_block_sizes=preflight["block_sizes"],
            )
            total_expected += len(block_names)
            continue

        all_origin_frames: list[pd.DataFrame] = []
        all_reporting_frames: list[pd.DataFrame] = []
        all_summary_frames: list[pd.DataFrame] = []
        parent_child_rows: list[dict[str, object]] = []
        completed_blocks: list[str] = []
        failed_blocks: list[str] = []

        for block_name in block_names:
            child_run_label = f"{parent.run_label}__remove_{block_name}"
            child_run_id = ""
            try:
                child_model = build_feature_value_model(
                    args,
                    spec=spec,
                    model_name=parent.model_name,
                    experiments=[experiment_map[code] for code in available_codes],
                    excluded_blocks=(block_name,),
                    ablation_scheme_name=scheme_name,
                    ablation_target_block=target_block,
                )
                child_run_id, _, _, _, _ = run_benchmark_suite(
                    config=config,
                    run_label=child_run_label,
                    models=[*build_naive_baseline_models(), child_model],
                    include_external_features=True,
                    show_progress=args.show_progress,
                    progress_label=f"{spec.stage}_{spec.model_family}_{scheme_name}_remove_{block_name}",
                    origin_schedule_by_split=origin_schedule_by_split,
                )
                child_run_dir = config.output_root / "runs" / child_run_id
                apply_inherited_rmae_to_child_run(child_run_dir, parent, feature_family=block_name)
                by_origin, by_reporting_level, summary = build_parent_child_comparison_frames(
                    parent,
                    child_run_dir=child_run_dir,
                    feature_family=block_name,
                    smoke_test=args.smoke_test,
                )
                for frame in (by_origin, by_reporting_level, summary):
                    frame["scheme_name"] = scheme_payload["scheme_name"]
                    frame["scheme_version"] = scheme_payload["scheme_version"]
                    frame["layer_name"] = scheme_payload["layer_name"]
                    frame["stage_name"] = scheme_payload["stage_name"]
                    frame["target_block"] = target_block or ""
                    frame["scheme_hash"] = scheme_payload["scheme_hash"]
                    frame["feature_taxonomy_hash"] = scheme_payload["feature_taxonomy_hash"]
                all_origin_frames.append(by_origin)
                all_reporting_frames.append(by_reporting_level)
                all_summary_frames.append(summary)
                completed_blocks.append(block_name)
                parent_child_rows.append(
                    {
                        "model": parent.model_name,
                        "model_family": parent.model_family,
                        "fs_stage": parent.fs_level,
                        "stage": spec.stage,
                        "context_code": spec.context_code,
                        "parent_context_label": feature_value_parent_context_label(spec),
                        "feature_family": block_name,
                        "scheme_name": scheme_payload["scheme_name"],
                        "scheme_version": scheme_payload["scheme_version"],
                        "layer_name": scheme_payload["layer_name"],
                        "stage_name": scheme_payload["stage_name"],
                        "target_block": target_block or "",
                        "scheme_hash": scheme_payload["scheme_hash"],
                        "feature_taxonomy_hash": scheme_payload["feature_taxonomy_hash"],
                        "parent_run_id": parent.run_id,
                        "parent_run_label": parent.run_label,
                        "child_run_id": child_run_id,
                        "child_run_label": child_run_label,
                        "child_run_dir": str(child_run_dir),
                        "aggregate_run_id": aggregate_run_id,
                        "aggregate_run_label": aggregate_run_label,
                        "comparison_type": "grouped_ablation",
                        "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                        "comparison_unit_name": "ablation_block",
                        "child_status": "complete",
                        "status": "complete",
                        "smoke_test": bool(args.smoke_test),
                    }
                )
            except Exception as exc:
                any_failed = True
                failed_blocks.append(block_name)
                parent_child_rows.append(
                    {
                        "model": parent.model_name,
                        "model_family": spec.model_family,
                        "fs_stage": "FS3",
                        "stage": spec.stage,
                        "context_code": spec.context_code,
                        "parent_context_label": feature_value_parent_context_label(spec),
                        "feature_family": block_name,
                        "scheme_name": scheme_payload["scheme_name"],
                        "scheme_version": scheme_payload["scheme_version"],
                        "layer_name": scheme_payload["layer_name"],
                        "stage_name": scheme_payload["stage_name"],
                        "target_block": target_block or "",
                        "scheme_hash": scheme_payload["scheme_hash"],
                        "feature_taxonomy_hash": scheme_payload["feature_taxonomy_hash"],
                        "parent_run_id": parent.run_id,
                        "parent_run_label": parent.run_label,
                        "child_run_id": child_run_id,
                        "child_run_label": child_run_label,
                        "child_run_dir": "",
                        "aggregate_run_id": aggregate_run_id,
                        "aggregate_run_label": aggregate_run_label,
                        "comparison_type": "grouped_ablation",
                        "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                        "comparison_unit_name": "ablation_block",
                        "child_status": "artifact_incomplete",
                        "status": "partial",
                        "smoke_test": bool(args.smoke_test),
                        "error_message": str(exc),
                    }
                )

        feature_value_by_origin = pd.concat(all_origin_frames, ignore_index=True) if all_origin_frames else pd.DataFrame()
        feature_value_by_reporting_level = (
            pd.concat(all_reporting_frames, ignore_index=True) if all_reporting_frames else pd.DataFrame()
        )
        feature_value_summary = pd.concat(all_summary_frames, ignore_index=True) if all_summary_frames else pd.DataFrame()
        feature_value_parent_child_map = pd.DataFrame(parent_child_rows)

        for frame in (feature_value_by_origin, feature_value_by_reporting_level, feature_value_summary):
            if "dataset_split" in frame.columns:
                frame.rename(columns={"dataset_split": "split"}, inplace=True)

        aggregate_status = "partial" if failed_blocks else "complete"
        if args.smoke_test:
            aggregate_status = "smoke_test" if not failed_blocks else "partial"
        metadata.update(
            {
                "aggregate_status": aggregate_status,
                "run_completeness_status": aggregate_status,
                "execution_status": "success" if not failed_blocks else "partial",
                "parent_context_label": feature_value_parent_context_label(spec),
                "stage": spec.stage,
                "context_code": spec.context_code,
                "benchmark_ready": bool(spec.benchmark_ready),
                "support_status": spec.support_status,
                "support_note": spec.support_note,
                "requested_family_codes": requested_codes,
                "selected_feature_families": block_names,
                "missing_family_codes": missing_codes,
                "completed_child_family_codes": completed_blocks,
                "failed_child_family_codes": failed_blocks,
                "family_name_policy": "artifact_field_reused_for_block_names",
                "stage_tuning_status": "fs3_parent_context_uses_stage_level_configuration",
                "child_tuning_status": "reuse_parent_stage_tuned_hyperparameters",
                "bounded_light_retune_applied": False,
            }
        )
        _write_scheme_aggregate_artifacts(
            aggregate_run_dir=aggregate_run_dir,
            by_origin=feature_value_by_origin,
            by_reporting_level=feature_value_by_reporting_level,
            summary=feature_value_summary,
            parent_child_map=feature_value_parent_child_map,
            metadata=metadata,
            run_summary_payload={
                "run_id": aggregate_run_id,
                "run_label": aggregate_run_label,
                "run_role": "feature_family_ablation_aggregate",
                "model": parent.model_name,
                "model_family": parent.model_family,
                "fs_stage": parent.fs_level,
                "stage": spec.stage,
                "context_code": spec.context_code,
                "parent_context_label": feature_value_parent_context_label(spec),
                "parent_run_id": parent.run_id,
                "parent_run_label": parent.run_label,
                "feature_families": block_names,
                "child_run_ids": [row["child_run_id"] for row in parent_child_rows if row.get("child_run_id")],
                "smoke_test": bool(args.smoke_test),
                "aggregate_status": aggregate_status,
                "execution_status": "success" if not failed_blocks else "partial",
                "completed_child_count": len(completed_blocks),
                "expected_child_count": len(block_names),
                "failed_child_family_codes": failed_blocks,
                "support_status": spec.support_status,
                "support_note": spec.support_note,
                "benchmark_ready": bool(spec.benchmark_ready),
                "scheme_name": scheme_payload["scheme_name"],
                "scheme_version": scheme_payload["scheme_version"],
                "layer_name": scheme_payload["layer_name"],
                "stage_name": scheme_payload["stage_name"],
                "target_block": target_block or "",
                "scheme_hash": scheme_payload["scheme_hash"],
                "feature_taxonomy_hash": scheme_payload["feature_taxonomy_hash"],
            },
            preflight_summary=preflight["summary"],
            preflight_assignments=preflight["assignments"],
            preflight_block_sizes=preflight["block_sizes"],
        )
        total_completed += len(completed_blocks)
        total_expected += len(block_names)

    final_status = "partial" if any_failed else "complete"
    if args.smoke_test and not any_failed:
        final_status = "smoke_test"
    return {
        "context_code": spec.context_code,
        "stage": spec.stage,
        "model_family": spec.model_family,
        "parent_context_label": feature_value_parent_context_label(spec),
        "parent_run_label": parent.run_label,
        "aggregate_run_id": "; ".join(aggregate_ids),
        "aggregate_run_label": "; ".join(aggregate_labels),
        "parent_run_id": parent.run_id,
        "status": final_status,
        "benchmark_ready": bool(spec.benchmark_ready),
        "support_note": f"{len(scheme_requests)} ablation scheme(s) executed.",
        "smoke_test": bool(args.smoke_test),
        "requested_family_codes": ", ".join(requested_codes),
        "completed_child_count": total_completed,
        "expected_child_count": total_expected,
    }


def run_feature_value_ablation_from_parent(
    args: argparse.Namespace,
    *,
    config: HourlyDAPipelineConfig,
    spec: FeatureValueContextSpec,
    experiment_map: dict[str, FS3Experiment],
    parent_bundle: dict[str, object],
) -> dict[str, object]:
    if spec.stage == "combo" and spec.context_code == "combo_promoted":
        return _run_fs3_combo_block_ablation_from_parent(
            args,
            config=config,
            spec=spec,
            experiment_map=experiment_map,
            parent_bundle=parent_bundle,
        )

    requested_codes = list(parent_bundle["requested_codes"])
    available_codes = list(parent_bundle["available_codes"])
    missing_codes = list(parent_bundle["missing_codes"])
    parent = parent_bundle["parent"]
    parent_run_label = str(parent_bundle["parent_run_label"])
    origin_schedule_by_split = smoke_origin_schedules(config, args.smoke_origins_per_split) if args.smoke_test else None

    aggregate_run_label = f"feature_family_ablation__{parent.run_label}"
    aggregate_run_id, aggregate_run_dir = create_run_directory(config.output_root, aggregate_run_label)
    metadata = feature_family_metadata_payload(
        parent,
        aggregate_run_id=aggregate_run_id,
        aggregate_run_label=aggregate_run_label,
        selected_feature_families=available_codes,
        smoke_test=args.smoke_test,
        smoke_origins_per_split=args.smoke_origins_per_split if args.smoke_test else None,
    )

    all_origin_frames: list[pd.DataFrame] = []
    all_reporting_frames: list[pd.DataFrame] = []
    all_summary_frames: list[pd.DataFrame] = []
    parent_child_rows: list[dict[str, object]] = []
    completed_codes: list[str] = []
    failed_codes: list[str] = []

    for family_code in available_codes:
        remaining_codes = [code for code in available_codes if code != family_code]
        child_run_label = f"{parent.run_label}__remove_{family_code}"
        child_run_id = ""
        try:
            child_model = build_feature_value_model(
                args,
                spec=spec,
                model_name=parent.model_name,
                experiments=[experiment_map[code] for code in remaining_codes],
            )
            child_run_id, _, _, _, _ = run_benchmark_suite(
                config=config,
                run_label=child_run_label,
                models=[*build_naive_baseline_models(), child_model],
                include_external_features=True,
                show_progress=args.show_progress,
                progress_label=f"{spec.stage}_{spec.model_family}_remove_{family_code}",
                origin_schedule_by_split=origin_schedule_by_split,
            )
            child_run_dir = config.output_root / "runs" / child_run_id
            apply_inherited_rmae_to_child_run(child_run_dir, parent, feature_family=family_code)
            by_origin, by_reporting_level, summary = build_parent_child_comparison_frames(
                parent,
                child_run_dir=child_run_dir,
                feature_family=family_code,
                smoke_test=args.smoke_test,
            )
            all_origin_frames.append(by_origin)
            all_reporting_frames.append(by_reporting_level)
            all_summary_frames.append(summary)
            completed_codes.append(family_code)
            parent_child_rows.append(
                {
                    "model": parent.model_name,
                    "model_family": parent.model_family,
                    "fs_stage": parent.fs_level,
                    "stage": spec.stage,
                    "context_code": spec.context_code,
                    "parent_context_label": feature_value_parent_context_label(spec),
                    "feature_family": family_code,
                    "parent_run_id": parent.run_id,
                    "parent_run_label": parent.run_label,
                    "child_run_id": child_run_id,
                    "child_run_label": child_run_label,
                    "child_run_dir": str(child_run_dir),
                    "aggregate_run_id": aggregate_run_id,
                    "aggregate_run_label": aggregate_run_label,
                    "comparison_type": "grouped_ablation",
                    "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                    "child_status": "complete",
                    "status": "complete",
                    "smoke_test": bool(args.smoke_test),
                }
            )
        except Exception as exc:
            failed_codes.append(family_code)
            parent_child_rows.append(
                {
                    "model": parent.model_name,
                    "model_family": spec.model_family,
                    "fs_stage": "FS3",
                    "stage": spec.stage,
                    "context_code": spec.context_code,
                    "parent_context_label": feature_value_parent_context_label(spec),
                    "feature_family": family_code,
                    "parent_run_id": parent.run_id,
                    "parent_run_label": parent.run_label,
                    "child_run_id": child_run_id,
                    "child_run_label": child_run_label,
                    "child_run_dir": "",
                    "aggregate_run_id": aggregate_run_id,
                    "aggregate_run_label": aggregate_run_label,
                    "comparison_type": "grouped_ablation",
                    "ablation_policy": "reuse_parent_stage_tuned_hyperparameters",
                    "child_status": "artifact_incomplete",
                    "status": "partial",
                    "smoke_test": bool(args.smoke_test),
                    "error_message": str(exc),
                }
            )

    feature_value_by_origin = pd.concat(all_origin_frames, ignore_index=True) if all_origin_frames else pd.DataFrame()
    feature_value_by_reporting_level = (
        pd.concat(all_reporting_frames, ignore_index=True) if all_reporting_frames else pd.DataFrame()
    )
    feature_value_summary = pd.concat(all_summary_frames, ignore_index=True) if all_summary_frames else pd.DataFrame()
    feature_value_parent_child_map = pd.DataFrame(parent_child_rows)

    for frame in (feature_value_by_origin, feature_value_by_reporting_level, feature_value_summary):
        if "dataset_split" in frame.columns:
            frame.rename(columns={"dataset_split": "split"}, inplace=True)

    aggregate_status = "partial" if failed_codes else "complete"
    if args.smoke_test:
        aggregate_status = "smoke_test" if not failed_codes else "partial"
    metadata.update(
        {
            "aggregate_status": aggregate_status,
            "run_completeness_status": aggregate_status,
            "execution_status": "success" if not failed_codes else "partial",
            "parent_context_label": feature_value_parent_context_label(spec),
            "stage": spec.stage,
            "context_code": spec.context_code,
            "benchmark_ready": bool(spec.benchmark_ready),
            "support_status": spec.support_status,
            "support_note": spec.support_note,
            "requested_family_codes": requested_codes,
            "selected_feature_families": available_codes,
            "missing_family_codes": missing_codes,
            "completed_child_family_codes": completed_codes,
            "failed_child_family_codes": failed_codes,
            "family_name_policy": "preserve_code_level_fs3_family_names",
            "stage_tuning_status": "fs3_parent_context_uses_stage_level_configuration",
            "child_tuning_status": "reuse_parent_stage_tuned_hyperparameters",
            "bounded_light_retune_applied": False,
        }
    )

    write_csv(aggregate_run_dir / "feature_family_value_by_origin.csv", feature_value_by_origin)
    write_csv(aggregate_run_dir / "feature_family_value_by_reporting_level.csv", feature_value_by_reporting_level)
    write_csv(aggregate_run_dir / "feature_family_value_summary.csv", feature_value_summary)
    write_csv(aggregate_run_dir / "feature_family_parent_child_map.csv", feature_value_parent_child_map)
    write_json(aggregate_run_dir / "feature_family_value_metadata.json", metadata)
    write_json(
        aggregate_run_dir / "run_summary.json",
        {
            "run_id": aggregate_run_id,
            "run_label": aggregate_run_label,
            "run_role": "feature_family_ablation_aggregate",
            "model": parent.model_name,
            "model_family": parent.model_family,
            "fs_stage": parent.fs_level,
            "stage": spec.stage,
            "context_code": spec.context_code,
            "parent_context_label": feature_value_parent_context_label(spec),
            "parent_run_id": parent.run_id,
            "parent_run_label": parent.run_label,
            "feature_families": available_codes,
            "child_run_ids": [row["child_run_id"] for row in parent_child_rows if row.get("child_run_id")],
            "smoke_test": bool(args.smoke_test),
            "aggregate_status": aggregate_status,
            "execution_status": "success" if not failed_codes else "partial",
            "completed_child_count": len(completed_codes),
            "expected_child_count": len(available_codes),
            "failed_child_family_codes": failed_codes,
            "support_status": spec.support_status,
            "support_note": spec.support_note,
            "benchmark_ready": bool(spec.benchmark_ready),
        },
    )

    return {
        "context_code": spec.context_code,
        "stage": spec.stage,
        "model_family": spec.model_family,
        "parent_context_label": feature_value_parent_context_label(spec),
        "parent_run_label": parent_run_label,
        "aggregate_run_id": aggregate_run_id,
        "aggregate_run_label": aggregate_run_label,
        "parent_run_id": parent.run_id,
        "status": aggregate_status,
        "benchmark_ready": bool(spec.benchmark_ready),
        "support_note": spec.support_note,
        "smoke_test": bool(args.smoke_test),
        "requested_family_codes": ", ".join(requested_codes),
        "completed_child_count": len(completed_codes),
        "expected_child_count": len(available_codes),
    }


def run_feature_value_context(
    args: argparse.Namespace,
    *,
    config: HourlyDAPipelineConfig,
    spec: FeatureValueContextSpec,
    experiment_map: dict[str, FS3Experiment],
) -> dict[str, object]:
    requested_codes = list(spec.family_codes)
    parent_run_label = feature_value_parent_run_label(spec)
    step = str(args.feature_value_step)

    if spec.support_status != "complete":
        return {
            "context_code": spec.context_code,
            "stage": spec.stage,
            "model_family": spec.model_family,
            "parent_context_label": feature_value_parent_context_label(spec),
            "parent_run_label": parent_run_label,
            "aggregate_run_id": "",
            "aggregate_run_label": f"feature_family_ablation__{parent_run_label}",
            "parent_run_id": "",
            "status": "unsupported",
            "benchmark_ready": bool(spec.benchmark_ready),
            "support_note": spec.support_note,
            "smoke_test": bool(args.smoke_test),
            "requested_family_codes": ", ".join(requested_codes),
            "completed_child_count": 0,
            "expected_child_count": 0,
        }

    try:
        if step in {"parent", "all"}:
            parent_bundle = run_feature_value_parent_context(
                args,
                config=config,
                spec=spec,
                experiment_map=experiment_map,
            )
        else:
            parent_bundle = resolve_feature_value_parent_context(
                config,
                spec=spec,
                experiment_map=experiment_map,
            )
    except Exception as exc:
        return {
            "context_code": spec.context_code,
            "stage": spec.stage,
            "model_family": spec.model_family,
            "parent_context_label": feature_value_parent_context_label(spec),
            "parent_run_label": parent_run_label,
            "aggregate_run_id": "",
            "aggregate_run_label": f"feature_family_ablation__{parent_run_label}",
            "parent_run_id": "",
            "status": "incompatible_parent" if step == "ablation" else "unsupported",
            "benchmark_ready": bool(spec.benchmark_ready),
            "support_note": str(exc),
            "smoke_test": bool(args.smoke_test),
            "requested_family_codes": ", ".join(requested_codes),
            "completed_child_count": 0,
            "expected_child_count": len([code for code in spec.family_codes if code in experiment_map]),
        }

    if step == "parent":
        parent = parent_bundle["parent"]
        return {
            "context_code": spec.context_code,
            "stage": spec.stage,
            "model_family": spec.model_family,
            "parent_context_label": feature_value_parent_context_label(spec),
            "parent_run_label": parent_run_label,
            "aggregate_run_id": "",
            "aggregate_run_label": "",
            "parent_run_id": parent.run_id,
            "status": "smoke_test" if args.smoke_test else "complete",
            "benchmark_ready": bool(spec.benchmark_ready),
            "support_note": spec.support_note,
            "smoke_test": bool(args.smoke_test),
            "requested_family_codes": ", ".join(parent_bundle["requested_codes"]),
            "completed_child_count": 0,
            "expected_child_count": len(parent_bundle["available_codes"]),
        }

    return run_feature_value_ablation_from_parent(
        args,
        config=config,
        spec=spec,
        experiment_map=experiment_map,
        parent_bundle=parent_bundle,
    )


def run_feature_value_workflow(
    args: argparse.Namespace,
    *,
    config: HourlyDAPipelineConfig,
    experiment_map: dict[str, FS3Experiment],
    summary_dir,
) -> tuple[list[dict[str, object]], list[str], dict[str, object]]:
    results: list[dict[str, object]] = []
    note_lines: list[str] = []
    context_registry = feature_value_context_registry_frame()
    write_csv(summary_dir / "feature_value_context_registry.csv", context_registry)

    contexts = selected_feature_value_contexts(args)
    if not contexts:
        note_lines.append("feature value: no FS3 contexts matched the requested stage/model filters.")
        write_csv(summary_dir / "feature_value_run_status.csv", pd.DataFrame())
        return results, note_lines, {"selected_contexts": []}

    payload: dict[str, object] = {
        "selected_contexts": [
            {
                "context_code": spec.context_code,
                "stage": spec.stage,
                "model_family": spec.model_family,
                "support_status": spec.support_status,
                "benchmark_ready": bool(spec.benchmark_ready),
            }
            for spec in contexts
        ]
    }

    for spec in contexts:
        if spec.support_status != "complete":
            results.append(
                {
                    "context_code": spec.context_code,
                    "stage": spec.stage,
                    "model_family": spec.model_family,
                    "parent_context_label": feature_value_parent_context_label(spec),
                    "parent_run_label": feature_value_parent_run_label(spec),
                    "aggregate_run_id": "",
                    "aggregate_run_label": f"feature_family_ablation__{feature_value_parent_run_label(spec)}",
                    "parent_run_id": "",
                    "status": "unsupported",
                    "benchmark_ready": bool(spec.benchmark_ready),
                    "support_note": spec.support_note,
                    "smoke_test": bool(args.smoke_test),
                    "requested_family_codes": ", ".join(spec.family_codes),
                    "completed_child_count": 0,
                    "expected_child_count": 0,
                }
            )
            note_lines.append(f"{spec.label}: unsupported for Phase 5 first-wave execution. {spec.support_note}")
            continue

        result = run_feature_value_context(args, config=config, spec=spec, experiment_map=experiment_map)
        results.append(result)
        note_lines.append(
            f"{spec.label}: status={result['status']}; parent={result['parent_run_id'] or 'n/a'}; "
            f"aggregate={result['aggregate_run_id'] or 'n/a'}"
        )

    result_frame = pd.DataFrame(results)
    write_csv(summary_dir / "feature_value_run_status.csv", result_frame)
    payload["result_rows"] = result_frame.to_dict(orient="records") if not result_frame.empty else []
    return results, note_lines, payload


def selected_phase_list(stage: str) -> list[PhaseSpec]:
    if stage == "all":
        return list(PHASE_SEQUENCE)
    if stage in PHASE_BY_STAGE:
        return [PHASE_BY_STAGE[stage]]
    return []


def main() -> None:
    args = parse_args()
    config = replace(
        HourlyDAPipelineConfig(market_area=args.market_area),
        monitoring=MonitoringConfig(fit_time_absolute_threshold_sec=args.fit_time_threshold_sec),
    )

    store = load_external_feature_store(config)
    experiment_map = store.experiment_map()
    family_catalog = build_external_family_catalog(config, store)

    summary_run_id, summary_dir = create_run_directory(config.output_root, "fs3_ordered_summary")
    write_csv(summary_dir / "external_family_catalog.csv", family_catalog)

    payload: dict[str, object] = {
        "summary_run_id": summary_run_id,
        "market_area": args.market_area,
        "stage": args.stage,
        "execution_mode": args.execution_mode,
        "coverage_gap_threshold_pct": args.coverage_gap_threshold_pct,
        "available_experiments": sorted(experiment_map),
        "active_model_scope": "FS3 continues only with model families already shortlisted after FS2.",
    }
    note_lines = [
        f"Market: {args.market_area}",
        f"Stage: {args.stage}",
        f"Coverage comparability threshold vs same-family FS2: {args.coverage_gap_threshold_pct:.2f} percentage points",
        "FS3 is only valid after the cross-model shortlist at FS2 has been frozen.",
        "The current FS3 screening scaffold is prepared for LEAR and XGBoost survivors. Prophet should only be promoted into FS3 if its regressor set stays compact and causal.",
    ]

    phase_run_rows: list[dict[str, object]] = []
    phase_decisions: list[dict[str, object]] = []
    all_summaries: list[pd.DataFrame] = []
    promoted_all_codes: list[str] = []
    combo_run_id = ""

    if args.execution_mode in {"ordered", "all"}:
        for phase in selected_phase_list(args.stage):
            phase_experiments = [experiment_map[code] for code in phase.experiment_codes if code in experiment_map]
            if not phase_experiments:
                note_lines.append(f"{phase.stage}: no available experiments found in the external feature store.")
                continue

            screen_run_id, _, _, _, _ = run_benchmark_suite(
                config=config,
                run_label=phase.screen_run_label,
                models=screening_models(args, phase, phase_experiments),
                include_external_features=True,
                show_progress=args.show_progress,
                progress_label=f"{phase.stage}_screen",
            )
            screen_summary = build_reporting_level_summary(
                _run_dir(config, screen_run_id),
                model_metadata=model_metadata_for_phase(phase_experiments, evaluation_role="screen_candidate", families=("xgboost",)),
                coverage_gap_threshold_pct=args.coverage_gap_threshold_pct,
                phase_name=phase.stage,
            )
            shortlisted = shortlist_codes(screen_summary, phase, args.shortlist_k)
            write_csv(summary_dir / f"{phase.stage}_screen_summary.csv", screen_summary)
            phase_run_rows.append(
                {
                    "phase_name": phase.stage,
                    "phase_label": phase.label,
                    "run_type": "screen",
                    "run_id": screen_run_id,
                    "primary_reporting_level": phase.primary_reporting_level,
                }
            )
            payload[f"{phase.stage}_screen_run_id"] = screen_run_id
            payload[f"{phase.stage}_shortlist_codes"] = shortlisted
            note_lines.append(
                f"{phase.stage} screen: {screen_run_id}; shortlisted: {', '.join(shortlisted) if shortlisted else 'none'}"
            )

            promoted_phase: list[str] = []
            confirm_summary = pd.DataFrame()
            if shortlisted:
                shortlisted_experiments = [experiment_map[code] for code in shortlisted]
                confirm_run_id, _, _, _, _ = run_benchmark_suite(
                    config=config,
                    run_label=phase.confirm_run_label,
                    models=confirmation_models(args, phase, shortlisted_experiments),
                    include_external_features=True,
                    show_progress=args.show_progress,
                    progress_label=f"{phase.stage}_confirm",
                )
                confirm_summary = build_reporting_level_summary(
                    _run_dir(config, confirm_run_id),
                    model_metadata=model_metadata_for_phase(shortlisted_experiments, evaluation_role="phase_candidate", families=("lear", "xgboost")),
                    coverage_gap_threshold_pct=args.coverage_gap_threshold_pct,
                    phase_name=phase.stage,
                )
                promoted_phase = promoted_codes(confirm_summary, phase)
                write_csv(summary_dir / f"{phase.stage}_confirmation_summary.csv", confirm_summary)
                phase_run_rows.append(
                    {
                        "phase_name": phase.stage,
                        "phase_label": phase.label,
                        "run_type": "confirm",
                        "run_id": confirm_run_id,
                        "primary_reporting_level": phase.primary_reporting_level,
                    }
                )
                payload[f"{phase.stage}_confirm_run_id"] = confirm_run_id
                payload[f"{phase.stage}_promoted_codes"] = promoted_phase
                note_lines.append(
                    f"{phase.stage} confirm: {confirm_run_id}; promoted: {', '.join(promoted_phase) if promoted_phase else 'none'}"
                )
                all_summaries.append(confirm_summary)
            else:
                payload[f"{phase.stage}_promoted_codes"] = []
                note_lines.append(f"{phase.stage} confirm: skipped because the screen produced no promotable shortlist.")

            phase_decisions.extend(phase_decision_rows(confirm_summary if not confirm_summary.empty else screen_summary, phase, shortlisted, promoted_phase))
            promoted_all_codes.extend(code for code in promoted_phase if code not in promoted_all_codes)

        combo_summary = pd.DataFrame()
        combo_run_id = ""
        combo_metadata: dict[str, object] = {}
        if args.stage == "combo":
            promoted_all_codes = [code for code in args.promoted_codes or [] if code in experiment_map]

        if args.stage in {"combo", "all"} and promoted_all_codes:
            promoted_experiments = [experiment_map[code] for code in promoted_all_codes if code in experiment_map]
            combo_run_label = str(args.combo_run_label or default_combo_run_label(args.combo_model_family))
            target_combo_families = combo_target_families(args.combo_model_family)
            combo_model_list, combo_metadata = combo_models(args, promoted_experiments)
            combo_run_id, _, _, _, _ = run_benchmark_suite(
                config=config,
                run_label=combo_run_label,
                models=combo_model_list,
                include_external_features=True,
                show_progress=args.show_progress,
                progress_label=f"combo_confirm_{args.combo_model_family}",
            )
            combo_model_metadata = {}
            if "lear" in target_combo_families:
                combo_model_metadata["lear_fs3_combo_promoted"] = {"family_code": "combo_promoted", "evaluation_role": "combo_candidate"}
            if "xgboost" in target_combo_families:
                combo_model_metadata["xgboost_fs3_combo_promoted"] = {"family_code": "combo_promoted", "evaluation_role": "combo_candidate"}
            combo_summary = build_reporting_level_summary(
                _run_dir(config, combo_run_id),
                model_metadata=combo_model_metadata,
                coverage_gap_threshold_pct=args.coverage_gap_threshold_pct,
                phase_name="combo",
            )
            write_csv(summary_dir / "combo_confirmation_summary.csv", combo_summary)
            phase_run_rows.append(
                {
                    "phase_name": "combo",
                    "phase_label": "Combined promoted families" if args.combo_model_family == "all" else f"Combined promoted families ({args.combo_model_family})",
                    "run_type": "confirm",
                    "run_id": combo_run_id,
                    "primary_reporting_level": "stitched_all_horizon",
                }
            )
            payload["combo_run_id"] = combo_run_id
            payload["combo_run_label"] = combo_run_label
            payload["combo_metadata"] = combo_metadata
            note_lines.append(
                f"combo confirm ({args.combo_model_family}): {combo_run_id}; "
                f"run_label={combo_run_label}; promoted codes used: {', '.join(promoted_all_codes)}"
            )
            all_summaries.append(combo_summary)
        elif args.stage in {"combo", "all"}:
            note_lines.append("combo confirm: skipped because no experiments were promoted from the earlier phases.")
    else:
        note_lines.append("ordered workflow: skipped by execution-mode filter.")

    if args.execution_mode in {"feature_value", "all"}:
        feature_value_results, feature_value_notes, feature_value_payload = run_feature_value_workflow(
            args,
            config=config,
            experiment_map=experiment_map,
            summary_dir=summary_dir,
        )
        note_lines.extend(feature_value_notes)
        payload["feature_value"] = feature_value_payload
        payload["feature_value_completed_contexts"] = [
            row["context_code"] for row in feature_value_results if row.get("status") in {"complete", "smoke_test"}
        ]
    else:
        note_lines.append("feature value: skipped by execution-mode filter.")

    if all_summaries:
        write_csv(summary_dir / "selected_reporting_level_summary.csv", pd.concat(all_summaries, ignore_index=True))
    else:
        write_csv(summary_dir / "selected_reporting_level_summary.csv", pd.DataFrame())
    write_csv(summary_dir / "phase_runs.csv", pd.DataFrame(phase_run_rows))
    write_csv(summary_dir / "phase_decisions.csv", pd.DataFrame(phase_decisions))

    payload["promoted_codes"] = promoted_all_codes
    payload["phase_runs"] = phase_run_rows
    write_json(summary_dir / "ordered_runs.json", payload)
    write_text(summary_dir / "summary_note.md", "\n".join(note_lines))

    print(f"Summary run: {summary_run_id}")
    print("Promoted experiment codes:", ", ".join(promoted_all_codes) if promoted_all_codes else "none")
    if combo_run_id:
        print(f"Combo run: {combo_run_id}")
    storage_summary = apply_default_storage_policy(config.output_root)
    for line in format_storage_summary_lines(storage_summary):
        print(line)


if __name__ == "__main__":
    main()
