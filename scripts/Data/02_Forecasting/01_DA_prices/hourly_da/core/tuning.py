from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class TuningCadencePolicy:
    fs_level: str
    search_intensity: str
    validation_role: str
    daily_refit_rule: str
    notes: str


@dataclass(frozen=True)
class ModelTuningSnippet:
    model_family: str
    fs_level: str
    search_intensity: str
    parameter_focus: tuple[str, ...]
    suggested_start: str
    suggested_grid: str
    notes: str


@dataclass(frozen=True)
class AblationTuningPolicy:
    applies_to_fs_levels: tuple[str, ...]
    default_settings_inheritance_policy: str
    reuse_parent_stage_tuned_hyperparameters: bool
    full_retuning_per_ablation_run: bool
    canonical_source_of_truth: str
    metadata_fields: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class RollingOriginArtifactPolicy:
    artifact_name: str
    grain: str
    status: str
    notes: str


@dataclass(frozen=True)
class FeatureValueScopeDecision:
    topic: str
    status: str
    decision: str
    notes: str


TUNING_CADENCE_POLICIES: tuple[TuningCadencePolicy, ...] = (
    TuningCadencePolicy(
        fs_level="FS0",
        search_intensity="None",
        validation_role="Validation is used only to choose the official naive benchmark.",
        daily_refit_rule="No structural tuning per origin.",
        notes="Seasonal naive baselines are deterministic benchmark candidates.",
    ),
    TuningCadencePolicy(
        fs_level="FS1",
        search_intensity="Fast / coarse",
        validation_role="Tune structural hyperparameters on validation only, then freeze the chosen FS1 settings.",
        daily_refit_rule="Daily walk-forward re-fits only. Do not repeat full search at each origin.",
        notes="FS1 is not a shortlisting stage.",
    ),
    TuningCadencePolicy(
        fs_level="FS2",
        search_intensity="First serious tuning round",
        validation_role="Run the first full validation-only benchmark tuning pass before freezing FS2 settings.",
        daily_refit_rule="Daily walk-forward re-fits only. No origin-level retuning.",
        notes="FS2 is the first fair shortlist point.",
    ),
    TuningCadencePolicy(
        fs_level="FS3",
        search_intensity="Mandatory retuning",
        validation_role="Retune because causal exogenous families materially change the problem.",
        daily_refit_rule="After the FS3 choice is frozen, daily walk-forward only re-fits.",
        notes="Apply the same rule again for each materially different FS3 family bundle.",
    ),
    TuningCadencePolicy(
        fs_level="FS4",
        search_intensity="Selective rigorous retuning",
        validation_role="Focus deeper search only on surviving finalists.",
        daily_refit_rule="Freeze the FS4 design before daily walk-forward execution.",
        notes="Most likely applies to XGBoost and possibly LEAR.",
    ),
)

