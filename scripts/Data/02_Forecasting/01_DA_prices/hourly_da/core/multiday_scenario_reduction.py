"""Probability-aware reduction for coherent multi-day price paths.

The reducer is deliberately independent of realised target prices.  It selects
tail paths from the generated distribution itself, then assigns every source
path to its nearest retained medoid and transfers the complete cluster mass.
It can therefore be used for both the raw->30 and nested 30->10 reductions
without introducing evaluation-period information.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PathReductionResult:
    representative_indices: np.ndarray
    representative_ids: tuple[str, ...]
    probabilities: np.ndarray
    source_to_representative_index: np.ndarray
    protected_representative_ids: tuple[str, ...]


def _standardise_paths(paths: np.ndarray) -> np.ndarray:
    values = np.asarray(paths, dtype=float)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("paths must be a non-empty two-dimensional array")
    centre = np.nanmedian(values, axis=0)
    q75 = np.nanpercentile(values, 75.0, axis=0)
    q25 = np.nanpercentile(values, 25.0, axis=0)
    scale = q75 - q25
    fallback = np.nanstd(values, axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, fallback)
    scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, 1.0)
    return np.nan_to_num((values - centre) / scale, nan=0.0, posinf=0.0, neginf=0.0)


def _tail_indices(paths: np.ndarray, count: int) -> list[int]:
    if count <= 0:
        return []
    values = np.asarray(paths, dtype=float)
    ramps = np.max(np.abs(np.diff(values, axis=1)), axis=1) if values.shape[1] > 1 else np.zeros(values.shape[0])
    metrics = (
        np.max(values, axis=1),
        -np.min(values, axis=1),
        np.ptp(values, axis=1),
        np.mean(np.maximum(values - np.median(values, axis=0), 0.0), axis=1),
        np.mean(np.maximum(np.median(values, axis=0) - values, 0.0), axis=1),
        ramps,
    )
    selected: list[int] = []
    for metric in metrics:
        idx = int(np.nanargmax(metric))
        if idx not in selected:
            selected.append(idx)
        if len(selected) >= count:
            return selected
    ranks = np.zeros(values.shape[0], dtype=float)
    for metric in metrics:
        order = np.argsort(np.argsort(np.nan_to_num(metric, nan=-np.inf)))
        ranks += order
    for idx in np.argsort(-ranks, kind="stable"):
        candidate = int(idx)
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= count:
            break
    return selected


def _squared_distances(paths: np.ndarray, medoid_indices: list[int]) -> np.ndarray:
    selected = paths[np.asarray(medoid_indices, dtype=int)]
    return np.mean((paths[:, None, :] - selected[None, :, :]) ** 2, axis=2)


def reduce_weighted_paths(
    paths: np.ndarray,
    *,
    scenario_ids: list[str] | tuple[str, ...],
    weights: np.ndarray | None,
    n_keep: int,
    protected_count: int,
) -> PathReductionResult:
    """Reduce complete paths and transfer empirical mass to retained medoids."""

    values = np.asarray(paths, dtype=float)
    ids = tuple(str(value) for value in scenario_ids)
    if values.ndim != 2 or values.shape[0] != len(ids):
        raise ValueError("paths and scenario_ids have incompatible shapes")
    if not 1 <= int(n_keep) <= values.shape[0]:
        raise ValueError("n_keep must lie between one and the source scenario count")
    source_weights = np.ones(values.shape[0], dtype=float) if weights is None else np.asarray(weights, dtype=float)
    if source_weights.shape != (values.shape[0],) or np.any(source_weights < 0.0):
        raise ValueError("weights must be a non-negative vector with one entry per path")
    total = float(source_weights.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError("weights must have positive finite mass")
    source_weights = source_weights / total

    scaled = _standardise_paths(values)
    protected = _tail_indices(values, min(int(protected_count), int(n_keep)))
    medoids = list(protected)
    if not medoids:
        medoids.append(int(np.argmax(source_weights)))
    while len(medoids) < int(n_keep):
        distance = _squared_distances(scaled, medoids).min(axis=1)
        distance[np.asarray(medoids, dtype=int)] = -np.inf
        score = distance * np.sqrt(np.maximum(source_weights, 1e-15))
        medoids.append(int(np.argmax(score)))

    distances = _squared_distances(scaled, medoids)
    assignment = np.argmin(distances, axis=1).astype(int)
    # Every medoid represents itself, including protected tails.
    for representative_position, source_index in enumerate(medoids):
        assignment[int(source_index)] = int(representative_position)
    reduced_weights = np.bincount(assignment, weights=source_weights, minlength=len(medoids)).astype(float)
    reduced_weights /= reduced_weights.sum()
    representative_ids = tuple(ids[index] for index in medoids)
    protected_ids = tuple(ids[index] for index in protected)
    return PathReductionResult(
        representative_indices=np.asarray(medoids, dtype=int),
        representative_ids=representative_ids,
        probabilities=reduced_weights,
        source_to_representative_index=assignment,
        protected_representative_ids=protected_ids,
    )


def assert_nested_reduction(
    parent_ids: list[str] | tuple[str, ...],
    child_result: PathReductionResult,
    *,
    tolerance: float = 1e-12,
) -> None:
    parent = tuple(str(value) for value in parent_ids)
    if not set(child_result.representative_ids).issubset(set(parent)):
        raise AssertionError("nested reduction contains a representative outside the parent set")
    if abs(float(child_result.probabilities.sum()) - 1.0) > float(tolerance):
        raise AssertionError("nested reduction probabilities do not sum to one")
    if child_result.source_to_representative_index.shape != (len(parent),):
        raise AssertionError("nested reduction mapping does not cover every parent scenario")
