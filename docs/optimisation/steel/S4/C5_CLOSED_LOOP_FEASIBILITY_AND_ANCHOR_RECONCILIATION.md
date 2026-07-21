# C5 Closed-Loop Feasibility and Anchor Reconciliation

## Purpose

This stage turns the deterministic steel planning window into a genuine
receding-horizon feasibility test.  It solves 168 hours, executes only the
first 24 hours, transfers represented material inventories into the next solve,
and repeats.  It also annualises the first planning window for **reporting-only
comparison** with the canonical C5 anchor register.

## Closed-loop policy

- Only represented material buffers are handed over: coke, sinter, hot iron,
  cold slab and C1 DRI.
- Steam, WAG and residual electricity/NG are flows or diagnostics, not stores;
  they are never handed over as fictitious inventory.
- Each new 168-hour plan retains hard cumulative final-product deadlines and
  terminal equality to its inherited start state.
- C0 retains the fixed governed schedule. C1 retains the bottom-up fixed
  retained-route policy.
- Prices, DA, revenues, ETS costs and residual filling remain disabled.

## Annual anchor comparison policy

The run reports a `8760 / 168` extrapolation of the first planning window. It
is not a year simulation and it cannot establish a thesis claim by itself.

Every anchor row is classified as one of:

- `partial_comparable`: a numerical comparison is informative, but a site or
  plant boundary caveat remains;
- `not_directly_comparable`: value is retained for context, but denominator,
  unit, process boundary or coverage prevents a score;
- `out_of_scope_or_generic`: generic/sensitivity/historical context only.

Examples of intentionally non-direct comparisons are liquid-steel anchors
against final-product proxy, full-site Scope 1 against explicit WAG-only CO2,
and full-site ASU demand against an incomplete utility layer.

## Required outputs

The local run folder includes:

- `rolling_execution.csv`: executed 24-hour blocks and cumulative quota;
- `inventory_handoff.csv`: starting and transferred represented inventories;
- `annual_plant_metrics.csv`: annualised model activity by plant;
- `annual_anchor_reconciliation.csv`: all canonical anchors, with comparison
  status and gaps where defensible;
- validation, config, manifest and limitations files.

## Gate

A pass means only that represented material inventory handoff, production
quota, WAG/steam/utility accounting and anchor reporting execute without
relaxing the physical model.  It does not mean that the model is annual,
full-site, ETS-ready, economics-ready or anchor-calibrated.
