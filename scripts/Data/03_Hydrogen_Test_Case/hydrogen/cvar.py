from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WeightedCvarResult:
    alpha: float
    zeta: float
    cvar: float
    expected_loss: float
    losses: np.ndarray
    probabilities: np.ndarray
    xi: np.ndarray


def validate_probability_vector(probabilities: np.ndarray, *, tolerance: float = 1e-9) -> None:
    if probabilities.ndim != 1:
        raise ValueError("probabilities must be a 1D vector.")
    if len(probabilities) == 0:
        raise ValueError("probabilities is empty.")
    if np.any(probabilities < -tolerance):
        raise ValueError("probabilities must be nonnegative.")
    total = float(np.sum(probabilities))
    if abs(total - 1.0) > tolerance:
        raise ValueError(f"probabilities must sum to 1.0, got {total:.12f}")


def compute_weighted_cvar(losses: np.ndarray, probabilities: np.ndarray, *, alpha: float) -> WeightedCvarResult:
    loss_vector = np.asarray(losses, dtype=float).reshape(-1)
    probability_vector = np.asarray(probabilities, dtype=float).reshape(-1)
    if loss_vector.shape != probability_vector.shape:
        raise ValueError("losses and probabilities must have the same length.")
    if not 0.0 < float(alpha) < 1.0:
        raise ValueError("alpha must lie strictly between 0 and 1.")
    validate_probability_vector(probability_vector)

    candidates = np.unique(loss_vector)
    objective_values = []
    xi_by_candidate = []
    scale = 1.0 / (1.0 - float(alpha))
    for candidate in candidates:
        xi = np.maximum(loss_vector - float(candidate), 0.0)
        objective = float(candidate + scale * np.sum(probability_vector * xi))
        objective_values.append(objective)
        xi_by_candidate.append(xi)
    best_index = int(np.argmin(objective_values))
    zeta = float(candidates[best_index])
    xi = xi_by_candidate[best_index]
    cvar = float(objective_values[best_index])
    expected_loss = float(np.sum(probability_vector * loss_vector))
    return WeightedCvarResult(
        alpha=float(alpha),
        zeta=zeta,
        cvar=cvar,
        expected_loss=expected_loss,
        losses=loss_vector,
        probabilities=probability_vector,
        xi=xi.astype(float),
    )


def compute_weighted_cvar_from_frame(
    frame: pd.DataFrame,
    *,
    loss_column: str = "loss_eur",
    probability_column: str = "scenario_probability",
    alpha: float,
) -> WeightedCvarResult:
    if loss_column not in frame.columns or probability_column not in frame.columns:
        raise ValueError(
            f"Frame must contain {loss_column!r} and {probability_column!r} to compute weighted CVaR."
        )
    return compute_weighted_cvar(
        frame[loss_column].astype(float).to_numpy(),
        frame[probability_column].astype(float).to_numpy(),
        alpha=float(alpha),
    )