MODEL_TUNING_SNIPPETS: tuple[ModelTuningSnippet, ...] = (
    ModelTuningSnippet(
        model_family="lear",
        fs_level="FS1",
        search_intensity="Fast / coarse",
        parameter_focus=("alpha", "training_window_days", "starter_lag_bundle"),
        suggested_start="alpha=0.01, training window=90 days",
        suggested_grid="alpha in logspace; 90/180/365-day windows; small lag-bundle variants",
        notes="Keep the search light at FS1 because FS1 is a foundation stage, not a shortlist.",
    ),
    ModelTuningSnippet(
        model_family="xgboost",
        fs_level="FS1",
        search_intensity="Fast / coarse",
        parameter_focus=("learning_rate", "max_depth", "min_child_weight"),
        suggested_start="learning_rate=0.05, max_depth=4",
        suggested_grid="small grid over depth, learning rate, and leaf conservatism",
        notes="XGBoost needs explicit regressors, but not exogenous forecasts, to be fair at FS1.",
    ),
    ModelTuningSnippet(
        model_family="lear",
        fs_level="FS2",
        search_intensity="Serious",
        parameter_focus=("alpha", "training_window_days", "lag_bundle"),
        suggested_start="Reuse the best FS1 region as the FS2 starting point",
        suggested_grid="broader alpha sweep plus window and lag-bundle checks on validation",
        notes="Calendar and holiday structure changes the shrinkage pattern enough to justify a real tuning round.",
    ),
    ModelTuningSnippet(
        model_family="xgboost",
        fs_level="FS2",
        search_intensity="Serious",
        parameter_focus=("learning_rate", "max_depth", "subsample", "colsample_bytree", "reg_alpha", "reg_lambda"),
        suggested_start="learning_rate=0.05, max_depth=4, subsample=0.8, colsample_bytree=0.8",
        suggested_grid="moderate grid around tree depth, shrinkage, and regularization",
        notes="FS2 is the first serious tuning round and the first fair shortlist point.",
    ),
    ModelTuningSnippet(
        model_family="prophet",
        fs_level="FS2",
        search_intensity="Serious",
        parameter_focus=("seasonality_mode", "changepoint_prior_scale", "seasonality_prior_scale", "holidays_prior_scale"),
        suggested_start="multiplicative seasonality, cps=0.05, sps=10, hps=10",
        suggested_grid="seasonality mode in {additive,multiplicative}; cps, sps, hps over compact validation grids",
        notes="Prophet starts at FS2 only. Keep the regressor set compact and causal.",
    ),
    ModelTuningSnippet(
        model_family="lear",
        fs_level="FS3",
        search_intensity="Mandatory retuning",
        parameter_focus=("alpha", "training_window_days", "feature-family bundle"),
        suggested_start="FS2 winner as the starting baseline",
        suggested_grid="retune once each material exogenous family bundle is added",
        notes="Do not trust FS2 hyperparameters unchanged once exogenous structure is added.",
    ),
    ModelTuningSnippet(
        model_family="xgboost",
        fs_level="FS3",
        search_intensity="Mandatory retuning",
        parameter_focus=("learning_rate", "max_depth", "regularization", "feature-family bundle"),
        suggested_start="FS2 winner as the starting baseline",
        suggested_grid="retune around the FS2 winner after each major causal feature-family change",
        notes="XGBoost is the main beneficiary of richer FS3 and FS4 feature engineering.",
    ),
    ModelTuningSnippet(
        model_family="prophet",
        fs_level="FS3",
        search_intensity="Conditional",
        parameter_focus=("compact regressor subset", "regressor prior strength"),
        suggested_start="Only if Prophet survives FS2 and the regressor set remains compact",
        suggested_grid="small validation-only regressor subset checks and prior-scale tuning",
        notes="Prophet should not be forced into FS3 if the regressor story becomes bloated or weakly causal.",
    ),
    ModelTuningSnippet(
        model_family="xgboost",
        fs_level="FS4",
        search_intensity="Selective rigorous retuning",
        parameter_focus=("full tree regularization set", "feature subset", "advanced engineered feature bundle"),
        suggested_start="Best FS3 finalist configuration",
        suggested_grid="broader finalist-only search after FS4 features are frozen",
        notes="FS4 is expected to be XGBoost-centric.",
    ),
    ModelTuningSnippet(
        model_family="lear",
        fs_level="FS4",
        search_intensity="Selective rigorous retuning",
        parameter_focus=("alpha", "feature subset", "window length"),
        suggested_start="Best FS3 finalist configuration",
        suggested_grid="retune sparsity after the engineered feature layer is fixed",
        notes="LEAR remains a valid finalist if it survives FS3 strongly enough.",
    ),
)

ABLATION_TUNING_POLICY = AblationTuningPolicy(
    applies_to_fs_levels=("FS1", "FS2"),
    default_settings_inheritance_policy="reuse_parent_stage_tuned_hyperparameters",
    reuse_parent_stage_tuned_hyperparameters=True,
    full_retuning_per_ablation_run=False,
    canonical_source_of_truth="hourly_da.core.tuning.ABLATION_TUNING_POLICY",
    metadata_fields=(
        "settings_inheritance_policy",
        "parent_run_id",
        "parent_run_label",
        "parent_model",
        "parent_fs_level",
    ),
    notes="Phase 2 freezes the default future ablation rule: inherit the parent-stage tuned settings unless a later methodology decision explicitly opts into retuning.",
)

ROLLING_ORIGIN_ARTIFACT_POLICIES: tuple[RollingOriginArtifactPolicy, ...] = (
    RollingOriginArtifactPolicy(
        artifact_name="feature_value_by_origin.csv",
        grain="rolling_origin",
        status="reserved_for_future_use",
        notes="Use rolling-origin terminology instead of fold terminology for future feature-value comparisons.",
    ),
    RollingOriginArtifactPolicy(
        artifact_name="feature_value_by_reporting_level.csv",
        grain="reporting_level",
        status="reserved_for_future_use",
        notes="This stays compatible with the current shared reporting-level metric summaries.",
    ),
    RollingOriginArtifactPolicy(
        artifact_name="feature_value_summary.csv",
        grain="summary",
        status="reserved_for_future_use",
        notes="Compact run-level summary for future feature-family evaluation outputs.",
    ),
)

