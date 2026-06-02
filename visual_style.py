"""Project-wide visual style utilities for thesis/reporting figures.

Use this module in notebooks and reporting scripts before plotting:

    from src.reporting.visual_style import (
        COLORS,
        MODEL_COLORS,
        STRATEGY_COLORS,
        MARKET_CHAIN_COLORS,
        apply_visual_style,
        save_figure,
    )

    apply_visual_style()

The module intentionally stays lightweight: it defines semantic colours,
Matplotlib defaults, and small helpers. Chart-choice rules belong in
VISUALISATION.md.
"""

from pathlib import Path

import matplotlib.pyplot as plt
from cycler import cycler


COLORS = {
    "actual": "#222222",
    "main_model": "#1F4E79",
    "alternative_model": "#C97941",
    "third_model": "#3A7D7C",
    "benchmark": "#7A7A7A",
    "perfect_foresight": "#6F7D4E",
    "price_insensitive": "#333333",
    "risk_neutral": "#1F4E79",
    "cvar_sensitive": "#C97941",
    "uncertainty": "#DDEAF2",
    "scenario_path": "#A8C3D8",
    "violation": "#B85C5C",
    "warning": "#B85C5C",
    "grid": "#D9D9D9",
    "background": "#FAFAF7",
    "text": "#2B2D33",
    "muted_plum": "#7A5C8C",
    "muted_olive": "#6F7D4E",
    "light_neutral": "#EEF1F2",
}


MODEL_COLORS = {
    "XGBoost FS3": "#1F4E79",
    "Hourly XGBoost FS3": "#1F4E79",
    "QH XGBoost FS3": "#1F4E79",
    "LEAR FS3": "#3A7D7C",
    "Hourly LEAR FS3": "#3A7D7C",
    "QH LEAR FS3": "#3A7D7C",
    "LEAR Strict": "#C97941",
    "Hourly LEAR Strict": "#C97941",
    "QH LEAR Strict": "#C97941",
    "Naive": "#7A7A7A",
    "Benchmark": "#7A7A7A",
    "Perfect foresight": "#6F7D4E",
    "Price insensitive": "#333333",
}


STRATEGY_COLORS = {
    "perfect_foresight": "#6F7D4E",
    "perfect foresight": "#6F7D4E",
    "oracle": "#6F7D4E",
    "price_insensitive": "#333333",
    "price insensitive": "#333333",
    "risk_neutral": "#1F4E79",
    "risk neutral": "#1F4E79",
    "forecast_based": "#1F4E79",
    "forecast based": "#1F4E79",
    "stochastic_risk_neutral": "#1F4E79",
    "stochastic risk neutral": "#1F4E79",
    "cvar_sensitive": "#C97941",
    "cvar sensitive": "#C97941",
    "risk_averse": "#C97941",
    "risk averse": "#C97941",
    "naive": "#7A7A7A",
    "benchmark": "#7A7A7A",
}


MARKET_CHAIN_COLORS = {
    "submitted_energy": "#5B7894",
    "cleared_energy": "#1F4E79",
    "used_energy": "#3A7D7C",
    "unused_cleared_energy": "#C97941",
    "rejected_energy": "#B85C5C",
    "realised_price": "#222222",
    "bid_price": "#7A5C8C",
    "settlement_cost": "#C97941",
    "hydrogen_revenue": "#6F7D4E",
    "penalty_or_shortfall": "#B85C5C",
}


METRIC_COLORS = {
    "profit": "#1F4E79",
    "cost": "#C97941",
    "revenue": "#6F7D4E",
    "production": "#3A7D7C",
    "risk": "#C97941",
    "cvar": "#C97941",
    "shortfall": "#B85C5C",
    "violation": "#B85C5C",
    "runtime": "#7A5C8C",
    "mip_gap": "#7A7A7A",
}


DEFAULT_COLOR_CYCLE = [
    COLORS["main_model"],
    COLORS["alternative_model"],
    COLORS["third_model"],
    COLORS["muted_plum"],
    COLORS["muted_olive"],
    COLORS["benchmark"],
]


def apply_visual_style() -> None:
    """Apply project-wide Matplotlib defaults for academic figures."""

    plt.rcParams.update(
        {
            "figure.figsize": (8, 4.5),
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "axes.edgecolor": COLORS["text"],
            "axes.labelcolor": COLORS["text"],
            "xtick.color": COLORS["text"],
            "ytick.color": COLORS["text"],
            "text.color": COLORS["text"],
            "axes.grid": True,
            "grid.color": COLORS["grid"],
            "grid.linewidth": 0.6,
            "grid.alpha": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "axes.prop_cycle": cycler(color=DEFAULT_COLOR_CYCLE),
        }
    )


def get_model_color(model_name: str, fallback: str = "#7A7A7A") -> str:
    """Return the approved colour for a model name, with a neutral fallback."""

    return MODEL_COLORS.get(model_name, fallback)


def get_strategy_color(strategy_name: str, fallback: str = "#7A7A7A") -> str:
    """Return the approved colour for a strategy name, with a neutral fallback."""

    return STRATEGY_COLORS.get(strategy_name, fallback)


def save_figure(fig: plt.Figure, output_stem: str | Path, *, save_pdf: bool = True) -> None:
    """Save a Matplotlib figure as 300 dpi PNG and optionally as PDF.

    Parameters
    ----------
    fig:
        Matplotlib figure object.
    output_stem:
        Path without extension, or a path whose suffix will be ignored.
    save_pdf:
        If True, also save a vector PDF version.
    """

    path = Path(output_stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = path.with_suffix("")

    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
    if save_pdf:
        fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
