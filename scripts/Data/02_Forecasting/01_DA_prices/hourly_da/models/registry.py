from __future__ import annotations

from .naive import PreviousWeekNaiveModel, PreviousYearNaiveModel


def build_naive_baseline_models() -> list:
    return [
        PreviousWeekNaiveModel(),
        PreviousYearNaiveModel(),
    ]


def naive_model_names() -> tuple[str, ...]:
    return (
        "naive_previous_week",
        "naive_previous_year",
    )
