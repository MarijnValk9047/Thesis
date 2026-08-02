# Strict LEAR hydrogen horizon and granularity comparison

## Status and scope

This record defines the implemented hydrogen comparison that follows the frozen
307-day hourly model-family selection. That earlier experiment is not rerun or
reinterpreted. The present analysis uses Strict LEAR only and separates:

1. the value of extending the planning horizon from D to D--D+4; and
2. the incremental value of moving from hourly to quarter-hour resolution at
   the same D--D+4 horizon.

The compared configurations are `H-D`, `H-D4`, and `QH-D4`. The primary
stochastic strategy uses 30 probability-weighted paths; the nested 10-path set
is a computational sensitivity. All cases are risk-neutral (`cvar_gamma=0`),
with unchanged plant physics, bid ladder, settlement, hydrogen price,
emergency-import price, and quota target.

## Forecast and scenario lineage

`H-D4` and `QH-D4` reuse the canonical forecasting run
`20260729_strict_lear_dplus4_full_a03`. The quarter-hour point forecast is the
causal mean-shape extension of the hourly Strict LEAR anchor, and every
quarter-hour scenario averages exactly to its linked hourly scenario.

`H-D` is a support extension of the already selected frozen
`lago_lear_247_imputed_x2_1092` model. Its 1,092-day window, 247-feature
definition, Lasso/AIC fitting rule, timing, and missing-value policy are held
fixed. Training rolls causally: only rows strictly before each delivery day are
eligible. A historical overlap check must reproduce frozen predictions within
`1e-8 EUR/MWh`; failure blocks the export.

The H-D scenarios do not introduce a second calibration. For lead D, the
innovation of the paired H-D4 path is moved around the frozen H-D anchor:

\[
p^{H-D,s}_{t}=\widehat p^{H-D}_{t}
+\left(p^{H-D4,s}_{t}-\widehat p^{H-D4}_{t}\right).
\]

Thus scenario ID, probability, parent ID, and residual source block remain
linked across the comparison. Historical D-only scenario results remain
model-selection evidence and are not mixed with these common-support paths.

## Support contract

Forecast statistics use 116 common origins for delivery days 18 March through
19 July 2026. Hydrogen execution uses two independent episodes:

- primary: 6 April--19 July 2026 (105 consecutive delivery days);
- secondary: 18--28 March 2026 (11 consecutive delivery days).

Both episodes start from the same frozen physical and quota state. No storage,
power, production, or quota state crosses the unsupported 29 March--5 April
gap. Partial first and last calendar weeks are prorated only over included
delivery days. March--July is an extended out-of-sample evaluation, not a
previously untouched holdout.

## Receding-horizon implementation

At each origin, `H-D` optimizes D and the multiday configurations optimize
D--D+4. Only D bids are cleared, redispatched, and settled. Planned D+1--D+4
decisions are discarded; the next day receives a fresh forecast and solve.
The realized closing storage inventory and electrolyser power become the next
day's initial values, including a boundary ramp constraint. On/off status is
recorded for lineage; no new minimum-up/down or compressor-commitment physics
is invented.

The weekly target is 19,000 kg times the number of supported days in that
calendar week. Compression above the target may be used within the same week
but never becomes credit for another week. Deadline and conservative terminal
feasibility constraints are imposed in every stochastic scenario and in EV,
price-insensitive, true-PF, and realized redispatch models. Hydrogen retains
the historical EUR 8/kg revenue semantics.

All bid-ladder decisions over a solve horizon are scenario-independent. This
is a conservative two-stage representation, not a multistage scenario tree.

## Benchmarks and attribution

Each configuration is run with stochastic-30, stochastic-10, EV-30,
price-insensitive, and configuration-matched true perfect foresight. True PF
uses the same resolution, horizon, bid ladder, physical constraints, quota,
clearing, redispatch, and accounting as its paired configuration. It is an
upper bound, not a feasible forecasting strategy. Historical
`perfect_foresight_market_cap` results are not used.

The primary episode also includes `H-D4|D`: the H-D4 lead-D forecast and paths
are optimized for one day. This separates the point-anchor contribution from
the pure lookahead contribution:

\[
H-D4-H-D=(H-D4|D-H-D)+(H-D4-H-D4|D).
\]

## Metrics and inference

Forecast metrics retain the thesis definitions: MAE, RMSE, signed bias, p90
and p95 absolute error, rMAE against the frozen official previous-week naive
denominator, daily Spearman correlation, top-/bottom-six hit rate, tail MAE,
and absolute high--low spread error. H-D and H-D4 are compared on identical
lead-D timestamps. Scenario metrics are probability weighted and include
p10--p90 and p05--p95 coverage and width, p50 bias, tail misses, min--max
containment, CRPS, full-path energy score, and effective scenario size.

Operational outputs include adjusted profit/net cost, DA cost, paid price,
hydrogen production and compression, shortfall, emergency import, quota
fulfilment, storage bounds, high-price avoidance, low-price capture, solver
status, build/solve/postprocess time, MIP gap, and model size. Terminal
inventory value is removed from each daily result and added exactly once at
episode end.

Headline effects use paired daily differences on the 105-day episode. A
circular moving-block bootstrap uses 10,000 draws, seed 42, and seven-day
blocks; three- and fourteen-day blocks are appendix sensitivities. No
independent-quarter-hour t-test is used.

## Hard gates and interpretation

