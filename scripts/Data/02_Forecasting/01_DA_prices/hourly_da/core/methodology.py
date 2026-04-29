from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


FIRST_SHORTLIST_STAGE = "FS2"
STARTER_ENDOGENOUS_FEATURE_NOTE = (
    "FS1 is the explicit endogenous feature foundation. The current implementation uses one compact pre-registered "
    "endogenous pool: raw lag anchors {lag_1, lag_2, lag_24, lag_25, lag_168, lag_169}, lag differences, rolling "
    "regime descriptors, and block summary statistics. This frozen benchmark foundation keeps the stage "
    "interpretable, leakage-safe, and reusable for later FS levels without turning FS1 into an uncontrolled lag "
    "buffet."
)

ACTIVE_BASELINE_MODEL_NAMES = (
    "naive_previous_week",
    "naive_previous_year",
)

ACTIVE_MODEL_FAMILIES = ("naive", "lear", "xgboost", "prophet")
RETIRED_MODEL_FAMILIES = ("arima", "sarima")


@dataclass(frozen=True)
class FeatureStagePolicy:
    fs_level: str
    feature_scope: str
    active_model_families: tuple[str, ...]
    prophet_policy: str
    shortlisting_policy: str
    tuning_policy: str
    implementation_status: str
    notes: str


@dataclass(frozen=True)
class ModelStatusPolicy:
    model_family: str
    status: str
    first_fs_level: str
    summary: str


FEATURE_STAGE_POLICIES: tuple[FeatureStagePolicy, ...] = (
    FeatureStagePolicy(
        fs_level="FS0",
        feature_scope="Seasonal naive benchmark only: previous-week and previous-year.",
        active_model_families=("naive",),
        prophet_policy="Not applicable at FS0.",
        shortlisting_policy="No shortlisting.",
        tuning_policy="No tuning.",
        implementation_status="Active",
        notes="Both active seasonal naive baselines are evaluated so the benchmark can be chosen on validation.",
    ),
    FeatureStagePolicy(
        fs_level="FS1",
        feature_scope=(
            "Explicit endogenous feature foundation only: compact raw lags, lag differences, rolling regime "
            "descriptors, and recent block summaries."
        ),
        active_model_families=("lear", "xgboost"),
        prophet_policy="Prophet is deliberately excluded at FS1.",
        shortlisting_policy="No shortlisting. LEAR and XGBoost both continue to FS2.",
        tuning_policy="Fast or coarse validation-only tuning, then freeze settings for FS1.",
        implementation_status="Active",
        notes=STARTER_ENDOGENOUS_FEATURE_NOTE,
    ),
    FeatureStagePolicy(
        fs_level="FS2",
        feature_scope="FS1 endogenous foundation plus forecast-known calendar and holiday structure.",
        active_model_families=("lear", "xgboost", "prophet"),
        prophet_policy="Prophet enters for the first time at FS2 because calendar and holiday structure is now meaningful.",
        shortlisting_policy="First real shortlist point across the FS2 stack.",
        tuning_policy="First serious validation-only tuning round, then freeze settings for FS2.",
        implementation_status="Active",
        notes=(
            "LEAR and XGBoost keep using explicit regressors. Prophet joins only here and should remain compact and "
            "causal."
        ),
    ),
    FeatureStagePolicy(
        fs_level="FS3",
        feature_scope="FS2 foundation plus causal exogenous feature families added gradually.",
        active_model_families=("shortlisted_fs2_survivors",),
        prophet_policy="Carry Prophet into FS3 only if it survives FS2 and the regressor set stays compact and causal.",
        shortlisting_policy="Only survivors shortlisted after FS2 continue into FS3.",
        tuning_policy="Mandatory retuning because the feature space changes materially.",
        implementation_status="Planned scaffold",
        notes=(
            "Examples include load forecast, wind forecast, solar forecast, net load, and neighboring market signals "
            "only when causally available."
        ),
    ),
    FeatureStagePolicy(
        fs_level="FS4",
        feature_scope="Advanced engineered feature layer on top of the causal stack.",
        active_model_families=("finalists",),
        prophet_policy="Use Prophet at FS4 only with a strong reason and a compact causal regressor set.",
        shortlisting_policy="Only finalist models continue.",
        tuning_policy="Selective rigorous retuning for surviving finalists only.",
        implementation_status="Planned",
        notes=(
            "Main focus is likely XGBoost and possibly LEAR, with Huang-style similar-day summaries and embedded "
            "selection."
        ),
    ),
)

MODEL_STATUS_POLICIES: tuple[ModelStatusPolicy, ...] = (
    ModelStatusPolicy(
        model_family="naive",
        status="Active",
        first_fs_level="FS0",
        summary="Seasonal naive previous-week and previous-year baselines remain active.",
    ),
    ModelStatusPolicy(
        model_family="lear",
        status="Active",
        first_fs_level="FS1",
        summary="LEAR is active from FS1 onward as the main linear benchmark.",
    ),
    ModelStatusPolicy(
        model_family="xgboost",
        status="Active",
        first_fs_level="FS1",
        summary="XGBoost is active from FS1 onward and is expected to remain central in later stages.",
    ),
    ModelStatusPolicy(
        model_family="prophet",
        status="Active",
        first_fs_level="FS2",
        summary="Prophet joins only from FS2 onward when calendar and holiday structure are available.",
    ),
    ModelStatusPolicy(
        model_family="arima",
        status="Retired",
        first_fs_level="None",
        summary="ARIMA is removed from the active DAM methodology and kept only as archived history.",
    ),
    ModelStatusPolicy(
        model_family="sarima",
        status="Retired",
        first_fs_level="None",
        summary="SARIMA is removed from the active DAM methodology and kept only as archived history.",
    ),
)


def feature_stage_policy_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for policy in FEATURE_STAGE_POLICIES:
        row = asdict(policy)
        row["active_model_families"] = ", ".join(policy.active_model_families)
        rows.append(row)
    return pd.DataFrame(rows)


def model_status_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(policy) for policy in MODEL_STATUS_POLICIES])


def shortlisting_policy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_point": "After FS1",
                "policy": "No shortlist. Keep LEAR and XGBoost alive into FS2.",
            },
            {
                "decision_point": "After FS2",
                "policy": "First fair shortlist across LEAR, XGBoost, and Prophet.",
            },
            {
                "decision_point": "After FS3",
                "policy": "Feature-family promotion within the already-shortlisted survivor set.",
            },
            {
                "decision_point": "After FS4",
                "policy": "Finalist selection only.",
            },
        ]
    )


def methodology_snapshot() -> dict[str, object]:
    return {
        "first_shortlist_stage": FIRST_SHORTLIST_STAGE,
        "starter_endogenous_feature_note": STARTER_ENDOGENOUS_FEATURE_NOTE,
        "active_baseline_model_names": list(ACTIVE_BASELINE_MODEL_NAMES),
        "active_model_families": list(ACTIVE_MODEL_FAMILIES),
        "retired_model_families": list(RETIRED_MODEL_FAMILIES),
        "feature_stages": feature_stage_policy_frame().to_dict(orient="records"),
        "model_status": model_status_frame().to_dict(orient="records"),
        "shortlisting_policy": shortlisting_policy_frame().to_dict(orient="records"),
    }
