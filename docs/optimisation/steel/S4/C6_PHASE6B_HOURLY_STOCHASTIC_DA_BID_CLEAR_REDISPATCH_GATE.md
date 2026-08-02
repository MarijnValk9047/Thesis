# C6 Phase 6B Hourly Stochastic DA Bid--Clear--Redispatch Gate

## Decision

`hourly_stochastic_DA_bid_clear_redispatch_validated_on_engineering_fixtures`

Phase 6B validates an hourly price--quantity day-ahead market chain around the
frozen Phase-5K C0/C1 steel boundary. The accepted run is:

`steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730`

It is thesis-candidate implementation validation, not long-run economic
evaluation, forecast tuning evidence or authorization for QH, CVaR or mFRR.

## Scope and inputs

- Forecast model: frozen Strict LEAR
  `lear_lago_direct_dplus4_strict_no_future_1092`.
- Information set: D-1 08:00 Europe/Amsterdam; D--D+4 hourly point and nested
  weighted S10 paths from `20260729_strict_lear_dplus4_full_a03`.
- Policies: H-point, H-S10, price-insensitive and configuration-matched true
  perfect foresight.
- Configurations: C0 and C1 with identical frozen physical, quota, terminal,
  cost and settlement contracts.
- Bid grid ID: `steel_phase6b_hourly_da_bid_grid_v1`; SHA-256
  `9546d964836a9544d591b752246bb4c99eaec152f144b167d422157b978a3ca7`.
- Risk: risk-neutral expected cost; `cvar_gamma = 0`.
- Evidence: 27 April 2026 as a normal-day fixture and 27 April--3 May 2026 as
  a separate seven-day rolling fixture.

The scenario-undercoverage warning from forecasting remains active. The run
does not claim calibrated 90% risk coverage.

## Market formulation

For hour (t), price tier (b) and scenario (s), the model chooses one
scenario-independent incremental purchase volume:

\[
q_{t,b}\ge 0,\qquad
A_{t,b,s}=\mathbf 1[p_b\ge p_{t,s}],\qquad
Q^{clear}_{t,s}=\sum_b A_{t,b,s}q_{t,b}.
\]

Scenario-dependent physical schedules may adapt to the cleared scenario
quantity, but the bid curve is common to every scenario. The lexicographic
solve preserves production progress first, expected represented procurement
cost second, the frozen physical tie-break third, and a canonical minimum-
volume/highest-willingness-price representation last.

After submission, only the 24 D-hours are retained. Actual prices are loaded
through a separate interface and determine acceptance and settlement:

\[
accepted_{t,b}=\mathbf 1[p_b\ge p_t^{actual}],\qquad
C^{DA}=\sum_{t\in D}p_t^{actual}\sum_b accepted_{t,b}q_{t,b}.
\]

The physical redispatch must use the cleared import exactly. No imbalance
market, emergency import, export or energy-destruction variable is added, and
DA settlement is not counted again in the redispatch objective.

## Rolling state and terminal policy

Only D is executed and settled; planned D+1--D+4 decisions are discarded. The
next origin receives the exact realised state:

- coke, sinter, hot-iron, cold-slab and, for C1, DRI inventory;
- cumulative final-product progress;
- cumulative BOF/EAF/HSM/DSP/imported-slab route progress;
- executed hours, episode identity and final executed timestamp.

The route-progress state is essential. Without it, a truncated replan would
restart fixed-reference route bands and could make a previously feasible tail
infeasible. Phase 6B therefore reuses the deterministic campaign-progress
transformation that subtracts executed route quantities from the remaining
deadline bands.

The week-end inventory target is selected once from an unbanded, flat
EUR 80/MWh price-insensitive trajectory before responsive strategies are
evaluated. A common configuration-specific 1% band is then imposed on all four
policies. When the fixed 168-hour endpoint enters the look-ahead, the physical
horizon is truncated to 120, 96, 72, 48 and 24 hours. The terminal band replaces
the builder's cyclic horizon equalities, while exact campaign production and
route-progress accounting remain active.

## Engineering results

Realised represented cost is a cost measure: lower is better. These amounts
describe fixtures and must not be interpreted as annual performance estimates.

| Fixture | Configuration | H-point (EUR) | H-S10 (EUR) | Price-insensitive (EUR) | True PF (EUR) |
|---|---|---:|---:|---:|---:|
| Normal day | C0 | 5,469,986.59 | 5,453,799.63 | 5,596,250.43 | 5,358,807.92 |
| Normal day | C1 | 9,176,949.45 | 9,284,682.94 | 9,989,998.60 | 8,956,515.90 |
| Rolling week | C0 | 37,751,479.80 | 37,364,101.60 | 38,743,497.70 | 37,295,144.22 |
| Rolling week | C1 | 60,820,199.52 | 60,719,582.57 | 62,995,527.30 | 60,548,733.53 |

On the week fixture, S10 costs EUR 387,378 less than H-point for C0 and EUR
100,617 less for C1. This is implementation evidence that the strategies can
produce distinct, feasible market responses; it is not a stable economic-value
estimate. The isolated one-day C1 ordering is reversed, reinforcing why the
fixture must not be used for substantive value claims.

## Validation evidence

- 16 main policy trajectories and two prior terminal-target selections.
- 256/256 contract and result checks pass.
- 128/128 main bidding/redispatch solves and 28/28 target-selection solves are
  optimal; no time-limit or relaxed headline case is included.
- Exact a02--a03 parity: maximum cost difference EUR 0 and production
  difference 0 t. A03 supersedes a02 only because all consolidated output keys
  now include `fixture_id`.
- 24,576 bid rows, 1,536 clearing rows, 1,536 redispatch rows, 64 state rows and
  7,488 compact scenario-dispatch audit rows have zero duplicate governed keys.
- No actual-, realised- or error field occurs in submitted bidding output.
- Maximum cleared-import/redispatch residual is `2.8612e-8 MWh`; export is zero.
- All 12 configuration-matched PF-dominance checks pass.
- Every scenario probability sum, scenario count, grid identity, complete state
  handoff and common terminal-band check passes.
- A03 wall time is 969.1 seconds. H-S10 bidding consumes 106.0 solver-seconds
  in C0 and 653.6 solver-seconds in C1 across the day and week fixtures.
- H-S10 bidding models range from 9,354--46,690 variables in C0 and
  12,234--61,090 in C1 as the endpoint-truncated horizon changes.

## Phase 6A bridge and limitations

Phase 6A remains the historical quantity-only bridge: its forecast-driven
quantity is treated as fully accepted, so it does not test bid-price rejection
or physical redispatch after clearing. Phase 6B uses the same steel boundary
but adds a price ladder, scenario-independent volumes, realised acceptance and
an exact redispatch. The two phases are methodologically linked but not
economically interchangeable.

The present evidence covers one normal day and one week. It establishes
information timing, bidding, clearing, settlement, physical recourse and state
carryover. It does not establish annual profitability, seasonal robustness,
the long-run value of scenarios or quarter-hour granularity. A longer hourly
evaluation is a separate future gate; QH follows only after hourly validation
is stable.

## Governed artifacts

- Run root:
  `data/03_Optimisation/runs/steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730/`
- Comparison bundle:
  `data/03_Optimisation/steel_hourly_da_bid_clear_redispatch/steel_phase6b_hourly_da_bid_clear_redispatch_a03_20260730/`
- Classification: `output_policy = diagnostics`,
  `run_class = diagnostic_validation`, `lineage_role = thesis-candidate
  implementation validation, not economic evaluation`.

Generated tables and solver diagnostics remain local and ignored. The runner,
shared module, frozen config, tests and this method record are canonical source.