FEATURE_VALUE_SCOPE_DECISIONS: tuple[FeatureValueScopeDecision, ...] = (
    FeatureValueScopeDecision(
        topic="lear_coefficient_stability",
        status="deferred_to_phase3_or_later",
        decision="Do not implement LEAR coefficient stability diagnostics yet.",
        notes="Current benchmark runs do not persist full coefficient paths, so grouped-ablation work should proceed without this initially.",
    ),
    FeatureValueScopeDecision(
        topic="xgboost_gain_importance",
        status="in_scope_for_phase3",
        decision="Native gain-based importance can be added later as secondary interpretation.",
        notes="Grouped ablation remains the main evidence; gain is an auxiliary model-native view.",
    ),
    FeatureValueScopeDecision(
        topic="xgboost_permutation_importance",
        status="optional_for_phase3",
        decision="Permutation importance is optional later if runtime remains acceptable.",
        notes="Treat this as a selective diagnostic rather than a default requirement.",
    ),
    FeatureValueScopeDecision(
        topic="xgboost_shap",
        status="deferred_unless_trivial",
        decision="SHAP stays deferred unless it is dependency-compatible with negligible extra integration cost.",
        notes="Do not assume SHAP support as part of the default Phase 3 scope.",
    ),
    FeatureValueScopeDecision(
        topic="prophet_interpretation",
        status="constrained_for_phase3",
        decision="Keep Prophet interpretation compact and modest later.",
        notes="Future Prophet analysis should focus on grouped ablation and compact regressor/component summaries only.",
    ),
)


def tuning_cadence_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(policy) for policy in TUNING_CADENCE_POLICIES])


def tuning_snippet_frame(model_family: str | None = None, fs_level: str | None = None) -> pd.DataFrame:
    rows = pd.DataFrame([asdict(snippet) for snippet in MODEL_TUNING_SNIPPETS])
    if model_family is not None:
        rows = rows[rows["model_family"] == model_family].copy()
    if fs_level is not None:
        rows = rows[rows["fs_level"] == fs_level].copy()
    if rows.empty:
        return rows
    rows["parameter_focus"] = rows["parameter_focus"].map(lambda values: ", ".join(values))
    return rows.reset_index(drop=True)


def build_tuning_placeholder(model_family: str, fs_level: str) -> dict[str, object]:
    snippet_rows = tuning_snippet_frame(model_family=model_family, fs_level=fs_level)
    if snippet_rows.empty:
        return {
            "model_family": model_family,
            "fs_level": fs_level,
            "validation_only": True,
            "freeze_after_selection": True,
            "daily_walk_forward_repeats_search": False,
            "notes": "No tuning snippet has been defined yet for this combination.",
        }
    record = snippet_rows.iloc[0].to_dict()
    record["validation_only"] = True
    record["freeze_after_selection"] = True
    record["daily_walk_forward_repeats_search"] = False
    return record


def benchmark_context_fs_level(model_fs_levels: list[str] | tuple[str, ...]) -> str:
    def _rank(fs_level: str) -> tuple[int, str]:
        text = str(fs_level)
        if text.startswith("FS") and text[2:].isdigit():
            return int(text[2:]), text
        return -1, text

    normalized = [str(level) for level in model_fs_levels if str(level)]
    if not normalized:
        return "FS0"
    return max(normalized, key=_rank)


def ablation_tuning_policy_snapshot() -> dict[str, object]:
    return asdict(ABLATION_TUNING_POLICY)


def rolling_origin_artifact_policy_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(policy) for policy in ROLLING_ORIGIN_ARTIFACT_POLICIES])


def feature_value_scope_decision_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(decision) for decision in FEATURE_VALUE_SCOPE_DECISIONS])


def effective_policy_summary(fs_level: str, *, run_role: str) -> dict[str, object]:
    cadence = tuning_cadence_frame()
    cadence_row = cadence[cadence["fs_level"] == fs_level]
    stage_policy = cadence_row.iloc[0].to_dict() if not cadence_row.empty else {"fs_level": fs_level}
    return {
        "run_role": run_role,
        "context_fs_level": fs_level,
        "validation_only": True,
        "daily_walk_forward_repeats_search": False,
        "stage_tuning_policy": stage_policy,
        "future_ablation_defaults": ablation_tuning_policy_snapshot(),
        "reserved_feature_value_artifacts": rolling_origin_artifact_policy_frame().to_dict(orient="records"),
        "feature_value_scope_decisions": feature_value_scope_decision_frame().to_dict(orient="records"),
    }


def tuning_snapshot() -> dict[str, object]:
    return {
        "cadence": tuning_cadence_frame().to_dict(orient="records"),
        "model_snippets": tuning_snippet_frame().to_dict(orient="records"),
        "future_ablation_defaults": ablation_tuning_policy_snapshot(),
        "reserved_feature_value_artifacts": rolling_origin_artifact_policy_frame().to_dict(orient="records"),
        "feature_value_scope_decisions": feature_value_scope_decision_frame().to_dict(orient="records"),
    }
