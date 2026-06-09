# MFRR Capacity 12.3_F Down Scenario Collapse Diagnostic Daily V1

## Scope
This note audits why the generated Down accepted-threshold proxy scenarios are nearly collapsed. It does not regenerate scenarios, change the selected rule policy, or create a MILP export.

## Decision Summary
The Down scenario collapse is primarily data-driven, not mainly a scenario-builder bug.

Observed 12.3_F accepted-offer thresholds for Down are already very flat on most days:
- `p90 - p75` has median `0.00` in every Down calibration/evaluation and weekday/weekend slice inspected.
- `max - p90` has median `0.00` in every Down slice.
- `max - p75` also has median `0.00` in every Down slice.

The selected deterministic `direction_daytype_median_markup` method preserves that flat central tendency. It does compress rare nonzero Down tails into a nearly deterministic spread structure, but it is not inventing a collapse that is absent from the observed accepted-offer data.

Recommendation for v1: keep the current threshold scenario artifact for first MILP integration, freeze it with a clear caveat that Down stochastic richness is weak, and plan a simple v2 repair only if downstream results show that richer Down tail variation matters materially.

## Observed Accepted-Stack Spread
Metrics below use the observed threshold table and compare accepted-offer proxy levels directly.

### Down: `p90 - p75`
- Calibration weekday: mean `0.0110`, median `0.0000`, p90 `0.0300`, max `0.4000`, share zero `0.768`, share `<= 0.05` `0.952`
- Calibration weekend: mean `0.0328`, median `0.0000`, p90 `0.0800`, max `0.5800`, share zero `0.760`, share `<= 0.05` `0.880`
- Evaluation weekday: mean `0.0174`, median `0.0000`, p90 `0.0100`, max `0.9600`, share zero `0.864`, share `<= 0.05` `0.970`
- Evaluation weekend: mean `0.0085`, median `0.0000`, p90 `0.0100`, max `0.1700`, share zero `0.885`, share `<= 0.05` `0.962`

### Down: `max - p90`
- Calibration weekday: mean `0.1517`, median `0.0000`, p90 `0.0000`, max `18.2500`, share zero `0.968`, share `<= 0.05` `0.968`
- Calibration weekend: mean `0.0888`, median `0.0000`, p90 `0.0000`, max `1.8700`, share zero `0.940`, share `<= 0.05` `0.940`
- Evaluation weekday: mean `0.1208`, median `0.0000`, p90 `0.0000`, max `4.2700`, share zero `0.970`, share `<= 0.05` `0.970`
- Evaluation weekend: mean `0.1669`, median `0.0000`, p90 `0.0000`, max `4.3300`, share zero `0.923`, share `<= 0.05` `0.962`

### Down: `max - p75`
- Calibration weekday: mean `0.1627`, median `0.0000`, p90 `0.0300`, max `18.2500`, share zero `0.752`, share `<= 0.05` `0.928`
- Calibration weekend: mean `0.1216`, median `0.0000`, p90 `0.0830`, max `2.2600`, share zero `0.740`, share `<= 0.05` `0.860`
- Evaluation weekday: mean `0.1382`, median `0.0000`, p90 `0.0100`, max `4.3900`, share zero `0.848`, share `<= 0.05` `0.955`
- Evaluation weekend: mean `0.1754`, median `0.0000`, p90 `0.0150`, max `4.5000`, share zero `0.846`, share `<= 0.05` `0.962`

Interpretation:
- Down accepted stacks are genuinely flat for most rows.
- Nonzero spreads exist, but mostly as rare tail events rather than typical daily structure.
- The mean is occasionally lifted by a few large maxima, but the median and upper-middle quantiles remain near zero.

## Markup Compression Diagnostic
Using the selected rule family in the threshold backtest:
- anchor: `naive_lag_7d_same_direction`
- markup rule: `direction_daytype_median_markup`

Calibrated markup values:
- Down weekday: `p75 = 0.040`, `p90 = 0.040`, `max = 0.040`
- Down weekend: `p75 = 0.165`, `p90 = 0.180`, `max = 0.180`
- Up weekday: `p75 = 0.940`, `p90 = 1.140`, `max = 2.200`
- Up weekend: `p75 = 0.115`, `p90 = 0.165`, `max = 0.205`

Derived markup spreads:
- Down weekday: `p90 - p75 = 0.000`, `max - p90 = 0.000`, `max - p75 = 0.000`
- Down weekend: `p90 - p75 = 0.015`, `max - p90 = 0.000`, `max - p75 = 0.015`
- Up weekday: `0.200`, `1.060`, `1.260`
- Up weekend: `0.050`, `0.040`, `0.090`

Interpretation:
- For Down, the selected median-markup rule reproduces the typical observed central tendency almost exactly.
- It does compress rare nonzero Down tail spreads because a single daytype median cannot preserve occasional large `max - p90` or `max - p75` excursions.
- The collapse therefore comes mostly from the observed data being flat, with a secondary contribution from deterministic median aggregation removing rare-tail richness.

## Current Scenario Spread Confirmation
Current scenario artifact spreads reproduce the selected markups exactly:
- Down weekday: conservative to central `0.000`, central to optimistic `0.000`
- Down weekend: conservative to central `0.015`, central to optimistic `0.000`
- Up weekday: `0.200`, `1.060`
- Up weekend: `0.050`, `0.040`

These values are identical in synthetic pre-overlap and observed-overlap periods because the scenario method applies fixed calibration-derived daytype markups across the whole test horizon.

## Alternative Method Assessment
1. Keep current deterministic daytype-median markups
- Classification: `keep_for_v1`
- Reason: stable, monotonic, simple, and broadly consistent with the observed Down central tendency.

2. Use direction-level quantile markups consistently
- Classification: `reject`
- Reason: likely to inject extra spread mechanically rather than from observed Down structure, and would weaken the current simple/monotonic interpretation without clear evidence of better realism.

3. Use empirical daily spread sampling from calibration days
- Classification: `too_complex_for_v1`
- Reason: could preserve richer empirical spread structure, but introduces sampling design, temporal coherence, and reproducibility questions that are not justified before first MILP integration.

4. Use fixed observed spread add-ons
- Classification: `promising_for_v1_repair`
- Reason: `central = conservative + median observed (p90 - p75)` and `optimistic = central + median observed (max - p90)` would preserve monotonicity and keep observed spread logic explicit. This is the cleanest v2 repair candidate if Down richness later proves too weak.

## Recommendation
Recommendation: keep the current threshold scenario artifact as v1 for first MILP integration, with an explicit caveat, and plan a simple v2 repair only if needed.

Reasoning:
- The Down collapse is primarily data-driven.
- The deterministic median-markup method does remove rare nonzero Down tails, but it is not collapsing a rich observed spread into a flat scenario set.
- For first MILP integration, the current artifact is still methodologically defensible because it preserves the central accepted-offer structure and keeps the scenario design transparent.
- If downstream MILP results show that Down-side stochastic richness materially affects outcomes, the first repair to test should be fixed observed spread add-ons, not a full sampling framework.

## Caveats
- `12.3.F` contains accepted/procured offers only.
- Rejected bids are unobserved.
- These are accepted-threshold proxies, not full submitted bid ladders.
- `max` is an optimistic upper-bound proxy, not a true market-clearing threshold.
- Pre-`2025-01-07` thresholds are synthetic/proxy only.
- Scenario probabilities are scenario weights, not empirical probabilities.
- No plant feasibility, activation, or MILP bidding logic is included yet.
