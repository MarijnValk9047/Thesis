"""Coupled hourly/quarter-hour D..D+4 residual-path scenarios."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist


@dataclass(frozen=True)
class ResidualBlock:
    block_id: str
    source_origin_utc: pd.Timestamp
    available_at_utc: pd.Timestamp
    dataset_split: str
    hourly_by_lead: tuple[np.ndarray, ...]
    shape_by_lead: tuple[np.ndarray, ...]


@dataclass(frozen=True)
class RawCoupledPaths:
    hourly: np.ndarray
    quarterhour: np.ndarray
    source_block_ids: tuple[str, ...]


def stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % (2**32 - 1)


def _resize(values: np.ndarray, length: int) -> np.ndarray:
    source = np.asarray(values, dtype=float)
    if source.size == int(length):
        return source.copy()
    if source.size == 0:
        return np.zeros(int(length), dtype=float)
    if source.size == 1:
        return np.repeat(source[0], int(length)).astype(float)
    source_x = np.linspace(0.0, 1.0, num=source.size)
    target_x = np.linspace(0.0, 1.0, num=int(length))
    return np.interp(target_x, source_x, source).astype(float)


def _centre_within_hour(values: np.ndarray, qh_to_hour: np.ndarray) -> np.ndarray:
    centred = np.asarray(values, dtype=float).copy()
    mapping = np.asarray(qh_to_hour, dtype=int)
    for hour_index in np.unique(mapping):
        mask = mapping == int(hour_index)
        centred[mask] -= float(np.mean(centred[mask]))
    return centred


def eligible_blocks(
    blocks: Iterable[ResidualBlock],
    *,
    forecast_origin_utc: pd.Timestamp,
    allowed_splits: set[str],
) -> list[ResidualBlock]:
    origin = pd.Timestamp(forecast_origin_utc)
    return [
        block
        for block in blocks
        if block.dataset_split in allowed_splits and pd.Timestamp(block.available_at_utc) < origin
    ]


def generate_raw_coupled_paths(
    *,
    hourly_point: np.ndarray,
    qh_point: np.ndarray,
    hourly_counts_by_lead: tuple[int, ...],
    qh_counts_by_lead: tuple[int, ...],
    qh_to_hour: np.ndarray,
    residual_blocks: list[ResidualBlock],
    n_raw: int,
    level_scale: float,
    shape_scale: float,
    seed: int,
) -> RawCoupledPaths:
    if not residual_blocks:
        raise ValueError("no causally eligible residual blocks")
    hourly_central = np.asarray(hourly_point, dtype=float)
    qh_central = np.asarray(qh_point, dtype=float)
    if sum(hourly_counts_by_lead) != hourly_central.size:
        raise ValueError("hourly lead-day counts do not match the hourly point path")
    if sum(qh_counts_by_lead) != qh_central.size:
        raise ValueError("quarter-hour lead-day counts do not match the QH point path")
    rng = np.random.default_rng(int(seed))
    sampled = rng.integers(0, len(residual_blocks), size=int(n_raw))
    hourly_paths = np.empty((int(n_raw), hourly_central.size), dtype=float)
    qh_paths = np.empty((int(n_raw), qh_central.size), dtype=float)
    source_ids: list[str] = []
    for scenario_index, block_index in enumerate(sampled.tolist()):
        block = residual_blocks[int(block_index)]
        level_parts = [
            _resize(block.hourly_by_lead[lead], count)
            for lead, count in enumerate(hourly_counts_by_lead)
        ]
        shape_parts = [
            _resize(block.shape_by_lead[lead], count)
            for lead, count in enumerate(qh_counts_by_lead)
        ]
        level = np.concatenate(level_parts)
        shape_error = _centre_within_hour(np.concatenate(shape_parts), qh_to_hour)
        hourly_scenario = hourly_central + float(level_scale) * level
        expanded_level = hourly_scenario[np.asarray(qh_to_hour, dtype=int)] - hourly_central[np.asarray(qh_to_hour, dtype=int)]
        qh_scenario = qh_central + expanded_level + float(shape_scale) * shape_error
        # Numeric finaliser: retain exact scenario-wise hourly means.
        discrepancy = np.empty_like(qh_scenario)
        for hour_index in np.unique(qh_to_hour):
            mask = np.asarray(qh_to_hour, dtype=int) == int(hour_index)
            discrepancy[mask] = float(np.mean(qh_scenario[mask]) - hourly_scenario[int(hour_index)])
        qh_scenario -= discrepancy
        hourly_paths[scenario_index] = hourly_scenario
        qh_paths[scenario_index] = qh_scenario
        source_ids.append(block.block_id)
    return RawCoupledPaths(hourly=hourly_paths, quarterhour=qh_paths, source_block_ids=tuple(source_ids))


def weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    x = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(x, kind="stable")
    x = x[order]
    w = w[order]
    cumulative = np.cumsum(w)
    if cumulative[-1] <= 0.0:
        return float("nan")
    return float(np.interp(float(quantile) * cumulative[-1], cumulative, x))


def weighted_interval_summary(paths: np.ndarray, actual: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    samples = np.asarray(paths, dtype=float)
    truth = np.asarray(actual, dtype=float)
    probability = np.asarray(weights, dtype=float)
    probability = probability / probability.sum()
    quantiles = {
        q: np.asarray([weighted_quantile(samples[:, index], probability, q) for index in range(samples.shape[1])])
        for q in (0.05, 0.10, 0.50, 0.90, 0.95)
    }
    return {
        "coverage_p10_p90": float(np.mean((truth >= quantiles[0.10]) & (truth <= quantiles[0.90]))),
        "coverage_p05_p95": float(np.mean((truth >= quantiles[0.05]) & (truth <= quantiles[0.95]))),
        "average_width_p10_p90": float(np.mean(quantiles[0.90] - quantiles[0.10])),
        "average_width_p05_p95": float(np.mean(quantiles[0.95] - quantiles[0.05])),
        "p50_bias": float(np.mean(quantiles[0.50] - truth)),
        "high_tail_miss_rate": float(np.mean(truth > quantiles[0.95])),
        "low_tail_miss_rate": float(np.mean(truth < quantiles[0.05])),
        "min_max_containment": float(np.mean((truth >= samples.min(axis=0)) & (truth <= samples.max(axis=0)))),
    }


def crps_by_timestamp(paths: np.ndarray, actual: np.ndarray, weights: np.ndarray) -> np.ndarray:
    samples = np.asarray(paths, dtype=float)
    truth = np.asarray(actual, dtype=float)
    probability = np.asarray(weights, dtype=float)
    probability = probability / probability.sum()
    first = np.sum(probability[:, None] * np.abs(samples - truth[None, :]), axis=0)
    second = np.zeros(samples.shape[1], dtype=float)
    for index in range(samples.shape[1]):
        x = samples[:, index]
        order = np.argsort(x, kind="stable")
        sorted_x = x[order]
        sorted_w = probability[order]
        cum_w = np.cumsum(sorted_w)
        cum_wx = np.cumsum(sorted_w * sorted_x)
        left_w = np.concatenate(([0.0], cum_w[:-1]))
        left_wx = np.concatenate(([0.0], cum_wx[:-1]))
        pair_sum = np.sum(sorted_w * (sorted_x * left_w - left_wx))
        second[index] = pair_sum
    return first - second


def energy_score(paths: np.ndarray, actual: np.ndarray, weights: np.ndarray) -> float:
    samples = np.asarray(paths, dtype=float)
    truth = np.asarray(actual, dtype=float)
    probability = np.asarray(weights, dtype=float)
    probability = probability / probability.sum()
    first = float(np.sum(probability * np.linalg.norm(samples - truth[None, :], axis=1)))
    pair = cdist(samples, samples, metric="euclidean")
    second = 0.5 * float(np.sum(probability[:, None] * probability[None, :] * pair))
    return first - second