The full runner blocks headline conclusions when support, probability,
uniqueness, state carryover, solver optimality/0.001-gap, or matched true-PF
dominance fails. The 10-set must remain a nested weighted reduction of the
30-set, and actual prices remain separate from optimization inputs.

The existing scenario-undercoverage result is a mandatory warning, not a
technical failure: these paths can be used to test decision value, but the
analysis must not claim calibrated 90% risk coverage.

## Reproducible entry points and outputs

The canonical runner is
`scripts/Data/03_Hydrogen_Test_Case/run_strict_lear_horizon_granularity_comparison.py`
with configuration
`scripts/Data/03_Hydrogen_Test_Case/configs/strict_lear_horizon_granularity_comparison.yaml`.
The frozen support exporter is
`scripts/Data/02_Forecasting/01_DA_prices/hourly_da/frozen_donly_2026_support.py`.

Governed child artifacts are written below
`scripts/Data/03_Hydrogen_Test_Case/runs/`; the thesis comparison bundle is
written below
`data/03_Hydrogen_Test_Case/horizon_granularity_comparison/`. Large outputs are
generated local evidence and remain Git-ignored.

## Accepted full run and results

The accepted execution is
`20260729_strict_lear_horizon_granularity_full_a01`. All support, solver,
state-carryover, weekly-quota, D-only-settlement, and configuration-matched
true-PF dominance gates pass. The run contains 30 main policy/episode
combinations plus the primary `H-D4|D` attribution control. The primary
`QH-D4` stochastic-30 policy initially reached the 300-second limit for seven
bidding solves. It was rerun uniformly for all 105 primary days with a
900-second limit. Forecasts, scenarios, physics, quotas, risk setting, bid
ladder, settlement, and the 0.001 MIP-gap did not change; all 210 bidding and
redispatch solves then terminated optimally. The failed attempt is retained as
auditable generated evidence.

On the 116-origin statistical support, frozen `H-D` is more accurate on lead D
than the D--D+4 anchor: MAE is 23.589 versus 25.268 EUR/MWh, with a paired
daily HAC/DM loss difference of -1.679 EUR/MWh (`p=0.0329`). On native QH
truth, mean shape lowers MAE from 32.749 for flat hourly repetition to 31.995
EUR/MWh (2.30%) and improves daily Spearman correlation from 0.870 to 0.893.
It does not create hourly accuracy: aggregation remains exactly equal to the
hourly anchor by construction and contract test.

The 30-path hourly D--D+4 set attains only 80.2% p05--p95 coverage overall;
the QH set attains 79.2%. The nested 10-sets attain 75.2% and 74.3%,
respectively. The support is technically complete and probability-consistent,
but these values confirm material undercoverage and prohibit calibrated 90%
risk claims.

For the primary 105-day episode, stochastic-30 realised adjusted profit is:

| Configuration | Profit (EUR m) | Uplift vs matched PI (EUR m) | Regret vs matched PF (EUR m) | Value captured |
|---|---:|---:|---:|---:|
| `H-D` | 6.692 | 0.740 | 0.206 | 78.2% |
| `H-D4` | 6.775 | 0.905 | 0.076 | 92.2% |
| `QH-D4` | 5.047 | -0.824 | 1.654 | -99.2% |

The observed horizon value is EUR 82,835, or EUR 789/day. The primary
seven-day moving-block-bootstrap 95% interval is -451 to 2,151 EUR/day, so the
data do not support a precise positive horizon-value claim. The attribution
control assigns EUR 71,721 of the observed difference to the changed lead-D
anchor and EUR 11,115 to pure lookahead within the D4 anchor.

The observed incremental granularity value is EUR -1,727,401, or EUR
-16,451/day. Its seven-day block-bootstrap interval is -24,136 to -10,079
EUR/day; the 3- and 14-day sensitivities have the same sign. QH-D4/30 requires
501.4 MWh of emergency import versus 5.5 MWh for H-D4/30, although both meet
all weekly quotas and have zero hydrogen shortfall. The result is therefore
not evidence that QH prices lack value in general. It shows that this frozen
mean-shape/scenario/bidding combination did not convert finer information into
value for this plant and period; undercoverage and the conservative
scenario-independent five-day bid plan are material explanatory limitations.

Reducing 30 paths to 10 cuts policy runtime by 57% for `H-D`, 83% for `H-D4`,
and 94% for `QH-D4`, but reduces realised profit by EUR 0.444m, EUR 0.214m,
and EUR 1.612m, respectively. Ten scenarios are therefore a usable explicit
compute sensitivity, not an economically equivalent default for this test.
## Performance addendum (2026-07-30)

The canonical runner now defaults to `optimized_equivalent`: scenario and
actual maps are prepared before the rolling loop, future-path DataFrames are
lazy, and safe warm starts require exact structural/source identity. Forecast,
scenario, quota, physical, bid, settlement and risk semantics are unchanged.

The three-origin diagnostic passed 96/96 realised-ledger parity checks. The
one-origin objective fixture passed 40/40 checks, including eight exact solver
objective comparisons. Median bidding speedups were 1.01x (H-D-30), 1.12x
(H-D4-30), 1.22x (QH-D4-10) and 0.97x (QH-D4-30). The requested QH targets were
not reached, so the accepted conclusion is parity-preserving infrastructure
with solver-dominated QH30 performance, not a claimed 2x acceleration.
