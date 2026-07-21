# C5 Anchor Boundary Reconciliation Design

## Purpose

This compact C5p_ah stage turns the unresolved annual-anchor comparisons into
explicit design decisions. It does not change the model, source cards,
coefficients, or executable inputs, and it does not run sensitivities.

## Decisions

- Athanasiadis Table 8/9 WAG totals remain Rank-3 model-precedent context only.
  Their metric definition and denominator are unresolved, so they cannot score
  or tune the model.
- A denominator bridge is required before any combined annual anchor score:
  model final-product proxy, liquid steel, HRC/downstream, and site totals must
  remain distinct.
- Current residual electricity and NG are signed reporting KPIs, never hidden
  loads, costs, allocations, or calibration plugs.
- C1 non-WAG electricity decomposition may proceed. It must keep gross demand,
  internal generation offsets, grid import, and WAG interpretation separate.
- C5p_o remains the authoritative diagnostic WAG interface. Aggregate WAG,
  mixed WAG, and C5p_k cannot be used for physical reconciliation.

## Gate

The next safe implementation is a non-WAG C1 electricity-boundary
decomposition. Sensitivity scoring remains blocked until a numerator,
denominator, scaling rule, locator status, and boundary are explicit for every
scored anchor.
